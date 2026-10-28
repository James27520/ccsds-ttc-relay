# 验证记录与未完成项

记录日期：2026-10-28。当前对象为 Z7ADDALite 遥控板（`xc7z020clg484-2`，AD9643）；PL 采集、PS C 解调及 UDP 控制路线的源码、约束、GUI、测试与重建入口已归档到 [board/z7addalite](../board/z7addalite/README.md)。需要加载固件的步骤采用临时JTAG加载；发送板沿用现有Pluto Linux，波形放在RAM。未改写SD或Flash启动介质。

最新业务序列与稳定性见 [稳定性验证摘要](validation/2026-10-28-rf-stability.json)；GUI实板控制见 [GUI实板控制摘要](validation/2026-10-28-gui-loop.json)；真实输入闭环见 [真实输入闭环摘要](validation/2026-10-28-analog-loop.json)；UART_NETTEST双板UDP验证见 [双板UDP验证摘要](validation/2026-10-27-dual-udp.json)；网口验证及修复回归见 [网络验证摘要](validation/2026-10-27-network.json)；r4c时序、全通道快照和历史串口证据见 [r4c完整M2验证摘要](validation/2026-10-27-m2.json)。[早期摘要](validation/2026-10-27.json) 保留为当天前期快照；原40字节RTL环回另见 [历史验证记录](legacy-validation.md)。原始采样二进制和完整厂商构建输出不随源码包分发。

## 已完成

### M1与最终PL实现

M1内部PN9诊断已验证125 MSPS DDR数字接口、SPI配置读回、A通道PN9和B通道checker。最终完整M2使用冻结r4c输入，布局布线结果为：

| 项目 | r4c结果 |
|---|---|
| WNS / WHS / WPWS | +0.483 / +0.022 / +0.264 ns |
| TNS / THS / TPWS | 全部0 |
| DRC | 0 errors |
| ADC输入路径 | 56条完整计时路径 |
| 动态mailbox端点 | 198个，全部具有有效20 ns datapath约束；最差余量18.128 ns |

四组mailbox采用payload保持到ack、两级数据寄存器和三级请求toggle后发布；24个常量端点仅在直接GND/VCC驱动时认可。未使用笼统异步clock-group例外或mailbox-data false_path。

CDC路径复核：CDC-10的启动延时计数译码仅驱动向量复位置位链；CDC-12的全局/启动/PS复位组合采用8级clk_vec释放链，避免源时钟停止时释放；CDC-11是相等配置位合并到同一held_data位，目的端仍属于保持到ack的bundle并全部受20 ns约束。其余已记录的CDC-6/15涉及命令保持总线和厂商ILA内部bundle/clock-enable。stream_valid已在clk_vec寄存后再同步；物理时钟heartbeat跨PS/capture复位继续运行，真实停钟故障仍保持。快照RAM复位后内容无效，新成功采集必须覆盖全部65536字后才发布DONE。

### M2真实ADC→RAM→PS快照

完整r4c位流、匹配XSA/ps7_init/BSP和最终采集ELF已临时上板。A通道PN9与B通道checker在k=0..3全部通过；每个快照为131072个符号扩展int16样点。板端检查之后，使用JTAG导出PS DDR缓存，再由独立Python实现检查，结果均PASS；A通道PN9无递推错误、非法码字或零状态，B通道固定k的checker值正确。

两次完整临时下载后，共导出并独立检查13份快照、1703936个样点：7份A通道PN9、4份B通道checker和2份normal格式检查。立即取消采集后返回CANCEL且快照无效，随后重新采集通过；第二次下载后的PN9复测通过。此处不把另外两次GUI采集计入独立DDR导出统计。

normal A/B快照的14位符号扩展格式检查通过，normal后重新切回training A的PN9检查通过。该次normal测试未接外部信号，只证明当次格式与模式切换，不能作为模拟指令接收证据。ADC_TEST快照decode没有有效帧，没有发出RF_SET。

### M3协议、C解调与PS控制

