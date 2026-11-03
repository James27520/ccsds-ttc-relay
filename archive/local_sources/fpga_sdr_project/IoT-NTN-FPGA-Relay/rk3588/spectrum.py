#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
spectrum.py -- 频谱遥测帧协议（PL → RK3588）

设计目标
--------
UART @115200 只有 11.5 kB/s，搬不动 30.72 MSPS 的原始 IQ。
所以 PL 侧先做 FFT + 功率谱 + 多帧平均，只把 **1 KB 的频谱** 传下来：
1024 点 → 1 KB/帧 → 约 11 帧/秒，足够做连续信道监测。

帧格式（全部小端）
--------------------------------------------------------------
偏移  长度  字段            说明
0     2     同步头          0xA5 0x5A
2     1     版本            0x01
3     1     标志位          bit0=饱和 bit1=平均有效
4     2     点数 N          1024
6     4     采样率          30720000
10    4     中心频偏        Hz，相对 RX_LO（int32）
14    4     帧计数          uint32，回绕
18    2     平均次数        uint16
20    2     噪声底          uint8.8 定点（dBFS×256，负数补码）
22    2     峰值            uint8.8 定点
24    N     频谱数据        uint8，值 = round(dBFS + 128)，0..255
24+N  2     CRC-16/CCITT    poly 0x1021 init 0xFFFF，覆盖从偏移 0 到 N+23
--------------------------------------------------------------
总长 = 26 + N 字节。N=1024 时共 1050 字节 → 91 ms @115200。

