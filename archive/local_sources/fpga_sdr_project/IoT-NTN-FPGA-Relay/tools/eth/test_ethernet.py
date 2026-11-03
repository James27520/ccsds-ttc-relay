#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_ethernet.py -- 验证 LDSDR <-> RK3588 的网线通路

思路：让 LDSDR 启动**原厂 Linux**（它有完整的以太网驱动），
     然后两边配静态 IP，对 ping、测吞吐。

关键技巧：不改 SD 卡，只在 U-Boot 里把 relayboot 换成一句无害的 echo，
         这样 uenvboot 照跑但不会进转发应用的死循环，Linux 正常启动。
"""

import sys
import time

sys.path.insert(0, r"E:\LDSDR_010\rk3588")
sys.path.insert(0, r"E:\LDSDR_010")
from serial_port import SerialPort                        # noqa: E402

LDSDR = sys.argv[1] if len(sys.argv) > 1 else "COM5"
RK = sys.argv[2] if len(sys.argv) > 2 else "COM8"
IP_LDSDR = "192.168.10.1"
IP_RK = "192.168.10.2"
OUT = r"E:\LDSDR_010\ethernet_test.txt"


def rd(sp, secs):
    t0 = time.time()
    o = bytearray()
    while time.time() - t0 < secs:
        d = sp.read()
        if d:
            o += d
        else:
            time.sleep(0.03)
    return bytes(o)


def main():
    f = open(OUT, "w", encoding="utf-8")

    def W(s):
        print(s)
        f.write(s + "\n")
        f.flush()

    # ---------------- 1. 打断 U-Boot ----------------
    W("=== 1. 连 LDSDR 串口并打断 U-Boot ===")
    sp = SerialPort(LDSDR, 115200)
    time.sleep(0.4)
    sp.read()

    # 让板子自己重启一次：先进 Linux（用 SKIP 技巧）再 reboot 太慢，
    # 所以这里直接等用户/JTAG 复位——先试着看当前是不是已经在 U-Boot
    sp.write("\r\n")
    time.sleep(0.6)
    cur = rd(sp, 0.8).decode("ascii", "replace")
    W("  当前输出尾部: %r" % cur[-80:])

    in_uboot = ("Pluto>" in cur) or ("U-Boot" in cur)
    if not in_uboot:
        W("  不在 U-Boot。")
        W("  >>> 请现在按一下板子上的复位键（标 RST 的那个），或断电重上电 <<<")
        W("  脚本会持续敲键，最多等 240 秒。")
        t0 = time.time()
        acc = bytearray()
        last = 0
        while time.time() - t0 < 240:
            sp.write(" ")          # 持续敲键，复位后必然打断
            d = sp.read()
            if d:
                acc += d
            if b"Pluto> " in bytes(acc) or b"Hit any key" in bytes(acc):
                break
            if time.time() - last > 15:
                last = time.time()
                W("      ...等待中（%.0f 秒）" % (time.time() - t0))
            time.sleep(0.08)
        if b"Pluto> " not in bytes(acc) and b"Hit any key" not in bytes(acc):
            W("  !! 240 秒内没进 U-Boot，中止。")
            W("  期间抓到的输出尾部: %r" % bytes(acc)[-300:])
            f.close(); sp.close(); return 1
        W("  ✅ 已进入 U-Boot")
        rd(sp, 0.8)

    rd(sp, 0.5)

    # ---------------- 2. 启动原厂 Linux ----------------
    W("\n=== 2. 手动 load + bootm 启动原厂 Linux ===")
    W("  （不用 run sdboot —— 它内部的 uenvboot 会重新导入 uEnv.txt，")
    W("    把我们对 relayboot 的修改覆盖掉，转发器又会起来）")
    rd(sp, 0.5)

    cmds = [
        ("load mmc 0 0x2080000 uImage",            "uImage"),
        ("load mmc 0 0x2000000 devicetree.dtb",    "devicetree.dtb"),
        ("load mmc 0 0x4000000 uramdisk.image.gz", "uramdisk.image.gz"),
    ]
    for c, what in cmds:
        sp.write(c + "\r\n")
        t0 = time.time()
        buf = bytearray()
        while time.time() - t0 < 25:
            d = sp.read()
            if d:
                buf += d
            if b"Pluto> " in bytes(buf) or b"bytes read" in bytes(buf):
                break
            time.sleep(0.05)
        txt = bytes(buf).decode("ascii", "replace")
        got = [l.strip() for l in txt.splitlines() if "bytes read" in l]
        W("    %-38s -> %s" % (what, got[0] if got else txt.strip()[-70:]))

    W("  发送 bootm 0x2080000 0x4000000 0x2000000 ...")
    sp.write("bootm 0x2080000 0x4000000 0x2000000\r\n")

    acc = bytearray()
    t0 = time.time()
    while time.time() - t0 < 150:
        d = sp.read()
        if d:
            acc += d
        txt = acc.decode("ascii", "replace")
        if "login:" in txt:
            break
        time.sleep(0.05)
    tail = acc.decode("ascii", "replace")
    for l in tail.splitlines():
        s = l.strip()
        if any(k in s for k in ("eth0", "RTL8211", "Link is", "macb", "login:",
                                "Starting kernel", "Uncompressing", "IPv6",
                                "random: crng", "Freeing")):
            W("    " + s[:110])
    if "login:" not in tail:
        W("  !! 没到登录提示，尾部输出:")
        W(tail[-1500:])
        f.close(); sp.close(); return 1
    W("  ✅ Linux 已启动")

    # ---------------- 3. 登录并配 IP ----------------
    W("\n=== 3. 登录 LDSDR Linux 并配置网口 ===")
    sp.write("root\r\n"); time.sleep(1.5); rd(sp, 0.8)
    sp.write("analog\r\n"); time.sleep(3.0); rd(sp, 1)
    sp.write("stty -echo 2>/dev/null; export PS1='LD> '\r\n"); time.sleep(1.0); rd(sp, 0.6)

    def ldsdr(cmd, wait=1.5):
        sp.write(cmd + "\r\n")
        time.sleep(wait)
        t = rd(sp, 0.6).decode("ascii", "replace")
        out = []
        for l in t.splitlines():
            s = l.replace("LD>", "").strip()
            if s and s != cmd:
                out.append(s)
        return "\n".join(out)

    W("  接口列表:")
    W("    " + ldsdr("ip -br link").replace("\n", "\n    "))
    W("  PHY 信息:")
    W("    " + ldsdr("ethtool eth0 2>/dev/null | head -20", 2.0).replace("\n", "\n    "))
    W("  配置 IP %s:" % IP_LDSDR)
    W("    " + ldsdr("ip addr add %s/24 dev eth0 2>&1; ip link set eth0 up; "
                     "ip addr show eth0 | head -5" % IP_LDSDR, 2.5).replace("\n", "\n    "))

    f.close()
    sp.close()
    W("\nLDSDR 侧完成。结果存 %s" % OUT)
    W("下一步：配 3588 的 IP 并 ping")
    return 0


if __name__ == "__main__":
    sys.exit(main())
