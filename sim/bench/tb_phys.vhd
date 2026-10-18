--------------------------------------------------------------------------------
-- tb_phys.vhd -- 定位发射链剩下那"每个 16 位字最高 2 位错"的确切位置
--
-- 已确认（tb_datalink.vhd 实测）：
--   ccsds_tx_datalink_layer 的输出【完全正确】
--     · coder 的 672 位并行输出与期望 CADU 逐位差异 = 0
--     · BITSOUTPUTP 的 42 个 16 位字与期望全等
--   ⇒ 损坏在 datalink 之后：mapper / oversampler / SRRC 这条链上
--
-- 本 TB 的做法
-- ------------
--   用【真实时钟比】把 datalink 和 mapper 串起来：
--     clk_bit = clk_i/160   (整字搬运)
--     clk_dat = clk_i/20
--     clk_sym = clk_i/10    (mapper 的符号节拍，= 16 x clk_bit)
--   把 mapper 的 sym_i_o 逐拍写成 bit 流，与期望 CADU 对比。
--
--   判据：
--     · 符号流与期望 CADU 逐位相同      -> mapper 正确，问题在 oversampler/SRRC
--     · 符号流每个 16 位字头部错若干位  -> 确认是 mapper 窗口与字边界【相位未对齐】
--------------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use std.textio.all;

entity tb_phys is
end tb_phys;

architecture sim of tb_phys is

  constant PERIOD : time := 10 ns;      -- clk_i = 100 MHz

  signal clk_i   : std_logic := '0';
  signal clk_bit : std_logic := '0';
  signal clk_dat : std_logic := '0';
  signal clk_sym : std_logic := '0';
  signal rst     : std_logic := '1';

  -- 分频计数器
  signal cnt160 : integer range 0 to 159 := 0;
  signal cnt20  : integer range 0 to 19  := 0;
  signal cnt10  : integer range 0 to 9   := 0;

  -- datalink
  signal dl_dat_i : std_logic_vector(15 downto 0) := (others => '0');
  signal dl_dat_o : std_logic_vector(15 downto 0);
  signal dl_nxt, dl_val, dl_idl : std_logic;

  -- mapper
  signal sym_i, sym_q : std_logic_vector(0 downto 0);
  signal sym_val      : std_logic;

  signal running : boolean := true;

  function hex4c(v : std_logic_vector(3 downto 0)) return character is
    constant hx : string(1 to 16) := "0123456789ABCDEF";
    variable n : integer := 0;
  begin
    for i in 3 downto 0 loop
      n := n * 2;
      if v(i) = '1' then n := n + 1; end if;
    end loop;
    return hx(n+1);
  end function;

begin

  clk_i <= not clk_i after PERIOD/2 when running else '0';

  -- clk_bit = clk_i/160 ; clk_dat = clk_i/20 ; clk_sym = clk_i/10
  DIVS: process (clk_i)
  begin
    if rising_edge(clk_i) then
      -- /160
      if cnt160 = 159 then
        cnt160 <= 0; clk_bit <= not clk_bit;
      else
        cnt160 <= cnt160 + 1;
      end if;
      -- /20
      if cnt20 = 19 then
        cnt20 <= 0; clk_dat <= not clk_dat;
      else
        cnt20 <= cnt20 + 1;
      end if;
      -- /10
      if cnt10 = 9 then
        cnt10 <= 0; clk_sym <= not clk_sym;
      else
        cnt10 <= cnt10 + 1;
      end if;
    end if;
  end process;

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

  -- 与 ccsds_tx_physical_layer.vhd 里对 mapper 的实例化完全一致
  MAPPER1: entity work.ccsds_tx_mapper_bits_symbols
    generic map (
      CCSDS_TX_MAPPER_BITS_PER_SYMBOL => 1,
      CCSDS_TX_MAPPER_MODULATION_TYPE => 2,
      CCSDS_TX_MAPPER_DATA_BUS_SIZE   => 16
    )
    port map (
      clk_i     => clk_sym,
      dat_i     => dl_dat_o,
      dat_val_i => dl_val,
      rst_i     => rst,
      sym_i_o   => sym_i,
      sym_q_o   => sym_q,
      sym_val_o => sym_val
    );

  ----------------------------------------------------------------------------
  -- 转储：每个 clk_sym 上升沿记录一个符号位（sym_i_o(0)）
  ----------------------------------------------------------------------------
  SDUMP: process (clk_sym)
    file fs : text;
    variable l : line;
    variable started : boolean := false;
    variable n : integer := 0;
  begin
    if rising_edge(clk_sym) then
      if rst = '0' then
        if not started then
          file_open(fs, "E:/ccsds_fpga/sim/out/ph_sym.txt", write_mode);
          started := true;
        end if;
        -- 格式: <symbol> <datalink dat_o 的 hex> <dat_val_o>
        if sym_i(0) = '1' then
          write(l, character'('1'));
        else
          write(l, character'('0'));
        end if;
        write(l, string'(" "));
        write(l, hex4c(dl_dat_o(15 downto 12)));
        write(l, hex4c(dl_dat_o(11 downto 8)));
        write(l, hex4c(dl_dat_o(7 downto 4)));
        write(l, hex4c(dl_dat_o(3 downto 0)));
        write(l, string'(" "));
        if dl_val = '1' then
          write(l, character'('1'));
        else
          write(l, character'('0'));
        end if;
        writeline(fs, l);
        n := n + 1;
      end if;
    end if;
  end process;

  STIM: process
  begin
    rst <= '1';
    wait for 1000 ns;
    rst <= '0';
    wait for 1500 us;                 -- 足够覆盖 LFSR 填满(320 clk_dat=64us) + 多个 CADU
    report "tb_phys done" severity note;
    running <= false;
    assert false report "SIMULATION FINISHED" severity failure;
    wait;
  end process;

end sim;
