import sys, time
sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from serial_port import SerialPort

PORT = "COM11"
OUT = r"E:\LDSDR_010\new_board_info.txt"


def rd(sp, secs):
    t0 = time.time(); o = bytearray()
    while time.time() - t0 < secs:
        d = sp.read()
        if d: o += d
        else: time.sleep(0.03)
    return bytes(o)


def main():
    f = open(OUT, "w", encoding="utf-8")

    def W(s):
        print(s); f.write(s + "\n"); f.flush()

    sp = SerialPort(PORT, 115200)
    time.sleep(0.4); sp.read()
    sp.write("\r\n")
    time.sleep(1.5)
    b = rd(sp, 1.5)
    W("=== %s 初始输出 ===" % PORT)
    W(b.decode("ascii", "replace")[-800:])

    txt = b.decode("ascii", "replace")
    if "login:" in txt:
        W("\n--- 尝试登录 root/analog ---")
        sp.write("root\r\n"); time.sleep(1.5); rd(sp, 0.8)
        sp.write("analog\r\n"); time.sleep(3.0); rd(sp, 1)
    sp.write("stty -echo 2>/dev/null; export PS1='NB> '\r\n")
    time.sleep(1.0); rd(sp, 0.6)

    def cmd(c, wait=1.2):
        sp.write(c + "\r\n"); time.sleep(wait)
        t = rd(sp, 0.6).decode("ascii", "replace")
        return "\n".join(s.replace("NB>", "").strip() for s in t.splitlines()
                         if s.replace("NB>", "").strip() and s.strip() != c)

    probes = [
        ("内核", "uname -a"),
        ("发行版", "cat /etc/os-release 2>/dev/null | head -3"),
        ("硬件型号", "cat /sys/firmware/devicetree/base/model 2>/dev/null; echo"),
        ("compatible", "cat /sys/firmware/devicetree/base/compatible 2>/dev/null | tr '\\0' ' '; echo"),
        ("CPU", "cat /proc/cpuinfo | grep -m1 Hardware; nproc"),
        ("内存", "free -h | head -2"),
        ("iio 设备", "ls /sys/bus/iio/devices/ 2>/dev/null"),
        ("AD936x 型号", "cat /sys/bus/iio/devices/iio:device0/name 2>/dev/null; "
                        "cat /sys/bus/iio/devices/iio:device0/dev 2>/dev/null"),
        ("收发频段", "cat /sys/bus/iio/devices/iio:device0/phy/... 2>/dev/null; "
                     "find /sys/bus/iio/devices/iio:device0 -name '*rf_bandwidth*' 2>/dev/null | head -2"),
        ("网口", "ip -br addr 2>/dev/null"),
        ("USB 配置", "ls /sys/class/udc/ 2>/dev/null; mount | grep -i gadget"),
        ("固件版本", "cat /etc/*release 2>/dev/null | head -2; "
                     "strings /opt/VERSIONS 2>/dev/null | head -5"),
        ("hwref", "cat /sys/kernel/debug/iio/iio:device0/* 2>/dev/null | head -3; "
                  "dmesg 2>/dev/null | grep -iE 'ad936|hwref|model' | head -6"),
        ("板子型号串", "dmesg 2>/dev/null | grep -i 'PlutoSDR Rev' | head -2; "
                       "cat /proc/device-tree/model 2>/dev/null; echo"),
    ]
    for name, c in probes:
        W("\n### %s\n$ %s\n%s" % (name, c, cmd(c)))
    f.close(); sp.close()
    W("\n存到 %s" % OUT)


if __name__ == "__main__":
    main()
