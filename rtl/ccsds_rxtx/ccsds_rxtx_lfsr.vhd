-------------------------------
---- Project: EurySPACE CCSDS RX/TX with wishbone interface
---- Design Name: ccsds_rxtx_lfsr
---- Version: 1.0.0
---- Description:
---- Linear Feedback Shift Register
---- Input: none
---- Timing requirements: CCSDS_RXTX_LFSR_DATA_BUS_SIZE+1 clock cycles for valid output data
---- Output: dat_val_o <= "1" / dat_o <= "LFSRSEQUENCE"
---- Ressources requirements: TODO
-------------------------------
---- Author(s):
---- Guillaume REMBERT
-------------------------------
---- Licence:
---- MIT
-------------------------------
---- Changes list:
---- 2016/11/05: initial release
-------------------------------
-- Test ressources:
-- GNURADIO GLFSR block

-- CCSDS parameters
-- Width = 8
-- Mode = Fibonacci ('0')
-- Polynomial = x"95"
-- Seed = x"FF"
-- Result = "1111111101001000000011101100000010011010"
--
-- ============================================================================
-- PROJECT PATCH (2026-10, CCSDS 标准版) -- WHY THE POLYNOMIAL IS x"95" AND NOT
-- x"A9", AND WHY THE OUTPUT IS THE MSB.
--
-- The CCSDS 131.0-B pseudo-randomiser is
--     h(x) = x^8 + x^7 + x^5 + x^3 + 1
-- In the "bit i = coefficient of x^i" convention that is the tap mask
--     0b10101001 = 0xA9   ->  taps {0,3,5,7}
--
-- This module shifts LEFT and feeds the feedback into bit 0.  In that
-- orientation the recursion consumes the register bits in the order
-- bit0, bit1, ... i.e. it walks the polynomial from x^0 upwards, so the
-- polynomial must be supplied in the SAME order it is consumed.  Feeding the
-- {0,3,5,7} mask into a left-shifting register produces a period-217 sequence
-- whose bytes are AD 75 59 34 CD C4 -- NOT the CCSDS sequence.
--
-- The correct pairing for a left-shifting Fibonacci register is the
-- BIT-REVERSED mask
--     0b10010101 = 0x95   ->  taps {0,2,4,7}
-- combined with emitting the bit shifted out (the MSB, bit 7).
--
-- Verified by brute force over all (mask, seed, shift direction, output bit)
-- combinations against the reference sequence recorded above
-- (sim/solve_lfsr.py, sim/vectors/lfsr_standard_255.txt):
--     mask 0x95, seed 0xFF, shift left, output bit 7
--        -> period 255, first 6 bytes FF 48 0E C0 9A 0D   <-- exact match
--     mask 0xA9, seed 0xFF, shift left, output bit 0
--        -> period 217, first 6 bytes AD 75 59 34 CD C4   <-- previous state
-- Only these two parameter sets matter in practice; the other two solutions
-- found by the solver (0x95/0xB1/left/bit0 and 0xA9/0x8D/right/bit7) are the
-- same m-sequence phase-shifted or mirrored and are not used.
--
-- A wrong randomiser sequence cannot be recovered from at the receiver: the
-- de-randomiser is the same XOR, so a mismatched sequence corrupts every bit
-- of every frame.  This is why the polynomial direction trap is the single
-- most damaging bug in this core.
-- ============================================================================

-- Width = 8
-- Mode = Galois ('1')
-- Polynomial = x"A9"
-- Seed = x"FF"
-- Result = "101001011011000001011000110110"

-- libraries used
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

