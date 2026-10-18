#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cmu200_demo.py -- 让遥测板持续发射，配合 CMU200 看频谱

为什么需要这个
--------------
模式 B 的发射是「有界管道循环」，只持续十几秒 —— 拿 CMU200 看根本来不及调。
本工具起一个【长时间持续】的发射（默认 10 分钟），并且可以随时停。

两种发射内容：
  tone   板载 DDS 出单音     —— 频谱上是一根干净的谱线，最容易找到
  ccsds  CCSDS 遥测波形      —— 频谱上是一片有带宽的信号（跳变、起伏）
                              ★ 用户要的「跳变的波形」就是这个

频率对照（CMU200 要设的中心频率 = 板子本振 + 基带频率）
  本振 2400 MHz
  tone 基带 1.000 MHz   -> 射频 2401.000 MHz
  ccsds 中频 0.200 MHz  -> 射频 2400.200 MHz

用法
  python cmu200_demo.py tone            # 开持续单音
  python cmu200_demo.py ccsds           # 开持续 CCSDS 波形
  python cmu200_demo.py off             # 停
  python cmu200_demo.py status          # 看状态
  python cmu200_demo.py freq            # 打印该设的中心频率

可选参数
  --lo 2400            本振 MHz
  --tone-hz 1000000    单音基带频率 Hz
  --txatt 40           TX 衰减 dB（数字越大输出越小）
  --minutes 10         持续多少分钟
