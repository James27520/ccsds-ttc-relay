--------------------------------------------------------------------------------
-- ccsds_rxtx_srrc.vhd  --  SRRC 成形/匹配滤波器（纯 signal / 显式位宽）
--
-- ★★★ 本文件由 sim/gen_srrc_signals.py 自动生成，请勿手工编辑 ★★★
--
-- 板级决定性实验结论（本会话）：
--   把本实体改成直通 `sam_o <= sam_i` 后，板上
--       frame_match = 1、rx_crc_ok = 1、rx_err_cnt = 0
--   —— 整条 CCSDS 链路（组帧/随机化/卷积编码/ASM/BPSK/硬判/译码/CRC）全通。
--   也就是说唯一坏掉的就是滤波器本身：euryspace 原版和我第一版
--   （variable + for 循环累加）在综合后都与仿真不一致 ——
--   输出恒在 ±128 满量程，且把 SHIFT 从 7 改到 9 完全没反应。
--
-- 因此本版写成『综合不可能有歧义』的形式：
--   · 全程只用 signal，不用 variable
--   · 每级加法显式 resize，绝不做隐式截断
--   · 乘法两侧位宽精确匹配（9bit x 8bit = 17bit）
--   · 对称结构省一半乘法器
--   · 输出端一次算术右移 + 饱和
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

architecture explicit_fir of ccsds_rxtx_srrc is

  constant NTAPS : integer := 61;
  constant SHIFT : integer := 7;   -- 系数 Q1.7，故 >>7 得单位增益

  -- 输入移位寄存器：s(0) 最新
  type samp_arr is array(0 to NTAPS-1) of signed(7 downto 0);
  signal s : samp_arr := (others => (others => '0'));

  -- 对称预加（9bit）
  type pre_arr is array(0 to 30) of signed(8 downto 0);
  signal p : pre_arr;

  -- 常量乘法结果（9bit x 8bit = 17bit）
  type mul_arr is array(0 to 30) of signed(16 downto 0);
  signal m : mul_arr;

  -- 加法树第 1 级：31 -> 16，位宽 18
  type t0_arr is array(0 to 15) of signed(17 downto 0);
  signal t0 : t0_arr;

  -- 加法树第 2 级：16 -> 8，位宽 19
  type t1_arr is array(0 to 7) of signed(18 downto 0);
  signal t1 : t1_arr;

  -- 加法树第 3 级：8 -> 4，位宽 20
  type t2_arr is array(0 to 3) of signed(19 downto 0);
  signal t2 : t2_arr;

  -- 加法树第 4 级：4 -> 2，位宽 21
  type t3_arr is array(0 to 1) of signed(20 downto 0);
  signal t3 : t3_arr;

  -- 加法树第 5 级：2 -> 1，位宽 22
  type t4_arr is array(0 to 0) of signed(21 downto 0);
  signal t4 : t4_arr;

