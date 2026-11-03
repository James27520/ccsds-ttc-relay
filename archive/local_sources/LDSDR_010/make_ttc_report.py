#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成《遥控遥测链路框架与验证方法》报告"""
import os

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor, Cm

OUT = r"E:\fpga_sdr_project\遥控遥测链路框架与验证方法报告.docx"

doc = Document()

# ---------- 页面设置（A4 + 窄边距，给 ASCII 图留够宽度）----------
_sec = doc.sections[0]
_sec.page_width = Cm(21.0)
_sec.page_height = Cm(29.7)
_sec.left_margin = Cm(1.9)
_sec.right_margin = Cm(1.9)
_sec.top_margin = Cm(2.0)
_sec.bottom_margin = Cm(2.0)

# ★ 去掉东亚文档网格：docGrid 会按格子排布字符，中英混排时容易导致溢出
from docx.oxml.ns import qn as _qn
from docx.oxml import OxmlElement as _OE
_dg = _sec._sectPr.find(_qn("w:docGrid"))
if _dg is not None:
    _sec._sectPr.remove(_dg)

# ---------- 全局字体 ----------
from docx.oxml import OxmlElement


def _set_lang(style_or_run_el, ea="zh-CN"):
    """设置东亚语言，否则 LibreOffice 不会对中文做断行（整串中文被当成一个词）"""
    rPr = style_or_run_el.get_or_add_rPr()
    lang = rPr.find(qn("w:lang"))
    if lang is None:
        lang = OxmlElement("w:lang")
        rPr.append(lang)
    lang.set(qn("w:val"), "en-US")
    lang.set(qn("w:eastAsia"), ea)


st = doc.styles["Normal"]
st.font.name = "Times New Roman"
st.font.size = Pt(10.5)
st._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
st.paragraph_format.space_after = Pt(4)
st.paragraph_format.line_spacing = 1.15
_set_lang(st._element)

for i, (nm, sz) in enumerate([("Heading 1", 15), ("Heading 2", 12.5),
                              ("Heading 3", 11.5), ("Title", 20)]):
    s = doc.styles[nm]
    s.font.name = "Times New Roman"
    s.font.size = Pt(sz)
    s.font.color.rgb = RGBColor(0x1F, 0x35, 0x64)
    s._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")
    _set_lang(s._element)


def H(t, lvl=1):
    doc.add_heading(t, level=lvl)


def _ea(run, ea="宋体", size=None, bold=None):
    """统一设置中西文字体 + 东亚语言（后者决定中文能否断行）"""
    run.font.name = "Times New Roman"
    if size:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    rPr = run._element.get_or_add_rPr()
    rf = rPr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts")
        rPr.append(rf)
    rf.set(qn("w:eastAsia"), ea)
    lang = rPr.find(qn("w:lang"))
    if lang is None:
        lang = OxmlElement("w:lang")
        rPr.append(lang)
    lang.set(qn("w:val"), "en-US")
    lang.set(qn("w:eastAsia"), "zh-CN")


def P(t, bold=False, indent=0):
    p = doc.add_paragraph()
    if indent:
        p.paragraph_format.left_indent = Cm(indent)
    r = p.add_run(t)
    r.bold = bold
    _ea(r, "宋体")
    return p


def B(t):
    p = doc.add_paragraph(style="List Bullet")
    _ea(p.add_run(t), "宋体")
    return p


def CODE(lines):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.6)
    p.paragraph_format.space_before = Pt(3)
    p.paragraph_format.space_after = Pt(6)
    r = p.add_run("\n".join(lines))
    r.font.name = "Consolas"
    r.font.size = Pt(7.5)
    rPr = r._element.get_or_add_rPr()
    rf = rPr.find(qn("w:rFonts"))
    if rf is None:
        from docx.oxml import OxmlElement
        rf = OxmlElement("w:rFonts")
        rPr.append(rf)
    rf.set(qn("w:eastAsia"), "NSimSun")
    return p


