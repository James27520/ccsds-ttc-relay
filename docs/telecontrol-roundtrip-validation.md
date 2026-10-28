# 真实遥控与射频回报的同一事务验证

本阶段沿用已加载的 Z7ADDALite candidate04 与匹配 PS 程序，验证真实 ADC_NORMAL 指令、板间 UDP/ACK、LDSDR 独立 SPI 和 DAC 射频返回的事务关联。采用顺序执行，不同时运行业务转发，不改 Flash/SD。

2026-10-28，两条新指令均通过，实际下行各恢复4个CRC正确帧。完整证据索引见[结构化摘要](validation/2026-10-28-telecontrol-roundtrip.json)。

## 实测结果

| 空口序号 | 请求 RX/TX MHz | UDP序号 | 解码/发送/ACK事件 | 独立SPI RX/TX Hz | 下行DAC序号 | 有效帧 |
| --- | --- | --- | --- | --- | --- | --- |
| 240 | 900 / 1001 | 5 | 9 / 10 / 11 | 900000000 / 1000999998 | 18 | 4 |
| 241 | 900 / 1000 | 6 | 12 / 13 / 14 | 900000000 / 1000000000 | 19 | 4 |

两次 `decoded` 分别由0→1、1→2，`applied` 由4→5、5→6，`failures` 始终0。所有三阶段记录均为 ADC_NORMAL，空口序号与频率一致，发送与ACK使用同一UDP序号。第二笔通过真实上行恢复基线频率，没有本地 `lo` 或 UART_NETTEST 替代。下行采样结束再读 SPI，频率与对应 ACK 及先前 SPI 一致。

每份 IQ 为262144个复数样本，均无削顶，RMS分别约18.09和18.64码；载波相对90MHz接收LO约+500029Hz。每次四个重复帧只代表一笔事务的一份快照，不作为四条指令。原始IQ重新解码并逐帧核对负载及CRC，结果一致。

本版每笔完整诊断流程约113秒，包含多次身份核验、波形准备、网络启动、ADC控制、接收角色切换、下行采集和清理；其中下行采集约16.9秒。后续GUI整合需同时减少重复核验带来的等待，但保留关键阶段的身份与停发检查。

另在遥控板auto/network/ARM关闭时验证源板30秒保护：开启同一工作点后，主机33秒不发控制命令，随后读回TX LO关闭、DMA为0、两路89dB衰减、guard stopped；迟到的enable_request未重新启发。此段没有新ADC解码或UDP应用，不计入两笔闭环结果，也不是拔掉USB/断电测试。

162项地面站软件回归通过，包括13项事务证据测试；会话测试整理后13项针对性回归通过。覆盖CRC错误、错误来源/事务、旧快照、错频率、设备重启、忙状态拒绝、清理故障及禁止主机绕过保护直接启发。软件fixture与上述真实采样分别记录。

## 接线与执行顺序

用户已将发送板 TX1A → LDSDR RX1 这根线的接收端移至遥控板 ADC1/J5。其他连接保持：遥控板 DAC1/J6 → 同一发送板 RX1A/JP2；LDSDR TX1 → 独立接收板 RX1A；遥控板与 LDSDR 网线直连。全部 DEBUG USB 保留，无天线。

验证工具为 `python -m sw.ground_station.tc_roundtrip`。先只读核验三块参与板卡，再显式确认接线才允许配置临时指令源。命令源采用既有 V2 波形生成器，名义 100.5 MHz、100 ksym/s、数字峰值 0.1、TX 衰减 30 dB；请求限定在已验证的 RX900/901、TX1000/1001 MHz。本轮下行沿用 90.5 MHz、数字峰值 128/32768、单次 33.6 ms，接收增益 20 dB。

每笔事务按以下步骤执行：

