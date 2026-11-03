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


def clean(t):
    return [l.strip() for l in t.decode("utf-8", "replace").splitlines()
            if l.strip() and "rk3x-i2c" not in l and "timeout, ipd" not in l]


print("=== 1. 登录（用户名 elf / 密码 elf）===")
for attempt in range(3):
    for i in range(4):
        sp.write("\r\n")
        time.sleep(0.2)
    time.sleep(0.8)
    rd(1.0)
    sp.write("elf\r")
    time.sleep(1.5)
    sp.write("elf\r")
    time.sleep(3.0)
    out = rd(2.0)
    ls = clean(out)
    print("  第 %d 次尝试，非刷屏输出: %s" % (attempt + 1, ls[-3:] if ls else "(无)"))
    if any("$" in l or "#" in l or "Welcome" in l for l in ls):
        print("  ✅ 似乎登录成功")
        break
    if any("incorrect" in l.lower() for l in ls):
        print("  ✗ 密码不对")
        continue

print("\n=== 2. 压低日志级别（用 sudo）===")
sp.write("echo elf | sudo -S dmesg -n 1\r")
time.sleep(4.0)
rd(2.0)
print("  已尝试")

print("\n=== 3. 验证刷屏是否停止 ===")
t0 = time.time()
n = 0
while time.time() - t0 < 5:
    d = sp.read()
    if d:
        n += len(d)
    time.sleep(0.02)
print("  5 秒收到 %d 字节（之前是 1700）" % n)
quiet = n < 400
print("  %s" % ("✅ 刷屏停了" if quiet else "⚠️ 还在刷"))

if quiet:
    def C(c, w=1.5):
        sp.write(c + "\r\n")
        time.sleep(w)
        return clean(rd(1.3))

    print("\n=== 4. 收集诊断信息 ===")
    for c in ("uname -r", "uptime",
              "ls /sys/bus/i2c/devices/ | tr '\\n' ' '",
              "cat /sys/bus/i2c/devices/i2c-*/name 2>/dev/null | tr '\\n' ' '",
              "lsusb 2>&1 | head -10",
              "ls /sys/bus/usb/devices/ | tr '\\n' ' '"):
        r = C(c, 2.0)
        print("  $ %s" % c)
        for l in r[-6:]:
            print("      %s" % l[:110])
else:
    print("\n  刷屏太厉害，先解决这个再诊断")

sp.close()
print("\n完成")
