#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
uboot_autofix.py -- 等待板子重启 → 打断 U-Boot → 测试 env import 覆盖行为 → 尝试自动启动转发

做三件事：
  1. 测 env import 会不会覆盖已存在的变量（决定能不能直接改 bootcmd）
  2. 测几种 uenvcmd 写法哪个能通过 `test -n $uenvcmd`
  3. 直接把转发命令跑一遍，确认可用
"""

import sys
import time

sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from serial_port import SerialPort                       # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM5"


def send(sp, cmd, wait=3.0, echo=True):
    if echo:
        print("\n>>> " + cmd)
    sp.write(cmd + "\r\n")
    t0 = time.time()
    line = bytearray()
    while time.time() - t0 < wait:
        d = sp.read()
        if d:
            line += d
            t0 = time.time()
        else:
            time.sleep(0.05)
    txt = bytes(line).decode("utf-8", "replace")
    if echo:
        for l in txt.splitlines():
            s = l.strip()
            if s and s != cmd and s != "Pluto>":
                print("    " + s[:120])
    return txt


def main():
    sp = SerialPort(PORT, 115200)
    print("=== 打开 %s，等待板子重启 ===" % PORT)
    time.sleep(0.3)
    sp.read()

    acc = bytearray()
    t0 = time.time()
    hit = False
    while time.time() - t0 < 180:
        d = sp.read()
        if d:
            acc += d
            sys.stdout.write(d.decode("utf-8", "replace"))
            sys.stdout.flush()
        if not hit and b"Hit any key" in acc:
            sp.write(" ")
            hit = True
            print("\n>>> 已打断自动启动 <<<\n")
        if hit and b"Pluto> " in bytes(acc):
            break
        time.sleep(0.05)

    if not hit:
        print("\n!! 没抓到 autoboot 提示。请确认是按复位键（不是断电导致串口消失）")
        sp.close()
        return 1
    time.sleep(0.6)
    sp.read()

    print("=" * 70)
    print(" 测试 1: env import 会不会覆盖已存在的变量")
    print("=" * 70)
    # 把当前环境导出到内存，改掉 bootcmd，再导入，看 bootcmd 变不变
    send(sp, "setenv CHKTEST original")
    send(sp, "setenv bootcmd 'echo SENTINEL_BOOTCMD'")
    send(sp, "env export -t 0x3000000")
    send(sp, "setenv bootcmd 'echo RESTORED_BOOTCMD'")
    r = send(sp, "env import -t 0x3000000 ${filesize}")
    r = send(sp, "printenv bootcmd")
    if "SENTINEL_BOOTCMD" in r:
        print("\n  ==> env import 会覆盖已存在的变量 ✅  可以直接改 bootcmd")
        overwrite = True
    else:
        print("\n  ==> env import 不覆盖已存在的变量 ❌  只能靠 uenvcmd")
        overwrite = False

    print("\n" + "=" * 70)
    print(" 测试 2: 哪种 uenvcmd 写法能通过 test -n")
    print("=" * 70)
    for name, val in (("单词", "relayboot"),
                      ("两词", "run relayboot"),
                      ("带分号无空格", "echo;echo"),
                      ("原样多词", "echo === X ===; load mmc 0 0x1000000 relay.bit")):
        send(sp, "setenv uenvcmd '%s'" % val, echo=False)
        r = send(sp, "test -n $uenvcmd; echo TRC=$?", echo=False)
        ok = "TRC=0" in r
        print("  %-14s -> test -n 结果: %s    (%s)" % (name, "通过" if ok else "失败", val[:45]))

    print("\n" + "=" * 70)
    print(" 测试 3: 直接跑一遍转发启动命令")
    print("=" * 70)
    send(sp, "setenv relayboot 'echo === PL RELAY BOOT ===; load mmc 0 0x1000000 relay.bit; setenv bs ${filesize}; echo bitstream ${bs}; fpga loadb 0 0x1000000 ${bs}; load mmc 0 0x2000000 relay.elf; echo elf loaded; bootelf 0x2000000'", wait=2)
    send(sp, "printenv relayboot")
    print("\n  >> 现在执行 run relayboot ...")
    sp.write("run relayboot\r\n")
    t0 = time.time()
    while time.time() - t0 < 25:
        d = sp.read()
        if d:
            sys.stdout.write(d.decode("utf-8", "replace"))
            sys.stdout.flush()
        else:
            time.sleep(0.05)
    sp.close()
    print("\n=== 结束 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