def TABLE(headers, rows, widths=None):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Light Grid Accent 1"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        c = t.rows[0].cells[i]
        c.text = ""
        _ea(c.paragraphs[0].add_run(h), "黑体", 9, True)
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            _ea(cells[i].paragraphs[0].add_run(str(v)), "宋体", 9)
    t.autofit = False
    _tw = OxmlElement("w:tblW")
    _tw.set(qn("w:w"), str(int(sum(widths) * 567)))
    _tw.set(qn("w:type"), "dxa")
    t._tbl.tblPr.append(_tw)

    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Cm(w)
    doc.add_paragraph()
    return t


# =====================================================================
doc.add_heading("遥控遥测链路框架与验证方法", level=0)
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run("7010_AD9363 测控板 · RK3588 星上处理 · LDSDR 转发板")
r.font.size = Pt(10.5)
r.font.color.rgb = RGBColor(0x60, 0x60, 0x60)

P("本报告说明遥控遥测（TT&C）链路在整个卫星转发系统中的位置、硬件与软件框架、"
  "协议设计，以及一套可操作的验证方法——包括每一步应该观察到什么现象、"
  "以及为什么该现象能够证明该环节正常。")

# ---------------------------------------------------------------------
H("一、遥控遥测在系统中的位置", 1)

P("整个系统有三块板子、一个星上处理器和三方地面设备：")
CODE([
    "   地面测控站(地面2)                地面馈电站(地面1)",
    "          │                                │",
    "     测控上行                          馈电上行",
    "          ▼                                ▼",
    "   ┌──────────────┐              ┌──────────────────┐",
    "   │   遥测板      │              │  转发板 (LDSDR)   │",
    "   │  7010_AD9363 │              │ RX→DDC→DUC→TX    │",
    "   │  (本报告对象) │              │                  │",
    "   └──┬────────▲──┘              └───┬──────────▲───┘",
    "      │        │                     │          │",
    " 解调遥控│    │发遥测           用户下行│          │用户上行",
    "      ▼        │                     ▼          │",
    "   ┌───────────┴──┐              终端 ◄──────────┘",
    "   │   RK3588     │",
    "   │   星上处理    │",
    "   │   遥测组包    │",
    "   │   指令执行    │",
    "   └──────┬───────┘",
    "          │ 控制指令(串口/以太网)",
    "          ▼",
    "     转发板参数调整",
])

P("遥测板的两项职责：", bold=True)
B("遥控上行：接收地面测控站的射频信号 → 变频 → 数字化 → 交给 RK3588 解调出 CCSDS 遥控包")
B("遥测下行：把 RK3588 组好的 CCSDS 遥测包 → 调制 → 上变频 → 发给地面测控站")

P("注意一个关键事实：", bold=True)
P("遥测板本身是透明转发器（跑厂商原生 PlutoSDR 固件），它不解调、不组包、不应答。"
  "所有协议层的工作都在 RK3588 上完成。这是本框架的核心分工。", indent=0.6)

# ---------------------------------------------------------------------
H("二、硬件框架", 1)

H("2.1 遥测板硬件", 2)
TABLE(
    ["项目", "规格", "说明"],
    [["主芯片", "Xilinx Zynq-7010 (xc7z010clg400)", "PS: 双核 Cortex-A9 / PL: 28K 逻辑单元"],
     ["射频收发", "ADI AD9363-BBCZ", "2R2T，325 MHz–3.8 GHz（保守读法 650M–2.7G）"],
     ["射频带宽", "≤ 20 MHz（数据手册）", "软件可放宽但不应依赖"],
     ["双工巴伦", "Mini-Circuits TCM1-63AX+ ×4", "10 MHz–6 GHz 宽带变压器，无滤波器"],
     ["DDR", "512 MB", "运行 Linux"],
     ["存储", "SD 卡 + 预留 SPI Flash 焊位", "Flash 未贴片"],
     ["USB", "USB3320 PHY", "① RNDIS 网卡 ② U 盘 ③ 串口 ④ IIO-USB"],
     ["以太网", "RTL8211 千兆", "独立于 USB"],
     ["JTAG", "无独立调试器", "仅 USB DFU"],
     ],
    widths=[3.0, 5.5, 7.5])

H("2.2 射频端口与频率规划", 2)
TABLE(
    ["端口", "用途", "当前设置"],
    [["RX1", "遥控上行接收", "RX_LO = 1000.000 MHz"],
     ["RX2", "备用 / 遥测自环", "共用 RX_LO"],
     ["TX1", "遥测下行发射", "TX_LO = 1000.000 MHz"],
     ["TX2", "备用", "共用 TX_LO"],
     ],
    widths=[2.0, 5.0, 6.0])

