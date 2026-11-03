#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_adda_coe.py -- 为 Z7ADDALite（AD9122 DAC）生成 32768 点 × 16bit 的 .coe 波形

为什么是 32768 点
----------------
原厂例程 sin_wave.v 里：
    addr_reg 从 0 数到 32767 循环（ADDA_MAX = 32767）
    blk_mem_gen_0 (addra[14:0], douta[15:0])
⇒ ROM 深度固定 32768，宽度 16 bit，内容每 32768 个采样点循环一次。

所以本脚本生成的 .coe 就是"一整遍播放内容"，播完自动从头再来。

两种模式
--------
  tone : 生成一个单音，用来【标定 DAC 采样率 Fs】和【测衰减】
  text : 生成一段 BPSK 文本帧，用来做"转发内容"演示

用法
----
  # ① 标定用：按假设 Fs=250MSPS 生成 100 MHz 单音
  python gen_adda_coe.py --mode tone --fs 250e6 --if 100e6 --out sin_100m.coe

  # ② 标定算出真实 Fs 后，重新生成
  python gen_adda_coe.py --mode tone --fs 218.25e6 --if 100e6 --out sin_100m.coe

  # ③ 内容：把 "hello world" 用 BPSK 搬到 100 MHz 中频
  python gen_adda_coe.py --mode text --fs 218.25e6 --if 100e6 \
                         --text "hello world" --sps 48 --out text_hello.coe

  # ④ 看参数是否合理（不写文件）
  python gen_adda_coe.py --mode text --fs 218.25e6 --if 100e6 --text hi --dry-run

产物
----
  .coe 文件（radix 10，有符号，值域 -32767..32767），直接替换
      <例程>/matlab/sin32768b16.coe
  然后 Vivado 2018.3 重新综合、生成位流、下载即可。

⚠️ 前提与约束
--------------
  · AD9361 调谐下限 70 MHz ⇒ 中频 if 必须 ≥ 70 MHz（建议 90~110 MHz）
  · 中频必须 < Fs/2（奈奎斯特），否则混叠
  · 符号率 = fs / sps；转发板采样率 30.72 MSPS，带宽 ±15 MHz
  · DAC 无重构滤波器，会有 Fs±if 的镜像，靠转发板 RX 的 rf_bandwidth 抑制
