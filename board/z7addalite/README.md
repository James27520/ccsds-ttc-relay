# Z7ADDALite 遥控板源码

目标链路：ADC 125 MSPS → PL 采集/每 4 点抽取 → PS C 解调（31.25 MSPS）→ UDP → LDSDR 转发板。这里归档可重建源码。r4c完整M2已通过临时JTAG上板的A/B全通道、k=0..3内部PN9/checker快照检查，板端检查与独立JTAG DDR导出检查一致；早期normal A/B格式与normal→training切换测试未接外部信号；2026-10-28另完成真实100.5 MHz SMA输入及自动控制闭环。

最终时序WNS/WHS/WPWS为+0.483/+0.022/+0.264 ns，TNS/THS/TPWS=0，DRC=0；198个动态mailbox端点均受20 ns物理延迟约束。网络修复正式固件的三组金标准与131072点合成波形（277 ms、no_UDP=1）通过；正式固件的一份A通道k=0内部PN9快照回归通过，板端与独立DDR检查错误均为0。`network on`成功，自动协商1000 Mbps，PC→遥控板连续ping 10/10通过（<1～2 ms）；UART_NETTEST双板UDP的四个成功事务、匹配ACK、独立SPI频率读回及network off拒绝通过；真实100.5 MHz SMA指令经ADC_NORMAL自动解调、UDP、匹配ACK及LDSDR独立SPI读回的四例控制与恢复已通过；GUI启停及ADC_NORMAL自动控制另已通过，GUI nettest按钮未实测；业务RF、误码率、长期连续运行与启动仍待验收。详细证据见 [最新验证记录](../../docs/validation.md)、[GUI实板控制摘要](../../docs/validation/2026-10-28-gui-loop.json)、[真实输入闭环摘要](../../docs/validation/2026-10-28-analog-loop.json)、[双板UDP验证摘要](../../docs/validation/2026-10-27-dual-udp.json)、[网络验证摘要](../../docs/validation/2026-10-27-network.json) 与 [r4c历史摘要](../../docs/validation/2026-10-27-m2.json)。

- `telecontrol_system/`：冻结 r4c 的 RTL、XDC、ABI、BD、脚本及仿真源码，构建用法见其 README。
- `ps_software/`：采集/网络/控制集成源码与离线重建入口，见其 README。
- `software/protocol/`：可独立编译的 C99 数字帧、RF_SET/ACK 及状态函数。
- `software/demod/`：浮点实采样解调及合成波形测试。
- `software/fixtures/`：确定性合成 ADC fixture 生成器。
- `host_software/`：Tkinter 串口界面与离线 fake 串口测试。
- `tools/serial_probe.py`：有时限的串口记录工具，仅发送显式 `--command` 参数。
- `tools/load_telecontrol_ps.tcl`：按指定线缆选择 XC7Z020/A9，复位并停两核、临时配置匹配 BIT，执行匹配 ps7_init 后将 ELF 下载到 DDR 运行；不写 Flash/SD。
- `tools/dump_adda_snapshot.tcl`：从明确线缆及 DDR 地址导出板端已发布、刷出缓存的 262144 字节快照；仅在脚本确实停下 CPU 时恢复执行。
- `tools/check_snapshot.py`：对导出的131072点快照独立检查 PN9、checker 或 normal 样点格式，不调用板端 C 检查器。

以下命令在仓库根目录执行。Python 需要 NumPy；串口工具需要 PySerial，GUI 需要 Python 自带的 Tkinter。依赖不随源码归档：

```powershell
python -m pip install -r board/z7addalite/software/requirements.txt -r board/z7addalite/host_software/requirements.txt
pwsh -File board/z7addalite/software/protocol/run_tests.ps1
pwsh -File board/z7addalite/software/demod/build_and_test.ps1
python -B -m unittest discover -s board/z7addalite/host_software -p test_monitor.py -v
python -B board/z7addalite/software/fixtures/generate_waveform_fixture.py
```

C 测试默认使用 PATH 中的 `gcc`；可传 `-Compiler <gcc.exe>` 或设置 `CC`。波形脚本默认使用 `python`（可传 `-Python` 或设置 `PYTHON`），默认参考当前仓库的 `sw/ccsds/ccsds_tm_tx.py`，可通过 `-Reference` 显式覆盖。编译器所在目录会临时加入 PATH，以加载工具链运行库。可选 `-ArmCompiler <arm-none-eabi-gcc.exe>` 仅检查 Cortex-A9 目标文件编译，不代表已链接 BSP 或上板运行。

