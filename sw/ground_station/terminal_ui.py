"""Bidirectional terminal workspace backed by the shared local radio service."""
from datetime import datetime
import uuid
import tkinter as tk
from tkinter import ttk

from .ui_v2 import StationReview, BG, PAPER, INK, MUTED, LINE, TEAL, BLUE, card, label, button
from .ui_v2_model import text_bytes
from .rf_profiles import business_center_hz, DEMO_TX_CENTERS, DEMO_RX_CENTERS


class TrafficHistory(ttk.Treeview):
    """Keep existing record fields; direction comes from the local RX/TX event."""
    def __init__(self, parent, page, **kwargs):
        self.page = page
        super().__init__(parent, **kwargs)
        self.tag_configure('sent', foreground=BLUE)
        self.tag_configure('received', foreground=TEAL)

    def insert(self, parent, index, iid=None, **kwargs):
        values = list(kwargs.get('values', ()))
        tag = kwargs.pop('direction', 'received')
        if tag not in ('sent', 'received'):
            raise ValueError('history direction must be sent or received')
        if len(values) == 4:
            values[3] = self._prefix(tag, values[3])
            kwargs['values'] = values
        kwargs['tags'] = (tag,)
        return super().insert(parent, index, iid, **kwargs)

    @staticmethod
    def _prefix(tag, text):
        return ('↑ 发出 · ' if tag == 'sent' else '↓ 实收 · ') + str(text)

    def set(self, item, column=None, value=None):
        if column == 'status' and value is not None:
            tags = self.item(item, 'tags')
            value = self._prefix('sent' if 'sent' in tags else 'received', value)
        return super().set(item, column, value)


