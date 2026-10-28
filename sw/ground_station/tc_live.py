"""Ground-only TC operation: one local SDR, real uplink and RF return.

No ADDA or relay serial connection is opened here. The separately commissioned
ADDA service owns capture, decode, UDP and finite automatic DAC replies.
Only the existing wired 100.5 MHz uplink / 90.5 MHz downlink is enabled.
"""
import hashlib
import json
import math
from pathlib import Path
import queue
import re
import threading
import time
import uuid

from .tc_hardware import CommandSource, request_values
from .device_lease import PortLease
from .transport import Console
from .rf_live import Cancelled, FS, SAMPLES
from .tc_evidence import _integer, _json_finite
from sw.tools.telemetry_downlink import decode_capture_windows, parse_frame
from sw.tools.telecontrol_waveform import OPERATIONS


def assess_rf_reply(requested, report, previous=None):
    """Validate raw ATM1 bytes against this request, without USB substitutes.

    CRC and request association are not cryptographic authentication. First
    reply in a connection has no remote boot/uptime baseline. Later replies
    must advance events and uptime; a reboot requires a new connection.
    """
    request_values(**requested)
    _json_finite(report)
    if type(report) is not dict or type(report.get('frames')) is not list or not report['frames']:
        raise TimeoutError('没有收到有效射频回报，执行结果未知')
    unique = {}
    for frame in report['frames']:
        if type(frame) is not dict or type(frame.get('payload_hex')) is not str or not re.fullmatch(r'(?:[0-9a-fA-F]{192}|[0-9a-fA-F]{224})', frame['payload_hex']):
            raise ValueError('回报帧字节缺失或长度错误')
        crc = _integer(frame.get('crc16'), 0, 65535, 'CRC16')
        payload = bytes.fromhex(frame['payload_hex'])
        snapshot = parse_frame(b'\xaa\xaa'+bytes([len(payload)])+payload+crc.to_bytes(2, 'big'))
        operation = requested.get('operation', 'frequency')
        if (operation != 'frequency') != (snapshot['protocol'] == 'EXPERIMENTAL_ATM2'):
            raise ValueError('回报版本与操作不符')
        records = [snapshot[name] for name in ('decoded_record', 'send_record', 'ack_record')]
        for record in records:
            if record['valid'] != 1 or record['origin'] != 1:
                raise ValueError('回报并非完整的 ADC_NORMAL 遥控事务')
            if (any(record[key] != requested[key] for key in ('rx_mhz', 'tx_mhz', 'air_seq')) or
                    record['command_version'] != OPERATIONS[operation]):
                raise ValueError('射频回报与本次指令不符，不能标为成功')
        decoded, sent, ack = records
        if not (0 < decoded['event'] < sent['event'] < ack['event'] == snapshot['events']):
            raise ValueError('回报事务顺序无效')
        if (snapshot['pending'] or snapshot['armed'] or not snapshot['network'] or
                sent['udp_seq'] != ack['udp_seq'] or sent['rc'] or
                not 1 <= sent['count'] <= 3 or not 0 <= ack['udp_seq'] <= 0x3fff):
            raise ValueError('回报中的执行状态或 UDP ACK 无效')
        if operation == 'frequency' and ack['rc']:
            raise ValueError('改频 ACK 无效')
        if ack['rc'] not in range(-7, 1):
            raise ValueError('未知远端返回码')
        if not ack['rc']:
            if operation in ('frequency', 'enable'):
                for axis in ('rx', 'tx'):
                    if abs(ack[axis+'_hz']-requested[axis+'_mhz']*1_000_000) > 10_000:
                        raise ValueError('返回频率与请求不符')
            if operation != 'frequency':
                radio = snapshot['relay']
                if not radio['valid']:
                    raise ValueError('回报缺少有效模式与电平回读')
                if operation == 'enable' and (radio['mode'] != 1 or radio['rx_gain_db'] != [30, 30] or
                        radio['tx_attenuation_mdb'] != [50000, 50000] or not radio['lease_active'] or radio['mute_fault']):
                    raise ValueError('开启回报的实际模式、电平或租期不符')
                if operation == 'stop' and (radio['mode'] != 2 or radio['rx_gain_db'] != [0, 0] or
                        radio['tx_attenuation_mdb'] != [89000, 89000] or radio['lease_active'] or radio['remaining_ms']):
                    raise ValueError('停止回报未确认静音电平')
        if previous and (snapshot['events'] <= previous['events'] or
                         snapshot['uptime_ms'] < previous['uptime_ms'] or
                         snapshot['sequence'] <= previous['sequence']):
            raise ValueError('回报过期或远端已重启，请重新建立会话')
        unique[payload] = snapshot
    if len(unique) != 1:
        raise ValueError('采样含有多个不同事务快照，不能合并为一次成功')
    snapshot = next(iter(unique.values()))
    ack = snapshot['ack_record']
    result = dict(passed=ack['rc'] == 0, matched=True, requested=dict(requested),
                ack=dict(rx_hz=ack['rx_hz'], tx_hz=ack['tx_hz'], udp_seq=ack['udp_seq']),
                frame_count=len(report['frames']), snapshot=snapshot,
                evidence_source='actual_iq_crc_checked',
                frequency_source='relay_ack_in_rf_return', independent_spi=False)
    if operation != 'frequency':
        result.update(remote_rc=ack['rc'], relay=dict(snapshot['relay']))
    return result


