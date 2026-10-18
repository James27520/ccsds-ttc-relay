#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
board_loopback_test.py -- 遥测板 TX->RX (SMA 环回) 通路测试

目的：验证「模式 B（经板子 USB/IIO）」的硬件通路是否可用。
      不需要我们自己的 FPGA 位流 —— 用原厂固件 + libiio 即可。

流程：
  1) 本地生成测试 IQ（复数单音，30.72 MSPS，int16 交织）
  2) pscp 传到板子 /tmp/wave.bin
  3) 板子上后台发射（有界循环喂 iio_writedev）
  4) 板子上 iio_readdev 抓一段回来
  5) pscp 取回 /tmp/rx.bin，本地 FFT 分析：单音是否出现在预期频点
  6) 清理板子上的后台进程

用法:
  python board_loopback_test.py            # 默认 -40 dB TX 衰减, RX 手动 30 dB
  python board_loopback_test.py --txatt 60 --rxgain 40
"""
import argparse
import os
import subprocess
import sys
import time

import numpy as np

PLINK = r"D:\PuTTY\plink.exe"
PSCP = r"D:\PuTTY\pscp.exe"
BOARD = "root@192.168.2.1"
PW = "analog"

FS = 30_720_000.0
N = 61440                     # 2 ms
TONE_HZ = 1_000_000.0         # 环回单音频点
AMP = 0.5

LOCAL = r"E:\ccsds_fpga\out"
WAVE = os.path.join(LOCAL, "lb_wave.bin")
RXB = os.path.join(LOCAL, "lb_rx.bin")


def hostkey():
    """板子每次重启都重新生成主机密钥，所以每次现抓"""
    r = subprocess.run([PLINK, "-ssh", "-batch", "-pw", PW, BOARD, "echo P"],
                       capture_output=True)
    txt = (r.stdout + r.stderr).decode("utf-8", "replace")
    import re
    m = re.search(r"SHA256:[A-Za-z0-9+/=]+", txt)
    return m.group(0) if m else None


FP = None


def sh(cmd, timeout=120, quiet=False):
    global FP
    args = [PLINK, "-ssh", "-batch"]
    if FP:
        args += ["-hostkey", FP]
    args += ["-pw", PW, BOARD, cmd]
    r = subprocess.run(args, capture_output=True, timeout=timeout)
    out = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace").strip()
    if not quiet and out:
        for line in out.splitlines():
            print("    | %s" % line[:150])
    return out


def push(local, remote):
    args = [PSCP, "-batch", "-scp"]
    if FP:
        args += ["-hostkey", FP]
    args += ["-pw", PW, local, "%s:%s" % (BOARD, remote)]
    r = subprocess.run(args, capture_output=True, timeout=180)
    out = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace").strip()
    if r.returncode != 0:
        print("    ! pscp 上传失败: %s" % out[:300])
    return r.returncode == 0


def pull(remote, local):
    args = [PSCP, "-batch", "-scp"]
    if FP:
        args += ["-hostkey", FP]
    args += ["-pw", PW, "%s:%s" % (BOARD, remote), local]
    r = subprocess.run(args, capture_output=True, timeout=180)
    if r.returncode != 0:
        out = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace")
        print("    ! pscp 下载失败: %s" % out[:300])
    return r.returncode == 0


def main():
    global FP
    ap = argparse.ArgumentParser()
    ap.add_argument("--txatt", type=int, default=40, help="TX 衰减 dB (正数, 越大越安全)")
    ap.add_argument("--rxgain", type=int, default=30, help="RX 手动增益 dB")
    ap.add_argument("--tone", type=float, default=TONE_HZ)
    a = ap.parse_args()

    print("=" * 74)
    print("  遥测板 TX->RX 环回通路测试")
    print("=" * 74)

    FP = hostkey()
    print("  主机密钥: %s" % FP)
    if not FP:
        print("  [!] 抓不到主机密钥，板子可能没在线")
        return 1

    print("\n-- 1) 生成测试 IQ --")
    t = np.arange(N) / FS
    z = AMP * np.exp(2j * np.pi * a.tone * t)
    iq = np.empty(2 * N, dtype=np.int16)
    iq[0::2] = np.round(z.real * 32767).astype(np.int16)
    iq[1::2] = np.round(z.imag * 32767).astype(np.int16)
    iq.tofile(WAVE)
    print("  %s  (%d B, %d 样点, 单音 %.0f Hz)" % (WAVE, os.path.getsize(WAVE), N, a.tone))

    print("\n-- 2) 传到板子 --")
    if not push(WAVE, "/tmp/wave.bin"):
        return 1
    sh("ls -l /tmp/wave.bin")

    print("\n-- 3) 配置 AD9361 --")
    conf = [
        "iio_attr -u ip:localhost -c ad9361-phy voltage0 sampling_frequency 30720000",
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
    ]
    for c in conf:
        sh(c, quiet=True)
    for k, c in (("RX gain", "-i -c ad9361-phy voltage0 hardwaregain"),
                 ("TX att ", "-o -c ad9361-phy voltage1 hardwaregain"),
                 ("RX LO  ", "-c ad9361-phy altvoltage0 frequency"),
                 ("TX LO  ", "-c ad9361-phy altvoltage1 frequency")):
        print("  %s = %s" % (k, sh("iio_attr -u ip:localhost %s" % c, quiet=True)))

    print("\n-- 4) 清理旧进程 --")
    sh("killall -9 iio_writedev 2>/dev/null; echo cleaned")

    print("\n-- 5) 后台发射（有界循环，避免管道挂住）--")
    passes = 40
    inner = ("nohup sh -c 'for i in $(seq 1 %d); do cat /tmp/wave.bin; done | "
             "iio_writedev -u ip:localhost -s %d -b 65536 "
             "cf-ad9361-dds-core-lpc voltage0 voltage1' >/tmp/tx.log 2>&1 & echo TX_STARTED"
             % (passes, N))
    sh(inner)
    time.sleep(1.5)
    print("  发射进程数: %s" % sh("ps | grep '[i]io_writedev' | wc -l", quiet=True))

    print("\n-- 6) 抓接收数据 --")
    sh("iio_readdev -u ip:localhost -b 65536 -s %d cf-ad9361-lpc voltage0 voltage1 "
       "> /tmp/rx.bin" % (2 * N), timeout=120)
    sh("ls -l /tmp/rx.bin")

    print("\n-- 7) 停止发射并取回数据 --")
    sh("killall -9 iio_writedev 2>/dev/null; echo stopped")
    if not pull("/tmp/rx.bin", RXB):
        return 1

    print("\n-- 8) 分析 --")
    raw = np.fromfile(RXB, dtype=np.int16)
    print("  取回 %d 个 int16 = %d 个复数样点" % (len(raw), len(raw) // 2))
    if len(raw) < 4096:
        print("  [!] 数据太少")
        return 1
    I = raw[0::2].astype(float)
    Q = raw[1::2].astype(float)
    z = I + 1j * Q
    print("  I/Q 范围: I [%d, %d]  Q [%d, %d]" % (I.min(), I.max(), Q.min(), Q.max()))
    print("  RMS = %.1f  (满量程 32768)" % np.sqrt(np.mean(np.abs(z) ** 2)))

    nfft = 8192
    k = min(len(z) // nfft, 16)
    w = np.hanning(nfft)
    acc = np.zeros(nfft)
    for i in range(k):
        s = z[i * nfft:(i + 1) * nfft] * w
        acc += np.abs(np.fft.fftshift(np.fft.fft(s))) ** 2
    P = 10 * np.log10(acc / max(k, 1) + 1e-30)
    f = (np.arange(nfft) - nfft // 2) * (FS / nfft)
    pk = int(np.argmax(P))
    print("  频谱峰值: %.0f Hz  (%.1f dB)   —— 期望 %.0f Hz" % (f[pk], P[pk], a.tone))
    print("  底噪(中位): %.1f dB   峰值/底噪 = %.1f dB"
          % (np.median(P), P[pk] - np.median(P)))
    ok = abs(f[pk] - a.tone) < 100_000 and (P[pk] - np.median(P)) > 10
    print("\n  %s" % ("★★★ 环回通路正常！TX 发的单音在 RX 收到了 ★★★" if ok
                      else "✗ 没收到 —— 检查 SMA 环回线是否接在 TX1A->RX1A"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
