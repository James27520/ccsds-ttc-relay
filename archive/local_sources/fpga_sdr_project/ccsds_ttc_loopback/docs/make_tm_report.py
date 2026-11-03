#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_tm_report.py -- 生成《CCSDS 遥测链路 总结报告》DOCX"""
import os
import sys

from docx import Document
from docx.shared import Pt, RGBColor, Cm
from docx.oxml.ns import qn

sys.path.insert(0, r"E:\ccsds_fpga\tools")
import tm_params as TP  # noqa: E402

OUT = r"E:\fpga_sdr_project\CCSDS遥测链路_总结报告.docx"
CN = "SimSun"
MONO = "Courier New"


def cn(run, name=CN):
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)


def h(doc, t, lv=1):
    p = doc.add_heading("", level=lv)
    cn(p.add_run(t))
    return p


def para(doc, t="", bold=False, size=10.5, color=None):
    p = doc.add_paragraph()
    r = p.add_run(t)
    r.bold = bold
    r.font.size = Pt(size)
    if color:
        r.font.color.rgb = color
    cn(r)
    return p


def mono(doc, t, wrap=94):
    for raw in t.split("\n"):
        line = raw
        while len(line) > wrap:
            cut = line.rfind(" ", 0, wrap)
            if cut < wrap // 2:
                cut = wrap
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.5)
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(0)
            r = p.add_run(line[:cut])
            r.font.name = MONO
            r.font.size = Pt(8.5)
            r._element.rPr.rFonts.set(qn("w:eastAsia"), MONO)
            line = line[cut:].lstrip()
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(0.5)
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(line)
        r.font.name = MONO
        r.font.size = Pt(8.5)
        r._element.rPr.rFonts.set(qn("w:eastAsia"), MONO)


def table(doc, hdr, rows, widths=None):
    t = doc.add_table(rows=1, cols=len(hdr))
    t.style = "Light Grid Accent 1"
    for i, x in enumerate(hdr):
        c = t.rows[0].cells[i]
        c.text = ""
        r = c.paragraphs[0].add_run(x)
        r.bold = True
        r.font.size = Pt(9)
        cn(r)
    for row in rows:
        cs = t.add_row().cells
        for i, v in enumerate(row):
            cs[i].text = ""
            r = cs[i].paragraphs[0].add_run(str(v))
            r.font.size = Pt(9)
            cn(r)
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Cm(w)
    return t


doc = Document()
for s in doc.sections:
    s.left_margin = Cm(1.9)
    s.right_margin = Cm(1.9)

p = doc.add_heading("", level=0)
cn(p.add_run("CCSDS 遥测链路 总结报告"))
para(doc, "对象：遥测板 7010_AD9363（xc7z010clg400-1 + AD9363）",
     color=RGBColor(0x44, 0x44, 0x44))
para(doc, "标准依据：CCSDS 131.0-B（遥测同步与信道编码）",
     color=RGBColor(0x44, 0x44, 0x44))
para(doc)

# ============================== 一 ==============================
h(doc, "一、结论", 1)
para(doc, "遥测链路已经在遥测板上完整跑通，并通过三级验证：", bold=True)
table(doc, ["验证层级", "内容", "结果"],
      [["① 仿真", "整链环回（组帧→编码→调制→解调→译码→解帧）",
        "10 个抽取相位全部 PASS，40 字节逐字节一致"],
       ["② 板上 ILA", "遥测板 FPGA 自主完成编解码（数字环回）",
        "frame_match = 1、rx_crc_ok = 1、rx_err_cnt ≈ 0"],
       ["③ 过板子（模式 B）", "PC 组包 → 板子发射 → 环回 → 板子接收 → PC 解出参数表",
        "16 个参数全部一致，ASM 错 0 bit"]],
      widths=[2.6, 6.4, 7.0])
para(doc)
para(doc, "整个过程共解决 5 个关键技术问题，其中【SRRC 滤波器的综合陷阱】是最难定位的一个 —— "
          "它在仿真中完全正常，只在综合后才失效。详见第四章。", bold=True)

