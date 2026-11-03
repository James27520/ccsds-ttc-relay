# 波形、协议与实验工具

本目录同时保留当前程序复用的模块和早期硬件调试脚本。

| 内容 | 当前用途 |
| --- | --- |
| `telecontrol_protocol.py`、`telecontrol_waveform.py` | 当前测控命令编码、频率约束与上行波形；桌面站仍直接导入 |
| `telemetry_downlink.py` | 当前射频回报解析与接收解码；桌面站仍直接导入 |
| `rf_text_link.py` 及相邻频谱/序列检查工具 | 实验业务帧、波形及各专项验证使用；具体采样路径以调用方为准 |
| `board_loopback_test.py`、`ccsds_mode_b_test.py`、`cmu200_demo.py`、`tx_path_probe.py`、`verify_leakage.py` | 早期台架脚本，保留原COM号、设备和 `E:\ccsds_fpga` 路径假设，非当前日常启动入口 |

当前业务接收由[板端stream_rx](../../board/terminal/stream_rx/README.md)持续采样解调，不能因本目录存在旧快照工具，就把当前接收描述成反复下载短IQ快照。

日常操作见[双电脑说明](../../docs/two-computer-guide.md)，历史实验结果见[文档索引](../../docs/README.md)。本次整理没有修改脚本行为或执行硬件操作。
