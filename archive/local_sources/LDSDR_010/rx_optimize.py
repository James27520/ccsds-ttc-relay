#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rx_optimize.py -- 收 CMU200 的信号，扫增益找最佳点，显示频谱

约定：CMU200 发 900.1 MHz，RX_LO 设 900.0 MHz -> 基带 +100 kHz
"""
import os, subprocess, numpy as np, sys

BOARD, USER = "192.168.2.1", "root"
KEY = r"C:\Users\23638\.ssh\id_ed25519_dsh"
SSH = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no",
       "-o", "UserKnownHostsFile=/dev/null", "-o", "BatchMode=yes",
       "-o", "ConnectTimeout=10", "%s@%s" % (USER, BOARD)]

RX_LO = 900_000_000
CMU = 900_100_000
FS = 1_000_000
N = 4096


def sh(cmd, timeout=90, binary_to=None):
    if binary_to:
        with open(binary_to, "wb") as fh:
            r = subprocess.run(SSH + [cmd], stdout=fh, stderr=subprocess.PIPE, timeout=timeout)
        return r.returncode
    r = subprocess.run(SSH + [cmd], capture_output=True, text=True, timeout=timeout)
    return ((r.stdout or "").strip() or (r.stderr or "").strip())


D0 = "/sys/bus/iio/devices/iio:device0"
D3 = "/sys/bus/iio/devices/iio:device3/scan_elements"

print("=" * 74)
print(" 接收优化：CMU200 @900.1MHz  ->  RX_LO 900.0MHz  ->  基带 +100kHz")
print("=" * 74)

# ---- 基础配置 ----
sh("for c in voltage0 voltage1 voltage2 voltage3; do echo 0 > %s/in_${c}_en; done" % D3)
sh("echo 1 > %s/in_voltage0_en" % D3, timeout=40)
sh("echo 1 > %s/in_voltage1_en" % D3, timeout=40)

print("\n[1] 配置")
cfg = [
    ("采样率",       "iio_attr -c ad9361-phy voltage0 sampling_frequency %d" % FS),
    ("RF 带宽",      "iio_attr -c ad9361-phy voltage0 rf_bandwidth 1000000"),
    ("增益模式",     "iio_attr -c ad9361-phy voltage0 gain_control_mode manual"),
    ("RX_LO",        "iio_attr -c ad9361-phy altvoltage0 frequency %d" % RX_LO),
    ("射频口",       "iio_attr -c ad9361-phy voltage0 rf_port_select A_BALANCED"),
]
for name, c in cfg:
    out = sh(c, timeout=40)
    ok = "error" not in out.lower()
    print("  %-10s %-52s %s" % (name, c.replace("iio_attr -c ad9361-phy ", ""),
                                "OK" if ok else out[:60]))

print("\n[2] 回读")
for n, a in [("采样率", "voltage0 sampling_frequency"), ("RF带宽", "voltage0 rf_bandwidth"),
             ("增益模式", "voltage0 gain_control_mode"), ("RX_LO", "altvoltage0 frequency")]:
    print("  %-10s -> %s" % (n, sh("iio_attr -c ad9361-phy " + a, timeout=30)))


def cap(gain):
    sh("iio_attr -c ad9361-phy voltage0 hardwaregain %d" % gain, timeout=40)
    g = sh("iio_attr -c ad9361-phy voltage0 hardwaregain", timeout=30).splitlines()
    p = r"E:\LDSDR_010\_rxg.bin"
    sh("iio_readdev -s 131072 cf-ad9361-lpc voltage0 voltage1 > /tmp/r.bin 2>/dev/null", timeout=90)
    sh("cat /tmp/r.bin", binary_to=p, timeout=200)
    raw = np.fromfile(p, dtype=np.int16)
    I, Q = raw[0::2].astype(float), raw[1::2].astype(float)
    K = min(len(I) // N, 32)
    win = np.hanning(N)
    a = np.zeros(N)
    for k in range(K):
        s = (I[k*N:(k+1)*N] + 1j*Q[k*N:(k+1)*N]) * win
        a += np.abs(np.fft.fftshift(np.fft.fft(s)))**2
    pC = 10*np.log10(a/K/(N*N) + 1e-20)
    f = (np.arange(N) - N/2) * (FS/N)
    # +100kHz 附近的峰（用正频半边）
    hi = (f > 50e3) & (f < 150e3)
    pk = pC[hi].max()
    fpk = f[hi][pC[hi].argmax()]
    noise = np.median(pC[(f > 300e3)])          # 远端噪声底
    return gain, I.std(), Q.std(), fpk, pk, noise, pk - noise, pC, f


print("\n[3] 增益扫描（看 +100kHz 的峰）")
print("  增益   I.std  Q.std   峰位置     峰功率    噪声底    SNR")
best = None
for g in (20, 30, 40, 50, 60, 65, 70):
    gain, istd, qstd, fpk, pk, noise, snr, pC, f = cap(g)
    print("  %4d  %5.2f  %5.2f  %+8.1f kHz  %7.1f  %7.1f  %5.1f dB"
          % (gain, istd, qstd, fpk/1e3, pk, noise, snr))
    if best is None or snr > best[6]:
        best = (gain, istd, qstd, fpk, pk, noise, snr, pC, f)

gain, istd, qstd, fpk, pk, noise, snr, pC, f = best
print("\n[4] 最佳增益 %d dB，SNR %.1f dB —— 出图" % (gain, snr))

sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from spectrum_tool import render_ascii
from spectrum import SpectrumFrame
import channel_detect as cd
fr = SpectrumFrame(list(pC), FS, 0, 0, 32, float(noise), float(pk), False)
chans, _ = cd.detect(fr, tracker=None)
print(render_ascii(fr, width=78, height=13, channels=chans,
                   title="─"*78 + "\n  CMU200 @900.100MHz  RX_LO=900.000MHz  fs=1MSPS  gain=%ddB" % gain))
print("  检测到 %d 个信道" % len(chans))
for c in chans[:6]:
    print("    %+9.1f kHz  bw %8.0f Hz  SNR %5.1f dB" % (c.center_hz/1e3, c.bw_hz, c.snr_db))

# 理论位置校验
print("\n[5] 位置校验")
print("  预期基带频率 = 900.100 - 900.000 = +100.0 kHz")
print("  实测峰位置   = %+.1f kHz" % (fpk/1e3))
print("  误差         = %+.1f kHz" % (fpk/1e3 - 100.0))
err = abs(fpk/1e3 - 100.0)
print("  %s" % ("✅ 误差在 1 个 bin (%.0f Hz) 内，频率准确" % (FS/N)
                 if err < 2*FS/N/1e3 else "⚠️ 偏差 %.1f kHz，需查" % err))