| 验证层 | 结果与范围 |
|---|---|
| 数字帧/控制协议 | 2906项主机断言通过；26字节RF_SET兼容旧解析器，ACK/重试/序号检查通过 |
| 波形算法 | 45/45合成波形通过，覆盖频偏、极性、时钟偏差及噪声/单音/坏CRC负例 |
| PS离线状态测试 | core88、capture/controller11193断言通过；pattern57项历史fixture回放通过；A9 hard-float目标文件编译通过 |
| 历史完整M2固件 | ELF SHA256 `00d14352729bb2748f7a7604547416474b9022082a520b8b6e35dcf49ac64c30` 下，三组金标准与131072点合成波形通过，波形耗时278 ms、no_UDP=1 |
| 网络修复回归 | 正式ELF的selftest及131072点合成波形（277 ms、no_UDP=1）通过；正式ELF另检一份131072点A通道k=0内部PN9，板端及独立DDR检查错误均为0 |

合成波形耗时是单块A9执行时间，不能据此宣称31.25 MSPS连续无间断解调。SYNTHETIC和ADC_TEST来源不获得自动转发资格；有效ADC_NORMAL仍需ARM、网络ready和匹配成功ACK才计为远端已确认。

### M4网口验证、失败恢复与上位机

PHY/初始化/MDIO的mock负例通过，包括18处注入MDIO失败、有界reset/无链路等待、64次PHY和64次DMA初始化失败的资源回收，以及后续恢复。历史v6三次和完整M2固件一次`network on`失败后，串口status和selftest仍正常；这些记录保留，但原“无PHY响应”推断错误。

JTAG直读MDIO地址0和1均得到`001C:C915`。RTL8211E原厂datasheet 7.7 Table 13定义地址0为广播地址，各PHY均响应；本板地址脚实际为1。当前驱动严格使用地址1及ID `001C:C915`，允许匹配该ID的地址0广播响应；其他地址、错误ID及MDIO错误仍拒绝。

网络修复正式ELF（SHA256 `aa7eb6d368f8ab256749d53a40ad24d1b50ddccac0873e13c6e705a97ce8b4a2`）已临时上板，使用相同r4c BIT（SHA256 `10ac68b0ccfcfb5dbe50c80d8ed185e840ff6be3e67a331bd3d50b712a97057b`）和ps7_init（SHA256 `3998a8f3c4e16e76286e8fcb2e6b73628e13c7f89f6efc51fd2319b52fb8b205`）。`network on`成功，自动协商1000 Mbps，status显示network=1；PC `169.254.219.130` → ADDA `169.254.9.11` 连续10次ping全部成功，延迟<1～2 ms。ping中显示0 ms的结果表示延迟小于1 ms。

真实双板UDP已通过，来源为`UART_NETTEST`。PC仅经COM10向ADDA发送`nettest`，ADDA `169.254.9.11:5006` 经板间网线向LDSDR `169.254.9.10:5005` 发送26字节RF_SET；COM13的`rfread`提供独立SPI读回。ADDA使用上述正式ELF；LDSDR使用原已验证ELF临时DDR热加载，未写Flash或SD。

| 事务 | 独立SPI读回RX / TX（Hz） | 结果 |
|---|---|---|
| 原值900/1000 MHz | 900000000 / 1000000000 | 匹配ACK成功 |
| 仅RX改为901 MHz | 900999998 / 1000000000 | 匹配ACK成功 |
| 仅TX改为1001 MHz | 900999998 / 1000999998 | 匹配ACK成功 |
| network off后请求900/1000 MHz | 保持900999998 / 1000999998 | NETWORK_NOT_READY，rc=-12，无发送 |
| network on后恢复900/1000 MHz | 900000000 / 1000000000 | 匹配ACK成功 |

最终applied=4、pending=0、failures=0；`retries=1`表示该事务总发送次数为1。ADDA的network/armed/auto均关闭，LDSDR保持mode=2静音、txatt=89。此次未打开GUI，未接SMA或真实ADC指令输入；该次结果仅验证UART_NETTEST控制路径；2026-10-28真实有线指令控制结果另见下节，业务RF仍待验收。

串口GUI已在最终r4c固件上实际完成status、selftest、waveformtest、normal采集、空输入decode及training采集。normal输入未解出有效帧，切回training后PN9检查通过；GUI显示快照就绪、来源ADC_TEST、网络/ARM/自动模式关闭，未发送RF_SET。该阶段10项fake串口测试覆盖输入校验、连接不自动写命令及来源/状态分离；本轮扩展至15项，见下节。

