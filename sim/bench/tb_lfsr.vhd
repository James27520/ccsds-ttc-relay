------------------------------------------------------------------------------
---- tb_lfsr -- dump ccsds_rxtx_lfsr's sequence so it can be compared directly
----             with ccsds_tm_tx.rand_seq()
------------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.textio.all;

entity tb_lfsr is
end tb_lfsr;

architecture bench of tb_lfsr is

  constant CLK_PERIOD : time    := 10 ns;
  constant BUS_SIZE   : integer := 160;

  component ccsds_rxtx_lfsr is
    generic(
      constant CCSDS_RXTX_LFSR_DATA_BUS_SIZE: integer
    );
    port(
      clk_i: in std_logic;
      rst_i: in std_logic;
      dat_o: out std_logic_vector(CCSDS_RXTX_LFSR_DATA_BUS_SIZE-1 downto 0);
      dat_val_o: out std_logic
    );
  end component;

  signal clk      : std_logic := '0';
  signal rst      : std_logic := '1';
  signal lfsr_dat : std_logic_vector(BUS_SIZE-1 downto 0);
  signal lfsr_val : std_logic;
  signal captured : boolean := false;
  signal done     : boolean := false;

begin

  clk <= '0' when done else not clk after CLK_PERIOD/2;

  u_lfsr: ccsds_rxtx_lfsr
    generic map(
      CCSDS_RXTX_LFSR_DATA_BUS_SIZE => BUS_SIZE
    )
    port map(
      clk_i => clk,
      rst_i => rst,
      dat_o => lfsr_dat,
      dat_val_o => lfsr_val
    );

  CAPTURE: process (clk)
    file     f : text;
    variable l : line;
    variable n : integer;
  begin
    if rising_edge(clk) then
      if (lfsr_val = '1' and captured = false) then
        captured <= true;
        file_open(f, "E:/ccsds_fpga/sim/out/lfsr_bits.txt", write_mode);
        for n in 0 to (BUS_SIZE/16)-1 loop
          write(l, to_integer(unsigned(lfsr_dat(BUS_SIZE-1-n*16 downto BUS_SIZE-16-n*16))));
          writeline(f, l);
        end loop;
        file_close(f);
        report "TB: lfsr dump complete" severity note;
      end if;
    end if;
  end process;

  STIMULUS: process
  begin
    rst <= '1';
    wait for 20*CLK_PERIOD;
    rst <= '0';
    wait for 20 us;
    if not captured then
      report "TB: lfsr never became valid" severity failure;
    end if;
    report "TB: lfsr done" severity note;
    done <= true;
    wait;
  end process;

end bench;
