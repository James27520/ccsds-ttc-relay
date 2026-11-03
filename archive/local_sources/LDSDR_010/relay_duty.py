#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测量并改善转发占空比"""
import subprocess, sys, time

BOARD, USER = "192.168.2.1", "root"
KEY = r"C:\Users\23638\.ssh\id_ed25519_dsh"
SSH = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no",
       "-o", "UserKnownHostsFile=/dev/null", "-o", "BatchMode=yes",
       "-o", "ConnectTimeout=10", "%s@%s" % (USER, BOARD)]


def sh(cmd, timeout=180):
    r = subprocess.run(SSH + [cmd], capture_output=True, timeout=timeout)
    return (r.stdout or b"").decode("utf-8", "replace").strip() or \
           (r.stderr or b"").decode("utf-8", "replace").strip()


print("=== 1. 停掉当前循环 ===")
print("  " + sh("pkill -f relay.sh; pkill -f iio_readdev; pkill -f iio_writedev; sleep 1; "
                "ps | grep -c '[r]elay' || true"))

print("\n=== 2. 测量单次「读+写」周期耗时 ===")
print("  用一个循环跑 20 轮，量总时间")
for N in (8192, 32768, 131072, 262144):
    cmd = ("S=$(date +%%s%%N); i=0; "
           "while [ $i -lt 20 ]; do "
           "  iio_readdev -s %d -b %d cf-ad9361-lpc voltage0 voltage1 > /tmp/b.bin 2>/dev/null; "
           "  iio_writedev -s %d -b %d cf-ad9361-dds-core-lpc voltage0 voltage1 < /tmp/b.bin 2>/dev/null; "
           "  i=$((i+1)); done; E=$(date +%%s%%N); "
           "echo $(( (E-S)/1000000/20 ))" % (N, N, N, N))
    ms = sh(cmd, timeout=300)
    try:
        ms = int(ms)
    except Exception:
        print("  N=%-7d 解析失败: %s" % (N, ms[:60])); continue
    play_ms = N / 4000.0          # 4 MSPS 下的播放时长
    duty = 100.0 * play_ms / ms if ms else 0
    print("  N=%-7d  每轮 %4d ms   其中播放 %5.1f ms   占空比约 %5.1f%%"
          % (N, ms, play_ms, duty))

print("\n=== 3. 试「FIFO 常开」方案（设备不关，连续流）===")
r = sh("rm -f /tmp/fifo; mkfifo /tmp/fifo; "
       "(iio_writedev -b 262144 cf-ad9361-dds-core-lpc voltage0 voltage1 "
       "< /tmp/fifo &) ; sleep 0.5; "
       "(iio_readdev -b 262144 cf-ad9361-lpc voltage0 voltage1 > /tmp/fifo &) ; "
       "sleep 3; echo '--- 进程 ---'; ps | grep '[i]io_' | head -4; "
       "echo '--- fifo 有无阻塞 ---'; ls -l /tmp/fifo", timeout=120)
print("  " + r.replace("\n", "\n  "))

print("\n=== 4. 跑 3 秒看是否真的在流 ===")
print("  " + sh("S=$(date +%s%N); sleep 3; E=$(date +%s%N); "
                "echo \"3 秒后仍在运行:\"; ps | grep -c '[i]io_readdev'; "
                "ps | grep -c '[i]io_writedev'").replace("\n", "\n  "))

print("\n=== 5. 清理 ===")
print("  " + sh("pkill -f iio_readdev; pkill -f iio_writedev; rm -f /tmp/fifo; echo done"))
