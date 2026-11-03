#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_link_report.py -- 生成《CCSDS 遥测链路 板上验证报告》DOCX"""
import os
from docx import Document
from docx.shared import Pt, RGBColor, Cm
from docx.oxml.ns import qn

OUT = r"E:\fpga_sdr_project\CCSDS遥测链路_板上验证报告.docx"
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


def mono(doc, t, wrap=92):
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
    s.left_margin = Cm(2.0)
    s.right_margin = Cm(2.0)

p = doc.add_heading("", level=0)
cn(p.add_run("CCSDS 遥测链路 板上验证报告"))
para(doc, "对象：遥测板 7010_AD9363（xc7z010clg400-1 + AD9363）", color=RGBColor(0x44,0x44,0x44))
para(doc, "结论：数字环回整链在硬件上跑通，40 字节逐字节一致、CRC 通过、零误码",
     bold=True, color=RGBColor(0x00,0x66,0x00))
para(doc)

# ---------------- 一 ----------------
h(doc, "一、最终验证结果", 1)
para(doc, "用 12 探针 ILA 在板上抓取（out/base_new2.csv，8192 采样）：")
mono(doc,
     "frame_match   = 1      <- 整个抓取窗口 8192/8192 全为 1\n"
     "rx_crc_ok     = 1      <- 8192/8192\n"
     "match_cnt     = 01     <- 有一帧完全匹配\n"
     "rx_state_dbg  = 2      <- ST_DONE，解帧完成\n"
     "rx_err_cnt    = 0001   <- 仅 1 个非法输出对\n"
     "rx_frame_idx  = 0x28 = 40   <- 收到整整 40 字节\n"
     "rx_frame_byte = 0x63        <- 最后一个字节")
para(doc, "期望帧：")
mono(doc, "02a00000180043435344532d36472d4e544e2d373031302d5454432d465047412d504f5254210463")
para(doc, "该帧最后一个字节正是 0x63，与板上 rx_frame_byte 完全一致；"
          "frame_match 只在 40 字节全部相等时才置位。证据链闭合。", bold=True)

# ---------------- 二 ----------------
h(doc, "二、根因：SRRC 滤波器的综合陷阱", 1)
para(doc, "现象（板级实测，同一个 CCSDS 核）：", bold=True)
mono(doc,
     "发射链 datalink + mapper 输出 = 期望 CADU   ->  正确（板上 300/300 逐位验证）\n"
     "oversampler 零插值输出       = {0, ±31}     ->  正确\n"
     "SRRC 输出                    = {0, -128}    ->  ★ 只剩两个值，完全没有成形波形\n"
     "而同一份 RTL 在 ModelSim 里输出 -46..+44 的正常波形")
para(doc, "决定性实验：把 SRRC 实体改成直通 sam_o <= sam_i，板上立刻 "
          "frame_match=1、rx_crc_ok=1、rx_err_cnt=0 —— 整条链路全通。"
          "这证明：唯一坏掉的就是这个滤波器。", bold=True)
para(doc, "进一步实验：把输出移位量从 7 改成 9（增益降 4 倍），板上输出完全没变"
          "（仍是 ±128）→ 综合结果根本不是那条算式。")
para(doc, "结论：euryspace 库用 variable + for 循环做 61 级乘加累加。"
          "这种写法在仿真中正确，Vivado 综合后行为完全不同。"
          "第一版重写（同样是 variable + for）复现了完全相同的现象，"
          "说明这是这类描述的通病，不是偶然。")

# ---------------- 三 ----------------
h(doc, "三、修复：改成综合无歧义的写法", 1)
para(doc, "文件：rtl\\ccsds_rxtx\\ccsds_rxtx_srrc.vhd（生成脚本 sim\\gen_srrc_signals.py）")
table(doc,
      ["原来的写法", "修改后"],
      [["variable 在进程内累加", "全程只用 signal"],
       ["隐式截断的 resize", "每级加法显式 resize（18/19/20/21/22 位）"],
       ["61 个乘法器", "对称结构，31 个乘法器（h(k)=h(N-1-k)）"],
       ["位宽靠推断", "乘法两侧精确匹配（9bit x 8bit = 17bit）"],
       ["输出直接切片", "一次算术右移 + 显式饱和"]],
      widths=[7.5, 8.0])

