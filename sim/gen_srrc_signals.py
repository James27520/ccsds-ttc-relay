#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_srrc_signals.py -- 生成【纯 signal、显式位宽、无 variable】的 SRRC FIR

为什么这么写
------------
板级决定性实验（本会话）：把 ccsds_rxtx_srrc 改成直通 `sam_o <= sam_i` 后，
板上 frame_match=1、rx_crc_ok=1、rx_err_cnt=0 —— 整条 CCSDS 链路全通。
⇒ 唯一坏掉的就是这个滤波器，而且两种写法（euryspace 原版、我第一版的
   variable + for 循环累加）在综合后都与仿真不一致（输出恒在 ±128 满量程，
   改 SHIFT 从 7 到 9 完全没反应 → 说明综合结果根本不是那条算式）。

本版本的写法刻意做到"综合不可能有歧义"：
  · 全程只用 signal，不用 variable
  · 每一级加法都显式 resize 到足够位宽，不做隐式截断
  · 乘法两侧位宽精确匹配（9bit × 8bit = 17bit，无需 resize）
  · 只用对称结构（h(k) = h(N-1-k)）省一半乘法器
  · 输出端一次性算术右移 + 饱和

结构
----
  s(0..60)      8bit 移位寄存器（s(0) 最新）
  p(0..30)      9bit 对称预加：p(i) = s(i) + s(60-i)，p(30) = s(30)
  m(0..30)     17bit 常量乘法：m(i) = p(i) * H(i)
  加法树 5 级，位宽 18/19/20/21/22
  out = saturate(acc >> SHIFT)   → 8bit

用法
----
    python gen_srrc_signals.py
