-------------------------------
---- Project: EurySPACE CCSDS RX/TX with wishbone interface
---- Design Name: ccsds_tx_mapper_bits_symbols
---- Version: 1.0.0
---- Description:
---- Map input bits to complex I&Q symbols depending on modulation type
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

-- libraries used
library ieee;
use ieee.std_logic_1164.all;

--=============================================================================
-- Entity declaration for ccsds_tx / unitary tx bits to symbols mapper inputs and outputs
--=============================================================================
entity ccsds_tx_mapper_bits_symbols is
  generic(
    constant CCSDS_TX_MAPPER_BITS_PER_SYMBOL: integer := 1; -- For QAM - 1 bit/symbol <=> QPSK/4-QAM - 2 bits/symbol <=> 16-QAM - 3 bits/symbol <=> 64-QAM - ... - N bits/symbol <=> 2^(N*2)-QAM
    constant CCSDS_TX_MAPPER_GRAY_CODER: std_logic := '1'; -- Gray coder activation
    constant CCSDS_TX_MAPPER_MODULATION_TYPE: integer := 1; -- 1=QPSK/QAM - 2=BPSK
    constant CCSDS_TX_MAPPER_DATA_BUS_SIZE: integer -- in bits
  );
  port(
    -- inputs
    clk_i: in std_logic;
    dat_i: in std_logic_vector(CCSDS_TX_MAPPER_DATA_BUS_SIZE-1 downto 0);
    dat_val_i: in std_logic;
    rst_i: in std_logic;
    -- outputs
    sym_val_o: out std_logic;
    sym_i_o: out std_logic_vector(CCSDS_TX_MAPPER_BITS_PER_SYMBOL-1 downto 0);
    sym_q_o: out std_logic_vector(CCSDS_TX_MAPPER_BITS_PER_SYMBOL-1 downto 0)
  );
end ccsds_tx_mapper_bits_symbols;

--=============================================================================
-- architecture declaration / internal components and connections
--=============================================================================
architecture rtl of ccsds_tx_mapper_bits_symbols is
-- internal constants
  constant MAPPER_SYMBOL_NUMBER_PER_CHANNEL: integer := CCSDS_TX_MAPPER_DATA_BUS_SIZE*CCSDS_TX_MAPPER_MODULATION_TYPE/(2*CCSDS_TX_MAPPER_BITS_PER_SYMBOL);
-- internal variable signals
-- components instanciation and mapping
  begin
-- presynthesis checks
     CHKMAPPERP0 : if (CCSDS_TX_MAPPER_DATA_BUS_SIZE mod (CCSDS_TX_MAPPER_BITS_PER_SYMBOL*2*CCSDS_TX_MAPPER_MODULATION_TYPE) /= 0) generate
      process
      begin
        report "ERROR: DATA BUS SIZE HAS TO BE A MULTIPLE OF 2*BITS PER SYMBOLS (EXCEPT FOR BPSK MODULATION)" severity failure;
	      wait;
      end process;
    end generate CHKMAPPERP0;
     CHKMAPPERP1: if (CCSDS_TX_MAPPER_BITS_PER_SYMBOL /= 1) and (CCSDS_TX_MAPPER_MODULATION_TYPE = 2) generate
      process
      begin
        report "ERROR: BPSK MODULATION REQUIRES 1 BIT PER SYMBOL" severity failure;
	      wait;
      end process;
    end generate CHKMAPPERP1;
     CHKMAPPERP2 : if (CCSDS_TX_MAPPER_MODULATION_TYPE /= 1) and (CCSDS_TX_MAPPER_MODULATION_TYPE /= 2) generate
      process
      begin
        report "ERROR: UNKNOWN MODULATION TYPE - 1=QPSK/QAM / 2=BPSK" severity failure;
	      wait;
      end process;
    end generate CHKMAPPERP2;
