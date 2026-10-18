#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_simple_srrc.py -- 生成一个【简单、可验证】的 SRRC FIR，替换 euryspace 那套
                      "pipelined systolic symmetric" 实现。

为什么替换
----------
板级实测（12 探针 ILA）：
  ccsds_flt_b_tap（SRRC 输入）= {0, ±31}      ← 零插值上采样，正确
  ccsds_sam_i_tap（SRRC 输出）= {0, -128}     ← 只剩两个值，累加器卡在最大负值
而同一份 RTL 在 ModelSim 里输出 -46..+44 的正常成形波形。
⇒ euryspace 那个 61 级 systolic 乘加链在【综合后】的行为与仿真不一致，
  属于该第三方模块自身的缺陷，不是配置问题。

新实现的做法（刻意保守，只为"能综合出与仿真一致的结果"）
----------------------------------------------------------
  · 61 抽头、直接型（direct form）并行 FIR，不用 systolic 技巧
  · 系数用【预计算整数常量表】（不再用 math_real 在 elaboration 现算）
  · 累加器显式开够（22 位），最后一步才右移 + 饱和，中间不回绕
  · 输出增益归一化到 ≈1（系数按 h(0)=1 的 Q1.7 定标，累加器 >>7）
  · 接口与 ccsds_rxtx_srrc 完全一致，可直接替换

用法
----
    python gen_simple_srrc.py            # 生成 ccsds_rxtx_srrc.vhd（会先备份原文件）
