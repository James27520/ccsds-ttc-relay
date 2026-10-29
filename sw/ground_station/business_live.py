"""V2 business endpoints: local SDR only, externally commissioned relay.

Receiver never reads the sender's messages or any other station's files.
The sender reuses the finite board-side TX guard, without renewing it.
"""
import hashlib
import json
import queue
import re
import shlex
import time
import uuid

from .controller import StationController, FS, CAPTURE_SAMPLES
from .device_lease import PortLease
from .protocol import generate_message_iq, new_session_id
from .rf_session import SessionRxConsole, _usb_identity, _USB_KEYS
from .rf_live import Cancelled
from .tc_hardware import CommandSource
from .transport import Console
from .ui_v2_model import business_frequency_plan


def _verify_runtime_binding(c):
    """Check current boot, USB and IIO map between full identity probes."""
    if c._closed:
        raise RuntimeError('本地设备会话已关闭')
    try:
        before = _usb_identity(c.info['port'])
        if any(before[k] != c._fingerprint[k] for k in _USB_KEYS):
            raise RuntimeError('本地设备USB身份变化')
        values = c.run(f'cat /proc/sys/kernel/random/boot_id {c.phy}/name {c.tx}/name {c.rx}/name').splitlines()
        if values != [c._fingerprint['linux_boot_id'],'ad9361-phy',
                       'cf-ad9361-dds-core-lpc','cf-ad9361-lpc'] or _usb_identity(c.info['port']) != before:
            raise RuntimeError('本地设备重启或IIO映射变化')
    except BaseException:
        c.close()
        raise


class BusinessSource(CommandSource):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.info.update(identity_scope='current process, Linux boot and USB; fixed wired business TX',
                         physical_role='user-selected TX1A to LDSDR RX1')

    def write(self, path, value, tolerance=0):
        if not self.owned or self._closed:
            raise RuntimeError('业务发送会话未取得控制')
        allowed = {
            'out_altvoltage1_TX_LO_frequency': {'900000000', '901000000'},
            'out_altvoltage1_TX_LO_powerdown': {'1'},
            'out_voltage_sampling_frequency': {'2500000'},
            'out_voltage_rf_bandwidth': {'3000000'},
            'out_voltage0_rf_port_select': {'A'},
            'out_voltage0_hardwaregain': {str(-x) for x in range(50, 90)},
            'out_voltage1_hardwaregain': {'-89'},
        }
        if not path.startswith(self.phy+'/') or str(value) not in allowed.get(path[len(self.phy)+1:], set()):
            raise ValueError('超出已验证业务发送配置')
        # Full identity remains checked at prepare/start/stop. Each grouped
        # sysfs write additionally checks current boot/USB/map without iio_info.
        _verify_runtime_binding(self)
        return Console.write(self, path, value, tolerance)

    def apply_frequency(self, lo_hz, check_cancel):
        """Explicit local tuning while muted; never starts a DMA or TX guard."""
        if type(lo_hz) is not int or lo_hz not in (900000000, 901000000):
            raise ValueError('业务本振仅支持900/901 MHz')
        self.verify_binding()
        self.require_idle()
        if self.read(self.phy+'/out_altvoltage1_TX_LO_powerdown') != '1':
            raise RuntimeError('应用业务频率前本地TX必须关闭')
        check_cancel()
        self.owned = True
        self.mute()
        check_cancel()
        got = int(self.write(self.phy+'/out_altvoltage1_TX_LO_frequency', lo_hz, 10))
        if self.read(self.phy+'/out_altvoltage1_TX_LO_powerdown') != '1':
            raise RuntimeError('本地静音状态未保持')
        return got

    def prepare_message(self, text, session, sequence, attenuation_db, check_cancel, *, tx_rf_mhz=900.5):
        plan = business_frequency_plan('sender', tx_rf_mhz)
        if type(attenuation_db) is not int or not 50 <= attenuation_db <= 89:
            raise ValueError('发射衰减须为50–89 dB整数')
        iq, manifest = generate_message_iq(text, session, sequence)
        raw = iq.tobytes()
        manifest = dict(manifest, sha256=hashlib.sha256(raw).hexdigest(),
                        business_center_hz=plan['center_hz'], business_lo_hz=plan['lo_hz'])
        self.remote = '/tmp/business_tx_'+uuid.uuid4().hex[:12]
        self._prepare_waveform(raw, manifest, lo_hz=plan['lo_hz'],
                               attenuation_db=attenuation_db, block_samples=len(iq),
                               check_cancel=check_cancel)
        return manifest


