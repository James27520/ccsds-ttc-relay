#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
new_board_iio.py -- 通过 SSH + libiio 验证新板（PlutoSDR 克隆）的收发能力

流程：读属性 -> 配置 -> 抓 IQ -> 传回 PC -> FFT -> 显示频谱
"""

import os
import subprocess
import sys
import time

BOARD, USER = "192.168.2.1", "root"
KEY = r"C:\Users\23638\.ssh\id_ed25519_dsh"
OUT = r"E:\LDSDR_010\new_board_caps.txt"

SSH = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no",
       "-o", "UserKnownHostsFile=/dev/null", "-o", "BatchMode=yes",
       "-o", "ConnectTimeout=10", "%s@%s" % (USER, BOARD)]

f = open(OUT, "w", encoding="utf-8")


def W(s):
    print(s)
    f.write(s + "\n")
    f.flush()


def sh(cmd, timeout=60):
    r = subprocess.run(SSH + [cmd], capture_output=True, text=True, timeout=timeout)
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    return out if out else err


# =====================================================================
W("=" * 72)
W(" 新板（PlutoSDR Rev.C 克隆）能力实测")
W("=" * 72)

W("\n### iio_info 摘要")
info = sh("iio_info 2>&1 | head -60")
for l in info.splitlines():
    W("  " + l)

W("\n### RX DMA 设备可用通道")
W(sh("ls /sys/bus/iio/devices/iio:device3/scan_elements/ 2>&1 | tr '\\n' ' '"))
W(sh("for f in /sys/bus/iio/devices/iio:device3/scan_elements/*_en; do "
     "echo -n \"$(basename $f)=\"; cat $f; done 2>&1 | tr '\\n' ' '"))

W("\n### 关键属性现状")
attrs = [
    ("RX_LO 频率", "/sys/bus/iio/devices/iio:device0/out_altvoltage0_RX_LO_frequency"),
    ("TX_LO 频率", "/sys/bus/iio/devices/iio:device0/out_altvoltage1_TX_LO_frequency"),
    ("采样率", "/sys/bus/iio/devices/iio:device0/in_voltage_sampling_frequency"),
    ("RF 带宽", "/sys/bus/iio/devices/iio:device0/in_voltage_rf_bandwidth"),
    ("RX 增益模式", "/sys/bus/iio/devices/iio:device0/in_voltage0_gain_control_mode"),
    ("RX 硬件增益", "/sys/bus/iio/devices/iio:device0/in_voltage0_hardwaregain"),
    ("RX RSSI", "/sys/bus/iio/devices/iio:device0/in_voltage0_rssi"),
    ("TX 衰减", "/sys/bus/iio/devices/iio:device0/out_voltage0_hardwaregain"),
]
for name, p in attrs:
    W("  %-14s %s" % (name, sh("cat %s 2>&1" % p)))

W("\n### 频段边界测试（读驱动的可用范围）")
W("  RX_LO available : " + sh(
    "cat /sys/bus/iio/devices/iio:device0/out_altvoltage0_RX_LO_frequency_available 2>&1"))
W("  采样率 available : " + sh(
    "cat /sys/bus/iio/devices/iio:device0/in_voltage_sampling_frequency_available 2>&1"))
W("  RF带宽 available : " + sh(
    "cat /sys/bus/iio/devices/iio:device0/in_voltage_rf_bandwidth_available 2>&1"))

# ---------------- 抓 IQ ----------------
W("\n### 抓 IQ 数据")
SR = 2000000            # 2 MSPS，窄带，够快
NSAMP = 262144          # 26 万样点
W("  设置采样率 %d Hz ..." % SR)
W("  " + sh("echo %d > /sys/bus/iio/devices/iio:device0/in_voltage_sampling_frequency; "
            "cat /sys/bus/iio/devices/iio:device0/in_voltage_sampling_frequency" % SR))
W("  设置 RX_LO 900 MHz ...")
W("  " + sh("echo 900000000 > /sys/bus/iio/devices/iio:device0/out_altvoltage0_RX_LO_frequency; "
            "cat /sys/bus/iio/devices/iio:device0/out_altvoltage0_RX_LO_frequency"))

W("  启用扫描通道 ...")
W("  " + sh("for c in voltage0 voltage1 voltage2 voltage3; do "
            "echo 1 > /sys/bus/iio/devices/iio:device3/scan_elements/"
            "in_${c}_en 2>/dev/null; done; "
            "for f in /sys/bus/iio/devices/iio:device3/scan_elements/*_en; do "
            "echo -n \"$(basename $f)=\"; cat $f; done 2>&1 | tr '\\n' ' '"))

W("  用 iio_readdev 抓 %d 样点 ..." % NSAMP)
t0 = time.time()
r = sh("cd /tmp && iio_readdev -s %d cf-ad9361-lpc voltage0 voltage1 > /tmp/iq.bin 2>/tmp/iq.err; "
       "echo \"rc=$?\"; ls -l /tmp/iq.bin; cat /tmp/iq.err | head -3" % NSAMP, timeout=180)
W("  " + r.replace("\n", "\n  "))
W("  用时 %.1f 秒" % (time.time() - t0))

# 若失败，列出可用通道名
if "No such file" in r or "rc=1" in r or "not found" in r.lower():
    W("\n  抓取失败，列出设备3的通道名：")
    W("  " + sh("ls /sys/bus/iio/devices/iio:device3/ 2>&1 | tr '\\n' ' '"))
    W("  " + sh("iio_readdev --help 2>&1 | head -20"))

# ---------------- 传回 PC ----------------
W("\n### 传回 PC")
dest = r"E:\LDSDR_010\iq_new_board.bin"
r = subprocess.run(["scp", "-i", KEY, "-o", "StrictHostKeyChecking=no",
                    "-o", "UserKnownHostsFile=/dev/null", "-o", "BatchMode=yes",
                    "%s@%s:/tmp/iq.bin" % (USER, BOARD), dest],
                   capture_output=True, text=True, timeout=300)
W("  scp rc=%d" % r.returncode)
if r.stderr.strip():
    W("  " + r.stderr.strip()[:200])
if os.path.exists(dest):
    W("  本地文件 %s  %d 字节" % (dest, os.path.getsize(dest)))

f.close()
print("\n结果存 %s" % OUT)
