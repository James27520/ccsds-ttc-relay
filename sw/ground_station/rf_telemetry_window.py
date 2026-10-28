"""RF telemetry viewer. Opening only discovers available serial ports.

Only CRC-checked frame bytes populate telemetry. Report summaries, USB TM1 and
sender expectations are deliberately not inputs to the displayed records.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, ttk
from typing import Any, Callable

from .app import COLORS


def validated_snapshots(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Recheck payload+received CRC; never trust a telemetry/expected summary."""
    from sw.tools.telemetry_downlink import parse_frame
    if report.get("format") != "EXPERIMENTAL_ATM1_RF":
        raise ValueError("仅支持 EXPERIMENTAL_ATM1_RF 解码报告，不能导入 USB 状态或发送清单")
    snapshots = []
    for frame in report.get("frames", []):
        if frame.get("crc_valid") is not True:
            continue
        try:
            payload = bytes.fromhex(frame["payload_hex"])
            crc = frame["crc16"]
            if type(crc) is not int or not 0 <= crc <= 65535:
                continue
            snapshot = parse_frame(b"\xaa\xaa\x60" + payload + crc.to_bytes(2, "big"))
            for key in ("first_symbol_sample", "carrier_offset_hz"):
                value = frame.get(key)
                snapshot[key] = value if isinstance(value, (int, float)) and math.isfinite(value) else None
            snapshots.append(snapshot)
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
    return snapshots


