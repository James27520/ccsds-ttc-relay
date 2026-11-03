# 转发板 UDP 改频实验

## 当前状态（2026-10-18）

已在连接的转发板上完成 UDP 收包、AD9361 接收/发射本振改频和独立 SPI 读回验证，7 项检查全部通过。使用现有 Vivado 2026.1 XSDB、STM32CubeIDE 附带的 ARM GCC 12.3.1 和归档 BSP 完成构建与下载，无需安装 SDK 2018.3。

| 检查 | 结果 |
| --- | --- |
| 同频设置 | 接收 900000000 Hz，发射 1000000000 Hz |
| 单独修改接收频率至 901 MHz | SPI 读回 900999998 Hz，发射不变 |
| 再修改发射频率至 1001 MHz | SPI 读回 1000999998 Hz，接收不变 |
| 错误 CRC | 返回 rc=-3，频率不变 |
| 错误长度 | 返回 rc=-1，频率不变 |
| 越界频率 | 返回 rc=-4，频率不变 |
| 恢复原频率 | 接收 900 MHz，发射 1000 MHz |

2 Hz 差异来自本振频率量化。验证使用 `rfread` 命令调用 AD9361 驱动通过 SPI 读取本振配置；尚未用频谱仪测量射频输出。测试结束已恢复接收增益 0 dB、发射衰减 30 dB、转发模式和状态自动输出。

**当前为 JTAG 加载到 DDR 的软件版本，重启后将运行原启动介质中的固件，需要重新加载。尚未制作上电自启动 BOOT.bin。** 现有 PL、SD 卡和 Flash 未改写，也未重新生成 bitstream。

## 已验证的连接

- 板端地址：`169.254.9.10/16`，UDP 端口 `5005`。
- 电脑以太网：`169.254.219.130/16`，Windows 接口索引 `5`，链路 1 Gbps。电脑地址及接口索引可能变化。
- 串口：`COM13`，115200 波特率。运行验证脚本前关闭其他占用串口的软件。
- RF_SET：现有 `rk3588/ccsds.py` 的 26 字节空间包，APID `0x101`。PS 检查包头、长度、CRC 和参数范围，调用 AD9361 API 后返回完整 Hz 读回值。

## 电脑发包

在本目录运行（需要 Python 3）：

```powershell
python send_rf_udp.py
python send_rf_udp.py --rx-mhz 901 --tx-mhz 1001
python send_rf_udp.py
```

第一条和最后一条将频率设置为 900/1000 MHz。成功应答示例：

```text
rc=0 seq=7 rx_hz=900999998 tx_hz=1000999998
```

## 重建固件

```powershell
python IoT-NTN-FPGA-Relay/scripts/build_udp_standalone.py
```

默认构建目录为 `D:\RelayTools\work\relay_udp2026`，可通过 `--build-dir` 修改；`--gcc` 可指定 `arm-none-eabi-gcc.exe`。默认自动查找本机 STM32CubeIDE 的编译器。

首次构建从 Xilinx 官方 GitHub 下载 `embeddedsw` 的 `xilinx-v2018.3` 标签源码压缩包，约 47 MB；已有缓存会复用。脚本提取 lwIP 2.0.2 和 GEM 驱动，结合归档 BSP 编译，处理当前编译器/newlib 的兼容差异。输出包括 ELF、链接映射和带 SHA256 的构建清单。

已验证 ELF 大小约 848 KiB；链接的代码、数据及 BSS（含预留堆栈）合计约 2.73 MiB。这是板端内存占用规模。

## 通过 JTAG 重新加载

本脚本适用于本次验证的原板端启动环境：原 FSBL 已初始化 DDR、PS 时钟、GEM0 RGMII/MDIO 引脚，原 PL 已加载。它不是冷启动初始化脚本。归档 HDF 中 ENET0 为关闭状态，本实现通过软件显式补充 GEM0 配置；硬件工程和 BSP 尚未完整迁移到 2026。

先在串口依次发送 `auto 0`、`mode 2`，暂停状态输出并将转发静音，然后运行：

```powershell
& 'D:\AMDDesignTools\2026.1\Vivado\bin\xsdb.bat' '.\IoT-NTN-FPGA-Relay\scripts\program_udp_warm.tcl' '.\firmware\relay_udp.elf'
```

脚本保留 PS/PL 初始化，停止 ARM 核、下载 ELF 并继续执行。若 GEM0 时钟未启用，脚本报错，需要先完成匹配的 PS 初始化。串口出现 `UDP RF_SET ready: 169.254.9.10:5005` 后即可发包。串口 `rfread` 返回独立 SPI 本振读回；`status` 中的 MHz 字段不能替代该检查。

## 重复实板验证

需要 Python 的 `pyserial` 包。脚本临时改变频率，结束时恢复测试前的本振、增益和衰减，并开启状态自动输出。

```powershell
python IoT-NTN-FPGA-Relay/tools/test_udp_rf.py --host 169.254.9.10 --local-ip 169.254.219.130 --interface-index 5 --serial COM13 --log verification_logs/udp_rf_repeat.json
```

请按电脑实际网卡和串口调整参数。脚本使用 UDP 应答和串口 SPI 读回交叉检查，记录每个包及结果。

## 交付文件

- [已验证固件](firmware/relay_udp.elf)、[构建清单](firmware/build_manifest.json)、[交付哈希及验证关联](firmware/release_manifest.json)。
- [最终实板验证记录](verification_logs/udp_rf_verified_final_20261018.json)、[最终下载记录](verification_logs/udp_deploy_final_20261018.json)。
- `IoT-NTN-FPGA-Relay/ps/`：维护的控制协议、UDP 服务和 UART CLI 头文件，构建时覆盖到应用副本。
- `vendor_sdk/9361/src/`：接入 UDP 的厂商 PS 应用副本。
- `IoT-NTN-FPGA-Relay/scripts/build_udp_standalone.py`：可重建脚本。
- `IoT-NTN-FPGA-Relay/scripts/program_udp_warm.tcl`：保留现有初始化的 JTAG 加载脚本。
- `IoT-NTN-FPGA-Relay/tools/test_udp_rf.py`：实板验证脚本。

下一步若需要上电自动运行，应生成匹配 GEM0 配置的 PS 初始化、FSBL 和启动镜像，并单独验证冷启动。