P("⚠ 重要约束：RX1/RX2 共用同一个本振，TX1/TX2 也共用。所以收发频段不能独立任意设置，"
  "只能靠波束/极化/空间隔离来分离收发。", indent=0.6)

H("2.3 实测得到的硬性限制", 2)
TABLE(
    ["项目", "实测值", "对设计的影响"],
    [["可用采样率", "仅 2.5 / 3.84 / 4 MSPS", "其余请求被静默拒绝并回退到 4 MSPS"],
     ["USB 后端吞吐", "8 ~ 13 MB/s", "2.5 MSPS 单路 IQ 需 10 MB/s，收发同时不够"],
     ["RX 增益范围", "0 ~ 71 dB（manual）", "上电默认 slow_attack 自动模式"],
     ["TX 衰减范围", "0 ~ −89.75 dB", "★ 上电默认接近 0 dB（满功率）"],
     ["上电默认状态", "LO 2.4 GHz / 30.72 MSPS / AGC", "每次上电都要重新配置"],
     ],
    widths=[3.2, 4.5, 7.0])

# ---------------------------------------------------------------------
H("三、信号链细节", 1)

H("3.1 接收方向（遥控上行）", 2)
CODE([
    "地面测控站",
    "   │  射频 f_RF",
    "   ▼",
    "RX1 SMA ──► TCM1-63AX+ 巴伦（单端→差分）",
    "   │",
    "   ▼",
    "AD9363 ──► LNA ──► 正交下变频(RX_LO) ──► 低通 ──► 12bit ADC ×2 (I/Q)",
    "   │        基带 I/Q @ 2.5 MSPS",
    "   ▼",
    "LVDS 接口 ──► PL (FPGA)",
    "   │  DATA_CLK = 4 × 单通道采样率（2R2T 约束）",
    "   │  6 通道 × DDR = 12 bit/时钟；一个 12bit I/Q 样点分两个时钟送",
    "   ▼",
    "AXI-DMA ──► DDR 缓冲区",
    "   │",
    "   ▼",
    "iiod (IIO 服务) ──► USB IIO-USB 后端 ──► RK3588 libiio 客户端",
    "   │",
    "   ▼",
    "numpy 处理：FFT / 滤波 / 解调 / CCSDS 解包 / CRC 校验",
])

H("3.2 发射方向（遥测下行）", 2)
CODE([
    "RK3588: 造遥测包 ──► 调制成 I/Q 波形（int16 交错）",
    "   │",
    "   ▼",
    "libiio 循环缓冲区(cyclic) ──► USB ──► iiod",
    "   │  ★ 循环缓冲区让 DMA 硬件自动无限重复，无需软件干预",
    "   ▼",
    "AXI-DMA ──► PL ──► LVDS ──► AD9363",
    "   │",
    "   ▼",
    "12bit DAC ×2 ──► 正交上变频(TX_LO) ──► 可编程衰减 ──► TX1",
    "   │",
    "   ▼",
    "TCM1-63AX+ 巴伦 ──► TX1 SMA ──► 地面测控站",
])

H("3.3 控制通路", 2)
P("所有参数都通过同一条 USB 链路用 IIO 属性读写：")
TABLE(
    ["参数", "IIO 属性", "注意"],
    [["RX 本振", "ad9361-phy / altvoltage0 / frequency", ""],
     ["TX 本振", "ad9361-phy / altvoltage1 / frequency", ""],
     ["采样率", "ad9361-phy / voltage0 / sampling_frequency", "只有 3 档可用"],
     ["RX 增益", "-i voltage0 hardwaregain", "★ 必须加 -i"],
     ["TX 衰减", "-o voltage1 hardwaregain", "★ 必须加 -o"],
     ["TX 波形", "cf-ad9361-dds-core-lpc 缓冲区", "循环模式可实现连续发射"],
     ["RX 数据", "cf-ad9361-lpc 缓冲区", "支持 1/2/4 通道"],
     ],
    widths=[3.0, 6.5, 4.5])

