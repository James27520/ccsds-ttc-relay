--------------------------------------------------------------------------------
---- Project : CCSDS 遥测发射链 FPGA 移植 (7010_AD9363SDR)
---- Design  : frame_gen -- 动态 TM 传输帧源（取代固定常量 CADU）
---- Version : 1.0.0
----
---- 为什么需要它
---- ============
---- 移植期为了 bring-up，ccsds_tx_datalink_layer 用常量 STATIC_FRAME 喂编码器
---- （CCSDS_TX_DATALINK_STATIC_FRAME_ENABLED = true）。代价是发出的 CADU 永远
---- 是开机那一帧（FHP=0x7FE、载荷 32×0xFF、MCFC 恒 0）—— 不能承载真实遥测。
----
---- 为什么不修上游 framer（实测结论，见 PORTING_NOTES.md §5）
---- ======================================================
----   frame_output_counter 与 next_frame_write_pos 的重装值在 P=1 时相等
----   -> 相位锁死，current_frame_ready 永远来不及置位；
----   且 footer valid 之后再没拉高过 -> 恒定输出空闲帧。
----   另外上游 CRC 等效 CRC-16/AUG-CCITT(init 0x1D0F)，与地面接收端
----   需要的 CCITT-FALSE(init 0xFFFF) 不同参。
----   所以本模块自己组帧 + 自己算 CRC。
----
---- 帧结构（与软件参考 ccsds_tm_tx.build_tm_frame 逐字节一致）
---- ==========================================================
----   byte 0-1  : w0  = 版本(2b)=0 | SCID(10b) | VCID(3b) | OCF(1b)   大端
----   byte 2    : MCFC (主信道帧计数，每帧 +1)
----   byte 3    : VCFC (虚拟信道帧计数，每帧 +1)
----   byte 4-5  : w56 = 副头标志(1b) | 同步标志(1b) | 包序标志(1b) |
----                     段长标识(2b)=11b | 首包头指针(11b)             大端
----   byte 6..37: 载荷 32 字节
----   byte 38-39: FECF = CRC-16/CCITT-FALSE(body)，大端
----   总长 40 字节 = 320 bit
----
---- CRC-16/CCITT-FALSE：poly=0x1021、init=0xFFFF、不反转、无末异或、MSB-first
---- ================================================================
----   与软件 crc16() 逐位等价。逐位实现（每字节 8 拍）以保证可审计，
----   40 字节 x 8 = 320 拍 << 一帧的 2xNWORDS 拍预算。
----
---- 时序
---- ====
---- 全部在 clk_dat（datalink 字时钟）域。一帧 = NWORDS 个字周期
---- （NWORDS = 40*8/16 = 20；实测 CADU 672 bit 时 datalink 的
----  FRAME_OUTPUT_WORDS = 42，本模块输出 20 个字，余量充足）。
---- 双缓冲：一块在组装、一块被输出，组装有 2xNWORDS 拍可用。
----
---- Author: 本项目自行编写（非 euryspace 派生）
--------------------------------------------------------------------------------

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity frame_gen is
  generic (
    constant FG_PAYLOAD_BYTES : integer := 32;                  -- 载荷字节数
    constant FG_FRAME_BYTES   : integer := 32 + 6 + 2           -- 含 6B 头 + 2B FECF
  );
  port (
    clk       : in  std_logic;
    rst_n     : in  std_logic;

    -- ---- 配置（准静态，来自 AXI 寄存器）----
    cfg_scid    : in  std_logic_vector(9 downto 0);
    cfg_vcid    : in  std_logic_vector(2 downto 0);
    cfg_ocf     : in  std_logic;
    cfg_sec_hdr : in  std_logic;
    cfg_fhp     : in  std_logic_vector(10 downto 0);

    -- ---- 载荷写入口（AXI 侧随时可写，影子寄存器）----
    pay_we    : in  std_logic;
    pay_addr  : in  std_logic_vector(4 downto 0);
    pay_data  : in  std_logic_vector(7 downto 0);

    -- ---- 帧启动：一个 clk 脉冲表示"把当前影子载荷封成一帧"----
    frame_go  : in  std_logic;

    -- ---- 诊断 ----
    mcfc      : out std_logic_vector(7 downto 0);   -- 当前输出帧的 MCFC
    frame_cnt : out std_logic_vector(31 downto 0);  -- 已封帧总数
    busy      : out std_logic;                      -- 正在组装

    -- ---- 整帧输出（准静态，直到下一帧被封好）----
    --   宽位向量：frame_o(FG_FRAME_BYTES*8-1 downto 0)
    --   字节 i 位于 bit (FG_FRAME_BYTES-1-i)*8 +7 downto (FG_FRAME_BYTES-1-i)*8
    --   即 frame_o(319 downto 312) = 帧第 0 字节（最高字的高字节）
    frame_o   : out std_logic_vector(FG_FRAME_BYTES*8-1 downto 0);

    -- ---- 帧字输出：datalink 期望的顺序（最高字先）----
    dat_o     : out std_logic_vector(15 downto 0);
    -- 整帧就绪（准静态，直到下一帧被封装）
    dat_val_o : out std_logic
  );