普通协议测试不依赖旧工程。如需核对旧解析器，显式运行 `run_tests.ps1 -LegacyInclude <含relay_rf_packet.h的目录>`，或设置 `ADDA_LEGACY_INCLUDE`。编译结果位于各目录 `build/`；fixture 默认写入 `software/fixtures/generated/`，也可传 `--output <目录>`。生成的大型 C 数组、二进制、缓存和日志均不入库。fixture 是合成数据，不是 ADC 实测，不能作为 UDP 控制来源。

GUI 启动：`python board/z7addalite/host_software/adda_monitor.py`。程序启动、连接串口均不自动发送命令；真实采集、网络初始化、ARM 与 nettest 操作需操作者在界面中明确选择。离线测试仅使用 fake 串口和隐藏窗口，不打开真实 COM 口。具体输入、算法限制和串口行为见子目录 README。

FPGA 工具链构建需要先把相应工程复制到纯 ASCII 工作目录；本仓库所在中文路径不应直接用作 Vivado 构建目录。PL 冻结构建入口会自动把输入复制到指定的 ASCII 输出目录，详见 `telecontrol_system/README.md`。

PS 的 ARM/BSP 重建、网络补丁 mock 测试及 `verify_xsa_binding.py` 的离线 XSA/HWH/init/bit 一致性入口，见 `ps_software/README.md`。硬件工具的显式参数如下（先完成匹配输入审阅与线缆识别，再由操作者运行）：

```powershell
xsdb.bat board/z7addalite/tools/load_telecontrol_ps.tcl '<匹配ELF>' '<匹配ps7_init.tcl>' '<匹配BIT>' '<线缆序列号>'
xsdb.bat board/z7addalite/tools/dump_adda_snapshot.tcl '<线缆序列号>' '<0x加8位DDR地址>' '<新快照.bin>'
python -B board/z7addalite/tools/check_snapshot.py '<快照.bin>' --kind pn9 --output '<检查结果.json>'
```

DDR 地址必须取自对应固件实际发布的快照记录，并结合 UART 的来源、通道、epoch 等元数据保存。`--kind checker` 用于内部 checker 抽取结果；`--kind normal` 仅检查样点格式，不宣称收到外部信号或有效命令。内部 PN9/checker 检查面向 ADC training 模式 `0x14=0x05`，离线检查不等于新的硬件验收。

## 双板 UDP 复测

此UART_NETTEST复测仅将两块板的RJ45直接相连，USB调试口均接电脑，不接SMA；真实SMA输入闭环另见上述2026-10-28报告。先核对两块板的JTAG线缆和UART USB序列号，再加载报告中记录的匹配固件。LDSDR使用既有工程的UDP固件（SHA256 `c37843bf31165e12124d267f1104f2e5fb22ab1121dfeae22122d8a3bd9183cd`），该ELF与其完整厂商工程仍在独立的`relay_udp_work`目录，本仓库不包含其BSP和启动映像。下面的LDSDR加载器要求该板已经由原启动介质完成正确PS/PL初始化，不能用于裸板冷启动，也不能传入ADDA的ELF或ps7_init。

```powershell
xsdb.bat board/z7addalite/tools/load_relay_udp_checked.tcl '<已核对的LDSDR UDP ELF>' '<LDSDR JTAG序列号>'
python -B board/z7addalite/tools/check_dual_board_udp.py --adda '<ADDA COM口>' --relay '<LDSDR COM口>' --adda-usb-serial '<ADDA UART USB序列号>' --relay-usb-serial '<LDSDR UART USB序列号>' --out '<新的结果目录>'
```

脚本先校验USB身份并设置转发板静音、89 dB TX衰减，要求初始RX/TX为900/1000 MHz。电脑仅发送串口命令，UDP由遥控板产生。五项检查覆盖原值、RX单独改频、TX单独改频、network off拒绝和重新启用后的恢复；每个成功事务均核对ACK、计数及独立`rfread`。结束时恢复900/1000 MHz，关闭遥控板网络/ARM并保持LDSDR静音。原始串口日志和JSON存入新目录，异常恢复不计为UDP成功。该脚本不验证外部ADC信号或射频频谱。
