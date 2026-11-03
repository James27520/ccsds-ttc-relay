# GitHub RTL、FPGA、仿真、板级脚本与技术报告核对

审查日期：2026-10-26。审查基线：`James27520/ccsds-ttc-relay`，`main`，提交 `132889d8e232d5d7d8e360340aa5e17d7f5abfd8`。

本报告是静态阅读结果。本次没有运行仿真、综合、实现、烧写、串口命令、网络改频或射频实验；历史文档中的 PASS 与仪器数据均不代表本次复测。仓库位于 `C:\Users\Lu\Desktop\全国大学生嵌入式芯片与系统设计竞赛\ccsds-ttc-relay`。以下源码路径均相对此根目录，行号对应上述提交。DOCX 用已提取文本的 `[段落号]` 定位，原文保留在 `docs/reports/`。

## 1. 结论与复用边界

现有仓库值得复用：它具有 CCSDS 发射编码链、板上固定帧数字环回接收链、AD936x LVDS 接口、SPI 初始化、单元仿真和历史调试经验。但它没有提交一套可直接重建、通过网口收参数、动态修改 RX/TX 本振并持续转发外部业务信号的完整转发板 PL/PS 工程。README 中的“转发板”是系统角色描述和已有串口 CLI 接口描述，不能据此认定当前 `system_top.v` 就是该转发固件。

因此后续应保留和核对既有资产，先补齐原始转发工程与构建依赖，再按用户的 ADDA＋转发板架构适配。不能把当前数字环回顶层直接当成用户的双向射频转发板烧写。

| 范围 | 当前静态确认 | 仍不能据此确认 |
|---|---|---|
| CCSDS 发射 | 随机化、卷积编码、ASM、BPSK、零插值、固定系数 FIR 源码齐全 | PC 填参数后动态送进现有板上发射链 |
| CCSDS 接收 | 匹配滤波、10 相位 ASM 搜索、简化硬判决译码、解随机化、CRC、40 字节输出 | 真正 Viterbi 纠错、频偏/载波恢复、持续多帧、外部 RF 接收 |
| 板级接口 | AD936x SPI、2R2T LVDS 拆装、时钟和复位源码 | 当前板型号、引脚、参考时钟与用户手中硬件完全一致 |
| 变频控制 | README 描述 `lo <rxMHz> <txMHz>` 等已有 CLI | CLI 对应的 PS 驱动/程序、PL 转发通路和网口服务存在于本仓库 |
| 构建与验证 | 仿真源文件、操作脚本及历史文字结论 | 克隆后能够原样重建、历史位流与当前源码一一对应 |

## 2. 真正连接起来的链路

`fpga/src/system_top.v` 是当前板级顶层。其真实路径为：

```text
固定 40 字节帧
  → ccsds_tx / datalink / coder / BPSK / SRRC
  → 8 位内部 sam_i tap ───→ ccsds_rx_lvds → 40 字节 → 固定字节比对 → ILA
  → 12 位 TX0 I/Q → data_process → AD936x LVDS TX

AD936x LVDS RX → data_process → rx0_i/q、rx1_i/q    （未接到上述 CCSDS 接收机）
TX1 I/Q = 0
```

- 顶层端口仅有系统时钟及 AD936x 控制/SPI/LVDS，没有 PS DDR/FIXED_IO、AXI 控制、以太网或 UART 参数入口：`system_top.v:1–30`。
- 固定发射链输出给 TX0：`system_top.v:138–158`；TX1 两路置零：`:160–161`。
- RX 模块实际输入 `.sam_i(ccsds_sam_i_tap)`、`.sam_q(8'd0)`：`:183–211`，尤其 `:194–195`；外部接收样点只出现在接口连接 `:324–327`。
- 接收结果比对常量 `EXPECTED_FRAME`：`:223–224`。`frame_match` 为粘滞标志，匹配后保持 1：`:240–247`。该置位条件没有同时要求 `crc_ok`；CRC 是单独探针。
- `ila_0` 探针：`:289–303`。在当前仓库中找不到 `ila_0` 实现、XCI 或生成 Tcl。
- `data_process.v` 提供两路 I/Q 的 LVDS 拆装；这是一份接口层资产，并不等于已经接好了 RX1→TX2 / RX2→TX1 的双向业务转发。

