#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rx_fix.py -- 修正版：采样率用合法值、增益走 sysfs 直写

约定：CMU200 发 900.1 MHz，RX_LO = 900.0 MHz -> 基带 +100 kHz
"""
import os, subprocess, numpy as np, sys

BOARD, USER = "192.168.2.1", "root"
KEY = r"C:\Users\23638\.ssh\id_ed25519_dsh"
SSH = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no",
       "-o", "UserKnownHostsFile=/dev/null", "-o", "BatchMode=yes",
       "-o", "ConnectTimeout=10", "%s@%s" % (USER, BOARD)]

RX_LO = 900_000_000
FS = 4_000_000          # 合法（下限 2083333）
N = 4096
D0 = "/sys/bus/iio/devices/iio:device0"
D3 = "/sys/bus/iio/devices/iio:device3/scan_elements"


def sh(cmd, timeout=90, binary_to=None):
    if binary_to:
        with open(binary_to, "wb") as fh:
            r = subprocess.run(SSH + [cmd], stdout=fh, stderr=subprocess.PIPE, timeout=timeout)
        return r.returncode
    r = subprocess.run(SSH + [cmd], capture_output=True, text=True, timeout=timeout)
    return ((r.stdout or "").strip() or (r.stderr or "").strip())


print("=" * 74)
print(" 接收修正版：fs=4MSPS（合法值），增益走 sysfs 直写")
print("=" * 74)

sh("for c in voltage0 voltage1 voltage2 voltage3; do echo 0 > %s/in_${c}_en; done" % D3)
sh("echo 1 > %s/in_voltage0_en" % D3)
sh("echo 1 > %s/in_voltage1_en" % D3)

print("\n[1] 配置（全部走 sysfs 直写）")
for name, path, val in [
    ("采样率",  D0 + "/in_voltage_sampling_frequency", FS),
    ("RF带宽",  D0 + "/in_voltage_rf_bandwidth", 1000000),
    ("增益模式", D0 + "/in_voltage0_gain_control_mode", "manual"),
    ("RX_LO",   D0 + "/out_altvoltage0_RX_LO_frequency", RX_LO),
]:
    out = sh("echo %s > %s 2>&1; echo -n rc=$?; cat %s" % (val, path, path))
    print("  %-8s -> %s" % (name, out.replace("\n", " ")[:70]))

print("\n[2] 增益扫描（sysfs 直写 in_voltage0_hardwaregain）")
print("  增益  读回     I.std   Q.std   峰位置     峰功率  噪声底   SNR   饱和")
best = None
results = []
for g in (0, 5, 10, 15, 20, 25, 30, 40):
    sh("echo %d > %s/in_voltage0_hardwaregain" % (g, D0))
    rb = sh("cat %s/in_voltage0_hardwaregain" % D0)
    p = r"E:\LDSDR_010\_rx2.bin"
    sh("iio_readdev -s 131072 cf-ad9361-lpc voltage0 voltage1 > /tmp/r.bin 2>/dev/null")
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
    hi = (f > 60e3) & (f < 140e3)
    pk = pC[hi].max(); fpk = f[hi][pC[hi].argmax()]
    noise = np.median(pC[np.abs(f) > 1.5e6])
    sat = 100.0 * np.mean(np.abs(I) > 2000)
    snr = pk - noise
    print("  %4d  %-6s  %6.1f %6.1f  %+8.1f kHz  %7.1f %7.1f %5.1f dB  %4.2f%%"
          % (g, rb.split()[0] if rb.split() else "?", I.std(), Q.std(),
             fpk/1e3, pk, noise, snr, sat))
    results.append((g, snr, sat, pC, f, I.std()))
    if sat < 0.01 and (best is None or snr > best[1]):
        best = (g, snr, sat, pC, f, I.std())

if best is None:
    # 全饱和，取饱和最低的
    best = min(results, key=lambda r: r[2])
g, snr, sat, pC, f, istd = best
print("\n[3] 选增益 %d dB（饱和率 %.2f%%，SNR %.1f dB）" % (g, sat, snr))

sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from spectrum_tool import render_ascii
from spectrum import SpectrumFrame
import channel_detect as cd
fr = SpectrumFrame(list(pC), FS, 0, 0, 32, float(np.median(pC)), float(pC.max()), False)
chans, _ = cd.detect(fr, tracker=None)
print(render_ascii(fr, width=78, height=13, channels=chans,
                   title="─"*78 + "\n  CMU200@900.100MHz  RX_LO=900.000MHz  fs=4MSPS  gain=%ddB" % g))
print("  检测到 %d 个信道（信号干净时应该只有 1 个）" % len(chans))
for c in chans[:5]:
    print("    %+9.2f kHz  bw %8.0f Hz  SNR %5.1f dB" % (c.center_hz/1e3, c.bw_hz, c.snr_db))

print("\n[4] 频率校验")
print("  预期 +100.0 kHz（900.100 - 900.000）")
hi = (f > 60e3) & (f < 140e3)
fpk = f[hi][pC[hi].argmax()]
print("  实测 %+.2f kHz   误差 %+.2f kHz   (1 bin = %.1f Hz)"
      % (fpk/1e3, fpk/1e3 - 100.0, FS/N))
print("  %s" % ("✅ 准确" if abs(fpk/1e3 - 100.0) < 2*FS/N/1e3 else "⚠️ 偏差偏大"))