# ============================== 二 ==============================
doc.add_page_break()
h(doc, "二、系统架构与链路", 1)
mono(doc,
     "（信号源）--CCSDS 帧--> 遥控/遥测板 --解析出转发控制参数--> 以太网 --> 转发板\n"
     "                                              --> 转发板按参数工作\n"
     "                                                  （目标频段/带宽/增益…）\n"
     "\n"
     "遥测板自身：AD9361 收发一体，负责射频收发；FPGA 负责 CCSDS 编解码。")

h(doc, "2.1 遥测板硬件要点", 2)
table(doc, ["项目", "值/说明"],
      [["器件", "xc7z010clg400-1（Zynq-7010）+ AD9363"],
       ["AD9361 接口模式", "★ LVDS（不是 CMOS）—— 这是最初打不开器件的根因"],
       ["SPI 引脚", "enable=T15, spi_csn=R17, spi_clk=V18, spi_mosi=P16, spi_miso=V17"],
       ["BD 关键参数", "CMOS_OR_LVDS_N=0, MODE_1R1T=0(2R2T), ADC_INIT_DELAY=30"],
       ["DATA_CLK", "122.88 MHz"],
       ["采样率", "30.72 MSPS（软件版链路用 2.5 MSPS 以便与地面软件对齐）"],
       ["本振", "TX/RX 均为 2400 MHz（原厂固件实测）"]],
      widths=[4.0, 12.0])

h(doc, "2.2 帧格式（固定 40 字节）", 2)
mono(doc,
     "偏移  长度  内容\n"
     "----  ----  --------------------------------------------------\n"
     " 0     2    主头：SCID(10b) + VCID(3b) + 保留 + 帧类型 + 版本\n"
     " 2     2    主头：帧计数(8b) + 状态字\n"
     " 4     2    主头：数据域长度等\n"
     " 6    32    数据域 = 16 个 16 位参数（小端）\n"
     "38     2    FECF：CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF, MSB first)\n"
     "----  ----  --------------------------------------------------\n"
     "合计 40 字节 / 320 bit")

h(doc, "2.3 信道编码链", 2)
table(doc, ["环节", "参数", "说明"],
      [["随机化", "LFSR x^8+x^7+x^5+x^3+1，种子 0xFF",
        "与 CCSDS 131.0-B 一致；同步字不参与随机化"],
       ["卷积编码", "1/2 码率，K=7，G1=1111001，G2=1011011，第二路取反",
        "每比特出两个符号"],
       ["同步字 ASM", "0x1ACFFC1D（4 字节）", "前置，构成 CADU"],
       ["CADU", "32 + 640 = 672 bit（84 字节）", "ASM 32 bit + 编码后 640 bit"],
       ["调制", "BPSK", "负 -> 1，正 -> 0（极性已由理想激励定标）"],
       ["成形", "SRRC，61 抽头，beta=0.35，过采样 10", "收发各一个，SRRC x SRRC = 升余弦，符号点无 ISI"]],
      widths=[2.2, 6.3, 6.5])

# ============================== 三 ==============================
doc.add_page_break()
h(doc, "三、参数集设计", 1)
para(doc, "CCSDS 帧的数据域不是自由文本，而是一张【事先定义好的参数表】："
          "每个参数的字节偏移、类型、量纲、比例因子都是定死的，发端只填数值，收端按同一张表解析。")
para(doc, "本工程提供两套参数集（各 16 个 16 位参数 = 32 字节），界面可切换：", bold=True)

h(doc, "3.1 转发板控制参数（默认）—— 遥控板解析后下发给转发板", 2)
rows = []
for q in TP.RELAY_PARAMS:
    rows.append([q["name"], q["off"], q["fmt"], "%g" % q["scale"], q["unit"],
                 "%d~%d" % (q["lo"], q["hi"]), TP.format_eng(q, q["init"]), q["desc"]])
table(doc, ["参数名", "偏移", "类型", "比例", "单位", "范围", "默认", "含义"],
      rows, widths=[2.2, 1.0, 1.0, 1.0, 1.0, 1.9, 1.7, 4.2])

