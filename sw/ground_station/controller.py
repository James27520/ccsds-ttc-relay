"""One worker owns each selected SDR. Receiver has no access to sender state."""
import hashlib
import json
from pathlib import Path
import queue
import threading
import time
import uuid

import numpy as np

from .transport import Console, discover_devices
from .relay import RelayConsole
from .protocol import generate_message_iq, decode_capture, MessageTracker, new_session_id

FS = 2_500_000
CAPTURE_SAMPLES = 32768


class StationController:
    def __init__(self, role, emit, log_dir=None, console_factory=Console, relay_factory=RelayConsole):
        if role not in ('sender', 'receiver'):
            raise ValueError('Invalid station role')
        self.role, self.emit, self.factory = role, emit, console_factory
        self.commands = queue.Queue(maxsize=20)
        self.console = None
        self.relay = None
        self.relay_factory = relay_factory
        self.urgent = queue.Queue()
        self.active = False
        self.configured = False
        self.settings = {}
        self.session = new_session_id()
        self.sequence = 0
        self.tracker = MessageTracker()
        self.remote = '/tmp/ground_station_' + uuid.uuid4().hex[:12]
        self.writer = None
        self.guard = None
        self.pending_guard = None
        self.capture_index = 0
        self.capture_owned = False
        self.closing = False
        self.interrupt = threading.Event()
        self.log_dir = Path(log_dir) if log_dir else Path.home()/'CCSDSGroundStation'/'sessions'/(
            time.strftime('%Y%m%d_%H%M%S')+'_'+role+'_'+self.session)
        self.log_dir.mkdir(parents=True, exist_ok=False)
        self.journal = (self.log_dir/'events.jsonl').open('x', encoding='utf-8')
        self.worker = threading.Thread(target=self._work, name='station-'+role, daemon=True)
        self.worker.start()

    def record(self, **event):
        self.journal.write(json.dumps(dict(time=time.time(), **event), ensure_ascii=False)+'\n')
        self.journal.flush()

    def event(self, kind, **data):
        event = dict(type=kind, **data)
        self.record(**event)
        self.emit(event)

    def status(self, state, message):
        self.event('status', state=state, message=message)

    def submit(self, action, **kwargs):
        if self.closing:
            return
        if action in ('stop', 'disconnect', 'close'):
            self.interrupt.set()
            self.urgent.put((action, kwargs))
            return
        try:
            self.commands.put_nowait((action, kwargs))
        except queue.Full:
            self.emit(dict(type='log', level='error', message='操作队列已满，请等待当前操作完成'))

    def _work(self):
        self.status('disconnected', '请选择本端SDR的DEBUG串口')
        self.event('log', level='info', message='会话日志：'+str(self.log_dir))
        try:
            while not self.closing:
                try:
                    try:
                        action, kwargs = self.urgent.get_nowait()
                        # Commands entered before Stop/Close must not restart RF.
                        while True:
                            try:
                                self.commands.get_nowait()
                            except queue.Empty:
                                break
                    except queue.Empty:
                        action, kwargs = self.commands.get(timeout=.25)
                except queue.Empty:
                    if self.active:
                        try:
                            if self.role == 'receiver':
                                self._capture()
                            elif time.monotonic()-self.last_lease > 10:
                                self._renew()
                        except Exception as exc:
                            self._failed(exc)
                    continue
                try:
                    if self.interrupt.is_set() and action not in ('stop', 'disconnect', 'close'):
                        continue
                    if action == 'discover':
                        self.event('devices', devices=discover_devices())
                    elif action == 'connect':
                        self._connect(**kwargs)
                    elif action == 'configure':
                        self._configure(**kwargs)
                    elif action == 'read_relay':
                        if not self.relay:
                            raise RuntimeError('请先连接发送端的LDSDR调试口')
                        state = self.relay.status()
                        values = self.relay.diagnostics(atten=int(state['txatt']), gain=int(state['rxgain']),
                                                        exact_frequency=False)
                        values['relay_mode'] = int(state['mode'])
                        self.event('relay_telemetry', values=values, received_at=time.time())
                    elif action == 'send':
                        self._send(**kwargs)
                    elif action == 'receive':
                        if self.role != 'receiver' or not self.configured:
                            raise RuntimeError('请先连接并应用接收配置')
                        self.active = True
                        self.status('receiving', '正在轮询真实I/Q快照；串口回传存在采样空档')
                    elif action == 'stop':
                        self._stop()
                        self.interrupt.clear()
                        self.status('stopped', '本端任务已停止；历史消息保留')
                    elif action in ('disconnect', 'close'):
                        self._disconnect()
                        self.interrupt.clear()
                        if action == 'close':
                            self.closing = True
                        else:
                            self.status('disconnected', '已断开设备')
                    else:
                        raise ValueError('Unknown action: '+action)
                except Exception as exc:
                    self._failed(exc)
                    if action == 'close':
                        self.closing = True
        finally:
            # Always release handles, even if cleanup could not be confirmed.
            for attr in ('console', 'relay'):
                handle = getattr(self, attr)
                if handle:
                    try:
                        handle.close()
                    except Exception as exc:
                        self.record(kind='close_error', device=attr, error=str(exc))
                    setattr(self, attr, None)
            try:
                self.event('closed')
            finally:
                self.journal.close()

    def _failed(self, exc):
        self.active = False
        self.configured = False
        text = str(exc)
        try:
            self._stop()
        except Exception as cleanup:
            text += '；清理未确认：'+str(cleanup)+'。请检查板卡，勿直接重新启发。'
        self.event('log', level='error', message=text)
        self.status('error', text)

    def _connect(self, port, relay_port=None):
        if self.console:
            raise RuntimeError('请先断开当前设备')
        self.status('connecting', '读取Linux / IIO身份…')
        if self.role == 'sender' and (not relay_port or relay_port == port):
            raise ValueError('发送端需要选择不同的发送板与LDSDR调试口')
        board = self.factory(port, self.record)
        try:
            board.require_idle()
            board.mute()
            # The same application can reconnect to its existing private directory.
            board.run('mkdir -p '+self.remote)
            if self.role == 'sender':
                self.relay = self.relay_factory(relay_port, self.record)
            self.console = board
        except Exception:
            board.close()
            raise
        self.event('identity', identity=board.info)
        self.status('ready', '身份已读取，TX已关闭；请应用本端配置')

    @staticmethod
    def _finite(value):
        value = float(value)
        if not np.isfinite(value):
            raise ValueError('参数必须为有限数值')
        return value

    def _configure(self, **values):
        if not self.console:
            raise RuntimeError('尚未连接设备')
        self._stop()
        self.configured = False
        c = self.console
        c.require_idle()
        c.mute()
        if self.role == 'sender':
            lo = self._finite(values.get('tx_lo_mhz', 900))
            atten = self._finite(values.get('tx_atten_db', 50))
            if lo != 900 or not 50 <= atten <= 89:
                raise ValueError('当前有线工作点限定TX LO=900 MHz、衰减50..89 dB')
            got = c.write(c.phy+'/out_altvoltage1_TX_LO_frequency', int(lo*1e6), 10)
            c.write(c.phy+'/out_voltage_sampling_frequency', FS)
            c.write(c.phy+'/out_voltage_rf_bandwidth', 3000000)
            c.write(c.phy+'/out_voltage0_rf_port_select', 'A')
            relay_settings = self.relay.prepare()
            self.settings = dict(tx_lo_mhz_requested=lo, tx_lo_hz_readback=int(got),
                                 tx_atten_db_requested=atten, sample_rate_hz=FS,
                                 tx_atten_db_readback=89, expected_rf_hz=int(got)+500000, **relay_settings)
        else:
            lo = self._finite(values.get('rx_lo_mhz', 1000.75))
            rf = self._finite(values.get('expected_rf_mhz', 1000.5))
            gain = self._finite(values.get('rx_gain_db', 30))
            if lo != 1000.75 or rf not in (1000.5, 1001.5) or not 0 <= gain <= 30:
                raise ValueError('接收工作点：RX LO=1000.75 MHz，预期RF=1000.5/1001.5 MHz，增益0..30 dB')
            c.write(c.phy+'/in_voltage_sampling_frequency', FS)
            c.write(c.phy+'/in_voltage_rf_bandwidth', 3000000)
            c.write(c.phy+'/in_voltage0_gain_control_mode', 'manual')
            gain_read = c.write(c.phy+'/in_voltage0_hardwaregain', gain)
            c.write(c.phy+'/in_voltage0_rf_port_select', 'A_BALANCED')
            got = c.write(c.phy+'/out_altvoltage0_RX_LO_frequency', int(lo*1e6), 10)
            # Verify the actual scan data layout, not just an IIO device name.
            for channel, index in [('voltage0', '0'), ('voltage1', '1')]:
                fmt = c.read(c.rx+'/scan_elements/in_'+channel+'_type')
                if fmt != 'le:S12/16>>0' or c.read(c.rx+'/scan_elements/in_'+channel+'_index') != index:
                    raise RuntimeError('接收I/Q格式不匹配')
            self.settings = dict(rx_lo_mhz_requested=lo, rx_lo_hz_readback=int(got),
                                 expected_rf_mhz=rf, rx_gain_db_requested=gain,
                                 rx_gain_db_readback=float(gain_read.split()[0]), sample_rate_hz=FS)
        self.configured = True
        self.event('settings', values=self.settings)
        self.status('ready', '配置及读回通过；本阶段为有线业务演示，使用本地转发设置')

    def _guard_script(self, lease):
        c = self.console
        # Lease survives loss of the host UI; PID start ticks avoid PID-reuse kills.
        return (f'while sleep 2; do\n'
                f'deadline=$(cat {lease} 2>/dev/null)\n'
                'test "$deadline" = 0 && exit 0\n'
                'now=$(date +%s)\n'
                'if test -z "$deadline" || test "$now" -ge "$deadline"; then\n'
                f'echo 1 > {c.phy}/out_altvoltage1_TX_LO_powerdown\n'
                f'echo -89 > {c.phy}/out_voltage0_hardwaregain\n'
                f'echo -89 > {c.phy}/out_voltage1_hardwaregain\n'
                f'for f in {c.tx}/out_altvoltage*_scale; do echo 0 > "$f"; done\n'
                f'if test "$(awk \'{{print $22}}\' /proc/{self.writer[0]}/stat 2>/dev/null)" = {self.writer[1]}; then kill -INT {self.writer[0]}; fi\n'
                f'echo expired > {self.remote}/guard_state\nexit 0\nfi\ndone\n').encode('ascii')

    def _set_lease(self, lease):
        self.console.run(f'echo $(( $(date +%s) + 45 )) > {lease}.next && mv {lease}.next {lease}')
        self.last_lease = time.monotonic()

    def _renew(self):
        c = self.console
        if not self.writer:
            raise RuntimeError('未持有发送进程')
        pid, ticks = self.writer
        c.run(f'test "$(awk \'{{print $22}}\' /proc/{pid}/stat)" = {ticks} && '
              f'test "$(cat {c.tx}/buffer/enable)" = 1')
        if not self.guard:
            raise RuntimeError('发送保护进程不存在')
        guard_pid, guard_ticks, lease = self.guard
        c.run(f'test "$(awk \'{{print $22}}\' /proc/{guard_pid}/stat)" = {guard_ticks}')
        if c.read(c.phy+'/out_altvoltage1_TX_LO_powerdown') != '0':
            raise RuntimeError('发射已关闭，可能已触发保护')
        if self.relay:
            state = self.relay.status()
            if state['mode'] != '1':
                raise RuntimeError('转发板不再处于业务模式')
            self.settings.update(self.relay.diagnostics(atten=50))
        self._set_lease(lease)

    def _send(self, text):
        if self.role != 'sender' or not self.configured:
            raise RuntimeError('请先连接并应用发送配置')
        if self.sequence > 65535:
            self.session, self.sequence = new_session_id(), 0
        # Validation happens before touching the currently running transmitter.
        iq, manifest = generate_message_iq(text, self.session, self.sequence)
        self._stop()
        c = self.console
        self.status('busy', '正在上传新消息波形并校验；尚未发射')
        path = self.remote+'/'+uuid.uuid4().hex[:12]+'.iq'
        def progress(fraction):
            if self.interrupt.is_set():
                raise RuntimeError('上传已取消，发送保持关闭')
        c.upload(path, iq.tobytes(), progress)
        n = len(iq)
        # The shell records ownership before replying; a lost UART reply can be
        # recovered in _stop via this per-application identity file.
        c.run(f'iio_writedev -u local: -b {n} -c cf-ad9361-dds-core-lpc voltage0 voltage1 '
              f'< {path} > {self.remote}/writer.log 2>&1 & p=$!; '
              f't=$(awk \'{{print $22}}\' /proc/$p/stat); '
              f'if test -n "$t"; then echo "$p $t" > {self.remote}/owned || '
              '{ kill -INT "$p"; exit 1; }; '
              'else kill -INT "$p" 2>/dev/null; exit 1; fi')
        identity = c.read(self.remote+'/owned').split()
        if len(identity) != 2 or not all(x.isdigit() for x in identity):
            raise RuntimeError('发送进程身份读取失败')
        pid, ticks = int(identity[0]), identity[1]
        self.writer = (pid, ticks)
        c.run(f'sleep 1; kill -0 {pid}; test "$(cat {c.tx}/buffer/enable)" = 1 && '
              f'test "$(cat {c.tx}/scan_elements/out_voltage0_en)" = 1 && '
              f'test "$(cat {c.tx}/scan_elements/out_voltage1_en)" = 1 && '
              f'test "$(cat {c.tx}/scan_elements/out_voltage2_en)" = 0 && '
              f'test "$(cat {c.tx}/scan_elements/out_voltage3_en)" = 0')
        guard_path = self.remote+'/'+uuid.uuid4().hex[:12]+'.guard'
        lease = guard_path+'.lease'
        self.pending_guard = (lease, guard_path+'.owned')
        self._set_lease(lease)
        c.upload(guard_path, self._guard_script(lease))
        guard_reply = c.run(f'sh {guard_path} </dev/null > {guard_path}.log 2>&1 & p=$!; '
                            't=$(awk \'{print $22}\' /proc/$p/stat); '
                            f'if test -n "$t" && echo "$p $t" > {guard_path}.owned; '
                            'then echo "$p $t"; else kill -TERM "$p"; exit 1; fi')
        gp = guard_reply.split()
        if len(gp) != 2 or not all(x.isdigit() for x in gp):
            raise RuntimeError('保护进程身份不完整')
        self.guard = (int(gp[0]), gp[1], lease)
        c.run(f'test "$(awk \'{{print $22}}\' /proc/{gp[0]}/stat)" = {gp[1]}')
        if self.interrupt.is_set():
            raise RuntimeError('发送已取消')
        c.write(c.phy+'/out_voltage0_hardwaregain', -self.settings['tx_atten_db_requested'])
        c.write(c.phy+'/out_altvoltage1_TX_LO_powerdown', 0)
        self.settings.update(self.relay.start())
        self.settings['tx_atten_db_readback'] = -float(c.read(c.phy+'/out_voltage0_hardwaregain').split()[0])
        self.event('settings', values=self.settings)
        self.active = True
        message_id = f'{self.session}:{self.sequence:04x}'
        self.sequence += 1
        (self.log_dir/(message_id.replace(':', '_')+'.tx.json')).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        self.event('tx', message_id=message_id, text=text, payload_bytes=len(text.encode('utf-8')))
        self.status('transmitting', '循环发射当前消息；板端45秒租约保护已启用')

    def _capture(self):
        if self.interrupt.is_set():
            return
        c = self.console
        begin = time.monotonic()
        self.capture_index += 1
        stem = f'rx_{self.capture_index:06d}'
        path = self.remote+'/capture.bin'
        self.event('log', level='info', message=f'快照 {self.capture_index}：采集及串口回传中…')
        if c.read(c.phy+'/out_altvoltage1_TX_LO_powerdown') != '1':
            raise RuntimeError('接收板TX未保持关闭')
        self.capture_owned = True
        c.run(f'iio_readdev -u local: -T 3000 -b {CAPTURE_SAMPLES} -s {CAPTURE_SAMPLES} '
              f'cf-ad9361-lpc voltage0 voltage1 > {path}', timeout=12)
        raw = c.download(path, CAPTURE_SAMPLES*4)
        if c.read(c.rx+'/buffer/enable') != '0':
            raise RuntimeError('采集buffer未释放')
        self.capture_owned = False
        self._publish_capture(raw, stem, begin)

    def _publish_capture(self, raw, stem, begin):
        """Decode only local IQ; shared with the source-only V2 station."""
        if self.interrupt.is_set():
            return
        (self.log_dir/(stem+'.bin')).write_bytes(raw)
        report = decode_capture(raw, expected_offset_hz=self.settings['expected_rf_mhz']*1e6-
                                self.settings['rx_lo_hz_readback'])
        if self.interrupt.is_set():
            return
        if report['clip_components'] or report['rms_codes'] > 1000:
            raise RuntimeError('采样出现削顶或超过本次已验证输入范围，接收已停止')
        messages = []
        for message in report['messages']:
            kind = self.tracker.observe(message)
            if kind == 'conflict':
                self.event('log', level='error', message='同一消息ID出现不同内容，已拒绝：'+message['message_id'])
                continue
            messages.append(dict(message, duplicate=kind == 'duplicate'))
        (self.log_dir/(stem+'.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        iq = np.frombuffer(raw, dtype='<i2').reshape(-1, 2)
        z = iq[:4096, 0].astype(float)+1j*iq[:4096, 1]
        win = np.hanning(len(z))
        spectrum = abs(np.fft.fftshift(np.fft.fft((z-z.mean())*win)))/sum(win)/2048
        # Max-pool bins preserves narrow peaks at modest Canvas resolution.
        frequencies = (np.fft.fftshift(np.fft.fftfreq(len(z), 1/FS))+
                       self.settings['rx_lo_hz_readback'])/1e6
        points = dict(freq_mhz=frequencies.reshape(-1, 8).mean(axis=1).tolist(),
                      dbfs=(20*np.log10(np.maximum(spectrum, 1e-8))).reshape(-1, 8).max(axis=1).tolist())
        carrier = self.settings['rx_lo_hz_readback']+report['carrier_offset_hz'] if messages else None
        if self.interrupt.is_set():
            return
        self.event('rx', messages=messages, valid_frames=len(messages),
                   crc_rejected=report['crc_rejected_frames'], rms_codes=report['rms_codes'],
                   carrier_hz=carrier, spectrum=points, capture_seconds=time.monotonic()-begin,
                   received_at=time.time(), capture_file=str(self.log_dir/(stem+'.bin')))

    def _stop(self):
        self.active = False
        c = self.console
        errors = []
        if self.relay:
            try:
                self.settings.update(self.relay.mute())
            except Exception as exc:
                errors.append(str(exc))
        if c:
            try:
                c.mute()
                if self.role == 'sender':
                    self.settings['tx_atten_db_readback'] = 89
            except Exception as exc:
                errors.append(str(exc))
            if self.role == 'receiver' and self.capture_owned:
                try:
                    c.write(c.rx+'/buffer/enable', 0)
                    self.capture_owned = False
                except Exception as exc:
                    errors.append(str(exc))
            if self.role == 'sender':
                try:
                    identity = self.writer
                    if not identity:
                        owned = c.run(f'if test -f {self.remote}/owned; then cat {self.remote}/owned; fi').split()
                        identity = tuple(owned) if len(owned) == 2 and all(x.isdigit() for x in owned) else None
                    if identity:
                        pid, ticks = identity
                        c.run(f'if test "$(awk \'{{print $22}}\' /proc/{pid}/stat 2>/dev/null)" = {ticks}; '
                              f'then kill -INT {pid}; fi; sleep 1')
                    if c.read(c.tx+'/buffer/enable') != '0':
                        raise RuntimeError('发送DMA停止未确认')
                    self.writer = None
                    c.run(f': > {self.remote}/owned')
                except Exception as exc:
                    errors.append(str(exc))
            # A failed mute leaves the guard armed so it can retry independently.
            if (self.guard or self.pending_guard) and not errors:
                try:
                    lease = self.guard[2] if self.guard else self.pending_guard[0]
                    c.run(f'echo 0 > {lease}')
                    identity = self.guard[:2] if self.guard else None
                    if not identity and self.pending_guard:
                        path = self.pending_guard[1]
                        owned = c.run(f'if test -f {path}; then cat {path}; fi').split()
                        if len(owned) == 2 and all(x.isdigit() for x in owned):
                            identity = tuple(owned)
                    if identity:
                        pid, ticks = identity
                        c.run(f'if test "$(awk \'{{print $22}}\' /proc/{pid}/stat 2>/dev/null)" = {ticks}; '
                              f'then kill -TERM {pid}; fi')
                    self.guard = None  # Old lease is never reused by the next send.
                    self.pending_guard = None
                except Exception as exc:
                    errors.append(str(exc))
        if self.settings:
            self.event('settings', values=self.settings)
        if errors:
            raise RuntimeError('; '.join(errors))

    def _disconnect(self):
        self._stop()
        if self.console:
            self.console.close()
            self.console = None
        if self.relay:
            self.relay.close()
            self.relay = None
        self.configured = False
