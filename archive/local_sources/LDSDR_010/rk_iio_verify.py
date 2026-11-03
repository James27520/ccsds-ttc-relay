import sys
sys.path.insert(0, r"E:\LDSDR_010")
from rk_console import RKConsole


def sq(s):
    return "'" + s.replace("'", "'\\''") + "'"


with RKConsole("COM8") as rk:
    def R(c, w=2.0, t=180):
        return rk.run(c, wait=w, timeout=t)

    print("=== 1. 3588 上的 Python 环境 ===")
    print(R("python3 -c \"import numpy;print('numpy',numpy.__version__)\" 2>&1 | tail -1", w=2.5))
    print(R("python3 -c \"import scipy;print('scipy',scipy.__version__)\" 2>&1 | tail -1", w=2.5))
    print("  iio python 绑定: " + R("python3 -c \"import iio;print('iio ok')\" 2>&1 | tail -1", w=2.5))

    print("\n=== 2. 通过 USB 后端读遥测板状态（控制通路）===")
    print(R("iio_attr -u usb: -c ad9361-phy altvoltage0 frequency 2>&1 | tail -1"))
    print(R("iio_attr -u usb: -c ad9361-phy voltage0 sampling_frequency 2>&1 | tail -1"))
    print(R("iio_attr -u usb: -c ad9361-phy voltage0 hardwaregain 2>&1 | tail -2"))
    print(R("iio_attr -u usb: -c ad9361-phy voltage0 rf_bandwidth 2>&1 | tail -1"))

    print("\n=== 3. 使能 RX 扫描通道（关掉多余的）===")
    print(R("for c in 0 1 2 3; do iio_attr -u usb: -c cf-ad9361-lpc voltage$c scan 0 2>&1; done; "
            "iio_attr -u usb: -c cf-ad9361-lpc voltage0 scan 1 2>&1; "
            "iio_attr -u usb: -c cf-ad9361-lpc voltage1 scan 1 2>&1; "
            "echo '--- 当前通道 ---'; iio_attr -u usb: -c cf-ad9361-lpc 2>&1 | tail -20", w=3.0))

    print("\n=== 4. ★ 通过 USB 抓 IQ（关键测试）===")
    print(R("rm -f /tmp/iq.bin; "
            "S=$(date +%s%N); "
            "timeout 60 iio_readdev -u usb: -s 262144 -b 262144 cf-ad9361-lpc voltage0 voltage1 "
            "> /tmp/iq.bin 2>/tmp/iq.err; RC=$?; "
            "E=$(date +%s%N); "
            "echo \"rc=$RC  耗时 $(( (E-S)/1000000 )) ms  文件 $(stat -c %s /tmp/iq.bin 2>/dev/null || echo 0) 字节\"; "
            "head -3 /tmp/iq.err", w=8.0, t=180))

    print("\n=== 5. 吞吐测试：一次抓 2M 样点（8 MB）===")
    print(R("S=$(date +%s%N); timeout 120 iio_readdev -u usb: -s 2097152 -b 1048576 "
            "cf-ad9361-lpc voltage0 voltage1 > /tmp/big.bin 2>/dev/null; E=$(date +%s%N); "
            "MS=$(( (E-S)/1000000 )); SZ=$(stat -c %s /tmp/big.bin); "
            "echo \"${MS} ms, ${SZ} 字节 = $(( SZ/1048576 )) MB -> $(( SZ/1000/(MS>0?MS:1) )) MB/s\"",
            w=15.0, t=240))

    print("\n=== 6. 在 3588 上直接分析 IQ（看 CMU200 信号还在不在）===")
    py = (
        "import numpy as np,sys\n"
        "raw=np.fromfile('/tmp/iq.bin',dtype=np.int16)\n"
        "n=len(raw)//2\n"
        "I=raw[0::2].astype(float); Q=raw[1::2].astype(float)\n"
        "print('样点',n,' I.std=%.2f Q.std=%.2f'%(I.std(),Q.std()))\n"
        "N=4096;K=min(n//N,32);w=np.hanning(N);a=np.zeros(N)\n"
        "for k in range(K):\n"
        "    s=(I[k*N:(k+1)*N]+1j*Q[k*N:(k+1)*N])*w\n"
        "    a+=np.abs(np.fft.fftshift(np.fft.fft(s)))**2\n"
        "p=10*np.log10(a/K/(N*N)+1e-20)\n"
        "fs=4000000.0;f=(np.arange(N)-N/2)*(fs/N)\n"
        "hi=(f>50e3)&(f<150e3)\n"
        "if hi.any():\n"
        "    print('+100kHz 附近 峰 %.1f dB @ %.1f kHz, 噪声底 %.1f dB, SNR %.1f dB'%(\n"
        "        p[hi].max(), f[hi][p[hi].argmax()]/1e3, np.median(p), p[hi].max()-np.median(p)))\n"
        "print('全带最大峰 %.1f kHz (%.1f dB)'%(f[p.argmax()]/1e3, p.max()))\n"
    )
    print(R("cat > /tmp/an.py <<'PYEOF'\n" + py + "PYEOF\npython3 /tmp/an.py 2>&1", w=6.0, t=180))
