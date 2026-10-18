------------------------------------------------------------------------------
---- tb_ccsds_tx_chain -- end-to-end check of the patched euryspace TX chain
----
---- Instantiates the same four blocks as ccsds_tx.vhd (manager / buffer /
---- datalink / physical layer) but keeps the datalink output bus visible, so
---- the CADU words actually handed to the symbol mapper can be dumped to a
---- file and fed to the verified Python ground receiver
---- (sw/ttc/ccsds_tm_tx.py :: decode_cadu).
----
---- Configuration is the telemetry-board one:
----   BPSK, 1 bit/symbol, 16 bit datalink bus, oversampling ratio 10
----   -> symbol rate = clk_i/10, i.e. 250 ksym/s when the AD9363 runs at
----      2.5 MSPS (clk_i == DATA_CLK == sample rate)
----
---- Payload fed to the framer: the 12 ASCII bytes "CCSDS-6G-NTN".
------------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.textio.all;

entity tb_ccsds_tx_chain is
  generic(
    constant TB_CLK_PERIOD   : time    := 10 ns;
    constant TB_CAPTURE_WORDS: integer := 126   -- 3 CADUs of 42 words (672 bit)
  );
end tb_ccsds_tx_chain;

architecture bench of tb_ccsds_tx_chain is

  constant DATA_BUS_SIZE   : integer := 16;
  constant OVERSAMPLING    : integer := 10;
  constant SIG_QUANT_DEPTH : integer := 8;
  constant PAYLOAD_WORDS   : integer := 16;   -- 32 byte payload
  -- clk_dat cycles between two payload words presented to the framer.
  -- See the comment in PAYLOAD_FEED for why this must not be 1.
  constant PACE_PERIOD     : integer := 10;

  -- "CCSDS-6G-NTN-7010-TTC-FPGA-PORT!" as 16 big-endian 16 bit words
  type payload_rom_t is array (0 to PAYLOAD_WORDS-1) of std_logic_vector(15 downto 0);
  constant PAYLOAD_ROM : payload_rom_t := (
    x"4343", x"5344", x"532D", x"3647",
    x"2D4E", x"544E", x"2D37", x"3031",
    x"302D", x"5454", x"432D", x"4650",
    x"4741", x"2D50", x"4F52", x"5421"
  );

  component ccsds_tx_manager is
    generic(
      CCSDS_TX_MANAGER_BITS_PER_SYMBOL: integer;
      CCSDS_TX_MANAGER_MODULATION_TYPE: integer;
      CCSDS_TX_MANAGER_OVERSAMPLING_RATIO: integer;
      CCSDS_TX_MANAGER_DATA_BUS_SIZE : integer
    );
    port(
      clk_i: in std_logic;
      clk_bit_o: out std_logic;
      clk_dat_o: out std_logic;
      clk_sam_o: out std_logic;
      clk_sym_o: out std_logic;
      rst_i: in std_logic;
      ena_i: in std_logic;
      ena_o: out std_logic;
      in_sel_i: in std_logic;
      dat_par_i: in std_logic_vector(CCSDS_TX_MANAGER_DATA_BUS_SIZE-1 downto 0);
      dat_ser_i: in std_logic;
      dat_val_i: in std_logic;
      dat_val_o: out std_logic;
      dat_o: out std_logic_vector(CCSDS_TX_MANAGER_DATA_BUS_SIZE-1 downto 0)
    );
  end component;

  component ccsds_rxtx_buffer is
    generic(
      constant CCSDS_RXTX_BUFFER_DATA_BUS_SIZE : integer;
      constant CCSDS_RXTX_BUFFER_SIZE : integer
    );
    port(
      clk_i: in std_logic;
      dat_i: in std_logic_vector(CCSDS_RXTX_BUFFER_DATA_BUS_SIZE-1 downto 0);
      dat_val_i: in std_logic;
      dat_nxt_i: in std_logic;
      rst_i: in std_logic;
      buf_emp_o: out std_logic;
      buf_ful_o: out std_logic;
      dat_o: out std_logic_vector(CCSDS_RXTX_BUFFER_DATA_BUS_SIZE-1 downto 0);
      dat_val_o: out std_logic
    );
  end component;

  component ccsds_tx_datalink_layer is
    generic(
      CCSDS_TX_DATALINK_DATA_BUS_SIZE: integer;
      CCSDS_TX_DATALINK_CODER_DIFFERENTIAL_BITS_PER_CODEWORD: integer
    );
    port(
      clk_bit_i: in std_logic;
      clk_dat_i: in std_logic;
      rst_i: in std_logic;
      dat_val_i: in std_logic;
      dat_i: in std_logic_vector(CCSDS_TX_DATALINK_DATA_BUS_SIZE-1 downto 0);
      dat_val_o: out std_logic;
      dat_o: out std_logic_vector(CCSDS_TX_DATALINK_DATA_BUS_SIZE-1 downto 0);
      dat_nxt_o: out std_logic;
      idl_o: out std_logic
    );
  end component;

  component ccsds_tx_physical_layer is
    generic(
      CCSDS_TX_PHYSICAL_BITS_PER_SYMBOL: integer;
      CCSDS_TX_PHYSICAL_MODULATION_TYPE: integer;
      CCSDS_TX_PHYSICAL_DATA_BUS_SIZE: integer;
      CCSDS_TX_PHYSICAL_OVERSAMPLING_RATIO: integer;
      CCSDS_TX_PHYSICAL_SIG_QUANT_DEPTH: integer
    );
    port(
      clk_sam_i: in std_logic;
      clk_sym_i: in std_logic;
      rst_i: in std_logic;
      sam_i_o: out std_logic_vector(CCSDS_TX_PHYSICAL_SIG_QUANT_DEPTH-1 downto 0);
      sam_q_o: out std_logic_vector(CCSDS_TX_PHYSICAL_SIG_QUANT_DEPTH-1 downto 0);
      dat_i: in std_logic_vector(CCSDS_TX_PHYSICAL_DATA_BUS_SIZE-1 downto 0);
      dat_val_i: in std_logic
    );
  end component;

  -- The physical layer (mapper + oversampler + 61 tap SRRC) is deliberately NOT
  -- instantiated here: this test only has to prove that the framing / randomiser
  -- / convolutional coder / ASM chain produces a CADU the ground receiver can
  -- decode. Leaving the SRRC out keeps the ModelSim run short (the filter would
  -- otherwise evaluate 61 constant multiplies on every one of 21k+ clocks).
  -- The SRRC itself is covered by the synthesis run in syn\synth_probe.tcl.


  signal clk    : std_logic := '0';
  signal rst    : std_logic := '1';
  signal ena    : std_logic := '1';

  signal wire_clk_bit : std_logic;
  signal wire_clk_dat : std_logic;
  signal wire_clk_sym : std_logic;

  signal wire_dat_nxt_buf  : std_logic;
  signal wire_dat_val_buf  : std_logic;
  signal wire_dat_val_dat  : std_logic;
  signal wire_dat_val_man  : std_logic;
  signal wire_dat_buf      : std_logic_vector(DATA_BUS_SIZE-1 downto 0);
  signal wire_dat_man      : std_logic_vector(DATA_BUS_SIZE-1 downto 0);
  signal wire_dat_dat      : std_logic_vector(DATA_BUS_SIZE-1 downto 0);

  -- payload source, mimics the adapter: present the next word at clk_dat,
  -- hold while the input buffer is full
  signal payload_ptr : integer range 0 to PAYLOAD_WORDS-1 := 0;
  signal payload_word: std_logic_vector(15 downto 0) := PAYLOAD_ROM(0);
  signal pace_cnt    : integer range 0 to PACE_PERIOD-1 := 0;
  signal buf_ful     : std_logic;
  signal dat_val_tx  : std_logic := '1';
  signal idle_seen   : std_logic;
  signal capture_done: boolean := false;
  -- stops the clock generator so `run -all` returns and vsim can quit
  signal done        : boolean := false;
  -- handshake diagnostics
  signal cnt_push   : integer := 0;   -- cycles the source presented a word
  signal cnt_manval : integer := 0;   -- manager accepted a word
  signal cnt_bufval : integer := 0;   -- buffer presented a word to the framer
  signal cnt_dnxt   : integer := 0;   -- framer asked the buffer for a word
  signal cnt_coder  : integer := 0;   -- coder produced a finished CADU

