#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_demo_doc.py -- 生成《CCSDS 演示工具 遥测参数与演示手册》DOCX"""
import os
import sys

from docx import Document
from docx.shared import Pt, RGBColor, Cm
from docx.oxml.ns import qn

sys.path.insert(0, r"E:\ccsds_fpga\tools")
import tm_params as TP  # noqa: E402

OUT = r"E:\fpga_sdr_project\CCSDS演示工具_遥测参数与演示手册.docx"
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
cn(p.add_run("CCSDS 演示工具：遥测参数说明与演示手册"))
para(doc, "启动：ccsds_ttc_loopback\\演示工具.bat", color=RGBColor(0x44, 0x44, 0x44))
para(doc, "依据：CCSDS 131.0-B（遥测同步与信道编码）", color=RGBColor(0x44, 0x44, 0x44))
para(doc)

# ============================== 一 ==============================
h(doc, "一、重要：遥测发的是『固定格式的参数表』，不是自由文本", 1)
para(doc, "这一点很容易搞错，先说清楚：", bold=True)
mono(doc,
     "遥测下行（星->地）：\n"
     "  · 发的是一组【事先定义好的工程参数】：每个参数在数据域里的字节偏移、\n"
     "    类型、量纲、比例因子都是任务书 / 接口文件里定死的\n"
     "  · 星上只负责把测量值填进对应位置，地面按同一张表解析\n"
     "  · 星上【不能】随便发一段文本 —— 地面根本不知道那串字节是什么意思\n"
     "\n"
     "『想发什么就发什么』那是上行数据注入 / 遥控指令，属于另一条链路，\n"
     "由地面站发给星上，不是遥测。\n"
     "\n"
     "所以本工具界面是一张【只能改数值】的参数表（类似 IIO 的属性列表）：\n"
     "偏移 / 类型 / 量纲都锁死，只让改数字，并做范围校验。")
para(doc, "帧格式固定 40 字节：6 字节主头 + 32 字节数据域（16 个 16 位参数）+ 2 字节 FECF。",
     bold=True)

# ============================== 二 ==============================
h(doc, "二、链路架构：CCSDS 帧里装的是什么", 1)
para(doc, "这一条最容易被搞错，先说清楚：", bold=True)
mono(doc,
     "本系统的链路：\n"
     "  （信号源）--CCSDS 帧--> 遥控板接收 --> 遥控板解析出【转发控制参数】\n"
     "                                      --> 通过以太网下发给转发板\n"
     "                                      --> 转发板按参数工作\n"
     "                                          （转发到哪个频段、多大带宽、多少增益…）\n"
     "\n"
     "所以帧的数据域里装的是【转发板的控制参数】，不是自由文本。\n"
     "每个参数在数据域里的字节偏移、类型、量纲、比例因子都是事先定死的；\n"
     "发端只填数值，收端按同一张表解析。\n"
     "\n"
     "为什么不能随便发文本：地面/转发板不知道那串字节是什么意思。\n"
     "『想发什么就发什么』那是数据注入，不是常规遥控/遥测。")

h(doc, "两套参数集（界面左上角可切换，共用同一个 40 字节帧格式）", 2)
para(doc, "① 转发板控制参数（默认）—— 遥控板解析后下发给转发板", bold=True)
rows = []
for q in TP.RELAY_PARAMS:
    rows.append([q["name"], q["off"], q["fmt"], "%g" % q["scale"], q["unit"],
                 "%d ~ %d" % (q["lo"], q["hi"]), TP.format_eng(q, q["init"])])
table(doc, ["参数名", "偏移", "类型", "比例", "单位", "允许范围(原始值)", "默认工程值"],
      rows, widths=[2.5, 1.1, 1.1, 1.2, 1.2, 3.5, 2.5])
para(doc)
for q in TP.RELAY_PARAMS:
    para(doc, "· %s（偏移 %d，%s，x%g %s）：%s"
         % (q["name"], q["off"], q["fmt"], q["scale"], q["unit"], q["desc"]), size=9.5)
para(doc)
para(doc, "★ 目标频率是 32 位：实际频率 = 目标频率高 x 65536 + 目标频率低（单位 MHz）。"
          "默认 5785 MHz；演示时改成 2200 就是「转发到 2200 MHz」。", bold=True)

para(doc)
para(doc, "② 卫星遥测参数 —— 传统的星上工程参数下行", bold=True)
rows = []
for q in TP.TM_PARAMS:
    rows.append([q["name"], q["off"], q["fmt"], "%g" % q["scale"], q["unit"],
                 "%d ~ %d" % (q["lo"], q["hi"]), TP.format_eng(q, q["init"])])
