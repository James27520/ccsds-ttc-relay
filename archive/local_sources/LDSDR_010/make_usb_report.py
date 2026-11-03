#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成《USB 端口失效根因分析与遥控遥测架构调整报告》"""
import os

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

OUT = r"E:\fpga_sdr_project\USB失效根因分析与遥控遥测架构调整报告.docx"
FIGS = r"E:\fpga_sdr_project\figs"

doc = Document()

_sec = doc.sections[0]
_sec.page_width, _sec.page_height = Cm(21.0), Cm(29.7)
_sec.left_margin = _sec.right_margin = Cm(2.0)
_sec.top_margin = _sec.bottom_margin = Cm(2.0)
_dg = _sec._sectPr.find(qn("w:docGrid"))
if _dg is not None:
    _sec._sectPr.remove(_dg)


def _ea(run, ea="宋体", size=None, bold=None, color=None, mono=False):
    run.font.name = "Consolas" if mono else "Times New Roman"
    if size:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if color:
        run.font.color.rgb = color
    rPr = run._element.get_or_add_rPr()
    rf = rPr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts")
        rPr.append(rf)
    rf.set(qn("w:eastAsia"), "NSimSun" if mono else ea)
    lg = rPr.find(qn("w:lang"))
    if lg is None:
        lg = OxmlElement("w:lang")
        rPr.append(lg)
    lg.set(qn("w:val"), "en-US")
    lg.set(qn("w:eastAsia"), "zh-CN")


for nm, sz in [("Normal", 10.5), ("Heading 1", 15), ("Heading 2", 12.5),
               ("Heading 3", 11.5)]:
    s = doc.styles[nm]
    s.font.name = "Times New Roman"
    s.font.size = Pt(sz)
    if nm != "Normal":
        s.font.color.rgb = RGBColor(0x1F, 0x35, 0x64)
    s._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体" if nm != "Normal" else "宋体")
    rPr = s._element.get_or_add_rPr()
    lg = OxmlElement("w:lang")
    lg.set(qn("w:val"), "en-US")
    lg.set(qn("w:eastAsia"), "zh-CN")
    rPr.append(lg)
doc.styles["Normal"].paragraph_format.space_after = Pt(4)
doc.styles["Normal"].paragraph_format.line_spacing = 1.15


def H(t, lvl=1):
    doc.add_heading(t, level=lvl)


def P(t, bold=False, ind=0, color=None):
    p = doc.add_paragraph()
    if ind:
        p.paragraph_format.left_indent = Cm(ind)
    _ea(p.add_run(t), "宋体", bold=bold, color=color)
    return p


def B(t):
    _ea(doc.add_paragraph(style="List Bullet").add_run(t), "宋体")


def CODE(lines):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.5)
    p.paragraph_format.space_before = Pt(3)
    p.paragraph_format.space_after = Pt(5)
    _ea(p.add_run("\n".join(lines)), mono=True, size=7.5)


def TAB(headers, rows, widths=None, fs=8.5):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Light Grid Accent 1"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        c = t.rows[0].cells[i]
        c.text = ""
        _ea(c.paragraphs[0].add_run(h), "黑体", fs, True)
    for row in rows:
        cs = t.add_row().cells
        for i, v in enumerate(row):
            cs[i].text = ""
            _ea(cs[i].paragraphs[0].add_run(str(v)), "宋体", fs)
    t.autofit = False
    _tw = OxmlElement("w:tblW")
    _tw.set(qn("w:w"), str(int(sum(widths) * 567)))
    _tw.set(qn("w:type"), "dxa")
    t._tbl.tblPr.append(_tw)

    if widths:
        for r in t.rows:
            for i, w in enumerate(widths):
                r.cells[i].width = Cm(w)
    doc.add_paragraph()
    return t


def FIG(fn, w=16.6, cap=None):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run().add_picture(os.path.join(FIGS, fn), width=Cm(w))
    if cap:
        c = doc.add_paragraph()
        c.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _ea(c.add_run(cap), "宋体", 9, color=RGBColor(0x60, 0x60, 0x60))


# =====================================================================
doc.add_heading("USB 端口失效根因分析与遥控遥测架构调整报告", level=0)
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
_ea(p.add_run("RK3588 星上处理 · 7010_AD9363 测控板 · LDSDR 转发板"),
    "宋体", 10.5, color=RGBColor(0x60, 0x60, 0x60))

P("本报告分两部分：第一部分分析 RK3588 全部 USB 端口失效的根本原因，"
  "给出损坏判定依据；第二部分据此重新定义遥控遥测模块、转发模块及其对接方式，"
  "确立「独立供电 + 以太网数据」的新架构。")