"""
import argparse
import os
import re
import subprocess
import sys
import time

import numpy as np

PLINK = r"D:\PuTTY\plink.exe"
PSCP = r"D:\PuTTY\pscp.exe"
BOARD = "root@192.168.2.1"
PW = "analog"
OUT = r"E:\ccsds_fpga\out"

FS = 2_500_000.0            # 和模式 B 一致，方便复用同一份波形
SYM = 250_000.0
IF = 200_000.0
FP = None


def hostkey():
    r = subprocess.run([PLINK, "-ssh", "-batch", "-pw", PW, BOARD, "echo P"],
                       capture_output=True)
    m = re.search(r"SHA256:[A-Za-z0-9+/=]+",
                  (r.stdout + r.stderr).decode("utf-8", "replace"))
    return m.group(0) if m else None


def sh(cmd, timeout=300, show=False):
    args = [PLINK, "-ssh", "-batch"]
    if FP:
        args += ["-hostkey", FP]
    args += ["-pw", PW, BOARD, cmd]
    r = subprocess.run(args, capture_output=True, timeout=timeout)
    out = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace").strip()
    if show and out:
        for l in out.splitlines():
            print("    | %s" % l[:150])
    return out


def push(local, remote):
    args = [PSCP, "-batch", "-scp"]
    if FP:
        args += ["-hostkey", FP]
    args += ["-pw", PW, local, "%s:%s" % (BOARD, remote)]
    return subprocess.run(args, capture_output=True, timeout=600).returncode == 0


def base_cfg(lo_hz, txatt, gain=30):
    for c in [
        "iio_attr -u ip:localhost -c ad9361-phy voltage0 sampling_frequency %d" % int(FS),
        "iio_attr -u ip:localhost -c ad9361-phy voltage0 rf_bandwidth 1000000",
        "iio_attr -u ip:localhost -c ad9361-phy voltage1 rf_bandwidth 1000000",
        "iio_attr -u ip:localhost -c ad9361-phy altvoltage0 frequency %d" % lo_hz,
        "iio_attr -u ip:localhost -c ad9361-phy altvoltage1 frequency %d" % lo_hz,
        "iio_attr -u ip:localhost -i -c ad9361-phy voltage0 gain_control_mode manual",
        "iio_attr -u ip:localhost -i -c ad9361-phy voltage0 hardwaregain %d" % gain,
        "iio_attr -u ip:localhost -o -c ad9361-phy voltage1 hardwaregain -%d" % txatt,
    ]:
        sh(c)


def dds_off():
    for c in ("altvoltage0", "altvoltage1", "altvoltage2", "altvoltage3"):
        sh("iio_attr -u ip:localhost -c cf-ad9361-dds-core-lpc %s scale 0" % c)


def make_wave(path, nsamp, burst_ms=None):
    """
    burst_ms: (on_ms, off_ms)。给了就做成间断发射 ——
              CMU200 用 Zero Span 能看到清晰的脉冲包络（"跳变"）。
    """
    sys.path.insert(0, r"E:\fpga_sdr_project\ccsds_ttc_loopback\sw\ttc")
    sys.path.insert(0, r"E:\ccsds_fpga\tools")
    import ccsds_tm_tx as CC
    import tm_params as TP
    data = TP.build_data_block()
    frame = CC.build_tm_frame(scid=42, vcid=0, mcfc=0, vcfc=0, data=data, fecf=True)
    cadu, _ = CC.build_cadu(frame)
    ret = CC.cadu_to_iq(cadu, fs=FS, sym_rate=SYM, beta=0.35, amp=0.6, if_hz=IF)
    iq = CC.iq_interleave(ret[0], ret[1]) if isinstance(ret, tuple) else ret
    one = np.asarray(iq, dtype=np.int16)

    if burst_ms is not None:
        on_ms, off_ms = burst_ms
        n_on = int(FS * on_ms / 1000.0)
        n_off = int(FS * off_ms / 1000.0)
        # 一个周期 = 若干遍 CCSDS 波形（发）+ 一段静默（不发）
        reps_on = max(1, int(round(n_on / float(len(one)))))
        on_block = np.tile(one, reps_on)
        off_block = np.zeros(n_off, dtype=np.int16)
        period = np.concatenate([on_block, off_block])
        reps = int(np.ceil(nsamp / float(len(period))))
        w = np.tile(period, reps)[:nsamp]
        w.tofile(path)
        return len(w), len(one), len(period), len(on_block), len(off_block)

    reps = int(np.ceil(nsamp / float(len(one))))
    w = np.tile(one, reps)[:nsamp]
    w.tofile(path)
    return len(w), len(one), None, None, None


def main():
    global FP
    ap = argparse.ArgumentParser()
    ap.add_argument("act", choices=["tone", "ccsds", "burst", "off", "status", "freq"])
    ap.add_argument("--lo", type=float, default=2400.0)
    ap.add_argument("--tone-hz", type=float, default=1_000_000.0)
    ap.add_argument("--txatt", type=int, default=40)
    ap.add_argument("--minutes", type=float, default=10.0)
    ap.add_argument("--on-ms", type=float, default=20.0, help="burst: 发射毫秒数")
    ap.add_argument("--off-ms", type=float, default=20.0, help="burst: 静默毫秒数")
    a = ap.parse_args()

    FP = hostkey()
    if not FP:
        print("  [!] 板子不在线。先确认 ping 192.168.2.1 通")
        return 1
    lo_hz = int(a.lo * 1e6)

    if a.act == "freq":
        print("=" * 70)
        print("  CMU200 该设的中心频率")
        print("=" * 70)
        print("  本振 = %.3f MHz" % a.lo)
        print("  ── 单音模式 (tone) ──")
        print("     基带 %.3f MHz  ->  中心频率 %.4f MHz"
              % (a.tone_hz / 1e6, a.lo + a.tone_hz / 1e6))
        print("     Span 200 kHz 左右就够看一根谱线")
        print("  ── CCSDS 间断模式 (burst) ──")
        print("     中心频率同 ccsds = %.4f MHz" % (a.lo + IF / 1e6))
        print("     用 Zero Span（Span=0）看时域包络 -> 能看到清晰的脉冲跳变")
        print("  ── CCSDS 连续模式 (ccsds) ──")
        print("     基带中频 %.3f MHz  ->  中心频率 %.4f MHz"
              % (IF / 1e6, a.lo + IF / 1e6))
        print("     占用带宽约 %.0f kHz -> Span 用 1 MHz"
              % (SYM * 1.35 / 1e3))
        print("  两种模式都建议:  Reference Level = -30 dBm")
        return 0

    if a.act == "off":
        sh("killall -9 iio_writedev 2>/dev/null; echo KILLED", show=True)
        dds_off()
        print("  已停止发射，DDS 已关")
        return 0

    if a.act == "status":
        print("  iio_writedev 进程数: %s" % sh("ps | grep '[i]io_writedev' | wc -l"))
        for ch in ("altvoltage0", "altvoltage1", "altvoltage2", "altvoltage3"):
            print("  DDS %s scale = %s" % (ch, sh(
                "iio_attr -u ip:localhost -c cf-ad9361-dds-core-lpc %s scale" % ch)))
        print("  RX 本振 = %s" % sh("iio_attr -u ip:localhost -c ad9361-phy altvoltage0 frequency"))
        print("  TX 本振 = %s" % sh("iio_attr -u ip:localhost -c ad9361-phy altvoltage1 frequency"))
        print("  TX 衰减 = %s" % sh("iio_attr -u ip:localhost -o -c ad9361-phy voltage1 hardwaregain"))
        return 0

    # ---- 开持续发射 ----
    print("=" * 70)
    _what = {"tone": "板载 DDS 单音",
             "ccsds": "CCSDS 遥测波形（连续）",
             "burst": "CCSDS 遥测波形（间断，看得出跳变）"}[a.act]
    print("  持续发射：%s" % _what)
    print("=" * 70)
    base_cfg(lo_hz, a.txatt)
    print("  本振 %.3f MHz，TX 衰减 %d dB" % (a.lo, a.txatt))
    sh("killall -9 iio_writedev 2>/dev/null; echo ok")

    if a.act == "tone":
        f = int(a.tone_hz)
        dds_off()
        sh("iio_attr -u ip:localhost -c cf-ad9361-dds-core-lpc altvoltage0 frequency %d" % f)
        sh("iio_attr -u ip:localhost -c cf-ad9361-dds-core-lpc altvoltage0 phase 90000")
        sh("iio_attr -u ip:localhost -c cf-ad9361-dds-core-lpc altvoltage0 scale 0.5")
        sh("iio_attr -u ip:localhost -c cf-ad9361-dds-core-lpc altvoltage2 frequency %d" % f)
        sh("iio_attr -u ip:localhost -c cf-ad9361-dds-core-lpc altvoltage2 phase 0")
        sh("iio_attr -u ip:localhost -c cf-ad9361-dds-core-lpc altvoltage2 scale 0.5")
        print("  DDS 已开：I/Q 都在 %.3f MHz，scale 0.5" % (f / 1e6))
        print("  ★ 这是连续信号，不需要缓冲区，CMU200 上应该是一根稳定的谱线")
        print("\n  CMU200 设：中心频率 %.4f MHz   Span 200 kHz   Ref -30 dBm"
              % (a.lo + f / 1e6))
    else:
        dds_off()
        nsamp = 3_456_320
        wf = os.path.join(OUT, "cmu_wave.bin")
        if a.act == "burst":
            n, one, per, non, noff = make_wave(wf, nsamp,
                                               burst_ms=(a.on_ms, a.off_ms))
            print("  间断波形 %d 样点：发 %d（%.1f ms）+ 停 %d（%.1f ms），一个周期 %d 样点"
                  % (n, non, a.on_ms, noff, a.off_ms, per))
        else:
            n, one, per, non, noff = make_wave(wf, nsamp)
            print("  波形 %d 样点（一遍 %d），上传中..." % (n, one))
        if not push(wf, "/tmp/cmu_wave.bin"):
            print("  [!] 上传失败")
            return 1
        total = int(FS * a.minutes * 60)
        passes = int(np.ceil(total / float(n))) + 2
        print("  目标持续 %.1f 分钟 = %d 样点，循环 %d 遍喂管道" % (a.minutes, total, passes))
        inner = ("cd /tmp && nohup sh -c 'for i in $(seq 1 %d); do cat /tmp/cmu_wave.bin; done | "
                 "iio_writedev -u ip:localhost -s %d -b 65536 "
                 "cf-ad9361-dds-core-lpc voltage0 voltage1' >/tmp/cmu_tx.log 2>&1 & echo STARTED"
                 % (passes, total))
        sh(inner)
        time.sleep(2.0)
        print("  发射进程数: %s" % sh("ps | grep '[i]io_writedev' | wc -l"))
        if a.act == "burst":
            print("  ★ 间断发射：频域上看还是一块 %.0f kHz 宽的信号，" % (SYM * 1.35 / 1e3))
            print("     但用 Zero Span 看时域能看到清晰的脉冲跳变")
            print("\n  CMU200 设（两种看法）：")
            print("   ① 频域：Center %.4f MHz  Span 1 MHz  RBW 10 kHz  Ref -30 dBm"
                  % (a.lo + IF / 1e6))
            print("   ② 时域看跳变：Center %.4f MHz  【Span = 0 (Zero Span)】"
                  % (a.lo + IF / 1e6))
            print("      Sweep Time 设 100 ms 左右 -> 应看到周期约 %.0f ms 的脉冲"
                  % (a.on_ms + a.off_ms))
        else:
            print("  ★ 频谱上应该是一片有带宽的信号（占用约 %.0f kHz）" % (SYM * 1.35 / 1e3))
            print("\n  CMU200 设：Center %.4f MHz   Span 1 MHz   RBW 10 kHz   Ref -30 dBm"
                  % (a.lo + IF / 1e6))
    print("\n  停止：python cmu200_demo.py off")
    return 0


if __name__ == "__main__":
    sys.exit(main())
