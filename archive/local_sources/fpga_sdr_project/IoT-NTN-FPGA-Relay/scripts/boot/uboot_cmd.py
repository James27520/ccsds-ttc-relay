#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
uboot_cmd.py -- 登录 Linux → reboot → 打断 U-Boot 自动启动 → 在 U-Boot 命令行执行命令

用法：
    python uboot_cmd.py COM5
    （命令写在下面的 CMDS 列表里）
"""

import sys
import time

sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from serial_port import SerialPort                       # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM5"

# 在 U-Boot 提示符下要执行的命令
CMDS = [
    "printenv uenvcmd",
    "printenv modeboot",
    "printenv bootcmd",
    "printenv preboot",
    "printenv sdboot",
    "printenv uenvboot",
    "printenv importbootenv",
    "printenv loadbootenv",
]

LOG = r"E:\LDSDR_010\uboot_log.txt"


def pump(sp, secs, echo=True, sink=None):
    t0 = time.time()
    while time.time() - t0 < secs:
        d = sp.read()
        if d:
            if sink is not None:
                sink.extend(d)
            if echo:
                sys.stdout.write(d.decode("utf-8", "replace"))
                sys.stdout.flush()
        else:
            time.sleep(0.05)


def main():
    sp = SerialPort(PORT, 115200)
    print("=== 打开 %s ===" % PORT)
    time.sleep(0.3)
    sp.read()

    # 1) 登录
    sp.write("\r\n")
    buf = bytearray()
    pump(sp, 6, echo=False, sink=buf)
    if b"login:" in bytes(buf):
        print("=== 登录 ===")
        sp.write("root\r\n"); time.sleep(1.2); sp.read()
        sp.write("analog\r\n"); time.sleep(2.5); sp.read()
    sp.write("stty -echo\r\n"); time.sleep(0.8); sp.read()

    # 2) reboot
    print("\n=== reboot ===")
    sp.write("reboot\r\n")

    # 3) 等 "Hit any key"，然后敲键打断
    acc = bytearray()
    t0 = time.time()
    hit = False
    while time.time() - t0 < 45:
        d = sp.read()
        if d:
            acc += d
        if not hit and (b"Hit any key" in acc or b"stop autoboot" in acc):
            print("\n>>> 检测到自动启动提示，发送按键打断 <<<\n")
            sp.write(" ")
            hit = True
        if hit and (b"> " in bytes(acc[-400:])):
            break
        time.sleep(0.05)

    tail = bytes(acc[-600:]).decode("utf-8", "replace")
    print(tail)
    if not hit:
        print("!! 没抓到 autoboot 提示，可能已经启动完成")
        sp.close()
        return 1

    time.sleep(1.0)
    sp.read()

    # 4) 逐条执行命令
    print("\n" + "=" * 70)
    print(" U-Boot 命令输出")
    print("=" * 70)
    logf = open(LOG, "wb")
    for c in CMDS:
        print("\n>>> %s" % c)
        sp.write(c + "\r\n")
        t0 = time.time()
        line = bytearray()
        while time.time() - t0 < 3.0:
            d = sp.read()
            if d:
                line += d
                t0 = time.time()
            else:
                time.sleep(0.05)
        txt = bytes(line).decode("utf-8", "replace")
        print(txt)
        logf.write(("### %s\n" % c).encode())
        logf.write(line)
    logf.close()
    print("\n已存 %s" % LOG)

    print("\n>>> 现在把板子交还给你（停在 U-Boot 提示符）")
    print("    想启动 Linux: 输入 boot")
    sp.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
