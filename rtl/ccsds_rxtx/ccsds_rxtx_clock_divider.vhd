-------------------------------
---- Project: EurySPACE CCSDS RX/TX with wishbone interface
---- Design Name: ccsds_rxtx_clock_divider
---- Version: 1.0.0
---- Description:
---- Generate output clock = input clock / divider
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
-- Entity declaration for ccsds_tx / unitary tx clock generator inputs and outputs
--=============================================================================
entity ccsds_rxtx_clock_divider is
  generic(
    constant CCSDS_RXTX_CLOCK_DIVIDER: integer range 1 to 4096
  );
  port(
    -- inputs
    clk_i: in std_logic;
    rst_i: in std_logic;
    -- outputs
    clk_o: out std_logic
  );
end ccsds_rxtx_clock_divider;

--=============================================================================
-- architecture declaration / internal components and connections
--=============================================================================
architecture structure of ccsds_rxtx_clock_divider is
-- internal constants
-- internal variable signals
-- components instanciation and mapping
  begin
-- presynthesis checks
	  CHKCLKDIV0: if (CCSDS_RXTX_CLOCK_DIVIDER mod 2 /= 0) and (CCSDS_RXTX_CLOCK_DIVIDER /= 1) generate
		  process
		  begin
			  report "ERROR: CLOCK DIVIDER MUST BE A MULTIPLE OF 2 OR 1" severity failure;
			  wait;
		  end process;
	  end generate CHKCLKDIV0;
-- internal processing
  CLOCKDIVIDER1P: if (CCSDS_RXTX_CLOCK_DIVIDER = 1) generate
    -- ★★★ PROJECT PATCH (板级根因修复) ★★★
    --
    -- 原来是：clk_o <= clk_i and (not rst_i);
    -- 而 rst_i 接的是 wire_rst_clk = not ena_i，ena_i = ad9361_config_init_done，
    -- 也就是：clk_sam = clk_i AND ena_i  —— 一个【组合门控时钟】。
    --
    -- 后果（板级实测，本会话最关键的一条结论）：
    --   ena_i 来自另一块逻辑锥，在时钟边沿附近会抖动，导致 clk_sam 上出现假钟沿。
    --   · mapper（clk_sym 域，每符号只动 1 位）—— 侥幸仍然正确（板上 300/300 CADU）
    --   · SRRC（clk_sam 域，61 级寄存器 + 61 个乘法器）—— 被假沿打乱，输出完全错误
    --     板级现象：sam_i 相邻样点跳 ±100（仿真里是平滑的、相邻差 ~5）
    --   而仿真里时钟理想、无毛刺，所以仿真 10/10 相位全过 —— 典型的
    --   "仿真对、板上错"，根因不在算法而在时钟实现。
    --
    -- Xilinx 明确不推荐用 fabric 组合逻辑分频做时钟（原厂 ADI 设计用的是 MMCM+BUFG）。
    -- 这里 DIVIDER=1，本来就不需要分频，直接透传时钟即可；
    -- 复位由各子模块自己的同步复位处理，不依赖"把时钟关掉"。
    clk_o <= clk_i;
  end generate CLOCKDIVIDER1P;
  CLOCKDIVIDERNP: if (CCSDS_RXTX_CLOCK_DIVIDER /= 1) generate
    --=============================================================================
    -- Begin of clockdividerp
    -- Clock divider
    --=============================================================================
    -- read: rst_i
    -- write: clk_o
    -- r/w:
    CLOCKDIVIDERP : process (clk_i, rst_i)
    -- variables instantiation
    variable counter: integer range 0 to CCSDS_RXTX_CLOCK_DIVIDER/2-1 := CCSDS_RXTX_CLOCK_DIVIDER/2-1;
    variable clock_state: std_logic := '1';
    begin
      if (rst_i = '1') then
        clk_o <= '0';
        clock_state := '1';
        counter := CCSDS_RXTX_CLOCK_DIVIDER/2-1;
      else
        -- on each clock rising edge
        if rising_edge(clk_i) then
          clk_o <= clock_state;
          if (counter = 0) then
            clock_state := clock_state xor '1';
            counter := CCSDS_RXTX_CLOCK_DIVIDER/2-1;
          else
            counter := counter-1;
          end if;
        end if;
      end if;
    end process;
  end generate CLOCKDIVIDERNP;
end structure;