# ---------------------------------------------------------------------
H("一、事件经过", 1)
TAB(["时间", "事件", "现象"],
    [["长期", "遥测板通过 USB 从 RK3588 取电，持续运行数小时", "正常工作"],
     ["测试中", "环回测试期间 TX 循环缓冲区持续发射", "USB 链路偶发不稳"],
     ["之后", "用户断电重启遥测板与 3588", "3588 串口开始刷 I2C 超时"],
     ["随后", "再次完全断电重启 3588", "刷屏立即复现，USB 全部无电"],
     ["最终", "PuTTY 登录后无法输入（刷屏淹没）", "3588 失去可用控制通道"],
     ],
    widths=[2.4, 7.6, 6.6])

P("关键观察：", bold=True)
B("3588 本身仍能启动、内核运行（uptime 持续增长）")
B("故障从内核启动早期就出现，与用户操作无关")
B("断电重启不能恢复 —— 这一点是判定永久损坏的决定性依据")

# ---------------------------------------------------------------------
H("二、根本原因分析", 1)

H("2.1 电流预算严重不匹配", 2)
TAB(["项目", "数值", "来源"],
    [["遥测板峰值电流", "约 1.0 ~ 1.2 A @ 5V", "AD9363 + Zynq7010 + DDR 合计"],
     ["RK3588 USB 2.0 端口规范供电", "500 mA", "USB 2.0 规范"],
     ["3588 内部 4 口 HUB", "总线供电，500 mA 为全部下游端口总量", "Terminus 总线供电 HUB"],
     ["实际余量", "不足额定需求的一半", "——"],
     ],
    widths=[5.0, 5.6, 6.0])

P("这是一个长期存在的过载状态，而不是某次插拔造成的瞬时冲击。"
  "过载不会立刻损坏器件，但会让 USB 电源开关 IC 的结温持续偏高，"
  "加速其内部 MOSFET 与驱动逻辑的退化。", ind=0.5)

H("2.2 故障因果链", 2)
FIG("fig3_rootcause.png", 16.2, "图 3  USB 端口失效的根本原因链")

H("2.3 为什么「所有」USB 端口一起失效", 2)
P("因为 VBUS 的通断由电源开关 IC 统一控制，而这些 IC 的使能与状态回读都走同一条 I2C 总线：")
CODE([
    "RK3588 SoC ──I2C(feaa0000)──► USB 电源开关 IC ──VBUS──► Type-A / Type-C 端口",
    "                                      │",
    "                                      └── 该 IC 一旦不响应，其辖下所有端口同时失去 VBUS",
])
P("所以「一个芯片损坏」表现为「所有 USB 口没电」，并不矛盾。", ind=0.5)

H("2.4 为什么断电重启无效 —— 判定永久损坏的依据", 2)
TAB(["情形", "断电重启后表现", "本次实测"],
    [["保护电路锁存跳闸", "重新上电后释放，刷屏停止，USB 恢复", "❌ 不符合"],
     ["电源开关 IC 永久损坏", "重新上电后 I2C 依旧超时，USB 依旧无电", "✅ 符合"],
     ],
    widths=[4.6, 7.0, 5.0])
P("这是区分「可恢复保护」与「永久损坏」最直接的方法，"
  "本次结果明确落在后者。", ind=0.5)

H("2.5 放大因素", 2)
P("① 地环路", bold=True)
CODE([
    "PC ──USB串口──► 3588 ──USB──► 遥测板 ──SMA──► CMU200 ──?──► PC",
    "  └──────────────────── 地环路 ────────────────────────┘",
])
P("PC、3588、CMU200、遥测板通过 USB 地与射频地形成闭合回路。"
  "环路电流会流经 USB 地线与屏蔽层，进一步加重端口电路的负担。", ind=0.5)

P("② 环回测试期间的持续满功率发射", bold=True)
P("环回测试使用 libiio 循环缓冲区，TX 处于不间断发射状态，"
  "AD9363 发射通道长期工作在功耗峰值，使整板电流持续贴近上限。", ind=0.5)

H("2.6 已排除的其他可能", 2)
TAB(["假设", "排除依据"],
    [["3588 主芯片或 PMIC 损坏", "板子能正常启动、内核运行、网口可用，核心供电完好"],
     ["软件配置错误关闭了 USB", "断电重启后固件重新初始化，问题依旧"],
     ["USB 线缆或接头故障", "所有端口同时失效，单根线缆无法解释"],
     ["遥测板反向灌入高压", "遥测板自身工作正常，且 USB 口无异常发热记录"],
     ],
    widths=[5.6, 11.0])

# ---------------------------------------------------------------------
H("三、损坏判定与后续处置", 1)
TAB(["检查项", "方法", "结论"],
    [["Type-A 口是否有 5V", "插 U 盘，或万用表量 VBUS", "无电 → 确认失效"],
     ["Type-C 口是否有 5V", "同上", "无电 → 确认失效"],
     ["串口是否仍刷屏", "PuTTY 观察", "是 → IC 仍不响应"],
     ["网口是否可用", "插入交换机后 ping", "可用 → 数据通路尚存"],
     ],
    widths=[4.4, 6.2, 6.0])

