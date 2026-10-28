"""Explicit, temporary hardware adapters for the wired TC round-trip test.

Separate from the RX-only RF viewer. No persistent device allowlist, no Flash
write, and no automatic takeover of an already active board. Console.run stays
an internal trusted API, not an untrusted-command security boundary.
"""
import re
import time
import uuid

from .transport import Console
from .rf_session import SessionRxConsole, SessionAdda
from sw.tools.telecontrol_waveform import command_iq, make_manifest


def request_values(rx_mhz, tx_mhz, air_seq):
    if (type(rx_mhz) is not int or rx_mhz not in (900, 901) or
            type(tx_mhz) is not int or tx_mhz not in (1000, 1001) or
            type(air_seq) is not int or not 0 <= air_seq <= 255):
        raise ValueError('本阶段限定RX 900/901、TX 1000/1001 MHz，序号0..255')
    return dict(rx_mhz=rx_mhz, tx_mhz=tx_mhz, air_seq=air_seq)


class ControlAdda(SessionAdda):
    """Manual normal capture only; no synthetic/nettest/automatic receive path."""
    controls = {'auto off', 'arm off', 'arm on', 'levels 0 89', 'network on',
                'network off', 'capture normal 0 0', 'capture cancel', 'decode'}

    def __init__(self, *args, **kwargs):
        self.control_owned = False
        super().__init__(*args, **kwargs)

    def control(self, command):
        if command not in self.controls or not self.control_owned or self._closed:
            raise ValueError('遥控事务命令未授权')
        self.verify_binding()
        lines = self._exchange(command, timeout=20 if command == 'network on' else 8)
        if any(line.startswith('BOOT ') for line in lines):
            self.close()
            raise RuntimeError('遥控板会话已重启')
        return lines

    def capture_status(self):
        lines = self._command('status')
        rows = [re.fullmatch(r'CONTROLLER auto=([01]) capture_state=([0-7]) '
                            r'capture_valid=([01]) consumed=([01])', line) for line in lines]
        rows = [r for r in rows if r]
        if len(rows) != 1:
            raise RuntimeError('缺少唯一ADC控制状态')
        return dict(zip(('auto', 'state', 'valid', 'consumed'), map(int, rows[0].groups())))

    def acquire_control(self):
        self.verify_binding()
        capture, state = self.capture_status(), self.query()
        if (capture['auto'] or capture['state'] in range(1, 6) or
                any(state[k] for k in ('network', 'armed', 'pending'))):
            raise RuntimeError('遥控板已有任务；拒绝接管')
        self.control_owned = True
        return state

    def release_control(self):
        if not self.control_owned:
            return
        errors = []
        for command in ('auto off', 'arm off', 'capture cancel', 'network off'):
            try:
                self.control(command)
            except Exception as exc:
                errors.append(command+': '+str(exc))
        try:
            state = self.query()
            if any(state[k] for k in ('network', 'armed', 'pending')):
                errors.append('遥控任务空闲未确认')
        except Exception as exc:
            errors.append(str(exc))
        if errors:
            raise RuntimeError('; '.join(errors))
        self.control_owned = False


