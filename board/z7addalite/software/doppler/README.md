# 遥控上行接收的预测与测量补偿

本目录是 Z7ADDALite 的可选 C 模块，处理 ADC1 的 100.5 MHz 测控上行。默认构建不接入；实验构建上电后仍为 OFF。它不修改三个 GUI、终端参数、LDSDR 本振、UDP/空口协议或转发租期。

实现和验证边界、曲线及报告用文字见 [补偿验证说明](../../../../docs/doppler-telecontrol-prototype.md)。该说明记录的早期轮次完成主机波形验证、控制器集成验证和 Cortex-A9 完整 ELF 链接，当时未下载到板卡、未做动态射频闭环。后续团队确认的测控上行补偿通过范围见[2026-11-03验收结论](../../../../docs/validation/20261103_acceptance.md)；本目录的合成波形统计仍属离线证据。

## 文件

| 文件 | 职责 |
|---|---|
| `doppler.c/.h` | 单向多普勒几何计算、局部时间预测、alpha-beta 残差跟踪、丢失/过期/乱序保护 |
| `adda_doppler_rx.c/.h` | 从真实解调 API 获取频偏观测，驱动可选线性变化率混频；只接测控 ADC1 |
| 相邻 `demod/adda_demod.c` | 保留原 API；新增带搜索中心、变化率和搜索宽度的解调入口 |
| `test_doppler.c` | 几何符号、时间回绕、状态、重复及错误观测测试 |
| `test_controller_doppler.c` | 寄存器模型 → 原控制器 → 真实 C 解调 → 原 UDP 状态机；不是实板 |
| `test_dynamic.py` | 独立生成含噪 ADC 波形、四组补偿对照、跨块观测丢失测试 |
| `run_tests.py` | 主机编译与原功能回归，不打开串口或网络 |
| `verify_legacy.py` | 对照补偿前提交 `7600e45`，核对默认解调结果及全部统计量 |
| `plot_results.py` | 从 JSON 原始结果生成 PNG/SVG 报告图，不生成测试数据 |

## 主机复现

需要 Python 3.11+、NumPy 和一个 C99 编译器；绘图另外需要 Matplotlib。它们不加入桌面站启动依赖。以下从仓库根目录运行，输出目录可自定：

```powershell
python board/z7addalite/software/doppler/run_tests.py --cc gcc --out D:/doppler-test/host
python board/z7addalite/software/doppler/verify_legacy.py --cc gcc --library D:/doppler-test/host/doppler_receiver.dll --out D:/doppler-test/legacy
python board/z7addalite/software/doppler/plot_results.py --results D:/doppler-test/host/dynamic_results.json --out D:/doppler-test/figures
```

使用 Zig 时，将 `--cc gcc` 替换为 `--zig <zig.exe完整路径>`。脚本显式使用 `-UNDEBUG`，保证优化构建也执行原测试中的 `assert`。测试没有设备访问。

## 板端构建与运行开关

对当前已核验的 BSP、XSA 和 `ps7_init.tcl`，沿用 `ps_software/build_platform.py` 的参数，额外传 `--doppler-enabled`，输出到一个新的目录。生成文件名含 `_doppler`，防止误认成默认演示固件。该构建工具只编译/链接，从不烧录。

```text
python board/z7addalite/ps_software/build_platform.py
  --out <新输出目录> --bsp <已核验BSP>
  --arm-bin <arm-none-eabi工具目录>
  --xsa <当前PL匹配XSA> --ps-init <对应ps7_init.tcl>
  --tm-tx-enabled --service-standby --doppler-enabled
```

只有另行加载实验固件后，UART 才提供下面的命令。配置模型和模式前需停止采集/服务，等 `service status` 确认退出；不要对正在演示的板卡执行。这里只说明接口，本轮没有执行这些串口命令。

