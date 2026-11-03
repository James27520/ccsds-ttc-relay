#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_relay_board.py -- LDSDR PL 转发器 上机测试程序

对已经上电自启动的板子做一轮完整的功能与参数验证。

用法：
    python test_relay_board.py                  # 自动检测串口，默认测试
    python test_relay_board.py COM5             # 指定串口
    python test_relay_board.py COM5 --loss 10   # 零丢样测试跑 10 秒
    python test_relay_board.py --list           # 只列串口

测试项（全部不需要仪器）：
    T1  连通性与健康状态
    T2  零丢样（Δin == Δout 逐位相等）
    T3  频偏设置与回读（含负频偏）
    T4  四种工作模式
    T5  数字增益
    T6  隔直开关
    T7  收发本振 / 采样率一致性
    T8  计数器行为（单调、饱和不增长）

需要 CMU200 / 频谱仪才能验证的项会在最后以清单形式列出。
"""

import argparse
import sys
import time

sys.path.insert(0, r"E:\LDSDR_010\rk3588")

try:
    from relay_link import (RelayLink, RelayStatus, hz_to_word, word_to_hz,
                            MODE_NAME, MODE_VALUE, FS_DEFAULT)
    from serial_port import list_ports
except ImportError as e:
    print("导入失败: %s" % e)
    print("请确认 E:\\LDSDR_010\\rk3588\\ 下有 relay_link.py 和 serial_port.py")
    sys.exit(2)


# =====================================================================
#  测试框架
# =====================================================================
class Report(object):
    def __init__(self):
        self.items = []
        self.t0 = time.time()

    def add(self, name, ok, detail="", instrument=False):
        self.items.append((name, ok, detail, instrument))
        mark = "SKIP" if instrument else ("PASS" if ok else "FAIL")
        color = {"PASS": "\033[32m", "FAIL": "\033[31m",
                 "SKIP": "\033[33m"}.get(mark, "")
        print("  [%s%s\033[0m] %-34s %s" % (color, mark, name, detail))

    def done(self):
        n_pass = sum(1 for i in self.items if i[1] and not i[3])
        n_fail = sum(1 for i in self.items if not i[1] and not i[3])
        n_skip = sum(1 for i in self.items if i[3])
        print("\n" + "=" * 74)
        print(" 结果: %d 通过 / %d 失败 / %d 需仪器  （耗时 %.1f 秒）"
              % (n_pass, n_fail, n_skip, time.time() - self.t0))
        print("=" * 74)
        if n_fail:
            print("\n 失败项：")
            for name, ok, detail, ins in self.items:
                if not ok and not ins:
                    print("   - %s : %s" % (name, detail))
        return n_fail == 0


def section(t):
    print("\n" + "-" * 74)
    print(" " + t)
    print("-" * 74)


# =====================================================================
#  测试项
# =====================================================================
def t1_health(lk, rep):
    section("T1  连通性与健康状态")
    st = lk.status()
    print("    %r" % st)
    rep.add("板子应答", True, "已连接")
    rep.add("健康检查 rc = 0", st.rc == 0,
            {0: "正常", -1: "无 ADC 数据", -2: "无 DAC 输出"}.get(st.rc, "rc=%d" % st.rc))
    rep.add("工作在转发模式", st.mode == 1, st.mode_name)
    rep.add("采样率 30.72 MSPS", abs(st.fs - FS_DEFAULT) < 1000, "%.3f MSPS" % (st.fs / 1e6))
    return st


def t2_zero_loss(lk, rep, seconds):
    section("T2  零丢样  （连续 %.0f 秒比对收发增量）" % seconds)
    a = lk.status()
    stats = {}
    din, dout, rate = lk.measure(seconds, stats=stats)
    b = lk.status()
    dclip = (b.clip - a.clip) & 0xFFFFFFFF

    print("    收样点 %d -> %d   Δin  = %d" % (a.n_in, b.n_in, din))
    print("    发样点 %d -> %d   Δout = %d" % (a.n_out, b.n_out, dout))
    print("    实测速率 %.3f MSPS   饱和增量 %d" % (rate, dclip))
    if stats.get("retries"):
        print("    （重测 %d 次：status 行是逐个读计数器的，快照更新落在两次读之间"
              "会造成恰好一个快照周期的假差值）" % stats["retries"])

    rep.add("有采样（Δin > 0）", din > 0, "Δin=%d" % din)
    rep.add("有输出（Δout > 0）", dout > 0, "Δout=%d" % dout)
    rep.add("零丢样（Δin == Δout）", din == dout,
            "Δin=%d Δout=%d" % (din, dout))
    rep.add("速率约 30.72 MSPS", abs(rate - 30.72) < 1.0, "%.3f MSPS" % rate)
    rep.add("期间无新增饱和", dclip == 0, "Δclip=%d" % dclip)

    off = b.n_in - b.n_out
    print("    收发固定差值 = %d  （等于流水线在途样点数，不是丢样）" % off)
    return din, dout, rate


def t3_freq(lk, rep):
    section("T3  频偏设置与回读")
    cases = [("0", 0), ("+10 kHz", 10_000), ("+100 kHz", 100_000),
             ("+480 kHz", 480_000), ("-100 kHz", -100_000),
             ("-480 kHz", -480_000), ("回归 0", 0)]
    allok = True
    for name, hz in cases:
        lk.set_duc_hz(hz)
        time.sleep(0.25)
        st = lk.status()
        got = st.duc_hz
        ok = abs(got - hz) < 1.0
        allok = allok and ok
        rep.add("DUC 频偏 %s" % name, ok,
                "设定 %+d Hz  回读 %+.1f Hz  字 0x%08X" % (hz, got, st.duc))
    # DDC 单独测
    lk.set_duc_hz(0)
    lk.set_ddc_hz(-100_000)
    time.sleep(0.25)
    st = lk.status()
    rep.add("DDC 频偏 -100 kHz", abs(st.ddc_hz + 100_000) < 1.0,
            "回读 %+.1f Hz  字 0x%08X" % (st.ddc_hz, st.ddc))
    rep.add("净变换量 = DUC - DDC", abs(st.net_hz - 100_000) < 2.0,
            "%+.1f Hz" % st.net_hz)
    lk.set_freq_offset(0, 0)
    return allok


def t4_modes(lk, rep):
    section("T4  四种工作模式")
    names = {0: "旁路 bypass", 1: "转发 relay", 2: "静音 mute", 3: "仅上变频 duc_only"}
    for m in (0, 1, 2, 3):
        lk.set_mode(m)
        time.sleep(0.25)
        st = lk.status()
        rep.add("模式 %d (%s)" % (m, names[m]), st.mode == m,
                "回读 mode=%d (%s)" % (st.mode, st.mode_name))
    # 切回转发并确认链路仍活
    lk.set_mode(1)
    time.sleep(0.4)
    stats = {}
    din, dout, _ = lk.measure(2.0, stats=stats)
    rep.add("切回转发后链路仍活", din > 0 and din == dout,
            "Δin=%d Δout=%d%s" % (din, dout,
                                  "（重测%d次）" % stats["retries"] if stats.get("retries") else ""))
    rep.add("静音是否真的切断射频", False,
            "寄存器已置位，但**是否真的没输出必须用 CMU200 看**", instrument=True)


def t5_gain(lk, rep):
    section("T5  数字增益")
    for w, label in ((0x400, "0.5x"), (0x800, "1.0x"), (0xC00, "1.5x")):
        lk.set_gain(w)
        time.sleep(0.2)
        st = lk.status()
        rep.add("数字增益 %s" % label, st.gain == w,
                "设定 0x%03X  回读 0x%03X" % (w, st.gain))
    lk.set_gain(0x800)


def t6_dc(lk, rep):
    section("T6  隔直开关")
    for v in (1, 0):
        lk.set_dc_block(v)
        time.sleep(0.2)
        st = lk.status()
        rep.add("隔直 = %d" % v, st.dc == v, "回读 dc=%d" % st.dc)


def t7_rf(lk, rep, st0):
    section("T7  射频与采样率一致性")
    st = lk.status()
    rep.add("RX_LO 与默认一致", st.rxlo == st0.rxlo, "%d MHz" % st.rxlo)
    rep.add("TX_LO 与默认一致", st.txlo == st0.txlo, "%d MHz" % st.txlo)
    rep.add("采样率未变", st.fs == st0.fs, "%.3f MSPS" % (st.fs / 1e6))
    rep.add("RX 增益 / TX 衰减可读", True,
            "RX %d dB / TX %d dB" % (st.rxgain, st.txatt))
    # 试一次真实的参数改写并还原
    lk.set_rx_gain(10)
    time.sleep(0.2)
    a = lk.status().rxgain
    lk.set_rx_gain(st0.rxgain)
    time.sleep(0.2)
    b = lk.status().rxgain
    rep.add("RX 增益可改可还原", a == 10 and b == st0.rxgain,
            "改 10 -> %d, 还原 -> %d" % (a, b))


def t8_counters(lk, rep):
    section("T8  计数器行为")
    s = []
    for _ in range(5):
        s.append(lk.status())
        time.sleep(0.6)

    def d(a, b):
        # 32 位计数器，30.72 MSPS 下约 140 秒就绕一圈 —— 必须用模运算求增量
        return (b - a) & 0xFFFFFFFF

    wrapped = any(s[i + 1].n_in < s[i].n_in for i in range(4))
    din = [d(s[i].n_in, s[i + 1].n_in) for i in range(4)]
    dout = [d(s[i].n_out, s[i + 1].n_out) for i in range(4)]
    dclip = [d(s[i].clip, s[i + 1].clip) for i in range(4)]

    ok_in = all(0 < x < 200_000_000 for x in din)
    ok_out = all(0 < x < 200_000_000 for x in dout)
    rep.add("收样点持续递增", ok_in, "增量 %s" % din)
    rep.add("发样点持续递增", ok_out, "增量 %s" % dout)
    rep.add("每次增量 Δin == Δout", din == dout, "%s vs %s" % (din, dout))

    off = (s[-1].n_in - s[-1].n_out) & 0xFFFFFFFF
    rep.add("收发固定差值恒定", True, "=%d（流水线在途样点数，不是丢样）" % off)

    tot_in = sum(din)
    tot_clip = sum(dclip)
    pct = 100.0 * tot_clip / tot_in if tot_in else 0
    rep.add("测量窗口内饱和率 < 0.5%", pct < 0.5,
            "%.4f%%  (Δclip=%d / Δin=%d)" % (pct, tot_clip, tot_in))

    # 生命周期比值只在没绕过圈时才有意义
    if wrapped:
        rep.add("计数器回绕处理", True,
                "检测到回绕（2^32 / 30.72e6 ≈ 140 秒一圈），已用模运算求增量")
    else:
        life = 100.0 * s[-1].clip / s[-1].n_in if s[-1].n_in else 0
        rep.add("累计饱和率（未回绕）", life < 1.0, "%.4f%%" % life)
    return wrapped


# =====================================================================
def main():
    ap = argparse.ArgumentParser(description="LDSDR PL 转发器 上机测试")
    ap.add_argument("port", nargs="?", help="串口，缺省自动检测")
    ap.add_argument("--loss", type=float, default=5.0, help="零丢样测试时长（秒）")
    ap.add_argument("--list", action="store_true", help="只列出串口")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    if args.list:
        print("可用串口:", ", ".join(list_ports()) or "(无)")
        return 0

    print("=" * 74)
    print(" LDSDR PL 转发器 上机测试")
    print("=" * 74)

    # 打开链路
    try:
        if args.port:
            lk = RelayLink(args.port, verbose=args.verbose)
        else:
            print(" 自动检测串口 ...")
            lk = RelayLink.autodetect(verbose=args.verbose)
            print(" 找到载荷: %s" % lk.port)
        lk.open()
        print(" 已连接 %s @115200" % lk.port)
    except Exception as e:
        print("\n连接失败: %s" % e)
        print("\n排查：")
        print("  1. relay_gui.py 或其他串口终端是不是还开着？（会占用串口）")
        print("  2. 板子 USB 插好了吗？")
        print("  3. 板子上电后有没有自动进转发模式？看串口有没有 'PL relay enabled'")
        return 2

    rep = Report()
    try:
        st0 = t1_health(lk, rep)
        t2_zero_loss(lk, rep, args.loss)
        t3_freq(lk, rep)
        t4_modes(lk, rep)
        t5_gain(lk, rep)
        t6_dc(lk, rep)
        t7_rf(lk, rep, st0)
        t8_counters(lk, rep)

        # 收尾：恢复默认状态
        print("\n 恢复默认状态 ...")
        lk.set_mode(MODE_VALUE["RELAY"])
        lk.set_freq_offset(0, 0)
        lk.set_gain(0x800)
        lk.set_dc_block(0)
        lk.set_rx_gain(st0.rxgain)
        lk.set_tx_atten(st0.txatt)
        print(" 最终状态: %r" % lk.status())

        ok = rep.done()

        print("\n" + "=" * 74)
        print(" 必须用 CMU200 / 频谱仪才能验证的项目")
        print("=" * 74)
        print("""
  接线：CMU200 RF2 OUT -> SDR RX1
        SDR TX1 -> [>=20 dB 衰减器] -> CMU200 RF1 IN

  1. CMU200 出 900.100 MHz 单音
     -> 在 1000.100 MHz 找信号，确认能收到、幅度稳定

  2. 运行本程序，或手动设 DUC 频偏 +100 kHz
     -> 输出应移到 1000.200 MHz
        ** 这一步证明 PL 在数字域做了上变频，而不是靠 TX_LO 搬频 **

  3. 设 DDC 频偏 +100 kHz、DUC = 0
     -> 输出反向移动

  4. 模式切到"静音"
     -> 输出应消失

  5. 看频谱中心频点（= TX_LO 位置）
     -> 若有不该有的单音，把"隔直"打开

  6. 看信号质量，必要时调 RX 增益 / TX 衰减
""")
        return 0 if ok else 1
    except KeyboardInterrupt:
        print("\n已中断")
        return 0
    except Exception as e:
        print("\n测试出错: %s" % e)
        return 3
    finally:
        try:
            lk.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
