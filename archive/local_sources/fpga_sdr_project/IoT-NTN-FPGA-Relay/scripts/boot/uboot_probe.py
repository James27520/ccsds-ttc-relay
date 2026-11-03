#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""uboot_probe.py -- 只做测试，结果写文件，然后尝试持久化 relayboot 到 uEnv.txt"""

import sys
import time

sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from serial_port import SerialPort                       # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM5"
RES = r"E:\LDSDR_010\uboot_probe_result.txt"

RB = ("echo === PL RELAY BOOT ===; load mmc 0 0x1000000 relay.bit; "
      "setenv bs ${filesize}; fpga loadb 0 0x1000000 ${bs}; "
      "load mmc 0 0x2000000 relay.elf; bootelf 0x2000000")

# 待测的 uenvcmd 写法
FORMS = [
    ("1word-relayboot",       "relayboot"),
    ("2words-runX",           "run relayboot"),
    ("1word-noexist",         "zzzz"),
    ("2words-echox",          "echo hi"),
    ("1word-semionly",        "echo;echo"),
    ("3words-echo",           "echo a b"),
]


def rd(sp, secs):
    t0 = time.time()
    o = bytearray()
    while time.time() - t0 < secs:
        d = sp.read()
        if d:
            o += d
        else:
            time.sleep(0.04)
    return bytes(o)


def cmdcap(sp, c, wait=2.0):
    """发命令并把回显+输出都抓下来（去掉提示符）"""
    sp.write(c + "\r\n")
    raw = rd(sp, wait).decode("utf-8", "replace")
    out = []
    for l in raw.splitlines():
        s = l.strip()
        if not s:
            continue
        if s == c or s == "Pluto>":
            continue
        out.append(s)
    return "\n".join(out)


def main():
    f = open(RES, "w", encoding="utf-8")

    def W(s):
        print(s)
        f.write(s + "\n")
        f.flush()

    sp = SerialPort(PORT, 115200)
    time.sleep(0.3)
    sp.read()

    W("=== 等 Linux 起来并登录（最多 120 秒）===")
    b = bytearray()
    t0 = time.time()
    sp.write("\r\n")
    while time.time() - t0 < 120:
        d = sp.read()
        if d:
            b += d
        if b"login:" in b or b"# " in b or b"$ " in b:
            break
        time.sleep(0.1)
    W("  提示符: %r" % bytes(b[-60:]))
    if b"login:" in b:
        sp.write("root\r\n"); time.sleep(1.5); rd(sp, 1)
        sp.write("analog\r\n"); time.sleep(3.0); rd(sp, 1)
    # 确认真的在 shell 里
    sp.write("stty -echo; echo SHELL_OK\r\n")
    time.sleep(1.5)
    chk = rd(sp, 1)
    W("  shell 检查: %r" % chk[-80:])
    if b"SHELL_OK" not in chk:
        W("  !! 没进 shell，中止")
        f.close(); sp.close(); return 1

    W("=== reboot ===")
    sp.write("reboot\r\n")
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
            W("  已打断")
        if hit and b"Pluto> " in bytes(acc):
            break
        time.sleep(0.04)
    if not hit:
        W("!! 打断失败")
        f.close()
        sp.close()
        return 1
    time.sleep(0.6)
    rd(sp, 1)

    W("\n=== 测试 B: 哪种 uenvcmd 能通过 test -n ===")
    for name, val in FORMS:
        cmdcap(sp, "setenv uenvcmd '%s'" % val, 1.0)
        r = cmdcap(sp, "test -n $uenvcmd; echo TRC=$?", 1.5)
        ok = "TRC=0" in r
        W("  %-18s val=%-18r -> %s   %s"
          % (name, val, "通过" if ok else "失败", r.replace("\n", " | ")[:60]))

    W("\n=== 测试 A: env import 是否覆盖已存在变量 ===")
    cmdcap(sp, "setenv bootcmd 'echo SENTINEL_A'", 1.0)
    cmdcap(sp, "env export -t 0x3000000", 2.0)
    cmdcap(sp, "setenv bootcmd 'echo SENTINEL_B'", 1.0)
    cmdcap(sp, "env import -t 0x3000000 ${filesize}", 2.0)
    r = cmdcap(sp, "printenv bootcmd", 1.5)
    W("  printenv bootcmd -> %s" % r.replace("\n", " | ")[:80])
    W("  => %s" % ("会覆盖 ✅" if "SENTINEL_A" in r else "不覆盖 ❌"))
    # 恢复
    cmdcap(sp, "setenv bootcmd 'run $modeboot'", 1.0)

    W("\n=== 测试 C: run_command 能否解析 relayboot 的内容 ===")
    cmdcap(sp, "setenv uenvcmd 'relayboot'", 1.0)
    r = cmdcap(sp, "run uenvcmd", 3.0)
    W("  run uenvcmd (值=relayboot) -> %s" % r.replace("\n", " | ")[:100])
    cmdcap(sp, "setenv uenvcmd 'run relayboot'", 1.0)
    r = cmdcap(sp, "run uenvcmd", 3.0)
    W("  run uenvcmd (值=run relayboot) -> %s" % r.replace("\n", " | ")[:100])

    W("\n=== 测试 D: 把 relayboot 写进 uEnv.txt 并持久化 ===")
    cmdcap(sp, "setenv relayboot '%s'" % RB, 2.0)
    W("  relayboot 已设置")
    r = cmdcap(sp, "printenv relayboot", 2.0)
    W("  printenv -> %s" % r.replace("\n", " ")[:150])

    f.close()
    sp.close()
    W("\n结果已存 %s" % RES)
    return 0


if __name__ == "__main__":
    sys.exit(main())
