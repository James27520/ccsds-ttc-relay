"""gen_ttc_report.py -- 遥测遥控 FPGA 移植报告（DOCX）

素材全部来自本会话的实测记录：
  E:\\ccsds_fpga\\REMOTE_BOARD_HANDOFF.md     走不通路径的完整记录
  E:\\ccsds_fpga\\JTAG_DEPLOY_RECIPE.md       已验证可行的部署配方
  E:\\ccsds_fpga\\ONBOARD_DEPLOY_NOTES.md     板卡操作备忘
"""

from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

doc = Document()

# 中文字体：python-docx 需要显式设置 eastAsia，否则中文可能回退
style = doc.styles["Normal"]
style.font.name = "Microsoft YaHei"
style.font.size = Pt(10.5)
style.element.rPr.rFonts.set(
    "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}eastAsia",
    "Microsoft YaHei")


def h(text, level=1):
    p = doc.add_heading(text, level=level)
    for r in p.runs:
        r.font.name = "Microsoft YaHei"
        r.element.rPr.rFonts.set(
            "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}eastAsia",
            "Microsoft YaHei")
    return p


def para(text, bold=False, italic=False):
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.bold = bold
    r.italic = italic
    r.font.name = "Microsoft YaHei"
    r.element.rPr.rFonts.set(
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}eastAsia",
        "Microsoft YaHei")
    return p


def mono(lines, caption=None):
    if caption:
        para(caption, bold=True)
    for ln in lines:
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Pt(18)
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(ln)
        r.font.name = "Consolas"
        r.font.size = Pt(9)


def table(headers, rows):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Light Grid Accent 1"
    for i, hd in enumerate(headers):
        c = t.rows[0].cells[i]
        c.text = ""
        r = c.paragraphs[0].add_run(hd)
        r.bold = True
        r.font.size = Pt(9.5)
        r.font.name = "Microsoft YaHei"
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            r = cells[i].paragraphs[0].add_run(str(v))
            r.font.size = Pt(9.5)
            r.font.name = "Microsoft YaHei"
    doc.add_paragraph()
    return t


# ============================================================ 封面
doc.add_heading("遥测遥控 FPGA 移植报告", 0)
para("CCSDS 遥测发射链从 Altera 参考设计到 AMD Zynq-7010 的移植、验证与上板部署", italic=True)
doc.add_paragraph()
table(["项目", "内容"], [
    ["目标器件", "Zynq XC7Z010 (7z010clg400-1) + AD9361 (CMOS 1R1T)"],
    ["目标板卡", "遥控板 7010_AD9363SDR"],
    ["协议参考", "euryspace CCSDS 协议核（Altera/DE0-Nano 参考设计）"],
    ["验证基准", "E:\\fpga_sdr_project\\ccsds_ttc_loopback\\sw\\ttc（双板射频环回已通过）"],
    ["开发环境", "Vivado 2018.3 / ModelSim ASE 10.5b"],
    ["状态", "仿真闭环完成；上板部署已打通 JTAG 通道，剩最后一步时序配合"],
])

# ============================================================ 1
h("1  项目背景与目标", 1)
para("本项目将一套已在软件侧（PC + Python）验证通过的 CCSDS 遥测发射链，"
     "移植进遥控板 Zynq-7010 的 PL 中，使其脱离 PC 独立工作，"
     "为后续星载载荷（透明转发 + 遥测遥控）做硬件准备。")
para("严格来说这不是一次普通的\u201c平台移植\u201d，而是三件事叠加：", bold=True)
table(["层次", "内容"], [
    ["① 平台移植", "协议核从 Altera 工程搬进 AMD Vivado 工程"],
    ["② 缺陷修复", "协议核本身与已验证软件参考之间存在 4 处致命不一致"],
    ["③ 系统集成", "接入 AD9361 接口、绕过锁定的 Block Design、解决上板部署"],
])

# ============================================================ 2
h("2  系统架构", 1)

h("2.1  两块板卡的定位", 2)
para("项目中涉及两块板卡，它们的差别常被低估——并非\u201c遥控板只多一个协议\u201d，"
     "而是数据通路架构根本不同。")
