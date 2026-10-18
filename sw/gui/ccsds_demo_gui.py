#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ccsds_demo_gui.py -- CCSDS 遥测链路演示工具（电脑端）

设计要点
--------
遥测下行发的是【固定格式的参数表】，不是自由文本：
  · 每个参数在数据域里的字节偏移、类型、量纲、比例因子都是事先定好的
  · 星上只填数值，地面按同一张表解析
  · 所以界面是一张【只能改数字】的参数表（类似 IIO 的属性列表），
    而不是一个"想发啥发啥"的文本框

帧格式（固定 40 字节）
  6 字节主头（SCID/VCID/VCFC）+ 32 字节数据域（16 个 16 位参数）+ 2 字节 FECF

三种通信方式
  A. 纯软件环回   不接硬件，整条 CCSDS 算法链跑一遍（最稳，演示首选）
  B. 经板子       PC 组包 -> 遥测板发射 -> 环回 -> 板子接收 -> PC 解出参数
  C. 经 FPGA      板上 FPGA 自主完成编解码（用 Vivado ILA 演示）

运行: python ccsds_demo_gui.py
"""
import os
import sys
import threading
import traceback

import numpy as np

SW = r"E:\fpga_sdr_project\ccsds_ttc_loopback\sw\ttc"
TOOLS = r"E:\ccsds_fpga\tools"
for d in (SW, TOOLS):
    if d not in sys.path:
        sys.path.insert(0, d)
import ccsds_tm_tx as ccsds          # noqa: E402
import tm_params as TP               # noqa: E402

try:
    import tkinter as tk
    from tkinter import ttk, scrolledtext, messagebox
except Exception as e:               # pragma: no cover
    print("需要 tkinter:", e)
    raise

FS = 2_500_000.0
SYM_RATE = 250_000.0
BETA = 0.35
IF_HZ = 200_000.0
AMP = 0.6
SPS = 10


# ============================================================================
def modulate(frame_bytes):
    cadu, info = ccsds.build_cadu(frame_bytes)
    ret = ccsds.cadu_to_iq(cadu, fs=FS, sym_rate=SYM_RATE, beta=BETA,
                           amp=AMP, if_hz=IF_HZ)
    if isinstance(ret, tuple) and len(ret) == 2:
        iq = ccsds.iq_interleave(ret[0], ret[1])
    else:
        iq = ret
    return cadu, np.asarray(iq), info


def channel(iq, snr_db=None, freq_off=0.0, gain=1.0, seed=0):
    x = iq.astype(np.float64)
    z = (x[0::2] + 1j * x[1::2]) * gain
    if freq_off:
        t = np.arange(len(z)) / FS
        z = z * np.exp(2j * np.pi * freq_off * t)
    if snr_db is not None:
        p = np.mean(np.abs(z) ** 2)
        n = np.sqrt(p / (2 * 10 ** (snr_db / 10.0)))
        rng = np.random.default_rng(seed)
        z = z + n * (rng.standard_normal(len(z)) + 1j * rng.standard_normal(len(z)))
    out = np.empty(2 * len(z), dtype=np.int16)
    out[0::2] = np.clip(np.round(z.real * 32767), -32768, 32767)
    out[1::2] = np.clip(np.round(z.imag * 32767), -32768, 32767)
    return out


def demodulate(iq):
    x = iq.astype(np.float64)
    z = x[0::2] + 1j * x[1::2]
    t = np.arange(len(z)) / FS
    bb = z * np.exp(-1j * 2 * np.pi * IF_HZ * t)
    h = ccsds.srrc(BETA, SPS, span=6)
    mf = np.convolve(bb, h, mode="same")
    best = None
    for ph in range(SPS):
        sym = mf[ph::SPS]
        conf = float(np.sum(np.abs(sym.real)))
        if best is None or conf > best[0]:
            best = (conf, ph, (sym.real < 0).astype(np.uint8))
    return best[2], best[1]


def find_asm_and_decode(bits):
    asm = np.array([(0x1ACFFC1D >> (31 - i)) & 1 for i in range(32)], dtype=np.uint8)
    for i in range(len(bits) - 32):
        if np.array_equal(bits[i:i + 32], asm):
            cadu = bits[i:i + 672]
            if len(cadu) < 672:
                return False, i, None, "位流不够长"
            try:
                frame, detail = ccsds.decode_cadu(cadu, verbose=False)
                return True, i, frame, detail
            except Exception as e:
                return True, i, None, "decode_cadu 异常: %s" % e
    return False, -1, None, "没找到 ASM 0x1ACFFC1D"


# ============================================================================
class Demo(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CCSDS 遥测链路演示  —  遥测参数表 → 组帧 → 调制 → 接收解析")

        # ★★★ 窗口尺寸必须按【屏幕实际可用大小】来定 ★★★
        #   踩过的坑：原来硬写 geometry("1500x960")，而现场屏幕只有 1280x800
        #   （工作区 1280x752），窗口底部被推到屏幕外面 —— 表现就是"怎么缩放
        #   都看不到最下面的输出"。改成按屏幕算，并留出任务栏的余量。
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w = min(1400, max(1000, sw - 20))
        h = min(980, max(600, sh - 70))
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 3)
        self.geometry("%dx%d+%d+%d" % (w, h, x, y))
        self.minsize(960, 560)     # 再小就没法用了，但不允许小于这个

        self.tx_frame = None
        self.rows = {}          # 参数名 -> Entry
        self.eng_labels = {}    # 参数名 -> Label（工程值显示）
        self.build_ui()

    # ---------------- UI ----------------
    def build_ui(self):
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure("Big.TButton", font=("Consolas", 12, "bold"), padding=6)
        st.configure("Verdict.TLabel", font=("Microsoft YaHei", 15, "bold"))
        st.configure("Hdr.TLabel", font=("Microsoft YaHei", 10, "bold"))

        # ★★ 顶层布局：用【垂直 PanedWindow】把界面分成上下两块，
        #    中间一条可拖动的分隔条（sash），两块都设了最小高度。
        #
        #    为什么这么做（两次踩坑的教训）：
        #      第一版：所有控件顺次 pack -> 参数表 16 行把底部按钮挤出窗口
        #      第二版：上下两块都 expand=True -> 窗口一缩小，下面那块被压到看不见
        #    正解：PanedWindow 会给每块保留 minsize，怎么缩放都不会消失，
        #    而且中间那条分隔条可以拖动，用户自己决定上下各占多少。
        pw = tk.PanedWindow(self, orient="vertical", sashwidth=8,
                            sashrelief="raised", bg="#d0d0d0",
                            opaqueresize=True)
        pw.pack(fill="both", expand=True)

        top = ttk.Frame(pw, padding=6)
        bot_outer = ttk.Frame(pw, padding=(6, 0, 6, 6))

        # ★ 顺序很重要：先 add 的在上（pane 0），sash_place(0,0,pos) 给的就是 pane 0 的高度。
        #   之前把接收区先 add，结果 sash_place 把高度给了接收区，参数表面板被压到 283px，
        #   而它需要 509px -> 超出部分排到窗口外，按钮就点不到了。
        pw.add(top, minsize=300, stretch="always")
        pw.add(bot_outer, minsize=130, stretch="always")

        # ============ 左：遥测参数表 ============
        left = ttk.LabelFrame(top, text=" ① 遥测参数表（只能改数值；偏移/类型/量纲是固定的） ",
                              padding=6)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        # ★ 布局要点（踩过的坑）：原来把所有东西都按顺序 pack，参数表 16 行太高，
        #   把最下面的【生成并发送】挤出了窗口，而且没有滚动条，点不到。
        #   正确做法：先用 side="bottom" 把固定的底部元素占住位置，
        #   再让参数表用 fill="both", expand=True 吃掉剩余空间并带滚动条。
        #   Tk 的 pack 是按调用顺序分配空间的，所以顺序必须是「先底后中」。

        # --- 底部（固定）：主按钮 ---
        btns = ttk.Frame(left)
        btns.pack(side="bottom", fill="x", pady=(8, 0))
        ttk.Button(btns, text="生成并发送 ▶", style="Big.TButton",
                   command=self.on_send).pack(side="left")
        ttk.Button(btns, text="只生成不发", command=self.on_build_only).pack(side="left", padx=8)
        ttk.Button(btns, text="清空接收区", command=self.clear_rx).pack(side="left")

        # --- 底部（固定）：信道条件 ---
        cf = ttk.Frame(left)
        cf.pack(side="bottom", fill="x", pady=(4, 0))
        self.v_snr = tk.StringVar(value="")
        self.v_foff = tk.StringVar(value="0")
        ttk.Label(cf, text="SNR(dB,空=无噪):").pack(side="left")
        ttk.Entry(cf, textvariable=self.v_snr, width=5).pack(side="left", padx=(2, 8))
        ttk.Label(cf, text="频偏(Hz):").pack(side="left")
        ttk.Entry(cf, textvariable=self.v_foff, width=7).pack(side="left", padx=2)

        # --- 底部（固定）：通信方式（横排，省纵向空间）---
        mf = ttk.LabelFrame(left, text=" 通信方式 ", padding=3)
        mf.pack(side="bottom", fill="x", pady=(4, 0))
        self.v_mode = tk.StringVar(value="soft")
        for val, txt in (("soft", "A 纯软件"),
                         ("board", "B 经板子"),
                         ("fpga", "C 经FPGA")):
            ttk.Radiobutton(mf, text=txt, value=val, variable=self.v_mode).pack(
                side="left", padx=2)

        # --- 底部（固定）：参数按钮 ---
        br = ttk.Frame(left)
        br.pack(side="bottom", fill="x", pady=(6, 0))
        ttk.Button(br, text="恢复默认值", command=self.on_defaults).pack(side="left")
        ttk.Button(br, text="全部置零", command=self.on_zero).pack(side="left", padx=6)
        ttk.Button(br, text="模拟一帧遥测", command=self.on_simulate).pack(side="left")

        # --- 顶部（固定）：帧头 ---
        hf = ttk.LabelFrame(left, text=" 帧头 ", padding=4)
        hf.pack(side="top", fill="x", pady=(0, 6))
        self.v_scid = tk.StringVar(value="42")
        self.v_vcid = tk.StringVar(value="0")
        self.v_vcfc = tk.StringVar(value="0")
        for i, (lab, var, w) in enumerate((("航天器ID SCID", self.v_scid, 6),
                                           ("虚拟信道 VCID", self.v_vcid, 4),
                                           ("帧计数 VCFC", self.v_vcfc, 6))):
            ttk.Label(hf, text=lab).grid(row=0, column=i * 2, sticky="e", padx=(4, 2))
            ttk.Entry(hf, textvariable=var, width=w).grid(row=0, column=i * 2 + 1, sticky="w")
        self.v_vcfc_auto = tk.BooleanVar(value=True)
        ttk.Checkbutton(hf, text="每发一帧自动+1", variable=self.v_vcfc_auto).grid(
            row=1, column=0, columnspan=6, sticky="w", padx=4)

        # --- 顶部（固定）：参数集选择 ---
        prf = ttk.Frame(left)
        prf.pack(side="top", fill="x", pady=(0, 4))
        ttk.Label(prf, text="参数集:").pack(side="left")
        self.v_profile = tk.StringVar(value=TP.profile_name())
        cb = ttk.Combobox(prf, textvariable=self.v_profile, state="readonly", width=46,
                          values=[TP.PROFILES[k]["name"] for k in ("relay", "tm")])
        cb.pack(side="left", padx=4)
        cb.bind("<<ComboboxSelected>>", self._on_profile)
        self._cb_profile = cb

        # --- 中间（可滚动，吃剩余空间）：参数表格 ---
        pf_container = ttk.Frame(left)
        pf_container.pack(side="top", fill="both", expand=True)
        _cv, pf = self._scrollable(pf_container, height=132)
        self._pf = pf
        self._build_param_rows(pf)

        # ============ 右：报文 ============
        right = ttk.Frame(top)
        right.grid(row=0, column=1, sticky="nsew")
        top.columnconfigure(0, weight=0)
        top.columnconfigure(1, weight=1)

        pkt = ttk.LabelFrame(right, text=" ② 软件生成的 CCSDS 包 ", padding=6)
        pkt.pack(fill="both", expand=True)
        self.txt_pkt = scrolledtext.ScrolledText(pkt, width=78, height=15,
                                                 font=("Consolas", 10), wrap="none")
        self.txt_pkt.pack(fill="both", expand=True)

        bot = ttk.LabelFrame(bot_outer, text=" ③ 接收端解析结果（CCSDS 解码后的参数） ", padding=6)
        bot.pack(fill="both", expand=True)

        vf = ttk.Frame(bot)
        vf.pack(fill="x")
        self.lbl_verdict = ttk.Label(vf, text="（还没发送）", style="Verdict.TLabel",
                                     foreground="#888")
        self.lbl_verdict.pack(side="left")
        self.lbl_info = ttk.Label(vf, text="", font=("Consolas", 10))
        self.lbl_info.pack(side="left", padx=16)

        # ★ 下块用 Notebook 分两个视图：
        #   ① 参数解析  —— 结构化表格，演示时最醒目：CCSDS 解码后就是这一堆参数
        #   ② 详细日志  —— 帧十六进制、ASM/CRC、板子交互日志等细节
        nb = ttk.Notebook(bot)
        nb.pack(fill="both", expand=True, pady=(4, 0))

        # --- 页 1：参数解析表 ---
        tab1 = ttk.Frame(nb)
        nb.add(tab1, text=" ① 参数解析（CCSDS 解码后的内容） ")
        cols = ("name", "off", "raw", "eng", "cmp", "desc")
        heads = ("参数名", "偏移", "原始值", "工程值", "与发送端", "说明")
        wids = (110, 44, 70, 110, 70, 330)
        self.tree = ttk.Treeview(tab1, columns=cols, show="headings", height=8)
        for c, h, w in zip(cols, heads, wids):
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w, anchor=("w" if c in ("name", "desc") else "center"))
        tv_sb = ttk.Scrollbar(tab1, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tv_sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        tv_sb.pack(side="right", fill="y")
        self.tree.tag_configure("ok", foreground="#006600")
        self.tree.tag_configure("bad", foreground="#cc0000")

        # --- 页 2：详细日志 ---
        tab2 = ttk.Frame(nb)
        nb.add(tab2, text=" ② 详细日志（帧字节 / ASM / CRC / 板子交互） ")
        self.txt_rx = scrolledtext.ScrolledText(tab2, height=8, font=("Consolas", 10),
                                                wrap="none")
        self.txt_rx.pack(fill="both", expand=True)
        self._nb = nb

        # 分隔条的初始位置：上块约占 60%，剩下的给接收区。
        # 之后用户可以自己拖这条分隔条调整上下比例（这就是"可以拖动的上下条"）。
        self._pw = pw
        self.after(80, self._place_sash)

    def _place_sash(self):
        """把可拖动分隔条放到一个合理位置，保证上下两块都看得见"""
        try:
            n = self._pw.winfo_height()
            pos = min(max(300, int(n * 0.60)), max(300, n - 170))
            self._pw.sash_place(0, 0, pos)
        except Exception:
            pass

    # ---------------- 参数解析表显示 ----------------
    def _fill_tree(self, parsed, sent_vals=None, show_cmp=True):
        """
        把 CCSDS 解码出来的参数填进表格。
        parsed: [(参数定义, 原始值, 工程值), ...]
        sent_vals: 发送端的原始值字典（用于『与发送端』列的比对）
        """
        for i in self.tree.get_children():
            self.tree.delete(i)
        for p, raw, eng in parsed:
            if show_cmp and sent_vals is not None:
                same = sent_vals.get(p["name"]) == raw
                cmptxt = "一致" if same else "★不一致"
                tag = "ok" if same else "bad"
            else:
                cmptxt = "—"
                tag = "ok"
            self.tree.insert("", "end", tags=(tag,),
                             values=(p["name"], p["off"], raw,
                                     TP.format_eng(p, raw), cmptxt,
                                     p.get("desc", "")))

    def _clear_tree(self):
        for i in self.tree.get_children():
            self.tree.delete(i)

    # ---------------- 参数表构建 / 切换 ----------------
    def _build_param_rows(self, pf):
        """按当前生效的参数集，重建参数表的所有行"""
        for w in pf.winfo_children():
            w.destroy()
        self.rows = {}
        self.eng_labels = {}
        hdr = ("参数名", "偏移", "类型", "原始值", "单位", "工程值")
        widths = (13, 5, 5, 9, 7, 14)
        for c, (h, w) in enumerate(zip(hdr, widths)):
            ttk.Label(pf, text=h, style="Hdr.TLabel", width=w,
                      anchor="w").grid(row=0, column=c, sticky="w", padx=2, pady=(0, 2))
        for r, p in enumerate(TP.PARAMS, start=1):
            ttk.Label(pf, text=p["name"], width=widths[0], anchor="w").grid(
                row=r, column=0, sticky="w", padx=2)
            ttk.Label(pf, text=str(p["off"]), width=widths[1], anchor="w").grid(
                row=r, column=1, sticky="w", padx=2)
            ttk.Label(pf, text=p["fmt"], width=widths[2], anchor="w").grid(
                row=r, column=2, sticky="w", padx=2)
            e = ttk.Entry(pf, width=widths[3], justify="right")
            e.insert(0, str(p["init"]))
            e.grid(row=r, column=3, sticky="w", padx=2, pady=1)
            e.bind("<KeyRelease>", lambda ev, nm=p["name"]: self._upd_eng(nm))
            e.bind("<FocusOut>", lambda ev, nm=p["name"]: self._clamp_one(nm))
            self.rows[p["name"]] = e
            ttk.Label(pf, text=p["unit"], width=widths[4], anchor="w").grid(
                row=r, column=4, sticky="w", padx=2)
            lb = ttk.Label(pf, text=TP.format_eng(p, p["init"]), width=widths[5], anchor="w")
            lb.grid(row=r, column=5, sticky="w", padx=2)
            self.eng_labels[p["name"]] = lb

    def _on_profile(self, _ev=None):
        """切换参数集：relay（转发控制）/ tm（卫星遥测）"""
        name = self.v_profile.get()
        for k, v in TP.PROFILES.items():
            if v["name"] == name:
                TP.set_profile(k)
                break
        self._build_param_rows(self._pf)
        self._clear_tree()          # 参数集变了，之前的解析结果也失效了
        self.lbl_verdict.config(text="已切换参数集：%s" % TP.profile_name(), foreground="#666")
        self.lbl_info.config(text="")

    # ---------------- UI 辅助 ----------------
    def _scrollable(self, parent, height=170):
        """
        造一个带垂直滚动条的容器，返回 (canvas, inner_frame)。
        里面的东西放在 inner_frame 里。

        ★ height 必须给一个【有限值】：Canvas 的请求高度就是它，
          否则 16 行参数表会把整个左侧面板撑高，进而把窗口撑出屏幕。
          可滚动 + 有限高度 = 参数表再长也不会顶掉别的控件。
        """
        cv = tk.Canvas(parent, highlightthickness=0, borderwidth=0, height=height)
        vsb = ttk.Scrollbar(parent, orient="vertical", command=cv.yview)
        inner = ttk.Frame(cv)
        win = cv.create_window((0, 0), window=inner, anchor="nw")
        cv.configure(yscrollcommand=vsb.set)

        inner.bind("<Configure>",
                   lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>",
                lambda e: cv.itemconfigure(win, width=e.width))

        def _wheel(ev):
            cv.yview_scroll(int(-1 * (ev.delta / 120)), "units")

        def _enter(ev):
            cv.bind_all("<MouseWheel>", _wheel)

        def _leave(ev):
            cv.unbind_all("<MouseWheel>")

        cv.bind("<Enter>", _enter)
        cv.bind("<Leave>", _leave)
        cv.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        return cv, inner

    # ---------------- 参数读写 ----------------
    @staticmethod
    def hexdump(b, per=16, prefix=""):
        out = []
        for i in range(0, len(b), per):
            ch = b[i:i + per]
            hx = " ".join("%02X" % x for x in ch)
            asc = "".join(chr(x) if 32 <= x < 127 else "." for x in ch)
            out.append("%s%04X  %-*s  |%s|" % (prefix, i, per * 3 - 1, hx, asc))
        return "\n".join(out)

    def _upd_eng(self, name):
        p = next(x for x in TP.PARAMS if x["name"] == name)
        try:
            raw = int(self.rows[name].get())
        except Exception:
            self.eng_labels[name].config(text="—")
            return
        self.eng_labels[name].config(text=TP.format_eng(p, raw))

    def _clamp_one(self, name):
        p = next(x for x in TP.PARAMS if x["name"] == name)
        try:
            raw = int(self.rows[name].get())
        except Exception:
            raw = p["init"]
        v = TP.clamp(p, raw)
        self.rows[name].delete(0, "end")
        self.rows[name].insert(0, str(v))
        self.eng_labels[name].config(text=TP.format_eng(p, v))

    def read_values(self):
        vals = {}
        for p in TP.PARAMS:
            try:
                vals[p["name"]] = TP.clamp(p, int(self.rows[p["name"]].get()))
            except Exception:
                vals[p["name"]] = p["init"]
        return vals

    def write_values(self, vals):
        for p in TP.PARAMS:
            v = TP.clamp(p, vals.get(p["name"], p["init"]))
            self.rows[p["name"]].delete(0, "end")
            self.rows[p["name"]].insert(0, str(v))
            self.eng_labels[p["name"]].config(text=TP.format_eng(p, v))

    def on_defaults(self):
        self.write_values({p["name"]: p["init"] for p in TP.PARAMS})

    def on_zero(self):
        self.write_values({p["name"]: max(p["lo"], 0) if p["lo"] <= 0 else p["lo"]
                           for p in TP.PARAMS})

    def on_simulate(self):
        """模拟一帧真实遥测：参数小幅漂移、时间戳递增"""
        vals = self.read_values()
        rng = np.random.default_rng()
        for p in TP.PARAMS:
            if p["name"] == "时间戳低位":
                vals[p["name"]] = (vals[p["name"]] + 1) & 0xFFFF
            elif p["name"] in ("丢帧计数", "CRC错误计数", "遥控指令计数", "工作模式"):
                continue
            else:
                span = max(1, int((p["hi"] - p["lo"]) * 0.002))
                vals[p["name"]] = max(p["lo"], min(p["hi"],
                                                   vals[p["name"]] + int(rng.integers(-span, span + 1))))
        self.write_values(vals)

    # ---------------- 组帧 ----------------
    def build_frame(self):
        def pi(s, d):
            s = (s or "").strip()
            if not s:
                return d
            return int(s, 16) if s.lower().startswith("0x") else int(s)
        scid = max(0, min(1023, pi(self.v_scid.get(), 42)))
        vcid = max(0, min(7, pi(self.v_vcid.get(), 0)))
        vcfc = max(0, min(255, pi(self.v_vcfc.get(), 0)))
        data = TP.build_data_block(self.read_values())
        frame = ccsds.build_tm_frame(scid=scid, vcid=vcid, mcfc=0, vcfc=vcfc,
                                     data=data, fecf=True)
        return frame, data, scid, vcid, vcfc

    def show_packet(self, frame, data, cadu, iq, scid, vcid, vcfc):
        t = self.txt_pkt
        t.delete("1.0", "end")
        t.insert("end", "== 帧头 ==\n")
        t.insert("end", "  SCID=%-5d VCID=%-3d VCFC=%-4d （主头 6 字节：%s）\n"
                 % (scid, vcid, vcfc, " ".join("%02X" % x for x in frame[:6])))
        t.insert("end", "\n== 数据域：遥测参数表（32 字节，小端）==\n")
        t.insert("end", "  %-14s %-4s %-5s %-8s %s\n" % ("参数名", "偏移", "原始值", "字节", "工程值"))
        vals = self.read_values()
        for p in TP.PARAMS:
            raw = vals[p["name"]]
            b2 = data[p["off"]:p["off"] + 2]
            t.insert("end", "  %-14s %-4d %-5d %-8s %s\n"
                     % (p["name"], p["off"], raw, " ".join("%02X" % x for x in b2),
                        TP.format_eng(p, raw)))
        t.insert("end", "\n  FECF = %s\n" % " ".join("%02X" % x for x in frame[-2:]))
        t.insert("end", "\n== 完整帧（%d 字节）==\n" % len(frame))
        t.insert("end", self.hexdump(frame, prefix="  ") + "\n")
        t.insert("end", "\n== 编码过程 ==\n")
        t.insert("end", "  帧比特       : %d bit (%d 字节)\n" % (len(frame) * 8, len(frame)))
        t.insert("end", "  随机化       : LFSR x^8+x^7+x^5+x^3+1\n")
        t.insert("end", "  卷积编码 1/2 : %d bit (K=7, G1=1111001, G2=1011011)\n"
                 % (len(frame) * 8 * 2))
        t.insert("end", "  + ASM 4 字节 : %d bit = CADU (84 字节)\n" % len(cadu))
        t.insert("end", "  ASM          : 1A CF FC 1D\n")
        t.insert("end", "\n== 调制 ==\n")
        t.insert("end", "  采样率 %.0f Hz / 符号率 %.0f Hz / SRRC β=%.2f / 中频 %.0f Hz\n"
                 % (FS, SYM_RATE, BETA, IF_HZ))
        t.insert("end", "  IQ 样点 %d  →  射频中心 = 本振 + %.0f kHz\n" % (len(iq), IF_HZ / 1e3))

    # ---------------- 动作 ----------------
    def on_build_only(self):
        try:
            frame, data, scid, vcid, vcfc = self.build_frame()
            cadu, iq, info = modulate(frame)
            self.tx_frame = frame
            self.show_packet(frame, data, cadu, iq, scid, vcid, vcfc)
            self.lbl_verdict.config(text="已生成，未发送", foreground="#888")
        except Exception as e:
            messagebox.showerror("出错", "%s\n\n%s" % (e, traceback.format_exc()))

    def on_send(self):
        mode = self.v_mode.get()
        if mode == "board":
            self.on_send_board()
            return
        if mode == "fpga":
            messagebox.showinfo(
                "模式 C 怎么演示",
                "C（经 FPGA）链路已经验证通过，但演示不在这个窗口里：\n\n"
                "  1. 板子停在 u-boot:  tools\\uboot_stop.ps1\n"
                "  2. 烧写 + 抓取:  vivado -mode batch -source ccsds_pl\\program_and_base.tcl\n"
                "  3. ILA 里看:  frame_match=1  rx_crc_ok=1\n"
                "                 rx_frame_idx=40  rx_frame_byte=63\n"
                "  4. 恢复原厂:  Pluto> 敲 boot，或断电重插\n\n"
                "原因：板上设计是自带固定帧的自环链路，PC 不下发参数。\n"
                "要 PC 下发参数需再给 FPGA 加一条串口注入通路。\n\n"
                "想『电脑填参数、真的过板子』请选 B。")
            return
        try:
            frame, data, scid, vcid, vcfc = self.build_frame()
            cadu, iq, info = modulate(frame)
            self.tx_frame = frame
            self.show_packet(frame, data, cadu, iq, scid, vcid, vcfc)

            snr = self.v_snr.get().strip()
            snr = float(snr) if snr else None
            foff = float(self.v_foff.get().strip() or 0)
            iq_ch = channel(iq, snr_db=snr, freq_off=foff)

            bits, ph = demodulate(iq_ch)
            res = None
            for tag, b in (("正", bits), ("反", (1 - bits).astype(np.uint8))):
                ok, pos, dframe, detail = find_asm_and_decode(b)
                if ok and dframe is not None:
                    res = (tag, pos, dframe, detail)
                    break
            self.show_result(frame, data, res, snr, foff, len(iq_ch), ph)
            if self.v_vcfc_auto.get():
                try:
                    self.v_vcfc.set(str((int(self.v_vcfc.get() or 0) + 1) & 0xFF))
                except Exception:
                    pass
            self.on_simulate()
        except Exception as e:
            messagebox.showerror("出错", "%s\n\n%s" % (e, traceback.format_exc()))

    def _rx_params(self, frame):
        """从收到的帧里解析遥测参数表，返回 (解析结果, 与发送端是否一致)"""
        data = frame[6:6 + TP.DATA_BYTES]
        parsed = TP.parse_data_block(data)
        sent = self.read_values()
        diff = []
        for p, raw, eng in parsed:
            if sent.get(p["name"]) != raw:
                diff.append((p["name"], sent.get(p["name"]), raw))
        return parsed, diff

    def show_result(self, frame, data, res, snr, foff, niq, ph=0):
        t = self.txt_rx
        t.delete("1.0", "end")
        hdr = "信道: 无噪" if snr is None else "SNR=%.1f dB" % snr
        if foff:
            hdr += "  频偏=%.0f Hz" % foff
        t.insert("end", "信道条件 : %s   （%d 个 IQ 样点）\n" % (hdr, niq))
        t.insert("end", "-" * 90 + "\n")
        if res is None:
            self.lbl_verdict.config(text="✗ 未同步上", foreground="#c00")
            self.lbl_info.config(text="没找到 ASM")
            t.insert("end", "接收端没能在位流中找到同步字 0x1ACFFC1D。\n")
            return

        tag, pos, dframe, detail = res
        n = min(len(dframe), len(frame))
        bytediff = int((np.frombuffer(dframe[:n], dtype=np.uint8) !=
                        np.frombuffer(frame[:n], dtype=np.uint8)).sum())
        crc_ok = (len(dframe) >= 2 and dframe[-2:] == frame[-2:])
        parsed, pdiff = self._rx_params(dframe) if len(dframe) >= 8 else ([], [])

        if bytediff == 0 and not pdiff:
            self.lbl_verdict.config(text="✓ 接收参数与发送完全一致", foreground="#080")
        else:
            self.lbl_verdict.config(text="✗ 有 %d 字节 / %d 个参数不一致"
                                         % (bytediff, len(pdiff)), foreground="#c00")
        self.lbl_info.config(text="ASM@%d 极性=%s CRC=%s 抽取相位=%d"
                                  % (pos, tag, "通过" if crc_ok else "失败", ph))
        # ★ 解析出来的参数填进结构化表格（这是 CCSDS 解码后的"那堆参数"）
        self._fill_tree(parsed, self.read_values())
        self._nb.select(0)

        t.insert("end", "同步      : ASM 命中，位置 %d（极性 %s）\n" % (pos, tag))
        t.insert("end", "CRC/FECF  : %s  (收到 0x%s，期望 0x%s)\n"
                 % ("通过 ✓" if crc_ok else "失败 ✗",
                    dframe[-2:].hex().upper(), frame[-2:].hex().upper()))
        t.insert("end", "逐字节    : %s\n" % ("完全一致 ✓" if bytediff == 0
                                              else "%d 字节不同 ✗" % bytediff))
        t.insert("end", "\n【接收端解出的遥测参数表】\n")
        t.insert("end", "  %-14s %-6s %-10s %-10s %s\n"
                 % ("参数名", "偏移", "原始值", "工程值", "与发送端"))
        for p, raw, eng in parsed:
            s = "一致 ✓" if sent_eq(p, raw, self.read_values()) else "★ 不一致"
            t.insert("end", "  %-14s %-6d %-10d %-10s %s\n"
                     % (p["name"], p["off"], raw, TP.format_eng(p, raw), s))
        t.insert("end", "\n【接收到的完整帧】\n")
        t.insert("end", self.hexdump(dframe, prefix="  ") + "\n")

    # ---------------- 模式 B ----------------
    def on_send_board(self):
        self.lbl_verdict.config(text="⏳ 正在过板子…（约 20 秒）", foreground="#c60")
        self.lbl_info.config(text="组包 → 上传 → 发射 → 接收 → 译码")
        t = self.txt_rx
        t.delete("1.0", "end")
        t.insert("end", "== 模式 B：PC 组包 → 遥测板发射 → 环回 → 板子接收 → PC 解出参数 ==\n\n")

        def worker():
            try:
                if TOOLS not in sys.path:
                    sys.path.insert(0, TOOLS)
                import mode_b_link
                link = mode_b_link.ModeBLink(log=lambda s: self.after(0, self._rx_log, s))
                # 用参数表构造 32 字节数据域，交给链路层组帧
                data = TP.build_data_block(self.read_values())
                r = link.run(data_block=data, scid=int(self.v_scid.get() or 42),
                             vcid=int(self.v_vcid.get() or 0), vcfc=int(self.v_vcfc.get() or 0))
                self.after(0, self._rx_done, r)
            except Exception as e:
                self.after(0, self._rx_fail, "%s" % e)

        threading.Thread(target=worker, daemon=True).start()

    def _rx_log(self, s):
        self.txt_rx.insert("end", s + "\n")
        self.txt_rx.see("end")

    def _rx_fail(self, msg):
        self.lbl_verdict.config(text="✗ 模式 B 出错", foreground="#c00")
        self.lbl_info.config(text=msg[:100])
        self.txt_rx.insert("end", "\n  [!] %s\n" % msg)
        self.txt_rx.insert("end", "\n  排查顺序：\n"
                                  "   1. ping 192.168.2.1 通不通\n"
                                  "   2. 板子本振是否同频（iio_attr ... altvoltage0/1 frequency）\n"
                                  "   3. 先跑 tools\\verify_leakage.py 确认射频通路\n"
                                  "   4. 先跑 tools\\tx_path_probe.py 确认 TX 出信号\n")

    def _rx_done(self, r):
        t = self.txt_rx
        if r.get("ok"):
            self.lbl_verdict.config(text="✓ 接收参数与发送完全一致（经真实板子）",
                                    foreground="#080")
            self.lbl_info.config(text="ASM@%s 错%sbit 相位%s 眼图%.0f  RMS=%.1f  %s"
                                      % (r["asm_pos"], r["asm_err"], r["phase"],
                                         r["conf"], r.get("rms", 0), r.get("path", "")))
            parsed, pdiff = self._rx_params(r["decoded"])
            # ★ 解析出来的参数填进结构化表格，并自动切到"参数解析"页
            self._fill_tree(parsed, self.read_values())
            self._nb.select(0)
            t.insert("end", "\n【原始帧】\n")
            t.insert("end", self.hexdump(r["decoded"], prefix="  ") + "\n")
            t.insert("end", "\n【帧结构解析】\n")
            t.insert("end", "   主头 6B : %s\n"
                     % " ".join("%02X" % x for x in r["decoded"][:6]))
            t.insert("end", "   数据域   : %s\n"
                     % " ".join("%02X" % x for x in r["decoded"][6:38]))
            t.insert("end", "   FECF 2B  : %s\n"
                     % " ".join("%02X" % x for x in r["decoded"][38:40]))
            t.insert("end", "   参数集   : %s\n" % TP.profile_name())
            t.insert("end", "\n【射频路径判定】%s\n" % r.get("path", "?"))
            t.insert("end", "   接收 RMS = %.1f"
                            "（接了 SMA 环回电缆约 2446；仅芯片内部泄漏约 11）\n"
                     % r.get("rms", 0))
            t.insert("end", "\n★ 这一帧是真的从板子射频出去、经环回、再被板子收回来解出的。\n")
            t.insert("end", "★ 注意：AD9361 是收发一体芯片，不接电缆也能靠内部泄漏自环；\n"
                            "   所以要证明『电缆有效』必须看电平（上面那条 RMS）。\n")
        else:
            self.lbl_verdict.config(text="✗ 没解出（%s）" % r.get("reason", "?"), foreground="#c00")
            self._clear_tree()
            t.insert("end", "\n  解出前 64 字节: %s\n" % r.get("head", b"").hex())

    def clear_rx(self):
        self.txt_rx.delete("1.0", "end")
        self._clear_tree()
        self.lbl_verdict.config(text="（还没发送）", foreground="#888")
        self.lbl_info.config(text="")


def sent_eq(p, raw, sent):
    return sent.get(p["name"]) == raw


if __name__ == "__main__":
    Demo().mainloop()
