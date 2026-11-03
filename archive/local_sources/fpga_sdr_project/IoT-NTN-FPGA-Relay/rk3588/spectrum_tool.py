#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
spectrum_tool.py -- 频谱接收 / 显示 / 信道检测 命令行工具（RK3588 侧）

用法
----
    python3 spectrum_tool.py demo                 # 合成数据演示，不需要硬件
    python3 spectrum_tool.py recv                 # 从载荷收频谱并显示
    python3 spectrum_tool.py recv --ascii-only    # 只出字符图（串口终端友好）
    python3 spectrum_tool.py watch                # 连续监视，信道出现/消失打日志
    python3 spectrum_tool.py png out.png          # 存一张频谱图（合成数据）
    python3 spectrum_tool.py bench                # FFT/检测性能基准

设计说明
--------
* **字符图**是主力显示方式——因为 3588 常用串口终端调试，没法看图。
* 检测用 channel_detect.py 的 CFAR，虚警率恒定，适应噪声底漂移。
* 图形显示（matplotlib/png）作为可选，装了才用。
"""

import argparse
import math
import sys
import time

sys.path.insert(0, "/home/elf/ldsdr")
try:
    sys.path.insert(0, r"E:\LDSDR_010\rk3588")
except Exception:
    pass

from spectrum import (SpectrumFrame, synth_frame, decode_frame,
                      SpectrumReceiver, FS_DEFAULT, DB_OFFSET)   # noqa: E402
import channel_detect as cd                                     # noqa: E402


# =====================================================================
#  字符频谱图
# =====================================================================
def render_ascii(frame, width=78, height=14, channels=None,
                 db_top=None, db_bot=None, title=None):
    """把一帧画成字符频谱图。返回多行字符串。"""
    bins = frame.bins
    n = len(bins)
    if n == 0:
        return "(空帧)"

    if db_top is None:
        db_top = max(bins) + 2
    if db_bot is None:
        db_bot = frame.noise_dbfs - 8

    # 把 N 个 bin 压成 width 列（取每列最大值，保留窄带信号）
    cols = []
    for c in range(width):
        a = int(c * n / width)
        b = max(a + 1, int((c + 1) * n / width))
        cols.append(max(bins[a:b]))

    # 频率刻度
    f_lo = -n / 2.0 * frame.rbw_hz + frame.center_hz
    f_hi = (n / 2.0) * frame.rbw_hz + frame.center_hz

    lines = []
    if title:
        lines.append(title)

    # 检测到的信道在哪些列
    ch_cols = {}
    for ch in (channels or []):
        c0 = int((ch.lo_bin) / n * width)
        c1 = max(c0, int((ch.hi_bin + 1) / n * width) - 1)
        ch_cols[ch.id] = (c0, c1)

    for row in range(height):
        # 这一行对应的 dB
        db = db_top - (db_top - db_bot) * row / float(height - 1)
        s = []
        for c in range(width):
            if cols[c] >= db:
                s.append("#")
            elif row == height - 1:
                s.append("_")
            else:
                s.append(" ")
        mark = ""
        for cid, (c0, c1) in ch_cols.items():
            mark = mark  # 占位：信道标记单独画在下面
        lines.append("%6.1f |%s|" % (db, "".join(s)))

    # 底部横轴
    axis = ["-"] * width
    for cid, (c0, c1) in ch_cols.items():
        for c in range(c0, min(c1 + 1, width)):
            axis[c] = "^" if c == (c0 + c1) // 2 else "="
    lines.append("       |%s|" % "".join(axis))

    # 频率刻度行
    lbl = [" "] * width
    for frac, txt in ((0.0, "%.1f" % (f_lo / 1e6)),
                      (0.5, "%.1f" % (frame.center_hz / 1e6)),
                      (1.0, "%.1f" % (f_hi / 1e6))):
        p = int(frac * (width - len(txt)))
        for k, ch in enumerate(txt):
            if 0 <= p + k < width:
                lbl[p + k] = ch
    lines.append(" MHz   %s   (相对 RX_LO, RBW %.1f kHz)" % ("".join(lbl), frame.rbw_hz / 1e3))
    return "\n".join(lines)


def print_channels(channels):
    if not channels:
        print("  信道: 无（频谱干净）")
        return
    print("  信道 %d 个:" % len(channels))
    print("    ID   中心频率      带宽      峰值      噪声底     SNR     连续")
    for c in sorted(channels, key=lambda x: x.center_hz):
        print("    #%-3s %+9.3fMHz %8.1fkHz %8.1fdB %8.1fdB %7.1fdB %5d帧"
              % (c.id, c.center_hz / 1e6, c.bw_hz / 1e3,
                 c.peak_dbfs, c.noise_dbfs, c.snr_db, c.age))


def show_frame(frame, channels, tracker_log=None, width=78, height=14):
    print(render_ascii(frame, width=width, height=height, channels=channels,
                       title="─" * 78))
    print("  帧 #%-6d N=%d  RBW=%.1fkHz  噪声底=%.1fdBFS  峰值=%.1fdBFS  "
          "平均=%d次%s"
          % (frame.frame_no, frame.n, frame.rbw_hz / 1e3, frame.noise_dbfs,
             frame.peak_dbfs, frame.avg_count,
             "  ⚠饱和" if frame.saturated else ""))
    print_channels(channels)
    if tracker_log:
        for l in tracker_log:
            print("  " + l)
    print("─" * 78)


# =====================================================================
#  命令实现
# =====================================================================
def cmd_demo(args):
    print("=== 合成数据演示（不需要硬件）===")
    tracker = cd.ChannelTracker()
    truth = [(-6.0e6, 22, 5), (-1.5e6, 30, 2), (4.0e6, 18, 12)]
    for k in range(args.frames):
        # 第 3 帧起 +8MHz 冒出一个新信号，第 6 帧起 -6MHz 那个消失
        cur = list(truth)
        if k >= 2:
            cur.append((8.0e6, 25, 3))
        if k >= 5:
            cur = [t for t in cur if abs(t[0] + 6.0e6) > 1]
        fr = synth_frame(n=1024, fs=FS_DEFAULT, noise_dbfs=-60.0,
                         carriers=cur, avg_count=64, frame_no=k, seed=42 + k)
        chans, info = cd.detect(fr, tracker=tracker)
        log = []
        for c in info["appeared"]:
            log.append("★ 新信道 #%s  %+.3f MHz  bw %.0f kHz  SNR %.1f dB"
                       % (c.id, c.center_hz / 1e6, c.bw_hz / 1e3, c.snr_db))
        for c in info["gone"]:
            log.append("✖ 信道 #%s 消失  %+.3f MHz" % (c.id, c.center_hz / 1e6))
        show_frame(fr, chans, log if log else None)
        time.sleep(args.interval)
    return 0


def cmd_recv(args):
    from relay_link import RelayLink
    from serial_port import list_ports

    port = args.port
    if not port:
        ports = list_ports()
        port = ports[0] if ports else None
    if not port:
        print("找不到串口，用 --port 指定", file=sys.stderr)
        return 2

    lk = RelayLink(port, args.baud)
    lk.open()
    print("已连接 %s @%d" % (port, args.baud))

    # 告诉载荷开始连续发频谱
    try:
        lk.command("spectrum_stream 1")
    except Exception:
        pass

    rx = SpectrumReceiver(lk)
    tracker = cd.ChannelTracker()
    n = 0
    t0 = time.time()
    try:
        while args.frames == 0 or n < args.frames:
            frames = rx.pump(seconds=0.5)
            for fr in frames:
                chans, info = cd.detect(fr, tracker=tracker)
                log = []
                for c in info["appeared"]:
                    log.append("★ 新信道 #%s  %+.3f MHz  SNR %.1f dB"
                               % (c.id, c.center_hz / 1e6, c.snr_db))
                for c in info["gone"]:
                    log.append("✖ 信道 #%s 消失" % c.id)
                show_frame(fr, chans, log if log else None)
                n += 1
            if not frames and time.time() - t0 > 5 and n == 0:
                print("5 秒内没收到频谱帧。")
                print("检查：PL 侧频谱引擎是否已实现？载荷是否支持 spectrum_stream？")
                break
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        try:
            lk.command("spectrum_stream 0")
        except Exception:
            pass
        lk.close()
    dt = time.time() - t0
    print("\n共收 %d 帧，用时 %.1f 秒（%.2f 帧/秒），坏帧 %d"
          % (n, dt, n / dt if dt else 0, rx.bad))
    return 0


def cmd_watch(args):
    """连续监视，只在信道出现/消失时打日志（适合长时间挂机）。"""
    tracker = cd.ChannelTracker()
    t0 = time.time()
    k = 0
    try:
        while True:
            cur = [(-1.5e6, 30, 2)]
            if (k // 5) % 2:
                cur.append((3.0e6, 20, 6))
            fr = synth_frame(n=1024, fs=FS_DEFAULT, noise_dbfs=-60.0,
                             carriers=cur, avg_count=64, frame_no=k,
                             seed=1000 + k)
            chans, info = cd.detect(fr, tracker=tracker)
            ts = time.strftime("%H:%M:%S")
            for c in info["appeared"]:
                print("[%s] ★ 新信道 #%-2s %+9.3f MHz  bw %6.0f kHz  SNR %5.1f dB"
                      % (ts, c.id, c.center_hz / 1e6, c.bw_hz / 1e3, c.snr_db))
            for c in info["gone"]:
                print("[%s] ✖ 信道 #%-2s 消失     %+9.3f MHz"
                      % (ts, c.id, c.center_hz / 1e6))
            k += 1
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n已停止，共处理 %d 帧（%.0f 秒）" % (k, time.time() - t0))
    return 0


def cmd_png(args):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("没装 matplotlib，无法出图", file=sys.stderr)
        return 2

    fr = synth_frame(n=1024, fs=FS_DEFAULT, noise_dbfs=-60.0,
                     carriers=[(-6.0e6, 22, 5), (-1.5e6, 30, 2), (4.0e6, 18, 12)],
                     avg_count=64, seed=42)
    chans, info = cd.detect(fr, tracker=None)

    f = [x / 1e6 for x in fr.freq_axis()]
    fig, ax = plt.subplots(figsize=(11, 4.5), dpi=120)
    ax.plot(f, fr.bins, lw=0.7, color="#1f77b4", label="功率谱")
    ax.plot(f, info["thresh"], lw=0.7, ls="--", color="#d62728",
            label="CFAR 门限")
    ax.axhline(fr.noise_dbfs, lw=0.7, ls=":", color="#2ca02c",
               label="噪声底 %.1f dBFS" % fr.noise_dbfs)
    for c in chans:
        ax.axvspan(c.freq_lo / 1e6, c.freq_hi / 1e6, color="#ff7f0e", alpha=0.25)
        ax.annotate("#%s\n%.0fkHz\n%.1fdB" % (c.id, c.bw_hz / 1e3, c.snr_db),
                    xy=(c.center_hz / 1e6, c.peak_dbfs),
                    xytext=(0, 12), textcoords="offset points",
                    ha="center", fontsize=7)
    ax.set_xlabel("频率相对 RX_LO (MHz)")
    ax.set_ylabel("功率 (dBFS)")
    ax.set_title("LDSDR 频谱  N=%d  RBW=%.1f kHz  平均 %d 次"
                 % (fr.n, fr.rbw_hz / 1e3, fr.avg_count))
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="lower right")
    ax.set_xlim(f[0], f[-1])
    fig.tight_layout()
    fig.savefig(args.out)
    print("已保存 %s（检测到 %d 个信道）" % (args.out, len(chans)))
    for c in chans:
        print("   ", c)
    return 0


def cmd_bench(args):
    """性能基准：这是决定要不要上 GPU 的依据。"""
    import numpy as np
    print("=== 性能基准（RK3588, 8×A76/A55）===")
    n = args.n
    iters = args.iters

    x = (np.random.randn(n) + 1j * np.random.randn(n)).astype(np.complex64)

    # numpy FFT
    t0 = time.time()
    for _ in range(iters):
        X = np.fft.fft(x)
    t_fft = (time.time() - t0) / iters
    print("  numpy FFT  %5d 点: %8.1f us/次  (%.2f MSPS 等效)"
          % (n, t_fft * 1e6, n / t_fft / 1e6))

    # 功率谱（dB）
    t0 = time.time()
    for _ in range(iters):
        p = 10.0 * np.log10(np.abs(X) ** 2 + 1e-30)
    t_psd = (time.time() - t0) / iters
    print("  功率谱(dB) %5d 点: %8.1f us/次" % (n, t_psd * 1e6))

    # 检测
    fr = SpectrumFrame(list(p), FS_DEFAULT, 0, 0, 1, -60, -20, False)
    t0 = time.time()
    for _ in range(max(1, iters // 4)):
        cd.detect(fr, tracker=None)
    t_det = (time.time() - t0) / max(1, iters // 4)
    print("  CFAR 检测  %5d 点: %8.1f us/次" % (n, t_det * 1e6))

    total = t_fft + t_psd + t_det
    print("\n  单帧总耗时 %.1f us -> 理论上限 %.0f 帧/秒" % (total * 1e6, 1 / total))
    print("  UART 115200 限制: 1050 字节/帧 -> %.1f 帧/秒" % (11520 / 1050.0))
    print("\n  结论: %s"
          % ("CPU 处理速度远超 UART 带宽，**不需要 GPU**，瓶颈在串口。"
             if 1 / total > 11520 / 1050.0 else
             "CPU 是瓶颈，值得考虑 GPU 加速。"))
    return 0


# =====================================================================
def main():
    ap = argparse.ArgumentParser(
        description="LDSDR 频谱接收/显示/检测工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("demo", help="合成数据演示")
    p.add_argument("--frames", type=int, default=8)
    p.add_argument("--interval", type=float, default=0.6)
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("recv", help="从载荷收频谱")
    p.add_argument("--port")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--frames", type=int, default=0, help="0=无限")
    p.set_defaults(func=cmd_recv)

    p = sub.add_parser("watch", help="长时间监视，只报信道变化")
    p.add_argument("--interval", type=float, default=0.5)
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("png", help="存一张频谱图")
    p.add_argument("out")
    p.set_defaults(func=cmd_png)

    p = sub.add_parser("bench", help="性能基准")
    p.add_argument("--n", type=int, default=1024)
    p.add_argument("--iters", type=int, default=200)
    p.set_defaults(func=cmd_bench)

    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