table(["", "遥控板 7010_AD9363SDR", "转发板 LDSDR"], [
    ["FPGA", "XC7Z010 (7z010clg400-1)", "XC7Z010（同款）"],
    ["射频", "AD9361 CMOS 1R1T", "AD9361 LVDS 2R2T"],
    ["PS 操作系统", "Linux 5.15（ADI PlutoSDR 固件）", "裸机 + 串口 CLI"],
    ["驱动栈", "完整 IIO（iio_attr / iio_readdev）", "无"],
    ["S_AXI_HP0", "启用（DMA 直通 DDR）", "禁用"],
    ["数据通路", "ADC→axi_dmac→DDR→Linux；DMA→DAC", "RX→TX 在 PL 内直连，不进 DDR"],
    ["能否抓样点", "能", "不能"],
    ["Block Design", "ADI 参考设计，IP 全部锁定", "自定义 design_1，可编辑"],
    ["启动介质", "SD 卡（出厂 pluto-fw-v0.38）", "SD 卡（BD 里 QSPI 已禁用）"],
])
para("关键结论：转发板是一条\u201c硬件直连管道\u201d，数据不经 PS，所以对软件栈几乎零依赖，"
     "上电即工作；遥控板的数据必须穿过 PS，因此 Linux 起不来、驱动初始化不正确，"
     "整块板子就是废的。这决定了两块板卡完全不同的调试难度。", bold=True)

h("2.2  遥控板通道数", 2)
para("AD9361 芯片本身支持 2R2T（板上有 4 个 SMA 口），但本板 PL 设计只做了 1R1T：")
mono([
    "system_top.v 顶层端口:",
    "  input         rx_clk_in        <- 只有 1 条 RX 时钟",
    "  input  [11:0] rx_data_in       <- 只有 1 组 12 位 RX 总线",
    "  output [11:0] tx_data_out      <- 只有 1 组 12 位 TX 总线",
    "",
    "BD 参数:  MODE_1R1T = 1 ,  CMOS_OR_LVDS_N = 1",
    "uEnv.txt: mode=1r1t",
])
para("由于 ADI 的 IP 全部 locked=1 无法修改，第二通道在本板上不可用。"
     "当前的 CCSDS 发射链使用的是 PL 能提供的全部资源，没有浪费。")

# ============================================================ 3
h("3  移植方法：为什么\u201c库层面是零工作量\u201d", 1)
para("移植可行性的第一步不是改代码，而是依赖扫描。对 30 个 VHDL 文件统计全部 library/use 子句：")
mono([
    "29x  library ieee;",
    "29x  use ieee.std_logic_1164.all;",
    " 6x  use ieee.numeric_std.all;",
    " 2x  use ieee.math_real.all;",
    " 3x  use work.ccsds_rxtx_functions.all;",
    " 2x  use work.ccsds_rxtx_parameters.all;",
    " 2x  use work.ccsds_rxtx_types.all;",
    "",
    "厂商库扫描: altera / cyclone / stratix / arria / megafunction /",
    "           lpm_ / altpll / altera_mf / unisim / xilinx   ->  全部 0 处",
])
para("VHDL 的 library 是逻辑命名空间而非二进制库。ieee 是工具自带的（Quartus 有、Vivado 也有），"
     "自己的包就是那 4 个 .vhd 源文件。因此不存在\u201c移库\u201d这个动作，"
     "只需按依赖顺序编译并写好接口适配层。", bold=True)
table(["移植步骤", "内容"], [
    ["① 依赖扫描", "证明零厂商原语，确定可行性"],
    ["② 编译顺序", "euryspace 的 .core 顺序有误（functions 排在 types 前），须手工排正"],
    ["③ 丢弃专有部分", "SoC 层（.sof/.jic、DE0-Nano 板级）整块不要；Wishbone 总线重写"],
    ["④ AMD 侧适配", "rtl/adapter/ccsds_tx_wrap.v：8→12 位定标、BPSK 极性、12 个 ODDR"],
])
para("AMD 侧唯一使用的厂商特性是 attribute use_dsp，用于控制 SRRC 乘法器的实现方式（见 4.2）。")

# ============================================================ 4
h("4  移植中遇到的问题", 1)
para("本章是报告重点。问题分三类：协议一致性、资源取舍、上板部署。"
     "每一类都记录现象、定位过程和结论。")

# ---- 4.1
h("4.1  协议一致性：4 处会直接导致收不到码的不一致", 2)
para("协议核原样编译通过 ≠ 能收到码。以\u201c已在双板射频环回上验证通过的软件实现\u201d"
     "为基准逐条比对，发现 4 处致命差异：")
