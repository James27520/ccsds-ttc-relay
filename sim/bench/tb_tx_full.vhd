------------------------------------------------------------------------------
---- tb_tx_full -- does the FULL ccsds_tx (including the SRRC physical layer)
----               actually produce non-zero I/Q samples on sam_i_o ?
----
---- The earlier chain test deliberately left the physical layer out (the 61 tap
---- SRRC makes ModelSim crawl), so the sample output path itself was never
---- checked. If the mapper / oversampler / SRRC never asserts sam_val or emits
---- zeros, the DAC pins would carry a constant and the receiver would see
---- nothing -- which is exactly the symptom on the board.
------------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.textio.all;

entity tb_tx_full is
  generic(
    constant CLK_PERIOD  : time    := 10 ns;
    constant DUMP_SAMPLES: integer := 2000
  );
end tb_tx_full;

architecture bench of tb_tx_full is

  constant DATA_BUS_SIZE   : integer := 16;
  constant OVERSAMPLING    : integer := 10;
  constant SIG_QUANT_DEPTH : integer := 8;

  component ccsds_tx is
    generic (
      constant CCSDS_TX_BITS_PER_SYMBOL: integer;
      constant CCSDS_TX_BUFFER_SIZE: integer;
      constant CCSDS_TX_MODULATION_TYPE: integer;
      constant CCSDS_TX_DATA_BUS_SIZE: integer;
      constant CCSDS_TX_OVERSAMPLING_RATIO: integer;
      constant CCSDS_TX_PHYS_SIG_QUANT_DEPTH : integer
    );
    port(
      clk_i: in std_logic;
      dat_par_i: in std_logic_vector(CCSDS_TX_DATA_BUS_SIZE-1 downto 0);
      dat_ser_i: in std_logic;
      dat_val_i: in std_logic;
      ena_i: in std_logic;
      in_sel_i: in std_logic;
      rst_i: in std_logic;
      buf_ful_o: out std_logic;
      clk_o: out std_logic;
      ena_o: out std_logic;
      idl_o: out std_logic;
      sam_i_o: out std_logic_vector(CCSDS_TX_PHYS_SIG_QUANT_DEPTH-1 downto 0);
      sam_q_o: out std_logic_vector(CCSDS_TX_PHYS_SIG_QUANT_DEPTH-1 downto 0)
    );
  end component;

  signal clk    : std_logic := '0';
  signal rst    : std_logic := '1';
  signal sam_i  : std_logic_vector(SIG_QUANT_DEPTH-1 downto 0);
  signal sam_q  : std_logic_vector(SIG_QUANT_DEPTH-1 downto 0);
  signal buf_ful, clk_o, ena_o, idl_o : std_logic;
  signal done   : boolean := false;
  signal nz     : integer := 0;   -- non-zero sample count
  signal ntot   : integer := 0;   -- total samples seen

begin

  clk <= '0' when done else not clk after CLK_PERIOD/2;

  u: ccsds_tx
    generic map(
      CCSDS_TX_BITS_PER_SYMBOL      => 1,
      CCSDS_TX_BUFFER_SIZE          => 16,
      CCSDS_TX_MODULATION_TYPE      => 2,
      CCSDS_TX_DATA_BUS_SIZE        => DATA_BUS_SIZE,
      CCSDS_TX_OVERSAMPLING_RATIO   => OVERSAMPLING,
      CCSDS_TX_PHYS_SIG_QUANT_DEPTH => SIG_QUANT_DEPTH
    )
    port map(
      clk_i     => clk,
      dat_par_i => (others => '0'),
      dat_ser_i => '0',
      dat_val_i => '0',
      ena_i     => '1',
      in_sel_i  => '0',
      rst_i     => rst,
      buf_ful_o => buf_ful,
      clk_o     => clk_o,
      ena_o     => ena_o,
      idl_o     => idl_o,
      sam_i_o   => sam_i,
      sam_q_o   => sam_q
    );

  -- count / dump the first samples produced by the physical layer
  SAMPLE_WATCH: process (clk)
    file     f : text;
    variable l : line;
    variable n : integer := 0;
  begin
    if rising_edge(clk) then
      if (rst = '0') then
        ntot <= ntot + 1;
        if (sam_i /= std_logic_vector(to_signed(0, SIG_QUANT_DEPTH))) then
          nz <= nz + 1;
        end if;
        if (n < DUMP_SAMPLES and ntot > 5000) then
          if (n = 0) then
            file_open(f, "E:/ccsds_fpga/sim/out/tx_samples.txt", write_mode);
          end if;
          write(l, to_integer(signed(sam_i)));
          write(l, string'(" "));
          write(l, to_integer(signed(sam_q)));
          writeline(f, l);
          n := n + 1;
          if (n = DUMP_SAMPLES) then
            file_close(f);
            report "TB: dumped " & integer'image(n) & " samples" severity note;
          end if;
        end if;
      end if;
    end if;
  end process;

  STIMULUS: process
  begin
    rst <= '1';
    wait for 40*CLK_PERIOD;
    rst <= '0';
    -- 100 us is well past the 67.2 us a full CADU takes, so the physical layer
    -- has definitely had a chance to produce samples
    wait for 100 us;
    report "TB: total_clocks=" & integer'image(ntot) &
           " nonzero_samples=" & integer'image(nz) severity note;
    done <= true;
    wait;
  end process;

end bench;
