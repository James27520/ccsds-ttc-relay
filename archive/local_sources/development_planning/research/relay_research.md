# 转发板资料与历史实现核对

调研日期：2026-10-26。范围为本机资料、压缩包源码和已保存的历史验证记录；本轮未连接板卡、重新上板、综合或运行硬件测试。以下相对路径均相对于 `C:/Users/Lu/Desktop/全国大学生嵌入式芯片与系统设计竞赛`。

## 主要结论

用户已明确确认：手中转发板始终是同一块 LDSDR，`7010_AD9363_SDR` 是用户为该板提供的资料目录。本报告以这一确认作为实物身份依据，不再推断另有一块实物。2026-10-18 的 UDP 改频实测与 LDSDR 工程、对应 PL 和 PS 初始化构成已经验证的实现基线。资料目录内另有 2021.1 ADI工程、Pluto 固件和不同目标器件配置；这些是资料版本/适配差异，不能据此否定用户确认。后续优先延续已验证 LDSDR 基线，需要引用资料包内容时核对引脚、器件、DDR和寄存器适配。

真正具有两路独立 DDC/DUC 控制的转发 RTL 在本机 `LDSDR_010`。`relay_udp_work` 内同名 RTL 是较早的两路共享 NCO/控制版本；其 UDP 软件是已实测版本，但应与最新双路 RTL 分别管理，不能仅按文件名整目录覆盖。

## 用户确认的实物与两套资料的对应关系

| 项目 | 7010_AD9363_SDR 资料 | LDSDR 历史基线 |
| --- | --- | --- |
| 厂商/来源 | 用户手册第 2 页写 OPENSDR 社区，这是手册来源说明 | 用户确认实物为 LDSDR；本机已有 LDSDR_010 工程与实际验证记录 |
| Zynq 型号 | 手册第 5 页同时列 XC7Z010-CLG400 / XC7Z020-CLG400；资料包内纯 PL xpr、ADI PS+PL BD 默认是 **xc7z020clg400-2** | `LDSDR_010/zynq_dev_fmcomms3.xpr:10` 为 **xc7z010clg400-1**；10/18 `verification_logs/program_udp_final.txt` 的实际 JTAG 目标列出 **xc7z010** |
| 工具版本 | vendor 工程 `Vivado2021.1工程`，xpr/BD 确认 2021.1；Pluto 移植源码链接目录标 2022.2 Linux | xpr 第 2 行是 Vivado 2018.3；10/18 软件构建用既有 ARM GCC 12.3.1 + 归档 BSP，XSDB 2026.1 下载 |
| 射频通道 | 手册第 6、17 页为双发双收，TX1A/RX1A、TX2A/RX2A；原理图第 15 页可见这四个射频口 | 历史交接称 AD9363-BBCZ、2R2T LVDS；当前源代码存在两个 I/Q 数据通道 |
| 数字接口 | 原理图第 13 页为 6 对 RX、6 对 TX 差分线以及 frame/clock；纯 PL `data_process.v` 按 LVDS 2R2T 解包为两路 12 bit I/Q | 自定义 `ad9361_phy`，12 bit I/Q、valid；与 ADI `axi_ad9361` 端口不相同 |
| 时钟 | 原理图第 13 页有 40 MHz RF 参考晶振；PS 例程 `main.c:182` 同为 40 MHz | 10/18 日志最终采样率 30.72 MSPS；后续换配置应按新的时钟链重新核对 |
| USB 调试 | 原理图第 10 页为 **FT2232HL**，JTAG 与 UART | 会话历史硬件检测为 **FT4232H**，与 `LDSDR_010/原理图_文字提取.txt:260` 的 FT4232HL 相符；最终测试日志记录 COM13。资料包 FT2232HL 差异只说明资料对应关系待适配，不能推断有另一块实物 |
| 网口 | 原理图第 6 页 RTL8211E-VB-CG；手册第 5 页千兆以太网 | 10/18 日志协商到 1000 Mbps，GEM0 UDP 服务已响应 |
| 启动软件 | 出厂资料写 pluto-fw-v0.38；Linux/IIO 路线与纯 PL、裸机例程均存在 | FSBL + 原 PL + 裸机应用；已验证 UDP ELF 为 JTAG 内存加载版本 |

