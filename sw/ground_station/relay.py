"""Explicit local setup of the already-validated LDSDR wired business path."""
import re
import time


class RelayConsole:
    def __init__(self, port, record=lambda **event: None):
        import serial
        from serial.tools import list_ports
        matches = [p for p in list_ports.comports() if p.device == port]
        if len(matches) != 1 or matches[0].vid is None:
            raise ValueError('请选择转发板USB调试口')
        self.record = record
        self.port = serial.Serial(port=None, baudrate=115200, timeout=.03, write_timeout=3)
        self.port.dtr = self.port.rts = False
        self.port.port = port
        self.port.open()
        try:
            status = self.status()
            if status['mode'] != '2' or status['txatt'] != '89':
                raise RuntimeError('转发板未处于已确认的静音状态；拒绝接管正在工作的链路')
            self.diagnostics(atten=89, gain=0, exact_frequency=False)
        except Exception:
            self.port.close()
            raise

    def run(self, command):
        self.port.reset_input_buffer()
        payload = command.encode('ascii')+b'\r\n'
        if self.port.write(payload) != len(payload):
            raise RuntimeError('转发板命令未完整发送')
        end = time.monotonic()+(1.5 if command.startswith('lo ') else .65)
        data = bytearray()
        while time.monotonic() < end:
            data.extend(self.port.read(max(1, min(self.port.in_waiting, 8192))))
            if len(data) > 65536:
                raise RuntimeError('转发板响应超过长度限制')
        reply = data.decode('ascii', 'replace')
        self.record(kind='relay', command=command, reply=reply)
        if 'ERR' in reply or not reply.strip():
            raise RuntimeError('转发板响应异常：'+reply[-500:])
        return reply

    def status(self):
        raw = self.run('status')
        rows = [x for x in raw.splitlines() if x.startswith('STAT ')]
        if len(rows) != 1:
            raise RuntimeError('未识别到LDSDR转发程序')
        fields = dict(re.findall(r'(\w+)=([^\s]+)', rows[0]))
        for key, value in dict(fs='30720000', ddc='00000000', duc='00000000', gain='800', dc='0', rc='0').items():
            if fields.get(key) != value:
                raise RuntimeError('转发板基线不匹配：'+key)
        if not all(k in fields for k in ('mode', 'txatt', 'rxgain', 'clip')):
            raise RuntimeError('转发板状态不完整')
        return fields

    def diagnostics(self, atten=89, gain=30, exact_frequency=True):
        raw = self.run('rfdiag')
        lines = [x.strip() for x in raw.splitlines() if x.strip()]
        required = ['RFPORT1 addr=0x010 rc=0 raw=0x88',
                    'RFDIAG_END rc=0 ready=1 init_rc=0 spi_errors_total=0']
        required += [f'RFATT tx1_mdB_rc=0 value={atten*1000} tx2_mdB_rc=0 value={atten*1000}',
                     f'RFGAIN rx1_db_rc=0 value={gain} rx2_db_rc=0 value={gain}']
        for key in ('RFPLL_RX', 'RFPLL_TX'):
            if not any(re.fullmatch(key+r' addr=0x[0-9A-F]+ rc=0 raw=0x[0-9A-F]+ locked=1', line) for line in lines):
                raise RuntimeError('转发板PLL未锁定')
        for key in ('RFBIST', 'RFLOOP', 'RFPORT_TEST', 'RFDAC_TEST'):
            if not any(re.fullmatch(key+r' addr=0x[0-9A-F]+ rc=0 raw=0x00', line) for line in lines):
                raise RuntimeError('转发板测试源未关闭')
        if not all(x in lines for x in required):
            raise RuntimeError('转发板I/Q修正版或增益/衰减读回不匹配')
        rows = [re.fullmatch(r'RFREAD rx_rc=0 tx_rc=0 rx_hz=(\d+) tx_hz=(\d+)', line) for line in lines]
        matches = [m for m in rows if m]
        m = matches[0] if len(matches) == 1 else None
        if not m or exact_frequency and (abs(int(m[1])-900000000)>10 or abs(int(m[2])-1000000000)>10):
            raise RuntimeError('转发板实际频率不匹配')
        return dict(relay_rx_hz_readback=int(m[1]), relay_tx_hz_readback=int(m[2]),
                    relay_tx_atten_db_readback=atten, relay_rx_gain_db_readback=gain)

    def prepare(self):
        for command in ('auto 0', 'mode 2', 'txatt 89', 'rxgain 30', 'lo 900 1000'):
            self.run(command)
        state = self.status()
        if state['mode'] != '2':
            raise RuntimeError('转发板未静音')
        return dict(self.diagnostics(), relay_mode=2)

    def start(self):
        # Stop resets gain to zero; explicitly restore it before enabling output.
        for command in ('mode 2', 'txatt 89', 'rxgain 30'):
            self.run(command)
        self.diagnostics()
        self.run('txatt 50')
        self.run('mode 1')
        if self.status()['mode'] != '1':
            raise RuntimeError('转发模式未确认')
        return dict(self.diagnostics(atten=50), relay_mode=1)

    def mute(self):
        errors = []
        for command in ('mode 2', 'txatt 89', 'rxgain 0'):
            try:
                self.run(command)
            except Exception as exc:
                errors.append(str(exc))
        try:
            state = self.status()
            if state['mode'] != '2':
                raise RuntimeError('转发静音读回失败')
            result = dict(self.diagnostics(atten=89, gain=0, exact_frequency=False), relay_mode=2)
        except Exception as exc:
            errors.append(str(exc))
            result = {}
        if errors:
            raise RuntimeError('; '.join(errors))
        return result

    def close(self):
        self.port.close()
