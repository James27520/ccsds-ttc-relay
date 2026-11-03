#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
new_board_capture.py -- 从新板抓 IQ，在 PC 上做 FFT，出频谱
"""

import os, subprocess, sys, time
import numpy as np

BOARD, USER = "192.168.2.1", "root"
KEY = r"C:\Users\23638\.ssh\id_ed25519_dsh"
IQ = r"E:\LDSDR_010\iq_new_board.bin"

SSH = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no",
       "-o", "UserKnownHostsFile=/dev/null", "-o", "BatchMode=yes",
       "-o", "ConnectTimeout=10", "%s@%s" % (USER, BOARD)]


def sh(cmd, timeout=120, binary_to=None):
    if binary_to:
        with open(binary_to, "wb") as fh:
            r = subprocess.run(SSH + [cmd], stdout=fh, stderr=subprocess.PIPE, timeout=timeout)
        return r.returncode, r.stderr.decode("ascii", "replace")
    r = subprocess.run(SSH + [cmd], capture_output=True, text=True, timeout=timeout)
    return (r.stdout or "").strip() or (r.stderr or "").strip()


print("=" * 74)
print(" 新板 IQ 抓取 + FFT")
print("=" * 74)

# ---------- 配置 ----------
SR = 4000000
NSAMP = 262144
print("\n[1] 配置（用 iio_attr，比直接写 sysfs 可靠）")
for c in [
    "iio_attr -c ad9361-phy voltage0 sampling_frequency %d" % SR,
    "iio_attr -c ad9361-phy voltage0 rf_bandwidth %d" % (SR * 2),
    "iio_attr -c ad9361-phy voltage0 gain_control_mode manual",
    "iio_attr -c ad9361-phy voltage0 hardwaregain 40",
    "iio_attr -c ad9361-phy altvoltage0 frequency 900000000",
    "iio_attr -c ad9361-phy altvoltage1 frequency 1000000000",
]:
    out = sh(c, timeout=40)
    print("  %-62s %s" % (c.replace("iio_attr ", ""), out if out else "OK"))

print("\n[2] 回读确认")
for c in ["iio_attr -c ad9361-phy voltage0 sampling_frequency",
          "iio_attr -c ad9361-phy voltage0 rf_bandwidth",
          "iio_attr -c ad9361-phy voltage0 hardwaregain",
          "iio_attr -c ad9361-phy altvoltage0 frequency",
          "iio_attr -c ad9361-phy altvoltage1 frequency"]:
    print("  %-46s -> %s" % (c.replace("iio_attr -c ad9361-phy ", ""), sh(c, timeout=30)))

print("\n[3] 抓 %d 样点 @ %d Hz" % (NSAMP, SR))
t0 = time.time()
out = sh("iio_readdev -s %d cf-ad9361-lpc voltage0 voltage1 > /tmp/iq.bin 2>/tmp/e; "
         "echo rc=$?; ls -l /tmp/iq.bin | awk '{print $5}'; head -2 /tmp/e" % NSAMP)
print("  " + out.replace("\n", "\n  "))
print("  用时 %.2f 秒" % (time.time() - t0))

print("\n[4] 传回 PC（用 ssh cat，绕开 sftp-server 缺失）")
rc, err = sh("cat /tmp/iq.bin", binary_to=IQ, timeout=300)
if os.path.exists(IQ):
    print("  %s  %d 字节  (rc=%d)" % (IQ, os.path.getsize(IQ), rc))
    if err.strip():
        print("  stderr: %s" % err.strip()[:150])

# ---------- FFT ----------
if os.path.exists(IQ) and os.path.getsize(IQ) >= 4096:
    raw = np.fromfile(IQ, dtype=np.int16)
    n = len(raw) // 2
    iq = raw[:2 * n].astype(np.float32)
    I = iq[0::2].astype(np.float32)
    Q = iq[1::2].astype(np.float32)
    print("\n[5] FFT 分析  样点数 I=%d Q=%d" % (len(I), len(Q)))
    print("  I: 均值 %.1f 标准差 %.1f 最小 %d 最大 %d" % (I.mean(), I.std(), I.min(), I.max()))
    print("  Q: 均值 %.1f 标准差 %.1f 最小 %d 最大 %d" % (Q.mean(), Q.std(), Q.min(), Q.max()))

    if I.std() < 0.5:
        print("  ⚠️ I/Q 几乎全是常数 —— 可能没使能扫描通道，或没有数据流")
    else:
        N = 4096
        K = len(I) // N
        # 用 Welch 法平均，平滑噪声
        win = np.hanning(N).astype(np.float32)
        acc = np.zeros(N)
        for k in range(min(K, 64)):
            seg = (I[k * N:(k + 1) * N] + 1j * Q[k * N:(k + 1) * N]) * win
            X = np.fft.fftshift(np.fft.fft(seg))
            acc += np.abs(X) ** 2
        acc /= min(K, 64)
        psd = 10 * np.log10(acc / (N * N) + 1e-20)

        fs = SR
        rbw = fs / N
        f = (np.arange(N) - N / 2) * rbw
        noise = np.median(psd)
        peak = psd.max()
        pk_i = int(psd.argmax())
        print("  FFT %d 点 × %d 次平均，RBW = %.1f Hz" % (N, min(K, 64), rbw))
        print("  噪声底 %.1f dB   峰值 %.1f dB   峰在 %+.1f kHz   SNR %.1f dB"
              % (noise, peak, f[pk_i] / 1e3, peak - noise))

        # ASCII 频谱
        import sys as _s
        _s.path.insert(0, r"E:\LDSDR_010\rk3588")
        from spectrum_tool import render_ascii
        from spectrum import SpectrumFrame
        import channel_detect as cd

        fr = SpectrumFrame(list(psd), fs, 0, 0, min(K, 64), noise, peak, False)
        chans, info = cd.detect(fr, tracker=None)
        print("\n" + render_ascii(fr, width=78, height=13, channels=chans,
                                  title="─" * 78))
        print("  检测到 %d 个信道" % len(chans))
        for c in chans[:8]:
            print("    #%s %+9.3f kHz  bw %7.0f Hz  SNR %5.1f dB"
                  % (c.id, c.center_hz / 1e3, c.bw_hz, c.snr_db))

        # 存 csv
        csv = r"E:\LDSDR_010\new_board_spectrum.csv"
        np.savetxt(csv, np.column_stack([f, psd]), delimiter=",",
                   header="freq_hz,psd_db", comments="")
        print("\n  频谱存 %s" % csv)
else:
    print("\n没有有效 IQ 数据，跳过 FFT")

print("\n完成。")
