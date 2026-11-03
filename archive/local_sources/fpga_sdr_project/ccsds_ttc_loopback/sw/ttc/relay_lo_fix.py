#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
relay_lo_fix.py -- 把转发板配成 "1000 进 / 900 出"，并检查 RX 是否还在饱和

转发板搬频关系
--------------
    基带 = 输入 - RX_LO
    输出 = TX_LO + 基带 = 输入 + (TX_LO - RX_LO)

  要 1000 进 900 出  =>  TX_LO - RX_LO = -100 MHz
  所以  lo 1000 900

  若 RX_LO == TX_LO（比如都是 1000），输出就等于输入频率，CMU200 在 900 收不到。
"""
import sys
import time

sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from serial_port import SerialPort

G = "\033[32m"; R = "\033[31m"; Y = "\033[33m"; C = "\033[36m"
B = "\033[1m"; D = "\033[2m"; N = "\033[0m"

sp = SerialPort("COM5", 115200)
time.sleep(0.8)
sp.read()


def cmd(c, w=1.2):
    sp.read()
    sp.write(c + "\r\n")
    time.sleep(w)
    return sp.read().decode("utf-8", "replace").replace("\r", "")


def stat():
    for l in cmd("status", 1.5).splitlines():
        if l.strip().startswith("STAT"):
            return l.strip()
    return ""


def kv(line):
    import re
    d = {}
    for tok in re.sub(r"\((\d+)\)", "", line).split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            d[k] = v
    return d


print("%s═══ 转发板：修正为 1000 进 / 900 出 ═══%s" % (B + C, N))

print("\n%s[1] 当前状态%s" % (C, N))
before = stat()
print("   " + before)

print("\n%s[2] 先把 RX 增益降到 0，确认不是自激%s" % (C, N))
cmd("auto 0", 0.8)
print("   " + cmd("rxgain 0").strip().splitlines()[0][:60])
s0 = stat()
time.sleep(4)
s1 = stat()
c0 = int(kv(s0).get("clip", 0)); c1 = int(kv(s1).get("clip", 0))
print("   4 秒内 clip 增长 = %d  %s"
      % (c1 - c0, "✅ 没有饱和，问题是增益太高" if (c1 - c0) < 1000
         else "⚠️ 还在饱和 —— RX 通路本身有问题"))

print("\n%s[3] 设置频率：rxlo=1000  txlo=900%s" % (C, N))
for c in ["lo 1000 900",
          "txatt 30",            # 先给个中等衰减，方便在 CMU200 上看到
          "rxgain 20",
          "rate 30.72",
          "mode 1", "gain 2048", "ddc 0", "duc 0", "dc 0"]:
    print("   %s %-16s %s" % ("✅", c, cmd(c, 1.0).strip().splitlines()[0][:52]))

time.sleep(1.0)
print("\n%s[4] 配置后状态%s" % (C, N))
after = stat()
print("   " + after)
k = kv(after)
print("""
   搬频关系：输出 = 输入 + (TX_LO - RX_LO)
             = 输入 + (%s - %s) = 输入 - 100 MHz
   所以 1000 MHz 进  →  900 MHz 出   %s
""" % (k.get("txlo"), k.get("rxlo"),
       "✅" if (int(k.get("txlo", 0)) - int(k.get("rxlo", 0))) == -100 else "⚠️ 检查"))

print("%s[5] 现在怎么测%s" % (C, N))
print("""
   CMU200 设置：
     信号源：  1000.200 MHz，-60 dBm   （偏移 200 kHz 避开零中频的脏区）
     分析仪：  中心 900.200 MHz，span 1 MHz，RBW 10 kHz

   ⭐ 关键：输入频率必须和 RX_LO 差在基带范围内（±1.25 MHz 对应 30.72 MSPS）。
      1000.2 - 1000.0 = +200 kHz ✓ 在范围内

   ⭐ 如果你只想看有没有波形，也可以让 CMU200 发 1000.2、收 900.2：
      转发板把 +200 kHz 的基带原样搬到 TX_LO 上 → 900.2 MHz

   接线（按你说的两组 txrx，别跨组）：
     CMU200 RF OUT ──► 转发板 RX1
     转发板 TX1    ──► CMU200 RF IN
""")

print("%s[6] 看 clip 是否还在涨（决定 rxgain 合不合适）%s" % (C, N))
s2 = stat(); time.sleep(4); s3 = stat()
d = int(kv(s3).get("clip", 0)) - int(kv(s2).get("clip", 0))
print("   4 秒内 clip 增长 = %d  %s"
      % (d, "✅ 合适" if d < 1000 else "⚠️ 还是太高，把 rxgain 再降 10"))

sp.close()
