#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ccsds_tm_tx.py -- CCSDS 遥测下行发射链（软件版 / 阶段 A）

依据 CCSDS 131.0-B（TM 同步与信道编码）与 132.0-B（TM 空间数据链路协议）。

发射链顺序（★ 这是最容易搞错的地方）
------------------------------------
    TM 传输帧 (132.0-B)
        ↓  可选 Reed-Solomon (255,223)
        ↓  ★ 伪随机化       （ASM 不参与随机化）
        ↓  ★ 卷积编码 (7,1/2)
        ↓  ★ 插入 ASM 0x1ACFFC1D
        ↓  符号映射
        ↓  SRRC 成形
      I/Q 样点

三个关键细节
------------
1. ASM 在随机化【之后】插入 —— 所以 ASM 本身不被随机化
   （euryspace 的 asm_encoder.vhd 注释 "add asm stream after pseudo randomization"）
2. 随机化 LFSR: h(x)=x^8+x^7+x^5+x^3+1，初值全 1 (0xFF)
   （euryspace ccsds_rxtx_lfsr.vhd: POLYNOMIAL=0xA9, SEED=0xFF）
3. 卷积编码 G1=0o171(0x79)、G2=0o133(0x5B)，第二路输出取反
   （euryspace ccsds_tx_coder_convolutional.vhd:
     CONNEXION_VECTORS=("1111001","1011011"), OUTPUT_INVERSION=(false,true)）

自检
----
本文件带一个软件环回自检：编码 → 解码 → 比对，不需要任何硬件。
    python ccsds_tm_tx.py selftest
