#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
capture_reboot.py -- 登录板子 Linux，执行 reboot，从头抓完整的启动日志

这样不会像被动抓取那样错过 U-Boot 那一段。
"""

import sys
import time

sys.path.insert(0, r"E:\LDSDR_010\rk3588")
sys.path.insert(0, r"E:\LDSDR_010")
from serial_port import SerialPort                       # noqa: E402

OUT = r"E:\LDSDR_010\boot_full.txt"


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM5"
    cap = float(sys.argv[2]) if len(sys.argv) > 2 else 75.0

    sp = SerialPort(port, 115200)
    print("已打开 %s，准备登录并 reboot" % port)
    time.sleep(0.3)
    sp.read()

    # --- 等 login 提示 ---
    sp.write("\r\n")
    t0 = time.time()
    buf = b""
    while time.time() - t0 < 10:
        buf += sp.read()
        if b"login:" in buf or b"# " in buf or b"$ " in buf:
            break
        time.sleep(0.2)
    print("  当前状态:", buf[-80:])

    if b"login:" in buf:
        sp.write("root\r\n")
        time.sleep(1.0)
        sp.read()
        sp.write("analog\r\n")
        time.sleep(2.5)
        got = sp.read()
        print("  登录返回:", got[-120:])

    # --- 关回显，准备重启 ---
    sp.write("stty -echo\r\n")
    time.sleep(0.8)
    sp.read()

    print("\n" + "=" * 70)
    print(" 执行 reboot，开始从头抓取 %.0f 秒" % cap)
    print("=" * 70 + "\n")

    sp.write("reboot\r\n")

    t0 = time.time()
    data = bytearray()
    last = 0.0
    while time.time() - t0 < cap:
        d = sp.read()
        if d:
            data += d
            sys.stdout.write(d.decode("utf-8", "replace"))
            sys.stdout.flush()
            last = time.time()
    sp.close()

    open(OUT, "wb").write(bytes(data))
    txt = bytes(data).decode("utf-8", "replace")

    print("\n" + "=" * 70)
    print(" 抓取完成: %d 字节 -> %s" % (len(data), OUT))
    print("=" * 70)

    print("\n关键事件：")
    for kw in ("U-Boot", "Hit any key", "Loaded environment", "Running uenvcmd",
               "PL RELAY", "Loading bitstream", "Loading elf", "FPGA_LOADB_FAILED",
               "fpga", "bootelf", "Booting Linux", "Unknown command",
               "reading uImage", "bytes read"):
        hits = [l.strip() for l in txt.splitlines() if kw.lower() in l.lower()]
        if hits:
            print("  [%s] x%d" % (kw, len(hits)))
            for h in hits[:3]:
                print("      %s" % h[:110])

    print("\n结论：")
    if "PL RELAY" in txt or "relay enabled" in txt:
        print("  ✅ uenvcmd 执行了，而且我们的应用跑起来了")
    elif "Running uenvcmd" in txt:
        print("  ⚠️ uenvcmd 执行了但没成功 —— 看上面的错误行")
    elif "Loaded environment" in txt:
        print("  ⚠️ uEnv.txt 被导入了，但 uenvcmd 没被执行 —— 变量名或格式问题")
    else:
        print("  ⚠️ 似乎根本没读 uEnv.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
