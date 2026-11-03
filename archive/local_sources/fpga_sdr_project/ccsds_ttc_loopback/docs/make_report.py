#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_report.py -- 生成双板环回验证报告 DOCX

中文排版要点（都是之前踩过的坑）：
  * 每个 run 都要设 w:lang w:eastAsia="zh-CN"，否则 LibreOffice 里中文不换行
  * 去掉 w:docGrid，否则行距异常
  * 表格要 t.autofit=False + 显式 tblW，否则列宽失控
"""
import os
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

OUT = r"E:\fpga_sdr_project\ccsds_ttc_loopback\docs\CCSDS双板环回验证报告.docx"
os.makedirs(os.path.dirname(OUT), exist_ok=True)

doc = Document()

# ---------- 页面 ----------
sec = doc.sections[0]
sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
for m in ("left_margin", "right_margin"):
    setattr(sec, m, Cm(2.0))
for m in ("top_margin", "bottom_margin"):
    setattr(sec, m, Cm(1.9))


def _fix(run, size=10.5, bold=False, color=None, mono=False):
    run.font.size = Pt(size)
    run.font.bold = bold
    name = "Consolas" if mono else "Microsoft YaHei"
    run.font.name = name
    rpr = run._element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts")
        rpr.append(rf)
    rf.set(qn("w:ascii"), name)
    rf.set(qn("w:hAnsi"), name)
    rf.set(qn("w:eastAsia"), "Microsoft YaHei" if not mono else "Microsoft YaHei")
    # ★ 关键：给每个 run 加东亚语言标记，否则 LibreOffice 里中文不换行
    lang = rpr.find(qn("w:lang"))
    if lang is None:
        lang = OxmlElement("w:lang")
        rpr.append(lang)
    lang.set(qn("w:val"), "en-US")
    lang.set(qn("w:eastAsia"), "zh-CN")
    if color:
        run.font.color.rgb = RGBColor(*color)


def _kill_grid(p):
    """清掉 docGrid，并显式打开东亚换行相关的属性。

    ★ LibreOffice 渲染 CJK 时，如果段落没有这些属性，会把一整串中文当成
      一个不可断的词，直接冲出右边界被切掉。Word 通常能自己处理，
      但为了让 LibreOffice 预览也正确，这里显式写上。
    """
    ppr = p._element.get_or_add_pPr()
    for g in ppr.findall(qn("w:docGrid")):
        ppr.remove(g)
    # 东亚排版属性：允许西文与东亚文字间自动间距、允许标点溢出、允许行首禁则
    for tag, val in (("w:autoSpaceDE", "1"), ("w:autoSpaceDN", "1"),
                     ("w:overflowPunct", "1")):
        e = ppr.find(qn(tag))
        if e is None:
            e = OxmlElement(tag)
            ppr.append(e)
        e.set(qn("w:val"), val)
    # 关键：允许在东亚文字之间断行
    ww = ppr.find(qn("w:wordWrap"))
    if ww is None:
        ww = OxmlElement("w:wordWrap")
        ppr.append(ww)
    ww.set(qn("w:val"), "0")


def H(text, level=1):
    p = doc.add_heading("", level=level)
    _kill_grid(p)
    r = p.add_run(text)
    sizes = {0: 19, 1: 14.5, 2: 12.5, 3: 11}
    _fix(r, sizes.get(level, 11), bold=True,
         color=(0x1F, 0x3A, 0x5F) if level <= 2 else (0x33, 0x33, 0x33))
    return p


def P(text, size=10.5, bold=False, align=None, indent=0.0, mono=False, color=None):
    p = doc.add_paragraph()
    _kill_grid(p)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.line_spacing = 1.25
    if indent:
        p.paragraph_format.left_indent = Cm(indent)
    if align:
        p.alignment = align
    _fix(p.add_run(text), size, bold, color, mono)
    return p


def CODE(lines):
    for ln in lines:
        p = doc.add_paragraph()
        _kill_grid(p)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.line_spacing = 1.0
        p.paragraph_format.left_indent = Cm(0.5)
        _fix(p.add_run(ln if ln else " "), 8, False, (0x20, 0x20, 0x20), mono=True)


def BULLET(text, size=10.5):
    p = doc.add_paragraph(style="List Bullet")
    _kill_grid(p)
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.line_spacing = 1.2
    _fix(p.add_run(text), size)


USABLE_CM = 17.0        # A4 宽 21.0 − 左右边距 2.0×2


def TABLE(headers, rows, widths=None):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False

    # ★ 关键：如果给了列宽，先按比例缩放到可用宽度，否则表格会伸出页面右边被切掉。
    #   （tblW=100% 和显式 cell width 同时存在时，LibreOffice 会以 cell width 为准）
    ncol = len(headers)
    if widths:
        tot = float(sum(widths))
        if tot > 0:
            widths = [w * USABLE_CM / tot for w in widths]
    else:
        widths = [USABLE_CM / ncol] * ncol

    # 明确写 tblW 为固定总宽（dxa 单位，1 cm = 567 twips）
    tblpr = t._tbl.tblPr
    for e in tblpr.findall(qn("w:tblW")):
        tblpr.remove(e)
    tw = OxmlElement("w:tblW")
    tw.set(qn("w:w"), str(int(USABLE_CM * 567)))
    tw.set(qn("w:type"), "dxa")
    tblpr.append(tw)

    # 同时写 tblGrid，LibreOffice 更认这个
    grid = t._tbl.find(qn("w:tblGrid"))
    if grid is not None:
        t._tbl.remove(grid)
    grid = OxmlElement("w:tblGrid")
    for w in widths:
        gc = OxmlElement("w:gridCol")
        gc.set(qn("w:w"), str(int(w * 567)))
        grid.append(gc)
    t._tbl.insert(list(t._tbl).index(tblpr) + 1, grid)

    for i, h in enumerate(headers):
        c = t.rows[0].cells[i]
        c.text = ""
        p = c.paragraphs[0]
        _kill_grid(p)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _fix(p.add_run(h), 9.5, bold=True)
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            p = cells[i].paragraphs[0]
            _kill_grid(p)
            p.paragraph_format.space_after = Pt(1)
            _fix(p.add_run(str(v)), 9.5)

    for r in t.rows:
        for i, w in enumerate(widths):
            r.cells[i].width = Cm(w)
    doc.add_paragraph()
    return t


# =====================================================================
H("CCSDS 遥测下行链路", 0)
H("双板环回端到端验证报告", 0)

P("验证目标：在 FPGA-SDR 卫星转发器平台上，打通从软件编码 → 真实射频发射 → "
  "转发板中继 → 接收解调 → 译码校验的完整闭环。",
  size=11, bold=True)

P("日期：2026 年 10 月     平台：Zynq-7010 + AD9363 ×2     状态：✅ 验证通过",
  size=9.5, color=(0x60, 0x60, 0x60))

# ---------------------------------------------------------------- 1
H("1  验证结论", 1)

P("双板环回链路验证通过。接收端在 +200 kHz 频偏处解出 8 个 CCSDS 传输帧，"
  "全部通过 CRC-16 校验，载荷数据与发送端逐字节一致。")

TABLE(["检验项", "结果", "说明"],
      [["链路增益", "+32.7 dB", "发射开 vs 发射关的接收功率差，证明信号确实经转发板返回"],
       ["接收 SNR", "45.0 dB", "频谱峰值与底噪之差"],
       ["定时恢复", "相位 5/10", "眼图开度 955,909"],
       ["同步字搜索", "0 bit 错", "0x1ACFFC1D 精确命中"],
       ["译码结果", "8 帧", "连续 8 个传输帧"],
       ["CRC-16", "全部通过", "说明每一个比特都正确"],
       ["载荷比对", "逐字节一致", "SCID=0x2A, MCFC 连续递增"],
       ["转发板饱和", "0 次", "4 秒内 clip 计数零增长"]],
      widths=[3.6, 3.4, 10.0])

P("这条链路的物理路径是：遥测板 TX1 → 转发板 RX1 → 转发板基带转发通路 → "
  "转发板 TX1 → 遥测板 RX1。信号穿过了两块板子的射频前端、ADC、FPGA 转发通路和 DAC，"
  "因此这是一次真实的射频端到端验证，而非软件环回。")

# ---------------------------------------------------------------- 2
H("2  硬件与链路架构", 1)

H("2.1  硬件配置", 2)
TABLE(["板子", "主芯片", "射频芯片", "角色", "控制方式"],
      [["遥测板", "Zynq-7010", "AD9363", "CCSDS 发射 / 接收", "stock PlutoSDR 固件 + libiio / SSH"],
       ["转发板", "Zynq-7010", "AD9363 (2R2T)", "双通道透明转发", "自研 PL + 裸机程序 / 串口 CLI"]],
      widths=[2.2, 2.4, 2.8, 3.8, 5.8])

P("两块板子都是 4 个射频口、两组 TX/RX。本验证使用第 1 组（RX1/TX1）。")

H("2.2  完整信号链", 2)
CODE([
    "Python 生成 TM 传输帧 (CCSDS 132.0-B)",
    "    |  CRC-16 FECF",
    "    |  伪随机化 (LFSR)",
    "    |  卷积编码 (7,1/2)",
    "    |  ASM 插入 (0x1ACFFC1D)",
    "    |  BPSK 映射 + SRRC 成形",
    "    v  +200 kHz 中频",
    "遥测板 TX1 ------ 1000.2 MHz ------> 转发板 RX1 (RX_LO = 1000 MHz)",
    "                                        |  基带 +200 kHz",
    "                                     转发板 TX1 (TX_LO = 1000 MHz)",
    "                                        |  1000.2 MHz",
    "遥测板 RX1 <--------------------------- +",
    "    |  iio_readdev 抓回电脑",
    "    |  自动频偏搜索 -> 下变频",
    "    |  SRRC 匹配滤波 -> 符号定时恢复",
    "    |  ASM 搜索 -> Viterbi 译码",
    "    |  解随机化 -> 解传输帧",
    "    v  CRC-16 校验",
    "8 个帧，逐字节一致   [验证通过]",
])

# ---------------------------------------------------------------- 3
H("3  CCSDS 发射链", 1)

P("依据 CCSDS 131.0-B（TM 同步与信道编码）与 132.0-B（TM 空间数据链路协议）。")

H("3.1  三个最容易搞错的地方", 2)
TABLE(["#", "要点", "说明"],
      [["1", "ASM 插在随机化之后",
        "所以 ASM 本身不被随机化。euryspace 的 asm_encoder.vhd 注释明确写着 "
        "\"add asm stream after pseudo randomization\""],
       ["2", "随机化 LFSR 参数",
        "h(x) = x⁸+x⁷+x⁵+x³+1，对应多项式 0xA9，初值全 1（0xFF）"],
       ["3", "卷积编码第二路取反",
        "G1 = 0o171 = 0x79，G2 = 0o133 = 0x5B，OUTPUT_INVERSION = (false, true)"]],
      widths=[0.9, 4.2, 11.9])

H("3.2  关键参数", 2)
TABLE(["参数", "取值", "备注"],
      [["采样率 fs", "2.5 MSPS", "遥测板（PlutoSDR 固件）只接受 2.5 / 3.84 / 4 MSPS"],
       ["符号率", "250 ksym/s", "过采样比 = 10"],
       ["调制", "BPSK", "bit 0 → +1，bit 1 → −1"],
       ["成形滤波", "SRRC β = 0.35", "跨度 8 个符号"],
       ["中频", "+200 kHz", "避开零中频的直流失调与本振泄漏"],
       ["信道编码", "卷积 (7,1/2)", "约束长度 7"],
       ["同步字", "0x1ACFFC1D", "32 bit"],
       ["帧结构", "6 + N + 2 字节", "主头 + 数据域 + CRC-16 FECF"],
       ["CRC", "CRC-16/CCITT", "多项式 0x1021，初值 0xFFFF"]],
      widths=[3.2, 4.0, 9.8])

H("3.3  传输帧格式（132.0-B）", 2)
CODE([
    "octet 1-2 : 版本(2) | 航天器ID(10) | 虚拟信道ID(3) | OCF标志(1)",
    "octet 3   : 主信道帧计数 MCFC (8)",
    "octet 4   : 虚拟信道帧计数 VCFC (8)",
    "octet 5-6 : 副头标志(1) | 同步标志(1) | 包序标志(1) | 段长标识(2) | 首包头指针(11)",
    "octet 7.. : 数据域",
    "末尾 2 字节: FECF (CRC-16/CCITT)",
])

# ---------------------------------------------------------------- 4
H("4  接收链与自动频偏搜索", 1)

H("4.1  为什么必须做频偏搜索", 2)
P("最初接收端硬编码「信号在 +200 kHz」。实测频谱峰值出现在 −153 kHz 附近，"
  "按 +200 kHz 下变频后得到的不是干净的 BPSK，译码必然失败。")
P("真实接收机同样需要载波恢复。本工程采用最直接的办法：在 ±600 kHz 范围按 10 kHz 步进"
  "扫描频偏，每个频偏都完整跑一遍「下变频 → 匹配滤波 → 定时恢复 → ASM 搜索 → Viterbi」，"
  "取能通过 CRC 校验的那个。", indent=0.4)

P("加上频偏搜索后，正确频偏处输出为 +200 kHz —— 与发射端设置完全一致，"
  "同时印证了整条射频链路的频率是准确的。", bold=True)

H("4.2  接收处理步骤", 2)
TABLE(["步骤", "处理", "实现要点"],
      [["1", "直流去除", "减去 I/Q 均值"],
       ["2", "下变频", "乘以 exp(−j2π·f_off·t)，f_off 由搜索给出"],
       ["3", "匹配滤波", "与发射端相同的 SRRC，总响应升余弦"],
       ["4", "符号定时恢复", "在 [0, 10) 个采样相位上扫描，取 Σ|Re| 最大者"],
       ["5", "判决", "Re < 0 → bit 1"],
       ["6", "ASM 搜索", "逐位滑窗比对 0x1ACFFC1D，≤2 bit 错即认为命中"],
       ["7", "Viterbi 译码", "硬判决，状态 7 位（见 6.3 的坑）"],
       ["8", "解随机化", "与发射端同一个 LFSR，自逆"],
       ["9", "解帧 + CRC", "按 108 / 40 字节候选帧长尝试，CRC 通过即接受"]],
      widths=[1.3, 3.4, 12.3])

H("4.3  软件自检结果", 2)
P("用发射端波形加高斯白噪声喂接收链，验证鲁棒性：")
TABLE(["SNR (dB)", "定时相位", "ASM 错 bit", "解出帧", "内容一致"],
      [["40", "0", "0", "1", "✅"], ["30", "0", "0", "1", "✅"],
       ["25", "0", "0", "1", "✅"], ["20", "0", "0", "1", "✅"],
       ["15", "0", "0", "1", "✅"], ["12", "0", "0", "1", "✅"],
       ["10", "0", "0", "1", "✅"]],
      widths=[3.0, 3.0, 3.2, 3.0, 3.0])
P("SNR 降至 10 dB 仍能完美解码，说明接收链实现正确。")

# ---------------------------------------------------------------- 5
H("5  转发板双通道改造", 1)

P("转发板原设计只有一组通道。为支持双向转发（基站→终端、终端→基站），"
  "把 PL 扩展为双通道并保持完全独立。")

H("5.1  改动内容", 2)
TABLE(["改动", "说明"],
      [["NCO 从 2 个增至 4 个", "每个通道独占一对 DDC/DUC NCO，可独立设置多普勒补偿"],
       ["新增 ch2 控制寄存器", "0x2C CH2_CTRL、0x30 CH2_DDC_FREQ、0x34 CH2_DUC_FREQ"],
       ["新增 ch2 状态寄存器", "0x38 样点计数、0x3C 饱和计数"],
       ["复位默认值改为转发模式", "两个通道上电即转发，不依赖 PS 程序"],
       ["PS 端 CLI 扩展", "新增 stat2 / mode2 / ddc2 / duc2 / off2 / xoff2 / gain2 / dc2 命令"]],
      widths=[4.6, 12.4])

H("5.2  资源占用（xc7z010clg400-1）", 2)
TABLE(["资源", "使用", "总量", "占比"],
      [["Slice LUTs", "3346", "17600", "19.01%"],
       ["Slice Registers", "5992", "35200", "17.02%"],
       ["Block RAM Tile", "5.5", "60", "9.17%"],
       ["DSPs", "20", "80", "25.00%"]],
      widths=[4.5, 3.5, 3.5, 3.5])
P("时序：WNS = +0.588 ns，WHS = +0.022 ns，均满足。")
P("DSP 用量恰好是单通道的 2 倍（每通道 10 个），说明两通道的 DSP 实现完全对称。")

H("5.3  双通道验证结果", 2)
TABLE(["检验项", "ch1 (RX1→TX1)", "ch2 (RX2→TX2)"],
      [["转发模式 + 单位增益", "✅", "✅"],
       ["ADC 计数在增长", "✅", "✅"],
       ["收发计数同步（零丢样）", "✅ in−out = 0", "—"],
       ["射频通路", "✅ 可见波形", "✅ 可见波形"],
       ["互不干扰", "✅ 改 ch2 不影响 ch1", "✅ 改 ch1 不影响 ch2"]],
      widths=[4.6, 6.2, 6.2])

# ---------------------------------------------------------------- 6
H("6  问题定位与根因分析", 1)

P("本次验证过程中遇到的所有问题、真实根因与修复方式。这些都是实测确认的，不是推测。")

TABLE(["#", "现象", "根因", "修复"],
      [["6.1", "板子命令返回 rc=127",
        "板子固件是 Buildroot，没有 pkill / timeout / python",
        "改用 killall + pidof；限时改为把 -s 设成正好 N 秒的样点数，让工具自己退出"],
       ["6.2", "SSH 会话卡住 160 秒",
        "stdin 用 while true; do cat 供给，iio_writedev 退出后 cat 仍往断掉的管道写",
        "改成有界 for 循环，算好需要几遍，写完自然结束"],
       ["6.3", "Viterbi 译码结果错乱",
        "状态用了 6 位，但编码器寄存器是 7 位，输入比特存在最低位，被丢掉了",
        "改用 7 位状态（128 个），回溯时取新状态的最低 bit 作为输入"],
       ["6.4", "找不到同步字",
        "硬编码 b\"C\\xff\\xc1\\x1d\" = 43 FF C1 1D，而 ASM 是 0x1ACFFC1D = 1A CF FC 1D",
        "统一从 ASM 常量派生字节串，不再手写字面量"],
       ["6.5", "转发板 RX 饱和 6.9 亿次",
        "rxgain ≥ 15 时 RX 通路饱和（实测 15 → 45 万次/4 秒，20 → 1920 万次/4 秒）",
        "rxgain 限制在 ≤ 10；配合转发板 TX 衰减构成可编程衰减链"],
       ["6.6", "CMU200 在 900 MHz 收不到波形",
        "转发板 TX_LO 设成了 1000。搬频关系是 输出 = 输入 + (TX_LO − RX_LO)",
        "改为 lo 1000 900，实现 1000 MHz 进 / 900 MHz 出"],
       ["6.7", "抓不到数据 / 抓到的全是噪声",
        "抓取命令里用了 timeout，板子上没有这个命令；且接收端硬编码中频",
        "去掉 timeout；接收端加自动频偏搜索"]],
      widths=[1.0, 3.5, 6.0, 6.5])

H("6.1  关于「用可编程衰减代替物理衰减器」", 2)
P("AD9361 的 TX 满量程约 +7 dBm，RX 绝对最大输入 +2.5 dBm。"
  "直接用 SMA 线对接两块板子存在过载风险。")
P("本验证用转发板的 TX 衰减（0 ~ −89.75 dB）和 RX 增益（0 ~ 71 dB）"
  "构成约 160 dB 的可编程调节范围，替代物理衰减器：", indent=0.4)
TABLE(["环节", "电平", "对端耐压", "余量"],
      [["遥测板 TX → 转发板 RX", "+7 − 30 = −23 dBm", "+2.5 dBm", "25 dB"],
       ["转发板 TX → 遥测板 RX", "+7 − 60 = −53 dBm", "+2.5 dBm", "55 dB"],
       ["遥测板上电瞬态", "−3 dBm", "+2.5 dBm", "安全"],
       ["转发板上电瞬态", "+4.5 dBm", "+2.5 dBm", "⚠️ 超 2 dB"]],
      widths=[4.6, 4.6, 3.4, 4.4])
P("唯一真实风险是转发板上电瞬态。对策：接线状态下不重启转发板；"
  "串一个 30 dB SMA 衰减器可彻底消除。", bold=True)

# ---------------------------------------------------------------- 7
H("7  交付物", 1)

TABLE(["类别", "文件", "作用"],
      [["软件", "ccsds_tm_tx.py",
        "CCSDS 核心库：132.0-B 帧 / CRC / 随机化 / 卷积 / ASM / BPSK / SRRC + Viterbi 译码"],
       ["软件", "auto_decode.py", "带自动频偏搜索的接收端（本次成功的关键）"],
       ["软件", "sweep_gain.py", "自动扫增益找可解码点"],
       ["软件", "diag_link.py", "链路通断快速诊断（对比发射开关的接收功率）"],
       ["软件", "arm_loopback.py", "双板安全配置"],
       ["软件", "loopback_test.py", "完整环回测试"],
       ["软件", "test_rx_chain.py", "接收链软件自检"],
       ["固件", "relay_dq.v 等 6 个", "转发板双通道 PL 源码"],
       ["脚本", "program_device.tcl", "转发板 JTAG 烧录流程"],
       ["脚本", "build_pl.tcl / modify_bd.tcl", "转发板 PL 构建与 BD 修改"]],
      widths=[1.8, 4.6, 10.6])

# ---------------------------------------------------------------- 8
H("8  结论与下一步", 1)

H("8.1  已完成", 2)
BULLET("转发板双通道双向转发改造完成，PL 通过时序收敛，资源占用 19%/17%/9%/25%")
BULLET("转发板双通道寄存器级与独立性验证全部通过，射频通路确认可见波形")
BULLET("CCSDS 遥测发射链实现并软件自检通过（含反向解码器）")
BULLET("接收链实现并在 SNR 10 dB 下自检通过")
BULLET("双板环回射频端到端验证通过：8 个帧 CRC 全部正确，载荷逐字节一致")
BULLET("遥测板 FPGA 工程（Pluto 2018.3）在新环境下可完整重建，基线出比特流")
BULLET("CCSDS FPGA 开源参考调研完成，选定 MIT 许可的 euryspace 作为主干")

H("8.2  下一步", 2)
TABLE(["优先级", "任务", "说明"],
      [["高", "把 CCSDS 编码搬进 FPGA",
        "把 euryspace（MIT）加进 Pluto 工程，在顶层拦截 DAC 数据注入。"
        "工程基线已可构建（LUT 44%、FF 40%、BRAM 3%、DSP 70%）；"
        "注意 DSP 已用 70%，需评估 SRRC 的 DSP 占用"],
       ["中", "接收端连续解码",
        "当前依赖发射与抓取的时序重合，只能断续解出。加入更好的定时/载波同步可连续解"],
       ["中", "转发板样点率标定",
        "实测计数率约为请求值的 1/6，比例恒定说明控制线性有效，但绝对标定需查证"],
       ["低", "RS(255,223) 编码",
        "CCSDS 标准中的可选纠错，euryspace 未实现，可从 dshekhalev/FEC（MIT）移植"]],
      widths=[1.6, 4.4, 11.0])

doc.add_paragraph()
P("—— 报告结束 ——", size=9, align=WD_ALIGN_PARAGRAPH.CENTER,
  color=(0x80, 0x80, 0x80))

doc.save(OUT)
print("已生成: %s" % OUT)
print("大小: %d 字节" % os.path.getsize(OUT))
