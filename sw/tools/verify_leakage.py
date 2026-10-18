#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_leakage.py -- 判定"板上收到的信号到底从哪来"

背景：用户提问 —— TX1A 和 RX1A 没有用 SMA 线连起来，结果却也解出帧了。
      如果两点之间没有任何外部连接，那信号只能通过 AD9361 内部 / PCB 的
      TX->RX 泄漏过去（同一颗芯片、同一个本振，是已知现象）。
      必须实测确认，否则"过板子"的意义说不清。

三个对照实验：
  A) TX 静默（DDS scale=0）        -> 应该只有噪声
  B) TX 出单音（DDS scale=0.5）    -> 应该有单音
  C) TX 本振挪 +1 MHz             -> 收到的单音应该跟着挪（+1 MHz）
     这一条最关键：只有信号真的走 TX 调制->射频->RX 解调 这条路，
     本振一挪频点才会跟着挪。数字串扰不受本振影响。

用法: python verify_leakage.py
"""
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
FP = None
FS = 30_720_000.0
CAP = 262_144


def hostkey():
    r = subprocess.run([PLINK, "-ssh", "-batch", "-pw", PW, BOARD, "echo P"],
                       capture_output=True)
    m = re.search(r"SHA256:[A-Za-z0-9+/=]+",
                  (r.stdout + r.stderr).decode("utf-8", "replace"))
    return m.group(0) if m else None


def sh(cmd, timeout=240):
    args = [PLINK, "-ssh", "-batch"]
    if FP:
        args += ["-hostkey", FP]
    args += ["-pw", PW, BOARD, cmd]
    r = subprocess.run(args, capture_output=True, timeout=timeout)
    return ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace").strip()


def pull(remote, local):
    args = [PSCP, "-batch", "-scp"]
    if FP:
        args += ["-hostkey", FP]
    args += ["-pw", PW, "%s:%s" % (BOARD, remote), local]
    return subprocess.run(args, capture_output=True, timeout=300).returncode == 0


def capture(tag):
    sh("iio_readdev -u ip:localhost -b 65536 -s %d cf-ad9361-lpc voltage0 voltage1 "
       "> /tmp/vl_cap.bin" % (2 * CAP), timeout=240)
    loc = os.path.join(OUT, "vl_%s.bin" % tag)
    if not pull("/tmp/vl_cap.bin", loc):
        return None
    raw = np.fromfile(loc, dtype=np.int16)
    z = raw[0::2].astype(float) + 1j * raw[1::2].astype(float)
    return z


def spectrum(z):
    nfft = 8192
    k = max(1, min(len(z) // nfft, 16))
    w = np.hanning(nfft)
    acc = np.zeros(nfft)
    for i in range(k):
        acc += np.abs(np.fft.fftshift(np.fft.fft(z[i * nfft:(i + 1) * nfft] * w))) ** 2
    P = 10 * np.log10(acc / k + 1e-30)
    f = (np.arange(nfft) - nfft // 2) * (FS / nfft)
    return f, P


def report(tag, z, expect_hz=None):
    if z is None:
        print("  [%s] 抓取失败" % tag)
        return None
    rms = float(np.sqrt(np.mean(np.abs(z) ** 2)))
    f, P = spectrum(z)
    pk = int(np.argmax(P))
    snr = P[pk] - np.median(P)
    print("  [%-22s] RMS=%6.2f  峰值 %+9.0f Hz (%5.1f dB)  底噪 %5.1f  峰/底 %5.1f"
          % (tag, rms, f[pk], P[pk], np.median(P), snr))
    return rms, f[pk], snr


def main():
    global FP
    FP = hostkey()
    print("  主机密钥: %s" % FP)
    if not FP:
        return 1

    print("\n-- 配置：30.72 MSPS，TX/RX 本振都 2400 MHz，TX 衰减 40 dB，RX 增益 30 dB --")
    for c in [
        "iio_attr -u ip:localhost -c ad9361-phy voltage0 sampling_frequency 30720000",
        "iio_attr -u ip:localhost -i -c ad9361-phy voltage0 gain_control_mode manual",
        "iio_attr -u ip:localhost -i -c ad9361-phy voltage0 hardwaregain 30",
        "iio_attr -u ip:localhost -i -c ad9361-phy voltage1 gain_control_mode manual",
        "iio_attr -u ip:localhost -i -c ad9361-phy voltage1 hardwaregain 30",
        "iio_attr -u ip:localhost -o -c ad9361-phy voltage1 hardwaregain -40",
        "iio_attr -u ip:localhost -c ad9361-phy altvoltage0 frequency 2400000000",
        "iio_attr -u ip:localhost -c ad9361-phy altvoltage1 frequency 2400000000",
    ]:
        sh(c)

    # --- A) TX 静默 ---
    print("\n=== A) TX 静默（DDS 全部 scale=0）===")
    for c in ("altvoltage0", "altvoltage1", "altvoltage2", "altvoltage3"):
        sh("iio_attr -u ip:localhost -c cf-ad9361-dds-core-lpc %s scale 0" % c)
    time.sleep(0.5)
    zA = capture("quiet")
    rA = report("A 静默", zA)

    # --- B) TX 出 1 MHz 单音 ---
    print("\n=== B) TX 出 1 MHz 单音（scale=0.5）===")
    sh("iio_attr -u ip:localhost -c cf-ad9361-dds-core-lpc altvoltage0 frequency 1000000")
    sh("iio_attr -u ip:localhost -c cf-ad9361-dds-core-lpc altvoltage0 phase 90000")
    sh("iio_attr -u ip:localhost -c cf-ad9361-dds-core-lpc altvoltage0 scale 0.5")
    sh("iio_attr -u ip:localhost -c cf-ad9361-dds-core-lpc altvoltage2 frequency 1000000")
    sh("iio_attr -u ip:localhost -c cf-ad9361-dds-core-lpc altvoltage2 phase 0")
    sh("iio_attr -u ip:localhost -c cf-ad9361-dds-core-lpc altvoltage2 scale 0.5")
    time.sleep(0.5)
    zB = capture("tone2400")
    rB = report("B 单音(TXLO 2400)", zB)

    # --- C) TX 本振挪 +1 MHz ---
    print("\n=== C) TX 本振挪到 2401 MHz（RX 本振不动）===")
    print("     只有信号真的走射频，收到的单音才会跟着挪；数字串扰不会。")
    sh("iio_attr -u ip:localhost -c ad9361-phy altvoltage1 frequency 2401000000")
    time.sleep(0.5)
    zC = capture("tone2401")
    rC = report("C 单音(TXLO 2401)", zC)
    sh("iio_attr -u ip:localhost -c ad9361-phy altvoltage1 frequency 2400000000")

    print("\n" + "=" * 78)
    print("  结论")
    print("=" * 78)
    if rA and rB:
        print("  A 静默  峰/底=%.1f dB    B 单音  峰/底=%.1f dB" % (rA[2], rB[2]))
        print("  ★ 判据要用【峰值/底噪比】，不能用 RMS —— RMS 被噪声主导，")
        print("    单音存在与否在 RMS 上只差一点点，但在峰值上差别很大。")
        if rB[2] > rA[2] + 10:
            print("  -> TX 出单音时峰/底明显抬高  => 收到的单音确实来自 TX")
        else:
            print("  -> TX 开关对峰值没影响  => 收到的不是 TX 的信号")
    if rB and rC:
        print("  B 峰值 %+.0f Hz   C 峰值 %+.0f Hz  (差 %+.0f Hz)"
              % (rB[1], rC[1], rC[1] - rB[1]))
        move = rC[1] - rB[1]
        if move > 500e3:
            print("  -> TX 本振挪 +1 MHz，接收峰跟着挪 %+.0f Hz" % move)
            print("     ★ 证明信号真的经历了 TX 调制 -> 射频 -> RX 解调")
            print("     ★ 即：这是 AD9361 内部/PCB 的 TX->RX 泄漏，不是数字串扰")
        else:
            print("  -> 接收峰没跟着挪  => 信号不走射频（可能是数字串扰）")
    print()
    print("  ★ 对演示的意义：")
    print("     · 没接 SMA 线时，靠芯片内部泄漏就能自环 —— 演示照常能做")
    print("     · 但这【不是】真实的射频链路；要演示『真的发出去』")
    print("       必须用 SMA 线 TX1A -> RX1A（或接转发板/CMU200）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
