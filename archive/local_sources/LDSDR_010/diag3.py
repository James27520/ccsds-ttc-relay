import base64
import sys

sys.path.insert(0, r"E:\LDSDR_010")
from rk_console import RKConsole

AN = r'''import numpy as np, os, sys
p = "/tmp/c.bin"
if not os.path.exists(p) or os.path.getsize(p) < 8192:
    print("AN: 无数据"); sys.exit(1)
r = np.fromfile(p, dtype=np.int16)
I = r[0::2].astype(float); Q = r[1::2].astype(float)
N = 4096
K = max(1, min(len(I) // N, 32))
w = np.hanning(N)
a = np.zeros(N)
for k in range(K):
    s = (I[k*N:(k+1)*N] + 1j*Q[k*N:(k+1)*N]) * w
    a += np.abs(np.fft.fftshift(np.fft.fft(s))) ** 2
p_ = 10*np.log10(a/K/(N*N) + 1e-20)
f = (np.arange(N) - N/2) * (2.5e6/N)
noise = np.median(p_)
i = int(p_.argmax())
print("AN: n=%d  I.std=%.1f  Q.std=%.1f  max=%d" % (len(I), I.std(), Q.std(), int(abs(r).max())))
print("AN: 峰 %+.2f kHz  %.1f dB   噪声底 %.1f dB   SNR %.1f dB"
      % (f[i]/1e3, p_[i], noise, p_[i]-noise))
# 正频半边最强（排除镜像）
half = p_[N//2:]
fh = f[N//2:]
j = int(half.argmax())
print("AN: 正频最强 %+.2f kHz  %.1f dB" % (fh[j]/1e3, half[j]))
'''

with RKConsole("COM8") as rk:
    def R(c, w=2.0, t=200, timeout=None):
        return rk.run(c, wait=w, timeout=(timeout or t))

    b64 = base64.b64encode(AN.encode("utf-8")).decode("ascii")
    R("rm -f /tmp/an.b64", w=0.4)
    for i in range(0, len(b64), 640):
        R("printf '%%s' '%s' >> /tmp/an.b64" % b64[i:i + 640], w=0.3, timeout=40)
    print("上传: " + R("base64 -d /tmp/an.b64 > /tmp/an.py && rm -f /tmp/an.b64 && wc -c < /tmp/an.py",
                       w=0.8).strip() + " 字节\n")

    print("=== 抓 131072 样点并分析 ===")
    print(R("rm -f /tmp/c.bin; timeout 40 iio_readdev -u usb: -s 131072 -b 65536 "
            "cf-ad9361-lpc voltage0 voltage1 > /tmp/c.bin 2>/dev/null; "
            "ls -l /tmp/c.bin | awk '{print $5}'; python3 /tmp/an.py 2>&1", w=12.0, t=200))
