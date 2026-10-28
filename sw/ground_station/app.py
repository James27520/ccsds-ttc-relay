"""Light desktop station. All controller callbacks cross a queue into Tk's thread.

Importing this module never opens a serial port or starts hardware activity.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import math
import queue
import tkinter as tk
from tkinter import ttk, font as tkfont
from typing import Any, Callable


COLORS = {
    "background": "#F3F6FA", "surface": "#FFFFFF", "ink": "#172C43",
    "muted": "#738297", "line": "#DFE7EF", "blue": "#2563B8",
    "teal": "#087F8C", "pale": "#EAF5F6", "danger": "#B94848",
}


class SpectrumCanvas(tk.Canvas):
    """A deliberately empty plot until a real capture supplies spectrum points."""

    def __init__(self, parent: tk.Misc):
        super().__init__(parent, background=COLORS["surface"], highlightthickness=0,
                         height=215, borderwidth=0)
        self.points: list[tuple[float, float]] = []
        self.bind("<Configure>", lambda _event: self.redraw())

    def set_spectrum(self, spectrum: dict[str, Any] | None) -> None:
        data = spectrum or {}
        self.points = []
        for frequency, level in zip(data.get("freq_mhz", []), data.get("dbfs", [])):
            try:
                point = float(frequency), float(level)
                if all(math.isfinite(value) for value in point):
                    self.points.append(point)
            except (TypeError, ValueError):
                continue
        self.redraw()

    def redraw(self) -> None:
        self.delete("all")
        width, height = max(self.winfo_width(), 200), max(self.winfo_height(), 80)
        left, top, right, bottom = 56, 20, width - 23, height - 37
        if not self.points:
            self.create_rectangle(left, top, right, bottom, outline=COLORS["line"])
            self.create_text((left + right) / 2, (top + bottom) / 2 - 10,
                             text="等待真实接收快照", fill=COLORS["muted"],
                             font=("Microsoft YaHei UI", 12))
            self.create_text((left + right) / 2, (top + bottom) / 2 + 17,
                             text="采集完成后显示实测频谱", fill=COLORS["muted"],
                             font=("Microsoft YaHei UI", 9))
            return
        minimum_x, maximum_x = min(p[0] for p in self.points), max(p[0] for p in self.points)
        minimum_y = math.floor(min(p[1] for p in self.points) / 20) * 20
        maximum_y = max(0, math.ceil(max(p[1] for p in self.points) / 20) * 20)
        if maximum_x == minimum_x:
            maximum_x += 1
        if maximum_y == minimum_y:
            maximum_y += 20
        label_height = tkfont.Font(self, font=("Segoe UI", 8)).metrics("linespace")
        y_intervals = max(1, min(4, int((bottom - top) / (label_height + 5))))
        for i in range(y_intervals + 1):
            fraction = i / y_intervals
            y = top + fraction * (bottom - top)
            self.create_line(left, y, right, y, fill=COLORS["line"])
            self.create_text(left - 8, y, text=f"{maximum_y - fraction * (maximum_y - minimum_y):.0f}",
                             anchor="e", fill=COLORS["muted"], font=("Segoe UI", 8), tags="level_tick")
        for i in range(5):
            fraction = i / 4
            x = left + fraction * (right - left)
            self.create_text(x, bottom + 16,
                             text=f"{minimum_x + fraction * (maximum_x - minimum_x):.3f}",
                             fill=COLORS["muted"], font=("Segoe UI", 8))
        self.create_text(left - 6, top - 12, text="dBFS", fill=COLORS["muted"],
                         font=("Segoe UI", 8))
        self.create_text(right, height - 4, text="MHz", fill=COLORS["muted"],
                         anchor="e", font=("Segoe UI", 8))
        # Limit Canvas work without changing the values displayed at selected bins.
        stride = max(1, len(self.points) // max(width * 2, 1))
        coordinates: list[float] = []
        for frequency, level in self.points[::stride]:
            coordinates.extend((left + (frequency - minimum_x) / (maximum_x - minimum_x) * (right - left),
                                bottom - (level - minimum_y) / (maximum_y - minimum_y) * (bottom - top)))
        if len(coordinates) >= 4:
            self.create_line(*coordinates, fill=COLORS["teal"], width=1.7)


class StationApp:
    """One independent sender or receiver application, with an injectable backend."""

    def __init__(self, root: tk.Tk, role: str,
                 controller_factory: Callable[..., Any] | None = None,
                 log_dir: str | None = None,
                 telemetry_controller_factory: Callable[..., Any] | None = None):
        if role not in {"sender", "receiver"}:
            raise ValueError("role must be sender or receiver")
        self.root, self.role = root, role
        self.events: queue.Queue[dict[str, Any]] = queue.Queue()
        self.state = "disconnected"
        self.connected = False
        self.receiving = False
        self.closing = False
        self.closed = False
        self._station_closed = False
        self.telemetry_window = None
        self.telemetry_controller_factory = telemetry_controller_factory
        self.devices: dict[str, str] = {}
        self.readbacks: dict[str, tk.StringVar] = {}
        self.requested: dict[str, tk.StringVar] = {}
        self.message_rows = 0
        self.last_valid_time = "—"
        self._close_warning_id: str | None = None
        self._poll_id: str | None = None
        self._style()
        self._build()
        if controller_factory is None:
            from .controller import StationController
            controller_factory = StationController
        self.controller = controller_factory(role, self.events.put, log_dir=log_dir)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._poll_id = self.root.after(60, self._drain_events)
        # Device discovery enumerates ports; connection and RF remain explicit actions.
        self.controller.submit("discover")
        self._update_controls()

    def _style(self) -> None:
        self.root.title("NTN 验证地面站 · " + ("发送端" if self.role == "sender" else "接收端"))
        width = min(1240, self.root.winfo_screenwidth() - 60)
        height = min(900, self.root.winfo_screenheight() - 100)
        self.root.geometry(f"{width}x{height}+20+20")
        self.root.minsize(1000, 840)
        self.root.configure(background=COLORS["background"])
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", font=("Microsoft YaHei UI", 10), foreground=COLORS["ink"])
        style.configure("TFrame", background=COLORS["background"])
        style.configure("Card.TFrame", background=COLORS["surface"])
        style.configure("TLabel", background=COLORS["background"])
        style.configure("Card.TLabel", background=COLORS["surface"])
        style.configure("Muted.TLabel", foreground=COLORS["muted"])
        style.configure("CardMuted.TLabel", background=COLORS["surface"], foreground=COLORS["muted"], font=("Microsoft YaHei UI", 9))
        style.configure("Heading.TLabel", font=("Microsoft YaHei UI", 23, "bold"))
        style.configure("CardHeading.TLabel", background=COLORS["surface"], font=("Microsoft YaHei UI", 12, "bold"))
        style.configure("Metric.TLabel", background=COLORS["surface"], font=("Segoe UI", 19, "bold"), foreground=COLORS["teal"])
        style.configure("TButton", padding=(13, 8), background="#EBF0F6", borderwidth=0)
        style.map("TButton", background=[("active", "#DFE8F2"), ("disabled", "#F0F3F6")],
                  foreground=[("disabled", "#9CA8B5")])
        style.configure("Primary.TButton", foreground="white", background=COLORS["blue"])
        style.map("Primary.TButton", background=[("active", "#1D529B"), ("disabled", "#BBCBDF")],
                  foreground=[("disabled", "#F6F8FA")])
        style.configure("Teal.TButton", foreground="white", background=COLORS["teal"])
        style.map("Teal.TButton", background=[("active", "#066C78"), ("disabled", "#BED4D8")])
        style.configure("TEntry", fieldbackground="white", padding=7, bordercolor=COLORS["line"])
        style.configure("TCombobox", fieldbackground="white", padding=6, bordercolor=COLORS["line"])
        style.configure("Treeview", background="white", fieldbackground="white", rowheight=32,
                        borderwidth=0, font=("Microsoft YaHei UI", 9))
        style.configure("Treeview.Heading", background="#F0F5F9", font=("Microsoft YaHei UI", 9, "bold"), padding=7)
        style.map("Treeview", background=[("selected", "#DCECF8")], foreground=[("selected", COLORS["ink"])])
        style.configure("TCheckbutton", background=COLORS["background"])

    def _card(self, parent: tk.Misc, title: str, subtitle: str | None = None) -> ttk.Frame:
        edge = tk.Frame(parent, background=COLORS["line"], bd=0)
        card = ttk.Frame(edge, style="Card.TFrame", padding=18)
        card.pack(fill="both", expand=True, padx=1, pady=1)
        card.edge = edge  # type: ignore[attr-defined]
        ttk.Label(card, text=title, style="CardHeading.TLabel").pack(anchor="w")
        if subtitle:
            ttk.Label(card, text=subtitle, style="CardMuted.TLabel", wraplength=660).pack(anchor="w", pady=(4, 12))
        return card

    def _build(self) -> None:
        main = ttk.Frame(self.root, padding=(25, 18, 25, 12))
        main.pack(fill="both", expand=True)
        header = ttk.Frame(main)
        header.pack(fill="x", pady=(0, 16))
        brand = ttk.Frame(header)
        brand.pack(side="left")
        ttk.Label(brand, text="NTN  验证地面站", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(brand, text="变频转发 · 真实硬件文本链路", style="Muted.TLabel").pack(anchor="w", pady=(3, 0))
        role_text = "TX  /  发送端" if self.role == "sender" else "RX  /  接收端"
        role_badge = tk.Label(header, text=role_text, bg=COLORS["pale"], fg=COLORS["teal"],
                              font=("Microsoft YaHei UI", 12, "bold"), padx=18, pady=10)
        role_badge.pack(side="right", pady=5)
        if self.role == "sender":
            self.telemetry_button = ttk.Button(header, text="测控状态", command=self.open_telemetry)
            self.telemetry_button.pack(side="right", padx=14)

        connection = self._card(main, "设备连接")
        connection.edge.pack(fill="x", pady=(0, 14))
        bar = ttk.Frame(connection, style="Card.TFrame")
        bar.pack(fill="x", pady=(10, 0))
        ttk.Label(bar, text="发送板 DEBUG" if self.role == "sender" else "接收板 DEBUG", style="CardMuted.TLabel").pack(side="left", padx=(0, 10))
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(bar, textvariable=self.port_var, state="readonly", width=33)
        self.port_combo.pack(side="left")
        self.port_combo.bind("<<ComboboxSelected>>", lambda _event: self._update_controls())
        self.refresh_button = ttk.Button(bar, text="刷新", command=lambda: self._submit("discover"))
        self.refresh_button.pack(side="left", padx=8)
        self.connect_button = ttk.Button(bar, text="连接设备", style="Primary.TButton", command=self._connect)
        self.connect_button.pack(side="left")
        self.disconnect_button = ttk.Button(bar, text="断开", command=lambda: self._submit("disconnect"))
        self.disconnect_button.pack(side="left", padx=8)
        self.status_dot = tk.Label(bar, text="●", foreground=COLORS["muted"], background="white", font=("Segoe UI", 15))
        self.status_dot.pack(side="left", padx=(14, 5))
        self.status_var = tk.StringVar(value="未连接")
        ttk.Label(bar, textvariable=self.status_var, style="Card.TLabel").pack(side="left")
        if self.role == "sender":
            relay_bar = ttk.Frame(connection, style="Card.TFrame")
            relay_bar.pack(fill="x", pady=(8, 0))
            ttk.Label(relay_bar, text="转发板 DEBUG", style="CardMuted.TLabel").pack(side="left", padx=(0, 10))
            self.relay_port_var = tk.StringVar()
            self.relay_port_combo = ttk.Combobox(relay_bar, textvariable=self.relay_port_var, state="readonly", width=33)
            self.relay_port_combo.pack(side="left")
            self.relay_port_combo.bind("<<ComboboxSelected>>", lambda _event: self._update_controls())
            ttk.Label(relay_bar, text="LDSDR · 须与发送板使用不同串口", style="CardMuted.TLabel").pack(side="left", padx=12)
        self.identity_var = tk.StringVar(value="选择本机设备后连接；连接不会自动启动发射。")
        ttk.Label(connection, textvariable=self.identity_var, style="CardMuted.TLabel").pack(anchor="w", pady=(9, 0))

        content = ttk.Frame(main)
        self.content = content
        content.pack(fill="both", expand=True)
        content.columnconfigure(0, weight=0, minsize=335)
        content.columnconfigure(1, weight=1)
        content.rowconfigure(0, weight=1)
        sidebar = ttk.Frame(content)
        sidebar.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        settings_canvas = tk.Canvas(sidebar, width=320, background=COLORS["surface"], highlightthickness=0)
        settings_scroll = ttk.Scrollbar(sidebar, orient="vertical", command=settings_canvas.yview)
        settings_canvas.configure(yscrollcommand=settings_scroll.set)
        settings_scroll.pack(side="right", fill="y")
        settings_canvas.pack(side="left", fill="both", expand=True)
        settings = self._card(settings_canvas, "射频参数", "先设置参数，再启动任务。")
        settings_window = settings_canvas.create_window((0, 0), window=settings.edge, anchor="nw")
        settings_canvas.bind("<Configure>", lambda event: settings_canvas.itemconfigure(settings_window, width=event.width))
        settings.edge.bind("<Configure>", lambda _event: settings_canvas.configure(scrollregion=settings_canvas.bbox("all")))
        self._build_settings(settings)
        # Scoped wheel bindings keep the sidebar accessible at small window heights.
        def sidebar_wheel(event: tk.Event) -> str:
            if settings.edge.winfo_height() > settings_canvas.winfo_height():
                settings_canvas.yview_scroll(-int(event.delta / 120), "units")
            return "break"
        def bind_sidebar(widget: tk.Misc) -> None:
            widget.bind("<MouseWheel>", sidebar_wheel, add=True)
            for child in widget.winfo_children():
                bind_sidebar(child)
        bind_sidebar(settings.edge)
        workspace = ttk.Frame(content)
        workspace.grid(row=0, column=1, sticky="nsew")
        if self.role == "sender":
            self._build_sender(workspace)
        else:
            self._build_receiver(workspace)
        self.log_visible = tk.BooleanVar(value=False)
        log_header = ttk.Frame(main)
        log_header.pack(side="bottom", fill="x", pady=(13, 0), before=content)
        ttk.Checkbutton(log_header, text="显示诊断日志", variable=self.log_visible, command=self._toggle_log).pack(side="left")
        self.footer_var = tk.StringVar(value="业务采用实验帧 · 仅展示设备返回的数据")
        ttk.Label(log_header, textvariable=self.footer_var, style="Muted.TLabel").pack(side="right")
        self.log_frame = ttk.Frame(main)
        self.log_text = tk.Text(self.log_frame, height=4, wrap="word", background="#EAF0F6",
                                foreground=COLORS["ink"], relief="flat", font=("Consolas", 9),
                                padx=10, pady=8, state="disabled")
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll = ttk.Scrollbar(self.log_frame, orient="vertical", command=self.log_text.yview)
        log_scroll.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.tag_configure("error", foreground=COLORS["danger"])
        self.log_text.tag_configure("warning", foreground="#946522")

    def _build_settings(self, card: ttk.Frame) -> None:
        columns = ttk.Frame(card, style="Card.TFrame")
        columns.pack(fill="x", pady=(3, 9))
        ttk.Label(columns, text="设置值", style="CardMuted.TLabel").pack(side="left")
        ttk.Label(columns, text="设备回读", style="CardMuted.TLabel").pack(side="right")
        self.setting_entries: list[ttk.Widget] = []
        if self.role == "sender":
            fields = [("tx_lo_mhz", "TX 本振 · MHz", "900", "locked"),
                      ("tx_atten_db", "TX 衰减 · dB", "50", "entry")]
        else:
            fields = [("rx_lo_mhz", "RX 本振 · MHz", "1000.75", "locked"),
                      ("expected_rf_mhz", "预期输入射频 · MHz", "1000.5", "select"),
                      ("rx_gain_db", "RX 增益 · dB", "30", "entry")]
        for key, label, initial, kind in fields:
            ttk.Label(card, text=label, style="Card.TLabel").pack(anchor="w", pady=(8, 5))
            row = ttk.Frame(card, style="Card.TFrame")
            row.pack(fill="x", pady=(0, 6))
            variable = tk.StringVar(value=initial)
            self.requested[key] = variable
            if kind == "select":
                entry = ttk.Combobox(row, textvariable=variable, values=("1000.5", "1001.5"), width=11, state="readonly")
            else:
                entry = ttk.Entry(row, textvariable=variable, width=13, state="readonly" if kind == "locked" else "normal")
            entry.pack(side="left")
            if kind != "locked":
                self.setting_entries.append(entry)
            readback = tk.StringVar(value="尚未回读")
            self.readbacks[key] = readback
            ttk.Label(row, textvariable=readback, style="CardMuted.TLabel").pack(side="right", padx=(8, 0))
        self.configure_button = ttk.Button(card, text="应用设置 / 读取回执", style="Primary.TButton", command=self._configure)
        self.configure_button.pack(fill="x", pady=(17, 12))
        safety = ("已验证：TX 本振固定 900 MHz\n衰减允许 50–89 dB" if self.role == "sender" else
                  "已验证：RX 本振固定 1000.75 MHz\n预期 RF：1000.5 / 1001.5 MHz\n增益允许 0–30 dB")
        note = tk.Label(card, text=safety, justify="left", anchor="w", background=COLORS["pale"],
                        foreground=COLORS["teal"], font=("Microsoft YaHei UI", 9), padx=12, pady=12)
        note.pack(fill="x", pady=(3, 12))
        ttk.Label(card, text="右侧仅展示设备回读；空值表示未确认。",
                  style="CardMuted.TLabel", justify="left").pack(anchor="w")
        if self.role == "sender":
            ttk.Separator(card).pack(fill="x", pady=12)
            ttk.Label(card, text="转发板读回 · 本地业务准备", style="CardHeading.TLabel").pack(anchor="w")
            self.relay_frequency_var = tk.StringVar(value="RX — MHz  →  TX — MHz")
            self.relay_mode_var = tk.StringVar(value="模式 —    衰减 — dB")
            ttk.Label(card, textvariable=self.relay_frequency_var, style="CardMuted.TLabel").pack(anchor="w", pady=(7, 3))
            ttk.Label(card, textvariable=self.relay_mode_var, style="CardMuted.TLabel").pack(anchor="w")
            ttk.Label(card, text="本地业务准备 · 非 ADC 遥控", style="CardMuted.TLabel").pack(anchor="w", pady=(8, 0))

    def _build_sender(self, parent: ttk.Frame) -> None:
        composer = self._card(parent, "发送内容", "输入将作为 UTF-8 文本发送；最多 32 字节。")
        composer.edge.pack(fill="x", pady=(0, 14))
        self.message_input = tk.Text(composer, height=4, wrap="word", relief="solid", borderwidth=1,
                                     highlightthickness=0, background="#F8FAFD", foreground=COLORS["ink"],
                                     font=("Microsoft YaHei UI", 12), padx=12, pady=10, undo=True)
        self.message_input.pack(fill="x", pady=(3, 7))
        self.message_input.bind("<<Modified>>", self._text_changed)
        controls = ttk.Frame(composer, style="Card.TFrame")
        controls.pack(fill="x")
        self.byte_var = tk.StringVar(value="0 / 32 字节")
        self.byte_label = ttk.Label(controls, textvariable=self.byte_var, style="CardMuted.TLabel")
        self.byte_label.pack(side="left")
        self.stop_button = ttk.Button(controls, text="停止发射", command=self._stop)
        self.stop_button.pack(side="right")
        self.send_button = ttk.Button(controls, text="发送文本", style="Teal.TButton", command=self._send)
        self.send_button.pack(side="right", padx=8)
        self.operation_var = tk.StringVar(value="尚未发射 · 请先连接发送端设备")
        ttk.Label(composer, textvariable=self.operation_var, style="CardMuted.TLabel").pack(anchor="w", pady=(10, 0))
        history = self._card(parent, "发送记录", "仅记录设备发送操作返回的消息；不推断另一端接收结果。")
        history.edge.pack(fill="both", expand=True)
        self._build_history(history)

    def _build_receiver(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=0)
        parent.rowconfigure(1, weight=1, minsize=140)
        # Keep complete text rows visible when Windows uses display scaling.
        parent.rowconfigure(2, weight=1, minsize=200)
        monitor = self._card(parent, "接收监测")
        monitor.configure(padding=(14, 10))
        monitor.edge.grid(row=0, column=0, sticky="nsew", pady=(0, 13))
        controls = ttk.Frame(monitor, style="Card.TFrame")
        controls.pack(fill="x", pady=(6, 6))
        self.receive_button = ttk.Button(controls, text="开始接收", style="Teal.TButton", command=self._receive)
        self.receive_button.pack(side="left")
        self.stop_button = ttk.Button(controls, text="停止接收", command=self._stop)
        self.stop_button.pack(side="left", padx=8)
        self.operation_var = tk.StringVar(value="等待设备 · 接收端独立解码")
        metrics = ttk.Frame(controls, style="Card.TFrame")
        metrics.pack(side="right", fill="x", expand=True, padx=(20, 0))
        self.metric_vars: dict[str, tk.StringVar] = {}
        for column, (key, title) in enumerate((("valid", "本次有效帧"), ("crc", "本次 CRC 拒绝"), ("rms", "RMS / codes"))):
            metrics.columnconfigure(column, weight=1, minsize=96)
            cell = ttk.Frame(metrics, style="Card.TFrame")
            cell.grid(row=0, column=column, sticky="ew")
            variable = tk.StringVar(value="—")
            self.metric_vars[key] = variable
            ttk.Label(cell, textvariable=variable, style="Metric.TLabel").pack(anchor="w")
            ttk.Label(cell, text=title, style="CardMuted.TLabel").pack(anchor="w")
        self.capture_var = tk.StringVar(value="采样周期：等待首个快照    最后有效帧：—")
        ttk.Label(monitor, textvariable=self.capture_var, style="CardMuted.TLabel").pack(anchor="w", pady=(6, 0))
        spectrum_card = self._card(parent, "接收频谱", "分段快照 · 更新周期包含串口传输时间，采样存在空档")
        spectrum_card.configure(padding=(14, 10))
        spectrum_card.edge.grid(row=1, column=0, sticky="nsew", pady=(0, 13))
        self.carrier_var = tk.StringVar(value="载波估计：—  MHz（板卡时钟参考）")
        ttk.Label(spectrum_card, textvariable=self.carrier_var, style="CardMuted.TLabel").pack(side="bottom", anchor="w")
        self.spectrum_time_var = tk.StringVar(value="最后采集：—")
        ttk.Label(spectrum_card, textvariable=self.spectrum_time_var, style="CardMuted.TLabel").pack(side="bottom", anchor="w", pady=(0, 2))
        self.spectrum = SpectrumCanvas(spectrum_card)
        self.spectrum.pack(fill="both", expand=True)
        history = self._card(parent, "已解码文本 · 来自独立接收设备")
        history.configure(padding=(14, 10))
        history.edge.grid(row=2, column=0, sticky="nsew")
        self._build_history(history, height=3)

    def _build_history(self, parent: ttk.Frame, height: int = 7) -> None:
        self.selected_message_var = tk.StringVar(value="选择记录可查看完整文本。")
        ttk.Label(parent, textvariable=self.selected_message_var, style="CardMuted.TLabel", wraplength=640).pack(side="bottom", anchor="w", pady=(8, 0))
        box = ttk.Frame(parent, style="Card.TFrame")
        box.pack(fill="both", expand=True, pady=(3, 0))
        self.history = ttk.Treeview(box, columns=("time", "id", "text", "bytes", "result"), show="headings", height=height)
        for key, title, width, stretch in (("time", "时间", 77, False), ("id", "消息编号", 130, False),
                                            ("text", "真实文本内容", 220, True), ("bytes", "字节", 48, False),
                                            ("result", "状态", 66, False)):
            self.history.heading(key, text=title)
            self.history.column(key, width=width, minwidth=width if not stretch else 100, stretch=stretch,
                                anchor="w" if key == "text" else "center")
        scroll = ttk.Scrollbar(box, orient="vertical", command=self.history.yview)
        self.history.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.history.pack(side="left", fill="both", expand=True)
        self.history.tag_configure("duplicate", foreground=COLORS["muted"])
        self.history.bind("<<TreeviewSelect>>", self._select_message)

    def _submit(self, action: str, **kwargs: Any) -> None:
        if self.closing and action != "close":
            return
        try:
            self.controller.submit(action, **kwargs)
        except Exception as error:
            self._log(f"提交 {action} 失败：{error}", "error")
            self.footer_var.set(str(error))

    def _connect(self) -> None:
        port = self.devices.get(self.port_var.get())
        if port:
            parameters = {"port": port}
            if self.role == "sender":
                relay = self.devices.get(self.relay_port_var.get())
                if not relay or relay == port:
                    self.footer_var.set("发送板和转发板须选择两个不同的 DEBUG 串口")
                    return
                parameters["relay_port"] = relay
            self.status_var.set("正在连接…")
            self.connect_button.configure(state="disabled")
            self._submit("connect", **parameters)

    def _configure(self) -> None:
        try:
            values = {key: float(variable.get()) for key, variable in self.requested.items()}
            if not all(math.isfinite(value) for value in values.values()):
                raise ValueError("参数必须为有限数字")
            if self.role == "sender":
                if values["tx_lo_mhz"] != 900 or not 50 <= values["tx_atten_db"] <= 89:
                    raise ValueError("TX 本振固定 900 MHz，衰减须为 50–89 dB")
            elif (values["rx_lo_mhz"] != 1000.75 or values["expected_rf_mhz"] not in (1000.5, 1001.5)
                  or not 0 <= values["rx_gain_db"] <= 30):
                raise ValueError("RX 本振固定 1000.75 MHz，增益须为 0–30 dB")
        except ValueError as error:
            self.footer_var.set(f"参数未提交：{error}")
            self._log(f"参数未提交：{error}", "warning")
            return
        for readback in self.readbacks.values():
            readback.set("等待设备确认")
        self._submit("configure", **values)

    def _text_changed(self, _event: tk.Event | None = None) -> None:
        if not self.message_input.edit_modified():
            return
        self.message_input.edit_modified(False)
        self._update_controls()

    def _send(self) -> None:
        text = self.message_input.get("1.0", "end-1c")
        count = len(text.encode("utf-8"))
        if not 1 <= count <= 32:
            self.footer_var.set("发送内容须为 1–32 个 UTF-8 字节")
            return
        self._submit("send", text=text)

    def _receive(self) -> None:
        self.receiving = True
        self.operation_var.set("采集与串口传输中…")
        self._update_controls()
        # The controller owns continuous snapshots and prevents overlapping captures.
        self._submit("receive")

    def _stop(self) -> None:
        self.receiving = False
        self.operation_var.set("正在停止，等待在途操作结束…")
        self.stop_button.configure(state="disabled")
        self._submit("stop")

    def _update_controls(self) -> None:
        idle = self.connected and self.state in {"ready", "stopped", "error"} and not self.receiving and not self.closing
        connecting = self.state == "connecting"
        if self.role == "sender":
            self.telemetry_button.configure(state="disabled" if self.closing else "normal")
        selected = self.devices.get(self.port_var.get())
        device_selection_valid = bool(selected)
        if self.role == "sender":
            relay_selected = self.devices.get(self.relay_port_var.get())
            device_selection_valid = bool(selected and relay_selected and relay_selected != selected)
            self.relay_port_combo.configure(state="disabled" if self.connected or connecting or self.closing else "readonly")
        self.connect_button.configure(state="normal" if not self.connected and not connecting and device_selection_valid and not self.closing else "disabled")
        self.disconnect_button.configure(state="normal" if self.connected and not self.closing else "disabled")
        self.refresh_button.configure(state="disabled" if self.closing else "normal")
        self.port_combo.configure(state="disabled" if self.connected or connecting or self.closing else "readonly")
        self.configure_button.configure(state="normal" if idle else "disabled")
        for entry in self.setting_entries:
            entry.configure(state=("readonly" if isinstance(entry, ttk.Combobox) else "normal") if idle else "disabled")
        self.stop_button.configure(state="normal" if self.connected and not self.closing and (self.receiving or self.state in {"receiving", "transmitting", "busy"}) else "disabled")
        if self.role == "sender":
            count = len(self.message_input.get("1.0", "end-1c").encode("utf-8"))
            self.byte_var.set(f"{count} / 32 字节" + (" · 已超出上限" if count > 32 else ""))
            self.byte_label.configure(foreground=COLORS["danger"] if count > 32 else COLORS["muted"])
            can_send = self.connected and self.state in {"ready", "stopped", "transmitting"} and not self.closing
            self.send_button.configure(state="normal" if can_send and 1 <= count <= 32 else "disabled")
        else:
            self.receive_button.configure(state="normal" if idle else "disabled")

    def _drain_events(self) -> None:
        if self.closed:
            return
        for _ in range(100):
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            try:
                self._handle_event(event)
            except Exception as error:
                self._log(f"界面处理事件失败：{error}", "error")
            if self.closed:
                return
        self._poll_id = self.root.after(60, self._drain_events)

    def _handle_event(self, event: dict[str, Any]) -> None:
        kind = event.get("type", event.get("event"))
        if kind == "devices":
            current = self.port_var.get()
            self.devices = {str(item.get("label") or item["port"]): str(item["port"]) for item in event.get("devices", [])}
            self.port_combo.configure(values=list(self.devices))
            if current not in self.devices:
                self.port_var.set("")
            if self.role == "sender":
                current_relay = self.relay_port_var.get()
                self.relay_port_combo.configure(values=list(self.devices))
                if current_relay not in self.devices:
                    self.relay_port_var.set("")
            self.footer_var.set(f"发现 {len(self.devices)} 个串口设备" if self.devices else "未发现串口设备 · 可连接设备后刷新")
        elif kind == "status":
            self.state = event.get("state", self.state)
            names = {"disconnected": "未连接", "connecting": "正在连接", "ready": "已连接 · 就绪", "transmitting": "正在发射",
                     "receiving": "正在接收", "stopped": "已停止", "error": "操作异常", "busy": "设备处理中"}
            self.status_var.set(names.get(self.state, str(self.state)))
            message = str(event.get("message", ""))
            if message:
                self.footer_var.set(message)
                self.operation_var.set(message)
            if self.state in {"ready", "transmitting", "receiving", "stopped"}:
                self.connected = True
            elif self.state in {"disconnected", "connecting"}:
                self.connected = False
            if self.state in {"disconnected", "stopped", "error"}:
                self.receiving = False
            color = COLORS["danger"] if self.state == "error" else COLORS["teal"] if self.connected else COLORS["muted"]
            self.status_dot.configure(foreground=color)
            if self.state == "disconnected":
                self.identity_var.set("设备已断开 · 选择本机设备后重新连接")
                for readback in self.readbacks.values():
                    readback.set("尚未回读")
                if self.role == "sender":
                    self.relay_frequency_var.set("RX — MHz  →  TX — MHz")
                    self.relay_mode_var.set("模式 —    衰减 — dB")
        elif kind == "identity":
            identity = event.get("identity", {})
            self.connected = True
            self.identity_var.set(f"设备 {identity.get('model', '—')}    序列号 {identity.get('serial', '—')}    {identity.get('port', '')}")
        elif kind == "settings":
            self._settings_event(event.get("values", {}))
        elif kind == "relay_telemetry" and self.role == "sender":
            if self.telemetry_window is not None and not self.telemetry_window.closed:
                self.telemetry_window.show_relay(event)
        elif kind == "tx" and self.role == "sender":
            self._append_message(event, "已发送")
            self.operation_var.set(f"消息 {event.get('message_id', '—')} 已提交至发送设备")
        elif kind == "rx" and self.role == "receiver":
            self._receive_event(event)
        elif kind == "log":
            self._log(str(event.get("message", "")), str(event.get("level", "info")).lower())
        elif kind == "closed":
            self._station_closed = True
            if not self.closing:
                self.close()
            self._finish_close_if_ready()
            return
        self._update_controls()
        if self.closing:
            self.status_var.set("正在关闭 · 等待设备清理")

    def _settings_event(self, values: dict[str, Any]) -> None:
        for key, variable in self.readbacks.items():
            readback_key = key + "_readback"
            requested_key = key + "_requested"
            if requested_key in values:
                self.requested[key].set(str(values[requested_key]))
            if readback_key in values:
                value = values[readback_key]
                variable.set("未获得回读" if value is None else str(value))
            elif key.endswith("_mhz") and key.replace("_mhz", "_hz_readback") in values:
                variable.set(f"{float(values[key.replace('_mhz', '_hz_readback')]) / 1e6:g}")
            elif key == "expected_rf_mhz" and key in values:
                self.requested[key].set(str(values[key]))
                variable.set("解码先验")
            elif key in values:
                # Unqualified backend values are not silently described as readbacks.
                variable.set(f"返回：{values[key]}")
            else:
                variable.set("未提供回读")
        if self.role == "sender" and any(key.startswith("relay_") for key in values):
            rx = values.get("relay_rx_hz_readback")
            tx = values.get("relay_tx_hz_readback")
            self.relay_frequency_var.set(f"RX {float(rx) / 1e6:g} MHz  →  TX {float(tx) / 1e6:g} MHz" if rx is not None and tx is not None else "转发频率：未获得完整回读")
            self.relay_mode_var.set(f"模式 {values.get('relay_mode', '—')}    衰减 {values.get('relay_tx_atten_db_readback', '—')} dB")
        extra = {key: value for key, value in values.items() if not any(key.startswith(field) for field in self.readbacks)}
        if extra:
            self._log("设置回执：" + "; ".join(f"{key}={value}" for key, value in extra.items()))

    def _receive_event(self, event: dict[str, Any]) -> None:
        valid = event.get("valid_frames", 0)
        self.metric_vars["valid"].set(str(valid))
        self.metric_vars["crc"].set(str(event.get("crc_rejected", 0)))
        rms = event.get("rms_codes")
        self.metric_vars["rms"].set(f"{float(rms):.1f}" if rms is not None else "—")
        timestamp = self._time_label(event.get("received_at"))
        self.spectrum_time_var.set(f"最后快照：{timestamp} · 频率 MHz / 电平 dBFS")
        if valid:
            self.last_valid_time = timestamp
        duration = event.get("capture_seconds")
        duration_text = f"{float(duration):.1f} s" if duration is not None else "—"
        self.capture_var.set(f"本次采样/传输周期：{duration_text}    最后有效帧：{self.last_valid_time}")
        self.spectrum.set_spectrum(event.get("spectrum"))
        carrier = event.get("carrier_hz")
        self.carrier_var.set(f"载波估计：{float(carrier) / 1e6:.6f} MHz（板卡时钟参考）" if carrier is not None else "载波估计：未检出（板卡时钟参考）")
        for message in event.get("messages", []):
            self._append_message(message, "重复帧" if message.get("duplicate") else "已解码", timestamp)
        self.operation_var.set("本次快照完成 · 继续采集" if self.receiving else "本次快照完成")

    @staticmethod
    def _time_label(value: Any = None) -> str:
        if value is None:
            return datetime.now().strftime("%H:%M:%S")
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value).strftime("%H:%M:%S")
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone().strftime("%H:%M:%S")
        except ValueError:
            return str(value)

    def _append_message(self, message: dict[str, Any], result: str, timestamp: str | None = None) -> None:
        payload = message.get("payload_bytes")
        count = len(payload) if isinstance(payload, (bytes, bytearray, list, tuple)) else payload
        text = str(message.get("text", ""))
        if count is None:
            count = len(text.encode("utf-8"))
        values = (timestamp or self._time_label(), message.get("message_id", "—"), text, count, result)
        row = self.history.insert("", "end", values=values, tags=("duplicate",) if message.get("duplicate") else ())
        self.history.see(row)
        self.message_rows += 1
        if self.message_rows > 500:
            self.history.delete(self.history.get_children()[0])
            self.message_rows -= 1

    def _select_message(self, _event: tk.Event) -> None:
        selection = self.history.selection()
        if selection:
            values = self.history.item(selection[0], "values")
            self.selected_message_var.set(f"消息 {values[1]}：{values[2]}")

    def _toggle_log(self) -> None:
        if self.log_visible.get():
            self.log_frame.pack(side="bottom", fill="x", pady=(7, 0), before=self.content)
        else:
            self.log_frame.pack_forget()

    def _log(self, message: str, level: str = "info") -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{self._time_label()}  {level.upper():7s}  {message}\n", level)
        if int(self.log_text.index("end-1c").split(".")[0]) > 1000:
            self.log_text.delete("1.0", "101.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        if level in {"error", "warning"}:
            self.footer_var.set(message)

    def close(self) -> None:
        if self.closing:
            self.log_visible.set(True)
            self._toggle_log()
            return
        self.closing = True
        self.receiving = False
        self.status_var.set("正在关闭 · 等待设备清理")
        self.footer_var.set("正在停止收发并清理设备连接；收到完成回执后关闭窗口。")
        self._update_controls()
        if self.telemetry_window is not None and not self.telemetry_window.closed:
            self.telemetry_window.close()
        self._submit("close")
        self._close_warning_id = self.root.after(12000, self._close_wait_notice)

    def _close_wait_notice(self) -> None:
        if not self.closed:
            self.footer_var.set("设备仍在清理中，窗口保持打开。串口快照结束后将继续关闭。")
            self._log("关闭尚未完成：仍在等待控制器清理回执，未强制退出。", "warning")
            self.log_visible.set(True)
            self._toggle_log()

    def open_telemetry(self) -> None:
        if self.role != "sender" or self.closing:
            return
        if self.telemetry_window is not None and not self.telemetry_window.closed:
            self.telemetry_window.show()
            return
        from .telemetry_window import TelemetryWindow
        try:
            self.telemetry_window = TelemetryWindow(
                self.root, read_relay=lambda: self._submit("read_relay"),
                on_closed=self._telemetry_closed, controller_factory=self.telemetry_controller_factory,
                can_read_relay=lambda: self.connected and not self.closing)
        except Exception as error:
            self._log(f"测控监控启动失败：{error}", "error")

    def _telemetry_closed(self) -> None:
        self.telemetry_window = None
        self._finish_close_if_ready()

    def _finish_close_if_ready(self) -> None:
        if not self._station_closed:
            return
        if self.telemetry_window is not None and not self.telemetry_window.closed:
            self.footer_var.set("业务控制器已清理，继续等待测控监控串口关闭回执。")
            return
        self.closed = True
        if self._poll_id:
            self.root.after_cancel(self._poll_id)
        if self._close_warning_id:
            self.root.after_cancel(self._close_warning_id)
        self.root.destroy()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="CCSDS 独立发送端 / 接收端桌面站")
    parser.add_argument("--role", choices=("sender", "receiver"), required=True, help="此应用的独立工作角色")
    parser.add_argument("--log-dir", default=None, help="设备诊断日志保存目录")
    args = parser.parse_args(argv)
    root = tk.Tk()
    StationApp(root, args.role, log_dir=args.log_dir)
    root.mainloop()


if __name__ == "__main__":
    main()