class CommandSource(SessionRxConsole):
    """A selected current-boot source, limited to the validated 100.5 MHz test.

    Constructor is read-only. prepare() needs an explicit wiring confirmation
    and creates a private waveform/guard in RAM while TX is still off. start()
    must be invoked separately. The inherited ordinary Console gate is intact.
    """
    def __init__(self, *args, **kwargs):
        self.owned = self.prepared = False
        self.remote = '/tmp/tc_roundtrip_'+uuid.uuid4().hex[:12]
        super().__init__(*args, **kwargs)
        self.info['identity_scope'] = 'current process, Linux boot and USB; explicit fixed TC TX profile'
        self.info['physical_role'] = 'user-selected TX1A to ADDA ADC1; wiring confirmation required'

    def write(self, path, value, tolerance=0):
        if not self.owned or self._closed:
            raise RuntimeError('指令源会话未取得控制')
        allowed = {
            'out_altvoltage1_TX_LO_frequency': {'100000000'},
            'out_altvoltage1_TX_LO_powerdown': {'1'},
            'out_voltage_sampling_frequency': {'2500000'},
            'out_voltage_rf_bandwidth': {'3000000'},
            'out_voltage0_rf_port_select': {'A'},
            'out_voltage0_hardwaregain': {'-30', '-89'},
            'out_voltage1_hardwaregain': {'-89'},
        }
        if not path.startswith(self.phy+'/') or str(value) not in allowed.get(path[len(self.phy)+1:], set()):
            raise ValueError('超出本阶段固定发射工作点')
        self.verify_binding()
        return Console.write(self, path, value, tolerance)

    def prepare(self, requested, *, wiring_confirmed=False):
        request_values(**requested)
        if wiring_confirmed is not True:
            raise ValueError('需要先确认TX1A到ADC1/J5的接线')
        iq = command_iq(requested['rx_mhz'], requested['tx_mhz'], requested['air_seq'], .1)
        manifest = make_manifest('cmd', iq, .1, requested['rx_mhz'], requested['tx_mhz'], requested['air_seq'])
        self._prepare_waveform(iq.tobytes(), manifest, lo_hz=100000000,
                               attenuation_db=30, block_samples=len(iq))
        self.record(kind='tc_source_prepared', requested=requested, manifest=self.manifest)
        return self.manifest

    def _prepare_waveform(self, raw, manifest, *, lo_hz, attenuation_db, block_samples,
                          check_cancel=lambda: None):
        """Internal helper; each adapter's write whitelist still gates its profile."""
        if self.prepared or type(block_samples) is not int or not 1 <= block_samples <= 262144:
            raise ValueError('发送波形状态或长度无效')
        if len(raw) != block_samples*4:
            raise ValueError('发送波形字节数不符')
        self.block_samples, self.attenuation_db = block_samples, attenuation_db
        check_cancel()
        self.verify_binding()
        self.require_idle()
        if self.read(self.phy+'/out_altvoltage1_TX_LO_powerdown') != '1':
            raise RuntimeError('指令源TX未关闭；拒绝接管')
        self.owned = True
        self.mute()
        self.run('mkdir '+self.remote)
        for name, value in [('out_altvoltage1_TX_LO_frequency', lo_hz),
                            ('out_voltage_sampling_frequency', 2500000),
                            ('out_voltage_rf_bandwidth', 3000000),
                            ('out_voltage0_rf_port_select', 'A')]:
            check_cancel()
            self.write(self.phy+'/'+name, value, 10 if 'frequency' in name else 0)
        self.manifest = manifest
        Console.upload(self, self.remote+'/waveform.bin', raw, lambda _fraction: check_cancel())
        # Only this board-side guard can enable LO. A delayed host request after
        # expiry cannot re-enable TX; it merely creates an unused request file.
        guard = ('cleanup() {\n'
                 f'echo 1 > {self.phy}/out_altvoltage1_TX_LO_powerdown\n'
                 f'echo -89 > {self.phy}/out_voltage0_hardwaregain\n'
                 f'echo -89 > {self.phy}/out_voltage1_hardwaregain\n'
                 f'if read p t < {self.remote}/owned; then\n'
                 'if test "$(awk \'{print $22}\' /proc/$p/stat 2>/dev/null)" = "$t"; then kill -INT "$p"; fi\n'
                 f'fi\necho stopped > {self.remote}/guard_state\n'+'}\n'
                 "trap 'cleanup; exit' INT TERM\n"
                 'deadline=$(( $(cut -d. -f1 /proc/uptime) + 30 ))\n'
                 f'echo "$deadline" > {self.remote}/deadline\n'
                 f'echo ready > {self.remote}/guard_state\n'
                 'enabled=0\nwhile true; do\n'
                 'now=$(cut -d. -f1 /proc/uptime)\n'
                 f'if test -f {self.remote}/cancel || test "$now" -ge "$deadline"; then cleanup; exit; fi\n'
                 f'if test "$enabled" = 0 && test -f {self.remote}/enable_request; then\n'
                 f'echo 0 > {self.phy}/out_altvoltage1_TX_LO_powerdown || '+ '{ cleanup; exit 1; }\n'
                 f'enabled=1; echo enabled > {self.remote}/guard_state\n'
                 'fi\nsleep .05\ndone\n').encode('ascii')
        check_cancel()
        Console.upload(self, self.remote+'/guard.sh', guard, lambda _fraction: check_cancel())
        self.prepared = True

    def start(self):
        if not self.prepared:
            raise RuntimeError('指令波形未准备')
        self.verify_binding()
        self.require_idle()
        if self.read(self.phy+'/out_altvoltage1_TX_LO_powerdown') != '1':
            raise RuntimeError('启发前TX必须关闭')
        digest = self.run('sha256sum '+self.remote+'/waveform.bin').split()[0]
        if digest != self.manifest['sha256']:
            raise RuntimeError('板端指令波形摘要变化')
        self.run(f'iio_writedev -u local: -b {self.block_samples} -c cf-ad9361-dds-core-lpc voltage0 voltage1 '
                 f'< {self.remote}/waveform.bin > {self.remote}/writer.log 2>&1 & p=$!; '
                 't=$(awk \'{print $22}\' /proc/$p/stat); '
                 f'if test -n "$t"; then echo "$p $t" > {self.remote}/owned; '
                 'else kill -INT "$p" 2>/dev/null; exit 1; fi')
        self.run(f'sleep .2; test "$(cat {self.tx}/buffer/enable)" = 1 && '
                 f'test "$(cat {self.tx}/scan_elements/out_voltage0_en)" = 1 && '
                 f'test "$(cat {self.tx}/scan_elements/out_voltage1_en)" = 1 && '
                 f'test "$(cat {self.tx}/scan_elements/out_voltage2_en)" = 0 && '
                 f'test "$(cat {self.tx}/scan_elements/out_voltage3_en)" = 0')
        self.write(self.phy+'/out_voltage0_hardwaregain', -self.attenuation_db)
        self.run(f'sh {self.remote}/guard.sh </dev/null > {self.remote}/guard.log 2>&1 & p=$!; '
                 't=$(awk \'{print $22}\' /proc/$p/stat); '
                 f'test -n "$t" && echo "$p $t" > {self.remote}/guard_owned')
        guard = self.read(self.remote+'/guard_owned').split()
        if len(guard) != 2 or not all(x.isdigit() for x in guard):
            raise RuntimeError('指令源停发保护身份不完整')
        self.run(f'test "$(awk \'{{print $22}}\' /proc/{guard[0]}/stat)" = {guard[1]}')
        self.verify_binding()
        self.run('touch '+self.remote+'/enable_request')
        deadline = time.monotonic()+3
        while self.read(self.remote+'/guard_state') != 'enabled':
            if time.monotonic() >= deadline:
                raise RuntimeError('保护进程未确认开启TX')
            time.sleep(.05)
        self.run(f'test "$(awk \'{{print $22}}\' /proc/{guard[0]}/stat)" = {guard[1]} && '
                 f'test $(( $(cat {self.remote}/deadline) - $(cut -d. -f1 /proc/uptime) )) -gt 10')
        if self.read(self.phy+'/out_altvoltage1_TX_LO_powerdown') != '0':
            raise RuntimeError('指令源本振开启未确认')
        self.record(kind='guarded_source_started', guard_seconds=30, attenuation_db=self.attenuation_db)

    def stop(self):
        if not self.owned:
            return
        self.verify_binding()
        errors = []
        try:
            # Cancels a delayed enable request too. Wait for the guard to finish
            # before independent mute, so it cannot race and undo the mute.
            self.run(f'if test -d {self.remote}; then touch {self.remote}/cancel; fi')
            guard = self.run(f'if test -f {self.remote}/guard_owned; then cat {self.remote}/guard_owned; fi').split()
            if guard:
                if len(guard) != 2 or not all(x.isdigit() for x in guard):
                    raise RuntimeError('保护进程身份损坏')
                deadline = time.monotonic()+3
                while self.read(self.remote+'/guard_state') != 'stopped':
                    if time.monotonic() >= deadline:
                        raise RuntimeError('保护进程停止未确认')
                    time.sleep(.05)
        except Exception as exc:
            errors.append(str(exc))
        try:
            self.mute()
        except Exception as exc:
            errors.append(str(exc))
        try:
            identity = self.run(f'if test -f {self.remote}/owned; then cat {self.remote}/owned; fi').split()
            if identity:
                if len(identity) != 2 or not all(x.isdigit() for x in identity):
                    raise RuntimeError('指令源进程身份损坏')
                pid, ticks = identity
                self.run(f'if test "$(awk \'{{print $22}}\' /proc/{pid}/stat 2>/dev/null)" = {ticks}; '
                         f'then kill -INT {pid}; fi')
            deadline = time.monotonic()+3
            while self.read(self.tx+'/buffer/enable') != '0':
                if time.monotonic() >= deadline:
                    raise RuntimeError('指令源DMA未退出')
                time.sleep(.05)
        except Exception as exc:
            errors.append(str(exc))
        if errors:
            raise RuntimeError('; '.join(errors))
        self.prepared = False
        self.record(kind='tc_source_stopped')
