# Z7ADDALite PS 接收与转发

包含采集 ABI 客户端、来源/ARM/事务门控、PN9/checker 检查、CLI/平台接入和网络 BSP 补丁。协议与解调算法位于相邻 `software/`。原 C/H、网络策略及补丁字节不变；仓库仅调整 `test_pattern_check.py`，使其重放归档的 PN9 mem。`SOURCE_MANIFEST.json` 列字节不变输入，`REPRO_MANIFEST.json` 单列该测试入口差异。完整r4c已临时上板通过全通道/四个k内部PN9/checker及normal格式/切换检查，板端与独立DDR检查一致；真实模拟输入和PHY/双板UDP仍待验收。

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

最终采集ELF SHA256为 `00d14352729bb2748f7a7604547416474b9022082a520b8b6e35dcf49ac64c30`：三组金标准与131072点合成波形在板端通过，波形278 ms、no_UDP=1；ADC_TEST decode未发现有效帧，未发RF_SET。`network on`仍因MDIO无PHY响应返回rc=-2，随后status/selftest正常；v6的三次失败恢复与最终固件一次失败恢复均有记录，未据此证明物理网络连通。
