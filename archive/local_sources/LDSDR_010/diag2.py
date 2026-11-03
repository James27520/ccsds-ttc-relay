import sys
import time

sys.path.insert(0, r"E:\LDSDR_010")
from rk_console import RKConsole


def sq(s):
    return "'" + s.replace("'", "'\\''") + "'"


with RKConsole("COM8") as rk:
    def R(c, w=2.0, t=150):
        return rk.run(c, wait=w, timeout=t)

    print("=== 登录确认 ===")
    print("  " + R("hostname; whoami", w=1.5).replace("\n", " "))

    print("\n=== 1. 残留进程 ===")
    print(R("ps | grep -E '[i]io_|[t]tc_spec' | head -10", w=2.5) or "  (无残留)")

    print("\n=== 2. 全部杀掉 ===")
    print("  " + R("kill -9 $(ps | grep -E '[t]tc_spectrum|[i]io_readdev|[i]io_writedev' "
                   "| awk '{print $1}') 2>/dev/null; sleep 1; "
                   "echo -n '剩余: '; ps | grep -cE '[t]tc_spectrum|[i]io_readdev'", w=3.0))

    print("\n=== 3. 遥测板状态 ===")
    for n, c in (("DDS freq", "iio_attr -u usb: -c cf-ad9361-dds-core-lpc altvoltage0 frequency"),
                 ("DDS scale", "iio_attr -u usb: -c cf-ad9361-dds-core-lpc altvoltage0 scale"),
                 ("TX 衰减", "iio_attr -u usb: -o -c ad9361-phy voltage1 hardwaregain"),
                 ("RX 增益", "iio_attr -u usb: -i -c ad9361-phy voltage0 hardwaregain"),
                 ("RX 模式", "iio_attr -u usb: -i -c ad9361-phy voltage0 gain_control_mode"),
                 ("TX_LO", "iio_attr -u usb: -c ad9361-phy altvoltage1 frequency"),
                 ("RX_LO", "iio_attr -u usb: -c ad9361-phy altvoltage0 frequency"),
                 ("采样率", "iio_attr -u usb: -c ad9361-phy voltage0 sampling_frequency")):
        print("  %-10s %s" % (n, R(c + " 2>&1 | tail -1", w=1.6)))

    print("\n=== 4. 抓一次，看 I/Q 和频谱 ===")
    print(R("rm -f /tmp/c.bin; timeout 40 iio_readdev -u usb: -s 131072 -b 65536 "
            "cf-ad9361-lpc voltage0 voltage1 > /tmp/c.bin 2>/dev/null; "
            "python3 -c \"import numpy as np;"
            "r=np.fromfile('/tmp/c.bin',dtype=np.int16);"
            "I=r[0::2].astype(float);Q=r[1::2].astype(float);"
            "N=4096;K=len(I)//N;w=np.hanning(N);a=np.zeros(N);"
            "\\nfor k in range(min(K,32)):\\n"
            " s=(I[k*N:(k+1)*N]+1j*Q[k*N:(k+1)*N])*w\\n"
            " a+=np.abs(np.fft.fftshift(np.fft.fft(s)))**2\\n"
            "p=10*np.log10(a/min(K,32)/(N*N)+1e-20);"
            "f=(np.arange(N)-N/2)*(2.5e6/N);i=int(p.argmax());"
            "print('I.std=%.1f Q.std=%.1f max=%d'%(I.std(),Q.std(),abs(r).max()));"
            "print('峰 %+.2f kHz  %.1f dB  底 %.1f dB  SNR %.1f dB'"
            "%(f[i]/1e3,p[i],np.median(p),p[i]-np.median(p)))\" 2>&1", w=12.0, t=180))
