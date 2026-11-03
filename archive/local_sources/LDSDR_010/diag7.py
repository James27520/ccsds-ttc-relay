import base64
import sys

sys.path.insert(0, r"E:\LDSDR_010")
from rk_console import RKConsole

AN = r'''import numpy as np, os, sys
r = np.fromfile(sys.argv[1], dtype=np.int16)
tag = sys.argv[2]
ch = [r[i::4].astype(float) for i in range(4)]
n = len(ch[0]); N = 4096
K = max(1, min(n // N, 16))
w = np.hanning(N)
f = (np.arange(N) - N/2) * (2.5e6/N)

def psd(x):
    acc = np.zeros(N)
    for k in range(K):
        acc += np.abs(np.fft.fftshift(np.fft.fft(x[k*N:(k+1)*N]*w)))**2
    return 10*np.log10(acc/K/(N*N) + 1e-20)

def peakdb(x):
    p = psd(x)
    i = int(p.argmax())
    return f[i]/1e3, p[i], np.median(p)

out = []
for i in range(4):
    k, pk, nb = peakdb(ch[i])
    out.append("ch%d std=%7.2f 峰%+8.2f kHz %6.1f dB 底%6.1f dB" % (i, ch[i].std(), k, pk, nb))
print("AN[%s]" % tag)
for o in out:
    print("AN[%s]   %s" % (tag, o))
# 存一份供对比
np.save("/tmp/ch_%s.npy" % tag, np.array([ch[i].std() for i in range(4)]))
'''

CMP = r'''import numpy as np
a = np.load("/tmp/ch_off.npy")
b = np.load("/tmp/ch_on.npy")
print("CMP: 通道 std 对比  (DDS关 -> DDS开)")
for i in range(4):
    r = b[i] / a[i] if a[i] > 0.01 else 0
    print("CMP:   ch%d  %8.2f -> %8.2f   倍数 %.2f  %s"
          % (i, a[i], b[i], r, "★ 有响应" if r > 1.5 else "(无变化)"))
'''

with RKConsole("COM8") as rk:
    def R(c, w=2.0, t=200, timeout=None):
        return rk.run(c, wait=w, timeout=(timeout or t))

    for nm, txt in (("an5", AN), ("cmp", CMP)):
        b64 = base64.b64encode(txt.encode("utf-8")).decode("ascii")
        R("rm -f /tmp/%s.b64" % nm, w=0.4)
        for i in range(0, len(b64), 640):
            R("printf '%%s' '%s' >> /tmp/%s.b64" % (b64[i:i + 640], nm), w=0.3, timeout=40)
        R("base64 -d /tmp/%s.b64 > /tmp/%s.py && rm -f /tmp/%s.b64" % (nm, nm, nm), w=0.8)
    print("脚本已上传\n")

    CAP = ("kill -9 $(ps | grep '[i]io_readdev' | awk '{print $1}') 2>/dev/null; sleep 0.4; "
           "rm -f %s; timeout 40 iio_readdev -u usb: -s 32768 -b 32768 "
           "cf-ad9361-lpc voltage0 voltage1 voltage2 voltage3 > %s 2>/dev/null; ")

    print("=== ① 关掉 DDS，抓一次 ===")
    R("iio_attr -u usb: -c cf-ad9361-dds-core-lpc altvoltage0 scale 0", w=2.0)
    R("iio_attr -u usb: -c cf-ad9361-dds-core-lpc altvoltage1 scale 0", w=2.0)
    print(R(CAP % ("/tmp/off.bin", "/tmp/off.bin") + "python3 /tmp/an5.py /tmp/off.bin off 2>&1",
            w=10.0, t=200))

    print("\n=== ② 打开 DDS，再抓一次 ===")
    R("iio_attr -u usb: -c cf-ad9361-dds-core-lpc altvoltage0 frequency 200000", w=1.6)
    R("iio_attr -u usb: -c cf-ad9361-dds-core-lpc altvoltage0 scale 0.5", w=1.6)
    R("iio_attr -u usb: -c cf-ad9361-dds-core-lpc altvoltage1 frequency 200000", w=1.6)
    R("iio_attr -u usb: -c cf-ad9361-dds-core-lpc altvoltage1 scale 0.5", w=1.6)
    print(R(CAP % ("/tmp/on.bin", "/tmp/on.bin") + "python3 /tmp/an5.py /tmp/on.bin on 2>&1",
            w=10.0, t=200))

    print("\n=== ③ 对比 ===")
    print(R("python3 /tmp/cmp.py 2>&1", w=4.0, t=120))
