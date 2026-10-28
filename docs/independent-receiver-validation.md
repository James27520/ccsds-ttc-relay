# 独立接收板有线业务验证

2026-10-28，发送板TX1A → LDSDR RX1、LDSDR TX1 → 新接收板RX1A的两线链路通过8个窗口测试。RX1A丝印由用户确认，所有测试I/Q采集均来自新增COM18接收板，不再使用发送板RX。ADDA仅通过网口控制，没有真实ADC指令输入。数值、设备身份及原始证据包校验和见[验证摘要](validation/2026-10-28-independent-receiver.json)。

## 接收板身份与复用范围

接收板运行Linux 5.15、固件`v0.38-1-g6f8e-dirty`。设备树字符串为`Analog Devices PlutoSDR Rev.C (Z7010/AD9363)`，IIO为`Analog Devices PlutoSDR Rev.C (Z7010-AD9361)`；这些是软件声明，不能据此确认射频芯片或FPGA封装型号，也不证明TX或100.5 MHz性能。

USB换线后才成功枚举，未取得稳定factory serial。控制目标以Windows完整实例路径和IIO `hw_serial=104473023196000bf5ff1a00aae12c3ca8`双重绑定，具体实例路径记录于摘要；换USB位置后须重新识别，不能只凭COM号选择板卡。接SMA前已关闭TX，测试期间TX持续关闭、DDS全零、两路TX衰减89 dB。

本轮核对GitHub当时的main和开放PR（0个），已有`mode_b_link.py`、`board_loopback_test.py`包含IIO采样。实际复用已验证bench runner、原I/Q采样格式及`rf_text_link.py`、`rf_sequence_check.py`，只将采样传输目标切到独立绑定的接收端。交接目录的`rx_board.py`本地存在但不在当时main，旧peak-FFT文本解调及SSH流程未直接执行；未新增解码器、GUI或板端固件。

原发送板在准备阶段返回登录，读到uptime约613秒且此前RAM波形目录不存在，原因未知。重新登录后先确认关闭状态，再恢复配置和上传波形；这项现象不计为故障恢复验收。

## 连接、改频与内容结果

业务源名义900.5 MHz，LDSDR RX LO为900 MHz、TX LO为1000/1001 MHz，源及转发TX衰减50 dB、LDSDR RX增益30 dB。接收端RX LO实际读回1000749998 Hz、2.5 MSPS、3 MHz带宽、手动增益30 dB。每窗8192组I/Q、3.2768 ms，电脑离线恢复100 ksym/s实验BPSK文本序列`SEQ000:ABCD`至`SEQ007:ABCD`，非遥控V2帧。

| 窗口 | 完整CRC有效帧 | 条件比较bit | 结果 |
|---|---:|---:|---|
| 基线 | 0 | 0 | 无有效帧 |
| UDP设置1000 MHz，两窗 | 3 | 640 | 内容一致 |
| 转发静音 | 0 | 0 | 无有效帧 |
| UDP设置1001 MHz，两窗 | 3 | 639 | 内容一致 |
| 源关闭 | 0 | 0 | 无有效帧 |
| 源恢复 | 2 | 320 | 内容一致 |
| 合计 | 8 | 1599 | 5正例、3负例通过 |

五个正例无捕获失败，1599个CRC选定同步与已知序列锚定后的条件比较bit无差异。全部窗口ADC削顶分量0，逐窗LDSDR削顶增量0。该结果不推导整体BER、连续帧交付率或跨窗口无漏帧。

ADDA以UART_NETTEST发送seq140设置900/1000 MHz、seq141设置900/1001 MHz，收尾seq142恢复900/1000 MHz；三笔均获匹配ACK及独立SPI读回，applied从27增至30。测得两个频点载波均值由−249894.025 Hz变为+750103.210 Hz，位移999997.235 Hz；1001 MHz改频未使用LDSDR本地lo命令。接收端LO保持不变，UDP、SPI和独立RF内容关联通过。

## 收尾与下一步

发送端及新接收端TX LO关闭、buffers清零、DDS全零、两路TX衰减89 dB；LDSDR mode=2、两路TX衰减89 dB、RX增益0、RX900/TX1000 MHz；ADDA auto/network/ARM关闭、pending=0、failures=0。清理无错误，GUI、遥控V2、固件及启动介质未改，本轮不需要新上板固件。

现有两根线可先静音停发、分段换线复核真实ADC遥控与修正版LDSDR。真实遥控与业务同时运行仍需确认独立100.5 MHz指令源能力及第三根同轴；新接收板TX未测试，不能先假定它能兼任指令源。绝对功率、全频段、第二路RF、整体误码率及长期连续运行未验收，见[同时联动计划](system-integration-plan.md)。
