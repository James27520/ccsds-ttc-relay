"""Read-only TM1 state return from the Z7ADDALite PS over its DEBUG UART.

This management path is separate from a future DAC/SMA telemetry waveform.
The sender/relay configuration worker remains the sole owner of LDSDR's port.
"""
import binascii
import json
from pathlib import Path
import queue
import re
import threading
import time
import uuid

from .transport import discover_devices

TM1_FIELDS = (
    'uptime_ms events network armed pending decoded applied failures '
    'd_valid d_event d_origin d_air_seq d_rx_mhz d_tx_mhz '
    's_valid s_event s_origin s_air_seq s_rx_mhz s_tx_mhz s_udp_seq s_count s_rc '
    'a_valid a_event a_origin a_air_seq a_rx_mhz a_tx_mhz a_udp_seq a_rc a_rx_hz a_tx_hz spi_valid'
).split()


def parse_tm1(line):
    """Validate the entire versioned line before exposing any state fields."""
    if not isinstance(line, str) or len(line) > 1023:
        raise ValueError('TM1行类型或长度不符')
    line = line.rstrip('\r\n')
    match = re.fullmatch(r'(TM1 [\x20-\x7e]+) crc16=([0-9A-F]{4})', line)
    if not match or binascii.crc_hqx(match[1].encode('ascii'), 0xffff) != int(match[2], 16):
        raise ValueError('TM1格式或CRC校验失败，未更新状态')
    pairs = match[1][4:].split(' ')
    if len(pairs) != len(TM1_FIELDS):
        raise ValueError('TM1字段不完整')
    values = {}
    for key, pair in zip(TM1_FIELDS, pairs):
        field = re.fullmatch(re.escape(key) + r'=(-?(?:0|[1-9][0-9]*))', pair)
        if not field:
            raise ValueError('TM1字段顺序或整数格式不符：' + key)
        value = int(field[1])
        if key in ('s_rc', 'a_rc'):
            lower, upper = -(1 << 31), (1 << 31)-1
        elif key in ('a_rx_hz', 'a_tx_hz'):
            lower, upper = 0, (1 << 64)-1
        elif key.endswith('_mhz') or key.endswith('_udp_seq'):
            lower, upper = 0, 65535
        elif key.endswith('_air_seq'):
            lower, upper = 0, 255
        elif key.endswith('_origin'):
            lower, upper = 0, 4
        elif key.endswith('_valid') or key in ('network', 'armed', 'pending'):
            lower, upper = 0, 1
        else:
            lower, upper = 0, (1 << 32)-1
        if not lower <= value <= upper:
            raise ValueError('TM1数值越界：' + key)
        values[key] = value
    if values['spi_valid'] != 0 or (values['a_valid'] and values['a_rc'] != 0):
        raise ValueError('TM1状态语义不符')
    for prefix in ('d', 's', 'a'):
        if values[prefix+'_valid'] and values[prefix+'_origin'] == 0:
            raise ValueError('有效TM1记录缺少来源')
    return values


class TelemetrySerial:
    """Only status and telemetry queries are permitted on this connection."""

    def __init__(self, port, record=lambda **event: None):
        import serial
        from serial.tools import list_ports
        matches = [p for p in list_ports.comports() if p.device == port]
        if len(matches) != 1 or matches[0].vid is None:
            raise ValueError('请选择当前USB调试串口')
        self.record = record
        self.port = serial.Serial(port=None, baudrate=115200, timeout=.05, write_timeout=1,
                                  xonxoff=False, rtscts=False, dsrdtr=False)
        self.port.dtr = self.port.rts = False
        self.port.port = port
        self.port.open()
        try:
            lines = self._command('status')
            if not any(x.startswith('CONTROLLER auto=') for x in lines) or not any(
                    x.startswith('STATUS network=') for x in lines):
                raise RuntimeError('未识别到Z7ADDALite遥控程序')
            self.record(type='identity', port=port, usb_serial=matches[0].serial_number)
        except Exception:
            self.port.close()
            raise

    def _command(self, command):
        if command not in ('status', 'telemetry'):
            raise ValueError('此通道只允许只读查询')
        self.port.reset_input_buffer()
        data = (command+'\r\n').encode('ascii')
        if self.port.write(data) != len(data):
            raise RuntimeError('遥测查询未完整写入')
        raw = bytearray()
        deadline = time.monotonic()+2
        while time.monotonic() < deadline:
            raw.extend(self.port.read(max(1, min(self.port.in_waiting, 4096))))
            if len(raw) > 32768:
                raise RuntimeError('遥测查询响应超过上限')
            if re.search(rb'(?:^|[\r\n])CLI_RESULT rc=-?[0-9]+[\r\n]', raw):
                break
        lines = [x for x in re.split(r'[\r\n]+', raw.decode('ascii', 'strict')) if x]
        self.record(type='telemetry_console', command=command, lines=lines)
        results = [x for x in lines if x.startswith('CLI_RESULT rc=')]
        if len(results) != 1 or results[0] != 'CLI_RESULT rc=0':
            raise RuntimeError('遥测查询未得到成功回执；请核对TM1固件')
        return lines

    def query(self):
        lines = [x for x in self._command('telemetry') if x.startswith('TM1 ')]
        if len(lines) != 1:
            raise RuntimeError('未收到唯一TM1遥测帧')
        return parse_tm1(lines[0])

    def close(self):
        self.port.close()


