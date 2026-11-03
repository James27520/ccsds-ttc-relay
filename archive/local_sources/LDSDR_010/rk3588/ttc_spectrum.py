#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ttc_spectrum.py -- 在 3588 上运行：抓遥测板 RX 的 IQ，算频谱，发给电脑

策略：抓 4 个通道，逐个算实数谱，自动选信噪比最好的那个显示。
      （这块板子的通道布局不完全符合 [I,Q] 假设，用单通道实数谱最稳妥无歧义）

输出格式（每帧一行）：
  SPEC|<fs>|<rbw>|<峰值kHz>|<底dBFS>|<峰dBFS>|<通道号>|<4个std,逗号分隔>|<base64 1024×uint8>
"""
import base64
import os
import subprocess
import sys
import time

import numpy as np

URI = "usb:"
RX_LO = 1000_000_000
FS = 2_500_000
N_FFT = 4096
N_CH = 4
N_AVG = 16
N_SAMP = N_FFT * N_AVG
FS_AMP = 2048.0
CAP = "/tmp/ttc_spec.bin"


def sh(cmd, timeout=60):
    r = subprocess.run(cmd, shell=True, capture_output=True, timeout=timeout)
    return (r.stdout or b"").decode("utf-8", "replace").strip()


def cfg(gain):
    for c in [
        "iio_attr -u %s -c ad9361-phy altvoltage0 frequency %d" % (URI, RX_LO),
        "iio_attr -u %s -c ad9361-phy voltage0 sampling_frequency %d" % (URI, FS),
        "iio_attr -u %s -c ad9361-phy voltage0 rf_bandwidth 1000000" % URI,
        "iio_attr -u %s -i -c ad9361-phy voltage0 gain_control_mode manual" % URI,
        "iio_attr -u %s -i -c ad9361-phy voltage0 hardwaregain %d" % (URI, gain),
        "iio_attr -u %s -i -c ad9361-phy voltage1 gain_control_mode manual" % URI,
        "iio_attr -u %s -i -c ad9361-phy voltage1 hardwaregain %d" % (URI, gain),
    ]:
        sh(c, timeout=40)


def main():
    frames = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    gain = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    cfg(gain)

    win = np.hanning(N_FFT)
    norm = (FS_AMP * win.sum() / 2.0) ** 2
    f = (np.arange(N_FFT) - N_FFT / 2) * (FS / N_FFT)

    k = 0
    while frames == 0 or k < frames:
        k += 1
        t0 = time.time()
        sh("rm -f %s; timeout 30 iio_readdev -u %s -s %d -b %d cf-ad9361-lpc "
           "voltage0 voltage1 voltage2 voltage3 > %s 2>/dev/null"
           % (CAP, URI, N_SAMP, N_FFT * 4, CAP), timeout=60)

        if not os.path.exists(CAP) or os.path.getsize(CAP) < N_SAMP * 8:
            print("SPEC|%d|0|0|0|0|-1|-|" % FS)
            sys.stdout.flush()
            time.sleep(0.3)
            continue

        raw = np.fromfile(CAP, dtype=np.int16)
        chs = [raw[i::N_CH].astype(np.float64) for i in range(N_CH)]
        stds = [float(c.std()) for c in chs]

        best = None
        for ci, c in enumerate(chs):
            K = len(c) // N_FFT
            if K < 1:
                continue
            acc = np.zeros(N_FFT)
            for j in range(K):
                acc += np.abs(np.fft.fftshift(np.fft.fft(c[j*N_FFT:(j+1)*N_FFT] * win)))**2
            psd = 10.0 * np.log10(acc / K / norm + 1e-20)
            nb = float(np.median(psd))
            pi = int(psd.argmax())
            snr = float(psd[pi]) - nb
            if best is None or snr > best[0]:
                best = (snr, ci, psd, nb, float(psd[pi]), float(f[pi] / 1e3))

        snr, ci, psd, noise, peak_db, peak_khz = best
        v = np.maximum.reduceat(psd, np.arange(0, N_FFT, N_FFT // 1024))
        b = np.clip(np.round(v + 128.0), 0, 255).astype(np.uint8)
        b64 = base64.b64encode(b.tobytes()).decode("ascii")
        print("SPEC|%d|%.0f|%.2f|%.1f|%.1f|%d|%s|%s"
              % (FS, FS / N_FFT, peak_khz, noise, peak_db, ci,
                 ",".join("%.0f" % s for s in stds), b64))
        sys.stdout.flush()
        dt = time.time() - t0
        if dt < 0.08:
            time.sleep(0.08 - dt)


if __name__ == "__main__":
    main()
