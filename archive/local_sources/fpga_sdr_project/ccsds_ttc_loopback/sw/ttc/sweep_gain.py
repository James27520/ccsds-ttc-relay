#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sweep_gain.py -- 自动扫转发板增益组合，找出能让 CCSDS 解出帧的设置

为什么需要
----------
  txatt=60 / rxgain=5 时，收到的有用信号只有 std=67（满量程 0.2%），
  被转发板的杂散盖住了，解不出帧。

  但这两个值是之前为了安全保守设的。现在 CMU200 已拔掉，
  可以逐步放开，找到"能解码 + 不饱和"的最佳点。

搜索策略
--------
  对 (rxgain, txatt) 组合：
    1. 设置转发板
    2. 检查 clip 是否增长（饱和就跳过）
    3. 发射 + 抓取
    4. 用 auto_decode 的频偏搜索解码
    5. 记录结果

  一旦解出帧就继续多试几组，最后报告最好的那组。
"""
import os
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, r"E:\LDSDR_010\rk3588")
import ccsds_tm_tx as CC
import auto_decode as AD
from serial_port import SerialPort

G = "\033[32m"; R = "\033[31m"; Y = "\033[33m"; C = "\033[36m"
B = "\033[1m"; D = "\033[2m"; N = "\033[0m"

BOARD = "192.168.2.1"
KEY = r"C:\Users\23638\.ssh\id_ed25519_dsh"
SSH = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no",
       "-o", "UserKnownHostsFile=NUL", "-o", "LogLevel=ERROR",
       "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "root@" + BOARD]
NS = 524288

sp = SerialPort("COM5", 115200)
time.sleep(0.8); sp.read()


def rc(c, w=1.1):
    sp.read(); sp.write(c + "\r\n"); time.sleep(w)
    return sp.read().decode("utf-8", "replace").replace("\r", "")


def rstat():
    for l in rc("status", 1.5).splitlines():
        if l.strip().startswith("STAT"):
            return l.strip()
    return ""


def kv(l):
    import re
    d = {}
    for t in re.sub(r"\((\d+)\)", "", l).split():
        if "=" in t:
            k, v = t.split("=", 1); d[k] = v
    return d


def ssh(cmd, timeout=180):
    r = subprocess.run(SSH + [cmd], capture_output=True, timeout=timeout)
    return ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace").strip()


def grab():
    ssh("rm -f /tmp/s.bin", 60)
    ssh("iio_readdev -u ip:localhost -s %d -b 65536 cf-ad9361-lpc "
        "voltage0 voltage1 > /tmp/s.bin 2>&1; echo rc=$?" % NS, 180)
    sz = ssh("wc -c < /tmp/s.bin 2>/dev/null || echo 0", 60).strip()
    if not sz.isdigit() or int(sz) < 4096:
        return None
    subprocess.run(["scp", "-O", "-i", KEY, "-o", "StrictHostKeyChecking=no",
                    "-o", "UserKnownHostsFile=NUL", "-o", "LogLevel=ERROR",
                    "-o", "BatchMode=yes", "root@%s:/tmp/s.bin" % BOARD,
                    os.path.join(HERE, "sweep.bin")], capture_output=True, timeout=180)
    raw = np.fromfile(os.path.join(HERE, "sweep.bin"), dtype=np.int16)
    return raw[0::2].astype(float), raw[1::2].astype(float)


def try_decode(I, Q):
    iq = (I + 1j * Q)
    iq = iq - iq.mean()
    h = CC.srrc(0.35, AD.SPS, span=8)
    for off_khz in range(-400, 401, 20):
        bits, ph, _ = AD.rx_at(iq, off_khz * 1e3, h)
        pos, err = AD.find_asm(bits)
        if err <= 2:
            fr = AD.decode_at(bits, pos)
            if fr:
                return off_khz, fr
    return None, []


def main():
    print("%s═══ 自动扫增益找可解码点 ═══%s" % (B + C, N))
    print("  链路：遥测板 TX1 → 转发板 RX1 → 转发板 TX1 → 遥测板 RX1")
    print("  遥测板: TX −30 dB, RX 增益 40 dB（固定）\n")

    rc("auto 0", 0.7)
    rc("lo 1000 1000", 1.0)
    rc("mode 1", 0.9); rc("gain 2048", 0.9)
    rc("ddc 0", 0.8); rc("duc 0", 0.8); rc("dc 0", 0.8)

    combos = [(5, 60), (10, 60), (10, 40), (15, 40),
              (20, 40), (20, 30), (30, 30), (10, 30)]

    results = []
    for rxg, txa in combos:
        print("%s── rxgain=%d  txatt=%d ──%s" % (C, rxg, txa, N))
        rc("rxgain %d" % rxg, 1.0)
        rc("txatt %d" % txa, 1.0)
        time.sleep(0.6)

        a = kv(rstat()); time.sleep(3); b = kv(rstat())
        clip = int(b.get("clip", 0)) - int(a.get("clip", 0))
        sat = clip > 2000
        print("   clip 增长 = %-10d %s" % (clip, "❌ 饱和，跳过" if sat else "✅"))
        if sat:
            results.append((rxg, txa, clip, None, None, []))
            continue

        ssh("killall -9 iio_writedev 2>/dev/null", 60)
        ssh("nohup sh -c 'for i in $(seq 1 30); do cat /tmp/wave.bin; done | "
            "iio_writedev -u ip:localhost -s %d -b 65536 "
            "cf-ad9361-dds-core-lpc voltage0 voltage1' >/dev/null 2>&1 & echo BG"
            % (52746320 * 10), 60)
        time.sleep(2.5)
        r = grab()
        ssh("killall -9 iio_writedev 2>/dev/null", 60)
        if r is None:
            print("   抓取失败")
            results.append((rxg, txa, clip, None, None, []))
            continue
        I, Q = r
        off, fr = try_decode(I, Q)
        print("   I.std=%-7.1f  max=%-6d  频偏=%-6s  帧=%d %s"
              % (I.std(), int(np.abs(np.concatenate([I, Q])).max()),
                 ("%+d kHz" % off) if off is not None else "—",
                 len(fr), "✅" if fr else "❌"))
        if fr:
            for o, L, p in fr[:2]:
                print("      SCID=0x%X MCFC=%d CRC=OK payload=%s..."
                      % (p["scid"], p["mcfc"], p["payload"][:4].hex()))
        results.append((rxg, txa, clip, float(I.std()), off, fr))

    print("\n%s═══ 汇总 ═══%s" % (B + C, N))
    print("  rxgain  txatt   clip增长    I.std    频偏      帧")
    print("  " + "-" * 58)
    for rxg, txa, clip, std, off, fr in results:
        print("  %-7d %-7d %-10d %-9s %-9s %d %s"
              % (rxg, txa, clip,
                 ("%.1f" % std) if std else "—",
                 ("%+d kHz" % off) if off is not None else "—",
                 len(fr), "✅" if fr else ""))

    good = [r for r in results if r[5]]
    if good:
        rxg, txa, _, std, off, fr = good[0]
        print("\n%s✅ 可用设置：rxgain=%d  txatt=%d（频偏 %+d kHz 时解出 %d 帧）%s"
              % (G + B, rxg, txa, off, len(fr), N))
        rc("rxgain %d" % rxg, 1.0); rc("txatt %d" % txa, 1.0)
        print("   已保留这组设置。")
    else:
        print("\n%s❌ 所有组合都没解出帧%s" % (R + B, N))
        print("""
  下一步查这个：
    有用信号到底在哪个频率？
      发射端：TX_LO=1000 + 基带 +200 kHz = 1000.2 MHz
      接收端：RX_LO=1000 → 基带应在 +200 kHz
    如果收到的不在 +200 kHz，说明中间有搬频没被发现。

  最可能：转发板的 DDC/DUC 没真正归零，或者转发板 RX 的 AD9361
  内部有频率偏移。可以在转发板上单独试：
      ddc 0 ; duc 0        （已设）
      rate 30.72           （已设）
    然后用 CMU200 单音测转发板的实际搬频量。
""")
    rc("auto 1", 0.8)
    sp.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