### 2026-10-28：真实输入联调准备

新增离线V2波形生成器和快照分析工具，复用已有编码/SRRC和C接收器，未修改已上板固件。6项生成器单元测试通过；量化IQ经理想上变频/采样模型送入原C接收器，12组指令正确恢复，单音、零输入、噪声和非法样点格式4组负例通过。结果属于软件兼容验证，不是实板模拟接收。

新发送板通过DEBUG读到独立串口/JTAG和Pluto Linux/IIO接口。JTAG为XC7Z010，固件型号字符串含Z7020/AD9361；后续已按持有者确认的资料包核对板型，按厂家AD9363资料处理，未把固件字符串作为芯片型号证明。最初只读阶段没有下载固件、设置LO、上传波形或启动发射；后续控制预检与真实输入结果分段记录。接口依据见 [中频输入联调](signal-input-bringup.md)，准备阶段证据见 [准备验证记录](validation/2026-10-28-signal-prep.json)。

### 2026-10-28：真实SMA输入与自动控制闭环

实测接线为发送板TX1A/JP1 → ADDA ADC1/J5。100 MHz LO加500 kHz复基带偏移形成100.5 MHz有线输入；TX衰减60 dB、40 dB两次单音均测得6.749868 MHz采样别名，FFT幅度增加20.015 dB。该结果验证当前通路与相对幅度变化，不替代SMA绝对功率校准。

先保持network/ARM/auto关闭，采集三组真实指令900/1000/80、901/1000/81、901/1001/82（RX MHz / TX MHz / seq）；ADC_NORMAL快照由主机和PS正确解码，字段及CRC均通过，板端约277 ms，没有发送UDP。

随后启用受控自动解调转发，真实ADC_NORMAL指令经C解调、26字节UDP RF_SET及匹配ACK控制LDSDR，独立SPI读回如下：

| RX / TX（MHz） | seq | SPI读回RX / TX（Hz） | applied |
|---|---|---|---|
| 900 / 1000 | 80 | 900000000 / 1000000000 | 4 → 5 |
| 901 / 1000 | 81 | 900999998 / 1000000000 | 5 → 6 |
| 901 / 1001 | 82 | 900999998 / 1000999998 | 6 → 7 |
| 900 / 1000（恢复） | 83 | 900000000 / 1000000000 | 7 → 8 |

四例均通过，pending=0、failures=0；各例retries=1表示总发送1次。每例重复帧继续观察2秒，没有新UDP或新增applied；最后关闭信号再观察2秒，无误触发。此为短时去重与无信号检查，不作为误码率或长期连续运行结论。

结束时发送板LO关闭、DDS全零、DMA关闭、两路TX衰减89 dB；ADDA network/ARM/auto关闭；LDSDR静音、TX衰减89 dB，SPI恢复900000000/1000000000 Hz。未改写SD或Flash启动介质。该次结论限本次实物和当前有线100.5 MHz工作点，未验收绝对功率、全频段、误码率、长期连续运行、业务RF或GUI控制；后续GUI验证见下节。原始日志、快照、波形及本机复测脚本已归档为`analog_loop_20261028.zip`，保存在电脑1的`D:/RelayTools/releases`，文件大小和SHA256见[真实输入闭环摘要](validation/2026-10-28-analog-loop.json)。

### 2026-10-28：GUI实板自动控制与停止验证

GUI新增持久显示`last_decoded`与`last_ack`，分别表示最近有效解码和最近ACK确认，均依据板端报告，不是PLL遥测；最近解码不代表已执行。`--log-file`将完整会话日志保存到新文件，父目录须已存在，不覆盖旧文件。15项fake单测通过。自动采集固定为normal、A通道、k=0；界面模式、通道及k下拉框仅用于单次采集。

