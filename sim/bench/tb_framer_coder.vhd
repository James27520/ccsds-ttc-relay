------------------------------------------------------------------------------
---- tb_framer_coder -- isolate the framing and coding stages
----
---- Instantiates ccsds_tx_framer and ccsds_tx_coder back to back and dumps
---- BOTH output vectors as 16 bit chunks into two files:
----
----   sim/out/framer_bits.txt : the 160 bit frame (6 B header + 12 B payload
----                             + 2 B FECF), one 16 bit chunk per line
----   sim/out/coder_bits.txt  : the 352 bit CADU (4 B ASM + 2 x 160 coded),
----                             one 16 bit chunk per line
----
---- Python then compares chunk 0 with the most significant bits, i.e. the byte
---- order matches build_tm_frame / build_cadu (both MSB first).
----
---- This separates three questions that the full chain test cannot tell apart:
----   * does the framer build the header / FECF / bit order Python builds?
----   * does the randomiser produce Python's sequence, correctly aligned?
----   * does the convolutional encoder emit Python's bit order?
------------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.textio.all;

entity tb_framer_coder is
end tb_framer_coder;

architecture bench of tb_framer_coder is

  constant CLK_PERIOD    : time    := 10 ns;
  constant DATA_BUS_SIZE : integer := 16;
  constant PAYLOAD_WORDS : integer := 6;      -- 12 bytes
  constant FRAME_BITS    : integer := 160;    -- (6+12+2)*8
  constant CADU_BITS     : integer := 352;    -- 32 + 2*160

  type payload_rom_t is array (0 to PAYLOAD_WORDS-1) of std_logic_vector(15 downto 0);
  -- "CCSDS-6G-NTN"
  constant PAYLOAD_ROM : payload_rom_t := (
    x"4343", x"5344", x"532D", x"3647", x"2D4E", x"544E"
  );

  component ccsds_tx_framer is
    generic(
      CCSDS_TX_FRAMER_DATA_BUS_SIZE : integer;
      CCSDS_TX_FRAMER_DATA_LENGTH : integer;
      CCSDS_TX_FRAMER_FOOTER_LENGTH : integer;
      CCSDS_TX_FRAMER_HEADER_LENGTH : integer
    );
    port(
      clk_i: in std_logic;
      rst_i: in std_logic;
      dat_i: in std_logic_vector(CCSDS_TX_FRAMER_DATA_BUS_SIZE-1 downto 0);
      dat_val_i: in std_logic;
      dat_o: out std_logic_vector((CCSDS_TX_FRAMER_DATA_LENGTH+CCSDS_TX_FRAMER_HEADER_LENGTH+CCSDS_TX_FRAMER_FOOTER_LENGTH)*8-1 downto 0);
      dat_nxt_o: out std_logic;
      dat_val_o: out std_logic;
      idl_o: out std_logic
    );
  end component;

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

  signal clk : std_logic := '0';
  signal rst : std_logic := '1';

  signal framer_ptr  : integer range 0 to PAYLOAD_WORDS-1 := 0;
  signal framer_dat_i: std_logic_vector(15 downto 0) := PAYLOAD_ROM(0);
  signal framer_dat_o: std_logic_vector(FRAME_BITS-1 downto 0);
  signal framer_nxt  : std_logic;
  signal framer_val  : std_logic;
  signal framer_idl  : std_logic;

  signal coder_dat_o : std_logic_vector(CADU_BITS-1 downto 0);
  signal coder_val   : std_logic;

  -- rising-edge memories so one frame / CADU is dumped exactly once
  signal framer_val_d : std_logic := '0';
  signal coder_val_d  : std_logic := '0';
  signal done : boolean := false;

begin

  clk <= not clk after CLK_PERIOD/2;
  framer_dat_i <= PAYLOAD_ROM(framer_ptr);

  FRAMER_FEED: process (clk)
  begin
    if rising_edge(clk) then
      if (rst = '1') then
        framer_ptr <= 0;
      elsif (framer_nxt = '1') then
        if (framer_ptr = PAYLOAD_WORDS-1) then
          framer_ptr <= 0;
        else
          framer_ptr <= framer_ptr + 1;
        end if;
      end if;
    end if;
  end process;

  u_framer: ccsds_tx_framer
    generic map(
      CCSDS_TX_FRAMER_DATA_BUS_SIZE => DATA_BUS_SIZE,
      CCSDS_TX_FRAMER_DATA_LENGTH => 12,
      CCSDS_TX_FRAMER_FOOTER_LENGTH => 2,
      CCSDS_TX_FRAMER_HEADER_LENGTH => 6
    )
    port map(
      clk_i => clk,
      rst_i => rst,
      dat_i => framer_dat_i,
      dat_val_i => '1',
      dat_o => framer_dat_o,
      dat_nxt_o => framer_nxt,
      dat_val_o => framer_val,
      idl_o => framer_idl
    );

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
      dat_i => framer_dat_o,
      dat_val_i => framer_val,
      rst_i => rst,
      dat_o => coder_dat_o,
      dat_val_o => coder_val
    );

  -- dump the frame (10 x 16 bit chunks, most significant first)
  CAPTURE_FRAME: process (clk)
    file     f : text;
    variable l : line;
    variable n : integer := 0;
  begin
    if rising_edge(clk) then
      framer_val_d <= framer_val;
      if (framer_val = '1' and framer_val_d = '0' and n < 10) then
        if (n = 0) then
          file_open(f, "E:/ccsds_fpga/sim/out/framer_bits.txt", write_mode);
        end if;
        write(l, to_integer(unsigned(framer_dat_o(FRAME_BITS-1-n*16 downto FRAME_BITS-16-n*16))));
        writeline(f, l);
        n := n + 1;
        if (n = 10) then
          file_close(f);
          report "TB: framer dump complete" severity note;
        end if;
      end if;
    end if;
  end process;

  -- dump the CADU (22 x 16 bit chunks, most significant first)
  CAPTURE_CADU: process (clk)
    file     f : text;
    variable l : line;
    variable n : integer := 0;
  begin
    if rising_edge(clk) then
      coder_val_d <= coder_val;
      if (coder_val = '1' and coder_val_d = '0' and n < 22) then
        if (n = 0) then
          file_open(f, "E:/ccsds_fpga/sim/out/coder_bits.txt", write_mode);
        end if;
        write(l, to_integer(unsigned(coder_dat_o(CADU_BITS-1-n*16 downto CADU_BITS-16-n*16))));
        writeline(f, l);
        n := n + 1;
        if (n = 22) then
          file_close(f);
          report "TB: coder dump complete" severity note;
        end if;
      end if;
    end if;
  end process;

  STIMULUS: process
  begin
    rst <= '1';
    wait for 20*CLK_PERIOD;
    rst <= '0';
    wait for 20 us;
    report "TB: framer/coder isolate done" severity note;
    wait;
  end process;

end bench;
