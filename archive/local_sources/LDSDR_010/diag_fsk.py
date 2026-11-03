import base64
import sys

sys.path.insert(0, r"E:\LDSDR_010")
from rk_console import RKConsole

PY = r'''import numpy as np, os, sys
sys.path.insert(0, "/tmp/ttc")
import iio

URI = "usb:"
FS = 2_500_000
F0, F1 = 150_000, 400_000
T_BIT = 0.004
spb = int(T_BIT * FS)

ctx = iio.Context(URI)
tx = ctx.find_device("cf-ad9361-dds-core-lpc")
rx = ctx.find_device("cf-ad9361-lpc")

# 造一段只有前导 10101010... 的波形，交替最明显
nb = 64
bits = [0, 1] * (nb // 2)
t = np.arange(spb) / FS
segs = [np.exp(1j*2*np.pi*(F0 if b == 0 else F1)*t) for b in bits]
bb = np.concatenate(segs)
I = np.clip(np.real(bb)*8000, -32768, 32767).astype(np.int16)
Q = np.clip(np.imag(bb)*8000, -32768, 32767).astype(np.int16)
w = np.empty(2*len(I), dtype=np.int16); w[0::2] = I; w[1::2] = Q

for ch in tx.channels:
    if ch.output:
        ch.enabled = True
txbuf = iio.Buffer(tx, len(bits)*spb, True)
txbuf.write(bytearray(w.tobytes()))
txbuf.push()
print("DIAG: TX 循环启动（64 bit 交替 0101）")

for nm, en in (("voltage0", True), ("voltage1", True),
               ("voltage2", False), ("voltage3", False)):
    c = rx.find_channel(nm)
    if c:
        c.enabled = en

n = spb * 40
rb = iio.Buffer(rx, n, False)
rb.refill()
d = rb.read()
try:
    txbuf.cancel()
except Exception:
    pass
print("DIAG: TX 停止，收到 %d 字节" % len(d))

raw = np.frombuffer(d, dtype=np.int16)
a = raw[0::2].astype(np.float64)
b = raw[1::2].astype(np.float64)
print("DIAG: ch0.std=%.1f  ch1.std=%.1f" % (a.std(), b.std()))

# 短时频率估计：用滑动相位的过零率不稳，改用分段 Goertzel
def zc(x):
    """过零率估频（对单音有效）"""
    x = x - x.mean()
    return np.sum(np.diff(np.sign(x)) != 0) / 2.0 / (len(x)/FS)

print("DIAG: 每 bit 的过零频率估计（前 24 bit），期望在 150000/400000 之间跳")
outs = []
for k in range(24):
    s = a[k*spb:(k+1)*spb]
    if len(s) < spb: break
    z0 = zc(s)
    # 与两个参考频率的相关
    tt = np.arange(spb)/FS
    e0 = abs(np.dot(s, np.exp(-1j*2*np.pi*F0*tt)))
    e1 = abs(np.dot(s, np.exp(-1j*2*np.pi*F1*tt)))
    outs.append((k, z0, 0 if e0 >= e1 else 1, e0/(e1+1e-9)))
for k, z0, bit, r in outs:
    print("DIAG:   bit%2d  过零频率=%7.0f Hz  判=%d  能量比 %.2f" % (k, z0, bit, r))
seq = "".join(str(o[2]) for o in outs)
print("DIAG: 判决序列 = %s" % seq)
print("DIAG: 期望 0101... = %s" % ("01"*12))
```

with RKConsole("COM8") as rk:
    def R(c, w=2.0, t=200, timeout=None):
        return rk.run(c, wait=w, timeout=(timeout or t))

    b64 = base64.b64encode(PY.encode("utf-8")).decode("ascii")
    R("rm -f /tmp/dg.b64", w=0.4)
    for i in range(0, len(b64), 640):
        R("printf '%%s' '%s' >> /tmp/dg.b64" % b64[i:i + 640], w=0.3, timeout=40)
    R("base64 -d /tmp/dg.b64 > /tmp/dg.py && rm -f /tmp/dg.b64", w=0.8)

    print("=== 执行瞬时频率诊断 ===")
    print(R("kill -9 $(ps | grep -E '[t]tc_fsk|[i]io_' | awk '{print $1}') 2>/dev/null; sleep 1; "
            "cd /tmp/ttc && python3 /tmp/dg.py 2>&1", w=30.0, t=300))
