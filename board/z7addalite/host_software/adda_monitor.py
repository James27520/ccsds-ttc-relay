#!/usr/bin/env python3
"""Z7ADDALite monitor. Opening the GUI never opens a serial port automatically."""
from pathlib import Path
import sys
import time
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

LOCAL_PACKAGES = Path(__file__).resolve().parent / "_packages"
if LOCAL_PACKAGES.is_dir():
    sys.path.insert(0, str(LOCAL_PACKAGES))
try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None

from monitor_core import BoardState, Session


class Monitor(tk.Tk):
    def __init__(self, serial_factory=None, enumerate_ports=None, hidden=False, log_file=None):
        super().__init__()
        if hidden:
            self.withdraw()
        self.title("遥控板（Z7ADDALite）")
        width = min(1000, self.winfo_screenwidth() - 40)
        height = min(720, self.winfo_screenheight() - 90)
        self.geometry(f"{width}x{height}")
        self.minsize(740, 520)
        self.session = Session()
        self.state = BoardState()
        self.log_stream = None
        if log_file is not None:
            try:
                self.log_stream = Path(log_file).open("x", encoding="utf-8", buffering=1)
            except OSError:
                self.destroy()
                raise
        self.factory = serial_factory or (serial.Serial if serial else None)
        self.enumerate_ports = enumerate_ports or (list_ports.comports if list_ports else None)
        self.port = tk.StringVar()
        self.baud = tk.StringVar(value="115200")
        self.connection = tk.StringVar(value="未连接")
        self.board_status = tk.StringVar(value="网口/UDP：未知　ARM：未知")
        self.capture_status = tk.StringVar(value="自动模式：未知　采集：未知")
        self.source = tk.StringVar(value="最近数据来源：尚无板端记录")
        self.result = tk.StringVar(value=self.state.last_result)
        self.decoded = tk.StringVar(value="最近有效解码：尚无")
        self.confirmed = tk.StringVar(value="最近ACK确认：尚无")
        self.counts = tk.StringVar(value="最近STATUS计数 — 解码 / ACK确认 / 待确认 / 失败：未知")
        self.fields = [tk.StringVar(value=v) for v in ("100", "2450", "0", "0", "89")]
        self.capture_mode = tk.StringVar(value="training")
        self.capture_channel = tk.StringVar(value="0")
        self.capture_k = tk.StringVar(value="0")
        self.command_buttons = []
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.shutdown)
        self.log("HOST", "连接不改变板端ARM或网络状态；断开串口不等于解除ARM。")
        if log_file is not None:
            self.log("HOST", f"完整会话日志：{Path(log_file).resolve()}")
        if self.factory is None:
            self.log("HOST", "缺少PySerial：界面可离线打开，安装方法见同目录README.md。")
        self.after_id = self.after(100, self._poll)

    def _build(self):
        outer = ttk.Frame(self, padding=10)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(4, weight=1)
        ports = ttk.LabelFrame(outer, text="串口连接（8N1，DTR/RTS关闭）", padding=6)
        ports.grid(row=0, column=0, sticky="ew")
        self.port_box = ttk.Combobox(ports, textvariable=self.port, width=15)
        self.port_box.pack(side="left", padx=3)
        ttk.Button(ports, text="刷新端口", command=self.refresh_ports).pack(side="left", padx=3)
        ttk.Combobox(ports, textvariable=self.baud, values=(9600, 57600, 115200, 230400),
                     state="readonly", width=9).pack(side="left", padx=3)
        self.connect_button = ttk.Button(ports, text="连接", command=self.toggle_connection)
        self.connect_button.pack(side="left", padx=3)
        ttk.Label(ports, textvariable=self.connection).pack(side="left", padx=10)

        status = ttk.LabelFrame(outer, text="板端报告", padding=8)
        status.grid(row=1, column=0, sticky="ew", pady=6)
        for variable in (self.board_status, self.capture_status, self.counts, self.decoded, self.confirmed, self.source, self.result):
            ttk.Label(status, textvariable=variable).pack(anchor="w", pady=2)
        buttons = ttk.Frame(status)
        buttons.pack(anchor="w", pady=(5, 0))
        for label, action in (("读取状态", "status"), ("数字帧自检", "selftest"), ("合成波形自检", "waveformtest"),
                              ("ARM 开", "arm on"), ("ARM 关", "arm off"), ("命令帮助", "help")):
            button = ttk.Button(buttons, text=label, command=lambda a=action: self.send(a), state="disabled")
            button.pack(side="left", padx=(0, 6))
            self.command_buttons.append(button)

        tabs = ttk.Notebook(outer)
        tabs.grid(row=2, column=0, sticky="ew")
        capture = ttk.Frame(tabs, padding=8)
        tabs.add(capture, text="ADC采集 / 解调")
        settings = ttk.Frame(capture)
        settings.pack(anchor="w")
        for label, variable, choices in (("模式", self.capture_mode, ("training", "normal")),
                                          ("通道 A=0 / B=1", self.capture_channel, ("0", "1")),
                                          ("固定样点 K", self.capture_k, ("0", "1", "2", "3"))):
            ttk.Label(settings, text=label).pack(side="left", padx=3)
            ttk.Combobox(settings, textvariable=variable, values=choices, state="readonly", width=10).pack(side="left", padx=(0, 8))
        self.capture_button = ttk.Button(settings, text="单次采集", command=self.capture, state="disabled")
        self.capture_button.pack(side="left", padx=3)
        self.command_buttons.append(self.capture_button)
        actions = ttk.Frame(capture)
        actions.pack(anchor="w", pady=7)
        for label, action in (("取消采集", "capture cancel"), ("解调当前快照", "decode"),
                              ("自动采集并转发", "auto on"), ("停止自动并解除ARM", "auto off")):
            button = ttk.Button(actions, text=label, command=lambda a=action: self.send(a), state="disabled")
            button.pack(side="left", padx=(0, 6))
            self.command_buttons.append(button)
        capture_note = ttk.Label(capture, text="training为内部PN9/checker测试；normal为模拟输入采集。采集需匹配M2固件。\n解调在ARM开启时可转发有效ADC_NORMAL命令；自动模式会开启ARM。测试码和合成自检不发UDP。", wraplength=680)
        capture_note.pack(anchor="w")
        capture.bind("<Configure>", lambda event: capture_note.configure(wraplength=max(200, event.width - 20)))

        test = ttk.Frame(tabs, padding=8)
        tabs.add(test, text="网络控制测试")
        labels = ("RX MHz (70–6000)", "TX MHz (70–6000)", "SEQ (0–255)", "GAIN dB (0–76)", "ATT dB (0–89)")
        for index, (label, variable) in enumerate(zip(labels, self.fields)):
            test.columnconfigure(index, weight=1)
            ttk.Label(test, text=label).grid(row=0, column=index, sticky="w", padx=3)
            ttk.Entry(test, textvariable=variable, width=14).grid(row=1, column=index, sticky="ew", padx=3, pady=4)
        test_note = ttk.Label(test, text="只在点击后发送；需要板端网络可用。此操作不验证ADC接收，ACK前不计为已执行。",
                              wraplength=680)
        test_note.grid(row=2, column=0, columnspan=5, sticky="w", pady=3)
        self.nettest_button = ttk.Button(test, text="发送网络控制测试", command=self.nettest, state="disabled")
        self.nettest_button.grid(row=3, column=0, columnspan=5, sticky="w", pady=3)
        self.command_buttons.append(self.nettest_button)
        network_buttons = ttk.Frame(test)
        network_buttons.grid(row=4, column=0, columnspan=5, sticky="w", pady=3)
        for label, action in (("启动板端网络", "network on"), ("关闭网络并解除ARM", "network off")):
            button = ttk.Button(network_buttons, text=label, command=lambda a=action: self.send(a), state="disabled")
            button.pack(side="left", padx=(0, 6))
            self.command_buttons.append(button)
        source_note = ttk.Label(outer, text="来源标记：ADC_NORMAL = 板端报告的真实ADC正常模式；ADC_TEST / SYNTHETIC = 内部测试；UART_NETTEST = 手动网络测试。",
                                wraplength=680)
        source_note.grid(row=3, column=0, sticky="w", pady=6)
        outer.bind("<Configure>", lambda event: source_note.configure(wraplength=max(200, event.width - 25)))
        test.bind("<Configure>", lambda event: test_note.configure(wraplength=max(200, event.width - 25)))
        self.logs = scrolledtext.ScrolledText(outer, height=12, state="disabled", wrap="word", font=("Consolas", 10))
        self.logs.grid(row=4, column=0, sticky="nsew")

    def refresh_ports(self):
        if self.enumerate_ports is None:
            messagebox.showinfo("串口依赖", "当前Python缺少PySerial。请按README安装到项目_packages目录。", parent=self)
            return
        try:
            items = list(self.enumerate_ports())
            self.port_box["values"] = [item.device for item in items]
            self.log("HOST", "可用端口：" + ("；".join(f"{p.device} {p.description}" for p in items) or "无"))
        except Exception as exc:
            self.log("HOST", f"枚举端口失败：{exc}")

    def toggle_connection(self):
        if self.session.serial is not None:
            try:
                self.session.close()
            finally:
                self._disconnected()
                self.log("HOST", "串口已断开；未向板端发送ARM或其他命令。")
            return
        if self.factory is None:
            messagebox.showinfo("串口依赖", "缺少PySerial，安装说明见README.md。", parent=self)
            return
        try:
            self.session.connect(self.factory, self.port.get(), int(self.baud.get()))
        except Exception as exc:
            self.log("HOST", f"连接失败：{exc}")
            return
        self.state = BoardState()
        self._display_state()
        self.connection.set(f"已连接 {self.port.get()} / {self.baud.get()}")
        self.connect_button.configure(text="断开")
        for button in self.command_buttons:
            button.configure(state="normal")
        self.log("HOST", "串口已打开，未发送命令。请点击“读取状态”获取板端当前状态。")

    def _disconnected(self):
        self.connection.set("未连接")
        self.connect_button.configure(text="连接")
        self.state = BoardState()
        self._display_state()
        for button in self.command_buttons:
            button.configure(state="disabled")

    def _display_state(self):
        def flag(value):
            return "未知" if value is None else "ON" if value else "OFF"
        self.board_status.set(f"板端网口/UDP可用：{flag(self.state.network)}　ARM：{flag(self.state.armed)}")
        states = {0: "空闲", 1: "配置中", 2: "等待就绪", 3: "采集中", 4: "复制到DDR", 5: "释放缓冲", 6: "快照就绪", 7: "错误"}
        capture = "固件关闭采集功能" if self.state.capture_enabled is False else states.get(self.state.capture_state, "未知")
        self.capture_status.set(f"自动模式：{flag(self.state.automatic)}　采集：{capture}　快照有效：{flag(self.state.capture_valid)}")
        c = self.state.counters
        self.counts.set("最近STATUS计数 — 解码 / ACK确认 / 待确认 / 失败：" + " / ".join(str(c.get(k, "未知")) for k in ("decoded", "applied", "pending", "failures")))
        names = {"UNKNOWN": "尚无板端记录", "ADC_NORMAL": "真实ADC正常模式（板端报告）",
                 "ADC_TEST": "ADC内部测试码", "SYNTHETIC": "内部合成/数字帧测试",
                 "UART_NETTEST": "手动网络控制测试，不是ADC接收"}
        self.source.set(f"最近数据来源：{self.state.origin} — {names[self.state.origin]}")
        self.result.set(self.state.last_result)
        def command(record):
            if record is None:
                return "尚无"
            seq = f"空口序号 {record.air_seq}"
            if record.udp_seq is not None:
                seq += f" / UDP序号 {record.udp_seq}"
            return f"RX {record.rx_mhz} MHz / TX {record.tx_mhz} MHz　{seq}　[{record.source}]"
        self.decoded.set("最近有效解码（不代表已执行）：" + command(self.state.last_decoded))
        self.confirmed.set("最近ACK确认（板端报告）：" + command(self.state.last_ack))

    def send(self, action, values=()):
        try:
            text = self.session.send(action, values)
            self.log("TX", text)
        except (ValueError, RuntimeError) as exc:
            self.log("HOST", f"未发送：{exc}")
        except Exception as exc:
            self.log("HOST", f"发送失败：{exc}")
            self._disconnected()

    def nettest(self):
        self.send("nettest", tuple(variable.get() for variable in self.fields))

    def capture(self):
        self.send("capture", (self.capture_mode.get(), self.capture_channel.get(), self.capture_k.get()))

    def _poll(self):
        try:
            for line in self.session.poll():
                self.log("RX", line)
                self.state.receive(line)
            self._display_state()
        except Exception as exc:
            self.log("HOST", f"串口读取失败：{exc}")
            self._disconnected()
        self.after_id = self.after(100, self._poll)

    def log(self, direction, text):
        line = f"{time.strftime('%H:%M:%S')} [{direction}] {text}\n"
        if self.log_stream is not None:
            try:
                self.log_stream.write(line)
            except OSError as exc:
                try:
                    self.log_stream.close()
                except OSError:
                    pass
                self.log_stream = None
                line += f"[HOST] 日志文件写入失败，后续仅显示在界面：{exc}\n"
        self.logs.configure(state="normal")
        self.logs.insert("end", line)
        if int(self.logs.index("end-1c").split(".")[0]) > 3000:
            self.logs.delete("1.0", "501.0")
        self.logs.see("end")
        self.logs.configure(state="disabled")

    def shutdown(self):
        self.after_cancel(self.after_id)
        try:
            self.session.close()
        finally:
            try:
                if self.log_stream is not None:
                    self.log_stream.close()
            finally:
                self.destroy()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-file", type=Path, help="保存完整串口会话到新文件；父目录须已存在")
    args = parser.parse_args()
    Monitor(log_file=args.log_file).mainloop()
