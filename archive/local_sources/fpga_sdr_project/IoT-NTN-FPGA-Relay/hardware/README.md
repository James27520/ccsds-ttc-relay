# 硬件说明

## 开发板

**LDSDR**（Zynq-7000 + AD9361 软件无线电平台）

| 项 | 值 |
|---|---|
| 主芯片 | **Zynq XC7Z010**（clg400 封装，-1 速度等级） |
| 收发器 | **AD9361**，2×RX / 2×TX，70 MHz – 6 GHz，12-bit |
| PL↔AD9361 接口 | **LVDS 双端口全双工**，6 lane + frame + clk 各一组 |
| 启动方式 | SD 卡 / QSPI / JTAG |
| 调试 | JTAG（FT4232H）+ USB 串口（PS UART1，115200 8N1） |

> ⚠️ Vivado 工程 `zynq_dev_fmcomms3.xpr` 里同时存在 7010 与 7020 两个综合 run，**当前生效的是 `synth_2` / `impl_2`（xc7z010clg400-1）**。误用 7020 的 run 会生成无法在板上运行的码流。
> 7000 的位流是分器件的，**7010 的 .bit 不能烧到 7020 上**，反之亦然。以芯片丝印为准。

## AD9361 接口速率

来自 UG-570 Table 50（LVDS 双端口全双工）：

| 项 | 值 |
|---|---|
| 最大数据率（I+Q 合计） | **61.44 MSPS** |
| 最大射频带宽 | 56 MHz（受模拟滤波器限制） |
| 最大 `DATA_CLK` | 245.76 MHz |

**`DATA_CLK` 与采样率的关系：**

| 模式 | 关系 | 30.72 MSPS 时 |
|---|---|---|
| 2R2T（`phy_mode = 0`） | `DATA_CLK = 4 × 每通道采样率` | 122.88 MHz / 8.138 ns |
| 1R1T（`phy_mode = 1`） | `DATA_CLK = 采样率` | 30.72 MHz / 32.55 ns |

> 2R2T 的约束更紧（周期更短），所以 XDC 里按 2R2T 写即可覆盖两种模式。
> **改 `sample_rate` 必须同步改 `toppin.xdc`：`period_ns = 4000 / sample_rate_in_MSPS`**

## PL ↔ AD9361 引脚（`toppin.xdc` 摘要）

```
rx_clk_in_p/n        N20 / P20    LVDS_25, DIFF_TERM
rx_frame_in_p/n      Y16 / Y17    LVDS_25, DIFF_TERM
rx_data_in_p/n[5:0]  LVDS_25, DIFF_TERM     （双端口模式下 P0 = RX 总线）
tx_clk_out_p/n       N18 / P19    LVDS_25
tx_frame_out_p/n     V16 / W16    LVDS_25
tx_data_out_p/n[5:0] LVDS_25                （P1 = TX 总线）
sys_clk              K17          LVCMOS25   （ILA / dbg_hub 用）
```

## 板载 AD9361 的固定配置（不要随意改动）

这些参数与 PCB 走线绑定，改动会导致 LVDS 眼图失效：

| 参数 | 值 | 位置 |
|---|---|---|
| `lvds_mode_enable` | 1 | `main.c` init param |
| `single_port_mode_enable` | 0 | 同上 |
| `half_duplex_mode_enable` | 0 | 同上 |
| `pp_tx_swap_enable` / `pp_rx_swap_enable` | 1 / 1 | 同上 |
| `rx_frame_pulse_mode_enable` | 1 | 同上 |
| `rx_data_delay` | 4 | 同上 |
| `tx_fb_clock_delay` | 7 | 同上 |
| `lvds_invert1_control` / `lvds_invert2_control` | `0xFF` / `0x0F` | 同上 |
| `I_DELAY_EN` 寄存器 | `0x7f` | `main.c` |
| `I_DELAY_TAP` 寄存器 | 8 | `main.c` |

**只有 `I_DELAY_TAP` 在眼图变差时才需要微调**（判据：ILA 抓到的 I/Q 星座是否清晰）。

## 硬件连接

```
                    ┌──────────────────────┐
   信号源/CMU200 ───►│ RX1                  │
                    │       LDSDR          │
   频谱仪/CMU200 ◄───│ TX1                  │
                    │                      │
   PC (JTAG)  ──────►│ JTAG                 │
   PC (串口)  ──────►│ USB UART (115200)    │
                    └──────────────────────┘
```

> ⚠️ **TX1 到仪器之间务必加 ≥20 dB 衰减器。** AD9361 的 TX 输出最大约 0 dBm 量级，而原厂代码里的 TX 衰减参数单位写错（`70` mdB = 0.07 dB ≈ 满功率）。本仓库已改为 30 dB，但首次上电仍建议先实测再接入仪器。

## 供电与散热

AD9361 在 2R2T 全双工 30.72 MSPS 下功耗较大，长时间运行注意散热。板子功耗变化会轻微影响 LVDS 时序，若长时间运行后出现眼图变差，重新微调 `I_DELAY_TAP`。

## 已知硬件限制

| 限制 | 影响 |
|---|---|
| 板上没有独立 GPSDO / 1PPS | 无法做绝对频率与时间基准，多普勒测量只能做相对值 |
| ILA 时钟来自独立 `sys_clk`，与 `DATA_CLK` 不同源 | ILA 抓 data_clk 域信号会混叠，需要改接 `ila_0/clk` 才能用于诊断 |
| SD 卡启动会覆盖 JTAG 下载 | 开发期建议拔卡 |
