# 遥控板（Z7ADDALite）V2：核对与进展

更新：2026-10-27 00:27。DDR125 的 ADC 数字接口验收已通过：A 使用芯片内部 PN9、B 使用棋盘码，两次临时 JTAG 加载后共六段捕获、98,304 个 A 样点，PN9 零错误且覆盖全部 14 位，B 棋盘码与十项配置读回全部正确。PN9 版最终 WNS +0.483 ns、WHS +0.075 ns、TNS=0。未写启动 Flash；这不代表模拟中频接收或 PS/网络联调完成。汇总：`D:\RelayTools\work\adda_rx\validation\m1_125.json`。

角色以用户最新说明为准：本机 Z7ADDALite 现在对应旧图下方“遥控板”，名称不变；旧图左上“ADDA”位置已经由其他板卡替换。当前用户已选择先验证 125 MSPS 方案，并授权自主推进本板职责内的采集、PS 解调、网络控制和验证工作。

日期：2026-10-26。输入包：`C:\Users\Lu\Downloads\adda_handoff_v2.zip`；SHA256 `f2b571e399ae75b0872dd77b415663982e3e460060f2c10a1a5f98ee8785600c`。原包已解压至项目旁的 `adda_handoff_v2`，内容保持原样。

新路线按 **100.5 MHz 有线指令 → ADDA ADC → PS C 解调 → 网口控制 LDSDR** 开发。旧 DAC 信号源路线已停止。工程基线来自厂商 **LOOP** 的 ADC、时钟及引脚配置；不再使用 SIN_16BIT 的波形 ROM 路线。

## 给对接人的硬件答复

| 项目 | 核实结果 |
| --- | --- |
| ADDA 器件 | JTAG 识别 xc7z020；硬件手册和 RevB 原理图为 XC7Z020-2CLG484-I，Vivado 使用 `xc7z020clg484-2`。不能执行包内改成 `xc7z010clg400-1` 的步骤；后者混淆了 LDSDR 与 ADDA |
| PS USB Host | 现有 Type-C 的 D+/D- 接 FT2232HQ，作为 JTAG/UART；板卡资料未发现可直接使用的 PS USB PHY/Host 连接，厂商 Linux BD 也禁用 USB0/1。不能用这根调试 USB 线从 ADDA 控制转发板串口 |
| 当前系统 | 原有系统未确认；2026-10-27 已通过 JTAG 临时运行新编译的 Cortex-A9 裸机程序，COM10 115200/8N1 正常。未写入 Flash/SD，断电后恢复原启动介质 |
| PS 实施路线 | 本板 PS/DDR/UART/Ethernet 配置＋standalone C＋lwIP；无需 Linux `/dev/mem`。已生成 BSP、链接 ELF 并在本板完成帧和合成波形解调自检 |
| 转发板控制 | 沿用之前实际验证过的 26 字节 UDP RF_SET，避免新建 TCP/SSH。当前 LDSDR 跑的是 UART 诊断固件，正式联调前须整合/恢复 UDP 接口 |

硬件证据见 `D:\RelayTools\work\adda_rx\review\hardware_plan.md` 与 `adc_review.md`；串口原始记录为同目录 `adda_uart_probe.json`。

## 对交接包的必要修正

1. 双通道 DDR 1:8 的 112 位向量含 **两路各 4 个样点**；后级逻辑为 62.5 MHz，ADC 仍是每通道 250 MSPS。1:8 降低后级频率，不等于解决输入引脚的全部时序。两版未通过后，优先验证单通道 SDR 接收候选，见后文。
2. 100.5 MHz 在 31.25 MSPS 下的别名为 **6.75 MHz**，平方项为 13.5 MHz。JSON 和 PS 文档中的 6.25 MHz 不采用。实数平方还有 DC，不能全谱找最大值。
3. K=7 的最小 Viterbi trellis 为 **64 状态**。已有 Python 的 128 寄存器状态实现是冗余方式，不据此认定其一定解码错误。无尾比特时末态要取最小度量，不能强制零态。
4. 65536 点只有 2.097 ms，不能保证随机起点包含完整 1.6 ms 帧；计划使用 131072×16 位（256 KiB，4.194 ms）或重叠处理。M2 地址和容量必须统一，不能用 128 KiB 缓冲读取 256 KiB。
5. 8 点 boxcar 会把目标 100.5 MHz 信号衰减约 **21.69 dB**。诊断路径先明确为每 8 点取 1 点，后续评估带通抗混叠或 PL 下变频；不把它称为已完成的抗混叠接收器。
6. `COLLAB_PROTOCOL.md` 仍是旧 DAC 角色；删除 ADC 的指示作废。`rx_board.py` 的文本解调不是完整 V2 指令译码器；`pluto_siggen.py` 还依赖包内未附带的 `ccsds_tm_tx.py`，本地已有仓库可提供参考。
7. 发送脚本 `tools/pluto_siggen.py:268` 固定 `seq=0`，且没有 `--seq` 参数。按双方协议，相同序号必须去重；因此发送下一条不同频率指令时须使用新的序号，否则会被接收端识别为冲突。此项需在发送端同步修正，不能靠接收端绕过去重掩盖。

