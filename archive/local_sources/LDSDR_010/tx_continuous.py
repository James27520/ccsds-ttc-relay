#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tx_continuous.py -- 两步验证

第一步：用硬件 DDS 连续发一个单音，验证 TX 链路（应该看到稳定载波）
第二步：用 FIFO 让设备常开，做连续转发
"""
import subprocess, sys, time

BOARD, USER = "192.168.2.1", "root"
KEY = r"C:\Users\23638\.ssh\id_ed25519_dsh"
SSH = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no",
       "-o", "UserKnownHostsFile=/dev/null", "-o", "BatchMode=yes",
       "-o", "ConnectTimeout=10", "%s@%s" % (USER, BOARD)]
D0 = "/sys/bus/iio/devices/iio:device0"
DDS = "cf-ad9361-dds-core-lpc"

act = sys.argv[1] if len(sys.argv) > 1 else "dds"


def sh(c, t=180):
    r = subprocess.run(SSH + [c], capture_output=True, timeout=t)
    return (r.stdout or b"").decode("utf-8", "replace").strip() or \
           (r.stderr or b"").decode("utf-8", "replace").strip()


if act == "stop":
    print(sh("pkill -f iio_; rm -f /tmp/fifo; "
             "for c in 0 1 2 3; do echo 0 > /sys/bus/iio/devices/iio:device2/"
             "scan_elements/out_voltage${c}_en 2>/dev/null; done; echo stopped"))
    sys.exit(0)

print("=" * 76)
print(" 第一步：硬件 DDS 连续发单音（验证 TX 链路）")
print("=" * 76)

print("\n[1] TX_LO = 1000.0 MHz")
print("  " + sh("echo 1000000000 > %s/out_altvoltage1_TX_LO_frequency; "
                "cat %s/out_altvoltage1_TX_LO_frequency" % (D0, D0)).replace("\n", " "))

print("\n[2] 关掉 TX 的 DMA 通道（让 DDS 数据生效）")
print("  " + sh("for c in 0 1 2 3; do echo 0 > /sys/bus/iio/devices/iio:device2/"
                "scan_elements/out_voltage${c}_en; done; "
                "for f in /sys/bus/iio/devices/iio:device2/scan_elements/*_en; do "
                "echo -n \"$(basename $f)=\"; cat $f; done").replace("\n", " "))

print("\n[3] 看 DDS 有哪些通道和属性")
print(sh("iio_attr -d %s 2>&1 | head -30" % DDS))

print("\n[4] 设置 DDS：+100 kHz，幅度适中")
# DDS 通道名通常 altvoltage0/1
for c in ["iio_attr -c cf-ad9361-dds-core-lpc altvoltage0 frequency 100000",
          "iio_attr -c cf-ad9361-dds-core-lpc altvoltage0 scale 0.5",
          "iio_attr -c cf-ad9361-dds-core-lpc altvoltage0 raw 2048",
          "iio_attr -c cf-ad9361-dds-core-lpc altvoltage1 frequency 100000",
          "iio_attr -c cf-ad9361-dds-core-lpc altvoltage1 scale 0.5",
          "iio_attr -c cf-ad9361-dds-core-lpc altvoltage1 raw 2048"]:
    out = sh(c, t=40)
    print("  %-60s %s" % (c.replace("iio_attr -c cf-ad9361-dds-core-lpc ", ""), out[:50]))

print("\n[5] 回读 DDS 状态")
print(sh("for ch in altvoltage0 altvoltage1; do "
         "echo \"--- $ch ---\"; "
         "for a in frequency scale raw phase sampling_frequency; do "
         "  echo -n \"  $a = \"; iio_attr -c cf-ad9361-dds-core-lpc $ch $a 2>&1 | head -1; "
         "done; done"))

print("\n[6] 确认 TX 衰减")
print("  " + sh("cat %s/out_voltage0_hardwaregain" % D0).replace("\n", " "))

print("\n" + "=" * 76)
print(" >>> 现在 CMU200 设到 1000.1 MHz，应该看到【稳定连续】的载波 <<<")
print("     如果稳定 -> TX 链路没问题，之前断续纯粹是转发循环的占空比问题")
print("     如果还是没有 -> TX 链路本身有问题，另查")
print("=" * 76)
print("\n停止： python tx_continuous.py stop")
