# CCSDS 测控与变频转发实验系统

本项目面向嵌入式芯片与系统设计竞赛，实现遥控指令接收、频率参数解析和业务信号变频转发。当前遥控板采用 **Z7ADDALite（Zynq-7020 + AD9643）**，由 PL 采集 ADC 数据、PS 执行 C 解调与指令处理，再通过以太网控制 **LDSDR 转发板**。

截至 **2026-10-27**，r4c 完整 M2 已通过临时 JTAG 上板验证：A/B 全通道四个抽取位置的内部 PN9/checker 快照、normal 样点格式与模式切换均通过板端及独立 DDR 检查；板载 ARM 合成波形解调自测通过。PHY 地址识别修复后，`network on` 成功并自动协商至 1000 Mbps，PC 到遥控板连续 10 次 ping 全部成功（<1～2 ms）；UART_NETTEST 来源的遥控板→LDSDR 双板 UDP RF_SET、匹配ACK及独立SPI频率读回已通过，真实 100.5 MHz 指令接收与业务RF仍待验收。

Z7ADDALite 的 FPGA、PS、GUI、可移植测试 runner 和 BSP 重建入口已归档至 [board/z7addalite/](board/z7addalite/README.md)。重建需要外部工具链、2018.3 embeddedsw 源归档及匹配的硬件产物；第三方依赖与命令见板级说明。原有 RTL 环回、PC 演示软件和串口工具继续保留为早期实现。

## 系统组成

| 角色 | 当前硬件或职责 | 说明 |
|---|---|---|
| 电脑 1 / 电脑 A | 操作界面、参数设置、状态与日志 | 串口 GUI 的自检、normal/training 采集、空输入解调及状态显示已实测；双板UART_NETTEST另经串口命令验证，GUI nettest按钮未实测 |
| 发送端 | 提供业务信号和遥控指令信号 | 对应旧草图左上角“ADDA”的替换板；具体型号、端口和固件需在联调前逐板登记 |
| **遥控板** | **Z7ADDALite，XC7Z020-2CLG484-I，AD9643 ADC** | 接收 100.5 MHz 中频指令，PS 解调后通过网口控制转发板；DAC 不参与当前接收链 |
| **转发板** | **LDSDR** | 接收频率设置，执行业务信号变频转发；实际射频频段以该实物及固件验证结果为准 |
| 模拟板 / 电脑 2 | 业务端发送、接收与验证 | 保留原系统角色，板卡身份、信号方向及端口在多板联调时确认 |

旧草图下方的名称仍为“遥控板”，现在由 Z7ADDALite 承担。资料目录名 `7010_AD9363_SDR` 不代表另有一块转发板，也不能用来推断 Z7ADDALite 的器件型号。

下面给出当前优先验收的指令链和一条业务转发方向；它不是全部双向端口的接线图。

```mermaid
flowchart LR
    PC[电脑 1 / 电脑 A] -->|串口监控| TC[遥控板 Z7ADDALite]
    SRC[发送端] -->|100.5 MHz 中频指令 / SMA| TC
    TC -->|以太网 UDP RF_SET| RELAY[转发板 LDSDR]
    SRC -->|业务信号 f1| RELAY
    RELAY -->|变频后业务信号 f2| RX[模拟板 / 接收端]
    RX --> PC2[电脑 2]
```

SMA 接线前需确认实际 TX/RX 端口、输入允许电平和衰减配置。协议中的频率范围与示例值不等于实物全频段可用，短同轴线也不能当作已知衰减器。

## 遥控板接收链

1. AD9643 以名义 **125 MSPS** 采样。双通道 DDR 1:8 解串后，每个 31.25 MHz 向量包含 4 个 A 通道和 4 个 B 通道样点。
2. 固定选择一路的一个样点位置，形成 **31.25 MSPS** 数据流；每次保存 **131072 个 16 位样点，共 256 KiB、4.194304 ms**。
3. PS 裸机 C 程序进行平方律载波恢复、下变频、滤波、符号同步、Viterbi 译码、解随机化和 CRC 校验。
4. 校验通过的 V2 指令给出接收频率、转发频率和序号。控制层将其转换成原 LDSDR 接口的 **26 字节 UDP RF_SET**，匹配成功回执后才记录为已确认生效。

100.5 MHz 在上述采样与抽取路径中最终折叠到 6.75 MHz。当前固定抽取尚无数字抗混叠滤波，真实模拟输入的噪声、干扰和动态范围仍需验证。现阶段按短数据块解调，不宣称连续无间断接收。

详细字段、字节序、金标准向量及 UDP 回执见 [遥控链路 V2 协议](docs/telecontrol-v2.md)。该链路采用自定义短帧，使用 CCSDS 相关同步与编码方法；不据此宣称完整 CCSDS TM/TC 标准符合性。

