import sys
import time

sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from serial_port import SerialPort

sp = SerialPort("COM8", 115200)
time.sleep(0.5)
sp.read()


def rd(secs=1.2):
    t0 = time.time()
    o = bytearray()
    while time.time() - t0 < secs:
        d = sp.read()
        if d:
            o += d
        else:
            time.sleep(0.03)
    return bytes(o)


def wr(s):
    sp.write(s)


print("=== 0. 3588 还活着吗（串口有没有反应）===")
for i in range(4):
    wr("\x03")
    time.sleep(0.2)
wr("\r\n")
time.sleep(0.8)
t = rd(1.5).decode("ascii", "replace")
print("  %r" % t[-160:])

wr("echo ALIVE_$((11+11))\r\n")
time.sleep(1.2)
t = rd(1.5).decode("ascii", "replace")
alive = "ALIVE_22" in t
print("  %s" % ("✅ 3588 正常运行（只是 USB 口没电）" if alive
                else "⚠️ 串口没响应，3588 可能也没起来"))
if not alive:
    sp.close()
    raise SystemExit(0)


def C(c, w=1.5):
    wr(c + "\r\n")
    time.sleep(w)
    return rd(1.2).decode("utf-8", "replace").strip()


print("\n=== 1. 内核有没有报过流/掉电 ===")
print(C("dmesg 2>/dev/null | grep -iE 'over-?current|overcurrent|vbus|usb.*power|"
        "shutdown.*port|port.*power' | tail -15", 2.5) or "  (没找到相关记录)")

print("\n=== 2. 所有 USB 控制器与端口 ===")
print(C("ls /sys/bus/usb/devices/ 2>/dev/null | tr '\\n' ' '", 1.5))
print(C("lsusb 2>&1", 1.5))

print("\n=== 3. 各 root hub 的供电/端口状态 ===")
print(C("for d in /sys/bus/usb/devices/usb*; do "
        "echo \"--- $d ---\"; cat $d/product 2>/dev/null; "
        "cat $d/power/control 2>/dev/null; done", 2.5))

print("\n=== 4. 端口供电开关（很多 RK3588 板有 USB VBUS 使能 GPIO）===")
print(C("ls /sys/class/gpio/ 2>/dev/null | tr '\\n' ' '", 1.5))
print(C("gpioinfo 2>/dev/null | grep -iE 'usb|vbus|pwr|power' | head -20 || echo '(无 gpioinfo)'", 2.5))

print("\n=== 5. regulator（供电域）状态 ===")
print(C("cat /sys/kernel/debug/regulator/regulator_summary 2>/dev/null | "
        "grep -iE 'usb|vbus|5v|host' | head -20 || echo '(需 root 或不存在)'", 2.5))
print(C("ls /sys/class/regulator/ 2>/dev/null | tr '\\n' ' '", 1.5))

print("\n=== 6. 两个 Type-C / USB 口分别是什么控制器 ===")
print(C("dmesg 2>/dev/null | grep -iE 'xhci|ehci|ohci|dwc3|fusb|typec|tcpm' | tail -20", 2.5))

print("\n=== 7. 有没有 USB 设备在线（插着东西的话）===")
print(C("cat /sys/bus/usb/devices/*/idVendor 2>/dev/null | tr '\\n' ' '", 1.5))

sp.close()
print("\n完成")
