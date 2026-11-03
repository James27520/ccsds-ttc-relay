import sys

import numpy as np

sys.path.insert(0, r"E:\LDSDR_010\ttc_ccsds")
import ccsds_tm_tx as CC
import loopback_test as LT

payload = bytes(range(1, 33))
frame = CC.build_tm_frame(scid=0x2A, vcid=0, mcfc=7, vcfc=3, data=payload)
cadu, _ = CC.build_cadu(frame)
I, Q = CC.cadu_to_iq(cadu, fs=LT.FS, sym_rate=LT.SYM, if_hz=LT.IF, amp=0.6)

print("接收链验证（用发射波形自喂，逐步加噪）")
print("参考: SCID=0x2A MCFC=7 payload=%s" % payload[:4].hex())
print()

rng = np.random.default_rng(7)
for snr in (40, 30, 25, 20, 18, 15, 12, 10):
    s = float(I.std())
    n = s / (10 ** (snr / 20.0))
    In = np.clip(I + rng.normal(0, n, len(I)), -32768, 32767).astype(np.int16)
    Qn = np.clip(Q + rng.normal(0, n, len(Q)), -32768, 32767).astype(np.int16)
    bits, pos, err, inf = LT.decode_capture(In, Qn, verbose=False)
    fr, fi = LT.try_full_decode(bits, pos)
    ok = bool(fr)
    ex = ""
    if fr:
        p = fr[0][1]
        ex = " SCID=0x%X MCFC=%d 内容一致=%s" % (
            p["scid"], p["mcfc"], p["payload"] == payload)
    print("  SNR %2d dB: 相位=%d  ASM@%-5s 错%-2d  帧=%-2d %s%s"
          % (snr, inf["phase"], pos, err, fi.get("frames_found", 0),
             "✅" if ok else "❌", ex))