h(doc, "3.2 卫星遥测参数 —— 星上工程参数下行", 2)
rows = []
for q in TP.TM_PARAMS:
    rows.append([q["name"], q["off"], q["fmt"], "%g" % q["scale"], q["unit"],
                 TP.format_eng(q, q["init"]), q["desc"]])
table(doc, ["参数名", "偏移", "类型", "比例", "单位", "默认", "含义"],
      rows, widths=[2.2, 1.0, 1.0, 1.0, 1.0, 2.0, 5.8])
para(doc)
para(doc, "★ 目标频率为 32 位：实际频率 = 目标频率高 x 65536 + 目标频率低（单位 MHz）。", bold=True)

# ============================== 四 ==============================
doc.add_page_break()
h(doc, "四、关键技术问题与解决（核心章节）", 1)

h(doc, "4.1 问题一：AD9361 打不开（引脚整套错）", 2)
table(doc, ["项目", "内容"],
      [["现象", "板上 enable/spi 一直不对，AD9361 无法初始化，"
                "ad9361_config_init_done 始终为 0"],
       ["根因", "本板 AD9361 走的是 LVDS 接口，不是 CMOS；引脚也不对。"
                "最初按别的板子资料接的，整套引脚都是错的"],
       ["解决", "按本板原理图确认：enable=T15, spi_csn=R17, spi_clk=V18, "
                "spi_mosi=P16, spi_miso=V17；数据用 LVDS 差分对；"
                "BD 参数 CMOS_OR_LVDS_N=0、MODE_1R1T=0、ADC_INIT_DELAY=30"],
       ["验证", "板上 ad9361_config_init_done = 1、chip_rst_n = 1、txnrx = 1"]],
      widths=[2.5, 13.5])
para(doc, "教训：换板子资料时，引脚复用与接口电平是最容易踩的坑，必须逐个对照原理图。",
     bold=True)

h(doc, "4.2 问题二：SRRC 滤波器的综合陷阱（最难定位）", 2)
para(doc, "现象：", bold=True)
mono(doc,
     "板上实测（12 探针 ILA）：\n"
     "  datalink + mapper 输出   = 期望 CADU      ->  正确（300/300 逐位验证）\n"
     "  oversampler 零插值输出   = {0, ±31}       ->  正确\n"
     "  SRRC 输出                = {0, -128}      ->  ★ 只剩两个值，完全没有成形波形\n"
     "而同一份 RTL 在 ModelSim 里输出 -46..+44 的正常波形。")
para(doc, "定位过程（三步）：", bold=True)
mono(doc,
     "① 先怀疑幅度不够：给滤波器前加 ÷4 余量（算术右移 2 位）\n"
     "   结果：输入确实变成 ±31，但输出仍是 {0, -128}  ->  不是幅度问题\n"
     "\n"
     "② 再怀疑移位量：把输出右移从 7 改成 9（增益降 4 倍）\n"
     "   结果：板上输出完全没变  ->  ★ 综合结果根本不是那条算式\n"
     "\n"
     "③ 决定性实验：把 SRRC 实体改成直通  sam_o <= sam_i\n"
     "   结果：板上 frame_match = 1、rx_crc_ok = 1、rx_err_cnt = 0，整链全通！\n"
     "   ->  唯一坏掉的就是这个滤波器，一句实验锁定问题")
para(doc, "根因：", bold=True)
para(doc, "euryspace 第三方库的 SRRC 用 variable + for 循环做 61 级乘加累加。"
          "这种写法在 ModelSim 仿真中正确，但 Vivado 综合后行为完全不同 —— "
          "输出恒在 ±128 满量程乱跳。第一版重写（同样是 variable + for）"
          "复现了完全相同的现象，说明这是这类 VHDL 描述的通病，不是偶然。")
para(doc, "解决：改成『综合不可能有歧义』的写法 ——", bold=True)
table(doc, ["原来的写法", "修改后"],
      [["variable 在进程内累加", "全程只用 signal"],
       ["隐式截断的 resize", "每级加法显式 resize（18/19/20/21/22 位）"],
       ["61 个乘法器", "对称结构（h(k)=h(N-1-k)），31 个乘法器"],
       ["位宽靠推断", "乘法两侧精确匹配（9bit x 8bit = 17bit，无需 resize）"],
       ["输出直接切片", "一次算术右移 + 显式饱和"]],
      widths=[7.6, 8.4])
