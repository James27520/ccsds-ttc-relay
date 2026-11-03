#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rf_verify_dualch.py -- 转发板双通道【射频级】验证助手

寄存器级和独立性已经验证过了（见 test_relay_dualch.py）。
这个脚本负责射频部分：配置好参数，然后引导你一步步用 CMU200 测量并记录结果。

为什么用 CMU200 就够、不需要衰减器
----------------------------------
  CMU200 的 RF 口能承受 +30 dBm，输出电平可编程。
  LDSDR 满功率输出约 +7 dBm，txatt=30 时约 -23 dBm —— 都在 CMU200 承受范围内。
 🚫 但绝不要把 LDSDR 的 TX 直接接到它自己的 RX（上电瞬态满功率，RX 只耐 +2.5 dBm）。

用法：
    python rf_verify_dualch.py                 # 配置 + 交互式引导
    python rf_verify_dualch.py COM5
    python rf_verify_dualch.py COM5 setup      # 只配置不引导
"""
import sys
import time

sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from serial_port import SerialPort

G = "\033[32m"; R = "\033[31m"; Y = "\033[33m"; C = "\033[36m"
B = "\033[1m"; D = "\033[2m"; N = "\033[0m"

# ---- 频率规划（按你的实际需求改这两个数就行）----
RX_LO_MHZ = 900       # 上行频段本振
TX_LO_MHZ = 1000      # 下行频段本振
FS_MHZ = 30.72
TXATT = 30            # 衰减 dB，先用大一点保安全
RXGAIN = 20

# ch1: 馈电上行 -> 用户下行
CH1_RX_MHZ = 900.1
CH1_TX_EXPECT = 1000.1
# ch2: 用户上行 -> 馈电下行
CH2_RX_MHZ = 900.2
CH2_TX_EXPECT = 1000.2


class Relay:
    def __init__(self, port="COM5"):
        self.sp = SerialPort(port, 115200)
        time.sleep(0.8)
        self.sp.read()

    def cmd(self, c, w=1.3):
        self.sp.read()
        self.sp.write(c + "\r\n")
        time.sleep(w)
        return self.sp.read().decode("utf-8", "replace").replace("\r", "")

    def line(self, c, pref, w=1.5):
        r = self.cmd(c, w)
        for l in r.splitlines():
            if l.strip().startswith(pref):
                return l.strip()
        return ""

    def kv(self, line):
        d = {}
        for tok in line.replace("(", " ").replace(")", " ").split():
            if "=" in tok:
                k, v = tok.split("=", 1)
                d[k] = v
        return d

    def close(self):
        try:
            self.sp.close()
        except Exception:
            pass


def banner(t):
    print("\n%s%s%s" % (B + C, t, N))


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM5"
    just_setup = len(sys.argv) > 2 and sys.argv[2] == "setup"

    print("%s═══ 转发板双通道射频验证 ═══%s" % (B, N))
    print("   串口 %s" % port)
    print("   %s频率规划：RX_LO=%d MHz  TX_LO=%d MHz  fs=%.2f MHz%s"
          % (D, RX_LO_MHZ, TX_LO_MHZ, FS_MHZ, N))

    rl = Relay(port)

    banner("1. 配置转发板")
    setup = [
        "auto 0",
        "rxgain %d" % RXGAIN,
        "txatt %d" % TXATT,
        "lo %d %d" % (RX_LO_MHZ, TX_LO_MHZ),
        "rate %.2f" % FS_MHZ,
        # 两个通道都设为纯透明转发，无频偏
        "mode 1", "gain 2048", "ddc 0", "duc 0", "dc 0",
        "mode2 1", "gain2 2048", "ddc2 0", "duc2 0", "dc2 0",
    ]
    for c in setup:
        r = rl.cmd(c, 0.9)
        ok = "OK" in r or "auto" in r
        print("   %s %-16s %s" % (("✅" if ok else "⚠️"), c,
                                  r.strip().splitlines()[0][:56] if r.strip() else ""))

    time.sleep(1.0)
    s1 = rl.line("status", "STAT")
    s2 = rl.line("stat2", "ST2")
    print("\n   ch1 %s" % s1)
    print("   ch2 %s" % s2)

    if just_setup:
        rl.close()
        print("\n%s配置完成（未做射频引导）%s" % (G, N))
        return 0

    # ---------------- 射频引导 ----------------
    banner("2. 需要准备的接线")
    print("""
   你有 CMU200，它的 RF1/RF2 都是双工口（IN+OUT 合一）。

   测试① ch1：馈电上行 → 用户下行
        CMU200 RF1 OUT  ──SMA──►  LDSDR RX1
        CMU200 RF2 IN   ◄──SMA──  LDSDR TX1

   测试② ch2：用户上行 → 馈电下行
        CMU200 RF2 OUT  ──SMA──►  LDSDR RX2
        CMU200 RF1 IN   ◄──SMA──  LDSDR TX2

   ⚠️ 只用 SMA 线，不要接 LDSDR 自己的 RX↔TX。
   ⚠️ 第一次先把 CMU200 输出设到 -60 dBm 这种小电平。
""")
    input("   接线好了、CMU200 也打开了，按回车继续...")

    def ask(prompt):
        try:
            return input(prompt).strip()
        except EOFError:
            return ""

    banner("3. 测试① —— ch1（馈电上行 → 用户下行）")
    print("""
   CMU200 上做：
     信号源：  %d MHz，-60 dBm，开输出
     分析仪：  中心 %d MHz，span 1 MHz，RBW 10 kHz，参考电平 -40 dBm
               （建议开 Max Hold）
