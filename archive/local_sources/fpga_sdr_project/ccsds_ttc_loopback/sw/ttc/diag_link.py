#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diag_link.py -- 快速诊断双板射频链路通不通

思路
----
  在两个状态下各抓一小段，比功率：
    状态 A：遥测板发射【关】
    状态 B：遥测板发射【开】
  如果链路通，B 的功率应明显高于 A（几十 dB）。
  如果两者一样 → 信号根本没过来，问题在接线或转发板配置。

  这样不用解码就能定位问题层次，比直接跑解码快得多。
"""
import os
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import loopback_test as LT

G = "\033[32m"; R = "\033[31m"; Y = "\033[33m"; C = "\033[36m"
B = "\033[1m"; D = "\033[2m"; N = "\033[0m"

NS = 262144          # 每次抓 26 万样点


def grab(tag):
    LT.ssh("rm -f /tmp/d.bin", 60)
    r = LT.ssh("iio_readdev -u ip:localhost -s %d -b 65536 "
               "cf-ad9361-lpc voltage0 voltage1 > /tmp/d.bin 2>&1; echo rc=$?" % NS, 180)
    sz = LT.ssh("wc -c < /tmp/d.bin 2>/dev/null || echo 0", 60).strip()
    if not sz.isdigit() or int(sz) < 4096:
        print("   %s[%s] 抓取失败 rc/大小: %s / %s%s" % (R, tag, r[-40:], sz, N))
        return None
    subprocess.run(["scp", "-O", "-i", LT.KEY, "-o", "StrictHostKeyChecking=no",
                    "-o", "UserKnownHostsFile=NUL", "-o", "LogLevel=ERROR",
                    "-o", "BatchMode=yes", "root@%s:/tmp/d.bin" % LT.BOARD,
                    os.path.join(HERE, "diag.bin")], capture_output=True, timeout=180)
    raw = np.fromfile(os.path.join(HERE, "diag.bin"), dtype=np.int16)
    I = raw[0::2].astype(float)
    Q = raw[1::2].astype(float)
    p = float(np.mean(I ** 2 + Q ** 2))
    return {"std": float(I.std()), "pwr": p, "pdb": 10 * np.log10(p + 1e-12),
            "max": int(np.abs(raw).max()), "n": len(I)}


def main():
    print("%s═══ 双板射频链路诊断 ═══%s" % (B, N))
    print("  遥测板 TX1 → 转发板 RX1 → 转发板 TX1 → 遥测板 RX1")

    print("\n%s[1] 检查配置%s" % (C, N))
    print("  遥测板 TX 衰减: %s"
          % LT.ssh("iio_attr -u ip:localhost -o -c ad9361-phy voltage1 hardwaregain 2>&1|tail -1", 60))
    print("  遥测板 RX 增益: %s"
          % LT.ssh("iio_attr -u ip:localhost -i -c ad9361-phy voltage0 hardwaregain 2>&1|tail -1", 60))

    # 转发板状态
    sys.path.insert(0, r"E:\LDSDR_010\rk3588")
    try:
        from serial_port import SerialPort
        sp = SerialPort("COM5", 115200)
        time.sleep(0.8); sp.read()
        sp.write("status\r\n"); time.sleep(1.5)
        t = sp.read().decode("utf-8", "replace").replace("\r", "")
        st = ""
        for l in t.splitlines():
            if l.strip().startswith("STAT"):
                st = l.strip(); break
        print("  转发板: %s" % st)
        sp.close()
    except Exception as e:
        print("  %s转发板串口打不开: %s%s" % (R, e, N))

    print("\n%s[2] 发射关时的接收功率（基准）%s" % (C, N))
    LT.ssh("killall -9 iio_writedev 2>/dev/null; echo ok", 60)
    time.sleep(1.5)
    a = grab("关")
    if a:
        print("   std=%.2f  功率=%.1f dB  峰值=%d"
              % (a["std"], a["pdb"], a["max"]))

    print("\n%s[3] 发射开时的接收功率%s" % (C, N))
    inner = ("for i in $(seq 1 30); do cat %s; done | "
             "iio_writedev -u ip:localhost -s %d -b 65536 "
             "cf-ad9361-dds-core-lpc voltage0 voltage1"
             % (LT.WAVE, LT.N_SAMP * 10))
    LT.ssh_bg(inner)
    time.sleep(2.5)
    b = grab("开")
    if b:
        print("   std=%.2f  功率=%.1f dB  峰值=%d"
              % (b["std"], b["pdb"], b["max"]))
    LT.ssh("killall -9 iio_writedev 2>/dev/null; echo TX_STOPPED", 60)

    print("\n%s[4] 结论%s" % (C, N))
    if not a or not b:
        print("   %s抓取有问题，先解决抓取%s" % (R, N))
        return 1
    delta = b["pdb"] - a["pdb"]
    print("   发射开 - 发射关 = %+.1f dB" % delta)
    if delta > 15:
        print("   %s✅ 链路是通的 —— 信号确实经过转发板回来了%s" % (G, N))
        print("      下一步可以直接跑 loopback_test.py run 解码")
    elif delta > 6:
        print("   %s⚠️ 有信号但很弱 —— 转发板的 TX 衰减太大%s" % (Y, N))
        print("      把转发板 txatt 从 60 降到 30 或 20 再试")
    else:
        print("   %s❌ 链路不通 —— 信号没过来%s" % (R, N))
        print("""
   按这个顺序查：
     1) SMA 线接了吗？必须是【交叉】接：
          遥测板 TX1 → 转发板 RX1
          转发板 TX1 → 遥测板 RX1
        接成 TX→TX 就等于什么都没接。
     2) 转发板 rxlo 是不是 1000？（status 里看 rxlo=1000）
        不是的话：把转发板串口打开敲 'lo 1000 1000'
     3) 转发板 mode 是不是 1？
        不是的话敲 'mode 1'
     4) 转发板 txatt 是不是 60？先降到 30 试试：
          敲 'txatt 30'
     5) 遥测板 RX 增益提到 50：
          iio_attr -u ip:localhost -i -c ad9361-phy voltage0 hardwaregain 50
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
