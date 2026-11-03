#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tx_now.py -- 干净地发射一次并确认结果（不解析 SSH 警告）"""
import subprocess
import sys
import time

BOARD = "192.168.2.1"
KEY = r"C:\Users\23638\.ssh\id_ed25519_dsh"
SSH = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no",
       "-o", "UserKnownHostsFile=NUL", "-o", "LogLevel=ERROR",
       "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "root@" + BOARD]


def ssh(cmd, timeout=180):
    r = subprocess.run(SSH + [cmd], capture_output=True, timeout=timeout)
    return ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace").strip()


print("=== 1. 板子上的波形文件 ===")
print("  " + ssh("ls -l /tmp/wave.bin; md5sum /tmp/wave.bin"))

print("\n=== 2. 当前配置 ===")
for k, c in (("TX_LO", "-c ad9361-phy altvoltage1 frequency"),
             ("采样率", "-c ad9361-phy voltage0 sampling_frequency"),
             ("TX衰减(输出)", "-o -c ad9361-phy voltage1 hardwaregain"),
             ("DDS scale", "-c cf-ad9361-dds-core-lpc altvoltage0 scale")):
    print("  %-14s %s" % (k, ssh("iio_attr %s 2>&1 | tail -1" % c)))

N = 3456320
print("\n=== 3. 发射一次（%d 样点）===" % N)
t0 = time.time()
r = ssh("cd /tmp && iio_writedev -u ip:localhost -s %d -b 65536 "
        "cf-ad9361-dds-core-lpc voltage0 voltage1 < /tmp/wave.bin 2>&1; "
        "echo \"EXIT=$?\"" % N, timeout=200)
el = time.time() - t0
print("  耗时 %.1f 秒" % el)
for line in r.splitlines():
    if line.strip():
        print("  | %s" % line[:110])

print("\n=== 4. 连发 20 次保持信号（约 30 秒）===")
print("  现在请到 CMU200 上看 1000.2 MHz")
cmd = ("cd /tmp && for i in $(seq 1 20); do "
       "iio_writedev -u ip:localhost -s %d -b 65536 "
       "cf-ad9361-dds-core-lpc voltage0 voltage1 < /tmp/wave.bin "
       ">/dev/null 2>&1 || echo FAIL_$i; done; echo LOOP_DONE" % N)
t0 = time.time()
r = ssh(cmd, timeout=400)
print("  循环结束，耗时 %.1f 秒  输出: %s" % (time.time() - t0, r.strip()[:100]))