`rtl/ccsds_rxtx/ccsds_rxtx_top.vhd` 另有上游 Wishbone 控制框架，可控制使能与数据，但它没有接到当前 `system_top`，不能当作已有 PS/Ethernet 参数桥。

## 3. 固定项、可配置项与接收能力

### 发射帧与控制入口

- `ccsds_tx_datalink_layer.vhd:67` 默认 `CCSDS_TX_DATALINK_STATIC_FRAME_ENABLED=true`；`:138–140` 定义固定 40 字节帧，`:182–189` 选择固定帧，`:192` 起才是另一条上游组帧路径。
- `rtl/adapter/ccsds_tx_lvds.v:107–109` 的 `dat_par_i/dat_ser_i/dat_val_i` 全接常量零。因此上位机参数表没有通过该顶层注入 PL。
- 独立的 `frame_gen.vhd` 是有价值的动态组帧模块：配置端口 `:61–65`、载荷写入 `:68–70`、触发 `:73`，双缓冲与 CRC 流程 `:98–105、237–283`。但它没有被当前 `system_top`/`ccsds_tx` 路径实例化；`dat_o` 在 `:302` 只给首字，完整帧经 `frame_o` 输出，接入时要明确串行化和握手。
- `AD936X_Init.v:18–19` 查静态 LUT；模块端口 `:1–14` 无动态频率输入，初始化结束进入保持状态 `:71`。
- `AD936X_lut.v:10` 注释为 40 MHz 参考，`:1695` 注释为 RX/TX 均 2400 MHz，`:1730–1743` 是固定 RX/TX 频率字；不是运行时根据网口命令更新频率的接口。寄存器值受实际参考时钟影响，不能直接把注释的 MHz 当作用户板当前实测频率。

### 接收算法实际边界

- `ccsds_rx_lvds.v:167–179` 保存单一路径的 6 位历史，计算输入候选 0/1 的两个卷积输出并精确匹配，选择其中一个。没有多状态路径度量、ACS、幸存路径或回溯，**不是 Viterbi 译码器**。非法输出对计数也不等价于恢复后 BER。
- 接收只使用实数 I 样点（`:131`），Q 输入未用于解调；没有载波恢复、频偏补偿或一般异步符号时钟跟踪。
- `:184–208` 确有多相位 ASM 搜索，锁定某一路抽取相位。`PHASE` 参数仅在 `:54` 声明，现行算法不引用它。
- 固定帧长度默认为 40 字节；`:369–379` 收完后进入 `ST_DONE` 并保持，需要复位或撤销使能才能再收下一帧。因此现版本不具备持续指令流接收。
- `frame_valid` 在 `:372` 置位，CRC 比较在 `:298–301` 后续时钟完成。未来控制消费者必须等待校验结果，不能看到 `frame_valid` 就直接下发硬件命令。
- 上游 `ccsds_rx_physical_layer.vhd:50–52` 仅拼接 I/Q 到数据总线；`ccsds_rx_datalink_layer.vhd:45–52` 是透传/占位。不能通过文件名将这套上游 `ccsds_rx.vhd` 当作已完成调制解调器。

### 适配 ADDA 前必须处理的技术项

- SRRC 暴露滚降/过采样/量化位宽泛型，但当前 `ccsds_rxtx_srrc.vhd:44–160` 实为固定 61 抽头、8 位样点及固定系数。改变泛型不会自动重算系数或位宽。
- `ccsds_rxtx_srrc.vhd:202、210–214` 先把移位结果缩成 8 位，再与 127/-128 比较，超限分支无法实现真正饱和。应在宽位宽上判饱和后截断，并做边界/幅度回归；本次未修复、未运行验证。
- `sim/gen_srrc_signals.py:44–60、161–168` 从 `t=0` 起生成半边序列，再按对称输入对相乘；最终系数最大值位于两端而不是常规居中脉冲位置。这是应做独立脉冲响应/频响检查的风险，现有文字“SRRC×SRRC 符号点无 ISI”不能替代检查。
- `clk_pll.v:37–40` 的 50 MHz 时钟假设，与 `AD936X.xdc:73–76` 所述 38.4 MHz→76.8 MHz、数据 122.88 MHz/采样 30.72 MHz 不一致；实际 XDC 时钟在 `:81` 约束 RX 输入，不能凭 README 自动认定所有时钟约束完整。
- `AD936X.xdc:60–61` 含降低布线/未约束管脚检查约束，不适合直接复制到 ADDA。必须以实际板原理图、ADC/DAC 类型和连接方式为准。