实际GUI连接COM10、读取status，启动network并auto on。真实ADC_NORMAL指令901/1000 MHz、seq81收到ACK，独立SPI读回900999998/1000000000 Hz，applied增至9。GUI auto off后发送新的900/1000 MHz、seq83；06:43:20与06:43:42两次status均为decoded=132、applied=9、pending=0、failures=0，auto=ARM=0，SPI仍保持900999998/1000000000 Hz。再由GUI auto on，seq83被接收并ACK，SPI恢复900000000/1000000000 Hz，applied增至10。本轮共两次成功真实ADC事务，没有使用GUI nettest，GUI nettest按钮仍未实测。

停止观察以收到板端`AUTO_OFF`确认为起点。点击停止到确认之间仍有一帧seq81完成解码并被去重，没有新增UDP；不能把鼠标点击时刻当成采集已停。

结束时GUI关闭network/auto/ARM，decoded=180、applied=10、pending=0、failures=0。发送板LO关闭、buffer=0、两路TX衰减89 dB、DDS全零；LDSDR mode=2、TX衰减89 dB。未修改PL/PS或启动介质。此次验证当前实物有线100.5 MHz输入的GUI启停及自动控制，业务RF、功率校准、全频段、误码率和长期连续运行仍待验收。证据见 [GUI实板控制摘要](validation/2026-10-28-gui-loop.json)。

### 2026-10-28：第一路业务单音转发与I/Q修正

接线为发送板TX1A→LDSDR RX1、LDSDR TX1→发送板RX1A；遥控板本轮没有模拟输入。原LDSDR接收I/Q配置将+500 kHz基带翻转为−500 kHz。RX LO与DUC步进、重启后重现以及仅切换RX swap位的对照定位到接收侧；固定版默认RX swap=0、TX swap=1，0x010读回0x88。

重新加载固定版后，900 MHz源本振加500 kHz单音，经900/1000 MHz转发本振输出到约1000.5 MHz。接收LO读回1000749998 Hz，测得峰值−250075.56 Hz；TX LO改为1001 MHz后峰值+749936.67 Hz，两次相差1000012.23 Hz。转发静音及源端关闭时，目标频带功率分别下降30.43、30.12 dB。五份8192组I/Q快照均无ADC削顶，采集前后转发器累计削顶计数增量为0。相对功率使用ADC参考dBFS，不是校准dBm；峰值频率基于板卡LO与采样时钟。

同一固定版另完成三组UART_NETTEST→UDP→ACK→独立SPI读回，900/1000 MHz恢复成功，RX swap保持0；遥控板applied从10到13，pending/failures均0。GUI、遥控协议和Z7ADDALite固件未修改；此次没有重复真实ADC自动控制测试。

源代码和六组故障注入测试见[board/ldsdr](../board/ldsdr/README.md)，16项源码/链接布局检查通过。重建程序的全部运行时LOAD布局及载荷与实测ELF一致，完整ELF hash因DWARF路径不同而不同。该入口依赖原UDP BSP/对象缓存，不是从零重建厂商工程。活动LDSDR PL的完整来源仍待归档。

早期诊断暖加载后板端未启动且调试访问异常，LOAD与旧ELF页表地址重叠是候选原因；故障前实际TTBR未取得，尚未确认根因。一次断电恢复后，后续加载先检查实际TTBR并拒绝覆盖活动页表。固定版仅下载PS RAM，未写启动介质。结束时发送板LO/DMA/DDS关闭、两路89 dB；LDSDR静音、两路89 dB、RX增益0；遥控板auto/network/armed/pending均0。断电后修正不会自动保留。详见[联调记录](rf-forward-bringup.md)及[数值和证据索引](validation/2026-10-28-rf-forward.json)。

### 2026-10-28：调制文本业务与UDP实际改频

沿用同一双SMA接线、同一固件和I/Q配置，以100 ksym/s、SRRC成形BPSK发送三种11字节文本；每份8192组I/Q由电脑1离线解码。9个正例窗口恢复14个完整CRC有效帧，payload逐字节一致；低输出基线、转发静音、源关闭均没有有效帧，实际坏CRC波形的1个完整候选被拒绝。文本使用队友旧实验帧AAAA/len/payload/CRC，不是CCSDS遥控V2帧。

