#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ttc_modem.py -- 测控链路的调制/解调 + CCSDS 打包（纯 numpy，PC 和 3588 通用）

链路设计
--------
  基带 BPSK，IF = 200 kHz，符号率 25 ksym/s
  帧结构：[前导 32bit 交替] [同步字 0x1ACFFC1D] [CCSDS 包] [CRC-16]
  数据按 MSB 优先

为什么用 200 kHz 中频而不是直流
------------------------------
  直流处有本振泄漏和 DC 失调，信噪比最差。挪到 200 kHz 避开。

为什么符号率只有 25 ksym/s
--------------------------
  测控是窄带低速链路（真实 CCSDS 遥控通常 1~64 kbps）。
  符号率低 → 每符号样点多 → 解调对定时误差不敏感 → 自环测试容易成功。
"""

import struct

import numpy as np

# ---------------- 链路参数 ----------------
FS_DEFAULT = 2_500_000        # 采样率（板子实测可用的最低值）
IF_HZ = 200_000               # 中频
SYM_RATE = 25_000             # 符号率 sym/s
SPS = FS_DEFAULT // SYM_RATE  # 每符号样点数

PREAMBLE = 0b10101010101010101010101010101010   # 32 bit
SYNC = 0x1ACFFC1D                                # CCSDS 同步字


# =====================================================================
#  CRC-16/CCITT
# =====================================================================
def crc16(data):
    crc = 0xFFFF
    for b in bytearray(data):
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if (crc & 0x8000) else (crc << 1) & 0xFFFF
    return crc


# =====================================================================
#  CCSDS 空间包（与 ccsds.py 一致的简化版）
# =====================================================================
def make_ccsds_packet(apid, payload, seq=0, ptype=1):
    """构造一个 CCSDS 空间包。ptype: 0=遥控(TC) 1=遥测(TM)"""
    word0 = (0 << 13) | (ptype << 12) | (0 << 11) | (apid & 0x7FF)
    word1 = (0b11 << 14) | (seq & 0x3FFF)
    word2 = (len(payload) - 1) & 0xFFFF
    hdr = struct.pack(">HHH", word0, word1, word2)
    body = hdr + bytes(payload)
    return body + struct.pack(">H", crc16(body))


def parse_ccsds_packet(buf):
    """解一个 CCSDS 包，返回 dict 或 None"""
    if len(buf) < 8:
        return None
    w0, w1, w2 = struct.unpack_from(">HHH", buf, 0)
    plen = w2 + 1
    total = 6 + plen + 2
    if len(buf) < total:
        return None
    body = buf[:6 + plen]
    rx_crc, = struct.unpack_from(">H", buf, 6 + plen)
    return {
        "apid": w0 & 0x7FF,
        "ptype": (w0 >> 12) & 1,
        "seq": w1 & 0x3FFF,
        "len": plen,
        "payload": bytes(buf[6:6 + plen]),
        "crc_rx": rx_crc,
        "crc_calc": crc16(body),
        "crc_ok": rx_crc == crc16(body),
        "total": total,
    }


# =====================================================================
#  调制
# =====================================================================
def _bits_from_bytes(data):
    """字节 -> bit 列表（MSB 优先）"""
    out = []
    for b in bytearray(data):
        for i in range(7, -1, -1):
            out.append((b >> i) & 1)
    return out


def build_frame_bytes(packet):
    """前导 + 同步字 + 包 + CRC"""
    body = packet + struct.pack(">H", crc16(packet))
    return struct.pack(">I", PREAMBLE) + struct.pack(">I", SYNC) + body


def modulate(frame_bytes, fs=FS_DEFAULT, if_hz=IF_HZ, sym_rate=SYM_RATE,
             amp=0.5, reps=8):
    """把帧调制成复数基带 I/Q。返回 (I, Q) 两个 int16 数组。

    reps: 帧重复次数（便于接收端抓到）
    """
    sps = int(round(fs / sym_rate))
    bits = _bits_from_bytes(frame_bytes)
    # BPSK: 0 -> +1, 1 -> -1
    sym = np.array([1.0 if b == 0 else -1.0 for b in bits], dtype=np.float64)
    sym = np.tile(sym, reps)

    # 上采样（矩形脉冲 = 每符号保持 sps 个样点）
    base = np.repeat(sym, sps)

    n = len(base)
    t = np.arange(n) / fs
    # BPSK 调制到 IF
    bb = base * np.exp(1j * 2 * np.pi * if_hz * t)
    scale = amp * 32767.0 * 0.7      # 留余量，避免削顶
    I = np.clip(np.real(bb) * scale, -32768, 32767).astype(np.int16)
    Q = np.clip(np.imag(bb) * scale, -32768, 32767).astype(np.int16)
    return I, Q


def interleave_iq(I, Q):
    """打包成 iio_readdev/iio_writedev 需要的 I,Q,I,Q... int16 流"""
    out = np.empty(2 * len(I), dtype=np.int16)
    out[0::2] = I
    out[1::2] = Q
    return out


# =====================================================================
#  解调
# =====================================================================
def demodulate(I, Q, fs=FS_DEFAULT, if_hz=IF_HZ, sym_rate=SYM_RATE):
    """BPSK 解调 -> 返回硬判决 bit 数组"""
    I = np.asarray(I, dtype=np.float64)
    Q = np.asarray(Q, dtype=np.float64)
    n = len(I)
    t = np.arange(n) / fs
    # 下变频到基带
    bb = (I + 1j * Q) * np.exp(-1j * 2 * np.pi * if_hz * t)
    sps = int(round(fs / sym_rate))
    m = (n // sps) * sps
    if m < sps:
        return np.array([], dtype=np.int8)
    # 按符号积分（匹配滤波）
    seg = bb[:m].reshape(-1, sps)
    soft = seg.mean(axis=1).real          # BPSK：取实部
    return (soft < 0).astype(np.int8)     # 负 -> 1


def find_sync_and_parse(bits, sync=SYNC, preamble=PREAMBLE, ptype=None):
    """在 bit 流里找同步字，解出 CCSDS 包。

    返回 (ok, info, packet_dict)
    """
    if len(bits) < 64:
        return False, {"reason": "bit 太少 (%d)" % len(bits)}, None

    sync_bits = _bits_from_bytes(struct.pack(">I", sync))
    # 把 bit 流打包成 bytes 后做字节级搜索（快得多）
    try:
        raw = np.packbits(bits).tobytes()
    except Exception:
        raw = bytes(bytearray(np.packbits(bits).tolist()))

    needle = struct.pack(">I", sync)
    idx = raw.find(needle)
    info = {"bit_len": len(bits), "byte_len": len(raw)}
    if idx < 0:
        # 报一下最接近的相关峰，便于诊断
        return False, dict(info, reason="没找到同步字 0x1ACFFC1D"), None

    info["sync_at_byte"] = idx
    pkt = parse_ccsds_packet(raw[idx + 4:])
    if pkt is None:
        return False, dict(info, reason="同步字后数据不足"), None
    info.update({"apid": pkt["apid"], "crc_ok": pkt["crc_ok"]})
    return pkt["crc_ok"], info, pkt


# =====================================================================
#  自检：软件环回（不需要任何硬件）
# =====================================================================
if __name__ == "__main__":
    print("=" * 74)
    print(" ttc_modem 软件环回自检（不需要硬件）")
    print("=" * 74)

    payload = bytes([1, 0x04, 0x00, 0x00, 0x00, 0x08, 0x00, 0x00])   # RELAY_SET 示例
    pkt = make_ccsds_packet(0x100, payload, seq=7, ptype=0)
    print("\n[1] 打包")
    print("  包长 %d 字节" % len(pkt))
    p = parse_ccsds_packet(pkt)
    print("  APID=0x%03X  seq=%d  len=%d  CRC %s"
          % (p["apid"], p["seq"], p["len"], "OK" if p["crc_ok"] else "BAD"))

    frame = build_frame_bytes(pkt)
    print("\n[2] 成帧：前导4B + 同步4B + 包%d B + CRC2B = %d 字节"
          % (len(pkt), len(frame)))

    print("\n[3] 调制 (fs=%d, IF=%d, 符号率=%d, %d 样点/符号)"
          % (FS_DEFAULT, IF_HZ, SYM_RATE, FS_DEFAULT // SYM_RATE))
    I, Q = modulate(frame)
    print("  生成 %d 样点 (%.1f ms)" % (len(I), len(I) / FS_DEFAULT * 1e3))
    print("  I: 范围[%d,%d] std=%.1f   Q: 范围[%d,%d] std=%.1f"
          % (I.min(), I.max(), I.std(), Q.min(), Q.max(), Q.std()))

    print("\n[4] 加噪声后解调")
    for snr in (30, 20, 10, 6, 3):
        rng = np.random.default_rng(1234)
        sig_p = np.mean(I.astype(float) ** 2 + Q.astype(float) ** 2)
        noise_p = sig_p / (10 ** (snr / 10.0))
        s = np.sqrt(noise_p / 2)
        In = np.clip(I + rng.normal(0, s, len(I)), -32768, 32767).astype(np.int16)
        Qn = np.clip(Q + rng.normal(0, s, len(Q)), -32768, 32767).astype(np.int16)

        bits = demodulate(In, Qn)
        ok, info, pk = find_sync_and_parse(bits)
        if pk:
            same = pk["payload"] == payload and pk["apid"] == 0x100
            print("  SNR %2d dB: 同步@字节%-4s APID=0x%03X 包长%2d CRC=%s 内容一致=%s"
                  % (snr, info.get("sync_at_byte"), pk["apid"], pk["len"],
                     "OK" if pk["crc_ok"] else "BAD", "是" if same else "否"))
        else:
            print("  SNR %2d dB: 失败 - %s" % (snr, info.get("reason")))

    print("\n[5] 无损环回（应该 100% 正确）")
    bits = demodulate(I, Q)
    ok, info, pk = find_sync_and_parse(bits)
    print("  ok=%s  info=%s" % (ok, info))
    if pk:
        print("  payload 一致: %s" % (pk["payload"] == payload))
        print("  最低 SNR 门限约 6~10 dB（看上面）")

    print("\n自检完成。")