## 验证状态

| 项目 | 当前证据 | 尚不能声称的结果 |
| --- | --- | --- |
| M1 解串与 SPI | DDR125 PN9版 WNS +0.483 ns、WHS +0.075 ns、TNS=0；两次临时加载、六段捕获，98,304个A样点零PN9错误，14位全覆盖，B棋盘码/十项读回/向量计数全部正确 | 未证明普通模拟输入、绝对采样率精度、温压全范围性能；斜坡重复现象保留原始记录，不作为验收依据 |
| M2 PS 采集 | 已修正数据格式、容量与时钟跨域方案的设计约束 | 尚未建立 AXI 采集接口，未从 PS 读到实际 ADC 数据 |
| M3 帧层 C | 三组外部金标准编码/译码一致；2906 项断言通过，含错帧、截断、范围、极性、ASM 和 UDP/ACK 状态逻辑 | 不能用数字帧测试替代实数波形接收或板上运行 |
| M3 波形 C | 45/45 主机合成波形测试通过；板上 Cortex-A9 已对131072点固定合成波形解出100/2450MHz、seq0，报告耗时279ms；三组帧金向量亦实板通过，自测无UDP | 自测来源为SYNTHETIC，尚不证明ADC模拟波形或真实空口帧；279ms/块不是全速无间断接收 |
| M4 UDP 适配 | 26字节报文兼容原LDSDR解析器，只在匹配成功ACK后记录生效；无链路实板测试发现旧lwIP协商失败断言，正在改为有界报错并可重试 | 尚未由ADDA网口实际控制LDSDR；网口初始化返回不能替代物理链路和ACK验收 |

代码和构建原始证据位于 `D:\RelayTools\work\adda_rx`：`fpga` 为历史 M1 原型，`fpga_125_candidate` 为已加载的 DDR125 诊断版，`fpga_125_pn9` 为独立 PN9 诊断版，`telecontrol_system` 为 M2 集成工作区，`software/protocol` 为 C 帧层及 UDP 封装，`software/demod` 为波形解调。当前未向 GitHub 推送；已临时下载 DDR125 PL 位流，尚未启动新 PS 固件。

当前板上 M1 是 A PN9 / B 棋盘码的数字诊断程序。两次已测启动均识别 A 在原始偶数槽，但 M2 仍须每次启动自主训练，不能把这次结果硬编码为所有启动的通道位置。正常模式不使用测试码的极性补偿。两板仍无已确认的 SMA 连接，当前也没有本地可用的队友信号源和已确认衰减器，不能填写“现场收到 rx/tx、CRC OK”。

## 保留 250 MSPS 的单通道候选

ADI 的 AD9643 手册明确说明：通过 0x14 bit4 仅禁用一路数字输出后，保留通道的数据会在上升和下降沿重复。因此当前只接收一路中频时，可以保留 ADC 250 MSPS，将 FPGA 接口改为 SDR 1:8，得到 31.25 MHz 的每拍 8 个 A 样点；每拍选一个固定位置即为 8 倍抽取，输出仍为 31.25 MSPS。依据：[AD9643 数据手册，Digital Output Enable Function](https://www.analog.com/media/en/technical-documentation/data-sheets/AD9643.pdf)（本地 Rev.F p27；官网 Rev.G p26）。

这是需要真实配置并验证的芯片工作模式，不是放宽 DDR 时序约束。对照实现置于 `D:\RelayTools\work\adda_rx\fpga_sdr_candidate`；其首轮条件 STA 为 WNS +0.555 ns、WHS +0.077 ns、TNS=0，尚未上板。用户随后已选择 **先验证 125 MSPS**，故当前主线改为 `D:\RelayTools\work\adda_rx\fpga_125_candidate`：ADC125、双通道 DDR1:8、31.25 MHz 向量，每行4A+4B，4倍抽取后仍31.25 MSPS；两套结果分别记录。
