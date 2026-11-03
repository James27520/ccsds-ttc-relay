import sys
sys.path.insert(0, r"E:\LDSDR_010")
from rk_console import RKConsole

PY = r'''
import numpy as np, os
raw = np.fromfile('/tmp/probe.bin', dtype=np.int16)
print("文件 %d 字节 = %d 个 int16" % (os.path.getsize('/tmp/probe.bin'), len(raw)))
print("前 32 个 int16:")
print("  " + " ".join(str(v) for v in raw[:32]))
for name, sl in [("raw[0::2]", raw[0::2]), ("raw[1::2]", raw[1::2]),
                 ("raw[2::4]", raw[2::4]), ("raw[3::4]", raw[3::4])]:
    if len(sl):
        print("  %-11s n=%6d  std=%8.2f  min=%6d max=%6d  非零率=%.1f%%"
              % (name, len(sl), sl.astype(float).std(), sl.min(), sl.max(),
                 100.0*np.count_nonzero(sl)/len(sl)))
'''

with RKConsole("COM8") as rk:
    def R(c, w=2.0, t=120):
        return rk.run(c, wait=w, timeout=t)

    U = "-u usb:"

    print("=== 1. cf-ad9361-lpc 的通道详情（含 id / index / format）===")
    print(R("iio_attr %s -c cf-ad9361-lpc 2>&1" % U, w=3.0))

    print("\n=== 2. iio_info 里该设备的扫描元素 ===")
    print(R("iio_info %s 2>&1 | grep -A 40 'cf-ad9361-lpc' | head -45" % U, w=3.5))

    print("\n=== 3. 写诊断脚本 ===")
    print("  " + R("cat > /tmp/probe.py <<'PYEOF'\n" + PY + "PYEOF\nwc -l /tmp/probe.py", w=3.0))

    print("\n=== 4. 只请求 voltage0 voltage1（当前用法）===")
    print(R("rm -f /tmp/probe.bin; timeout 30 iio_readdev %s -s 64 -b 64 cf-ad9361-lpc "
            "voltage0 voltage1 > /tmp/probe.bin 2>/dev/null; "
            "python3 /tmp/probe.py 2>&1" % U, w=6.0, t=120))

    print("\n=== 5. 请求 4 个通道，看布局 ===")
    print(R("rm -f /tmp/probe.bin; timeout 30 iio_readdev %s -s 64 -b 64 cf-ad9361-lpc "
            "voltage0 voltage1 voltage2 voltage3 > /tmp/probe.bin 2>/dev/null; "
            "python3 /tmp/probe.py 2>&1" % U, w=6.0, t=120))

    print("\n=== 6. 只请求 voltage0 ===")
    print(R("rm -f /tmp/probe.bin; timeout 30 iio_readdev %s -s 64 -b 64 cf-ad9361-lpc "
            "voltage0 > /tmp/probe.bin 2>/dev/null; "
            "python3 /tmp/probe.py 2>&1" % U, w=6.0, t=120))
