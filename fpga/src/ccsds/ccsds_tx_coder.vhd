-------------------------------
---- Project: EurySPACE CCSDS RX/TX with wishbone interface
---- Design Name: ccsds_tx_coder
---- Version: 1.0.0 + project patch (parallel convolutional coding)
---- Description:
---- Implementation of standard CCSDS 131.0-B-2
-------------------------------
---- Author(s):
---- Guillaume REMBERT
-------------------------------
---- Licence:
---- MIT
-------------------------------
---- Changes list:
---- 2016/11/05: initial release
---- 2026/10   : PROJECT PATCH (FPGA-GPU 星载载荷 / 遥测板移植)
----
----   Problem 1 -- missing coding stage.
----     Upstream only randomizes and prepends the ASM; ccsds_tx_coder_convolutional
----     ships in the same directory but is never instantiated. The verified
----     ground link (sw/ttc/ccsds_tm_tx.py :: build_cadu) is rate-1/2 coded, so
----     an uncoded transmitter cannot be decoded by it.
----
----   Problem 2 -- the sequential coder does not fit the frame budget.
----     ccsds_tx_coder_convolutional emits one coded bit per clk_dat, so coding
----     the 160 bit frame takes 160 clk_dat cycles. The datalink layer serialises
----     FRAME_OUTPUT_WORDS (=22) words of 16 bit at clk_bit, and clk_dat = 8 *
----     clk_bit, so one output frame lasts 176 clk_dat cycles. 160 + framer +
----     synchroniser leaves essentially no margin, and the frame is not updated
----     atomically (the output vector is written bit by bit over 320 cycles),
----     which the datalink serialiser would sample mid-update.
----
----   Fix: a fully parallel (combinational) encoder for one frame.
----     With OPERATING_MODE = 1 the encoder register is cleared at every frame
----     start, so the two output bits of input bit j depend only on input bits
----     j, j+1, ... j+6 of the SAME frame -- no sequential state is required:
----
----        out(2j+1) = d(j) ^ d(j+3) ^ d(j+4) ^ d(j+5) ^ d(j+6)      (G1)
----        out(2j)   = ~( d(j) ^ d(j+1) ^ d(j+3) ^ d(j+4) ^ d(j+6) ) (~G2)
----
----     where d(k) = '0' for k outside the frame (that is exactly the register
----     being cleared). Taps were derived from G1 = 0x79, G2 = 0x5B with the
----     SAME bit convention as ccsds_tx_coder_convolutional /
----     convert_std_logic_vector_array_to_std_logic_vector (character i of the
----     string -> bit i of the vector), and the output ordering matches
----     euryspace (high two bits of dat_o belong to the first transmitted input
----     bit) as well as the Python encoder (out[2i] = p1, out[2i+1] = p2).
----
----     The whole frame is therefore produced in one clk_dat cycle, which keeps
----     the datalink serialiser's assumption intact.
----
----   Chain: frame -> randomizer -> convolutional(rate 2) -> ASM -> [diff] -> out
----   so the ASM is neither randomized nor coded, matching build_cadu():
----       cadu = asm_bits ++ conv_encode(randomize(frame))
-------------------------------

-- libraries used
library ieee;
use ieee.std_logic_1164.all;

--=============================================================================
-- Entity declaration for ccsds_tx / unitary tx coder inputs and outputs
--=============================================================================
entity ccsds_tx_coder is
  generic(
    constant CCSDS_TX_CODER_ASM_LENGTH: integer; -- Attached Synchronization Marker length / in Bytes
    constant CCSDS_TX_CODER_DATA_BUS_SIZE: integer; -- in bits
    constant CCSDS_TX_CODER_DIFFERENTIAL_BITS_PER_CODEWORD: integer; -- Number of bits per codeword (should be equal to bits per symbol of lower link)
    constant CCSDS_TX_CODER_DIFFERENTIAL_ENABLED: boolean; -- Enable differential coder
    -- project patch: convolutional coding (1 = upstream uncoded, 2 = rate 1/2)
    constant CCSDS_TX_CODER_OUTPUT_RATE: integer := 2
  );
  port(
    -- inputs
    clk_i: in std_logic;
    dat_i: in std_logic_vector(CCSDS_TX_CODER_DATA_BUS_SIZE-1 downto 0);
    dat_val_i: in std_logic;
    rst_i: in std_logic;
    -- outputs
    dat_o: out std_logic_vector(CCSDS_TX_CODER_DATA_BUS_SIZE*CCSDS_TX_CODER_OUTPUT_RATE+CCSDS_TX_CODER_ASM_LENGTH*8-1 downto 0);
    dat_val_o: out std_logic
  );