P("⚠ 通道选择陷阱：AD9361 存在同名通道（voltage0 同时有 input 和 output）。"
  "不加 -i/-o 时命令会写到错误的信道上，而且不报错——这是一个静默失败，"
  "曾导致发射电平异常。", indent=0.6)

# ---------------------------------------------------------------------
H("四、协议栈", 1)

H("4.1 分层", 2)
TABLE(
    ["层", "本系统采用", "说明"],
    [["应用层", "CCSDS 空间包", "遥控包 / 遥测包，带 APID 寻址"],
     ["校验层", "CRC-16/CCITT", "多项式 0x1021，初值 0xFFFF"],
     ["同步层", "同步字 0x1ACFFC1D", "CCSDS 标准附同步标记"],
     ["调制层", "BPSK（设计值）/ FSK（验证值）", "FSK 用于无相干 I/Q 时的验证"],
     ["物理层", "AD9363 正交调制解调", "2.5 MSPS 基带"],
     ],
    widths=[2.5, 5.0, 7.0])

H("4.2 CCSDS 空间包格式", 2)
CODE([
    " 位  15      12 11 10      0",
    "    ┌────────┬──┬──────────┐",
    " w0 │ 版本(0) │类型│  APID    │   类型 0=遥控(TC) 1=遥测(TM)",
    "    ├────────┴──┴──────────┤",
    " w1 │ 序列标志(11) │ 序列计数  │",
    "    ├───────────────────────┤",
    " w2 │      数据长度 − 1      │",
    "    ├───────────────────────┤",
    "    │      数据域 (N 字节)    │",
    "    ├───────────────────────┤",
    "    │      CRC-16 (2 字节)   │",
    "    └───────────────────────┘",
    "   主头固定 6 字节，总长 = 6 + N + 2",
])

H("4.3 APID 分配", 2)
TABLE(
    ["APID", "名称", "方向", "内容"],
    [["0x100", "RELAY_SET", "地面→星", "转发板参数设置（模式/DDC/DUC/增益/直流）"],
     ["0x101", "RELAY_QUERY", "地面→星", "查询转发板状态"],
     ["0x200", "STATUS_TM", "星→地面", "转发板状态遥测"],
     ["0x201", "SPECTRUM_TM", "星→地面", "频谱/信道检测结果"],
     ["0x202", "ACK_TM", "星→地面", "指令执行确认"],
     ],
    widths=[2.2, 3.2, 2.5, 6.6])

P("APID 就是地址。有无地址字段是判断'通信'还是'广播'的判据之一——"
  "纯载波没有地址、没有信息量（香农容量为零），既不是通信也不是广播。", indent=0.6)

H("4.4 帧结构（用于射频验证）", 2)
CODE([
    "┌──────────┬────────────┬──────────────┬────────┐",
    "│ 前导 8bit │ 同步 32bit │ CCSDS 包      │ CRC16  │",
    "│ 10101010 │ 1ACFFC1D   │ 6+N 字节      │ 2 字节  │",
    "└──────────┴────────────┴──────────────┴────────┘",
    "前导用于定时恢复；同步字用于帧定位；CRC 用于独立校验",
])

# ---------------------------------------------------------------------
H("五、RK3588 的职责", 1)

P("RK3588 是星上处理核心，本系统不做星上自主决策（模式 A），它只做三件事：")
TABLE(
    ["职责", "具体内容", "实现"],
    [["解调遥控", "从遥测板取 IQ → 解调 → 找同步字 → 解 CCSDS → 校验 CRC",
      "ttc_modem.py + ttc_fsk_test.py"],
     ["执行指令", "按遥控包内容控制转发板（模式/DDC/DUC/增益）",
      "payload_ctl.py → 串口/以太网 → LDSDR"],
     ["组遥测", "读转发板状态 → 打成 CCSDS 遥测包 → 交给遥测板发射",
      "ccsds.py + ttc_test.py"],
     ],
    widths=[2.5, 7.5, 4.0])

P("RK3588 上的工具链（已确认可用）：", bold=True)
B("Python 3.10.12 + numpy 2.2.1 + scipy 1.15.3")
B("python-iio 绑定（libiio 0.23）")
B("gcc / g++ / make / pyserial")

# ---------------------------------------------------------------------
H("六、验证方法（核心）", 1)

