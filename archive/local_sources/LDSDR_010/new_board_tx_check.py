#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查新板的 TX 通路是否可用（不发真实信号，只验证通路）"""
import subprocess, numpy as np

BOARD, USER = "192.168.2.1", "root"
KEY = r"C:\Users\23638\.ssh\id_ed25519_dsh"
SSH = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no",
       "-o", "UserKnownHostsFile=/dev/null", "-o", "BatchMode=yes",
       "-o", "ConnectTimeout=10", "%s@%s" % (USER, BOARD)]


def sh(cmd, timeout=60):
    r = subprocess.run(SSH + [cmd], capture_output=True, text=True, timeout=timeout)
    return ((r.stdout or "").strip() or (r.stderr or "").strip())


print("=== 1. TX DMA 设备的可用通道 ===")
print(sh("ls /sys/bus/iio/devices/iio:device2/scan_elements/ | tr '\\n' ' '"))
print("使能状态:")
print(sh("for f in /sys/bus/iio/devices/iio:device2/scan_elements/*_en; do "
         "echo -n \"$(basename $f)=\"; cat $f; done | tr '\\n' ' '"))

print("\n=== 2. 设置 TX_LO = 1000.1 MHz ===")
print("  " + sh("iio_attr -c ad9361-phy altvoltage1 frequency 1000100000"))
print("  回读: " + sh("iio_attr -c ad9361-phy altvoltage1 frequency"))

print("\n=== 3. 设置 TX 采样率 / 带宽 / 衰减 ===")
for c in ["iio_attr -c ad9361-phy voltage1 sampling_frequency 1000000",
          "iio_attr -c ad9361-phy voltage1 rf_bandwidth 1000000"]:
    print("  %-50s -> %s" % (c.replace("iio_attr -c ad9361-phy ", ""), sh(c)))
print("  out_voltage0_hardwaregain 回读: " + sh("iio_attr -c ad9361-phy voltage1 hardwaregain"))
print("  尝试设 -30 dB: " + sh("iio_attr -c ad9361-phy voltage1 hardwaregain -30"))

print("\n=== 4. 生成一段测试 IQ 并发送（验证通路，不接仪器也不会坏）===")
N = 8192
fs = 1000000.0
t = np.arange(N) / fs
# 基带 100 kHz 单音，幅度 1/4 满量程
tone = (0.25 * np.cos(2 * np.pi * 100e3 * t) * 32767).astype(np.int16)
iq = np.empty(2 * N, dtype=np.int16)
iq[0::2] = tone       # I
iq[1::2] = 0          # Q
local = r"E:\LDSDR_010\tx_tone.bin"
iq.tofile(local)
print("  本地生成 %s  (%d 字节, %d 样点)" % (local, iq.nbytes, N))

import os
r = subprocess.run(["scp", "-i", KEY, "-o", "StrictHostKeyChecking=no",
                    "-o", "UserKnownHostsFile=/dev/null", "-o", "BatchMode=yes",
                    "-O", local, "%s@%s:/tmp/tx.bin" % (USER, BOARD)],
                   capture_output=True, text=True, timeout=120)
print("  scp -O 上传 rc=%d  %s" % (r.returncode, (r.stderr or "").strip()[:120]))

print("\n=== 5. 用 iio_writedev 发送 ===")
cmd = ("cat /tmp/tx.bin | iio_writedev -s %d cf-ad9361-dds-core-lpc voltage0 voltage1 2>&1; "
       "echo rc=$?" % N)
out = sh(cmd, timeout=60)
print("  " + out.replace("\n", "\n  "))

print("\n=== 6. 是否有 iio_writedev 用法说明 ===")
print(sh("iio_writedev --help 2>&1 | head -18"))
