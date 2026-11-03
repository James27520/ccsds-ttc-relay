import sys, time
sys.path.insert(0, r"E:\LDSDR_010")
from rk_console import RKConsole

PW = "elf"

with RKConsole("COM8") as rk:
    def R(cmd, wait=0.8, timeout=40):
        return rk.run(cmd, wait=wait, timeout=timeout)

    def S(cmd, wait=1.2, timeout=90):
        return rk.run("echo %s | sudo -S %s 2>&1" % (PW, cmd), wait=wait, timeout=timeout)

    print("=== 谁在管 eth0 ===")
    print(R("nmcli -t -f DEVICE,STATE,CONNECTION dev 2>&1 | head -5"))
    print(R("systemctl is-active NetworkManager systemd-networkd 2>&1"))
    print(R("ip -br addr show eth0 2>&1"))

    print("\n=== 用 nmcli 配静态 IP（比裸 ip addr 抗重置）===")
    print(S("nmcli con mod 'Wired connection 1' ipv4.addresses 192.168.10.2/24 "
            "ipv4.method manual 2>&1"))
    print(S("nmcli con up 'Wired connection 1' 2>&1", wait=3.0, timeout=90))
    time.sleep(2)
    print(R("ip -br addr show eth0 2>&1"))

    print("\n=== 立刻双向 ping ===")
    print("3588 -> LDSDR:")
    print(R("ping -c 3 -W 2 192.168.10.1 2>&1", wait=1.5, timeout=60))
