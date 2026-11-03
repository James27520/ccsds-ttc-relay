#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
setup_ttc_ssh.py -- 通过串口控制台(COM11)给遥测板装回 SSH 公钥

背景：板子的 authorized_keys 没了（可能被重新刷过），SSH 免密失效。
      串口控制台是唯一可靠的入口。
"""
import sys
import time

sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from serial_port import SerialPort

PORT = "COM11"
USER = "root"
PW = "analog"          # PlutoSDR 默认密码
KEYFILE = r"C:\Users\23638\.ssh\id_ed25519_dsh.pub"


def rd(sp, secs=1.0):
    t0 = time.time()
    o = bytearray()
    while time.time() - t0 < secs:
        d = sp.read()
        if d:
            o += d
        else:
            time.sleep(0.03)
    return bytes(o)


def main():
    pub = open(KEYFILE, "r", encoding="utf-8").read().strip()
    print("公钥: %s..." % pub[:60])

    sp = SerialPort(PORT, 115200)
    time.sleep(0.5)
    sp.read()

    def wr(s):
        sp.write(s)

    print("\n=== 1. 唤醒 / 登录 ===")
    for attempt in range(4):
        for _ in range(3):
            wr("\r\n")
            time.sleep(0.3)
        time.sleep(1.0)
        t = rd(sp, 1.5).decode("utf-8", "replace")
        print("  第 %d 次探测: %r" % (attempt + 1, t[-90:]))
        if "login:" in t:
            wr(USER + "\r")
            time.sleep(1.5)
            t2 = rd(sp, 1.5).decode("utf-8", "replace")
            if "Password:" in t2 or "password" in t2.lower():
                wr(PW + "\r")
                time.sleep(3.0)
                t3 = rd(sp, 1.5).decode("utf-8", "replace")
                if "incorrect" in t3.lower():
                    print("  ✗ 密码不对")
                    continue
                print("  ✅ 已登录")
                break
        # 可能已经在 shell 里
        wr("echo PROBE$((7+7))\r\n")
        time.sleep(1.2)
        if "PROBE14" in rd(sp, 1.2).decode("utf-8", "replace"):
            print("  ✅ shell 可用")
            break

    def cmd(c, wait=1.3):
        wr(c + "\r\n")
        time.sleep(wait)
        return rd(sp, 1.0).decode("utf-8", "replace")

    print("\n=== 2. 环境确认 ===")
    print("  " + cmd("uname -a", 1.5).strip()[:110])
    print("  python: " + (cmd("which python3 || echo NO_PYTHON", 1.2).strip().splitlines() or ["?"])[-1][:80])
    print("  iio 工具: " + cmd("ls /usr/bin/iio_* 2>/dev/null | tr '\\n' ' '", 1.2).strip()[:110])

    print("\n=== 3. 装公钥 ===")
    cmd("mkdir -p /root/.ssh && chmod 700 /root/.ssh", 1.0)
    # 分两半写，避免串口行长限制
    half = len(pub) // 2
    cmd("printf '%%s' '%s' > /root/.ssh/authorized_keys" % pub[:half], 1.2)
    cmd("printf '%%s\\n' '%s' >> /root/.ssh/authorized_keys" % pub[half:], 1.2)
    cmd("chmod 600 /root/.ssh/authorized_keys", 1.0)
    print("  " + cmd("wc -c < /root/.ssh/authorized_keys; md5sum /root/.ssh/authorized_keys", 1.3).strip()[:120])

    print("\n=== 4. 确认 sshd 在跑 ===")
    print("  " + cmd("ps | grep -c '[s]shd'; netstat -tln 2>/dev/null | grep ':22 ' | head -2", 1.5).strip()[:120])

    sp.close()
    print("\n完成 —— 现在试 SSH")
    return 0


if __name__ == "__main__":
    sys.exit(main())
