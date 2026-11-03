#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
capture_boot.py -- 抓取板子的完整启动日志，看 U-Boot 支不支持串口烧写

用法：
    python capture_boot.py COM5 300 板子启动日志.txt

它会：
  1. 反复尝试打开串口（如果你还开着 relay_gui 或串口终端，会提示占用）
  2. 打开后一直抓，直到超时
  3. 把原始日志存文件，并打印关键行
"""

import sys
import time

sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from serial_port import SerialPort                    # noqa: E402


KEYS = ("U-Boot", "BootROM", "Xilinx First Stage", "Hit any key", "bootdelay",
        "Zynq>", "zynq-uboot>", "U-Boot>", "pluto login", "Welcome to",
        "Linux version", "mmc", "loady", "fatwrite", "part", "sf ", "ubi")


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM5"
    secs = float(sys.argv[2]) if len(sys.argv) > 2 else 300.0
    out = sys.argv[3] if len(sys.argv) > 3 else "boot_log.txt"

    print("=" * 70)
    print(" 抓取板子启动日志")
    print("=" * 70)
    print(" 串口   : %s @115200" % port)
    print(" 时长   : %.0f 秒" % secs)
    print()
    print(" >>> 请现在把板子断电再上电（或按复位键）<<<")
    print(" >>> 如果提示串口被占用，先关掉 relay_gui 和所有串口终端 <<<")
    print()

    t0 = time.time()
    sp = None
    WAIT_PORT = 900.0
    while time.time() - t0 < WAIT_PORT:
        try:
            sp = SerialPort(port, 115200)
            break
        except OSError as e:
            el = time.time() - t0
            print("  [%3.0fs] 等待 %s 出现 ... (%s)" % (el, port, e))
            time.sleep(3)
    if sp is None:
        print("  放弃：串口一直打不开")
        return 1

    print("  串口已打开，开始抓取 ...\n")
    buf = bytearray()
    t0 = time.time()
    last = 0
    try:
        while time.time() - t0 < secs:
            d = sp.read()
            if d:
                buf += d
                if time.time() - last > 1.0:
                    last = time.time()
                    sys.stdout.write(d.decode("utf-8", "replace"))
                    sys.stdout.flush()
    except KeyboardInterrupt:
        pass
    finally:
        sp.close()

    open(out, "wb").write(bytes(buf))
    print("\n" + "=" * 70)
    print(" 抓取结束：%d 字节，已存 %s" % (len(buf), out))
    print("=" * 70)

    txt = buf.decode("utf-8", "replace")
    print("\n关键行：")
    for kw in KEYS:
        hits = [l.strip() for l in txt.splitlines() if kw.lower() in l.lower()]
        if hits:
            print("  [%s] x%d" % (kw, len(hits)))
            for h in hits[:3]:
                print("      %s" % h[:110])

    print("\n能不能串口烧写？")
    has_uboot = ("U-Boot" in txt) or ("Hit any key" in txt)
    print("  找到 U-Boot        : %s" % ("是" if has_uboot else "否"))
    if has_uboot:
        print("  >> 可行。下一步用 U-Boot 的 loady + fatwrite 把 BOOT.bin 写进 SD 卡")
    elif "pluto login" in txt or "Linux version" in txt:
        print("  >> 直接进了 Linux。可以走 Linux 内部写卡，或找 U-Boot 中断时机")
    else:
        print("  >> 没看到启动日志。检查：串口是不是选对了？板子有没有真的重新上电？")
    return 0


if __name__ == "__main__":
    sys.exit(main())