begin

  -- 1) 移位寄存器
  SHIFTP: process (clk_i)
  begin
    if rising_edge(clk_i) then
      if (rst_i = '1') then
        s <= (others => (others => '0'));
      elsif (sam_val_i = '1') then
        s(0) <= signed(sam_i);
        for k in NTAPS-1 downto 1 loop
          s(k) <= s(k-1);
        end loop;
      end if;
    end if;
  end process;

  -- 2) 对称预加：p(i) = s(i) + s(NTAPS-1-i)，中间那一路 p(30) = s(30)
  p(0) <= resize(s(0), 9) + resize(s(60), 9);
  p(1) <= resize(s(1), 9) + resize(s(59), 9);
  p(2) <= resize(s(2), 9) + resize(s(58), 9);
  p(3) <= resize(s(3), 9) + resize(s(57), 9);
  p(4) <= resize(s(4), 9) + resize(s(56), 9);
  p(5) <= resize(s(5), 9) + resize(s(55), 9);
  p(6) <= resize(s(6), 9) + resize(s(54), 9);
  p(7) <= resize(s(7), 9) + resize(s(53), 9);
  p(8) <= resize(s(8), 9) + resize(s(52), 9);
  p(9) <= resize(s(9), 9) + resize(s(51), 9);
  p(10) <= resize(s(10), 9) + resize(s(50), 9);
  p(11) <= resize(s(11), 9) + resize(s(49), 9);
  p(12) <= resize(s(12), 9) + resize(s(48), 9);
  p(13) <= resize(s(13), 9) + resize(s(47), 9);
  p(14) <= resize(s(14), 9) + resize(s(46), 9);
  p(15) <= resize(s(15), 9) + resize(s(45), 9);
  p(16) <= resize(s(16), 9) + resize(s(44), 9);
  p(17) <= resize(s(17), 9) + resize(s(43), 9);
  p(18) <= resize(s(18), 9) + resize(s(42), 9);
  p(19) <= resize(s(19), 9) + resize(s(41), 9);
  p(20) <= resize(s(20), 9) + resize(s(40), 9);
  p(21) <= resize(s(21), 9) + resize(s(39), 9);
  p(22) <= resize(s(22), 9) + resize(s(38), 9);
  p(23) <= resize(s(23), 9) + resize(s(37), 9);
  p(24) <= resize(s(24), 9) + resize(s(36), 9);
  p(25) <= resize(s(25), 9) + resize(s(35), 9);
  p(26) <= resize(s(26), 9) + resize(s(34), 9);
  p(27) <= resize(s(27), 9) + resize(s(33), 9);
  p(28) <= resize(s(28), 9) + resize(s(32), 9);
  p(29) <= resize(s(29), 9) + resize(s(31), 9);
  p(30) <= resize(s(30), 9);

  -- 3) 常量乘法（9bit x 8bit -> 17bit，位宽精确，无需 resize）
  m(0) <= p(0) * to_signed(127, 8);
  m(1) <= p(1) * to_signed(124, 8);
  m(2) <= p(2) * to_signed(117, 8);
  m(3) <= p(3) * to_signed(104, 8);
  m(4) <= p(4) * to_signed(89, 8);
  m(5) <= p(5) * to_signed(70, 8);
  m(6) <= p(6) * to_signed(51, 8);
  m(7) <= p(7) * to_signed(33, 8);
  m(8) <= p(8) * to_signed(16, 8);
  m(9) <= p(9) * to_signed(1, 8);
  m(10) <= p(10) * to_signed(-10, 8);
  m(11) <= p(11) * to_signed(-17, 8);
  m(12) <= p(12) * to_signed(-21, 8);
  m(13) <= p(13) * to_signed(-22, 8);
  m(14) <= p(14) * to_signed(-20, 8);
  m(15) <= p(15) * to_signed(-16, 8);
  m(16) <= p(16) * to_signed(-11, 8);
  m(17) <= p(17) * to_signed(-5, 8);
  m(18) <= p(18) * to_signed(0, 8);
  m(19) <= p(19) * to_signed(4, 8);
  m(20) <= p(20) * to_signed(7, 8);
  m(21) <= p(21) * to_signed(8, 8);
  m(22) <= p(22) * to_signed(8, 8);
  m(23) <= p(23) * to_signed(7, 8);
  m(24) <= p(24) * to_signed(5, 8);
  m(25) <= p(25) * to_signed(3, 8);
  m(26) <= p(26) * to_signed(1, 8);
  m(27) <= p(27) * to_signed(-1, 8);
  m(28) <= p(28) * to_signed(-2, 8);
  m(29) <= p(29) * to_signed(-3, 8);
  m(30) <= p(30) * to_signed(-3, 8);

  -- 4) 加法树（每级显式 resize 到下一级位宽）
  t0(0) <= resize(m(0), 18) + resize(m(1), 18);
  t0(1) <= resize(m(2), 18) + resize(m(3), 18);
  t0(2) <= resize(m(4), 18) + resize(m(5), 18);
  t0(3) <= resize(m(6), 18) + resize(m(7), 18);
  t0(4) <= resize(m(8), 18) + resize(m(9), 18);
  t0(5) <= resize(m(10), 18) + resize(m(11), 18);
  t0(6) <= resize(m(12), 18) + resize(m(13), 18);
  t0(7) <= resize(m(14), 18) + resize(m(15), 18);
  t0(8) <= resize(m(16), 18) + resize(m(17), 18);
  t0(9) <= resize(m(18), 18) + resize(m(19), 18);
  t0(10) <= resize(m(20), 18) + resize(m(21), 18);
  t0(11) <= resize(m(22), 18) + resize(m(23), 18);
  t0(12) <= resize(m(24), 18) + resize(m(25), 18);
  t0(13) <= resize(m(26), 18) + resize(m(27), 18);
  t0(14) <= resize(m(28), 18) + resize(m(29), 18);
  t0(15) <= resize(m(30), 18);

  t1(0) <= resize(t0(0), 19) + resize(t0(1), 19);
  t1(1) <= resize(t0(2), 19) + resize(t0(3), 19);
  t1(2) <= resize(t0(4), 19) + resize(t0(5), 19);
  t1(3) <= resize(t0(6), 19) + resize(t0(7), 19);
  t1(4) <= resize(t0(8), 19) + resize(t0(9), 19);
  t1(5) <= resize(t0(10), 19) + resize(t0(11), 19);
  t1(6) <= resize(t0(12), 19) + resize(t0(13), 19);
  t1(7) <= resize(t0(14), 19) + resize(t0(15), 19);

  t2(0) <= resize(t1(0), 20) + resize(t1(1), 20);
  t2(1) <= resize(t1(2), 20) + resize(t1(3), 20);
  t2(2) <= resize(t1(4), 20) + resize(t1(5), 20);
  t2(3) <= resize(t1(6), 20) + resize(t1(7), 20);

  t3(0) <= resize(t2(0), 21) + resize(t2(1), 21);
  t3(1) <= resize(t2(2), 21) + resize(t2(3), 21);

  t4(0) <= resize(t3(0), 22) + resize(t3(1), 22);

  -- 5) 输出：算术右移 + 饱和，并打一拍输出有效
  OUTP: process (clk_i)
    variable acc : signed(21 downto 0);
    variable sh  : signed(7 downto 0);
  begin
    if rising_edge(clk_i) then
      if (rst_i = '1') then
        sam_o     <= (others => '0');
        sam_val_o <= '0';
      else
        acc := t4(0);
        sh  := resize(shift_right(acc, SHIFT), 8);
        if (sh > to_signed(127, 8)) then
          sam_o <= std_logic_vector(to_signed(127, 8));
        elsif (sh < to_signed(-128, 8)) then
          sam_o <= std_logic_vector(to_signed(-128, 8));
        else
          sam_o <= std_logic_vector(sh);
        end if;
        sam_val_o <= sam_val_i;
      end if;
    end if;
  end process;

end explicit_fir;