"""
import struct
import sys

import numpy as np

# =====================================================================
#  常量
# =====================================================================
ASM = 0x1ACFFC1D                      # 附同步标记

# 随机化：h(x) = x^8 + x^7 + x^5 + x^3 + 1
#
# 两种等价写法，务必分清（这是本项目踩过最深的坑）：
#   RAND_POLY      = 0xA9 = 0b10101001   "bit i = x^i 的系数"（CCSDS 131.0-B 原文写法）
#                                          抽头 {0,3,5,7}
#   RAND_POLY_LFSR = 0x95 = 0b10010101   同一个多项式的【位翻转】
#                                          抽头 {0,2,4,7}
#
# 本文件的 LFSR 是「左移 + 反馈进 bit0 + 输出 bit7」。这个方向下寄存器被消费的
# 顺序是 bit0,bit1,...（即从 x^0 往上走），所以喂进去的多项式必须是同一顺序的
# 位翻转形式 —— 也就是 0x95。
#
# 反过来，如果喂 0xA9（直觉写法），得到的是周期 217 的错序列：
#     AD 75 59 34 CD C4 ...
# 正确组合给出周期 255 的标准序列：
#     0x95 + 初值 0xFF + 左移 + 输出 bit7  ->  FF 48 0E C0 9A 0D ...
#
# 验证方式：对 (掩码 × 初值 × 移位方向 × 输出位) 全枚举，与 euryspace 头注释里
# 记录的标准序列逐位比对，唯一命中的实用组合就是上面这条
# （见 E:\ccsds_fpga\sim\solve_lfsr.py 与 sim\vectors\lfsr_standard_255.txt）。
# 标准序列前 40 bit 的参考值（来自 euryspace ccsds_rxtx_lfsr.vhd 头注释，
# 并用 sim/solve_lfsr.py 对 (掩码×初值×移位方向×输出位) 全枚举反解复核过）
LFSR_REFERENCE_40 = "1111111101001000000011101100000010011010"

RAND_POLY = 0xA9                       # CCSDS 131.0-B 的数学写法（仅作文档/校验用）
RAND_POLY_LFSR = 0x95                  # 本实现方向下真正使用的位翻转掩码
RAND_SEED = 0xFF

# 卷积编码 (7,1/2)
CONV_K = 7
CONV_G1 = 0b1111001                    # 0o171
CONV_G2 = 0b1011011                    # 0o133
CONV_INVERT_2ND = True                 # 第二路取反


# =====================================================================
#  CRC-16/CCITT (CCSDS FECF)
# =====================================================================
def crc16(data):
    crc = 0xFFFF
    for b in bytearray(data):
        crc ^= (b << 8) & 0xFFFF
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if (crc & 0x8000) else (crc << 1) & 0xFFFF
    return crc


# =====================================================================
#  132.0-B  TM 传输帧
# =====================================================================
def build_tm_frame(scid=0x2A, vcid=0, mcfc=0, vcfc=0, data=b"", fecf=True,
                   ocf=False, sec_hdr=False):
    """构造一个 TM 传输帧。

    主头 6 字节：
      octet 1-2 : 版本(2) | 航天器ID(10) | VCID(3) | OCF标志(1)
      octet 3   : 主信道帧计数 MCFC
      octet 4   : 虚拟信道帧计数 VCFC
      octet 5-6 : 传输帧副头标志(1) | 同步标志(1) | 包序标志(1) |
                  段长标识(2) | 首包头指针(11)
    """
    w0 = ((0 & 0x3) << 14) | ((scid & 0x3FF) << 4) | ((vcid & 0x7) << 1) | (1 if ocf else 0)
    hdr = struct.pack(">HBB", w0, mcfc & 0xFF, vcfc & 0xFF)
    # octet 5-6 : TF secondary header flag=1(有) / sync=0 / pkt order=0 /
    #             seg len id=3(11b, 未分段) / first header pointer=0
    w56 = ((1 if sec_hdr else 0) << 15) | (0 << 14) | (0 << 13) | (0b11 << 11) | 0
    hdr += struct.pack(">H", w56)

    body = hdr + bytes(data)
    if fecf:
        body += struct.pack(">H", crc16(body))
    return body


def parse_tm_frame(buf):
    if len(buf) < 8:
        return None
    w0, mcfc, vcfc = struct.unpack_from(">HBB", buf, 0)
    w56, = struct.unpack_from(">H", buf, 4)
    payload = buf[6:-2] if len(buf) > 8 else b""
    rx_crc, = struct.unpack_from(">H", buf, len(buf) - 2)
    calc = crc16(buf[:-2])
    return {
        "scid": (w0 >> 4) & 0x3FF, "vcid": (w0 >> 1) & 0x7, "ocf": w0 & 1,
        "mcfc": mcfc, "vcfc": vcfc,
        "fhp": w56 & 0x7FF, "seglen": (w56 >> 11) & 0x3,
        "payload": payload,
        "crc_ok": rx_crc == calc, "crc_rx": rx_crc, "crc_calc": calc,
    }


# =====================================================================
#  伪随机化
# =====================================================================
def rand_seq(nbits, poly=RAND_POLY_LFSR, seed=RAND_SEED):
    """生成 nbits 位的 CCSDS 伪随机序列（CCSDS 131.0-B）。

    LFSR 结构（与 ccsds_rxtx_lfsr.vhd 的 MSB_FIRST=true 一致）：
        输出 = s 的最高位 (bit7)
        抽头 = bit0 ^ bit2 ^ bit4 ^ bit7      (= 0x95，即 0xA9 的位翻转)
        s = (s << 1) | feedback              (左移，反馈进 bit0)
    初值 0xFF，周期 255。

    参考序列（前 6 字节，MSB-first 打包）：FF 48 0E C0 9A 0D
    """
    s = seed & 0xFF
    out = np.empty(nbits, dtype=np.uint8)
    for i in range(nbits):
        out[i] = (s >> 7) & 1                       # ★ 输出最高位（被移出的那一位）
        fb = ((s >> 0) ^ (s >> 2) ^ (s >> 4) ^ (s >> 7)) & 1   # ★ 0x95 的抽头
        s = ((s << 1) | fb) & 0xFF                  # ★ 左移，反馈进 bit0
    return out


def randomize(bits):
    """按位异或随机序列"""
    b = np.asarray(bits, dtype=np.uint8)
    return (b ^ rand_seq(len(b))).astype(np.uint8)


def derandomize(bits):
    return randomize(bits)          # 自逆


# =====================================================================
#  卷积编码 (7,1/2)
# =====================================================================
def conv_encode(bits, invert2=CONV_INVERT_2ND):
    """标准 NASA/CCSDS (7,1/2) 卷积编码，编码前寄存器清零。

    输出按 G1,G2 交替（每个输入比特出两个符号）。
    """
    b = np.asarray(bits, dtype=np.uint8)
    reg = 0
    out = np.empty(2 * len(b), dtype=np.uint8)
    for i, bit in enumerate(b):
        reg = ((reg << 1) | int(bit)) & ((1 << CONV_K) - 1)
        p1 = bin(reg & CONV_G1).count("1") & 1
        p2 = bin(reg & CONV_G2).count("1") & 1
        if invert2:
            p2 ^= 1
        out[2 * i] = p1
        out[2 * i + 1] = p2
    return out


def conv_decode_viterbi(syms):
    """(7,1/2) 硬判决 Viterbi 译码（用于自检）

    ★ 状态必须是【7 位】= 编码器寄存器的完整内容。
      编码时 reg = ((reg<<1)|bit) & 0x7F，所以新状态的最低位就是输入比特。
      早期版本用了 6 位状态（把最低位丢掉），回溯时无法还原输入比特 —— 这是错的。
    """
    s = np.asarray(syms, dtype=np.uint8)
    nsym = len(s) // 2
    NS = 1 << CONV_K                    # 128 = 完整 7 位寄存器
    INF = 10 ** 9

    pm = np.full(NS, INF, dtype=np.int64)
    pm[0] = 0
    trace = np.zeros((nsym, NS), dtype=np.int16)

    # 预计算所有 (state, bit) 的转移与输出，避免内层重复算
    trans = np.zeros((NS, 2), dtype=np.int32)
    outs = np.zeros((NS, 2, 2), dtype=np.int32)
    for st in range(NS):
        for bit in (0, 1):
            reg = ((st << 1) | bit) & ((1 << CONV_K) - 1)
            p1 = bin(reg & CONV_G1).count("1") & 1
            p2 = bin(reg & CONV_G2).count("1") & 1
            if CONV_INVERT_2ND:
                p2 ^= 1
            trans[st][bit] = reg
            outs[st][bit][0] = p1
            outs[st][bit][1] = p2

    for t in range(nsym):
        r1, r2 = int(s[2 * t]), int(s[2 * t + 1])
        npm = np.full(NS, INF, dtype=np.int64)
        for st in range(NS):
            base = pm[st]
            if base >= INF:
                continue
            for bit in (0, 1):
                nst = trans[st][bit]
                d = (outs[st][bit][0] ^ r1) + (outs[st][bit][1] ^ r2)
                if base + d < npm[nst]:
                    npm[nst] = base + d
                    trace[t][nst] = st
        pm = npm

    st = int(np.argmin(pm))
    bits = np.zeros(nsym, dtype=np.uint8)
    for t in range(nsym - 1, -1, -1):
        bits[t] = st & 1                    # ★ 新状态的最低位 = 该步的输入比特
        st = int(trace[t][st])
    return bits


# =====================================================================
#  bit <-> byte
# =====================================================================
def bytes_to_bits(data):
    a = np.frombuffer(bytes(data), dtype=np.uint8)
    return np.unpackbits(a).astype(np.uint8)


def bits_to_bytes(bits):
    b = np.asarray(bits, dtype=np.uint8)
    pad = (-len(b)) % 8
    if pad:
        b = np.concatenate([b, np.zeros(pad, dtype=np.uint8)])
    return np.packbits(b).tobytes()


# =====================================================================
#  完整发射链
# =====================================================================
def build_cadu(frame, use_rs=False, randomize_data=True):
    """传输帧 -> (可选 RS) -> 随机化 -> 卷积编码 -> 插入 ASM

    返回 (cadu_bits, info)
    """
    info = {}
    bits = bytes_to_bits(frame)
    info["frame_bytes"] = len(frame)
    info["frame_bits"] = len(bits)

    if use_rs:
        raise NotImplementedError("RS 编码尚未实现（阶段 A 暂不需要）")

    # ★ 随机化在 ASM 之前
    if randomize_data:
        bits = randomize(bits)
    info["randomized"] = randomize_data

    # ★ 卷积编码
    enc = conv_encode(bits)
    info["conv_bits"] = len(enc)

    # ★ ASM 不参与随机化、也不参与卷积编码
    asm_bits = bytes_to_bits(struct.pack(">I", ASM))
    cadu = np.concatenate([asm_bits, enc]).astype(np.uint8)
    info["cadu_bits"] = len(cadu)
    return cadu, info


def decode_cadu(cadu, verbose=False):
    """反流程：去 ASM -> Viterbi 译码 -> 解随机化 -> 解帧"""
    c = np.asarray(cadu, dtype=np.uint8)
    asm_bits = bytes_to_bits(struct.pack(">I", ASM))
    if len(c) < 32 or not np.array_equal(c[:32], asm_bits):
        return None, {"reason": "ASM 未命中"}
    enc = c[32:]
    n = (len(enc) // 2) * 2
    bits = conv_decode_viterbi(enc[:n])
    bits = derandomize(bits)
    frame = bits_to_bytes(bits)
    return frame, {"asm_ok": True}


# =====================================================================
#  调制：BPSK + SRRC
# =====================================================================
def srrc(beta=0.35, sps=10, span=8):
    """根升余弦滤波器"""
    N = span * sps
    t = (np.arange(-N // 2, N // 2 + 1)) / float(sps)
    h = np.zeros_like(t)
    for i, ti in enumerate(t):
        if abs(ti) < 1e-8:
            h[i] = 1.0 - beta + 4 * beta / np.pi
        elif abs(abs(ti) - 1.0 / (4 * beta)) < 1e-6:
            h[i] = (beta / np.sqrt(2)) * (
                (1 + 2 / np.pi) * np.sin(np.pi / (4 * beta)) -
                (1 - 2 / np.pi) * np.cos(np.pi / (4 * beta)))
        else:
            num = np.sin(np.pi * ti * (1 - beta)) + \
                  4 * beta * ti * np.cos(np.pi * ti * (1 + beta))
            den = np.pi * ti * (1 - (4 * beta * ti) ** 2)
            h[i] = num / den
    return h / np.sqrt(np.sum(h ** 2))


def cadu_to_iq(cadu, fs=2_500_000.0, sym_rate=250_000.0, beta=0.35,
               amp=0.6, if_hz=200_000.0):
    """CADU 比特 -> 复数基带 I/Q (int16)

    符号映射：BPSK, bit 0 -> +1, bit 1 -> -1
    if_hz：上变频到中频，避开零中频的直流失调和本振泄漏（不设就留在 0 Hz）

    返回 (N,2) 交错 int16 流，可直接喂 iio_writedev
    """
    sps = int(round(fs / sym_rate))
    bits = np.asarray(cadu, dtype=np.uint8)
    sym = np.where(bits == 0, 1.0, -1.0)

    up = np.zeros(len(sym) * sps)
    up[::sps] = sym
    h = srrc(beta, sps, span=8)
    bb = np.convolve(up, h, mode="same")

    # 峰值归一化，再加中频
    pk = np.max(np.abs(bb)) or 1.0
    bb = bb / pk
    if if_hz:
        t = np.arange(len(bb)) / fs
        bb = bb * np.exp(1j * 2 * np.pi * if_hz * t)

    scale = amp * 32767.0 * 0.7
    I = np.clip(np.real(bb) * scale, -32768, 32767).astype(np.int16)
    Q = np.clip(np.imag(bb) * scale, -32768, 32767).astype(np.int16)
    return I, Q


def iq_interleave(I, Q):
    out = np.empty(2 * len(I), dtype=np.int16)
    out[0::2] = I
    out[1::2] = Q
    return out


# =====================================================================
#  自检
# =====================================================================
def selftest():
    print("=" * 72)
    print(" CCSDS 遥测发射链 —— 软件环回自检")
    print("=" * 72)

    # ---- 随机化 LFSR 验证 ----
    # ★ 标准版（CCSDS 131.0-B）：输出 bit7、抽头 0x95、左移、反馈进 bit0、周期 255
    print("\n[1] 随机化 LFSR（CCSDS 标准）")
    seq = rand_seq(255)
    print("   前 40 位 : %s" % "".join(str(b) for b in seq[:40]))
    print("   参考序列 : %s" % LFSR_REFERENCE_40)
    s = RAND_SEED
    man = []
    for _ in range(255):
        man.append((s >> 7) & 1)                                    # 输出 MSB
        fb = ((s >> 0) ^ (s >> 2) ^ (s >> 4) ^ (s >> 7)) & 1        # 0x95 抽头
        s = ((s << 1) | fb) & 0xFF                                  # 左移进 bit0
    same = list(seq) == man
    hits_ref = "".join(str(b) for b in seq[:40]) == LFSR_REFERENCE_40
    # 周期判定：必须用【全长】序列比对，任何 k < n 都会自己跟自己比而假阳性。
    # 取 2*255 位、在 k < 255 范围内找最小周期。
    long_seq = rand_seq(510)
    period = next((k for k in range(1, 255)
                   if all(long_seq[i] == long_seq[i % k] for i in range(510))), 255)
    print("   手工核对 : %s" % ("[OK]" if same else "[FAIL]"))
    print("   命中标准 : %s" % ("[OK]" if hits_ref else "[FAIL]"))
    print("   周期     : %d  %s" % (period, "[OK]" if period == 255 else "[FAIL]"))
    print("   前 6 字节(MSB-first): %s" % bits_to_bytes(seq[:48]).hex(' ').upper())

    # ---- 传输帧 ----
    print("\n[2] 132.0-B 传输帧")
    payload = bytes(range(1, 33))                       # 32 字节遥测数据
    frame = build_tm_frame(scid=0x2A, vcid=0, mcfc=7, vcfc=3, data=payload)
    print("   帧长 %d 字节 (6 头 + 32 数据 + 2 FECF)" % len(frame))
    print("   %s" % frame.hex())
    p = parse_tm_frame(frame)
    print("   SCID=0x%X VCID=%d MCFC=%d VCFC=%d CRC=%s payload一致=%s"
          % (p["scid"], p["vcid"], p["mcfc"], p["vcfc"],
             "OK" if p["crc_ok"] else "BAD", p["payload"] == payload))

    # ---- 完整链 ----
    print("\n[3] 完整发射链（随机化 → 卷积 → ASM）")
    cadu, info = build_cadu(frame)
    print("   %s" % info)
    print("   CADU 前 4 字节 (应为 1acffc1d): %s"
          % bits_to_bytes(cadu[:32]).hex())

    # ---- 反向解码 ----
    print("\n[4] 反向解码验证")
    dec, dinfo = decode_cadu(cadu)
    print("   %s" % dinfo)
    print("   解码帧长 %d 字节" % len(dec))
    dp = parse_tm_frame(dec)
    ok = (dp is not None and dp["crc_ok"] and dp["payload"] == payload
          and dp["scid"] == 0x2A and dp["mcfc"] == 7)
    print("   内容一致: %s  CRC: %s" % (dp["payload"] == payload, dp["crc_ok"]))
    print("   %s 整链环回 %s" % ("[OK]" if ok else "[FAIL]", "通过" if ok else "失败"))

    # ---- 加噪 ----
    print("\n[5] 加噪鲁棒性（硬判决 Viterbi）")
    for flip in (0, 1, 2, 3, 5):
        c = cadu.copy()
        if flip:
            rng = np.random.default_rng(1)
            idx = rng.choice(len(c), flip, replace=False)
            c[idx] ^= 1
        d, _ = decode_cadu(c)
        good = False
        if d:
            q = parse_tm_frame(d)
            good = bool(q and q["payload"] == payload)
        print("   翻转 %d bit: %s" % (flip, "[OK] 恢复" if good else "[FAIL] 失败"))

    # ---- 调制 ----
    print("\n[6] BPSK + SRRC 调制")
    I, Q = cadu_to_iq(cadu, fs=2_500_000, sym_rate=250_000)
    print("   fs=2.5MSPS  sym=250ksym/s  sps=%d  样点=%d  %.1f ms"
          % (2_500_000 // 250_000, len(I), len(I) / 2.5e6 * 1e3))
    print("   I 范围 [%d, %d]  std=%.1f" % (I.min(), I.max(), I.std()))
    P = np.abs(np.fft.fftshift(np.fft.fft(I[:4096] * np.hanning(4096)))) ** 2
    f = (np.arange(4096) - 2048) * (2.5e6 / 4096)
    print("   主瓣在 %+.0f kHz 附近（BPSK 双边带）" % (f[int(P.argmax())] / 1e3))

    print("\n自检完成。")
    return 0


if __name__ == "__main__":
    act = sys.argv[1] if len(sys.argv) > 1 else "selftest"
    if act == "selftest":
        sys.exit(selftest())
    print("未知命令: %s" % act)
    sys.exit(2)
