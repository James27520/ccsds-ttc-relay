#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""干净地抓一次 IQ：只使能 voltage0/voltage1"""
import os, subprocess, numpy as np

BOARD, USER = "192.168.2.1", "root"
KEY = r"C:\Users\23638\.ssh\id_ed25519_dsh"
IQ = r"E:\LDSDR_010\iq_clean.bin"
SSH = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no",
       "-o", "UserKnownHostsFile=/dev/null", "-o", "BatchMode=yes",
       "-o", "ConnectTimeout=10", "%s@%s" % (USER, BOARD)]


def sh(cmd, timeout=120, binary_to=None):
    if binary_to:
        with open(binary_to, "wb") as fh:
            r = subprocess.run(SSH + [cmd], stdout=fh, stderr=subprocess.PIPE, timeout=timeout)
        return r.returncode
    r = subprocess.run(SSH + [cmd], capture_output=True, text=True, timeout=timeout)
    return ((r.stdout or "").strip() or (r.stderr or "").strip())


D3 = "/sys/bus/iio/devices/iio:device3/scan_elements"
print("=== 1. 只使能 voltage0(I) 和 voltage1(Q) ===")
sh("for c in voltage0 voltage1 voltage2 voltage3; do "
   "echo 0 > %s/in_${c}_en 2>/dev/null; done" % D3, timeout=40)
for c in ("voltage0", "voltage1"):
    sh("echo 1 > %s/in_%s_en" % (D3, c), timeout=40)
print("  " + sh("for f in %s/*_en; do echo -n \"$(basename $f)=\"; cat $f; done" % D3, timeout=40))

print("\n=== 2. 配置 (4 MSPS, RX_LO 900MHz, 手动增益 40dB) ===")
for c in ["iio_attr -c ad9361-phy voltage0 sampling_frequency 4000000",
          "iio_attr -c ad9361-phy voltage0 rf_bandwidth 4000000",
          "iio_attr -c ad9361-phy voltage0 gain_control_mode manual",
          "iio_attr -c ad9361-phy voltage0 hardwaregain 40",
          "iio_attr -c ad9361-phy altvoltage0 frequency 900000000"]:
    print("  %-52s -> %s" % (c.replace("iio_attr -c ad9361-phy ", ""), sh(c, timeout=40)))
print("  增益回读: " + sh("iio_attr -c ad9361-phy voltage0 hardwaregain", timeout=30))
print("  模式回读: " + sh("iio_attr -c ad9361-phy voltage0 gain_control_mode", timeout=30))

print("\n=== 3. 抓 262144 样点 ===")
print("  " + sh("iio_readdev -s 262144 cf-ad9361-lpc voltage0 voltage1 > /tmp/q.bin 2>/tmp/qe; "
                "echo rc=$?; ls -l /tmp/q.bin | awk '{print $5}'; head -2 /tmp/qe", timeout=120))
rc = sh("cat /tmp/q.bin", binary_to=IQ, timeout=300)
print("  传回 rc=%d  %d 字节" % (rc, os.path.getsize(IQ)))

# ---------- 分析 ----------
raw = np.fromfile(IQ, dtype=np.int16)
print("\n=== 4. 原始数据 ===")
print("  int16 个数 %d  -> %d 个样点对" % (len(raw), len(raw) // 2))
print("  前 16 个 int16: %s" % raw[:16])

I = raw[0::2].astype(np.float64)
Q = raw[1::2].astype(np.float64)
print("  I: mean %+.2f std %.2f  min %d max %d" % (I.mean(), I.std(), I.min(), I.max()))
print("  Q: mean %+.2f std %.2f  min %d max %d" % (Q.mean(), Q.std(), Q.min(), Q.max()))
print("  corr(I,Q) = %+.4f" % np.corrcoef(I, Q)[0, 1])

N, fs = 4096, 4000000.0
K = min(len(I) // N, 64)
win = np.hanning(N)
def psd(x):
    a = np.zeros(N)
    for k in range(K):
        s = x[k*N:(k+1)*N] * win
        a += np.abs(np.fft.fftshift(np.fft.fft(s)))**2
    return 10*np.log10(a/K/(N*N) + 1e-20)

pI, pQ, pC = psd(I), psd(Q), psd(I+1j*Q)
f = (np.arange(N)-N/2)*(fs/N)/1e3
def rep(p, nm):
    i = int(p.argmax()); print("  %-12s 峰 %+8.1f kHz (%6.1f dB)  底 %6.1f dB  差 %5.1f dB"
                               % (nm, f[i], p[i], np.median(p), p[i]-np.median(p)))
print("\n=== 5. 三种谱 ===")
rep(pI, "I 单独"); rep(pQ, "Q 单独"); rep(pC, "复数 I+jQ")
sym = np.abs(pC - pC[::-1])
print("  镜像不对称度: 均值 %.2f dB  最大 %.2f dB" % (sym.mean(), sym.max()))
print("  %s" % ("✅ 不对称 -> 是真复数信号（正常）" if sym.mean() > 3
                 else "⚠️ 仍然对称 -> 不是真 I/Q 对"))

import sys
sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from spectrum_tool import render_ascii
from spectrum import SpectrumFrame
import channel_detect as cd
fr = SpectrumFrame(list(pC), fs, 0, 0, K, float(np.median(pC)), float(pC.max()), False)
chans, _ = cd.detect(fr, tracker=None)
print("\n" + render_ascii(fr, width=78, height=12, channels=chans, title="─"*78))
print("  检测到 %d 个信道" % len(chans))
for c in chans[:6]:
    print("    %+9.1f kHz  bw %8.0f Hz  SNR %5.1f dB" % (c.center_hz/1e3, c.bw_hz, c.snr_db))