P("遥控遥测是否正常，不能靠'看起来有信号'来判断。必须分层验证，每层都有明确的"
  "判据。以下四层从下到上，每层通过才能进入下一层。")

H("6.1 第一层：控制通路", 2)
P("做什么：", bold=True)
P("从 RK3588 通过 libiio 的 USB 后端读写遥测板的参数。", indent=0.6)
CODE([
    "iio_attr -u usb: -c ad9361-phy altvoltage0 frequency 1000000000",
    "iio_attr -u usb: -c ad9361-phy altvoltage0 frequency      # 回读",
])
P("观察什么现象：", bold=True)
P("写入 1000000000，回读也是 1000000000；写 −40 dB 衰减，回读 −40 dB。", indent=0.6)
P("为什么能证明：", bold=True)
P("说明 USB 物理链路、IIO-USB 协议、AD9363 的 SPI 寄存器访问这三层全部打通。"
  "任何一个环节断了，回读值不会等于写入值。", indent=0.6)

H("6.2 第二层：发射链路", 2)
P("做什么：", bold=True)
P("让遥测板用硬件 DDS 发一个频率已知、连续的单音。", indent=0.6)
CODE([
    "iio_attr -u usb: -c cf-ad9361-dds-core-lpc altvoltage0 frequency 200000",
    "iio_attr -u usb: -c cf-ad9361-dds-core-lpc altvoltage0 scale 0.5",
    "  -> TX_LO 1000.000 MHz + 200 kHz = 1000.200 MHz 输出",
])
P("观察什么现象：", bold=True)
B("频谱仪（CMU200）在 1000.2 MHz 看到一根稳定的谱线")
B("信号稳定、不跳变、频率不漂")
P("为什么能证明：", bold=True)
P("说明'数字→DAC→正交上变频→射频输出'整条发射链路正常，"
  "而且 LO 频率与 DDS 频率的换算关系正确。如果 LO 有偏差、DDS 换算错、"
  "或发射通道没打开，谱线会消失或出现在错误的位置。", indent=0.6)
P("★ 这一步还暴露了一个重要风险：把频谱仪设成 Max Hold 时读到了 +4.5 dBm，"
  "远超稳态值。那是 AD9363 上电初始化的瞬态——衰减还没被驱动设下来时，"
  "TX 是接近满功率的。这直接证明了'绝不能把 TX 直连 RX'。", indent=0.6)

H("6.3 第三层：接收链路", 2)
P("做什么：", bold=True)
P("让遥测板接收一个已知频率的信号，把 IQ 抓回 RK3588 算频谱。", indent=0.6)
P("观察什么现象：", bold=True)
CODE([
    "═══ 遥测板实时频谱（电脑显示）═══",
    "   峰值  -200.20 kHz    -45.6 dBFS   噪声底 -94.6 dBFS   SNR 49.0 dB",
])
P("为什么能证明：", bold=True)
P("说明'射频→下变频→ADC→数字接口→DMA→USB→主机'整条接收链路正常。"
  "而且频率准确度可以直接量化：", indent=0.6)
CODE([
    "期望：DDS 寄存器 200007 Hz @ 采样率 2.5 MSPS   ->  200.007 kHz",
    "实测：200.20 kHz",
    "误差：193 Hz = 0.32 个分辨单元（RBW = 610 Hz）   通过",
])

H("6.4 第四层：协议闭环（最终判据）", 2)
P("做什么：", bold=True)
P("在 RK3588 上造一个 CCSDS 遥控包，调制成射频信号发出去，"
  "经射频环回后再收回来，解调、解包、校验、逐字节比对。", indent=0.6)
CODE([
    "造包  ->  加前导+同步字  ->  调制  ->  TX 循环缓冲区",
    "                                        │",
    "                                   〔射频环回〕",
    "                                        │",
    "收 IQ  ->  解调  ->  找同步字  ->  解 CCSDS  ->  CRC  ->  逐字节比对",
])
P("观察什么现象：", bold=True)
CODE([
    "同步字   0x1ACFFC1D 命中",
    "APID     = 0x100（正确）",
    "CRC-16   校验通过",
    "内容     逐字节一致",
    "误码率   0",
])
P("为什么能证明（最重要）：", bold=True)
P("这是四道相互独立的关卡，任何一环出错都会失败：", indent=0.6)
TABLE(
    ["关卡", "检验什么", "失败说明什么"],
    [["同步字命中", "帧定位 + 位定时", "调制/解调时序错，或频率偏差过大"],
     ["APID 正确", "包结构解析", "CCSDS 打包/解包实现错"],
     ["CRC-16 通过", "数据完整性（独立校验）", "链路有误码，或长度字段错"],
     ["逐字节一致", "端到端内容无损", "协议栈某层有系统性错误"],
     ],
    widths=[3.2, 4.5, 6.5])
