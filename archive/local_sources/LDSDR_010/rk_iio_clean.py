import sys
sys.path.insert(0, r"E:\LDSDR_010")
from rk_console import RKConsole

# 分析脚本：接受 argv[1]=标签，argv[2]=fs
PY_AN = """import sys, numpy as np
tag = sys.argv[1] if len(sys.argv) > 1 else '?'
fs = float(sys.argv[2]) if len(sys.argv) > 2 else 4e6
raw = np.fromfile('/tmp/iq.bin', dtype=np.int16)
n = len(raw) // 2
I = raw[0::2].astype(float); Q = raw[1::2].astype(float)
N = 4096
K = max(1, min(n // N, 32))
w = np.hanning(N)
a = np.zeros(N)
for k in range(K):
    s = (I[k*N:(k+1)*N] + 1j*Q[k*N:(k+1)*N]) * w
    a += np.abs(np.fft.fftshift(np.fft.fft(s))) ** 2
p = 10*np.log10(a/K/(N*N) + 1e-20)
f = (np.arange(N) - N/2) * (fs / N)
noise = np.median(p)
pk = p.max(); pki = int(p.argmax())
hi = (f > 50e3) & (f < 150e3)
snr100 = p[hi].max() - noise if hi.any() else -99.0
f100 = f[hi][p[hi].argmax()]/1e3 if hi.any() else 0.0
print("  {:>4s}  std={:7.1f}  max={:5d}  fp100k={:+8.2f}kHz  SNR={:5.1f}dB  peak={:+9.2f}kHz  noise={:.1f}dB".format(
    tag, I.std(), int(abs(I).max()), f100, snr100, f[pki]/1e3, noise))
"""

with RKConsole("COM8") as rk:
    def R(c, w=2.5, t=240):
        return rk.run(c, wait=w, timeout=t)

    print("=== 写入分析脚本 ===")
    print("  " + R("cat > /tmp/an.py <<'PYEOF'\n" + PY_AN + "PYEOF\nwc -l /tmp/an.py", w=3.0))

    print("\n=== 增益扫描（RX_LO 900MHz, fs 4MSPS, CMU200@900.1MHz）===")
    for g in (0, 10, 20, 30, 40, 50, 60):
        R("iio_attr -u usb: -c ad9361-phy voltage0 hardwaregain %d >/dev/null 2>&1" % g, w=1.8)
        cap = ("rm -f /tmp/iq.bin; "
               "timeout 30 iio_readdev -u usb: -s 262144 -b 262144 cf-ad9361-lpc "
               "voltage0 voltage1 > /tmp/iq.bin 2>/dev/null; ")
        out = R(cap + "python3 /tmp/an.py %d 4000000 2>&1 | tail -1" % g, w=6.0, t=150)
        print(out.replace("\n", " ")[:120] if out.strip() else "  %d  (无输出)" % g)

    print("\n=== 找出最佳增益后做详细分析 ===")
    R("iio_attr -u usb: -c ad9361-phy voltage0 hardwaregain 40 >/dev/null 2>&1", w=2.0)
    print(R("rm -f /tmp/iq.bin; "
            "timeout 30 iio_readdev -u usb: -s 262144 -b 262144 cf-ad9361-lpc "
            "voltage0 voltage1 > /tmp/iq.bin 2>/dev/null; python3 /tmp/an.py g40 4000000",
            w=6.0, t=150))

    print("\n=== 吞吐测量：4M 样点（16 MB）===")
    print(R("rm -f /tmp/tp.bin; S=$(date +%s%N); "
            "timeout 300 iio_readdev -u usb: -s 4194304 -b 1048576 cf-ad9361-lpc "
            "voltage0 voltage1 > /tmp/tp.bin 2>/dev/null; E=$(date +%s%N); "
            "MS=$(( (E-S)/1000000 )); SZ=$(stat -c %s /tmp/tp.bin); "
            "echo \"$MS ms   $SZ bytes\"", w=30.0, t=500))
    print("  " + R("SZ=$(stat -c %s /tmp/tp.bin 2>/dev/null || echo 0); "
                   "echo \"解析: 若 1000ms -> $(( SZ/1000/1000 )) MB/s\"", w=2.0))
    R("rm -f /tmp/tp.bin", w=1.5)
