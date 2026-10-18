-------------------------------
---- Project: EurySPACE CCSDS RX/TX with wishbone interface
---- Design Name: ccsds_tx_datalink_layer
---- Version: 1.0.0
---- Description:
---- TM (TeleMetry) Space Data Link Protocol
-------------------------------
---- Author(s):
---- Guillaume REMBERT
-------------------------------
---- Licence:
---- MIT
-------------------------------
---- Changes list:
---- 2015/11/17: initial release
---- 2016/10/21: rework based on TX final architecture
-------------------------------

-- libraries used
library ieee;
use ieee.std_logic_1164.all;

--=============================================================================
-- Entity declaration for ccsds_tx / unitary tx datalink layer inputs and outputs
--=============================================================================
entity ccsds_tx_datalink_layer is
  generic (
    constant CCSDS_TX_DATALINK_ASM_LENGTH: integer := 4; -- Attached Synchronization Marker length / in Bytes
    constant CCSDS_TX_DATALINK_CODER_DIFFERENTIAL_ENABLED: boolean := false; -- Enable differential coder
    constant CCSDS_TX_DATALINK_CODER_DIFFERENTIAL_BITS_PER_CODEWORD: integer; -- Number of bits per codeword from differential coder
    constant CCSDS_TX_DATALINK_DATA_BUS_SIZE: integer; -- in bits
    -- PROJECT PATCH: upstream default was 12, giving a 20 byte frame. The
    -- verified ground receiver (sw/ttc/auto_decode.py:92) only searches the
    -- decoded bit stream for frame lengths L in (108, 40), i.e. 100 byte or
    -- 32 byte payloads, so a 20 byte frame can never be found. 32 bytes gives
    -- a 40 byte frame (6 header + 32 data + 2 FECF) and a 672 bit CADU.
    -- framer.vhd CHKFRAMERP0 also requires DATA_LENGTH*8 mod DATA_BUS_SIZE = 0
    -- (32*8 = 256, bus 16 -> OK).
    constant CCSDS_TX_DATALINK_DATA_LENGTH: integer := 32; -- datagram data size (Bytes) / (has to be a multiple of CCSDS_TX_DATALINK_DATA_BUS_SIZE)
    constant CCSDS_TX_DATALINK_FOOTER_LENGTH: integer := 2; -- datagram footer length (Bytes)
    constant CCSDS_TX_DATALINK_HEADER_LENGTH: integer := 6; -- datagram header length (Bytes)
    -- PROJECT PATCH: the framer throttles how often it starts a new frame.
    -- frame_output_counter is reloaded with
    --     DATA_LENGTH*P*8/DATA_BUS_SIZE
    -- and next_frame_write_pos is reloaded with
    --     DATA_LENGTH*8/DATA_BUS_SIZE
    -- Both only advance on cycles where the source presents a word, so P = 1
    -- makes the two periods IDENTICAL and locks their phase: a frame finishes
    -- collecting on exactly the cycle a new frame starts, current_frame_ready
    -- never gets set, and the framer emits the all-ones idle pattern for ever
    -- (measured: payload came back as 32 x 0xFF with FHP = 0x7FE).
    -- P = 2 doubles the frame period, so collection completes halfway through
    -- and current_frame_ready is set in time for every frame start.
    -- Upstream default was 16, which makes the framer ~12x slower than the
    -- serialiser (16 words * 256 clk_dat = 4096 clk_dat against an output frame
    -- period of FRAME_OUTPUT_WORDS = 42 clk_bit = 336 clk_dat), i.e. mostly
    -- idle frames as well.
    constant CCSDS_TX_DATALINK_FRAMER_PARALLELISM_MAX_RATIO: integer := 2;
    -- project patch: 1 = upstream (uncoded) frame, 2 = rate-1/2 convolutional
    -- coded frame. The verified ground link uses 2, which turns the 38 byte
    -- frame (6 header + 32 data + 2 FECF) into 640 coded bits and then the
    -- 4 byte ASM into a 672 bit = 84 byte CADU, i.e. 42 words of 16 bits.
    constant CCSDS_TX_DATALINK_CODER_OUTPUT_RATE: integer := 2;
    -- project patch: true = feed the coder from the fixed CADU in STATIC_FRAME
    -- (bring-up), false = use the upstream framer. See the long comment at the
    -- instantiation section for why the default is true.
    constant CCSDS_TX_DATALINK_STATIC_FRAME_ENABLED: boolean := true
  );
  port(
    -- inputs
    clk_bit_i: in std_logic;
    clk_dat_i: in std_logic;
    dat_i: in std_logic_vector(CCSDS_TX_DATALINK_DATA_BUS_SIZE-1 downto 0);
    dat_val_i: in std_logic;
    rst_i: in std_logic;
    -- outputs
    dat_o: out std_logic_vector(CCSDS_TX_DATALINK_DATA_BUS_SIZE-1 downto 0);
    dat_nxt_o: out std_logic;
    dat_val_o: out std_logic;
    idl_o: out std_logic
  );
