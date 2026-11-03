import base64
import sys

sys.path.insert(0, r"E:\LDSDR_010")
from rk_console import RKConsole

AN = r'''import numpy as np, os
r = np.fromfile("/tmp/c.bin", dtype=np.int16)
ch = [r[i::4].astype(float) for i in range(4)]
n = len(ch[0]); N = 4096
K = max(1, min(n // N, 32))
w = np.hanning(N)
f = (np.arange(N) - N/2) * (2.5e6/N)

print("AN: 4 通道样点 n=%d" % n)
for i in range(4):
    print("AN:   ch%d std=%7.2f  min=%6d max=%6d" % (i, ch[i].std(), ch[i].min(), ch[i].max()))

print("AN: 相关系数矩阵")
for i in range(4):
    print("AN:   " + "  ".join("%+6.3f" % np.corrcoef(ch[i], ch[j])[0,1] for j in range(4)))

def psd(x):
    acc = np.zeros(N)
    for k in range(K):
        s = x[k*N:(k+1)*N] * w
        acc += np.abs(np.fft.fftshift(np.fft.fft(s)))**2
    return 10*np.log10(acc/K/(N*N) + 1e-20)

print("AN: 各候选 I/Q 对的复数谱（镜像不对称度 > 3 dB 才是真复数）")
pairs = [(0,1), (2,3), (0,2), (1,3), (0,3), (1,2)]
best = None
for (a, b) in pairs:
    p = psd(ch[a] + 1j*ch[b])
    sym = float(np.abs(p - p[::-1]).mean())
    i = int(p.argmax())
    tag = "★ 真复数" if sym > 3 else ""
    print("AN:    ch%d+jch%d  峰%+9.2f kHz %6.1f dB  不对称度 %5.2f dB  %s"
          % (a, b, f[i]/1e3, p[i], sym, tag))
    if best is None or sym > best[0]:
        best = (sym, a, b, p)

if best and best[0] > 3:
    sym, a, b, p = best
    print("AN: ★★ 最佳 I/Q 对 = ch%d + j ch%d（不对称度 %.1f dB）" % (a, b, sym))
    half = slice(N//2, N)
    j = int(p[half].argmax())
    print("AN:    正频最强 %+.2f kHz  %.1f dB   负频最强 %.1f dB"
          % (f[half][j]/1e3, p[half][j], p[:N//2].max()))
else:
    print("AN: ✗ 没有找到真复数对 —— 信号本身可能就是实的")
'''

with RKConsole("COM8") as rk:
    def R(c, w=2.0, t=200, timeout=None):
        return rk.run(c, wait=w, timeout=(timeout or t))

    b64 = base64.b64encode(AN.encode("utf-8")).decode("ascii")
    R("rm -f /tmp/an4.b64", w=0.4)
    for i in range(0, len(b64), 640):
        R("printf '%%s' '%s' >> /tmp/an4.b64" % b64[i:i + 640], w=0.3, timeout=40)
    R("base64 -d /tmp/an4.b64 > /tmp/an4.py && rm -f /tmp/an4.b64", w=0.8)

    print("=== 抓 4 通道 × 32768 样点并全面分析 ===")
    print(R("kill -9 $(ps | grep '[i]io_readdev' | awk '{print $1}') 2>/dev/null; sleep 0.5; "
            "rm -f /tmp/c.bin; timeout 40 iio_readdev -u usb: -s 32768 -b 32768 "
            "cf-ad9361-lpc voltage0 voltage1 voltage2 voltage3 > /tmp/c.bin 2>/dev/null; "
            "ls -l /tmp/c.bin | awk '{print $5}'; python3 /tmp/an4.py 2>&1", w=12.0, t=200))