class TerminalReview(StationReview):
    combined_terminal = True

    def __init__(self, session, role):
        self.received_ids = set()
        self.tx_requests = {}
        self.last_business_error = None
        self.business_issue_kind = None
        self.rx_active = self.tx_active = self.tc_active = False
        self.rx_health = 'warming'
        self.local_apply_pending = False
        self.local_applied = None
        super().__init__(session, role)
        self.update_business_controls()

    def _build_details(self):
        label(self.details, '连接后持续自动接收；发送文本期间保持接收，测控结束后自动恢复业务。',
              color=MUTED, size=9).pack(anchor='w', pady=(8, 0))
        label(self.details, '本机 TX 本振 = 发送中心 − 0.5 MHz；RX 本振 = 接收中心 + 0.25 MHz。',
              color=MUTED, size=9).pack(anchor='w', pady=(6, 0))

    def _build_sender(self):
        self._build_terminal()

    def _build_receiver(self):
        self._build_terminal()

    def _build_terminal(self):
        peer = '终端2' if self.role == 'sender' else '终端1'
        self.body.columnconfigure(0, weight=1, uniform='terminal')
        self.body.columnconfigure(1, weight=1, uniform='terminal')
        self.body.rowconfigure(2, weight=1)
        self.local_tx_center = tk.StringVar(self.window, DEMO_TX_CENTERS[0])
        self.local_rx_center = tk.StringVar(self.window, DEMO_RX_CENTERS[0])
        self.local_plan_note = tk.StringVar(self.window, '连接时应用本机频率；不会修改转发板或另一终端。')
        self.business_note = tk.StringVar(self.window, '连接本地板卡后自动接收，可随时发送文本。')
        self.mode_label = tk.StringVar(self.window, '未连接')
        self.sender_frequency = tk.StringVar(self.window, '—')
        self.sender_readback = tk.StringVar(self.window, '本地 TX LO 尚未回读')
        self.receiver_frequency = tk.StringVar(self.window, '—')
        self.receiver_plan_note = tk.StringVar(self.window, '本地 RX LO 尚未回读')
        self.carrier_frequency = tk.StringVar(self.window, '—')
        self.sent_count = tk.StringVar(self.window, '已发 0 条')
        self.received_count = tk.StringVar(self.window, '实收 0 条')
        ttk.Style(self.window).configure('V2.LocalFrequency.TEntry', padding=(8, 6),
            bordercolor=LINE, fieldbackground='#F8FAFC', foreground=INK)
        for col, title, variable, readback, draft, bounds in (
                (0, '↑  本机发送中心', self.sender_frequency, self.sender_readback,
                 self.local_tx_center, '1980.100–2009.900 MHz'),
                (1, '↓  本机接收中心', self.receiver_frequency, self.receiver_plan_note,
                 self.local_rx_center, '2170.100–2199.900 MHz')):
            pane = card(self.body, title, padding=10)
            pane.edge.grid(row=0, column=col, sticky='nsew', padx=(0, 7) if col == 0 else (7, 0), pady=(0, 8))
            row = tk.Frame(pane, bg=PAPER)
            row.pack(fill='x')
            entry = ttk.Entry(row, textvariable=draft, style='V2.LocalFrequency.TEntry',
                              width=14, font=('Segoe UI', 18))
            entry.pack(side='left', fill='x', expand=True, padx=(0, 10))
            label(row, 'MHz', size=16, color=BLUE if col == 0 else TEAL, bold=True).pack(side='right')
            label(pane, bounds+'  ·  步进 0.001', size=9, color=MUTED).pack(anchor='w', pady=(6, 6))
            actual = tk.Frame(pane, bg=PAPER)
            actual.pack(fill='x')
            label(actual, '已应用  ', size=10, color=MUTED).pack(side='left')
            label(actual, variable=variable, size=12, bold=True, color=BLUE if col == 0 else TEAL).pack(side='left')
            label(actual, ' MHz', size=10, color=MUTED).pack(side='left')
            label(actual, variable=readback, size=9, color=MUTED).pack(side='right')

        plan_bar = tk.Frame(self.body, bg=BG)
        plan_bar.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(0, 6))
        self.local_apply_button = button(plan_bar, '应用本机频率', self.apply_local_frequency,
                                         primary=True, disabled=True)
        self.local_apply_button.pack(side='right', padx=(12, 0))
        self.local_note_label = label(plan_bar, variable=self.local_plan_note, size=10, color=MUTED, wrap=700, bg=BG)
        self.local_note_label.pack(side='left', fill='x', expand=True)
        self.local_tx_center.trace_add('write', self._local_frequency_changed)
        self.local_rx_center.trace_add('write', self._local_frequency_changed)

        compose = card(self.body, '发送给'+peer, padding=14)
        compose.edge.grid(row=2, column=0, sticky='nsew', padx=(0, 7), pady=(0, 12))
        field = tk.Frame(compose, bg='#F8FAFC', highlightbackground=LINE, highlightthickness=1)
        field.pack(fill='both', expand=True, pady=(8, 10))
        self.message_input = tk.Text(field, wrap='word', height=4, bd=0, padx=14, pady=14,
            bg='#F8FAFC', fg=INK, insertbackground=TEAL, font=('Microsoft YaHei UI', 17), undo=True)
        self.message_input.pack(fill='both', expand=True)
        self.placeholder = label(field, '输入要发送的文本…', size=17, color='#9AA8B7', bg='#F8FAFC')
        self.placeholder.place(x=16, y=16)
        self.placeholder.bind('<Button-1>', lambda _e: self.message_input.focus_set())
        self.message_input.bind('<<Modified>>', self._text_changed)
        toolbar = tk.Frame(compose, bg=PAPER)
        toolbar.pack(side='bottom', fill='x', before=field)
        self.byte_count = tk.StringVar(self.window, '0 / 32 字节')
        self.byte_label = label(toolbar, variable=self.byte_count, color=MUTED, size=9)
        self.byte_label.pack(side='left')
        self.send_button = button(toolbar, '发送文本', self.send_business, primary=True, disabled=True)
        self.send_button.pack(side='right')
        button(toolbar, '清空', lambda: self.message_input.delete('1.0', 'end')).pack(side='right', padx=6)

        received = card(self.body, '来自'+peer, padding=14)
        received.edge.grid(row=2, column=1, sticky='nsew', padx=(7, 0), pady=(0, 12))
        text_box = tk.Frame(received, bg='#F0F8F6', padx=14, pady=12)
        text_box.pack(fill='both', expand=True, pady=(8, 8))
        self.received_text = tk.StringVar(self.window, '等待接收文本')
        self.received_hero = label(text_box, variable=self.received_text, size=18, color='#9BADA9', bg='#F0F8F6', wrap=420)
        self.received_hero.pack(fill='both', expand=True)
        self.received_hero.bind('<Configure>', lambda event: self.received_hero.configure(wraplength=max(100, event.width-8)))
        receive_status = tk.Frame(received, bg=PAPER)
        receive_status.pack(side='bottom', fill='x', before=text_box)
        self.received_meta = tk.StringVar(self.window, '尚无实际接收结果')
        self.received_meta_label = label(receive_status, variable=self.received_meta, size=9, color=MUTED, wrap=450)
        self.received_meta_label.pack(anchor='w')
        carrier = tk.Frame(receive_status, bg=PAPER)
        carrier.pack(fill='x', pady=(3, 0))
        label(carrier, '实测载频  ', size=9, color=MUTED).pack(side='left')
        label(carrier, variable=self.carrier_frequency, size=10, color=TEAL, bold=True).pack(side='left')
        label(carrier, '  MHz', size=9, color=MUTED).pack(side='left')
        from .app import SpectrumCanvas
        self.spectrum = SpectrumCanvas(self.details)
        self.spectrum.configure(height=80)
        self.spectrum.pack(fill='x', pady=(6, 4))
        self.frame_stats = tk.StringVar(self.window, '有效帧 — / CRC候选拒绝 —')
        self.capture_note = tk.StringVar(self.window, '尚未采集')
        self.frame_stats_label = label(receive_status, variable=self.frame_stats, size=9, color=MUTED, wrap=450)
        self.frame_stats_label.pack(anchor='w')
        controls = tk.Frame(receive_status, bg=PAPER)
        controls.pack(fill='x', pady=(6, 0))
        label(controls, variable=self.capture_note, size=9, color=MUTED).pack(side='left')
        label(controls, '连接后自动接收', color=TEAL, size=9).pack(side='right')

        strip = tk.Frame(self.body, bg=BG)
        strip.grid(row=3, column=0, columnspan=2, sticky='ew', pady=(0, 10))
        label(strip, variable=self.mode_label, color=TEAL, bold=True, bg=BG).pack(side='left')
        label(strip, variable=self.sent_count, color=BLUE, bg=BG).pack(side='left', padx=(22, 12))
        label(strip, variable=self.received_count, color=TEAL, bg=BG).pack(side='left')
        self.business_stop_button = button(strip, '停止发送', self.stop_business, disabled=True)
        self.business_stop_button.pack(side='right')
        self.retry_button = button(strip, '重试选中', self.retry_selected, disabled=True)
        self.retry_button.pack(side='right', padx=8)
        self.resume_rx_button = button(strip, '恢复接收', self.resume_receive, disabled=True)
        self.history_card = card(self.body, '通信记录', padding=12)
        self.history_card.edge.grid(row=4, column=0, columnspan=2, sticky='nsew')
        self.history = TrafficHistory(self.history_card, self, columns=('time', 'id', 'content', 'status'),
            displaycolumns=('time', 'status', 'content', 'id'), show='headings', style='V2.Treeview', height=1)
        for key, title, width in (('time','时间',80), ('id','消息编号',140), ('content','文本内容',360), ('status','方向 / 状态',240)):
            self.history.heading(key, text=title)
            self.history.column(key, width=width, minwidth=60, stretch=key=='content')
        scrollbar = ttk.Scrollbar(self.history_card, orient='vertical', command=self.history.yview)
        self.history.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.history.pack(fill='both', expand=True)
        self.history.bind('<<TreeviewSelect>>', lambda _event: self.update_business_controls())

    def remember_transmit_plan(self, center):
        # A control result is a plan; actual frequency remains the backend readback.
        if not self.closed and not self.closing:
            self.business_note.set(f'远端已确认输入中心 {center} MHz；本机频率保持原设置。')

    def _local_values(self):
        return (business_center_hz('sender', self.local_tx_center.get()),
                business_center_hz('receiver', self.local_rx_center.get()))

    def _local_frequency_changed(self, *_):
        if hasattr(self, 'send_button'):
            self.update_business_controls()

    def apply_local_frequency(self):
        if (not self.business_online or not self.local_claimed or self.tc_active or
                self.local_apply_pending or self.cancel_pending or self.closing):
            return
        try:
            tx, rx = self._local_values()
        except ValueError as error:
            self.local_plan_note.set(str(error))
            return
        self.local_apply_pending = True
        try:
            self.controller.submit('apply_plan', tx_center=tx/1e6, rx_center=rx/1e6)
        except Exception as error:
            self.local_apply_pending = False
            self.business_note.set('本机频率未提交：'+str(error))
            self._show_business_issue(self.business_note.get(), 'configuration')
        else:
            self._clear_business_issue('configuration')
        self.update_business_controls()

    def _show_business_issue(self, message, kind='submission'):
        self.business_issue_kind = kind
        self.connection_issue.set(str(message))
        self.connection_issue_label.pack(fill='x', pady=(6, 0))

    def _clear_business_issue(self, kind=None):
        if kind is not None and self.business_issue_kind != kind:
            return
        self.business_issue_kind = None
        self.connection_issue.set('')
        self.connection_issue_label.pack_forget()

    def _business_submit(self, action, **kwargs):
        accepted = super()._business_submit(action, **kwargs)
        if not accepted:
            self._show_business_issue(self.business_note.get())
        return accepted

    def _start_business(self):
        try:
            self.controller = self.session.terminal_controller(self.role, self.events.put)
        except Exception as error:
            self._business_released(f'通信服务启动失败：{error}', 'error')
        else:
            self._poll_id = self.window.after(60, self._drain_online_events)
        self.update_business_controls()

    def update_business_controls(self):
        if not hasattr(self, 'business_note') or self.closed:
            return
        available = self.business_online and not self.closing and self.controller is not None
        connected = available and self.local_claimed and self.online_state not in ('connecting', 'disconnected', 'error')
        try:
            local_values = self._local_values()
            local_valid = True
            local_dirty = local_values != self.local_applied
        except ValueError as error:
            local_valid, local_dirty = False, True
            self.local_plan_note.set(str(error))
        if local_valid:
            self.local_plan_note.set('正在应用本机频率，请稍候。' if self.local_apply_pending else
                '测控占用中；结束后恢复本机原频率。' if self.tc_active else
                '修改尚未应用；请先应用本机频率。' if connected and local_dirty else
                '本机频率已应用；接收已暂停，请先恢复接收。' if connected and self.rx_health == 'suspended' else
                '本机频率已应用；接收已启动，发送需点击“发送文本”。' if connected else
                '连接时应用本机频率；不会修改转发板或另一终端。')
        self.local_note_label.configure(fg='#8E671D' if connected and local_dirty else MUTED)
        self.local_apply_button.configure(state='normal' if connected and local_valid and local_dirty
            and not self.local_apply_pending and not self.tc_active and not self.cancel_pending else 'disabled')
        text = self.message_input.get('1.0', 'end-1c')
        valid_text = bool(text) and len(text.encode('utf-8')) <= 32
        self.send_button.configure(state='normal' if connected and self.business_configured and valid_text
                                   and self.rx_health not in ('suspended', 'recovering')
                                   and not local_dirty and not self.local_apply_pending
                                   and not self.cancel_pending else 'disabled',
                                   text='排队发送' if self.tc_active else '发送文本')
        self.retry_button.configure(state='normal' if connected and self.business_configured
                                    and self.rx_health not in ('suspended', 'recovering')
                                    and not local_dirty and not self.local_apply_pending
                                    and not self.cancel_pending and self._selected_retry_request() else 'disabled')
        self.business_stop_button.configure(state='normal' if connected and self.tx_active
                                             and not self.cancel_pending else 'disabled')
        if self.rx_health == 'suspended' and connected:
            self.resume_rx_button.pack(side='right', padx=8)
            self.resume_rx_button.configure(state='normal' if not self.tc_active else 'disabled')
        else:
            self.resume_rx_button.pack_forget()
        self.connect_button.configure(text='断开' if self.local_claimed else '连接',
            state='normal' if available and not self.cancel_pending and self.business_pending != 'connect'
            and (self.local_claimed or self.selection.get() in self.session.devices) else 'disabled')
        self.port_combo.configure(state='disabled' if self.local_claimed or self.closing else 'readonly')
        self.refresh_button.configure(state='disabled' if self.closing else 'normal')
        if not self.business_online:
            self.mode_label.set('离线界面预览 · 未连接设备')

    def connect_business(self):
        if not self.business_online or self.closing or self.cancel_pending or self.controller is None:
            return
        if self.local_claimed:
            self.stop_business('disconnect')
            return
        device = self.session.devices.get(self.selection.get())
        if not device:
            return
        try:
            tx, rx = self._local_values()
        except ValueError as error:
            self.local_plan_note.set(str(error))
            return
        self.last_business_error = None
        self._clear_business_issue()
        self.local_claimed = self.accept_connected = True
        self.connecting_port = device['port']
        self.business_pending = 'connect'
        self.business_configured = False
        self.online_state = 'connecting'
        self.connection_status.set('●  正在连接')
        self.mode_label.set('正在连接 · 完成后自动接收')
        self.business_note.set('正在连接与配置本地板卡，完成后自动接收。')
        self._business_submit('connect', port=self.connecting_port, tx_center=tx/1e6, rx_center=rx/1e6)
        self.session.update_online_controls()

    def send_business(self):
        if (not self.business_online or self.closing or self.cancel_pending or not self.local_claimed
                or not self.business_configured or self.local_apply_pending
                or self.online_state in ('connecting', 'disconnected', 'error')):
            return
        try:
            if self._local_values() != self.local_applied:
                return
        except ValueError:
            return
        text = self.message_input.get('1.0', 'end-1c')
        try:
            text_bytes(text)
        except ValueError as error:
            self.business_note.set(str(error))
            self._show_business_issue(str(error))
            return
        request_id = uuid.uuid4().hex
        try:
            accepted_id = self.controller.submit('send', text=text, request_id=request_id)
        except Exception as error:
            self.business_note.set('未加入发送队列：'+(str(error) or type(error).__name__))
            self._show_business_issue(self.business_note.get())
        else:
            self._clear_business_issue('submission')
            request_id = accepted_id if isinstance(accepted_id, str) and accepted_id else request_id
            self._update_tx_queue(dict(request_id=request_id, text=text, state='queued'))
            self.business_note.set('已加入发送队列；测控确认转发可用且恢复接收后按顺序发送。' if self.tc_active else '已加入发送队列。')
        self.session.update_online_controls()

    def _selected_retry_request(self):
        if not hasattr(self, 'history'):
            return None
        selected = self.history.selection()
        if len(selected) != 1:
            return None
        return next((request_id for request_id, entry in self.tx_requests.items()
                     if entry['row'] == selected[0] and entry['state'] == 'retry'), None)

    def retry_selected(self):
        request_id = self._selected_retry_request()
        if (not request_id or not self.business_online or self.closing or self.cancel_pending
                or not self.local_claimed or not self.business_configured or self.controller is None
                or self.local_apply_pending):
            return
        try:
            if self._local_values() != self.local_applied:
                return
        except ValueError:
            return
        try:
            self.controller.submit('retry', request_id=request_id)
        except Exception as error:
            self.business_note.set('重试未提交：'+(str(error) or type(error).__name__))
            self._show_business_issue(self.business_note.get())
        else:
            self._clear_business_issue('submission')
            entry = self.tx_requests[request_id]
            self._update_tx_queue(dict(request_id=request_id, text=entry['text'], state='queued'))
            self.business_note.set('选中记录已重新加入发送队列。')
        self.session.update_online_controls()

    def resume_receive(self):
        if self.local_claimed and self.rx_health == 'suspended' and not self.tc_active:
            if self._business_submit('resume_rx'):
                self.rx_health = 'recovering'
                self._show_activity()
            self.session.update_online_controls()

    def _update_tx_queue(self, event):
        request_id, text, state = event.get('request_id'), event.get('text'), event.get('state')
        if (not isinstance(request_id, str) or not isinstance(text, str)
                or state not in ('queued', 'sending', 'sent', 'retry')):
            return
        entry = self.tx_requests.get(request_id)
        if entry is not None and entry['state'] == 'sent':
            return  # An already sent request is never put back into the queue.
        status = dict(queued='排队中', sending='发送中', sent='已发送', retry='待重试')[state]
        message_id = event.get('message_id')
        if entry is None:
            row = self.history.insert('', 0, direction='sent', values=(datetime.now().strftime('%H:%M:%S'),
                message_id or request_id, text, status))
            entry = self.tx_requests[request_id] = dict(row=row, text=text, state=state)
        else:
            self.history.set(entry['row'], 'status', status)
            if message_id:
                self.history.set(entry['row'], 'id', message_id)
            entry['state'] = state
        if state == 'sent' and isinstance(message_id, str):
            self.business_tx_ids.add(message_id)
        if state == 'retry':
            self.business_note.set('待发送记录保留，选中后点击“重试选中”。'+str(event.get('reason') or ''))
        self.sent_count.set(f'已发 {len(self.business_tx_ids)} 条')

    def stop_business(self, action='stop_tx'):
        if not self.business_online or self.closing or self.controller is None or not self.local_claimed:
            return
        action = 'stop_tx' if action == 'stop' else action
        if action not in ('stop_tx', 'disconnect'):
            return
        if action == 'disconnect':
            self.cancel_pending = True
            self.business_pending = action
            self.connection_status.set('●  正在断开')
        self._business_submit(action)
        self.session.update_online_controls()

    def close_business(self):
        if self.closing:
            return
        self.closing = True
        if self.controller is None:
            self.session._destroy_page(self.role)
            return
        self._business_submit('close')
        self.session.update_online_controls()

    def _clear_business_readback(self):
        self.sender_frequency.set('—')
        self.receiver_frequency.set('—')
        self.sender_readback.set('本地 TX LO 尚未回读')
        self.receiver_plan_note.set('本地 RX LO 尚未回读')
        self.carrier_frequency.set('—')
        self.spectrum.set_spectrum(None)

    def _business_released(self, message, state='disconnected'):
        if state == 'error':
            self.last_business_error = str(message)
        elif self.last_business_error is not None:
            # Cleanup often reports disconnected after the actual failure.
            # Keep its cause visible until a new connection attempt or success.
            state, message = 'error', self.last_business_error
        if state == 'error':
            self._show_business_issue(str(message), 'connection')
        self.local_claimed = self.accept_connected = self.cancel_pending = False
        self.rx_active = self.tx_active = self.tc_active = False
        self.online_identity = self.connecting_port = None
        self.business_configured = False
        self.local_apply_pending = False
        self.local_applied = None
        self.business_pending = None
        self.online_state = state
        self.connection_status.set('●  连接异常' if state == 'error' else '●  未连接')
        self.mode_label.set('连接异常' if state == 'error' else '未连接')
        self.capture_note.set('接收已断开 · 历史记录保留')
        self.business_note.set(str(message))
        self._clear_business_readback()
        self.update_details()

    def _handle_business_event(self, event):
        if self.closed:
            return
        kind = event.get('type')
        if kind == 'closed' or kind == 'status' and event.get('state') == 'closed':
            # A facade close detaches this page; the session owns the radio.
            if self.closing:
                self.controller = None
                self.session._destroy_page(self.role)
                self.session.update_online_controls()
            return
        if self.closing:
            return
        if kind == 'identity':
            identity = event.get('identity')
            device = self.session.devices.get(self.selection.get())
            if (not isinstance(identity, dict) or not device or identity.get('port') != device['port']
                    or self.connecting_port and identity.get('port') != self.connecting_port):
                return
            self.online_identity = dict(identity)
            self.local_claimed = True
            self.connecting_port = identity['port']
            self.accept_connected = False
            self.update_details()
        elif kind == 'settings':
            values = event.get('values', {})
            if not isinstance(values, dict) or self.cancel_pending:
                return
            tx_lo = values.get('tx_lo_hz_readback')
            rx_lo = values.get('rx_lo_hz_readback')
            if self._finite_business(tx_lo):
                self.sender_frequency.set(f'{(tx_lo + 500_000)/1e6:.6f}')
                self.sender_readback.set(f'TX LO {tx_lo/1e6:.6f} MHz')
            if self._finite_business(rx_lo):
                self.receiver_frequency.set(f'{(rx_lo-250000)/1e6:.6f}')
                self.receiver_plan_note.set(f'RX LO 回读 {rx_lo/1e6:.6f} MHz')
            if self._finite_business(tx_lo) and self._finite_business(rx_lo):
                self.local_applied = (values.get('requested_tx_center_hz', round((tx_lo+500000)/1000)*1000),
                                      values.get('requested_rx_center_hz', round((rx_lo-250000)/1000)*1000))
            if 'configured' in values:
                self.business_configured = values['configured'] is True
            self.business_settings_seen = True
        elif kind == 'local_plan_applied':
            self.local_apply_pending = False
        elif kind == 'local_plan_cancelled':
            self.local_apply_pending = False
        elif kind == 'terminal_state':
            self.rx_active = bool(event.get('rx_active'))
            self.tx_active = bool(event.get('tx_active'))
            self.tc_active = bool(event.get('tc_active'))
            self.rx_health = event.get('rx_health', self.rx_health)
            if event.get('connected'):
                self.last_business_error = None
                self._clear_business_issue('connection')
                self.local_claimed = True
                self.business_pending = None
                if self.online_state in ('connecting', 'disconnected', 'error'):
                    self.online_state = 'receiving' if self.rx_active else 'ready'
            elif (self.accept_connected and self.business_pending == 'connect'
                    and not self.cancel_pending and self.last_business_error is None):
                # The backend is not connected yet while identity verification
                # is running; this state must not release an in-flight connect.
                pass
            else:
                self._business_released(event.get('message', '本地设备已断开'))
            if self.local_claimed and self.online_state != 'connecting':
                self._show_activity()
            if event.get('message') and self.last_business_error is None:
                self.business_note.set(str(event['message']))
        elif kind == 'status':
            state = event.get('state')
            message = str(event.get('message', state))
            if state in ('error', 'disconnected'):
                if state == 'disconnected' and self.accept_connected and not self.cancel_pending:
                    return
                self._business_released(message, state)
            else:
                self.online_state = state
                self.business_note.set(message)
                if state in ('ready', 'receiving', 'transmitting', 'paused'):
                    self.last_business_error = None
                    self._clear_business_issue('connection')
                    self.local_claimed = True
                    self.business_pending = None
                    self.cancel_pending = False
                if state == 'receiving':
                    self.rx_active, self.tx_active, self.tc_active = True, False, False
                elif state == 'transmitting':
                    self.tx_active = True
                elif state == 'paused':
                    self.rx_active = False
                if state == 'connecting':
                    self.connection_status.set('●  正在连接')
                    self.mode_label.set('正在连接 · 完成后自动接收')
                else:
                    self._show_activity()
        elif kind == 'tx_queue':
            self._update_tx_queue(event)
        elif kind == 'receive_health':
            self.rx_health = event['level']
            if self.rx_health in ('degraded', 'recovering', 'suspended'):
                self._show_business_issue(str(event.get('reason', '接收性能下降')), 'receive_health')
            else:
                self._clear_business_issue('receive_health')
            self._show_activity()
        elif kind == 'tx':
            if not self.local_claimed or self.cancel_pending:
                return
            message_id, text = event.get('message_id'), event.get('text')
            if not isinstance(message_id, str) or not isinstance(text, str):
                return
            request_id = event.get('request_id')
            if isinstance(request_id, str):
                self._update_tx_queue(dict(event, state='sent'))
            elif message_id not in self.business_tx_ids:
                self.history.insert('', 0, direction='sent', values=(datetime.now().strftime('%H:%M:%S'),
                    message_id, text, '已发送'))
            self.business_tx_ids.add(message_id)
        elif kind == 'rx':
            if not self.local_claimed or self.cancel_pending:
                return
            self._business_rx(event)
        elif kind == 'log' and event.get('level') in ('warning', 'error'):
            self.business_note.set(str(event.get('message', '')))
            self._show_business_issue(self.business_note.get(), 'diagnostic')
        self.sent_count.set(f'已发 {len(self.business_tx_ids)} 条')
        self.received_count.set(f'实收 {len(self.received_ids)} 条')
        self.session.update_online_controls()

    def _show_activity(self):
        if self.tc_active:
            text = '测控中 · 文本排队，确认转发可用后发送'
        elif self.rx_health == 'suspended':
            text = '接收已暂停 · 连接保留，需手动恢复'
        elif self.rx_health == 'recovering':
            text = '正在恢复接收 · 未重发旧文本'
        elif self.rx_health == 'degraded':
            text = '接收性能下降 · 正在观察，可能漏收'
        elif self.tx_active:
            text = '正在发送 · 自动接收保持运行' if self.rx_active else '正在发送 · 接收暂歇'
        elif self.rx_active:
            text = '正在自动接收 · 可随时发送文本'
        elif self.local_claimed:
            text = '接收暂歇 · 等待自动恢复'
        else:
            return
        self.mode_label.set(text)
        self.connection_status.set('●  已连接')
        self.capture_note.set({'suspended':'接收已暂停 · 历史记录保留',
                               'recovering':'正在恢复接收',
                               'degraded':'性能下降 · 连续性未确认',
                               'warming':'正在建立接收基线'}.get(self.rx_health,
                              '自动接收中' if self.rx_active else '接收暂歇 · 自动恢复'))

    def _business_rx(self, event):
        # The inherited renderer accepts only CRC-verified messages. Treeview
        # defaults these inserts to received, independent of the window role.
        super()._business_rx(event)
        self._show_activity()
        for message in event.get('messages', []):
            if (isinstance(message, dict) and message.get('crc_valid') is True
                    and isinstance(message.get('text'), str) and isinstance(message.get('message_id'), str)):
                self.received_ids.add(message['message_id'])