table(["#", "问题", "后果", "定位方式"], [
    ["1", "ccsds_tx_coder 根本没接卷积编码（目录里有 convolutional 模块但从未被实例化）",
     "接收端完全解不出", "逐模块比对数据流"],
    ["2", "随机化 LFSR 多项式被位反转：实现为 {0,2,4,7}=0x95，CCSDS 要求 {0,3,5,7}=0xA9",
     "解随机化全错", "仿真波形与软件参考逐位比对"],
    ["3", "BPSK 极性相反（VHDL bit0→负满量程，软件参考 bit0→+1）",
     "判决全反", "同上"],
    ["4", "帧长 20 字节，而接收端只搜索 40/108 字节的帧",
     "找不到帧", "读接收端源码 auto_decode.py:92"],
])
para("第 2 项的根因值得单独记录：", bold=True)
para("VHDL 中用字符串字面量初始化未约束 std_logic_vector 时，索引范围是【升序】的，"
     "POLYNOMIAL(0) 是最左字符（最高位）而非最低位。"
     "因此按\u201c第 0/1/2… 位\u201d抽头会得到位反转的多项式。"
     "修复方式是在 ccsds_rxtx_lfsr.vhd 中加入 normalise_polynomial 函数做规范化。")
para("另有一处非致命差异：SRRC 默认 β=0.5 + Hamming 窗，而软件版是 β=0.35 无窗，"
     "已改为与软件版一致。")

# ---- 4.2
h("4.2  资源取舍：SRRC 的 DSP 与 LUT 之争", 2)
para("SRRC 成形滤波器在 OSR=10、span=6 时有 61 个抽头，系数是编译期常量。"
     "Vivado 默认会为每个抽头推断一个 DSP48。实测 A/B（模块级综合）：")
table(["use_dsp 设置", "DSP48", "LUT"], [
    ['"no"（强制 LUT）', "0", "1832"],
    ['"yes"/默认推断', "20", "1035"],
])
para("最终选择 use_dsp=\"no\"，理由是 DSP 是这块板最紧的资源。整版资源对比：")
table(["资源", "基线（无 CCSDS）", "加入 CCSDS 后", "增量"], [
    ["LUT", "7817", "11194 (63.60%)", "+3377"],
    ["FF", "14142", "18479 (52.50%)", "+4337"],
    ["BRAM", "2", "2 (3.33%)", "+0"],
    ["DSP48", "56", "56 (70.00%)", "+0"],
])
para("重要教训（已写入源码注释防止重蹈）：", bold=True)
para("后续曾尝试把 use_dsp 改为 \"yes\" 以腾出 LUT、缩小位流，结果整版布局失败：")
mono([
    "ERROR: [Place 30-640] This design requires more DSPs cells than are available.",
    "       requires 96 of such cell types but only 80 compatible sites are available.",
])
para("原因：模块级 A/B 只反映 SRRC 自身需要 20 个 DSP，但整版综合后 Vivado 会把其他逻辑也"
     "推给 DSP48，总需求达到 96，超过 XC7Z010 的 80 个上限。"
     "结论：use_dsp=\"no\" 是必须的，不能改。")

# ---- 4.3
h("4.3  上板部署：本报告篇幅最大、代价最高的一节", 2)
para("这是整个项目中最曲折的部分。为便于后续复现与避坑，按尝试顺序完整记录。")

h("4.3.1  先决认知：板子的启动方式", 3)
para("从厂商资料与实测确认：")
mono([
    "SD 卡启动（出厂即如此，厂商说明文档：\"出厂所带SD卡为固件pluto-fw-v0.38\"）",
    "启动介质由 BOOT1 两位拨码选择（控制 QSPI_D2/QSPI_D3 = Zynq MIO[4]/MIO[5]）",
    "",
    "QSPI 分区（板子基本不读，仅 u-boot 环境 mtd1 会被读）：",
    "  mtd0 qspi-fsbl-uboot 1MB    mtd1 qspi-uboot-env 128KB",
    "  mtd2 qspi-nvmfs     896KB   mtd3 qspi-linux     14MB",
])
para("位流由 FSBL 从 SD 卡 BOOT.bin 加载。这一条是后来所有工作的基础。", bold=True)

