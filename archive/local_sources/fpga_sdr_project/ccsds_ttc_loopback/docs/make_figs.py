#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_figs.py -- 用 PIL 画报告用的框图（中文字体）

生成：
  fig1_6g.png        6G 全域覆盖网络总体框图（空天地一体化）
  fig2_payload.png   卫星载荷框图，标出本课题所在位置
  fig3_compare.png   与 4G/5G 的相同点 / 不同点
  fig4_chain.png     本课题的信号链路（发射链 + 接收链）
  fig5_fpga.png      为什么必须用 FPGA（实时性/确定性对比）
"""
import os
from PIL import Image, ImageDraw, ImageFont

OUT = r"E:\fpga_sdr_project\ccsds_ttc_loopback\docs\figs"
os.makedirs(OUT, exist_ok=True)

F_REG = r"C:\Windows\Fonts\msyh.ttc"
F_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
F_MONO = r"C:\Windows\Fonts\consola.ttf"

_cache = {}


def font(size, bold=False, mono=False):
    key = (size, bold, mono)
    if key not in _cache:
        path = F_MONO if mono else (F_BOLD if bold else F_REG)
        _cache[key] = ImageFont.truetype(path, size)
    return _cache[key]


# 配色
C_BG = (255, 255, 255)
C_SPACE = (232, 241, 252)      # 空间段
C_GROUND = (236, 249, 238)     # 地面段
C_USER = (255, 246, 232)       # 用户段
C_MINE = (255, 226, 226)       # 本课题（高亮）
C_SAME = (224, 245, 224)       # 相同
C_DIFF = (255, 235, 205)       # 不同
C_BOX = (255, 255, 255)
C_LINE = (90, 90, 90)
C_TXT = (30, 30, 30)
C_ACC = (200, 40, 40)
C_BLUE = (30, 80, 160)


class Fig:
    def __init__(self, w, h, bg=C_BG):
        self.im = Image.new("RGB", (w, h), bg)
        self.d = ImageDraw.Draw(self.im)
        self.w, self.h = w, h

    # ---- 基本图元 ----
    def rbox(self, x, y, w, h, text="", fill=C_BOX, outline=C_LINE, width=2,
             size=18, bold=False, tcolor=C_TXT, radius=10, lines=None):
        self.d.rounded_rectangle([x, y, x + w, y + h], radius=radius,
                                 fill=fill, outline=outline, width=width)
        if lines is None:
            lines = [text] if text else []
        if not lines:
            return
        f = font(size, bold)
        lh = size + 6
        total = lh * len(lines) - 6
        cy = y + (h - total) / 2
        for i, ln in enumerate(lines):
            bb = self.d.textbbox((0, 0), ln, font=f)
            tw = bb[2] - bb[0]
            self.d.text((x + (w - tw) / 2, cy + i * lh), ln, font=f, fill=tcolor)

    def arrow(self, x1, y1, x2, y2, color=C_LINE, width=2, label=None,
              lsize=14, dash=False, lcolor=None, loff=(0, -16)):
        if dash:
            self._dash(x1, y1, x2, y2, color, width)
        else:
            self.d.line([x1, y1, x2, y2], fill=color, width=width)
        # 箭头
        import math
        ang = math.atan2(y2 - y1, x2 - x1)
        L = 11
        for s in (+1, -1):
            a = ang + s * 0.42
            self.d.line([x2, y2, x2 - L * math.cos(a), y2 - L * math.sin(a)],
                        fill=color, width=width)
        if label:
            f = font(lsize)
            bb = self.d.textbbox((0, 0), label, font=f)
            tw, th = bb[2] - bb[0], bb[3] - bb[1]
            mx, my = (x1 + x2) / 2 + loff[0], (y1 + y2) / 2 + loff[1]
            self.d.rectangle([mx - 3, my - 2, mx + tw + 3, my + th + 6], fill=C_BG)
            self.d.text((mx, my), label, font=f, fill=(lcolor or color))

    def _dash(self, x1, y1, x2, y2, color, width, dash=9, gap=7):
        import math
        L = math.hypot(x2 - x1, y2 - y1)
        if L == 0:
            return
        n = int(L / (dash + gap)) + 1
        for i in range(n):
            t0 = i * (dash + gap) / L
            t1 = min(1.0, (i * (dash + gap) + dash) / L)
            if t0 > 1:
                break
            self.d.line([x1 + (x2 - x1) * t0, y1 + (y2 - y1) * t0,
                         x1 + (x2 - x1) * t1, y1 + (y2 - y1) * t1],
                        fill=color, width=width)

    def text(self, x, y, s, size=18, bold=False, color=C_TXT, anchor="lt", mono=False):
        self.d.text((x, y), s, font=font(size, bold, mono), fill=color, anchor=anchor)

    def band(self, x, y, w, h, title, fill, outline=None, tsize=17):
        self.d.rounded_rectangle([x, y, x + w, y + h], radius=6, fill=fill,
                                 outline=outline or (200, 200, 200), width=1)
        self.text(x + 10, y + 8, title, tsize, True, (70, 70, 70))

    def save(self, name):
        p = os.path.join(OUT, name)
        self.im.save(p, "PNG")
        print("  已生成 %s  (%dx%d)" % (name, self.w, self.h))
        return p


# ===========================================================================
# 图 1：6G 全域覆盖网络
# ===========================================================================
def fig1():
    f = Fig(1180, 880)
    f.text(590, 22, "图 1  6G 全域覆盖网络（空天地一体化 SAGIN）", 26, True,
           C_BLUE, anchor="mt")

    # ---- 空间段 ----
    f.band(40, 80, 840, 250, "空间段  Space Segment", C_SPACE)
    sat = [("GEO 静止轨道卫星", ["骨干回传 / 广播", "覆盖恒定，时延大"], 70),
           ("LEO 低轨星座", ["接入覆盖主力", "低时延、多普勒大"], 340),
           ("HAPS 高空平台", ["区域补盲", "20 km 驻空"], 610)]
    for name, sub, x in sat:
        fill = C_MINE if "LEO" in name else C_BOX
        f.rbox(x, 120, 200, 96, lines=[name] + sub, fill=fill,
               outline=C_ACC if "LEO" in name else C_LINE,
               width=3 if "LEO" in name else 2, size=16, bold=True)
    # 星间链路
    f.arrow(270, 168, 340, 168, C_BLUE, 2, "ISL", 13, loff=(0, -20))
    f.arrow(540, 168, 610, 168, C_BLUE, 2, "ISL", 13, loff=(0, -20))
    f.text(70, 232, "★ 星上载荷：本课题所在位置（LEO 接入节点）", 16, True, C_ACC)
    f.text(70, 256, "   星间链路 ISL：卫星之间组网，实现全球一张网", 14, False, (90, 90, 90))

    # ---- 星地链路 ----
    f.band(40, 350, 840, 78, "星地链路", (250, 244, 235))
    f.text(70, 382, "馈电链路 Feeder Link（信关站 → 卫星）        用户链路 Service Link（卫星 → 终端）",
           16, True, (120, 80, 30))
    for x in (170, 440, 710):
        f.arrow(x, 330, x, 350, (120, 80, 30), 2)
        f.arrow(x, 428, x, 448, (120, 80, 30), 2)

    # ---- 地面段 ----
    f.band(40, 448, 840, 150, "地面段  Ground Segment", C_GROUND)
    ground = [("信关站 Gateway", ["馈电 / 星地网关"], 70),
              ("6G 核心网", ["SBA / 云原生", "统一管理天地接入"], 340),
              ("地面蜂窝网", ["5G/6G TN", "与卫星互补覆盖"], 610)]
    for name, sub, x in ground:
        f.rbox(x, 484, 200, 92, lines=[name] + sub, fill=C_BOX, size=16, bold=True)
    f.arrow(270, 530, 340, 530, C_LINE, 2)
    f.arrow(540, 530, 610, 530, C_LINE, 2)

    # ---- 用户段 ----
    f.band(40, 618, 840, 96, "用户段", C_USER)
    f.rbox(70, 652, 740, 46,
           lines=["手机 / 物联网终端 / 车联网 / 机载 / 船载 / 应急通信"],
           fill=C_BOX, size=17, bold=True)
    f.arrow(440, 598, 440, 618, C_LINE, 2)

    # ---- 右侧说明 ----
    f.rbox(900, 80, 240, 634, fill=(250, 250, 250), outline=(200, 200, 200), width=1)
    f.text(1020, 96, "6G 与 4G/5G 的根本差别", 17, True, C_BLUE, anchor="mt")
    notes = [
        ("4G / 5G", "纯地面蜂窝"),
        ("", "覆盖约 20% 陆地面积"),
        ("", "海洋/荒漠/极地无覆盖"),
        ("", ""),
        ("6G", "空天地一体化"),
        ("", "卫星是网络一级公民"),
        ("", "全球 100% 无缝覆盖"),
        ("", ""),
        ("本课题", "星上测控与转发载荷"),
        ("", "决定卫星能否"),
        ("", "自主完成协议处理"),
    ]
    y = 134
    for a, b in notes:
        if a:
            f.text(912, y, a, 15, True, C_ACC if a == "本课题" else C_BLUE)
            y += 22
        if b:
            f.text(912, y, b, 14, False, (60, 60, 60))
            y += 20
    f.rbox(900, 730, 240, 120, lines=["", "天基接入 + 地面蜂窝", "统一协议、统一核心网",
                                      "→ 一张网覆盖全球"],
           fill=(235, 245, 255), outline=C_BLUE, width=2, size=15)
    return f.save("fig1_6g.png")


# ===========================================================================
# 图 2：卫星载荷框图（本课题位置）
# ===========================================================================
def fig2():
    f = Fig(1180, 760)
    f.text(590, 20, "图 2  卫星载荷框图 —— 本课题所在层级", 25, True, C_BLUE, anchor="mt")

    # 卫星外框
    f.d.rounded_rectangle([40, 66, 1140, 700], radius=14, fill=(247, 250, 255),
                          outline=C_BLUE, width=3)
    f.text(60, 78, "卫星（6G LEO 接入节点，再生式载荷）", 19, True, C_BLUE)

    # 平台分系统
    f.rbox(66, 112, 220, 250, fill=C_BOX, outline=C_LINE, width=2)
    f.text(176, 122, "平台分系统", 17, True, C_TXT, anchor="mt")
    for i, t in enumerate(["· 姿态与轨道控制", "· 电源 / 蓄电池", "· 热控", "· 星务管理（数管）",
                           "· 测控应答机（传统弯管）"]):
        f.text(80, 156 + i * 34, t, 14)

    # 载荷分系统
    f.d.rounded_rectangle([310, 112, 1116, 676], radius=10, fill=(255, 252, 246),
                          outline=(180, 140, 80), width=2)
    f.text(713, 122, "载荷分系统  Payload", 17, True, (140, 100, 40), anchor="mt")

    # 本课题高亮框
    f.d.rounded_rectangle([336, 156, 1090, 620], radius=10, fill=C_MINE,
                          outline=C_ACC, width=4)
    f.text(713, 166, "★ 测控与转发单元（本课题）", 19, True, C_ACC, anchor="mt")

    # 接收通路
    f.rbox(366, 206, 700, 54, lines=["接收天线 → 低噪放 LNA → 下变频 → ADC"],
           fill=C_BOX, outline=C_LINE, size=16, bold=True)
    f.arrow(716, 260, 716, 282, C_LINE, 2)

    # FPGA 核心
    f.rbox(366, 282, 700, 116, fill=(225, 238, 255), outline=C_BLUE, width=3)
    f.text(716, 292, "FPGA 基带处理（可编程逻辑 PL）", 18, True, C_BLUE, anchor="mt")
    for i, t in enumerate(["匹配滤波 → 帧同步（ASM）→ 译码 → 解随机化 → CRC",
                           "→ 解析出转发控制参数（目标频段 / 带宽 / 增益…）"]):
        f.text(716, 324 + i * 30, t, 15, anchor="mt")
    f.arrow(716, 398, 716, 420, C_LINE, 2)

    # 参数转发
    f.rbox(366, 420, 340, 62, lines=["参数下发", "（以太网 → 转发板）"],
           fill=C_BOX, outline=C_LINE, size=15, bold=True)
    f.rbox(726, 420, 340, 62, lines=["转发控制", "（目标频段/带宽/增益）"],
           fill=C_BOX, outline=C_LINE, size=15, bold=True)
    f.arrow(706, 451, 726, 451, C_LINE, 2)
    f.arrow(896, 482, 896, 512, C_LINE, 2)

    # 发射通路
    f.rbox(366, 512, 700, 54,
           lines=["DAC → 上变频 → 功率放大器 PA → 发射天线"],
           fill=C_BOX, outline=C_LINE, size=16, bold=True)
    f.text(716, 578, "（可编程逻辑同时完成 CCSDS 编码与 BPSK/SRRC 调制）", 14, False, (90, 90, 90),
           anchor="mt")

    # 右侧标注
    f.rbox(60, 400, 226, 280, fill=(250, 250, 250), outline=(200, 200, 200), width=1)
    f.text(173, 412, "本课题的边界", 16, True, C_ACC, anchor="mt")
    for i, t in enumerate(["· 射频前端由 AD9361", "  完成（数模转换+变频）", "",
                           "· 协议与基带处理", "  全部在 FPGA 内实现", "",
                           "· 输出：转发控制参数", "  （交给转发板执行）"]):
        f.text(72, 446 + i * 26, t, 13)
    return f.save("fig2_payload.png")


# ===========================================================================
# 图 3：与 4G/5G 的相同点 / 不同点
# ===========================================================================
def fig3():
    f = Fig(1180, 860)
    f.text(590, 20, "图 3  6G 卫星链路 与 4G/5G 地面蜂窝：相同点与不同点", 24, True,
           C_BLUE, anchor="mt")

    # 两列
    f.rbox(60, 70, 480, 200, fill=C_BOX, outline=C_LINE, width=2)
    f.text(300, 82, "4G / 5G  地面蜂窝", 19, True, (60, 60, 60), anchor="mt")
    for i, t in enumerate(["· 基站 gNB/eNB", "· 核心网 EPC / 5GC",
                           "· 用户终端 UE", "· 纯地面覆盖，无卫星"])    :
        f.text(84, 116 + i * 30, t, 15)

    f.rbox(640, 70, 480, 200, fill=C_BOX, outline=C_BLUE, width=2)
    f.text(880, 82, "6G  空天地一体化", 19, True, C_BLUE, anchor="mt")
    for i, t in enumerate(["· 地面基站 + 卫星 + HAPS", "· 6G 核心网（云原生/SBA）",
                           "· 含直连卫星的终端", "· 全球无缝覆盖"])    :
        f.text(664, 116 + i * 30, t, 15)

    # 相同
    f.rbox(60, 300, 1060, 220, fill=C_SAME, outline=(90, 160, 90), width=3)
    f.text(80, 312, "● 相同部分（通用的通信系统技术，本课题同样用到）", 18, True,
           (30, 120, 30))
    same = [
        "射频前端：天线 / 低噪放 / 变频 / ADC / DAC",
        "基带基本数学：成形滤波、匹配滤波、符号定时、同步",
        "信道编码：纠错码的编码与译码（本课题用卷积码 + Viterbi）",
        "数据链路：帧结构、CRC 校验、数据随机化、帧同步",
        "网络与传输：以太网承载、参数配置与管理",
    ]
    for i, t in enumerate(same):
        f.text(84, 350 + i * 32, "· " + t, 15)

    # 不同
    f.rbox(60, 546, 1060, 290, fill=C_DIFF, outline=(200, 130, 40), width=3)
    f.text(80, 558, "● 不同部分（航天/星上特有的约束，决定本课题的实现方式）", 18, True,
           (170, 90, 10))
    rows = [
        ("协议栈", "CCSDS 航天标准（131.0-B）", "3GPP 地面蜂窝标准"),
        ("波形", "单载波 + SRRC 成形，PAPR 低", "OFDM，PAPR 高（8~10 dB）"),
        ("编码", "卷积码 + Viterbi（时延小）", "LDPC / Polar（性能强、复杂度高）"),
        ("帧同步", "ASM 硬同步字 0x1ACFFC1D", "PSS / SSS 相关同步"),
        ("星上处理", "再生式：解调-再调制", "卫星多为弯管透明转发"),
        ("信噪条件", "功率受限，需低 PAPR 高效率", "市电供电，功率不受限"),
        ("时延/多普勒", "RTT 大（10~600 ms）、多普勒大", "毫秒级、多普勒小"),
    ]
    y = 592
    f.text(90, y, "维度", 15, True, (120, 60, 0))
    f.text(220, y, "6G 卫星链路（本课题）", 15, True, (120, 60, 0))
    f.text(680, y, "4G / 5G 地面蜂窝", 15, True, (120, 60, 0))
    y += 26
    f.d.line([80, y - 6, 1100, y - 6], fill=(180, 140, 100), width=1)
    for a, b, c in rows:
        f.text(90, y, a, 14, True)
        f.text(220, y, b, 14)
        f.text(680, y, c, 14)
        y += 27
    return f.save("fig3_compare.png")


# ===========================================================================
# 图 4：本课题信号链路
# ===========================================================================
def fig4():
    f = Fig(1180, 700)
    f.text(590, 18, "图 4  本课题的 CCSDS 信号链路（全部实现在 FPGA 可编程逻辑内）", 23, True,
           C_BLUE, anchor="mt")

    # 发射链
    f.band(40, 66, 1100, 240, "发射链（TX）", (232, 241, 252))
    tx = ["帧组装\n40 字节", "CRC-16\nFECF", "加扰\nLFSR", "卷积编码\n1/2 K=7",
          "加同步字\nASM 4B", "BPSK\n映射", "1:10\n插零", "SRRC 成形\n61 抽头"]
    x, w, y, hh = 58, 114, 110, 86
    for i, t in enumerate(tx):
        parts = t.split("\n")
        f.rbox(x, y, w, hh, lines=parts, fill=C_BOX, outline=C_LINE, size=13, bold=True)
        if i < len(tx) - 1:
            f.arrow(x + w, y + hh / 2, x + w + 16, y + hh / 2, C_LINE, 2)
        x += w + 16
    f.text(60, 212, "输出：BPSK 基带波形（30.72 MSPS）→ AD9361 DAC → 上变频 → 天线",
           15, False, (60, 60, 60))
    f.text(60, 240, "关键点：整条链在 1 个采样周期（约 32.5 ns）内必须推进完一级 —— 软件做不到",
           15, True, C_ACC)
    f.text(60, 266, "运算量：SRRC 61 抽头 × 30.72 MSPS ≈ 1.87 G 次乘加/秒",
           15, True, C_ACC)

    # 接收链
    f.band(40, 330, 1100, 250, "接收链（RX）", (236, 249, 238))
    rx = ["匹配滤波\nSRRC", "硬判决\n取符号位", "帧同步\n10 相位并行", "译码\nViterbi",
          "解扰\nLFSR", "CRC\n校验", "参数解析\n16 参数"]
    x, w, y, hh = 58, 132, 374, 86
    for i, t in enumerate(rx):
        parts = t.split("\n")
        fill = (255, 226, 226) if "10 相位" in t else C_BOX
        f.rbox(x, y, w, hh, lines=parts, fill=fill,
               outline=C_ACC if "10 相位" in t else C_LINE,
               width=3 if "10 相位" in t else 2, size=13, bold=True)
        if i < len(rx) - 1:
            f.arrow(x + w, y + hh / 2, x + w + 18, y + hh / 2, C_LINE, 2)
        x += w + 18
    f.text(60, 476, "输入：AD9361 ADC → 下变频 的数字基带", 15, False, (60, 60, 60))
    f.text(60, 502, "关键点：10 个抽取相位各跑一路 ASM 搜索并行比对，先命中者锁定 —— "
                    "摆脱对相位标定的依赖", 15, True, C_ACC)
    f.text(60, 528, "输出：16 个转发控制参数（目标频段/带宽/增益…），附 CRC 校验结果",
           15, False, (60, 60, 60))

    # 底部说明
    f.rbox(40, 600, 1100, 78, fill=(250, 250, 250), outline=(200, 200, 200), width=1)
    f.text(60, 612, "验证结果：板上 ILA 实测 frame_match = 1、rx_crc_ok = 1、"
                    "rx_err_cnt ≈ 0；仿真 10 个抽取相位全部 PASS", 15, True, (30, 110, 30))
    f.text(60, 640, "同一份 RTL 既用于发射也用于接收，SRRC 实体共用（SRRC × SRRC = 升余弦，"
                    "符号点无码间干扰）", 14, False, (70, 70, 70))
    return f.save("fig4_chain.png")


# ===========================================================================
# 图 5：为什么必须用 FPGA
# ===========================================================================
def fig5():
    f = Fig(1180, 740)
    f.text(590, 18, "图 5  为什么必须是 FPGA：软件实现与硬件实现的本质差别", 23, True,
           C_BLUE, anchor="mt")

    # 左：软件
    f.rbox(50, 70, 500, 480, fill=(250, 246, 246), outline=(180, 120, 120), width=2)
    f.text(300, 84, "软件实现（ARM / PC）", 19, True, (150, 60, 60), anchor="mt")
    for i, t in enumerate([
        "串行执行：一个样点算完才算下一个",
        "",
        "30.72 MSPS 下每个样点只有 32.5 ns",
        "需要数十 GOPS —— 差两个数量级",
        "",
        "定时来自：中断响应 + 任务调度 + 缓存",
        "→ 抖动微秒级、不可预测",
        "",
        "延迟：数据要经内存搬运",
        "→ 毫秒级且不确定",
        "",
        "必须外接 PC，脱机即失效",
    ]):
        f.text(72, 124 + i * 30, t, 14, i in (2, 5, 8, 11))

    # 右：FPGA
    f.rbox(630, 70, 500, 480, fill=(240, 250, 242), outline=(90, 160, 90), width=2)
    f.text(880, 84, "FPGA 实现（可编程逻辑）", 19, True, (30, 120, 30), anchor="mt")
    for i, t in enumerate([
        "并行执行：61 个乘法器同时工作",
        "",
        "一个时钟出结果，全速实时",
        "30.72 MSPS 连续处理，收发并行",
        "",
        "定时来自：时钟周期计数",
        "→ 抖动为整数个时钟周期，完全确定",
        "",
        "延迟：PL 内部仅几十个时钟周期",
        "→ 恒定且可测",
        "",
        "单板自主运行，脱机可用",
    ]):
        f.text(652, 124 + i * 30, t, 14, i in (2, 5, 8, 11))

    # 中间箭头
    f.arrow(570, 310, 610, 310, C_ACC, 4)

    # 结论
    f.rbox(50, 578, 1080, 76, fill=(255, 235, 205), outline=(200, 130, 40), width=3)
    f.text(590, 592, "结论：AD9361 只负责数模转换与变频；决定『这是不是 CCSDS 载荷』的"
                     "调制解调器，全部在 FPGA 里。",
           16, True, (150, 80, 10), anchor="mt")
    f.text(590, 620, "没有 FPGA，这块板子只是通用 SDR；有了 FPGA，它才是测控载荷。",
           16, True, C_ACC, anchor="mt")
    return f.save("fig5_fpga.png")


if __name__ == "__main__":
    print("  生成框图到 %s" % OUT)
    fig1()
    fig2()
    fig3()
    fig4()
    fig5()
