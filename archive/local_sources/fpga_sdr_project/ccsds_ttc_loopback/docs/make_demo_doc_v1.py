#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_demo_doc.py -- 生成《CCSDS 演示工具 参数说明与演示手册》DOCX

内容：
  1. 演示工具是什么、三种模式
  2. 每个参数的取值范围、含义、如何映射进 CCSDS 帧、演示建议值
  3. 演示步骤（话术）
  4. 要接哪些硬件
  5. 常见问题
"""
import os
from docx import Document
from docx.shared import Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

OUT = r"E:\fpga_sdr_project\CCSDS演示工具_参数说明与演示手册.docx"

CN = "SimSun"          # 宋体：Windows 标准字体，Linux 也有度量兼容替代
MONO = "Courier New"    # 等宽：Windows/Linux 都有


def set_cn(run, name=CN):
    """中文字体要显式设 w:eastAsia，否则中文可能显示成方块"""
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)


def h(doc, text, level=1):
    p = doc.add_heading("", level=level)
    r = p.add_run(text)
    set_cn(r)
    return p


def para(doc, text="", bold=False, size=10.5, color=None, align=None):
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.bold = bold
    r.font.size = Pt(size)
    if color:
        r.font.color.rgb = color
    set_cn(r)
    if align:
        p.alignment = align
    return p


def mono(doc, text, wrap=94):
    """
    等宽文本块。
    ★ 必须按行拆成独立段落并手工折行 —— 第一版把整块塞进一个 run（用 \n 做软换行），
      LibreOffice/Word 对超长不换行串（路径、表格线等）会溢出右边距，渲染出来右边被截掉。
    """
    for raw in text.split("\n"):
        line = raw
        while len(line) > wrap:
            cut = line.rfind(" ", 0, wrap)
            if cut < wrap // 2:
                cut = wrap
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.6)
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(0)
            r = p.add_run(line[:cut])
            r.font.name = MONO
            r.font.size = Pt(8.5)
            r._element.rPr.rFonts.set(qn("w:eastAsia"), MONO)
            line = line[cut:].lstrip()
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(0.6)
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(line)
        r.font.name = MONO
        r.font.size = Pt(8.5)
        r._element.rPr.rFonts.set(qn("w:eastAsia"), MONO)


def table(doc, headers, rows, widths=None):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Light Grid Accent 1"
    for i, htxt in enumerate(headers):
        c = t.rows[0].cells[i]
        c.text = ""
        r = c.paragraphs[0].add_run(htxt)
        r.bold = True
        r.font.size = Pt(9.5)
        set_cn(r)
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            r = cells[i].paragraphs[0].add_run(str(v))
            r.font.size = Pt(9.5)
            set_cn(r)
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Cm(w)
    return t


def main():
    doc = Document()

    # 页边距
    for s in doc.sections:
        s.left_margin = Cm(2.0)
        s.right_margin = Cm(2.0)

    # ---- 标题 ----
    tp = doc.add_heading("", level=0)
    r = tp.add_run("CCSDS 演示工具：参数说明与演示手册")
    set_cn(r)
    para(doc, "适用工具：ccsds_ttc_loopback\\演示工具.bat",
         color=RGBColor(0x44, 0x44, 0x44))
    para(doc, "依据标准：CCSDS 131.0-B（遥测同步与信道编码）", color=RGBColor(0x44, 0x44, 0x44))
    para(doc)

    # ============================================================
    h(doc, "一、这个工具是做什么的", 1)
    para(doc, "它把你要演示的整条链路做成一个窗口：")
    mono(doc,
         "① 左边写参数  ->  ② 中间看到软件生成的 CCSDS 包  ->  ③ 下边看到接收端解出的内容\n"
         "                                                     两端自动逐字节比对，给出结论")
    para(doc, "也就是说：你改一个参数，就能立刻看到“这个参数怎么变成 CCSDS 帧里的字节”、"
              "以及“接收端能不能一模一样地把它解出来”。")

    h(doc, "三种通信方式", 2)
    table(doc,
          ["模式", "数据怎么走", "要不要硬件", "当前状态"],
          [["A. 纯软件环回", "参数→组帧→编码→调制→【数字信道】→解调→译码→比对",
            "不用接任何硬件", "✅ 可用（演示首选）"],
           ["B. 经板子 USB/IIO", "电脑生成 IQ → 遥测板发射；遥测板接收 → 电脑解调译码",
            "遥测板 + SMA 回环线", "✅ 线路已通（界面已接入）"],
           ["C. 经 FPGA", "遥测板 FPGA 自己做 CCSDS 编码调制与解调译码",
            "遥测板 + 我们自己的位流", "❌ 待修（板上 SRRC 成形输出饱和）"]],
          widths=[2.6, 5.8, 3.4, 3.6])

    para(doc)
    para(doc, "⚠️ 注意：模式 A 不接板子，但它把 CCSDS 算法链（随机化、卷积编码、"
              "帧同步、查表译码、CRC 校验）完整跑了一遍，结果与硬件链一致；"
              "它换掉的只有“射频/数字信道”这一段。", bold=True)

    doc.add_page_break()

    # ============================================================
    h(doc, "二、参数怎么设置", 1)
    para(doc, "界面左上有四个参数，它们决定 CCSDS 遥测帧的“主头”和“数据域”。")

    # ---- SCID ----
    h(doc, "1. 航天器 ID（SCID）", 2)
    table(doc,
          ["项目", "说明"],
          [["取值范围", "0 ~ 1023（10 位）"],
           ["填法", "十进制（如 42）或十六进制（如 0x2A）"],
           ["含义", "标识这条遥测链路属于哪个航天器。地面站靠它区分信号来源"],
           ["在帧里的位置", "主头第 1~2 字节的高 10 位"],
           ["演示建议值", "42（=0x2A，本工程一直用的值）"]],
          widths=[3.6, 11.9])
    para(doc, "举例：SCID=42 时，主头前两字节是 02 A0 ——", size=10)
    mono(doc, "  0x02A0 = 0000 0010 1010 0000\n"
              "           ^^^^^^^^^^ 取高 10 位 = 00 0010 1010 = 42   ✓")

    # ---- VCID ----
    h(doc, "2. 虚拟信道 ID（VCID）", 2)
    table(doc,
          ["项目", "说明"],
          [["取值范围", "0 ~ 7（3 位）"],
           ["含义", "同一个航天器里可以有多条虚拟信道，用来区分不同来源/优先级的遥测数据"
                    "（例如：实时工程参数走 0，延时数据走 1）"],
           ["在帧里的位置", "主头第 2 字节的低 3 位"],
           ["演示建议值", "0"]],
          widths=[3.6, 11.9])

    # ---- VCFC ----
    h(doc, "3. 帧计数（VCFC）", 2)
    table(doc,
          ["项目", "说明"],
          [["取值范围", "0 ~ 255（8 位），循环"],
           ["含义", "该虚拟信道已发送的帧数。地面站靠它发现【丢帧】和【重复帧】"],
           ["在帧里的位置", "主头第 4 字节"],
           ["自动行为", "★ 每点一次【生成并发送】，本工具自动 +1（满 255 回 0）"],
           ["演示建议值", "0 起步，连点几次就能演示“帧计数递增”"]],
          widths=[3.6, 11.9])

    # ---- payload ----
    h(doc, "4. 载荷内容", 2)
    table(doc,
          ["项目", "说明"],
          [["长度", "0 ~ 32 字节；超出会被截断到 32 字节，不足自动补 0x00"],
           ["填法", "直接写文字（按 UTF-8 编码）"],
           ["含义", "要传的实际数据内容。这里可以放工程参数、命令、状态字等"],
           ["在帧里的位置", "数据域（主头之后、FECF 之前）"],
           ["演示建议值", "CCSDS-6G-NTN-7010-TTC-FPGA-PORT!  （正好 32 字节，填满）"]],
          widths=[3.6, 11.9])
    para(doc, "为什么是 32 字节：本工程用的帧格式是", size=10)
    mono(doc, "  6 字节主头 + 32 字节数据 + 2 字节 FECF = 40 字节\n"
              "  FECF 是 CRC-16/CCITT-FALSE（poly 0x1021, init 0xFFFF, MSB first）")
    para(doc, "对应 CADU：40 字节 → 随机化 → 卷积编码(1/2) 得 640 bit → 前置 ASM 4 字节 "
              "→ 共 672 bit（84 字节）", size=10)

    doc.add_page_break()

    # ---- comm mode ----
    h(doc, "5. 通信方式", 2)
    table(doc,
          ["选项", "什么时候选它"],
          [["A. 纯软件环回", "★ 演示默认选这个。不接任何硬件，把 CCSDS 算法链完整跑一遍"],
           ["B. 经板子 USB/IIO", "要用真实板子走一遍射频（TX1A→RX1A 环回线）时选"],
           ["C. 经 FPGA", "要展示“FPGA 自己完成 CCSDS 编解码”时选（待 SRRC 修好后可用）"]],
          widths=[4.0, 11.5])

    # ---- channel ----
    h(doc, "6. 信道条件（只在模式 A 生效）", 2)
    table(doc,
          ["参数", "取值", "含义", "建议"],
          [["SNR(dB)", "留空 / 0~30",
            "留空 = 不加噪声（理想信道）；\n填数值 = 按该信噪比加高斯白噪声",
            "先用【留空】演示“能通”，\n再填 10 演示“抗噪”"],
           ["频偏(Hz)", "任意（例 3000）",
            "在接收信号上叠加一个载波频率偏差，\n用来演示链路对频偏的容忍度",
            "填 3000 演示“有频偏也能解”"]],
          widths=[2.6, 2.8, 6.2, 3.9])
    para(doc, "实测参考（本工具在电脑上跑出来的）：", size=10)
    mono(doc,
         "  SNR = 无噪 / 20 / 15 / 12 / 10 / 8 dB   全部 PASS（40 字节逐字节一致）")

    doc.add_page_break()

    # ============================================================
    h(doc, "三、演示步骤（照着念就行）", 1)
    steps = [
        ("准备", "双击 演示工具.bat；通信方式保持默认的“A. 纯软件环回”"),
        ("第 1 步", "把“载荷内容”改成一个观众能记住的字符串，例如  HELLO-2026"),
        ("第 2 步", "点【生成并发送 ▶】"),
        ("第 3 步", "指中间区域说明：这是软件按 CCSDS 131.0-B 组出来的包 ——\n"
                   "            6 字节主头 + 32 字节数据 + 2 字节 FECF = 40 字节；\n"
                   "            再经随机化、卷积编码(1/2)、加同步字 ASM，得到 672 bit 的 CADU"),
        ("第 4 步", "指下边绿色大字：✓ 两端内容完全一致 ——\n"
                   "            接收端解出的 40 字节与发送端逐字节相同，CRC 通过，零误码"),
        ("第 5 步", "（可选）在“SNR(dB)”填 10，再点一次 → 仍然 ✓，说明链路抗噪"),
        ("第 6 步", "（可选）连点几次【生成并发送】→ 看“帧计数”自动递增，演示连续组帧"),
        ("第 7 步", "（进阶）切到“B. 经板子” → 真实过一遍遥测板的射频环回"),
    ]
    for k, v in steps:
        p = doc.add_paragraph(style="List Bullet")
        r = p.add_run("%s：" % k)
        r.bold = True
        set_cn(r)
        r2 = p.add_run(v)
        set_cn(r2)

    # ============================================================
    h(doc, "四、要接哪些硬件", 1)
    table(doc,
          ["演示模式", "需要接的硬件"],
          [["A. 纯软件环回", "什么都不用接"],
           ["B. 经板子", "① 遥测板（7010_AD9363）\n"
                        "② 板子 JTAG 口 Type-C → 电脑（供电 + 调试 + 串口）\n"
                        "③ 板子 OTG 口 Type-C → 电脑（RNDIS 网口，SSH 用它）\n"
                        "④ 一根 SMA 回环线：TX1A ↔ RX1A（出厂附带）\n"
                        "⑤ 板子跑原厂固件（SD 卡原样）"],
           ["C. 经 FPGA", "同 B，但板子要烧 E:\\ccsds_fpga\\ccsds_pl\\out\\ccsds_pl_ila.bit"],
           ["双板完整链路\n（转发板）", "在 B 的基础上再加：\n"
                                       "⑥ 转发板（LDSDR）\n"
                                       "⑦ 两根射频线：遥测板 TX1A → 转发板 RX1A；转发板 TX1A → 遥测板 RX1A\n"
                                       "⑧ ⚠️ 必须加 ≥30 dB 衰减器（遥测板 TX 输出约 +7 dBm，"
                                       "而 RX 耐压仅 +2.5 dBm）\n"
                                       "⑨ ⚠️ 接线状态下绝不能重启板子（上电初始化完成前 TX 衰减≈0）"]],
          widths=[3.2, 12.3])

    para(doc)
    para(doc, "⚠️ 一个必须知道的频率问题：厂商固件里 TX 本振 = 2500 MHz、RX 本振 = 2400 MHz，"
              "两者相差 100 MHz，远超 9 MHz 接收带宽 —— 所以“遥测板自己 TX 接自己 RX”"
              "在默认配置下收不到，必须先把本振改成一致（改 AD936X_lut.v 的寄存器表）。",
         bold=True)

    doc.add_page_break()

    # ============================================================
    h(doc, "五、常见问题", 1)
    faq = [
        ("双击 .bat 报 “'锟斤拷rem' 不是内部或外部命令”",
         "该 .bat 文件带了 BOM 或用了 LF 换行。cmd.exe 只认【纯 ASCII + CRLF】。"
         "本工程的 演示工具.bat 已按此格式重写；若再改，注意保持这两点。"),
        ("点【生成并发送】弹出“该模式暂不可用”",
         "说明你选了 B 或 C。B 需要板子 + 回环线就绪；C 需要板上 SRRC 修好。"
         "演示请先用 A。"),
        ("接收端没同步上（模式 A）",
         "① SNR 填得太低（低于 8 dB 就可能失败）；② 频偏填得太大（超过约 ±10 kHz）。"
         "把两个都清空再试。"),
        ("帧计数怎么变成 2 了",
         "每点一次【生成并发送】自动 +1，这是设计行为，用来演示连续组帧。"),
        ("怎么确认板子在不在",
         "在电脑上跑：Get-PnpDevice -PresentOnly | Where InstanceId -match 'VID_0403'（JTAG 口）"
         "和 'VID_0456'（OTG 口 gadget）。★ 必须带 -PresentOnly，否则会读到 Windows 缓存的历史设备而误判。"),
    ]
    for q, a in faq:
        p = doc.add_paragraph(style="List Bullet")
        r = p.add_run("问：" + q)
        r.bold = True
        set_cn(r)
        p2 = doc.add_paragraph()
        p2.paragraph_format.left_indent = Cm(0.8)
        r2 = p2.add_run("答：" + a)
        set_cn(r2)

    # ============================================================
    h(doc, "六、附：一帧 CCSDS 遥测帧的构成", 1)
    mono(doc,
         "偏移  长度  内容\n"
         "----  ----  ------------------------------------------------\n"
         " 0     2    主头：SCID(10b) + VCID(3b) + 保留 + 帧类型 + 版本\n"
         " 2     2    主头：帧计数(8b) + 状态字\n"
         " 4     2    主头：数据域长度等\n"
         " 6    32    数据域（本工具里就是“载荷内容”）\n"
         "38     2    FECF：CRC-16/CCITT-FALSE\n"
         "----  ----  ------------------------------------------------\n"
         "合计 40 字节 / 320 bit\n"
         "\n"
         "再往下：\n"
         "  随机化（LFSR x^8+x^7+x^5+x^3+1，种子 0xFF）\n"
         "  卷积编码 1/2（K=7，G1=1111001，G2=1011011，第二路取反） → 640 bit\n"
         "  前置 ASM 同步字 0x1ACFFC1D（4 字节）                  → 672 bit CADU\n"
         "  BPSK 调制 + SRRC 成形（β=0.35，过采样 10）\n")

    doc.save(OUT)
    print("  已生成: %s" % OUT)
    print("  大小: %d B" % os.path.getsize(OUT))


if __name__ == "__main__":
    main()