para(doc, "三种版本的板上对比：", bold=True)
table(doc, ["SRRC 版本", "板上 sam_i", "frame_match"],
      [["euryspace 原版（variable + systolic）", "2 个取值 {0,-128}，饱和", "0"],
       ["第一版重写（variable + for 累加）", "249 个取值但幅度 ±128 乱跳", "0"],
       ["现版本（纯 signal，显式位宽）", "110 个取值，范围 ±73，相邻差均值 3.9", "1"]],
      widths=[6.5, 6.5, 3.0])
para(doc, "仿真也从 7/10 相位提升到 10/10 相位，寄存器用量还从 8776 降到 6120。", bold=True)

h(doc, "4.3 问题三：clk_sam 是组合门控时钟", 2)
table(doc, ["项目", "内容"],
      [["根因", "ccsds_rxtx_clock_divider 在 DIVIDER=1 时写成 "
                "clk_o <= clk_i and (not rst_i)，而 rst_i 接的是 not ena_i —— "
                "等于用时钟去与一个来自其他逻辑锥的使能信号，综合后会产生毛刺"],
       ["影响", "clk_sam 域上的大块时序逻辑（SRRC）行为不可预测"],
       ["解决", "DIVIDER=1 时直接透传 clk_o <= clk_i，复位交给各子模块自己的同步复位"],
       ["说明", "Xilinx 明确不推荐用 fabric 组合逻辑分频做时钟；"
                "原厂 ADI 设计用的是 MMCM + BUFG"]],
      widths=[2.5, 13.5])

h(doc, "4.4 问题四：接收机抽取相位在板上对不齐", 2)
table(doc, ["项目", "内容"],
      [["现象", "rx_asm_hit 始终为 0、rx_state_dbg 始终停在 ST_ASM，"
                "接收机在位流里找不到同步字"],
       ["根因", "收发两侧的分频器初始相位在硬件上与仿真不一致 —— "
                "仿真里 PHASE=9 能过，板上过不了"],
       ["解决", "改成 10 个抽取相位各跑一路 ASM 搜索，哪一路先凑满 32 位同步字就锁定它，"
                "后续所有抽取都按锁定相位走。完全不依赖手工标定的相位常数"],
       ["代价", "只多了 10 个 32 位移位寄存器 + 比较；匹配滤波器（最贵的一块）仍然共用"],
       ["验证", "仿真 10 个相位全部 PASS（改动前只有 9 个）"]],
      widths=[2.5, 13.5])

h(doc, "4.5 问题五：datalink 输出字没有有效标志", 2)
table(doc, ["项目", "内容"],
      [["根因", "BITSVALIDP 里的 dat_val_o 被做成了电平（置起后再也不清零），"
                "下游无法判断字边界"],
       ["解决", "改成每输出一个字翻转一次的 wire_word_toggle，"
                "并且放在 if/else 之外；dat_nxt_o 清 0"]],
      widths=[2.5, 13.5])

# ============================== 五 ==============================
doc.add_page_break()
h(doc, "五、验证结果", 1)

h(doc, "5.1 板上 ILA 实测（数字环回）", 2)
mono(doc,
     "frame_match   = 1          <- 整个抓取窗口 8192/8192 全为 1\n"
     "rx_crc_ok     = 1          <- 8192/8192\n"
     "match_cnt     = 01         <- 有一帧完全匹配\n"
     "rx_state_dbg  = 2          <- ST_DONE，解帧完成\n"
     "rx_err_cnt    = 0001       <- 仅 1 个非法输出对\n"
     "rx_frame_idx  = 0x28 = 40  <- 收到整整 40 字节\n"
     "rx_frame_byte = 0x63       <- 期望帧的最后一字节\n"
     "\n"
     "期望帧: 02a00000180043435344532d36472d4e544e2d373031302d5454432d465047412d504f5254210463\n"
     "                                                                    ^^ 末尾正是 0x63")

