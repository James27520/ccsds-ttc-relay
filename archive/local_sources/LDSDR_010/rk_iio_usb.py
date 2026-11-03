import sys
sys.path.insert(0, r"E:\LDSDR_010")
from rk_console import RKConsole


def sq(s):
    return "'" + s.replace("'", "'\\''") + "'"


with RKConsole("COM8") as rk:
    def R(c, w=1.5, t=120):
        return rk.run(c, wait=w, timeout=t)

    def S(c, w=2.0, t=180):
        return rk.run("echo elf | sudo -S sh -c %s 2>&1" % sq(c), wait=w, timeout=t)

    print("=== 1. libiio 支持哪些后端 ===")
    print(R("iio_info --version 2>&1 | head -5"))

    print("\n=== 2. 扫描 USB 后端（关键测试）===")
    print(R("iio_info -u usb: 2>&1 | head -25", w=4.0, t=120))

    print("\n=== 3. 列出 USB 扫描结果 ===")
    print(R("lsusb -d 0456:b673 2>&1"))

    print("\n=== 4. 逐个试 URI ===")
    for uri in ("usb:", "usb:1.4", "usb:1.3.5", "usb:1.3.4"):
        out = R("timeout 8 iio_info -u %s 2>&1 | head -6" % uri, w=3.0, t=60)
        ok = "IIO context" in out or "hw_model" in out
        print("  %-14s %s" % (uri, ("✅ 成功" if ok else "❌ ") + out.replace("\n", " | ")[:90]))

    print("\n=== 5. USB 权限（libusb 需要）===")
    print(R("ls -l /dev/bus/usb/001/ 2>&1 | tail -6"))
    print("  udev 规则: " + R("ls /etc/udev/rules.d/ 2>&1 | head -10"))
    print("  用户组: " + R("id"))

    print("\n=== 6. 如果有权限问题，试试 sudo 跑 ===")
    print(S("timeout 10 iio_info -u usb: 2>&1 | head -12", w=5.0, t=120))
