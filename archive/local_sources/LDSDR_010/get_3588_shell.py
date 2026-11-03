import sys
import time

sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from serial_port import SerialPort

sp = SerialPort("COM8", 115200)
time.sleep(0.3)
sp.read()


def rd(secs=1.5):
    t0 = time.time()
    o = bytearray()
    while time.time() - t0 < secs:
        d = sp.read()
        if d:
            o += d
        else:
            time.sleep(0.02)
    return bytes(o)


def wr(s):
    sp.write(s)


print("=== 1. 先压低内核日志级别，止住刷屏 ===")
for c in ["dmesg -n 1\r", "echo 1 > /proc/sys/kernel/printk\r"]:
    wr(c)
    time.sleep(1.0)
out = rd(2.0).decode("utf-8", "replace")
print("  输出尾部: %r" % out[-200:])

print("\n=== 2. 试拿 shell（发命令找标记）===")
ok = False
for i in range(5):
    wr("\x03")
    time.sleep(0.3)
    wr("echo MK$((5+5))MK\r\n")
    time.sleep(1.5)
    out = rd(1.5).decode("utf-8", "replace")
    if "MK10MK" in out:
        ok = True
        print("  ✅ shell 可用（第 %d 次）" % (i + 1))
        break
    tail = [l for l in out.splitlines() if l.strip()]
    print("  第 %d 次: %s" % (i + 1, (tail[-1][:90] if tail else "(空)")))

if ok:
    def C(c, w=1.5):
        wr(c + "\r\n")
        time.sleep(w)
        return rd(1.2).decode("utf-8", "replace")

    print("\n=== 3. 系统信息 ===")
    for c in ("uname -r", "uptime", "whoami"):
        o = C(c)
        ls = [l.strip() for l in o.splitlines() if l.strip() and not l.startswith("[")]
        print("  $ %-10s -> %s" % (c, ls[-1][:90] if ls else "?"))

    print("\n=== 4. 这条 I2C 上挂的是什么 ===")
    for c in ("ls /sys/bus/i2c/devices/ | tr '\\n' ' '",
              "cat /sys/bus/i2c/devices/i2c-*/name 2>/dev/null | tr '\\n' ' '",
              "cat /sys/bus/platform/devices/feaa0000.i2c/uevent 2>/dev/null",
              "ls /sys/bus/platform/devices/ | grep -i i2c | tr '\\n' ' '"):
        o = C(c, 2.0)
        ls = [l.strip() for l in o.splitlines() if l.strip() and not l.startswith("[")]
        print("  $ %s" % c)
        for l in ls[-4:]:
            print("      %s" % l[:110])

    print("\n=== 5. USB 控制器与供电 ===")
    for c in ("lsusb 2>&1 | head -12",
              "ls /sys/bus/usb/devices/ | tr '\\n' ' '",
              "cat /sys/kernel/debug/regulator/regulator_summary 2>/dev/null | "
              "grep -iE 'vbus|usb|5v' | head -12"):
        o = C(c, 2.0)
        ls = [l.strip() for l in o.splitlines() if l.strip() and not l.startswith("[")]
        print("  $ %s" % c)
        for l in ls[-8:]:
            print("      %s" % l[:110])

sp.close()
print("\n完成")