class AutonomousRadio(CommandSource):
    """Fixed TC transmitter plus bounded local RX, sharing one console owner."""
    def __init__(self, *args, **kwargs):
        self.capture_directory = None
        self.rx_lo = None
        super().__init__(*args, **kwargs)

    def prepare(self, requested, *, wiring_confirmed=False):
        if self.prepared or self.capture_directory:
            raise RuntimeError('上次测控操作尚未结束')
        self.remote = '/tmp/tc_auto_'+uuid.uuid4().hex[:12]
        return super().prepare(requested, wiring_confirmed=wiring_confirmed)

    def configure_receive(self, check_cancel):
        self.verify_binding()
        self.require_idle()
        if not self.owned or self.read(self.phy+'/out_altvoltage1_TX_LO_powerdown') != '1':
            raise RuntimeError('必须在已静音的测控会话中准备接收')
        # Fixed values only; no caller-provided sysfs path or raw command.
        for name, value in [('in_voltage_sampling_frequency', FS),
                            ('in_voltage_rf_bandwidth', 3000000),
                            ('in_voltage0_gain_control_mode', 'manual'),
                            ('in_voltage0_hardwaregain', 20),
                            ('in_voltage0_rf_port_select', 'A_BALANCED'),
                            ('out_altvoltage0_RX_LO_frequency', 90000000)]:
            check_cancel()
            got = Console.write(self, self.phy+'/'+name, value, 10 if 'frequency' in name else 0)
            if name == 'out_altvoltage0_RX_LO_frequency':
                self.rx_lo = int(got)
        for channel, index in [('voltage0', '0'), ('voltage1', '1')]:
            if (self.read(self.rx+'/scan_elements/in_'+channel+'_type') != 'le:S12/16>>0' or
                    self.read(self.rx+'/scan_elements/in_'+channel+'_index') != index):
                raise RuntimeError('下行 I/Q 格式或通道顺序不符')

    def finish_capture(self):
        directory = self.capture_directory
        if not directory:
            return
        owned = self.run(f'if test -f {directory}/owned; then cat {directory}/owned; fi').split()
        if len(owned) != 2 or not all(re.fullmatch(r'[0-9]+', x) for x in owned):
            raise RuntimeError('本次接收进程身份缺失，不能确认清理')
        pid, ticks = owned
        self.run(f'if test "$(awk \'{{print $22}}\' /proc/{pid}/stat 2>/dev/null)" = {ticks}; '
                 f'then kill -INT {pid}; fi')
        deadline = time.monotonic()+3
        while self.read(self.rx+'/buffer/enable') != '0':
            if time.monotonic() >= deadline:
                raise RuntimeError('接收缓冲尚未释放')
            time.sleep(.03)
        self.capture_directory = None

    def capture_reply(self, check_cancel):
        self.verify_binding()
        self.require_idle()
        if self.rx_lo is None or self.read(self.phy+'/out_altvoltage1_TX_LO_powerdown') != '1':
            raise RuntimeError('下行采集前必须准备 RX 并确认 TX 已关闭')
        directory = '/tmp/tc_reply_'+uuid.uuid4().hex[:12]
        self.run('mkdir '+directory)
        self.capture_directory = directory
        check_cancel()
        started = time.time()
        try:
            launch = (f'(iio_readdev -u local: -T 1500 -b 65536 -s {SAMPLES} '
                      f'cf-ad9361-lpc voltage0 voltage1 > {directory}/capture.bin 2> {directory}/err & '
                      'p=$!; printf "%s %s\\n" "$p" "$(awk \'{print $22}\' /proc/$p/stat)" '
                      f'> {directory}/owned; wait "$p"; echo $? > {directory}/rc) & '
                      f'for i in $(seq 1 200); do test -f {directory}/rc && break; sleep .01; done; '
                      f'cat {directory}/rc; cat {directory}/err')
            result = self.run(launch, timeout=5)
            if result.strip() != '0':
                raise RuntimeError('下行采集未正常完成：'+result[-200:])
            finished = time.time()
            self.finish_capture()
            check_cancel()
            raw = self.download(directory+'/capture.bin', SAMPLES*4)
            check_cancel()
            return raw, dict(started_at=started, finished_at=finished,
                             sample_rate_hz=FS, samples=SAMPLES, receiver_lo_hz=self.rx_lo)
        finally:
            self.finish_capture()