## 4. 构建与仿真能复用什么、先补什么

| 发现 | 证据 | 实际影响 |
|---|---|---|
| 构建脚本没有提交 | README `:211、242–243、255–256` 提及 `fpga/build`；实际文件树无此目录和 Tcl | 不能按快速开始重建/下载 |
| 缺工程/IP配置 | 无 XPR/BD/XCI、无 PS C/H/BSP/FSBL/ELF/BOOT；`system_top.v:289` 需要 `ila_0` | 需要原始 Tcl、器件配置、ILA 探针定义、PS 工程及依赖清单 |
| 忽略规则可能漏掉脚本 | `.gitignore:64` 为通用 `build/` | 新建 `fpga/build` 脚本也会被默认忽略；属于缺失原因线索 |
| 备用 DDS 缺 IP | `fpga/src/DDS.v:58` 实例化 `blk_mem_gen_0`，仓库无实现；当前顶层未用 DDS | 仅影响选用该备用 DDS 时，不能误记为当前顶层必要依赖 |
| 机器路径硬编码 | 5 个 PS1 仿真入口均含 `E:\ccsds_fpga`、旧 ModelSim 安装路径；Python 校验器另引用 `E:\fpga_sdr_project\ccsds_ttc_loopback\sw\ttc` | 不能在此电脑原样运行；需先相对路径/工具路径配置 |
| 多个 TB 使用旧帧长 | `tb_coder_only.vhd:29–34`、`tb_framer_coder.vhd:32–39` 使用 160 bit 旧测试帧；主环回使用 320 bit | 单元向量可复用，但不能把所有 TB 的 PASS 混为当前系统端到端 PASS |
| 相位扫描未改变信号 | `tb_ccsds_loopback.v:54、64` 只传 PHASE，RX 内该参数未用 | 当前 0–9 十次运行相同设计，不是十种真实输入延迟/采样相位覆盖 |
| 环回 PASS 范围窄 | `tb_ccsds_loopback.v:71` 数字直连同源时钟；`:176` 检查字节一致+CRC | 无 AWGN、频偏、独立时钟、连续帧/丢帧、动态参数压力覆盖 |
| 失败退出不可靠 | `run_loopback.ps1:109–115` 和 `run_rx_ideal.ps1:107–114` 主要打印结果；TB 超时仍可能 `$finish` | 自动化必须将超时、FAIL、错误帧数变成失败退出码 |
| TX 检查器阈值偏宽 | `check_tx_chain.py:100–126` 只要至少一帧 CRC OK 就 PASS，期望载荷不同只打印 | 不能证明全部帧/指定载荷成功 |

建议保留当前固定帧数字环回作为回归基线；补可重现构建后再增加独立延迟、噪声、频偏、连续帧、CRC 错误拒绝、动态参数和真实外部 RX 样点测试。仿真只是后续计划，本次没有执行上述脚本。两份 `gen_*srrc*.py` 会写 RTL 文件，不能作为“只读检查”直接运行。

`board/` 都是操作辅助工具：`board_serial.ps1` 面向 Linux shell，`board_ssh2.ps1` 面向 root@192.168.2.1，`uboot_stop.ps1` 会发 reboot 并拦截启动，`unbind_cmd.sh` 解绑原厂驱动。它们不包含转发板网口收包、CLI 实现或频率控制固件。本次没有执行。

## 5. 三份 DOCX 与 README 的证据等级

三份 DOCX 的全部提取正文已阅读。下表段落号来自 `development_planning/research` 下同名 `.txt`，是正文顺序索引，不是 Word 页码。