class BusinessReceiver(SessionRxConsole):
    def verify_stream_binding(self):
        """Full identity is bound at connect/configure; recheck boot/USB/mapping.

        Avoid running the verbose iio_info tool four times per small snapshot.
        This is current-boot continuity, not permanent device authentication.
        """
        _verify_runtime_binding(self)

    def write(self, path, value, tolerance=0):
        if not self._writable or self._closed:
            raise RuntimeError('业务接收会话未取得控制')
        allowed = {
            self.phy+'/in_voltage_sampling_frequency': {'2500000'},
            self.phy+'/in_voltage_rf_bandwidth': {'3000000'},
            self.phy+'/in_voltage0_gain_control_mode': {'manual'},
            self.phy+'/in_voltage0_hardwaregain': {'30'},
            self.phy+'/in_voltage0_rf_port_select': {'A_BALANCED'},
            self.phy+'/in_voltage1_gain_control_mode': {'manual'},
            self.phy+'/in_voltage1_hardwaregain': {'30'},
            self.phy+'/in_voltage1_rf_port_select': {'A_BALANCED'},
            self.phy+'/out_altvoltage0_RX_LO_frequency': {'1000750000', '1001750000'},
            self.phy+'/out_altvoltage1_TX_LO_powerdown': {'1'},
            self.phy+'/out_voltage0_hardwaregain': {'-89'},
            self.phy+'/out_voltage1_hardwaregain': {'-89'},
        }
        if str(value) not in allowed.get(path, set()):
            raise ValueError('超出已验证业务接收配置')
        self.verify_binding()
        return Console.write(self, path, value, tolerance)


