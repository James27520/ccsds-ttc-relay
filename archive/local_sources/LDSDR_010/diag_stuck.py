import sys
sys.path.insert(0, r"E:\LDSDR_010")
from rk_console import RKConsole

with RKConsole("COM8") as rk:
    def R(c, w=2.0, t=120):
        return rk.run(c, wait=w, timeout=t)

    U = "-u usb:"

    print("=== 1. 有没有残留进程在抢设备 ===")
    print(R("ps | grep -E '[i]io_|[t]tc_spec|[p]ython3' | head -15 || echo '(无)'", w=2.5))

    print("\n=== 2. 残留进程数量 ===")
    print("  ttc_spectrum: " + R("ps | grep -c '[t]tc_spectrum' || echo 0", w=1.5))
    print("  iio_readdev : " + R("ps | grep -c '[i]io_readdev' || echo 0", w=1.5))

    print("\n=== 3. DDS 单音还在不在 ===")
    print("  freq  = " + R("iio_attr %s -c cf-ad9361-dds-core-lpc altvoltage0 frequency 2>&1|tail -1" % U))
    print("  scale = " + R("iio_attr %s -c cf-ad9361-dds-core-lpc altvoltage0 scale 2>&1|tail -1" % U))
    print("  TX衰减 = " + R("iio_attr %s -o -c ad9361-phy voltage1 hardwaregain 2>&1|tail -1" % U))
    print("  RX增益 = " + R("iio_attr %s -i -c ad9361-phy voltage0 hardwaregain 2>&1|tail -1" % U))
    print("  RX模式 = " + R("iio_attr %s -i -c ad9361-phy voltage0 gain_control_mode 2>&1|tail -1" % U))

    print("\n=== 4. 清理所有残留 ===")
    print(R("kill -9 $(ps | grep -E '[t]tc_spectrum|[i]io_readdev|[i]io_writedev' "
            "| awk '{print $1}') 2>/dev/null; sleep 1; "
            "echo '剩余:'; ps | grep -cE '[t]tc_spectrum|[i]io_readdev' || echo 0", w=3.0))

    print("\n=== 5. 清理后再抓一次，看数据是否正常 ===")
    print(R("rm -f /tmp/c.bin; timeout 30 iio_readdev %s -s 256 -b 256 cf-ad9361-lpc "
            "voltage0 voltage1 > /tmp/c.bin 2>/dev/null; python3 -c \""
            "import numpy as np;r=np.fromfile('/tmp/c.bin',dtype=np.int16);"
            "I=r[0::2].astype(float);Q=r[1::2].astype(float);"
            "print('n=%d I.std=%.1f Q.std=%.1f max=%d'%(len(I),I.std(),Q.std(),abs(r).max()))\" 2>&1",
            w=8.0, t=150))

    print("\n=== 6. 抓大一点，算频谱看有没有 200kHz 的峰 ===")
    print(R("rm -f /tmp/c.bin; timeout 40 iio_readdev %s -s 131072 -b 65536 cf-ad9361-lpc "
            "voltage0 voltage1 > /tmp/c.bin 2>/dev/null; python3 -c \""
            "import numpy as np;"
            "r=np.fromfile('/tmp/c.bin',dtype=np.int16);"
            "I=r[0::2].astype(float);Q=r[1::2].astype(float);"
            "N=4096;K=len(I)//N;w=np.hanning(N);a=np.zeros(N);"
            "\nfor k in range(min(K,32)):\n"
            " s=(I[k*N:(k+1)*N]+1j*Q[k*N:(k+1)*N])*w\n"
            " a+=np.abs(np.fft.fftshift(np.fft.fft(s)))**2\n"
            "p=10*np.log10(a/min(K,32)/(N*N)+1e-20);"
            "f=(np.arange(N)-N/2)*(2.5e6/N);"
            "i=int(p.argmax());"
            "print('I.std=%.1f Q.std=%.1f'%(I.std(),Q.std()));"
            "print('峰 %+.2f kHz  %.1f dB  底 %.1f dB'%(f[i]/1e3,p[i],np.median(p)))\" 2>&1",
            w=12.0, t=180))
