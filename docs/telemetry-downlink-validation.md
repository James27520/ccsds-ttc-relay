# DAC 测控下行数字实现与板端验证

2026-10-28，保持现有两根业务 SMA、板间网线与 DEBUG 接线不变，完成 Z7ADDALite 下行发送源码、仿真、完整时序检查及临时 JTAG 板端验证。**DAC→SMA→SDR 的实际接收与 CRC 解码尚未验收**，本轮遥控板未接 SMA，不能把板端发送完成状态写成空口接收成功。

## 已完成

| 项目 | 结果与范围 |
| --- | --- |
| 新 PL | 从冻结 r4c 派生，ADC125及原捕获 ABI不变，新增512B发送缓存、100ksym/s BPSK、名义90.5MHz DDS和DAC DDR输出 |
| 默认状态 | 上电停发；显式单次发送约33.6ms后归零；可取消；失锁、配置失配或复位不自动续发 |
| DAC配置实板读回 | verified=1、finished=1，最终diagnostic=0x102A0110；关键模式/DCI/插值/电源状态及FIFO对齐检查通过 |
| 发送引擎仿真 | 850685项检查，3个完整包、170000周期逐样本检查；含完整位序、符号长度、越界、取消、复位/失锁、忙时拒写 |
| DAC SPI仿真 | 正常流程、14个关键读回失配、断开/钳位、FIFO未确认或未释放、期限及三线换向通过 |
| DDR输出仿真 | 119项检查：有符号I、Q保持零、DCI及异步复位；新增一级流水延迟固定为一个DAC周期 |
| 完整采集回归 | 786634项检查，4次完整捕获、524288样点；原ADC FIFO、epoch、超时、取消等回归通过 |
| 软件 | C启用/禁用两模式mock及Cortex-A9编译通过；4项Python测试通过，含合成矩形BPSK的频偏/相位/极性解调；C/Python的96B向量一致 |
| 实板停发与恢复 | 默认空闲、连续两次显式发送、发送中取消、故障后拒发/显式清除、CPU晚轮询、网络关闭后显式发送状态均通过 |
| 原功能回归 | selftest、合成解调、A通道k=0内部PN9通过；900/1001与900/1000MHz两次UART_NETTEST、匹配ACK及LDSDR独立SPI读回通过 |

本轮内部PN9为131072样点，errors/invalid/zero_states均0。遥控板的decoded=0、applied=2来自UART_NETTEST；没有新ADC_NORMAL输入证据。板端发送序号最终为7，其中包含一次取消，不能把7写成7次RF成功接收。

## 时序与来源

最终候选 `candidate04`，Vivado2026.1，`xc7z020clg484-2`：WNS **+0.066ns**、WHS **+0.048ns**、WPWS **+0.264ns**，TNS/THS/TPWS=0，DRC错误0、锁存器0、内部未约束端点0。56条ADC输入检查与64条DAC双边沿setup/hold检查齐全；新增命令/完成mailbox分别满足3ns/20ns数据路径限制。资源4330 LUT、7219 FF，DAC发送缓存占一块RAMB18。

最初候选未通过时序，没有下载。最终版在调制逻辑与ODDR之间增加一级寄存器，并明确区分异步复位到输出弧与正常数据路径；未放松ADC输入约束、DAC正常数据约束或增加整组时钟假路径。DAC约束依据AD9122 DCI delay=3，包含100ps板级偏斜预算；该预算未经过板级测量，66ps正余量也不代表已验证模拟链路。

CDC报告仍包含工具不能自动识别的复位结构及保持数据bundle提示。新增67条critical路径均与复位相关：1条复位同步器前的组合逻辑、34条到ODDR异步R端、32条到输出流水寄存器CLR端。系统/PS复位和MMCM失锁共用异步断言源；两域各自三级同步释放，ODDR与流水寄存器的释放由DAC域同步链保持。新增单bit状态使用三级同步；命令/完成bundle在确认前保持且实际布线延迟受限。未宣称CDC报告为零，也没有把正常数据路径整体排除。

PS另修复启动和取消的MMIO边界：外设复位中不发写事务，启动STOP延后至复位释放；取消后须等待尾握手结束再清空。旧r4c默认编译仍禁用新寄存器访问。仅新匹配PL使用显式`--tm-tx-enabled`的固件。PS/BSP平台HWH（除导出时间）、初始化脚本与上轮已验证平台一致；新XSA内嵌bit及当前init绑定检查通过。

| 产物 | SHA256 |
| --- | --- |
| adda_m2_candidate_tm.elf | `19aa52fc22f173473fdcd7d6937d59855cb14713a74d7d7c8ab7e2fc96aa5c9b` |
| telecontrol_system.bit | `1cfd233356baf7cd06715cf9ca638ac96d487b78d849e3ce660ca24386095fba` |
| telecontrol_system_final.xsa | `2b9783602b6211dc8f23dce1513c2157fa9cc0d871753818101018ad98306a07` |
| ps7_init.tcl | `3998a8f3c4e16e76286e8fcb2e6b73628e13c7f89f6efc51fd2319b52fb8b205` |

## 协议、收尾与下一步

ATM1二进制负载分别保留最近解码、UDP发送和匹配成功ACK的来源与序号。它复用已有业务实验外帧，不是完整CCSDS遥测标准帧；USB TM1接口和原遥控协议保持原含义。ACK频率不冒充独立SPI。发送四份重复快照用于有限发送中的接收机会，不代表四个独立事件；序号及uptime在PS初始化后重新开始。

收尾遥控板pending/stopping/network/armed均0，DAC发送状态0x28（已完成、缓存已使用、非active），diag=0；LDSDR恢复mode2、89dB衰减、gain0、RX900/TX1000MHz。只使用易失JTAG加载，未写Flash或SD。

本轮预检发现原独立接收板的USB序号`6`出现在COM19，系统报告空IIO序号及FISH Ball Rev.A，与此前COM18/Pluto Rev.C记录不同。地面站身份检查正确拒绝配置该设备，没有绕过检查。发送板COM17仍可识别并已确认停发。后续先重新确认接收设备身份，或在独立下行试验中使用已确认发送板的空闲RX1A；不凭外观推断角色。

下一步是单独验证 `Z7ADDALite DAC1/J6 → 已确认SDR接收口`：核对端口、电平、接收窗口与有限发送的时间重叠，再从实际I/Q恢复ATM1及CRC。当前用户无需移动线；有空闲SMA后再逐端口安排。完成该单链后再推进反向业务、频率资源规划及六线整体联动，不能仅凭新增六根同轴认定共用本振冲突已解决。

重建入口见[下行工程说明](../board/z7addalite/telemetry_downlink/README.md)，协议寄存器见[ABI](../board/z7addalite/telemetry_downlink/ABI.md)。原始报告、控制台记录、候选源快照和匹配固件的索引见[结构化摘要](validation/2026-10-28-telemetry-downlink.json)。