end ccsds_tx_datalink_layer;

--=============================================================================
-- architecture declaration / internal components and connections
--=============================================================================
architecture structure of ccsds_tx_datalink_layer is
  component ccsds_tx_framer is
    generic(
      CCSDS_TX_FRAMER_DATA_BUS_SIZE : integer;
      CCSDS_TX_FRAMER_DATA_LENGTH : integer;
      CCSDS_TX_FRAMER_FOOTER_LENGTH : integer;
      CCSDS_TX_FRAMER_HEADER_LENGTH : integer;
      CCSDS_TX_FRAMER_PARALLELISM_MAX_RATIO : integer
    );
    port(
      clk_i: in std_logic;
      rst_i: in std_logic;
      dat_i: in std_logic_vector(CCSDS_TX_FRAMER_DATA_BUS_SIZE-1 downto 0);
      dat_val_i: in std_logic;
      dat_o: out std_logic_vector((CCSDS_TX_FRAMER_DATA_LENGTH+CCSDS_TX_FRAMER_HEADER_LENGTH+CCSDS_TX_FRAMER_FOOTER_LENGTH)*8-1 downto 0);
      dat_val_o: out std_logic;
      dat_nxt_o: out std_logic;
      idl_o: out std_logic
    );
  end component;
  component ccsds_tx_coder is
    generic(
      CCSDS_TX_CODER_DIFFERENTIAL_BITS_PER_CODEWORD: integer;
      CCSDS_TX_CODER_DIFFERENTIAL_ENABLED: boolean;
      CCSDS_TX_CODER_DATA_BUS_SIZE : integer;
      CCSDS_TX_CODER_ASM_LENGTH: integer;
      CCSDS_TX_CODER_OUTPUT_RATE: integer
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

-- internal constants
  constant FRAME_CODED_SIZE: integer := (CCSDS_TX_DATALINK_DATA_LENGTH+CCSDS_TX_DATALINK_HEADER_LENGTH+CCSDS_TX_DATALINK_FOOTER_LENGTH)*8*CCSDS_TX_DATALINK_CODER_OUTPUT_RATE;
  constant FRAME_OUTPUT_SIZE: integer := FRAME_CODED_SIZE+CCSDS_TX_DATALINK_ASM_LENGTH*8;
  constant FRAME_OUTPUT_WORDS: integer := FRAME_OUTPUT_SIZE/CCSDS_TX_DATALINK_DATA_BUS_SIZE;

  -- PROJECT PATCH: static bring-up frame (see CCSDS_TX_DATALINK_STATIC_FRAME_ENABLED).
  -- Produced by the verified ground reference itself:
  --   build_tm_frame(scid=0x2A, vcid=0, mcfc=0, vcfc=0,
  --                  data=b"CCSDS-6G-NTN-7010-TTC-FPGA-PORT!", fecf=True)
  -- Layout: 6 byte primary header | 32 byte payload | 2 byte CRC-16/CCITT FECF.
  -- The explicit (n downto 0) range in the declaration matters: an
  -- unconstrained std_logic_vector initialised from a string literal takes an
  -- ASCENDING index range, which silently reverses any bit indexing done on it.
  constant STATIC_FRAME: std_logic_vector((CCSDS_TX_DATALINK_DATA_LENGTH+CCSDS_TX_DATALINK_HEADER_LENGTH+CCSDS_TX_DATALINK_FOOTER_LENGTH)*8-1 downto 0) :=
    x"02a00000180043435344532d36472d4e544e2d37" &
    x"3031302d5454432d465047412d504f5254210463";

-- interconnection signals
  signal wire_framer_data: std_logic_vector((CCSDS_TX_DATALINK_DATA_LENGTH+CCSDS_TX_DATALINK_HEADER_LENGTH+CCSDS_TX_DATALINK_FOOTER_LENGTH)*8-1 downto 0);
  signal wire_framer_data_valid: std_logic;
  signal wire_coder_data: std_logic_vector(FRAME_OUTPUT_SIZE-1 downto 0);
  signal wire_coder_data_valid: std_logic;
  -- PROJECT PATCH: 每输出一个字翻转一次，作为下游 mapper 符号窗口的同步沿。
  -- 原实现用 dat_val_o 做"电平"，导致 mapper 窗口与字边界无相位关系
  -- （实测每个 16 位字末尾 5 位错，96/672）。
  signal wire_word_toggle: std_logic := '0';

-- components instanciation and mapping
  begin

  -- PROJECT PATCH: dat_val_o 现在由 BITSOUTPUTP 里的"每字翻转一次"信号驱动
  -- （原来是 BITSVALIDP 在 clk_dat 域置 1 后永不清零的电平）。
  dat_val_o <= wire_word_toggle;

  --===========================================================================
  -- PROJECT PATCH -- frame source selection
  --
  -- The upstream framer + footer + CRC trio does not run continuously with the
  -- data source used here. Measured behaviour (sim/bench/tb_ccsds_tx_chain.vhd,
  -- 202 us run): the coder is strobed 681 times, i.e. it is NOT stalled, but
  -- every strobe carries the SAME frame -- the idle frame produced once at
  -- start-up (FHP = 0x7FE, payload all ones, MCFC stuck at 0). The output is
  -- therefore byte-identical no matter how the framer throughput generic is
  -- set (tried PARALLELISM_MAX_RATIO = 16 / 1 / 2 and source pacing 1 / 10 / 20
  -- clk_dat), which points at the framer/footer handshake, not at the data
  -- source. That state machine is written for a slow Wishbone slave.
  --
  -- For the bring-up transmitter we therefore feed the (fully verified) coder
  -- with one fixed CADU generated by the ground reference itself. This is the
  -- plan the hand-over document already prescribes ("frame data source: store a
  -- fixed test CADU first for bring-up"). It also sidesteps the framer's CRC
  -- seed, which computes CRC-16/AUG-CCITT (init 0x1D0F) rather than
  -- CRC-16/CCITT-FALSE (init 0xFFFF) and so would not match the receiver.
  --
  -- Set CCSDS_TX_DATALINK_STATIC_FRAME_ENABLED to false to route the upstream
  -- framer through instead, once its handshake has been fixed.
  --===========================================================================
  STATIC_FRAME_SOURCE: if (CCSDS_TX_DATALINK_STATIC_FRAME_ENABLED = true) generate
    -- the frame is constant, so a permanently asserted valid keeps the coder
    -- output (randomiser -> convolutional coder -> ASM) stable and the
    -- serialiser simply repeats the same CADU
    wire_framer_data <= STATIC_FRAME;
    wire_framer_data_valid <= '1';
    dat_nxt_o <= '0';
    idl_o <= '0';
  end generate STATIC_FRAME_SOURCE;

  UPSTREAM_FRAMER_SOURCE: if (CCSDS_TX_DATALINK_STATIC_FRAME_ENABLED = false) generate
  tx_datalink_framer_0: ccsds_tx_framer
    generic map(
      CCSDS_TX_FRAMER_HEADER_LENGTH => CCSDS_TX_DATALINK_HEADER_LENGTH,
      CCSDS_TX_FRAMER_DATA_LENGTH => CCSDS_TX_DATALINK_DATA_LENGTH,
      CCSDS_TX_FRAMER_FOOTER_LENGTH => CCSDS_TX_DATALINK_FOOTER_LENGTH,
      CCSDS_TX_FRAMER_DATA_BUS_SIZE => CCSDS_TX_DATALINK_DATA_BUS_SIZE,
      CCSDS_TX_FRAMER_PARALLELISM_MAX_RATIO => CCSDS_TX_DATALINK_FRAMER_PARALLELISM_MAX_RATIO
    )
    port map(
      clk_i => clk_dat_i,
      rst_i => rst_i,
      dat_val_i => dat_val_i,
      dat_i => dat_i,
      dat_val_o => wire_framer_data_valid,
      dat_nxt_o => dat_nxt_o,
      dat_o => wire_framer_data,
      idl_o => idl_o
    );
  end generate UPSTREAM_FRAMER_SOURCE;

  tx_datalink_coder_0: ccsds_tx_coder
    generic map(
      CCSDS_TX_CODER_ASM_LENGTH => CCSDS_TX_DATALINK_ASM_LENGTH,
      CCSDS_TX_CODER_DATA_BUS_SIZE => (CCSDS_TX_DATALINK_DATA_LENGTH+CCSDS_TX_DATALINK_HEADER_LENGTH+CCSDS_TX_DATALINK_FOOTER_LENGTH)*8,
      CCSDS_TX_CODER_DIFFERENTIAL_BITS_PER_CODEWORD => CCSDS_TX_DATALINK_CODER_DIFFERENTIAL_BITS_PER_CODEWORD,
      CCSDS_TX_CODER_DIFFERENTIAL_ENABLED => CCSDS_TX_DATALINK_CODER_DIFFERENTIAL_ENABLED,
      CCSDS_TX_CODER_OUTPUT_RATE => CCSDS_TX_DATALINK_CODER_OUTPUT_RATE
    )
    port map(
      clk_i => clk_dat_i,
      dat_i => wire_framer_data,
      dat_val_i => wire_framer_data_valid,
      rst_i => rst_i,
      dat_val_o => wire_coder_data_valid,
      dat_o => wire_coder_data
    );
-- presynthesis checks
-- internal processing
    --=============================================================================
    -- Begin of bitsvalidp
    --
    -- PROJECT PATCH (遥测板 CCSDS 发射链: 每个 16 位字末尾 5 位错误)
    --
    -- 原实现把 dat_val_o 当成"电平"：一旦 coder 数据有效就置 1，永不清零。
    -- 下游 ccsds_tx_mapper_bits_symbols 在 clk_sym 上跑，它把 dat_val_i 理解成
    -- "每拍都有效"，于是它的 16 符号窗口完全自由跑，与 BITSOUTPUTP 的
    -- clk_bit 字边界没有任何相位关系。
    --
    -- 实测后果（sim/bench/tb_phys.vhd + Python 对比）:
    --     符号流与期望 CADU 差 96/672，差异位置 mod 16 = {11,12,13,14,15}
    --     —— 每个 16 位字的最后 5 个符号取到了【下一个字】的内容。
    --
    -- 修法：dat_val_o 改为"每输出一个字翻转一次"的同步信号（toggle），
    -- 由 BITSOUTPUTP 在 clk_bit 域驱动（它是唯一知道字边界的进程）。
    -- 下游 mapper 对 dat_val_i 做边沿检测，检测到翻转就把符号窗口复位到
    -- 最高位，从而与字边界严格对齐。
    --
    -- 注：dat_val_o 只被 mapper 使用（ccsds_tx.vhd: wire_dat_val_dat ->
    --     ccsds_tx_physical_layer -> mapper.dat_val_i），改成 toggle 不影响别处。
    --=============================================================================
    -- read: rst_i
    -- write: (dat_val_o 由 BITSOUTPUTP 驱动)
    -- r/w:
    dat_nxt_o <= '0';    -- 上游未使用；显式驱动避免悬空
    --=============================================================================
    -- Begin of bitsoutputp
    -- Generate bits output word by word based on coder output
    --=============================================================================
    -- read: rst_i, wire_coder_data
    -- write: dat_o
    -- r/w: 
    BITSOUTPUTP: process (clk_bit_i)
    variable next_word_pointer : integer range 0 to FRAME_OUTPUT_WORDS := FRAME_OUTPUT_WORDS - 1;
    variable current_frame: std_logic_vector(FRAME_OUTPUT_SIZE-CCSDS_TX_DATALINK_DATA_BUS_SIZE-1 downto 0) := (others => '0');
    begin
      -- on each clock rising edge
      if rising_edge(clk_bit_i) then
        -- reset signal received
        if (rst_i = '1') then
          next_word_pointer := FRAME_OUTPUT_WORDS - 1;
          dat_o <= (others => '0');
          wire_word_toggle <= '0';
        else
          -- generating valid bits output words
          if (next_word_pointer = FRAME_OUTPUT_WORDS - 1) then
            current_frame := wire_coder_data(FRAME_OUTPUT_SIZE-CCSDS_TX_DATALINK_DATA_BUS_SIZE-1 downto 0);
            dat_o <= wire_coder_data(FRAME_OUTPUT_SIZE-1 downto FRAME_OUTPUT_SIZE-CCSDS_TX_DATALINK_DATA_BUS_SIZE);
            next_word_pointer := FRAME_OUTPUT_WORDS - 2;
          else
            dat_o <= current_frame((next_word_pointer+1)*CCSDS_TX_DATALINK_DATA_BUS_SIZE-1 downto next_word_pointer*CCSDS_TX_DATALINK_DATA_BUS_SIZE);
            if (next_word_pointer = 0) then
              next_word_pointer := FRAME_OUTPUT_WORDS - 1;
            else
              next_word_pointer := next_word_pointer - 1;
            end if;
          end if;
          -- PROJECT PATCH: 每输出一个字翻转一次，作为下游 mapper 符号窗口的同步沿。
          -- ★ 必须放在 if/else 之外！放进 "= FRAME_OUTPUT_WORDS-1" 分支里就变成
          --   "每帧翻转一次"（42 个字才一次），mapper 每帧只吐 16 个符号然后卡死
          --   —— 实测符号流 6747/7500 全是 1。踩过一次，记在这里。
          wire_word_toggle <= not wire_word_toggle;
        end if;
      end if;
    end process;
end structure;