1. 确认源 TX 关闭、DMA 空闲，遥控板 auto/network/arm/pending 均关闭，LDSDR mode2、增益0、衰减89dB。
2. 启用板间网络，确认就绪；ARM 后只进行一次 `capture normal 0 0`。等待新 ADC 快照 READY，再停止指令源。
3. 对这份快照只执行一次 C 解调，要求 ADC_NORMAL 来源、正确序号及频率，applied 只增加1、failures 不增。
4. 等匹配 ACK，再读取 LDSDR 独立 SPI；之后关闭控制、ARM、网络，保留该事务的三条历史记录。
5. 将同一 SDR 切换为下行接收；延续原 USB/Linux 启动身份及遥控板 uptime 约束。接收缓冲就绪后显式发送一次 DAC 回报。
6. 从实际 IQ 独立解码，逐帧重新校验 ATM1 CRC，再比较 decoded/send/ACK 的来源、事件、空口序号、UDP序号、频率及计数。ACK 与独立 SPI 分开记录。

RX/TX 共用资源按上行、停发、下行顺序切换；本结果不能称为业务与测控全并发。V2 上行和实验 ATM1 下行的格式不同，也不表示完整 NTN/CCSDS 协议符合性。

## 启发、身份与取消

`CommandSource` 是独立的固定工作点指令源适配器，普通业务 Console 和 RF 接收窗口的身份/写入限制保持不变。没有写入永久设备白名单。使用端口须与实物接线相符，COM号、模型字符串和短USB序号不能证明永久身份。

TX 开启只由板端保护进程处理，主机不能直接调用该适配器开启本振。保护进程按板端 uptime 计时，30秒后或收到取消请求后关闭 LO、设89dB衰减并退出本次 writer；迟到的主机开启请求不能在保护结束后重新启发。正常停止等待保护进程确认停止，再独立检查静音与DMA释放。错误回执不自动重复发射，其他任务忙时不接管。

控制阶段和下行阶段分别持有串口，转换时延续遥控板旧启动时间区间，重启后不能重新绑定并继续发回报。此 uptime 方法仍不是唯一 boot nonce 或设备认证。

## 复现入口

在仓库根目录执行，端口以当次只读识别与实物核对为准：

```powershell
python -m sw.ground_station.tc_roundtrip --source COM19 --adda COM10 --relay COM13 --probe --out D:\RelayTools\work\tc_probe_new
python -m sw.ground_station.tc_roundtrip --source COM19 --adda COM10 --relay COM13 --rx 900 --tx 1001 --seq 240 --wiring-confirmed --out D:\RelayTools\work\tc_run_new
```

输出目录必须不存在，序号必须与最近控制记录不同。`--probe` 只读、不发射；`--wiring-confirmed` 表示操作者已确认本页接线，不能仅为绕过检查而添加。工具不复位板卡、不用 UART_NETTEST 或本地 LO 指令替代真实上行；完成后保留真实指令设置的频率。

工具保存控制日志、请求波形、实际下行 IQ、解码报告和事务核对结果。下行 IQ 或报告可在现有“RF测控下行”窗口打开；该窗口显示实际 ADC_NORMAL 记录。本阶段的整笔事务由独立验证入口执行，尚未把指令生成与全部步骤合并成一个 GUI 按钮。

## 收尾与后续

本轮结束保留900/1000MHz、LDSDR mode2/89dB/增益0，两个Linux SDR均停发、DMA空闲；遥控板auto/network/ARM/pending关闭，DAC空闲。当前线缆保持测控上下行接法，业务输入端暂未接回LDSDR RX1。下一阶段可用现有接线接入整笔事务的GUI控制；恢复业务演示前需要停发再恢复第一根线。

原始IQ、全量控制日志、限时保护记录、独立收尾读回、测试日志与源码快照归档在本地 `D:\RelayTools\releases\telecontrol_roundtrip_20261028.zip`。包内逐文件SHA256及包摘要见结构化记录，原始二进制不提交Git。反向业务、两台电脑迁移、独立指令源、共用本振规划和六线全系统运行仍按[六线计划](six-link-system-plan.md)推进。
