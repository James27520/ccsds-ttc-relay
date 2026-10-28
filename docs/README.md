# 文档索引

## 当前架构（2026-10-28）

| 文档 | 内容 |
|---|---|
| [项目首页](../README.md) | Z7ADDALite 遥控板、LDSDR 转发板和当前系统范围 |
| [遥控链路 V2](telecontrol-v2.md) | 100.5 MHz 指令链、8 字节 body、金标准及 UDP 接口 |
| [验证与待办](validation.md) | 已测结果、测试边界及未完成项 |
| [业务转发联调](rf-forward-bringup.md) | 第一条有线单音链、RX I/Q修正、改频和关闭信号对照 |
| [业务RF验证摘要](validation/2026-10-28-rf-forward.json) | 最新实测数值、固件和原始证据包 SHA-256 |
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
