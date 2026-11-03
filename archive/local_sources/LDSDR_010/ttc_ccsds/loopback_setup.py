#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
loopback_setup.py -- 双板环回验证：配置 + 引导接线 + 发射接收解码

链路
----
    遥测板 TX1 ──SMA──► 转发板 RX1
                          ↓ 转发板 relay 模式（可编程衰减）
    转发板 TX1 ──SMA──► 遥测板 RX1
                          ↓
                  遥测板 iio_readdev 抓回来 → Viterbi 解码

用电平预算替代物理衰减器
------------------------
    AD9361 TX 满量程 ≈ +7 dBm，RX 绝对最大 +2.5 dBm
    遥测板 TX 衰减 -30 dB  → -23 dBm  → 转发板 RX 安全（余量 25 dB）
    转发板 TX 衰减 -60 dB  → -53 dBm  → 遥测板 RX 安全（余量 55 dB）

⚠️ 两块板子的上电瞬态都高于稳态：遥测板约 -3 dBm、转发板约 +4.5 dBm。
   所以必须【先配好衰减，再接线】，且接线状态下不要重启任何板子。
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from serial_port import SerialPort

BOARD = "192.168.2.1"
KEY = r"C:\Users\23638\.ssh\id_ed25519_dsh"
LDSDR_PORT = "COM5"

FS_TTC = 2_500_000
LO = 1000.0                     # 两块板子都用 1000 MHz
IF_HZ = 200_000                 # 遥测板的基带中频
TTC_TXATT = 30                  # 遥测板 TX 衰减 dB
TTC_RXGAIN = 30
LDSDR_TXATT = 60                # ★ 转发板 TX 衰减，先给足
LDSDR_RXGAIN = 20

SSH = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no",
       "-o", "UserKnownHostsFile=NUL", "-o", "LogLevel=ERROR",
       "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "root@" + BOARD]

G = "\033[32m"; R = "\033[31m"; Y = "\033[33m"; C = "\033[36m"
B = "\033[1m"; D = "\033[2m"; N = "\033[0m"


def ssh(cmd, timeout=180):
    r = subprocess.run(SSH + [cmd], capture_output=True, timeout=timeout)
    return ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace").strip()


class Ldsdr:
    def __init__(self, port=LDSDR_PORT):
        self.sp = SerialPort(port, 115200)
        time.sleep(0.6)
        self.sp.read()

    def cmd(self, c, w=1.1):
        self.sp.read()
        self.sp.write(c + "\r\n")
        time.sleep(w)
        return self.sp.read().decode("utf-8", "replace").replace("\r", "")

    def line(self, c, pref="STAT", w=1.4):
        r = self.cmd(c, w)
        for l in r.splitlines():
            if l.strip().startswith(pref):
                return l.strip()
        return ""

    def kv(self, line):
        import re
        d = {}
        for tok in re.sub(r"\((\d+)\)", "", line).split():
            if "=" in tok:
                k, v = tok.split("=", 1)
                d[k] = v
        return d

    def close(self):
        try:
            self.sp.close()
        except Exception:
            pass


def banner(t):
    print("\n%s%s%s" % (B + C, t, N))


