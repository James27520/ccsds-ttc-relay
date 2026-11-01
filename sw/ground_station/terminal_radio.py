"""One current-boot radio owner for business duplex and finite TC transactions.

RX has its own board process and never shares a UART reader with TX. Only the
owner's verified RX is allowed to remain enabled while preparing a business TX.
All TC retunes still require idle DMA. Nothing here opens a satellite-side port.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import time
import uuid

from .business_live import BusinessSource, _verify_runtime_binding
from .tc_live import AutonomousRadio
from .transport import Console
from .rf_profiles import BUSINESS_TX_LO_HZ, BUSINESS_RX_LO_HZ, business_lo_allowed
from .ui_v2_model import business_frequency_plan
from .rf_session import _usb_identity, _USB_KEYS
from .receive_snapshot import snapshot_script


class ReceiveUnavailable(RuntimeError):
    """Owned RX stopped; the same bound board may rebuild RX, never old TX."""


class TerminalRadio(AutonomousRadio):
    tx_channel = 1

    def verify_binding(self):
        # Constructor performs the full model/IIO identification. Within that
        # connection, verify USB, Linux boot and device mapping on every use.
        # A reboot/reconnect invalidates the session; no cached RF state is used.
        _verify_runtime_binding(self)
        return True

    def mute(self):
        if not self.owned or self._closed:
            raise RuntimeError('发送会话未取得控制')
        self.verify_binding()
        # Attempt every shutdown write, even if one fails. Read back the LO,
        # both attenuators and all DDS scales in the same bounded transaction.
        script = (f'p={self.phy}; t={self.tx}; bad=0; '
                  'echo 1 > $p/out_altvoltage1_TX_LO_powerdown || bad=1; '
                  'for n in 0 1; do echo -89 > $p/out_voltage${n}_hardwaregain || bad=1; done; '
                  'for f in $t/out_altvoltage*_scale; do echo 0 > "$f" || bad=1; done; '
                  'cat $p/out_altvoltage1_TX_LO_powerdown $p/out_voltage0_hardwaregain '
                  '$p/out_voltage1_hardwaregain $t/out_altvoltage*_scale; test "$bad" = 0')
        values = self.run(script).splitlines()
        # The supported dual-TX DDS core has eight scale attributes. A partial
        # sysfs set must not count as a confirmed shutdown.
        if len(values) != 11 or values[0] != '1':
            raise RuntimeError('停发读回不完整')
        for i, value in enumerate(values[1:]):
            expected = -89 if i < 2 else 0
            if not re.fullmatch(r'[+-]?[0-9]+(?:\.[0-9]+)?(?: dB)?' if i < 2 else
                                r'[+-]?[0-9]+(?:\.[0-9]+)?', value):
                raise RuntimeError('停发电平读回无效')
            number = float(value.split()[0])
            if not math.isfinite(number) or number != expected:
                raise RuntimeError('停发电平未确认')

    def __init__(self, *args, **kwargs):
        self.stream = None
        self.stream_owner = None
        self.stream_owners = {}
        self.rx_channel = None
        self.business_mode = True
        super().__init__(*args, **kwargs)
        self.info.update(identity_scope='current boot and USB; one local terminal owner',
                         physical_role='local TX1A business / TX2A TC / selected business RX')

    def write(self, path, value, tolerance=0):
        if not self.business_mode:
            return super().write(path, value, tolerance)
        allowed = {
            'out_altvoltage1_TX_LO_frequency': {str(value)} if business_lo_allowed('sender', value) else set(),
            'out_altvoltage0_RX_LO_frequency': {str(value)} if business_lo_allowed('receiver', value) else set(),
            'out_altvoltage1_TX_LO_powerdown': {'1'},
            'out_voltage_sampling_frequency': {'2500000'},
            'in_voltage_sampling_frequency': {'2500000'},
            'out_voltage_rf_bandwidth': {'3000000'},
            'in_voltage_rf_bandwidth': {'3000000'},
            'out_voltage0_rf_port_select': {'A'},
            'out_voltage0_hardwaregain': set(map(str, range(-89, -49))),
            'out_voltage1_hardwaregain': {'-89'},
        }
        for n in (0, 1):
            allowed.update({f'in_voltage{n}_gain_control_mode': {'manual'},
                            f'in_voltage{n}_hardwaregain': {'30'},
                            f'in_voltage{n}_rf_port_select': {'A_BALANCED'}})
        name = path.removeprefix(self.phy+'/')
        if not self.owned or self._closed or name not in allowed or str(value) not in allowed[name]:
            raise ValueError('配置超出终端已验证业务范围')
        # Active RX clocks/LO must never be changed by the TX preparation path.
        if self.stream and (name.startswith('in_') or 'RX_LO' in name or
                            name in ('out_voltage_sampling_frequency', 'out_voltage_rf_bandwidth')):
            raise RuntimeError('持续接收期间不能重配共享时钟或接收参数')
        _verify_runtime_binding(self)
        return Console.write(self, path, value, tolerance)

    def require_idle(self):
        if not self.stream:
            return super().require_idle()
        if not self.business_mode:
            raise RuntimeError('测控配置前必须释放业务接收')
        self.verify_stream()
        checks = [(self.tx+'/buffer/enable', '0'),
                  (self.phy+'/out_altvoltage1_TX_LO_powerdown', '1'),
                  (self.phy+'/ensm_mode', 'fdd'),
                  (self.phy+'/in_voltage_sampling_frequency', '2500000'),
                  (self.phy+'/out_voltage_sampling_frequency', '2500000')]
        checks += [(self.debug+'/'+key, '0') for key in ('bist_prbs', 'bist_tone', 'loopback')]
        prefixes = {self.phy: '$p', self.tx: '$t', self.debug: '$d'}
        paths = [next(alias+path[len(prefix):] for prefix, alias in prefixes.items()
                      if path.startswith(prefix+'/')) for path, _ in checks]
        actual = self.run(f'p={self.phy}; t={self.tx}; d={self.debug}; cat '+' '.join(paths)).splitlines()
        if actual != [value for _, value in checks]:
            raise RuntimeError('并行业务收发前提变化')

    def configure_business(self, tx_center, rx_center, rx_channel):
        if self.stream:
            raise RuntimeError('调频前必须暂停业务接收')
        self.verify_binding()
        super().require_idle()
        if self.read(self.phy+'/out_altvoltage1_TX_LO_powerdown') != '1':
            raise RuntimeError('本地TX未关闭，拒绝接管')
        self.business_mode = True
        self.tx_channel = 1
        self.rx_channel = rx_channel
        if rx_channel not in (1, 2):
            raise ValueError('未知业务接收口')
        if rx_channel == 2 and self.read(self.debug+'/adi,2rx-2tx-mode-enable') != '1':
            raise RuntimeError('终端1需要RX2A通道')
        self.owned = True
        self.mute()
        tx = business_frequency_plan('sender', tx_center)
        rx = business_frequency_plan('receiver', rx_center)
        for name, value in [('out_voltage_sampling_frequency', 2500000),
                            ('in_voltage_sampling_frequency', 2500000),
                            ('out_voltage_rf_bandwidth', 3000000),
                            ('in_voltage_rf_bandwidth', 3000000),
                            (f'in_voltage{rx_channel-1}_gain_control_mode', 'manual'),
                            (f'in_voltage{rx_channel-1}_hardwaregain', 30),
                            (f'in_voltage{rx_channel-1}_rf_port_select', 'A_BALANCED'),
                            ('out_altvoltage1_TX_LO_frequency', tx['lo_hz']),
                            ('out_altvoltage0_RX_LO_frequency', rx['lo_hz'])]:
            self.configure_if_changed(name, value, 10 if 'frequency' in name else 0)
        return dict(configured=True, tx_lo_hz_readback=int(self.read(self.phy+'/out_altvoltage1_TX_LO_frequency')),
                    rx_lo_hz_readback=int(self.read(self.phy+'/out_altvoltage0_RX_LO_frequency')),
                    expected_rf_hz=tx['center_hz'], expected_rf_mhz=rx['center_hz']/1e6,
                    sample_rate_hz=2500000, rx_channel=rx_channel,
                    tx_atten_db_requested=55, tx_atten_db_readback=89)

    prepare_message = BusinessSource.prepare_message

    @staticmethod
    def receiver_binary():
        path = os.environ.get('NTN_STREAM_RX')
        override = bool(path)
        root = Path(__file__).resolve().parents[2]
        if not path:
            path = root/'board/terminal/stream_rx/bin/stream_rx_armv7'
        path = Path(path)
        if not path.is_file():
            raise RuntimeError('缺少板端接收程序，请先按stream_rx说明构建')
        raw = path.read_bytes()
        if len(raw) > 1048576 or raw[:4] != b'\x7fELF':
            raise ValueError('板端接收程序格式或大小不符')
        if not override:
            manifest = json.loads((root/'board/terminal/stream_rx/build_manifest.json').read_text(encoding='utf-8'))
            source = (root/'board/terminal/stream_rx/stream_rx.c').read_bytes()
            if (hashlib.sha256(raw).hexdigest() != manifest['binary_sha256'] or
                    hashlib.sha256(source.replace(b'\r\n', b'\n')).hexdigest() != manifest['source_sha256']):
                raise RuntimeError('板端接收程序与构建清单不一致')
        return raw

    def start_receive(self):
        if self.stream or not self.business_mode:
            raise RuntimeError('接收状态不允许启动')
        self.verify_binding(); super().require_idle()
        self.ensure_receive_cpu()
        first = (self.rx_channel-1)*2
        for i in (first, first+1):
            if self.read(f'{self.rx}/scan_elements/in_voltage{i}_type') != 'le:S12/16>>0':
                raise RuntimeError('业务采样格式变化')
        raw = self.receiver_binary()
        directory = '/tmp/terminal_rx_'+uuid.uuid4().hex[:12]
        self.run('mkdir '+directory)
        self.stream = directory  # Retain ownership path even on partial startup.
        digest = hashlib.sha256(raw).hexdigest()
        cached = getattr(self, '_receiver_program', None)
        if cached and cached[0] == digest:
            source = cached[1]
            if self.run('sha256sum '+source).split()[0] != digest:
                raise RuntimeError('已部署的接收程序摘要变化')
            self.run(f'cp {source} {directory}/decode')
            if self.run('sha256sum '+directory+'/decode').split()[0] != digest:
                raise RuntimeError('接收程序复用校验失败')
            self.record(kind='receiver_program_reused', sha256=digest)
        else:
            Console.upload(self, directory+'/decode', raw)
            self._receiver_program = (digest, directory+'/decode')
        self.run(f'chmod 700 {directory}/decode; mkfifo {directory}/iq')
        # Three separately pinned processes. The lease never enables a TX.
        self._launch_owned('decoder', f'exec {directory}/decode {directory}/rx --live < {directory}/iq')
        self._launch_owned('reader', f'exec iio_readdev -u local: -T 2000 -b 32768 cf-ad9361-lpc '
                           f'voltage{first} voltage{first+1} > {directory}/iq')
        self.renew_receive()
        guard = (f'while sleep 2; do n=$(cut -d. -f1 /proc/uptime); '
                 f'd=$(cat {directory}/deadline 2>/dev/null); '
                 'test -n "$d" && test "$n" -lt "$d" && continue; '
                 f'for f in {directory}/reader.owned {directory}/decoder.owned; do '
                 'read p t < "$f" || continue; '
                 'test "$(awk \'{print $22}\' /proc/$p/stat 2>/dev/null)" = "$t" && kill -TERM "$p"; '
                 'done; exit; done')
        self._launch_owned('guard', guard)
        deadline = time.monotonic()+6
        while self.read(self.rx+'/buffer/enable') != '1':
            if time.monotonic() > deadline:
                raise RuntimeError('持续接收DMA启动失败')
            time.sleep(.05)
        self.stream_owner = self.read(directory+'/reader.owned').split()
        self.verify_stream()
        Console.upload(self, directory+'/snapshot.sh', snapshot_script(self), mode='legacy')
        self._snapshot_ready_for = directory
        self.record(kind='continuous_receiver_started', directory=directory,
                    reader=self.stream_owner, binary_sha256=hashlib.sha256(raw).hexdigest())

    def ensure_receive_cpu(self):
        """Online an available second Zynq CPU for this boot, never edit bootargs.

        The affected board boots with maxcpus=1. Linux present/possible are
        checked instead of inferring hardware from a vendor model string.
        Called only before RX startup with idle DMA and a verified binding.
        """
        _verify_runtime_binding(self)
        state = self.run('cat /sys/devices/system/cpu/present '
                         '/sys/devices/system/cpu/possible /sys/devices/system/cpu/online '
                         '/proc/cmdline').splitlines()
        if len(state) != 4:
            raise RuntimeError('CPU配置快照不完整')
        present, possible, online, cmdline = state
        changed = False
        if present == possible == '0-1' and online == '0' and 'maxcpus=1' in cmdline.split():
            if self.read(self.phy+'/out_altvoltage1_TX_LO_powerdown') != '1':
                raise RuntimeError('CPU接收优化前必须停止发射')
            _verify_runtime_binding(self)
            result = self.run('if test -w /sys/devices/system/cpu/cpu1/online; then '
                              'echo 1 > /sys/devices/system/cpu/cpu1/online; fi; '
                              'cat /sys/devices/system/cpu/online')
            _verify_runtime_binding(self)
            changed = result == '0-1'
            online = result
        self.record(kind='receive_cpu_configuration', present=present, possible=possible,
                    online=online, second_cpu_enabled=changed, persistence='current boot only')
        if online == '0':
            self.record(kind='receive_cpu_warning', message='只有一个CPU在线；并行收发吞吐需实测，异常恢复保持启用')

    def _launch_owned(self, name, body):
        d = self.stream
        script = f'echo "$$ $(awk \'{{print $22}}\' /proc/$$/stat)" > {d}/{name}.owned || exit 1; '+body
        self.run(f'sh -c {shlex.quote(script)} > {d}/{name}.log 2>&1 &')
        deadline = time.monotonic()+3
        while True:
            identity = self.run(f'if test -f {d}/{name}.owned; then cat {d}/{name}.owned; fi').split()
            if len(identity) == 2 and all(x.isdigit() for x in identity):
                self.stream_owners[name] = identity
                break
            if time.monotonic() > deadline:
                raise RuntimeError('未取得接收进程身份：'+name)
            time.sleep(.02)

    def renew_receive(self):
        if self.stream:
            self.run(f'echo $(( $(cut -d. -f1 /proc/uptime) + 90 )) > {self.stream}/deadline.next && '
                     f'mv {self.stream}/deadline.next {self.stream}/deadline')

    def verify_stream(self):
        if not self.stream:
            raise RuntimeError('未持有业务接收进程')
        if getattr(self, '_snapshot_ready_for', None) == self.stream:
            before = _usb_identity(self.info['port'])
            if any(before[k] != self._fingerprint[k] for k in _USB_KEYS):
                raise RuntimeError('本地设备USB身份变化')
            result = self.run(f'sh {self.stream}/snapshot.sh check')
            if _usb_identity(self.info['port']) != before:
                raise RuntimeError('本地设备USB身份变化')
            if result.startswith('RXERROR unavailable '):
                self._receive_unavailable('本会话接收已停止：'+result.split()[-1])
            if result != 'RXCHECK1':
                raise RuntimeError('本地接收身份或配置变化：'+result)
            return
        _verify_runtime_binding(self)
        missing = []
        for name in ('reader', 'decoder', 'guard'):
            identity = self.read(self.stream+'/'+name+'.owned').split()
            if len(identity) != 2 or not all(x.isdigit() for x in identity):
                raise RuntimeError('接收进程身份缺失')
            if identity != self.stream_owners.get(name):
                raise RuntimeError('接收进程身份记录变化：'+name)
            if name == 'reader' and self.stream_owner and identity != self.stream_owner:
                raise RuntimeError('接收进程身份变化')
            # Missing is recoverable, a reused PID or changed record is not.
            state = self.run(f'if test ! -e /proc/{identity[0]}/stat; then echo missing; '
                f'elif test "$(awk \'{{print $22}}\' /proc/{identity[0]}/stat)" = {identity[1]}; '
                f'then awk \'{{print $3}}\' /proc/{identity[0]}/stat; else echo changed; fi')
            if state in ('missing', 'Z'):
                missing.append(name)
            elif state not in ('R', 'S', 'D', 'I'):
                raise RuntimeError('接收进程身份或运行状态变化：'+name)
        if missing:
            self._receive_unavailable('本会话接收进程已退出：'+', '.join(missing))
        mask = self.run('cat '+self.rx+'/scan_elements/in_voltage?_en').split()
        if mask != (['0','0','1','1'] if self.rx_channel == 2 else ['1','1','0','0']):
            raise RuntimeError('业务接收通道掩码变化')
        if self.read(self.rx+'/buffer/enable') != '1':
            self._receive_unavailable('业务接收DMA已停止')

    def _receive_unavailable(self, reason):
        # A fatal input error publishes its reason before the decoder exits.
        # Do not hide it behind the later observation of a missing process.
        _verify_runtime_binding(self)
        path = shlex.quote(self.stream+'/rx.status.json')
        raw = self.run(f'if test -f {path}; then echo RXFINAL; cat {path}; else echo RXFINAL_MISSING; fi')
        _verify_runtime_binding(self)
        if raw != 'RXFINAL_MISSING':
            marker, separator, payload = raw.partition('\n')
            if marker.strip() != 'RXFINAL' or not separator:
                raise ValueError('接收退出状态报告缺失或无效')
            status = json.loads(payload)
            if not isinstance(status, dict) or type(status.get('input_error')) is not bool:
                raise ValueError('接收退出状态报告无效')
            if status['input_error']:
                raise RuntimeError('板端采样输入异常，接收进程已退出')
        raise ReceiveUnavailable(reason)

    def poll_receive(self):
        if self._closed or not self.stream:
            raise RuntimeError('本地接收会话已关闭')
        before = _usb_identity(self.info['port'])
        if any(before[k] != self._fingerprint[k] for k in _USB_KEYS):
            raise RuntimeError('本地设备USB身份变化')
        d = self.stream
        mark = time.monotonic()
        result = self.run(f'sh {d}/snapshot.sh', timeout=12)
        elapsed = time.monotonic()-mark
        if _usb_identity(self.info['port']) != before:
            raise RuntimeError('本地设备USB身份变化')
        if result.startswith('RXERROR unavailable '):
            self._receive_unavailable('本会话接收已停止：'+result.split()[-1])
        if result.startswith('RXERROR '):
            raise RuntimeError('本地接收身份或配置变化：'+result)
        if not result.startswith('RXSNAP1\n') and not result.startswith('RXSNAP1\r\n'):
            raise ValueError('板端接收快照标记无效')
        payload, metrics = result.split('RXMETRICS', 1)
        metrics = metrics.strip().splitlines()
        if len(metrics) != 6 or metrics[-1] != self._fingerprint['linux_boot_id']:
            raise RuntimeError('本地设备重启或接收性能快照无效')
        payload = payload.split('\n', 1)[1].lstrip()
        decoder = json.JSONDecoder()
        status, pos = decoder.raw_decode(payload)
        messages = json.loads(payload[pos:].strip())
        if status is None:
            return None
        status['host_poll_ms'] = round(elapsed*1000, 3)
        status['cpu_online'], status['loadavg'], status['cpu_ticks'] = metrics[:3]
        status['decoder_proc_stat'], status['reader_proc_stat'] = metrics[3:5]
        return status, messages

    def verify_transmit(self):
        # Full IIO identification is performed when connecting. Repeating it
        # every poll consumed the single-core board's DSP scheduling margin.
        _verify_runtime_binding(self)
        values = self.run('cat '+' '.join((self.remote+'/guard_state',
            self.phy+'/out_altvoltage1_TX_LO_powerdown', self.remote+'/guard_owned',
            self.remote+'/owned', self.remote+'/deadline', '/proc/uptime',
            self.tx+'/buffer/enable'))).splitlines()
        if len(values) != 7:
            # guard_state is written by the exiting shell. An in-flight
            # truncate/write may briefly omit its line; accept only a fully
            # confirmed off state, never infer that an incomplete TX is live.
            return self._confirm_transmit_stopped()
        state, powerdown, guard, writer, deadline, uptime, dma = values
        if state not in ('enabled', 'stopped'):
            raise RuntimeError('发送保护状态异常')
        if state == 'stopped' or powerdown != '0' or dma != '1' or int(deadline)-float(uptime.split()[0]) <= 0:
            return self._confirm_transmit_stopped()
        checks = []
        for identity in (guard, writer):
            owned = identity.split()
            if len(owned) != 2 or not all(x.isdigit() for x in owned):
                raise RuntimeError('发送保护进程身份无效')
            checks.append(f'if {{ read -r s < /proc/{owned[0]}/stat; }} 2>/dev/null; then '
                          's=${s##*) }; set -- $s; state=$1; shift 19; '
                          f'if test "$1" != {owned[1]}; then echo changed; '
                          'elif test "$state" = Z; then echo missing; else echo live; fi; '
                          'else echo missing; fi')
        states = self.run('; '.join(checks)).splitlines()
        if len(states) != 2 or any(s not in ('live', 'missing') for s in states):
            raise RuntimeError('发送保护进程身份变化')
        if 'missing' in states:
            # The deadline can cross between the two reads. Missing is not
            # equivalent to PID reuse, and a completed guarded stop is normal.
            return self._confirm_transmit_stopped()
        return True

    def _confirm_transmit_stopped(self):
        """A transition is normal only after guard, LO and DMA agree on off."""
        until = time.monotonic()+1.5
        while True:
            values = self.run('cat '+self.remote+'/guard_state '+
                              self.phy+'/out_altvoltage1_TX_LO_powerdown '+
                              self.tx+'/buffer/enable').splitlines()
            if values == ['stopped', '1', '0']:
                self.record(kind='transmit_stop_confirmed', guard='stopped', tx_lo_off=True, tx_dma=0)
                return False
            if time.monotonic() >= until:
                raise RuntimeError('发送保护发生变化，但停发状态未确认')
            time.sleep(.05)

    def stop_receive(self):
        if not self.stream:
            return
        _verify_runtime_binding(self)
        d = self.stream
        stopping = []
        for name in ('guard', 'reader', 'decoder'):
            identity = self.run(f'if test -f {d}/{name}.owned; then cat {d}/{name}.owned; fi').split()
            if not identity:
                if name in self.stream_owners:
                    raise RuntimeError('接收清理身份记录丢失：'+name)
                continue
            if len(identity) != 2 or not all(x.isdigit() for x in identity):
                raise RuntimeError('接收清理身份无效')
            if name in self.stream_owners and identity != self.stream_owners[name]:
                raise RuntimeError('接收清理身份变化：'+name)
            stopping.append(identity)
            self.run(f'if test "$(awk \'{{print $22}}\' /proc/{identity[0]}/stat 2>/dev/null)" = {identity[1]}; '
                     f'then kill -TERM {identity[0]}; fi')
        end = time.monotonic()+4
        while True:
            active = self.read(self.rx+'/buffer/enable') != '0'
            for pid, ticks in stopping:
                alive = self.run(f'if test "$(awk \'{{print $22}}\' /proc/{pid}/stat 2>/dev/null)" = {ticks}; '
                                 f'then awk \'{{print $3}}\' /proc/{pid}/stat; fi')
                active = active or bool(alive and alive != 'Z')
            if not active:
                break
            if time.monotonic()>end:
                raise RuntimeError('持续接收进程或DMA退出未确认')
            time.sleep(.05)
        self.record(kind='continuous_receiver_stopped', directory=d, reader=self.stream_owner)
        self.stream = self.stream_owner = None
        self.stream_owners.clear()
