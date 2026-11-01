"""Serialized ownership per terminal; RX lives on board across business sends.

The UI receives decoded RF events only. TC temporarily stops local business,
uses the same verified console, then restores RX, never the previous TX.
"""
from collections import OrderedDict, deque
import json
import math
from pathlib import Path
import queue
import threading
import time
import uuid

from .device_lease import PortLease
from .protocol import encode_message, parse_message, new_session_id, MessageTracker, _link
from .rf_live import Cancelled
from .rf_profiles import DEMO_TX_CENTERS, DEMO_RX_CENTERS, business_center_hz
from .tc_live import TelecontrolController, decode_capture_windows
from .tc_sequence import SequencePool
from .terminal_radio import TerminalRadio, ReceiveUnavailable
from .ui_v2_model import business_frequency_plan


class _Transaction:
    """Reuse the validated RF association/CRC/sequence transaction synchronously."""
    _send = TelecontrolController._send

    def __init__(self, owner):
        self.owner = owner
        self.radio = owner.radio
        self.log_dir = owner.log_dir/'control'
        self.log_dir.mkdir(exist_ok=True)
        self.interrupt = owner.interrupt
        self.transmit_seconds = 8
        self.quiet_seconds = 30
        self.not_before = time.monotonic()+30
        self.sequence_pool = SequencePool()
        self.used_sequences = set()
        self.previous = None
        self.index = 0
        self.decoder = decode_capture_windows

    def record(self, **event):
        self.owner.record(channel='control', **event)

    def event(self, kind, **event):
        if kind == 'result':
            self.owner.tc_result = dict(event)
            self.owner.tc_result_at = time.monotonic()
        self.owner.event(kind, channel='control', **event)
        # A remote ACK describes the relay. It never changes a local RF plan.

    def status(self, state, message, **values):
        self.event('status', state=state, message=message, **values)

    def _check_cancel(self):
        self.owner.check_cancel()


