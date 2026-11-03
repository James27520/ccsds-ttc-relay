#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tx_continuous.py -- 连续发射（把波形用 cat 循环喂给 iio_writedev）

为什么这样能连续
----------------
反复启动 iio_writedev 每次都要重新读 13.8MB 文件 + 建 DMA 缓冲，中间有约
0.3 秒空隙，频谱仪上就是"一闪一闪"。

改成让 iio_writedev【只启动一次】，stdin 用 cat 死循环喂同一个文件，
DMA 就一直在跑，没有空隙。用 timeout 控制发多久。
"""
import subprocess
import sys
import time

BOARD = "192.168.2.1"
KEY = r"C:\Users\23638\.ssh\id_ed25519_dsh"
SSH = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no",
       "-o", "UserKnownHostsFile=NUL", "-o", "LogLevel=ERROR",
       "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "root@" + BOARD]


def ssh(cmd, timeout=900):
    r = subprocess.run(SSH + [cmd], capture_output=True, timeout=timeout)
    return ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace").strip()


def repr_sh(s):
    """把字符串安全地放进单引号，供远端 sh -c 使用"""
    return "'" + s.replace("'", "'\\''") + "'"


def main():
    secs = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    N = 3456320                       # 一帧波形的样点数

    print("=== 检查板子状态 ===")
    print("  " + ssh("iio_attr -u ip:localhost -o -c ad9361-phy voltage1 hardwaregain 2>&1|tail -1", 60))
    print("  " + ssh("ls -l /tmp/wave.bin", 60))

    # 让 iio_writedev 一次读很久，stdin 由 cat 死循环供给
    # ★ timeout 必须包住【整个子 shell】，否则 cat 循环在 iio_writedev 被杀后
    #   还继续往断掉的管道里写，SSH 会话会一直挂住不返回。
    big = N * 1000
    print("\n=== 连续发射 %d 秒 ===" % secs)
    print("  iio_writedev 只启动一次，stdin 用 cat 循环喂")
    print("  ★ 现在去 CMU200 看，应该是连续稳定的了\n")

    inner = ("( while true; do cat /tmp/wave.bin; done ) | "
             "iio_writedev -u ip:localhost -s %d -b 65536 "
             "cf-ad9361-dds-core-lpc voltage0 voltage1" % big)
    cmd = "timeout -k 2 %d sh -c %s; echo PIPE_DONE rc=$?" % (secs, repr_sh(inner))

    t0 = time.time()
    try:
        r = ssh(cmd, timeout=secs + 90)
        for line in r.splitlines():
            if line.strip():
                print("  | %s" % line[:110])
    except subprocess.TimeoutExpired:
        print("  超时（发射应已结束）")
    print("  实际耗时 %.1f 秒" % (time.time() - t0))

    print("\n=== 停止后确认 DDS 是关的 ===")
    print("  " + ssh("iio_attr -u ip:localhost -c cf-ad9361-dds-core-lpc altvoltage0 scale 2>&1|tail -1", 60))
    return 0


if __name__ == "__main__":
    sys.exit(main())
