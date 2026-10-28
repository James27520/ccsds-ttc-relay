# Z7ADDALite PS 接收与转发

新增遥控操作 `0x21/0x22/0x23`，对应开启租期、静音停止、只读查询；详见[wire约定](../../../docs/remote-relay-control.md)。ADC_NORMAL 开启固定为30 dB RX增益、50 dB TX衰减、300000 ms租期；原`0x01`仍只改频。新操作发送34字节UDP，严格匹配50字节binary ACK的peer/操作/序号；成功还必须通过实际回读检查。匹配负ACK保存为失败状态并可下行，不增加成功计数。ATM1/UART TM1保持旧格式，新操作使用ATM2（112字节payload、484字节有限burst）。服务发送窗口按实际burst长度预留结束时间。首次发送新协议后UDP序号单boot不再回卷，16383用尽必须重新初始化双方。

显式台架诊断入口为`remotenettest <enable|stop|status> <rx_mhz> <tx_mhz> <air_seq> <lease_ms>`。必须network ready、arm off、auto off、service inactive且capture不在进行中；enable租期2000..300000 ms，stop/status必须为0。仅此UART诊断入口可覆盖开启租期，电平仍固定30/50；来源始终为`UART_NETTEST`，没有空口解码记录。匹配ACK另输出完整`REMOTE_ACK source=... operation=... air_seq=... udp_seq=... rc=... flags=... mode=... rx1_gain=... rx2_gain=... tx1_mdB=... tx2_mdB=... remaining_ms=... uptime_ms=... rx_hz=... tx_hz=...`行，数值仅在flags bit0置位时视为有效硬件回读。`build_remote_tests.ps1`与扩展的`build_service_tests.ps1`验证协议、短租期诊断隔离、负ACK和ATM2突发边界；这些native测试不访问硬件。

2026-10-29新增 `adda_service.c` 有界自动测控服务，与 candidate04 ADC/DAC PL及 `--tm-tx-enabled` 构建配套。一次台架执行 `network on`、`service on` 后，板端自主完成ADC_NORMAL采样、C解调、UDP/ACK和有限DAC回报，不需要每笔下发capture/decode/tmsend。`service status`只读；`service off`取消并清理。启动默认关闭，服务限600秒/16笔事务，每个空口序号在本次服务中最多接受一次；ACK后延迟3秒，在20秒窗口内至多发送400次同一快照。停止、断网或异常不产生成功回报。实际GUI闭环与限制见[自主测控验证](../../../docs/telecontrol-autonomous-validation.md)，`build_service_tests.ps1`提供无硬件状态机测试。下方记录保留各历史阶段的适用边界。

最新增加[DAC有限下行](../telemetry_downlink/README.md)配套驱动及ATM1二进制状态包。默认构建禁用新MMIO，仍兼容r4c；仅配套新PL时显式使用`build_platform.py --tm-tx-enabled`，输出名含`_tm`。命令为`tmstatus/tmsend/tmstop/tmclear`，启动停发，支持复位延后STOP与取消尾握手检查。本轮新PL/ELF已临时上板，结果及尚未完成的SMA接收见[DAC下行验证](../../../docs/telemetry-downlink-validation.md)。`build_telemetry_tests.ps1`覆盖启用/禁用驱动及ARM编译；`python -m unittest sw.tools.test_telemetry_downlink`从仓库根运行。

2026-10-28更新：增加只读 `telemetry` 命令及[TM1状态帧](../../../docs/telemetry-status.md)，分别保留解码、发送、匹配ACK来源。新PS实板selftest、合成解调、内部PN9、三次UDP/ACK/SPI及网络关闭负例通过，见[本轮验收](../../../docs/station-speed-telemetry-validation.md)。该回传经DEBUG USB，未实现DAC射频下行；r4c PL不变。以下原有网络发布记录为历史证据，新的ELF与来源以本轮摘要为准。

当前 `build_platform.py` 在链接前要求 `ADDA_BSP_BUILD_V2` 清单。旧库即使曾通过实板也要用当前 `build_bsp.py` 从已打补丁的BSP重新编译；不要只复制或补写清单。构建冻结实际源码和本地/共享头文件，并绑定对象、archive成员、库hash及当前PHY策略，防止错用旧地址扫描驱动。离线负例可运行 `python -B board/z7addalite/ps_software/test_build_bsp_guard.py -v`。本轮10项检查、101个xil及34个lwip对象重建通过。平台与最终XSA的一致性仍须另行运行下述绑定检查。