table(doc, ["参数名", "偏移", "类型", "比例", "单位", "允许范围(原始值)", "默认工程值"],
      rows, widths=[2.5, 1.1, 1.1, 1.2, 1.2, 3.5, 2.5])
para(doc, "两套参数都是 16 个 16 位参数，正好占满 32 字节数据域。"
          "切换参数集时界面会重建表格，数值恢复成该套的默认值。")

# ============================== 三 ==============================
h(doc, "三、帧头参数", 1)
table(doc, ["项目", "范围", "在帧里的位置", "默认值", "说明"],
      [["航天器 ID (SCID)", "0 ~ 1023", "主头第 1~2 字节高 10 位", "42",
        "标识这条遥测链路属于哪个航天器"],
       ["虚拟信道 (VCID)", "0 ~ 7", "主头第 2 字节低 3 位", "0",
        "区分不同来源 / 优先级的遥测数据"],
       ["帧计数 (VCFC)", "0 ~ 255", "主头第 4 字节", "0",
        "该虚拟信道已发帧数，地面靠它发现丢帧 / 重复帧。可勾选『每发一帧自动+1』"]],
      widths=[3.0, 1.8, 3.6, 1.5, 5.0])

# ============================== 四 ==============================
h(doc, "四、三种通信方式", 1)
table(doc, ["模式", "数据怎么走", "要什么硬件", "当前状态"],
      [["A. 纯软件环回",
        "参数表 -> 组帧 -> 随机化 -> 卷积编码 -> 加 ASM -> BPSK -> 【数字信道】"
        " -> 解调 -> 译码 -> 解析参数表",
        "什么都不用接", "可用（演示首选）"],
       ["B. 经板子 USB/IIO",
        "PC 组包 -> 遥测板发射 -> 环回 -> 遥测板接收 -> PC 解出参数表",
        "遥测板跑原厂固件 + 板子在线（RNDIS/SSH）",
        "已实测通过"],
       ["C. 经 FPGA",
        "遥测板 FPGA 自己做 CCSDS 编码调制与解调译码",
        "遥测板 + 我们自己的位流（JTAG 烧写）",
        "链路已验证（用 ILA 演示）"]],
      widths=[2.8, 6.2, 4.0, 2.8])

para(doc, "信道条件（只在模式 A 生效）：", bold=True)
table(doc, ["参数", "取值", "含义", "演示建议"],
      [["SNR(dB)", "留空 / 0~30", "留空=不加噪声；填数值=按该信噪比加高斯白噪声",
        "先用留空演示『能通』，再填 10 演示抗噪"],
       ["频偏(Hz)", "任意（例 3000）", "给接收信号叠加载波频偏", "填 3000 演示抗频偏"]],
      widths=[2.5, 2.5, 6.5, 4.3])

# ============================== 五 ==============================
h(doc, "五、演示步骤", 1)
for k, v in [
    ("准备", "双击 演示工具.bat；通信方式保持默认的 A（纯软件环回）"),
    ("第 1 步", "在参数表里改几个值 —— 比如把『母线电压』从 2850 改成 2900、"
                "『功放温度』从 420 改成 455（右边『工程值』实时变成 29.00 V / 45.5 度）"),
    ("第 2 步", "点【生成并发送】"),
    ("第 3 步", "指中间区域：这是软件按 CCSDS 131.0-B 组出来的包 ——\n"
                "          6 字节主头 + 32 字节数据域（16 个遥测参数）+ 2 字节 FECF = 40 字节；\n"
                "          每个参数在数据域里的偏移和字节顺序都列出来了"),
    ("第 4 步", "指下面绿色大字：接收参数与发送完全一致 ——\n"
                "          接收端把 32 字节数据域按同一张参数表解析回 16 个工程值，"
                "逐个比对全部一致，CRC 通过"),
    ("第 5 步", "（可选）SNR 填 10 再点一次 -> 仍然一致，说明链路抗噪"),
    ("第 6 步", "（可选）连点几次【生成并发送】-> 帧计数自动 +1、时间戳递增，演示连续组帧"),
    ("第 7 步", "（进阶）切到 B 模式 -> 真的过一遍遥测板的射频前端"),
]:
    p = doc.add_paragraph(style="List Bullet")
    r = p.add_run("%s：" % k)
    r.bold = True
    cn(r)
    cn(p.add_run(v))

