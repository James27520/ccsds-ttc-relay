"""One current-boot radio owner for business duplex and finite TC transactions.

RX has its own board process and never shares a UART reader with TX. Only the
owner's verified RX is allowed to remain enabled while preparing a business TX.
All TC retunes still require idle DMA. Nothing here opens a satellite-side port.
"""
import hashlib
import json
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


class ReceiveUnavailable(RuntimeError):
    """Owned RX stopped; the same bound board may rebuild RX, never old TX."""


class TerminalRadio(AutonomousRadio):
    tx_channel = 1

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
        for path, expected in checks:
            if self.read(path) != expected:
                raise RuntimeError('并行业务收发前提变化：'+path.rsplit('/', 1)[1])

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
        first = (self.rx_channel-1)*2
        for i in (first, first+1):
            if self.read(f'{self.rx}/scan_elements/in_voltage{i}_type') != 'le:S12/16>>0':
                raise RuntimeError('业务采样格式变化')
        raw = self.receiver_binary()
        directory = '/tmp/terminal_rx_'+uuid.uuid4().hex[:12]
        self.run('mkdir '+directory)
        self.stream = directory  # Retain ownership path even on partial startup.
        Console.upload(self, directory+'/decode', raw)
        self.run(f'chmod 700 {directory}/decode; mkfifo {directory}/iq')
        # Three separately pinned processes. The lease never enables a TX.
        self._launch_owned('decoder', f'exec {directory}/decode {directory}/rx < {directory}/iq')
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
        self.record(kind='continuous_receiver_started', directory=directory,
                    reader=self.stream_owner, binary_sha256=hashlib.sha256(raw).hexdigest())

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
            raise ReceiveUnavailable('本会话接收进程已退出：'+', '.join(missing))
        mask = self.run('cat '+self.rx+'/scan_elements/in_voltage?_en').split()
        if mask != (['0','0','1','1'] if self.rx_channel == 2 else ['1','1','0','0']):
            raise RuntimeError('业务接收通道掩码变化')
        if self.read(self.rx+'/buffer/enable') != '1':
            raise ReceiveUnavailable('业务接收DMA已停止')

    def poll_receive(self):
        self.verify_stream(); self.renew_receive()
        d = self.stream
        result = self.run(f'if test -f {d}/rx.status.json; then cat {d}/rx.status.json; '
                          f'echo; cat {d}/rx.messages.json; fi', timeout=12)
        if not result.strip():
            return None
        # Two atomically replaced, independently valid JSON records.
        decoder = json.JSONDecoder()
        status, pos = decoder.raw_decode(result.lstrip())
        messages = json.loads(result.lstrip()[pos:].strip())
        return status, messages

    def verify_transmit(self):
        self.verify_binding()
        state = self.read(self.remote+'/guard_state')
        if state == 'stopped':
            return False
        if state != 'enabled' or self.read(self.phy+'/out_altvoltage1_TX_LO_powerdown') != '0':
            raise RuntimeError('发送保护状态异常')
        for name in ('guard_owned', 'owned'):
            owned = self.read(self.remote+'/'+name).split()
            if len(owned) != 2 or not all(x.isdigit() for x in owned):
                raise RuntimeError('发送保护进程身份无效')
            self.run(f'test "$(awk \'{{print $22}}\' /proc/{owned[0]}/stat)" = {owned[1]}')
        remaining = int(self.run(f'echo $(( $(cat {self.remote}/deadline) - $(cut -d. -f1 /proc/uptime) ))'))
        if remaining <= 0:
            return False
        if self.read(self.tx+'/buffer/enable') != '1':
            raise RuntimeError('发送DMA已停止')
        return True

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