h("4.3.2  走过的弯路（按顺序）", 3)
table(["尝试", "做法", "结果与结论"], [
    ["① fpga_manager 热切换",
     "Linux 下直接写 /sys/class/fpga_manager/fpga0/firmware",
     "PL 能配上，但 ADI 驱动簿记失效：fs=117878、ensm 报 EIO、"
     "iio_readdev 超时；解绑重绑也救不回 cf_axi_adc"],
    ["② QSPI mtd3 换 FIT",
     "解析 FIT、替换 /images/fpga@1、重刷 mtd3",
     "板子根本不读 mtd3，DDS 判据证明 PL 仍是原厂位流"],
    ["③ uEnv.txt 的 uenvcmd",
     "在 SD 卡 uEnv.txt 加 uenvcmd=fatload...; fpga load...",
     "u-boot 打印 fpga 用法帮助——参数正确却报用法"],
    ["④ preboot 加载",
     "fw_setenv preboot '...; fpga loadb ...'",
     "同上，仍打印用法"],
    ["⑤ 官方博客写法",
     "mmcinfo; fatload ...; fpga loadb ... ${filesize}",
     "仍打用法。定位到 ${filesize} 展开陷阱：u-boot 的 run 在执行前"
     "就展开全部变量，fatload 尚未运行，${filesize} 恒为空"],
    ["⑥ 硬编码 size",
     "fpga loadb 0 0x100000 0xEC848 + mmcinfo",
     "仍打用法。控制台证实 fpga 命令存在但该操作未编译"],
    ["⑦ bootgen 重打包 BOOT.bin",
     "提取 fsbl.elf、厂商 BIF 模板、bootgen 重打包",
     "BOOT.bin 内无任何有效 ELF（bootgen 存的是裸二进制分区），"
     "u-boot.elf 提取不出，无法重打包"],
    ["⑧ 原地替换位流",
     "把我们的位流塞进厂商 BOOT.bin 的位流区间",
     "我们的 968,712 > 厂商的 946,378；尝试缩小位流时触发 96>80 DSP 失败"],
])
para("其中最重要的技术结论是第 ③~⑥ 条共同指向的一点：", bold=True)
mono([
    "控制台证据:",
    "  reading system_top_c.bin",
    "  968712 bytes read in 104 ms        <- fatload 成功",
    "  fpga - loadable FPGA image support",
    "  Usage: fpga [operation type] ...   <- 打印用法 = 该操作未编译",
    "",
    "u-boot 的 fpga 帮助文本是【静态字符串】，无条件列出所有操作；",
    "但命令分发是条件编译的：",
    "  #if defined(CONFIG_CMD_FPGA_LOADB)",
    "      else if (!strcmp(op, \"loadb\")) op = FPGA_LOADB;",
    "  #endif",
    "=> 帮助里列出 loadb != 它被编译进去了。这份 u-boot 没有可用的 PL 加载通道。",
])

h("4.3.3  突破口：JTAG", 3)
para("既然 u-boot 路径不通，改走 JTAG——它绕开 FSBL/u-boot/SD/QSPI/BOOT.bin 的全部启动逻辑。")
para("关键发现是 FT2232H 被厂商 EEPROM 烧成了 Digilent 电缆标识：")
mono([
    "$ ftd2xx.dll / FT_CreateDeviceInfoList -> numDevs = 2",
    "  [0] 'Digilent Adept USB Device A'  serial=000000000069A   <- JTAG 通道",
    "  [1] 'Digilent Adept USB Device B'  serial=000000000069B   <- 串口 COM12",
])
para("连接过程中还踩了两个坑，均靠工具原话定位：")
table(["坑", "现象", "解法"], [
    ["Vivado batch 无硬件管理器",
     "invalid command name open_hw_manager",
     "报错原文点名：You must execute 'open_hw'——batch 模式用 open_hw"],
    ["vivado_lab 未安装",
     "找不到 vivado_lab",
     "全功能 Vivado 的 batch + open_hw 即可"],
])
para("最终结果（已实测）：")
mono([
    "TARGET: localhost:3121/xilinx_tcf/Digilent/000000000069A",
    "DEVICE: arm_dap_0  /  xc7z010_1",
    "",
    "=== programming xc7z010_1 with system_top_c.bit (968712 bytes) ===",
    "INFO: [Labtools 27-3164] End of startup status: HIGH",
    "PROGRAMMED_OK",
])
para("End of startup status: HIGH 即 PL 的 DONE 拉高，位流配置成功。", bold=True)

