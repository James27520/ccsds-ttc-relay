"""Read-only TM1 monitor. USB status and independent SPI evidence stay separate."""
from __future__ import annotations

from datetime import datetime
import queue
import time
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from .app import COLORS


ORIGINS = {0: "UNKNOWN · 来源未知", 1: "ADC_NORMAL · ADC 正常输入",
           2: "ADC_TEST · ADC 测试", 3: "SYNTHETIC · 软件合成",
           4: "UART_NETTEST · 串口网络测试"}


class TelemetryWindow:
    """A Toplevel whose controller is closed before the window is destroyed."""

    def __init__(self, parent: tk.Misc, read_relay: Callable[[], None],
                 on_closed: Callable[[], None], controller_factory: Callable[..., Any] | None = None,
                 log_dir: str | None = None, can_read_relay: Callable[[], bool] | None = None):
        self.read_relay = read_relay
        self.on_closed = on_closed
        self.can_read_relay = can_read_relay or (lambda: True)
        self.events: queue.Queue[dict[str, Any]] = queue.Queue()
        self.closed = self.closing = self.connected = False
        self.devices: dict[str, str] = {}
        self.received_at: float | None = None
        self.relay_received_at: float | None = None
        self.snapshot: dict[str, int] = {}
        self._poll_id: str | None = None
        self._wait_id: str | None = None
        self.window = tk.Toplevel(parent)
        self.window.title("NTN 测控状态 · 只读监控")
        self.window.geometry("1080x900+45+45")
        self.window.minsize(930, 770)
        self.window.configure(background=COLORS["background"])
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        if controller_factory is None:
            from .telemetry import TelemetryController
            controller_factory = TelemetryController
        try:
            self.controller = controller_factory(self.events.put, log_dir=log_dir)
        except Exception:
            self.window.destroy()
            raise
        self._poll_id = self.window.after(80, self._drain_events)
        self._submit("discover")
        self._update_controls()

    def _card(self, parent: tk.Misc, title: str, subtitle: str) -> ttk.Frame:
        edge = tk.Frame(parent, background=COLORS["line"])
        card = ttk.Frame(edge, style="Card.TFrame", padding=15)
        card.pack(fill="both", expand=True, padx=1, pady=1)
        card.edge = edge  # type: ignore[attr-defined]
        ttk.Label(card, text=title, style="CardHeading.TLabel").pack(anchor="w")
        ttk.Label(card, text=subtitle, style="CardMuted.TLabel", wraplength=440).pack(anchor="w", pady=(4, 9))
        return card

    def _build(self) -> None:
        main = ttk.Frame(self.window, padding=20)
        main.pack(fill="both", expand=True)
        header = ttk.Frame(main)
        header.pack(fill="x", pady=(0, 10))
        ttk.Label(header, text="测控状态", style="Heading.TLabel").pack(side="left")
        tk.Label(header, text="USB DEBUG 状态回传，非 DAC 射频下行", background=COLORS["pale"],
                 foreground=COLORS["teal"], padx=12, pady=9,
                 font=("Microsoft YaHei UI", 10, "bold")).pack(side="right")
        connection = self._card(main, "遥控板 DEBUG", "每 2 秒只读 TM1，不发 ARM / nettest / RF 指令；请选择遥控板串口。")
        connection.edge.pack(fill="x", pady=(0, 10))
        row = ttk.Frame(connection, style="Card.TFrame")
        row.pack(fill="x")
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(row, textvariable=self.port_var, width=34, state="readonly")
        self.port_combo.pack(side="left", padx=(0, 8))
        self.port_combo.bind("<<ComboboxSelected>>", lambda _event: self._update_controls())
        self.refresh_button = ttk.Button(row, text="刷新", command=lambda: self._submit("discover"))
        self.refresh_button.pack(side="left", padx=(0, 8))
        self.connect_button = ttk.Button(row, text="连接监控", style="Primary.TButton", command=self._connect)
        self.connect_button.pack(side="left", padx=(0, 8))
        self.disconnect_button = ttk.Button(row, text="断开", command=lambda: self._submit("disconnect"))
        self.disconnect_button.pack(side="left", padx=(0, 8))
        self.query_button = ttk.Button(row, text="立即查询", command=lambda: self._submit("query"))
        self.query_button.pack(side="left")
        self.status_var = tk.StringVar(value="未连接")
        ttk.Label(connection, textvariable=self.status_var, style="CardMuted.TLabel", wraplength=990).pack(anchor="w", pady=(8, 0))
        self.counters_var = tk.StringVar(value="运行 —    事件 —    network —    armed —    pending —    decoded —    applied —    failures —")
        ttk.Label(main, textvariable=self.counters_var, style="Muted.TLabel", wraplength=1000).pack(anchor="w", pady=(0, 7))
        self.freshness_var = tk.StringVar(value="TM1 最后更新：未知 · 尚未收到状态")
        self.freshness_label = ttk.Label(main, textvariable=self.freshness_var, style="Muted.TLabel")
        self.freshness_label.pack(anchor="w", pady=(0, 10))

        stage_area = ttk.Frame(main)
        stage_area.pack(fill="both", expand=True)
        stage_canvas = tk.Canvas(stage_area, background=COLORS["background"], highlightthickness=0, width=1, height=440)
        stage_scroll = ttk.Scrollbar(stage_area, orient="vertical", command=stage_canvas.yview)
        stage_canvas.configure(yscrollcommand=stage_scroll.set)
        stage_scroll.pack(side="right", fill="y")
        stage_canvas.pack(side="left", fill="both", expand=True)
        grid = ttk.Frame(stage_canvas)
        stage_window = stage_canvas.create_window((0, 0), window=grid, anchor="nw")
        stage_canvas.bind("<Configure>", lambda event: stage_canvas.itemconfigure(stage_window, width=event.width))
        grid.bind("<Configure>", lambda _event: stage_canvas.configure(scrollregion=stage_canvas.bbox("all")))
        for number in range(2):
            grid.columnconfigure(number, weight=1, uniform="stage")
            grid.rowconfigure(number, weight=1, uniform="stage")
        self.stage_vars: dict[str, dict[str, tk.StringVar]] = {}
        self.origin_labels: dict[str, tk.Label] = {}
        for index, (prefix, title, subtitle) in enumerate((
                ("d", "01  已解码", "仅表示解码记录，不代表 UDP 已发出。"),
                ("s", "02  UDP 发送尝试", "发送尝试与收到匹配 ACK 分别记录。"),
                ("a", "03  匹配 ACK", "ACK 携带频率值，不等同于独立 SPI 回读。"))):
            card = self._card(grid, title, subtitle)
            card.edge.grid(row=index // 2, column=index % 2, sticky="nsew",
                           padx=(0, 10) if index % 2 == 0 else 0, pady=(0, 10) if index < 2 else 0)
            variables = {key: tk.StringVar(value="未知" if key == "state" else "—") for key in ("state", "detail", "frequency", "extra")}
            self.stage_vars[prefix] = variables
            ttk.Label(card, textvariable=variables["state"], style="CardHeading.TLabel").pack(anchor="w")
            badge = tk.Label(card, text="UNKNOWN · 来源未知", background="#EEF2F6", foreground=COLORS["muted"],
                             font=("Microsoft YaHei UI", 9, "bold"), padx=8, pady=4)
            badge.pack(anchor="w", pady=(6, 8))
            self.origin_labels[prefix] = badge
            for key in ("detail", "frequency", "extra"):
                ttk.Label(card, textvariable=variables[key], style="CardMuted.TLabel", wraplength=440).pack(anchor="w", pady=(0, 4))

        spi = self._card(grid, "04  独立 SPI 读回", "从已连接的转发板调试口读取当前频率。")
        spi.edge.grid(row=1, column=1, sticky="nsew")
        self.spi_var = tk.StringVar(value="未知 · 尚未请求独立 SPI 读回")
        self.spi_details_var = tk.StringVar(value="RX — MHz  /  TX — MHz\n衰减 — dB  /  接收增益 — dB  /  模式 —")
        self.spi_time_var = tk.StringVar(value="SPI 最后更新：未知")
        ttk.Label(spi, textvariable=self.spi_var, style="CardHeading.TLabel").pack(anchor="w", pady=(0, 6))
        ttk.Label(spi, textvariable=self.spi_details_var, style="CardMuted.TLabel", wraplength=440).pack(anchor="w", pady=(0, 6))
        ttk.Label(spi, textvariable=self.spi_time_var, style="CardMuted.TLabel").pack(anchor="w", pady=(0, 7))
        self.spi_button = ttk.Button(spi, text="读取转发板 SPI", command=self._request_relay)
        self.spi_button.pack(anchor="w")

        footer = ttk.Frame(main)
        footer.pack(side="bottom", fill="x", before=stage_area, pady=(10, 0))
        self.footer_var = tk.StringVar(value="TM1 spi_valid=0：状态帧本身不提供独立 SPI 证明。")
        ttk.Label(footer, textvariable=self.footer_var, style="Muted.TLabel", wraplength=880).pack(anchor="w", pady=(0, 5))
        self.log_text = tk.Text(footer, height=2, background="#EAF0F6", foreground=COLORS["ink"],
                                relief="flat", font=("Microsoft YaHei UI", 9), wrap="word", state="disabled", padx=9, pady=6)
        self.log_text.pack(fill="x")

    def _submit(self, action: str, **kwargs: Any) -> None:
        if self.closing and action != "close":
            return
        try:
            self.controller.submit(action, **kwargs)
        except Exception as error:
            self._log(f"{action} 提交失败：{error}")

    def _connect(self) -> None:
        port = self.devices.get(self.port_var.get())
        if port:
            self.status_var.set("正在连接，只读取状态…")
            self.connect_button.configure(state="disabled")
            self._submit("connect", port=port)

    def _request_relay(self) -> None:
        if self.closing or not self.can_read_relay():
            return
        self.footer_var.set("正在查询转发板，等待独立频率读回。")
        self.read_relay()

    def _update_controls(self) -> None:
        live = not self.closing
        self.port_combo.configure(state="readonly" if live and not self.connected else "disabled")
        self.refresh_button.configure(state="normal" if live else "disabled")
        self.connect_button.configure(state="normal" if live and not self.connected and self.port_var.get() in self.devices else "disabled")
        for button in (self.disconnect_button, self.query_button):
            button.configure(state="normal" if live and self.connected else "disabled")
        self.spi_button.configure(state="normal" if live and self.can_read_relay() else "disabled")

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
                self._log(f"状态显示失败：{error}")
            if self.closed:
                return
        self._refresh_freshness()
        self._update_controls()
        self._poll_id = self.window.after(100, self._drain_events)

    def _handle_event(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        if kind == "devices":
            self.devices = {str(item.get("label") or item["port"]): str(item["port"]) for item in event.get("devices", [])}
            self.port_combo.configure(values=list(self.devices))
            if self.port_var.get() not in self.devices:
                self.port_var.set("")
        elif kind == "status":
            state = event.get("state")
            if state == "connected":
                self.connected = True
            elif state in {"disconnected", "error"}:
                self.connected = False
            self.status_var.set(str(event.get("message") or {"connected": "已连接 · 只读查询", "disconnected": "未连接", "error": "监控异常"}.get(state, state)))
        elif kind == "telemetry":
            self.snapshot = dict(event.get("snapshot", {}))
            self.received_at = float(event["received_at"])
            self._show_snapshot()
        elif kind == "log":
            self._log(str(event.get("message", "")))
        elif kind == "closed":
            self.closed = True
            for callback in (self._poll_id, self._wait_id):
                if callback:
                    self.window.after_cancel(callback)
            self.window.destroy()
            self.on_closed()
            return
        self._refresh_freshness()
        self._update_controls()
        if self.closing:
            self.status_var.set("正在关闭监控，等待串口清理回执…")

    def _show_snapshot(self) -> None:
        data = self.snapshot
        self.counters_var.set(f"运行 {data.get('uptime_ms', 0) / 1000:.1f} s    事件 {data.get('events', '—')}    network {data.get('network', '—')}    armed {data.get('armed', '—')}    pending {data.get('pending', '—')}    "
                              f"decoded {data.get('decoded', '—')}    applied {data.get('applied', '—')}    failures {data.get('failures', '—')}（累计）")
        for prefix, variables in self.stage_vars.items():
            if not data.get(prefix + "_valid", 0):
                variables["state"].set("未知 · 尚无有效记录")
                for key in ("detail", "frequency", "extra"):
                    variables[key].set("—")
                self.origin_labels[prefix].configure(text=ORIGINS[0], background="#EEF2F6", foreground=COLORS["muted"])
                continue
            origin = data.get(prefix + "_origin", 0)
            real_adc = origin == 1
            self.origin_labels[prefix].configure(text=ORIGINS.get(origin, f"UNKNOWN ({origin}) · 来源未知"),
                                                  background=COLORS["pale"] if real_adc else "#FFF1D9",
                                                  foreground=COLORS["teal"] if real_adc else "#8B611D")
            variables["state"].set("有记录" + (" · 测试来源" if origin in (2, 3, 4) else ""))
            variables["detail"].set(f"事件 {data.get(prefix + '_event', '—')}    空口序号 {data.get(prefix + '_air_seq', '—')}")
            variables["frequency"].set(f"请求 RX {data.get(prefix + '_rx_mhz', '—')} MHz  /  TX {data.get(prefix + '_tx_mhz', '—')} MHz")
            if prefix == "s":
                variables["extra"].set(f"UDP 序号 {data.get('s_udp_seq', '—')}    尝试计数 {data.get('s_count', '—')}    rc {data.get('s_rc', '—')}")
            elif prefix == "a":
                variables["extra"].set(f"UDP 序号 {data.get('a_udp_seq', '—')}    ACK rc {data.get('a_rc', '—')}\nACK 携带 RX {data.get('a_rx_hz', '—')} Hz / TX {data.get('a_tx_hz', '—')} Hz")
            else:
                variables["extra"].set("解码阶段；后续发送与执行见各自记录。")

    def show_relay(self, event: dict[str, Any]) -> None:
        """Display only independent worker readbacks; TM1 ACK values never reach this card."""
        if self.closed:
            return
        values = event.get("values", {})
        rx, tx = values.get("relay_rx_hz_readback"), values.get("relay_tx_hz_readback")
        if rx is None or tx is None:
            self.footer_var.set("独立 SPI 回读不完整；未更新 SPI 证据。")
            return
        self.relay_received_at = float(event["received_at"])
        self.spi_var.set("已获得独立 SPI 回读")
        self.footer_var.set("转发板频率已读回；请结合各项更新时间判断当前状态。")
        self.spi_details_var.set(f"RX {float(rx) / 1e6:g} MHz  /  TX {float(tx) / 1e6:g} MHz\n"
                                 f"衰减 {values.get('relay_tx_atten_db_readback', '—')} dB  /  接收增益 {values.get('relay_rx_gain_db_readback', '—')} dB  /  模式 {values.get('relay_mode', '—')}")
        self._refresh_freshness()

    def _refresh_freshness(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        if self.received_at is not None:
            age = max(0, now - self.received_at)
            stale = age > 6
            self.freshness_var.set(f"TM1 最后更新：{datetime.fromtimestamp(self.received_at):%H:%M:%S} · {age:.1f} 秒前" +
                                   (" · 已过期（超过 6 秒），以下为历史状态" if stale else " · " + ("已连接" if self.connected else "已断开，保留历史")))
            self.freshness_label.configure(foreground=COLORS["danger"] if stale else COLORS["muted"])
        if self.relay_received_at is not None:
            age = max(0, now - self.relay_received_at)
            self.spi_time_var.set(f"SPI 最后更新：{datetime.fromtimestamp(self.relay_received_at):%H:%M:%S}" + (" · 已过期（超过 6 秒）" if age > 6 else f" · {age:.1f} 秒前"))

    def _log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{datetime.now():%H:%M:%S}  {message}\n")
        if int(self.log_text.index("end-1c").split(".")[0]) > 200:
            self.log_text.delete("1.0", "51.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def show(self) -> None:
        if not self.closed:
            self.window.deiconify()
            self.window.lift()

    def close(self) -> None:
        if self.closed or self.closing:
            return
        self.closing = True
        self.status_var.set("正在关闭监控，等待串口清理回执…")
        self._update_controls()
        self._submit("close")
        self._wait_id = self.window.after(8000, self._close_wait_notice)

    def _close_wait_notice(self) -> None:
        if not self.closed:
            self._log("监控串口仍在清理中，窗口继续等待 closed 回执，未强制退出。")
            self.status_var.set("关闭仍在等待；监控窗口保持打开，直到串口清理完成。")
