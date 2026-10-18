#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ccsds.py -- CCSDS 空间包（Space Packet, CCSDS 133.0-B-2）最小实现

纯 Python 标准库，零依赖。PC 和 RK3588 上都能直接跑。

本模块实现的是"简化版 CCSDS"，用于载荷遥控/遥测的实验室验证：
  * 空间包主头（6 字节）—— 完全符合 CCSDS 133.0-B-2
  * 包尾 CRC-16/CCITT（2 字节，可选）—— 用于串口链路的误码检测
  * 传输帧同步头 0x1ACFFC1D（可选）—— CCSDS TM/TC 传输帧附着同步标志

主头格式：
   15        11 10  9  8  7                    0
  ┌────────────┬──┬──┬──┬──────────────────────┐
  │ 版本 = 000 │类型│副头│      APID            │  word0
  ├────────────┴──┴──┴──┼──────────────────────┤
  │    序列标志 (11)     │    序列计数 (14)      │  word1
  ├──────────────────────┴──────────────────────┤
  │        包数据长度 = 数据域字节数 − 1          │  word2
  └─────────────────────────────────────────────┘

  类型  0 = 遥控(TC)  1 = 遥测(TM)
  序列标志 3 = 独立包（standalone）
"""

import struct
import time

# ------------------------------------------------------------------ 常量
SYNC = b"\x1a\xcf\xfc\x1d"          # CCSDS 传输帧附着同步标志

SEQ_STANDALONE = 3                   # 序列标志：独立包
SEQ_FIRST = 1                        # 分段：首段
SEQ_CONT = 0                         # 分段：中间段
SEQ_LAST = 2                         # 分段：末段

TYPE_TC = 0                          # 遥控
TYPE_TM = 1                          # 遥测

HDR_LEN = 6
CRC_LEN = 2

# ------------------------------------------------------------- APID 分配表
APID_RELAY_SET   = 0x100   # 转发参数整体设置
APID_RF_SET      = 0x101   # 射频参数设置
APID_RELAY_MODE  = 0x102   # 只切工作模式
APID_FREQ_OFFSET = 0x103   # 只设频偏（Hz）
APID_DIG_GAIN    = 0x104   # 只设数字增益 / 隔直
APID_REQ_STATUS  = 0x110   # 请求状态（无数据域）

APID_STATUS_TM   = 0x200   # 状态遥测
APID_SPECTRUM_TM = 0x201   # 频谱监测遥测（GPU 输出）
APID_ACK_TM      = 0x202   # 命令应答

APID_NAMES = {
    APID_RELAY_SET:   "RELAY_SET",
    APID_RF_SET:      "RF_SET",
    APID_RELAY_MODE:  "RELAY_MODE",
    APID_FREQ_OFFSET: "FREQ_OFFSET",
    APID_DIG_GAIN:    "DIG_GAIN",
    APID_REQ_STATUS:  "REQ_STATUS",
    APID_STATUS_TM:   "STATUS_TM",
    APID_SPECTRUM_TM: "SPECTRUM_TM",
    APID_ACK_TM:      "ACK_TM",
}

MODE_NAME = {0: "BYPASS", 1: "RELAY", 2: "MUTE", 3: "DUC_ONLY"}
MODE_VALUE = {v: k for k, v in MODE_NAME.items()}


# ------------------------------------------------------------------ CRC
def crc16_ccitt(data, crc=0xFFFF):
    """CRC-16/CCITT-FALSE, poly 0x1021, init 0xFFFF, 不反转, 不异或输出。"""
    for b in data:
        crc ^= (b << 8) & 0xFFFF
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc & 0xFFFF


# ------------------------------------------------------------------ 空间包
class SpacePacket(object):
    def __init__(self, apid, payload=b"", seq=0, ptype=TYPE_TC,
                 seqflags=SEQ_STANDALONE, crc=True):
        if isinstance(payload, bytearray):
            payload = bytes(payload)
        self.apid = apid & 0x7FF
        self.payload = payload
        self.seq = seq & 0x3FFF
        self.ptype = ptype & 1
        self.seqflags = seqflags & 3
        self.crc = crc

    # -------- 打包 --------
    def pack(self, with_crc=None, sync=False):
        with_crc = self.crc if with_crc is None else with_crc
        w0 = (0 << 13) | (self.ptype << 12) | (0 << 11) | self.apid
        w1 = (self.seqflags << 14) | self.seq
        w2 = len(self.payload) - 1
        if w2 < 0:
            w2 = 0xFFFF                      # 空数据域用 0xFFFF 表示
        body = struct.pack(">HHH", w0, w1, w2) + self.payload
        if with_crc:
            body += struct.pack(">H", crc16_ccitt(body))
        return (SYNC + body) if sync else body

    # -------- 解包（需要完整的一包）--------
    @classmethod
    def unpack(cls, buf, with_crc=True):
        """返回 (SpacePacket, 消耗字节数)；数据不足返回 (None, 0)。"""
        off = 0
        if buf[:4] == SYNC:
            off = 4
        if len(buf) < off + HDR_LEN:
            return None, 0
        w0, w1, w2 = struct.unpack(">HHH", buf[off:off + HDR_LEN])
        n = 0 if w2 == 0xFFFF else w2 + 1
        total = off + HDR_LEN + n + (CRC_LEN if with_crc else 0)
        if len(buf) < total:
            return None, 0
        payload = buf[off + HDR_LEN: off + HDR_LEN + n]
        body = buf[off: off + HDR_LEN + n]
        if with_crc:
            got = struct.unpack(">H", buf[off + HDR_LEN + n: total])[0]
            if got != crc16_ccitt(body):
                raise ValueError("CRC mismatch (got 0x%04X, want 0x%04X)"
                                 % (got, crc16_ccitt(body)))
        p = cls(apid=w0 & 0x7FF,
                payload=payload,
                seq=w1 & 0x3FFF,
                ptype=(w0 >> 12) & 1,
                seqflags=(w1 >> 14) & 3,
                crc=with_crc)
        return p, total

    def __repr__(self):
        return ("<SpacePacket %s(0x%03X) type=%s seq=%d len=%d>"
                % (APID_NAMES.get(self.apid, "?"), self.apid,
                   "TM" if self.ptype else "TC", self.seq, len(self.payload)))


# ------------------------------------------------------------- 流式解码器
class PacketDecoder(object):
    """从字节流里找同步头并重组完整空间包。

    用法：
        dec = PacketDecoder()
        for pkt in dec.feed(ser.read(4096)):
            handle(pkt)
    """

    def __init__(self, with_crc=True, use_sync=True, max_len=2048):
        self.buf = bytearray()
        self.with_crc = with_crc
        self.use_sync = use_sync
        self.max_len = max_len

    def feed(self, data):
        self.buf += data
        out = []
        while True:
            if self.use_sync:
                i = self.buf.find(SYNC)
                if i < 0:
                    # 保留末尾 3 字节（同步头可能被切断）
                    if len(self.buf) > 3:
                        del self.buf[:-3]
                    break
                if i > 0:
                    del self.buf[:i]
            if len(self.buf) < HDR_LEN + (4 if self.use_sync else 0):
                break
            base = 4 if self.use_sync else 0
            try:
                w2 = struct.unpack(">H", self.buf[base + 4:base + 6])[0]
            except struct.error:
                break
            n = 0 if w2 == 0xFFFF else w2 + 1
            total = base + HDR_LEN + n + (CRC_LEN if self.with_crc else 0)
            if total > self.max_len:
                del self.buf[:base + 1]         # 长度不合理，滑一个字节重找
                continue
            if len(self.buf) < total:
                break
            try:
                pkt, used = SpacePacket.unpack(bytes(self.buf[:total]),
                                               with_crc=self.with_crc)
            except ValueError:
                del self.buf[:base + 1]         # CRC 错，滑一个字节重找
                continue
            out.append(pkt)
            del self.buf[:used]
            if not self.use_sync:
                break
        return out


# ------------------------------------------------------------- 序号发生器
class SeqCounter(object):
    """每个 APID 独立的 CCSDS 序列计数器（14 bit，模 16384）。"""

    def __init__(self):
        self._c = {}

    def next(self, apid):
        v = self._c.get(apid, 0)
        self._c[apid] = (v + 1) & 0x3FFF
        return v


# ================================================================ 数据域
#  下面这些是"载荷参数"的编码格式。RK3588 用它构造遥控包，PS 侧用它
#  翻译成 PL 寄存器写入。

def enc_relay_set(mode, duc_word, ddc_word, gain, dc_en):
    """APID 0x100  转发参数整体设置。12 字节。"""
    return struct.pack(">BIIHB", mode & 3, duc_word & 0xFFFFFFFF,
                       ddc_word & 0xFFFFFFFF, gain & 0xFFF, dc_en & 1)


def dec_relay_set(b):
    mode, duc, ddc, gain, dc = struct.unpack(">BIIHB", b[:12])
    return dict(mode=mode, duc=duc, ddc=ddc, gain=gain, dc=dc)


def enc_rf_set(rx_lo_hz, tx_lo_hz, rx_gain_db, tx_att_db):
    """APID 0x101  射频参数设置。10 字节。"""
    return struct.pack(">QQBB", rx_lo_hz, tx_lo_hz,
                       rx_gain_db & 0xFF, tx_att_db & 0xFF)


def dec_rf_set(b):
    rx, tx, g, a = struct.unpack(">QQBB", b[:18] if len(b) >= 18 else b.ljust(18, b"\0"))
    return dict(rx_lo=rx, tx_lo=tx, rxgain=g, txatt=a)


def enc_mode(mode):
    """APID 0x102  只切工作模式。1 字节。"""
    return struct.pack(">B", mode & 3)


def enc_freq_offset(duc_hz, ddc_hz):
    """APID 0x103  频偏（Hz，二补码 32 位）。8 字节。"""
    return struct.pack(">ii", int(duc_hz), int(ddc_hz))


def dec_freq_offset(b):
    d, x = struct.unpack(">ii", b[:8])
    return dict(duc_hz=d, ddc_hz=x)


def enc_dig_gain(gain, dc_en):
    """APID 0x104  数字增益 + 隔直。3 字节。"""
    return struct.pack(">HB", gain & 0xFFF, dc_en & 1)


def enc_status_tm(in_cnt, out_cnt, clip_cnt, rc, mode, ddc, duc, gain):
    """APID 0x200  状态遥测。28 字节。"""
    return struct.pack(">IIIiBIIH", in_cnt & 0xFFFFFFFF, out_cnt & 0xFFFFFFFF,
                       clip_cnt & 0xFFFFFFFF, int(rc), mode & 3,
                       ddc & 0xFFFFFFFF, duc & 0xFFFFFFFF, gain & 0xFFF)


def dec_status_tm(b):
    a = struct.unpack(">IIIiBIIH", b[:27] if len(b) >= 27 else b.ljust(27, b"\0"))
    return dict(in_cnt=a[0], out_cnt=a[1], clip_cnt=a[2], rc=a[3],
                mode=a[4], ddc=a[5], duc=a[6], gain=a[7])


def enc_spectrum_tm(timestamp, fs_hz, bins_db):
    """APID 0x201  频谱监测遥测（GPU FFT 输出）。

    timestamp : Unix 秒（32 位）
    fs_hz     : 采样率
    bins_db   : 各频点功率，dB（int8，量化到 1 dB）
    """
    b = bytearray()
    b += struct.pack(">IIH", timestamp & 0xFFFFFFFF, fs_hz & 0xFFFFFFFF,
                     len(bins_db))
    for v in bins_db:
        b += struct.pack(">b", max(-128, min(127, int(round(v)))))
    return bytes(b)


def dec_spectrum_tm(b):
    ts, fs, n = struct.unpack(">IIH", b[:10])
    bins = list(struct.unpack(">%db" % n, b[10:10 + n])) if n else []
    return dict(timestamp=ts, fs=fs, bins_db=bins)
