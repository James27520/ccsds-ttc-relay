#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main_3588_sim_v2.py — 改进版: 限带搜索(利用多普勒物理先验)
与 v1 唯一区别: FFT找峰只在 ±SEARCH_MAX_HZ 范围内找,
噪声峰再也没有机会在 15 MHz 外冒名顶替。
运行: python3 -u main_3588_sim_v2.py   (Ctrl+C 停止并打印统计)
"""

import time
import csv
import numpy as np

# ======================= 参数区 =======================
MODE             = "SIM"
SDR_URI          = "ip:192.168.3.10"

FS               = 30_720_000
BUF_SIZE         = 2**18

SNR_DB           = -30.0               # 直接设在最恶劣点, 检验改进效果
DOPPLER_MAX_HZ   = 40_000.0
DOPPLER_PERIOD_S = 20.0

EST_EVERY_N      = 16
EST_FFT_LEN      = 8192
SEARCH_MAX_HZ    = 60_000              # 新增: 搜索范围(LEO@2GHz多普勒≤±48kHz, 留余量)

LOG_FILE         = "freq_est_log_v2.csv"
# ======================================================


class SimSource:
    """模拟数据源: 频率按正弦漂移的单音+噪声(与v1完全相同)"""
    def __init__(self):
        self.n0 = 0
        self.true_f = 0.0
        self.noise_amp = 10 ** (-SNR_DB / 20.0)

    def read(self):
        t = self.n0 / FS
        self.true_f = DOPPLER_MAX_HZ * np.sin(2 * np.pi * t / DOPPLER_PERIOD_S)
        n = self.n0 + np.arange(BUF_SIZE)
        sig = np.exp(1j * 2 * np.pi * self.true_f * n / FS)
        noise = (self.noise_amp / np.sqrt(2)) * (
            np.random.randn(BUF_SIZE) + 1j * np.random.randn(BUF_SIZE))
        self.n0 += BUF_SIZE
        return (sig + noise).astype(np.complex64)


class SdrSource:
    """真实SDR数据源 —— 预留! 等 LDSDR↔3588 网线打通后实现。"""
    def __init__(self):
        raise SystemExit("[!] SDR模式还没接线, 请先用 MODE='SIM' 跑通骨架")


def estimate_freq_offset(iq, fs, fft_len):
    """改进版: 限带搜索 + 抛物线插值。
    物理先验: LEO卫星在2GHz频段的多普勒频偏不超过±48kHz,
    所以只在中心±SEARCH_MAX_HZ内找峰 —— 范围外的噪声峰直接无视。"""
    x = np.asarray(iq[:fft_len]) * np.hanning(fft_len)
    mag = np.abs(np.fft.fftshift(np.fft.fft(x)))

    # ---- 限带: 只取中心±SEARCH_MAX_HZ的格子 ----
    bin_hz = fs / fft_len                       # 每格 3.75 kHz
    half = int(SEARCH_MAX_HZ / bin_hz)          # ±60kHz -> ±16格
    c = fft_len // 2
    lo, hi = c - half, c + half + 1
    k = lo + int(np.argmax(mag[lo:hi]))         # argmax只在窗口内找

    # ---- 抛物线插值(与v1相同) ----
    delta = 0.0
    if 0 < k < fft_len - 1:
        a, b, cc = mag[k - 1], mag[k], mag[k + 1]
        denom = (a - 2 * b + cc)
        if abs(denom) > 1e-12:
            delta = 0.5 * (a - cc) / denom
    offset_hz = (k + delta - fft_len / 2) * fs / fft_len
    return offset_hz


def main():
    if MODE == "SIM":
        src = SimSource()
        print(f"[模式] 模拟信号v2(限带±{SEARCH_MAX_HZ/1e3:.0f}kHz) | "
              f"多普勒 ±{DOPPLER_MAX_HZ/1e3:.0f} kHz, SNR={SNR_DB:.0f}dB")
    else:
        src = SdrSource()

    f_csv = open(LOG_FILE, "w", newline="")
    writer = csv.writer(f_csv)
    writer.writerow(["time_s", "true_offset_Hz", "est_offset_Hz", "error_Hz"])

    print(f"[运行] 块大小 {BUF_SIZE} 点 | 每 {EST_EVERY_N} 块估计一次 | "
          f"Ctrl+C 停止")
    errors, n_blk, t_start = [], 0, time.time()
    t_stat = t_start

    try:
        while True:
            iq = src.read()
            n_blk += 1
            _pwr = 10 * np.log10(np.mean(np.abs(iq) ** 2) + 1e-12)

            if n_blk % EST_EVERY_N == 0:
                f_est = estimate_freq_offset(iq, FS, EST_FFT_LEN)
                f_true = getattr(src, "true_f", float("nan"))
                err = f_est - f_true
                errors.append(abs(err))
                t_now = time.time() - t_start
                writer.writerow([f"{t_now:.3f}", f"{f_true:.1f}",
                                 f"{f_est:.1f}", f"{err:.1f}"])
                print(f"[估计] t={t_now:6.1f}s | 真实 {f_true/1e3:+7.2f} kHz"
                      f" | 估计 {f_est/1e3:+7.2f} kHz"
                      f" | 误差 {err/1e3:+6.3f} kHz")

            if n_blk % 64 == 0:
                dt = time.time() - t_stat
                rate = 64 * BUF_SIZE / dt / 1e6
                print(f"[统计] 处理速度 {rate:.1f} MSPS(等效)")
                t_stat = time.time()

    except KeyboardInterrupt:
        pass
    finally:
        f_csv.close()
        if errors:
            e = np.array(errors)
            print("\n========== 汇总(报告素材) ==========")
            print(f"  估计次数      : {len(e)}")
            print(f"  平均误差      : {e.mean()/1e3:.3f} kHz")
            print(f"  最大误差      : {e.max()/1e3:.3f} kHz")
            print(f"  日志已保存    : {LOG_FILE}")
            print("====================================")
        print("[退出] 完成")


if __name__ == "__main__":
    main()
