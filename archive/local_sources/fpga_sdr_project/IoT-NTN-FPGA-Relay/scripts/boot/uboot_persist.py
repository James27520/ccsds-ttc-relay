#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
uboot_persist.py -- 用 U-Boot 自己的 fatwrite 把 relayboot/uenvcmd 写进 uEnv.txt

完全不需要读卡器：板子能读卡就能写卡。

流程：
  1. 等 Linux 起来 → 登录 → reboot → 打断 U-Boot
  2. 在 U-Boot 里设置 relayboot 与 uenvcmd，先测 test -n 能不能通过
  3. env export -t 把整个环境导出成文本
  4. fatwrite 写回 uEnv.txt
  5. reset，观察是否自动启动转发
"""

import sys
import time

sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from serial_port import SerialPort                       # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM5"
RES = r"E:\LDSDR_010\uboot_persist_result.txt"

# 注意：故意不含 ${filesize} / || / === ，避免 hush 递归展开干扰 test
RB = ("echo RELAY_START; "
      "load mmc 0 0x1000000 relay.bit; "
      "fpga loadb 0 0x1000000 2083846; "
      "load mmc 0 0x2000000 relay.elf; "
      "bootelf 0x2000000")


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


def cmd(sp, c, wait=2.0):
    sp.write(c + "\r\n")
    raw = rd(sp, wait).decode("utf-8", "replace")
    out = []
    for l in raw.splitlines():
        s = l.strip()
        if s and s != c and s != "Pluto>":
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

    W("=== 1. 等 Linux 并登录 ===")
    b = bytearray()
    t0 = time.time()
    sp.write("\r\n")
    while time.time() - t0 < 150:
        d = sp.read()
        if d:
            b += d
        if b"login:" in b or b"# " in b or b"$ " in b:
            break
        time.sleep(0.1)
    W("  提示符: %r" % bytes(b[-50:]))
    if b"login:" in b:
        sp.write("root\r\n"); time.sleep(1.5); rd(sp, 1)
        sp.write("analog\r\n"); time.sleep(3.0); rd(sp, 1)
    sp.write("stty -echo; echo SHELL_OK\r\n"); time.sleep(1.5)
    chk = rd(sp, 1)
    if b"SHELL_OK" not in chk:
        W("  !! 没进 shell（%r），中止" % chk[-60:])
        f.close(); sp.close(); return 1
    W("  已进 shell")

    W("\n=== 2. reboot 并打断 U-Boot ===")
    sp.write("reboot\r\n")
    acc = bytearray()
    t0 = time.time()
    hit = False
    while time.time() - t0 < 70:
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
        W("  !! 打断失败")
        f.close(); sp.close(); return 1
    time.sleep(0.6)
    rd(sp, 1)

    W("\n=== 3. 设置 relayboot 与 uenvcmd，并验证 test -n ===")
    cmd(sp, "setenv relayboot '%s'" % RB, 2.0)
    W("  relayboot 已设置")
    for name, val in (("2词 run relayboot", "run relayboot"),
                      ("1词 relayboot", "relayboot")):
        cmd(sp, "setenv uenvcmd '%s'" % val, 1.0)
        r = cmd(sp, "test -n $uenvcmd; echo TRC=$?", 1.5)
        W("  %-18s -> %s   (%s)" % (name, "通过" if "TRC=0" in r else "失败",
                                    r.replace("\n", "|")[:50]))
    W("  当前 uenvcmd = %s" % cmd(sp, "printenv uenvcmd", 1.5).replace("\n", " ")[:100])

    W("\n=== 4. 尝试 env export + fatwrite 写回 uEnv.txt ===")
    r = cmd(sp, "env export -t 0x3000000", 2.5)
    W("  env export -> %s" % r.replace("\n", " | ")[:120])
    r = cmd(sp, "printenv filesize", 1.5)
    W("  filesize -> %s" % r.replace("\n", " ")[:40])
    r = cmd(sp, "fatwrite mmc 0 0x3000000 uEnv.txt ${filesize}", 4.0)
    W("  fatwrite -> %s" % r.replace("\n", " | ")[:150])

    W("\n=== 5. 确认新文件 ===")
    r = cmd(sp, "fatls mmc 0", 3.0)
    W(r[:600])

    W("\n=== 6. reset 观察是否自动启动转发 ===")
    sp.write("reset\r\n")
    out = rd(sp, 40)
    txt = out.decode("utf-8", "replace")
    W(txt[-3000:])

    W("\n" + "=" * 66)
    if "RELAY_START" in txt:
        W(" ✅ uenvcmd 被自动执行了")
    elif "Running uenvcmd" in txt:
        W(" ⚠️ uenvcmd 执行了但内容失败")
    else:
        W(" ⚠️ uenvcmd 仍未自动执行（看上面日志）")
    if "relay enabled" in txt or "rxlo" in txt:
        W(" ✅ 转发应用自动启动成功 —— 大功告成")
    W("=" * 66)
    f.close()
    sp.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
