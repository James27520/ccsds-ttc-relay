"""File-based RF telemetry viewer. Importing/opening never touches hardware.

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
    """Offline-only first version; decode_iq may be injected for tests/backends.

    decode_iq(raw_bytes, **sample_rate_hz/symbol_rate/expected_offset_hz/search_hz)
    returns an EXPERIMENTAL_ATM1_RF report containing original frame payload/CRC.
    Future live controller contract: factory(emit, log_dir=None), submit(action,
    **kwargs); discover/connect(port)/query/disconnect/close are separate from
    an explicit capture_request action. No such action is called by this viewer.
    """

    def __init__(self, parent: tk.Misc, on_closed: Callable[[], None],
                 decode_iq: Callable[..., dict[str, Any]] | None = None):
        self.on_closed, self.decode_iq = on_closed, decode_iq
        self.closed = self.closing = False
        self.events: queue.Queue[dict[str, Any]] = queue.Queue()
        self.snapshots: list[dict[str, Any]] = []
        self.report_path: Path | None = None
        self._signature = None
        self._generation = 0
        self._busy = False
        self.window = tk.Toplevel(parent)
        self.window.title("RF 测控下行 · 文件解码")
        self.window.geometry("1120x840+45+40")
        self.window.minsize(950, 730)
        self.window.configure(background=COLORS["background"])
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        self._poll_id = self.window.after(100, self._drain_events)
        self._refresh_id = self.window.after(2000, self._refresh)

    def _build(self) -> None:
        main = ttk.Frame(self.window, padding=20)
        main.pack(fill="both", expand=True)
        wrap_labels = []
        main.bind("<Configure>", lambda event: [label.configure(wraplength=max(event.width - 40, 200)) for label in wrap_labels])
        ttk.Label(main, text="RF 测控下行", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(main, text="文件解码 / 历史报告 · USB TM1 状态在独立窗口查看；此窗口不连接设备、不触发发送。",
                  style="Muted.TLabel").pack(anchor="w", pady=(3, 12))
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
        area.pack(fill="both", expand=True, pady=(12, 8))
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
        records.pack(fill="x", side="bottom", before=area)
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
        footer.pack(anchor="w", side="bottom", before=records, pady=(10, 0))
        wrap_labels.append(footer)

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
        self.iq_button.configure(state="disabled")
        self.json_button.configure(state="disabled")
        self._clear()
        self.status_var.set("正在读取文件并复核 CRC…")
        return self._generation

    def load_iq(self, filename: str) -> None:
        if self.closed:
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
        if self.closed:
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
        if self.closed or event.get("generation") != self._generation:
            return
        self._busy = False
        self.iq_button.configure(state="normal")
        self.json_button.configure(state="normal")
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
        else:
            self.digest_var.set(f"报告声明 IQ：{report.get('iq_path', report.get('source_iq', '未提供原始路径'))}\n"
                                f"SHA256（报告声明，未复核 IQ）：{report.get('sha256', '未提供')}")
        self.time_var.set("文件修改时间：" + datetime.fromtimestamp(event["mtime"], tz=timezone.utc).astimezone().isoformat(timespec="seconds") + "（非射频接收时间）")
        unique = len({json.dumps({k: v for k, v in snapshot.items()
                                  if k not in ('first_symbol_sample', 'carrier_offset_hz')}, sort_keys=True)
                      for snapshot in self.snapshots})
        self.status_var.set(f"CRC 复核有效 ATM1：{len(self.snapshots)} 帧 / {unique} 份状态快照 · 文件来源以采集记录为准。")
        for index, snapshot in enumerate(self.snapshots):
            self.frames.insert("", "end", iid=str(index), values=(snapshot["sequence"], snapshot["uptime_ms"],
                               snapshot.get("first_symbol_sample") if snapshot.get("first_symbol_sample") is not None else "—",
                               f"{snapshot['carrier_offset_hz']:.1f}" if snapshot.get("carrier_offset_hz") is not None else "—"))
        if self.snapshots:
            self.frames.selection_set("0")
            self._select()

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
            except queue.Empty:
                break
        self._poll_id = self.window.after(100, self._drain_events)

    def _refresh(self) -> None:
        if self.closed:
            return
        if self.auto_var.get() and self.report_path is not None and not self._busy:
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
        if self.closed:
            return
        self.closed = self.closing = True
        self._generation += 1
        self.window.after_cancel(self._poll_id)
        self.window.after_cancel(self._refresh_id)
        self.window.destroy()
        self.on_closed()