class TelemetryController:
    """One serial owner; no ARM, nettest, RF settings, or transmitter writes."""

    def __init__(self, emit, log_dir=None, serial_factory=TelemetrySerial):
        self.emit, self.factory = emit, serial_factory
        self.commands = queue.Queue(maxsize=16)
        self.closing = threading.Event()
        self.serial = None
        self.log_dir = Path(log_dir) if log_dir else Path.home()/'CCSDSGroundStation'/'sessions'/(
            time.strftime('%Y%m%d_%H%M%S')+'_telemetry_'+uuid.uuid4().hex[:8])
        self.log_dir.mkdir(parents=True, exist_ok=False)
        self.journal = (self.log_dir/'events.jsonl').open('x', encoding='utf-8')
        self.worker = threading.Thread(target=self._work, name='station-telemetry', daemon=True)
        self.worker.start()

    def record(self, **event):
        self.journal.write(json.dumps(dict(time=time.time(), **event), ensure_ascii=False)+'\n')
        self.journal.flush()

    def event(self, kind, **values):
        event = dict(type=kind, **values)
        self.record(**event)
        self.emit(event)

    def submit(self, action, **values):
        if action == 'close':
            self.closing.set()
        elif not self.closing.is_set():
            try:
                self.commands.put_nowait((action, values))
            except queue.Full:
                self.emit(dict(type='log', level='error', message='遥测查询队列已满'))

    def _disconnect(self):
        connection, self.serial = self.serial, None
        if connection is not None:
            connection.close()

    def _work(self):
        next_query = 0.
        try:
            while not self.closing.is_set():
                try:
                    action, values = self.commands.get(timeout=.1)
                except queue.Empty:
                    if not self.serial or time.monotonic() < next_query:
                        continue
                    action, values = 'query', {}
                if self.closing.is_set():
                    break
                try:
                    if action == 'discover':
                        self.event('devices', devices=discover_devices())
                    elif action == 'connect':
                        if self.serial:
                            raise RuntimeError('请先断开原遥控板')
                        self.serial = self.factory(values['port'], self.record)
                        snapshot = self.serial.query()
                        self.event('status', state='connected', message='TM1已连接；仅执行只读状态查询')
                        self.event('telemetry', snapshot=snapshot, received_at=time.time())
                        next_query = time.monotonic()+2
                    elif action == 'query':
                        if not self.serial:
                            raise RuntimeError('遥控板尚未连接')
                        snapshot = self.serial.query()
                        self.event('telemetry', snapshot=snapshot, received_at=time.time())
                        next_query = time.monotonic()+2
                    elif action == 'disconnect':
                        self._disconnect()
                        self.event('status', state='disconnected', message='已断开；历史值不代表当前状态')
                    else:
                        raise ValueError('不支持的遥测操作')
                except Exception as exc:
                    message = str(exc)
                    try:
                        self._disconnect()
                    except Exception as cleanup:
                        message += '；串口关闭异常：'+str(cleanup)
                    self.event('status', state='error', message=message)
        finally:
            try:
                try:
                    self._disconnect()
                except Exception as exc:
                    self.event('log', level='error', message='串口关闭异常：'+str(exc))
            finally:
                # A failing journal must not strand Tk waiting for cleanup forever.
                try:
                    try:
                        self.record(type='closed')
                    finally:
                        self.emit(dict(type='closed'))
                finally:
                    self.journal.close()
