#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_relay_dualch.py -- 转发板双通道（双向转发）验证

两条链路：
  ch1  馈电上行 -> 用户下行   (RX1 -> TX1)
  ch2  用户上行 -> 馈电下行   (RX2 -> TX2)

测试分三级：
  A 寄存器级   两个通道都能独立读写，计数器都在走（不需要射频）
  B 独立性     改 ch2 不影响 ch1，反之亦然
  C 射频级     需要信号源/频谱仪（给出步骤，人工判读）

用法：
    python test_relay_dualch.py            # A + B
    python test_relay_dualch.py COM5       # 指定串口
"""
import re
import sys
import time

sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from serial_port import SerialPort

G = "\033[32m"; R = "\033[31m"; Y = "\033[33m"; C = "\033[36m"
B = "\033[1m"; D = "\033[2m"; N = "\033[0m"


class Relay:
    def __init__(self, port="COM5"):
        self.sp = SerialPort(port, 115200)
        time.sleep(0.6)
        self.sp.read()

    def close(self):
        try:
            self.sp.close()
        except Exception:
            pass

    def cmd(self, c, wait=1.4):
        self.sp.read()
        self.sp.write(c + "\r\n")
        time.sleep(wait)
        t = self.sp.read().decode("utf-8", "replace").replace("\r", "")
        return [l.strip() for l in t.splitlines() if l.strip()]

    def find(self, c, key, wait=1.4):
        """发命令，返回含 key 的那一行"""
        self.sp.read()
        self.sp.write(c + "\r\n")
        time.sleep(wait)
        t = self.sp.read().decode("utf-8", "replace").replace("\r", "")
        for l in t.splitlines():
            if key in l:
                return l.strip()
        return ""

    def kv(self, line):
        """解析 STAT/ST2 行。注意 gain 现在打印成 'gain=800(2048)' —— 括号里是十进制，
        括号会污染取值，这里统一剥掉。"""
        import re as _re
        d = {}
        line = _re.sub(r"\((\d+)\)", r"", line)      # 去掉 '(2048)' 这种十进制附注
        for tok in line.split():
            if "=" in tok:
                k, v = tok.split("=", 1)
                d[k] = v
        return d


ok_all = True


def chk(name, cond, detail=""):
    global ok_all
    print("   %s %-34s %s" % (("✅" if cond else "❌"), name,
                              ("%s%s%s" % (D, detail, N)) if detail else ""))
    if not cond:
        ok_all = False
    return cond


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM5"
    print("%s═══ 转发板双通道（双向转发）验证 ═══%s" % (B, N))
    print("   串口 %s   115200" % port)
    print("   ch1 = 馈电上行→用户下行 (RX1→TX1)")
    print("   ch2 = 用户上行→馈电下行 (RX2→TX2)")
    print("   %s注意：CLI 里 gain / ddc / duc 是【十六进制】打印，mode 和计数器是十进制%s\n"
          % (D, N))

    # CLI 打印进制：十进制字段 / 十六进制字段
    DEC = ("mode", "rxgain", "txatt", "rxlo", "txlo", "fs",
           "in", "out", "clip", "in2", "clip2")
    HEX = ("ddc", "duc", "gain")

    def hexeq(got, want):
        """CLI 的 gain/ddc/duc 是十六进制小写打印"""
        try:
            return int(str(got), 16) == int(want)
        except Exception:
            return False

    rl = Relay(port)

    # ---------------- A 寄存器级 ----------------
    print("%s【A】寄存器级 —— 两个通道都在工作%s" % (C, N))
    rl.cmd("auto 0")
    time.sleep(0.4)

    s1a = rl.kv(rl.find("status", "STAT"))
    t1a = rl.kv(rl.find("stat2", "ST2"))
    if not s1a or not t1a:
        print("   %s❌ 拿不到状态，检查串口/固件版本%s" % (R, N))
        rl.close()
        return 2

    print("   ch1: mode=%s ddc=%s duc=%s gain=%s(hex) in=%s out=%s"
          % (s1a.get("mode"), s1a.get("ddc"), s1a.get("duc"),
             s1a.get("gain"), s1a.get("in"), s1a.get("out")))
    print("   ch2: mode=%s ddc=%s duc=%s gain=%s(hex) in2=%s"
          % (t1a.get("mode"), t1a.get("ddc"), t1a.get("duc"),
             t1a.get("gain"), t1a.get("in2")))

    chk("ch1 处于 relay 模式", s1a.get("mode") == "1")
    chk("ch2 处于 relay 模式", t1a.get("mode") == "1")
    chk("ch1 单位增益 (0x800)", hexeq(s1a.get("gain"), 0x800))
    chk("ch2 单位增益 (0x800)", hexeq(t1a.get("gain"), 0x800))

    print("   %s等待 4 秒后重读计数器...%s" % (D, N))
    time.sleep(4.0)
    s2a = rl.kv(rl.find("status", "STAT"))
    t2a = rl.kv(rl.find("stat2", "ST2"))

    def grew(a, b, k):
        try:
            return (int(b.get(k, 0)) - int(a.get(k, 0))) & 0xFFFFFFFF
        except Exception:
            return -1

    d_in1 = grew(s1a, s2a, "in")
    d_out = grew(s1a, s2a, "out")
    d_in2 = grew(t1a, t2a, "in2")
    chk("ch1 ADC 计数在增长", d_in1 > 0, "+%d" % d_in1)
    chk("ch1 DAC 计数在增长", d_out > 0, "+%d" % d_out)
    chk("ch2 ADC 计数在增长", d_in2 > 0, "+%d" % d_in2)
    chk("★ ch1 收发计数同步（零丢样）",
        abs(d_in1 - d_out) <= 4096, "in-out=%d (≤4096 为快照竞争)" % (d_in1 - d_out))

    # ---------------- B 独立性 ----------------
    print("\n%s【B】两通道相互独立%s" % (C, N))
    before1 = rl.kv(rl.find("status", "STAT"))

    # ch2: mute + 增益减半 + +100kHz 频偏 (fs=30.72M -> 0x00D55555)
    print("   %s设置 ch2: mode2=2(mute) gain2=0x400 duc2=0x00D55555%s" % (D, N))
    rl.cmd("mode2 2", 1.0)
    rl.cmd("gain2 1024", 1.0)                 # 1024 = 0x400
    rl.cmd("duc2 1398101", 1.0)               # 1398101 = 0x155555
    time.sleep(0.5)

    after1 = rl.kv(rl.find("status", "STAT"))
    after2 = rl.kv(rl.find("stat2", "ST2"))

    print("   ch1: mode=%s gain=%s(hex) duc=%s" %
          (after1.get("mode"), after1.get("gain"), after1.get("duc")))
    print("   ch2: mode=%s gain=%s(hex) duc=%s" %
          (after2.get("mode"), after2.get("gain"), after2.get("duc")))

    chk("ch2 模式已改为 mute", after2.get("mode") == "2")
    chk("ch2 增益已改为 0x400", hexeq(after2.get("gain"), 0x400),
        "回读 %s = %d" % (after2.get("gain"), int(after2.get("gain", "0"), 16)))
    chk("ch2 频偏已设置", hexeq(after2.get("duc"), 0x155555))
    chk("★ ch1 模式未受影响", after1.get("mode") == before1.get("mode"),
        "%s -> %s" % (before1.get("mode"), after1.get("mode")))
    chk("★ ch1 增益未受影响", after1.get("gain") == before1.get("gain"))
    chk("★ ch1 频偏未受影响", after1.get("duc") == before1.get("duc"))

    # 反向：改 ch1，看 ch2
    b2 = rl.kv(rl.find("stat2", "ST2"))
    rl.cmd("gain 1024", 1.0)
    rl.cmd("mode 2", 1.0)
    time.sleep(0.5)
    a2 = rl.kv(rl.find("stat2", "ST2"))
    chk("★ 改 ch1 不影响 ch2 增益", a2.get("gain") == b2.get("gain"))
    chk("★ 改 ch1 不影响 ch2 模式", a2.get("mode") == b2.get("mode"))

    # ---------------- 恢复 ----------------
    print("\n%s【恢复默认】%s" % (C, N))
    for c in ("mode 1", "gain 2048", "duc 0", "ddc 0",
              "mode2 1", "gain2 2048", "duc2 0", "ddc2 0", "auto 1"):
        rl.cmd(c, 0.7)
    fin1 = rl.kv(rl.find("status", "STAT"))
    fin2 = rl.kv(rl.find("stat2", "ST2"))
    print("   ch1: mode=%s gain=%s(hex) ddc=%s duc=%s"
          % (fin1.get("mode"), fin1.get("gain"), fin1.get("ddc"), fin1.get("duc")))
    print("   ch2: mode=%s gain=%s(hex) ddc=%s duc=%s"
          % (fin2.get("mode"), fin2.get("gain"), fin2.get("ddc"), fin2.get("duc")))
    chk("恢复后 ch1 relay + 单位增益",
        fin1.get("mode") == "1" and hexeq(fin1.get("gain"), 0x800))
    chk("恢复后 ch2 relay + 单位增益",
        fin2.get("mode") == "1" and hexeq(fin2.get("gain"), 0x800))

    rl.close()

    print("\n" + "═" * 66)
    if ok_all:
        print("  %s结论：双通道寄存器级 + 独立性验证 全部通过%s" % (G + B, N))
        print("  两条链路可各自独立配置，双向转发的基础具备。")
    else:
        print("  %s结论：有项目未通过，见上面的 ❌%s" % (R + B, N))
    print("═" * 66)

    print("\n%s【C】射频级验证（需要信号源，人工判读）%s" % (C, N))
    print("""   设置（示例，LO 900/1000 MHz）：
     rxgain 20 ; txatt 30 ; lo 900 1000 ; rate 30.72
     mode 1 ; gain 800 ; ddc 0 ; duc 0
     mode2 1 ; gain2 800 ; ddc2 0 ; duc2 0

   判据：
     ① 向 RX1 送 900.x MHz 单音  ->  频谱仪在 TX1 应看到 1000.x MHz
     ② 向 RX2 送 900.y MHz 单音  ->  频谱仪在 TX2 应看到 1000.y MHz
     ③ 两条同时送，互不干扰
     ④ 用 duc2/off2 改 ch2 频偏，TX2 频率应单独移动，TX1 不动
     ⑤ clip 与 clip2 计数应保持不增长（否则说明输入过强）

   ⚠️ 接线：TX1/TX2 不要直接接到 RX1/RX2，上电瞬态是满功率。""")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