| 文件与段落 | 报告内容 | 可据此记录的历史结果 | 不能扩展的结论 |
|---|---|---|---|
| 《CCSDS演示工具_参数与演示手册》[321–332] | A 纯软件、B 原厂固件经 IIO、C 自定义 PL | 三种路径有明确区分 | B 成功不能证明自定义 PL 接收外部 RF |
| 同上 [403–420] | 模式 C 用 ILA，固定帧自环，PC 不下发参数 | 文档明确承认当前 PL 固定帧边界 | GUI 已能给 FPGA 动态填参 |
| 同上 [389–402] | 不接 SMA 的内部泄漏与 TX LO 挪移实验 | 历史单芯片 RF 路径辨识方法 | 已证明双板业务透明转发、任意 RF 输入接收 |
| 《CCSDS遥测链路_总结报告》[433–455] | 数字 ILA、一帧匹配、模式 B 电缆/泄漏差值 | 固定帧环回与 PC 解码测试的文字记录 | 8192 个采样窗不是 8192 帧；`rx_err_cnt=1` 不是零 BER |
| 同上 [554–564] | 后续“接转发板”“以太网下发”“FPGA 参数注入”“真实双板 RF” | 明确证明这些集成项当时尚列为后续 | 项目已完成用户草图所有链路 |
| 《面向6G的卫星测控与转发载荷_FPGA实现报告》[561–591] | 仿真、ILA、PC 过板、CMU200 频谱 | 历史声称 CMU200 观测 2400.200 MHz、关闭下降 29.2 dB | 未提交原始仪器截图/原始数据，不能本次独立复核 |
| 同上 [644–658] | CCSDS RX 移植转发板、Ethernet/寄存器桥、参数注入、双板 RF 待做 | 支持“已有算法和独立实验，需要系统集成”的判断 | “遥控板解析已实现”不能自动说明解析位于 PL 或下发已贯通 |
| README `:153–193` | ILA、10 相位仿真、RF 与资源时序表 | 仓库作者报告的历史测量值 | 当前提交可重建、持续满速收发及双向可改频已证实 |

证据缺件：没有随仓库提交对应 ILA CSV/WDB/LTX/位流、对应构建/布局布线报告、仿真 transcript/结果文件、IQ 原始采样、CMU200 原始记录以及固件构建清单。`docs/images/` 仅有五张说明性系统框图；另核对 DOCX 嵌入媒体，FPGA 报告的五张嵌图与这五张 PNG 的 SHA256 逐一相同，其他两份 DOCX 没有嵌入图片。因此不存在藏在 DOCX 媒体中的仪器截图。资源占用与时序数值只能标记“报告记载”，不能当本次审查重新测得的余量。

需要纠正/避免继续传播的表述：

- README `:94` 与 FPGA 报告 [125] 的“卷积码＋Viterbi”不能用来描述当前 Verilog 硬件 RX；软件参考中存在 Viterbi 不等于 RTL 已实现。
- 报告 [630] “全部 RTL 自研”与 README `:424–429` 明确声明 EurySPACE 上游来源不一致。应保留上游 MIT 声明并准确说明修改范围。
- “variable＋for 是综合通病”“无第三方 IP”“10 相位硬件一定锁上”“全速连续完成”均是过强概括。当前缺少最小复现/网表证明，而且存在上述固定系数、单帧保持等实际限制。
- 参数表含频段、加密、极化等字段，仅代表传输格式设计；不能由此推出硬件已实现加密、外部参考切换或极化控制。

## 6. 规划阶段的优先缺口

