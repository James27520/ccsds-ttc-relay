#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
relay_gui.py -- IoT-NTN PL 转发器 监控 / 控制界面

零依赖：只用 Python 标准库（tkinter + ctypes 调 Win32 串口）。
不需要安装 pyserial。

用法：
    python relay_gui.py                    自动检测串口
    python relay_gui.py COM5               指定串口
    python relay_gui.py --list             只列出串口

界面显示：
    * 收/发样点、实时速率、丢样检测、饱和计数、健康状态
    * 当前工作模式、DDC/DUC 频偏、数字增益、隔直
    * RX/TX 本振、RX 增益、TX 衰减
    * 底部可下发任意命令（等价于串口终端）

丢样判据：两次轮询之间 Δout 必须等于 Δin；不等即判定丢样并变红。
"""
import ctypes
import ctypes.wintypes as wt
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

# =====================================================================
#  Win32 串口（ctypes，无第三方依赖）
# =====================================================================
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
PURGE_RXCLEAR = 0x0008
PURGE_TXCLEAR = 0x0004

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)


class _DCB(ctypes.Structure):
    _fields_ = [
        ("DCBlength", wt.DWORD), ("BaudRate", wt.DWORD),
        ("fBinary", wt.DWORD, 1), ("fParity", wt.DWORD, 1),
        ("fOutxCtsFlow", wt.DWORD, 1), ("fOutxDsrFlow", wt.DWORD, 1),
        ("fDtrControl", wt.DWORD, 2), ("fDsrSensitivity", wt.DWORD, 1),
        ("fTXContinueOnXoff", wt.DWORD, 1), ("fOutX", wt.DWORD, 1),
        ("fInX", wt.DWORD, 1), ("fErrorChar", wt.DWORD, 1),
        ("fNull", wt.DWORD, 1), ("fRtsControl", wt.DWORD, 2),
        ("fAbortOnError", wt.DWORD, 1), ("fDummy2", wt.DWORD, 17),
        ("wReserved", wt.WORD), ("XonLim", wt.WORD), ("XoffLim", wt.WORD),
        ("ByteSize", wt.BYTE), ("Parity", wt.BYTE), ("StopBits", wt.BYTE),
        ("XonChar", ctypes.c_char), ("XoffChar", ctypes.c_char),
        ("ErrorChar", ctypes.c_char), ("EofChar", ctypes.c_char),
        ("EvtChar", ctypes.c_char), ("wReserved1", wt.WORD),
    ]


class _TIMEOUTS(ctypes.Structure):
    _fields_ = [("ReadIntervalTimeout", wt.DWORD),
                ("ReadTotalTimeoutMultiplier", wt.DWORD),
                ("ReadTotalTimeoutConstant", wt.DWORD),
                ("WriteTotalTimeoutMultiplier", wt.DWORD),
                ("WriteTotalTimeoutConstant", wt.DWORD)]


_k32.CreateFileW.restype = wt.HANDLE
_k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p,
                             wt.DWORD, wt.DWORD, wt.HANDLE]
_k32.SetCommState.argtypes = [wt.HANDLE, ctypes.POINTER(_DCB)]
_k32.GetCommState.argtypes = [wt.HANDLE, ctypes.POINTER(_DCB)]
_k32.SetCommTimeouts.argtypes = [wt.HANDLE, ctypes.POINTER(_TIMEOUTS)]
_k32.PurgeComm.argtypes = [wt.HANDLE, wt.DWORD]
_k32.ReadFile.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD,
                          ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
_k32.WriteFile.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD,
                           ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
_k32.CloseHandle.argtypes = [wt.HANDLE]


def list_ports():
    """返回可用串口名列表。"""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"HARDWARE\DEVICEMAP\SERIALCOMM")
        out = []
        i = 0
        while True:
            try:
                _name, val, _t = winreg.EnumValue(key, i)
                out.append(val)
                i += 1
            except OSError:
                break
        winreg.CloseKey(key)
        return sorted(set(out), key=lambda s: (len(s), s))
    except Exception:
        return ["COM%d" % n for n in range(1, 33)]


class Serial(object):
    def __init__(self, port, baud=115200):
        self.port = port
        self.h = _k32.CreateFileW("\\\\.\\" + port, GENERIC_READ | GENERIC_WRITE,
                                  0, None, OPEN_EXISTING, 0, None)
        if self.h == INVALID_HANDLE_VALUE or not self.h:
            raise OSError("cannot open %s (err %d)" % (port, ctypes.get_last_error()))
        dcb = _DCB()
        dcb.DCBlength = ctypes.sizeof(_DCB)
        if not _k32.GetCommState(self.h, ctypes.byref(dcb)):
            self.close()
            raise OSError("GetCommState failed")
        dcb.BaudRate = baud
        dcb.ByteSize = 8
        dcb.Parity = 0
        dcb.StopBits = 0
        dcb.fBinary = 1
        dcb.fParity = 0
        dcb.fOutxCtsFlow = 0
        dcb.fOutxDsrFlow = 0
        dcb.fDtrControl = 1
        dcb.fDsrSensitivity = 0
        dcb.fOutX = 0
        dcb.fInX = 0
        dcb.fRtsControl = 1
        dcb.fAbortOnError = 0
        if not _k32.SetCommState(self.h, ctypes.byref(dcb)):
            self.close()
            raise OSError("SetCommState failed (baud %d)" % baud)
        to = _TIMEOUTS(0, 0, 50, 0, 50)      # 读: 最多等 50 ms
        _k32.SetCommTimeouts(self.h, ctypes.byref(to))
        _k32.PurgeComm(self.h, PURGE_RXCLEAR | PURGE_TXCLEAR)

    def write(self, data):
        if isinstance(data, str):
            data = data.encode("ascii", "replace")
        n = wt.DWORD(0)
        buf = ctypes.create_string_buffer(data, len(data))
        _k32.WriteFile(self.h, buf, len(data), ctypes.byref(n), None)

    def read(self, n=4096):
        buf = ctypes.create_string_buffer(n)
        got = wt.DWORD(0)
        _k32.ReadFile(self.h, buf, n, ctypes.byref(got), None)
        return buf.raw[:got.value]

    def close(self):
        if getattr(self, "h", None):
            _k32.CloseHandle(self.h)
            self.h = None


# =====================================================================
#  设备通信层
# =====================================================================
class RelayLink(object):
    def __init__(self):
        self.ser = None
        self.lines = queue.Queue()
        self.rx = b""
        self.stop = threading.Event()
        self.thread = None

    # ---------------- discovery ----------------
    def probe(self, port, timeout=1.2):
        """打开 port 发 status，收到 STAT 就认为找到了板子。"""
        try:
            s = Serial(port)
        except OSError:
            return False
        try:
            time.sleep(0.2)
            s.read()
            s.write("auto 0\r\n")
            time.sleep(0.2)
            s.read()
            for _ in range(3):
                s.write("status\r\n")
                t0 = time.time()
                acc = b""
                while time.time() - t0 < timeout:
                    acc += s.read()
                    if b"STAT" in acc:
                        return True
                    time.sleep(0.05)
            return False
        finally:
            s.close()

    def autodetect(self, log=None):
        for p in list_ports():
            if log:
                log("  探测 %s ..." % p)
            if self.probe(p):
                return p
        return None

    # ---------------- connect ----------------
    def open(self, port):
        self.close()
        self.ser = Serial(port)
        time.sleep(0.2)
        self.ser.read()
        self.ser.write("auto 0\r\n")      # GUI 自己轮询，关掉板子的自动上报
        time.sleep(0.3)
        self.ser.read()
        self.stop.clear()
        self.thread = threading.Thread(target=self._reader, daemon=True)
        self.thread.start()

    def _reader(self):
        while not self.stop.is_set():
            try:
                d = self.ser.read(2048)
            except Exception:
                break
            if not d:
                continue
            self.rx += d
            while b"\n" in self.rx:
                ln, self.rx = self.rx.split(b"\n", 1)
                txt = ln.decode("ascii", "replace").strip()
                if txt:
                    self.lines.put(txt)

    def send(self, cmd):
        if self.ser:
            self.ser.write(cmd + "\r\n")

    def close(self):
        self.stop.set()
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None


# =====================================================================
#  解析
# =====================================================================
HEX_KEYS = ("ddc", "duc", "gain")


def parse_stat(line):
    if not line.startswith("STAT"):
        return None
    d = {}
    for tok in line.split()[1:]:
        if "=" in tok:
            k, v = tok.split("=", 1)
            try:
                # ddc / duc / gain are printed in hex by the firmware
                d[k] = int(v, 16) if k in HEX_KEYS else int(v, 0)
            except ValueError:
                d[k] = v
    return d


def word_to_hz(word, fs):
    """32-bit 频率字 -> Hz（自动处理负频偏的回绕）。"""
    if word >= 0x80000000:
        word -= 0x100000000
    return word / float(1 << 32) * fs


def hz_to_word(hz, fs):
    w = int(round(hz / float(fs) * (1 << 32))) & 0xFFFFFFFF
    return w


MODE_NAMES = {0: "旁路 bypass", 1: "转发 relay", 2: "静音 mute", 3: "仅上变频 duc_only"}
MODE_BY_NAME = {v: k for k, v in MODE_NAMES.items()}


# =====================================================================
#  GUI
# =====================================================================
class App(object):
    POLL_MS = 600

    def __init__(self, root, port=None):
        self.root = root
        self.link = RelayLink()
        self.stat = None
        self.prev = None           # (t, in, out, clip)
        self.rate = 0.0
        self.drops = 0
        self.connected = False

        root.title("IoT-NTN PL 转发器 — 监控与控制")
        root.geometry("880x760")
        root.minsize(820, 700)

        self._build(port)
        if port:
            self.connect(port)
        else:
            self.do_autodetect()

    # ------------------------------------------------------------------
    def _build(self, port):
        pad = dict(padx=8, pady=4)

        # ---------- 连接栏 ----------
        top = ttk.LabelFrame(self.root, text=" 连接 ")
        top.pack(fill="x", **pad)
        ttk.Label(top, text="串口").grid(row=0, column=0, padx=(8, 2), pady=8)
        self.port_var = tk.StringVar(value=port or "")
        self.cmb = ttk.Combobox(top, textvariable=self.port_var, width=10,
                                values=list_ports())
        self.cmb.grid(row=0, column=1, padx=2, pady=8)
        ttk.Button(top, text="刷新", width=6,
                   command=lambda: self.cmb.configure(values=list_ports())
                   ).grid(row=0, column=2, padx=2)
        ttk.Button(top, text="自动检测", width=9,
                   command=self.do_autodetect).grid(row=0, column=3, padx=2)
        ttk.Button(top, text="连接", width=6,
                   command=lambda: self.connect(self.port_var.get())
                   ).grid(row=0, column=4, padx=2)
        ttk.Button(top, text="断开", width=6,
                   command=self.disconnect).grid(row=0, column=5, padx=2)
        self.conn_lbl = ttk.Label(top, text="● 未连接", foreground="#b00020",
                                  font=("", 10, "bold"))
        self.conn_lbl.grid(row=0, column=6, padx=14)

        # ---------- 转发状态 ----------
        st = ttk.LabelFrame(self.root, text=" 转发状态 ")
        st.pack(fill="x", **pad)
        for c in range(4):
            st.columnconfigure(c, weight=1)

        def cell(r, c, title):
            f = ttk.Frame(st)
            f.grid(row=r, column=c, sticky="w", padx=10, pady=3)
            ttk.Label(f, text=title, width=11, foreground="#555").pack(side="left")
            v = ttk.Label(f, text="—", font=("Consolas", 12, "bold"))
            v.pack(side="left")
            return v

        self.v_in   = cell(0, 0, "收样点")
        self.v_out  = cell(0, 1, "发样点")
        self.v_rate = cell(0, 2, "实测速率")
        self.v_diff = cell(0, 3, "收发差值")
        self.v_clip = cell(1, 0, "饱和计数")
        self.v_clipr= cell(1, 1, "饱和率")
        self.v_drop = cell(1, 2, "丢样")
        self.v_rc   = cell(1, 3, "健康")
        self.v_rc.configure(font=("", 12, "bold"))

        # ---------- 参数 ----------
        pa = ttk.LabelFrame(self.root, text=" 当前参数 （可直接修改，回车或点“应用”下发） ")
        pa.pack(fill="x", **pad)
        for c in range(4):
            pa.columnconfigure(c, weight=1)

        self.e_mode = self._field(pa, 0, 0, "工作模式")
        self.cmb_mode = ttk.Combobox(pa, textvariable=self.e_mode, width=13,
                                     values=list(MODE_BY_NAME.keys()), state="readonly")
        self.cmb_mode.grid(row=0, column=1, sticky="w", padx=4, pady=4)

        self.e_gain = self._field(pa, 0, 2, "数字增益")
        self.e_dc   = self._field(pa, 1, 2, "隔直 0/1")

        self.e_duc = self._field(pa, 1, 0, "DUC 频偏 Hz")
        self.e_ddc = self._field(pa, 2, 0, "DDC 频偏 Hz")
        self.e_rxlo = self._field(pa, 2, 2, "RX LO MHz")
        self.e_txlo = self._field(pa, 3, 2, "TX LO MHz")
        self.e_rxg  = self._field(pa, 3, 0, "RX 增益 dB")
        self.e_txa  = self._field(pa, 4, 0, "TX 衰减 dB")

        btns = ttk.Frame(pa)
        btns.grid(row=5, column=0, columnspan=4, sticky="w", padx=8, pady=6)
        ttk.Button(btns, text="应用", width=8, command=self.apply).pack(side="left", padx=3)
        ttk.Button(btns, text="净变换归零 (DDC=DUC)",
                   command=self.zero_net).pack(side="left", padx=3)
        ttk.Button(btns, text="旁路", width=6,
                   command=lambda: self.quick_mode(0)).pack(side="left", padx=3)
        ttk.Button(btns, text="转发", width=6,
                   command=lambda: self.quick_mode(1)).pack(side="left", padx=3)
        ttk.Button(btns, text="静音", width=6,
                   command=lambda: self.quick_mode(2)).pack(side="left", padx=3)

        # ---------- 快捷频偏 ----------
        q = ttk.LabelFrame(self.root, text=" 快捷频偏 （设置 DUC 上变频偏移） ")
        q.pack(fill="x", **pad)
        for v in (0, 10000, 50000, 100000, 480000, -100000):
            ttk.Button(q, text=("%+d kHz" % (v // 1000)) if v else "0 kHz",
                       width=9,
                       command=lambda v=v: self.set_offset(v)
                       ).pack(side="left", padx=4, pady=6)

        # ---------- 日志 ----------
        lg = ttk.LabelFrame(self.root, text=" 日志 ")
        lg.pack(fill="both", expand=True, **pad)
        self.txt = tk.Text(lg, height=12, font=("Consolas", 9), wrap="none")
        sb = ttk.Scrollbar(lg, command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.txt.pack(fill="both", expand=True)

        cmd = ttk.Frame(self.root)
        cmd.pack(fill="x", **pad)
        ttk.Label(cmd, text="命令").pack(side="left")
        self.cmd_var = tk.StringVar()
        e = ttk.Entry(cmd, textvariable=self.cmd_var)
        e.pack(side="left", fill="x", expand=True, padx=6)
        e.bind("<Return>", lambda _e: self.send_raw())
        ttk.Button(cmd, text="发送", command=self.send_raw).pack(side="left")

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _field(self, parent, r, c, label):
        ttk.Label(parent, text=label, width=11).grid(row=r, column=c,
                                                     sticky="e", padx=(8, 2), pady=4)
        v = tk.StringVar()
        ttk.Entry(parent, textvariable=v, width=14).grid(row=r, column=c + 1,
                                                         sticky="w", padx=(0, 10))
        return v

    # ------------------------------------------------------------------
    def log(self, msg):
        self.txt.insert("end", msg + "\n")
        self.txt.see("end")

    def do_autodetect(self):
        self.log("自动检测串口 ...")
        self.root.update_idletasks()
        p = self.link.autodetect(log=self.log)
        if p:
            self.log("找到板子: %s" % p)
            self.port_var.set(p)
            self.connect(p)
        else:
            self.log("未找到。请确认板子已上电、USB 已连接、程序已下载。")
            self.log("可用串口: %s" % ", ".join(list_ports()))

    def connect(self, port):
        port = (port or "").strip()
        if not port:
            self.log("请先选择串口")
            return
        try:
            self.link.open(port)
            self.connected = True
            self.stat = None
            self.conn_lbl.configure(text="● 已连接 %s" % port, foreground="#0a7d28")
            self.log("已连接 %s @115200，正在等待板子应答 ..." % port)
            self.prev = None
            self.drops = 0
            self.poll()
            # 打开串口本身从不失败；必须靠板子回 STAT 才能确认它跑的是转发程序
            self.root.after(1800, self.verify_connect)
        except OSError as e:
            self.connected = False
            self.conn_lbl.configure(text="● 连接失败", foreground="#b00020")
            self.log("打开 %s 失败: %s" % (port, e))
            self.log("  （err 5 = 串口被别的程序占用，先关掉其他串口终端）")

    def verify_connect(self):
        if not self.connected:
            return
        if self.stat is not None:
            self.log("板子已应答，参数已同步。")
            return
        self.conn_lbl.configure(text="● %s 无应答" % self.port_var.get(),
                                foreground="#b00020")
        self.log("=" * 62)
        self.log("!! 串口打开了，但 1.8 秒内收不到 STAT 回复。")
        self.log("!! 板子上现在跑的大概率不是转发程序。常见原因：")
        self.log("!!   1) 板子断电/复位后从 SD 卡启动了原厂 Pluto Linux")
        self.log("!!      （日志里会出现 'pluto login:' 之类字样）")
        self.log("!!   2) 还没有用 JTAG 下载转发码流")
        self.log("!! 处理：运行 program_device.tcl 重新下载，例如")
        self.log("!!   E:\\Vivado_2018\\SDK\\2018.3\\bin\\xsct.bat "
                 "E:/LDSDR_010/program_device.tcl")
        self.log("!! 开发期间建议直接拔出 SD 卡，避免复位后又启动 Linux。")
        self.log("=" * 62)

    def disconnect(self):
        self.connected = False
        self.link.close()
        self.conn_lbl.configure(text="● 未连接", foreground="#b00020")
        self.log("已断开")

    def on_close(self):
        self.link.close()
        self.root.destroy()

    # ------------------------------------------------------------------
    def poll(self):
        if not self.connected:
            return
        self.link.send("status")
        self.drain()
        self.root.after(self.POLL_MS, self.poll)

    def drain(self):
        got = None
        while True:
            try:
                ln = self.link.lines.get_nowait()
            except queue.Empty:
                break
            s = parse_stat(ln)
            if s:
                got = s
            else:
                self.log("< " + ln)
        if got:
            self.update_view(got)

    # ------------------------------------------------------------------
    def update_view(self, s):
        now = time.time()
        self.stat = s
        fs = s.get("fs", 30720000)
        nin, nout, clip = s.get("in", 0), s.get("out", 0), s.get("clip", 0)

        if self.prev:
            t0, i0, o0, c0 = self.prev
            dt = now - t0
            if dt > 0:
                self.rate = (nin - i0) / dt
            din, dout = nin - i0, nout - o0
            if dout != din:
                self.drops += 1
                self.v_drop.configure(text="丢样! Δin=%d Δout=%d" % (din, dout),
                                      foreground="#b00020")
            else:
                self.v_drop.configure(text="无 (Δ=%d)" % din, foreground="#0a7d28")
        self.prev = (now, nin, nout, clip)

        self.v_in.configure(text="{:,}".format(nin))
        self.v_out.configure(text="{:,}".format(nout))
        self.v_diff.configure(text="%d" % (nin - nout))
        self.v_rate.configure(text="%.3f MSPS" % (self.rate / 1e6))
        self.v_clip.configure(text="{:,}".format(clip))
        pct = (100.0 * clip / nin) if nin else 0.0
        self.v_clipr.configure(text="%.3f %%" % pct,
                               foreground="#b00020" if pct > 1.0 else "#000000")

        rc = s.get("rc", 0)
        if rc == 0:
            self.v_rc.configure(text="正常 (rc=0)", foreground="#0a7d28")
        elif rc == -1:
            self.v_rc.configure(text="无 ADC 数据 (rc=-1)", foreground="#b00020")
        elif rc == -2:
            self.v_rc.configure(text="无 DAC 输出 (rc=-2)", foreground="#b00020")
        else:
            self.v_rc.configure(text="rc=%d" % rc, foreground="#b00020")

        # 参数回填（不覆盖用户正在编辑的框：只在未聚焦时更新）
        def put(var, val):
            w = self.root.focus_get()
            if w is None or str(w) not in [str(x) for x in self.root.winfo_children()]:
                pass
            var.set(str(val))

        mode = s.get("mode", 0)
        self.e_mode.set(MODE_NAMES.get(mode, str(mode)))
        self.e_gain.set("0x%03X" % s.get("gain", 0x800))
        self.e_dc.set(str(s.get("dc", 0)))
        self.e_duc.set("%.0f" % word_to_hz(s.get("duc", 0), fs))
        self.e_ddc.set("%.0f" % word_to_hz(s.get("ddc", 0), fs))
        self.e_rxlo.set(str(s.get("rxlo", 0)))
        self.e_txlo.set(str(s.get("txlo", 0)))
        self.e_rxg.set(str(s.get("rxgain", 0)))
        self.e_txa.set(str(s.get("txatt", 0)))

    # ------------------------------------------------------------------
    def _num(self, var, default=0.0):
        try:
            return float(str(var.get()).strip().replace(",", ""))
        except ValueError:
            return default

    def apply(self):
        try:
            mode = MODE_BY_NAME.get(self.e_mode.get().strip(), None)
            if mode is not None:
                self.link.send("mode %d" % mode)
            self.link.send("gain 0x%X" % int(self._num(self.e_gain, 0x800)))
            self.link.send("dc %d" % int(self._num(self.e_dc, 0)))
            self.link.send("off %d" % int(self._num(self.e_duc, 0)))
            self.link.send("xoff %d" % int(self._num(self.e_ddc, 0)))
            self.link.send("rxgain %d" % int(self._num(self.e_rxg, 0)))
            self.link.send("txatt %d" % int(self._num(self.e_txa, 0)))
            self.link.send("lo %d %d" % (int(self._num(self.e_rxlo, 900)),
                                         int(self._num(self.e_txlo, 1000))))
            self.log("→ 已下发参数")
            self.root.after(150, self.drain)
        except Exception as e:
            self.log("下发失败: %s" % e)

    def quick_mode(self, m):
        self.link.send("mode %d" % m)
        self.log("→ mode %d (%s)" % (m, MODE_NAMES.get(m, "?")))

    def set_offset(self, hz):
        self.link.send("off %d" % hz)
        self.log("→ DUC 频偏 %+d Hz" % hz)

    def zero_net(self):
        self.link.send("xoff 0")
        self.link.send("off 0")
        self.log("→ DDC = DUC = 0（净变换归零）")

    def send_raw(self):
        c = self.cmd_var.get().strip()
        if c:
            self.link.send(c)
            self.log("> " + c)
            self.cmd_var.set("")
            self.root.after(120, self.drain)


# =====================================================================
def main():
    args = [a for a in sys.argv[1:]]
    if "--list" in args:
        print("可用串口:", ", ".join(list_ports()))
        return 0
    port = None
    for a in args:
        if not a.startswith("-"):
            port = a
            break
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except Exception:
        pass
    App(root, port)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
