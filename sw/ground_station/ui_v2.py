"""Three task-oriented desktop windows, offline review by default.

Run: python -m sw.ground_station.ui_v2 --all
Add --online-control to enable the control window's finite hardware transactions.
Add --online-business for local text TX/RX. PC1 roles require an explicit handoff.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import math
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from .ui_v2_model import (command_request, device_choices, format_mhz, frequency_plan,
                         load_device_aliases, load_historical_transaction, simulated_reply, text_bytes)


BG = '#F4F6F8'
PAPER = '#FFFFFF'
INK = '#18324A'
MUTED = '#728195'
LINE = '#E1E7EE'
TEAL = '#087E87'
PALE = '#EAF5F3'
BLUE = '#2D64B3'
AMBER = '#8E671D'
ROLES = {
    'sender': ('电脑1 · 文本发送', '文本发送', '把一段新文本送往电脑2。', '01  /  业务发送'),
    'receiver': ('电脑2 · 文本接收', '文本接收', '查看经过外部硬件链路实际收到的内容。', '02  /  业务接收'),
    'control': ('电脑1 · 改频控制', '改频控制', '下达转发频率指令，核对执行回报。', '03  /  卫星测控'),
}


def label(parent, text='', *, variable=None, size=10, color=INK, bold=False,
          bg=PAPER, wrap=0):
    widget = tk.Label(parent, text=text, textvariable=variable, bg=bg, fg=color,
                      font=('Microsoft YaHei UI', size, 'bold' if bold else 'normal'),
                      anchor='w', justify='left', borderwidth=0, wraplength=wrap)
    return widget


def button(parent, text, command=None, *, primary=False, disabled=False):
    return ttk.Button(parent, text=text, command=command,
                      style='V2.Primary.TButton' if primary else 'V2.TButton',
                      state='disabled' if disabled else 'normal')


def card(parent, title=None, subtitle=None, padding=18):
    edge = tk.Frame(parent, bg=LINE, bd=0)
    body = tk.Frame(edge, bg=PAPER, padx=padding, pady=padding)
    body.pack(fill='both', expand=True, padx=1, pady=1)
    body.edge = edge
    if title:
        label(body, title, size=12, bold=True).pack(anchor='w', pady=(0, 5))
    if subtitle:
        label(body, subtitle, color=MUTED, size=9).pack(anchor='w', pady=(0, 8))
    return body


class ReviewSession:
    """Shares only local device selection across the two PC1 windows.

    Received text never comes from another window. Enabled windows own separate
    backends; PC1 sender/control share selection and require explicit handoff.
    """
    def __init__(self, root, port_provider=None, aliases=None, *, online_control=False,
                 controller_factory=None, log_dir=None, online_business=False,
                 business_controller_factory=None):
        self.root = root
        self.source_selection = tk.StringVar(root)
        self.receiver_selection = tk.StringVar(root)
        self.windows = {}
        self.devices = {}
        self.aliases = load_device_aliases() if aliases is None else aliases
        self.next_sequence = 0
        self.online_control = online_control
        self.online_business = online_business
        self.business_controller_factory = business_controller_factory
        self.controller_factory, self.log_dir = controller_factory, log_dir
        self.port_provider = port_provider or self._ports
        self._style()
        self.refresh_devices()

    @staticmethod
    def _ports():
        from serial.tools import list_ports
        return [dict(port=p.device, description=p.description, vid=p.vid, pid=p.pid,
                     serial=p.serial_number) for p in list_ports.comports()]

    def _style(self):
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('V2.TButton', font=('Microsoft YaHei UI', 10),
                        padding=(15, 9), background='#EDF1F6', foreground=INK,
                        borderwidth=0, focusthickness=0)
        style.map('V2.TButton', background=[('active', '#E1E9F2'), ('disabled', '#EFF2F5')],
                  foreground=[('disabled', '#A1ADBA')])
        style.configure('V2.Primary.TButton', background=TEAL, foreground='white')
        style.map('V2.Primary.TButton', background=[('active', '#076972'), ('disabled', '#C7DDDF')],
                  foreground=[('disabled', '#F8FBFC')])
        style.configure('V2.TCombobox', padding=8, font=('Microsoft YaHei UI', 10),
                        fieldbackground=PAPER, background=PAPER, bordercolor=LINE)
        style.map('V2.TCombobox', fieldbackground=[('readonly', PAPER)],
                  foreground=[('readonly', INK)])
        style.configure('V2.TSpinbox', padding=8, bordercolor=LINE,
                        font=('Microsoft YaHei UI', 10), fieldbackground=PAPER)
        style.configure('V2.Frequency.TEntry', padding=10, bordercolor=LINE,
                        fieldbackground='#F8FAFC', foreground=INK)
        style.configure('V2.Treeview', font=('Microsoft YaHei UI', 9), rowheight=29,
                        background=PAPER, fieldbackground=PAPER, foreground=INK,
                        borderwidth=0)
        style.configure('V2.Treeview.Heading', font=('Microsoft YaHei UI', 9, 'bold'),
                        padding=(8, 7), background='#F1F5F8', foreground=MUTED)
        style.map('V2.Treeview', background=[('selected', '#E2F1F0')],
                  foreground=[('selected', INK)])

    def refresh_devices(self):
        try:
            devices = device_choices(self.port_provider(), self.aliases)
        except Exception:
            devices = {}
        old_devices, self.devices = self.devices, devices
        for selection, role in ((self.source_selection, 'sender'), (self.receiver_selection, 'receiver')):
            old = old_devices.get(selection.get())
            matches = [name for name, device in devices.items() if device == old] if old else []
            # Initial role defaults are historical labels, not a connection or verification.
            if not old_devices and not selection.get():
                matches = [name for name, device in devices.items() if device.get('role') == role]
            selection.set(matches[0] if len(matches) == 1 else '')
        for window in self.windows.values():
            window.port_combo.configure(values=tuple(self.devices))
            window.update_details()

    def show(self, role):
        if role not in self.windows:
            self.windows[role] = StationReview(self, role)
        window = self.windows[role].window
        window.deiconify()
        window.lift()
        self.update_online_controls()
        return self.windows[role]

    def close(self, role):
        page = self.windows.get(role)
        if page is None:
            return
        if page.live and page.controller is not None:
            page.close_business() if page.business_online else page.close_online()
            return
        self._destroy_page(role)

    def _destroy_page(self, role):
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError('Tk windows must be disposed on the main thread')
        page = self.windows.pop(role)
        page.closed = True
        page.selection.trace_remove('write', page.selection_trace)
        # Window.destroy does not remove Variable traces: a callback bound to
        # page can retain a page/Variable/interpreter cycle until a worker's GC.
        for value in vars(page).values():
            if isinstance(value, tk.Variable) and value is not page.selection:
                for modes, command in value.trace_info():
                    value.trace_remove(modes, command)
        if page._poll_id:
            page.window.after_cancel(page._poll_id)
            page._poll_id = None
        page.window.destroy()
        for name, value in tuple(vars(page).items()):
            if isinstance(value, (tk.Variable, tk.Misc)) or (isinstance(value, list) and
                    any(isinstance(item, (tk.Variable, tk.Misc)) for item in value)):
                setattr(page, name, None)
        value = None
        if not self.windows:
            self.root.destroy()
            self.source_selection = self.receiver_selection = self.root = None

    def update_online_controls(self):
        for role, page in self.windows.items():
            if page.business_online:
                page.update_business_controls()
            elif page.online:
                page.update_online_controls()
            elif role == 'sender' and self.online_control:
                occupied = self.other_owner(role) is not None
                page.port_combo.configure(state='disabled' if occupied else 'readonly')
                page.refresh_button.configure(state='disabled' if occupied else 'normal')

    def other_owner(self, role):
        if role not in ('sender', 'control'):
            return None
        other = 'control' if role == 'sender' else 'sender'
        page = self.windows.get(other)
        return other if page and page.live and page.local_claimed else None


class StationReview:
    def __init__(self, session, role):
        self.session, self.role = session, role
        self.online = session.online_control and role == 'control'
        self.business_online = session.online_business and role in ('sender', 'receiver')
        self.live = self.online or self.business_online
        self.local_claimed = False
        self._blocked_by = None
        self.business_pending = None
        self.business_configured = self.business_settings_seen = False
        self.business_accept_tx = self.business_accept_rx = False
        self.business_text = None
        self.business_tx_row = None
        self.business_capture_info = ''
        self.business_tx_ids = set()
        self.controller = None
        self.events = queue.Queue()
        self.online_state = 'disconnected'
        self.online_identity = None
        self.connecting_port = None
        self.accept_connected = False
        self.cancel_pending = self.closing = False
        self.closed = False
        self.active_request = None
        self.active_plan = None
        self.last_evidence = None
        self._poll_id = None
        self.window = tk.Toplevel(session.root)
        self.window.title(ROLES[role][0])
        offset = {'sender': 0, 'receiver': 1, 'control': 2}[role]
        self.window.geometry(f'1160x860+{40+offset*70}+{35+offset*55}')
        self.window.minsize(1040, 800)
        self.window.configure(bg=BG)
        self.window.protocol('WM_DELETE_WINDOW', lambda: session.close(role))
        self.selection = session.receiver_selection if role == 'receiver' else session.source_selection
        self.details_open = False
        self.draft = None
        self.historical = None
        self.simulation = None
        self._build()
        self.selection_trace = self.selection.trace_add('write', lambda *_: self.update_details())
        self.update_details()
        if self.online:
            self._start_online()
        elif self.business_online:
            self._start_business()

    def _build(self):
        main = tk.Frame(self.window, bg=BG, padx=26, pady=20)
        main.pack(fill='both', expand=True)
        mast = tk.Frame(main, bg=BG)
        mast.pack(fill='x')
        label(mast, 'NTN   /   卫星测控与变频转发', color=MUTED, size=10, bg=BG).pack(side='left')
        badge = label(mast, ' 在线测控 ' if self.online else ' 在线业务 ' if self.business_online else ' 界面审阅 ',
                      color=TEAL if self.live else AMBER, size=9, bg=PALE if self.live else '#FBF2DE')
        badge.pack(side='right', padx=(15, 0))
        label(mast, ROLES[self.role][3], color=TEAL, bold=True, bg=BG).pack(side='right')

        header = tk.Frame(main, bg=BG)
        header.pack(fill='x', pady=(15, 18))
        heading = tk.Frame(header, bg=BG)
        heading.pack(side='left')
        label(heading, ROLES[self.role][1], size=25, bold=True, bg=BG).pack(anchor='w')
        if self.role != 'receiver':
            other = 'control' if self.role == 'sender' else 'sender'
            button(header, '改频控制  →' if other == 'control' else '←  文本发送',
                   lambda: self.session.show(other)).pack(side='right', pady=8)

        connection = card(main, padding=12)
        connection.edge.pack(fill='x', pady=(0, 14))
        label(connection, '接收板' if self.role == 'receiver' else '发送板', bold=True).pack(side='left', padx=(2, 15))
        self.port_combo = ttk.Combobox(connection, textvariable=self.selection,
            values=tuple(self.session.devices), state='readonly', style='V2.TCombobox', width=32)
        self.port_combo.pack(side='left')
        self.refresh_button = button(connection, '刷新', self.session.refresh_devices)
        self.refresh_button.pack(side='left', padx=8)
        self.connect_button = button(connection, '连接', self.connect_business if self.business_online else self.connect_online, disabled=True)
        self.connect_button.pack(side='left')
        self.connection_status = tk.StringVar(self.window, '●  未连接')
        if self.session.online_control and self.role == 'sender' and not self.business_online:
            self.connection_status.set('●  测控模式 · 文本禁发')
        label(connection, variable=self.connection_status, color=MUTED, size=9).pack(side='left', padx=15)
        self.details_button = button(connection, '设备与参数  ▾', self.toggle_details)
        self.details_button.pack(side='right')
        self.details = card(main, padding=12)
        self.device_detail = tk.StringVar(self.window)
        detail_label = label(self.details, variable=self.device_detail, color=MUTED, size=9, wrap=1000)
        detail_label.pack(anchor='w')
        self.details.bind('<Configure>', lambda event: detail_label.configure(wraplength=max(200, event.width-24)))
        self._build_details()

        self.body = tk.Frame(main, bg=BG)
        self.body.pack(fill='both', expand=True)
        getattr(self, '_build_'+self.role)()

    def _build_details(self):
        if self.role == 'sender':
            row = tk.Frame(self.details, bg=PAPER)
            row.pack(fill='x', pady=(8, 0))
            label(row, '发射衰减  dB', size=9).pack(side='left', padx=(0, 10))
            self.attenuation = tk.StringVar(self.window, '50')
            self.attenuation_spin = ttk.Spinbox(row, from_=50, to=89, width=6, textvariable=self.attenuation,
                        state='readonly', style='V2.TSpinbox')
            self.attenuation_spin.pack(side='left')
            self.attenuation_note = tk.StringVar(self.window, '  计划值 · 数值越大，信号越弱；未应用到设备。')
            label(row, variable=self.attenuation_note, color=MUTED, size=9).pack(side='left')
            label(self.details, '业务中心以本地本振回读 + 0.5 MHz 显示；不代表远端接收。' if self.business_online else '本振 900 MHz + 基带偏移 0.5 MHz = 业务中心 900.5 MHz。',
                  color=MUTED, size=9).pack(anchor='w', pady=(8, 0))
        elif self.role == 'receiver':
            label(self.details, '本地接收本振 1000.75 MHz；计划增益 30 dB。频谱来自接收采样，未采集时不显示曲线。',
                  color=MUTED, size=9).pack(anchor='w', pady=(8, 0))
        else:
            self.mapping = tk.StringVar(self.window, '业务中心减去 0.5 MHz 为协议本振；当前报文的本振精度为 1 MHz。')
            label(self.details, variable=self.mapping, color=MUTED, size=9).pack(anchor='w', pady=(8, 0))
            label(self.details, '遥控上行 100.5 MHz · 状态下行 90.5 MHz；与文本发送共用本地 SDR，按分时方案接入。',
                  color=MUTED, size=9).pack(anchor='w', pady=(6, 0))

    def update_details(self):
        device = self.session.devices.get(self.selection.get())
        if self.live and self.connecting_port and (not device or device['port'] != self.connecting_port):
            if not self.cancel_pending and not self.closing:
                self.stop_business('disconnect') if self.business_online else self.cancel_online('disconnect')
        if self.online_identity is not None and device and device['port'] == self.online_identity.get('port'):
            identity = self.online_identity
            self.device_detail.set(f'在线核验：{identity["port"]} · {identity.get("model", "本地 SDR")} · '
                                   f'USB 序号 {identity.get("usb_serial", "未知")}；' +
                                   ('仅为本地身份，不代表远端状态。' if self.business_online else '远端就绪由实际事务确认。'))
            if self.business_capture_info:
                self.device_detail.set(self.device_detail.get()+'\n'+self.business_capture_info)
            if self.business_online:
                self.device_detail.set(self.device_detail.get()+'\n'+self.business_note.get())
            if self.last_evidence:
                self.device_detail.set(self.device_detail.get()+
                    f'\n本次接收 IQ：{self.last_evidence["iq_path"]}\n本次报告：{self.last_evidence["report_path"]}')
            return
        self.device_detail.set(f'接口：{device["port"]} · {device["description"]} · USB 序号 {device.get("serial") or "未知"}；待在线核验。'
                               if device else '尚未选择本地设备；USB 列表不代表已确认板卡身份。')
        if self.business_online:
            self.device_detail.set(self.device_detail.get()+'\n'+self.business_note.get())
        if self.business_online:
            self.update_business_controls()
        elif self.online:
            self.update_online_controls()

    def _start_business(self):
        try:
            factory = self.session.business_controller_factory
            if factory is None:
                from .business_live import BusinessController
                factory = BusinessController
            self.controller = factory(self.role, self.events.put, log_dir=None)
        except Exception as error:
            self.online_state = 'error'
            self.business_note.set(f'在线业务启动失败：{error}')
        else:
            self._poll_id = self.window.after(60, self._drain_online_events)
        self.update_business_controls()

    def update_business_controls(self):
        if not self.business_online or not hasattr(self, 'business_note'):
            return
        blocked = self.session.other_owner(self.role)
        if blocked:
            self._blocked_by = blocked
            self.connection_status.set('●  改频控制占用')
            self.business_note.set('发送板由改频控制占用，请先在该窗口断开；切换窗口不会换线。')
        elif self._blocked_by:
            self._blocked_by = None
            self.connection_status.set('●  未连接')
            self.business_note.set('占用已释放，请连接本地设备；业务收发前须确认业务接线。')
        available = not self.closing and not self.cancel_pending and not blocked
        idle = available and self.business_pending is None
        disconnected = self.online_state in ('disconnected', 'error')
        self.port_combo.configure(state='readonly' if idle and disconnected else 'disabled')
        self.refresh_button.configure(state='normal' if idle and disconnected else 'disabled')
        self.connect_button.configure(text='断开中' if self.cancel_pending else '取消连接' if self.accept_connected else
                                      '断开连接' if self.local_claimed else '连接',
            state='normal' if available and self.controller is not None and
            (self.local_claimed or self.session.devices.get(self.selection.get())) else 'disabled')
        ready = idle and self.business_configured and self.online_identity is not None
        self.business_stop_button.configure(state='normal' if available and
            (self.business_pending is not None or self.online_state in ('transmitting', 'receiving')) else 'disabled')
        if self.role == 'sender':
            text = self.message_input.get('1.0', 'end-1c')
            try:
                text_bytes(text)
                valid = True
            except ValueError:
                valid = False
            self.send_button.configure(state='normal' if ready and valid and self.online_state in ('ready', 'stopped', 'transmitting') else 'disabled')
            self.attenuation_spin.configure(state='readonly' if idle and self.online_state in ('disconnected', 'error', 'ready', 'stopped') else 'disabled')
        else:
            self.receive_button.configure(state='normal' if ready and self.online_state in ('ready', 'stopped') else 'disabled')
            self.expected_combo.configure(state='readonly' if idle and self.online_state in ('disconnected', 'error', 'ready', 'stopped') else 'disabled')

    def _business_submit(self, action, **kwargs):
        try:
            self.controller.submit(action, **kwargs)
            return True
        except Exception as error:
            self.business_accept_tx = self.business_accept_rx = False
            self.business_note.set(f'{action} 提交失败：{error}；等待断开清理。')
            self.business_pending = 'disconnect'
            self.cancel_pending = True
            self.connection_status.set('●  等待清理回执')
            if action == 'close':
                self.closing = False
            else:
                try:
                    self.controller.submit('disconnect')
                except Exception:
                    self.business_note.set(f'{action} 提交失败：{error}；请关闭窗口重试清理。')
            self.session.update_online_controls()
            return False

    def connect_business(self):
        if not self.business_online or self.closing or self.cancel_pending or self.controller is None:
            return
        if self.session.other_owner(self.role):
            self.session.update_online_controls()
            return
        if self.local_claimed:
            self.stop_business('disconnect')
            return
        device = self.session.devices.get(self.selection.get())
        if not device:
            return
        self.local_claimed = True
        self.connecting_port = device['port']
        self.accept_connected = True
        self.online_identity = None
        self.business_configured = self.business_settings_seen = False
        self.business_pending = 'connect'
        self.online_state = 'connecting'
        self.business_accept_tx = self.business_accept_rx = False
        self.business_capture_info = ''
        self._clear_business_readback()
        self.connection_status.set('●  正在核验本地设备')
        self.business_note.set('正在连接本地设备；连接和配置不会自动发送或接收。')
        self._business_submit('connect', port=self.connecting_port)
        self.session.update_online_controls()

    def configure_business(self):
        if (not self.business_online or self.closing or self.cancel_pending or self.online_identity is None
                or self.business_pending not in (None, 'connect') or self.online_state in ('transmitting', 'receiving')):
            return
        try:
            if self.role == 'sender':
                value = int(self.attenuation.get())
                if str(value) != self.attenuation.get() or not 50 <= value <= 89:
                    raise ValueError('发射衰减须为 50–89 dB 整数')
                values = dict(tx_atten_db=value)
            else:
                value = float(self.expected_rf.get())
                if value not in (1000.5, 1001.5):
                    raise ValueError('本地接收先验仅支持 1000.5 / 1001.5 MHz')
                values = dict(expected_rf_mhz=value)
        except ValueError as error:
            self.business_configured = False
            self.business_note.set(str(error))
            self.update_business_controls()
            return
        self.business_configured = self.business_settings_seen = False
        self.business_pending = 'configure'
        self.online_state = 'busy'
        self.connection_status.set('●  配置本地设备')
        self._business_submit('configure', **values)
        self.session.update_online_controls()

    def send_business(self):
        if (not self.business_online or self.role != 'sender' or self.closing or self.cancel_pending
                or self.business_pending is not None or not self.business_configured or self.online_identity is None
                or self.online_state not in ('ready', 'stopped', 'transmitting') or self.session.other_owner(self.role)):
            return
        text = self.message_input.get('1.0', 'end-1c')
        try:
            text_bytes(text)
        except ValueError as error:
            self.business_note.set(str(error))
            return
        self.business_text = text
        self.business_accept_tx = True
        self.business_pending = 'send'
        self.online_state = 'busy'
        self.business_note.set('正在提交本地限时循环发送；不代表电脑2已收到。')
        self._business_submit('send', text=text)
        self.session.update_online_controls()

    def receive_business(self):
        if (not self.business_online or self.role != 'receiver' or self.closing or self.cancel_pending
                or self.business_pending is not None or not self.business_configured or self.online_identity is None
                or self.online_state not in ('ready', 'stopped')):
            return
        self.business_accept_rx = True
        self.business_pending = 'receive'
        self.online_state = 'receiving'
        self.received_text.set('等待本次接收文本')
        self.received_hero.configure(fg='#9BADA9')
        self.received_meta.set('尚无本次 CRC 有效消息；历史记录保留在下方。')
        self.capture_note.set('正在采集')
        self.carrier_frequency.set('—')
        self.frame_stats.set('本次有效帧 — / CRC 失败 —')
        self.spectrum.set_spectrum(None)
        self._business_submit('receive')
        self.session.update_online_controls()

    def stop_business(self, action='stop'):
        if not self.business_online or self.closing or self.cancel_pending or self.controller is None or not self.local_claimed:
            return
        self.business_accept_tx = self.business_accept_rx = False
        self.business_pending = action
        self.cancel_pending = True
        self.online_state = 'busy'
        self.connection_status.set('●  正在停止' if action == 'stop' else '●  正在断开')
        self.business_note.set('等待本端停止回执；当前窗口仍占用本地板卡。')
        self._business_submit(action)
        self.session.update_online_controls()

    def close_business(self):
        if self.closing:
            return
        self.closing = True
        self.business_accept_tx = self.business_accept_rx = False
        self.connection_status.set('●  正在关闭')
        self.business_note.set('等待本地收发停止并释放串口后关闭窗口。')
        self._business_submit('close')
        self.session.update_online_controls()

    def _clear_business_readback(self):
        if self.role == 'sender':
            self.sender_frequency.set('900.500')
            self.sender_frequency_note.set('MHz / 计划中心 · 尚未设备回读')
            self.sender_readback.set('设备回读：—')
            self.attenuation_note.set('  本地配置尚未确认。')
        else:
            self.carrier_frequency.set('—')
            self.receiver_plan_note.set('MHz · 本地先验尚未应用，远端状态未知')
            self.frame_stats.set('有效帧 — / CRC 失败 —')
            self.spectrum.set_spectrum(None)

    def _business_released(self, message, state='disconnected'):
        self.local_claimed = False
        self.online_identity = None
        self.connecting_port = None
        self.accept_connected = self.cancel_pending = False
        self.business_accept_tx = self.business_accept_rx = False
        self.business_configured = self.business_settings_seen = False
        self.business_pending = None
        self.online_state = state
        self.connection_status.set('●  业务异常 · 已断开' if state == 'error' else '●  未连接')
        self.business_note.set(str(message))
        self._clear_business_readback()
        if self.role == 'receiver':
            self.capture_note.set('已断开')
            self.received_meta.set('历史接收记录 · 本地连接已释放；尚无新的接收结果。')
        elif self.business_tx_row:
            self.history.set(self.business_tx_row, 'status', '本地异常 / 结果未知' if state == 'error' else '本地已停发 / 已断开')
        self.update_details()

    @staticmethod
    def _finite_business(value):
        return type(value) in (int, float) and math.isfinite(value)

    def _handle_business_event(self, event):
        if self.closed:
            return
        kind = event.get('type')
        if kind == 'closed':
            if self._poll_id:
                self.window.after_cancel(self._poll_id)
                self._poll_id = None
            self.controller = None
            self.session._destroy_page(self.role)
            self.session.update_online_controls()
            return
        if self.closing:
            return
        if kind == 'identity':
            if not self.accept_connected or self.cancel_pending:
                return
            identity = event.get('identity', {})
            device = self.session.devices.get(self.selection.get())
            if not isinstance(identity, dict) or identity.get('port') != self.connecting_port or not device or device['port'] != self.connecting_port:
                self.stop_business('disconnect')
                return
            self.accept_connected = False
            self.online_identity = dict(identity)
            self.update_details()
            self.configure_business()
        elif kind == 'settings':
            if self.online_identity is None or (self.cancel_pending and self.business_pending != 'stop'):
                return
            values = event.get('values', {})
            if self.role == 'sender':
                if values.get('configured') is True:
                    self.business_settings_seen = True
                    if 'tx_lo_hz_readback' not in values:
                        self.attenuation_note.set('  发送配置已登记；实际 LO / 衰减待发送后回读。')
                lo = values.get('tx_lo_hz_readback')
                if self._finite_business(lo):
                    self.sender_frequency.set(f'{(lo+500_000)/1e6:.3f}')
                    self.sender_frequency_note.set('MHz / 本地回读 LO + 0.5 MHz')
                    attenuation = values.get('tx_atten_db_readback', '—')
                    self.sender_readback.set(f'本地 LO {lo/1e6:.6f} MHz\n衰减回读 {attenuation} dB')
                    self.attenuation_note.set(f'  本地衰减回读 {attenuation} dB；发送计划 {self.attenuation.get()} dB。')
            else:
                lo = values.get('rx_lo_hz_readback')
                if self._finite_business(lo):
                    self.receiver_plan_note.set(f'本地 LO {lo/1e6:.3f} MHz\n先验 {values.get("expected_rf_mhz", self.expected_rf.get())} MHz · 远端状态未知')
                    if values.get('configured') is True:
                        self.business_settings_seen = True
        elif kind == 'status':
            state = event.get('state')
            message = str(event.get('message', state))
            if state in ('error', 'disconnected'):
                if state == 'disconnected' and self.accept_connected and not self.cancel_pending:
                    return  # Queued startup status, before this Connect click.
                if state == 'error' and self.cancel_pending and (event.get('category') == 'cancelled' or '取消' in message):
                    self.online_identity = None
                    self.business_configured = False
                    self.business_note.set(message+'；等待本次停止/断开最终回执。')
                    self._clear_business_readback()
                    self.session.update_online_controls()
                    return
                self._business_released(message, state)
            elif self.local_claimed:
                if self.cancel_pending and state != 'stopped':
                    return
                if state == 'ready':
                    if self.online_identity is None or not self.business_settings_seen:
                        return  # Connect-ready is not configure-ready.
                    self.business_configured = True
                    self.business_pending = None
                    self.online_state = 'ready'
                    self.connection_status.set('●  本地配置就绪')
                    self.business_note.set('本地配置已确认；业务收发前须确认业务接线。')
                    if self.role == 'receiver':
                        self.received_meta.set('本地接收已就绪 · 等待开始接收；历史消息见下方记录。')
                        self.capture_note.set('已就绪 · 待开始')
                elif state == 'stopped':
                    if self.business_pending in ('disconnect', 'close'):
                        return
                    if self.online_identity is None:
                        self._business_released('取消清理完成，本地连接已释放。')
                        self.session.update_online_controls()
                        return
                    self.cancel_pending = False
                    self.business_pending = None
                    self.business_accept_tx = self.business_accept_rx = False
                    self.online_state = 'stopped'
                    self.connection_status.set('●  本端已停止')
                    self.business_note.set(message)
                    if self.role == 'sender' and self.business_tx_row:
                        self.history.set(self.business_tx_row, 'status', '本地已停发 / 静音')
                    elif self.role == 'receiver':
                        self.capture_note.set('接收已停止')
                elif self.online_identity is not None:
                    if state == 'transmitting' and not self.business_accept_tx or state == 'receiving' and not self.business_accept_rx:
                        return
                    if state in ('busy', 'transmitting', 'receiving'):
                        self.online_state = state
                        self.connection_status.set('●  本地限时发送' if state == 'transmitting' else '●  正在接收' if state == 'receiving' else '●  本地处理中')
                        self.business_note.set(message)
                        if state == 'receiving' and self.business_pending == 'receive':
                            self.business_pending = None
        elif kind == 'tx':
            if not self.business_accept_tx or self.cancel_pending or self.online_identity is None or event.get('text') != self.business_text:
                return
            message_id = event.get('message_id')
            if not isinstance(message_id, str) or message_id in self.business_tx_ids:
                return
            self.business_tx_ids.add(message_id)
            self.business_pending = None
            self.business_tx_row = self.history.insert('', 0, values=(datetime.now().strftime('%H:%M:%S'),
                message_id, event['text'], '本地限时循环发送'))
            self.business_note.set('本地约 30 秒有界循环发送；未表示电脑2已收到。')
        elif kind == 'rx':
            if not self.business_accept_rx or self.cancel_pending or self.online_identity is None:
                return
            self._business_rx(event)
        elif kind == 'log' and event.get('level') in ('warning', 'error'):
            self.business_note.set(str(event.get('message', '')))
        self.session.update_online_controls()

    def _business_rx(self, event):
        stamp = event.get('received_at')
        try:
            timestamp = datetime.fromtimestamp(stamp, tz=timezone.utc).astimezone().strftime('%H:%M:%S')
        except (TypeError, ValueError, OSError, OverflowError):
            timestamp = '未知时间'
        messages = event.get('messages', [])
        valid = [message for message in messages if isinstance(message, dict) and message.get('crc_valid') is True
                 and isinstance(message.get('text'), str) and isinstance(message.get('message_id'), str)]
        for message in valid:
            status = 'CRC 有效 / 重复' if message.get('duplicate') else 'CRC 有效 / 新消息'
            self.history.insert('', 0, values=(timestamp, message['message_id'], message['text'], status))
            self.received_text.set(message['text'])
            self.received_hero.configure(fg=INK)
            self.received_meta.set(f'{message["message_id"]}  /  {timestamp}  /  {status}')
        carrier = event.get('carrier_hz')
        self.carrier_frequency.set(f'{carrier/1e6:.6f}' if valid and self._finite_business(carrier) else '—')
        rms = event.get('rms_codes')
        rms_text = f'{rms:.2f}'.rstrip('0').rstrip('.') if self._finite_business(rms) else '—'
        self.frame_stats.set(f'有效帧 {event.get("valid_frames", "—")} / CRC 失败 {event.get("crc_rejected", "—")} / '
                             f'RMS {rms_text}')
        self.capture_note.set(f'最后采集 {timestamp}')
        self.spectrum.set_spectrum(event.get('spectrum'))
        self.business_capture_info = f'最后接收 IQ：{event.get("capture_file", "未提供")} / {timestamp}；本次流程 {event.get("capture_seconds", "未知")} s'
        self.update_details()

    def _start_online(self):
        self._reset_reply()
        self.history.delete(*self.history.get_children())
        self.preview_button.configure(state='disabled')
        self.preview_combo.configure(state='disabled')
        self.record_button.configure(state='disabled')
        self.request_note.set('在线仅开放 900.5/901.5 → 1000.5/1001.5 MHz；先连接本地发送板。')
        try:
            factory = self.session.controller_factory
            if factory is None:
                from .tc_live import TelecontrolController
                factory = TelecontrolController
            self.controller = factory(self.events.put, log_dir=self.session.log_dir)
        except Exception as error:
            self.online_state = 'error'
            self.reply_title.set('在线控制启动失败')
            self.reply_body.set(str(error))
            self.reply_heading.configure(fg='#B64242')
        else:
            self._poll_id = self.window.after(60, self._drain_online_events)
        self.update_online_controls()

    def update_online_controls(self):
        if not self.online or not hasattr(self, 'command_send_button'):
            return
        blocked = self.session.other_owner(self.role)
        if blocked:
            self._blocked_by = blocked
            self.connection_status.set('●  文本发送占用')
            self.request_note.set('发送板由文本发送占用，请先在该窗口断开；切换窗口不会换线。')
        elif self._blocked_by:
            self._blocked_by = None
            self.connection_status.set('●  未连接')
            self.request_note.set('占用已释放，请连接本地发送板。')
        idle = not self.closing and not self.cancel_pending and self.active_request is None
        local_ready = self.online_state == 'connected' and self.online_identity is not None
        disconnected = self.online_state in ('disconnected', 'error')
        selected = self.session.devices.get(self.selection.get())
        self.port_combo.configure(state='readonly' if idle and disconnected and not blocked else 'disabled')
        self.refresh_button.configure(state='normal' if idle and disconnected and not blocked else 'disabled')
        self.connect_button.configure(text=('取消连接' if self.accept_connected else
                                           '断开中' if self.cancel_pending else
                                           '断开连接' if not disconnected else '连接'),
                                      state='normal' if not self.closing and not self.cancel_pending and not blocked and self.controller is not None
                                      and (bool(selected) or not disconnected) else 'disabled')
        sendable = bool(idle and local_ready and self.draft and self.draft.get('body_hex') and self.draft.get('request')
                        and self.draft['request']['air_seq'] == self.session.next_sequence < 256)
        self.command_send_button.configure(state='normal' if sendable else 'disabled')
        self.generate_button.configure(state='normal' if idle else 'disabled')
        for entry in self.frequency_entries:
            entry.configure(state='normal' if idle else 'disabled')
        self.stop_button.configure(state='normal' if not self.closing and not self.cancel_pending and
                                   (self.accept_connected or self.active_request is not None) else 'disabled')

    def _submit_online(self, action, **kwargs):
        try:
            self.controller.submit(action, **kwargs)
            return True
        except Exception as error:
            self._online_error(str(error), 'hardware')
            if action == 'close':
                self.closing = False
                self.reply_title.set('关闭提交失败 · 请重试关闭')
            else:
                # A rejected/uncertain queue submission is not proof that hardware is idle.
                self.cancel_pending = True
                self.local_claimed = True
                self.online_state = 'stopping'
                self.connection_status.set('●  等待停止回执')
                try:
                    self.controller.submit('stop')
                except Exception:
                    self.reply_body.set(str(error)+'\n停止提交也未确认，请关闭窗口以重试设备清理。')
            self.session.update_online_controls()
            return False

    def connect_online(self):
        if not self.online or self.closing or self.cancel_pending or self.controller is None:
            return
        if self.session.other_owner(self.role):
            self.session.update_online_controls()
            return
        if self.online_state not in ('disconnected', 'error') or self.accept_connected:
            self.cancel_online('disconnect')
            return
        device = self.session.devices.get(self.selection.get())
        if not device:
            return
        self._reset_reply()
        self.active_request = self.active_plan = None
        self.online_identity = None
        self.connecting_port = device['port']
        self.local_claimed = True
        self.accept_connected = True
        self.online_state = 'connecting'
        self.connection_status.set('●  正在核验本地设备')
        self.reply_title.set('连接中 · 尚未发送')
        self._submit_online('connect', source_port=self.connecting_port)
        self.session.update_online_controls()

    def send_online(self):
        if not self.online or self.closing or self.cancel_pending or self.active_request is not None:
            return
        if self.online_state != 'connected' or self.online_identity is None or not self.draft:
            return
        request = self.draft.get('request')
        if (not self.draft.get('body_hex') or not request or request['air_seq'] != self.session.next_sequence
                or self.session.next_sequence >= 256 or request['rx_mhz'] not in (900, 901)
                or request['tx_mhz'] not in (1000, 1001)):
            return
        self.active_request = dict(request)
        self.active_plan = dict(self.draft['plan'])
        # Consume before submitting: an uncertain submission must never reuse an air sequence.
        self.session.next_sequence += 1
        self.draft = None
        self._reset_reply()
        self.reply_title.set('指令执行中')
        self.reply_body.set('等待真实上行发送与射频回报；尚未确认执行结果。')
        self.request_note.set(f'本会话第 {self.session.next_sequence} 条指令 · 正在执行')
        self.step_labels[0].configure(text='01   指令已提交', fg=TEAL)
        self.online_state = 'sending'
        self.connection_status.set('●  执行中')
        self._record_online('在线 · 已提交，待回报')
        self._submit_online('send', requested=dict(request), wiring_confirmed=True)
        self.session.update_online_controls()

    def _record_online(self, status):
        if self.active_plan is None:
            return
        plan = self.active_plan
        self.history.insert('', 0, values=(datetime.now().strftime('%H:%M:%S'),
            f'{format_mhz(plan["input_hz"])} → {format_mhz(plan["output_hz"])}', status))

    def cancel_online(self, action='stop'):
        if not self.online or self.closing or self.cancel_pending or self.controller is None:
            return
        self.cancel_pending = True
        self.accept_connected = False
        self.online_identity = None
        self.active_request = None
        self.draft = None
        self._reset_reply()
        self.reply_title.set('正在取消并释放设备')
        self.reply_body.set('等待设备停止与断开回执；本次结果尚未确认。')
        self.online_state = 'stopping'
        self.connection_status.set('●  正在断开')
        self.update_details()
        self._submit_online(action)
        self.session.update_online_controls()

    def close_online(self):
        if self.closing:
            return
        self.closing = True
        self.accept_connected = False
        self.online_identity = None
        self.active_request = None
        self._reset_reply()
        self.reply_title.set('正在关闭 · 等待设备清理')
        self.reply_body.set('收到控制器关闭回执后，此窗口将自动关闭。')
        self.connection_status.set('●  正在关闭')
        self.update_details()
        self._submit_online('close')
        self.session.update_online_controls()

    def _online_error(self, message, category=None):
        awaiting_cancel = self.cancel_pending and category == 'cancelled'
        timeout = category == 'timeout' or (category is None and ('超时' in message or 'timeout' in message.lower()))
        cancelled = category == 'cancelled'
        self._reset_reply()
        self.reply_title.set('等待超时 · 结果未知' if timeout else '操作已取消 · 结果未知' if cancelled else '执行失败')
        self.reply_body.set(str(message))
        self.reply_heading.configure(fg=AMBER if timeout or cancelled else '#B64242')
        self._record_online('在线 · 等待超时' if timeout else '在线 · 已取消' if cancelled else '在线 · 失败')
        self.active_request = self.active_plan = None
        self.draft = None
        self.online_identity = None
        self.connecting_port = None
        self.accept_connected = False
        self.cancel_pending = awaiting_cancel
        self.local_claimed = awaiting_cancel
        self.online_state = 'stopping' if awaiting_cancel else 'error'
        self.connection_status.set('●  正在断开' if awaiting_cancel else '●  已断开 · 请重新连接')
        self.update_details()
        self.session.update_online_controls()

    def _handle_online_event(self, event):
        if self.closed:
            return
        if self.business_online:
            self._handle_business_event(event)
            return
        kind = event.get('type')
        state = event.get('state')
        if kind == 'closed' or (kind == 'status' and state == 'closed'):
            if self._poll_id:
                self.window.after_cancel(self._poll_id)
                self._poll_id = None
            self.controller = None
            self.session._destroy_page(self.role)
            self.session.update_online_controls()
            return
        if self.closing:
            return
        if kind == 'connected':
            if not self.accept_connected or self.cancel_pending:
                return
            source = event.get('source', {})
            device = self.session.devices.get(self.selection.get())
            if (not isinstance(source, dict) or source.get('port') != self.connecting_port
                    or not device or device['port'] != self.connecting_port):
                self.cancel_online('disconnect')
                return
            if 'next_sequence' in event:
                suggested = event['next_sequence']
                if type(suggested) is not int or not 0 <= suggested <= 256:
                    self.cancel_online('disconnect')
                    self.reply_body.set('连接返回的指令序号无效；已请求断开，不会发送。')
                    return
                next_sequence = max(self.session.next_sequence, suggested)
                if next_sequence != self.session.next_sequence:
                    self.draft = None
                    self.request_note.set('跨进程序号已更新，请重新生成指令。')
                self.session.next_sequence = next_sequence
                if next_sequence >= 256:
                    self.draft = None
                    self.request_note.set('本会话 0–255 序号已用完，请关闭并新建在线会话。')
            self.online_identity = dict(source)
            self.accept_connected = False
            self.online_state = 'connected'
            self.connection_status.set('●  本地已连接')
            self.reply_title.set('本地已连接 · 尚未发送')
            self.reply_body.set('本地发送设备已核验；远端服务就绪与执行结果由本次事务确认。')
            self.update_details()
        elif kind == 'status':
            if self.cancel_pending and state not in ('disconnected', 'error'):
                return
            if state == 'error':
                self._online_error(str(event.get('message', '操作失败')), event.get('category'))
                return
            if state == 'disconnected':
                # The controller's startup status may be queued before a quick Connect click.
                if self.accept_connected and not self.cancel_pending:
                    return
                was_cancelled = self.cancel_pending
                had_request = self.active_request is not None
                self.online_identity = None
                self.local_claimed = False
                self.connecting_port = None
                self.active_request = self.active_plan = None
                self.accept_connected = self.cancel_pending = False
                self.online_state = 'disconnected'
                self.connection_status.set('●  未连接')
                if was_cancelled:
                    self._reset_reply()
                    self.reply_title.set('已取消并断开 · 结果未知')
                    self.reply_body.set('本次操作已停止；再次发送前请重新连接。')
                elif had_request:
                    self._reset_reply()
                    self.reply_title.set('连接已断开 · 结果未知')
                    self.reply_body.set('尚未收到本次有效射频回报；再次发送前请重新连接。')
                self.update_details()
            elif state in ('connecting', 'connected', 'sending', 'receiving', 'stopping'):
                # Unsolicited or delayed status cannot recreate ownership or a transaction.
                if not (self.accept_connected or self.online_identity is not None):
                    return
                self.online_state = state
                self.connection_status.set({'connecting': '●  正在核验本地设备',
                    'connected': '●  本地已连接' if self.online_identity is not None else '●  正在核验本地设备',
                    'sending': '●  正在发送上行', 'receiving': '●  等待射频回报',
                    'stopping': '●  正在停止'}[state])
                if self.active_request is not None:
                    self.reply_body.set(str(event.get('message', '等待本次事务回报')))
                    if state == 'receiving':
                        self.reply_title.set('等待射频回报')
                        self.step_labels[1].configure(text='02   上行已发送', fg=TEAL)
                        self.step_labels[2].configure(text='03   等待射频回报', fg=AMBER)
                    elif state == 'sending':
                        self.step_labels[1].configure(text='02   上行发送中', fg=AMBER)
        elif kind == 'result':
            if self.cancel_pending or self.active_request is None or self.online_identity is None:
                return
            request = self.active_request
            # A late result for another air sequence cannot satisfy this transaction.
            if event.get('requested') != request:
                return
            ack = event.get('ack', {})
            count = event.get('frame_count')
            matched = (isinstance(ack, dict) and all(type(ack.get(axis+'_hz')) is int and
                       abs(ack[axis+'_hz']-request[axis+'_mhz']*1_000_000) <= 10_000 for axis in ('rx', 'tx')))
            if event.get('passed') is not True or type(count) is not int or count <= 0 or not matched:
                self._online_error('真实回报未通过请求关联、CRC 帧数或频率核对。', 'validation')
                return
            self._reset_reply()
            self.last_evidence = dict(iq_path=str(event.get('iq_path', '未提供')),
                                      report_path=str(event.get('report_path', '未提供')))
            self.reply_title.set('执行成功 · 射频回报')
            self.connection_status.set('●  回报核对通过')
            self.reply_heading.configure(fg=TEAL)
            self.reply_body.set(f'{count} 个 CRC 正确帧 · 本次指令关联通过\n'
                                f'回报本振：RX {ack["rx_hz"]/1e6:.6f} / TX {ack["tx_hz"]/1e6:.6f} MHz\n\n'
                                f'接收 IQ：{Path(self.last_evidence["iq_path"]).name}\n'
                                f'报告：{Path(self.last_evidence["report_path"]).name}\n完整路径见“设备与参数”。')
            self.update_details()
            for index, (item, text) in enumerate(zip(self.step_labels, ('已提交指令', '上行已发送', '收到射频回报', '核对通过')), 1):
                item.configure(text=f'0{index}   {text}', fg=TEAL)
            self._record_online('在线 · 执行成功，射频回报')
            self.active_request = self.active_plan = None
            self.request_note.set('本次事务完成；下一条指令需重新生成，序号不会复用。')
        elif kind == 'log' and event.get('level') in ('error', 'warning'):
            self.request_note.set(str(event.get('message', '')))
        self.session.update_online_controls()

    def _drain_online_events(self):
        while self.session.windows.get(self.role) is self:
            try:
                self._handle_online_event(self.events.get_nowait())
            except queue.Empty:
                break
        if self.session.windows.get(self.role) is self:
            self._poll_id = self.window.after(60, self._drain_online_events)

    def toggle_details(self):
        self.update_details()
        self.details_open = not self.details_open
        if self.details_open:
            self.history_card.edge.grid_remove()
            self.details.edge.pack(fill='x', pady=(0, 12), before=self.body)
        else:
            self.details.edge.pack_forget()
            self.history_card.edge.grid()
        self.details_button.configure(text='设备与参数  ▴' if self.details_open else '设备与参数  ▾')

    def _history(self, parent, title, columns):
        pane = card(parent, title, padding=14)
        keys = [item[0] for item in columns]
        tree = ttk.Treeview(pane, columns=keys, show='headings', style='V2.Treeview', height=3)
        for key, heading, width in columns:
            tree.heading(key, text=heading)
            tree.column(key, width=width, minwidth=65, stretch=key in ('content', 'target'))
        tree.pack(fill='both', expand=True, pady=(8, 0))
        return pane, tree

    def _build_sender(self):
        self.body.columnconfigure(0, weight=1)
        self.body.columnconfigure(1, weight=0, minsize=285)
        self.body.rowconfigure(0, weight=1)
        compose = card(self.body, '发送内容')
        compose.edge.grid(row=0, column=0, sticky='nsew', padx=(0, 16), pady=(0, 14))
        field = tk.Frame(compose, bg='#F8FAFC', highlightbackground=LINE, highlightthickness=1)
        field.pack(fill='both', expand=True, pady=(8, 12))
        self.message_input = tk.Text(field, wrap='word', height=4, bd=0, padx=16, pady=16,
            bg='#F8FAFC', fg=INK, insertbackground=TEAL, font=('Microsoft YaHei UI', 18), undo=True)
        self.message_input.pack(fill='both', expand=True)
        self.placeholder = label(field, '在这里输入要传输的文本…', size=17, color='#9AA8B7', bg='#F8FAFC')
        self.placeholder.place(x=16, y=16)
        self.placeholder.bind('<Button-1>', lambda _e: self.message_input.focus_set())
        self.message_input.bind('<<Modified>>', self._text_changed)
        toolbar = tk.Frame(compose, bg=PAPER)
        toolbar.pack(fill='x')
        self.byte_count = tk.StringVar(self.window, '0 / 32 字节')
        self.byte_label = label(toolbar, variable=self.byte_count, color=MUTED, size=9)
        self.byte_label.pack(side='left')
        self.send_button = button(toolbar, '发送文本', self.send_business, primary=True, disabled=True)
        self.send_button.pack(side='right')
        self.business_stop_button = button(toolbar, '停止', self.stop_business, disabled=True)
        if self.business_online:
            self.business_stop_button.pack(side='right', padx=(8, 0))
        button(toolbar, '清空', lambda: self.message_input.delete('1.0', 'end')).pack(side='right', padx=8)

        rail = tk.Frame(self.body, bg=BG)
        rail.grid(row=0, column=1, sticky='nsew', pady=(0, 14))
        frequency = card(rail, '业务发送频率')
        frequency.edge.pack(fill='x', pady=(0, 14))
        self.sender_frequency = tk.StringVar(self.window, '900.500')
        self.sender_frequency_note = tk.StringVar(self.window, 'MHz / 计划中心 · 尚未设备回读' if self.business_online else 'MHz / 计划信号中心')
        self.sender_readback = tk.StringVar(self.window, '设备回读：—')
        label(frequency, variable=self.sender_frequency, size=25, bold=True, color=TEAL).pack(anchor='w', pady=(10, 0))
        label(frequency, variable=self.sender_frequency_note, color=MUTED, size=9).pack(anchor='w', pady=(0, 10))
        label(frequency, variable=self.sender_readback, color=MUTED, size=9, wrap=240).pack(anchor='w')
        self.business_note = tk.StringVar(self.window, '业务发送前须确认业务接线；切换窗口不会换线。')
        if self.business_online:
            label(frequency, variable=self.business_note, color=MUTED, size=9, wrap=240).pack(anchor='w', pady=(12, 0))
        history, self.history = self._history(self.body, '发送记录', [
            ('time', '时间', 90), ('id', '消息编号', 140), ('content', '文本内容', 450), ('status', '发送状态', 130)])
        history.edge.grid(row=1, column=0, columnspan=2, sticky='nsew')
        self.history_card = history
        if self.business_online:
            self.attenuation.trace_add('write', lambda *_: self.configure_business())

    def _text_changed(self, _event=None):
        if not self.message_input.edit_modified():
            return
        self.message_input.edit_modified(False)
        text = self.message_input.get('1.0', 'end-1c')
        if text:
            self.placeholder.place_forget()
        else:
            self.placeholder.place(x=16, y=16)
        count = len(text.encode('utf-8'))
        self.byte_count.set(f'{count} / 32 字节'+(' · 内容过长' if count > 32 else ''))
        self.byte_label.configure(fg='#B64242' if count > 32 else MUTED)
        if self.business_online:
            self.update_business_controls()

    def _build_receiver(self):
        self.body.columnconfigure(0, weight=1)
        self.body.columnconfigure(1, weight=0, minsize=300)
        self.body.rowconfigure(0, weight=1)
        latest = card(self.body, '最新收到的文本')
        latest.edge.grid(row=0, column=0, sticky='nsew', padx=(0, 16), pady=(0, 14))
        text_box = tk.Frame(latest, bg='#F6FAF9', padx=20, pady=20)
        text_box.pack(fill='both', expand=True, pady=(10, 12))
        self.received_text = tk.StringVar(self.window, '等待接收文本')
        hero = label(text_box, variable=self.received_text, size=23, color='#9BADA9', bg='#F6FAF9', wrap=540)
        self.received_hero = hero
        hero.pack(fill='both', expand=True)
        hero.bind('<Configure>', lambda event: hero.configure(wraplength=max(180, event.width-10)))
        self.received_meta = tk.StringVar(self.window, '消息编号  —      接收时间  —      校验结果  —')
        label(latest, variable=self.received_meta, color=MUTED, size=9, wrap=580).pack(anchor='w')
        controls = tk.Frame(latest, bg=PAPER)
        controls.pack(fill='x', pady=(15, 0))
        self.receive_button = button(controls, '开始接收', self.receive_business, primary=True, disabled=True)
        self.receive_button.pack(side='left')
        self.business_stop_button = button(controls, '停止接收', self.stop_business, disabled=True)
        self.business_stop_button.pack(side='left', padx=8)
        self.capture_note = tk.StringVar(self.window, '尚未采集')
        label(controls, variable=self.capture_note, color=MUTED, size=9).pack(side='right')

        signal = card(self.body, '接收信号')
        signal.edge.grid(row=0, column=1, sticky='nsew', pady=(0, 14))
        self.carrier_frequency = tk.StringVar(self.window, '—')
        label(signal, variable=self.carrier_frequency, size=27, bold=True, color=TEAL).pack(anchor='w', pady=(5, 0))
        label(signal, 'MHz  /  实际载波估计', color=MUTED, size=9).pack(anchor='w', pady=(0, 14))
        expectation = tk.Frame(signal, bg=PAPER)
        expectation.pack(fill='x')
        label(expectation, '接收目标', size=9).pack(side='left')
        self.expected_rf = tk.StringVar(self.window, '1000.5')
        self.expected_combo = ttk.Combobox(expectation, textvariable=self.expected_rf, values=('1000.5', '1001.5'),
                     state='readonly', style='V2.TCombobox', width=8)
        self.expected_combo.pack(side='right')
        self.receiver_plan_note = tk.StringVar(self.window, 'MHz · 本地接收计划，未应用')
        label(signal, variable=self.receiver_plan_note, color=MUTED, size=9, wrap=250).pack(anchor='w', pady=(5, 14))
        if self.business_online:
            from .app import SpectrumCanvas
            self.spectrum = SpectrumCanvas(signal)
            self.spectrum.configure(height=100)
        else:
            self.spectrum = tk.Canvas(signal, bg='#F8FAFC', height=100, highlightthickness=0)
            self.spectrum.bind('<Configure>', self._empty_spectrum)
        self.spectrum.pack(fill='both', expand=True)
        self.frame_stats = tk.StringVar(self.window, '有效帧  —    校验失败  —')
        label(signal, variable=self.frame_stats, color=MUTED, size=9, wrap=250).pack(anchor='w', pady=(12, 0))
        self.business_note = tk.StringVar(self.window, '本端真实 IQ 接收；先验不会改变远端转发板状态。')
        if self.business_online:
            hint = label(signal, variable=self.business_note, color=MUTED, size=9, wrap=250)
            hint.configure(height=2)
            hint.pack(anchor='w', pady=(6, 0))
        history, self.history = self._history(self.body, '接收记录', [
            ('time', '接收时间', 90), ('id', '消息编号', 140), ('content', '实际收到的文本', 430), ('status', '校验 / 重复', 140)])
        history.edge.grid(row=1, column=0, columnspan=2, sticky='nsew')
        self.history_card = history
        if self.business_online:
            self.history.configure(height=2)
            self.expected_rf.trace_add('write', lambda *_: self.configure_business())

    def _empty_spectrum(self, event):
        self.spectrum.delete('all')
        self.spectrum.create_rectangle(8, 10, event.width-8, event.height-10, outline=LINE)
        self.spectrum.create_text(event.width/2, event.height/2, text='采集后显示频谱',
                                  fill=MUTED, font=('Microsoft YaHei UI', 10))

    def _build_control(self):
        self.body.columnconfigure(0, weight=1, uniform='control')
        self.body.columnconfigure(1, weight=1, uniform='control')
        self.body.rowconfigure(0, weight=1)
        request = card(self.body, '转发频率设置')
        request.edge.grid(row=0, column=0, sticky='nsew', padx=(0, 8), pady=(0, 12))
        fields = tk.Frame(request, bg=PAPER)
        fields.pack(fill='x', pady=(12, 8))
        self.input_frequency = tk.StringVar(self.window, '900.5')
        self.output_frequency = tk.StringVar(self.window, '1001.5')
        self.frequency_entries = []
        for title, variable in (('业务输入', self.input_frequency), ('业务输出', self.output_frequency)):
            row = tk.Frame(fields, bg=PAPER)
            row.pack(fill='x', pady=(0, 12))
            label(row, title, size=11).pack(side='left', padx=(0, 14))
            label(row, 'MHz', color=TEAL, bold=True, size=16).pack(side='right', padx=(12, 0))
            entry = ttk.Entry(row, textvariable=variable, style='V2.Frequency.TEntry',
                              width=12, font=('Segoe UI', 21))
            entry.pack(side='left', fill='x', expand=True)
            self.frequency_entries.append(entry)
        label(request, '中心频率  70.5–6000.5 MHz  ·  最多 6 位小数', size=9, color=MUTED).pack(anchor='w', pady=(0, 12))
        self.request_note = tk.StringVar(self.window, '')
        note = label(request, variable=self.request_note, size=9, color=MUTED, wrap=430)
        note.pack(anchor='w', pady=(0, 12))
        note.bind('<Configure>', lambda event: note.configure(wraplength=max(150, event.width)))
        actions = tk.Frame(request, bg=PAPER)
        actions.pack(fill='x')
        self.generate_button = button(actions, '生成指令', self.generate_command, primary=True)
        self.generate_button.pack(side='left')
        self.command_send_button = button(actions, '发送指令', self.send_online, disabled=True)
        self.command_send_button.pack(side='left', padx=8)
        self.stop_button = button(actions, '停止', lambda: self.cancel_online('stop'), disabled=True)
        if self.online:
            self.stop_button.pack(side='left')

        reply = card(self.body, '执行回报')
        reply.edge.grid(row=0, column=1, sticky='nsew', padx=(8, 0), pady=(0, 12))
        self.reply_title = tk.StringVar(self.window, '等待执行回报')
        self.reply_body = tk.StringVar(self.window, '')
        self.reply_heading = label(reply, variable=self.reply_title, size=18, color=MUTED, bold=True)
        self.reply_heading.pack(anchor='w', pady=(16, 12))
        response = label(reply, variable=self.reply_body, size=10, color=MUTED, wrap=430)
        response.pack(fill='both', expand=True)
        response.bind('<Configure>', lambda event: response.configure(wraplength=max(150, event.width)))
        preview = tk.Frame(reply, bg=PAPER)
        preview.pack(fill='x', pady=(12, 0))
        self.preview_outcome = tk.StringVar(self.window, '成功')
        self.preview_combo = ttk.Combobox(preview, textvariable=self.preview_outcome, values=('成功', '失败', '超时'),
                     state='readonly', width=5, style='V2.TCombobox')
        self.preview_combo.pack(side='left')
        self.preview_button = button(preview, '模拟预览', self.preview_report)
        self.preview_button.pack(side='left', padx=8)
        self.record_button = button(reply, '历史实测记录', self.choose_record)
        self.record_button.pack(anchor='w', pady=(8, 0))

        steps = card(self.body, padding=12)
        steps.edge.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(0, 12))
        self.step_labels = []
        for index, title in enumerate(('准备指令', '发送上行', '等待回报', '核对结果')):
            steps.columnconfigure(index, weight=1, uniform='steps')
            item = label(steps, f'0{index+1}   {title}', color=MUTED, size=10)
            item.grid(row=0, column=index, sticky='w', padx=8)
            self.step_labels.append(item)
        history, self.history = self._history(self.body, '本窗口指令记录', [
            ('time', '时间', 90), ('target', '业务输入 → 输出 / MHz', 400), ('status', '状态', 220)])
        history.edge.grid(row=2, column=0, columnspan=2, sticky='nsew')
        self.history_card = history
        self.history.bind('<<TreeviewSelect>>', self._select_draft)
        if self.online:
            self.history.configure(height=2)
        for variable in (self.input_frequency, self.output_frequency):
            variable.trace_add('write', self._invalidate_draft)

    def _reset_reply(self):
        self.historical = self.simulation = None
        self.last_evidence = None
        self.reply_title.set('等待执行回报')
        self.reply_body.set('')
        self.reply_heading.configure(fg=MUTED)
        for index, (item, title) in enumerate(zip(self.step_labels, ('准备指令', '发送上行', '等待回报', '核对结果')), 1):
            item.configure(text=f'0{index}   {title}', fg=MUTED)
        if self.online and self.online_identity is not None:
            self.update_details()

    def _invalidate_draft(self, *_):
        self.draft = None
        if self.online and self.active_request is not None:
            self.request_note.set('当前指令执行中；新的参数需在结束后重新生成。')
            self.update_online_controls()
            return
        self.request_note.set('参数已修改，请重新生成指令。')
        self.mapping.set('业务中心减去 0.5 MHz 为协议本振；当前报文的本振精度为 1 MHz。')
        self._reset_reply()
        if self.online:
            self.update_online_controls()

    def generate_command(self):
        if self.online and (self.closing or self.active_request is not None or self.cancel_pending):
            return
        self.draft = None
        self._reset_reply()
        if self.online:
            self.update_online_controls()
        try:
            plan = frequency_plan(self.input_frequency.get(), self.output_frequency.get())
        except ValueError as error:
            self.request_note.set(str(error))
            return
        sequence = self.session.next_sequence
        if self.online and sequence >= 256:
            self.request_note.set('本会话 0–255 序号已用完，请关闭并新建在线会话。')
            self.update_online_controls()
            return
        request, body = None, None
        try:
            request = command_request(self.input_frequency.get(), self.output_frequency.get(), sequence)
            if self.online and (request['rx_mhz'] not in (900, 901) or request['tx_mhz'] not in (1000, 1001)):
                request = None
                raise ValueError('在线仅开放业务中心 900.5/901.5 → 1000.5/1001.5 MHz，其他方案暂不发送。')
            from sw.tools.telecontrol_waveform import build_body
            body = build_body(request['rx_mhz'], request['tx_mhz'], sequence)
        except ValueError as error:
            self.request_note.set(str(error))
        else:
            if not self.online:
                self.session.next_sequence = (sequence+1) % 256
            self.request_note.set('指令已生成 · 尚未发送')
        self.draft = dict(plan=plan, request=request, body_hex=body.hex() if body else None)
        self.mapping.set(f'计划本振：RX {format_mhz(plan["input_hz"]-500_000)} MHz / '
                         f'TX {format_mhz(plan["output_hz"]-500_000)} MHz；'
                         + ('现有报文可编码。' if body else '当前在线方案未开放，未生成可发送正文。' if self.online else '待扩展报文精度，未生成可发送正文。'))
        self.step_labels[0].configure(text='01   已生成 · 未发送' if body else '01   方案待接入', fg=TEAL)
        self._add_history('草稿 · 未发送' if body else '在线方案 · 暂不发送' if self.online else '频率方案 · 待扩展报文')
        if self.online:
            self.update_online_controls()

    def _add_history(self, status):
        plan = self.draft['plan']
        self.history.insert('', 0, values=(datetime.now().strftime('%H:%M:%S'),
            f'{format_mhz(plan["input_hz"])} → {format_mhz(plan["output_hz"])}', status))

    def preview_report(self):
        if self.online:
            return
        if self.draft is None:
            self.generate_command()
        if self.draft is None:
            return
        outcome = {'成功': 'success', '失败': 'failure', '超时': 'timeout'}[self.preview_outcome.get()]
        self._reset_reply()
        result = simulated_reply(self.draft['plan'], outcome)
        self.simulation = result
        self.reply_title.set(result['title'])
        self.reply_body.set(result['body']+'\n\n仅用于界面预览，未连接硬件。')
        color = {'success': TEAL, 'failure': '#B64242', 'timeout': AMBER}[outcome]
        self.reply_heading.configure(fg=color)
        for index, item in enumerate(self.step_labels):
            title = ('准备指令', '上行发送', '收到回报', '核对一致')[index]
            if outcome == 'failure' and index == 3:
                title = '执行失败'
            if outcome == 'timeout' and index >= 2:
                title = '等待超时' if index == 2 else '结果未知'
            item.configure(text=f'模拟 · {title}', fg=color if index >= 2 else TEAL)
        self._add_history(result['title'])

    def _select_draft(self, _event=None):
        selection = self.history.selection()
        if selection:
            row = self.history.item(selection[0], 'values')
            self.request_note.set(f'记录：{row[1]} MHz · {row[2]}')

    def choose_record(self):
        if self.online:
            return
        path = filedialog.askopenfilename(parent=self.window, title='选择历史事务的 result.json',
                                           filetypes=[('事务记录', '*.json')])
        if path:
            self.load_record(path)

    def load_record(self, path):
        if self.online:
            return False
        # Clear previous evidence first: a failed import must not leave a green result.
        self._reset_reply()
        if self.draft and self.draft['body_hex']:
            self.step_labels[0].configure(text='01   已生成 · 未发送', fg=TEAL)
        elif self.draft:
            self.step_labels[0].configure(text='01   方案待接入', fg=TEAL)
        self.reply_title.set('正在核对历史记录')
        self.reply_body.set('')
        try:
            record = load_historical_transaction(path)
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.reply_title.set('历史记录未通过核对')
            self.reply_heading.configure(fg='#B64242')
            self.reply_body.set(str(error))
            return False
        self.historical = record
        result = record['assessment']
        ack = result['ack']
        self.reply_title.set('历史回报 · 核对通过')
        self.reply_heading.configure(fg=TEAL)
        self.reply_body.set(
            f'{result["physical_frame_count"]} 个 CRC 正确帧\n'
            f'转发板本振回报：{ack["rx_hz"]/1e6:.6f} → {ack["tx_hz"]/1e6:.6f} MHz\n'
            '已核对指令关联及独立频率读回。\n\n'
            '这是保存的实测记录，不是本窗口刚执行的指令。\n'
            '本次复核报告帧字节与 CRC，未重新解调原始 IQ。')
        return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--all', action='store_true', help='打开三个审阅窗口')
    group.add_argument('--role', choices=tuple(ROLES))
    parser.add_argument('--online-control', action='store_true', help='启用改频窗口实板事务；文本业务另由 --online-business 启用')
    parser.add_argument('--online-business', action='store_true', help='启用本地文本发送/接收；与改频窗口须显式断开交接')
    args = parser.parse_args(argv)
    root = tk.Tk()
    root.withdraw()
    root.tk.call('tk', 'scaling', 1.33)
    session = ReviewSession(root, online_control=args.online_control, online_business=args.online_business)
    for role in ROLES if args.all else (args.role,):
        session.show(role)
    root.mainloop()


if __name__ == '__main__':
    main()