class TelecontrolController:
    """One serialized worker owns only the PC1 SDR; UI calls are nonblocking."""
    def __init__(self, emit, log_dir=None, *, radio_factory=AutonomousRadio,
                 decoder=decode_capture_windows, transmit_seconds=8,
                 quiet_seconds=30, sequence_pool=None):
        from .tc_sequence import SequencePool
        self.emit, self.radio_factory, self.decoder = emit, radio_factory, decoder
        if not 0 < transmit_seconds <= 8:
            raise ValueError('指令发送时间必须在 0–8 秒内')
        self.transmit_seconds = transmit_seconds
        if not 0 <= quiet_seconds <= 30:
            raise ValueError('旧回报等待时间无效')
        self.quiet_seconds = quiet_seconds
        self.not_before = 0
        self.sequence_pool = sequence_pool if sequence_pool is not None else SequencePool()
        self.commands, self.urgent = queue.Queue(maxsize=4), queue.Queue()
        self.interrupt = threading.Event()
        self.closing = False
        self.radio = None
        self.port_lease = None
        self.used_sequences = set()
        self.previous = None
        self.index = 0
        self.log_dir = Path(log_dir) if log_dir else Path.home()/'CCSDSGroundStation'/'sessions'/(
            time.strftime('%Y%m%d_%H%M%S')+'_tc_'+uuid.uuid4().hex[:8])
        self.log_dir.mkdir(parents=True, exist_ok=False)
        self.journal = (self.log_dir/'events.jsonl').open('x', encoding='utf-8')
        self.worker = threading.Thread(target=self._work, name='tc-ground-only', daemon=True)
        self.worker.start()

    def record(self, **values):
        self.journal.write(json.dumps(dict(time=time.time(), **values), ensure_ascii=False)+'\n')
        self.journal.flush()

    def event(self, kind, **values):
        event = dict(type=kind, **values)
        self.record(**event)
        self.emit(event)

    def status(self, state, message, **values):
        self.event('status', state=state, message=message, **values)

    def submit(self, action, **values):
        if self.closing:
            return
        if action in ('stop', 'disconnect', 'close'):
            self.interrupt.set()
            self.urgent.put((action, values))
        else:
            self.commands.put_nowait((action, values))

    def _check_cancel(self):
        if self.interrupt.is_set():
            raise Cancelled('操作已取消；远端已执行与否以射频回报为准')

    def _connect(self, source_port):
        if self.radio:
            raise RuntimeError('请先断开当前会话')
        self.status('connecting', '正在核验本地发送板')
        self.port_lease = PortLease(source_port)
        self.radio = self.radio_factory(source_port, self.record)
        self.radio.require_idle()
        if self.radio.read(self.radio.phy+'/out_altvoltage1_TX_LO_powerdown') != '1':
            raise RuntimeError('板卡正在发射，拒绝接管')
        self._check_cancel()
        self.previous = None  # Remote reboot requires an explicit new connection.
        # Existing finite automatic replies end within 23 s after ACK. Start a
        # new quiet interval only after local TX-off has actually been checked.
        self.not_before = time.monotonic()+self.quiet_seconds
        self.event('connected', source=self.radio.info,
                   next_sequence=self.sequence_pool.next_available())
        self.status('connected', '本地发送板已连接')

    def _send(self, requested, wiring_confirmed=False):
        requested = request_values(**requested)
        if wiring_confirmed is not True:
            raise ValueError('当前须为测控上下行接线')
        if not self.radio:
            raise RuntimeError('请先连接本地发送板')
        if requested['air_seq'] in self.used_sequences:
            raise ValueError('本会话已使用该指令序号，请生成新指令')
        self.sequence_pool.reserve(requested['air_seq'])
        self.used_sequences.add(requested['air_seq'])  # Reserve even on failure.
        self.index += 1
        directory = self.log_dir/f'command_{self.index:04d}'
        directory.mkdir(exist_ok=False)
        report = dict(passed=False, requested=requested, source=self.radio.info)
        started = time.monotonic()
        try:
            self._check_cancel()
            self.status('sending', '正在准备并发送遥控指令')
            report['waveform'] = self.radio.prepare(requested, wiring_confirmed=True)
            self._check_cancel()
            self.radio.configure_receive(self._check_cancel)
            self._check_cancel()
            delay = max(0, self.not_before-time.monotonic())
            if delay:
                self.status('sending', f'等待旧回报窗口结束，约 {delay:.0f} 秒')
                if self.interrupt.wait(delay):
                    self._check_cancel()
            self.record(kind='tc_quiet_window_complete', minimum_seconds=self.quiet_seconds)
            self.radio.start()
            report['uplink_started_at'] = time.time()
            try:
                if self.interrupt.wait(self.transmit_seconds):
                    self._check_cancel()
            finally:
                self.radio.stop()
            report['uplink_stopped_at'] = time.time()
            self._check_cancel()
            self.status('receiving', '正在接收遥控板自动返回的射频回报')
            raw, timing = self.radio.capture_reply(self._check_cancel)
            report['acquisition'] = timing
            iq_path = directory/'reply.bin'
            iq_path.write_bytes(raw)
            decoded = self.decoder(raw, sample_rate_hz=FS, symbol_rate=100000,
                                   expected_offset_hz=90500000-self.radio.rx_lo)
            decoded.update(iq_path=str(iq_path), sha256=hashlib.sha256(raw).hexdigest())
            report_path = directory/'reply.json'
            report_path.write_text(json.dumps(decoded, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
            if decoded['clip_components'] or decoded['rms_codes'] > 1000:
                raise RuntimeError('下行采样削顶或幅度超出已验证范围')
            self._check_cancel()
            assessed = assess_rf_reply(requested, decoded, self.previous)
            report.update(assessed, iq_path=str(iq_path), report_path=str(report_path),
                          elapsed_seconds=time.monotonic()-started)
            if 'relay' in assessed:
                # The ACK's lease clock predates receipt. Subtract the entire
                # operation duration, a conservative lower bound without clock sync.
                report['relay'] = dict(assessed['relay'],
                    remaining_lower_bound_ms=max(0, assessed['relay']['remaining_ms']-
                                                 math.ceil(report['elapsed_seconds']*1000)),
                    snapshot_received_at=time.time())
            self.previous = assessed['snapshot']
        except Exception as exc:
            report['error'] = str(exc)
            raise
        finally:
            (directory/'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        self.event('result', **report)
        self.status('connected', '已收到与本次指令匹配的射频执行回报')

    def _disconnect(self):
        errors = []
        if self.radio:
            try:
                self.radio.finish_capture()
            except Exception as exc:
                errors.append('接收停止：'+str(exc))
            try:
                self.radio.stop()
            except Exception as exc:
                errors.append('发送停止：'+str(exc))
            try:
                self.radio.close()
            except Exception as exc:
                errors.append('串口关闭：'+str(exc))
        self.radio = None
        if self.port_lease:
            self.port_lease.close()
            self.port_lease = None
        if errors:
            raise RuntimeError('；'.join(errors))

    def _work(self):
        try:
            self.status('disconnected', '请选择本地发送板')
            while not self.closing:
                try:
                    action, values = self.urgent.get_nowait()
                    while not self.commands.empty():
                        try:
                            self.commands.get_nowait()
                        except queue.Empty:
                            break
                except queue.Empty:
                    try:
                        action, values = self.commands.get(timeout=.1)
                    except queue.Empty:
                        continue
                try:
                    if action in ('stop', 'disconnect', 'close'):
                        self.status('stopping', '正在停止本地收发并释放设备')
                        self._disconnect()
                        if action == 'close':
                            self.closing = True
                        else:
                            self.status('disconnected', '本地已停发；远端自动回报按有界窗口结束')
                    else:
                        self._check_cancel()
                        if action == 'connect':
                            self._connect(**values)
                        elif action == 'send':
                            self._send(**values)
                        else:
                            raise ValueError('未知测控操作')
                except Exception as exc:
                    category = ('cancelled' if isinstance(exc, Cancelled) else
                                'timeout' if isinstance(exc, TimeoutError) else
                                'validation' if isinstance(exc, ValueError) else 'hardware')
                    cleanup = ''
                    try:
                        self._disconnect()
                    except Exception as error:
                        cleanup = '；清理未完全确认：'+str(error)
                    self.status('error', str(exc)+cleanup, category=category)
                    if action == 'close':
                        self.closing = True
                finally:
                    # A failed cleanup must not poison every future connection.
                    # A newer queued urgent action retains cancellation priority.
                    if action in ('stop', 'disconnect', 'close') and self.urgent.empty():
                        self.interrupt.clear()
        finally:
            self.closing = True
            try:
                self._disconnect()
            except Exception as exc:
                self.emit(dict(type='status', state='error', message=str(exc), category='hardware'))
            closed = dict(type='status', state='closed', message='测控窗口已关闭')
            try:
                self.record(**closed)
            except Exception as exc:
                self.emit(dict(type='log', level='error', message='关闭日志写入失败：'+str(exc)))
            finally:
                try:
                    self.journal.close()
                finally:
                    self.emit(closed)  # UI closure must not depend on disk health.
