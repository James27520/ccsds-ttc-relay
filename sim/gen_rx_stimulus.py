#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_rx_stimulus.py -- 为 CCSDS 接收机生成【理想】参考激励

为什么需要它
------------
要验证 ccsds_rx_lvds.v 是否正确，必须给它一个【已知正确】的信号。
如果拿 FPGA 自己的发射链输出当激励，一旦解不出来就分不清是发射链错还是接收机错
（而发射链现在确实有一个未查清的 16 位字边界问题）。

所以这里用已经与参考逐位验证过的 Python 模型（ccsds_tm_tx.py）生成理想信号。

与 FPGA 对齐的关键参数
----------------------
  · 过采样比 OVERSAMPLING = 10        （ccsds_tx_lvds.v 里 OVERSAMPLING=10）
  · SRRC 抽头数  = 61                 （ccsds_rxtx_srrc.vhd: RESPONSE_SYMBOL_CYCLES=6
                                        → 系数数 = 10*6+1 = 61）
    而 ccsds_tm_tx.srrc() 的 span 参数给出 (span*sps+1) 抽头，所以要 span=6
    ★ 注意：默认 span=8 给出 81 抽头，与 FPGA 不符 —— 这里必须用 6
  · 滚降 β = 0.35、无窗（Dirichlet）    （ccsds_rxtx_srrc.vhd 里 PROJECT PATCH 改过的默认值）
  · BPSK 映射：bit0 → +, bit1 → -      （ccsds_tm_tx.cadu_to_iq 的约定）
  · 量化到 8 位有符号（FPGA 的 sam_i 是 8 位）

输出
----
  E:\\ccsds_fpga\\sim\\out\\rx_stim_i.mem    每行一个有符号十进制样点
  E:\\ccsds_fpga\\sim\\out\\rx_stim_meta.txt  帧内容、样点数、峰值等，供 testbench 对照
"""
import os
import sys

import numpy as np

sys.path.insert(0, r"E:\fpga_sdr_project\ccsds_ttc_loopback\sw\ttc")
from ccsds_tm_tx import build_cadu, build_tm_frame, srrc  # noqa: E402

OUT = r"E:\ccsds_fpga\sim\out"
os.makedirs(OUT, exist_ok=True)

# 发射端静态帧（ccsds_tx_datalink_layer.vhd:138），40 字节
FRAME_HEX = ("02a00000180043435344532d36472d4e544e2d37"
             "3031302d5454432d465047412d504f5254210463")
FRAME = bytes.fromhex(FRAME_HEX)

SPS   = 10        # 过采样比，与 FPGA 一致
SPAN  = 6         # ★ 6 -> 61 抽头，与 FPGA 的 SRRC 一致（默认 8 会得到 81 抽头）
BETA  = 0.35
AMP   = 100       # 8 位有符号，峰值取 100 留余量（FPGA 的 sam_i 是 ±127）

def main():
    print("=" * 78)
    print(" CCSDS 接收机理想激励生成")
    print("=" * 78)

    cadu, info = build_cadu(FRAME)
    cadu = np.asarray(cadu, dtype=np.uint8)
    print("  帧长 %d 字节, CADU %d bit (%s)" % (len(FRAME), len(cadu), info))

    h = srrc(BETA, SPS, span=SPAN)
    print("  SRRC: β=%.2f sps=%d span=%d -> %d 抽头" % (BETA, SPS, SPAN, len(h)))
    assert len(h) == SPS * SPAN + 1 == 61, "抽头数必须是 61，才与 FPGA 一致"

    # BPSK: bit0 -> +1, bit1 -> -1   （与 cadu_to_iq 一致）
    sym = np.where(cadu == 0, 1.0, -1.0)

    # 上采样（零插值）后 SRRC 成形
    up = np.zeros(len(sym) * SPS)
    up[::SPS] = sym
    bb = np.convolve(up, h, mode="full")

    # 归一化到 AMP 并量化到 int8
    pk = np.max(np.abs(bb)) or 1.0
    bb = bb / pk * AMP
    samp = np.clip(np.round(bb), -128, 127).astype(np.int8)

    # 前后各补一段 0，让接收机的 ASM 搜索有边界余量
    pad = np.zeros(200, dtype=np.int8)
    samp = np.concatenate([pad, samp, pad])

    print("  样点总数 %d (含前后各 200 个 0 的填充)" % len(samp))
    print("  峰值 %d  范围 [%d, %d]" % (int(np.max(np.abs(samp))), int(samp.min()), int(samp.max())))

    with open(os.path.join(OUT, "rx_stim_i.mem"), "w") as f:
        for v in samp:
            f.write("%d\n" % int(v))

    with open(os.path.join(OUT, "rx_stim_meta.txt"), "w") as f:
        f.write("frame_hex=%s\n" % FRAME_HEX)
        f.write("frame_bytes=%d\n" % len(FRAME))
        f.write("cadu_bits=%d\n" % len(cadu))
        f.write("samples=%d\n" % len(samp))
        f.write("sps=%d\n" % SPS)
        f.write("srrc_taps=%d\n" % len(h))
        f.write("pad=%d\n" % 200)
        f.write("peak=%d\n" % AMP)
        # 期望解出的帧（供 testbench 对照），40 字节 hex
        f.write("expected_frame=%s\n" % FRAME_HEX)

    print()
    print("  -> %s\\rx_stim_i.mem" % OUT)
    print("  -> %s\\rx_stim_meta.txt" % OUT)
    print()
    print("  期望解出的帧: %s" % FRAME_HEX)
    print("=" * 78)

if __name__ == "__main__":
    sys.exit(main())
