#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_scanmask3.py -- 更稳健的登录 + 使能扫描通道"""
import base64
import sys

sys.path.insert(0, r"E:\LDSDR_010")
from rk_console import RKConsole

PY = r'''import serial, time, sys

D3 = "/sys/bus/iio/devices/iio:device3/scan_elements"
s = serial.Serial("/dev/ttyACM0", 115200, timeout=0.3)
s.reset_input_buffer()

def rd(secs=0.6):
    t0 = time.time(); out = b""
    while time.time() - t0 < secs:
        d = s.read(8192)
        if d: out += d
    return out

def wr(t):
    s.write(t.encode()); s.flush()

def wait_for(pat, timeout=12):
    """等某个字符串出现，返回(是否命中, 累计输出)"""
    t0 = time.time(); acc = b""
    while time.time() - t0 < timeout:
        d = s.read(8192)
        if d:
            acc += d
            if pat in acc:
                return True, acc
        else:
            time.sleep(0.05)
    return False, acc

def login():
    for attempt in range(4):
        wr("\r\n"); time.sleep(0.8); rd(1.0)
        ok, acc = wait_for(b"login:", 5)
        if not ok:
            wr("\r\n"); time.sleep(0.6); rd(0.8)
            ok, acc = wait_for(b"login:", 5)
        if ok:
            s.reset_input_buffer()
            wr("root\r")
            ok2, acc2 = wait_for(b"Password:", 8)
            if not ok2:
                continue
            s.reset_input_buffer()
            wr("analog\r")
            time.sleep(2.5)
            out = rd(1.5)
            if b"login:" not in out or b"$" in out or b"#" in out or b"~" in out:
                if b"incorrect" not in out.lower():
                    return True, out
        time.sleep(1.0)
    return False, b""

ok, out = login()
print("SCAN: login=%s  尾部=%r" % (ok, out[-90:]))
if not ok:
    print("SCAN: 放弃")
    s.close(); sys.exit(1)

wr("stty -echo 2>/dev/null; export PS1='TT> '\r\n"); time.sleep(1.5); rd(1.0)

def cmd(c, wait=1.3):
    wr(c + "\r\n"); time.sleep(wait)
    t = rd(0.9).decode("utf-8", "replace")
    return " | ".join(x.replace("TT>", "").strip() for x in t.splitlines()
                      if x.replace("TT>", "").strip() and x.strip() != c)

print("SCAN: host=%s" % cmd("hostname", 1.5))
print("SCAN: BEFORE %s" % cmd(
    "for f in %s/*_en; do echo -n \"$(basename $f)=$(cat $f) \"; done" % D3, 1.6))
cmd("for c in voltage0 voltage1 voltage2 voltage3; do echo 0 > %s/in_${c}_en; done" % D3, 1.5)
cmd("echo 1 > %s/in_voltage0_en" % D3, 1.1)
cmd("echo 1 > %s/in_voltage1_en" % D3, 1.1)
print("SCAN: AFTER  %s" % cmd(
    "for f in %s/*_en; do echo -n \"$(basename $f)=$(cat $f) \"; done" % D3, 1.6))
s.close()
print("SCAN: DONE")
'''

with RKConsole("COM8") as rk:
    def R(c, w=2.0, t=300, timeout=None):
        return rk.run(c, wait=w, timeout=(timeout or t))

    # base64 上传
    b64 = base64.b64encode(PY.encode("utf-8")).decode("ascii")
    R("rm -f /tmp/sf.b64", w=0.4)
    CH = 640
    for i in range(0, len(b64), CH):
        R("printf '%%s' '%s' >> /tmp/sf.b64" % b64[i:i + CH], w=0.3, timeout=40)
    print("上传: " + R("base64 -d /tmp/sf.b64 > /tmp/sf.py && rm -f /tmp/sf.b64 && wc -c < /tmp/sf.py",
                       w=0.8).strip() + " 字节")

    print("\n=== 执行 ===")
    print(R("python3 /tmp/sf.py 2>&1", w=30.0, t=400))

    print("\n=== 验证 ===")
    print(R("rm -f /tmp/chk.bin; timeout 30 iio_readdev -u usb: -s 256 -b 256 cf-ad9361-lpc "
            "voltage0 voltage1 > /tmp/chk.bin 2>/dev/null; python3 /tmp/chk.py 2>&1", w=8.0, t=150))
