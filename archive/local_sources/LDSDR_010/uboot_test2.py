#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
uboot_test2.py -- 登录 Linux → reboot → 打断 U-Boot → 跑测试 → 启动转发

一次跑完，不依赖人工按键。
"""

import sys
import time

sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from serial_port import SerialPort                       # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM5"
LOG = r"E:\LDSDR_010\uboot_test2.log"


def rd(sp, secs, show=True, sink=None):
    t0 = time.time()
    out = bytearray()
    while time.time() - t0 < secs:
        d = sp.read()
        if d:
            out += d
            if sink is not None:
                sink.extend(d)
            if show:
                sys.stdout.write(d.decode("utf-8", "replace"))
                sys.stdout.flush()
        else:
            time.sleep(0.05)
    return bytes(out)


def cmd(sp, c, wait=3.0):
    print("\n>>> %s" % c)
    sp.write(c + "\r\n")
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
    for l in txt.splitlines():
        s = l.strip()
        if s and s != c and s != "Pluto>":
            print("    " + s[:130])
    return txt


def main():
    sp = SerialPort(PORT, 115200)
    time.sleep(0.3)
    sp.read()

    print("=== 1. 登录 Linux ===")
    sp.write("\r\n")
    b = rd(sp, 5, show=False)
    if b"login:" in b:
        sp.write("root\r\n"); time.sleep(1.2); sp.read()
        sp.write("analog\r\n"); time.sleep(3.0)
        print(rd(sp, 1, show=False)[-100:])
    sp.write("stty -echo\r\n"); time.sleep(0.8); sp.read()

    print("\n=== 2. reboot ===")
    sp.write("reboot\r\n")

    print("\n=== 3. 等 U-Boot 并打断 ===")
    acc = bytearray()
    t0 = time.time()
    hit = False
    while time.time() - t0 < 60:
        d = sp.read()
        if d:
            acc += d
        if not hit and b"Hit any key" in acc:
            sp.write(" ")
            hit = True
            print("  >>> 已打断 <<<")
        if hit and b"Pluto> " in bytes(acc):
            break
        time.sleep(0.04)
    if not hit:
        print("  !! 打断失败")
        sp.close()
        return 1
    time.sleep(0.6)
    sp.read()

    log = open(LOG, "w", encoding="utf-8")

    def L(s):
        print(s)
        log.write(s + "\n")

    print("\n" + "=" * 66)
    print(" 测试 A: env import 会不会覆盖已存在的变量")
    print("=" * 66)
    cmd(sp, "setenv CHKTEST original", 1.5)
    cmd(sp, "setenv bootcmd 'echo SENTINEL_A'", 1.5)
    cmd(sp, "env export -t 0x3000000", 2.0)
    cmd(sp, "setenv bootcmd 'echo SENTINEL_B'", 1.5)
    cmd(sp, "env import -t 0x3000000 ${filesize}", 2.0)
    r = cmd(sp, "printenv bootcmd", 2.0)
    overwrite = "SENTINEL_A" in r
    L("\n  => env import %s覆盖已存在变量" % ("" if overwrite else "不"))

    print("\n" + "=" * 66)
    print(" 测试 B: uenvcmd 必须展开成一个词才能通过 test -n")
    print("=" * 66)
    for name, val in (("单词 relayboot", "relayboot"),
                      ("两词 run relayboot", "run relayboot"),
                      ("无空格 echo;echo", "echo;echo")):
        cmd(sp, "setenv uenvcmd '%s'" % val, 1.0)
        r = cmd(sp, "test -n $uenvcmd; echo TRC=$?", 1.2)
        L("  %-20s -> %s" % (name, "通过" if "TRC=0" in r else "失败"))

    print("\n" + "=" * 66)
    print(" 测试 C: 恢复 bootcmd，定义 relayboot 并执行")
    print("=" * 66)
    cmd(sp, "setenv bootcmd 'run $modeboot'", 1.5)
    RB = ("echo === PL RELAY BOOT ===; "
          "load mmc 0 0x1000000 relay.bit; setenv bs ${filesize}; "
          "echo bitstream ${bs} bytes; "
          "fpga loadb 0 0x1000000 ${bs}; "
          "load mmc 0 0x2000000 relay.elf; echo elf ok; "
          "bootelf 0x2000000")
    cmd(sp, "setenv relayboot '%s'" % RB, 2.0)
    r = cmd(sp, "printenv relayboot", 2.0)

    print("\n>>> run relayboot  (观察 25 秒)")
    sp.write("run relayboot\r\n")
    out = rd(sp, 25, show=True)
    log.write("\n--- run relayboot 输出 ---\n" + out.decode("utf-8", "replace"))
    log.close()

    print("\n" + "=" * 66)
    if b"PL relay enabled" in out or b"rxlo" in out:
        print(" ✅ 转发应用启动成功")
    else:
        print(" ⚠️ 没看到应用横幅，见上面输出")
    print("=" * 66)
    sp.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
