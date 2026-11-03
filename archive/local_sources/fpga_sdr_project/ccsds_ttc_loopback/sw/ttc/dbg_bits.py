import sys

import numpy as np

sys.path.insert(0, r"E:\LDSDR_010\ttc_ccsds")
import ccsds_tm_tx as CC

FS, SYM, IF = 2_500_000, 250_000, 200_000
SPS = FS // SYM

payload = bytes(range(1, 33))
frame = CC.build_tm_frame(scid=0x2A, vcid=0, mcfc=7, vcfc=3, data=payload)
cadu, _ = CC.build_cadu(frame)

I, Q = CC.cadu_to_iq(cadu, fs=FS, sym_rate=SYM, if_hz=IF, amp=0.6)
iq = I.astype(float) + 1j * Q.astype(float)

t = np.arange(len(iq)) / FS
bb = iq * np.exp(-1j * 2 * np.pi * IF * t)
h = CC.srrc(0.35, SPS, span=8)
mf = np.convolve(bb, h, mode="same")

sym = mf[0::SPS]
bits = (sym.real < 0).astype(np.uint8)

exp = cadu
print("发射 CADU 前 48 bit:")
print("  " + "".join(str(b) for b in exp[:48]))
print("接收比特 前 48:")
print("  " + "".join(str(b) for b in bits[:48]))
print()

# 逐位置找最佳对齐
best = (99, -1, 0)
for shift in range(0, 24):
    n = min(len(exp), len(bits) - shift)
    e = int(np.sum(bits[shift:shift + n] != exp[:n]))
    if e < best[0]:
        best = (e, shift, n)
print("全局最佳对齐: 接收[%d:] vs 发射[0:]，错 %d / %d bit  (%.1f%%)"
      % (best[1], best[0], best[2], 100.0 * best[0] / best[2]))

e, sh, n = best
print("\n对齐后对比（前 48 bit）:")
print("  发射: " + "".join(str(b) for b in exp[:48]))
print("  接收: " + "".join(str(b) for b in bits[sh:sh + 48]))
print("  差异: " + "".join("^" if a != b else " "
                          for a, b in zip(exp[:48], bits[sh:sh + 48])))

# 用最佳对齐做 ASM
print("\n用对齐偏移 %d 找 ASM:" % sh)
fr, fi = __import__("loopback_test").try_full_decode(bits, sh)
print("  解出帧数 = %d" % fi.get("frames_found", 0))
if fr:
    for off, p in fr[:3]:
        print("  ✅ 帧@%d SCID=0x%X MCFC=%d CRC=OK payload一致=%s"
              % (off, p["scid"], p["mcfc"], p["payload"] == payload))
