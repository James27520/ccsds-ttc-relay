#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main_3588_sim.py — RK3588 主程序骨架(脱离SDR可运行版)

现在的功能: 模拟一个"频率随时间漂移"的信号(模拟LEO多普勒),
           用FFT实时估计频偏, 真实值vs估计值记入CSV。
以后补接口: 只需改三处 TODO —— 换数据源、加转发、估计器换GPU。

运行: python3 -u main_3588_sim.py     (Ctrl+C 停止并打印统计)
"""

import time
import csv
import numpy as np

# ======================= 参数区 =======================
MODE             = "SIM"    # "SIM"=模拟信号(现在)  "SDR"=真实板子(预留)
SDR_URI          = "ip:192.168.3.10"   # TODO: 接SDR时用

FS               = 30_720_000          # 采样率(与转发链路一致)
BUF_SIZE         = 2**18               # 每块 262144 点 ≈ 8.5ms

SNR_DB           = 20.0                # 模拟信噪比(可改小做抗噪实验)
DOPPLER_MAX_HZ   = 40_000.0            # 模拟多普勒最大偏移 ±40kHz(LEO@2GHz量级)
DOPPLER_PERIOD_S = 20.0                # 多普勒变化周期 20 秒

EST_EVERY_N      = 16                  # 每 16 块估计一次
EST_FFT_LEN      = 8192                # FFT 点数(分辨率=FS/8192≈3.75kHz, 靠插值细化)

LOG_FILE         = "freq_est_log.csv"  # 结果日志, 拷回电脑画图
# ======================================================


# -------------------- 数据源层 --------------------
class SimSource:
    """模拟数据源: 频率按正弦漂移的单音+噪声(模拟LEO过顶的多普勒曲线)"""
    def __init__(self):
        self.n0 = 0                              # 全局采样计数(保证相位连续)
        self.true_f = 0.0                        # 当前块的真实频偏(供对比)
        self.noise_amp = 10 ** (-SNR_DB / 20.0)  # 噪声幅度

    def read(self):
        t = self.n0 / FS
        # 多普勒曲线: ±40kHz 正弦漂移 —— 以后可换成真实星历
        self.true_f = DOPPLER_MAX_HZ * np.sin(2 * np.pi * t / DOPPLER_PERIOD_S)
        n = self.n0 + np.arange(BUF_SIZE)
        sig = np.exp(1j * 2 * np.pi * self.true_f * n / FS)
        noise = (self.noise_amp / np.sqrt(2)) * (
            np.random.randn(BUF_SIZE) + 1j * np.random.randn(BUF_SIZE))
        self.n0 += BUF_SIZE
        return (sig + noise).astype(np.complex64)


class SdrSource:
    """真实SDR数据源 —— 预留! 等 LDSDR↔3588 网线打通后实现。
    TODO: 把 relay_3588.py 里验证过的参数原样搬来:
          uri=ip:192.168.3.10, FS=30.72M, RX_LO=2140M, TX_LO=2350M,
          手动增益50dB, TX衰减0dB, buffer=2^18, loopback=0"""
    def __init__(self):
        raise SystemExit("[!] SDR模式还没接线, 请先用 MODE='SIM' 跑通骨架")


# -------------------- 频偏估计层 --------------------
def estimate_freq_offset(iq, fs, fft_len):
    """CPU版频偏估计: 加窗FFT找峰 + 抛物线插值细化。
    TODO: GPU环境就绪后, 把本函数内部换成 OpenCL/Mali-G610 实现,
          函数输入输出不变, 主程序一行不用改。"""
    x = np.asarray(iq[:fft_len]) * np.hanning(fft_len)
    mag = np.abs(np.fft.fftshift(np.fft.fft(x)))
    k = int(np.argmax(mag))
    # 抛物线插值: 用峰值左右两点把估计精度细化到分辨率以内
    delta = 0.0
    if 0 < k < fft_len - 1:
        a, b, c = mag[k - 1], mag[k], mag[k + 1]
        denom = (a - 2 * b + c)
        if abs(denom) > 1e-12:
            delta = 0.5 * (a - c) / denom
    offset_hz = (k + delta - fft_len / 2) * fs / fft_len
    return offset_hz


# -------------------- 主流程 --------------------
def main():
    if MODE == "SIM":
        src = SimSource()
        print(f"[模式] 模拟信号 | 多普勒 ±{DOPPLER_MAX_HZ/1e3:.0f} kHz, "
              f"周期 {DOPPLER_PERIOD_S:.0f}s, SNR={SNR_DB:.0f}dB")
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

            # TODO(转发): 接SDR后在这里加一行 sdr.tx(iq)
            # 现在只统计接收功率, 占位验证数据流
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
            print(f"  日志已保存    : {LOG_FILE} (拷回电脑画曲线)")
            print("====================================")
        print("[退出] 完成")


if __name__ == "__main__":
    main()