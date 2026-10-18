#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
relay_link.py -- LDSDR 载荷控制链路（PS 串口命令行协议的封装）

载荷侧的固件接口是 relay_cli.h 里实现的行式 ASCII 协议：

    主机 → 载荷 :  "mode 1\\r\\n"
    载荷 → 主机 :  "OK mode=1\\r\\n"
    主机 → 载荷 :  "status\\r\\n"
    载荷 → 主机 :  "STAT mode=1 ddc=00000000 duc=04000000 ... rc=0\\r\\n"

本模块把它封装成 Python 方法，并负责：
  * 串口自动检测
  * status 行的解析（注意 gain/ddc/duc 是十六进制）
  * 频率字换算（Hz ↔ 32 位相位增量）
  * 命令回执校验

用法：
    from relay_link import RelayLink
    with RelayLink.autodetect() as lk:
        lk.set_mode("RELAY")
        lk.set_duc_hz(100_000)
        st = lk.status()
        print(st.rate_hint, st.rc)
"""

import re
import time

from serial_port import SerialPort, list_ports

FS_DEFAULT = 30_720_000          # 默认采样率 30.72 MSPS

MODE_BYPASS = 0
MODE_RELAY = 1
MODE_MUTE = 2
MODE_DUC_ONLY = 3

MODE_NAME = {0: "BYPASS", 1: "RELAY", 2: "MUTE", 3: "DUC_ONLY"}
MODE_VALUE = dict((v, k) for k, v in MODE_NAME.items())

HEX_KEYS = ("ddc", "duc", "gain")            # 固件用 %03X / %08X 打印


# ------------------------------------------------------------------ 换算
def hz_to_word(hz, fs=FS_DEFAULT):
    """频偏 Hz → 32 位相位增量（二补码）。"""
    w = int(round(float(hz) / float(fs) * (1 << 32)))
    return w & 0xFFFFFFFF


def word_to_hz(word, fs=FS_DEFAULT):
    """32 位相位增量 → 频偏 Hz（自动处理负值回绕）。"""
    if word >= 0x80000000:
        word -= 0x100000000
    return word / float(1 << 32) * fs


# ------------------------------------------------------------------ 状态
class RelayStatus(object):
    __slots__ = ("raw", "mode", "ddc", "duc", "gain", "dc", "rxgain", "txatt",
                 "rxlo", "txlo", "fs", "n_in", "n_out", "clip", "rc")

    def __init__(self, d):
        self.raw = d
        self.mode = d.get("mode", 0)
        self.ddc = d.get("ddc", 0)
        self.duc = d.get("duc", 0)
        self.gain = d.get("gain", 0x800)
        self.dc = d.get("dc", 0)
        self.rxgain = d.get("rxgain", 0)
        self.txatt = d.get("txatt", 0)
        self.rxlo = d.get("rxlo", 0)
        self.txlo = d.get("txlo", 0)
        self.fs = d.get("fs", FS_DEFAULT)
        self.n_in = d.get("in", 0)
        self.n_out = d.get("out", 0)
        self.clip = d.get("clip", 0)
        self.rc = d.get("rc", 0)

    @property
    def mode_name(self):
        return MODE_NAME.get(self.mode, "?")

    @property
    def duc_hz(self):
        return word_to_hz(self.duc, self.fs)

    @property
    def ddc_hz(self):
        return word_to_hz(self.ddc, self.fs)

    @property
    def net_hz(self):
        """净变换量 = DUC − DDC。"""
        return self.duc_hz - self.ddc_hz

    @property
    def healthy(self):
        return self.rc == 0

    def __repr__(self):
        return ("<RelayStatus %s ddc=%+.0fHz duc=%+.0fHz net=%+.0fHz "
                "gain=0x%03X in=%d out=%d clip=%d rc=%d>"
                % (self.mode_name, self.ddc_hz, self.duc_hz, self.net_hz,
                   self.gain, self.n_in, self.n_out, self.clip, self.rc))


# ------------------------------------------------------------------ 链路
class RelayLink(object):
    def __init__(self, port, baud=115200, timeout=1.0, verbose=False):
        self.port = port
        self.baud = baud
        self.timeout = timeout
        self.verbose = verbose
        self.sp = None
        self.fs = FS_DEFAULT

    # ---------- 生命周期 ----------
    @classmethod
    def autodetect(cls, baud=115200, verbose=False):
        for p in list_ports():
            if _probe(p, baud):
                return cls(p, baud, verbose=verbose)
        raise RuntimeError("没有找到载荷串口。已试过: %s" % ", ".join(list_ports()))

    def open(self):
        self.sp = SerialPort(self.port, self.baud)
        time.sleep(0.2)
        self.sp.read()
        self.sp.write("auto 0\r\n")      # 关掉载荷的周期上报，改由本模块轮询
        time.sleep(0.25)
        self.sp.read()
        st = self.status()
        self.fs = st.fs
        return self

    def close(self):
        if self.sp:
            self.sp.close()
            self.sp = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *a):
        self.close()

    # ---------- 收发 ----------
    def _log(self, s):
        if self.verbose:
            print(s)

    def cmd(self, line, expect="OK", timeout=None):
        """发一条命令，等待含 expect 的回行。返回该行（str）。"""
        if not self.sp:
            raise RuntimeError("链路未打开")
        self._log("  > " + line)
        self.sp.write(line + "\r\n")
        t0 = time.time()
        to = timeout if timeout is not None else self.timeout
        while time.time() - t0 < to:
            ln = self.sp.readline(0.2)
            if not ln:
                continue
            s = ln.decode("ascii", "replace").strip()
            if not s:
                continue
            self._log("  < " + s)
            if expect and s.startswith(expect):
                return s
            if s.startswith("ERR"):
                raise RuntimeError("载荷返回错误: " + s)
        raise TimeoutError("等待 %r 超时（命令 %r）" % (expect, line))

    # ---------- 状态 ----------
    def status(self, retries=3):
        for _ in range(retries):
            try:
                line = self.cmd("status", expect="STAT", timeout=1.5)
                return RelayStatus(_parse_stat(line))
            except TimeoutError:
                continue
        raise TimeoutError("载荷不响应 status（检查板子是否已下载转发程序、"
                           "SD 卡是否启动成了原厂 Linux）")

    # ---------- 控制 ----------
    def set_mode(self, mode):
        m = MODE_VALUE[mode.upper()] if isinstance(mode, str) else int(mode)
        self.cmd("mode %d" % m)
        return m

    def set_ddc_word(self, word):
        self.cmd("ddc 0x%08X" % (word & 0xFFFFFFFF))

    def set_duc_word(self, word):
        self.cmd("duc 0x%08X" % (word & 0xFFFFFFFF))

    def set_duc_hz(self, hz):
        self.cmd("off %d" % int(hz))

    def set_ddc_hz(self, hz):
        self.cmd("xoff %d" % int(hz))

    def set_freq_offset(self, duc_hz, ddc_hz=0):
        self.set_duc_hz(duc_hz)
        self.set_ddc_hz(ddc_hz)

    def set_gain(self, gain_word):
        self.cmd("gain 0x%03X" % (int(gain_word) & 0xFFF))

    def set_dc_block(self, on):
        self.cmd("dc %d" % (1 if on else 0))

    def set_rx_gain(self, db):
        self.cmd("rxgain %d" % int(db))

    def set_tx_atten(self, db):
        self.cmd("txatt %d" % int(db))

    def set_lo(self, rx_mhz, tx_mhz):
        self.cmd("lo %d %d" % (int(rx_mhz), int(tx_mhz)))

    def set_sample_rate(self, msps):
        """警告：必须与 toppin.xdc 里的 DATA_CLK 约束匹配，否则可能损坏 LVDS 接口。"""
        self.cmd("rate %d" % int(msps))

    def mute(self):
        return self.set_mode(MODE_MUTE)

    def relay(self):
        return self.set_mode(MODE_RELAY)

    # ---------- 丢样检测 ----------
    SNAP_PERIOD = 4096          # 固件里状态计数器的快照周期

    def measure(self, seconds=2.0, retries=4, stats=None):
        """在 seconds 秒内测量收发增量，返回 (delta_in, delta_out, rate_msps)。

        ⚠️ 已知的测量竞态
        -----------------
        固件构造 status 行时是**逐个读 AXI 寄存器**的（先读收样点、再读发样点）。
        而 PL 里三个计数器每 4096 个样点做一次一致性快照。如果快照更新正好落在
        这两次 AXI 读之间，读到的两个数就来自不同快照，差值恰好为一个快照周期
        （4096）——**这是测量竞态，不是丢样**。

        所以本函数在发现"差值恰为 4096 的整数倍"时自动重测；若差值不是快照周期
        的整数倍，说明是真丢样，立即返回不重测。
        """
        din = dout = 0
        for attempt in range(retries):
            a = self.status()
            t0 = time.time()
            time.sleep(seconds)
            b = self.status()
            dt = time.time() - t0
            din = (b.n_in - a.n_in) & 0xFFFFFFFF
            dout = (b.n_out - a.n_out) & 0xFFFFFFFF
            if din == dout:
                if stats is not None:
                    stats["retries"] = attempt
                return din, dout, din / dt / 1e6
            if (din - dout) % self.SNAP_PERIOD != 0:
                # 不是整周期偏差 -> 真丢样，不重测
                break
            # 整周期偏差 -> 测量竞态，重测
        if stats is not None:
            stats["retries"] = retries
        return din, dout, din / dt / 1e6


# ------------------------------------------------------------------ 解析
def _parse_stat(line):
    # 固件分两行打印，合并后解析；这里同时兼容单行
    d = {}
    for tok in line.split()[1:]:
        if "=" in tok:
            k, v = tok.split("=", 1)
            try:
                d[k] = int(v, 16) if k in HEX_KEYS else int(v, 0)
            except ValueError:
                d[k] = v
    return d


def _probe(port, baud):
    try:
        sp = SerialPort(port, baud)
    except OSError:
        return False
    try:
        time.sleep(0.2)
        sp.read()
        sp.write("auto 0\r\n")
        time.sleep(0.2)
        sp.read()
        for _ in range(3):
            sp.write("status\r\n")
            t0 = time.time()
            acc = b""
            while time.time() - t0 < 1.2:
                acc += sp.read()
                if b"STAT" in acc:
                    return True
                time.sleep(0.05)
        return False
    finally:
        sp.close()


# ------------------------------------------------------------------ 自测
if __name__ == "__main__":
    import sys
    print("== 频率字换算自测 ==")
    for hz in (0, 10_000, 100_000, 480_000, -100_000, -480_000):
        w = hz_to_word(hz)
        back = word_to_hz(w)
        print("  %+9d Hz -> 0x%08X -> %+12.1f Hz  %s"
              % (hz, w, back, "OK" if abs(back - hz) < 1 else "偏差!"))
    assert hz_to_word(-100_000) == 0xFF2AAAAB, "负频偏换算错误"
    print("  负频偏校验通过 (0xFF2AAAAB)")

    print("\n== 链路自测 ==")
    try:
        if len(sys.argv) > 1:
            lk = RelayLink(sys.argv[1], verbose=True)
        else:
            lk = RelayLink.autodetect(verbose=True)
            print("  自动检测到: %s" % lk.port)
    except OSError as e:
        print("  跳过硬件测试: %s" % e)
        sys.exit(0)
    with lk:
        st = lk.status()
        print(" ", st)
        din, dout, rate = lk.measure(2.0)
        print("  Δin=%d Δout=%d  %.3f MSPS  %s"
              % (din, dout, rate, "零丢样" if din == dout else "!! 丢样"))
