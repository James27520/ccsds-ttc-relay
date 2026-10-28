# 有线调制文本业务转发验证

2026-10-28，沿已接好的两根同轴线完成三种 BPSK 文本的第一路转发与电脑 1 离线解码。
最终汇总及证据校验和见[验证摘要](validation/2026-10-28-rf-payload.json)。
本轮不改 GUI、遥控 V2 或板端固件，沿用已通过单音验收的 LDSDR RX I/Q 修正版。

## 实验帧与波形

沿用队友 `gen_adda_coe.py` 的旧实验文本帧：

```text
AA AA | UTF-8 字节长度（1 字节，1..200） | UTF-8 payload | CRC16（2 字节，大端）
```

CRC 为 CRC-16/CCITT-FALSE，仅覆盖 payload，poly=0x1021、init=0xFFFF、不反射、xorout=0。
**这不是 CCSDS 遥控帧，也不是遥控 V2 的 8 字节 body / 160 bit 指令。**
`hello world` 的已知帧为 `aaaa0b68656c6c6f20776f726c64efeb`；另以
`CRC("123456789")=0x29B1` 独立核对 CRC 约定，避免只依赖编码、解码共享实现的自洽。

发端采用 100 ksym/s、2.5 MSPS、每符号 25 点；SRRC β=0.35、跨度 8 符号，
复基带偏移 +500 kHz，数字复幅峰值归一为 0.1。三帧连续成形后保留中间帧，
保证重复块的滤波边界及载波周期连续。三个文本均为 11 字节，每帧 128 bit、
3200 个复样点、12800 字节、1.28 ms。数字幅度不表示 RF 输出功率。

## 连接与测量

连接保持为 `7010_AD9363_SDR TX1A → LDSDR RX1`、`LDSDR TX1 → 7010_AD9363_SDR RX1A`，
不接天线或遥控板 ADC。源端及转发端 TX 衰减均为 50 dB；短同轴线不作为已知衰减器。
源 TX LO=900 MHz，实际信号中心名义 900.5 MHz；LDSDR RX LO=900 MHz，
mode=1、DDC/DUC=0、数字增益 0x800、DC blocker 关闭、RX 增益 30 dB。

测量端 RX LO 实际读回 1000749998 Hz，Fs=2.5 MSPS、手动增益 30 dB、带宽 3 MHz。
LDSDR TX LO=1000 MHz 时预期接收偏移约 −250 kHz；改为 1001 MHz 时约 +750 kHz。
每次有界采集 8192 组 12 位符号扩展 I/Q（小端 int16 存储），32768 字节，窗口约 3.2768 ms。
板端文件与电脑回传文件核对 SHA-256 后，才在电脑 1 离线分析；不是在板上运行文本解码器。

解码使用[文本链工具](../sw/tools/rf_text_link.py)：按已知频率规划预混频、平方律估计残余频偏，
再做 SRRC 匹配滤波、采样相位搜索、双极性及任意 bit 边界搜索，按长度和 CRC 接受完整帧。
恢复过程不接收期望文本；取得 CRC 有效帧后，验收脚本才与发送 payload 逐字节比对。

## 已完成的文本及负例

`capture_full_r1` 的 9 个正例窗口、4 个负例窗口均通过，清理无错误：

| 内容 / 条件 | 窗口数 | CRC 有效完整帧 | 结果 |
|---|---:|---:|---|
| `hello world`，TX LO=1000 MHz | 3 | 4 | payload 全部一致 |
| `relay test1`，TX LO=1000 MHz | 3 | 4 | payload 全部一致 |
| `relay test2`，TX LO=1001 MHz | 3 | 6 | payload 全部一致 |
| 两端低输出基线 | 1 | 0 | 未误报文本 |
| LDSDR mode=2 | 1 | 0 | 未误报文本 |
| 源端关闭 | 1 | 0 | 未误报文本 |
| payload 不变、仅翻转 CRC 一位 | 1 | 0 | 1 个完整候选被 CRC 拒绝 |

共接受 14 个完整帧、1232 个 payload bit；这些**已接受帧**与发送文本相比，payload bit 差异为 0。
各正例频偏估计符合 −250 / +750 kHz 的分支；所有窗口均无接收削顶，采样前后 LDSDR 削顶计数增量为 0。
负例即使输出载波估计，也不因该估计认定收到了有效业务帧。

这只证明所列短窗口中的内容恢复与负例拒绝，**不宣称 BER=0、连续链路 FER 或无间断收发**。
边缘截断帧及匹配滤波过渡区不属于完整可评估帧；未接受的数据不能从错误统计中消失后再据此推算 BER。
采集之间存在空档；第二路、长时间运行、业务与遥控同时运行尚未验收。ADC 参考 dBFS 不是校准 dBm。

## UDP 控制与实际内容的补充验证

文本首轮直接通过 LDSDR CLI 设置本振。已完成的 `capture_udp` 使用原 ADDA
`UART_NETTEST → UDP → LDSDR ACK` 设置 900/1000、900/1001 MHz，在两组状态各采集两次
相同的 `hello world`。4 个正例窗口、1 个低输出基线窗口均通过；共接受 5 个完整帧、
440 个 payload bit，已接受内容与发送文本一致，基线未接受帧。

两组命令日志分别为 `air_seq=100`、`101`，均有精确字段匹配的成功 ACK；独立 SPI
读回 TX 分别为 1000000000、1000999998 Hz。两次采样的载波估计均值分别为
−250067.24、+749932.54 Hz，相差 +999999.78 Hz，且两组均恢复同一文本。
因此本项把 UDP 控制回执、独立 RF 寄存器读回、实际频点变化和恢复内容关联起来。
该控制来源是 **UART_NETTEST，不是遥控板 ADC 自动解调**；日志中的 `air_seq`
是该命令字段，不据此推断 UDP 报文序号。

## 收尾与复查

已完成的首轮结束时，源端 TX LO、TX/RX buffer 关闭，八路 DDS 幅度为 0，两路 TX 衰减为 89 dB；
LDSDR mode=2、两路 TX 衰减 89 dB、RX 增益 0、DDC/DUC=0，恢复 900/1000 MHz 并经独立 SPI 检查。
UDP 补测以 `air_seq=102` 再次成功确认恢复 900/1000 MHz、RX 增益 0、TX 衰减 89 dB；
ADDA applied 从 13 增至 16，最终 auto/network/armed/pending 均为 0、failures=0。
源端及 LDSDR 静音读回与首轮一致，两轮 `cleanup_errors` 均为空。
采集与解码结果分别保存；离线判定不能替代板端清理确认。

可离线复查：`python -B -m unittest discover -s sw/tools -p test_rf_text_link.py -v`。
当前 9 项测试覆盖独立已知值、周期成形、频偏 / 相位 / 极性 / 截断起点、+750 kHz 分支、
噪声 / 单音 / 静默、坏 CRC / 长度、非法 ADC 格式和 UTF-8；不访问硬件。

单独生成波形与复查保存的采样：

```powershell
python sw/tools/rf_text_link.py generate --text "hello world" --out '<新的波形目录>'
python sw/tools/rf_text_link.py decode '<采样文件.bin>' --offset -250000 --out '<新的结果.json>'
```

1001 MHz输出组将`--offset`改为`750000`。工具只读写本地文件，不配置或启动板卡。
本次100 ksym/s是已验证的工作点，最终业务速率和持续接收方案仍需另行验收。
