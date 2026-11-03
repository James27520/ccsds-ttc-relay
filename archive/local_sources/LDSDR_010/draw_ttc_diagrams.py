#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""draw_ttc_diagrams.py -- 用 PIL 画遥控遥测系统的架构图与流程图"""
import os

from PIL import Image, ImageDraw, ImageFont

HEI = r"C:\Windows\Fonts\simhei.ttf"
YAHEI = r"C:\Windows\Fonts\msyh.ttc"
OUT = r"E:\fpga_sdr_project\figs"
os.makedirs(OUT, exist_ok=True)

BG = (255, 255, 255)
INK = (30, 40, 60)
GRAY = (110, 120, 135)
BLUE = (31, 78, 160)
LBLUE = (226, 236, 250)
GREEN = (22, 130, 80)
LGREEN = (223, 243, 232)
ORANGE = (200, 100, 20)
LORANGE = (253, 236, 218)
RED = (185, 40, 40)
LRED = (253, 228, 228)
PURPLE = (110, 60, 160)
LPURPLE = (238, 230, 250)
LINE = (70, 80, 100)


def F(sz, bold=False):
    try:
        return ImageFont.truetype(YAHEI if not bold else HEI, sz)
    except Exception:
        return ImageFont.truetype(HEI, sz)


def box(d, x, y, w, h, text, fill=LBLUE, edge=BLUE, fs=20, bold=True,
        radius=8, lw=2, tc=None):
    d.rounded_rectangle([x, y, x + w, y + h], radius=radius, fill=fill,
                        outline=edge, width=lw)
    f = F(fs, bold)
    lines = text.split("\n")
    lh = fs + 6
    ty = y + (h - lh * len(lines)) / 2
    for i, ln in enumerate(lines):
        bb = d.textbbox((0, 0), ln, font=f)
        d.text((x + (w - (bb[2] - bb[0])) / 2, ty + i * lh), ln,
               font=f, fill=tc or INK)


def arrow(d, x1, y1, x2, y2, color=LINE, lw=3, dash=False, label=None,
          lfs=15, lcolor=None, lpos=0.5, lside="r"):
    if dash:
        # 手绘虚线
        import math
        L = math.hypot(x2 - x1, y2 - y1)
        n = max(1, int(L / 14))
        for i in range(n):
            if i % 2:
                continue
            t0, t1 = i / n, min((i + 0.6) / n, 1.0)
            d.line([x1 + (x2 - x1) * t0, y1 + (y2 - y1) * t0,
                    x1 + (x2 - x1) * t1, y1 + (y2 - y1) * t1],
                   fill=color, width=lw)
    else:
        d.line([x1, y1, x2, y2], fill=color, width=lw)
    # 箭头
    import math
    a = math.atan2(y2 - y1, x2 - x1)
    s = 12
    d.polygon([(x2, y2),
               (x2 - s * math.cos(a - 0.42), y2 - s * math.sin(a - 0.42)),
               (x2 - s * math.cos(a + 0.42), y2 - s * math.sin(a + 0.42))],
              fill=color)
    if label:
        f = F(lfs)
        bb = d.textbbox((0, 0), label, font=f)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        mx, my = x1 + (x2 - x1) * lpos, y1 + (y2 - y1) * lpos
        ox = 8 if lside == "r" else -tw - 8
        oy = -th / 2 - 2
        d.rectangle([mx + ox - 3, my + oy - 2, mx + ox + tw + 3, my + oy + th + 4],
                    fill=BG)
        d.text((mx + ox, my + oy), label, font=f, fill=lcolor or GRAY)


