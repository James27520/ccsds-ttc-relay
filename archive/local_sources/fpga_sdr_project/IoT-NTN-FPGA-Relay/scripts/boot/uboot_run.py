#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
uboot_run.py -- 板子已经停在 U-Boot 提示符时，逐条下发命令并抓输出

用法： python uboot_run.py COM5
"""

import sys
import time

sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from serial_port import SerialPort                       # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM5"

CMDS = [
    "echo --- STEP1 load bitstream ---",
    "load mmc 0 0x1000000 relay.bit",
    "echo --- STEP2 fpga loadb ---",
    "fpga loadb 0 0x1000000 2083846",
    "echo --- STEP3 load elf ---",
    "load mmc 0 0x2000000 relay.elf",
    "echo --- STEP4 bootelf ---",
    "bootelf 0x2000000",
]


def main():
    sp = SerialPort(PORT, 115200)
    time.sleep(0.3)
    sp.read()
    sp.write("\r\n")
    time.sleep(1.0)
    pre = sp.read()
    print("当前提示符:", pre[-120:])

    for c in CMDS:
        print("\n>>> %s" % c)
        sp.write(c + "\r\n")
        t0 = time.time()
        line = bytearray()
        while time.time() - t0 < 5.0:
            d = sp.read()
            if d:
                line += d
                t0 = time.time()
            else:
                time.sleep(0.05)
        print(bytes(line).decode("utf-8", "replace"))
    sp.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