P("处置结论：", bold=True)
B("★ 该 3588 的 USB 功能不可再依赖，所有 USB 相关方案必须废弃")
B("★ 数据通路改用以太网 —— 3588 的网口经实测完好")
B("★ 若需修复 USB，需更换 USB 电源开关 IC，属板级维修")
B("★ 在修复之前，3588 只能通过网口与串口访问")

# ---------------------------------------------------------------------
H("四、架构调整", 1)

H("4.1 四条设计原则", 2)
TAB(["原则", "内容", "本次故障的对应教训"],
    [["原则一", "每块板子独立供电，不共享电源轨",
      "遥测板峰值 1.2 A 却接在 500 mA 端口上"],
     ["原则二", "数据接口只传数据，不作供电路径",
      "USB 同时承担供电与数据，一旦过载两者全失"],
     ["原则三", "优先使用以太网作为板间数据通路",
      "网络天生隔离、带宽高、支持多客户端"],
     ["原则四", "保留一条与数据通路无关的救援通道",
      "USB 失效后 3588 一度完全失去控制手段"],
     ],
    widths=[2.2, 6.4, 8.0])

H("4.2 调整后的系统架构", 2)
FIG("fig1_arch.png", 16.6, "图 1  调整后的系统架构（独立供电 + 以太网数据）")

H("4.3 与旧架构的对比", 2)
TAB(["对比项", "旧架构", "新架构"],
    [["遥测板供电", "从 3588 的 USB 取电（500 mA 端口带 1.2 A 负载）",
      "★ 独立 DC 电源座"],
     ["转发板供电", "从主机 USB 取电", "有源 USB HUB（自带适配器）"],
     ["遥测板数据", "USB IIO 后端（usb:）", "★ 以太网（ip:192.168.10.3）"],
     ["转发板数据", "USB 串口", "以太网（后续）＋ 串口（过渡）"],
     ["同时客户端", "只允许 1 个，收发必须同进程", "多客户端，收发可分进程"],
     ["带宽", "8~13 MB/s", "千兆，理论 100+ MB/s"],
     ["救援通道", "无（USB 一坏全断）", "独立串口 + 网口双通道"],
     ],
    widths=[3.0, 6.6, 7.0])

P("附带收益：", bold=True)
P("USB IIO 后端有个硬限制 —— 同一时刻只允许一个客户端。"
  "这曾导致 iio_readdev 与 Python 的 iio.Context 冲突（Device or resource busy），"
  "迫使我们把收发塞进同一个进程、用循环缓冲区实现连续发射。"
  "改用网络后端后，这个妥协可以取消，工具结构能显著简化。", ind=0.5)

# ---------------------------------------------------------------------
H("五、模块职责重新定义", 1)

H("5.1 三条链路的数据流", 2)
FIG("fig2_dataflow.png", 16.6, "图 2  三条链路的数据流与处理分工")

H("5.2 遥测板（7010_AD9363）", 2)
TAB(["职责", "内容", "接口"],
    [["遥控接收", "射频 → 下变频 → ADC → IQ", "RX1 SMA；IQ 走网线给 3588"],
     ["遥测发射", "IQ → 上变频 → 射频", "TX1 SMA；IQ 从 3588 经网线来"],
     ["供电", "独立 DC 电源座", "★ 不再由 3588 供电"],
     ["配置", "libiio over IP", "iio_attr -u ip:192.168.10.3"],
     ],
    widths=[2.6, 6.4, 7.6])
P("定位：透明射频收发前端。不解调、不组包、不应答 —— 全部协议处理在 3588 完成。",
  ind=0.5)

H("5.3 转发板（LDSDR）", 2)
TAB(["职责", "内容", "接口"],
    [["业务转发", "RX1→DDC→DUC→TX1；RX2→DDC→DUC→TX2", "两副业务天线"],
     ["参数控制", "模式 / DDC / DUC / 增益 / 直流", "网线（过渡期用串口）"],
     ["供电", "有源 USB HUB", "★ 不再由 3588 供电"],
     ["状态输出", "收发计数 / 饱和计数 / 输出计数", "供 3588 组成遥测包"],
     ],
    widths=[2.6, 6.8, 7.2])
P("定位：透明弯管。不解调业务数据，因此 3588 看不到业务内容 —— "
  "这是当前架构的真实边界，若要闭环感知需另加 IQ 通路。", ind=0.5)

