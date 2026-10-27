# 真实中频输入联调

2026-10-28已完成发送板TX1A/JP1 → 遥控板ADC1/J5的真实100.5 MHz有线输入验证：单音、三组关闭转发的指令解码及四组ADC_NORMAL自动解调→UDP→LDSDR控制闭环均通过。结论限本次实物和工作点；绝对功率、全频段、误码率、长期连续运行、业务RF与GUI控制未验收。见 [真实输入闭环摘要](validation/2026-10-28-analog-loop.json)。

## 板卡与资料对应

2026-10-28按实物持有者确认的对应关系，核对了手册接口图、原理图以及发送端软件归档。以下页码均为PDF页序。第三方资料保留在本地，不随项目源码重复上传。

| 角色 | 资料目录及依据 | 已确认的资料内容 |
|---|---|---|
| 新发送板 | `7010_AD9363_SDR/XC7Z010_AD9363SDR用户手册.pdf`，第5、6页；`硬件资料/原理图.pdf`，第15页 | 手册标注AD9363，可用XC7Z010/020版本，双发双收；TX1A为JP1，接芯片TX1A_P/N；TX2A为JP3，接TX2A_P/N。当前实物JTAG为XC7Z010。 |
| 转发板 | `LDSDR（7010_rev3.1）/7.开发手册/LDSDR使用说明及开发手册.pdf`，第2、23页；`6.原理图/原理图.pdf`，第4页 | 标注XC7Z010CLG400-1、AD9363-BBCZ、512 MB DDR3；TX1接芯片TX1A，TX2接TX2A。原理图TX2匹配网络的中间网名TX1BN不能误读为芯片TX1B。 |
| 遥控板 | `Z7ADDALite资料/03使用教程手册/01Z7ADDALite硬件参考手册.pdf`，第3、8页；`02硬件资料/原理图/Z7ADDALite_SCH_RevB.pdf`，第10、11页 | ADC1/J5接AD9643 A通道，ADC2/J4接B通道，经过ADA4937-2前端；默认交流耦合，手册标注50 Ω输入。J6是DAC输出，当前接收链不使用。 |

新发送板手册第5页把靠网口的Type-C标为JTAG，功能为供电、JTAG及UART；另一Type-C为USB通信及供电，对应用户描述的DEBUG与USB2.0。DEBUG可配置、诊断系统，但不是USB虚拟网口。手册第15页起给出USB/IIO用法；包内另有只支持以太网的固件，不能把这种固件的USB限制套在所有版本上。LDSDR手册第2至3页也区分数据USB与FT4232调试口，两块板应分别识别。

发送板的软件包含`Vivado2021.1工程/PL_PS驱动/AD936X_PL.zip`、`AD936X_PS.zip`、Pluto SD固件及Linux源码地址。PS例程使用`ID_AD9361`和双收双发配置，手册也说明AD9363按AD9361方式配置；这些都不是实物芯片变为AD9361的证明，也未证明当前Linux由该裸机例程构建。资料足以继续适配现有Linux，不需要先下载或刷写另一份大固件。

## 频段、电平与接线条件

