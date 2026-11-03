#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_decode.py -- 带自动频偏搜索的接收端

为什么需要它
------------
  loopback_test.py 的接收端硬编码"信号在 +200 kHz"。
  实测频谱峰值在 -153 kHz，硬编码的频率就错了，下变频之后不是干净的 BPSK，
  自然解不出帧。

  真实接收机也要做这件事（载波恢复）。这里用最直接的办法：
  在 ±500 kHz 上扫频偏，每个频偏都试一遍解码，取 CRC 通过的那个。

用法
----
    python auto_decode.py                 # 解码 cap.bin
    python auto_decode.py cap2.bin
    python auto_decode.py --sweep         # 只打印频谱，不解码
"""
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ccsds_tm_tx as CC

G = "\033[32m"; R = "\033[31m"; Y = "\033[33m"; C = "\033[36m"
B = "\033[1m"; D = "\033[2m"; N = "\033[0m"

FS, SYM = 2_500_000, 250_000
SPS = FS // SYM
ASM_BITS = CC.bytes_to_bits(struct.pack(">I", CC.ASM))


def spectrum(I, Q, nfft=4096, navg=32):
    K = min(len(I) // nfft, navg)
    w = np.hanning(nfft)
    acc = np.zeros(nfft)
    for k in range(K):
        s = (I[k * nfft:(k + 1) * nfft] + 1j * Q[k * nfft:(k + 1) * nfft]) * w
        acc += np.abs(np.fft.fftshift(np.fft.fft(s))) ** 2
    P = 10 * np.log10(acc / max(K, 1) + 1e-20)
    f = (np.arange(nfft) - nfft // 2) * (FS / float(nfft))
    return f, P


def rx_at(iq, f_off, h):
    """在给定频偏上下变频 + 匹配滤波，返回最佳相位的比特流"""
    n = len(iq)
    t = np.arange(n) / FS
    bb = iq * np.exp(-1j * 2 * np.pi * f_off * t)
    mf = np.convolve(bb, h, mode="same")
    best = None
    for ph in range(SPS):
        sym = mf[ph::SPS]
        conf = float(np.sum(np.abs(sym.real)))
        if best is None or conf > best[0]:
            best = (conf, ph, (sym.real < 0).astype(np.uint8))
    return best[2], best[1], best[0]


def find_asm(bits):
    n = len(bits)
    if n < 32:
        return -1, 99
    best, bi = 99, -1
    for i in range(0, n - 32):
        e = int(np.sum(bits[i:i + 32] != ASM_BITS))
        if e < best:
            best, bi = e, i
            if e == 0:
                break
    return bi, best


def decode_at(bits, asm_pos):
    """ASM 之后 -> Viterbi -> 解随机化 -> 找 CRC 正确的帧"""
    if asm_pos < 0:
        return []
    enc = bits[asm_pos + 32:]
    n = (len(enc) // 2) * 2
    if n < 128:
        return []
    dec = CC.conv_decode_viterbi(enc[:n])
    der = CC.derandomize(dec)
    frame = CC.bits_to_bytes(der)
    out = []
    for L in (108, 40):                 # 两种可能的帧长
        off = 0
        while off + L <= len(frame) and len(out) < 8:
            p = CC.parse_tm_frame(frame[off:off + L])
            if p and p["crc_ok"]:
                out.append((off, L, p))
                off += L
            else:
                off += 1
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sweep_only = "--sweep" in sys.argv
    path = args[0] if args else os.path.join(HERE, "cap.bin")

    raw = np.fromfile(path, dtype=np.int16)
    I = raw[0::2].astype(float)
    Q = raw[1::2].astype(float)
    print("%s═══ 自动频偏搜索解码 ═══%s" % (B, N))
    print("  %s  (%d 样点, I.std=%.1f)" % (os.path.basename(path), len(I), I.std()))

    f, P = spectrum(I, Q)
    pk = int(P.argmax())
    # 找前 5 个局部峰
    order = np.argsort(P)[::-1]
    seen, peaks = [], []
    for i in order:
        if all(abs(f[i] - f[j]) > 60e3 for j in seen):
            seen.append(i); peaks.append((f[i], P[i]))
        if len(peaks) >= 5:
            break
    print("\n  频谱主要峰（前 5）:")
    for ff, pp in peaks:
        print("    %+9.1f kHz   %6.1f dB   (底噪 %.1f dB, SNR %5.1f dB)"
              % (ff / 1e3, pp, np.median(P), pp - np.median(P)))
    if sweep_only:
        return 0

    iq = I + 1j * Q
    iq = iq - iq.mean()
    h = CC.srrc(0.35, SPS, span=8)

    print("\n  扫描频偏（步进 10 kHz，范围 ±600 kHz）:")
    best = None
    for off_khz in range(-600, 601, 10):
        bits, ph, conf = rx_at(iq, off_khz * 1e3, h)
        pos, err = find_asm(bits)
        frames = decode_at(bits, pos) if err <= 2 else []
        if frames:
            print("    %+6d kHz: 相位=%d ASM错=%d  帧=%d  %s"
                  % (off_khz, ph, err, len(frames), "★"))
            if best is None or len(frames) > len(best[2]):
                best = (off_khz, ph, frames)
        elif err <= 2:
            print("    %+6d kHz: 相位=%d ASM错=%d  帧=0" % (off_khz, ph, err))

    print()
    if best:
        off, ph, frames = best
        print("%s✅ 用频偏 %+d kHz 解出 %d 个帧%s" % (G + B, off, len(frames), N))
        for o, L, p in frames:
            print("   帧@%-5d len=%-4d SCID=0x%X VCID=%d MCFC=%3d VCFC=%3d CRC=OK payload=%s..."
                  % (o, L, p["scid"], p["vcid"], p["mcfc"], p["vcfc"], p["payload"][:4].hex()))
        print("\n%s═══ 双板环回验证通过 ═══%s" % (G + B, N))
        print("  遥测板 TX → 转发板 RX/TX → 遥测板 RX → CCSDS 解码 → CRC 校验")
        print("  这是真实射频链路上的端到端验证。")
    else:
        print("%s❌ 没解出帧%s" % (R, N))
        print("""
  频谱里有信号（前面峰值 SNR 很高），但解不出来。按可能性排：
    1) 电平不合适 —— 转发板 txatt 从 60 降到 40 试试
    2) 信号不是我们发的那个 —— 那个强峰可能是转发板的杂散/本振泄漏
       如果是这样，需要提高有用信号电平让它盖过杂散
    3) 转发板 rxgain 太低（现在 5）—— 提到 10 试试
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
