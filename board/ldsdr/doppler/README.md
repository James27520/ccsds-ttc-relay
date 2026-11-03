# LDSDR 双路业务多普勒实验扩展

两路业务的预测、测量、数字移频均在 LDSDR 内执行，运行时默认 OFF。现有 GUI、遥控协议及演示固件入口不变。完整边界和结果见[业务补偿说明](../../../docs/doppler-compensation.md)。

## 文件

| 文件 | 用途 |
|---|---|
| `relay_doppler.c/.h` | 两段传播模型、两路独立跟踪、原始 BPSK I/Q 频偏估计、NCO 字计算 |
| `relay_doppler_board.h` | A9 主循环接入、短段抓取搬运、原租期/模式检查、实验 CLI |
| `relay_iq_snapshot.v` | 双时钟、双路冻结 RAM；不改动原业务数据通路 |
| `rebuild.py` | 独立实验 ELF 构建，不访问板卡 |
| `build_pl.tcl` | 从既有 PL 工程另存候选工程、接入新 AXI 抓取模块、生成位流 |
| `verify.py` / `test_*.c` / `tb_*.sv` | 基础算法、板端轮询替身、采样接口及 C→原转发 RTL 集成检查 |

共用预测/残差核心为 `board/z7addalite/software/doppler/doppler.c/.h`；共用算法不等于共用遥控 ADC 观测。通用 `source_valid` 字段在 ADDA 由 CRC 等门限生成，在 LDSDR 由 BPSK 相关质量生成，后者不声称业务 CRC 通过。

## 构建

这是依赖已验证厂商工程/BSP 缓存的扩展，不是无依赖 clean build。需要原 `relay_udp2026` 缓存、匹配的 `remote_control` 已验证参考构建、ARM hard-float 编译器、native GCC，以及 Vivado。

```powershell
python board/ldsdr/doppler/rebuild.py --base '<原UDP缓存>' --reference '<已验证remote构建>' --out '<新输出目录>' --host-cc '<native-gcc.exe>' --compiler '<arm-none-eabi-gcc.exe>'
vivado -mode batch -source board/ldsdr/doppler/build_pl.tcl -tclargs '<已验证双路PL工程.xpr>' '<新PL目录>'
python board/ldsdr/doppler/verify.py --cc '<native-gcc.exe>' --vivado-bin '<Vivado/bin>' --relay-rtl '<已验证relay_*.v目录>' --out '<新测试目录>'
```

参考构建必须全项通过，ELF、全部源文件、当前 remote 头文件、基线 BSP/libxil/复用网络对象均检查哈希。新编译器可生成不同机器码，因此不会声称新 ELF 与旧 ELF 逐字节一致，也没有放宽旧固定镜像的验证门限。旧构建入口不改。

本地已验证 PL 基线为 `D:/RelayTools/work/six_line_20261031/relay_pl_candidate01/zynq_dev_fmcomms3.xpr`，器件 `xc7z010clg400-1`、2R2T、每路 30.72 MSPS、数据时钟 122.88 MHz。新模块与原同一 ADC 数据钟连接，原 ADC/DAC 线、转发 RTL 与原约束不变。

`build_pl.tcl` 只在另存的新项目中修改，复制自定义 IP 仓库；不会连接 JTAG，不加载 bit，不写 SD/Flash。ELF 要与新 PL 配套，不应在旧 PL 上尝试读取新 AXI 地址。

## 实验控制

仅实验 ELF 新增以下 LDSDR UART 命令；当前 GUI 不会主动发出这些命令。先按原流程设置本振并获得有效转发租期，再配置补偿。模型在 LDSDR 收到命令时建立本地时间基准，之后不依赖串口持续输入。

```text
dp status
dp radial <通道1或2> <输入RF_Hz> <输出RF_Hz> <上行径向速度_m/s> <上行径向加速度_m/s²> <下行径向速度_m/s> <下行径向加速度_m/s²> <有效期_ms>
dp off
```

零运动检查示例（已有实际 RF 计划需对应 1989.5 → 2179.5 MHz）：

```text
dp radial 1 1989500000 2179500000 0 0 0 0 30000
dp radial 2 1989500000 2179500000 0 0 0 0 30000
dp status
dp off
```

这两个示例不模拟实际移动；用于验证默认名义频率保持与测量残差。非零运动值必须对应真实或明确注入的测试频偏，不能只改模型就宣称补偿了实际多普勒。命令只接受已激活租期；不自动开转发。模型有效期不会延长五分钟租期。运行中重新配置先 `dp off`；采样忙时配置会拒绝，应在状态确认后重试。终端2的下行预补偿参数属于另一传播段，需要独立给定。

状态中的 `in_hz/out_hz` 是跟踪/预测值，`measured_hz` 是原始业务估计；`quality` 为相干度×1000，`max_age_ms` 包含搬运与计算时间。OFF 后历史统计只作诊断，`on=0` 表示未应用补偿。

## 硬件接口

| 偏移 | 读写 | 含义 |
|---|---|---|
| `0x00` | R | `0x44505131`，DPQ1 |
| `0x04` | R | bit0：busy；bit1：至少一份快照完成且当前非 busy |
| `0x08` | W | 写 1 开始；busy 时返回 SLVERR；不支持半字节写 |
| `0x0C` | R | 每通道样本数 4096 |
| `0x10` | R | 完成序号 |
| `0x14` | R | ABI 版本 1 |
| `0x4000–0x7FFF` | R | 通道1，4096×32 bit |
| `0x8000–0xBFFF` | R | 通道2，4096×32 bit |

样本 I 在 bit11:0，Q 在 bit27:16，均为 12 位二补码。采集未完成、busy 或无效地址读取返回 SLVERR。PS 必须先查 busy、完成序号再读 RAM，读完才发新请求。

NCO 使用旧地址 `RELAY_BASE+0x14/+0x30`；只改 DDC，DUC 保留。新代码只在主动配置后取得 NCO 所有权。停止/租期/模式变化释放；检测到其他写入者时不覆盖其新值。

## 构建审查边界

现有约束下布局布线通过，不代表全设计 CDC/接口时序签核。新请求/完成两条 toggle 均被 Vivado 识别为两级同步，复位同步也识别通过。抓取端还有 32 条 CDC Critical，均追溯到厂商 `PHY_MODE` 静态 AXI 位经 ADC-valid 组合逻辑进入计数/BRAM 写使能。这不是新握手路径；实验约束为固定 2R2T、运行中不切 PHY_MODE，软件在初始化及轮询中检查该位。全设计其他遗留 CDC、输入输出延时和 RAM 异步控制警告也保留，未通过隐藏约束消除。

在正式发布/动态切换 PHY 模式之前，需要另做厂商 PHY 控制跨域整改与接口时序签核。本扩展当前仍为待实板验收的独立实验镜像。
