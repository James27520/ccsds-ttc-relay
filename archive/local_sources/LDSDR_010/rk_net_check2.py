import sys
sys.path.insert(0, r"E:\LDSDR_010")
from rk_console import RKConsole


def sq(s):
    """把字符串安全地放进单引号里，供 sh -c 使用"""
    return "'" + s.replace("'", "'\\''") + "'"


with RKConsole("COM8") as rk:
    def R(c, w=1.2, t=90):
        return rk.run(c, wait=w, timeout=t)

    def S(c, w=1.5, t=120):
        # sudo sh -c '...'  -> 让重定向也以 root 执行
        return rk.run("echo elf | sudo -S sh -c %s 2>&1" % sq(c), wait=w, timeout=t)

    print("=== 1. 3588 有没有别的网络（WiFi / 第二网口）===")
    print(R("ls /sys/class/net/"))
    print(R("nmcli -t -f DEVICE,TYPE,STATE device 2>&1 | head -10"))
    print("  WiFi 硬件: " + R("ls /sys/class/ieee80211/ 2>&1; "
                              "lspci 2>/dev/null | grep -iE 'net|wireless' | head -3"))

    print("\n=== 2. 能不能上网 ===")
    print(R("ip route 2>&1"))
    print(R("timeout 5 ping -c 1 223.5.5.5 2>&1 | tail -2"))

    print("\n=== 3. PlutoSDR 那个 U 盘里有什么 ===")
    print(R("lsblk 2>&1 | head -10"))
    print(S("mkdir -p /tmp/msd && mount /dev/sda1 /tmp/msd 2>&1; ls -la /tmp/msd 2>&1 | head -20",
            w=2.5))

    print("\n=== 4. 3588 上有没有 libiio ===")
    print(R("which iio_info iio_attr iio_readdev 2>&1 || echo '(无)'"))
    print(R("ls /usr/lib/*/libiio* /usr/lib/libiio* 2>&1 | head -5"))
    print("  dpkg: " + R("dpkg -l 2>/dev/null | grep -i iio | head -5 || echo '(无)'"))
    print("  apt 缓存里的 deb: " + R("ls /var/cache/apt/archives/*.deb 2>/dev/null | head -5 "
                                     "|| echo '(空)'"))

    print("\n=== 5. 3588 上有没有编译器和 python ===")
    print(R("for c in gcc cc g++ make python3 pip3; do "
            "printf '%s=' $c; command -v $c || echo '-'; done"))
    print("  python3: " + R("python3 --version 2>&1"))

    print("\n=== 6. 挂载点清理 ===")
    print(S("umount /tmp/msd 2>/dev/null; echo ok", w=1.0))
