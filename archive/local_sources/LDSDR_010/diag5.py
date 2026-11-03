import base64
import sys

sys.path.insert(0, r"E:\LDSDR_010")
from rk_console import RKConsole

AN = r'''import numpy as np, os, sys
r = np.fromfile("/tmp/c.bin", dtype=np.int16)
print("AN: 文件 %d 字节 = %d 个 int16" % (os.path.getsize("/tmp/c.bin"), len(r)))
print("AN: 前 20 个: %s" % r[:20].tolist())
# 按 N 通道解交织，看每个通道是否非零
import itertools
for nc in (1, 2, 4):
    if len(r) % nc:
        continue
    m = len(r) // nc
    cols = [r[i::nc] for i in range(nc)]
    info = " ".join("ch%d:std=%.1f" % (i, c.astype(float).std()) for i, c in enumerate(cols))
    print("AN: 按 %d 通道解 -> %s" % (nc, info))
    if nc == 2 and all(c.astype(float).std() > 0.5 for c in cols):
        cc = np.corrcoef(cols[0].astype(float), cols[1].astype(float))[0, 1]
        print("AN:   2 通道相关系数 = %+.3f  %s"
              % (cc, "★ 接近 0 = 真正的 I/Q" if abs(cc) < 0.3 else "✗ 还是相关"))
'''

with RKConsole("COM8") as rk:
    def R(c, w=2.0, t=200, timeout=None):
        return rk.run(c, wait=w, timeout=(timeout or t))

    # 上传分析脚本
    b64 = base64.b64encode(AN.encode("utf-8")).decode("ascii")
    R("rm -f /tmp/an3.b64", w=0.4)
    for i in range(0, len(b64), 640):
        R("printf '%%s' '%s' >> /tmp/an3.b64" % b64[i:i + 640], w=0.3, timeout=40)
    R("base64 -d /tmp/an3.b64 > /tmp/an3.py && rm -f /tmp/an3.b64", w=0.8)

    print("=== 各种通道组合对比（每次抓 4096 样点）===")
    combos = [
        ("voltage0 voltage1", "voltage0 voltage1"),
        ("voltage0 voltage2", "voltage0 voltage2"),
        ("voltage1 voltage3", "voltage1 voltage3"),
        ("voltage0", "voltage0"),
        ("(默认全部)", ""),
        ("voltage0 voltage1 voltage2 voltage3", "voltage0 voltage1 voltage2 voltage3"),
    ]
    for name, ch in combos:
        R("kill -9 $(ps | grep '[i]io_readdev' | awk '{print $1}') 2>/dev/null", w=0.6)
        cmd = ("rm -f /tmp/c.bin; timeout 25 iio_readdev -u usb: -s 4096 -b 4096 "
               "cf-ad9361-lpc %s > /tmp/c.bin 2>/dev/null; python3 /tmp/an3.py 2>&1" % ch)
        print("\n--- %s ---" % name)
        print(R(cmd, w=6.0, t=150))