h("4.3.4  当前唯一遗留问题：加载时机", 3)
para("JTAG 烧写本身成功，但烧完之后采集失效，症状与热切换完全一致：")
mono([
    "fs    = 117878                 (应为 2500000)",
    "ensm  = Input/output error (5)",
    "txrate= BBPLL:1931320290 ... TXSAMP:117878",
    "iio_readdev -> Unable to refill buffer: Connection timed out (110)",
    "IIO 设备仍为 4 个，但功能已失效",
])
para("根因不在位流内容，而在【PL 重配置的时机】："
     "在 Linux/ADI 驱动运行中重新配置 PL，会打乱驱动的时钟簿记。"
     "这与 fpga_manager 热切换失败是同一根因。", bold=True)
para("解法：让 PL 在 Linux 启动之前就绪。已设计出无需人工干预的方案——"
     "用 preboot 让 u-boot 主动等待，为 JTAG 烧写留出窗口：")
mono([
    "fw_setenv preboot 'sleep 30'",
    "① 重启 -> FSBL 加载原厂位流(2s) -> u-boot 执行 preboot 睡 30 秒",
    "② 在这个 30 秒窗口内用 Vivado JTAG 烧我们的位流（此时 Linux 未启动）",
    "③ u-boot 醒来继续启动 Linux -> 驱动在【我们的 PL】上从头正确初始化",
    "④ DDS 判据验证",
])

# ============================================================ 5
h("5  验证方法", 1)

h("5.1  仿真闭环（已完成）", 2)
table(["层级", "内容", "结果"], [
    ["编码链比对", "tb_coder_only vs 软件参考 build_cadu", "逐位一致（320/320 bit）"],
    ["端到端", "tb_ccsds_tx_chain -> 已验证的 Python 接收端解码", "CRC OK + 载荷逐字节一致"],
    ["物理层", "tb_tx_full（含 SRRC）", "样点非零、Q 恒零（BPSK）、基带"],
    ["综合实现", "LUT 63.60% / DSP 56 未增 / WNS +0.853 ns", "通过"],
])

h("5.2  DDS 判据：上板部署的免接线判据", 2)
para("这是本项目最有价值的验证方法。我们的设计在顶层把 tx_data_out 换成了 CCSDS 数据，"
     "因此 DDS（PL 内的测试信号源）无法到达引脚。于是：")
table(["PL 中的位流", "DDS 通断", "std 比值"], [
    ["原厂位流", "DDS 能到引脚，被 RX 收到", "约 30 – 68 倍"],
    ["我们的位流", "DDS 被顶层 MUX 掐断", "约 1.0 倍"],
])
para("重要教训：", bold=True)
para("第一次用 −40 dB 衰减测量时只看到 1.12 倍，几乎误判为\u201c部署成功\u201d——"
     "那其实是耦合太弱看不见，不是被阻断。"
     "把发射开到满功率（衰减 0 dB）后，比值立刻跳到 68 倍，真相才暴露。")
para("结论：任何\u201c没测到\u201d的结论，都必须先有一个\u201c测得到\u201d的阳性对照。"
     "这条原则在本项目中反复被验证。", bold=True)

# ============================================================ 6
h("6  板卡操作要点（避坑清单）", 1)
table(["事项", "要点"], [
    ["两个 Type-C 口", "USB2.0 = OTG，主供电 + 数据（RNDIS + COM11）；"
                       "DEBUG = JTAG + u-boot 控制台（COM12）。两者都要接"],
    ["三个 LED", "BLUE1 驱动 FPGA_DONE（PL 是否配置成功）；RED1 常亮为电源；"
                 "White1 由 Zynq MIO0 驱动（Linux 用户灯）"],
    ["SSH 主机密钥", "rootfs 只读+overlay，密钥每次重启都重新生成。"
                     "连不上时先清注册表 HKCU\\Software\\SimonTatham\\PuTTY\\SshHostKeys"],
    ["文件传输", "pscp 必须加 -scp（板子无 sftp-server）"],
    ["挂载 SD 卡", "根文件系统只读，/mnt/sd 重启即失。"
                   "必须先 mkdir -p /mnt/sd 再 mount -t vfat /dev/mmcblk0p1"],
    ["串口监听", "被动监听 COM12 即可看到全部 u-boot 输出；"
                 "发字符会把 Hit any key 倒计时按停"],
    ["可用采样率", "2.5 / 3.84 / 4 MSPS（地面解码脚本要求 2.5）"],
])

# ============================================================ 7
h("7  当前状态与后续计划", 1)

