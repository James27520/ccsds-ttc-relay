--------------------------------------------------------------------------------
---- tb_frame_gen2 -- frame_gen 多帧序列验证
----
---- 导出 out/frame_gen_dut.txt：每帧一行，40 个十六进制字节拼接（byte0 在前）。
---- sim/check_frame_gen.py 逐帧与 Python build_tm_frame() 比对。
----
---- 覆盖的判据：
----   case 0 : SCID=0x2A VCID=0 OCF=0 sec=0 FHP=0x000  MCFC=0  VCFC=0  载荷 0x01..0x20
----   case 1 : 同上但载荷全 0xA5（验证载荷变化真的进了帧与 CRC）
----   case 2 : SCID=0x155 VCID=5 OCF=1 sec=1 FHP=0x123 载荷 0x00..0x1F
----   另：MCFC/VCFC 必须逐帧 +1（真实遥测的必要条件）
----
---- 用法: powershell -File sim/run_sim.ps1 -Tb tb_frame_gen2
--------------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.textio.all;

entity tb_frame_gen2 is
end tb_frame_gen2;

architecture bench of tb_frame_gen2 is

  constant CLK_PERIOD : time    := 10 ns;
  constant PAY_BYTES  : integer := 32;
  constant FRM_BYTES  : integer := 40;
  constant N_CASES    : integer := 3;

  component frame_gen is
    generic (
      constant FG_PAYLOAD_BYTES : integer;
      constant FG_FRAME_BYTES   : integer
    );
    port (
      clk         : in  std_logic;
      rst_n       : in  std_logic;
      cfg_scid    : in  std_logic_vector(9 downto 0);
      cfg_vcid    : in  std_logic_vector(2 downto 0);
      cfg_ocf     : in  std_logic;
      cfg_sec_hdr : in  std_logic;
      cfg_fhp     : in  std_logic_vector(10 downto 0);
      pay_we      : in  std_logic;
      pay_addr    : in  std_logic_vector(4 downto 0);
      pay_data    : in  std_logic_vector(7 downto 0);
      frame_go    : in  std_logic;
      mcfc        : out std_logic_vector(7 downto 0);
      frame_cnt   : out std_logic_vector(31 downto 0);
      busy        : out std_logic;
      frame_o     : out std_logic_vector(FRM_BYTES*8-1 downto 0);
      dat_o       : out std_logic_vector(15 downto 0);
      dat_val_o   : out std_logic
    );
  end component;

  signal clk         : std_logic := '0';
  signal rst_n       : std_logic := '1';
  signal cfg_scid    : std_logic_vector(9 downto 0)  := (others => '0');
  signal cfg_vcid    : std_logic_vector(2 downto 0)  := (others => '0');
  signal cfg_ocf     : std_logic := '0';
  signal cfg_sec_hdr : std_logic := '0';
  signal cfg_fhp     : std_logic_vector(10 downto 0) := (others => '0');
  signal pay_we      : std_logic := '0';
  signal pay_addr    : std_logic_vector(4 downto 0)  := (others => '0');
  signal pay_data    : std_logic_vector(7 downto 0)  := (others => '0');
  signal frame_go    : std_logic := '0';
  signal mcfc        : std_logic_vector(7 downto 0);
  signal frame_cnt   : std_logic_vector(31 downto 0);
  signal busy        : std_logic;
  signal frame_o     : std_logic_vector(FRM_BYTES*8-1 downto 0);
  signal dat_o       : std_logic_vector(15 downto 0);
  signal dat_val_o   : std_logic;

  signal done : boolean := false;
  signal errs : integer := 0;

  function byte_at (v : std_logic_vector; i : integer) return std_logic_vector is
    variable hi : integer;
  begin
    hi := (v'length/8 - 1 - i)*8 + 7;
    return v(hi downto hi-7);
  end function byte_at;

  function hex2 (v : std_logic_vector(7 downto 0)) return string is
    constant H : string(1 to 16) := "0123456789abcdef";
  begin
    return H(to_integer(unsigned(v(7 downto 4)))+1) & H(to_integer(unsigned(v(3 downto 0)))+1);
  end function hex2;

begin

  clk <= '0' when done else not clk after CLK_PERIOD/2;

  u_dut : frame_gen
    generic map (
      FG_PAYLOAD_BYTES => PAY_BYTES,
      FG_FRAME_BYTES   => FRM_BYTES
    )
    port map (
      clk         => clk,
      rst_n       => rst_n,
      cfg_scid    => cfg_scid,
      cfg_vcid    => cfg_vcid,
      cfg_ocf     => cfg_ocf,
      cfg_sec_hdr => cfg_sec_hdr,
      cfg_fhp     => cfg_fhp,
      pay_we      => pay_we,
      pay_addr    => pay_addr,
      pay_data    => pay_data,
      frame_go    => frame_go,
      mcfc        => mcfc,
      frame_cnt   => frame_cnt,
      busy        => busy,
      frame_o     => frame_o,
      dat_o       => dat_o,
      dat_val_o   => dat_val_o
    );

  STIM : process
    file     fo   : text;
    variable lo   : line;
    variable ngo  : integer;
    variable pay  : integer;   -- 载荷字节值（按 case 生成）
    variable pmode: integer;   -- 0 = i+1, 1 = 0xA5, 2 = i
  begin
    rst_n <= '0';
    wait for 10*CLK_PERIOD;
    rst_n <= '1';
    wait for 5*CLK_PERIOD;

    -- case 0
    pmode := 0;
    cfg_scid    <= std_logic_vector(to_unsigned(16#2A#, 10));
    cfg_vcid    <= "000";
    cfg_ocf     <= '0';
    cfg_sec_hdr <= '0';
    cfg_fhp     <= (others => '0');
    for c in 0 to N_CASES-1 loop

      -- 按 case 设置（case 0 已在循环外设好，这里对 1/2 重设）
      if c = 1 then
        pmode := 1;
      elsif c = 2 then
        pmode := 2;
        cfg_scid    <= std_logic_vector(to_unsigned(16#155#, 10));
        cfg_vcid    <= "101";
        cfg_ocf     <= '1';
        cfg_sec_hdr <= '1';
        -- 非零 FHP：软件参考 build_tm_frame() 把 w56 的 FHP 位域硬编码为 0，
        -- 所以这一帧不与它逐字节比对，改由 sim/check_frame_gen.py 做独立位域断言。
        cfg_fhp     <= std_logic_vector(to_unsigned(16#123#, 11));
      end if;
      wait for 2*CLK_PERIOD;

      -- 写载荷
      for i in 0 to PAY_BYTES-1 loop
        if    pmode = 0 then pay := i + 1;
        elsif pmode = 1 then pay := 16#A5#;
        else                 pay := i;
        end if;
        pay_addr <= std_logic_vector(to_unsigned(i, 5));
        pay_data <= std_logic_vector(to_unsigned(pay, 8));
        pay_we   <= '1';
        wait for CLK_PERIOD;
      end loop;
      pay_we <= '0';
      wait for 2*CLK_PERIOD;

      -- 触发组帧
      frame_go <= '1';
      wait for CLK_PERIOD;
      frame_go <= '0';

      ngo := 0;
      while (busy = '1' and ngo < 2000) loop
        wait for CLK_PERIOD;
        ngo := ngo + 1;
      end loop;
      wait for 5*CLK_PERIOD;

      report "TB: case " & integer'image(c) &
             " busy=" & integer'image(ngo) &
             " frame_cnt=" & integer'image(to_integer(unsigned(frame_cnt))) &
             " mcfc="    & integer'image(to_integer(unsigned(mcfc)))
             severity note;

      -- 时序判据
      if ngo /= 304 then
        report "TB: FAIL expected busy=304, got " & integer'image(ngo) severity error;
        errs <= errs + 1;
      end if;
      if to_integer(unsigned(frame_cnt)) /= c+1 then
        report "TB: FAIL frame_cnt expected " & integer'image(c+1) severity error;
        errs <= errs + 1;
      end if;

      -- 导出该帧
      if c = 0 then
        file_open(fo, "E:/ccsds_fpga/sim/out/frame_gen_dut.txt", write_mode);
      else
        file_open(fo, "E:/ccsds_fpga/sim/out/frame_gen_dut.txt", append_mode);
      end if;
      for i in 0 to FRM_BYTES-1 loop
        write(lo, hex2(byte_at(frame_o, i)));
        if i < FRM_BYTES-1 then
          write(lo, string'(" "));
        end if;
      end loop;
      writeline(fo, lo);
      file_close(fo);

    end loop;

    report "TB: total timing errors = " & integer'image(errs) severity note;
    report "TB: frame_gen multi-frame dump complete" severity note;
    done <= true;
    wait;
  end process;

end bench;