class RFTelemetryWindow:
    """Finite online captures and offline files share the same CRC evidence view.

    decode_iq(raw_bytes, **sample_rate_hz/symbol_rate/expected_offset_hz/search_hz)
    returns an EXPERIMENTAL_ATM1_RF report containing original frame payload/CRC.
    Controller: factory(emit, log_dir=None), submit(action, **kwargs). Discover,
    read-only probe, binding/connect and each finite capture are explicit steps.
    """

    def __init__(self, parent: tk.Misc, on_closed: Callable[[], None],
                 decode_iq: Callable[..., dict[str, Any]] | None = None,
                 rf_telemetry_controller_factory: Callable[..., Any] | None = None,
                 log_dir: str | None = None):
        self.on_closed, self.decode_iq = on_closed, decode_iq
        self.closed = self.closing = False
        self.events: queue.Queue[dict[str, Any]] = queue.Queue()
        self.snapshots: list[dict[str, Any]] = []
        self.report_path: Path | None = None
        self._signature = None
        self._generation = 0
        self._busy = False
        self.devices: dict[str, str] = {}
        self.live_state = "disconnected"
        self.binding_token = None
        self._binding_ports = None
        self._probe_ports = None
        self._pending = None
        self._capture_pending = False
        self._live_generation = None
        self.window = tk.Toplevel(parent)
        self.window.title("RF 测控下行 · 单次采集 / 文件解码")
        self.window.geometry("1120x900+45+40")
        self.window.minsize(950, 730)
        self.window.configure(background=COLORS["background"])
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        try:
            if rf_telemetry_controller_factory is None:
                from .rf_live import RFTelemetryController
                rf_telemetry_controller_factory = RFTelemetryController
            self.controller = rf_telemetry_controller_factory(self.events.put, log_dir=log_dir)
        except Exception:
            self.window.destroy()
            raise
        self._poll_id = self.window.after(100, self._drain_events)
        self._refresh_id = self.window.after(2000, self._refresh)
        self._submit("discover")
        self._update_controls()

    def _build(self) -> None:
        shell = ttk.Frame(self.window)
        shell.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(shell, background=COLORS["background"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(shell, orient="vertical", command=self.canvas.yview)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        main = ttk.Frame(self.canvas, padding=20)
        content = self.canvas.create_window((0, 0), window=main, anchor="nw")
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(content, width=event.width))
        main.bind("<Configure>", lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.window.bind("<MouseWheel>", lambda event: self.canvas.yview_scroll(-int(event.delta / 120), "units")
                         if event.widget != self.frames else None)
        wrap_labels = []
        main.bind("<Configure>", lambda event: [label.configure(wraplength=max(event.width - 40, 200)) for label in wrap_labels], add="+")
        ttk.Label(main, text="RF 测控下行", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(main, text="单次在线采集 / 文件解码 · USB TM1 状态在独立窗口查看；连接后须显式请求一次采集。",
                  style="Muted.TLabel").pack(anchor="w", pady=(3, 12))
        self._build_live(main)
        row = ttk.Frame(main)
        row.pack(fill="x")
        self.iq_button = ttk.Button(row, text="选择 IQ 文件并解码", style="Primary.TButton", command=self._choose_iq)
        self.iq_button.pack(side="left")
        self.json_button = ttk.Button(row, text="导入已有解码 JSON", command=self._choose_report)
        self.json_button.pack(side="left", padx=8)
        self.auto_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="每 2 秒刷新选定 JSON", variable=self.auto_var).pack(side="left")
        settings = ttk.Frame(main)
        settings.pack(fill="x", pady=9)
        ttk.Label(settings, text="离线参数", style="Muted.TLabel").pack(side="left", padx=(0, 10))
        self.parameters = {}
        for label, key, value in (("采样 Hz", "sample_rate_hz", "2500000"), ("符号 / 秒", "symbol_rate", "100000"),
                                  ("预期偏移 Hz", "expected_offset_hz", "500000"), ("搜索 ±Hz", "search_hz", "20000")):
            ttk.Label(settings, text=label).pack(side="left", padx=(0, 5))
            variable = tk.StringVar(value=value)
            self.parameters[key] = variable
            ttk.Entry(settings, textvariable=variable, width=11).pack(side="left", padx=(0, 10))
        ttk.Label(main, text="IQ：有符号 12 位扩展至 int16 小端 I,Q；长记录需滑窗搜索。参数只用于离线解调。",
                  style="Muted.TLabel").pack(anchor="w")
        self.source_var = tk.StringVar(value="接收途径：尚未加载文件；文件来源需结合采集日志核实。")
        self.digest_var = tk.StringVar(value="IQ 路径 / SHA256：—")
        self.time_var = tk.StringVar(value="文件时间：—（文件修改时间不是射频接收时间）")
        self.status_var = tk.StringVar(value="尚无 CRC 有效 ATM1 帧；不使用发送端预期值补齐结果。")
        for variable in (self.source_var, self.digest_var, self.time_var, self.status_var):
            label = ttk.Label(main, textvariable=variable, style="Muted.TLabel", wraplength=1050)
            label.pack(anchor="w", pady=(5, 0))
            wrap_labels.append(label)
        area = ttk.Frame(main)
        area.pack(fill="both", pady=(12, 8))
        columns = ("sequence", "uptime", "sample", "offset")
        self.frames = ttk.Treeview(area, columns=columns, show="headings", height=5)
        for key, text in zip(columns, ("CRC 有效帧序号", "板端 uptime / ms", "文件采样位置", "实测载波偏移 / Hz")):
            self.frames.heading(key, text=text)
            self.frames.column(key, width=185, stretch=True)
        scroll = ttk.Scrollbar(area, orient="vertical", command=self.frames.yview)
        self.frames.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.frames.pack(fill="both", expand=True)
        self.frames.bind("<<TreeviewSelect>>", lambda _event: self._select())
        records = ttk.Frame(main)
        records.pack(fill="x")
        self.record_vars = {}
        for index, (key, title) in enumerate((("decoded_record", "已解码"), ("send_record", "UDP 发送尝试"), ("ack_record", "匹配 ACK"))):
            records.columnconfigure(index, weight=1, uniform="record")
            card = ttk.Frame(records, style="Card.TFrame", padding=12)
            card.grid(row=0, column=index, sticky="nsew", padx=(0, 8) if index < 2 else 0)
            ttk.Label(card, text=title, style="CardHeading.TLabel").pack(anchor="w")
            variable = tk.StringVar(value="未知 · 无有效帧")
            self.record_vars[key] = variable
            label = ttk.Label(card, textvariable=variable, style="CardMuted.TLabel", wraplength=260)
            label.pack(anchor="w", pady=(8, 0))
            card.bind("<Configure>", lambda event, target=label: target.configure(wraplength=max(event.width - 24, 120)))
        footer = ttk.Label(main, text="实验 ATM1 / AAAA-LEN-CRC16；不表示完整 CCSDS 符合性。重复快照不等于独立事件。\n"
                  "ACK 为远端应答，不能代替独立 SPI 回读。序号/uptime 可在重启后重复，未提供唯一启动身份或认证。",
                  style="Muted.TLabel", wraplength=1050)
        footer.pack(anchor="w", pady=(10, 0))
        wrap_labels.append(footer)

    def _build_live(self, main: ttk.Frame) -> None:
        card = ttk.Frame(main, style="Card.TFrame", padding=14)
        card.pack(fill="x", pady=(0, 14))
        ttk.Label(card, text="在线 RF 下行 · 每次约 17 秒", style="CardHeading.TLabel").pack(anchor="w")
        ttk.Label(card, text="固定 DAC 90.5 MHz / 接收 LO 90 MHz / 100 ksym/s；不是连续实时收发。",
                  style="CardMuted.TLabel").pack(anchor="w", pady=(4, 9))
        self.adda_port_var, self.rx_port_var = tk.StringVar(), tk.StringVar()
        self.adda_port_combo = self.rx_port_combo = None
        for label, variable, key in (("遥控板 DEBUG", self.adda_port_var, "adda"),
                                     ("下行接收 SDR DEBUG", self.rx_port_var, "rx")):
            row = ttk.Frame(card, style="Card.TFrame")
            row.pack(fill="x", pady=(0, 5))
            ttk.Label(row, text=label, style="Card.TLabel", width=23).pack(side="left")
            combo = ttk.Combobox(row, textvariable=variable, state="readonly", width=48)
            combo.pack(side="left", fill="x", expand=True)
            setattr(self, key + "_port_combo", combo)
            variable.trace_add("write", lambda *_args: self._ports_changed())
        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x", pady=(5, 4))
        self.discover_button = ttk.Button(row, text="刷新端口", command=lambda: self._submit("discover"))
        self.probe_button = ttk.Button(row, text="只读核验", command=self._probe)
        self.connect_button = ttk.Button(row, text="绑定连接", command=self._connect)
        self.disconnect_button = ttk.Button(row, text="断开", command=self._disconnect)
        for button in (self.discover_button, self.probe_button, self.connect_button, self.disconnect_button):
            button.pack(side="left", padx=(0, 7))
        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x", pady=(4, 5))
        self.capture_button = ttk.Button(row, text="发送并接收一次", style="Primary.TButton", command=lambda: self._capture(True))
        self.sample_button = ttk.Button(row, text="仅采样", command=lambda: self._capture(False))
        self.stop_button = ttk.Button(row, text="停止", command=self._stop)
        for button in (self.capture_button, self.sample_button, self.stop_button):
            button.pack(side="left", padx=(0, 7))
        self.live_status_var = tk.StringVar(value="未连接 · 先选择两个不同串口，再只读核验。")
        self.binding_var = tk.StringVar(value="绑定身份：尚未核验")
        self.log_var = tk.StringVar(value="若串口被占用，请关闭该端口的 USB TM1 监控或主业务连接后重试。")
        for variable in (self.live_status_var, self.binding_var, self.log_var):
            label = ttk.Label(card, textvariable=variable, style="CardMuted.TLabel", wraplength=1000)
            label.pack(anchor="w", pady=(4, 0))
            # This card has 28 pixels less available width than the main area.
            card.bind("<Configure>", lambda event, target=label: target.configure(wraplength=max(event.width - 28, 200)), add="+")

    def _ports(self):
        return self.devices.get(self.rx_port_var.get()), self.devices.get(self.adda_port_var.get())

    def _distinct_ports(self) -> bool:
        ports = self._ports()
        return bool(all(ports) and str(ports[0]).casefold() != str(ports[1]).casefold())

    def _ports_changed(self) -> None:
        self.binding_token = self._binding_ports = None
        self._probe_ports = None
        self.binding_var.set("绑定身份：端口选择已更改，需重新只读核验")
        if self.live_state == "probed":
            self.live_state = "disconnected"
        self._update_controls()

    def _submit(self, action: str, **kwargs: Any) -> bool:
        if self.closed or (self.closing and action != "close"):
            return False
        try:
            self.controller.submit(action, **kwargs)
            return True
        except Exception as error:
            self.live_status_var.set(f"{action} 提交失败：{error}")
            return False

    def _probe(self) -> None:
        ports = self._ports()
        if self.closing or self._pending or self._busy or self.live_state in {"connected", "capturing", "stopped"}:
            return
        if not self._distinct_ports():
            self.live_status_var.set("请选择两个不同的串口。")
            return
        self.binding_token = self._binding_ports = None
        self._probe_ports = ports
        self._pending = "probe"
        self.live_status_var.set("正在只读核验两块板卡身份…")
        if not self._submit("probe", rx_port=ports[0], adda_port=ports[1]):
            self._pending = None
        self._update_controls()

    def _connect(self) -> None:
        if self.closing or self._pending or self._busy or self.live_state in {"connected", "capturing", "stopped"} or not self.binding_token or self._ports() != self._binding_ports:
            return
        self._pending = "connect"
        self.live_status_var.set("正在重新核验并绑定两串口；连接不触发发送。")
        if not self._submit("connect", binding_token=self.binding_token):
            self._pending = None
        self._update_controls()

    def _capture(self, send: bool) -> None:
        if self.closing or self._pending or self._busy or self.live_state not in {"connected", "stopped"}:
            return
        self.report_path = None
        self.auto_var.set(False)
        self._live_generation = self._begin()
        self._capture_pending = True
        self._pending = "capture"
        self.source_var.set("接收途径：在线单次采集 · " + ("请求有限发送并接收" if send else "仅采样 / 停发对照"))
        self.digest_var.set("IQ 路径 / SHA256：等待本次采集落盘")
        self.status_var.set("本次采集中，尚无新的 CRC 复核结果。")
        self.live_status_var.set("正在请求一次采集，约 17 秒；可按停止中断。")
        self.log_var.set("正在核验设备与接收窗口。")
        if not self._submit("capture", send=send):
            self._capture_pending = self._busy = False
            self._pending = None
        self._update_controls()

    def _stop(self) -> None:
        if self.closing or self._pending == "stop" or not (self._pending in {"probe", "connect", "capture"} or self.live_state in {"connected", "capturing", "stopped"}):
            return
        if self._submit("stop"):
            self._pending = "stop"
            self.live_status_var.set("正在停止有限发送与采集，等待控制器回执…")
        self._update_controls()

    def _disconnect(self) -> None:
        if self.closing or self._pending or self.live_state not in {"connected", "stopped"}:
            return
        self._pending = "disconnect"
        if not self._submit("disconnect"):
            self._pending = None
        self._update_controls()

    def _update_controls(self) -> None:
        if not hasattr(self, "iq_button"):
            return
        connected = self.live_state in {"connected", "capturing", "stopped"}
        idle = not self.closing and not self._pending and not self._busy and self.live_state != "capturing"
        ports = self._ports()
        for combo in (self.rx_port_combo, self.adda_port_combo):
            combo.configure(state="readonly" if idle and not connected else "disabled")
        states = ((self.discover_button, idle and not connected),
                  (self.probe_button, idle and not connected and self._distinct_ports()),
                  (self.connect_button, idle and not connected and bool(self.binding_token) and ports == self._binding_ports),
                  (self.disconnect_button, idle and connected),
                  (self.capture_button, idle and connected), (self.sample_button, idle and connected),
                  (self.stop_button, not self.closing and self._pending != "stop" and
                   (self._pending in {"probe", "connect", "capture"} or connected)),
                  (self.iq_button, idle), (self.json_button, idle))
        for button, enabled in states:
            button.configure(state="normal" if enabled else "disabled")

    def _choose_iq(self) -> None:
        path = filedialog.askopenfilename(parent=self.window, title="选择接收 IQ 原始文件", filetypes=[("IQ 原始文件", "*.bin *.iq *.raw"), ("所有文件", "*.*")])
        if path:
            self.load_iq(path)

    def _choose_report(self) -> None:
        path = filedialog.askopenfilename(parent=self.window, title="选择已有 RF 解码报告", filetypes=[("JSON", "*.json")])
        if path:
            self.load_report(path)

    def _begin(self) -> int:
        self._generation += 1
        self._busy = True
        self._update_controls()
        self._clear()
        self.status_var.set("正在读取文件并复核 CRC…")
        return self._generation

    def load_iq(self, filename: str) -> None:
        if self.closing or self.closed or self._pending or self._busy:
            return
        try:
            options = {key: float(variable.get()) for key, variable in self.parameters.items()}
            for key in ("sample_rate_hz", "symbol_rate"):
                if not options[key].is_integer() or options[key] <= 0:
                    raise ValueError("采样率和符号率必须为正整数")
                options[key] = int(options[key])
            if not all(math.isfinite(value) for value in options.values()):
                raise ValueError("参数须为有限数值")
        except ValueError as error:
            self.status_var.set(f"参数错误：{error}")
            return
        self.report_path = None
        self.auto_var.set(False)
        generation = self._begin()
        path = Path(filename).resolve()
        self.source_var.set(f"接收途径：从 IQ 文件离线解码 · {path}")
        self.digest_var.set("IQ SHA256：计算中…")
        def work():
            try:
                raw = path.read_bytes()
                if self.decode_iq is None:
                    from sw.tools.telemetry_downlink import decode_capture_windows
                    decoder = decode_capture_windows
                else:
                    decoder = self.decode_iq
                report = decoder(raw, **options)
                self.events.put(dict(type="loaded", generation=generation, report=report,
                                     path=str(path), iq_sha256=hashlib.sha256(raw).hexdigest(),
                                     mtime=path.stat().st_mtime, mode="iq"))
            except Exception as error:
                self.events.put(dict(type="error", generation=generation, message=str(error)))
        threading.Thread(target=work, daemon=True, name="rf-iq-file-decode").start()

    def load_report(self, filename: str) -> None:
        if self.closing or self.closed or self._pending or self._busy:
            return
        path = Path(filename).resolve()
        self.report_path = path
        generation = self._begin()
        self.source_var.set(f"接收途径：导入已有解码 JSON（历史文件，非新采集） · {path}")
        self.digest_var.set("IQ 路径 / SHA256：等待报告；报告声明未经原始 IQ 复核。")
        def work():
            try:
                raw = path.read_bytes()
                stat = path.stat()
                self.events.put(dict(type="loaded", generation=generation, report=json.loads(raw),
                                     path=str(path), mtime=stat.st_mtime, signature=(stat.st_mtime_ns, stat.st_size), mode="json"))
            except Exception as error:
                self.events.put(dict(type="error", generation=generation, message=str(error)))
        threading.Thread(target=work, daemon=True, name="rf-report-file-read").start()

    def _clear(self) -> None:
        self.snapshots = []
        self.frames.delete(*self.frames.get_children())
        for variable in self.record_vars.values():
            variable.set("未知 · 无有效帧")
        self.time_var.set("文件时间：—（文件修改时间不是射频接收时间）")

    def _handle_event(self, event: dict[str, Any]) -> None:
        if self.closed:
            return
        if event.get("type") in {"devices", "probe", "status", "capture", "closed", "log"}:
            self._handle_live_event(event)
            return
        if self.closing:
            return
        if self.closed or event.get("generation") != self._generation:
            return
        self._busy = False
        self._update_controls()
        if event["type"] == "error":
            self._clear()
            self.status_var.set(f"读取/解码失败：{event['message']}；当前无可用接收结果。")
            return
        try:
            self.snapshots = validated_snapshots(event["report"])
        except (ValueError, TypeError, AttributeError) as error:
            self._clear()
            self.status_var.set(f"报告不可用：{error}")
            return
        self._signature = event.get("signature")
        report = event["report"]
        if event["mode"] == "iq":
            self.digest_var.set(f"IQ 文件：{event['path']}\nSHA256（本次读取字节）：{event['iq_sha256']}")
        elif event["mode"] == "live":
            self.digest_var.set(f"IQ 文件：{event['path']}\nSHA256（接收控制器）：{report.get('sha256', '未提供')}\n"
                                f"解码报告：{event.get('report_path', '未提供')}")
        else:
            self.digest_var.set(f"报告声明 IQ：{report.get('iq_path', report.get('source_iq', '未提供原始路径'))}\n"
                                f"SHA256（报告声明，未复核 IQ）：{report.get('sha256', '未提供')}")
        timestamp = datetime.fromtimestamp(event["mtime"], tz=timezone.utc).astimezone().isoformat(timespec="seconds")
        duration = event.get("capture_seconds")
        duration_text = (f"{duration:.1f}" if type(duration) in (int, float)
                         and math.isfinite(duration) and duration >= 0 else "未知")
        self.time_var.set((f"在线采集完成时间：{timestamp} / 本次流程耗时 {duration_text} s"
                           if event["mode"] == "live" else "文件修改时间：" + timestamp + "（非射频接收时间）"))
        unique = len({json.dumps({k: v for k, v in snapshot.items()
                                  if k not in ('first_symbol_sample', 'carrier_offset_hz')}, sort_keys=True)
                      for snapshot in self.snapshots})
        self.status_var.set(f"CRC 复核有效 ATM1：{len(self.snapshots)} 帧 / {unique} 份状态快照 · " +
                            ("本次在线 IQ 解码结果。" if event["mode"] == "live" else "文件来源以采集记录为准。"))
        for index, snapshot in enumerate(self.snapshots):
            self.frames.insert("", "end", iid=str(index), values=(snapshot["sequence"], snapshot["uptime_ms"],
                               snapshot.get("first_symbol_sample") if snapshot.get("first_symbol_sample") is not None else "—",
                               f"{snapshot['carrier_offset_hz']:.1f}" if snapshot.get("carrier_offset_hz") is not None else "—"))
        if self.snapshots:
            self.frames.selection_set("0")
            self._select()

    def _handle_live_event(self, event: dict[str, Any]) -> None:
        kind = event["type"]
        if kind == "closed":
            self._finish_close()
            return
        if self.closing:
            return
        if kind == "devices":
            self.devices = {item["label"]: item["port"] for item in event.get("devices", [])}
            for combo in (self.rx_port_combo, self.adda_port_combo):
                combo.configure(values=list(self.devices))
            # A refreshed device list cannot silently preserve a stale identity.
            if self._binding_ports and self._binding_ports != self._ports():
                self._ports_changed()
        elif kind == "probe":
            if self._pending == "stop":
                return
            binding = event.get("binding", {})
            try:
                ports = (binding["receiver"]["port"], binding["adda"]["port"])
            except (KeyError, TypeError):
                ports = (event.get("rx_port"), event.get("adda_port"))
            self._pending = None
            if ports != self._probe_ports or ports != self._ports() or not event.get("binding_token"):
                self.binding_token = self._binding_ports = None
                self.live_state = "disconnected"
                self.live_status_var.set("核验结果与当前端口选择不符，需重新只读核验。")
            else:
                self.binding_token = event["binding_token"]
                self._binding_ports = ports
                self.live_state = "probed"
                descriptions = []
                for key, label in (("receiver", "接收 SDR"), ("adda", "遥控板")):
                    info = binding.get(key, {})
                    descriptions.append(f"{label}：{info.get('port', '未知端口')} · {info.get('model', info.get('description', '已核验'))}"
                                        f" · USB {info.get('usb_serial', '未提供序列号')}")
                self.binding_var.set("\n".join(descriptions))
                self.live_status_var.set("只读核验完成；可绑定连接，不会自动发送。")
        elif kind == "status":
            state = event.get("state", "disconnected")
            self.live_state = state
            self.live_status_var.set(str(event.get("message", state)))
            if state != "capturing" and (self._pending not in {"stop", "disconnect"} or state in {"disconnected", "error", "stopped"}):
                self._pending = None
            if state in {"disconnected", "error", "stopped"}:
                if self._capture_pending:
                    self._busy = False
                    self._capture_pending = False
                    self.status_var.set("本次采集已停止或失败；尚无新的 CRC 复核结果。")
                if state != "stopped":
                    self.binding_token = self._binding_ports = None
                    self.binding_var.set("绑定身份：未绑定，使用前需只读核验")
            if state == "error":
                self.log_var.set("若串口被占用，请关闭该端口的 USB TM1 监控或主业务连接，再重新核验。")
        elif kind == "capture":
            if not self._capture_pending or self._live_generation != self._generation:
                return
            self._capture_pending = False
            self.log_var.set("采集与解码已完成，原始 IQ 和报告已保存。")
            if self._pending != "stop":
                self._pending = None
            self._clear()
            self.source_var.set("接收途径：在线单次 IQ 采集 · " +
                                ("请求有限发送并接收" if event.get("send_requested") else "仅采样 / 停发对照"))
            self._handle_event(dict(type="loaded", generation=self._generation, mode="live",
                                    report=event["report"], path=str(event.get("iq_path", "未提供")),
                                    report_path=str(event.get("report_path", "未提供")),
                                    mtime=event["received_at"], capture_seconds=event.get("capture_seconds")))
        elif kind == "log":
            self.log_var.set(str(event.get("message", "")))
        self._update_controls()

    def _select(self) -> None:
        selected = self.frames.selection()
        if not selected:
            return
        snapshot = self.snapshots[int(selected[0])]
        for key, variable in self.record_vars.items():
            record = snapshot[key]
            if not record["valid"]:
                variable.set("未知 · 帧内此记录无效\n来源与频率：—")
                continue
            text = (f"来源：{record['origin_name']} ({record['origin']})\n事件 {record['event']} / 空口序号 {record['air_seq']}\n"
                    f"RX {record['rx_mhz']} / TX {record['tx_mhz']} MHz")
            if key == "send_record":
                text += f"\nUDP {record['udp_seq']} / 尝试 {record['count']} / rc {record['rc']}\n仅本地 UDP 发送记录"
            if key == "ack_record":
                text += f"\nACK RX {record['rx_hz']} Hz\nACK TX {record['tx_hz']} Hz\nUDP {record['udp_seq']} / rc {record['rc']}\n非独立 SPI 回读"
            variable.set(text)

    def _drain_events(self) -> None:
        if self.closed:
            return
        while True:
            try:
                self._handle_event(self.events.get_nowait())
                if self.closed:
                    return
            except queue.Empty:
                break
        self._poll_id = self.window.after(100, self._drain_events)

    def _refresh(self) -> None:
        if self.closed or self.closing:
            return
        if self.auto_var.get() and self.report_path is not None and not self._busy and not self._pending:
            try:
                stat = self.report_path.stat()
                signature = (stat.st_mtime_ns, stat.st_size)
                if signature != self._signature:
                    self.load_report(str(self.report_path))
            except OSError as error:
                self._clear()
                self.status_var.set(f"刷新失败：{error}；已清除旧结果。")
        self._refresh_id = self.window.after(2000, self._refresh)

    def show(self) -> None:
        self.window.deiconify()
        self.window.lift()

    def close(self) -> None:
        if self.closed or self.closing:
            return
        self.closing = True
        self._generation += 1
        self.auto_var.set(False)
        self.window.after_cancel(self._refresh_id)
        self.live_status_var.set("正在停止并释放 RF 下行串口；等待控制器关闭回执…")
        self.canvas.yview_moveto(0)
        self._update_controls()
        self._submit("close")

    def _finish_close(self) -> None:
        self.closed = self.closing = True
        self.window.after_cancel(self._poll_id)
        self.window.after_cancel(self._refresh_id)
        self.window.destroy()
        self.on_closed()