# ============================== 六 ==============================
doc.add_page_break()
h(doc, "六、硬件连接（做 B / C 模式时看）", 1)

h(doc, "6.1 模式 B 需要什么", 2)
table(doc, ["项目", "要求", "怎么确认"],
      [["遥测板在线", "跑原厂固件（拔插即恢复）",
        "Get-PnpDevice -PresentOnly | Where InstanceId -match 'VID_0456'；ping 192.168.2.1"],
       ["SSH 可用", "plink + 口令 analog（板子不认我们的密钥）",
        "tools\\board_ssh2.ps1 -Cmd \"uname -a\""],
       ["TX/RX 本振同频", "实测本板都是 2400 MHz",
        "iio_attr -u ip:localhost -c ad9361-phy altvoltage0 frequency（RX）\n"
        "iio_attr -u ip:localhost -c ad9361-phy altvoltage1 frequency（TX）"],
       ["射频通路", "不接线也能通（芯片内部 TX->RX 泄漏，见 6.3）；"
                    "要演示『真的发出去』就接 SMA 线 TX1A->RX1A",
        "tools\\verify_leakage.py"]],
      widths=[2.8, 6.0, 6.5])

h(doc, "6.2 接 CMU200 看频谱", 2)
para(doc, "射频中心频率 = 板子本振 + 基带中频偏移：", bold=True)
mono(doc,
     "TX 本振      = 2400 MHz\n"
     "基带中频偏移 = 200 kHz   （cadu_to_iq 的 if_hz）\n"
     "=> 射频中心   = 2400.200 MHz\n"
     "   占用带宽   = 250 ksym/s x (1 + 0.35) = 338 kHz\n"
     "\n"
     "CMU200 设置：\n"
     "   Center Frequency : 2400.200 MHz\n"
     "   Span             : 1 MHz\n"
     "   Reference Level  : -30 dBm  （TX 衰减 40 dB 时输出约 -33 dBm）\n"
     "   接板子的 TX1A（SMA 线）")
para(doc, "注意：CMU200 的频率上限取决于选件（常见 2.2 GHz 或 2.7 GHz）。"
          "如果上不到 2400 MHz，把板子本振改低：", bold=True)
mono(doc,
     "iio_attr -u ip:localhost -c ad9361-phy altvoltage1 frequency 1000000000\n"
     "=> 射频中心 = 1000.200 MHz")
para(doc, "注意：CMU200 只能看频谱，它不认 CCSDS 调制，做不了误码率测量。")

h(doc, "6.3 一个必须知道的现象：TX 和 RX 不接线也能通", 2)
para(doc, "实测：TX1A 和 RX1A 之间没有任何连接，B 模式仍然能零误码解出参数。"
          "原因是 AD9361 同一颗芯片内部 / PCB 的 TX->RX 泄漏。已用实验证明这是真实射频通路：",
     bold=True)
mono(doc,
     "A) TX 静默（DDS scale=0）       峰值     +0 Hz     峰/底 17.4 dB\n"
     "B) TX 出 1 MHz 单音（TXLO 2400） 峰值 +1001250 Hz  峰/底 42.6 dB\n"
     "C) TX 本振挪到 2401 MHz          峰值 +1998750 Hz  峰/底 22.3 dB\n"
     "\n"
     "B -> C 峰位差 = +997500 Hz = +1 MHz\n"
     "只动 TX 本振，接收峰就跟着挪 -> 信号真的走了\n"
     "  TX 基带 -> TX 本振上变频 -> 射频 -> RX 本振下变频 -> RX 基带\n"
     "数字串扰不会受本振影响，所以这一条排除了数字串扰的可能。")
para(doc, "对演示的意义：", bold=True)
para(doc, "· 不接 SMA 线：靠芯片内部泄漏自环，演示照常能做（本次零误码实测通过）")
para(doc, "· 接 SMA 线 TX1A->RX1A：是真正『出 SMA 口再回来』，演示更有说服力")
para(doc, "· 接转发板 / CMU200 / 频谱仪：必须接线，信号必须走出 SMA 口")

