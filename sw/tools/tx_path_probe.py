#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tx_path_probe.py -- 判定遥测板的 TX 缓冲通路到底出不出信号

对照关系：
  A) DDS 出单音                    -> 之前测过，RX RMS 18.6，峰/底噪 54.8 dB  ✓ 通
  B) iio_writedev 缓冲区出单音     -> 本脚本测，看是否也能收到

如果 A 通而 B 不通，说明问题在 iio_writedev / 缓冲区，不在射频。
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
FP = None


def hostkey():
    r = subprocess.run([PLINK, "-ssh", "-batch", "-pw", PW, BOARD, "echo P"],
                       capture_output=True)
    m = re.search(r"SHA256:[A-Za-z0-9+/=]+",
                  (r.stdout + r.stderr).decode("utf-8", "replace"))
    return m.group(0) if m else None


def sh(cmd, timeout=240, show=False):
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


def scp(local, remote, download=False):
    args = [PSCP, "-batch", "-scp"]
    if FP:
        args += ["-hostkey", FP]
    args += ["-pw", PW]
    args += ["%s:%s" % (BOARD, remote), local] if download else [local, "%s:%s" % (BOARD, remote)]
    r = subprocess.run(args, capture_output=True, timeout=300)
    if r.returncode != 0:
        print("    ! scp: %s" % ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace")[:200])
    return r.returncode == 0


def main():
    global FP
    ap = argparse.ArgumentParser()
    ap.add_argument("--fs", type=float, default=30_720_000.0)
    ap.add_argument("--tone", type=float, default=1_000_000.0)
    ap.add_argument("--txatt", type=int, default=40)
    ap.add_argument("--rxgain", type=int, default=30)
    ap.add_argument("--nsamp", type=int, default=3_456_320)
    ap.add_argument("--cap", type=int, default=262_144)
    a = ap.parse_args()

    FP = hostkey()
    print("  主机密钥: %s" % FP)
    if not FP:
        return 1

    print("\n-- 生成缓冲区单音 (%.2f MSPS, %.0f Hz, %d 样点) --" % (a.fs / 1e6, a.tone, a.nsamp))
    t = np.arange(a.nsamp) / a.fs
    z = 0.6 * np.exp(2j * np.pi * a.tone * t)
    iq = np.empty(2 * a.nsamp, dtype=np.int16)
    iq[0::2] = np.round(z.real * 32767).astype(np.int16)
    iq[1::2] = np.round(z.imag * 32767).astype(np.int16)
    wf = os.path.join(OUT, "probe_wave.bin")
    iq.tofile(wf)
    print("  %s (%d B = %.1f s)" % (wf, os.path.getsize(wf), a.nsamp / a.fs))

    if not scp(wf, "/tmp/probe_wave.bin"):
        return 1

    print("\n-- 配置（DDS 全部关掉）--")
    for c in [
        "iio_attr -u ip:localhost -c ad9361-phy voltage0 sampling_frequency %d" % int(a.fs),
        "iio_attr -u ip:localhost -c ad9361-phy voltage0 rf_bandwidth 18000000",
        "iio_attr -u ip:localhost -c ad9361-phy voltage1 rf_bandwidth 18000000",
        "iio_attr -u ip:localhost -c ad9361-phy altvoltage0 frequency 2400000000",
        "iio_attr -u ip:localhost -c ad9361-phy altvoltage1 frequency 2400000000",
        "iio_attr -u ip:localhost -i -c ad9361-phy voltage0 gain_control_mode manual",
        "iio_attr -u ip:localhost -i -c ad9361-phy voltage0 hardwaregain %d" % a.rxgain,
        "iio_attr -u ip:localhost -i -c ad9361-phy voltage1 gain_control_mode manual",
        "iio_attr -u ip:localhost -i -c ad9361-phy voltage1 hardwaregain %d" % a.rxgain,
        "iio_attr -u ip:localhost -o -c ad9361-phy voltage1 hardwaregain -%d" % a.txatt,
        "iio_attr -u ip:localhost -c cf-ad9361-dds-core-lpc altvoltage0 scale 0",
        "iio_attr -u ip:localhost -c cf-ad9361-dds-core-lpc altvoltage1 scale 0",
        "iio_attr -u ip:localhost -c cf-ad9361-dds-core-lpc altvoltage2 scale 0",
        "iio_attr -u ip:localhost -c cf-ad9361-dds-core-lpc altvoltage3 scale 0",
    ]:
        sh(c)
    print("  RX 采样率 = %s" % sh("iio_attr -u ip:localhost -c ad9361-phy voltage0 sampling_frequency"))
    print("  TX 衰减   = %s" % sh("iio_attr -u ip:localhost -o -c ad9361-phy voltage1 hardwaregain"))

    print("\n-- 发射（文件重定向）+ 立刻抓 --")
    sh("killall -9 iio_writedev 2>/dev/null; echo ok")
    sh("cd /tmp && nohup iio_writedev -u ip:localhost -s %d -b 65536 "
       "cf-ad9361-dds-core-lpc voltage0 voltage1 < /tmp/probe_wave.bin "
       ">/tmp/probe_tx.log 2>&1 & echo TX_STARTED" % a.nsamp)
    time.sleep(0.25)
    print("  发射进程数 = %s" % sh("ps | grep '[i]io_writedev' | wc -l"))
    sh("iio_readdev -u ip:localhost -b 65536 -s %d cf-ad9361-lpc voltage0 voltage1 "
       "> /tmp/probe_cap.bin" % (2 * a.cap), timeout=240)
    sh("killall -9 iio_writedev 2>/dev/null; echo TX_STOPPED")
    print("  tx.log: %s" % (sh("cat /tmp/probe_tx.log 2>/dev/null | head -3") or "(空)"))

    cb = os.path.join(OUT, "probe_cap.bin")
    if not scp(cb, "/tmp/probe_cap.bin", download=True):
        return 1

    raw = np.fromfile(cb, dtype=np.int16)
    I = raw[0::2].astype(float)
    Q = raw[1::2].astype(float)
    z = I + 1j * Q
    print("\n-- 分析 --")
    print("  %d 样点  RMS=%.1f  I[%d,%d] Q[%d,%d]"
          % (len(z), np.sqrt(np.mean(np.abs(z) ** 2)), I.min(), I.max(), Q.min(), Q.max()))
    nfft = 8192
    k = max(1, min(len(z) // nfft, 16))
    w = np.hanning(nfft)
    acc = np.zeros(nfft)
    for i in range(k):
        acc += np.abs(np.fft.fftshift(np.fft.fft(z[i * nfft:(i + 1) * nfft] * w))) ** 2
    P = 10 * np.log10(acc / k + 1e-30)
    f = (np.arange(nfft) - nfft // 2) * (a.fs / nfft)
    pk = int(np.argmax(P))
    print("  峰值 %.0f Hz (%.1f dB)  底噪 %.1f dB  峰/底 %.1f dB   —— 期望 %.0f Hz"
          % (f[pk], P[pk], np.median(P), P[pk] - np.median(P), a.tone))
    ok = (P[pk] - np.median(P)) > 10 and abs(f[pk] - a.tone) < max(50e3, a.fs / nfft * 3)
    print("\n  %s" % ("★★★ 缓冲区发射通路正常 ★★★" if ok
                      else "✗ 缓冲区发射没出信号"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
