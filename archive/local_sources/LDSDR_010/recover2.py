import sys
import time

sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from serial_port import SerialPort

sp = SerialPort("COM8", 115200)
time.sleep(0.4)
sp.read()


def rd(secs=1.0):
    t0 = time.time(); o = bytearray()
    while time.time() - t0 < secs:
        d = sp.read()
        if d: o += d
        else: time.sleep(0.03)
    return bytes(o)


def wr(s):
    sp.write(s)


print("=== 1. 打断一切（Ctrl-C x10 + Ctrl-D）===")
for i in range(10):
    wr("\x03"); time.sleep(0.2)
wr("\x04")
time.sleep(1.0)
wr("\r\n"); time.sleep(1.0)
t = rd(1.5).decode("ascii", "replace")
print("  %r" % t[-150:])

print("\n=== 2. 探测 shell ===")
ok = False
for i in range(5):
    wr("echo P$((3+4))\r\n"); time.sleep(1.2)
    t = rd(1.2).decode("ascii", "replace")
    if "P7" in t:
        ok = True
        print("  ✅ shell 正常（第 %d 次）" % (i + 1))
        break
    print("  第 %d 次: %r" % (i + 1, t[-80:]))
    for j in range(5):
        wr("\x03"); time.sleep(0.2)
    wr("\r\n"); time.sleep(0.6)

if not ok:
    print("\n  ⚠️ shell 救不回来。可能需要重启 3588（拔插它的电源）")
    sp.close(); sys.exit(1)

print("\n=== 3. 残留进程 ===")
wr("ps | grep -E '[i]io_|[t]tc_spec' | head -10\r\n"); time.sleep(2.0)
print("  %s" % rd(1.5).decode("ascii", "replace").strip()[:300])

print("\n=== 4. 全部杀掉 ===")
wr("kill -9 $(ps | grep -E '[t]tc_spectrum|[i]io_readdev|[i]io_writedev' | awk '{print $1}') "
   "2>/dev/null; sleep 1; ps | grep -cE '[t]tc_spectrum|[i]io_readdev'\r\n")
time.sleep(3.0)
print("  剩余: %s" % rd(1.5).decode("ascii", "replace").strip()[-100:])

print("\n=== 5. DDS / 增益状态 ===")
for n, c in (("DDS freq", "iio_attr -u usb: -c cf-ad9361-dds-core-lpc altvoltage0 frequency"),
             ("DDS scale", "iio_attr -u usb: -c cf-ad9361-dds-core-lpc altvoltage0 scale"),
             ("TX 衰减", "iio_attr -u usb: -o -c ad9361-phy voltage1 hardwaregain"),
             ("RX 增益", "iio_attr -u usb: -i -c ad9361-phy voltage0 hardwaregain"),
             ("RX 模式", "iio_attr -u usb: -i -c ad9361-phy voltage0 gain_control_mode"),
             ("TX_LO", "iio_attr -u usb: -c ad9361-phy altvoltage1 frequency"),
             ("RX_LO", "iio_attr -u usb: -c ad9361-phy altvoltage0 frequency")):
    wr(c + " 2>&1 | tail -1\r\n"); time.sleep(1.6)
    v = rd(1.0).decode("ascii", "replace").strip()
    print("  %-10s %s" % (n, v.splitlines()[-1] if v.splitlines() else "?"))

sp.close()
print("\n完成")