P("关键点：内容比对不是'看起来像'，而是逐 bit 比对。而且 CRC 是由发送端计算、"
  "接收端独立重算的——它和内容比对是两道独立的验证。"
  "数据从应用层出发，穿过整个协议栈和射频链路，回到应用层且完全一致，"
  "这才叫'遥控遥测正常'。", indent=0.6)

H("6.5 为什么用 FSK 而不是 BPSK 做验证", 2)
P("设计上遥控遥测用 BPSK。但在当前阶段，遥测板的 I/Q 通道布局存在不确定性"
  "（四个扫描通道互相高度相关，不符合标准 I/Q 关系），相干解调不可靠。", indent=0.6)
P("FSK 的判据是'峰值落在哪个频率'，只需要幅度信息，不需要相干 I/Q —— "
  "所以它能在 I/Q 未修复时给出无歧义的结论。这是验证手段的选择，"
  "不代表最终调制方式。", indent=0.6)

# ---------------------------------------------------------------------
H("七、实测数据汇总", 1)

TABLE(
    ["验证项", "方法", "实测结果", "判定"],
    [["3588 ↔ 遥测板控制", "libiio USB 读写回读", "写入值 = 回读值", "通过"],
     ["IQ 抓取吞吐", "iio_readdev 定长抓取", "8 ~ 13 MB/s", "通过"],
     ["发射频率准确度", "DDS 单音 + CMU200", "1000.2 MHz 稳定谱线", "通过"],
     ["接收频率准确度", "抓 IQ 算 FFT", "误差 193 Hz = 0.32 bin", "通过"],
     ["接收灵敏度", "增益扫描", "最佳增益 10 dB 时 SNR 78.2 dB", "通过"],
     ["CCSDS 打包/解包", "软件环回", "APID / 长度 / CRC 全对", "通过"],
     ["BPSK 调制解调", "加噪自检", "SNR 3 dB 仍能正确解出", "通过"],
     ["射频闭环（FSK）", "循环缓冲区收发", "两个频点能量均在（35.1/32.6 dB）", "部分"],
     ["bit 级解调", "相位搜索解调", "同步字未命中（最好错 6 bit）", "待改进"],
     ["相干 I/Q", "通道相关性分析", "四通道 |相关| > 0.95，非标准 I/Q", "待修复"],
     ],
    widths=[3.4, 4.2, 5.4, 1.8])

# ---------------------------------------------------------------------
H("八、当前的已知问题与后续", 1)

H("8.1 I/Q 通道布局", 2)
P("现象：抓 4 个通道，互相之间相关系数绝对值都大于 0.95；"
  "ch0≈ch2、ch1≈ch3。真正的 I/Q 对相关系数应接近 0。", indent=0.6)
P("影响：无法做相干解调，频谱只能显示为左右对称的实信号谱。"
  "能看到频率和强度，但分不清上/下边带。", indent=0.6)
P("原因：cf-ad9361-lpc 的设备端扫描通道掩码不是 [voltage0, voltage1]。"
  "扫描通道只能通过遥测板自身的 sysfs 修改，libiio 的 USB 后端改不了。"
  "板子重启后掩码会变得不可预期。", indent=0.6)
P("解决方向：登录遥测板的串口控制台，写 "
  "/sys/bus/iio/devices/iio:device3/scan_elements/in_voltage{0,1}_en。", indent=0.6)

H("8.2 射频闭环的 bit 级解调", 2)
P("现象：接收频谱在 150 kHz 和 400 kHz 两个频带都有明显能量"
  "（相对噪声底 35.1 dB / 32.6 dB），说明 FSK 信号确实到达了接收端；"
  "但按 bit 切片解调时，同步字搜索在 300 个相位偏移 × 166 个位置上"
  "最好只做到 6 bit 错——纯噪声在 5 万次尝试下也能碰出这个水平，"
  "所以当前结果不足以判定解调成功。", indent=0.6)