零点约定
--------
频谱值是 **dBFS**（相对 ADC 满量程），0 dBFS = 满量程正弦。
uint8 编码 = dBFS + 128，所以 0 → -128 dBFS，128 → 0 dBFS。
典型噪声底在 -60 dBFS 左右 → 编码值约 68。
"""

import struct
import time

SYNC = b"\xA5\x5A"
VERSION = 1
HDR_LEN = 24                      # 同步头到峰值
CRC_LEN = 2
N_DEFAULT = 1024
FS_DEFAULT = 30720000

FLAG_SATURATED = 0x01
FLAG_AVERAGED = 0x02

# 频谱值编码偏移：编码 = dBFS + OFFSET
DB_OFFSET = 128.0


# =====================================================================
#  CRC-16/CCITT (X.25 型)，与 ccsds.py 保持一致
# =====================================================================
def crc16(data):
    crc = 0xFFFF
    for b in bytearray(data):
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if (crc & 0x8000) else (crc << 1) & 0xFFFF
    return crc


# =====================================================================
#  编码 / 解码
# =====================================================================
def encode_frame(bins, fs=FS_DEFAULT, center_hz=0, frame_no=0,
                 avg_count=1, noise_dbfs=None, peak_dbfs=None, saturated=False):
    """把浮点 dBFS 频谱打包成二进制帧。bins 是长度为 N 的 dBFS 序列。"""
    n = len(bins)
    flags = (FLAG_SATURATED if saturated else 0) | (FLAG_AVERAGED if avg_count > 1 else 0)
    if noise_dbfs is None:
        noise_dbfs = float(min(bins))
    if peak_dbfs is None:
        peak_dbfs = float(max(bins))

    hdr = struct.pack("<2sBBHIIiHhh",
                      SYNC, VERSION, flags, n, int(fs), int(center_hz),
                      int(frame_no), int(avg_count),
                      int(round(noise_dbfs * 256)), int(round(peak_dbfs * 256)))
    payload = bytes(bytearray(max(0, min(255, int(round(v + DB_OFFSET)))) for v in bins))
    body = hdr + payload
    return body + struct.pack("<H", crc16(body))


class SpectrumFrame(object):
    """一帧解码后的频谱。"""

    def __init__(self, bins_dbfs, fs, center_hz, frame_no, avg_count,
                 noise_dbfs, peak_dbfs, saturated, raw=None):
        self.bins = bins_dbfs              # list[float]，dBFS
        self.fs = fs
        self.center_hz = center_hz
        self.frame_no = frame_no
        self.avg_count = avg_count
        self.noise_dbfs = noise_dbfs
        self.peak_dbfs = peak_dbfs
        self.saturated = saturated
        self.raw = raw
        self.t = time.time()

    @property
    def n(self):
        return len(self.bins)

    @property
    def rbw_hz(self):
        """分辨率带宽 = fs / N。"""
        return float(self.fs) / self.n if self.n else 0.0

    def freq_axis(self):
        """返回每个 bin 对应的频率（Hz，相对 RX_LO），已做 fftshift 顺序。"""
        n = self.n
        # 数据按 fftshift 顺序（-fs/2 .. +fs/2）
        return [(-n / 2.0 + i) * self.rbw_hz + self.center_hz for i in range(n)]

    def __repr__(self):
        return ("<SpectrumFrame #%d n=%d fs=%.3fMHz rbw=%.1fkHz "
                "noise=%.1fdBFS peak=%.1fdBFS avg=%d%s>"
                % (self.frame_no, self.n, self.fs / 1e6, self.rbw_hz / 1e3,
                   self.noise_dbfs, self.peak_dbfs, self.avg_count,
                   " SAT" if self.saturated else ""))


def decode_frame(buf):
    """尝试从 buf 里解出一帧。返回 (frame, 消耗字节数) 或 (None, 跳过字节数)。

    能处理流中的垃圾字节和分片（数据不足时返回 (None, 0) 表示还要更多数据）。
    """
    if len(buf) < 4:
        return None, 0

    # 找同步头
    i = buf.find(SYNC)
    if i < 0:
        # 保留最后 1 字节，以防同步头被切开
        return None, max(1, len(buf) - 1)
    if i > 0:
        return None, i                       # 丢掉同步头之前的垃圾

    if len(buf) < HDR_LEN:
        return None, 0                       # 头还没收全

    (sync, ver, flags, n, fs, center, fno, avg,
     noise_q, peak_q) = struct.unpack_from("<2sBBHIIiHhh", buf, 0)

    if ver != VERSION or n == 0 or n > 65535:
        return None, 2                       # 版本不对，跳过同步头继续找
    if fs == 0:
        return None, 2

    total = HDR_LEN + n + CRC_LEN
    if len(buf) < total:
        return None, 0                       # 数据还没收全

    body = buf[:HDR_LEN + n]
    crc_rx, = struct.unpack_from("<H", buf, HDR_LEN + n)
    if crc16(body) != crc_rx:
        return None, 2                       # CRC 错，跳过同步头重找

    payload = buf[HDR_LEN:HDR_LEN + n]
    bins = [b - DB_OFFSET for b in bytearray(payload)]
    frame = SpectrumFrame(bins, fs, center, fno, avg,
                          noise_q / 256.0, peak_q / 256.0,
                          bool(flags & FLAG_SATURATED), raw=bytes(body))
    return frame, total


class SpectrumReceiver(object):
    """从串口流里持续解频谱帧。"""

    def __init__(self, link, verbose=False):
        self.link = link
        self.verbose = verbose
        self.buf = bytearray()
        self.frames = 0
        self.bad = 0

    def pump(self, seconds=0.5):
        """读取串口若干秒，产出解出的帧。"""
        t0 = time.time()
        out = []
        while time.time() - t0 < seconds:
            d = self.link.read() if hasattr(self.link, "read") else None
            if d:
                self.buf += d
            else:
                time.sleep(0.02)
                continue
            while True:
                fr, used = decode_frame(bytes(self.buf))
                if used:
                    del self.buf[:used]
                if fr is None:
                    break
                self.frames += 1
                out.append(fr)
        while True:
            fr, used = decode_frame(bytes(self.buf))
            if not fr:
                if used:
                    del self.buf[:used]
                break
            self.frames += 1
            del self.buf[:used]
            out.append(fr)
        return out


# =====================================================================
#  合成信号（用于在 PL 频谱引擎做好之前开发和测试 3588 侧）
# =====================================================================
def synth_frame(n=1024, fs=FS_DEFAULT, noise_dbfs=-62.0, carriers=None,
                frame_no=0, avg_count=64, seed=0):
    """造一帧假的频谱，用于测试显示和检测。

    carriers: [(相对频偏Hz, 相对噪声底的dB, 带宽bin数), ...]
    """
    import math
    import random
    rnd = random.Random(seed)

    # 噪声：指数分布（功率谱的统计特性），平均到噪声底
    bins = []
    for _ in range(n):
        u = rnd.random()
        v = -math.log(max(u, 1e-9))            # 指数分布，均值 1
        bins.append(noise_dbfs + 10.0 * math.log10(max(v, 1e-6)))

    rbw = float(fs) / n
    for (f_hz, snr_db, width_bins) in (carriers or []):
        c = int(round(n / 2.0 + f_hz / rbw))
        for j in range(max(1, int(width_bins))):
            for idx in (c - j, c + j):
                if 0 <= idx < n:
                    target = noise_dbfs + snr_db
                    # 对数域平滑叠加
                    bins[idx] = 10.0 * math.log10(
                        10 ** (bins[idx] / 10.0) + 10 ** (target / 10.0))
    return SpectrumFrame(bins, fs, 0, frame_no, avg_count,
                         noise_dbfs, max(bins), False)


# =====================================================================
if __name__ == "__main__":
    print("=== 自检：编解码往返 ===")
    fr = synth_frame(n=256, carriers=[(-3.0e6, 25, 3), (2.0e6, 15, 1)], seed=1)
    blob = encode_frame(fr.bins, fs=fr.fs, frame_no=7, avg_count=32)
    print("  帧长 %d 字节（N=256 应为 %d）" % (len(blob), 26 + 256))

    got, used = decode_frame(blob)
    assert got is not None and used == len(blob), "解码失败"
    print("  ", got)
    err = max(abs(a - b) for a, b in zip(fr.bins, got.bins))
    print("  往返最大误差 %.4f dB（uint8 = 1 dB 步进，理论上限 0.5 dB）" % err)
    assert err < 0.51, "量化误差超标"

    print("\n=== 自检：垃圾 + 分片 ===")
    stream = b"\x11\x22\x33" + blob + b"\xff" + blob
    got2, used2 = decode_frame(stream)
    print("  跳过 %d 字节垃圾后解出 %r" % (used2 - 0, got2))
    half = blob[:100]
    g3, u3 = decode_frame(half)
    print("  分片（前 100 字节）-> %r, 消耗 %d（应为 None/0）" % (g3, u3))
    assert g3 is None and u3 == 0

    print("\n=== 自检：CRC 检错 ===")
    bad = bytearray(blob)
    bad[30] ^= 0x01
    g4, u4 = decode_frame(bytes(bad))
    print("  单比特翻转 -> %r, 消耗 %d（应跳过同步头=2）" % (g4, u4))
    assert g4 is None and u4 == 2

    print("\n全部自检通过。")