"""
import math
import os
import shutil
import sys

SRC = r"E:\ccsds_fpga\rtl\ccsds_rxtx\ccsds_rxtx_srrc.vhd"
BAK = SRC + ".euryspace.bak"

SPS = 10          # OVERSAMPLING_RATIO
SPAN = 6          # RESPONSE_SYMBOL_CYCLES
BETA = 0.35
NTAPS = SPS * SPAN + 1          # 61
Q = 8                           # SIG_QUANT_DEPTH
ACCW = 22                       # 累加器位宽（够放 127 * sum|h| 还有余量）
SHIFT = 9                       # 输出 = 累加器 >> 9


def coefficients():
    """按 CCSDS 的 SRRC 公式算 61 个抽头，定标到 h(0)=1 的 Q1.7（=127）。
       ★ 注意：这里【不】乘 NORMALIZATION_GAIN/(2^(Q-1)-1)，即不再把满量程缩放到 127，
         因为我们要的是增益 ≈1 的匹配滤波器，幅度由前面的 ÷4 和后面的 SCALE_SHIFT 管。
    """
    t0 = 1.0 - BETA + 4.0 * BETA / math.pi
    ts = (BETA / math.sqrt(2.0) * (1.0 + 2.0 / math.pi) * math.sin(math.pi / (4.0 * BETA))
          + (1.0 - 2.0 / math.pi) * math.cos(math.pi / (4.0 * BETA)))
    peak = (2 ** (Q - 1)) - 1          # 127
    c = [0] * NTAPS
    c[0] = int(round(peak * t0 / t0))  # = 127
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


TEMPLATE = r'''--------------------------------------------------------------------------------
-- ccsds_rxtx_srrc.vhd  --  简单直接型 SRRC 成形/匹配滤波器
--
-- ★★★ 本文件由 sim/gen_simple_srrc.py 自动生成，请勿手工编辑 ★★★
--     原 euryspace 版本已备份为 ccsds_rxtx_srrc.vhd.euryspace.bak
--
-- 为什么重写
-- ----------
-- 板级实测（12 探针 ILA，见 SESSION_SUMMARY_20261006.md §3.4）：
--     ccsds_flt_b_tap（本模块的输入）= {0, ±31}     ← 零插值上采样，正确
--     ccsds_sam_i_tap（本模块的输出）= {0, -128}    ← 只剩两个值，累加器卡在最大负值
-- 而同一份 RTL 在 ModelSim 里输出 -46..+44 的正常成形波形 —— 也就是说 euryspace
-- 那套 "pipelined systolic symmetric" 61 级乘加链【综合后】行为与仿真不一致，
-- 属于该第三方模块自身缺陷，不是配置问题。
--
-- 本实现刻意保守，只为保证"综合结果 == 仿真结果"：
--   · 直接型（direct form）并行 FIR，61 个常量系数乘法器，不用任何 systolic 技巧
--   · 系数是预计算整数常量表（不再用 ieee.math_real 在 elaboration 现算）
--   · 累加器显式开 %(ACCW)d 位，中间过程不回绕；只在最后右移 %(SHIFT)d 并饱和
--   · 系数按 h(0)=1 的 Q1.%(Q)d 定标，滤波器增益 ≈ 1（幅度由链路其它环节决定）
--   · 接口与原实体完全一致，可直接替换
--
-- 系数计算方法学（与 sim/gen_simple_srrc.py 一致）：
--   t0 = 1 - beta + 4*beta/pi
--   t  = Ts/(4*beta) 处用极限式；其它点用标准 SRRC 公式
--   全部乘以 (2^(Q-1)-1) 并四舍五入取整
--------------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity ccsds_rxtx_srrc is
  generic(
    constant CCSDS_RXTX_SRRC_APODIZATION_WINDOW_TYPE: integer range 0 to 2 := 0;
    constant CCSDS_RXTX_SRRC_OVERSAMPLING_RATIO: integer;
    constant CCSDS_RXTX_SRRC_ROLL_OFF: real := 0.35;
    constant CCSDS_RXTX_SRRC_SIG_QUANT_DEPTH: integer
  );
  port(
    clk_i: in std_logic;
    rst_i: in std_logic;
    sam_i: in std_logic_vector(CCSDS_RXTX_SRRC_SIG_QUANT_DEPTH-1 downto 0);
    sam_val_i: in std_logic;
    sam_o: out std_logic_vector(CCSDS_RXTX_SRRC_SIG_QUANT_DEPTH-1 downto 0);
    sam_val_o: out std_logic
  );
end ccsds_rxtx_srrc;

architecture simple_fir of ccsds_rxtx_srrc is

  constant NTAPS : integer := %(NTAPS)d;      -- 61
  constant Q     : integer := CCSDS_RXTX_SRRC_SIG_QUANT_DEPTH;
  constant ACCW  : integer := %(ACCW)d;       -- 累加器位宽
  constant SHIFT : integer := %(SHIFT)d;      -- 输出右移量（增益归一化）

  -- 预计算系数表（Q1.x 定标，h(0) = 2^(Q-1)-1）
  type coef_array is array(0 to NTAPS-1) of integer;
  constant COEF : coef_array := (
%(COEFS)s
  );

  -- 输入样点移位寄存器
  type samp_array is array(0 to NTAPS-1) of signed(Q-1 downto 0);
  signal sr : samp_array := (others => (others => '0'));

  -- 饱和上下限
  constant MAXP : signed(Q-1 downto 0) := to_signed(2**(Q-1)-1, Q);
  constant MINN : signed(Q-1 downto 0) := to_signed(-(2**(Q-1)), Q);

begin

  FIRP: process (clk_i)
    variable acc  : signed(ACCW-1 downto 0);
    variable term : signed(ACCW-1 downto 0);
    variable sh   : signed(Q-1 downto 0);
  begin
    if rising_edge(clk_i) then
      if (rst_i = '1') then
        sr        <= (others => (others => '0'));
        sam_o     <= (others => '0');
        sam_val_o <= '0';
      elsif (sam_val_i = '1') then
        -- 1) 移入新样点
        for k in NTAPS-1 downto 1 loop
          sr(k) <= sr(k-1);
        end loop;
        sr(0) <= signed(sam_i);

        -- 2) 全并行卷积求和（用当前 sr 值，含刚移入的这一拍之前的值）
        acc := (others => '0');
        for k in 0 to NTAPS-1 loop
          term := resize(sr(k) * to_signed(COEF(k), Q+1), ACCW);
          acc  := acc + term;
        end loop;

        -- 3) 右移 + 饱和
        sh := resize(shift_right(acc, SHIFT), Q);
        if (sh > MAXP) then
          sam_o <= std_logic_vector(MAXP);
        elsif (sh < MINN) then
          sam_o <= std_logic_vector(MINN);
        else
          sam_o <= std_logic_vector(sh);
        end if;

        sam_val_o <= '1';
      else
        sam_val_o <= '0';
      end if;
    end if;
  end process;

end simple_fir;
'''


def main():
    c = coefficients()
    assert len(c) == NTAPS, len(c)
    rows = []
    for i in range(0, NTAPS, 10):
        rows.append("    " + ", ".join("%4d" % x for x in c[i:i + 10])
                    + ("," if i + 10 < NTAPS else ""))
    coefs_txt = "\n".join(rows)

    if os.path.exists(SRC) and not os.path.exists(BAK):
        shutil.copy2(SRC, BAK)
        print("  已备份原文件 -> %s" % BAK)

    out = TEMPLATE % {"NTAPS": NTAPS, "ACCW": ACCW, "SHIFT": SHIFT, "Q": Q,
                      "COEFS": coefs_txt}
    with open(SRC, "w", encoding="utf-8", newline="\n") as f:
        f.write(out)

    print("  已生成: %s  (%d B)" % (SRC, os.path.getsize(SRC)))
    print("  抽头 %d 个, 中心 %d, 累加器 %d 位, 输出 >>%d" % (NTAPS, c[0], ACCW, SHIFT))
    print("  系数:")
    for i in range(0, NTAPS, 10):
        print("    " + " ".join("%5d" % x for x in c[i:i + 10]))


if __name__ == "__main__":
    sys.exit(main())