包含采集 ABI 客户端、来源/ARM/事务门控、PN9/checker 检查、CLI/平台接入和网络 BSP 补丁。协议与解调算法位于相邻 `software/`。网络BSP补丁及测试已更新本板PHY地址策略；`SOURCE_MANIFEST.json`记录对应输入及测试hash，`REPRO_MANIFEST.json`记录历史PN9 mem回放入口差异。完整r4c已临时上板通过全通道/四个k内部PN9/checker及normal格式/切换检查，板端与独立DDR检查一致；PHY识别、1000 Mbps协商及PC ping已通过，UART_NETTEST双板UDP、匹配ACK及独立SPI频率读回已通过，真实模拟输入与业务RF仍待验收。

以下主机测试从仓库根目录运行，需要 NumPy、宿主 GCC、支持 Cortex-A9 的 `arm-none-eabi-gcc.exe`。工具目录通过参数、`ADDA_HOST_GCC_BIN`/`ADDA_ARM_GCC_BIN` 或 PATH 提供，不绑定开发者磁盘路径：

```powershell
python -B board/z7addalite/software/fixtures/generate_waveform_fixture.py
pwsh -File board/z7addalite/ps_software/build_core_tests.ps1 -taskHostBin '<宿主GCC的bin>' -taskArmBin '<ARM GCC的bin>'
pwsh -File board/z7addalite/ps_software/build_capture_tests.ps1 -taskHostBin '<宿主GCC的bin>' -taskArmBin '<ARM GCC的bin>'
python -B board/z7addalite/ps_software/test_pattern_check.py --host-bin '<宿主GCC的bin>'
```

fixture C/H 为本地生成的合成数据，不提交大型数组。core/capture 测试包含 ARM 目标文件编译检查，但不链接 BSP 或运行板卡；UDP/UART/总线为 mock。pattern 的 57 case 使用 `telecontrol_system/sim/pn9_fixtures/` 三份历史内部测试捕获派生输入，并验证 fixture SHA；结果记录原 CSV SHA 与来源，测试中不依赖原 CSV，不代表新实测。可用 `--fixtures`、`--out` 显式替换位置，默认结果位于 `build/pattern/`。

完整离线 BSP/ELF 重建需要外部 Xilinx `embeddedsw-xilinx-v2018.3.zip`（本次验证归档 SHA256：`c654f487b75925764d4685f531fe7a4ea00a26d49c1fc90b29f429e39c5adeb2`）、与最终 XSA 匹配的 Vivado/XSDB HSI 工具和 ARM GNU 工具链。请在 ASCII 工作目录放置板级源码副本（保留 `ps_software`、`software`、`telecontrol_system` 相邻结构），然后在副本的 `ps_software/` 执行以下命令；所有输出目录必须选新目录。`platform_2018.mss` 对应 standalone 6.8、cpu_cortexa9 2.7、emacps 3.8、lwip202 1.2，生成前需与 XSA 的 PS7/UART1/以太网实例核对。

```powershell
$taskXsa = '<已审阅的最终ADDA XSA绝对路径>'
$taskSdk = '<embeddedsw-xilinx-v2018.3.zip绝对路径>'
$taskArmBin = '<ARM GCC的bin>'
$taskHostBin = '<宿主GCC的bin>'
# xsdb.bat 必须在 PATH；不要连接 target 或下载。
python -B ../software/fixtures/generate_waveform_fixture.py
python -B prepare_local_sources.py --embeddedsw-archive $taskSdk
xsdb.bat generate_m2_bsp_template.tcl $taskXsa platform_2018.mss platform_bsp_new
python -B patch_network_bsp.py --source platform_bsp_new --out platform_bsp_patched
python -B test_network_bsp.py --bsp platform_bsp_patched --out build/network_tests --host-bin $taskHostBin
python -B build_bsp.py --bsp platform_bsp_patched/ps7_cortexa9_0 --out bsp_build_new --arm-bin $taskArmBin
python -B build_platform.py --bsp bsp_build_new --out platform_build_release --xsa $taskXsa --ps-init platform_bsp_new/xsa_extracted/ps7_init.tcl --arm-bin $taskArmBin --hardware-note 'reviewed r4c platform'
```