# =====================================================================
# 图 1：系统架构与供电
# =====================================================================
def fig1():
    W, H = 1500, 1000
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)

    d.text((40, 28), "图 1  遥控遥测系统架构（调整后：独立供电 + 以太网数据）",
           font=F(28, True), fill=INK)
    d.line([40, 70, W - 40, 70], fill=(200, 205, 215), width=2)

    # 交换机
    box(d, 480, 100, 540, 74, "千兆交换机   192.168.10.0/24",
        fill=LPURPLE, edge=PURPLE, fs=23)

    # 三块板
    bx = [90, 590, 1090]
    y = 250
    names = ["RK3588\n星上处理\n192.168.10.2",
             "遥测板  7010_AD9363\n测控收发\n192.168.10.3",
             "转发板  LDSDR\n弯管转发\n192.168.10.1"]
    fills = [LBLUE, LGREEN, LORANGE]
    edges = [BLUE, GREEN, ORANGE]
    for i in range(3):
        box(d, bx[i], y, 320, 122, names[i], fill=fills[i], edge=edges[i], fs=19)
        # 交换机到板子
        cx = bx[i] + 160
        arrow(d, cx, 174, cx, y - 4, color=edges[i], lw=3)
        f = F(14)
        d.text((cx + 8, 200), "网线", font=f, fill=GRAY)

    # 供电
    py = 470
    pw = ["独立 DC 电源\n（板载供电口）",
          "独立 DC 电源\n★ DC 电源座",
          "有源 USB HUB\n（自带适配器）"]
    for i in range(3):
        cx = bx[i] + 160
        box(d, cx - 150, py, 300, 76, pw[i], fill=LRED, edge=RED, fs=17)
        arrow(d, cx, py - 4, cx, y + 126, color=RED, lw=3, dash=True)
        f = F(13)
        d.text((cx + 8, py + 84), "供电", font=f, fill=RED)

    # 救援通道
    box(d, 90, 620, 320, 70, "串口 (COM8) → 电脑\n★ 独立救援/配置通道",
        fill=(240, 240, 245), edge=GRAY, fs=17)
    arrow(d, 250, 620, 250, 378, color=GRAY, lw=2, dash=True)

    # 天线
    ax = [(590, 700, "测控天线", "地面2 测控站", GREEN),
          (1090, 700, "业务天线 ×2", "地面1 / 终端", ORANGE)]
    for x, yy, t1, t2, col in ax:
        box(d, x + 10, yy, 300, 62, t1, fill=BG, edge=col, fs=18)
        box(d, x + 10, yy + 86, 300, 62, t2, fill=BG, edge=col, fs=18)
        arrow(d, x + 160, yy - 4, x + 160, 378, color=col, lw=2)
        arrow(d, x + 130, 378, x + 130, yy - 4, color=col, lw=2)

    # 说明
    box(d, 620, 880, 780, 92,
        "原则：每块板子独立供电 · 数据接口不作供电路径 · 优先以太网 · 保留独立救援通道",
        fill=(245, 248, 252), edge=GRAY, fs=17)
    im.save(os.path.join(OUT, "fig1_arch.png"))
    print("fig1 已保存")


# =====================================================================
# 图 2：三条链路的数据流
# =====================================================================
def fig2():
    W, H = 1500, 1060
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)

    d.text((40, 26), "图 2  三条链路的数据流与处理分工",
           font=F(28, True), fill=INK)
    d.line([40, 68, W - 40, 68], fill=(200, 205, 215), width=2)

    # ---- 遥控上行 ----
    y0 = 100
    d.text((40, y0), "① 遥控上行（地面 → 星）", font=F(21, True), fill=GREEN)
    yy = y0 + 46
    xs = [60, 330, 640, 950, 1230]
    ts = ["地面2\n测控站", "遥测板 RX\n变频+ADC", "RK3588\n解调+CRC",
          "转发板\n参数调整", "生效"]
    cols = [BG, LGREEN, LBLUE, LORANGE, BG]
    eds = [GRAY, GREEN, BLUE, ORANGE, GRAY]
    for i in range(5):
        box(d, xs[i], yy, 210, 84, ts[i], fill=cols[i], edge=eds[i], fs=17)
        if i:
            arrow(d, xs[i - 1] + 210, yy + 42, xs[i] - 6, yy + 42, color=eds[i])
    f = F(14)
    d.text((xs[0] + 214, yy + 48), "RF", font=f, fill=GRAY)
    d.text((xs[1] + 214, yy + 48), "IQ/网线", font=f, fill=GRAY)
    d.text((xs[2] + 214, yy + 48), "指令/网线", font=f, fill=GRAY)

    # ---- 遥测下行 ----
    y1 = 300
    d.text((40, y1), "② 遥测下行（星 → 地面）", font=F(21, True), fill=BLUE)
    yy = y1 + 46
    ts = ["转发板\n状态寄存器", "RK3588\n组 CCSDS 包", "遥测板 TX\n调制+上变频",
          "地面2\n测控站", ""]
    cols = [LORANGE, LBLUE, LGREEN, BG, BG]
    eds = [ORANGE, BLUE, GREEN, GRAY, GRAY]
    for i in range(4):
        box(d, xs[i], yy, 210, 84, ts[i], fill=cols[i], edge=eds[i], fs=17)
        if i:
            arrow(d, xs[i - 1] + 210, yy + 42, xs[i] - 6, yy + 42, color=eds[i])
    d.text((xs[0] + 214, yy + 48), "串口/网线", font=f, fill=GRAY)
    d.text((xs[1] + 214, yy + 48), "IQ/网线", font=f, fill=GRAY)
    d.text((xs[2] + 214, yy + 48), "RF", font=f, fill=GRAY)

    # ---- 业务转发 ----
    y2 = 500
    d.text((40, y2), "③ 业务转发（透明弯管，不经 3588）", font=F(21, True), fill=ORANGE)
    yy = y2 + 46
    box(d, 60, yy, 240, 84, "地面1\n馈电站", fill=BG, edge=ORANGE, fs=17)
    box(d, 420, yy, 280, 84, "转发板 RX1\nDDC → DUC", fill=LORANGE,
        edge=ORANGE, fs=17)
    box(d, 820, yy, 240, 84, "转发板 TX1\n用户下行", fill=LORANGE,
        edge=ORANGE, fs=17)
    box(d, 1180, yy, 240, 84, "终端", fill=BG, edge=ORANGE, fs=17)
    arrow(d, 300, yy + 42, 414, yy + 42, color=ORANGE)
    arrow(d, 700, yy + 42, 814, yy + 42, color=ORANGE)
    arrow(d, 1060, yy + 42, 1174, yy + 42, color=ORANGE)
    d.text((306, yy + 48), "RF 馈电上行", font=f, fill=GRAY)
    d.text((706, yy + 48), "数字处理", font=f, fill=GRAY)
    d.text((1066, yy + 48), "RF 用户下行", font=f, fill=GRAY)

    yy2 = yy + 130
    box(d, 60, yy2, 240, 84, "终端", fill=BG, edge=ORANGE, fs=17)
    box(d, 420, yy2, 280, 84, "转发板 RX2\nDDC → DUC", fill=LORANGE,
        edge=ORANGE, fs=17)
    box(d, 820, yy2, 240, 84, "转发板 TX2\n馈电下行", fill=LORANGE,
        edge=ORANGE, fs=17)
    box(d, 1180, yy2, 240, 84, "地面1\n馈电站", fill=BG, edge=ORANGE, fs=17)
    arrow(d, 300, yy2 + 42, 414, yy2 + 42, color=ORANGE)
    arrow(d, 700, yy2 + 42, 814, yy2 + 42, color=ORANGE)
    arrow(d, 1060, yy2 + 42, 1174, yy2 + 42, color=ORANGE)
    d.text((306, yy2 + 48), "RF 用户上行", font=f, fill=GRAY)
    d.text((706, yy2 + 48), "数字处理", font=f, fill=GRAY)
    d.text((1066, yy2 + 48), "RF 馈电下行", font=f, fill=GRAY)

    box(d, 60, 900, 1380, 116,
        "关键点：转发板是透明弯管（不解调业务数据）。3588 只处理测控链路，"
        "通过遥控指令调整转发板参数，不接触业务数据流。\n"
        "两条业务链路互为反向（馈电↔用户），RX1/TX1 与 RX2/TX2 共同本振，"
        "收发频段靠波束/极化/空间隔离区分。",
        fill=(245, 248, 252), edge=GRAY, fs=17, bold=False)
    im.save(os.path.join(OUT, "fig2_dataflow.png"))
    print("fig2 已保存")


