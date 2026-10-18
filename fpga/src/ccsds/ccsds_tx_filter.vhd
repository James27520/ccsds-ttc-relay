-------------------------------
---- Project: EurySPACE CCSDS RX/TX with wishbone interface
---- Design Name: ccsds_tx_filter
---- Version: 1.0.0
---- Description:
---- Transform symbols to samples, oversample signal and filter it with SRRC filter
-------------------------------
---- Author(s):
---- Guillaume REMBERT
-------------------------------
---- Licence:
---- MIT
-------------------------------
---- Changes list:
---- 2016/11/06: initial release
-------------------------------

-- libraries used
library ieee;
use ieee.std_logic_1164.all;

--=============================================================================
-- Entity declaration for ccsds_tx / unitary tx filter inputs and outputs
--=============================================================================
entity ccsds_tx_filter is
  generic(
    constant CCSDS_TX_FILTER_BITS_PER_SYMBOL: integer; -- in bits
    constant CCSDS_TX_FILTER_OVERSAMPLING_RATIO: integer;
    constant CCSDS_TX_FILTER_OFFSET_IQ: boolean := true;
    constant CCSDS_TX_FILTER_MODULATION_TYPE: integer;
    constant CCSDS_TX_FILTER_SIG_QUANT_DEPTH: integer;
    constant CCSDS_TX_FILTER_TARGET_SNR: real := 40.0
  );
  port(
    -- inputs
    clk_i: in std_logic;
    rst_i: in std_logic;
    sym_i_i: in std_logic_vector(CCSDS_TX_FILTER_BITS_PER_SYMBOL-1 downto 0);
    sym_q_i: in std_logic_vector(CCSDS_TX_FILTER_BITS_PER_SYMBOL-1 downto 0);
    sym_val_i: in std_logic;
    -- outputs
    sam_i_o: out std_logic_vector(CCSDS_TX_FILTER_SIG_QUANT_DEPTH-1 downto 0);
    sam_q_o: out std_logic_vector(CCSDS_TX_FILTER_SIG_QUANT_DEPTH-1 downto 0);
    sam_val_o: out std_logic;
    -- PROJECT PATCH (板级定位): 引出滤波链的两级中间信号给 ILA。
    --   debug_a_o = ccsds_tx_mapper_symbols_samples 的输出（符号->样点幅度量化后，
    --               还没上采样）—— 若这里就已经只有 0/满量程，问题在量化级
    --   debug_b_o = oversampler 的输出（SRRC 的输入）—— 若这里不平滑，问题在上采样
    debug_a_o: out std_logic_vector(CCSDS_TX_FILTER_SIG_QUANT_DEPTH-1 downto 0);
    debug_b_o: out std_logic_vector(CCSDS_TX_FILTER_SIG_QUANT_DEPTH-1 downto 0)
  );
end ccsds_tx_filter;

--=============================================================================
-- architecture declaration / internal components and connections
--=============================================================================
architecture structure of ccsds_tx_filter is
  component ccsds_tx_mapper_symbols_samples is
    generic(
      constant CCSDS_TX_MAPPER_TARGET_SNR: real;
      constant CCSDS_TX_MAPPER_BITS_PER_SYMBOL: integer;
      constant CCSDS_TX_MAPPER_QUANTIZATION_DEPTH: integer
    );
    port(
      clk_i: in std_logic;
      rst_i: in std_logic;
      sym_i: in std_logic_vector(CCSDS_TX_MAPPER_BITS_PER_SYMBOL-1 downto 0);
      sym_val_i: in std_logic;
      sam_val_o: out std_logic;
      sam_o: out std_logic_vector(CCSDS_TX_MAPPER_QUANTIZATION_DEPTH-1 downto 0)
    );
  end component;
  component ccsds_rxtx_oversampler is
    generic(
      CCSDS_RXTX_OVERSAMPLER_OVERSAMPLING_RATIO: integer;
      CCSDS_RXTX_OVERSAMPLER_SYMBOL_DEPHASING: boolean;
      CCSDS_RXTX_OVERSAMPLER_SIG_QUANT_DEPTH: integer
    );
    port(
      clk_i: in std_logic;
      sam_i: in std_logic_vector(CCSDS_RXTX_OVERSAMPLER_SIG_QUANT_DEPTH-1 downto 0);
      sam_val_i: in std_logic;
      rst_i: in std_logic;
      sam_o: out std_logic_vector(CCSDS_RXTX_OVERSAMPLER_SIG_QUANT_DEPTH-1 downto 0);
      sam_val_o: out std_logic
    );
  end component;
  component ccsds_rxtx_srrc is
    generic(
      CCSDS_RXTX_SRRC_OVERSAMPLING_RATIO: integer;
      CCSDS_RXTX_SRRC_SIG_QUANT_DEPTH: integer
    );
    port(
      clk_i: in std_logic;
      rst_i: in std_logic;
      sam_i: in std_logic_vector(CCSDS_RXTX_SRRC_SIG_QUANT_DEPTH-1 downto 0);
      sam_val_i: in std_logic;
      sam_o: out std_logic_vector(CCSDS_RXTX_SRRC_SIG_QUANT_DEPTH-1 downto 0);
      sam_val_o: out std_logic
    );
  end component;
