# IoT-NTN FPGA Relay — 低轨卫星弯管式转发器 PL 载荷

面向 6G 非地面网络（NTN）的**低成本星载载荷验证平台**。在 LDSDR（Zynq-7010 + AD9361）上，用器件内部 FPGA（PL）实现完整的**数字下变频 → 隔直 → 数字上变频 → 数字增益**弯管转发数据面，PS（ARM）只做参数配置与状态监测，**不参与任何数据搬运**。

> **对空口数据包不做解调译码**（透明转发 / bent-pipe），符合弯管式载荷定义。

---

## 核心指标（实测，非估算）

| 指标 | 实测值 | 说明 |
|---|---|---|
| 转发速率 | **30.72 MSPS** | 2R2T 模式，每通道 |
| 收发一致性 | **Δin == Δout** | 连续 2.55 s 内 78,270,464 样点进、78,270,464 样点出，**零丢样** |
| 数据面时延 | **9 级流水线 = 10 个 `data_clk`** | ≈ **81 ns**（2R2T 下 `data_clk = 4 × 采样率 = 122.88 MHz`） |
| DSP48 占用 | **20 / 80（25%）** | 4 个复混频器 ×4 + 2 个增益 ×2 |
| Block RAM | 4.5 / 60（7.5%） | 正弦查找表 |
| Slice LUT | 3084 / 17600（17.5%） | |
| Slice Reg | 5229 / 35200（14.9%） | |
| 时序 | **WNS +0.540 ns / WHS +0.016 ns** | 0 个失败终点 / 13030 |
| 频率分辨率 | fs / 2³² | 双精度相位累加器，30.72 MSPS 下 ≈ 7.2 mHz |
| 数字变频范围 | ±fs/2 = ±15.36 MHz | 通过 AXI 寄存器实时可调 |

---

## 架构

### 三平面划分

```
┌─ 数据面 DATA PLANE ── PL 内闭环，硬实时，无包，不经 USB ────────────────┐
│                                                                        │
│  AD9361 RX ─► [DDC 复混频] ─► [隔直] ─► [DUC 复混频] ─► [数字增益] ─► AD9361 TX
│                e^-jθ(n)      无乘法器    e^+jθ(n)      Q1.11 饱和        │
│                    ▲                        ▲                          │
│              32-bit NCO                 32-bit NCO                     │
│                    └────────┬───────────────┘                          │
│                        AXI-Lite 寄存器组                                │
└────────────────────────────────┬───────────────────────────────────────┘
                                 │ 参数 / 状态
┌─ 控制面 CONTROL PLANE ── PS(ARM) 裸机 ─────────────────────────────────┐
│  上电初始化 AD9361 → 写转发参数 → 健康自检 → UART 命令行 → JTAG 信箱     │
└───────────────────────────────────────────────────────────────────────┘
```

**关键设计原则：`ad9361_phy` 暴露的 ADC/DAC 接口与数据面处于同一个时钟域（`data_clk`），因此数据通路内不存在任何跨时钟域。** 只有控制字与状态计数器跨域，由 `relay_cdc.v` 显式同步。

### 频率关系

```
输出频率 = TX_LO + (输入频率 − RX_LO) + (DUC_FREQ − DDC_FREQ) / 2³² × fs
```

---

## 仓库结构

