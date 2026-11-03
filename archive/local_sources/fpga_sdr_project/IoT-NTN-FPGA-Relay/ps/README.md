# PS 侧改动

本目录的内容**不是完整的应用工程**，而是叠加到厂商裸机工程上的补丁。
厂商工程（含 Analog Devices no-OS AD9361 驱动）请自行从板卡供应商处获取。

## 文件

| 文件 | 类型 | 说明 |
|---|---|---|
| `relay_reg.h` | 新文件 | 寄存器访问封装（地址宏 + 内联函数） |
| `relay_cli.h` | 新文件 | UART 命令行 + 状态行（约 40 条命令） |
| `main.c.patch` | unified diff | 对厂商 `main.c` 的改动，共 +119 / −13 行 |
| `patch_main_c.py` | 脚本 | 自动打补丁（幂等，自动备份 `main.c.bak`） |

## 应用方式

### 方式 A：自动脚本（推荐）

```bash
cd <SDK工程>/9361/src
python patch_main_c.py
```

脚本会自动备份原文件为 `main.c.bak`，并在结束时自检五项关键改动是否生效。

### 方式 B：手动打补丁

```bash
cd <SDK工程>/9361/src
patch -p1 < main.c.patch        # 注意路径前缀是 a/src/ b/src/
```

或直接照着 `main.c.patch` 手改。

### 然后把两个头文件拷进去

```bash
cp relay_reg.h relay_cli.h <SDK工程>/9361/src/
```

### 重新编译

```bash
xsct <repo>/scripts/build_app.tcl
```

## `main.c` 的 5 处改动

| # | 改动 | 为什么必须 |
|---|---|---|
| 1 | `#include "relay_reg.h"` / `relay_cli.h` | 寄存器与命令行接口 |
| 2 | **注释掉 AD9361 BIST 三行**（`0x3F4/0x3F5/0x3F6`） | `0x3F4 = 0x03` = BIST 使能 + TX 注入点 + 单音模式，**芯片内部单音会取代接口送来的 DAC 数据，转发信号根本发不出去** |
| 3 | **TX 衰减 `70` → `30000`** | 驱动文档明确 `attenuation_mdb` 单位是 **mdB**（注释里的例子是 `10000 (10 dB)`）。`70` mdB = 0.07 dB ≈ **满功率**，几乎肯定是小数点写错 |
| 4 | 频点 2400/2400 → **900/1000 MHz**，采样率 40 → **30.72 MSPS** | 收发同频在 FDD 下易自激；30.72 MSPS 是标准值且余量充足 |
| 5 | `while(1);` → **继电器启动序列 + 健康自检 + UART 命令行 + JTAG 信箱** | 原代码初始化完就死循环，没有任何运行时接口 |

## ⚠️ 改采样率必须同步改约束

```c
sample_rate = 30720000;   /* main.c */
```

```tcl
# toppin.xdc，2R2T 模式
create_clock -period 8.138 -name rx_clk [get_ports rx_clk_in_p]
#                    ^^^^^ = 4000 / sample_rate_in_MSPS
```

只改软件不重新综合匹配的约束，可能破坏 AD9361 的 LVDS 接口。

## 已知的坑（都已在代码里修好并注释）

| 坑 | 症状 | 修复位置 |
|---|---|---|
| 负数 double 转无符号是 UB | 所有**负频偏静默失效**，频率字回 `0x00000000` | `relay_reg.h` 的 `relay_freq_word()` 经有符号中间量截断 |
| 串口打开从不失败 | GUI 显示"已连接"但板子没跑转发程序 | `relay_gui.py` 的 `verify_connect()`：1.8 s 内无 `STAT` 就明确报警 |
| `status` 行里的 `gain`/`ddc`/`duc` 是**十六进制** | GUI 误按十进制解析，`0x800` 显示成 `0x320` | `relay_gui.py` 的 `HEX_KEYS` |

## 上电后的启动序列

```
ad9361_init()                        初始化 AD9361（含片内 128 抽头 FIR）
  ↓
ad9361_set_rx/tx_sampling_freq(30.72 MSPS)
ad9361_set_rx/tx_lo_freq(900/1000 MHz)
ad9361_set_rx_rf_bandwidth(18 MHz)
ad9361_set_rx_rf_gain(0 dB)          手动增益（MGC）
ad9361_set_tx_attenuation(30 dB)
  ↓
AXI 寄存器：IDELAY_EN=0x7F, IDELAY_TAP=8, PHY_MODE=2R2T
  ↓
（BIST 保持关闭）
  ↓
relay_set_mode(MUTE)                 安全态
relay_set_ddc_freq(0) / duc_freq(0)
relay_set_gain(0x800, dc=0)
relay_set_mode(RELAY)                进入转发
  ↓
relay_health_check()                 读状态计数器判活
  失败 → 回到 MUTE 并打印告警
  ↓
cli_help() + cli_stat()
while(1) { cli_poll(); }             只做命令行与信箱刷新
```

## 健康检查判据

```c
relay_health_check(&n_in, &n_out, &n_clip);
```

| rc | 含义 |
|---|---|
| 0 | 正常（采样在涨 且 输出在涨） |
| −1 | 没有 ADC 数据 |
| −2 | ADC 在跑但没有 DAC 输出 |

状态计数器每 4096 样点快照一次（≈133 µs @30.72 MSPS），所以 `relay_health_check` 内部有等待循环，不能在中断里调用。
