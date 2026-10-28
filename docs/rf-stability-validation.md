# 有线业务序列与稳定性验证

2026-10-28，沿用已验证的LDSDR RX I/Q修正版，在第一路有线业务链完成保持输出、重复UDP改频及软件拒绝/恢复检查。原始结果为completed=true，cleanup_errors为空；数值和证据包校验索引见[验证摘要](validation/2026-10-28-rf-stability.json)。本轮不改GUI、遥控V2、板端固件或启动介质。

## 连接与测试条件

连接为`7010_AD9363_SDR TX1A → LDSDR RX1`、`LDSDR TX1 → 7010_AD9363_SDR RX1A`，不接天线或ADDA SMA。发送和测量仍由同一块板承担，本轮不是独立接收板验收，也没有真实ADC遥控输入。

源TX LO为900 MHz，复基带偏移+500 kHz；源及LDSDR TX衰减均50 dB，LDSDR RX增益30 dB、RX LO为900 MHz。测量端RX LO实际读回1000749998 Hz，采样率2.5 MSPS、手动增益30 dB、带宽3 MHz。LDSDR TX LO在1000/1001 MHz交替，对应接收频偏约−250/+750 kHz。数字幅度与衰减值不替代RF功率校准。

发送内容为8个循环实验文本`SEQ000:ABCD`至`SEQ007:ABCD`，每帧11字节payload，采用旧实验AAAA/len/payload/CRC16格式、100 ksym/s BPSK及SRRC成形，非CCSDS遥控V2。每帧128 bit；离线序列工具8项测试通过。

## 输出保持与快照结果

同一TX writer保持输出311.136秒，期间没有重启，取得11次离散快照。全轮还包含8次交替改频和拒绝/恢复采样，共25个窗口；每窗8192组I/Q、32768字节、3.2768 ms，全部采样窗口合计81.92 ms，不能把输出保持时间当作连续接收时长。

| 窗口组 | 窗口数 | 完整CRC有效帧 | 条件比较bit |
|---|---:|---:|---:|
| 保持输出 | 11 | 12 | 3517 |
| 交替改频 | 8 | 11 | 2559 |
| 非法请求后、网络关闭/恢复、源恢复 | 4 | 6 | 1280 |
| 基线、源关闭负例 | 2 | 0 | 0 |
| 合计 | 25 | 29 | 7356 |

23个正例窗口均恢复预期内容，2个负例没有有效帧。29个完整帧共3712 bit，其中2552个payload bit与预期一致；没有非预期payload，窗口内6个序列转移均一致。CRC选定同步并以已知序列锚定后的7356个条件比较bit无差异。该比较依赖已捕获窗口及成功同步，不能推导整体BER=0、跨窗口无漏帧或24小时稳定性。

所有窗口ADC削顶分量数为0，每个窗口采集前后LDSDR削顶计数增量为0；311.136秒保持输出阶段累计削顶增量亦0。离散采样不覆盖所有瞬时波形。

## UDP改频与恢复边界

ADDA通过UART_NETTEST发送UDP控制，8次1000/1001 MHz交替设置后均恢复有效业务帧；连同初始、恢复及收尾事务，全轮11笔成功事务使applied从16增至27，最终pending=0、failures=0。

- seq=256请求在CLI参数检查处返回rc=-1，未发送畸形UDP，不作为网络报文解析负例。
- `network off`后请求返回NETWORK_NOT_READY、rc=-12；软件disable期间业务序列仍可接收，重新启用网络后改频与内容恢复成功。没有物理拔线测试。
- 关闭源后未恢复有效帧，重新启动源后内容恢复。

11笔成功事务从PC串口发指令到收到ACK通知为23.14～34.96 ms，该时间包含串口和主机流程，不是纯网络往返或PLL锁定时延。8次改频从请求到正确快照完成的流程上界约4.27～4.33秒，包含主机诊断、调度与采集命令耗时，不作为射频建立时间。

## 离线复核

在仓库根目录执行下列命令可生成序列或分析一份已保存的I/Q文件；工具不操作串口、网口或发射器。生成目录与结果文件必须不存在。

```powershell
python -B sw/tools/rf_sequence_check.py generate --out sequence
python -B sw/tools/rf_sequence_check.py analyze capture.bin sequence/manifest.json --offset -250000 --out decoded.json
python -B -m unittest discover -s sw/tools -p test_rf_sequence_check.py -v
```

`capture.bin`应为2.5 MSPS、I/Q交错的小端有符号16位样点。1001 MHz转发设置对应`--offset 750000`。检查JSON中的`passed`、`acquisition_failed`及条件比较字段；进程正常结束本身不等于收到正确内容。

## 收尾与后续

结束时源端LO、DMA关闭、DDS全零、两路TX衰减89 dB；LDSDR mode=2、两路TX衰减89 dB、RX增益0、DDC/DUC=0，SPI读回RX900/TX1000 MHz；ADDA auto/ARM/network关闭、pending=0。清理无错误，启动介质未改写。

本次结果限当前实物、第一路有线链及离散窗口。额外接收板外观/丝印与发送板相同、DEBUG已接电脑，其型号和功能仍在只读识别，不能据此外观假定接收或发射能力。下一步先用现有两根SMA验证独立接收端业务链；真实ADC遥控与业务同时运行还需独立100.5 MHz指令源及第三根同轴。长期连续接收、整体误码率、全频段及持久化启动仍待验收，见[同时联动计划](system-integration-plan.md)。
