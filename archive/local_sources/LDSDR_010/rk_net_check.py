import sys
sys.path.insert(0, r"E:\LDSDR_010")
from rk_console import RKConsole

NET = ("for d in /sys/class/net/*; do n=$(basename $d); "
       "echo \"$n state=$(cat $d/operstate 2>/dev/null) "
       "speed=$(cat $d/speed 2>/dev/null) carrier=$(cat $d/carrier 2>/dev/null)\"; done")

with RKConsole("COM8") as rk:
    print("=== 3588 网卡列表与状态 ===")
    print(rk.run(NET, wait=0.8, timeout=40))
    print("\n=== IP 地址 ===")
    print(rk.run("ip -br addr 2>&1", wait=0.6, timeout=30))
    print("\n=== 网卡驱动 ===")
    print(rk.run("ls /sys/class/net/", wait=0.4))
    print(rk.run("ethtool -i eth0 2>&1 | head -6", wait=0.6, timeout=30))
    print("\n=== 是否有抓包工具（raw socket 要用）===")
    print(rk.run("python3 -c \"import socket;print('AF_PACKET', hasattr(socket,'AF_PACKET'))\"", wait=0.6, timeout=30))
    print(rk.run("which tcpdump socat nc 2>&1", wait=0.5, timeout=30))