1. 用户已确认手中转发板始终是同一块 LDSDR，电脑1/GUI＋ADDA＋LDSDR 为本机开发范围。仓库历史角色名称与资料包配置只能说明来源和适配差异，不能据此推断用户有另一块实物。后续延续已经实测的 LDSDR 工程，按需核对参考资料。
2. 取得与现有 CLI 对应的转发板 PS/PL 源工程、Tcl、IP 参数及已验证版本。核实本地 `relay_udp_work` 与该版本的关系；不用从零重写已经存在的转发逻辑。
3. 冻结 PC1/ADDA 两路接口的物理含义及频率、样率、信号格式；决定 ADDA 做实数 IF 还是 I/Q，不能把 AD936x 接口直接迁移过去。
4. 冻结统一控制消息及状态回读，区分“收包成功”“参数应用成功”“读回一致”“RF 频点改变”“业务内容/质量保持”。不同层分别验收。
5. 恢复可重现构建与回归基线，补齐依赖后再接动态输入、CRC 完成握手、持续接收和网络控制；保留固定帧测试模式供排查。
6. 用独立信号源/ADDA 输入和接收观察点验真实通路，分别检查两向通道。内部 tap 环回只能用于模块回归。

## 7. 阅读覆盖与重复关系

`rtl/、fpga/、sim/、board/` 共 111 个文本文件，SHA256 去重后 77 份独立内容。34 个副本按哈希相同只读一份：`fpga/src/ccsds/` 下 32 个文件与 `rtl/ccsds_rxtx/` 同名文件逐个相同；另两份为 `fpga/src/ccsds_rx_lvds.v`、`fpga/src/ccsds_tx_lvds.v` 与 `rtl/adapter/` 下同名文件。

核心链路、独立功能模块、全部仿真/板级脚本及 testbench 已阅读。`AD936X_lut.v` 是 2715 行静态寄存器表：按全表结构索引及配置块阅读，重点核对接口/时钟/频率/结束标记；没有把每个寄存器值与 ADI 数据手册逐条做电气正确性认证。所有独立文件清单和哈希对应关系如下（自动索引）。