--=============================================================================
-- Entity declaration for ccsds_tx / unitary tx randomizer inputs and outputs
--=============================================================================
entity ccsds_rxtx_lfsr is
  generic(
    constant CCSDS_RXTX_LFSR_DATA_BUS_SIZE: integer; -- in bits
		constant CCSDS_RXTX_LFSR_MEMORY_SIZE: integer range 2 to 256 := 8; -- in bits
		constant CCSDS_RXTX_LFSR_MODE: std_logic := '0'; -- 0: Fibonacci / 1: Galois
		constant CCSDS_RXTX_LFSR_POLYNOMIAL: std_logic_vector	:= x"95"; -- Polynomial / MSB <=> lower polynome (needs to be '1')
		constant CCSDS_RXTX_LFSR_SEED: std_logic_vector	:= x"FF";	-- Initial Value
    -- Which end of the shift register is emitted first.
    --   true  : emit memory(MEMORY_SIZE-1), i.e. the bit shifted OUT (textbook
    --           Fibonacci LFSR).  THIS IS THE CCSDS 131.0-B BEHAVIOUR and the
    --           required setting for the standard sequence.
    --   false : emit memory(0), i.e. the bit the feedback will overwrite
    --           (this was the earlier, non-standard bring-up setting).
    -- The tap polynomial and the shift direction are identical either way, so
    -- this single bit selects between two different output sequences -- but it
    -- is only correct IN COMBINATION WITH the matching polynomial above.  See
    -- the long note in the CCSDS parameter block: the standard pairing is
    -- (POLYNOMIAL = x"95", MSB_FIRST = true) for this left-shifting register.
		constant CCSDS_RXTX_LFSR_MSB_FIRST: boolean := true
  );
  port(
    -- inputs
    clk_i: in std_logic;
    rst_i: in std_logic;
    -- outputs
    dat_o: out std_logic_vector(CCSDS_RXTX_LFSR_DATA_BUS_SIZE-1 downto 0);
    dat_val_o: out std_logic
  );
end ccsds_rxtx_lfsr;

--=============================================================================
-- architecture declaration / internal components and connections
--=============================================================================
architecture structure of ccsds_rxtx_lfsr is