end ccsds_tx_coder;

--=============================================================================
-- architecture declaration / internal components and connections
--=============================================================================
architecture structure of ccsds_tx_coder is
  component ccsds_tx_coder_differential is
    generic(
      CCSDS_TX_CODER_DIFF_BITS_PER_CODEWORD: integer;
      CCSDS_TX_CODER_DIFF_DATA_BUS_SIZE: integer
    );
    port(
      clk_i: in std_logic;
      dat_i: in std_logic_vector(CCSDS_TX_CODER_DIFF_DATA_BUS_SIZE-1 downto 0);
      dat_val_i: in std_logic;
      rst_i: in std_logic;
      dat_o: out std_logic_vector(CCSDS_TX_CODER_DIFF_DATA_BUS_SIZE-1 downto 0);
      dat_val_o: out std_logic
    );
  end component;
  component ccsds_tx_randomizer is
    generic(
      CCSDS_TX_RANDOMIZER_DATA_BUS_SIZE: integer
    );
    port(
      clk_i: in std_logic;
      dat_i: in std_logic_vector(CCSDS_TX_RANDOMIZER_DATA_BUS_SIZE-1 downto 0);
      dat_val_i: in std_logic;
      rst_i: in std_logic;
      dat_o: out std_logic_vector(CCSDS_TX_RANDOMIZER_DATA_BUS_SIZE-1 downto 0);
      dat_val_o: out std_logic
    );
  end component;
  component ccsds_tx_synchronizer is
    generic(
      CCSDS_TX_ASM_LENGTH: integer;
      CCSDS_TX_ASM_DATA_BUS_SIZE: integer
    );
    port(
      clk_i: in std_logic;
      dat_i: in std_logic_vector(CCSDS_TX_ASM_DATA_BUS_SIZE-1 downto 0);
      dat_val_i: in std_logic;
      rst_i: in std_logic;
      dat_o: out std_logic_vector(CCSDS_TX_ASM_DATA_BUS_SIZE+CCSDS_TX_ASM_LENGTH*8-1 downto 0);
      dat_val_o: out std_logic
    );
  end component;

-- internal constants
  constant CODER_CODED_FRAME_SIZE: integer := CCSDS_TX_CODER_DATA_BUS_SIZE*CCSDS_TX_CODER_OUTPUT_RATE;
  constant CODER_FRAME_SIZE: integer := CODER_CODED_FRAME_SIZE+CCSDS_TX_CODER_ASM_LENGTH*8;

