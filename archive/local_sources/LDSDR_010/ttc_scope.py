#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ttc_scope.py -- 电脑上的实时频谱显示

通过 3588 的调试串口 (COM8)：
  1. 把 ttc_spectrum.py 传到 3588
  2. 运行它，3588 抓遥测板 RX 的 IQ、算 FFT、把 1KB 频谱发回来
  3. 电脑绘制实时频谱（ASCII 或 matplotlib 窗口）

用法：
    python ttc_scope.py                 # ASCII 频谱（终端里看）
    python ttc_scope.py --gui           # matplotlib 窗口
    python ttc_scope.py --frames 30     # 只收 30 帧
"""
import argparse
import base64
import os
import sys
import time

import numpy as np

sys.path.insert(0, r"E:\LDSDR_010")
from rk_console import RKConsole

LOCAL = r"E:\LDSDR_010\rk3588"
REMOTE = "/tmp/ttc"
FILE = "ttc_spectrum.py"

R = "\033[31m"; G = "\033[32m"; Y = "\033[33m"; C = "\033[36m"
B = "\033[1m"; D = "\033[2m"; N = "\033[0m"


def upload(rk):
    import base64 as b64mod
    data = open(os.path.join(LOCAL, FILE), "rb").read()
    s = b64mod.b64encode(data).decode("ascii")
    rk.run("mkdir -p %s" % REMOTE, wait=0.4)
    rk.run("rm -f %s/%s.b64" % (REMOTE, FILE), wait=0.3)
    CH = 640
    for i in range(0, len(s), CH):
        rk.run("printf '%%s' '%s' >> %s/%s.b64" % (s[i:i + CH], REMOTE, FILE),
               wait=0.25, timeout=40)
    rk.run("base64 -d %s/%s.b64 > %s/%s && rm -f %s/%s.b64"
           % (REMOTE, FILE, REMOTE, FILE, REMOTE, FILE), wait=0.6)
    sz = rk.run("wc -c < %s/%s" % (REMOTE, FILE), wait=0.4).strip()
    good = sz.isdigit() and int(sz) == len(data)
    print("   %s %-18s %d 字节" % (("✅" if good else "❌"), FILE, len(data)))
    return good


# ---------------------------------------------------------------------
def render_ascii(bins, fs, peak_khz, noise, peak_db, width=78, height=13):
    n = len(bins)
    db_top = peak_db + 6
    db_bot = noise - 6
    cols = []
    for c in range(width):
        a = int(c * n / width); b = max(a + 1, int((c + 1) * n / width))
        cols.append(max(bins[a:b]))

    out = []
    for row in range(height):
        db = db_top - (db_top - db_bot) * row / float(height - 1)
        line = "".join("#" if cols[c] >= db else ("_" if row == height - 1 else " ")
                       for c in range(width))
        out.append("%6.1f |%s|" % (db, line))

    f_lo = -fs / 2e3; f_hi = fs / 2e3
    lbl = [" "] * width
    for frac, txt in ((0.0, "%.0f" % f_lo), (0.5, "0"), (1.0, "%.0f" % f_hi)):
        p = int(frac * (width - len(txt)))
        for k, ch in enumerate(txt):
            if 0 <= p + k < width:
                lbl[p + k] = ch
    out.append("  kHz  |%s|" % "".join(lbl))
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port", nargs="?", default="COM8")
    ap.add_argument("--frames", type=int, default=0)
    ap.add_argument("--gui", action="store_true")
    ap.add_argument("--gain", type=int, default=20, help="RX 增益 dB")
    args = ap.parse_args()

    print("%s═══ 遥测板实时频谱（电脑显示）═══%s" % (B, N))
    print("  RX_LO 1000.000 MHz   fs 2.5 MSPS   FFT 4096×32 平均")
    print("  3588 抓 IQ → FFT → 1KB 频谱 → COM8 → 电脑\n")

    plt = None
    if args.gui:
        try:
            import matplotlib
            matplotlib.use("TkAgg")
            import matplotlib.pyplot as plt
            plt.ion()
            fig, ax = plt.subplots(figsize=(10, 4.5))
            line, = ax.plot(np.zeros(1024))
            ax.grid(alpha=0.3)
            ax.set_xlabel("频率相对 RX_LO (kHz)")
            ax.set_ylabel("功率 (dBFS)")
            ax.set_ylim(-100, 10)
        except Exception as e:
            print("%s matplotlib 不可用: %s%s\n" % (Y, e, N))

    try:
        with RKConsole(args.port) as rk:
            print("%s[上传]%s" % (C, N))
            if not upload(rk):
                return 2

            cmd = "cd %s && python3 %s %d %d" % (REMOTE, FILE,
                                              args.frames if args.frames else 0, args.gain)
            # ★ 关键：先杀掉上一次残留的进程，否则两个进程抢同一个 DMA 设备
            rk.run("kill -9 $(ps | grep -E '[t]tc_spectrum|[i]io_readdev' "
                   "| awk '{print $1}') 2>/dev/null; sleep 1; "
                   "echo -n 'SS '; ps | grep -cE '[t]tc_spectrum|[i]io_readdev'",
                   wait=2.5, timeout=40)
            print("%s[运行]%s %s\n" % (C, N, cmd))
            rk.sp.write(cmd + "\r\n")

            buf = bytearray()
            got = 0
            t0 = time.time()
            last_draw = 0
            while args.frames == 0 or got < args.frames:
                if time.time() - t0 > 900:
                    break
                d = rk.sp.read()
                if d:
                    buf += d
                txt = rk._clean(bytes(buf))
                while "\n" in txt:
                    line_s, txt = txt.split("\n", 1)
                    line_s = line_s.strip()
                    if not line_s.startswith("SPEC|"):
                        continue
                    parts = line_s.split("|")
                    if len(parts) < 9:
                        continue
                    try:
                        fs = int(parts[1]); rbw = float(parts[2])
                        pk_khz = float(parts[3]); noise = float(parts[4])
                        pk_db = float(parts[5])
                        chsel = int(parts[6])
                        stds = parts[7]
                        bins = np.frombuffer(base64.b64decode(parts[8]), dtype=np.uint8)
                        bins = bins.astype(np.float64) - 128.0
                    except Exception:
                        continue
                    got += 1
                    if args.gui and plt is not None:
                        f = np.linspace(-fs / 2e3, fs / 2e3, len(bins), endpoint=False)
                        line.set_data(f, bins)
                        ax.set_xlim(-fs / 2e3, fs / 2e3)
                        ax.set_title("帧 %d   峰 %+.1f kHz (%.1f dBFS)   底 %.1f dBFS"
                                     % (got, pk_khz, pk_db, noise))
                        fig.canvas.draw(); fig.canvas.flush_events()
                    else:
                        if got - last_draw >= 4 or got == 1:
                            last_draw = got
                            sys.stdout.write("\033[2J\033[H")
                            print("%s═══ 遥测板实时频谱（电脑显示）═══%s  帧 %d  RBW %.0f Hz"
                                  % (B, N, got, rbw))
                            print("   峰值 %+8.2f kHz  %7.1f dBFS     噪声底 %7.1f dBFS     SNR %5.1f dB"
                                  % (pk_khz, pk_db, noise, pk_db - noise))
                            print("   通道 std = [%s]   显示 ch%d（SNR 最好）"
                                  % (stds, chsel))
                            print(render_ascii(bins, fs, pk_khz, noise, pk_db))
                            print("%s  频率轴相对 RX_LO 1000.000 MHz → 绝对频率 = 1000.000 + 峰值/1000 MHz%s"
                                  % (D, N))
                buf = bytearray(txt.encode("utf-8", "replace"))
                time.sleep(0.02)

            print("\n\n收到 %d 帧，用时 %.1f 秒" % (got, time.time() - t0))
    except KeyboardInterrupt:
        print("\n已停止")
        return 0
    except Exception as e:
        print("\n%s出错: %s%s" % (R, e, N))
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