两套资料中的 bitstream、FSBL、BSP 和 ELF 必须按已有 LDSDR 实测基线选择。7010/7020 器件目标、速度等级、DDR 参数、引脚和 AXI 地址的静态差异属于适配审查项；当前以已验证 LDSDR 工程为开发起点，不另要求用户重复确认实物身份。

## 7010_AD9363_SDR 现有工程实际完成什么

### 纯 PL 例程

压缩包：`7010_AD9363_SDR/Vivado2021.1工程/纯PL驱动/AD936X_only_PL.zip`。

- `AD936X_only_PL.xpr:10` 的默认器件为 xc7z020clg400-2，历史另有 xc7z010 的 run，但不能由此推断主工程适用于手中芯片。
- `Src/system_top.v:114–161` 四个 DDS 产生两路 I/Q：通道 0 为 1 MHz、通道 1 为 2 MHz，DDS 参数假定采样时钟 56 MHz。
- `Src/system_top.v:163–172` 把接收与发射数据接入 ILA；`175–204` 连接 `data_process`。
- `Src/data_process.v:24–51` 提供两路 12 bit I/Q，`54–64` 从 DATA_CLK 分频，后半段按 frame 序列解包、打包。
- 此例程的 TX 数据由 DDS 提供，未看到 RX→DDC/DUC→TX 的透明转发连接，也没有 PS/GEM 控制接口。它可作为该板的 LVDS 收发与初始化参考，不能称为已完成转发器。
- 压缩包附有 `AD936X_only_PL.runs/impl_1/system_top.bit`，仅确认文件存在，未验证可在当前实物使用。

### PS 加 PL 例程

压缩包：`PL_PS驱动/AD936X_PL.zip` 与 `AD936X_PS.zip`。

- `AD936X_PL.zip!/projects/fmcomms2/zc702/zc702.srcs/sources_1/bd/system/system.bd` 的 design_info 为工具 2021.1、器件 xc7z020clg400-2。
- BD 使用 ADI `axi_ad9361`、ADC/DAC DMA、pack/unpack、FIFO 和 PS7；当前组件列表没有 LDSDR 的 `relay_dq` 或 `axi_ctrl`。
- GEM0 已启用，RGMII 为 MIO16–27，MDIO 为 MIO52–53；此处与 LDSDR 归档 HDF 的 ENET0 关闭状态不同。
- `AD936X_PS.zip!/AD936X/src/main.c:178–214` 默认 ID_AD9361、2R2T、FDD、RX/TX LO 均 1 GHz、初始收发采样链最终 15 MSPS；`main.c:355` 开启 LVDS。编译条件可覆盖初始化，不能只截取一个默认数值作为运行事实。
- `AD936X/src/app_config.h:50–62` 选择 XILINX_PLATFORM、ADC_DMA_EXAMPLE、DAC_DMA_EXAMPLE，IIO_SUPPORT 注释关闭。
- `AD936X/src/parameters.h` 使用 ADI AXI AD9361/DMA 基址与 GPIO 定义，与已验证 LDSDR `XPAR_AXI_CTRL_0_BASEADDR=0x43C00000` 控制窗口并不等价。
- 压缩包附 `system_top.bit`、`system_top.xsa`，仅确认存在，未验证该套压缩包与手中 LDSDR 实物的适配。

### 网络和 Linux 路线

- `测试接口工程/Test_PS.zip!/ETH_FreeRTOS/src/main.c:41–54` 是 lwIP/FreeRTOS 网口示例，默认 `192.168.1.10/24`；它提供网络初始化参考，未与转发 RF_SET 业务整合。
- `Pluto固件相关/出厂所带SD卡为固件pluto-fw-v0.38.txt` 标明出厂 SD 固件版本。
- `基于pluto-fw-v0.38移植固件（支持网口和USB）/使用方法.txt` 说明 SD 启动、USB 虚拟网卡和手工配置 eth0。手册第 11 页示例地址是 192.168.1.10；该值是资料示例，不代表手中 LDSDR 当前地址。
- 此目录 `SD卡固件/uEnv.txt` 写 `mode=1r1t`，但手册第 17 页展示双路环回。这属于资料包中 Pluto 路线的默认值，不能覆盖已验证 LDSDR 裸机程序在 `main.c:456` 选择 2R2T 的事实。
- `基于ZC706-FMCOMMS2-3移植固件(支持网口）` 是另一启动路线，说明文件称板端固定 192.168.1.10，使用 BOOT.BIN/image.ub/rootfs 等；不能与 Pluto USB 路线混用。
- 出厂 Linux 与纯 PL 接管硬件时，驱动/寄存器映射和看门狗行为需要匹配。现有仓库的 U-Boot 停驻操作也不能被当作普遍适用的裸机启动流程。