-- internal constants
  -- PROJECT PATCH (FPGA-GPU 星载载荷 / 遥测板移植) -- polynomial tap indexing.
  --
  -- CCSDS_RXTX_LFSR_POLYNOMIAL is an unconstrained std_logic_vector generic
  -- initialised with a string literal. A string literal takes the ASCENDING
  -- index range, so POLYNOMIAL(0) is the LEFTMOST character written, i.e. the
  -- most significant bit of the value -- NOT the x^0 coefficient. Indexing the
  -- generic directly therefore taps the bit-reversed polynomial.
  --
  -- Measured consequence with the shipped default x"A9":
  --     intended taps (Python rand_seq, 0xA9) : {0,3,5,7}
  --     taps actually used by this code       : {0,2,4,7}  (= bit reverse)
  -- which produces a completely different m-sequence. The transmitter then
  -- cannot be derandomized by the ground receiver and nothing ever decodes.
  -- Evidence: sim/bench/tb_lfsr.vhd dumps dat_o, sim/solve_lfsr.py brute forces
  -- the recurrence and reports it exactly reproduces mask 0x95, out_bit 0,
  -- shift left -- while Python's rand_seq is mask 0xA9, out_bit 0, shift left.
  --
  -- Normalising through this function makes the tap mask independent of the
  -- literal's index direction, so the value really reads as "bit i = x^i".
  function normalise_polynomial(p: std_logic_vector; msize: integer)
    return std_logic_vector is
    variable r: std_logic_vector(msize-1 downto 0) := (others => '0');
  begin
    for i in 0 to msize-1 loop
      if (p'ascending) then
        r(i) := p(msize-1-i);
      else
        r(i) := p(i);
      end if;
    end loop;
    return r;
  end function normalise_polynomial;

  constant LFSR_POLYNOMIAL: std_logic_vector(CCSDS_RXTX_LFSR_MEMORY_SIZE-1 downto 0) :=
    normalise_polynomial(CCSDS_RXTX_LFSR_POLYNOMIAL, CCSDS_RXTX_LFSR_MEMORY_SIZE);

-- internal variable signals
	signal lfsr_memory: std_logic_vector(CCSDS_RXTX_LFSR_MEMORY_SIZE-1 downto 0) := CCSDS_RXTX_LFSR_SEED;
-- components instanciation and mapping
  begin

-- presynthesis checks
	  CHKLFSRP0 : if CCSDS_RXTX_LFSR_POLYNOMIAL'length /= CCSDS_RXTX_LFSR_MEMORY_SIZE generate
		  process
		  begin
			  report "ERROR: LFSR_POLYNOMIAL LENGTH MUST BE EQUAL TO MEMORY SIZE (SHORTENED VERSION / DON'T PUT MANDATORY HIGHER POLYNOME '1')" severity failure;
			  wait;
		  end process;
	  end generate CHKLFSRP0;
	  CHKLFSRP1 : if CCSDS_RXTX_LFSR_MEMORY_SIZE <= 1 generate
		  process
		  begin
			  report "ERROR: LFSR_MEMORY_SIZE MUST BE BIGGER THAN 1" severity failure;
			  wait;
		  end process;
	  end generate CHKLFSRP1;
	  CHKLFSRP2 : if CCSDS_RXTX_LFSR_SEED'length /= CCSDS_RXTX_LFSR_MEMORY_SIZE generate
		  process
		  begin
			  report "ERROR: LFSR_SEED LENGTH MUST BE EQUAL TO LFSR_MEMORY_SIZE" severity failure;
			  wait;
		  end process;
	  end generate CHKLFSRP2;
    CHKLFSRP3 : if CCSDS_RXTX_LFSR_POLYNOMIAL(CCSDS_RXTX_LFSR_MEMORY_SIZE-1) = '0' generate
      process
      begin
        report "ERROR: LFSR POLYNOMIAL MSB MUST BE EQUAL TO 1" severity failure;
        wait;
      end process;
    end generate CHKLFSRP3;

-- internal processing
    --=============================================================================
    -- Begin of crcp
    -- Compute CRC based on input data
    --=============================================================================
    -- read: rst_i
    -- write: dat_o, dat_val_o
    -- r/w: lfsr_memory
    LFSRP: process (clk_i)
    variable output_pointer: integer range -1 to (CCSDS_RXTX_LFSR_DATA_BUS_SIZE-1) := CCSDS_RXTX_LFSR_DATA_BUS_SIZE-1;
    variable feedback_register: std_logic := '0';
    begin
      -- on each clock rising edge
      if rising_edge(clk_i) then
        -- reset signal received
        if (rst_i = '1') then
          lfsr_memory <= CCSDS_RXTX_LFSR_SEED;
          dat_o <= (others => '0');
          dat_val_o <= '0';
          output_pointer := CCSDS_RXTX_LFSR_DATA_BUS_SIZE-1;
          feedback_register := '0';
        else
          -- generation is finished
          if (output_pointer = -1) then
            dat_val_o <= '1';
          -- generating sequence
          else
            dat_val_o <= '0';
            -- Fibonacci
            if (CCSDS_RXTX_LFSR_MODE = '0') then
              if (CCSDS_RXTX_LFSR_MSB_FIRST = true) then
                dat_o(output_pointer) <= lfsr_memory(CCSDS_RXTX_LFSR_MEMORY_SIZE-1);
              else
                dat_o(output_pointer) <= lfsr_memory(0);
              end if;
              output_pointer := output_pointer - 1;
              feedback_register := lfsr_memory(CCSDS_RXTX_LFSR_MEMORY_SIZE-1);
              for i in 0 to CCSDS_RXTX_LFSR_MEMORY_SIZE-2 loop
                if (LFSR_POLYNOMIAL(i) = '1') then
                  feedback_register := feedback_register xor lfsr_memory(i);
                end if;
              end loop;
              lfsr_memory <= std_logic_vector(resize(unsigned(lfsr_memory),CCSDS_RXTX_LFSR_MEMORY_SIZE-1)) & feedback_register;
            -- Galois
            else
              dat_o(output_pointer) <= lfsr_memory(CCSDS_RXTX_LFSR_MEMORY_SIZE-1);
              output_pointer := output_pointer - 1;
              lfsr_memory(0) <= lfsr_memory(CCSDS_RXTX_LFSR_MEMORY_SIZE-1);
              for i in 1 to CCSDS_RXTX_LFSR_MEMORY_SIZE-1 loop
                if (LFSR_POLYNOMIAL(i) = '1') then
                  lfsr_memory(i) <= lfsr_memory(i-1) xor lfsr_memory(CCSDS_RXTX_LFSR_MEMORY_SIZE-1);
                else
                  lfsr_memory(i) <= lfsr_memory(i-1);
                end if;
              end loop;
            end if;
          end if;
        end if;
      end if;
    end process;
end structure;