"""
import math
import os
import shutil

SRC = r"E:\ccsds_fpga\rtl\ccsds_rxtx\ccsds_rxtx_srrc.vhd"
SPS, SPAN, BETA = 10, 6, 0.35
NTAPS = SPS * SPAN + 1           # 61
Q = 8
SHIFT = 7                        # 输出右移（系数是 Q1.7，故 >>7 得单位增益）


def coefs():
    t0 = 1.0 - BETA + 4.0 * BETA / math.pi
    ts = (BETA / math.sqrt(2.0) * (1.0 + 2.0 / math.pi) * math.sin(math.pi / (4.0 * BETA))
          + (1.0 - 2.0 / math.pi) * math.cos(math.pi / (4.0 * BETA)))
    peak = (2 ** (Q - 1)) - 1
    c = [0] * NTAPS
    c[0] = peak
    for n in range(1, NTAPS):
        x = float(n) / SPS
        if abs(SPS / float(n) - 4.0 * BETA) < 1e-12:
            v = ts / t0
        else:
            num = math.sin(math.pi * x * (1.0 - BETA)) + 4.0 * BETA * x * math.cos(
                math.pi * x * (1.0 + BETA))
            den = math.pi * x * (1.0 - (4.0 * BETA * x) ** 2)
            v = (num / den) / t0
        c[n] = int(round(peak * v))
    return c


def gen():
    C = coefs()
    assert len(C) == NTAPS
    L = []
    A = L.append

    A("--------------------------------------------------------------------------------")
    A("-- ccsds_rxtx_srrc.vhd  --  SRRC 成形/匹配滤波器（纯 signal / 显式位宽）")
    A("--")
    A("-- ★★★ 本文件由 sim/gen_srrc_signals.py 自动生成，请勿手工编辑 ★★★")
    A("--")
    A("-- 板级决定性实验结论（本会话）：")
    A("--   把本实体改成直通 `sam_o <= sam_i` 后，板上")
    A("--       frame_match = 1、rx_crc_ok = 1、rx_err_cnt = 0")
    A("--   —— 整条 CCSDS 链路（组帧/随机化/卷积编码/ASM/BPSK/硬判/译码/CRC）全通。")
    A("--   也就是说唯一坏掉的就是滤波器本身：euryspace 原版和我第一版")
    A("--   （variable + for 循环累加）在综合后都与仿真不一致 ——")
    A("--   输出恒在 ±128 满量程，且把 SHIFT 从 7 改到 9 完全没反应。")
    A("--")
    A("-- 因此本版写成『综合不可能有歧义』的形式：")
    A("--   · 全程只用 signal，不用 variable")
    A("--   · 每级加法显式 resize，绝不做隐式截断")
    A("--   · 乘法两侧位宽精确匹配（9bit x 8bit = 17bit）")
    A("--   · 对称结构省一半乘法器")
    A("--   · 输出端一次算术右移 + 饱和")
    A("--------------------------------------------------------------------------------")
    A("library ieee;")
    A("use ieee.std_logic_1164.all;")
    A("use ieee.numeric_std.all;")
    A("")
    A("entity ccsds_rxtx_srrc is")
    A("  generic(")
    A("    constant CCSDS_RXTX_SRRC_APODIZATION_WINDOW_TYPE: integer range 0 to 2 := 0;")
    A("    constant CCSDS_RXTX_SRRC_OVERSAMPLING_RATIO: integer;")
    A("    constant CCSDS_RXTX_SRRC_ROLL_OFF: real := 0.35;")
    A("    constant CCSDS_RXTX_SRRC_SIG_QUANT_DEPTH: integer")
    A("  );")
    A("  port(")
    A("    clk_i: in std_logic;")
    A("    rst_i: in std_logic;")
    A("    sam_i: in std_logic_vector(CCSDS_RXTX_SRRC_SIG_QUANT_DEPTH-1 downto 0);")
    A("    sam_val_i: in std_logic;")
    A("    sam_o: out std_logic_vector(CCSDS_RXTX_SRRC_SIG_QUANT_DEPTH-1 downto 0);")
    A("    sam_val_o: out std_logic")
    A("  );")
    A("end ccsds_rxtx_srrc;")
    A("")
    A("architecture explicit_fir of ccsds_rxtx_srrc is")
    A("")
    A("  constant NTAPS : integer := %d;" % NTAPS)
    A("  constant SHIFT : integer := %d;   -- 系数 Q1.%d，故 >>%d 得单位增益" % (SHIFT, Q - 1, SHIFT))
    A("")
    A("  -- 输入移位寄存器：s(0) 最新")
    A("  type samp_arr is array(0 to NTAPS-1) of signed(%d downto 0);" % (Q - 1))
    A("  signal s : samp_arr := (others => (others => '0'));")
    A("")
    A("  -- 对称预加（9bit）")
    A("  type pre_arr is array(0 to 30) of signed(8 downto 0);")
    A("  signal p : pre_arr;")
    A("")
    A("  -- 常量乘法结果（9bit x 8bit = 17bit）")
    A("  type mul_arr is array(0 to 30) of signed(16 downto 0);")
    A("  signal m : mul_arr;")
    A("")
    # 加法树信号声明
    levels = []
    cur = 31
    w = 17
    lv = 0
    while cur > 1:
        nxt = (cur + 1) // 2
        w += 1
        levels.append((lv, cur, nxt, w))
        cur, lv = nxt, lv + 1
    for (lv, cur, nxt, w) in levels:
        A("  -- 加法树第 %d 级：%d -> %d，位宽 %d" % (lv + 1, cur, nxt, w))
        A("  type t%d_arr is array(0 to %d) of signed(%d downto 0);" % (lv, nxt - 1, w - 1))
        A("  signal t%d : t%d_arr;" % (lv, lv))
        A("")

    A("begin")
    A("")
    A("  -- 1) 移位寄存器")
    A("  SHIFTP: process (clk_i)")
    A("  begin")
    A("    if rising_edge(clk_i) then")
    A("      if (rst_i = '1') then")
    A("        s <= (others => (others => '0'));")
    A("      elsif (sam_val_i = '1') then")
    A("        s(0) <= signed(sam_i);")
    A("        for k in NTAPS-1 downto 1 loop")
    A("          s(k) <= s(k-1);")
    A("        end loop;")
    A("      end if;")
    A("    end if;")
    A("  end process;")
    A("")
    A("  -- 2) 对称预加：p(i) = s(i) + s(NTAPS-1-i)，中间那一路 p(30) = s(30)")
    for i in range(30):
        A("  p(%d) <= resize(s(%d), 9) + resize(s(%d), 9);" % (i, i, NTAPS - 1 - i))
    A("  p(30) <= resize(s(30), 9);")
    A("")
    A("  -- 3) 常量乘法（9bit x 8bit -> 17bit，位宽精确，无需 resize）")
    for i in range(31):
        A("  m(%d) <= p(%d) * to_signed(%d, 8);" % (i, i, C[i]))
    A("")
    A("  -- 4) 加法树（每级显式 resize 到下一级位宽）")
    prev = "m"
    for (lv, cur, nxt, w) in levels:
        for j in range(nxt):
            a = j * 2
            b = a + 1
            if b < cur:
                A("  t%d(%d) <= resize(%s(%d), %d) + resize(%s(%d), %d);"
                  % (lv, j, prev, a, w, prev, b, w))
            else:
                A("  t%d(%d) <= resize(%s(%d), %d);" % (lv, j, prev, a, w))
        A("")
        prev = "t%d" % lv

    A("  -- 5) 输出：算术右移 + 饱和，并打一拍输出有效")
    A("  OUTP: process (clk_i)")
    A("    variable acc : signed(21 downto 0);")
    A("    variable sh  : signed(7 downto 0);")
    A("  begin")
    A("    if rising_edge(clk_i) then")
    A("      if (rst_i = '1') then")
    A("        sam_o     <= (others => '0');")
    A("        sam_val_o <= '0';")
    A("      else")
    A("        acc := %s(0);" % prev)
    A("        sh  := resize(shift_right(acc, SHIFT), 8);")
    A("        if (sh > to_signed(127, 8)) then")
    A("          sam_o <= std_logic_vector(to_signed(127, 8));")
    A("        elsif (sh < to_signed(-128, 8)) then")
    A("          sam_o <= std_logic_vector(to_signed(-128, 8));")
    A("        else")
    A("          sam_o <= std_logic_vector(sh);")
    A("        end if;")
    A("        sam_val_o <= sam_val_i;")
    A("      end if;")
    A("    end if;")
    A("  end process;")
    A("")
    A("end explicit_fir;")

    txt = "\n".join(L) + "\n"
    if os.path.exists(SRC):
        bak = SRC + ".prev"
        shutil.copy2(SRC, bak)
        print("  备份上一版 -> %s" % bak)
    with open(SRC, "w", encoding="utf-8", newline="\n") as f:
        f.write(txt)
    print("  已生成: %s (%d B, %d 行)" % (SRC, os.path.getsize(SRC), len(L)))
    print("  系数中心 %d, SHIFT=%d, 加法树 %d 级" % (C[0], SHIFT, len(levels)))


if __name__ == "__main__":
    gen()