def main():
    print("%s═══ 双板环回验证：配置阶段 ═══%s" % (B, N))
    print("  遥测板 %s   转发板 %s" % (BOARD, LDSDR_PORT))

    # ---------------- 检查两块板子 ----------------
    banner("1. 检查两块板子")
    r = ssh("echo TTC_OK; iio_attr -V 2>/dev/null | head -1", 60)
    ttc_ok = "TTC_OK" in r
    print("   遥测板: %s  %s" % ("✅" if ttc_ok else "❌", r.replace("\n", " ")[:90]))

    try:
        l = Ldsdr()
        s = l.line("status")
        ldsdr_ok = bool(s)
    except Exception as e:
        print("   转发板: ❌ 打不开 %s: %s" % (LDSDR_PORT, e))
        return 2
    print("   转发板: %s  %s" % ("✅" if ldsdr_ok else "❌", s[:100]))

    # ---------------- 配置转发板 ----------------
    banner("2. 配置转发板（★ 先把它自己的 TX 降到安全电平）")
    l.cmd("auto 0", 0.7)
    for c in ["txatt %d" % LDSDR_TXATT,
              "rxgain %d" % LDSDR_RXGAIN,
              "lo %d %d" % (int(LO), int(LO)),
              "rate 30.72",
              "mode 1", "gain 2048", "ddc 0", "duc 0", "dc 0"]:
        out = l.cmd(c, 1.0)
        first = out.strip().splitlines()[0][:60] if out.strip() else ""
        print("   %s %-16s %s" % ("✅", c, first))

    time.sleep(0.8)
    st = l.kv(l.line("status"))
    print("\n   ch1: mode=%s gain=%s txatt=%s rxgain=%s rxlo=%s txlo=%s fs=%s rc=%s"
          % (st.get("mode"), st.get("gain"), st.get("txatt"), st.get("rxgain"),
             st.get("rxlo"), st.get("txlo"), st.get("fs"), st.get("rc")))

    # ---------------- 配置遥测板 ----------------
    banner("3. 配置遥测板")
    U = "-u ip:localhost"
    ttc_cmds = [
        "iio_attr %s -c ad9361-phy altvoltage1 frequency %d" % (U, int(LO * 1e6)),
        "iio_attr %s -c ad9361-phy altvoltage0 frequency %d" % (U, int(LO * 1e6)),
        "iio_attr %s -c ad9361-phy voltage0 sampling_frequency %d" % (U, FS_TTC),
        "iio_attr %s -c ad9361-phy voltage0 rf_bandwidth 1000000" % U,
        "iio_attr %s -c ad9361-phy voltage1 rf_bandwidth 1000000" % U,
        "iio_attr %s -i -c ad9361-phy voltage0 gain_control_mode manual" % U,
        "iio_attr %s -i -c ad9361-phy voltage0 hardwaregain %d" % (U, TTC_RXGAIN),
        "iio_attr %s -i -c ad9361-phy voltage1 gain_control_mode manual" % U,
        "iio_attr %s -i -c ad9361-phy voltage1 hardwaregain %d" % (U, TTC_RXGAIN),
        "iio_attr %s -o -c ad9361-phy voltage1 hardwaregain -%d" % (U, TTC_TXATT),
        "iio_attr %s -c cf-ad9361-dds-core-lpc altvoltage0 scale 0" % U,
        "iio_attr %s -c cf-ad9361-dds-core-lpc altvoltage1 scale 0" % U,
    ]
    for c in ttc_cmds:
        out = ssh(c, 60)
        print("   %s %s" % ("✅", c.replace(U + " ", "")[:62]))

    print("\n   回读:")
    for k, c in (("TX_LO", "altvoltage1 frequency"), ("RX_LO", "altvoltage0 frequency"),
                 ("采样率", "voltage0 sampling_frequency"),
                 ("TX衰减", "-o -c ad9361-phy voltage1 hardwaregain"),
                 ("RX增益", "-i -c ad9361-phy voltage0 hardwaregain")):
        cc = c if c.startswith("-") else "-c ad9361-phy " + c
        v = ssh("iio_attr %s %s 2>&1|tail -1" % (U, cc), 60)
        print("     %-8s %s" % (k, v[:50]))

    l.close()

    # ---------------- 电平预算 + 接线指引 ----------------
    banner("4. 电平预算（替代物理衰减器）")
    print("""
   遥测板 TX  +7 dBm  −%d dB(衰减) = %+d dBm   ──► 转发板 RX (耐 +2.5 dBm)  %s
   转发板 TX  +7 dBm  −%d dB(衰减) = %+d dBm   ──► 遥测板 RX (耐 +2.5 dBm)  %s

   ⚠️ 上电瞬态比稳态高很多：
        遥测板 ≈ -3 dBm（默认衰减 -10 dB）
        转发板 ≈ +4.5 dBm（默认衰减接近 0 dB）← 会打坏对端
      所以接线状态下【不要重启任何板子】。
""" % (TTC_TXATT, 7 - TTC_TXATT, "✅ 安全",
       LDSDR_TXATT, 7 - LDSDR_TXATT, "✅ 安全"))

    banner("5. 该接线了 —— 只接这两根")
    print("""
   ┌──────────────┐                      ┌──────────────┐
   │   遥测板      │                      │   转发板      │
   │              │                      │              │
   │  TX1 ●───────┼──── SMA 线 ─────────┼──►● RX1      │
   │              │                      │              │
   │  RX1 ●◄──────┼──── SMA 线 ─────────┼───● TX1      │
   └──────────────┘                      └──────────────┘

   ★ 两根线：遥测板 TX1 → 转发板 RX1
             转发板 TX1 → 遥测板 RX1
   ★ 现在两块板子都已经配好，可以安全接线
""")
    print("   接好之后跑：  python loopback_test.py run")
    print("   只抓不收：    python loopback_test.py capture")
    return 0


if __name__ == "__main__":
    sys.exit(main())