## 已有转发模块在哪里

| 本地实现 | 可复用内容 | 关键边界 |
| --- | --- | --- |
| `LDSDR_010/zynq_dev_fmcomms3.srcs/sources_1/new/relay_dq.v` | 双通道转发、独立 mode/gain/DC/DDC/DUC；四个 NCO（161、165、169、173 行） | 延续 LDSDR PHY 可直接沿用接口；只有选择迁移至 ADI AXI 核时才需要适配使能、样点排列、位宽和时钟域 |
| 同目录 `relay_path.v`、`relay_cmix.v`、`relay_nco.v`、`relay_sin_rom.v` | 12 bit 复数乘法、DDC/DC/DUC/增益路径、饱和逻辑 | 可复用算法核心，不直接照搬板级 XDC/时钟约束 |
| 同目录 `relay_cdc.v` | 控制跨时钟域、计数快照 | 需与新的 AXI/数据时钟及更新语义一起审查 |
| `LDSDR_010/repo/axi_ctrl/axi_ctrl_v1_0_S00_AXI.v` | 双路寄存器，CH2 位打包与计数器；274–276 行有 ch2 默认值，577 行输出 mode2 | 需同步维护软件寄存器接口 |
| `relay_udp_work/IoT-NTN-FPGA-Relay/ps/relay_rf_packet.h` | 26 字节 RF_SET 解析、CRC、范围检查 | 只有一组 RX LO/TX LO 与统一增益/衰减；不是四路独立频率协议 |
| 同目录 `relay_rf_control.h` | 设置本振、独立驱动读回、临时静音、失败恢复旧设置 | 静音操作依赖已验证 AXI 控制窗口，保持该基线可复用 |
| 同目录 `relay_udp.h` | lwIP raw UDP 服务，169.254.9.10:5005 | 继续满足已验证 LDSDR PL 与 PS 初始化约束；不可混用资料包另一工程的启动配置 |
| 同目录 `relay_cli.h` | UART CLI、`rfread` 独立 SPI 本振读回 | 与 vendor main.c 全局状态/驱动及 BSP 耦合 |
| `relay_udp_work/send_rf_udp.py`、`tools/test_udp_rf.py` | 电脑端 RF_SET 与实板证据记录流程 | 需支持最终统一协议与可配置地址；历史原始记录保持独立 |

注意：`relay_udp_work/IoT-NTN-FPGA-Relay/rtl/relay_dq.v` 第 118 行附近只有共享的两个 NCO，两个通道使用同一 mode/gain/DDC/DUC。不要以它替换 `LDSDR_010` 中已有双路独立版本。

现有 LDSDR 的线路是 RX1→TX1、RX2→TX2（`relay_dq.v:184–215`）；草图可能画成 RX1→TX2、RX2→TX1。需由用户确认是实际交叉转发需求还是标签摆放差异，之后再决定内部交换还是调整物理接线。

## 2026 年 10 月 18 日可确证的实板结果

证据文件：`relay_udp_work/verification_logs/udp_rf_verified_final_20261018.json` 与 `udp_deploy_final_20261018.json`。

| 用例 | 原始结果 |
| --- | --- |
| 同频配置 | rc=0；SPI 读回 RX 900000000、TX 1000000000 Hz |
| 单独更改接收 LO | rc=0；RX 900999998 Hz，TX 保持 1000000000 Hz |
| 再更改发射 LO | rc=0；TX 1000999998 Hz，RX 保持 900999998 Hz |
| 错 CRC | rc=-3，两个 LO 保持 |
| 错长度 | rc=-1，两个 LO 保持 |
| 越界频率 | rc=-4，两个 LO 保持 |
| 恢复基线 | rc=0，RX/TX 恢复 900/1000 MHz |

日志还包含 PHY 协商为 1000 Mbps、UDP ready、PL 输入输出计数推进以及 `rfread` 返回。它验证控制链与芯片配置读回，不证明整条 ADDA↔转发↔模拟板业务链路已完成，也不证明射频实测输出频率或低误码传输。

