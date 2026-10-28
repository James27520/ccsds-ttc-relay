# 遥控板 DAC 测控下行

本目录在冻结的 `../telecontrol_system` r4c 上派生新工程，保留 ADC125 接收、PS 网络及原采集 ABI，增加独立的有限长度 DAC 状态发送链。目标器件仍为实物确认的 `xc7z020clg484-2`。原 r4c 输入不修改，候选工程另行综合、布局布线和导出；不能把新增源码复制进旧工程后沿用旧时序结论。

2026-10-28候选04已完成数字/时序及板端验证；随后J6/DAC1经SMA进入SDR，三次有限发送实际恢复12个CRC正确帧、3份不同快照，五个停发窗口无有效帧。工作点和完整边界见[下行实收报告](../../../docs/telemetry-rf-validation.md)。

## 发送路径

PS 将最近解码、UDP 发送、匹配成功 ACK 三阶段的独立记录编码为 96 字节 ATM1 负载。外层沿用已有业务实验帧 `AA AA | LEN8 | payload | CRC16_BE`，CRC 覆盖负载。这是项目自定义实验遥测帧，不是完整 CCSDS 标准遥测帧，也不改变现有 CCSDS 风格的遥控上行协议。

PS 装入一组 420 字节、3360 位的有限发送数据：64 位交替前导、四份相同状态帧、64 位交替尾部。四份帧表示同一个状态快照，不计作四次新指令。PL 按 MSB first 调制矩形 BPSK，100 ksym/s；DDS 90.5 MHz，250 MSPS，固定峰值 128/32768。完整发送约 33.6 ms，结束后归零，没有自动循环或自动续发。

AD9122 使用字模式、I 路数据/Q 路零、四倍插值、DCI delay=3，DAC 转换时钟为 1000 MHz。配置完成后仍需显式发送命令。SPI 关键读回失败、时钟失锁、复位、取消均禁止继续发送。频率、电平估计和接口时序依据见 [DAC_CLOCK_REVIEW.md](DAC_CLOCK_REVIEW.md)；数字幅度不能替代真实 SMA 电平测量。

## 重建与验证

需 Vivado 2026.1、Python 3；在仓库根目录执行。所有 Vivado 运行目录使用新的纯 ASCII 路径。

```powershell
$env:VIVADO_BIN = '<Vivado安装目录>\bin'
pwsh -File board/z7addalite/telemetry_downlink/scripts/run_packet_sim.ps1
pwsh -File board/z7addalite/telemetry_downlink/scripts/run_dac_config_sim.ps1
pwsh -File board/z7addalite/telemetry_downlink/scripts/run_dac_io_sim.ps1
pwsh -File board/z7addalite/telemetry_downlink/scripts/run_build.ps1 -OutputRoot C:\fpga_build\tm_candidate -Python python
```

`prepare_build.py` 先校验冻结 r4c 的源清单，再复制并应用受检查的顶层修改：导出 ADC DCO 给 DAC MMCM、在原 CTRL 窗口内增加 `0x43C01000` 外设、复位与 SPI 控制、DDR 输出、DAC 专用约束。运行目录的清单记录全部派生输入及覆盖文件摘要。原 PS GP0 地址表与采集 RAM 不变，发送缓存独占 512 字节，不挪用采集 RAM。

构建须同时满足原 ADC 时序、DAC 16 路双沿 setup/hold、两个新增 mailbox 的实际数据路径约束、DRC 与内部约束覆盖。DAC 的异步复位到输出弧单独排除；正常 D1/D2 到输出数据路径仍完整计时。导出入口同时检查原 STA 与 TM STA 通过，并在导出前重查新增 DAC 路径。审阅通过后，才在运行目录执行 `scripts/export_reviewed.ps1 -Reviewed`。综合/仿真/导出都不等于射频实测通过。

## PS 命令与接收

默认 PS 构建 `ADDA_TM_TX_ENABLED=0`，不会访问新增寄存器，继续适用于 r4c。新 PL 只配套显式传入 `build_platform.py --tm-tx-enabled` 的 `_tm.elf`；其 XSA、初始化脚本及位流应先做绑定检查。详细寄存器见 [ABI.md](ABI.md)。

- `tmstatus`：只读发送状态、DAC 配置读回结果。
- `tmsend`：提交一个当前状态快照，发送完自动停。没有网络连接时也可报告该状态。
- `tmstop`：取消；启动期间外设尚在复位时延后提交，避免向拒写窗口发出 MMIO 写入。
- `tmclear`：空闲且取消握手结束后，显式清除发送缓存和故障。它不能修复 DAC 配置或时钟故障。

上电默认停发；PS 初始化只请求 STOP。状态的事件号、序号和 uptime 会在 PS 初始化后重新开始，不具备跨重启唯一性或认证功能。ACK 频率属于远端 ACK 报告，独立 SPI 仍单独核对。不能把 `ADC_TEST`、`SYNTHETIC` 或 `UART_NETTEST` 标成真实 ADC 指令。

接收端离线工具只从接收板的实际 I/Q 文件解调，不读取发送端状态或待发送负载：

```powershell
python -m sw.tools.telemetry_downlink received_iq.bin --offset 500000
```

此例对应DAC名义90.5MHz、接收LO90MHz；采样数据为2.5MSPS、int16 LE交错I/Q，须按接收板实际格式校核。工具对长记录使用重叠窗口并合并重复检测；当前实收使用262144点（104.8576ms）记录，窗口宽65536点。有限发送与采样仍需安排时间重叠，不能保证任意异步单次采样都会收到。合成信号测试和实际SMA结果分别记录。

本阶段不改变六线方案的共享本振限制。独立下行验证与双向业务、测控并发仍需分开验收。