准备脚本可改用 `ADDA_EMBEDDEDSW_ARCHIVE`；已保留链接参考，因此无需巨大 vendor UART 归档。它提取第三方源及顶层 `license.txt`，不下载依赖；每文件版权头及 lwIP COPYING 保留。补丁创建新 BSP 副本，验证 NO_SYS/autodetect/RGMII 前提并记录 diff/hash，不复用 LDSDR 的生成头、库或 ps7_init。网络负例测试从实际打补丁后的厂商函数抽取并编译 mock harness，验证 PHY/MDIO/初始化失败与恢复，完全不访问网络或板卡。

`build_platform.py` 生成独立 selftest 与采集候选 ELF、map、源快照和输入 hash 清单；以最终 XSA 生成的 ps7_init 为准。`vendor_reference/lscript_reference_only.ld` 是带 Xilinx 原版权的 2018.3 链接参考，构建脚本另生成调整后的链接脚本；它不证明与任何硬件映像兼容。BSP、库、ELF、缓存、生成的大型 fixture 均不入库。项目根许可证不覆盖 Xilinx/AMD 驱动、lwIP、链接参考和其他第三方源；各自许可证及版权约束继续适用，外部 SDK 归档不在本仓库分发。

在发布 ELF 前，用归档的只读一致性工具绑定 BSP 来源平台和最终位流（在本目录运行，输出文件必须未存在）：

```powershell
python -B verify_xsa_binding.py --platform-xsa '<生成BSP所用平台.xsa>' --final-xsa '<含bit的最终.xsa>' --ps-init '<匹配的ps7_init.tcl>' --bit '<最终.bit>' --out build/xsa_binding.json
```

该工具只依赖 Python 标准库，比较两份 XSA 内全部 HWH（仅忽略导出根 TIMESTAMP）、ps7_init 字节和最终 XSA 内嵌 bit 的 SHA256；失败返回非零。它不生成 BSP，也不访问硬件；一致性 PASS 不能替代板级验收。

本次仓库离线核验：core 88 assertions、capture/controller 11193 assertions、pattern 57 cases 通过；core/capture 的 Cortex-A9 hard-float compile-only 通过；网络 PHY/init/MDIO 三组 mock 测试通过。最终r4c BSP/ELF已另行完成生成、链接及HWH/init/bit绑定检查，见 [r4c验证摘要](../../../docs/validation/2026-10-27-m2.json)。

历史完整M2采集ELF SHA256为 `00d14352729bb2748f7a7604547416474b9022082a520b8b6e35dcf49ac64c30`，其失败恢复记录保留于r4c摘要。原“MDIO无PHY响应”推断已纠正：JTAG直读地址0和1均为`001C:C915`，RTL8211E原厂datasheet 7.7 Table 13定义地址0为广播地址，实际地址脚为1。当前本板驱动严格使用地址1及ID `001C:C915`，允许匹配该ID的地址0广播响应；其他地址、错误ID和MDIO错误仍拒绝。

网络修复正式ELF SHA256为 `aa7eb6d368f8ab256749d53a40ad24d1b50ddccac0873e13c6e705a97ce8b4a2`，配套r4c BIT SHA256为 `10ac68b0ccfcfb5dbe50c80d8ed185e840ff6be3e67a331bd3d50b712a97057b`、ps7_init SHA256为 `3998a8f3c4e16e76286e8fcb2e6b73628e13c7f89f6efc51fd2319b52fb8b205`。正式固件实板`network on`成功并自动协商1000 Mbps，status显示network=1；PC `169.254.219.130` → ADDA `169.254.9.11` 连续ping 10/10通过，延迟<1～2 ms。正式固件selftest与131072点合成波形（277 ms、no_UDP=1）通过；正式固件的一份131072点A通道k=0内部PN9，板端及独立DDR检查错误均为0。UART_NETTEST来源的ADDA `169.254.9.11:5006` → LDSDR `169.254.9.10:5005` 双板UDP已通过：四个成功事务均获匹配ACK，network off时拒绝且SPI读回保持原值，重新开启后恢复900/1000 MHz；最终applied=4、pending=0、failures=0，network/armed/auto均关闭。真实100.5 MHz/SMA输入、业务RF及持续运行/启动仍待验收。见 [双板UDP验证摘要](../../../docs/validation/2026-10-27-dual-udp.json) 与 [网络验证摘要](../../../docs/validation/2026-10-27-network.json)。