[ADI的AD9363数据手册](https://www.analog.com/media/en/technical-documentation/data-sheets/ad9363.pdf)规定工作频段325 MHz至3.8 GHz。LDSDR手册宣称固件扩展至70 MHz至6 GHz，新发送板手册也描述扩展使用；当前驱动允许设置100 MHz。因此100.5 MHz属于扩展频段，本轮已在当前实物和有线工作点验证，不作为厂商保证的工作点，也不把设备树中的AD9361名称当作频段验收。

发送板原理图的TX通路为芯片、18 pF/330 nH匹配网络、TC1-1-13M+变压器、SMA，未画出外接功放。[Mini-Circuits标注该变压器频段4.5至3000 MHz](https://www.minicircuits.com/pdfs/TC1-1-13M%2B.pdf)，包含100.5 MHz；这只排除了变压器标称频段不覆盖的问题，不证明整板匹配、输出功率或调制质量。

本轮实测接线为`发送板TX1A/JP1 → 遥控板ADC1/J5`，使用发送端可回读TX衰减控制幅度。手册照片中，发送板网口朝左上、SMA朝右时，TX1A是最靠网口一端的SMA；Z7ADDALite网口朝下、SMA朝上时，ADC1是最右侧SMA。实际连接以丝印为准。J5通路在原理图中交换了ADC A的差分极性，解调需继续保留双极性CRC判决。更换实物或连接时仍需重新核对端口和信号条件。

现有资料未给出新发送板在100.5 MHz的保证输出功率，也未给出Z7ADDALite SMA口的整板最大连续输入额定值。AD9643芯片的名义1.75 Vpp差分满量程不能直接当作SMA允许电压；板上的5 V ESD器件也不是5 V正常信号额定值。旧方案的AD936x RX上限与固定40 dB衰减建议针对另一方向，不能直接套用到当前ADDA输入。本轮已验证可回读TX衰减、通道选择和停止发射流程；单音相对幅度结果不替代绝对功率校准，短同轴线没有已知40 dB衰减。

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

2026-10-28通过DEBUG口识别出独立于原两块板的FTDI串口和JTAG。JTAG器件为XC7Z010；串口系统为Pluto Linux 5.15.0、Buildroot 2023.02.5、libiio 0.25。设备树型号字符串是`FISH Ball PlutoSDR Rev.A (Z7020/AD9361)`，与JTAG器件读数及手册芯片标注不一致。FPGA识别以JTAG为准，射频芯片在项目中按厂家AD9363资料处理；该字符串只记录固件声明，不据此改判为另一块板或要求替换现有固件。

只读发现`ad9361-phy`、`cf-ad9361-dds-core-lpc`和`cf-ad9361-lpc`；TX扫描元素有4路，顺序索引0..3，格式均为`le:s16/16>>0`。读取时扫描通道和TX buffer均未使能。驱动报告TX LO可设范围46,875,001..6,000,000,000 Hz，采样率范围2,083,333..61,440,000 Hz，包含约定的100 MHz LO和2.5 MSPS；这只说明软件允许范围，不证明实物在100.5 MHz的输出性能。

此前只读识别时，TX LO为2.4 GHz、采样率30.72 MSPS、RF带宽18 MHz、两路TX增益均为−10 dB，8路DDS scale均为0。TX LO powerdown读回0；这些寄存器状态不替代SMA功率测量。该次只读检查未更改这些值。USB2.0尚未在电脑上建立可用USB网络连接；DEBUG串口已经能读取系统，接收软件和发射脚本不能据此自动选择另一块板或重写固件。

## 发射端控制预检

2026-10-28已通过DEBUG串口完成新发送板的实际配置与回读：TX LO为100 MHz，采样率2.5 MSPS，RF带宽3 MHz，TX端口A。所有DDS幅度为0、两路衰减89 dB时，验证本振关闭/开启/关闭回读；在本振关闭时验证TX1衰减89/60/89 dB。此项只确认控制接口，没有测量RF输出功率。

通过串口向发送板RAM传入单音及三组指令，每份16000字节，均与本机SHA256一致。保持本振关闭，`iio_writedev -b 4000 -c`成功循环发送，仅启用流设备的`voltage0/1`，通道2/3关闭；SIGINT停止后退出码0、buffer从1回到0。无需以USB虚拟网口作为小波形联调的先决条件。驱动在buffer停止后可能切回DDS，停止流程必须同时清零全部DDS并关闭TX本振。

遥控板正常采集131072点，UART来源为ADC_NORMAL，按对应DDR地址经JTAG导出：AC RMS约1.395码，范围-17至-5，无削顶、无非法符号扩展、未检出有效帧。这是发射端控制预检时、发送端关闭的历史基线，不计作100.5 MHz接通证据。

同时发现LDSDR当时运行的固件不识别`rfread`，已按精确JTAG接口临时恢复此前验证的DDR固件；SPI独立读回RX 900 MHz、TX 1000 MHz。没有改写SD或Flash。最终发送板本振关闭、DDS全零、DMA关闭、两路衰减89 dB；遥控板network/ARM/auto关闭；LDSDR保持MUTE、衰减89 dB。

详细结果及本地证据哈希见[发射端控制预检记录](validation/2026-10-28-sender-control.json)。上述记录仅覆盖当时的DMA与寄存器预检；随后完成的SMA输入及控制闭环见下节。

## 本轮实物验证结果

| 顺序 | 操作与判据 |
|---|---|
| 1.确认接口 | 已实测发送板TX1A/JP1 → 遥控板ADC1/J5，ADDA采集来源为ADC_NORMAL。 |
| 2.单音验证 | TX衰减60 dB及40 dB时均测得采样别名6.749868 MHz；FFT幅度增加20.015 dB。此为相对幅度验证，未校准SMA绝对功率。 |
| 3.关闭转发解调 | network/ARM/auto关闭，真实900/1000/80、901/1000/81、901/1001/82指令均由主机及PS正确解码、CRC通过，板端约277 ms，未发UDP。 |
| 4.自动控制 | 上述三组指令及900/1000/83恢复均经ADC_NORMAL自动解调、UDP、匹配ACK及LDSDR独立SPI频率读回通过；applied从4增至8，pending=0、failures=0。每例总发送1次；重复帧各观察2秒无新UDP，关闭信号后2秒无误触发。 |

旧交接脚本的固定seq、双边单音、单帧零填充成形和字节/样点数混用问题已在离线生成及计数约定中处理。本轮使用当前Pluto系统与DEBUG串口完成波形传入及发送，未改写SD或Flash启动介质。结束时发送板LO关闭、DDS全零、DMA关闭、两路TX衰减89 dB；ADDA network/ARM/auto关闭；LDSDR保持静音、衰减89 dB及900/1000 MHz基线。