## 验证进展

| 项目 | 已有结果 | 验证范围 |
|---|---|---|
| M1：ADC 数字接口 | 两次临时 JTAG 加载、六段采集，98,304 个 A 通道样点，PN9 错误 0；B 通道棋盘码及配置读回正确 | 实板内部测试码，不是外部模拟输入 |
| M1：时序 | WNS +0.483 ns，WHS +0.075 ns，TNS/THS = 0 | 已上板 PN9 诊断版本 |
| M2：完整采集工程 | r4c WNS +0.483 ns、WHS +0.022 ns、WPWS +0.264 ns；TNS/THS/TPWS=0，DRC=0；全通道/四个k的真实快照检查通过 | 56条ADC路径与198个动态mailbox端点已复核；normal仅格式与切换，未接外部信号 |
| M3：C 解调 | 三组帧金标准、45组合成波形通过；最终完整M2固件在A9解调131072点合成波形278 ms通过 | ADC_TEST decode未找到有效帧、未发RF_SET；不代表真实信号接收或持续吞吐率 |
| M4：网络控制 | 报文/ACK与网络负例通过；实板PHY识别、1000 Mbps协商及PC→遥控板ping 10/10通过 | UART_NETTEST双板UDP四个成功事务及network off拒绝通过；真实ADC指令与业务RF待验收 |
| 多板通信 | ADDA→LDSDR的26字节RF_SET、匹配ACK及独立SPI频率读回通过 | 来源为UART_NETTEST；未接SMA，完整空口遥控链和业务RF仍待验收 |

完整记录、产物摘要和未完成项见 [验证与待办](docs/validation.md)。早期 40 字节 RTL 环回结果见 [历史验证记录](docs/legacy-validation.md)，两者使用不同的板卡与协议路径。

## 仓库内容与使用范围

| 路径 | 当前内容 | 适用范围 |
|---|---|---|
| [rtl/](rtl/) | 早期 CCSDS 编解码、滤波与板级适配模块 | 40 字节演示帧的 RTL 路径 |
| [fpga/src/](fpga/src/) | AD936X 板级顶层、接口、约束及工程内 RTL 副本 | 早期射频板工程，不能直接用于 Z7ADDALite |
| [sim/](sim/) | 原 RTL 的测试台和仿真脚本 | 含开发机路径依赖，使用前需调整工具和源码路径 |
| [sw/ccsds/](sw/ccsds/) | 40 字节遥测演示帧编解码与参数表 | 不是 V2 的 8 字节指令实现 |
| [sw/gui/](sw/gui/) | 原遥测参数演示 GUI | 含原开发机的模块搜索路径；不是新遥控板 GUI |
| [sw/link/](sw/link/) | 原空间包封装和 LDSDR 串口 CLI 适配 | 保留旧线格式兼容约定，见该目录协议说明 |
| [board/z7addalite/](board/z7addalite/README.md) | r4c PL、PS、GUI源码及重建/测试/快照工具 | 当前Z7ADDALite路线；工具需匹配产物及明确线缆 |
| [sw/tools/](sw/tools/)、其余 [board/](board/) | 原板卡实验和调试脚本 | 旧工程范围，运行前核对目标板、固件、地址与工具路径 |
| [docs/](docs/) | 当前架构与验收说明、历史图表和报告索引 | 以本 README、V2 协议和最新验证记录为当前描述 |

原 README 中的旧 `fpga/build/build_ccsds_pl_ila.tcl`、`program_and_base.tcl` 未纳入仓库。当前路线使用 [PL冻结构建入口](board/z7addalite/telecontrol_system/README.md)、[PS/BSP重建入口](board/z7addalite/ps_software/README.md) 和 [串口GUI](board/z7addalite/host_software/README.md)。

原脚本中的 U-Boot/Linux 操作针对早期射频板，不能直接用于当前裸机遥控板。Z7ADDALite 的新工程使用 Vivado 2026.1；PS 采用 standalone C + lwIP，已通过现有工具生成 BSP 并运行 ARM 自测，无需为了这条路线安装旧 SDK 2018.3。

## 文档与许可

- [当前遥控链路 V2 协议](docs/telecontrol-v2.md)
- [验证结果和后续验收项](docs/validation.md)
- [早期 RTL 与射频实验记录](docs/legacy-validation.md)
- [旧空间包与串口 CLI 协议](sw/link/PROTOCOL.md)
- [文档及历史报告索引](docs/README.md)

本项目及第三方组件的许可与署名见 [LICENSE](LICENSE)。EurySPACE CCSDS RX/TX 来源及原始文件头继续保留；厂商工具、板卡资料和未随仓库分发的驱动不因本次文档更新而改变许可范围。
