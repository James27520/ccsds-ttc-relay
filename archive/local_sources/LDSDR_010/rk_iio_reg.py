import sys
sys.path.insert(0, r"E:\LDSDR_010")
from rk_console import RKConsole


def sq(s):
    return "'" + s.replace("'", "'\\''") + "'"


with RKConsole("COM8") as rk:
    def R(c, w=2.0, t=120):
        return rk.run(c, wait=w, timeout=t)

    print("=== 1. iio_reg 能不能通过 USB 后端读写 AD9361 寄存器 ===")
    print("  " + R("which iio_reg"))
    print("  读 0x00 (PRODUCT_ID): " + R("iio_reg -u usb: ad9361-phy 0x00 2>&1 | tail -1"))
    print("  读 0x3F5 (BIST/loop): " + R("iio_reg -u usb: ad9361-phy 0x3F5 2>&1 | tail -1"))
    print("  读 0x3F4 (BIST ctrl) : " + R("iio_reg -u usb: ad9361-phy 0x3F4 2>&1 | tail -1"))
    print("  读 0x005 (chip ver)  : " + R("iio_reg -u usb: ad9361-phy 0x005 2>&1 | tail -1"))

    print("\n=== 2. iio_reg 用法 ===")
    print(R("iio_reg 2>&1 | head -12 ; iio_reg --help 2>&1 | head -8", w=2.5))

    print("\n=== 3. 关键寄存器当前值（BIST / 环回 / TX 衰减）===")
    for addr, name in [(0x3F4, "BIST_CTRL"), (0x3F5, "BIST_CONFIG/loopback"),
                       (0x3F6, "BIST_TONE_FREQ"), (0x3F7, "BIST_TONE_LEVEL"),
                       (0x074, "TX1 atten"), (0x075, "TX2 atten"),
                       (0x073, "TX atten update")]:
        v = R("iio_reg -u usb: ad9361-phy 0x%03X 2>&1 | tail -1" % addr, w=1.6)
        print("  0x%03X %-22s = %s" % (addr, name, v.strip()[:60]))

    print("\n=== 4. 试读 AD9361 的 loopback 相关寄存器 (0x3F5 bit0 = 'no rf loop') ===")
    print("  读 0x3F5 = " + R("iio_reg -u usb: ad9361-phy 0x3F5 2>&1|tail -1"))
    print("  写 0x3F5 = 0x00（打开 RF 环回）...")
    print("  " + R("iio_reg -u usb: ad9361-phy 0x3F5 0x00 2>&1 | tail -2", w=2.5))
    print("  回读 0x3F5 = " + R("iio_reg -u usb: ad9361-phy 0x3F5 2>&1|tail -1"))
    print("  ★ 写回 0x01 恢复（安全）...")
    print("  " + R("iio_reg -u usb: ad9361-phy 0x3F5 0x01 2>&1 | tail -2", w=2.5))
    print("  回读 0x3F5 = " + R("iio_reg -u usb: ad9361-phy 0x3F5 2>&1|tail -1"))
