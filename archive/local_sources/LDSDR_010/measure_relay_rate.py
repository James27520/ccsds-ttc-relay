import sys
import time

sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from serial_port import SerialPort

sp = SerialPort("COM5", 115200)
time.sleep(0.8)
sp.read()


def status():
    """返回 (收到该行的时刻, 解析出的 dict)"""
    sp.read()
    sp.write("status\r\n")
    time.sleep(1.2)
    t = sp.read().decode("utf-8", "replace").replace("\r", "")
    now = time.time()
    for l in t.splitlines():
        if l.startswith("STAT"):
            d = {}
            for tok in l.split():
                if "=" in tok:
                    k, v = tok.split("=", 1)
                    d[k] = v
            return now, d
    return now, {}


print("=== 精确测量样点速率 ===")
print("等待 12 秒，精确读两次...")
t1, d1 = status()
time.sleep(12.0)
t2, d2 = status()

dt = t2 - t1
try:
    din = (int(d2["in"]) - int(d1["in"])) & 0xFFFFFFFF
    dout = (int(d2["out"]) - int(d1["out"])) & 0xFFFFFFFF
    dclip = (int(d2["clip"]) - int(d1["clip"])) & 0xFFFFFFFF
    print("  时间间隔 = %.3f 秒" % dt)
    print("  in  增长 = %d" % din)
    print("  out 增长 = %d" % dout)
    print("  clip 增长 = %d" % dclip)
    print()
    print("  实测样点率 = %.3f MSPS" % (din / dt / 1e6))
    print("  配置采样率 = %s Hz = %.3f MSPS" % (d2.get("fs"), int(d2.get("fs", 0)) / 1e6))
    r = (din / dt) / int(d2.get("fs", 1))
    print("  比值       = %.4f   %s" % (r, "✅ 吻合" if abs(r - 1) < 0.02 else "⚠️ 不符"))
    print()
    print("  in - out   = %d   %s" % ((int(d2["in"]) - int(d2["out"])) & 0xFFFFFFFF,
                                     "(应为 0，或 4096 的整数倍=快照竞争)"))
except Exception as e:
    print("  解析失败: %s" % e)
    print("  d1=%s" % d1)
    print("  d2=%s" % d2)

sp.close()