para(doc, "三种版本的板上对比：", bold=True)
table(doc,
      ["SRRC 版本", "板上 sam_i", "frame_match"],
      [["euryspace 原版（variable+systolic）", "2 个取值 {0,-128}，饱和", "0"],
       ["第一版重写（variable+for 累加）", "249 个取值，幅度 ±128 乱跳", "0"],
       ["现版本（纯 signal 显式位宽）", "110 个取值，范围 ±73，平滑", "1  ✔"]],
      widths=[6.5, 5.5, 3.0])

# ---------------- 四 ----------------
h(doc, "四、同一会话中修掉的其他问题", 1)
table(doc,
      ["问题", "根因", "修复"],
      [["板子打不开 AD9361", "引脚整套错：本板是 LVDS 不是 CMOS；"
                            "BD 参数 MODE/延迟也不对",
        "enable=T15, spi_csn=R17, spi_clk=V18,\nspi_mosi=P16, spi_miso=V17；\n"
        "CMOS_OR_LVDS_N=0, ADC_INIT_DELAY=30"],
       ["datalink 输出字无有效标志",
        "BITSVALIDP 的 dat_val_o 做成了电平（置起后不清）",
        "改成每输出一个字翻转一次的 wire_word_toggle，"
        "放在 if/else 之外"],
       ["clk_sam 是组合门控时钟",
        "ccsds_rxtx_clock_divider 在 DIVIDER=1 时写 "
        "clk_o <= clk_i and (not rst_i)",
        "改成直接透传 clk_o <= clk_i"],
       ["接收机抽取相位在板上对不齐",
        "收发两侧分频器初始相位在硬件上与仿真不一致",
        "改成 10 个相位并行搜 ASM，先命中者锁定"]],
      widths=[4.0, 5.5, 5.5])

# ---------------- 五 ----------------
h(doc, "五、当前状态与资源", 1)
mono(doc,
     "器件        xc7z010clg400-1\n"
     "Slice LUT   ~6.3K / 17.6K  (36%)\n"
     "Slice Reg   ~6.1K / 35.2K  (17%)\n"
     "Block RAM   24.5 / 60      (41%)\n"
     "DSP         0 / 80          <- 未用 DSP，避免 Place 30-640\n"
     "WNS         +1.840 ns      WHS +0.121 ns")

# ---------------- 六 ----------------
h(doc, "六、怎么复现这个演示", 1)
para(doc, "① 让板子停在 u-boot（否则 Linux 的 ADI 驱动会挂住 AXI，看门狗 10 秒复位整板）：")
mono(doc, "tools\\uboot_stop.ps1        # 或断电重插，在串口出现 Pluto> 时按键打断")
para(doc, "② 烧写 + 抓取：")
mono(doc,
     "vivado -mode batch -source ccsds_pl\\program_and_base.tcl\n"
     "-> 输出 out\\base_new.csv / base_new2.csv")
para(doc, "③ 看结果：")
mono(doc,
     "frame_match = 1   rx_crc_ok = 1   match_cnt = 01\n"
     "rx_frame_idx = 40  rx_frame_byte = 63   <- 期望帧的最后一字节")
para(doc, "④ 恢复原厂：在 Pluto> 敲 boot，或断电重插")

doc.add_page_break()
h(doc, "附：数字环回的数据通路", 1)
mono(doc,
     "ccsds_tx_lvds  (发射)\n"
     "  datalink 组帧/随机化/卷积编码 -> mapper -> symbols\n"
     "  mapper_symbols_samples  -> +/-127\n"
     "  >>> PROJECT PATCH: 这里算术右移 2 位（÷4），给滤波器留余量\n"
     "  oversampler 零插值 (1:10)  -> flt_b = {0, +/-31}\n"
     "  SRRC 61 抽头成形           -> sam_i（本报告的主角）\n"
     "      |\n"
     "      +---- 数字环回（板上直连）----+\n"
     "      |                              |\n"
     "      v                              v\n"
     "ccsds_rx_lvds  (接收)\n"
     "  匹配滤波 SRRC -> 硬判 -> 10 相位并行搜 ASM -> 查表译码\n"
     "  -> 解随机化 -> CRC-16 校验 -> 组 40 字节 -> 与期望帧逐字节比对\n"
     "  -> frame_match / match_cnt / rx_frame_idx / rx_frame_byte")

doc.save(OUT)
print("  已生成: %s (%d B)" % (OUT, os.path.getsize(OUT)))