h(doc, "5.2 仿真（整链环回）", 2)
mono(doc,
     "抽取相位 0..9 全部 PASS\n"
     "每帧 40 字节逐字节一致、CRC 通过、零误码\n"
     "发射端 sam_i 相邻样点差均值约 5（平滑成形）")

h(doc, "5.3 过板子实测（模式 B）", 2)
mono(doc,
     "PC 组包 -> 遥测板发射 -> 环回 -> 遥测板接收 -> PC 解出参数表\n"
     "\n"
     "接 SMA 环回电缆 : 接收 RMS = 2446.6   眼图开度 2.35e8   每符号均值 4490.4\n"
     "不接电缆        : 接收 RMS =   10.9   眼图开度 1.17e6   每符号均值   22.3\n"
     "                  相差 225 倍 / 47 dB\n"
     "\n"
     "两种情况都 ASM 错 0 bit，16 个参数全部与发送端一致")

# ============================== 六 ==============================
h(doc, "六、一个必须知道的物理现象：不接电缆也能收", 2)
para(doc, "AD9361 是收发一体芯片，TX 和 RX 在同一颗硅片 + 同一块 PCB 上，"
          "两边本振又都是 2400 MHz，因此 TX 输出会通过衬底/封装/PCB 耦合进 RX 输入端。"
          "结果是【不接任何电缆也能解出帧】。", bold=True)
para(doc, "这一点用三个实验证明（都是真实射频通路，不是数字串扰）：", bold=True)
mono(doc,
     "A) TX 静默                    峰值     +0 Hz     峰/底 17.4 dB\n"
     "B) TX 出 1 MHz 单音（TXLO 2400） 峰值 +1001250 Hz  峰/底 42.6 dB\n"
     "C) TX 本振挪到 2401 MHz          峰值 +1998750 Hz  峰/底 22.3 dB\n"
     "\n"
     "B -> C 峰位差 = +997500 Hz = +1 MHz\n"
     "只动 TX 本振，接收峰就跟着挪  ->  信号真的走了\n"
     "  TX 基带 -> TX 本振上变频 -> 射频 -> RX 本振下变频 -> RX 基带\n"
     "数字串扰不会受本振影响，所以这一条排除了数字串扰的可能。")
para(doc, "因此：", bold=True)
para(doc, "· 工具会按接收电平 RMS 自动判定路径（>100 判为直连电缆，否则判为内部泄漏），"
          "并显示在界面上")
para(doc, "· 演示要证明『电缆有效』时，必须对比电平（拔掉电缆电平掉 47 dB），"
          "光看『能解出帧』是不够的")

# ============================== 七 ==============================
doc.add_page_break()
h(doc, "七、演示工具", 1)
para(doc, "启动：ccsds_ttc_loopback\\演示工具.bat")
table(doc, ["模式", "数据怎么走", "状态"],
      [["A. 纯软件环回", "参数表→组帧→编码→调制→数字信道→解调→译码→解析参数表",
        "可用（不接硬件）"],
       ["B. 经板子", "PC 组包 → 遥测板发射 → 环回 → 遥测板接收 → PC 解出参数表",
        "已实测通过"],
       ["C. 经 FPGA", "遥测板 FPGA 自主完成编解码", "链路已验证，用 Vivado ILA 演示"]],
      widths=[2.8, 9.2, 4.0])
para(doc)
para(doc, "界面布局：", bold=True)
mono(doc,
     "① 左上：参数集下拉框 + 帧头(SCID/VCID/VCFC) + 参数表（可滚动，只能改数值，带范围校验）\n"
     "        + 通信方式 + 信道条件 + 主按钮\n"
     "② 右上：软件生成的 CCSDS 包（逐参数列出偏移与字节）\n"
     "③ 下方：接收端解析结果\n"
     "        页1 参数解析：结构化表格（参数名/偏移/原始值/工程值/与发送端/说明），\n"
     "                      一致显示绿色、不一致显示红色\n"
     "        页2 详细日志：帧十六进制、帧结构分解（主头/数据域/FECF）、ASM/CRC、板子交互\n"
     "\n"
     "上下两块之间有可拖动的分隔条，可自行调整比例")

