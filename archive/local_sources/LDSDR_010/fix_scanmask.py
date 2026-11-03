#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_scanmask.py -- 通过 3588 的 /dev/ttyACM0 登录遥测板，使能 I/Q 扫描通道
（用 base64 传脚本，避免 heredoc 被串口控制台搅乱）
"""
import base64
import sys
import time

sys.path.insert(0, r"E:\LDSDR_010")
from rk_console import RKConsole

PY = r'''import os, time, sys
DEV = "/dev/ttyACM0"
D3 = "/sys/bus/iio/devices/iio:device3/scan_elements"
fd = os.open(DEV, os.O_RDWR | os.O_NOCTTY)
os.set_blocking(fd, False)

def rd(secs=1.0):
    t0 = time.time(); out = b""
    while time.time() - t0 < secs:
        try:
            d = os.read(fd, 4096)
            if d:
                out += d
            else:
                time.sleep(0.05)
        except BlockingIOError:
            time.sleep(0.05)
        except Exception:
            break
    return out

def wr(s):
    os.write(fd, s.encode())

def cmd(c, wait=1.2):
    wr(c + "\r\n"); time.sleep(wait)
    t = rd(0.8).decode("utf-8", "replace")
    return " | ".join(x.replace("TT>", "").strip() for x in t.splitlines()
                      if x.replace("TT>", "").strip() and x.strip() != c)

wr("\r\n"); time.sleep(1.5); b = rd(2.0)
print("初始: %r" % b[-100:])
if b"login:" in b:
    wr("root\r\n"); time.sleep(1.5); rd(1.5)
    wr("analog\r\n"); time.sleep(3.0); rd(2.0)
wr("stty -echo; export PS1='TT> '\r\n"); time.sleep(1.5); rd(1.0)
print("host: %s" % cmd("hostname", 1.5))
print("BEFORE: %s" % cmd("for f in %s/*_en; do echo -n \"$(basename $f)=$(cat $f) \"; done" % D3, 1.5))
cmd("for c in voltage0 voltage1 voltage2 voltage3; do echo 0 > %s/in_${c}_en; done" % D3, 1.5)
cmd("echo 1 > %s/in_voltage0_en" % D3, 1.0)
cmd("echo 1 > %s/in_voltage1_en" % D3, 1.0)
print("AFTER : %s" % cmd("for f in %s/*_en; do echo -n \"$(basename $f)=$(cat $f) \"; done" % D3, 1.5))
os.close(fd)
print("DONE")
'''

CHK = r'''import numpy as np, os
p = "/tmp/chk.bin"
if not os.path.exists(p) or os.path.getsize(p) < 256:
    print("CHK: 没有数据")
else:
    r = np.fromfile(p, dtype=np.int16)
    I = r[0::2].astype(float); Q = r[1::2].astype(float)
    print("CHK: int16=%d  前12个=%s" % (len(r), r[:12].tolist()))
    print("CHK: I.std=%.2f  Q.std=%.2f  %s"
          % (I.std(), Q.std(), "★ I/Q 正常了" if Q.std() > 1 else "✗ Q 还是 0"))
'''

with RKConsole("COM8") as rk:
    def R(c, w=2.0, t=240, timeout=None):
        return rk.run(c, wait=w, timeout=(timeout or t))

    def put(name, text):
        b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
        R("rm -f /tmp/%s.b64" % name, w=0.4)
        CH = 640
        for i in range(0, len(b64), CH):
            R("printf '%%s' '%s' >> /tmp/%s.b64" % (b64[i:i + CH], name), w=0.3, timeout=40)
        return R("base64 -d /tmp/%s.b64 > /tmp/%s.py && rm -f /tmp/%s.b64 && wc -c < /tmp/%s.py"
                 % (name, name, name, name), w=0.8)

    print("=== 上传脚本 ===")
    print("  scanfix: " + R("echo ok", w=0.3).strip() + " -> " + put("scanfix", PY).strip() + " 字节")
    print("  chk    : " + put("chk", CHK).strip() + " 字节")

    print("\n=== 执行：登录遥测板并使能 I/Q 扫描通道 ===")
    print(R("python3 /tmp/scanfix.py 2>&1", w=25.0, t=300))

    print("\n=== 抓 64 样点验证 ===")
    print(R("rm -f /tmp/chk.bin; timeout 30 iio_readdev -u usb: -s 64 -b 64 cf-ad9361-lpc "
            "voltage0 voltage1 > /tmp/chk.bin 2>/dev/null; python3 /tmp/chk.py 2>&1",
            w=8.0, t=150))

    print("\n=== 抓 131072 样点验证 ===")
    print(R("rm -f /tmp/chk.bin; timeout 30 iio_readdev -u usb: -s 131072 -b 65536 "
            "cf-ad9361-lpc voltage0 voltage1 > /tmp/chk.bin 2>/dev/null; python3 /tmp/chk.py 2>&1",
            w=10.0, t=180))
