# 早期 RTL 与射频实验记录

本页摘录自 [2026-10-18 的项目说明](https://github.com/James27520/ccsds-ttc-relay/blob/132889d8e232d5d7d8e360340aa5e17d7f5abfd8/README.md)，用于保留已有工程的验证背景。数据来自该历史版本，本次未重新运行，也未补充核验原始 ILA 或射频数据。

它们对应早期 Zynq-7010 / AD936X 工程、固定 40 字节演示帧及相关 PC 工具，不是 Z7ADDALite 遥控板的 V2 验收结果。

## 数字环回

原记录报告 10 个抽取相位仿真通过，每帧 40 字节逐字节相同。板上 ILA 记录：

```text
frame_match   = 1
rx_crc_ok     = 1
match_cnt     = 01
rx_state_dbg  = 2
rx_err_cnt    = 0001
rx_frame_idx  = 0x28 = 40
rx_frame_byte = 0x63
```

其中 `rx_err_cnt=0001` 原样保留；不能将这条记录概括为所有错误计数均为零。历史期望帧为：

```text
02a00000180043435344532d36472d4e544e2d373031302d5454432d465047412d504f5254210463
```

历史资源报告为 LUT 6263/17600、寄存器 6120/35200、BRAM 24.5/60、DSP 0/80；WNS +1.840 ns、WHS +0.103 ns。它们不代表新 Z7020 采集工程的资源占用或时序。

## 射频实验

旧说明记录了接射频环回电缆时 RMS=2446.6、不接时 RMS=10.9，以及发送 LO 移动 1 MHz 后接收峰移动约 997.5 kHz 的现象。原记录用于辨识该实验配置下的射频路径，不证明新多板架构、所有射频端口或所有频段均可用。

## 保留文件的使用条件

- `sim/run_loopback.ps1`、其他仿真脚本包含原开发机的工具或源码路径，调整后才能在新环境复现。
- `sw/gui/ccsds_demo_gui.py` 是 40 字节遥测参数演示工具，包含原路径依赖；不是当前遥控板的串口 GUI。
- `board/` 的 U-Boot、SSH、串口操作依赖早期板卡和固件；不适用于所有 Zynq 板卡。
- `fpga/src/` 的引脚及 AD936X 接口属于原工程，不能直接下载到 Z7ADDALite。
- 原说明列出的 `fpga/build/build_ccsds_pl_ila.tcl` 和 `program_and_base.tcl` 未包含在该仓库文件集中，因此当前无法据此宣称完整板级工程一键重建。

现阶段的架构和进展以 [项目首页](../README.md)、[V2 协议](telecontrol-v2.md) 和 [最新验证记录](validation.md) 为准。