P("已排除：电平和增益（std 从 3.3 提到 107.7，30 倍）、加窗抑制频谱泄漏、"
  "bit 相位偏移（已搜索 60 档）。", indent=0.6)
P("待查：收发采样时钟的实际一致性、循环缓冲区的实际播放时序、"
  "以及 I/Q 布局问题对单通道实数解调的影响。", indent=0.6)

H("8.3 上电瞬态风险（必须记住）", 2)
P("AD9363 上电初始化完成前，TX 衰减接近 0 dB，输出约 +7 dBm，"
  "而 RX 的绝对最大输入只有 +2.5 dBm。", indent=0.6)
TABLE(
    ["操作", "要求"],
    [["连接 TX→RX 之前", "板子必须已启动完、参数已配好（TX 衰减设到 −60 dB）"],
     ["重启板子之前", "必须先拔掉 TX→RX 连线"],
     ["永远不要", "插着线去上电/重启（实测已抓到 +4.5 dBm 的上电瞬态）"],
     ],
    widths=[4.5, 11.0])

# ---------------------------------------------------------------------
H("九、操作手册", 1)

P("RK3588 侧程序（位于 /tmp/ttc/）：", bold=True)
TABLE(
    ["文件", "作用"],
    [["ttc_modem.py", "CCSDS 打包/解包、CRC、BPSK 调制解调"],
     ["ttc_test.py", "单音发射 / 调制发射 / 软件环回 / 射频环回"],
     ["ttc_fsk_test.py", "FSK 遥控遥测闭环验证（含相位搜索解调）"],
     ["ttc_spectrum.py", "持续抓 IQ → FFT → 把 1 KB 频谱发回电脑"],
     ],
    widths=[4.0, 11.5])

P("电脑侧命令：", bold=True)
CODE([
    "cd E:\\LDSDR_010",
    "",
    "python ttc_monitor.py COM8 soft     # CCSDS 协议栈软件环回自检",
    "python ttc_monitor.py COM8 tone     # 开连续单音（1000.2 MHz）",
    "python ttc_monitor.py COM8 toneoff  # 关单音",
    "python ttc_monitor.py COM8 send     # 发 BPSK 调制信号",
    "python ttc_monitor.py COM8 fsk      # ★ FSK 遥控遥测闭环验证",
    "",
    "python ttc_scope.py COM8 --gain 30  # 电脑上看实时频谱",
])

P("电脑侧显示的判读：", bold=True)
TABLE(
    ["看到什么", "说明什么"],
    [["同步字命中 + CRC 通过 + 内容一致", "★ 遥控遥测链路完全正常"],
     ["同步字命中但 CRC 失败", "链路有误码，需提高信噪比或降低速率"],
     ["同步字未命中", "射频链路、增益或解调时序有问题"],
     ["频谱上只有噪声底", "发射未生效或接收未收到"],
     ],
    widths=[6.0, 9.5])

# ---------------------------------------------------------------------
H("十、结论", 1)

P("1. 遥控遥测的框架已经建立：遥测板做透明的射频收发，"
  "RK3588 做全部协议处理，转发板由 RK3588 通过遥控指令控制。", indent=0.6)
P("2. 控制通路、发射链路、接收链路、软件协议栈四层已经验证通过，"
  "其中接收频率准确度达到 0.32 个分辨单元。", indent=0.6)
P("3. 最终判据——射频闭环下的逐字节内容比对——"
  "目前尚未通过。信号确实到达了接收端（两个频点能量都在），"
  "但 bit 级解调还有残留错误，需要先解决 I/Q 通道布局问题。", indent=0.6)
P("4. 在完成 I/Q 修复之前，不要用'有信号'来判定遥控遥测正常。"
  "必须看同步字、CRC 和内容比对这三项。", indent=0.6)

doc.add_paragraph()
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
r = p.add_run("—— 报告完 ——")
r.font.color.rgb = RGBColor(0x80, 0x80, 0x80)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
doc.save(OUT)
print("已生成: %s" % OUT)
print("大小: %d 字节" % os.path.getsize(OUT))
