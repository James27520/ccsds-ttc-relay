import base64
import sys

sys.path.insert(0, r"E:\LDSDR_010")
from rk_console import RKConsole

AN = r'''import numpy as np, os, sys
r = np.fromfile("/tmp/c.bin", dtype=np.int16)
a = r[0::2].astype(float)     # 第 1 个通道
b = r[1::2].astype(float)     # 第 2 个通道
n = len(a); N = 4096
K = max(1, min(n // N, 32))
w = np.hanning(N)
f = (np.arange(N) - N/2) * (2.5e6/N)

def psd(x):
    acc = np.zeros(N)
    for k in range(K):
        s = x[k*N:(k+1)*N] * w
        acc += np.abs(np.fft.fftshift(np.fft.fft(s)))**2
    return 10*np.log10(acc/K/(N*N) + 1e-20)

print("A: std=%.2f  B: std=%.2f   corr(A,B)=%+.3f" % (a.std(), b.std(), np.corrcoef(a,b)[0,1]))
pA = psd(a); pB = psd(b); pC = psd(a + 1j*b)
for nm, p in (("A 单独(实数)", pA), ("B 单独(实数)", pB), ("A+jB (复数)", pC)):
    i = int(p.argmax())
    sym = np.abs(p - p[::-1]).mean()
    print("%-14s 峰%+9.2f kHz %6.1f dB  镜像不对称度 %.2f dB  %s"
          % (nm, f[i]/1e3, p[i], sym, "不对称=真复数" if sym > 3 else "对称=实数"))

# 正频半边单独看
half = slice(N//2, N)
for nm, p in (("A", pA), ("B", pB), ("A+jB", pC)):
    j = int(p[half].argmax())
    print("  %-5s 正频最强 %+9.2f kHz %.1f dB  (负频最强 %.1f dB)"
          % (nm, f[half][j]/1e3, p[half][j], p[:N//2].max()))

# 延迟相关：判断两个通道是不是同一信号的 I/Q
print("  A 与 B 的互相关峰: %+.3f" % (np.correlate(a-a.mean(), b-b.mean())[0]
                                     / (len(a)*a.std()*b.std())))
'''

with RKConsole("COM8") as rk:
    def R(c, w=2.0, t=200, timeout=None):
        return rk.run(c, wait=w, timeout=(timeout or t))

    # ★ 先杀残留，这是"后面没波形"的关键
    print("=== 清理残留进程（这是你'后面没波形'的原因）===")
    print("  " + R("kill -9 $(ps | grep -E '[t]tc_spectrum|[i]io_readdev|[i]io_writedev' "
                   "| awk '{print $1}') 2>/dev/null; sleep 1; "
                   "echo -n '剩余: '; ps | grep -cE '[t]tc_spectrum|[i]io_readdev'", w=3.0))

    b64 = base64.b64encode(AN.encode("utf-8")).decode("ascii")
    R("rm -f /tmp/an2.b64", w=0.4)
    for i in range(0, len(b64), 640):
        R("printf '%%s' '%s' >> /tmp/an2.b64" % b64[i:i + 640], w=0.3, timeout=40)
    print("\n上传分析脚本: " + R("base64 -d /tmp/an2.b64 > /tmp/an2.py && rm -f /tmp/an2.b64 "
                                 "&& wc -c < /tmp/an2.py", w=0.8).strip() + " 字节")

    print("\n=== 抓数据分析 ===")
    print(R("rm -f /tmp/c.bin; timeout 40 iio_readdev -u usb: -s 131072 -b 65536 "
            "cf-ad9361-lpc voltage0 voltage1 > /tmp/c.bin 2>/dev/null; python3 /tmp/an2.py 2>&1",
            w=12.0, t=200))