begin

  clk <= '0' when done else not clk after TB_CLK_PERIOD/2;

  tx_manager_0: ccsds_tx_manager
    generic map(
      CCSDS_TX_MANAGER_BITS_PER_SYMBOL => 1,
      CCSDS_TX_MANAGER_MODULATION_TYPE => 2,
      CCSDS_TX_MANAGER_OVERSAMPLING_RATIO => OVERSAMPLING,
      CCSDS_TX_MANAGER_DATA_BUS_SIZE => DATA_BUS_SIZE
    )
    port map(
      clk_i => clk,
      clk_bit_o => wire_clk_bit,
      clk_dat_o => wire_clk_dat,
      clk_sam_o => open,
      clk_sym_o => wire_clk_sym,
      rst_i => rst,
      ena_i => ena,
      ena_o => open,
      in_sel_i => '0',
      dat_par_i => payload_word,
      dat_ser_i => '0',
      dat_val_i => dat_val_tx,
      dat_val_o => wire_dat_val_man,
      dat_o => wire_dat_man
    );

  tx_buffer_0: ccsds_rxtx_buffer
    generic map(
      CCSDS_RXTX_BUFFER_DATA_BUS_SIZE => DATA_BUS_SIZE,
      CCSDS_RXTX_BUFFER_SIZE => 16
    )
    port map(
      clk_i => wire_clk_dat,
      rst_i => rst,
      dat_nxt_i => wire_dat_nxt_buf,
      dat_val_i => wire_dat_val_man,
      dat_i => wire_dat_man,
      buf_emp_o => open,
      buf_ful_o => buf_ful,
      dat_val_o => wire_dat_val_buf,
      dat_o => wire_dat_buf
    );

  tx_datalink_layer_0: ccsds_tx_datalink_layer
    generic map(
      CCSDS_TX_DATALINK_DATA_BUS_SIZE => DATA_BUS_SIZE,
      CCSDS_TX_DATALINK_CODER_DIFFERENTIAL_BITS_PER_CODEWORD => 1
    )
    port map(
      clk_dat_i => wire_clk_dat,
      clk_bit_i => wire_clk_bit,
      rst_i => rst,
      dat_val_i => wire_dat_val_buf,
      dat_i => wire_dat_buf,
      dat_val_o => wire_dat_val_dat,
      dat_nxt_o => wire_dat_nxt_buf,
      dat_o => wire_dat_dat,
      idl_o => idle_seen
    );

  -- payload feed: advance one word per clk_dat whenever the buffer is not full
  payload_word <= PAYLOAD_ROM(payload_ptr);

  DBG: process (wire_clk_dat)
  begin
    if rising_edge(wire_clk_dat) then
      if (rst = '0') then
        if (dat_val_tx = '1' and buf_ful = '0') then
          cnt_push <= cnt_push + 1;
        end if;
        if (wire_dat_val_man = '1') then
          cnt_manval <= cnt_manval + 1;
        end if;
        if (wire_dat_val_buf = '1') then
          cnt_bufval <= cnt_bufval + 1;
        end if;
        if (wire_dat_nxt_buf = '1') then
          cnt_dnxt <= cnt_dnxt + 1;
        end if;
        if (wire_dat_val_dat = '1') then
          cnt_coder <= cnt_coder + 1;
        end if;
      end if;
    end if;
  end process;

  PAYLOAD_FEED: process (wire_clk_dat)
  begin
    if rising_edge(wire_clk_dat) then
      if (rst = '1') then
        payload_ptr <= 0;
        dat_val_tx <= '0';
        pace_cnt <= 0;
      elsif (pace_cnt = 0 and buf_ful = '0') then
        -- A new payload word is presented to the manager every PACE_PERIOD
        -- clk_dat cycles. The framer accepts a word on every clk_dat once it
        -- is fed continuously (its dat_nxt_o stays asserted), and the
        -- datalink serialiser latches one frame every FRAME_OUTPUT_WORDS = 42
        -- clk_bit = 336 clk_dat. Feeding all 16 payload words back to back
        -- therefore completes a frame in 16 clk_dat and de-synchronises the
        -- framer from the serialiser, which then emits the idle pattern on
        -- roughly half of the transmitted frames. Pacing the source so that
        -- PAYLOAD_WORDS * PACE_PERIOD = 320 clk_dat <= 336 clk_dat keeps the
        -- framer's collection time just inside one output frame.
        dat_val_tx <= '1';
        pace_cnt <= PACE_PERIOD-1;
        if (payload_ptr = PAYLOAD_WORDS-1) then
          payload_ptr <= 0;
        else
          payload_ptr <= payload_ptr + 1;
        end if;
      else
        dat_val_tx <= '0';
        if (pace_cnt /= 0) then
          pace_cnt <= pace_cnt - 1;
        end if;
      end if;
    end if;
  end process;

  -- capture the CADU words handed to the symbol mapper
  CAPTURE: process (wire_clk_bit)
    file     f  : text;
    variable l  : line;
    variable n  : integer := 0;
  begin
    if rising_edge(wire_clk_bit) then
      if (rst = '1') then
        n := 0;
      elsif (n < TB_CAPTURE_WORDS) then
        if (n = 0) then
          file_open(f, "E:/ccsds_fpga/sim/out/cadu_words.txt", write_mode);
        end if;
        write(l, to_integer(unsigned(wire_dat_dat)));
        writeline(f, l);
        n := n + 1;
        if (n = TB_CAPTURE_WORDS) then
          file_close(f);
          capture_done <= true;
          report "TB: captured " & integer'image(n) & " CADU words" severity note;
        end if;
      end if;
    end if;
  end process;

  STIMULUS: process
  begin
    rst <= '1';
    wait for 20*TB_CLK_PERIOD;
    rst <= '0';
    -- one CADU is 42 clk_bit = 42*160 clk_i; the capture holds 3 CADUs
    for i in 0 to 400 loop
      exit when capture_done;
      wait for 1 us;
    end loop;
    report "TB: done, idle flag last = " & std_logic'image(idle_seen) severity note;
    report "TB: push=" & integer'image(cnt_push) &
           " man_accepted=" & integer'image(cnt_manval) &
           " buf_presented=" & integer'image(cnt_bufval) &
           " framer_requests=" & integer'image(cnt_dnxt) &
           " coder_frames=" & integer'image(cnt_coder) &
           " final_ptr=" & integer'image(payload_ptr) &
           " buf_ful=" & std_logic'image(buf_ful) severity note;
    if not capture_done then
      report "TB: TIMEOUT before the capture was complete" severity failure;
    end if;
    done <= true;
    wait;
  end process;

end bench;
