# 文档索引

## 当前使用与验收（2026-11-04整理）

日常使用根目录的 `setup_station.bat`、`check_station.bat`、`start_terminal1.bat` 和 `start_terminal2.bat`。两个终端均可收发；测控从终端1窗口进入。旧版、兼容、单独测控及预览BAT已删除。

| 文档 | 内容 |
| --- | --- |
| [项目首页](../README.md) | 当前四板系统、六线连接、处理分工与使用入口 |
| [双电脑操作说明](two-computer-guide.md) | 两台电脑的安装、连接、频率配置、互发与录屏 |
| [桌面站说明](../sw/ground_station/README.md) | 终端后台、测控共享连接、收发与异常恢复 |
| [本轮验收结论](validation/20261103_acceptance.md) | 团队确认的2026-11-03验收范围 |
| [验证记录与边界](validation.md) | 按时间保留各轮证据及当时未完成项 |
| [更新日志](../CHANGELOG.md) | 项目变更时间线 |
| [六线系统与资源分配](six-link-system-plan.md) | 当前端口、本振限制及业务/测控分时方式；附历史推进记录 |
| [六线固定接线验证](six-line-validation.md) | 固定接线、改频与双向业务的分轮实测 |
| [双向业务并行验证](duplex-business-validation.md) | 两个业务方向并行收发的专项工况 |
| [接收性能与恢复](validation/20261101_receive_pipeline.md) | 常驻RX、30分钟观测、60条文本实收与恢复边界 |
| [测控与文本收发耗时](validation/20261101_control_latency.md) | 测控期间业务暂停、射频回报及恢复时间 |
| [常驻监听与接收恢复](standby-recovery-validation.md) | 遥控监听常驻与转发输出租期的区别 |
| [本机频率与转发板测控](local-frequency-ui.md) | 两端本机计划独立应用，测控不自动修改本机频率 |
| [范围内自由改频](free-frequency-plan.md) · [验收](free-frequency-validation.md) | 输入/输出频率边界、1 kHz设置步进及实测范围 |
| [遥控与状态协议](remote-relay-control.md) | 当前kHz扩展、启停、查询、ATM1/ATM2兼容 |
| [LDSDR业务频偏补偿](doppler-compensation.md) | 默认关闭的双路业务扩展、实现位置和证据范围 |
| [ADDA测控上行补偿](doppler-telecontrol-prototype.md) | 默认关闭的测控接收扩展，保留早期离线对照数据 |
| [本地源码整理记录](local-source-inventory.md) | 上传盘点、历史归档和逐文件来源清单 |

## 阶段性实验记录与协议基线

以下记录主要对应2026-10-27至29阶段，保留原频点、接线、工具与统计口径。文内“当前”“未实现”“待验”应按该轮时间理解；现行操作优先使用上表，不照搬旧版单向窗口、短快照或换线步骤。