```
.
├── rtl/                  PL 转发数据面（Verilog-2001，可直接综合）
│   ├── relay_dq.v            顶层：双通道、共享 NCO、控制字 CDC、计数器
│   ├── relay_path.v          单通道 9 级流水线
│   ├── relay_cmix.v          两级复数混频器
│   ├── relay_nco.v           32 位相位累加器 + 象限重构
│   ├── relay_sin_rom.v       1/4 波正弦 ROM（自动生成）
│   ├── relay_cdc.v           复位同步 / 多 bit 控制字跨域 / 计数器快照
│   └── gen_relay_sin_rom.py  ROM 生成脚本
│
├── sim/                  ModelSim 功能验证（不需要硬件）
│   ├── tb_relay.v            10 个测试用例
│   ├── run_sim.do            运行脚本
│   └── analyse_relay.py      12 项断言分析
│
├── ps/                   PS 侧裸机代码（叠加到厂商工程）
│   ├── relay_reg.h           寄存器访问封装
│   ├── relay_cli.h           UART 命令行 + 状态行
│   ├── main.c.patch          厂商 main.c 的 unified diff
│   └── patch_main_c.py       自动打补丁脚本
│
├── rk3588/
│   ├── ccsds.py              CCSDS 空间包（简化版，含 CRC-16）
│   ├── serial_port.py        跨平台串口（Linux termios / Windows ctypes）
│   ├── relay_link.py         LDSDR 控制链路封装
│   ├── payload_ctl.py        载荷遥控控制台
│   ├── spectrum.py           ★ 频谱遥测帧协议（编解码 + CRC + 流式解析）
│   ├── channel_detect.py     ★ CFAR 信道检测 + 跨帧跟踪
│   ├── spectrum_tool.py      ★ 频谱显示/检测命令行（含 ASCII 频谱图）
│   ├── SPECTRUM_PROTOCOL.md  ★ 频谱帧格式 + PL 实现要点
│   ├── PROTOCOL.md           CCSDS 遥控协议
│   └── README.md
│   ├── ccsds.py              CCSDS 空间包编解码 + CRC-16 + 流式同步解码
│   ├── serial_port.py        跨平台串口（Linux termios / Windows ctypes）
│   ├── relay_link.py         载荷 CLI 协议封装 + 频率字换算
│   ├── payload_ctl.py        主控制台（CCSDS ↔ 载荷命令）
│   └── PROTOCOL.md           协议规范：APID 分配表、数据域编码
│
├── tools/
│   ├── relay_gui.py          PC 端监控/控制界面（零依赖）
│   ├── test_relay_board.py   ★ 上机测试程序（39 项，约 18 秒）
│   └── md2docx.py            Markdown 报告 → DOCX（生成 docs/ 下的 docx）
│
├── scripts/              构建与下载
│   ├── modify_bd.tcl         Block Design 修改（幂等）
│   ├── build_pl.tcl          Vivado 批处理构建
│   ├── build_app.tcl         XSCT 编译裸机程序
│   ├── program_device.tcl    JTAG 下载（含 ps7_init）
│   ├── verify_relay.tcl      读状态寄存器
│   ├── relay.bif             BOOT.bin 分区描述（仅供参考，不推荐使用）
│   ├── write_sd_boot.ps1     一键写 SD 卡（自动备份 + 校验）
│   └── boot/                 SD 卡自启动与 U-Boot 调试脚本
│       ├── fix_uenv_via_linux.py  ★ 从板子 Linux 修正 uEnv.txt（推荐）
│       ├── uboot_persist.py       用 U-Boot fatwrite 持久化变量
│       ├── capture_reboot.py      登录+reboot+完整抓取启动日志
│       ├── uboot_cmd.py           打断 U-Boot 并执行命令
│       └── flash_sd_via_uart.py   无读卡器时用串口传文件
│
├── ip-patch/
│   └── patch_axi_ctrl.py     给厂商 axi_ctrl IP 加 8 个寄存器
│
└── docs/
    ├── 01-架构设计.md
    ├── 02-调试报告.md        ★ 完整调试过程与所有踩过的坑
    ├── 03-寄存器手册.md
    ├── 04-上机测试步骤.md
    ├── 05-从软转发到硬转发.md  ★ 改造方法论：瓶颈量化、路线选择、五阶段实施
    ├── 06-SD卡上电自启动.md      ★ U-Boot uEnv.txt 方案（含三个必踩的坑）
    ├── 07-上机测试程序.md        ★ 39 项测试 + 两个必须处理的计数器特性
    ├── 08-信号与协议框架.md     ★ 四条链路逐条拆解 + 协议清单 + 自定义协议格式
    ├── 信号与协议框架.docx      上面这份的 Word 版
    └── PL实现说明.docx
```