| 独立内容代表文件 | 行数 | SHA256（前16位） |
|---|---:|---|
| `board/uboot_stop.ps1` | 100 | `7e70aa401a555b32` |
| `board/board_serial.ps1` | 119 | `07fab3ad19cedc2a` |
| `board/serial_log.ps1` | 46 | `0cc635ff5dfdda38` |
| `board/unbind_cmd.sh` | 9 | `59ae949b5b4283d1` |
| `board/board_ssh2.ps1` | 63 | `6a1a7d2ee31f5113` |
| `fpga/src/rst_gen_module.v` | 49 | `45245ccd7919e4cf` |
| `fpga/src/system_top.v` | 335 | `d8a8942f384d3a8c` |
| `fpga/src/clk_pll.v` | 65 | `591487efc5a94411` |
| `fpga/src/AD936X_lut.v` | 2715 | `3efb68e991f14feb` |
| `fpga/src/AD936X_Driver.v` | 357 | `38e5979099f4d6c3` |
| `fpga/src/AD936X_Init.v` | 188 | `2eaa5b5b9d1a7a89` |
| `fpga/src/spi_drive.v` | 196 | `710b5e573782e753` |
| `fpga/src/CLK_DIV_module.v` | 53 | `951d899b53fdd960` |
| `fpga/src/data_process.v` | 273 | `15d1b6ea1b1e7148` |
| `fpga/src/selectio_wiz_0.v` | 165 | `b7099bef4e200b6f` |
| `fpga/src/DDS.v` | 76 | `886082a502b96a52` |
| `fpga/src/AD936X.xdc` | 81 | `92f492a5c4e6aca3` |
| `rtl/adapter/ccsds_rx_lvds.v` | 385 | `347b88b4fe26dcad` |
| `rtl/adapter/ccsds_tx_lvds.v` | 165 | `f800682d3893fa76` |
| `rtl/ccsds_rxtx/ccsds_rx_datalink_layer.vhd` | 53 | `bec05441a7517f30` |
| `rtl/ccsds_rxtx/ccsds_rx_physical_layer.vhd` | 66 | `90f1250d94544d87` |
| `rtl/ccsds_rxtx/ccsds_rx.vhd` | 126 | `480f226c4e46e521` |
| `rtl/ccsds_rxtx/ccsds_rxtx_bench.vhd` | 2767 | `b9d77ca816a58a7e` |
| `rtl/ccsds_rxtx/ccsds_rxtx_buffer.vhd` | 141 | `fad6c18ad8be42a8` |
| `rtl/ccsds_rxtx/ccsds_rxtx_clock_divider.vhd` | 106 | `9eb9341cbbc2254c` |
| `rtl/ccsds_rxtx/ccsds_rxtx_constants.vhd` | 20 | `f2dd8e9f7abe8da4` |
| `rtl/ccsds_rxtx/ccsds_rxtx_crc.vhd` | 342 | `99d6f8003635cf78` |
| `rtl/ccsds_rxtx/ccsds_rxtx_functions.vhd` | 135 | `fac919132e5443e1` |
| `rtl/ccsds_rxtx/ccsds_rxtx_lfsr.vhd` | 250 | `c6ac27608efc1418` |
| `rtl/ccsds_rxtx/ccsds_rxtx_oversampler.vhd` | 113 | `86344c824618d9b7` |
| `rtl/ccsds_rxtx/ccsds_rxtx_parameters.vhd` | 42 | `b28d2714c5a4aa15` |
| `rtl/ccsds_rxtx/ccsds_rxtx_serdes.vhd` | 156 | `0689b423222a22ba` |
| `rtl/ccsds_rxtx/ccsds_rxtx_srrc.vhd` | 223 | `2b7c4c3ad2f524f7` |
| `rtl/ccsds_rxtx/ccsds_rxtx_top.vhd` | 322 | `b4000ab15ee89333` |
| `rtl/ccsds_rxtx/ccsds_rxtx_types.vhd` | 25 | `e8f13383ccfd1476` |
| `rtl/ccsds_rxtx/ccsds_tx_coder_convolutional.vhd` | 166 | `0c03d4a615e6917a` |
| `rtl/ccsds_rxtx/ccsds_tx_coder_differential.vhd` | 89 | `785da98ca61656ef` |
| `rtl/ccsds_rxtx/ccsds_tx_coder.vhd` | 241 | `f75424eba8251f84` |
| `rtl/ccsds_rxtx/ccsds_tx_datalink_layer.vhd` | 297 | `632ffdb4c61549d7` |
| `rtl/ccsds_rxtx/ccsds_tx_filter.vhd` | 247 | `632806ea4e5caf9c` |
| `rtl/ccsds_rxtx/ccsds_tx_footer.vhd` | 93 | `57f320bd423ebbeb` |
| `rtl/ccsds_rxtx/ccsds_tx_framer.vhd` | 363 | `b3cdb41bdaf3929e` |
| `rtl/ccsds_rxtx/ccsds_tx_header.vhd` | 159 | `9ce1a5aef94560f4` |
| `rtl/ccsds_rxtx/ccsds_tx_manager.vhd` | 203 | `93b49af5d5d324a4` |
| `rtl/ccsds_rxtx/ccsds_tx_mapper_bits_symbols.vhd` | 153 | `158784963822b8d0` |
| `rtl/ccsds_rxtx/ccsds_tx_mapper_symbols_samples.vhd` | 99 | `2531447c96a33473` |
| `rtl/ccsds_rxtx/ccsds_tx_physical_layer.vhd` | 133 | `e9a1534381d08919` |
| `rtl/ccsds_rxtx/ccsds_tx_randomizer.vhd` | 106 | `d2678ebcf8691540` |
| `rtl/ccsds_rxtx/ccsds_tx_synchronizer.vhd` | 93 | `fb180cbb474c7dd2` |
| `rtl/ccsds_rxtx/ccsds_tx.vhd` | 233 | `a280eba77444db03` |
| `rtl/ccsds_rxtx/frame_gen.vhd` | 309 | `494e48a1ec0e7a09` |
| `rtl/adapter/ccsds_tx_wrap.v` | 189 | `412ca80c71946442` |
| `sim/run_tx_chain.ps1` | 94 | `d01588807826a73e` |
| `sim/check_lfsr_vhdl.py` | 53 | `f221c40ea80e8571` |
| `sim/bench/tb_datalink.vhd` | 191 | `cbd5e38bef586013` |
| `sim/bench/tb_coder_only.vhd` | 139 | `00c4d5c608b1bad9` |
| `sim/gen_simple_srrc.py` | 211 | `77c64600d77d8d47` |
| `sim/bench/tb_ccsds_loopback.v` | 199 | `941fe110f0385198` |
| `sim/bench/tb_ccsds_rx_ideal.v` | 207 | `0a981362acdbfd52` |
| `sim/bench/tb_lfsr.vhd` | 85 | `0d0c96498f2a0168` |
| `sim/bench/tb_frame_gen2.vhd` | 220 | `0ed808d7307863e8` |
| `sim/bench/tb_ccsds_tx_chain.vhd` | 342 | `14f38e5f253cf97e` |
| `sim/run_loopback.ps1` | 121 | `1939e580df6693bb` |
| `sim/bench/tb_tx_full.vhd` | 137 | `1a7a9b449b1e2d7e` |
| `sim/check_frame_gen.py` | 123 | `3215d7f9245092df` |
| `sim/gen_rx_stimulus.py` | 108 | `32d7d2998c70a959` |
| `sim/check_coder_only.py` | 52 | `4184362254cfdd39` |
| `sim/bench/tb_phys.vhd` | 179 | `47be05dac6901c51` |
| `sim/check_framer_coder.py` | 123 | `4fda006807396132` |
| `sim/check_tx_chain.py` | 131 | `5012814412f9f496` |
| `sim/bench/tb_framer_coder.vhd` | 208 | `5c743c7afa754bdf` |
| `sim/check_lfsr_standard.py` | 70 | `6624afd443fdfad9` |
| `sim/verify_standard_randomizer.ps1` | 80 | `7fcf625551e7e18e` |
| `sim/diag_coder.py` | 117 | `86f6ea1e40492f9f` |
| `sim/run_sim.ps1` | 97 | `924076af8fda539b` |
| `sim/run_rx_ideal.ps1` | 119 | `9d2d96934690d288` |
| `sim/gen_srrc_signals.py` | 222 | `fcd46c1426d6512a` |