| 文档 | 内容 |
|---|---|
| [本地源码整理与上传](local-source-inventory.md) | 当前新增实现、历史归档、逐文件来源与哈希清单 |
| [星上业务多普勒补偿](doppler-compensation.md) | LDSDR 两路预测＋测量、数字移频；基础仿真、构建证据与实板边界 |
| [项目首页](../README.md) | Z7ADDALite 遥控板、LDSDR 转发板和当前系统范围 |
| [双端桌面站](../sw/ground_station/README.md) | 现行双向终端说明，并附第一版单向GUI历史操作 |
| [桌面站验证](ground-station-validation.md) | 动态文本、真实硬件链路、异常与重连测试 |
| [提速与状态回传](station-speed-telemetry-validation.md) | 早期2.9秒快照与USB/TM1回传；DAC射频下行在后续专项完成 |
| [TM1状态协议](telemetry-status.md) | 只读USB状态帧、CRC、来源与历史保持规则 |
| [DAC下行数字实现与板端验证](telemetry-downlink-validation.md) | 前一阶段的新PL时序、DAC配置读回、有限发送与取消 |
| [测控下行SMA实收](telemetry-rf-validation.md) | 12个CRC正确帧、3份不同快照、5个停发对照；设备身份与文件GUI边界 |
| [测控下行实收摘要](validation/2026-10-28-telemetry-rf.json) | 原始IQ哈希、快照字段、收尾状态及本地证据包 |
| [测控下行GUI采集](telemetry-live-validation.md) | 当前会话绑定、约17秒单次采集、真实GUI与关闭清理验证 |
| [GUI下行采集摘要](validation/2026-10-28-telemetry-live.json) | 新增8帧、静默对照、取消和原始IQ复核索引 |
| [真实遥控与射频回报闭环](telecontrol-roundtrip-validation.md) | 同一事务的ADC_NORMAL、UDP/ACK、独立SPI与实际IQ关联 |
| [测控闭环摘要](validation/2026-10-28-telecontrol-roundtrip.json) | 两条新指令、八个下行帧、限时停发与证据包校验 |
| [六线系统计划](six-link-system-plan.md) | 双向业务及双向测控的功能分配、共用本振限制与待办 |
| [遥控链路 V2](telecontrol-v2.md) | 100.5 MHz 指令链、8 字节 body、金标准及 UDP 接口 |
| [远端启停与状态协议](remote-relay-control.md) | 显式开启/停止/查询、板端租期、双路电平和ATM2 |
| [远端控制验证](remote-relay-validation.md) | RAM加载、UDP及ADC/DAC射频启停查询闭环，保留各轮工况 |
| [验证与待办](validation.md) | 已测结果、测试边界及未完成项 |
| [反向业务与第二通道](reverse-link-validation.md) | 第二路文本转发、三窗口回信与当前六线限制 |
| [高频有线转发](frequency-range-validation.md) | 2179.5/2450.5 MHz通过，2900.5 MHz接收裕量不足；原始IQ及失败记录 |
| [业务转发联调](rf-forward-bringup.md) | 第一条有线单音链、RX I/Q修正、改频和关闭信号对照 |
| [业务RF单音摘要](validation/2026-10-28-rf-forward.json) | 单音实测数值、固件和原始证据包 SHA-256 |
| [调制文本与UDP改频](rf-payload-validation.md) | 三段BPSK文本、CRC负例、网口控制后的实际频移与内容恢复 |
| [调制业务验证摘要](validation/2026-10-28-rf-payload.json) | 该轮采样/完整帧统计、边界和原始证据包 SHA-256 |
| [业务序列与稳定性](rf-stability-validation.md) | 311.136秒保持输出、离散序列快照、UDP改频及拒绝/恢复的实测范围 |
| [稳定性验证摘要](validation/2026-10-28-rf-stability.json) | 本轮帧/条件比特统计、时延口径及原始证据校验索引 |
| [独立接收板验证](independent-receiver-validation.md) | COM18独立采样、两频点业务内容、UDP/SPI/RF关联及身份边界 |
| [独立接收摘要](validation/2026-10-28-independent-receiver.json) | 8窗口统计、设备双重身份绑定及证据包校验和 |
| [真实ADC与业务分时验证](adc-business-staged-validation.md) | 四组实际指令、设置保持、换线后独立接收业务及停发对照 |
| [分时验证摘要](validation/2026-10-28-adc-business-staged.json) | ADC/ACK/SPI关联、6窗口统计、无中途改频检查及证据包校验和 |
| [真实指令闭环摘要](validation/2026-10-28-analog-loop.json) | 有线100.5 MHz指令、ADC解调、UDP和SPI读回 |
| [GUI验证摘要](validation/2026-10-28-gui-loop.json) | 实板自动控制启停及验证范围 |
| [早期验证摘要](validation/2026-10-27.json) | 当日前期产物与测试记录，后续结果见验证与待办 |

## 历史实现与资料

以下文件在架构调整前入库。它们保留原有实验和工具信息，不能替代当前遥控板的说明或作为新架构已完成的证据。

| 文档 | 适用范围 |
|---|---|
| [历史验证摘录](legacy-validation.md) | 原 40 字节 RTL 环回和射频实验记录 |
| [原空间包/串口协议](../sw/link/PROTOCOL.md) | PC/RK3588 到 LDSDR 串口适配，保留历史兼容约定 |
| [FPGA 实现报告](reports/面向6G的卫星测控与转发载荷_FPGA实现报告.docx) | 原 Zynq-7010/AD936X 架构、40 字节演示帧和图表 |
| [遥测链路总结](reports/CCSDS遥测链路_总结报告.docx) | 早期遥测链路实现与实验 |
| [演示工具手册](reports/CCSDS演示工具_参数与演示手册.docx) | 原参数表 GUI 的模式与操作 |
| [图表目录](images/) | 混合保存当前总体架构图、补偿实验图及历史配图；以引用文档的日期和范围为准 |

历史Word报告中的板卡角色、处理位置、帧格式及验证范围可能与现行实现不同，正式引用前需逐项核对。本次保留历史原件，供追溯原实验使用。

## 早期工具与仍被复用的源码

| 位置 | 使用范围 |
| --- | --- |
| [sim/](../sim/README.md) | 早期RTL链路仿真，保留原开发机路径；当前板级验证见各board子目录 |
| [sw/gui/](../sw/gui/README.md) | 早期参数表演示GUI，非当前双电脑桌面站 |
| [sw/tools/](../sw/tools/README.md) | 同时含当前复用的波形/协议模块和早期硬件脚本，不能整目录当作废弃代码删除 |
| [Linux串口工具](../board/board_serial.ps1)、[串口记录](../board/serial_log.ps1)、[U-Boot工具](../board/uboot_stop.ps1) | 早期Linux SDR调试，保留COM12与原机器路径假设，不属于当前双电脑启动流程 |
| [历史源码归档](../archive/local_sources/README.md) | 去重后的原件及来源索引，保留原字节和哈希，不参与当前启动 |