-- internal constants
-- internal variable signals
  signal wire_sam_i: std_logic_vector(CCSDS_TX_FILTER_SIG_QUANT_DEPTH-1 downto 0);
  signal wire_sam_q: std_logic_vector(CCSDS_TX_FILTER_SIG_QUANT_DEPTH-1 downto 0);
  -- ★★★ PROJECT PATCH (板级余量修复)：进 SRRC 之前先 ÷4 ★★★
  --
  -- 板级实测（12 探针 ILA）：
  --   ccsds_flt_a_tap（mapper_symbols_samples 输出）= ±127   ← BPSK 的满量程
  --   ccsds_flt_b_tap（oversampler 输出，SRRC 输入） = {0, ±127}  ← 零插值，正确
  --   ccsds_sam_i_tap（SRRC 输出）                   = {0, -128}  ← ★ 只剩两个值，完全没有成形波形
  --
  -- 而同样的输入在 ModelSim 仿真里 SRRC 输出是 -46..+44（90 个不同取值）。
  -- 输入已经是满量程 ±127，SRRC 内部是"pipelined systolic"加法器树，
  -- 没有余量，综合后的溢出行为与仿真不一致 —— 这就是 ~0.35 倍增益变成饱和的原因。
  --
  -- 修法：进滤波器之前算术右移 2 位（÷4，保号），给加法器树留 4 倍余量。
  -- 由此带来的电平下降在 ccsds_tx_lvds 里用 SCALE_SHIFT 补回（3 -> 5）。
  signal wire_sam_i_pre: std_logic_vector(CCSDS_TX_FILTER_SIG_QUANT_DEPTH-1 downto 0);
  signal wire_sam_q_pre: std_logic_vector(CCSDS_TX_FILTER_SIG_QUANT_DEPTH-1 downto 0);
  signal wire_sam_i_val: std_logic := '0';
  signal wire_sam_q_val: std_logic := '0';
  signal wire_sam_i_osr: std_logic_vector(CCSDS_TX_FILTER_SIG_QUANT_DEPTH-1 downto 0);
  signal wire_sam_q_osr: std_logic_vector(CCSDS_TX_FILTER_SIG_QUANT_DEPTH-1 downto 0);
  signal wire_sam_i_osr_val: std_logic;
  signal wire_sam_q_osr_val: std_logic;
  signal wire_sam_i_srrc_val: std_logic;
  signal wire_sam_q_srrc_val: std_logic;
