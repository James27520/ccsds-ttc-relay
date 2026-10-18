--------------------------------------------------------------------------------
-- tb_datalink.vhd -- 定位 CCSDS 发射链"每个 16 位字最高 2 位错"的根因
--
-- 背景
-- ----
--   用已验证的接收机当仪器量 FPGA 发射链输出：取反后与期望 CADU 相比，
--   每个 16 位字的【最高 2 位】错，672 位里错 42 位。
--   已用代码排除：编码器抽头、编码位序、SERDES、时钟比率、随机化器、映射器。
--
-- 本 TB 回答的问题：损坏在 coder 还是 BITSOUTPUTP？
--
-- 做法（避免 VHDL 层次引用，改用"直接把 coder 单独实例化"，它的输出就是 TB 的信号）
--   1) 用与 datalink 层完全相同的 generic 实例化 ccsds_tx_coder，
--      喂同一个 STATIC_FRAME（320 位），把它的 672 位并行输出写成 bit 串
--   2) 同时实例化 ccsds_tx_datalink_layer，把它的 16 位字输出流写成 hex
--   3) 两者交给 Python 对比
--
--   期望 coder 输出 = ASM(0x1ACFFC1D) ++ 640 编码位
--------------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use std.textio.all;

entity tb_datalink is
end tb_datalink;

architecture sim of tb_datalink is

  -- 与 ccsds_tx_datalink_layer.vhd:138 完全一致的静态帧，40 字节
  constant STATIC_FRAME : std_logic_vector(319 downto 0) :=
    x"02a00000180043435344532d36472d4e544e2d37" &
    x"3031302d5454432d465047412d504f5254210463";

  signal clk_dat : std_logic := '0';
  signal clk_bit : std_logic := '0';
  signal rst     : std_logic := '1';
  signal div     : integer range 0 to 3 := 0;

  -- coder 单独实例
  signal coder_data : std_logic_vector(671 downto 0);
  signal coder_val  : std_logic;

  -- datalink 实例
  signal dl_dat_i   : std_logic_vector(15 downto 0) := (others => '0');
  signal dl_dat_o   : std_logic_vector(15 downto 0);
  signal dl_nxt, dl_val, dl_idl : std_logic;

  function bits(v : std_logic_vector) return string is
    variable s : string(1 to v'length);
    variable k : integer := 1;
  begin
    for i in v'high downto v'low loop
      if    v(i) = '1' then s(k) := '1';
      elsif v(i) = '0' then s(k) := '0';
      else  s(k) := 'X';
      end if;
      k := k + 1;
    end loop;
    return s;
  end function;

  function hex4(v : std_logic_vector(3 downto 0)) return character is
    constant hx : string(1 to 16) := "0123456789ABCDEF";
    variable n : integer := 0;
  begin
    for i in 3 downto 0 loop
      n := n * 2;
      if v(i) = '1' then n := n + 1; end if;
    end loop;
    return hx(n+1);
  end function;

  function hex16(v : std_logic_vector(15 downto 0)) return string is
    variable s : string(1 to 4);
  begin
    s(1) := hex4(v(15 downto 12));
    s(2) := hex4(v(11 downto 8));
    s(3) := hex4(v(7 downto 4));
    s(4) := hex4(v(3 downto 0));
    return s;
  end function;

begin

  clk_dat <= not clk_dat after 5 ns;      -- 100 MHz

  CLKDIV: process (clk_dat)
  begin
    if rising_edge(clk_dat) then
      if div = 3 then
        div     <= 0;
        clk_bit <= not clk_bit;           -- clk_bit = clk_dat / 8
      else
        div <= div + 1;
      end if;
    end if;
  end process;

  ----------------------------------------------------------------------------
  -- 1) 编码器单独实例（generic 与 datalink 的第 205-220 行一致）
  ----------------------------------------------------------------------------
  CODER: entity work.ccsds_tx_coder
    generic map (
      CCSDS_TX_CODER_ASM_LENGTH                     => 4,
      CCSDS_TX_CODER_DATA_BUS_SIZE                  => 320,
      CCSDS_TX_CODER_DIFFERENTIAL_BITS_PER_CODEWORD => 1,
      CCSDS_TX_CODER_DIFFERENTIAL_ENABLED           => false,
      CCSDS_TX_CODER_OUTPUT_RATE                    => 2
    )
    port map (
      clk_i     => clk_dat,
      rst_i     => rst,
      dat_i     => STATIC_FRAME,
      dat_val_i => '1',
      dat_val_o => coder_val,
      dat_o     => coder_data
    );

  ----------------------------------------------------------------------------
  -- 2) datalink 实例
  ----------------------------------------------------------------------------
  DL: entity work.ccsds_tx_datalink_layer
    generic map (
      CCSDS_TX_DATALINK_DATA_BUS_SIZE                       => 16,
      CCSDS_TX_DATALINK_CODER_DIFFERENTIAL_BITS_PER_CODEWORD => 1
    )
    port map (
      clk_bit_i => clk_bit,
      clk_dat_i => clk_dat,
      dat_i     => dl_dat_i,
      dat_val_i => '1',
      rst_i     => rst,
      dat_o     => dl_dat_o,
      dat_nxt_o => dl_nxt,
      dat_val_o => dl_val,
      idl_o     => dl_idl
    );

  ----------------------------------------------------------------------------
  -- 转储 A：coder 的 672 位并行输出，采 8 次；全一样说明 coder 稳定
  ----------------------------------------------------------------------------
  CDUMP: process
    file fc : text;
    variable l : line;
    variable n : integer;
  begin
    wait for 2000 ns;
    file_open(fc, "E:/ccsds_fpga/sim/out/dl_coder.txt", write_mode);
    for n in 0 to 7 loop
      write(l, bits(coder_data));
      writeline(fc, l);
      wait for 1370 ns;                  -- 非 clk_dat 整数倍，避免总采同一相位
    end loop;
    file_close(fc);
    wait;
  end process;

  ----------------------------------------------------------------------------
  -- 转储 B：datalink 的 16 位字输出流（BITSOUTPUTP 的产物）
  ----------------------------------------------------------------------------
  WDUMP: process (clk_bit)
    file fw : text;
    variable l : line;
    variable started : boolean := false;
  begin
    if rising_edge(clk_bit) then
      if rst = '0' then
        if not started then
          file_open(fw, "E:/ccsds_fpga/sim/out/dl_words.txt", write_mode);
          started := true;
        end if;
        write(l, hex16(dl_dat_o));
        writeline(fw, l);
      end if;
    end if;
  end process;

  STIM: process
  begin
    rst <= '1';
    wait for 500 ns;
    rst <= '0';
    wait for 80 us;
    report "tb_datalink done" severity note;
    -- ★ 必须显式终止：时钟一直在跑，run -all 否则永不结束（踩过一次，
    --   仿真挂了十几分钟不返回）
    assert false report "SIMULATION FINISHED" severity failure;
    wait;
  end process;

end sim;