---

## 快速开始

### 环境

| 项 | 版本 |
|---|---|
| Vivado | 2018.3 |
| Xilinx SDK / XSCT | 2018.3 |
| 硬件 | LDSDR 开发板（Zynq XC7Z010 + AD9361），LVDS 双端口 |
| 仿真 | ModelSim（可选，用于跑 `sim/`） |
| PC 端 GUI | Python 3.8+，**无需第三方库** |

### 1. 只跑仿真（不需要硬件）

```bash
cd sim
vsim -c -do run_sim.do
python analyse_relay.py          # 期望 RESULT: 12/12 checks passed
```

### 2. 构建 PL

```tcl
# Vivado Tcl 控制台，先刷新被补丁过的 IP
update_ip_catalog -rebuild
reset_target    all [get_files design_1.bd]
generate_target all [get_files design_1.bd]
source <repo>/scripts/modify_bd.tcl
```

然后 `Generate Bitstream`（run 为 `synth_2` / `impl_2`）。

> 顺序很重要：**必须先重建 IP、再改 BD**。BD 单元的端口列表来自生成的 IP 产物而不是 `.bd` 文件；顺序反了会导致新寄存器看不到，脚本会退化成用常量固定控制口。

### 3. 编译并下载 PS 程序

```bash
xsct scripts/build_app.tcl
xsct scripts/program_device.tcl
```

`program_device.tcl` 已包含 `ps7_init`——**没有它 `dow` 会报 "Cannot access DDR: the controller is held in reset"**。

### 4. 用 RK3588 控制载荷（CCSDS）

```bash
cd rk3588
python3 payload_ctl.py demo          # 离线全链路演示，不需要硬件
python3 payload_ctl.py status        # 读载荷状态（自动检测串口）
python3 payload_ctl.py offset 100000 # 下发 +100 kHz 数字上变频
python3 payload_ctl.py watch         # 持续监视丢样
```

详见 [rk3588/README.md](rk3588/README.md) 与 [rk3588/PROTOCOL.md](rk3588/PROTOCOL.md)。

### 5. 打开监控界面

```bash
python tools/relay_gui.py            # 自动检测串口
python tools/relay_gui.py COM5       # 或指定
```

界面显示实时收/发样点、速率、**丢样自动检测**、饱和率、健康状态，并可直接修改工作模式、DDC/DUC 频偏、数字增益、收发本振、RX 增益、TX 衰减。

---

## 已知问题

| 问题 | 状态 | 说明 |
|---|---|---|
| ~~SD 卡会覆盖转发器~~ | ✅ **已解决** | 复用原厂 U-Boot，在 SD 卡的 `uEnv.txt` 里加两行（`relayboot` + `uenvcmd=run relayboot`）即可**上电自动跑转发器**，无需电脑。见 [docs/06-SD卡上电自启动.md](docs/06-SD卡上电自启动.md)。⚠️ 不要自造 BOOT.bin —— 本工程的 FSBL 没有 SD 驱动。 |
| `bootgen` 命令行不可用 | ⚠️ 环境问题 | 本机 Vivado 2018.3 的 bootgen 退出码 0 却写出 2.4 MB 垃圾数据，三个输入分区一个都没进去。做 SD 卡自启动需走 SDK 图形界面 `Xilinx → Create Boot Image`。 |
| ILA 时钟域不同源 | ⚠️ 已知局限 | ILA 由 `clk_wiz` 100 MHz 驱动，数据在 122.88 MHz 的 `data_clk` 域，抓出的波形会混叠。要看干净波形需把 `ila_0/clk` 改接 `ad9361_phy_0/data_clk`。 |
| 窄带信道化（CIC + 信道 FIR） | 🚧 未实现 | v1 是宽带透明转发。剩余 60 个 DSP48 足够扩展 2~3 个窄带信道。 |
| 闭环 AGC | 🚧 未实现 | 当前是手动数字增益 + AD9361 手动增益（MGC）。 |
| 多普勒闭环 | 🚧 未实现 | 接口已就绪（`relay_ddc_freq` / `relay_duc_freq` 可被外部算法实时写入）。 |

