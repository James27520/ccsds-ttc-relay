import sys
import time

sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from serial_port import SerialPort

sp = SerialPort("COM8", 115200)
time.sleep(0.3)
sp.read()

print("=== 连续监听 25 秒，看板子在做什么 ===")
buf = bytearray()
t0 = time.time()
last = 0
while time.time() - t0 < 25:
    d = sp.read()
    if d:
        buf += d
    if time.time() - last > 5:
        last = time.time()
        print("  [%4.1fs] 累计 %d 字节" % (time.time() - t0, len(buf)))
    time.sleep(0.02)

txt = bytes(buf).decode("utf-8", "replace")
lines = [l.rstrip() for l in txt.splitlines() if l.strip()]
print("\n=== 收到 %d 行，去重后 ===" % len(lines))

# 统计重复行
from collections import Counter
c = Counter(lines)
for line, n in c.most_common(20):
    print("  x%-4d %s" % (n, line[:120]))

sp.close()