`firmware/release_manifest.json` 对应 ELF 为 868624 字节、SHA256 `c37843bf31165e12124d267f1104f2e5fb22ab1121dfeae22122d8a3bd9183cd`，标明 JTAG warm load、`cold_boot_image_created=false`。`scripts/build_udp_standalone.py:3、62、206` 明确硬件约束是既有 LDSDR PL，且 GEM0 MIO/MDIO 必须已初始化。它是该 LDSDR 已验证的内存加载版本，不是可任意搭配资料包中其他 PS/PL 初始化的通用上电镜像。

历史 `fpga_sdr_project/项目交接文档.md` 声明双路转发和射频、CCSDS 软件端到端曾通过，且有 E: 盘另一台电脑路径、COM5/COM11 等。此文是队友历史陈述，本轮未取得对应完整原始实测记录，不能把这些数字计入本轮验收。文中 CMOS 1R1T 表述也与本次读取的资料包 LVDS 例程不同，应按实际选用工程和芯片运行模式处理。

## RF_SET 当前合同

`relay_rf_packet.h` 接受固定 26 字节：6 字节空间包头、18 字节参数、2 字节 CRC-16（poly 0x1021、init 0xffff）。头 ID 必须为 0x0101，序列号低 14 位，分段标志 0xc000，长度字段 17。参数为大端 uint64 RX Hz、大端 uint64 TX Hz、uint8 RX gain dB、uint8 TX attenuation dB。解析器范围为 70 MHz–6 GHz、增益 0–76、衰减 0–89，但这是软件拒绝范围，**不等于 AD9363 板卡在整个范围都满足射频指标**。

成功后返回 ASCII `rc=0 seq=... rx_hz=... tx_hz=...`，控制器接受 10 kHz 以内驱动读回差异。当前代码给 RX0/RX1 同样增益、TX0/TX1 同样衰减。要提供逐通道控制或确认执行后的状态，需要明确升级合同，不应让新 GUI 暗示已有这些能力。

## SMA 传输 helloworld 的物理接口结论

用户目标是 ADDA 通过 SMA 与 LDSDR 传输 `helloworld`。字符串需要先编码为帧，再调制成模拟波形；接收端须完成解调和帧校验，才能在 GUI 恢复文字。SMA 是模拟连接器，不会自行把 ASCII 字节送入 AD9363。项目已有 CCSDS/BPSK 算法和双路转发核心可承担其中部分处理，载频及电平应由开发侧设计和验证。

### AD9363 官方指标和本振结构