| 命令 | 含义 |
|---|---|
| `doppler status` | 只读：模式、状态、计划是否有效、接受/拒绝观测计数 |
| `doppler model 2000 20 10000` | 从当前板端时钟开始，预测 CFO 为 +2000 Hz、斜率 +20 Hz/s、有效 10000 ms；不自动启用 |
| `doppler radial -6000 10 10000` | 输入径向速度 −6000 m/s、径向加速度 +10 m/s²；A9 按 100.5 MHz 计算预测系数；不自动启用 |
| `doppler hybrid` | 启用预测搜索/变化率补偿及测量残差跟踪；要求先提供模型 |
| `doppler predict` | 仅预测的对照模式，不把强制混频频率当作测量更新 |
| `doppler measure` | 原逐块平方律估计，并记录跨块测量状态；不使用预测模型 |
| `doppler off` | 立即关闭新模块并清除残差，继续使用原解调算法；不启停转发 |

时间均为同一 A9 的本地单调毫秒时钟，支持 uint32 回绕；不能直接填电脑 UTC 或另一块板的 uptime。`model` / `radial` 仅提供一个最长 600000 ms 的线性段，没有自动下载星历或轨道传播器。新模型清空旧模型的残差，避免基准混用。未来接入星历时需显式映射时钟并分段更新，当前服务忙时会拒绝模型切换。

`radial` 的速度以距离增大为正，接近时为负。它不是随意指定完整三维加速度：传入的是距离的二阶导数。完整三维相对位置、速度、加速度使用 `dp_geometry()`，必须处于同一惯性坐标系、同一时刻，单位为 m、m/s、m/s²。

## 观测和状态合同

预测与测量都是接收频偏，正值表示接收频率上移。数字补偿取反号。观测有独立链路、通道、采样时刻、序号、CRC 与质量字段；测控频偏不能直接用于业务通道。

适配器使用采样 **ARM 命令时刻**，不会把 200～300 ms 后的解码结束时刻当作信号时刻。当前 PL 没有首样点硬件时间戳，用 ARM 到 DONE 首次观测的时间加 1 ms 作为保守不确定度；超过 20 ms 或使变化率预测误差超过 50 Hz，就退出新补偿路径，使用原接收算法。现有 PL 的 31.25 MSPS 数据及采样 ABI 不变。

正常混合模式用预测及历史残差确定搜索中心，以预测变化率消除块内二次相位；当前块仍以平方谱作精细载波估计。CRC 通过、输入 RMS ≥8 原始 ADC 计数、削顶样点比例 ≤0.1% 的观测才允许更新跨块残差。质量值只是这一门限的通过/失败标志，不是测得的 SNR。

| 状态 | 行为 |
|---|---|
| OFF | 新模块关闭，保持原解调 |
| PREDICT_ONLY | 模型有效，无新鲜历史测量；仍可尝试当前块精细估计 |
| HYBRID | 模型与最近 1500 ms 内的有效测量共同提供搜索中心/变化率 |
| HOLD | 观测超过 1500 ms，残差最多保持至 5000 ms；不无限外推残差斜率 |
| FAULT | 模型过期、计划超界或时间质量不足，适配器回退原解调，不更改射频状态 |

观测超过 5000 ms 后，混合模式退为仅模型引导；仅测量模式没有新鲜输入时报告计划无效。新观测的最大接收年龄为 1500 ms（在解码入口检查）。序号重复、乱序、未来时刻、坏 CRC、质量不足和残差跳变不更新状态。每个链路使用独立 `dp_tracker`；模块本身不访问设备，也没有发射使能权限。

UART `DOPPLER` 记录采样时间、epoch、状态、预测/残差、实际数字补偿及变化率、观测处理结果、CRC。频率日志以整数 Hz 输出，避免依赖裸机浮点 printf；完整精度在 `adp_trace` 内。`applied` 是软件混频器采用的值，不是转发板 LO 回读或射频校准结果。序号是捕获 epoch，不改变既有空口序号。

`dp_tracker` 在本轮 64 位主机 ABI 下为 168 字节，不按采样块分配内存。接收适配器复用原解调工作区；原解调器本身仍有 FFT/FIR 动态内存及同步运算，不能因此称为连续实时处理。