---

## 验证证据

### 仿真（12/12）

| 编号 | 模式 | 配置 | 预期 | 实测 |
|---|---|---|---|---|
| T1 | 仅上变频 | 直流输入，DUC=fs/64 | +480.0 kHz | +480.0 kHz，幅度 2046.3 |
| T2 | 旁路 | 原始直通 | +480.0 kHz，2000 | +480.0 kHz，2000.1 |
| T3 | 转发 | DDC=DUC=fs/64（净 0） | +480.0 kHz，1998 | +480.0 kHz，1998.6 |
| T4 | 仅上变频 | DUC=+fs/64 | **+960.0 kHz** | +960.0 kHz，1999.0 |
| T5 | 转发 | DDC=fs/64，DUC=0 | 直流 | 直流 1997.8，残差 std 0.65 |
| T6 | 静音 | 输出置零 | 全零 | 全零 |
| T7 | 仅上变频 | 增益 0.5 | +480.0 kHz，999.5 | +480.0 kHz，999.5 |
| T8 | 过驱动 | 增益 2.0 | 饱和 ±2047 | 峰值 2048，100% 饱和 |
| T9 | 2R2T 双通道 | 稀疏 valid，DUC=fs/64 | ch1/ch2 = +240.0 kHz | 240.0 / 240.0 kHz |
| T10 | 2R2T 双通道 | DDC=DUC（净 0） | ch1/ch2 = +120.0 kHz | 120.0 / 120.0 kHz |

### 硬件实测（零丢样）

```
read 1 : in=1,186,590,702  out=1,186,590,714  clip=275,615  rc=0
read 2 : in=1,264,861,166  out=1,264,861,178  clip=275,615  rc=0
         Δin = 78,270,464   Δout = 78,270,464     ← 完全相同
read 3 : in=1,343,057,902  out=1,343,057,914  clip=275,615  rc=0
         Δin = 78,196,736   Δout = 78,196,736     ← 完全相同
```

78,270,464 / 2.55 s ≈ **30.7 MSPS** = 配置速率。`in − out = 12` 恒定，等于流水线深度。

### 端到端（CMU200）

综测仪 RF2 出 900.100 MHz → SDR RX1，SDR TX1 → CMU200 RF1：

- 转发输出 **1000.100 MHz，−36.6 dBm** ✓
- 界面点「+100 kHz」→ 输出移到 1000.200 MHz，**波形明显左移** ✓
- 点「−100 kHz」→ 反向移动 ✓

---

## 硬件

LDSDR 开发板（Zynq XC7Z010 + AD9361）：

- **PL↔AD9361 接口**：LVDS 双端口全双工，`rx_data_in_p[5:0]` / `tx_data_out_p[5:0]`，DATA_CLK 约束 245.76 MHz（最大值）
- **2R2T 模式下 `DATA_CLK = 4 × 每通道采样率`**，30.72 MSPS → 122.88 MHz → 约束周期 8.138 ns
- **接口没有 DMA、没有 AXI-Stream 基础设施**，ADC 数据原本只接到 ILA，TX 由 DDS 驱动
- 转发的插入点：`ad9361_phy_0` 的 `adc_data_d1/q1` + `adc_d1q1_valid` → `dac_data_d1/q1` + `dac_valid`

---

## 许可

代码以 MIT 许可发布，见 [LICENSE](LICENSE)。

注意：`ps/` 下的补丁针对的是 **Analog Devices no-OS AD9361 驱动**（ADI 版权，BSD 风格许可）与 **LDSDR 厂商示例工程**，这两部分代码本身不包含在本仓库中，请自行从原出处获取。
