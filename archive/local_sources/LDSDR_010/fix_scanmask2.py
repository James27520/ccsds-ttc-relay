#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_scanmask2.py -- 用 3588 上的 pyserial 登录遥测板，使能 I/Q 扫描通道
"""
import base64
import sys

sys.path.insert(0, r"E:\LDSDR_010")
from rk_console import RKConsole

PY = r'''import serial, time, sys

D3 = "/sys/bus/iio/devices/iio:device3/scan_elements"

try:
    s = serial.Serial("/dev/ttyACM0", 115200, timeout=0.5)
except Exception as e:
    print("SCAN: 打开串口失败 %s" % e); sys.exit(1)

def rd(secs=1.0):
    t0 = time.time(); out = b""
    while time.time() - t0 < secs:
        d = s.read(4096)
        if d:
            out += d
    return out

def wr(t):
    s.write(t.encode())

s.reset_input_buffer()
wr("\r\n"); time.sleep(1.5); b = rd(2.0)
print("SCAN: 初始 %r" % b[-80:])
if b"login:" in b:
    wr("root\r\n"); time.sleep(1.5); rd(1.5)
    wr("analog\r\n"); time.sleep(3.0); rd(2.0)
wr("stty -echo; export PS1='TT> '\r\n"); time.sleep(1.5); rd(1.0)

def cmd(c, wait=1.2):
    wr(c + "\r\n"); time.sleep(wait)
    t = rd(0.8).decode("utf-8", "replace")
    return " | ".join(x.replace("TT>", "").strip() for x in t.splitlines()
                      if x.replace("TT>", "").strip() and x.strip() != c)

print("SCAN: host=%s" % cmd("hostname", 1.5))
print("SCAN: BEFORE %s" % cmd(
    "for f in %s/*_en; do echo -n \"$(basename $f)=$(cat $f) \"; done" % D3, 1.5))

cmd("for c in voltage0 voltage1 voltage2 voltage3; do echo 0 > %s/in_${c}_en; done" % D3, 1.5)
cmd("echo 1 > %s/in_voltage0_en" % D3, 1.0)
cmd("echo 1 > %s/in_voltage1_en" % D3, 1.0)

print("SCAN: AFTER  %s" % cmd(
    "for f in %s/*_en; do echo -n \"$(basename $f)=$(cat $f) \"; done" % D3, 1.5))
s.close()
print("SCAN: DONE")
'''

CHK = r'''import numpy as np, os
p = "/tmp/chk.bin"
if not os.path.exists(p) or os.path.getsize(p) < 256:
    print("CHK: 无数据")
else:
    r = np.fromfile(p, dtype=np.int16)
    I = r[0::2].astype(float); Q = r[1::2].astype(float)
    print("CHK: int16=%d 前12=%s" % (len(r), r[:12].tolist()))
    print("CHK: I.std=%.1f Q.std=%.1f  %s"
          % (I.std(), Q.std(), "★ I/Q 正常" if Q.std() > 1 else "✗ Q 仍为 0"))
'''

with RKConsole("COM8") as rk:
    def R(c, w=2.0, t=240, timeout=None):
        return rk.run(c, wait=w, timeout=(timeout or t))

    print("=== 恢复正常提示符 ===")
    print("  " + R("echo READY_$((1+1))", w=1.2).strip())

    print("\n=== 上传脚本（base64）===")
    for name, text in (("scanfix", PY), ("chk", CHK)):
        b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
        R("rm -f /tmp/%s.b64" % name, w=0.4)
        CH = 640
        for i in range(0, len(b64), CH):
            R("printf '%%s' '%s' >> /tmp/%s.b64" % (b64[i:i + CH], name), w=0.3, timeout=40)
        sz = R("base64 -d /tmp/%s.b64 > /tmp/%s.py && rm -f /tmp/%s.b64 && wc -c < /tmp/%s.py"
               % (name, name, name, name), w=0.8)
        print("  %-9s -> %s 字节" % (name, sz.strip()))

    print("\n=== 执行修复 ===")
    print(R("python3 /tmp/scanfix.py 2>&1", w=25.0, t=300))

    print("\n=== 验证抓取 ===")
    print(R("rm -f /tmp/chk.bin; timeout 30 iio_readdev -u usb: -s 256 -b 256 cf-ad9361-lpc "
            "voltage0 voltage1 > /tmp/chk.bin 2>/dev/null; python3 /tmp/chk.py 2>&1", w=8.0, t=150))