class TerminalController:
    def __init__(self, role, emit, log_dir=None, *, radio_factory=TerminalRadio,
                 lease_factory=PortLease, transaction_factory=_Transaction, poll_seconds=1,
                 tx_dwell_seconds=2):
        if role not in ('sender', 'receiver'):
            raise ValueError('终端角色无效')
        self.role, self.emit = role, emit
        self.radio_factory, self.lease_factory = radio_factory, lease_factory
        self.transaction_factory = transaction_factory
        self.radio = self.lease = self.transaction = None
        self.commands, self.urgent = queue.Queue(maxsize=4), queue.Queue()
        self.command_lock = threading.Lock()
        self.job_lock = threading.RLock()
        self.event_lock = threading.RLock()
        self.jobs, self.send_order = OrderedDict(), deque()
        self.close_requested = self.disconnecting = False
        self.tx_dwell_seconds = max(0, float(tx_dwell_seconds))
        self.tx_started_at = 0
        self.tc_result = None
        self.tc_result_at = 0
        self.interrupt = threading.Event()
        self.closing = False
        self.rx_active = self.tx_active = self.tc_active = False
        self.session, self.sequence = new_session_id(), 0
        self.tracker = MessageTracker()
        self.settings = {}
        self.tx_center, self.rx_center = DEMO_TX_CENTERS[0], DEMO_RX_CENTERS[0]
        self.poll_seconds = poll_seconds
        self.last_poll = 0
        self.last_samples = None
        self.last_progress = None
        self.last_receive_recovery = None
        self.receive_rate_anchor = None
        self.last_frame_count = self.last_reject_count = 0
        self.log_dir = Path(log_dir) if log_dir else Path.home()/'CCSDSGroundStation/sessions'/(
            time.strftime('%Y%m%d_%H%M%S')+'_terminal_'+role+'_'+uuid.uuid4().hex[:8])
        self.log_dir.mkdir(parents=True, exist_ok=False)
        self.journal = (self.log_dir/'events.jsonl').open('x', encoding='utf-8')
        self.worker = threading.Thread(target=self._work, daemon=True, name='terminal-'+role)
        self.worker.start()

    def record(self, **values):
        with self.event_lock:
            self.journal.write(json.dumps(dict(time=time.time(), **values), ensure_ascii=False)+'\n')
            self.journal.flush()

    def event(self, kind, **values):
        with self.event_lock:
            event = dict(type=kind, **values)
            self.record(**event)
            self.emit(event)

    def status(self, state, message):
        self.event('status', state=state, message=message)
        self.state(message)

    def state(self, message=''):
        self.event('terminal_state', connected=self.radio is not None,
                   source=self.radio.info if self.radio else None,
                   receiver_process=getattr(self.radio, 'stream_owner', None),
                   rx_active=self.rx_active, tx_active=self.tx_active,
                   tc_active=self.tc_active, message=message)

    def submit(self, action, **values):
        """Accept up to eight unsent jobs, independently of long TC commands.

        Sending confirms local TX only. Failed/cancelled jobs remain retryable;
        only an explicit retry queues them again under the same request ID.
        """
        if action == 'apply_plan' or action == 'connect' and 'tx_center' in values:
            values = dict(values)
            values['tx_center'] = business_center_hz('sender', values['tx_center'])/1e6
            values['rx_center'] = business_center_hz('receiver', values['rx_center'])/1e6
            if action == 'apply_plan' and (not self.radio or self.tc_active):
                raise RuntimeError('请先连接本机板卡，并等待测控结束后应用本机频率')
        if action in ('send', 'retry'):
            with self.job_lock:
                if self.closing or self.close_requested or self.disconnecting or not self.radio:
                    raise RuntimeError('本地终端尚未连接或正在关闭')
                if action == 'retry':
                    request_id = values.get('request_id')
                    job = self.jobs.get(request_id)
                    if job is None or job['state'] != 'retry':
                        raise ValueError('只能手动重试待重试的文本')
                    job.pop('message_id', None)
                else:
                    text = values.get('text')
                    # Validate synchronously, before accepting or logging a job.
                    encode_message(text, self.session, 0)
                    request_id = values.get('request_id')
                    if request_id is None: request_id = uuid.uuid4().hex
                    if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
                        raise ValueError('request_id必须是1至128字符的字符串')
                    if request_id in self.jobs:
                        if self.jobs[request_id]['text'] != text:
                            raise ValueError('同一request_id不能提交不同文本')
                        return request_id
                    if sum(job['state'] != 'sent' for job in self.jobs.values()) >= 8:
                        raise queue.Full('最多保留8条待发或待重试文本')
                    job = dict(request_id=request_id, text=text, state='queued')
                    self.jobs[request_id] = job
                self.send_order.append(request_id)
                self._queue_state(job, 'queued')
                return request_id
        if action == 'cancel_pending':
            self._retry_pending('已取消排队，请手动重试', include_sending=False)
            return
        if self.closing or self.close_requested:
            return
        if action in ('disconnect', 'close', 'cancel_tc', 'stop_tx'):
            if action == 'close': self.close_requested = True
            if action == 'disconnect': self.disconnecting = True
            self.interrupt.set()
            self.urgent.put((action, values))
        else:
            with self.command_lock:
                self.commands.put_nowait((action, values))

    def _queue_state(self, job, state, reason=None):
        # Called with job_lock held. RLock also permits immediate emit callbacks.
        job['state'] = state
        event = dict(request_id=job['request_id'], text=job['text'], state=state)
        if job.get('message_id'): event['message_id'] = job['message_id']
        if reason: event['reason'] = reason
        self.event('tx_queue', **event)

    def _retry_pending(self, reason, *, include_sending=True):
        with self.job_lock:
            self.send_order.clear()
            for job in self.jobs.values():
                if job['state'] == 'queued' or include_sending and job['state'] == 'sending':
                    self._queue_state(job, 'retry', reason)

    def _dispatch_next(self):
        if (not self.radio or not self.rx_active or self.tc_active or self.interrupt.is_set()
                or self.disconnecting or self.close_requested):
            return
        if self.tx_active and time.monotonic()-self.tx_started_at < self.tx_dwell_seconds:
            return
        with self.job_lock:
            while self.send_order:
                job = self.jobs[self.send_order.popleft()]
                if job['state'] == 'queued': break
            else:
                return
            job.pop('message_id', None)
            self._queue_state(job, 'sending')
        self._send(job['text'], request_id=job['request_id'])
        with self.job_lock:
            self._queue_state(job, 'sent')
            # Keep a bounded idempotency history; unsent jobs are never evicted.
            for request_id in list(self.jobs):
                if len(self.jobs) <= 256: break
                if self.jobs[request_id]['state'] == 'sent': del self.jobs[request_id]

    def check_cancel(self):
        if self.interrupt.is_set():
            raise Cancelled('本地操作已取消')

    def discard_pending(self):
        with self.command_lock:
            while True:
                try: self.commands.get_nowait()
                except queue.Empty: break

    def set_plan(self, tx_center, rx_center):
        tx = business_frequency_plan('sender', tx_center)
        rx = business_frequency_plan('receiver', rx_center)
        self.tx_center, self.rx_center = tx['center_hz']/1e6, rx['center_hz']/1e6

    def _connect(self, port, tx_center=None, rx_center=None):
        if self.radio or self.lease:
            raise RuntimeError('本地终端已连接')
        if tx_center is not None or rx_center is not None:
            self.set_plan(tx_center, rx_center)
        self.disconnecting = False
        self.status('connecting', '正在核验本地终端')
        self.lease = self.lease_factory(port)
        self.radio = self.radio_factory(port, self.record)
        self.radio.require_idle()
        if self.radio.read(self.radio.phy+'/out_altvoltage1_TX_LO_powerdown') != '1':
            raise RuntimeError('本地板卡正在发射，拒绝接管')
        self.check_cancel()
        self.event('identity', identity=self.radio.info)
        if self.role == 'sender':
            self.transaction = self.transaction_factory(self)
            self.event('connected', channel='control', source=self.radio.info,
                       next_sequence=self.transaction.sequence_pool.next_available())
        self._resume_receive()

    def _resume_receive(self):
        self.check_cancel()
        self.settings = self.radio.configure_business(self.tx_center, self.rx_center,
                                                       2 if self.role == 'sender' else 1)
        self.settings.update(requested_tx_center_hz=round(float(self.tx_center)*1e6),
                             requested_rx_center_hz=round(float(self.rx_center)*1e6))
        self.event('settings', values=dict(self.settings))
        self.check_cancel()
        self.radio.start_receive()
        self.rx_active = True
        self.last_samples = None
        self.last_progress = time.monotonic()
        self.receive_rate_anchor = None
        self.last_frame_count = self.last_reject_count = 0
        self.status('receiving', '自动接收中，可随时发送文本')

    def _apply_local_plan(self, tx_center, rx_center):
        previous = (float(self.tx_center), float(self.rx_center))
        self.set_plan(tx_center, rx_center)
        if not self.radio:
            raise RuntimeError('本地终端未连接')
        if not self.rx_active or previous != (self.tx_center, self.rx_center):
            self._retry_pending('本机频率已变更，待发文本保留，请手动重试')
            self.status('busy', '正在应用本机频率，暂歇收发')
            self._stop_tx()
            self.radio.stop_receive()
            self.rx_active = False
            self._resume_receive()
        self.event('local_plan_applied', tx_center=self.tx_center, rx_center=self.rx_center)

    def _stop_tx(self):
        if self.radio:
            self.radio.stop()
        self.tx_active = False
        self.state('发送已停止，接收保持运行' if self.rx_active else '发送已停止')

    def _recover_receive(self, cause):
        self.check_cancel()
        now = time.monotonic()
        if self.last_receive_recovery is not None and now-self.last_receive_recovery < 60:
            raise RuntimeError('接收恢复后再次退出，已停止自动恢复：'+str(cause))
        self.last_receive_recovery = now
        self.status('busy', '正在恢复本地接收，请稍候')
        self.record(kind='receive_recovery', reason=str(cause))
        # These methods recheck USB, boot and pinned ownership before writes.
        # Failure never reconnects another board or resumes a previous TX.
        self._stop_tx()
        self.radio.stop_receive()
        self.rx_active = False
        self.check_cancel()
        self._resume_receive()
        self.radio.verify_stream()
        self.record(kind='receive_recovered', old_transmit_resumed=False)

    def _ensure_receive_ready(self):
        self.check_cancel()
        if not self.radio:
            raise RuntimeError('本地终端未连接，请选择板卡并连接')
        try:
            self.radio.verify_stream()
        except ReceiveUnavailable as exc:
            self._recover_receive(exc)

    def _send(self, text, request_id=None):
        if not self.radio or not self.rx_active or self.tc_active:
            raise RuntimeError('终端尚未就绪')
        self._ensure_receive_ready()
        if self.sequence > 65535:
            self.session, self.sequence = new_session_id(), 0
        encode_message(text, self.session, self.sequence)
        self._stop_tx()
        seq = self.sequence
        self.sequence += 1
        message_id = f'{self.session}:{seq:04x}'
        if request_id is not None:
            with self.job_lock:
                self.jobs[request_id]['message_id'] = message_id
        self.check_cancel()
        self.status('busy', '准备发送文本；板端接收持续运行')
        manifest = self.radio.prepare_message(text, self.session, seq, 55, self.check_cancel,
                                              tx_rf_mhz=self.tx_center)
        self.check_cancel()
        self.radio.start()
        self.check_cancel()
        self.radio.verify_stream()
        if not self.radio.verify_transmit():
            raise RuntimeError('发送未进入有效保护状态')
        self.tx_active = True
        self.tx_started_at = time.monotonic()
        self.event('tx', message_id=message_id, request_id=request_id, text=text,
                   payload_bytes=len(text.encode('utf-8')),
                   receiver_process=getattr(self.radio, 'stream_owner', None))
        self.record(kind='tx_manifest', manifest=manifest)
        self.status('transmitting', '正在发送，同时接收；本次发送最多30秒')

    def _telecontrol(self, requested, wiring_confirmed=False):
        if self.role != 'sender' or not self.radio:
            raise RuntimeError('测控需要已连接的终端1')
        self._ensure_receive_ready()
        self.tc_active = True
        self.tc_result = None
        self.tc_result_at = 0
        release_reason = '测控未成功完成或已取消，请手动重试'
        self.status('paused', '测控占用中，业务接收将在结束后恢复')
        try:
            self._stop_tx()
            self.radio.stop_receive(); self.rx_active = False
            self.state('业务接收已暂停，正在执行测控')
            self.check_cancel()
            self.radio.business_mode = False
            self.radio.tx_channel = 2
            self.transaction._send(requested, wiring_confirmed=wiring_confirmed)
            release_reason = self._tc_queue_block_reason()
        finally:
            cleanup = []
            for operation in (self.radio.finish_capture, self.radio.stop):
                try: operation()
                except Exception as exc: cleanup.append(str(exc))
            self.radio.business_mode = True
            self.radio.tx_channel = 1
            self.tc_active = False
            if release_reason or self.interrupt.is_set() or cleanup:
                self._retry_pending(release_reason or '测控已取消或清理未确认，请手动重试')
            if cleanup:
                raise RuntimeError('测控清理未确认：'+'；'.join(cleanup))
            # Urgent close/disconnect owns the next transition. Cancellation is
            # handled by the urgent branch before RX is restored.
            if not self.interrupt.is_set():
                self._resume_receive()
                # Local reconfiguration can consume the remaining remote lease.
                reason = self._tc_queue_block_reason()
                if reason: self._retry_pending(reason)

    def _tc_queue_block_reason(self):
        result = self.tc_result
        if not result or result.get('passed') is not True or result.get('matched') is not True:
            return '测控未确认成功，待发文本保留，请手动重试'
        operation = result.get('requested', {}).get('operation', 'frequency')
        relay = result.get('relay', {})
        remaining = relay.get('remaining_lower_bound_ms', 0)
        if (operation not in ('enable', 'status') or relay.get('valid') is not True
                or relay.get('mode') != 1 or relay.get('lease_active') is not True
                or relay.get('mute_fault') or type(remaining) not in (int, float)
                or not math.isfinite(remaining)
                or remaining <= (time.monotonic()-self.tc_result_at)*1000):
            return '远端转发未开启或有效租期未确认，请开启转发后手动重试'
        ack = result.get('ack', {})
        expected = (round(float(self.tx_center)*1e6)-500000,
                    round(float(self.rx_center)*1e6)-500000)
        if not isinstance(ack, dict) or any(type(ack.get(key)) is not int or
                abs(ack[key]-value)>10 for key, value in zip(('rx_hz', 'tx_hz'), expected)):
            return '本机频率与远端转发回报未匹配，请应用本机频率后手动重试'
        return None

    def _check_receive_rate(self, samples, uptime):
        # Measure progress between board snapshots. Startup, FIFO opening and
        # initial filter fill must not depress every later cumulative average.
        if self.receive_rate_anchor is None:
            self.receive_rate_anchor = (samples, uptime)
            return
        previous_samples, previous_uptime = self.receive_rate_anchor
        if uptime < previous_uptime:
            raise RuntimeError('板端采样时间回退，接收会话已失效')
        elapsed = uptime-previous_uptime
        if elapsed >= 3000:
            if (samples-previous_samples)*1000/elapsed < 2300000:
                raise RuntimeError('板端解码吞吐不足，不能标记为持续接收')
            self.receive_rate_anchor = (samples, uptime)

    def _poll(self):
        if not self.radio or not self.rx_active:
            return
        if time.monotonic()-self.last_poll < self.poll_seconds:
            return
        self.last_poll = time.monotonic()
        if self.tx_active and not self.radio.verify_transmit():
            self._stop_tx()
        try:
            result = self.radio.poll_receive()
        except ReceiveUnavailable as exc:
            self._recover_receive(exc)
            return
        if result is None:
            if time.monotonic()-self.last_progress > 12:
                raise RuntimeError('板端接收统计未出现')
            return
        status, frames = result
        if not isinstance(status, dict) or not isinstance(frames, list) or len(frames)>128:
            raise ValueError('板端接收报告结构异常')
        if status.get('input_error') or status.get('stopped') or status.get('eof'):
            raise RuntimeError('板端采样程序已停止或输入异常')
        samples = status['samples']
        if type(samples) is not int or samples < 0 or (self.last_samples is not None and samples < self.last_samples):
            raise ValueError('板端采样计数回退或无效')
        uptime = status.get('uptime_ms', 0)
        if not math.isfinite(uptime) or uptime < 0:
            raise ValueError('板端采样时间无效')
        self._check_receive_rate(samples, uptime)
        if samples != self.last_samples:
            self.last_samples, self.last_progress = samples, time.monotonic()
        elif time.monotonic()-self.last_progress > 8:
            raise RuntimeError('板端采样进度停止，不能继续显示接收中')
        messages = []
        for frame in frames:
            payload = bytes.fromhex(frame['payload_hex'])
            if _link.crc16(payload) != frame['crc16']:
                raise ValueError('板端消息CRC复核失败')
            try:
                message = parse_message(payload.decode('utf-8', errors='strict'))
            except (UnicodeError, ValueError):
                continue
            observed = self.tracker.observe(message)
            if observed == 'conflict':
                self.event('log', level='error', message='拒绝同一消息编号的冲突内容')
            elif observed == 'new':
                messages.append(dict(message, duplicate=False, crc_valid=True, crc16=frame['crc16']))
        rms = status.get('recent_rms', status.get('rms', 0))
        if not math.isfinite(rms) or rms < 0 or status.get('clips', 0) or rms > 1000:
            raise RuntimeError('接收削顶或超出已验证电平范围')
        counts, rejects = status.get('frames', 0), status.get('rejects', 0)
        carrier = (self.settings['rx_lo_hz_readback']+frames[-1]['carrier_offset_hz']) if messages else None
        self.event('rx', messages=messages, valid_frames=max(0, counts-self.last_frame_count),
                   crc_rejected=max(0, rejects-self.last_reject_count), rms_codes=rms,
                   carrier_hz=carrier, spectrum=dict(freq_mhz=[], dbfs=[]),
                   capture_seconds=self.poll_seconds, received_at=time.time(),
                   capture_file='', continuous=True, stream_status=status)
        self.last_frame_count, self.last_reject_count = counts, rejects

    def _disconnect(self):
        self._retry_pending('连接已断开，请连接后手动重试')
        errors = []
        if self.radio:
            for operation in (self.radio.stop, self.radio.stop_receive, self.radio.finish_capture, self.radio.close):
                try:
                    operation()
                except Exception as exc:
                    self.discard_pending()
                    errors.append(str(exc))
        self.radio = None
        self.transaction = None
        self.rx_active = self.tx_active = self.tc_active = False
        if self.lease:
            self.lease.close(); self.lease = None
        if errors:
            raise RuntimeError('清理未完全确认：'+'；'.join(errors))

    def _work(self):
        try:
            self.status('disconnected', '未连接')
            while not self.closing:
                action = None
                try:
                    if not self.interrupt.is_set() and self.urgent.empty():
                        self._poll()
                    try:
                        action, values = self.urgent.get_nowait()
                        while not self.commands.empty():
                            try:
                                dropped, _ = self.commands.get_nowait()
                                if dropped == 'apply_plan':
                                    self.event('local_plan_cancelled')
                            except queue.Empty: break
                    except queue.Empty:
                        try: action, values = self.commands.get(timeout=.1)
                        except queue.Empty:
                            self._poll()
                            self._dispatch_next()
                            continue
                    if action in ('close', 'disconnect'):
                        self._disconnect()
                        self.closing = action == 'close'
                        if not self.closing: self.status('disconnected', '已断开')
                    elif action in ('stop_tx', 'cancel_tc'):
                        self._retry_pending('发送已停止或测控已取消，请手动重试')
                        self._stop_tx()
                        if self.urgent.empty(): self.interrupt.clear()
                        if self.radio and not self.rx_active and not self.interrupt.is_set():
                            self._resume_receive()
                        if action == 'cancel_tc':
                            self.event('status', channel='control', state='error', category='cancelled',
                                       message='测控已取消；业务接收已恢复，未重发旧文本。远端执行结果未知。')
                            self.state('测控已取消，业务接收已恢复')
                    else:
                        self.check_cancel()
                        if action == 'connect': self._connect(**values)
                        elif action == 'telecontrol': self._telecontrol(**values)
                        elif action == 'apply_plan':
                            self._apply_local_plan(**values)
                        else: raise ValueError('未知终端操作')
                except Cancelled:
                    if action == 'apply_plan':
                        self.event('local_plan_cancelled')
                    self._retry_pending('操作已取消，请手动重试')
                    # The urgent action clears stale queued sends and restores
                    # only RX, or disconnects. Never retry a TX automatically.
                    self.status('paused', '操作取消中')
                except Exception as exc:
                    self._retry_pending('操作失败，请手动重试：'+str(exc))
                    self.discard_pending()
                    if action == 'telecontrol' and self.radio and self.rx_active:
                        self.event('status', channel='control', state='error', message=str(exc),
                                   category='timeout' if isinstance(exc, TimeoutError) else 'hardware')
                        self.state('测控未确认；已恢复原业务接收计划')
                    else:
                        cleanup = ''
                        try: self._disconnect()
                        except Exception as err: cleanup = '；'+str(err)
                        self.status('error', str(exc)+cleanup)
                        if action == 'close': self.closing = True
                finally:
                    if action in ('close', 'disconnect', 'cancel_tc', 'stop_tx') and self.urgent.empty():
                        self.interrupt.clear()
        finally:
            try: self._disconnect()
            except Exception as exc: self.event('log', level='error', message=str(exc))
            self.closing = True
            self.event('status', state='closed', message='终端后台已关闭')
            with self.event_lock:
                self.journal.close()