完整重复对应：

- `fpga/src/ccsds_rx_lvds.v` = `rtl/adapter/ccsds_rx_lvds.v`（SHA256 相同）
- `fpga/src/ccsds_tx_lvds.v` = `rtl/adapter/ccsds_tx_lvds.v`（SHA256 相同）
- `fpga/src/ccsds/ccsds_rx_datalink_layer.vhd` = `rtl/ccsds_rxtx/ccsds_rx_datalink_layer.vhd`（SHA256 相同）
- `fpga/src/ccsds/ccsds_rx_physical_layer.vhd` = `rtl/ccsds_rxtx/ccsds_rx_physical_layer.vhd`（SHA256 相同）
- `fpga/src/ccsds/ccsds_rx.vhd` = `rtl/ccsds_rxtx/ccsds_rx.vhd`（SHA256 相同）
- `fpga/src/ccsds/ccsds_rxtx_bench.vhd` = `rtl/ccsds_rxtx/ccsds_rxtx_bench.vhd`（SHA256 相同）
- `fpga/src/ccsds/ccsds_rxtx_buffer.vhd` = `rtl/ccsds_rxtx/ccsds_rxtx_buffer.vhd`（SHA256 相同）
- `fpga/src/ccsds/ccsds_rxtx_clock_divider.vhd` = `rtl/ccsds_rxtx/ccsds_rxtx_clock_divider.vhd`（SHA256 相同）
- `fpga/src/ccsds/ccsds_rxtx_constants.vhd` = `rtl/ccsds_rxtx/ccsds_rxtx_constants.vhd`（SHA256 相同）
- `fpga/src/ccsds/ccsds_rxtx_crc.vhd` = `rtl/ccsds_rxtx/ccsds_rxtx_crc.vhd`（SHA256 相同）
- `fpga/src/ccsds/ccsds_rxtx_functions.vhd` = `rtl/ccsds_rxtx/ccsds_rxtx_functions.vhd`（SHA256 相同）
- `fpga/src/ccsds/ccsds_rxtx_lfsr.vhd` = `rtl/ccsds_rxtx/ccsds_rxtx_lfsr.vhd`（SHA256 相同）
- `fpga/src/ccsds/ccsds_rxtx_oversampler.vhd` = `rtl/ccsds_rxtx/ccsds_rxtx_oversampler.vhd`（SHA256 相同）
- `fpga/src/ccsds/ccsds_rxtx_parameters.vhd` = `rtl/ccsds_rxtx/ccsds_rxtx_parameters.vhd`（SHA256 相同）
- `fpga/src/ccsds/ccsds_rxtx_serdes.vhd` = `rtl/ccsds_rxtx/ccsds_rxtx_serdes.vhd`（SHA256 相同）
- `fpga/src/ccsds/ccsds_rxtx_srrc.vhd` = `rtl/ccsds_rxtx/ccsds_rxtx_srrc.vhd`（SHA256 相同）
- `fpga/src/ccsds/ccsds_rxtx_top.vhd` = `rtl/ccsds_rxtx/ccsds_rxtx_top.vhd`（SHA256 相同）
- `fpga/src/ccsds/ccsds_rxtx_types.vhd` = `rtl/ccsds_rxtx/ccsds_rxtx_types.vhd`（SHA256 相同）
- `fpga/src/ccsds/ccsds_tx_coder_convolutional.vhd` = `rtl/ccsds_rxtx/ccsds_tx_coder_convolutional.vhd`（SHA256 相同）
- `fpga/src/ccsds/ccsds_tx_coder_differential.vhd` = `rtl/ccsds_rxtx/ccsds_tx_coder_differential.vhd`（SHA256 相同）
- `fpga/src/ccsds/ccsds_tx_coder.vhd` = `rtl/ccsds_rxtx/ccsds_tx_coder.vhd`（SHA256 相同）
- `fpga/src/ccsds/ccsds_tx_datalink_layer.vhd` = `rtl/ccsds_rxtx/ccsds_tx_datalink_layer.vhd`（SHA256 相同）
- `fpga/src/ccsds/ccsds_tx_filter.vhd` = `rtl/ccsds_rxtx/ccsds_tx_filter.vhd`（SHA256 相同）
- `fpga/src/ccsds/ccsds_tx_footer.vhd` = `rtl/ccsds_rxtx/ccsds_tx_footer.vhd`（SHA256 相同）
- `fpga/src/ccsds/ccsds_tx_framer.vhd` = `rtl/ccsds_rxtx/ccsds_tx_framer.vhd`（SHA256 相同）
- `fpga/src/ccsds/ccsds_tx_header.vhd` = `rtl/ccsds_rxtx/ccsds_tx_header.vhd`（SHA256 相同）
- `fpga/src/ccsds/ccsds_tx_manager.vhd` = `rtl/ccsds_rxtx/ccsds_tx_manager.vhd`（SHA256 相同）
- `fpga/src/ccsds/ccsds_tx_mapper_bits_symbols.vhd` = `rtl/ccsds_rxtx/ccsds_tx_mapper_bits_symbols.vhd`（SHA256 相同）
- `fpga/src/ccsds/ccsds_tx_mapper_symbols_samples.vhd` = `rtl/ccsds_rxtx/ccsds_tx_mapper_symbols_samples.vhd`（SHA256 相同）
- `fpga/src/ccsds/ccsds_tx_physical_layer.vhd` = `rtl/ccsds_rxtx/ccsds_tx_physical_layer.vhd`（SHA256 相同）
- `fpga/src/ccsds/ccsds_tx_randomizer.vhd` = `rtl/ccsds_rxtx/ccsds_tx_randomizer.vhd`（SHA256 相同）
- `fpga/src/ccsds/ccsds_tx_synchronizer.vhd` = `rtl/ccsds_rxtx/ccsds_tx_synchronizer.vhd`（SHA256 相同）
- `fpga/src/ccsds/ccsds_tx.vhd` = `rtl/ccsds_rxtx/ccsds_tx.vhd`（SHA256 相同）
- `fpga/src/ccsds/frame_gen.vhd` = `rtl/ccsds_rxtx/frame_gen.vhd`（SHA256 相同）

另已阅读全文：`README.md`、`.gitignore`，以及前述三份 DOCX 的提取正文。
