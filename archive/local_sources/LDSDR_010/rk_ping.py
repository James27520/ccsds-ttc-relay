import sys
sys.path.insert(0, r"E:\LDSDR_010")
from rk_console import RKConsole

PW = "elf"

with RKConsole("COM8") as rk:
    def S(cmd, wait=1.0, timeout=60):
        return rk.run("echo %s | sudo -S %s 2>&1" % (PW, cmd), wait=wait, timeout=timeout)

    print("=== 配置 3588 eth0 = 192.168.10.2/24 ===")
    print(S("ip addr flush dev eth0"))
    print(S("ip addr add 192.168.10.2/24 dev eth0"))
    print(S("ip link set eth0 up"))
    print(rk.run("ip -br addr show eth0 2>&1", wait=0.6, timeout=30))

    print("\n=== ping LDSDR (192.168.10.1) ===")
    print(rk.run("ping -c 4 -W 2 192.168.10.1 2>&1", wait=1.5, timeout=60))

    print("\n=== ARP 表（能学到 MAC 就说明二层通了）===")
    print(rk.run("ip neigh show dev eth0 2>&1", wait=0.5, timeout=30))

    print("\n=== 网口统计 ===")
    print(rk.run("cat /sys/class/net/eth0/statistics/rx_packets "
                 "/sys/class/net/eth0/statistics/tx_packets 2>&1", wait=0.4, timeout=20))
