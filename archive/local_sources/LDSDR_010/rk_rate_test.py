import sys
sys.path.insert(0, r"E:\LDSDR_010")
from rk_console import RKConsole


def sq(s):
    return "'" + s.replace("'", "'\\''") + "'"


with RKConsole("COM8") as rk:
    def R(c, w=2.0, t=120):
        return rk.run(c, wait=w, timeout=t)

    print("=== 1. 实际能设到哪些采样率（驱动报的下限 2083333 未必能做到）===")
    for fs in (2083333, 1000000, 1250000, 1500000, 1920000, 2000000,
               2083334, 2400000, 2500000, 3072000, 3840000, 4000000):
        R("iio_attr -u usb: -c ad9361-phy voltage0 sampling_frequency %d >/dev/null 2>&1" % fs, w=1.6)
        got = R("iio_attr -u usb: -c ad9361-phy voltage0 sampling_frequency 2>&1 | tail -1", w=1.5)
        g = got.strip().split()[-1] if got.strip() else "?"
        ok = (g == str(fs))
        print("  设 %-8d -> 回读 %-9s %s" % (fs, g, "✅" if ok else "❌ 不接受"))

    print("\n=== 2. 收发同时跑，看 USB 带宽够不够（2.5 MSPS）===")
    R("iio_attr -u usb: -c ad9361-phy voltage0 sampling_frequency 2500000 >/dev/null 2>&1", w=1.6)
    print("  " + R("iio_attr -u usb: -c ad9361-phy voltage0 sampling_frequency 2>&1|tail -1"))

    print("  先测纯 RX 速率：")
    print("  " + R("rm -f /tmp/rx.bin; S=$(date +%s%N); "
                   "timeout 60 iio_readdev -u usb: -s 1048576 -b 262144 cf-ad9361-lpc "
                   "voltage0 voltage1 > /tmp/rx.bin 2>/dev/null; E=$(date +%s%N); "
                   "echo \"$(stat -c %s /tmp/rx.bin) 字节 / $(( (E-S)/1000000 )) ms\"; rm -f /tmp/rx.bin",
                   w=15.0, t=200))

    print("\n=== 3. TX 通道有哪些（用于发送）===")
    print(R("iio_attr -u usb: -c cf-ad9361-dds-core-lpc 2>&1 | head -20", w=2.5))

    print("\n=== 4. TX 衰减可控范围 ===")
    print("  " + R("iio_attr -u usb: -c ad9361-phy voltage1 hardwaregain 2>&1|tail -1"))
    for v in (-89.75, -60, -40, -20, -10, 0):
        R("iio_attr -u usb: -c ad9361-phy voltage1 hardwaregain %s >/dev/null 2>&1" % v, w=1.4)
        got = R("iio_attr -u usb: -c ad9361-phy voltage1 hardwaregain 2>&1|tail -1", w=1.4)
        print("  设 %-8s -> %s" % (v, got.strip().split()[-1] if got.strip() else "?"))
    R("iio_attr -u usb: -c ad9361-phy voltage1 hardwaregain -30 >/dev/null 2>&1", w=1.4)

    print("\n=== 5. 有没有内部环回（不用外部接线）===")
    print(R("ls /sys/kernel/debug/iio/ 2>&1"))
    print(R("iio_attr -u usb: -d ad9361-phy 2>&1 | grep -iE 'loop|bist|test' | head -5 || echo '(无)'"))
