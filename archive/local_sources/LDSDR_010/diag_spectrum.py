#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断新板 IQ 的对称峰异常"""
import numpy as np

IQ = r"E:\LDSDR_010\iq_new_board.bin"
raw = np.fromfile(IQ, dtype=np.int16)
n = len(raw) // 2
I = raw[0::2].astype(np.float64)
Q = raw[1::2].astype(np.float64)
print("样点 %d  I[:8]=%s  Q[:8]=%s" % (n, I[:8].astype(int), Q[:8].astype(int)))
print("I: mean %+.3f  std %.3f   Q: mean %+.3f  std %.3f"
      % (I.mean(), I.std(), Q.mean(), Q.std()))
print("相关系数 corr(I,Q) = %+.4f" % np.corrcoef(I, Q)[0, 1])
print("I 的直方图（前 12 个值）:")
u, c = np.unique(I, return_counts=True)
for v, k in list(zip(u, c))[:12]:
    print("    %6d : %d" % (v, k))
print("Q 的直方图（前 12 个值）:")
u, c = np.unique(Q, return_counts=True)
for v, k in list(zip(u, c))[:12]:
    print("    %6d : %d" % (v, k))

N = 4096
K = min(len(I) // N, 64)
win = np.hanning(N)
def psd(x):
    a = np.zeros(N)
    for k in range(K):
        seg = x[k*N:(k+1)*N] * win
        a += np.abs(np.fft.fftshift(np.fft.fft(seg)))**2
    return 10*np.log10(a/K/(N*N) + 1e-20)

pI = psd(I); pQ = psd(Q); pC = psd(I + 1j*Q)
fs = 4000000.0; rbw = fs/N
f = (np.arange(N) - N/2)*rbw/1e3     # kHz
def peak(p, name):
    i = int(p.argmax())
    print("  %-14s 峰 %+9.1f kHz (%7.1f dB)   底 %6.1f dB   差 %5.1f dB"
          % (name, f[i], p[i], np.median(p), p[i]-np.median(p)))
print("\n三种谱对比:")
peak(pI, "I 单独")
peak(pQ, "Q 单独")
peak(pC, "复数 I+jQ")

# 对称性检验：pC[k] 与 pC[N-1-k] 的差
sym = np.abs(pC - pC[::-1])
print("\n复数谱的镜像不对称度: 均值 %.2f dB  最大 %.2f dB" % (sym.mean(), sym.max()))
print("  （复数信号的谱不该对称；对称说明信号是实数）")

# 时域周期
seg = I[:N]
ac = np.correlate(seg - seg.mean(), seg - seg.mean(), 'full')[N-1:]
ac /= ac[0]
pk = 5 + int(np.argmax(ac[5:200]))
print("\nI 自相关第一个次峰在 lag=%d 样点 -> %.1f kHz（fs=%.0f MHz 时为 %.3f MHz）"
      % (pk, fs/pk/1e3, fs/1e6, fs/pk/1e6))
