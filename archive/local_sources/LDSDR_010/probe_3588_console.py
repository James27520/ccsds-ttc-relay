import sys
import time

sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from serial_port import SerialPort

sp = SerialPort("COM8", 115200)
time.sleep(0.3)
sp.read()

print("=== 1. 发一串回车+Ctrl-C，看有没有登录提示符 ===")
for i in range(6):
    sp.write("\r\n")
    time.sleep(0.25)
sp.write("\x03")
time.sleep(0.3)
for i in range(4):
    sp.write("\r\n")
    time.sleep(0.25)

t0 = time.time()
buf = bytearray()
while time.time() - t0 < 4:
    d = sp.read()
    if d:
        buf += d
    time.sleep(0.02)
txt = bytes(buf).decode("utf-8", "replace")
# 过滤掉刷屏行
keep = [l for l in txt.splitlines() if l.strip() and "rk3x-i2c" not in l]
print("  非刷屏内容 %d 行:" % len(keep))
for l in keep[-15:]:
    print("    %s" % l[:110])
if not keep:
    print("    (全是刷屏，输入没被回显)")

print("\n=== 2. 统计刷屏速率 ===")
n0 = 0
t0 = time.time()
while time.time() - t0 < 5:
    d = sp.read()
    if d:
        n0 += len(d)
    time.sleep(0.02)
print("  5 秒收到 %d 字节 = %.0f 字节/秒" % (n0, n0 / 5.0))
print("  推断：内核每 ~203ms 打一行，约 4.9 行/秒")

print("\n=== 3. 试 SSH 通路（如果 LDSDR 还接着网线）===")
import subprocess
r = subprocess.run("ping -n 2 192.168.10.2", shell=True, capture_output=True, timeout=30)
o = (r.stdout or b"").decode("gbk", "replace")
print("  ping 192.168.10.2:", [l for l in o.splitlines() if "TTL" in l or "丢失" in l or "loss" in l][:2])

sp.close()
print("\n完成")
