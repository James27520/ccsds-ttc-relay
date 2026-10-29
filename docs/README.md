# 文档索引

## 当前架构（2026-10-29）

| 文档 | 内容 |
|---|---|
| [项目首页](../README.md) | Z7ADDALite 遥控板、LDSDR 转发板和当前系统范围 |
| [双端桌面站](../sw/ground_station/README.md) | 浅色发送/接收 GUI、独立设备、安装与操作 |
| [桌面站验证](ground-station-validation.md) | 动态文本、真实硬件链路、异常与重连测试 |
| [提速与状态回传](station-speed-telemetry-validation.md) | 2.9秒快照、TM1/UDP/SPI实板回归、BSP构建检查与剩余DAC下行 |
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
| [远端控制验证](remote-relay-validation.md) | 新固件RAM加载、板间UDP超时静音、削顶隔离；新操作射频闭环待验 |
| [验证与待办](validation.md) | 已测结果、测试边界及未完成项 |
| [反向业务与第二通道](reverse-link-validation.md) | 第二路文本转发、三窗口回信与当前六线限制 |
| [高频有线转发](frequency-range-validation.md) | 2179.5/2450.5 MHz通过，2900.5 MHz接收裕量不足；原始IQ及失败记录 |
| [业务转发联调](rf-forward-bringup.md) | 第一条有线单音链、RX I/Q修正、改频和关闭信号对照 |
| [业务RF单音摘要](validation/2026-10-28-rf-forward.json) | 单音实测数值、固件和原始证据包 SHA-256 |
| [调制文本与UDP改频](rf-payload-validation.md) | 三段BPSK文本、CRC负例、网口控制后的实际频移与内容恢复 |
| [调制业务验证摘要](validation/2026-10-28-rf-payload.json) | 最新采样/完整帧统计、边界和原始证据包 SHA-256 |
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
| [图表目录](images/) | 原报告配图；未更新为 Z7ADDALite 遥控板架构 |

后续正式提交比赛报告前，应同步修订 Word 报告和配图中的板卡角色、处理位置、帧格式及验证范围。本次保留历史原件，供追溯原实验使用。
