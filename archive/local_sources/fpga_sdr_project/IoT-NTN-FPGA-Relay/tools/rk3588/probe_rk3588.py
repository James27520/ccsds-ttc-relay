#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probe_rk3588.py -- 通过调试串口登录 RK3588 (ELF2)，探测环境

用法: python probe_rk3588.py [COM8] [密码]
"""

import sys
import time

sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from serial_port import SerialPort                       # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM8"
PASSWD = sys.argv[2] if len(sys.argv) > 2 else "elf"
OUT = r"E:\RK_Series_Develop\rk3588_env.txt"


def rd(sp, secs):
    t0 = time.time()
    o = bytearray()
    while time.time() - t0 < secs:
        d = sp.read()
        if d:
            o += d
        else:
            time.sleep(0.05)
    return bytes(o)


def main():
    f = open(OUT, "w", encoding="utf-8")

    def W(s):
        print(s)
        f.write(s + "\n")
        f.flush()

    sp = SerialPort(PORT, 115200)
    time.sleep(0.4)
    sp.read()

    W("=== 连接 %s @115200 ===" % PORT)
    sp.write("\r\n")
    buf = bytearray()
    t0 = time.time()
    state = "wait_prompt"
    while time.time() - t0 < 25:
        d = sp.read()
        if d:
            buf += d
        txt = buf.decode("utf-8", "replace")
        if state == "wait_prompt" and ("login:" in txt or "# " in txt or "$ " in txt):
            if "login:" in txt:
                state = "wait_user"
                sp.write("elf\r\n")
            else:
                state = "ready"
            buf = bytearray()
        elif state == "wait_user" and "Password:" in txt:
            state = "wait_pass"
            sp.write(PASSWD + "\r\n")
            buf = bytearray()
        elif state == "wait_pass" and ("$ " in txt or "# " in txt or "incorrect" in txt):
            state = "ready" if "incorrect" not in txt else "wait_prompt"
            buf = bytearray()
        if state == "ready":
            break
        time.sleep(0.05)

    W("  登录状态: %s" % state)
    if state != "ready":
        W("  !! 没登进去。最近输出:\n%s" % txt[-500:])
        W("\n  排查：")
        W("   1. putty 是不是还占着 %s？关掉它。" % PORT)
        W("   2. 板子开机了吗？")
        f.close(); sp.close(); return 1

    sp.write("stty -echo 2>/dev/null; export PS1='RK> '\r\n")
    time.sleep(1.0)
    rd(sp, 0.5)
    W("  已进入 shell\n")

    probes = [
        ("内核", "uname -a"),
        ("发行版", "cat /etc/os-release | head -3"),
        ("主机名", "hostname"),
        ("CPU", "nproc"),
        ("内存", "free -h | head -2"),
        ("磁盘", "df -h / | tail -1"),
        ("Python3", "python3 --version"),
        ("pip", "python3 -m pip --version 2>&1 | head -1"),
        ("numpy", "python3 -c 'import numpy;print(\"numpy\",numpy.__version__)' 2>&1 | tail -1"),
        ("scipy", "python3 -c 'import scipy;print(\"scipy\",scipy.__version__)' 2>&1 | tail -1"),
        ("matplotlib", "python3 -c 'import matplotlib;print(\"matplotlib\",matplotlib.__version__)' 2>&1 | tail -1"),
        ("pyfftw", "python3 -c 'import pyfftw;print(\"pyfftw ok\")' 2>&1 | tail -1"),
        ("串口设备", "ls -l /dev/ttyUSB* /dev/ttyACM* /dev/ttyS4 2>&1"),
        ("USB 设备", "lsusb"),
        ("当前用户组", "id"),
        ("GPU 节点", "ls -l /dev/mali* /dev/dri/* 2>&1"),
        ("GPU 驱动", "cat /sys/class/misc/mali0/device/gpuinfo 2>/dev/null || dmesg 2>/dev/null | grep -i mali | head -3"),
        ("OpenCL", "ls /usr/lib/aarch64-linux-gnu/libOpenCL* /usr/lib/libOpenCL* 2>&1 | head -3"),
        ("clinfo", "which clinfo 2>&1"),
        ("网络", "ip -br addr 2>&1 | head -5"),
        ("内核模块", "lsmod | head -12"),
        ("CPU 频率", "cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq 2>/dev/null"),
        ("温度", "cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null"),
    ]

    for name, cmd in probes:
        sp.write("echo '---%s---'\r\n" % name)
        time.sleep(0.15)
        sp.write(cmd + "\r\n")
        time.sleep(1.2 if "import" in cmd or "lsusb" in cmd else 0.7)
        out = rd(sp, 0.6).decode("utf-8", "replace")
        lines = []
        skip = False
        for l in out.splitlines():
            s = l.strip()
            if not s or s.startswith("echo") or s == cmd:
                continue
            if s.startswith("---") and s.endswith("---"):
                continue
            if s in ("RK>", "stty -echo 2>/dev/null; export PS1='RK> '"):
                continue
            lines.append(s)
        W("\n### %s\n$ %s\n%s" % (name, cmd, "\n".join(lines)))

    f.close()
    sp.close()
    W("\n结果已存: %s" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