end frame_gen;

architecture rtl of frame_gen is

  constant NWORDS : integer := FG_FRAME_BYTES * 8 / 16;   -- 20

  type frame_t is array (0 to FG_FRAME_BYTES-1) of std_logic_vector(7 downto 0);

  -- 双缓冲
  signal frame_a : frame_t := (others => (others => '0'));
  signal frame_b : frame_t := (others => (others => '0'));
  signal out_sel : std_logic := '0';        -- 0 => 输出 frame_a

  -- 载荷影子寄存器
  signal pay : frame_t := (others => (others => '0'));

  -- 外层 FSM
  type state_t is (S_IDLE, S_ASM, S_DONE);
  signal st : state_t := S_IDLE;

  -- 内层按位 CRC
  signal crc_r     : std_logic_vector(15 downto 0) := (others => '0');
  signal byte_i    : integer range 0 to FG_PAYLOAD_BYTES := 0;  -- 载荷字节索引
  signal bit_i     : integer range 0 to 8 := 0;                 -- 该字节已处理位数
  signal stage     : integer range 0 to 1 := 0;                 -- 0=头 1=载荷
  signal body_i    : integer range 0 to FG_FRAME_BYTES := 0;    -- 头字节索引

  -- 输出
  signal rd_frame : frame_t;
  signal mcfc_r   : unsigned(7 downto 0) := (others => '0');
  signal vcfc_r   : unsigned(7 downto 0) := (others => '0');
  signal rd_mcfc  : std_logic_vector(7 downto 0) := (others => '0');
  signal fc       : unsigned(31 downto 0) := (others => '0');
  signal ready_r  : std_logic := '0';

  -- 大端取字：word j = {byte 2j, byte 2j+1}
  -- 用函数避免在端口上做变址运算
  function word_of (f : frame_t; j : integer) return std_logic_vector is
  begin
    return f(2*j) & f(2*j + 1);
  end function word_of;