h(doc, "6.4 模式 C 怎么演示", 2)
mono(doc,
     "1. 板子停在 u-boot：  tools\\uboot_stop.ps1\n"
     "   （或断电重插，在串口出现 Pluto> 时按一下打断）\n"
     "   必须先停 u-boot：Linux 一跑，ADI 驱动会去访问纯 PL 设计里不存在的\n"
     "   AXI 地址 -> 挂死 -> Zynq 看门狗 10 秒复位整板 -> 位流和 ILA 一起被冲掉\n"
     "\n"
     "2. 烧写 + 抓取：\n"
     "     vivado -mode batch -source ccsds_pl\\program_and_base.tcl\n"
     "\n"
     "3. 在 ILA 里看（12 个探针）：\n"
     "     frame_match   = 1        40 字节与期望帧全部相等\n"
     "     rx_crc_ok     = 1        CRC 通过\n"
     "     rx_err_cnt    ~ 0        零误码\n"
     "     rx_frame_idx  = 0x28=40  收到整整 40 字节\n"
     "     rx_frame_byte = 0x63     期望帧的最后一字节\n"
     "\n"
     "4. 恢复原厂：Pluto> 敲 boot，或断电重插")
para(doc, "注意：模式 C 目前是『板上自带固定帧的自环链路』，PC 不下发参数。"
          "要做到『电脑填参数给 FPGA』，需要再给 FPGA 加一条串口注入通路。", bold=True)

# ============================== 七 ==============================
doc.add_page_break()
h(doc, "七、常见问题", 1)
faq = [
    ("双击 .bat 报『不是内部或外部命令』",
     ".bat 带了 UTF-8 BOM 或用了 LF 换行。cmd.exe 只认【纯 ASCII + CRLF】，"
     "中文注释也会出问题。本工程的 .bat 已按此格式重写。"),
    ("界面里为什么没有可以随便输入文本的地方",
     "设计如此。遥测发的是固定格式的参数表，只允许改数值。"
     "想发任意内容是上行数据注入，不属于遥测。"),
    ("某个参数的数值填了但一发就变了",
     "做了范围校验：超出该参数允许范围的输入会被夹到边界值。"
     "表格里的『允许范围』列就是界限。"),
    ("点了 B 模式弹出错误",
     "排查顺序：ping 192.168.2.1；板子本振是否同频；"
     "tools\\verify_leakage.py 看射频通路；tools\\tx_path_probe.py 看 TX 是否出信号。"),
    ("B 模式解不出帧 / 有误码",
     "先确认 TX 衰减与 RX 增益（默认 40 dB / 30 dB 已实测可用）。"
     "数据域固定 32 字节，短帧会因 Viterbi 尾比特余量不足差 1 bit，所以不要改帧长。"),
    ("板子三个灯常亮、看不到 Pluto 的 U 盘",
     "说明板子停在 u-boot（不是故障）。这是烧写自定义位流 + 抓 ILA 必需的状态。"
     "恢复原厂：Pluto> 敲 boot，或断电重插。"),
    ("怎么确认板子在不在",
     "Get-PnpDevice -PresentOnly | Where InstanceId -match 'VID_0403'（JTAG 口）"
     "和 'VID_0456'（OTG 口 gadget）。必须带 -PresentOnly，"
     "否则会读到 Windows 缓存的历史设备而误判。"),
]
for q, a in faq:
    p = doc.add_paragraph(style="List Bullet")
    r = p.add_run("问：" + q)
    r.bold = True
    cn(r)
    p2 = doc.add_paragraph()
    p2.paragraph_format.left_indent = Cm(0.8)
    cn(p2.add_run("答：" + a))

# ============================== 附 ==============================
h(doc, "附录：一帧遥测帧的构成", 1)
mono(doc,
     "偏移  长度  内容\n"
     "----  ----  --------------------------------------------------\n"
     " 0     2    主头：SCID(10b) + VCID(3b) + 保留 + 帧类型 + 版本\n"
     " 2     2    主头：帧计数(8b) + 状态字\n"
     " 4     2    主头：数据域长度等\n"
     " 6    32    数据域 = 16 个 16 位遥测参数（小端）\n"
     "38     2    FECF：CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF, MSB first)\n"
     "----  ----  --------------------------------------------------\n"
     "合计 40 字节 / 320 bit\n"
     "\n"
     "再往下：\n"
     "  随机化（LFSR x^8+x^7+x^5+x^3+1，种子 0xFF）\n"
     "  卷积编码 1/2（K=7，G1=1111001，G2=1011011，第二路取反） -> 640 bit\n"
     "  前置 ASM 同步字 0x1ACFFC1D（4 字节）                       -> 672 bit CADU\n"
     "  BPSK 调制 + SRRC 成形（beta=0.35，过采样 10）")

doc.save(OUT)
print("  已生成: %s (%d B)" % (OUT, os.path.getsize(OUT)))
