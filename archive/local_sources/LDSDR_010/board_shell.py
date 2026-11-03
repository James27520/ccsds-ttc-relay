#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
board_shell.py -- 通过串口跟板子的 Linux 交互（登录 + 执行命令）

用法：
    python board_shell.py COM5                    # 登录并跑一组诊断命令
    python board_shell.py COM5 "ls /mnt"          # 登录后跑指定命令
"""

import sys
import time

sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from serial_port import SerialPort                     # noqa: E402

PROMPTS = (b"# ", b"$ ", b"> ", b"login: ", b"Password: ")


class BoardShell(object):
    def __init__(self, port, baud=115200, echo=True):
        self.sp = SerialPort(port, baud)
        self.echo = echo
        self.buf = b""
        time.sleep(0.3)
        self.sp.read()

    def _pump(self, secs):
        t0 = time.time()
        while time.time() - t0 < secs:
            d = self.sp.read()
            if d:
                self.buf += d
                if self.echo:
                    sys.stdout.write(d.decode("utf-8", "replace"))
                    sys.stdout.flush()

    def wait_for(self, needles, timeout=20.0):
        if isinstance(needles, bytes):
            needles = (needles,)
        t0 = time.time()
        while time.time() - t0 < timeout:
            self._pump(0.3)
            for n in needles:
                if n in self.buf:
                    return n
        return None

    def clear(self):
        self.buf = b""

    def send(self, s):
        self.sp.write(s + "\r\n")

    def cmd(self, s, wait=2.5):
        """发一条命令并等一会儿，返回这段时间的输出。"""
        self.clear()
        self.send(s)
        self._pump(wait)
        return self.buf.decode("utf-8", "replace")

    def login(self, user="root", password="analog"):
        print("--- 登录尝试: %s / %s ---" % (user, password))
        self.clear()
        self.sp.write("\r\n")
        got = self.wait_for((b"login: ", b"# ", b"$ ", b"> "), timeout=8)
        if got in (b"# ", b"$ ", b"> "):
            print("   已经在 shell 里了")
            return True
        if got is None:
            print("   没看到 login 提示")
            return False
        self.clear()
        self.send(user)
        got = self.wait_for((b"Password: ", b"# ", b"$ ", b"> "), timeout=8)
        if got in (b"# ", b"$ ", b"> "):
            print("   不需要密码")
            return True
        if got is None:
            print("   没看到 Password 提示")
            return False
        self.clear()
        self.send(password)
        got = self.wait_for((b"# ", b"$ ", b"> ", b"Login incorrect"), timeout=10)
        if got in (b"# ", b"$ ", b"> "):
            print("   登录成功")
            return True
        print("   登录失败")
        return False

    def close(self):
        self.sp.close()


DIAG = [
    ("系统",        "uname -a; cat /etc/issue 2>/dev/null"),
    ("挂载点",      "mount | grep -E 'mmc|vfat|ext' "),
    ("磁盘",        "df -h"),
    ("目录",        "ls -la / /boot /mnt /media /run/media 2>&1 | head -60"),
    ("找 BOOT.bin", "ls -la /boot/BOOT.bin /mnt/BOOT.bin /media/BOOT.bin 2>&1"),
    ("网络",        "ip addr 2>/dev/null || ifconfig -a 2>/dev/null"),
    ("可用工具",    "for c in base64 wget curl rz sz ftpd nc tftp; do printf '%s=' $c; "
                    "command -v $c >/dev/null && echo yes || echo no; done"),
    ("SD 设备",     "ls -la /dev/mmcblk* /dev/disk/by-path 2>&1 | head -20"),
]


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM5"
    one = sys.argv[2] if len(sys.argv) > 2 else None

    sh = BoardShell(port)
    try:
        if not sh.login():
            print("\n登录失败。可以试试别的密码，或者手动在串口终端里登录后告诉我环境。")
            return 1

        if one:
            print("\n$ " + one)
            print(sh.cmd(one, wait=5.0))
            return 0

        for name, c in DIAG:
            print("\n" + "=" * 66)
            print(" [%s]  $ %s" % (name, c[:100]))
            print("=" * 66)
            print(sh.cmd(c, wait=2.5))
    finally:
        sh.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