-- components instanciation and mapping
  begin
  tx_mapper_symbols_samples_i_0: ccsds_tx_mapper_symbols_samples
    generic map(
      CCSDS_TX_MAPPER_QUANTIZATION_DEPTH => CCSDS_TX_FILTER_SIG_QUANT_DEPTH,
      CCSDS_TX_MAPPER_TARGET_SNR => CCSDS_TX_FILTER_TARGET_SNR,
      CCSDS_TX_MAPPER_BITS_PER_SYMBOL => CCSDS_TX_FILTER_BITS_PER_SYMBOL
    )
    port map(
      clk_i => clk_i,
      sym_i => sym_i_i,
      sym_val_i => sym_val_i,
      rst_i => rst_i,
      sam_o => wire_sam_i,
      sam_val_o => wire_sam_i_val
    );
  tx_oversampler_i_0: ccsds_rxtx_oversampler
    generic map(
      CCSDS_RXTX_OVERSAMPLER_OVERSAMPLING_RATIO => CCSDS_TX_FILTER_OVERSAMPLING_RATIO,
      CCSDS_RXTX_OVERSAMPLER_SYMBOL_DEPHASING => CCSDS_TX_FILTER_OFFSET_IQ,
      CCSDS_RXTX_OVERSAMPLER_SIG_QUANT_DEPTH => CCSDS_TX_FILTER_SIG_QUANT_DEPTH
    )
    port map(
      clk_i => clk_i,
      sam_i => wire_sam_i_pre,      -- ★ ÷4 后的样点（原来直连 wire_sam_i）
      sam_val_i => wire_sam_i_val,
      rst_i => rst_i,
      sam_val_o => wire_sam_i_osr_val,
      sam_o => wire_sam_i_osr
    );
  tx_srrc_i_0: ccsds_rxtx_srrc
    generic map(
      CCSDS_RXTX_SRRC_OVERSAMPLING_RATIO => CCSDS_TX_FILTER_OVERSAMPLING_RATIO,
      CCSDS_RXTX_SRRC_SIG_QUANT_DEPTH => CCSDS_TX_FILTER_SIG_QUANT_DEPTH
    )
    port map(
      clk_i => clk_i,
      sam_i => wire_sam_i_osr,
      sam_val_i => wire_sam_i_osr_val,
      rst_i => rst_i,
      sam_o => sam_i_o,
      sam_val_o => wire_sam_i_srrc_val
    );
  -- BPSK
  BPSK_GENERATION: if (CCSDS_TX_FILTER_BITS_PER_SYMBOL = 1) and (CCSDS_TX_FILTER_MODULATION_TYPE = 2) generate
    sam_q_o <= (others => '0');
    wire_sam_q_srrc_val <= '1';
  end generate BPSK_GENERATION;
  -- nPSK
  NPSK_GENERATION: if (CCSDS_TX_FILTER_MODULATION_TYPE /= 2) or (CCSDS_TX_FILTER_BITS_PER_SYMBOL /= 1) generate
    tx_mapper_symbols_samples_q_0: ccsds_tx_mapper_symbols_samples
      generic map(
        CCSDS_TX_MAPPER_QUANTIZATION_DEPTH => CCSDS_TX_FILTER_SIG_QUANT_DEPTH,
        CCSDS_TX_MAPPER_TARGET_SNR => CCSDS_TX_FILTER_TARGET_SNR,
        CCSDS_TX_MAPPER_BITS_PER_SYMBOL => CCSDS_TX_FILTER_BITS_PER_SYMBOL
      )
      port map(
        clk_i => clk_i,
        sym_i => sym_q_i,
        sym_val_i => sym_val_i,
        rst_i => rst_i,
        sam_o => wire_sam_q,
        sam_val_o => wire_sam_q_val
      );
    tx_oversampler_q_0: ccsds_rxtx_oversampler
      generic map(
        CCSDS_RXTX_OVERSAMPLER_OVERSAMPLING_RATIO => CCSDS_TX_FILTER_OVERSAMPLING_RATIO,
        CCSDS_RXTX_OVERSAMPLER_SYMBOL_DEPHASING => false,
        CCSDS_RXTX_OVERSAMPLER_SIG_QUANT_DEPTH => CCSDS_TX_FILTER_SIG_QUANT_DEPTH
      )
      port map(
        clk_i => clk_i,
        sam_i => wire_sam_q,
        sam_val_i => wire_sam_q_val,
        rst_i => rst_i,
        sam_val_o => wire_sam_q_osr_val,
        sam_o => wire_sam_q_osr
      );
    tx_srrc_q_0: ccsds_rxtx_srrc
      generic map(
        CCSDS_RXTX_SRRC_OVERSAMPLING_RATIO => CCSDS_TX_FILTER_OVERSAMPLING_RATIO,
        CCSDS_RXTX_SRRC_SIG_QUANT_DEPTH => CCSDS_TX_FILTER_SIG_QUANT_DEPTH
      )
      port map(
        clk_i => clk_i,
        sam_i => wire_sam_q_osr,
        sam_val_i => wire_sam_q_osr_val,
        rst_i => rst_i,
        sam_o => sam_q_o,
        sam_val_o => wire_sam_q_srrc_val
      );
    end generate NPSK_GENERATION;
    --Valid samples indicator
    sam_val_o <= wire_sam_i_srrc_val and wire_sam_q_srrc_val;

    -- PROJECT PATCH (板级定位): 引出两级中间信号
    --   debug_a = mapper_symbols_samples 的输出（符号->幅度量化后，未上采样）
    --   debug_b = oversampler 的输出（SRRC 的输入）
    debug_a_o <= wire_sam_i;
    debug_b_o <= wire_sam_i_osr;

    -- ★ ÷4 预缩放（算术右移 2 位，补两个符号位，保证是有符号除法且位宽正好 8 位）
    --   ★ 位宽坑：写成 v(7) & v(7 downto 2) 只有 7 位（1+6），赋值给 8 位信号会出错/被截，
    --     必须补【两个】符号位：1+1+6 = 8。
    wire_sam_i_pre <= wire_sam_i(CCSDS_TX_FILTER_SIG_QUANT_DEPTH-1) &
                      wire_sam_i(CCSDS_TX_FILTER_SIG_QUANT_DEPTH-1) &
                      wire_sam_i(CCSDS_TX_FILTER_SIG_QUANT_DEPTH-1 downto 2);
    wire_sam_q_pre <= wire_sam_q(CCSDS_TX_FILTER_SIG_QUANT_DEPTH-1) &
                      wire_sam_q(CCSDS_TX_FILTER_SIG_QUANT_DEPTH-1) &
                      wire_sam_q(CCSDS_TX_FILTER_SIG_QUANT_DEPTH-1 downto 2);
-- presynthesis checks
	  CHKFILTERP0: if (CCSDS_TX_FILTER_BITS_PER_SYMBOL > 2*(CCSDS_TX_FILTER_SIG_QUANT_DEPTH-1)) generate
		  process
		  begin
			  report "ERROR: BITS PER SYMBOL CANNOT BE HIGHER THAN 2*(CCSDS_TX_FILTER_SIG_QUANT_DEPTH-1)" severity failure;
			  wait;
		  end process;
	  end generate CHKFILTERP0;
end structure;
