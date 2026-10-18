------------------------------------------------------------------------------
---- tb_coder_only -- unambiguous test of the patched coding stage
----
---- Drives ccsds_tx_coder with a HARDCODED 160 bit frame so there is no
---- handshake or sampling-timing question at all, then dumps the 352 bit CADU.
----
---- The frame is exactly what the ground reference builds:
----   build_tm_frame(scid=0x2A, vcid=0, mcfc=0, vcfc=0,
----                  data=b"CCSDS-6G-NTN", fecf=True)
----   = 02a000001800 43435344532d36472d4e544e 14d2
----     |-- header -| |------ payload -------| |CRC |
----
---- Python side (check_coder_only.py) compares the dump with
----   build_cadu(that frame) = asm ++ conv_encode(randomize(frame))
---- so a bit-identical result proves randomiser alignment, the convolutional
---- encoder and the ASM insertion are all correct.
------------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.textio.all;

entity tb_coder_only is
end tb_coder_only;

architecture bench of tb_coder_only is

  constant CLK_PERIOD : time    := 10 ns;
  constant FRAME_BITS : integer := 160;
  constant CADU_BITS  : integer := 352;

  -- build_tm_frame(scid=0x2A, vcid=0, mcfc=0, vcfc=0, data=b"CCSDS-6G-NTN")
  constant TEST_FRAME : std_logic_vector(FRAME_BITS-1 downto 0) :=
    x"02a00000180043435344532d36472d4e544e14d2";

  component ccsds_tx_coder is
    generic(
      CCSDS_TX_CODER_ASM_LENGTH: integer;
      CCSDS_TX_CODER_DATA_BUS_SIZE: integer;
      CCSDS_TX_CODER_DIFFERENTIAL_BITS_PER_CODEWORD: integer;
      CCSDS_TX_CODER_DIFFERENTIAL_ENABLED: boolean;
      CCSDS_TX_CODER_OUTPUT_RATE: integer := 2
    );
    port(
      clk_i: in std_logic;
      dat_i: in std_logic_vector(CCSDS_TX_CODER_DATA_BUS_SIZE-1 downto 0);
      dat_val_i: in std_logic;
      rst_i: in std_logic;
      dat_o: out std_logic_vector(CCSDS_TX_CODER_DATA_BUS_SIZE*CCSDS_TX_CODER_OUTPUT_RATE+CCSDS_TX_CODER_ASM_LENGTH*8-1 downto 0);
      dat_val_o: out std_logic
    );
  end component;

  signal clk       : std_logic := '0';
  signal rst       : std_logic := '1';
  signal dat_val_i : std_logic := '0';
  signal coder_dat_o : std_logic_vector(CADU_BITS-1 downto 0);
  signal coder_val   : std_logic;

  signal pulse_cnt : integer := 0;
  signal captured  : boolean := false;
  -- stops the clock generator so `run -all` returns and vsim exits cleanly
  signal done      : boolean := false;

begin

  clk <= '0' when done else not clk after CLK_PERIOD/2;

  -- the randomiser LFSR needs FRAME_BITS clocks after reset before it is ready,
  -- so pulse dat_val_i well after that
  VALID_PULSE: process (clk)
  begin
    if rising_edge(clk) then
      if (rst = '1') then
        pulse_cnt <= 0;
        dat_val_i <= '0';
      else
        pulse_cnt <= pulse_cnt + 1;
        if (pulse_cnt = 300) then
          dat_val_i <= '1';
        else
          dat_val_i <= '0';
        end if;
      end if;
    end if;
  end process;

  u_coder: ccsds_tx_coder
    generic map(
      CCSDS_TX_CODER_ASM_LENGTH => 4,
      CCSDS_TX_CODER_DATA_BUS_SIZE => FRAME_BITS,
      CCSDS_TX_CODER_DIFFERENTIAL_BITS_PER_CODEWORD => 1,
      CCSDS_TX_CODER_DIFFERENTIAL_ENABLED => false,
      CCSDS_TX_CODER_OUTPUT_RATE => 2
    )
    port map(
      clk_i => clk,
      dat_i => TEST_FRAME,
      dat_val_i => dat_val_i,
      rst_i => rst,
      dat_o => coder_dat_o,
      dat_val_o => coder_val
    );

  -- dump the CADU once, when dat_val_o is observed high
  CAPTURE: process (clk)
    file     f : text;
    variable l : line;
    variable n : integer := 0;
  begin
    if rising_edge(clk) then
      if (coder_val = '1' and captured = false) then
        captured <= true;
        file_open(f, "E:/ccsds_fpga/sim/out/coder_only_bits.txt", write_mode);
        for n in 0 to (CADU_BITS/16)-1 loop
          write(l, to_integer(unsigned(coder_dat_o(CADU_BITS-1-n*16 downto CADU_BITS-16-n*16))));
          writeline(f, l);
        end loop;
        file_close(f);
        report "TB: coder-only dump complete" severity note;
      end if;
    end if;
  end process;

  STIMULUS: process
  begin
    rst <= '1';
    wait for 20*CLK_PERIOD;
    rst <= '0';
    wait for 10 us;
    if not captured then
      report "TB: coder never produced a valid CADU" severity failure;
    end if;
    report "TB: coder-only done" severity note;
    done <= true;
    wait;
  end process;

end bench;