[ADI AD9363 Rev.D 数据手册](https://www.analog.com/media/en/technical-documentation/data-sheets/ad9363.pdf) 第 1、3、4 页规定收发载频 325 MHz–3.8 GHz、通道带宽最高 20 MHz。第 4 页的发射功率典型测试结果为 800 MHz 处 8 dBm、2.4 GHz 处 7.5 dBm，条件为 50 Ω 负载和 1 MHz 单音。第 15 页列射频输入峰功率绝对最大额定值 **+2.5 dBm**；这不是正常工作目标，也不能保证接近它时不压缩。

[ADI 收发器架构说明](https://wiki.analog.com/resources/eval/user-guides/ad9361) 的 Receive Chain 和 Transmit Chain 分别说明：RX1/RX2 共用一个接收频率合成器，TX1/TX2 共用一个发射频率合成器。收发两组本振可以不同，各组内部两条通道不能任意指定相隔很远的独立 LO。数字 DDC/DUC 可以在各自采样带宽内引入独立偏移，但不改变模拟前端的通带。该 Wiki 概述的 AD9363 最低频率数字与数据手册不一致，频率范围采用正式数据手册值，Wiki 仅用于架构说明。

本地 `relay_rf_packet.h` 允许 70 MHz–6 GHz，是驱动/应用配置范围；手册也提到按 AD9361 模式使用。**因此 70 MHz 等扩展频点只可列为需实测的候选，不能当作 AD9363 保证指标。** 10/18 的 900/1000 MHz SPI 读回也没有测量输入输出射频幅度或误码率。

### 板级模拟路径与电平

`7010_AD9363_SDR/硬件资料/原理图.pdf` 第 15 页所示 SMA 分别接 TX1A/RX1A/TX2A/RX2A，经过巴伦及 18 pF 耦合电容；它们属于射频口，未直接引出基带 I/Q 模拟输入。`LDSDR_010/原理图_文字提取.txt:4010–4150` 也包含 RX1/RX2/TX1/TX2 的巴伦/耦合路径，但本轮未找到该文本对应的原始 PDF，不能用它确认每一个器件值都与手中板版本一致。两套资料的元件和型号差异仍应限定为资料适配问题。

ADDA 子调研已从厂家教程获得约 1.2 Vpp 的 DAC 例程幅度，但负载条件未明确。若 **实际加在 50 Ω 接收口上的正弦** 为 1.2 Vpp，计算平均功率 `P=Vpp²/(8R)` 得到约 **+5.56 dBm**，已高于上述芯片绝对最大值；如果 1.2 Vpp 是开路值，接入匹配负载后的功率会不同。因此首个联调动作必须在已知终端负载下确认幅度，再设置数字幅度和需要的无源衰减，不能把厂家 DAC 满幅例程直接作为互联默认值。对调制波形还需留出峰均比余量。

ADDA 配置中“1 GSPS DAC 转换速率”并不代表板级 SMA 在 900/1000 MHz 工作；双路 ADC 250 MSPS 也不独自决定可用载频。现阶段没有整板模拟通带测量足以确认两板在官方支持 RF 频段直接互通，也不能据此断言必须购买外部变频器。应先由开发侧选取候选频点、配置插值/数字搬频或带通采样，做受控单音和回环测量，再冻结 `helloworld` 的载频与波形。若实测无法得到足够通带/动态范围，才提出具体变频器方案及依据。 ADDA 专项调研提出约 350 MHz 的直接互联候选：AD9122 利用插值、粗搬频与 NCO，AD9643 以 250 MSPS 对 350 MHz 带通信号欠采样至 100 MHz。它只是芯片能力层面的候选；现有例程仍输出 1 MHz，整板 350 MHz 通带、信噪比及 DAC I/Q 耦合对双通道业务的影响尚未验证。具体寄存器与证据见同目录 adda_research.md，不能作为已经可用的硬件配置。

建议实施顺序为：数字帧/解调仿真 → ADDA 单板已知波形与幅度校准 → 单音经过 SMA 到 LDSDR 的接收验证 → 短帧 `helloworld` → 双向或经完整转发链的端到端验证。第一步选软件参考模型与现有硬件核心复用，并不要求用户先理解或指定外部混频器。

## 需要主规划询问用户的项目

| 事项 | 需要确认的内容 | 对实现的影响 |
| --- | --- | --- |
| 转发模式 | 每个方向是否都透明转发；RX1→TX2 / RX2→TX1 是否为确定的通道映射？ | 决定是否交换数据路径，不能仅按草图猜测 |
| 四路频率 | 两个方向目标载频、带宽、是否同时运行，是否期待每个物理端口独立设 LO？ | 现有协议只有 RX/TX 两个全局 LO；每通道独立偏移需要利用数字 DDC/DUC及可用带宽 |
| 控制入口 | 草图“遥控板→转发板网口”是唯一业务控制入口吗？电脑1是否只调试转发板，正式运行仍经遥控链下发？ | GUI 控制路由、ACK来源、是否直连网口的设计不同 |
| 文字传输目标 | 用户已明确希望经 SMA 传输 helloworld；仅需进一步明确首版单向演示还是双向回传及期望显示方式 | 具体载频、调制、幅度和是否需变频模块由工程调研决定，不能要求用户先自行解决接口问题 |

## 本轮实际阅读范围

完整提取并阅读了 7010 用户手册 17 页、原理图 15 页文本；视觉核对用户手册第 6 页与原理图第 10、13、15 页（渲染文件保存在 `research/relay_tmp`）。检查五个 Vivado2021.1 压缩包的目录，提取并阅读纯 PL 用户 Src、xpr、ADI PS main.c/app_config.h/parameters.h、ADI 顶层 BD 关键组件/PS配置、FreeRTOS网络 main.c；未展开所有生成缓存或全部厂商驱动。

完整阅读已验证 RF_SET/UDP/控制头、对应主程序初始化关键段、relay_dq/path/reg、最终部署和7项测试JSON/manifest；对照 LDSDR 双通道 relay_dq、AXI 寄存器、BD连线与 xpr；阅读历史交接的硬件定义、双路转发、软件测控链与 FPGA 移植章节。没有把“文件存在”提升为“当前板实测通过”。