h("7.1  已完成", 2)
table(["项目", "状态"], [
    ["协议核移植（30 个 VHDL）", "完成，零厂商原语"],
    ["4 处协议不一致修复", "完成，仿真逐位一致"],
    ["Verilog 适配层", "完成（定标 / 极性 / 12 个 ODDR / 时钟）"],
    ["集成进 Vivado 工程", "完成（不改锁定 BD，顶层拦截 tx_data_out）"],
    ["Bitstream 生成", "完成，LUT 63.60%、DSP 未增、WNS +0.853"],
    ["仿真闭环验证", "完成（编码链逐位一致 + 端到端解码 + 物理层）"],
    ["JTAG 通道打通", "完成，已成功烧写位流（DONE=HIGH）"],
    ["DDS 判据标定", "完成（原厂 30–68× / 我们的 ~1.0×）"],
])

h("7.2  待完成（按优先级）", 2)
table(["#", "任务", "说明"], [
    ["1", "解决 PL 加载时机",
     "按 preboot=sleep 30 方案：重启后 30 秒窗口内 JTAG 烧写，再让 Linux 启动"],
    ["2", "上板射频验证",
     "DDS 判据确认后，用频谱仪 / 转发板做对端验证。约定：不再用 TX1↔RX1 直连线"],
    ["3", "射频工作参数",
     "RX_LO 900 MHz / TX_LO 1000 MHz（异频天然隔离，免双工器）/ 2.5 MSPS"],
    ["4", "透明转发（上行接收）",
     "当前只有发射链在 FPGA，接收链仍在 PC（auto_decode.py）。"
     "过渡方案：遥控板把 RX 的 IQ 经网口送出，由 PC 解析"],
    ["5", "星上解析（长期）",
     "把匹配滤波、定时恢复、Viterbi 译码、解扰、CRC 搬进 FPGA。"
     "LUT 是瓶颈（剩 6406），Viterbi 约需 3000–6000 LUT"],
    ["6", "板间通信（去掉 RK3588）",
     "数据量小，建议 UART 交叉直连；大数据量才需要以太网"
     "（转发板 GEM 在 BD 里被禁用，但 BD 可编辑）"],
    ["7", "遥测数据源接入",
     "替换当前的静态帧，接入真实遥测数据"],
])

h("7.3  资源余量（供后续规划参考）", 2)
table(["资源", "已用", "总量", "占用率", "剩余"], [
    ["Slice LUTs", "11194", "17600", "63.60%", "6406"],
    ["Slice Registers", "18479", "35200", "52.50%", "16721"],
    ["Block RAM", "2", "60", "3.33%", "58"],
    ["DSP48E1", "56", "80", "70.00%", "24"],
    ["Bonded IOB", "51", "100", "51.00%", "49"],
    ["BUFGCTRL", "6", "32", "18.75%", "26"],
])
para("时序：WNS +0.853 ns，WHS +0.018 ns。LUT 是最紧的资源；"
     "BRAM 极为充裕（97% 空闲）；DSP 还有 24 个余量。")

# ============================================================ 8
h("8  经验总结", 1)
para("1. 仿真一致是必要条件，不是充分条件。", bold=True)
para("仿真逐位一致只证明逻辑设计正确，证明不了三件事：位流真的进了 PL、"
     "引脚级电气行为、采样率与射频配置匹配。必须另设上板判据。")
para("2. 任何\u201c没测到\u201d的结论都必须先有阳性对照。", bold=True)
para("−40 dB 下的 1.12 倍与满功率下的 68 倍，差一点导致完全错误的结论。")
para("3. 工具的错误信息往往直接给出答案。", bold=True)
para("open_hw 这个正确命令就是 Vivado 报错原文里点名的；"
     "fpga loadb 的问题也是靠\u201c参数正确却打用法\u201d这一反常现象定位的。")
para("4. 先搞清\u201c板子从哪启动、位流从哪来\u201d，再动手。", bold=True)
para("项目前中期大量时间消耗在改 QSPI 上，而板子根本不读 QSPI。"
     "一次控制台捕获（COM12）的信息量超过前面所有盲试。")
para("5. 负面结论同样需要记录。", bold=True)
para("哪些路走不通、为什么走不通，与成功的路径一样有价值——"
     "本报告第 4.3.2 节的八条弯路，可让后续任何人少走数天弯路。")

doc.add_paragraph()
para("— 报告结束，待后续完善 —", italic=True).alignment = WD_ALIGN_PARAGRAPH.CENTER

out = r"E:\fpga_sdr_project\遥测遥控FPGA移植报告.docx"
doc.save(out)
print("written:", out)
