#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
判别 1688 kHz 伪影的性质：
  - 若它是「数字伪影」 -> 频率随 fs 成比例变化（占 fs 的固定比例）
  - 若它是「真实射频信号」 -> 绝对频率不变
再测不同增益，看它是不是内部耦合
"""
import os, subprocess, numpy as np

BOARD, USER = "192.168.2.1", "root"
KEY = r"C:\Users\23638\.ssh\id_ed25519_dsh"
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
sh("for c in voltage0 voltage1 voltage2 voltage3; do echo 0 > %s/in_${c}_en; done" % D3)
sh("echo 1 > %s/in_voltage0_en" % D3)
sh("echo 1 > %s/in_voltage1_en" % D3)

N = 4096


def capture(fs, gain_db, tag):
    for c in ["iio_attr -c ad9361-phy voltage0 sampling_frequency %d" % fs,
              "iio_attr -c ad9361-phy voltage0 rf_bandwidth %d" % min(fs, 56000000),
              "iio_attr -c ad9361-phy voltage0 gain_control_mode manual",
              "iio_attr -c ad9361-phy voltage0 hardwaregain %d" % gain_db,
              "iio_attr -c ad9361-phy altvoltage0 frequency 900000000"]:
        sh(c, timeout=40)
    g = sh("iio_attr -c ad9361-phy voltage0 hardwaregain", timeout=30).splitlines()[-1].strip()
    p = r"E:\LDSDR_010\_cap_%s.bin" % tag
    sh("iio_readdev -s 131072 cf-ad9361-lpc voltage0 voltage1 > /tmp/c.bin 2>/dev/null", timeout=120)
    sh("cat /tmp/c.bin", binary_to=p, timeout=200)
    raw = np.fromfile(p, dtype=np.int16)
    I, Q = raw[0::2].astype(float), raw[1::2].astype(float)
    K = min(len(I)//N, 32)
    win = np.hanning(N)
    def psd(x):
        a = np.zeros(N)
        for k in range(K):
            a += np.abs(np.fft.fftshift(np.fft.fft(x[k*N:(k+1)*N]*win)))**2
        return 10*np.log10(a/K/(N*N)+1e-20)
    pC = psd(I+1j*Q)
    f = (np.arange(N)-N/2)*(fs/N)
    # 只看正频半边，排除对称镜像
    half = pC[N//2:]
    fh = f[N//2:]
    noise = np.median(half)
    i = int(half.argmax())
    # 找所有超过 噪声底+10dB 的峰
    thr = noise + 10
    peaks = []
    k = 1
    while k < len(half)-1:
        if half[k] > thr and half[k] >= half[k-1] and half[k] >= half[k+1]:
            peaks.append((fh[k], half[k]-noise))
            k += 20
        k += 1
    print("  fs=%7.0f  gain=%-6s I.std=%5.2f Q.std=%5.2f  底%6.1f  峰: %s"
          % (fs, g.replace(" dB", ""), I.std(), Q.std(), noise,
             ", ".join("%.1fkHz(%+.0fdB)" % (p/1e3, s) for p, s in peaks[:4]) or "无"))
    return fs, peaks


print("=== 采样率扫描：伪影频率跟不跟着变？ ===")
res = []
for fs in (4000000, 2000000, 1000000, 8000000):
    res.append(capture(fs, 40, "fs%d" % fs))

print("\n=== 判定 ===")
for fs, peaks in res:
    if peaks:
        p0 = peaks[0][0]
        print("  fs=%.1f MHz -> 最强峰 %.1f kHz  (占 fs 的 %.4f)" % (fs/1e6, p0/1e3, p0/fs))
print("  >>> 若「占 fs 的比例」基本恒定 -> 数字伪影；若绝对频率恒定 -> 真实信号")

print("\n=== 增益扫描（4 MSPS）：看是不是内部耦合 ===")
for g in (0, 20, 40, 60):
    capture(4000000, g, "g%d" % g)
