import sys

import numpy as np

sys.path.insert(0, r"E:\LDSDR_010\ttc_ccsds")
import ccsds_tm_tx as CC

FS, SYM, IF = 2_500_000, 250_000, 200_000
SPS = FS // SYM

payload = bytes(range(1, 33))
frame = CC.build_tm_frame(scid=0x2A, vcid=0, mcfc=7, vcfc=3, data=payload)
cadu, _ = CC.build_cadu(frame)
print("CADU 比特数 = %d   ASM 前 32 位应等于 1acffc1d" % len(cadu))
print("  实际前 32 位: %s" % "".join(str(b) for b in cadu[:32]))

# ---- 发射 ----
I, Q = CC.cadu_to_iq(cadu, fs=FS, sym_rate=SYM, if_hz=IF, amp=0.6)
iq = I.astype(float) + 1j * Q.astype(float)
print("\n发射波形 %d 样点" % len(iq))

# ---- 接收：下变频 ----
t = np.arange(len(iq)) / FS
bb = iq * np.exp(-1j * 2 * np.pi * IF * t)

# 看一眼下变频后的星座（应该是实轴上的 BPSK）
print("\n下变频后（未匹配滤波）抽取每符号中点：")
for ph in range(0, SPS, 3):
    s = bb[ph::SPS][20:28]
    print("  相位%d: %s" % (ph, " ".join("%+7.0f" % v.real for v in s)))

# ---- 匹配滤波 ----
h = CC.srrc(0.35, SPS, span=8)
mf = np.convolve(bb, h, mode="same")
print("\n匹配滤波后：")
for ph in range(SPS):
    s = mf[ph::SPS]
    # 用后半段（避开卷积边缘）
    ss = s[len(s) // 4: 3 * len(s) // 4]
    conf = float(np.mean(np.abs(ss.real)))
    bits = (ss.real < 0).astype(np.uint8)
    asm = CC.bytes_to_bits(b"C\xff\xc1\x1d")
    best = 99
    for i in range(0, min(len(bits) - 32, 60)):
        e = int(np.sum(bits[i:i + 32] != asm))
        best = min(best, e)
    print("  相位%2d: 平均|实部|=%7.1f  最小ASM错=%2d %s"
          % (ph, conf, best, "★" if best <= 2 else ""))

# ---- 直接问：把 CADU 比特直接按 sps 上采样，能不能自洽地取回来 ----
print("\n[对照] 不做上变频/滤波，直接检查映射与抽取：")
sym = np.where(cadu == 0, 1.0, -1.0)
bits_back = (sym < 0).astype(np.uint8)
print("  直接映射回比特一致: %s" % bool(np.array_equal(bits_back, cadu)))
