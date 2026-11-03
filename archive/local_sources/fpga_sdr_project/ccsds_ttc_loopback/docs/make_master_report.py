#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_master_report.py -- 遥测板技术报告（持续更新版）

设计成可追加：
  * 章节编号固定留出扩展位（第 9 章之后的编号留给后续内容）
  * 末尾有「变更记录」表，每次追加在此登记
  * 追加内容时不用重写全文，只在本脚本里对应位置加代码块即可

中文排版：每个 run 都设 w:lang eastAsia="zh-CN"，列宽自动缩放到 17 cm。
"""
import os
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

OUT = r"E:\fpga_sdr_project\ccsds_ttc_loopback\docs\遥测板技术报告.docx"
os.makedirs(os.path.dirname(OUT), exist_ok=True)

doc = Document()
sec = doc.sections[0]
sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
sec.left_margin = sec.right_margin = Cm(2.0)
sec.top_margin = sec.bottom_margin = Cm(1.9)
USABLE = 17.0


def _fix(run, size=10.5, bold=False, color=None, mono=False):
    run.font.size = Pt(size)
    run.font.bold = bold
    name = "Consolas" if mono else "Microsoft YaHei"
    run.font.name = name
    rpr = run._element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts"); rpr.append(rf)
    rf.set(qn("w:ascii"), name); rf.set(qn("w:hAnsi"), name)
    rf.set(qn("w:eastAsia"), "Microsoft YaHei")
    lang = rpr.find(qn("w:lang"))
    if lang is None:
        lang = OxmlElement("w:lang"); rpr.append(lang)
    lang.set(qn("w:val"), "en-US"); lang.set(qn("w:eastAsia"), "zh-CN")
    if color:
        run.font.color.rgb = RGBColor(*color)


def _pp(p):
    ppr = p._element.get_or_add_pPr()
    for g in ppr.findall(qn("w:docGrid")):
        ppr.remove(g)
    for tag in ("w:autoSpaceDE", "w:autoSpaceDN", "w:overflowPunct"):
        e = ppr.find(qn(tag))
        if e is None:
            e = OxmlElement(tag); ppr.append(e)
        e.set(qn("w:val"), "1")
    ww = ppr.find(qn("w:wordWrap"))
    if ww is None:
        ww = OxmlElement("w:wordWrap"); ppr.append(ww)
    ww.set(qn("w:val"), "0")


def H(text, level=1):
    p = doc.add_heading("", level=level); _pp(p)
    r = p.add_run(text)
    _fix(r, {0: 19, 1: 14.5, 2: 12.5, 3: 11}.get(level, 11), bold=True,
         color=(0x1F, 0x3A, 0x5F) if level <= 2 else (0x33,) * 3)
    return p


def P(text, size=10.5, bold=False, align=None, indent=0.0, color=None):
    p = doc.add_paragraph(); _pp(p)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.line_spacing = 1.25
    if indent:
        p.paragraph_format.left_indent = Cm(indent)
    if align:
        p.alignment = align
    _fix(p.add_run(text), size, bold, color)
    return p


def CODE(lines):
    for ln in lines:
        p = doc.add_paragraph(); _pp(p)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.line_spacing = 1.0
        p.paragraph_format.left_indent = Cm(0.45)
        _fix(p.add_run(ln if ln else " "), 7.8, False, (0x20, 0x20, 0x20), mono=True)


def B(text, size=10.5):
    p = doc.add_paragraph(style="List Bullet"); _pp(p)
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.line_spacing = 1.2
    _fix(p.add_run(text), size)


def TABLE(headers, rows, widths=None):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"; t.alignment = WD_TABLE_ALIGNMENT.CENTER; t.autofit = False
    n = len(headers)
    if widths:
        s = float(sum(widths))
        widths = [w * USABLE / s for w in widths] if s else [USABLE / n] * n
    else:
        widths = [USABLE / n] * n
    tblpr = t._tbl.tblPr
    for e in tblpr.findall(qn("w:tblW")):
        tblpr.remove(e)
    tw = OxmlElement("w:tblW")
    tw.set(qn("w:w"), str(int(USABLE * 567))); tw.set(qn("w:type"), "dxa")
    tblpr.append(tw)
    grid = t._tbl.find(qn("w:tblGrid"))
    if grid is not None:
        t._tbl.remove(grid)
    grid = OxmlElement("w:tblGrid")
    for w in widths:
        gc = OxmlElement("w:gridCol"); gc.set(qn("w:w"), str(int(w * 567))); grid.append(gc)
    t._tbl.insert(list(t._tbl).index(tblpr) + 1, grid)
    for i, h in enumerate(headers):
        c = t.rows[0].cells[i]; c.text = ""
        p = c.paragraphs[0]; _pp(p)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _fix(p.add_run(h), 9.5, bold=True)
    for row in rows:
        cs = t.add_row().cells
        for i, v in enumerate(row):
            cs[i].text = ""
            p = cs[i].paragraphs[0]; _pp(p)
            p.paragraph_format.space_after = Pt(1)
            _fix(p.add_run(str(v)), 9.5)
    for r in t.rows:
        for i, w in enumerate(widths):
            r.cells[i].width = Cm(w)
    doc.add_paragraph()
    return t


# =====================================================================
H("遥测板技术报告", 0)
P("Zynq-7010 + AD9363 遥测发射链路 —— 架构、工作流程与 FPGA 移植方案",
  size=11.5, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
P("持续更新文档 · 2026 年 10 月", size=9.5,
  align=WD_ALIGN_PARAGRAPH.CENTER, color=(0x70, 0x70, 0x70))

# ---------------------------------------------------------------- 1
H("1  概述", 1)
P("本报告描述遥测板（Zynq-7010 + AD9363）的完整工作流程，包括硬件架构、"
  "固件栈、FPGA 工程结构、当前软件实现路径，以及把 CCSDS 编码搬入 PL 的移植方案。")
P("当前状态：软件版 CCSDS 发射链已实现并通过双板环回射频端到端验证"
  "（8 个传输帧 CRC 全部正确）。FPGA 移植尚未开始，地基已备好。")

TABLE(["项目", "内容"],
      [["板卡", "7010_AD9363SDR（Zynq-7010 + AD9363）"],
       ["固件", "stock PlutoSDR v0.38（Buildroot Linux）"],
       ["FPGA 工程", "ADI HDL 参考设计，定制为 xc7z010clg400-1，Vivado 2018.3"],
       ["基线构建", "✅ 通过：LUT 44.41% / FF 40.18% / BRAM 3.33% / DSP 70.00%，WNS +0.549 ns"],
       ["当前发射路径", "电脑 Python 生成 IQ → scp → 板子 iio_writedev → DMA → DAC → RF"],
       ["验证状态", "✅ 双板环回通过（经转发板中继，8 帧 CRC 全对）"]],
      widths=[3.4, 13.6])

# ---------------------------------------------------------------- 2
H("2  硬件架构", 1)

H("2.1  板卡组成", 2)
TABLE(["部件", "型号 / 规格", "作用"],
      [["主芯片", "Zynq-7010 (xc7z010clg400-1)", "PS: 双核 Cortex-A9 667 MHz；PL: 28K 逻辑单元"],
       ["射频", "AD9363", "1R1T（软件可配），70 MHz ~ 6 GHz"],
       ["内存", "DDR3 512 MB", "PS 运行 Linux，DMA 缓冲"],
       ["存储", "QSPI Flash + microSD", "固件与文件系统"],
       ["USB", "VID 0456 / PID B673", "复合设备：RNDIS 网卡 + 串口 + IIO + 存储"],
       ["以太网", "RTL8211 千兆", "第二控制通道"],
       ["时钟", "40 MHz 晶振", "AD9361 参考时钟"]],
      widths=[2.6, 5.4, 9.0])

H("2.2  射频接口", 2)
P("AD9363 采用 LVDS 接口与 PL 相连：")
TABLE(["信号", "方向", "说明"],
      [["rx_clk_in", "输入", "RX 数据时钟（DATA_CLK）"],
       ["rx_frame_in", "输入", "RX 帧同步"],
       ["rx_data_in[11:0]", "输入", "RX 数据总线，12 bit，DDR"],
       ["tx_clk_out", "输出", "TX 数据时钟"],
       ["tx_frame_out", "输出", "TX 帧同步"],
       ["tx_data_out[11:0]", "输出", "TX 数据总线，12 bit，DDR"],
       ["spi_*", "双向", "AD9361 寄存器配置（PS 通过 SPI 控制）"],
       ["enable / txnrx", "输出", "AD9361 使能与收发切换"]],
      widths=[4.2, 2.0, 10.8])
P("⭐ 1R1T 模式下，一个 12 bit 的 I/Q 样点占 2 个 DATA_CLK 周期（各 6 bit）。")

# ---------------------------------------------------------------- 3
H("3  固件与软件栈", 1)

H("3.1  分层结构", 2)
CODE([
    "+---------------------------------------------------------------+",
    "|  PC 侧（Windows）                                              |",
    "|    Python: CCSDS 编码 -> IQ 样点 -> scp 上传                   |",
    "|    SSH / scp  ->  192.168.2.1（RNDIS 网卡）                    |",
    "+----------------------------+----------------------------------+",
    "                             |",
    "+----------------------------v----------------------------------+",
    "|  PS 侧（ARM Cortex-A9, Linux）                                 |",
    "|    iiod 守护进程（libiio 服务端, 端口 30431）                   |",
    "|    iio_writedev / iio_readdev / iio_attr（命令行工具）          |",
    "|    AD9361 驱动（SPI 配置射频芯片）                              |",
    "|    DMA 驱动（AXI DMA 搬运 I/Q 数据）                            |",
    "+----------------------------+----------------------------------+",
    "                             |  AXI",
    "+----------------------------v----------------------------------+",
    "|  PL 侧（FPGA 逻辑）                                            |",
    "|    axi_ad9361        : AD9361 接口 + 数据打包/解包              |",
    "|    adc_dma / dac_dma : AXI DMA 控制器                          |",
    "|    fir_decimator     : 抽取滤波（RX）                          |",
    "|    fir_interpolator  : 内插滤波（TX）                          |",
    "|    ad_dds           : 内部 DDS（当前关闭 scale=0）              |",
    "|    PS7 硬核          : Zynq 处理系统                           |",
    "+---------------------------------------------------------------+",
])

H("3.2  各部分职责", 2)
TABLE(["部分", "职责", "本工程中的状态"],
      [["iiod", "libiio 服务端，把 IIO 设备暴露成网络/本地接口",
        "随固件启动，端口 30431"],
       ["iio_attr", "读写 IIO 设备属性（频率、增益、采样率、DDS）", "用于全部配置"],
       ["iio_writedev", "把 stdin 的 I/Q 数据流写入 DAC 通道", "★ 当前发射入口"],
       ["iio_readdev", "从 ADC 通道读出 I/Q 数据流", "★ 当前接收入口"],
       ["AD9361 驱动", "SPI 配置射频芯片的 PLL、增益、带宽、采样率", "由 iio_attr 间接调用"],
       ["AXI DMA", "PS 内存 ↔ PL 的高速数据搬运", "iio_*dev 通过它收发"],
       ["axi_ad9361 (PL)", "LVDS 时序、数据打包/解包、DDS 混合", "原厂逻辑，未改"],
       ["FIR 滤波器 (PL)", "RX 抽取 / TX 内插", "原厂逻辑，迁移时需评估是否保留"]],
      widths=[3.0, 8.0, 6.0])

H("3.3  板子上的工具限制（实测）", 2)
CODE([
    "✅ 有: iio_writedev  iio_readdev  iio_attr  iio_info  iio_reg",
    "        iio_genxml  iio_stresstest  kill  killall  pidof  ps",
    "❌ 没有: pkill   timeout   python   perl",
    "",
    "⚠️ 因此：定时不能用 timeout，要用「把 -s 设成正好 N 秒的样点数」",
    "   （iio_writedev/readdev 抓够就自己退出）",
])

# ---------------------------------------------------------------- 4
H("4  FPGA 工程结构", 1)

H("4.1  工程位置与来源", 2)
TABLE(["项", "内容"],
      [["原始位置", r"E:\7010_AD9363_开源资料\firmware\source project\pluto-7010clg400-user-ip"],
       ["工作副本", r"E:\7010_ttc_ccsds\pluto\pluto.xpr"],
       ["Vivado 版本", "2018.3（与原工程一致，无兼容问题）"],
       ["器件", "xc7z010clg400-1"],
       ["顶层", "system_top（Verilog）"],
       ["Block Design", "pluto.srcs/sources_1/bd/system/system.bd"],
       ["依赖", "ADI IP 已随工程打包，不需要额外下载 adi-hdl 仓库"]],
      widths=[3.0, 14.0])

H("4.2  修复的外来依赖", 2)
P("原工程引用了作者机器上的外部路径，归档时缺失。已修复：")
TABLE(["缺失项", "原引用路径", "修复方式"],
      [["ad_iobuf.v", "$PPRDIR/../../library/xilinx/common/ad_iobuf.v",
        "从 ADI 官方 hdl_2019_r1 分支下载，放到 E:\\library\\xilinx\\common\\"],
       ["component.xml", "$PPRDIR/../../component.xml",
        "警告级，不影响综合，暂未处理"]],
      widths=[3.0, 6.5, 7.5])

H("4.3  基线资源占用", 2)
TABLE(["资源", "使用", "总量", "占比", "剩余"],
      [["Slice LUTs", "7817", "17600", "44.41%", "9783"],
       ["Slice Registers", "14142", "35200", "40.18%", "21058"],
       ["Block RAM Tile", "2", "60", "3.33%", "58"],
       ["DSPs", "56", "80", "70.00%", "24"]],
      widths=[3.4, 2.6, 2.6, 2.6, 2.6, ] if False else [3.4, 2.6, 2.6, 2.6, 5.8])
P("⚠️ DSP 已用 70%，只剩 24 个。这是移植 CCSDS 时最需要关注的资源。", bold=True)
P("⭐ 注意：基线的两个 FIR 滤波器（抽取/内插）占用不少 DSP。"
  "遥测发射用不上抽取滤波器，如果需要腾资源可以考虑去掉。", indent=0.4)

H("4.4  顶层模块与注入点", 2)
P("system_top.v 中 AD9361 通过 system_wrapper 例化，DAC 数据从 wrapper 输出到引脚：")
CODE([
    "system_wrapper i_system_wrapper (",
    "    ...",
    "    .tx_clk_out  (tx_clk_out),      // 输出到 AD9361",
    "    .tx_data_out (tx_data_out),     // ★ 在这里注入 CCSDS 样点",
    "    .tx_frame_out(tx_frame_out),",
    "    ...",
    ");",
])
P("⭐ 注入策略（与转发板做法一致，避开改 BD）：", bold=True)
CODE([
    "CCSDS 链 (100 MHz 域, clock-enable 推样点)",
    "    |  8 bit I/Q",
    "    v",
    "8 -> 12 bit 定标",
    "    |",
    "    v",
    "异步 FIFO (100 MHz  ->  tx_clk 域)",
    "    |",
    "    v",
    "MUX --- ccsds_en ? fifo_out : wrapper_out ---> tx_data_out ---> AD9361",
])
P("这样完全不改 Block Design，避开「BD 模块引用端口列表被冻结」那类问题。", indent=0.4)

# ---------------------------------------------------------------- 5
H("5  当前工作流程（软件版）", 1)

H("5.1  发射流程", 2)
CODE([
    "① 电脑生成波形",
    "     build_tm_frame()   : 132.0-B 传输帧 (6B 主头 + 数据 + 2B CRC-16 FECF)",
    "     build_cadu()       : 随机化 -> 卷积编码 -> 插入 ASM",
    "     cadu_to_iq()       : BPSK 映射 -> SRRC 成形 -> 上变频到 +200 kHz",
    "     iq_interleave()    : I/Q 交错成 int16 流",
    "     存为 cadu_wave.bin",
    "",
    "② scp 上传到板子 /tmp/wave.bin",
    "",
    "③ 配置板子（iio_attr）",
    "     altvoltage1 frequency          = TX_LO",
    "     voltage0 sampling_frequency    = 2.5 MSPS",
    "     voltage1 hardwaregain (-o)     = TX 衰减（负值）",
    "     cf-ad9361-dds-core-lpc scale   = 0（关掉内部 DDS，避免和数据打架）",
    "",
    "④ 发射",
    "     for i in $(seq 1 N); do cat /tmp/wave.bin; done | \\",
    "       iio_writedev -u ip:localhost -s <样点数> -b 65536 \\",
    "       cf-ad9361-dds-core-lpc voltage0 voltage1",
    "     （★ 不用 while true —— 管道不关会把 SSH 挂死）",
])

H("5.2  接收流程", 2)
CODE([
    "① iio_readdev 抓 I/Q 到 /tmp/cap.bin，scp 回电脑",
    "",
    "② 接收处理（auto_decode.py）",
    "     - 去直流",
    "     - 自动频偏搜索：±600 kHz 按 10 kHz 步进",
    "         每个频偏都完整跑一遍下面 3~7 步",
    "     - 下变频 exp(-j2*pi*f_off*t)",
    "     - SRRC 匹配滤波",
    "     - 符号定时恢复：在 [0,10) 个采样相位扫，取 sum|Re| 最大者",
    "     - 判决 Re<0 -> bit 1",
    "     - ASM 滑窗搜索 0x1ACFFC1D（<=2 bit 错即命中）",
    "     - Viterbi 译码（硬判决，7 位状态）",
    "     - 解随机化",
    "     - 解帧 + CRC-16 校验",
])

H("5.3  为什么必须做频偏搜索", 2)
P("最初接收端硬编码「信号在 +200 kHz」。实测频谱峰值出现在 −153 kHz 附近，"
  "按 +200 kHz 下变频后得不到干净的 BPSK，译码必然失败。")
P("加入搜索后，正确频偏处输出 +200 kHz —— 与发射端一致，"
  "同时印证了整条射频链路的频率是准确的。", bold=True)

# ---------------------------------------------------------------- 6
H("6  FPGA 移植方案", 1)

H("6.1  现成例子：有，而且已经在你手上", 2)
P("不需要从零写。三个开源件已经下载完毕：", bold=True)
TABLE(["件", "位置", "许可", "作用", "成熟度"],
      [["Pluto ADI HDL 工程", r"E:\7010_ttc_ccsds\pluto", "ADI BSD / GPL-2",
        "地基：已适配本板卡，可完整构建出比特流", "✅ 已验证构建通过"],
       ["euryspace", r"E:\7010_ttc_ccsds\euryspace-master", "MIT",
        "CCSDS 发射链：随机化 / 卷积 / ASM / 映射 / SRRC", "✅ 31 个 VHDL 文件齐全"],
       ["dshekhalev/FEC", r"E:\7010_ttc_ccsds\FEC-main", "MIT",
        "RS(255,223) + Viterbi 译码", "备用（阶段 A 暂不需要 RS）"]],
      widths=[3.2, 4.6, 2.2, 5.2, 3.0])

H("6.2  euryspace 的接口", 2)
CODE([
    "entity ccsds_tx is",
    "  generic (",
    "    CCSDS_TX_BITS_PER_SYMBOL      : 1",
    "    CCSDS_TX_BUFFER_SIZE          : 16",
    "    CCSDS_TX_MODULATION_TYPE      : 1        -- 1=QPSK  2=BPSK",
    "    CCSDS_TX_DATA_BUS_SIZE        : N        -- 并行数据位宽",
    "    CCSDS_TX_OVERSAMPLING_RATIO   : 4        -- 符号->样点过采样",
    "    CCSDS_TX_PHYS_SIG_QUANT_DEPTH : 8        -- ★ 输出样点 8 位",
    "  );",
    "  port (",
    "    clk_i      : 样点时钟",
    "    dat_par_i  : 并行数据输入    <- 喂 CCSDS 帧",
    "    dat_ser_i  : 串行数据输入",
    "    dat_val_i  : 数据有效",
    "    ena_i, in_sel_i, rst_i",
    "    sam_i_o    : 8 位 I 样点     -> 需要定标到 12 位",
    "    sam_q_o    : 8 位 Q 样点",
    "    clk_o, ena_o, idl_o, buf_ful_o",
    "  );",
])
P("内部链路：串行比特 → 随机化 → 卷积编码 → ASM → 比特到符号 → 符号到样点 → SRRC → I/Q",
  indent=0.4)

H("6.3  需要改的三个参数", 2)
TABLE(["参数", "euryspace 默认", "本项目需要", "说明"],
      [["OVERSAMPLING_RATIO", "4", "10",
        "2.5 MSPS ÷ 250 ksym/s = 10"],
       ["PHYS_SIG_QUANT_DEPTH", "8", "保持 8，输出时定标到 12",
        "AD9361 的 LVDS 接口是 12 bit"],
       ["MODULATION_TYPE", "1 (QPSK)", "1 或 2 (BPSK)", "本轮验证用 BPSK"]],
      widths=[4.2, 3.2, 4.6, 5.0])

H("6.4  移植步骤", 2)
TABLE(["步骤", "内容", "风险 / 注意"],
      [["1", "把 euryspace 的 VHDL 加入工程 sources_1",
        "Vivado 支持混合语言，但要注意 VHDL 库声明"],
       ["2", "写 Verilog 包装 ccsds_tx_wrap.v",
        "实例化 VHDL 实体；处理 8→12 bit 定标；提供简化的寄存器接口替代 Wishbone"],
       ["3", "提供帧数据源",
        "先用 BRAM 存固定测试 CADU 做 bring-up，之后再改成 PS 经 AXI-Lite 写入"],
       ["4", "时钟域跨越",
        "CCSDS 链跑 100 MHz，DAC 在 tx_clk 域，需要异步 FIFO"],
       ["5", "顶层 MUX 注入 DAC",
        "拦截 system_wrapper 的 tx_data_out，ccsds_en 时切到 FIFO 输出"],
       ["6", "约束与构建",
        "新增 100 MHz 时钟约束、CDC 约束；⚠️ 注意 DSP 只剩 24 个"],
       ["7", "上板验证",
        "先用 CMU200 看频谱形状是否与软件版一致，再做自环解码比对"]],
      widths=[1.4, 6.6, 9.0])

H("6.5  资源预算评估", 2)
TABLE(["资源", "基线已用", "CCSDS 链估算", "合计", "余量"],
      [["LUT", "7817 (44%)", "~3000", "10817 (61%)", "✅ 够"],
       ["FF", "14142 (40%)", "~2200", "16342 (46%)", "✅ 够"],
       ["BRAM", "2 (3%)", "~4", "6 (10%)", "✅ 很宽"],
       ["DSP", "56 (70%)", "取决于 SRRC 实现", "可能超", "⚠️ 需重点评估"]],
      widths=[2.4, 3.2, 4.4, 3.5, 3.5])
P("⭐ 最需要先确认的是 euryspace 的 SRRC（ccsds_rxtx_srrc.vhd）是用 DSP48 还是 LUT 实现的。"
  "如果吃 DSP，24 个可能不够，方案是降低抽头数、改用 LUT 实现、"
  "或去掉基线里遥测发射用不到的抽取 FIR。", bold=True)

H("6.6  其他可参考的开源项目", 2)
TABLE(["项目", "许可", "内容", "建议"],
      [["rtbnb/CCSDS-TM", "GPL-2.0", "131+132 全套含地面段", "仅作参考（GPL 传染）"],
       ["SatNOGS-COMMS-FPGA", "GPL-3.0", "完整通信子系统", "仅作参考"],
       ["analogdevicesinc/hdl", "ADI BSD", "ADI 参考设计（本工程地基）", "已在使用"],
       ["euryspace", "MIT", "CCSDS 131 发射链 + SRRC", "★ 主干"],
       ["dshekhalev/FEC", "MIT", "RS / Viterbi", "按需取用"]],
      widths=[4.4, 2.4, 6.2, 4.0])

# ---------------------------------------------------------------- 7
H("7  实测数据", 1)

H("7.1  双板环回端到端验证", 2)
P("链路：遥测板 TX1 → 转发板 RX1 → 转发板基带转发 → 转发板 TX1 → 遥测板 RX1")
TABLE(["检验项", "结果", "说明"],
      [["链路增益", "+32.7 dB", "发射开 vs 发射关的接收功率差"],
       ["接收 SNR", "45.0 dB", "频谱峰值与底噪之差"],
       ["定时恢复", "相位 5/10", "眼图开度 955,909"],
       ["同步字搜索", "0 bit 错", "0x1ACFFC1D 精确命中"],
       ["译码结果", "8 帧", "连续 8 个传输帧"],
       ["CRC-16", "全部通过", "每一个比特都正确"],
       ["载荷比对", "逐字节一致", "SCID=0x2A，MCFC 连续递增"],
       ["频偏", "+200 kHz", "与发射端设置一致"]],
      widths=[3.4, 3.2, 10.4])

H("7.2  接收链软件自检", 2)
P("用发射端波形加高斯白噪声喂接收链：")
TABLE(["SNR (dB)", "40", "30", "25", "20", "15", "12", "10"],
      [["解出帧", "1", "1", "1", "1", "1", "1", "1"],
       ["内容一致", "✅", "✅", "✅", "✅", "✅", "✅", "✅"]],
      widths=[3.0] + [2.0] * 7)
P("SNR 降至 10 dB 仍完美解码，说明接收链实现正确。")

H("7.3  关键参数汇总", 2)
TABLE(["参数", "取值"],
      [["采样率", "2.5 MSPS（PlutoSDR 固件只接受 2.5 / 3.84 / 4 MSPS）"],
       ["符号率", "250 ksym/s，过采样比 10"],
       ["调制", "BPSK（bit 0 → +1，bit 1 → −1）"],
       ["成形滤波", "SRRC β=0.35，跨度 8 符号"],
       ["中频", "+200 kHz（避开零中频的直流与本振泄漏）"],
       ["信道编码", "卷积 (7,1/2)，G1=0x79，G2=0x5B，第二路取反"],
       ["随机化", "LFSR h(x)=x⁸+x⁷+x⁵+x³+1（0xA9），初值 0xFF"],
       ["同步字", "0x1ACFFC1D"],
       ["帧结构", "6 字节主头 + 数据域 + 2 字节 CRC-16/CCITT FECF"]],
      widths=[3.4, 13.6])

# ---------------------------------------------------------------- 8
H("8  问题定位与根因", 1)
P("全部为实测确认的根因，非推测。")
TABLE(["#", "现象", "根因", "修复"],
      [["1", "命令返回 rc=127", "板子固件是 Buildroot，没有 pkill / timeout / python",
        "改用 killall + pidof；限时改为把 -s 设成正好 N 秒的样点数"],
       ["2", "SSH 会话卡住 160 秒",
        "stdin 用 while true; do cat 供给，iio_writedev 退出后 cat 仍往断掉的管道写",
        "改成有界 for 循环"],
       ["3", "Viterbi 译码结果错乱",
        "状态用了 6 位，编码器寄存器是 7 位，输入比特在最低位被丢掉",
        "改用 7 位状态（128 个），回溯取新状态最低 bit"],
       ["4", "找不到同步字",
        "硬编码 b\"C\\xff\\xc1\\x1d\" = 43 FF C1 1D，ASM 应为 0x1ACFFC1D",
        "统一从 ASM 常量派生字节串"],
       ["5", "转发板 RX 饱和 6.9 亿次",
        "rxgain ≥ 15 时 RX 饱和（15 → 45 万次/4 秒，20 → 1920 万次/4 秒）",
        "rxgain 限制 ≤ 10"],
       ["6", "CMU200 在 900 MHz 收不到",
        "转发板 TX_LO 设成了 1000；搬频关系是 输出 = 输入 + (TX_LO − RX_LO)",
        "改为 lo 1000 900"],
       ["7", "解不出帧",
        "接收端硬编码中频 +200 kHz，实际有偏移",
        "加自动频偏搜索"],
       ["8", "BD 模块引用端口列表不刷新（转发板）",
        "BD 把端口列表冻结在 bd/mref/<模块>/component.xml",
        "改 Verilog 后必须同时改该 XML 并删除缓存 IP 目录"]],
      widths=[0.9, 3.4, 6.2, 6.5])

# ---------------------------------------------------------------- 9
H("9  结论与下一步", 1)
H("9.1  已完成", 2)
B("遥测板 FPGA 工程在新环境下可完整重建，基线出比特流（WNS +0.549 ns）")
B("CCSDS 遥测发射链实现并通过软件自检（含反向 Viterbi 译码器）")
B("接收链实现并在 SNR 10 dB 下自检通过")
B("双板环回射频端到端验证通过：8 帧 CRC 全对，载荷逐字节一致")
B("CCSDS FPGA 开源参考调研完成，选定 MIT 许可的 euryspace 作为主干")

H("9.2  下一步（按优先级）", 2)
TABLE(["优先级", "任务", "说明"],
      [["高", "评估 euryspace 的 SRRC 资源占用",
        "基线 DSP 只剩 24 个，先确认 SRRC 用 DSP 还是 LUT"],
       ["高", "把 euryspace 加进 Pluto 工程并包装",
        "VHDL 加入 sources_1；写 Verilog 包装处理 8→12 定标"],
       ["高", "顶层 MUX 注入 DAC 并构建",
        "拦截 system_wrapper 的 tx_data_out；注意新增时钟与 CDC 约束"],
       ["中", "接收端连续解码",
        "当前依赖发射与抓取的时序重合，只能断续解；需更好的定时/载波同步"],
       ["中", "转发板样点率标定",
        "实测计数率约为请求值的 1/6，比例恒定说明控制线性有效，绝对标定待查"],
       ["低", "RS(255,223) 编码",
        "euryspace 未实现，可从 dshekhalev/FEC（MIT）移植"]],
      widths=[1.6, 4.6, 10.8])

# ---------------------------------------------------------------- 附录
H("附录 A  常用命令速查", 1)
CODE([
    "#  协议链软件自检（不需要硬件）",
    "python ccsds_tm_tx.py selftest",
    "",
    "#  接收链自检（加噪，验证 SNR 鲁棒性）",
    "python test_rx_chain.py",
    "",
    "#  双板安全配置（改完线后必须重跑）",
    "python arm_loopback.py",
    "",
    "#  链路通断诊断（约 20 秒）",
    "python diag_link.py",
    "",
    "#  自动频偏搜索解码",
    "python auto_decode.py",
    "",
    "#  自动扫增益找可解码点",
    "python sweep_gain.py",
    "",
    "#  生成波形 / 发射",
    "python stage_a_tx.py build",
    "python board_tx.py cont 40          # 连续发 40 秒",
    "",
    "#  转发板（串口 COM5, 115200）",
    "status / stat2 / mode 1 / gain 2048 / ddc 0 / duc 0",
    "txatt 60 / rxgain 5 / lo 1000 1000 / rate 30.72",
])

H("附录 B  安全要点", 1)
TABLE(["项", "数值", "说明"],
      [["AD9361/9363 TX 满量程", "≈ +7 dBm", "0 dB 衰减时"],
       ["RX 绝对最大输入", "+2.5 dBm", "超过会损伤"],
       ["遥测板上电瞬态", "≈ −3 dBm", "默认 TX 衰减 −10 dB，安全"],
       ["转发板上电瞬态", "≈ +4.5 dBm", "⚠️ 超过接收端耐压 2 dB"],
       ["安全做法", "接线状态下不重启转发板",
        "要重启先拔线；串 30 dB SMA 衰减器可彻底消除风险"]],
      widths=[3.6, 3.4, 10.0])

H("附录 C  变更记录", 1)
P("后续内容追加请在此登记。", size=9.5, color=(0x70, 0x70, 0x70))
TABLE(["版本", "日期", "变更内容", "状态"],
      [["v1.0", "2026-10", "首版：遥测板架构、工作流程、FPGA 移植方案、实测数据、问题根因",
        "已完成"],
       ["v1.1", "待填", "（后续追加，例如：SRRC 资源评估结果、euryspace 集成进展、"
        "上板验证数据）", "待办"]],
      widths=[1.8, 2.4, 9.8, 3.0])

doc.add_paragraph()
P("—— 报告结束（本文档持续更新）——", size=9,
  align=WD_ALIGN_PARAGRAPH.CENTER, color=(0x80, 0x80, 0x80))

doc.save(OUT)
print("已生成: %s" % OUT)
print("大小: %d 字节" % os.path.getsize(OUT))