H("5.4 RK3588（星上处理）", 2)
TAB(["职责", "内容"],
    [["解调遥控", "取 IQ → 解调 → 找同步字 → 解 CCSDS → 校验 CRC"],
     ["执行指令", "按遥控包内容调整转发板参数"],
     ["组遥测", "读转发板状态 → 打 CCSDS 包 → 交遥测板发射"],
     ["网络中枢", "同时与遥测板、转发板通信（以太网）"],
     ],
    widths=[3.0, 13.6])
P("限于模式 A（执行地面遥控，不做星上自主决策）。", ind=0.5)

# ---------------------------------------------------------------------
H("六、接口定义", 1)
TAB(["接口", "连接", "类型", "速率/规格"],
    [["交换机 ↔ 3588", "网线", "千兆以太网", "192.168.10.2"],
     ["交换机 ↔ 遥测板", "网线", "千兆以太网", "192.168.10.3"],
     ["交换机 ↔ 转发板", "网线", "千兆以太网", "192.168.10.1"],
     ["3588 串口", "调试线 → 电脑", "UART 115200", "救援通道"],
     ["遥测板 RX1/TX1", "SMA ↔ 天线", "射频", "1000 MHz 频段"],
     ["转发板 RX1/TX1", "SMA ↔ 天线", "射频", "对地面1 / 终端"],
     ["转发板 RX2/TX2", "SMA ↔ 天线", "射频", "对终端 / 地面1"],
     ["供电（三块板）", "各自独立", "DC / 适配器", "★ 互不共享"],
     ],
    widths=[3.6, 4.4, 3.4, 5.2])

# ---------------------------------------------------------------------
H("七、改造清单", 1)
TAB(["#", "改造项", "难度", "优先级"],
    [["1", "遥测板改用 DC 座供电，网线接交换机", "低", "★ 立即"],
     ["2", "给遥测板 eth0 配静态 IP 并持久化", "低", "★ 立即"],
     ["3", "工具链 URI 从 usb: 改为 ip:192.168.10.3", "低", "★ 立即"],
     ["4", "转发板改由有源 USB HUB 供电", "低", "★ 立即"],
     ["5", "3588 串口加 loglevel=1，避免日志刷屏", "低", "高"],
     ["6", "取消收发同进程的循环缓冲区妥协", "中", "中"],
     ["7", "给转发板固件加以太网控制服务", "高", "中"],
     ["8", "维修或更换 3588 的 USB 电源开关 IC", "——", "低（可不用）"],
     ],
    widths=[1.2, 8.4, 2.0, 4.6])

# ---------------------------------------------------------------------
H("八、验证方法", 1)
P("架构调整后，按下面顺序逐层验证。每层通过才进入下一层。", bold=True)
TAB(["层次", "验证内容", "判定依据"],
    [["第一层", "网络连通", "电脑 ping 通 .10.1 / .10.2 / .10.3"],
     ["第二层", "3588 控制遥测板", "iio_attr -u ip: 写入值 == 回读值"],
     ["第三层", "遥测板发射", "频谱仪在预期频率看到稳定谱线"],
     ["第四层", "遥测板接收", "IQ 频谱峰值频率误差 < 1 个分辨单元"],
     ["第五层", "协议栈（软件）", "同步字命中 + CRC 通过 + 内容一致"],
     ["第六层", "射频闭环", "同上，且经真实射频环回"],
     ],
    widths=[2.0, 5.4, 9.2])

# ---------------------------------------------------------------------
H("九、结论与规范", 1)
P("9.1 根本原因结论", bold=True)
P("遥测板峰值电流（约 1.2 A）远超 RK3588 USB 端口规范供电能力（500 mA），"
  "长期持续过载导致 USB 电源开关 IC 永久损坏。"
  "该 IC 停止响应 I2C，直接造成两个后果：内核日志刷屏使控制台失效；"
  "其辖下全部 USB 端口 VBUS 关闭。断电重启后立即复现，"
  "证明这是物理损坏而非锁存保护。", ind=0.5)

P("9.2 架构调整结论", bold=True)
P("确立「每块板子独立供电、数据接口只传数据、优先以太网、保留独立救援通道」"
  "四条原则，并据此把遥测板与转发板的数据通路从 USB 迁移到以太网。"
  "这既消除了过载根源，也顺带解决了 USB 后端只允许单一客户端的限制。", ind=0.5)

P("9.3 应当固化为规范的三条", bold=True)
B("任何板卡接入主机前，必须先核算其峰值电流与主机端口的供电能力")
B("供电与数据必须走不同的物理通路，绝不用数据线兼做供电")
B("关键设备必须保留一条与主数据通路无关的带外管理通道")

doc.add_paragraph()
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
_ea(p.add_run("—— 报告完 ——"), "宋体", color=RGBColor(0x80, 0x80, 0x80))

doc.save(OUT)
print("已生成: %s" % OUT)
print("大小: %d 字节" % os.path.getsize(OUT))
