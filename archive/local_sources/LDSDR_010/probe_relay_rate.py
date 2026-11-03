import sys
import time

sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from serial_port import SerialPort

sp = SerialPort("COM5", 115200)
time.sleep(0.8)
sp.read()


def tx(c, w=1.2):
    sp.read()
    sp.write(c + "\r\n")
    time.sleep(w)
    return sp.read().decode("utf-8", "replace").replace("\r", "")


def stat():
    r = tx("status", 1.2)
    for l in r.splitlines():
        if l.startswith("STAT"):
            d = {}
            for tok in l.split():
                if "=" in tok:
                    k, v = tok.split("=", 1)
                    d[k] = v
            return d
    return {}


def rate_of(secs=8.0):
    a = stat()
    t1 = time.time()
    time.sleep(secs)
    b = stat()
    t2 = time.time()
    try:
        din = (int(b["in"]) - int(a["in"])) & 0xFFFFFFFF
        return din / (t2 - t1), din, b
    except Exception:
        return 0.0, 0, b


print("=== 当前速率 ===")
r, n, d = rate_of(8.0)
print("  实测 %.3f MSPS   (fs 变量=%s)" % (r / 1e6, d.get("fs")))

print("\n=== 尝试设置 rate 30.72 后再测 ===")
print("  " + tx("rate 30.72", 2.0).strip()[:120].replace("\n", " | "))
r2, n2, d2 = rate_of(8.0)
print("  实测 %.3f MSPS   (fs 变量=%s)" % (r2 / 1e6, d2.get("fs")))

print("\n=== 尝试 rate 3.84 ===")
print("  " + tx("rate 3.84", 2.0).strip()[:120].replace("\n", " | "))
r3, n3, d3 = rate_of(8.0)
print("  实测 %.3f MSPS   (fs 变量=%s)" % (r3 / 1e6, d3.get("fs")))

print("\n=== 尝试 rate 61.44 ===")
print("  " + tx("rate 61.44", 2.0).strip()[:120].replace("\n", " | "))
r4, n4, d4 = rate_of(8.0)
print("  实测 %.3f MSPS   (fs 变量=%s)" % (r4 / 1e6, d4.get("fs")))

print("\n=== 结论 ===")
for lbl, rr in (("30.72", r2), ("3.84", r3), ("61.44", r4)):
    print("  设 %-6s -> 实测 %.3f MSPS" % (lbl, rr / 1e6))
print("\n  ★ 哪个设置真的改变了实测值，就说明 AD9361 接受了那个")

print("\n=== 恢复 30.72 ===")
print("  " + tx("rate 30.72", 2.0).strip()[:100].replace("\n", " | "))
sp.close()
