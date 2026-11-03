import sys, time
sys.path.insert(0, r"E:\LDSDR_010")
sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from rk_console import RKConsole
from serial_port import SerialPort

PW = "elf"
LDSDR = SerialPort("COM5", 115200)


def sh(cmd, wait=1.5):
    LDSDR.write(cmd + "\r\n"); time.sleep(wait)
    t = LDSDR.read().decode("ascii", "replace")
    return "\n".join(s.replace("LD>", "").strip() for s in t.splitlines()
                     if s.replace("LD>", "").strip() and s.strip() != cmd)


time.sleep(0.4); LDSDR.read()
LDSDR.write("\r\n"); time.sleep(0.5)
LDSDR.write("stty -echo 2>/dev/null; export PS1='LD> '\r\n"); time.sleep(1.0); LDSDR.read()

with RKConsole("COM8") as rk:
    def R(cmd, wait=0.8, timeout=40):
        return rk.run(cmd, wait=wait, timeout=timeout)

    def S(cmd, wait=1.0, timeout=60):
        return rk.run("echo %s | sudo -S %s 2>&1" % (PW, cmd), wait=wait, timeout=timeout)

    print("=== 3588 侧 ARP 相关 sysctl ===")
    print(R("for k in arp_ignore arp_filter arp_announce rp_filter; do "
            "echo -n \"$k=\"; cat /proc/sys/net/ipv4/conf/eth0/$k; done"))
    print("\n=== 3588 侧 iptables/ufw ===")
    print(S("iptables -L -n 2>&1 | head -12"))
    print(R("systemctl is-active ufw 2>&1"))

    print("\n=== 清 LDSDR 的 ARP 缓存并复测 ===")
    print(sh("ip neigh flush dev eth0", 1.0))

    print("\n=== 3588 rx 计数（前）===")
    a = R("cat /sys/class/net/eth0/statistics/rx_packets")
    print("  rx_packets = %s" % a.strip())

    print("\n=== 让 LDSDR ping 3588 三次 ===")
    print(sh("ping -c 3 -W 2 192.168.10.2", 5.0))

    print("\n=== 3588 rx 计数（后）—— 增加说明 ARP 到了 3588 ===")
    b = R("cat /sys/class/net/eth0/statistics/rx_packets")
    print("  rx_packets = %s" % b.strip())
    try:
        print("  >>> 增量 = %d" % (int(b.strip()) - int(a.strip())))
    except Exception:
        pass

    print("\n=== 3588 的邻居表（看它怎么认 LDSDR）===")
    print(R("ip neigh show dev eth0"))

    print("\n=== 从 3588 ping LDSDR（反方向，应该通）===")
    print(R("ping -c 3 -W 2 192.168.10.1 2>&1", wait=1.2, timeout=40))

    print("\n=== 立刻再让 LDSDR ping 3588 ===")
    print(sh("ping -c 3 -W 2 192.168.10.2", 5.0))
    print(sh("ip neigh show dev eth0", 1.0))

LDSDR.close()