# =====================================================================
# 图 3：故障因果链
# =====================================================================
def fig3():
    W, H = 1400, 900
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.text((40, 26), "图 3  USB 端口失效的根本原因链",
           font=F(28, True), fill=INK)
    d.line([40, 68, W - 40, 68], fill=(200, 205, 215), width=2)

    items = [
        ("遥测板峰值电流 ≈ 1.0~1.2 A @ 5V", LRED, RED),
        ("RK3588 USB 2.0 端口规范供电 = 500 mA\n（内部 4 口 HUB 为总线供电，总量仅 500 mA）",
         LRED, RED),
        ("长期持续过载（非瞬时冲击，累计数小时）", LORANGE, ORANGE),
        ("USB 电源开关 IC 结温持续升高", LORANGE, ORANGE),
        ("IC 内部 MOSFET / 控制逻辑永久损坏", LRED, RED),
        ("该 IC 停止响应 I2C（feaa0000.i2c）", LPURPLE, PURPLE),
        ("内核驱动每 203 ms 轮询一次，全部超时\n→ 控制台被日志刷屏，无法交互",
         LPURPLE, PURPLE),
        ("该 IC 所辖全部 USB 端口 VBUS 关闭\n→ 所有 USB 口无电，且断电重启无法恢复",
         LRED, RED),
    ]
    y = 96
    for i, (t, fl, ed) in enumerate(items):
        h = 74 if "\n" in t else 58
        box(d, 300, y, 800, h, t, fill=fl, edge=ed, fs=17)
        if i:
            arrow(d, 700, y - 16, 700, y - 3, color=LINE, lw=3)
        y += h + 18

    # 侧注
    d.text((40, 100), "直接原因", font=F(18, True), fill=RED)
    d.text((40, 300), "劣化过程", font=F(18, True), fill=ORANGE)
    d.text((40, 480), "表现形式", font=F(18, True), fill=PURPLE)
    d.text((40, 690), "最终后果", font=F(18, True), fill=RED)

    box(d, 1140, 96, 230, 300,
        "放大因素\n\n① 地环路\nPC → 3588 →\nCMU200 → SMA →\n遥测板 → 3588\n\n"
        "② 环回测试期间\nTX 循环缓冲区\n持续满功率发射",
        fill=(250, 246, 235), edge=ORANGE, fs=15, bold=False)
    arrow(d, 1140, 240, 1104, 240, color=ORANGE, lw=2, dash=True)

    d.text((300, 800),
           "判别方法：断电重启后仍超时 → 永久损坏（非锁存保护）",
           font=F(17, True), fill=RED)
    im.save(os.path.join(OUT, "fig3_rootcause.png"))
    print("fig3 已保存")


if __name__ == "__main__":
    fig1()
    fig2()
    fig3()
    for f in sorted(os.listdir(OUT)):
        p = os.path.join(OUT, f)
        print("  %-26s %8d 字节" % (f, os.path.getsize(p)))