"""
import argparse
import os
import sys

import numpy as np

# Windows 中文控制台默认 GBK，脚本里有 ✓/✗ 等字符会抛 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROM_DEPTH = 32768
FULL_SCALE = 32767

PREAMBLE = b"\xaa\xaa"


# ---------------------------------------------------------------------------
#  CRC-16/CCITT-FALSE（与接收端 rx_board.py 一致）
# ---------------------------------------------------------------------------
def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def bytes_to_bits(data: bytes):
    bits = []
    for b in data:
        for i in range(7, -1, -1):
            bits.append((b >> i) & 1)
    return np.array(bits, dtype=np.uint8)


# ---------------------------------------------------------------------------
#  SRRC
# ---------------------------------------------------------------------------
def srrc(beta=0.35, sps=8, span=6):
    n = span * sps
    t = np.arange(-n, n + 1) / sps
    h = np.zeros_like(t, dtype=float)
    for i, ti in enumerate(t):
        if abs(ti) < 1e-12:
            h[i] = 1.0 - beta + 4.0 * beta / np.pi
        elif abs(abs(ti) - 1.0 / (4.0 * beta)) < 1e-9:
            h[i] = (beta / np.sqrt(2.0)) * (
                (1 + 2 / np.pi) * np.sin(np.pi / (4 * beta)) +
                (1 - 2 / np.pi) * np.cos(np.pi / (4 * beta)))
        else:
            num = (np.sin(np.pi * ti * (1 - beta)) +
                   4 * beta * ti * np.cos(np.pi * ti * (1 + beta)))
            den = np.pi * ti * (1 - (4 * beta * ti) ** 2)
            h[i] = num / den
    return h / np.sqrt(np.sum(h ** 2))


# ---------------------------------------------------------------------------
def build_text_frame(text: str) -> bytes:
    """[AA AA][len][text][CRC16 big-endian]，与 rx_board.py 的解调一致"""
    body = text.encode("utf-8")
    if len(body) == 0 or len(body) > 200:
        raise ValueError("文本长度必须在 1..200 字节之间")
    return PREAMBLE + bytes([len(body)]) + body + crc16(body).to_bytes(2, "big")


def modulate_text(bits, fs, if_hz, sps, beta, amp_ratio):
    """BPSK + SRRC + 上变频到 if_hz，返回 float 数组（满量程归一化到 ±1）"""
    sym = 1.0 - 2.0 * bits.astype(float)          # bit1 -> -1, bit0 -> +1
    up = np.zeros(len(sym) * sps)
    up[::sps] = sym
    h = srrc(beta=beta, sps=sps)
    base = np.convolve(up, h, mode="same")
    m = np.max(np.abs(base))
    if m > 0:
        base = base / m
    t = np.arange(len(base)) / fs
    return (base * np.cos(2 * np.pi * if_hz * t)) * amp_ratio


def modulate_tone(fs, if_hz, amp_ratio):
    n = ROM_DEPTH
    t = np.arange(n) / fs
    return np.cos(2 * np.pi * if_hz * t) * amp_ratio


# ---------------------------------------------------------------------------
def write_coe(path, samples):
    """写 Xilinx .coe：radix 10，有符号，逗号分隔，每行一个值"""
    v = np.clip(np.round(samples), -FULL_SCALE, FULL_SCALE).astype(np.int32)
    with open(path, "w", newline="\n") as f:
        f.write("MEMORY_INITIALIZATION_RADIX = 10;\n")
        f.write("MEMORY_INITIALIZATION_VECTOR =\n")
        strs = [str(int(x)) for x in v]
        for i in range(0, len(strs), 16):
            chunk = strs[i:i + 16]
            sep = "," if i + 16 < len(strs) else ";"
            f.write(",".join(chunk) + sep + "\n")
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["tone", "text"], default="tone")
    ap.add_argument("--fs", type=float, default=250e6, help="DAC 采样率 Hz（未知时先假设 250e6）")
    ap.add_argument("--if", dest="if_hz", type=float, default=100e6, help="中频 Hz（必须 >=70e6）")
    ap.add_argument("--text", default="hello world")
    ap.add_argument("--sps", type=int, default=48, help="每符号采样点数（text 模式）")
    ap.add_argument("--beta", type=float, default=0.35)
    ap.add_argument("--amp", type=float, default=0.85, help="幅度占满量程的比例 0.1~0.95")
    ap.add_argument("--out", default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    print("=" * 74)
    print("  Z7ADDALite DAC 波形生成（32768 点 × 16 bit）")
    print("=" * 74)
    print("  模式      : %s" % a.mode)
    print("  DAC 采样率: %.3f MSPS%s" % (a.fs / 1e6,
          "" if a.fs != 250e6 else "   ← 假设值，需标定"))
    print("  中频      : %.3f MHz" % (a.if_hz / 1e6))
    print("  满量程    : ±%d（幅度 %.0f%%）" % (FULL_SCALE, a.amp * 100))

    if a.if_hz < 70e6:
        print("\n  ✗ 中频 %.1f MHz < 70 MHz，AD9361 收不到，请改高" % (a.if_hz / 1e6))
        return 2
    if a.if_hz >= a.fs / 2:
        print("\n  ✗ 中频 %.1f MHz >= Fs/2 = %.1f MHz，会混叠" % (a.if_hz / 1e6, a.fs / 2e6))
        return 2
    if not (0.05 <= a.amp <= 0.95):
        print("\n  ✗ --amp 应在 0.05~0.95")
        return 2

    if a.mode == "tone":
        wav = modulate_tone(a.fs, a.if_hz, a.amp) * FULL_SCALE
        print("\n  每 ROM 周期含 %.3f 个中频周期" % (a.if_hz * ROM_DEPTH / a.fs))
        print("  播放一遍耗时 %.3f ms" % (ROM_DEPTH / a.fs * 1e3))
        out = a.out or "tone_%.0fM.coe" % (a.if_hz / 1e6)
    else:
        frame = build_text_frame(a.text)
        bits = bytes_to_bits(frame)
        print("\n  文本      : %r（%d 字节）" % (a.text, len(a.text.encode())))
        print("  帧内容    : %s" % frame.hex())
        print("  比特数    : %d" % len(bits))
        sym_rate = a.fs / a.sps
        need = len(bits) * a.sps
        print("  符号率    : %.3f kSPS" % (sym_rate / 1e3))
        print("  占用带宽  : ≈ %.3f MHz（含滚降）" % (sym_rate * (1 + a.beta) / 1e6))
        print("  需要点数  : %d / %d %s" % (need, ROM_DEPTH,
              "✓ 装得下" if need <= ROM_DEPTH else "✗ 超了，请减小 --sps"))
        if need > ROM_DEPTH:
            return 3
        wav = modulate_text(bits, a.fs, a.if_hz, a.sps, a.beta, a.amp) * FULL_SCALE
        out = a.out or "text_%s.coe" % "".join(
            c if c.isalnum() else "_" for c in a.text)[:20]

    # 补齐到 32768 点
    if len(wav) < ROM_DEPTH:
        pad = np.zeros(ROM_DEPTH - len(wav))
        wav = np.concatenate([wav, pad])
        print("  尾部补零  : %d 点" % len(pad))
    wav = wav[:ROM_DEPTH]

    print("  输出点数  : %d" % len(wav))
    print("  峰值      : %.0f / %d" % (np.max(np.abs(wav)), FULL_SCALE))

    if a.dry_run:
        print("\n  --dry-run：不写文件")
        return 0

    v = write_coe(out, wav)
    print("\n  ✓ 已写入: %s（%d 字节）" % (out, os.path.getsize(out)))
    print("\n  下一步：")
    print("    1. 用这个文件覆盖 <例程>/Z7ADDA_SIN_16BIT.srcs/sources_1/ip/blk_mem_gen_0/*.coe")
    print("       （或例程 matlab/sin32768b16.coe，并在 IP 里重新加载）")
    print("    2. Vivado 2018.3 打开例程 → Generate Output Products → 综合实现")
    print("    3. 下载位流，SMA J6 输出")
    print("    4. 接收端：python rx_board.py --lo %.0f --fft" % (a.if_hz / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main())