# ============================== 八 ==============================
h(doc, "八、资源占用", 1)
table(doc, ["资源", "用量", "总量", "占比"],
      [["Slice LUT", "6263", "17600", "35.6%"],
       ["Slice Register", "6120", "35200", "17.4%"],
       ["Block RAM Tile", "24.5", "60", "40.8%"],
       ["DSP", "0", "80", "0%"],
       ["WNS", "+1.840 ns", "—", "时序收敛"],
       ["WHS", "+0.103 ns", "—", "时序收敛"]],
      widths=[3.5, 3.0, 3.0, 3.0])
para(doc, "注：全程不使用 DSP（use_dsp=yes 会让整设计 DSP 超过 80 而导致 "
          "[Place 30-640] 布局失败）。改用 LUT 实现常量乘法。")

# ============================== 九 ==============================
doc.add_page_break()
h(doc, "九、硬件连接与操作要点", 1)

h(doc, "9.1 接 CMU200 看频谱", 2)
mono(doc,
     "射频中心频率 = 板子本振 + 基带中频偏移\n"
     "  本振 2400 MHz + 中频 0.200 MHz  ->  2400.200 MHz\n"
     "  占用带宽 = 250 ksym/s x (1 + 0.35) = 338 kHz\n"
     "\n"
     "CMU200 设置：Center 2400.200 MHz / Span 1 MHz / RBW 10 kHz / Ref -40 dBm\n"
     "接板子的 TX1A")
para(doc, "注意：CMU200 频率上限取决于选件（常见 2.2 或 2.7 GHz）。上不去就把板子本振改低。"
          "另外 CMU200 只能看频谱，它不认 CCSDS 调制，做不了误码率测量。")

h(doc, "9.2 烧写自定义位流的操作纪律", 2)
mono(doc,
     "必须先让板子停在 u-boot，再烧写：\n"
     "   tools\\uboot_stop.ps1        （或断电重插，在串口出现 Pluto> 时按一下打断）\n"
     "\n"
     "原因：Linux 一跑，ADI 驱动会去访问纯 PL 设计里不存在的 AXI 地址 -> 挂死 ->\n"
     "      Zynq 看门狗（cdns-wdt f8005000.watchdog，10 秒，nowayout）复位整板 ->\n"
     "      FSBL 重新加载原厂位流，我们的设计和 ILA 一起被冲掉。\n"
     "\n"
     "现象提示：停在 u-boot 时三个灯常亮、看不到 Pluto 的 U 盘，这是正常的，不是故障。\n"
     "恢复原厂：Pluto> 敲 boot，或断电重插。")

h(doc, "9.3 安全提醒", 2)
para(doc, "接了 TX1A->RX1A 电缆时，TX 衰减必须 >= 20 dB。", bold=True)
para(doc, "AD9361 接收端耐压约 +2.5 dBm，而 TX 在 0 dB 衰减时输出约 +7 dBm，"
          "直连可能损坏接收通道。当前默认 TX 衰减 40 dB（输出约 -33 dBm）是安全的。")

# ============================== 十 ==============================
h(doc, "十、后续工作", 1)
table(doc, ["#", "内容", "说明"],
      [["1", "接转发板", "把遥控板解析出的转发控制参数通过以太网下发给 LDSDR 转发板；"
                        "转发板工程为 Vivado 2018.3，余 14,516 LUT"],
       ["2", "给 FPGA 加参数注入通路", "让 C 模式也能『电脑填参数 → FPGA 编帧』；"
                                      "可用 FT2232H 的第二个串口通道加一个 UART 接收器（约 100 行 Verilog）"],
       ["3", "真实射频链路验证", "用 SMA 电缆 + 衰减器做真双板或 CMU200 环回，"
                                "替代目前依赖芯片内部泄漏的路径"],
       ["4", "性能指标测量", "用矢量信号分析仪测 EVM；用误码仪测 BER（CMU200 做不到）"]],
      widths=[1.0, 4.5, 10.5])

doc.save(OUT)
print("  已生成: %s (%d B)" % (OUT, os.path.getsize(OUT)))