begin

  ----------------------------------------------------------------------------
  -- 组帧 FSM
  ----------------------------------------------------------------------------
  process (clk, rst_n)
    variable w0  : std_logic_vector(15 downto 0);
    variable w56 : std_logic_vector(15 downto 0);
    variable al  : std_logic_vector(7 downto 0);   -- 当前处理的字节
    variable crc : std_logic_vector(15 downto 0);
    variable tgt : integer;                        -- 目标缓冲选择
    variable b   : std_logic_vector(7 downto 0);   -- 当前字节（用于写缓冲）
  begin
    if rst_n = '0' then
      st      <= S_IDLE;
      crc_r   <= (others => '0');
      byte_i  <= 0;
      bit_i   <= 0;
      stage   <= 0;
      body_i  <= 0;
      mcfc_r  <= (others => '0');
      vcfc_r  <= (others => '0');
      out_sel <= '0';
      fc      <= (others => '0');
      ready_r <= '0';
    elsif rising_edge(clk) then

      -- 载荷影子写入口（任何状态都可写）
      if pay_we = '1' then
        pay(to_integer(unsigned(pay_addr))) <= pay_data;
      end if;

      case st is

        ----------------------------------------------------------------
        when S_IDLE =>
          ready_r <= '0';
          if frame_go = '1' then
            -- 头两个字（组合）
            w0  := std_logic_vector(to_unsigned(0,2)) & cfg_scid & cfg_vcid & cfg_ocf;
            w56 := cfg_sec_hdr & '0' & '0' & "11" & cfg_fhp;
            -- 头 6 字节写入目标缓冲
            if out_sel = '0' then
              frame_b(0) <= w0(15 downto 8);
              frame_b(1) <= w0(7  downto 0);
              frame_b(2) <= std_logic_vector(mcfc_r);
              frame_b(3) <= std_logic_vector(vcfc_r);
              frame_b(4) <= w56(15 downto 8);
              frame_b(5) <= w56(7  downto 0);
            else
              frame_a(0) <= w0(15 downto 8);
              frame_a(1) <= w0(7  downto 0);
              frame_a(2) <= std_logic_vector(mcfc_r);
              frame_a(3) <= std_logic_vector(vcfc_r);
              frame_a(4) <= w56(15 downto 8);
              frame_a(5) <= w56(7  downto 0);
            end if;
            -- CRC init 0xFFFF，然后逐位处理 6 个头字节
            crc_r   <= (others => '1');
            body_i  <= 0;      -- 0..5 头
            bit_i   <= 0;
            stage   <= 0;
            byte_i  <= 0;
            st      <= S_ASM;
          end if;

        ----------------------------------------------------------------
        -- 逐位推进 CRC。stage=0 处理 6 个头字节，stage=1 处理 32 个载荷字节。
        -- 每字节 8 拍 -> 头 48 拍 + 载荷 256 拍 = 304 拍。
        ----------------------------------------------------------------
        when S_ASM =>
          -- 取当前要处理的字节
          if stage = 0 then
            w0  := std_logic_vector(to_unsigned(0,2)) & cfg_scid & cfg_vcid & cfg_ocf;
            w56 := cfg_sec_hdr & '0' & '0' & "11" & cfg_fhp;
            if out_sel = '0' then
              case body_i is
                when 0 => al := frame_b(0);
                when 1 => al := frame_b(1);
                when 2 => al := frame_b(2);
                when 3 => al := frame_b(3);
                when 4 => al := frame_b(4);
                when others => al := frame_b(5);
              end case;
            else
              case body_i is
                when 0 => al := frame_a(0);
                when 1 => al := frame_a(1);
                when 2 => al := frame_a(2);
                when 3 => al := frame_a(3);
                when 4 => al := frame_a(4);
                when others => al := frame_a(5);
              end case;
            end if;
            -- 同时把载荷字节搬进目标缓冲（用 body_i 复用为载荷搬运索引的时机在 stage=1）
          else
            al := pay(byte_i);
            -- 搬进目标缓冲
            if out_sel = '0' then frame_b(6 + byte_i) <= pay(byte_i);
            else                   frame_a(6 + byte_i) <= pay(byte_i); end if;
          end if;

          -- 一位 CRC 推进：按 MSB-first
          crc := crc_r;
          if (crc(15) xor al(7 - bit_i)) = '1' then
            crc := (crc(14 downto 0) & '0') xor x"1021";
          else
            crc := (crc(14 downto 0) & '0');
          end if;

          if bit_i = 7 then
            -- 该字节处理完
            crc_r  <= crc;
            bit_i  <= 0;
            if stage = 0 then
              if body_i = 5 then
                stage  <= 1;
                byte_i <= 0;
              else
                body_i <= body_i + 1;
              end if;
            else
              if byte_i = FG_PAYLOAD_BYTES - 1 then
                -- 全部数据字节处理完，写 FECF
                if out_sel = '0' then
                  frame_b(FG_FRAME_BYTES-2) <= crc(15 downto 8);
                  frame_b(FG_FRAME_BYTES-1) <= crc(7  downto 0);
                else
                  frame_a(FG_FRAME_BYTES-2) <= crc(15 downto 8);
                  frame_a(FG_FRAME_BYTES-1) <= crc(7  downto 0);
                end if;
                st <= S_DONE;
              else
                byte_i <= byte_i + 1;
              end if;
            end if;
          else
            crc_r <= crc;
            bit_i <= bit_i + 1;
          end if;

        ----------------------------------------------------------------
        when S_DONE =>
          -- 切换输出缓冲，推进计数
          rd_mcfc <= std_logic_vector(mcfc_r);
          fc      <= fc + 1;
          mcfc_r  <= mcfc_r + 1;
          vcfc_r  <= vcfc_r + 1;
          out_sel <= not out_sel;
          ready_r <= '1';
          st      <= S_IDLE;

        when others =>
          st <= S_IDLE;
      end case;
    end if;
  end process;

  ----------------------------------------------------------------------------
  -- 输出侧
  ----------------------------------------------------------------------------
  rd_frame  <= frame_a when out_sel = '0' else frame_b;

  -- 整帧宽位向量输出：字节 i -> bits (FG_FRAME_BYTES-1-i)*8+7 downto (FG_FRAME_BYTES-1-i)*8
  gen_frame_o : for i in 0 to FG_FRAME_BYTES-1 generate
    frame_o((FG_FRAME_BYTES-1-i)*8 + 7 downto (FG_FRAME_BYTES-1-i)*8) <= rd_frame(i);
  end generate;

  -- 第 0 号字（最高字）。使用方若需要整帧，直接用 frame_o。
  dat_o     <= word_of(rd_frame, 0);

  dat_val_o <= ready_r;
  mcfc      <= rd_mcfc;
  frame_cnt <= std_logic_vector(fc);
  busy      <= '1' when st = S_ASM else '0';

end rtl;