-- internal functions
  -- bit with out-of-frame reads treated as the (cleared) encoder register
  function frame_bit(v: std_logic_vector; idx: integer) return std_logic is
  begin
    if (idx >= 0) and (idx <= v'high) then
      return v(idx);
    else
      return '0';
    end if;
  end function frame_bit;

  function conv_p1(v: std_logic_vector; j: integer) return std_logic is
  begin
    return frame_bit(v, j) xor frame_bit(v, j+3) xor frame_bit(v, j+4) xor
           frame_bit(v, j+5) xor frame_bit(v, j+6);
  end function conv_p1;

  function conv_p2(v: std_logic_vector; j: integer) return std_logic is
  begin
    return frame_bit(v, j) xor frame_bit(v, j+1) xor frame_bit(v, j+3) xor
           frame_bit(v, j+4) xor frame_bit(v, j+6);
  end function conv_p2;

-- internal variable signals
  signal wire_coder_diff_dat_o: std_logic_vector(CODER_FRAME_SIZE-1 downto 0);
  signal wire_coder_diff_dat_val_o: std_logic;
  signal wire_randomizer_dat_o: std_logic_vector(CCSDS_TX_CODER_DATA_BUS_SIZE-1 downto 0);
  signal wire_randomizer_dat_val_o: std_logic;
  signal wire_coded_dat_o: std_logic_vector(CODER_CODED_FRAME_SIZE-1 downto 0);
  signal wire_coded_dat_val_o: std_logic;
  signal wire_synchronizer_dat_o: std_logic_vector(CODER_FRAME_SIZE-1 downto 0);
  signal wire_synchronizer_dat_val_o: std_logic;
-- components instanciation and mapping
  begin
  tx_coder_randomizer_0: ccsds_tx_randomizer
    generic map(
      CCSDS_TX_RANDOMIZER_DATA_BUS_SIZE => CCSDS_TX_CODER_DATA_BUS_SIZE
    )
    port map(
      clk_i => clk_i,
      rst_i => rst_i,
      dat_val_i => dat_val_i,
      dat_i => dat_i,
      dat_val_o => wire_randomizer_dat_val_o,
      dat_o => wire_randomizer_dat_o
    );

  -- project patch: rate-1/2 convolutional coding between randomizer and ASM
  CONVOLUTIONAL_RATE2: if (CCSDS_TX_CODER_OUTPUT_RATE = 2) generate
    CONVOLUTIONAL_PARALLEL: for j in 0 to CCSDS_TX_CODER_DATA_BUS_SIZE-1 generate
      wire_coded_dat_o(2*j+1) <= conv_p1(wire_randomizer_dat_o, j);
      wire_coded_dat_o(2*j)   <= not conv_p2(wire_randomizer_dat_o, j);
    end generate CONVOLUTIONAL_PARALLEL;
    wire_coded_dat_val_o <= wire_randomizer_dat_val_o;
  end generate CONVOLUTIONAL_RATE2;

  CONVOLUTIONAL_RATE1: if (CCSDS_TX_CODER_OUTPUT_RATE = 1) generate
    wire_coded_dat_o <= wire_randomizer_dat_o;
    wire_coded_dat_val_o <= wire_randomizer_dat_val_o;
  end generate CONVOLUTIONAL_RATE1;

  NODIFFCODERGENP: if (CCSDS_TX_CODER_DIFFERENTIAL_ENABLED = false) generate
    tx_coder_synchronizer_0: ccsds_tx_synchronizer
      generic map(
        CCSDS_TX_ASM_LENGTH => CCSDS_TX_CODER_ASM_LENGTH,
        CCSDS_TX_ASM_DATA_BUS_SIZE => CODER_CODED_FRAME_SIZE
      )
      port map(
        clk_i => clk_i,
        rst_i => rst_i,
        dat_val_i => wire_coded_dat_val_o,
        dat_i => wire_coded_dat_o,
        dat_val_o => dat_val_o,
        dat_o => dat_o
      );
   end generate NODIFFCODERGENP;
  DIFFCODERGENP: if (CCSDS_TX_CODER_DIFFERENTIAL_ENABLED = true) generate
    tx_coder_synchronizer_0: ccsds_tx_synchronizer
      generic map(
        CCSDS_TX_ASM_LENGTH => CCSDS_TX_CODER_ASM_LENGTH,
        CCSDS_TX_ASM_DATA_BUS_SIZE => CODER_CODED_FRAME_SIZE
      )
      port map(
        clk_i => clk_i,
        rst_i => rst_i,
        dat_val_i => wire_coded_dat_val_o,
        dat_i => wire_coded_dat_o,
        dat_val_o => wire_synchronizer_dat_val_o,
        dat_o => wire_synchronizer_dat_o
      );
    tx_coder_differential_0: ccsds_tx_coder_differential
      generic map(
        CCSDS_TX_CODER_DIFF_BITS_PER_CODEWORD => CCSDS_TX_CODER_DIFFERENTIAL_BITS_PER_CODEWORD,
        CCSDS_TX_CODER_DIFF_DATA_BUS_SIZE => CODER_FRAME_SIZE
      )
      port map(
        clk_i => clk_i,
        rst_i => rst_i,
        dat_val_i => wire_synchronizer_dat_val_o,
        dat_i => wire_synchronizer_dat_o,
        dat_val_o => dat_val_o,
        dat_o => dat_o
      );
   end generate DIFFCODERGENP;
-- presynthesis checks
-- internal processing
end structure;