""" % (CH1_RX_MHZ, CH1_TX_EXPECT))
    print("   %s在 LDSDR 端应该看到：%s" % (D, N))
    print("     - clip 计数不增长（增长说明输入过强）")
    print("     - in/out 计数继续增长")
    before = rl.kv(rl.line("status", "STAT"))
    ask("   按回车记录当前状态...")
    mid = rl.kv(rl.line("status", "STAT"))
    try:
        dc = (int(mid.get("clip", 0)) - int(before.get("clip", 0))) & 0xFFFFFFFF
    except Exception:
        dc = -1
    print("   clip 增长 = %d   %s" % (dc, "✅ 无饱和" if dc == 0 else "⚠️ 输入过强，降 CMU200 电平"))
    r1_freq = ask("   CMU200 RF2 上读到的频率 (MHz) = ")
    r1_level = ask("   CMU200 RF2 上读到的电平 (dBm) = ")

    banner("4. 测试② —— ch2（用户上行 → 馈电下行）")
    print("""
   CMU200 上做：
     信号源：  %d MHz，-60 dBm，开输出
     分析仪：  中心 %d MHz，span 1 MHz，RBW 10 kHz
""" % (CH2_RX_MHZ, CH2_TX_EXPECT))
    ask("   按回车记录当前状态...")
    a = rl.kv(rl.line("stat2", "ST2"))
    print("   ch2 in2=%s clip2=%s" % (a.get("in2"), a.get("clip2")))
    r2_freq = ask("   CMU200 RF1 上读到的频率 (MHz) = ")
    r2_level = ask("   CMU200 RF1 上读到的电平 (dBm) = ")

    banner("5. 测试③ —— 双通道同时（互相干扰检查）")
    print("""
   两路信号源同时开：
     RF1 OUT  %d MHz  ──►  RX1
     RF2 OUT  %d MHz  ──►  RX2
   然后看两个分析仪通道。
   预期 TX1 频率不动、TX2 频率不动，两个电平都不明显变化。
""" % (CH1_RX_MHZ, CH2_RX_MHZ))
    ask("   两路都开着，按回车记录...")
    b = rl.kv(rl.line("status", "STAT"))
    c = rl.kv(rl.line("stat2", "ST2"))
    print("   ch1 in=%s clip=%s" % (b.get("in"), b.get("clip")))
    print("   ch2 in2=%s clip2=%s" % (c.get("in2"), c.get("clip2")))
    r3_1 = ask("   同时开时 CMU200 RF2 频率/电平 = ")
    r3_2 = ask("   同时开时 CMU200 RF1 频率/电平 = ")

    banner("6. 测试④ —— 频偏独立性（最关键的一条）")
    print("""
   现在只改 ch2 的频偏，ch1 必须完全不动。
   例：给 ch2 加 +100 kHz
""" % ())
    delta = 100000
    word = int(round(delta / (FS_MHZ * 1e6) * (2 ** 32))) & 0xFFFFFFFF
    print("     将要发送：  duc2 %d   (= 0x%08X, +%d Hz)" % (word, word, delta))
    ask("   确认 ch1 分析仪正在看着，按回车执行...")
    pre1 = rl.line("status", "STAT")
    print("   " + rl.cmd("duc2 %d" % word, 1.2).strip().splitlines()[0][:80])
    time.sleep(0.6)
    post1 = rl.line("status", "STAT")
    post2 = rl.line("stat2", "ST2")
    print("   改之前 ch1: %s" % pre1)
    print("   改之后 ch1: %s" % post1)
    print("   改之后 ch2: %s" % post2)
    print("   %s★ ch1 的 duc 必须还是 00000000，且 CMU200 上 TX1 频率不动%s" % (Y, N))
    r4 = ask("   CMU200 RF2 上的频率有没有变？(y/n) = ")

    # 恢复
    rl.cmd("duc2 0", 0.9)
    rl.cmd("auto 1", 0.9)

    banner("7. 结果汇总")
    print("""
   ┌────────────────────────────────────────────────────────────┐
   │ 测试① ch1 馈电上行→用户下行                                 │
   │   预期 %.1f MHz    实测 %-10s   电平 %-8s        │
   ├────────────────────────────────────────────────────────────┤
   │ 测试② ch2 用户上行→馈电下行                                 │
   │   预期 %.1f MHz    实测 %-10s   电平 %-8s        │
   ├────────────────────────────────────────────────────────────┤
   │ 测试③ 同时开 —— RF2 %-16s RF1 %-16s │
   ├────────────────────────────────────────────────────────────┤
   │ 测试④ 改 ch2 频偏，TX1 是否移动：%-24s │
   └────────────────────────────────────────────────────────────┘
""" % (CH1_TX_EXPECT, r1_freq or "(未填)", r1_level or "(未填)",
       CH2_TX_EXPECT, r2_freq or "(未填)", r2_level or "(未填)",
       (r3_1 or "(未填)")[:16], (r3_2 or "(未填)")[:16],
       ("是(❌ 不独立)" if r4.lower().startswith("y") else "否(✅ 独立)")))

    print("""
   判读：
     ✅ 通过：两个频率都落在预期值 ±10 kHz 内，两路互不影响，
              改 ch2 频偏时 TX1 频率不动
     ⚠️ 频率偏了：检查 LO 设置和 ddc/duc 相位字换算
     ⚠️ 一路没信号：查该通道的 RX/TX SMA 接线、clip 计数、mode
""")

    rl.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
