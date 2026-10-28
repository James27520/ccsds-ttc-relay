"""Explicit, finite DAC-to-SDR acquisition. One worker owns both DEBUG ports.

Probe is read-only. Connecting configures an idle receiver but never starts DAC.
Only a separate capture(send=True) requests one 33.6 ms packet. No auto retry,
periodic send, relay setting, persistent board write, or source-text injection.
"""
import hashlib
import json
from pathlib import Path
import queue
import re
import threading
import time
import uuid

from .transport import discover_devices
from .rf_session import probe_pair, open_pair
from sw.tools.telemetry_downlink import decode_capture_windows

FS = 2_500_000
SAMPLES = 262144


class Cancelled(Exception):
    pass


def idle_dac(state):
    if (state['enabled'] != 1 or state['dac_verified'] != 1 or
            state['dac_finished'] != 1 or state['pending'] or state['stopping'] or
            state['status'] & 0xd5):  # owner, fault, active, STOP recovery, reset
        raise RuntimeError('DAC未处于已配置且空闲的状态；本次未请求发送')


class RFTelemetryController:
    def __init__(self, emit, log_dir=None, *, prober=probe_pair, opener=open_pair,
                 decoder=decode_capture_windows):
        self.emit, self.prober, self.opener, self.decoder = emit, prober, opener, decoder
        self.commands = queue.Queue(maxsize=8)
        self.urgent = queue.Queue()
        self.interrupt = threading.Event()
        self.closing = False
        self.receiver = self.adda = None
        self.receiver_owned = self.adda_owned = False
        self.binding = self.binding_token = None
        self.capture_directory = None
        self.index = 0
        self.log_dir = Path(log_dir) if log_dir else Path.home()/'CCSDSGroundStation'/'sessions'/(
            time.strftime('%Y%m%d_%H%M%S')+'_rf_tm_'+uuid.uuid4().hex[:8])
        self.log_dir.mkdir(parents=True, exist_ok=False)
        self.journal = (self.log_dir/'events.jsonl').open('x', encoding='utf-8')
        self.worker = threading.Thread(target=self._work, daemon=True, name='rf-telemetry')
        self.worker.start()

    def record(self, **data):
        self.journal.write(json.dumps(dict(time=time.time(), **data), ensure_ascii=False)+'\n')
        self.journal.flush()

    def event(self, kind, **data):
        event = dict(type=kind, **data)
        self.record(**event)
        self.emit(event)

    def status(self, state, message):
        self.event('status', state=state, message=message)

    def submit(self, action, **data):
        if self.closing:
            return
        if action in ('stop', 'disconnect', 'close'):
            self.interrupt.set()
            self.urgent.put((action, data))
        else:
            try:
                self.commands.put_nowait((action, data))
            except queue.Full:
                self.emit(dict(type='log', level='error', message='操作队列已满'))

    def _check_cancel(self):
        if self.interrupt.is_set():
            raise Cancelled()

    def _probe(self, rx_port, adda_port):
        if self.receiver or self.adda:
            raise RuntimeError('请先断开当前RF接收会话')
        if rx_port == adda_port:
            raise ValueError('遥控板与SDR不能选择同一串口')
        self.binding = self.binding_token = None
        binding = self.prober(rx_port, adda_port, self.record)
        self._check_cancel()
        self.binding, self.binding_token = binding, uuid.uuid4().hex
        self.event('probe', binding=binding, binding_token=self.binding_token)
        self.status('probed', '只读核验完成；绑定仅适用于当前连接及启动会话')

    def _connect(self, binding_token):
        if not self.binding or binding_token != self.binding_token:
            raise RuntimeError('绑定已失效，请重新核验两个端口')
        if self.receiver or self.adda:
            raise RuntimeError('会话已连接')
        self.receiver, self.adda = self.opener(self.binding, self.record)
        self._check_cancel()
        c, a = self.receiver, self.adda
        c.require_idle()
        idle_dac(a.tmstatus())
        state = a.query()
        if state['armed'] or state['pending']:
            raise RuntimeError('遥控板有正在执行的控制任务，请先停止原任务')
        # A failed idle/firmware precheck must not stop another task's hardware.
        self.receiver_owned = True
        c.mute()
        for name, value in [('in_voltage_sampling_frequency', FS),
                            ('in_voltage_rf_bandwidth', 3000000),
                            ('in_voltage0_gain_control_mode', 'manual'),
                            ('in_voltage0_hardwaregain', 20),
                            ('in_voltage0_rf_port_select', 'A_BALANCED')]:
            self._check_cancel()
            c.write(c.phy+'/'+name, value)
        self.rx_lo = int(c.write(c.phy+'/out_altvoltage0_RX_LO_frequency', 90000000, 10))
        for channel, index in [('voltage0', '0'), ('voltage1', '1')]:
            if (c.read(c.rx+'/scan_elements/in_'+channel+'_type') != 'le:S12/16>>0' or
                    c.read(c.rx+'/scan_elements/in_'+channel+'_index') != index):
                raise RuntimeError('接收I/Q格式或通道顺序不符')
        self._check_cancel()
        self.status('connected', '会话已绑定；90MHz接收、增益20dB；尚未请求DAC发送')

    def _finish_owned_capture(self):
        """Kill only the reader launched in this private directory, if still live."""
        c, directory = self.receiver, self.capture_directory
        if c is None or directory is None:
            return
        owned = c.run(f'if test -f {directory}/owned; then cat {directory}/owned; fi').split()
        if len(owned) == 2 and all(re.fullmatch(r'[0-9]+', x) for x in owned):
            pid, ticks = owned
            c.run(f'if test "$(awk \'{{print $22}}\' /proc/{pid}/stat 2>/dev/null)" = {ticks}; '
                  f'then kill -INT {pid}; fi')
        deadline = time.monotonic()+2.5
        while c.read(c.rx+'/buffer/enable') != '0':
            if time.monotonic() >= deadline:
                raise RuntimeError('本次采集缓冲释放未确认')
            time.sleep(.03)
        self.capture_directory = None

    def _capture(self, send=True):
        if type(send) is not bool:
            raise ValueError('send必须为布尔值')
        if not self.receiver or not self.adda:
            raise RuntimeError('请先核验并连接两个设备')
        begin = time.monotonic()
        c, a = self.receiver, self.adda
        # A long-lived connection is not ownership of a new task started by
        # another board-side client. Preflight failure only releases our ports.
        self.receiver_owned = self.adda_owned = False
        self._check_cancel()
        c.verify_binding()
        a.verify_binding()
        c.require_idle()
        before = a.tmstatus()
        idle_dac(before)
        if c.read(c.phy+'/out_altvoltage1_TX_LO_powerdown') != '1':
            raise RuntimeError('接收SDR的TX未保持关闭')
        reference = a.query()  # Journal only; never passed to the decoder.
        if reference['armed'] or reference['pending']:
            raise RuntimeError('遥控板任务仍在执行')
        self.receiver_owned = True
        if send:
            self.adda_owned = True
            a.clear()
        self._check_cancel()
        self.index += 1
        stem = f'rf_{self.index:06d}'
        directory = '/tmp/tm_live_'+uuid.uuid4().hex[:12]
        c.run('mkdir '+directory)
        self.capture_directory = directory
        self.status('capturing', '正在准备接收窗口'+('，随后发送一次状态' if send else '；本次不请求发送'))
        timing = dict(started_at=time.time(), send_requested=send)
        try:
            # Keep PID + /proc start ticks before waiting, including when the
            # console response is lost. No global kill or buffer reset.
            launch = (f'(iio_readdev -u local: -T 1500 -b 65536 -s {SAMPLES} '
                      f'cf-ad9361-lpc voltage0 voltage1 > {directory}/capture.bin 2> {directory}/err & '
                      'p=$!; printf "%s %s\\n" "$p" "$(awk \'{print $22}\' /proc/$p/stat)" '
                      f'> {directory}/owned; wait "$p"; echo $? > {directory}/rc) & '
                      f'for i in $(seq 1 100); do if test "$(cat {c.rx}/buffer/enable)" = 1; '
                      'then echo CAPTURE_READY; break; fi; sleep .005; done')
            response = c.run(launch, timeout=4)
            if 'CAPTURE_READY' not in response:
                raise RuntimeError('接收缓冲未就绪，本次未请求发送')
            timing['buffer_ready_at'] = time.time()
            self._check_cancel()
            if send:
                if c.read(c.rx+'/buffer/enable') != '1':
                    raise RuntimeError('采样窗口已结束，本次未请求发送')
                self._check_cancel()
                timing['send_requested_at'] = time.time()
                a.send()  # No extra status queries between ready and this write.
            completion = c.run(f'for i in $(seq 1 200); do test -f {directory}/rc && break; sleep .01; done; '
                               f'cat {directory}/rc; cat {directory}/err', timeout=4)
            if completion.strip() != '0':
                raise RuntimeError('采集进程未成功完成：'+completion[-300:])
            timing['capture_finished_at'] = time.time()
            self._finish_owned_capture()
            self._check_cancel()
            after = a.tmstatus()
            idle_dac(after)
            expected_sequence = (before['seq']+int(send)) & 0xffffffff
            if after['seq'] != expected_sequence:
                raise RuntimeError('板端发送序号变化与本次请求不符')
            self.event('log', level='info', message='采样完成，正在传回IQ；此时DAC已空闲')
            raw = c.download(directory+'/capture.bin', SAMPLES*4)
            iq_path = self.log_dir/(stem+'.bin')
            iq_path.write_bytes(raw)
            self._check_cancel()
            report = self.decoder(raw, sample_rate_hz=FS, symbol_rate=100000,
                                  expected_offset_hz=90500000-self.rx_lo)
            if report['clip_components'] or report['rms_codes'] > 1000:
                raise RuntimeError('采样削顶或超出本阶段已验证输入范围')
            report.update(iq_path=str(iq_path), sha256=hashlib.sha256(raw).hexdigest())
            report_path = self.log_dir/(stem+'.json')
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            evidence = dict(timing=timing, binding=self.binding, before=before, after=after,
                            usb_reference=reference, send_requested=send,
                            receiver_lo_hz=self.rx_lo, iq_sha256=report['sha256'])
            (self.log_dir/(stem+'.capture.json')).write_text(json.dumps(evidence, indent=2), encoding='utf-8')
            self._check_cancel()
            result = dict(report=report, iq_path=str(iq_path), report_path=str(report_path),
                          received_at=timing['capture_finished_at'], send_requested=send)
        finally:
            # A lost reply may mean SEND was accepted. Always stop, and do not
            # suppress a cleanup failure or retry a transmission automatically.
            errors = []
            try:
                if send:
                    self._stop_dac()
                    self.adda_owned = False
            except Exception as exc:
                errors.append('DAC停止未确认：'+str(exc))
            try:
                self._finish_owned_capture()
            except Exception as exc:
                errors.append(str(exc))
            if errors:
                raise RuntimeError('；'.join(errors))
        self._check_cancel()
        self.event('capture', **result, capture_seconds=time.monotonic()-begin)
        self.status('connected', f'本次收到{report["valid_telemetry_count"]}个CRC正确帧；已结束，不自动续发')

    def _stop_dac(self):
        self.adda.stop()
        deadline = time.monotonic()+1.5
        while True:
            state = self.adda.tmstatus()
            if not state['pending'] and not state['stopping'] and not state['status'] & 0xd1:
                self.record(kind='dac_stopped', state=state)
                return
            if time.monotonic() >= deadline:
                raise RuntimeError('DAC停止握手未确认')
            time.sleep(.02)

    def _disconnect(self):
        errors = []
        if self.adda and self.adda_owned:
            try:
                self._stop_dac()
            except Exception as exc:
                errors.append('DAC停止：'+str(exc))
        if self.receiver and self.receiver_owned:
            try:
                self._finish_owned_capture()
                self.receiver.require_idle()
                self.receiver.mute()
            except Exception as exc:
                errors.append('接收端清理：'+str(exc))
        for attr in ('adda', 'receiver'):
            handle = getattr(self, attr)
            if handle:
                try:
                    handle.close()
                except Exception as exc:
                    errors.append('关闭串口：'+str(exc))
                setattr(self, attr, None)
        self.binding = self.binding_token = None
        self.capture_directory = None
        self.receiver_owned = self.adda_owned = False
        if errors:
            raise RuntimeError('；'.join(errors))

    def _work(self):
        self.status('disconnected', '选择遥控板与下行接收SDR，先只读核验')
        try:
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
                if self.interrupt.is_set() and action not in ('stop', 'disconnect', 'close'):
                    continue
                try:
                    if action == 'discover':
                        self.event('devices', devices=discover_devices())
                    elif action == 'probe':
                        self._probe(**values)
                    elif action == 'connect':
                        self._connect(**values)
                    elif action == 'capture':
                        self._capture(**values)
                    elif action in ('stop', 'disconnect', 'close'):
                        self._disconnect()
                        self.interrupt.clear()
                        self.status('disconnected', '已停止并释放串口；再次使用需重新核验')
                    else:
                        raise ValueError('未知RF测控操作')
                except Cancelled:
                    self.event('log', level='info', message='本次操作已取消，等待停止清理')
                except Exception as exc:
                    message = str(exc)
                    try:
                        self._disconnect()
                    except Exception as cleanup:
                        message += '；'+str(cleanup)
                    self.status('error', message)
                finally:
                    if action == 'close':
                        self.closing = True
        finally:
            try:
                self._disconnect()
            except Exception as exc:
                self.emit(dict(type='log', level='error', message='关闭异常：'+str(exc)))
            finally:
                try:
                    self.emit(dict(type='closed'))
                finally:
                    self.journal.close()
