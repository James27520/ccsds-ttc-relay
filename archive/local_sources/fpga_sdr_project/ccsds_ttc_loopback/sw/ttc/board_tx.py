#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
board_tx.py -- 遥测板发射管理（Python 版，避免 shell 引号地狱）

板子上的现实约束（实测）
------------------------
  ✅ 有: iio_writedev / iio_attr / kill / killall / pidof / ps
  ❌ 没有: pkill / timeout / python
  → 所以定时不能用 timeout，改成把 -s 设成"正好 N 秒的样点数"，
    iio_writedev 到点自己退出，cat 循环收到 SIGPIPE 也结束。

用法
----
    python board_tx.py clean                 # 清掉残留
    python board_tx.py cont 40               # 连续发 40 秒
    python board_tx.py once                  # 单次发一遍
    python board_tx.py status                # 看状态
"""
import subprocess
import sys
import time

BOARD = "192.168.2.1"
KEY = r"C:\Users\23638\.ssh\id_ed25519_dsh"
FS = 2_500_000
N_SAMP = 3456320                    # 一帧波形样点数
WAVE = "/tmp/wave.bin"

SSH = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no",
       "-o", "UserKnownHostsFile=NUL", "-o", "LogLevel=ERROR",
       "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "root@" + BOARD]


def ssh(cmd, timeout=600):
    r = subprocess.run(SSH + [cmd], capture_output=True, timeout=timeout)
    return ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace").strip()


def q(s):
    """安全放进单引号，供远端 sh 使用"""
    return "'" + s.replace("'", "'\\''") + "'"


def clean():
    print("=== 清理板子上的残留进程 ===")
    print("  " + ssh("killall -9 iio_writedev 2>/dev/null; echo killall_done"))
    # 干掉所有含 wave.bin 的 sh -c 壳
    print("  " + ssh("for p in $(pidof sh); do "
                     "if grep -q wave.bin /proc/$p/cmdline 2>/dev/null; then "
                     "kill -9 $p 2>/dev/null; echo killed $p; fi; done; echo scan_done"))
    time.sleep(1)
    r = ssh("ps | grep -E 'iio_writedev|wave.bin' | grep -v grep | wc -l")
    print("  残留相关进程数: %s" % r)


def status():
    print("=== 板子状态 ===")
    for k, c in (("TX_LO", "-c ad9361-phy altvoltage1 frequency"),
                 ("采样率", "-c ad9361-phy voltage0 sampling_frequency"),
                 ("TX衰减", "-o -c ad9361-phy voltage1 hardwaregain"),
                 ("DDS", "-c cf-ad9361-dds-core-lpc altvoltage0 scale")):
        print("  %-8s %s" % (k, ssh("iio_attr -u ip:localhost %s 2>&1|tail -1" % c, 60)))
    print("  波形文件 %s" % ssh("ls -l %s 2>/dev/null || echo MISSING" % WAVE, 60))
    print("  iio 进程 %s" % ssh("ps | grep '[i]io_writedev' | wc -l", 60))


def cont(secs):
    """连续发射 secs 秒

    ★ 关键：stdin 的供给必须是【有界】循环。
      用 while true 的话，iio_writedev 到点退出后 cat 还在写管道，
      管道不关、SSH 会话永远挂着（实测卡了 160 秒）。
      改成算好需要几遍、用 for 循环，写完自然结束。
    """
    n = FS * secs
    passes = (n + N_SAMP - 1) // N_SAMP + 1        # 多给一遍，确保喂满
    total = passes * N_SAMP
    print("=== 连续发射 %d 秒 ===" % secs)
    print("  需要样点 = %d  (%.1f 秒 @ %.1f MSPS)" % (n, n / FS, FS / 1e6))
    print("  波形一遍 = %d 样点，循环 %d 遍（共 %d 样点）"
          % (N_SAMP, passes, total))
    print("  iio_writedev 只启动一次 → 没有进程重启的空隙")
    print("  ★ 现在去 CMU200 看，应该是连续稳定的\n")

    inner = ("for i in $(seq 1 %d); do cat %s; done | "
             "iio_writedev -u ip:localhost -s %d -b 65536 "
             "cf-ad9361-dds-core-lpc voltage0 voltage1" % (passes, WAVE, n))
    t0 = time.time()
    try:
        r = ssh(inner, timeout=secs + 90)
        for line in r.splitlines():
            if line.strip():
                print("  | %s" % line[:110])
    except subprocess.TimeoutExpired:
        print("  ⚠️ SSH 超时（信号可能还在发，检查残留进程）")
    dt = time.time() - t0
    print("  实际耗时 %.1f 秒  %s"
          % (dt, "✅" if abs(dt - secs) < 20 else "⚠️ 偏差较大，可能有残留"))


def once():
    print("=== 单次发射一遍 ===")
    t0 = time.time()
    r = ssh("cd /tmp && iio_writedev -u ip:localhost -s %d -b 65536 "
            "cf-ad9361-dds-core-lpc voltage0 voltage1 < %s 2>&1; echo rc=$?"
            % (N_SAMP, WAVE), timeout=200)
    print("  耗时 %.1f 秒" % (time.time() - t0))
    for line in r.splitlines():
        if line.strip():
            print("  | %s" % line[:110])


def main():
    act = sys.argv[1] if len(sys.argv) > 1 else "status"
    if act == "clean":
        clean()
    elif act == "status":
        status()
    elif act == "once":
        once()
    elif act == "cont":
        secs = int(sys.argv[2]) if len(sys.argv) > 2 else 40
        clean()
        cont(secs)
        clean()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
