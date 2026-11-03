import adi
import numpy as np
import matplotlib.pyplot as plt
import time

# ==================== 参数区 ====================
IP        = "ip:192.168.2.1"
FS        = 3_072_000
RX_LO     = 2_137_000_000      # 收 2140（偏3M）
TX_LO     = 2_397_000_000      # 发 2400.0（=2397+3）
RX_BW     = 20_000_000
TX_BW     = 20_000_000
TX_ATTEN  = 0
BUF_LEN   = 2**18
MODE      = "VIEW"             # ★ "VIEW"=实时频谱图(不转发) | "RELAY"=纯文字转发(不画图)
ENABLE_DSP = False             # ★ DDC/DUC开关：False=直通(省CPU,输出一样) True=演示流水线
# ================================================

sdr = adi.Pluto(IP)
sdr.sample_rate     = FS
sdr.rx_rf_bandwidth = RX_BW
sdr.tx_rf_bandwidth = TX_BW
sdr.rx_lo           = RX_LO
sdr.tx_lo           = TX_LO
sdr.rx_buffer_size  = BUF_LEN

sdr.gain_control_mode_chan0 = "manual"
sdr.rx_hardwaregain_chan0   = 50       


#------------------------------------------------

if ENABLE_DSP:  # 预生成NCO表（只生成用到的那个）
    t = np.arange(BUF_LEN) / FS
    NCO_DDC = np.exp(-2j*np.pi*3e6*t)
    NCO_DUC = np.exp(+2j*np.pi*3e6*t)

def pipeline(x):
    """一条线穿过 DDC→(处理)→DUC。对应FPGA流水线"""
    if ENABLE_DSP:
        x = x * NCO_DDC          # DDC
        x = x * NCO_DUC          # DUC
    return x

if MODE == "VIEW":
    # ---------- 模式1：实时频谱（像示波器，但在频域） ----------
    print("VIEW模式：实时频谱，Ctrl+C退出（不转发）")
    win   = np.hanning(BUF_LEN)
    freqs = np.fft.fftshift(np.fft.fftfreq(BUF_LEN, 1/FS)) / 1e6
    plt.ion()
    fig, ax = plt.subplots(figsize=(11, 5))
    line, = ax.plot(freqs, np.full(BUF_LEN, -120), lw=0.8, color='lime')
    ax.axvline(0, color='r', ls='--', lw=1, label='0 Hz (DC trap)')
    ax.axvline(3, color='g', ls='--', lw=1, label='+3 MHz (LTE center)')
    ax.set_ylim(-100, -30); ax.grid(alpha=0.3); ax.legend(loc='upper right')
    ax.set_xlabel("Baseband Freq (MHz)"); ax.set_ylabel("dB")
    ax.set_title(f"RX live | LO {RX_LO/1e6} MHz | {FS/1e6} MSPS")
    try:
        while plt.fignum_exists(fig.number):
            x = sdr.rx()
            F = 20*np.log10(np.abs(np.fft.fftshift(np.fft.fft(x*win)))/BUF_LEN + 1e-12)
            line.set_ydata(F)
            plt.pause(0.001)
    except KeyboardInterrupt:
        pass
    print("已退出VIEW")

elif MODE == "RELAY":
    # ---------- 模式2：转发（只有文字，绝不画图/FFT） ----------
    sdr.tx_cyclic_buffer = False
    sdr.tx_hardwaregain_chan0 = TX_ATTEN
    print(f"RELAY模式: {RX_LO/1e6} MHz -> {TX_LO/1e6} MHz, DSP={'ON' if ENABLE_DSP else 'OFF(直通)'}")
    n, samples, t0 = 0, 0, time.time()
    try:
        while True:
            x = sdr.rx()
            y = pipeline(x)
            sdr.tx(y)
            n += 1; samples += len(y)
            if n % 50 == 0:
                dt = time.time() - t0
                print(f"  当前RX增益: {sdr.rx_hardwaregain_chan0} dB")   # 加这行
                print(f"[{n}块 {dt:.0f}s] 实际 {samples/dt/1e6:.2f} MSPS（目标{FS/1e6}）")
                samples, t0 = 0, time.time()
    except KeyboardInterrupt:
        pass
    finally:
        sdr.tx_destroy_buffer()
        print("已停止，TX缓冲区已销毁")
