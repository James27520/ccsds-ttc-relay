# 真实中频输入联调

当前已完成内部ADC测试、合成波形解调及UART_NETTEST双板UDP控制。下一步验证发送端的真实100.5 MHz指令，经Z7ADDALite采样和C解调后控制LDSDR。本次准备没有启动发射、改变板端RF参数或写启动介质。

## 已准备的离线工具

`sw/tools/telecontrol_waveform.py`复用现有编码器和SRRC函数，生成V2的8字节body、160 bit帧。符号率100 ksym/s，采样率2.5 MSPS，复基带偏移+500 kHz；每块4000复样点、16000字节、1.6 ms。三帧连续成形后取中间帧，避免循环拼接时的零填充边界；单音采用复指数，只生成正偏移分量。

```powershell
python -B sw/tools/telecontrol_waveform.py --mode tone --out '<新单音目录>'
python -B sw/tools/telecontrol_waveform.py --mode cmd --rx 900 --tx 1000 --seq 80 --out '<新指令目录>'
python -B -m unittest discover -s sw/tools -p test_telecontrol_waveform.py -v
```

生成文件为signed int16 LE，顺序I0/Q0/I1/Q1。manifest记录body、CADU、样点数、字节数和SHA256。默认amplitude=0.1是数字复幅峰值，不代表SMA功率或安全输入电平。文件只是规范化参考格式，必须先核实实板IIO扫描通道及硬件映射才能使用；工具不包含SSH、IIO写操作或发射功能。频率与序号越界直接拒绝，输出目录必须是新目录。

`board/z7addalite/tools/analyze_adc_capture.py`离线读取单通道int16 LE快照，通过既有C接收器做平方律载波恢复、解调及CRC校验，同时报告幅度、直流、极值和格式异常。文件本身不能建立ADC_NORMAL来源资格，解出的命令不会提交到硬件。

```powershell
# 先按board/z7addalite/software/demod的入口构建本机C接收库。
python -B board/z7addalite/tools/analyze_adc_capture.py --samples '<快照.bin>' --library '<adda_receiver.dll或对应主机库>' --out '<新结果.json>'
python -B sw/tools/test_telecontrol_receiver.py --library '<同一主机库>' --out '<新测试目录>'
```

离线验证包括6项生成器单元测试，以及16项C接收器兼容测试：12组有效指令覆盖金标准、联调频率、不同捕获起点和极性；单音、零输入、噪声及非法14位符号扩展均拒绝。IQ经理想上变频和采样模型折叠到6.75 MHz；该模型不验证实际DAC/ADC前端、模拟电平或射频通道。

## 新发送板只读识别

2026-10-28通过DEBUG口识别出独立于原两块板的FTDI串口和JTAG。JTAG器件为XC7Z010；串口系统为Pluto Linux 5.15.0、Buildroot 2023.02.5、libiio 0.25。设备树型号字符串是`FISH Ball PlutoSDR Rev.A (Z7020/AD9361)`，与JTAG器件读数不一致。该字符串只记录当前固件声明，不能代替实际FPGA、射频芯片及板卡版本确认。

只读发现`ad9361-phy`、`cf-ad9361-dds-core-lpc`和`cf-ad9361-lpc`；TX扫描元素有4路，顺序索引0..3，格式均为`le:s16/16>>0`。读取时扫描通道和TX buffer均未使能。驱动报告TX LO可设范围46,875,001..6,000,000,000 Hz，采样率范围2,083,333..61,440,000 Hz，包含约定的100 MHz LO和2.5 MSPS；这只说明软件允许范围，不证明实物在100.5 MHz的输出性能。

当前读回TX LO为2.4 GHz、采样率30.72 MSPS、RF带宽18 MHz、两路TX增益均为−10 dB，8路DDS scale均为0。TX LO powerdown读回0；这些寄存器状态不替代SMA功率测量。本次未更改这些值。USB2.0尚未在电脑上建立可用USB网络连接；DEBUG串口已经能读取系统，接收软件和发射脚本不能据此自动选择另一块板或重写固件。

## 实物验收顺序

| 顺序 | 操作与判据 |
|---|---|
| 1.确认接口 | 核对新板型号、射频芯片、TX端口、两组I/Q与物理SMA的对应关系，以及Z7ADDALite输入口和电平限制。保留原两板网线和DEBUG连接。 |
| 2.确认信号条件 | 按实物能力确定低幅单音、TX衰减和外部衰减，保证通带覆盖偏移后的波形；不能沿用旧脚本的500 kHz RF带宽或凭数字amplitude推算电平。确认之后再接SMA。 |
| 3.仅采集解调 | 遥控板network/ARM/auto保持关闭。先观察正常ADC快照，再发送不同seq的V2指令，要求字段与CRC正确；内部训练码和合成数据不能算真实接收。 |
| 4.启用控制 | 真实输入解调通过后，再启用受控转发，逐笔检查LDSDR ACK与独立PLL回读；控制验证可保持LDSDR静音。 |

旧交接脚本的固定seq、双边单音、单帧零填充成形和字节/样点数混用问题已在离线生成及计数约定中处理。真实IIO写入适配仍需确认当前板的通道映射、实际滤波带宽、输出电平及USB或以太网传输路径；不能将离线通过写成已完成真实发送或接收。