class BusinessController(StationController):
    """Reuse the established decoder and presentation events, never RelayConsole."""
    def __init__(self, role, emit, log_dir=None, *, console_factory=None, lease_factory=PortLease,
                 direction='forward'):
        if direction not in ('forward', 'reverse'):
            raise ValueError('未知业务方向')
        self.direction = direction
        self.rx_channel = 2 if direction == 'reverse' else 1
        self.port_lease = None
        self.lease_factory = lease_factory
        self.source_taken = False
        self.capture_directory = None
        self.last_guard_check = 0
        super().__init__(role, emit, log_dir,
                         console_factory=console_factory or (BusinessSource if role=='sender' else BusinessReceiver))

    def event(self, kind, **data):
        super().event(kind, direction=self.direction, rx_channel=self.rx_channel, **data)

    def _verify_rx_channel(self):
        c = self.console
        if self.rx_channel == 2 and c.read(c.debug+'/adi,2rx-2tx-mode-enable') != '1':
            raise RuntimeError('回信接收需要已启用第二射频通道')
        first = (self.rx_channel-1)*2
        for index in (first, first+1):
            prefix = c.rx+f'/scan_elements/in_voltage{index}'
            if c.read(prefix+'_type') != 'le:S12/16>>0' or c.read(prefix+'_index') != str(index):
                raise RuntimeError('接收通道I/Q格式不匹配')

    def _check_cancel(self):
        if self.interrupt.is_set():
            raise Cancelled('本地操作已取消')

    def _connect(self, port):
        if self.console is not None or self.port_lease:
            raise RuntimeError('请先断开当前设备')
        self.status('connecting', '正在核验本地板卡')
        self.port_lease = self.lease_factory(port)
        self.console = self.factory(port, self.record)
        c = self.console
        c.verify_binding()
        c.require_idle()
        if c.read(c.phy+'/out_altvoltage1_TX_LO_powerdown') != '1':
            raise RuntimeError('本地板卡正在发射，拒绝接管')
        c.info['business_direction'] = self.direction
        c.info['physical_role'] = ('local TX1A to LDSDR RX2' if self.direction == 'reverse'
                                   else 'local TX1A to LDSDR RX1') if self.role == 'sender' else (
                                   'local RX2A from LDSDR TX2' if self.direction == 'reverse'
                                   else 'local RX1A from LDSDR TX1')
        self._check_cancel()
        self.source_taken = True
        if self.role == 'receiver':
            c._writable = True
        self.event('identity', identity=c.info)
        self.status('ready', '本地身份已确认，尚未应用业务配置')

    def _configure(self, **values):
        if not self.console or not self.source_taken:
            raise RuntimeError('请先连接本地板卡')
        if self.active:
            raise RuntimeError('请先停止当前收发再修改配置')
        c = self.console
        c.verify_binding(); c.require_idle(); self._check_cancel()
        self.configured = False
        if self.direction == 'reverse':
            key, default = ('tx_rf_mhz', 901.5) if self.role == 'sender' else ('expected_rf_mhz', 1000.5)
            if self._finite(values.get(key, default)) != default:
                raise ValueError('回信当前工作点：发送901.5 MHz、接收1000.5 MHz')
        if self.role == 'sender':
            attenuation = self._finite(values.get('tx_atten_db', 60 if self.direction == 'reverse' else 50))
            if attenuation != int(attenuation) or not 50 <= attenuation <= 89 or set(values)-{'tx_atten_db', 'tx_rf_mhz'}:
                raise ValueError('业务发送仅允许受限中心频率和50–89 dB整数衰减')
            plan = business_frequency_plan('sender', values.get('tx_rf_mhz', 901.5 if self.direction == 'reverse' else 900.5))
            got = c.apply_frequency(plan['lo_hz'], self._check_cancel)
            self.settings = dict(tx_lo_mhz_requested=plan['lo_hz']/1e6, tx_lo_hz_readback=int(got),
                                 tx_atten_db_requested=int(attenuation),
                                 tx_atten_db_readback=-float(c.read(c.phy+'/out_voltage0_hardwaregain').split()[0]),
                                 sample_rate_hz=FS, expected_rf_hz=plan['center_hz'])
        else:
            rf = self._finite(values.get('expected_rf_mhz', 1000.5))
            if set(values)-{'expected_rf_mhz'}:
                raise ValueError('本地接收目标只开放1000.5/1001.5 MHz')
            plan = business_frequency_plan('receiver', rf)
            self._verify_rx_channel()
            channel = self.rx_channel-1
            for name, value in [('in_voltage_sampling_frequency', FS), ('in_voltage_rf_bandwidth', 3000000),
                                (f'in_voltage{channel}_gain_control_mode', 'manual'), (f'in_voltage{channel}_hardwaregain', 30),
                                (f'in_voltage{channel}_rf_port_select', 'A_BALANCED')]:
                self._check_cancel(); c.write(c.phy+'/'+name, value)
            got = c.write(c.phy+'/out_altvoltage0_RX_LO_frequency', plan['lo_hz'], 10)
            self._verify_rx_channel()
            self.settings = dict(rx_lo_mhz_requested=plan['lo_hz']/1e6,rx_lo_hz_readback=int(got),
                                 expected_rf_mhz=rf,rx_gain_db_requested=30,rx_gain_db_readback=30,sample_rate_hz=FS)
        self._check_cancel()
        self.configured = True
        self.settings.update(direction=self.direction, rx_channel=self.rx_channel)
        self.settings['configured'] = True
        self.event('settings', values=dict(self.settings))
        self.status('ready', '本地配置就绪；远端业务链由实际接收确认')

    def _send(self, text):
        if self.role != 'sender' or not self.configured:
            raise RuntimeError('请先连接并配置本地发送板')
        # Validate text without stopping an existing valid transmission.
        from .protocol import encode_message
        encode_message(text, self.session, min(self.sequence, 65535))
        self._stop()
        self._check_cancel()
        if self.sequence > 65535:
            self.session, self.sequence = new_session_id(), 0
        sequence = self.sequence
        self.sequence += 1  # Never reuse an ID after an uncertain attempt.
        message_id = f'{self.session}:{sequence:04x}'
        self.status('busy', '正在准备本次文本波形，尚未发射')
        manifest = self.console.prepare_message(text, self.session, sequence,
                                                self.settings['tx_atten_db_requested'], self._check_cancel,
                                                tx_rf_mhz=self.settings['expected_rf_hz']/1e6)
        (self.log_dir/(message_id.replace(':','_')+'.tx.json')).write_text(
            json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        self._check_cancel()
        self.console.start()
        self._check_cancel()
        self.settings.update(tx_lo_hz_readback=int(self.console.read(self.console.phy+'/out_altvoltage1_TX_LO_frequency')),
                             tx_atten_db_readback=-float(self.console.read(self.console.phy+'/out_voltage0_hardwaregain').split()[0]))
        if abs(self.settings['tx_lo_hz_readback']-(self.settings['expected_rf_hz']-500000)) > 10:
            raise RuntimeError('发送本地本振回读与已应用计划不符')
        self._check_cancel()
        self.active = True; self.last_guard_check = time.monotonic()
        self.event('settings', values=dict(self.settings))
        self.event('tx', message_id=message_id,text=text,payload_bytes=len(text.encode('utf-8')))
        self.status('transmitting', '正在发送当前文本，板端最多30秒自动停发')

    def _poll_sender(self):
        if time.monotonic()-self.last_guard_check < 1:
            return
        self.last_guard_check = time.monotonic()
        self.console.verify_binding()
        state = self.console.read(self.console.remote+'/guard_state')
        if state == 'stopped':
            self._stop()
            self.status('stopped', '本次限时发送结束；可再次发送新文本')
        elif state != 'enabled' or self.console.read(self.console.phy+'/out_altvoltage1_TX_LO_powerdown') != '0':
            raise RuntimeError('发送保护或本振状态不符')
        else:
            guard = self.console.read(self.console.remote+'/guard_owned').split()
            if len(guard)!=2 or not all(re.fullmatch(r'[0-9]+',x) for x in guard):
                raise RuntimeError('发送保护进程身份不完整')
            remaining = self.console.run(f'echo $(( $(cat {self.console.remote}/deadline) - $(cut -d. -f1 /proc/uptime) ))')
            if not re.fullmatch(r'-?[0-9]+',remaining.strip()):
                raise RuntimeError('发送保护截止时间无法确认')
            if int(remaining)<=0:
                self._stop()
                self.status('stopped','本次限时发送结束；可再次发送新文本')
                return
            self.console.run(f'test "$(awk \'{{print $22}}\' /proc/{guard[0]}/stat)" = {guard[1]}')

    def _finish_capture(self):
        if not self.capture_directory:
            return
        c = self.console; c.verify_stream_binding()
        owned = c.read(self.capture_directory+'/owned').split()
        if len(owned)!=2 or not all(re.fullmatch(r'[0-9]+',s) for s in owned):
            raise RuntimeError('本次接收进程身份不完整')
        pid,ticks = owned
        c.run(f'if test "$(awk \'{{print $22}}\' /proc/{pid}/stat 2>/dev/null)" = {ticks}; '
              f'then kill -INT {pid}; fi')
        end=time.monotonic()+3
        while c.read(c.rx+'/buffer/enable')!='0':
            if time.monotonic()>=end:raise RuntimeError('本次接收DMA未释放')
            time.sleep(.03)
        self.capture_directory=None

    def _capture(self):
        self._check_cancel()
        c=self.console; c.verify_stream_binding(); c.require_idle()
        if c.read(c.phy+'/out_altvoltage1_TX_LO_powerdown')!='1':
            raise RuntimeError('接收板TX未关闭')
        if self.rx_channel == 2:
            self._verify_rx_channel()
        begin=time.monotonic();self.capture_index+=1
        stem=f'rx_{self.capture_index:06d}'
        directory='/tmp/business_rx_'+uuid.uuid4().hex[:12]
        c.run('mkdir '+directory)
        # Wrapper records its own PID/ticks before exec, even for a short capture.
        script=(f'echo "$$ $(awk \'{{print $22}}\' /proc/$$/stat)" > {directory}/owned || exit 1; '
                f'exec iio_readdev -u local: -T 1500 -b {CAPTURE_SAMPLES} -s {CAPTURE_SAMPLES} '
                f'cf-ad9361-lpc voltage{(self.rx_channel-1)*2} voltage{(self.rx_channel-1)*2+1}')
        self.capture_directory=directory
        try:
            result=c.run(f'sh -c {shlex.quote(script)} > {directory}/capture.bin 2> {directory}/err; '
                         f'echo $?; cat {directory}/err',timeout=5)
            if result.strip()!='0':raise RuntimeError('接收采样失败：'+result[-180:])
            self._finish_capture();self._check_cancel()
            c.verify_stream_binding()
            raw=c.download(directory+'/capture.bin',CAPTURE_SAMPLES*4)
            self._check_cancel();c.verify_stream_binding()
            if self.rx_channel == 2:
                self._verify_rx_channel()
                if c.read(c.phy+'/out_altvoltage1_TX_LO_powerdown') != '1':
                    raise RuntimeError('回信采集期间本地TX状态变化')
            self._publish_capture(raw,stem,begin)
            # Only the current private snapshot files; preserve files on failure.
            c.run(f'rm -f {directory}/capture.bin {directory}/owned {directory}/err; rmdir {directory}')
        finally:
            self._finish_capture()

    def _stop(self):
        self.active=False
        if self.console and self.source_taken:
            if self.role=='sender':
                self.console.stop()
            else:
                self._finish_capture()
                self.console.verify_binding()
                self.console.mute()
            if self.settings and self.role=='sender':
                self.settings['tx_atten_db_readback']=89
                self.event('settings',values=dict(self.settings))

    def _disconnect(self):
        errors=[]
        try:self._stop()
        except Exception as exc:errors.append(str(exc))
        try:
            if self.console:self.console.close()
        except Exception as exc:errors.append(str(exc))
        finally:
            self.console=None;self.source_taken=False;self.configured=False
            self.capture_directory=None
            if self.port_lease:self.port_lease.close();self.port_lease=None
        if errors:raise RuntimeError('清理未完全确认：'+'；'.join(errors))

    def _failed(self, exc):
        message=str(exc)
        try:self._disconnect()
        except Exception as cleanup:message+='；'+str(cleanup)
        self.event('status',state='error',message=message,
                   category='cancelled' if isinstance(exc,Cancelled) else 'hardware')

    def _work(self):
        try:
            self.status('disconnected','请选择本地板卡')
            while not self.closing:
                try:
                    action,kwargs=self.urgent.get_nowait()
                    while not self.commands.empty():
                        try:self.commands.get_nowait()
                        except queue.Empty:break
                except queue.Empty:
                    try:action,kwargs=self.commands.get(timeout=.15)
                    except queue.Empty:
                        if self.active:
                            try:
                                self._capture() if self.role=='receiver' else self._poll_sender()
                            except Exception as exc:self._failed(exc)
                        continue
                try:
                    if action in ('disconnect','close'):
                        self._disconnect()
                        if action=='close':self.closing=True
                        else:self.status('disconnected','本地收发已停止，设备已释放')
                    elif action=='stop':
                        self._stop()
                        self.status('stopped' if self.console else 'disconnected',
                                    '本地收发已停止；保留已收消息')
                    else:
                        self._check_cancel()
                        if action=='connect':self._connect(**kwargs)
                        elif action=='configure':self._configure(**kwargs)
                        elif action=='send':self._send(**kwargs)
                        elif action=='receive':
                            if self.role!='receiver' or not self.configured:raise RuntimeError('接收配置未就绪')
                            self.active=True;self.status('receiving','正在采集本地板卡，快照之间存在空档')
                        else:raise ValueError('未知业务操作')
                except Exception as exc:
                    self._failed(exc)
                    if action=='close':self.closing=True
                finally:
                    if action in ('stop','disconnect','close') and self.urgent.empty():self.interrupt.clear()
        finally:
            self.closing=True
            try:self._disconnect()
            except Exception as exc:self.emit(dict(type='status',state='error',message=str(exc)))
            try:self.record(type='closed')
            except Exception:pass
            finally:
                try:self.journal.close()
                finally:self.emit(dict(type='closed'))
