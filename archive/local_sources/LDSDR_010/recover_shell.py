import sys
import time

sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from serial_port import SerialPort

sp = SerialPort("COM8", 115200)
time.sleep(0.4)
sp.read()

print("=== 1. 发 Ctrl-C 若干次，打断续行 ===")
for i in range(6):
    sp.write("\x03")
    time.sleep(0.3)
sp.write("\x03" + "\x04")     # Ctrl-C + Ctrl-D
time.sleep(0.5)
sp.write("\r\n")
time.sleep(1.0)
t = sp.read().decode("ascii", "replace")
print("  输出: %r" % t[-200:])

print("\n=== 2. 检查是否回到正常提示符 ===")
sp.write("echo PROBE_OK_$((1+1))\r\n")
time.sleep(1.2)
t = sp.read().decode("ascii", "replace")
print("  %r" % t[-200:])
ok = "PROBE_OK_2" in t
print("  %s" % ("✅ shell 正常了" if ok else "⚠️ 还是不对，再发一次"))

if not ok:
    for i in range(10):
        sp.write("\x03")
        time.sleep(0.2)
    sp.write("\r\n"); time.sleep(1.0); sp.read()
    sp.write("echo PROBE2_$((2+3))\r\n"); time.sleep(1.2)
    t = sp.read().decode("ascii", "replace")
    print("  重试: %r" % t[-150:])
    ok = "PROBE2_5" in t

print("\n=== 3. 确认关键工具 ===")
if ok:
    for c in ("which python3 iio_readdev iio_attr",
              "python3 -c 'import serial;print(\"pyserial\")' 2>&1 | tail -1"):
        sp.write(c + "\r\n"); time.sleep(1.2)
        print("  $ %s" % c)
        print("    %s" % sp.read().decode("ascii", "replace").strip()[:200])
sp.close()
print("\n完成")
