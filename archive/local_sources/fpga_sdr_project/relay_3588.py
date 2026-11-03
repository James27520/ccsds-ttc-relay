#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
relay_3588.py — RK3588 控制 LDSDR(Pluto兼容固件) 弯管转发程序
链路: geeFlex eNB(2140MHz) --> LDSDR中继 --> 2350MHz 发出
运行: python3 -u relay_3588.py 2>&1 | tee relay_log_3588.txt
      (-u 必须加！否则管道缓冲会丢日志)
"""

import time
import numpy as np
import adi   # pyadi-iio, 需先 pip install pyadi-iio

# ================= 参数区(与 VM 版 relay_lte.py 一致) =================
SDR_URI        = "ip:192.168.2.1"   # LDSDR 地址(USB通道; 若用网线改 192.168.3.10)
FS             = 30_720_000         # 采样率 30.72 MSPS = 转发带宽
RX_LO          = 2_140_000_000      # 接收 2140 MHz(正对 geeFlex eNB)
TX_LO          = 2_350_000_000      # 发射 2350 MHz(频移 210 MHz)
RX_GAIN_DB     = 50                 # 手动增益, 规避 AGC 过冲
TX_ATTEN_DB    = 0                  # 发射衰减 0 dB
BUF_SIZE       = 2**18              # 262144 点/块 ≈ 8.5 ms
CTX_TIMEOUT_MS = 5000               # 超时保护, 防 -32/假死

# ---- 频偏估计外环(雏形): 每 N 块抽稀估一次, 目前 CPU 版 ----
ENABLE_FREQ_EST = True
EST_EVERY_N     = 64                # 每 64 块估一次
EST_FFT_LEN     = 4096              # 抽稀后的 FFT 点数
# =====================================================================


def connect_and_config():
    """连接 SDR 并完成配置, 关键参数设完立即读回打印(防驱动暗改)"""
    print(f"[连接] 正在连接 {SDR_URI} ...")
    sdr = adi.ad9361(uri=SDR_URI)
    sdr._ctx.set_timeout(CTX_TIMEOUT_MS)

    # --- 关键坑1: loopback 必须显式设 0 ---
    sdr.loopback = 0

    sdr.rx_enabled_channels = [0]
    sdr.tx_enabled_channels = [0]
    sdr.sample_rate = FS
    sdr.rx_lo = RX_LO
    sdr.tx_lo = TX_LO

    # --- 模拟滤波带宽: 设完必须读回确认, 驱动可能自动钳改 ---
    try:
        sdr.rx_rf_bandwidth = 20_000_000
        sdr.tx_rf_bandwidth = 20_000_000
    except Exception as e:
        print(f"[警告] RF带宽设置失败: {e}")

    # --- 关键坑2: 手动增益, 规避 AGC 暴涨-回落-不恢复 ---
    sdr.gain_control_mode_chan0 = "manual"
    sdr.rx_hardwaregain_chan0 = RX_GAIN_DB
    sdr.tx_hardwaregain_chan0 = TX_ATTEN_DB

    # --- FDD 模式(有些固件没有此属性, 失败不致命) ---
    try:
        sdr._ctrl.attrs["ensm_mode"].value = "fdd"
    except Exception:
        pass

    sdr.rx_buffer_size = BUF_SIZE

    # ================= 自检打印(读回真实值) =================
    print("=" * 56)
    print("[自检] 配置读回(以打印值为准, 不以设定值为准):")
    print(f"  sample_rate     = {sdr.sample_rate}")
    print(f"  rx_lo           = {sdr.rx_lo}")
    print(f"  tx_lo           = {sdr.tx_lo}")
    try:
        print(f"  rx_rf_bandwidth = {sdr.rx_rf_bandwidth}  <- 确认没被钳")
        print(f"  tx_rf_bandwidth = {sdr.tx_rf_bandwidth}")
    except Exception:
        pass
    print(f"  gain_ctrl_mode  = {sdr.gain_control_mode_chan0}")
    print(f"  rx_hw_gain      = {sdr.rx_hardwaregain_chan0} dB")
    print(f"  tx_hw_atten     = {sdr.tx_hardwaregain_chan0} dB")
    print(f"  loopback        = {sdr.loopback}  <- 必须是 0")
    print(f"  rx_buffer_size  = {BUF_SIZE}")
    print("=" * 56)
    return sdr


def estimate_freq_offset(iq, fs):
    """频偏估计(外环雏形, CPU版)。
    后面把本函数换成 OpenCL/Mali-G610 版本即可, 主循环不用动。"""
    x = np.asarray(iq[:EST_FFT_LEN])
    X = np.fft.fftshift(np.fft.fft(x))
    peak = int(np.argmax(np.abs(X)))
    offset_hz = (peak - EST_FFT_LEN // 2) * fs / EST_FFT_LEN
    power_db = 10 * np.log10(np.mean(np.abs(x) ** 2) + 1e-12)
    return offset_hz, power_db


def main():
    sdr = connect_and_config()
    ideal_blk_s = BUF_SIZE / FS          # 一块数据的"理论时长" ≈ 8.5 ms
    print(f"[转发] 开始转发 {RX_LO/1e6:.0f} -> {TX_LO/1e6:.0f} MHz, "
          f"Ctrl+C 停止")

    n_blk, n_fail = 0, 0
    t0 = time.time()
    try:
        while True:
            try:
                iq = sdr.rx()
                sdr.tx(iq)
                n_fail = 0
            except (TimeoutError, OSError) as e:
                # --- 关键坑3: 超时/假死不自闭, 报错后接着转 ---
                n_fail += 1
                print(f"[警告] 收发异常({e}), 连续第{n_fail}次, 继续重试")
                if n_fail >= 10:
                    print("[恢复] 连续失败过多, 重建连接...")
                    sdr = connect_and_config()
                    n_fail = 0
                time.sleep(0.2)
                continue

            n_blk += 1
            if n_blk % 16 == 0:
                dt = time.time() - t0
                rate = n_blk * BUF_SIZE / dt / 1e6        # 实际吞吐 MSPS
                duty = n_blk * ideal_blk_s / dt * 100     # 占空比 %
                print(f"[统计] {n_blk} 块 | 吞吐 {rate:.2f} MSPS | "
                      f"占空比 {duty:.1f}%")
                n_blk, t0 = 0, time.time()

            if ENABLE_FREQ_EST and (n_blk % EST_EVERY_N == 0):
                f_off, p_db = estimate_freq_offset(iq, FS)
                print(f"[频偏] 估计偏移 {f_off/1e3:+.1f} kHz | "
                      f"接收功率 {p_db:.1f} dBFS")

    except KeyboardInterrupt:
        print("\n[退出] 用户停止, 清理资源...")
    finally:
        try:
            sdr.tx_destroy_buffer()
        except Exception:
            pass
        print("[退出] 完成")


if __name__ == "__main__":
    main()
