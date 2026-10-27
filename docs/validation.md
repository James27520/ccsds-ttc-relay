# 验证记录与未完成项

记录日期：2026-10-27。当前对象为 Z7ADDALite 遥控板（`xc7z020clg484-2`，AD9643）；PL 采集、PS C 解调及 UDP 控制路线的源码、约束、GUI、测试与重建入口已归档到 [board/z7addalite](../board/z7addalite/README.md)。下列上板操作均为临时 JTAG 加载，未写启动 Flash。

最新网口验证及修复回归见 [网络验证摘要](validation/2026-10-27-network.json)；r4c时序、全通道快照和历史串口证据见 [r4c完整M2验证摘要](validation/2026-10-27-m2.json)。[早期摘要](validation/2026-10-27.json) 保留为当天前期快照；原40字节RTL环回另见 [历史验证记录](legacy-validation.md)。原始采样二进制和完整厂商构建输出不随源码包分发。

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

normal A/B快照的14位符号扩展格式检查通过，normal后重新切回training A的PN9检查通过。normal测试未接外部信号，只证明本次格式与模式切换，不能作为模拟指令接收证据。ADC_TEST快照decode没有有效帧，没有发出RF_SET。

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

真实双板UDP尚未开始，当前等待将PC端网线移接LDSDR；本次PC连通结果不代表RF_SET、匹配ACK或业务RF已验收。

串口GUI已在最终r4c固件上实际完成status、selftest、waveformtest、normal采集、空输入decode及training采集。normal输入未解出有效帧，切回training后PN9检查通过；GUI显示快照就绪、来源ADC_TEST、网络/ARM/自动模式关闭，未发送RF_SET。10项fake串口测试继续覆盖输入校验、连接不自动写命令及来源/状态分离。

## 后续验收

| 工作 | 验收要求 |
|---|---|
| 双板UDP/业务闭环 | 将PC端网线移接LDSDR，确认LDSDR固件与端口；验证RF_SET、匹配ACK、频率读回及实际业务转发；PHY识别和PC→ADDA连通已通过 |
| 真实100.5 MHz输入 | 登记发送端端口、电平与衰减；验证V2多组指令、序号变化、坏帧拒绝和实际接收边界 |
| 连续运行与启动 | 验证持续采集/控制、异常恢复、重复上电和启动介质方案，量化吞吐率与漏帧边界 |

旧`rtl/`、`fpga/src/`、原`sw/gui/`和历史仿真保留其早期工程范围，部分仍含原开发机路径，不用于直接重建Z7ADDALite。当前板级入口的工具路径可显式配置；2018.3第三方源和厂商工具依赖见板级README。旧协议线格式与新V2链路分别维护，不用旧环回或厂商资料目录名推断当前器件、端口与验收结果。