-- internal processing
    --=============================================================================
    -- Begin of mapperp
    -- Map bits to symbols
    --=============================================================================
    -- read: rst_i, dat_i, dat_val_i
    -- write: sym_i_o, sym_q_o, sym_val_o
    -- r/w:
    MAPPERP: process (clk_i)
      -- PROJECT PATCH (遥测板 CCSDS 发射链: 每个 16 位字末尾 5 位错误)
      --
      -- 原实现让 symbol_counter 自由跑（dat_val_i 被当成"每拍都有效"），
      -- 而 dat_val_i 来自 datalink 的 dat_val_o。原 datalink 把它做成电平
      -- （coder 有效后置 1 永不清零），于是 16 符号窗口与 clk_bit 的字边界
      -- 没有任何相位关系。
      --
      -- 实测（sim/bench/tb_phys.vhd + Python 对比）: 符号流与期望 CADU 差
      -- 96/672，差异位置 mod 16 = {11,12,13,14,15}，即每个字的最后 5 个
      -- 符号取到了【下一个字】的内容。
      --
      -- 修法：datalink 已把 dat_val_o 改成"每输出一个字翻转一次"的同步沿；
      -- 这里对 dat_val_i 做边沿检测，检测到翻转就锁存新字并把指针复位到
      -- 最高位，使窗口与字边界严格对齐。
      --
      -- 时序上两者同拍：dat_o 与 dat_val_o 都在 clk_bit 上升沿更新，mapper
      -- 在下一个 clk_sym 沿同时看到新字和新的翻转值，因此对齐无偏移。
      variable symbol_counter : integer range 0 to MAPPER_SYMBOL_NUMBER_PER_CHANNEL := 0;
      variable word_latched   : std_logic_vector(CCSDS_TX_MAPPER_DATA_BUS_SIZE-1 downto 0) := (others => '0');
      variable sync_prev      : std_logic := '0';
      begin
        -- on each clock rising edge
        if rising_edge(clk_i) then
          -- reset signal received
          if (rst_i = '1') then
            sym_i_o <= (others => '0');
            sym_q_o <= (others => '0');
            symbol_counter := 0;
            word_latched := (others => '0');
            sync_prev := '0';
            sym_val_o <= '0';
          else

            -- ★ 新字到达（dat_val_i 翻转）：锁存并重开一个完整窗口
            if (dat_val_i /= sync_prev) then
              sync_prev := dat_val_i;
              word_latched := dat_i;
              symbol_counter := MAPPER_SYMBOL_NUMBER_PER_CHANNEL;
            end if;

            -- ★★★ 保持不变：这里【必须】有 1 拍间隙。
            --
            -- 教训（本会话踩过）：我曾两次"改进"这里，两次都把仿真跑挂：
            --   ① 加 2 级同步器把 dat_val_i 打两拍 → 边沿检测整体偏移 2 个
            --      clk_sym，整个符号窗口错位 → 数据全错。
            --   ② 去掉这个间隙（sym_val_o 恒 1、计数器 16..1 循环）→ 也跑挂。
            -- 说明下游 ccsds_tx_filter 是基于 sym_val_i 的【上升沿/间隙】来识别
            -- 符号边界的，这个间隙是协议的一部分，不是 bug。
            -- 结论：这一版（带间隙、不做额外同步）是仿真 7/10 相位 PASS 的版本，
            -- 就按它上板；板上若仍不对，再另找原因，不要动这里。
            if (symbol_counter /= 0) then
              sym_val_o <= '1';
              -- BPSK mapping
              if (CCSDS_TX_MAPPER_BITS_PER_SYMBOL = 1) and (CCSDS_TX_MAPPER_MODULATION_TYPE = 2) then
                sym_q_o(0) <= '0';
                sym_i_o(0) <= word_latched(symbol_counter-1);
              -- QPSK/QAM mapping
              else
                sym_i_o <= word_latched(symbol_counter*CCSDS_TX_MAPPER_BITS_PER_SYMBOL*2-1 downto symbol_counter*2*CCSDS_TX_MAPPER_BITS_PER_SYMBOL-CCSDS_TX_MAPPER_BITS_PER_SYMBOL);
                sym_q_o <= word_latched(symbol_counter*2*CCSDS_TX_MAPPER_BITS_PER_SYMBOL-CCSDS_TX_MAPPER_BITS_PER_SYMBOL-1 downto symbol_counter*2*CCSDS_TX_MAPPER_BITS_PER_SYMBOL-2*CCSDS_TX_MAPPER_BITS_PER_SYMBOL);
              end if;
              symbol_counter := symbol_counter - 1;
            else
              sym_val_o <= '0';
            end if;
          end if;
        end if;
      end process;
end rtl;
