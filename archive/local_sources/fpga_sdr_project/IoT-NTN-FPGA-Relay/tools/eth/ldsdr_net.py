import sys, time
sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from serial_port import SerialPort

LDSDR = SerialPort("COM5", 115200)


def sh(cmd, wait=1.5):
    LDSDR.write(cmd + "\r\n")
    time.sleep(wait)
    t = LDSDR.read().decode("ascii", "replace")
    return "\n".join(s.replace("LD>", "").strip()
                     for s in t.splitlines()
                     if s.replace("LD>", "").strip() and s.strip() != cmd)


time.sleep(0.4); LDSDR.read()
LDSDR.write("\r\n"); time.sleep(0.5)
LDSDR.write("stty -echo 2>/dev/null; export PS1='LD> '\r\n"); time.sleep(1.0)
LDSDR.read()

print("=== LDSDR 地址 ===")
print(sh("ip -br addr"))
print("\n=== LDSDR 路由表 ===")
print(sh("ip route"))
print("\n=== LDSDR 邻居表 ===")
print(sh("ip neigh"))
print("\n=== LDSDR ping 3588 ===")
print(sh("ping -c 3 -W 2 192.168.10.2", 4.0))
print("\n=== 清掉 192.168.3.10，只留 192.168.10.1 ===")
print(sh("ip addr del 192.168.3.10/24 dev eth0 2>&1", 1.5))
print(sh("ip -br addr show eth0"))
print(sh("ip route"))
print("\n=== 再 ping ===")
print(sh("ping -c 3 -W 2 192.168.10.2", 4.0))
print("\n=== 邻居表 ===")
print(sh("ip neigh"))
LDSDR.close()