另由遥控板UART_NETTEST经网口控制900/1000及900/1001 MHz，各抓两份相同hello world，4个正例窗口全部恢复正确文本，共5帧。实测载波均值从−250067.24到+749932.54 Hz，相差999999.78 Hz；ACK、独立SPI读回和实际内容关联通过。该次1001 MHz设置未调用LDSDR本地lo命令。恢复指令另收到ACK，applied从13增至16，最终auto/network/armed/pending均0、failures=0。

两轮合计19个完整CRC有效帧、1672个已接受payload bit与发送内容一致；这不是全体传输比特的BER测量，也不代表没有漏帧。所有采样无ADC削顶，采样前后LDSDR削顶计数增量0。9项离线测试通过，包括独立CRC/帧已知值；工具和详情见[调制文本验证](rf-payload-validation.md)，原始采样和日志包的校验和见[摘要](validation/2026-10-28-rf-payload.json)。GUI、遥控协议、三板固件和启动介质均未修改，结束时源关闭、转发静音、两端两路TX衰减89 dB。

### 2026-10-28：业务序列、保持输出与UDP恢复

沿用发送板TX1A→LDSDR RX1、LDSDR TX1→发送板RX1A的两根有线连接，没有ADDA SMA输入。实验BPSK文本序列为SEQ000:ABCD至SEQ007:ABCD循环，非遥控V2帧；离线序列工具8项测试通过。同一TX writer保持输出311.136秒、期间未重启，取得11次离散快照。另完成8次1000/1001 MHz交替UART_NETTEST/UDP设置及异常恢复；全轮11笔成功事务使applied从16增至27，最终pending=0、failures=0。

全轮25个8192组I/Q窗口中，23个正例均恢复预期序列，共29个完整CRC有效帧、2552个已接受payload bit；2个负例（基线、源关闭）无有效帧。CRC选定同步与已知序列锚定后的7356个条件比较bit无差异，未发现非预期payload，窗口内6个序列转移均一致。所有窗口ADC削顶为0、逐窗口LDSDR削顶增量0，保持输出阶段累计增量亦0。离散窗口不能量化跨采样空档的丢帧或整体BER，也不是24小时运行结论。

非法seq=256由CLI参数检查拒绝，未构成畸形UDP测试；network off验证软件disable后的拒绝与恢复，不是物理拔线。11笔事务从PC串口发指令到收到ACK通知为23.14～34.96 ms，不是纯网络或PLL时延。8次改频从请求到正确快照完成的主机流程上界约4.27～4.33秒，包含主机步骤，不代表射频建立时间。

本轮completed=true、cleanup_errors为空；源端LO/DMA/DDS关闭、两路TX衰减89 dB，LDSDR静音、两路TX衰减89 dB、RX增益0、RX900/TX1000 MHz，ADDA auto/ARM/network关闭。GUI、遥控V2、固件及启动介质未改。详情见[业务序列与稳定性验证](rf-stability-validation.md)，数值与证据校验索引见[摘要](validation/2026-10-28-rf-stability.json)。

## 后续验收

| 工作 | 验收要求 |
|---|---|
| 业务RF | 单音、实验文本/序列、311.136秒保持输出与离散快照及UDP实际改频已通过；下一步用两根SMA和已接DEBUG待识别的独立接收板验证业务链，继续量化误码率、长帧/持续吞吐、第二路及最终业务带宽 |
| 联合控制与源码归档 | 修正版已通过UART_NETTEST回归；真实ADC与业务同时运行仍需独立100.5 MHz指令源及第三根同轴，重跑真实ADC自动控制并确定活动LDSDR PL的完整源码与位流对应关系 |
| 接收性能边界 | 当前实物有线100.5 MHz工作点已通过；后续按目标工作范围开展电平标定、误码率、真实坏帧拒绝与接收边界测试 |
| 连续运行与启动 | 验证持续采集/控制、异常恢复、重复上电和启动介质方案，量化吞吐率与漏帧边界 |

旧`rtl/`、`fpga/src/`、原`sw/gui/`和历史仿真保留其早期工程范围，部分仍含原开发机路径，不用于直接重建Z7ADDALite。当前板级入口的工具路径可显式配置；2018.3第三方源和厂商工具依赖见板级README。旧协议线格式与新V2链路分别维护，不用旧环回或厂商资料目录名推断当前器件、端口与验收结果。
