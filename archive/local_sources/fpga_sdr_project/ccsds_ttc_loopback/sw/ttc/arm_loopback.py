#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
arm_loopback.py -- 把两块板子配置成【安全 + 可用】的自环状态

改动要点（相对刚才给 CMU200 用的配置）
--------------------------------------
  1) 转发板 lo 1000 900  ->  lo 1000 1000
     自环不需要搬频。遥测板 RX_LO=1000，转发板必须也在 1000 发，
     否则遥测板收不到。
  2) 转发板 txatt 30 -> 60
     上电瞬态 +4.5 dBm 是唯一真实风险，衰减给足后稳态只有 -53 dBm。
  3) 转发板 rxgain 5（实测 >=15 就饱和）
  4) 遥测板 RX 增益 30 -> 40，补偿转发板的 -60 dB 衰减
"""
import subprocess
import sys
import time

sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from serial_port import SerialPort

BOARD = "192.168.2.1"
KEY = r"C:\Users\23638\.ssh\id_ed25519_dsh"
SSH = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no",
       "-o", "UserKnownHostsFile=NUL", "-o", "LogLevel=ERROR",
       "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "root@" + BOARD]

G = "\033[32m"; R = "\033[31m"; Y = "\033[33m"; C = "\033[36m"
B = "\033[1m"; D = "\033[2m"; N = "\033[0m"

LO = 1000.0
TTC_TXATT = 30
TTC_RXGAIN = 40
RELAY_TXATT = 60
RELAY_RXGAIN = 5


def ssh(cmd, timeout=120):
    r = subprocess.run(SSH + [cmd], capture_output=True, timeout=timeout)
    return ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace").strip()


sp = SerialPort("COM5", 115200)
time.sleep(0.8); sp.read()


def rc(c, w=1.1):
    sp.read(); sp.write(c + "\r\n"); time.sleep(w)
    return sp.read().decode("utf-8", "replace").replace("\r", "")


def rstat():
    for l in rc("status", 1.5).splitlines():
        if l.strip().startswith("STAT"):
            return l.strip()
    return ""


def kv(l):
    import re
    d = {}
    for t in re.sub(r"\((\d+)\)", "", l).split():
        if "=" in t:
            k, v = t.split("=", 1); d[k] = v
    return d


print("%s═══ 配置自环状态（安全 + 可用）═══%s" % (B + C, N))

print("\n%s[1] 转发板%s" % (C, N))
rc("auto 0", 0.7)
for c in ["txatt %d" % RELAY_TXATT,
          "rxgain %d" % RELAY_RXGAIN,
          "lo %d %d" % (int(LO), int(LO)),      # ★ 不搬频
          "rate 30.72",
          "mode 1", "gain 2048", "ddc 0", "duc 0", "dc 0"]:
    print("   ✅ %-16s %s" % (c, rc(c, 1.0).strip().splitlines()[0][:50]))

time.sleep(0.8)
rs = rstat()
print("\n   " + rs)
k = kv(rs)

print("\n   4 秒 clip 检查:")
a = kv(rstat()); time.sleep(4); b = kv(rstat())
cl = int(b.get("clip", 0)) - int(a.get("clip", 0))
print("      增长 = %d  %s" % (cl, "✅ 无饱和" if cl < 500 else "⚠️ 还有饱和，先拔掉 CMU200 的线"))

print("\n%s[2] 遥测板%s" % (C, N))
U = "-u ip:localhost"
for c in ["iio_attr %s -c ad9361-phy altvoltage1 frequency %d" % (U, int(LO * 1e6)),
          "iio_attr %s -c ad9361-phy altvoltage0 frequency %d" % (U, int(LO * 1e6)),
          "iio_attr %s -c ad9361-phy voltage0 sampling_frequency 2500000" % U,
          "iio_attr %s -c ad9361-phy voltage0 rf_bandwidth 1000000" % U,
          "iio_attr %s -c ad9361-phy voltage1 rf_bandwidth 1000000" % U,
          "iio_attr %s -i -c ad9361-phy voltage0 gain_control_mode manual" % U,
          "iio_attr %s -i -c ad9361-phy voltage0 hardwaregain %d" % (U, TTC_RXGAIN),
          "iio_attr %s -i -c ad9361-phy voltage1 gain_control_mode manual" % U,
          "iio_attr %s -i -c ad9361-phy voltage1 hardwaregain %d" % (U, TTC_RXGAIN),
          "iio_attr %s -o -c ad9361-phy voltage1 hardwaregain -%d" % (U, TTC_TXATT),
          "iio_attr %s -c cf-ad9361-dds-core-lpc altvoltage0 scale 0" % U,
          "iio_attr %s -c cf-ad9361-dds-core-lpc altvoltage1 scale 0" % U]:
    ssh(c, 60)
    print("   ✅ %s" % c.replace(U + " ", "")[:62])

print("\n   回读:")
for kk, c in (("TX_LO", "-c ad9361-phy altvoltage1 frequency"),
              ("RX_LO", "-c ad9361-phy altvoltage0 frequency"),
              ("TX衰减", "-o -c ad9361-phy voltage1 hardwaregain"),
              ("RX增益", "-i -c ad9361-phy voltage0 hardwaregain")):
    print("     %-8s %s" % (kk, ssh("iio_attr %s %s 2>&1|tail -1" % (U, c), 60)[:40]))

sp.close()

print("\n%s[3] 参数汇总%s" % (C, N))
print("""
   ┌──────────────┬──────────────┬──────────────┐
   │              │   遥测板      │   转发板      │
   ├──────────────┼──────────────┼──────────────┤
   │ LO           │ RX=1000      │ RX=1000      │
   │              │ TX=1000      │ TX=1000      │  ← 不搬频
   │ 采样率        │ 2.5 MSPS     │ 30.72 MSPS   │
   │ TX 衰减       │ -30 dB       │ -60 dB       │  ← 转发板给足
   │ RX 增益       │ 40 dB        │ 5 dB         │
   │ 模式          │ —            │ relay(gain=1)│
   └──────────────┴──────────────┴──────────────┘

  电平预算：
     遥测板 TX  +7 - 30 = %+4d dBm ──► 转发板 RX(耐+2.5)  ✅ 余量 %d dB
     转发板 TX  +7 - 60 = %+4d dBm ──► 遥测板 RX(耐+2.5)  ✅ 余量 %d dB

  ⚠️ 唯一的风险是转发板上电瞬态 +4.5 dBm。接线状态下不要重启转发板；
     要重启先拔线。最好串一个 30 dB SMA 衰减器，就彻底安全了。
""" % (7 - TTC_TXATT, 2.5 - (7 - TTC_TXATT),
       7 - RELAY_TXATT, 2.5 - (7 - RELAY_TXATT)))

print("%s[4] 现在可以接线了%s" % (C + B, N))
print("""
   ① 先把 CMU200 从转发板上拔掉（它的强信号在打饱和）
   ② 接两根 SMA（同一组，别跨组）：
        遥测板 TX1 ──► 转发板 RX1
        转发板 TX1 ──► 遥测板 RX1
   ③ 跑：  python diag_link.py      ← 先看链路通不通
           python loopback_test.py run   ← 通了再解码
""")
