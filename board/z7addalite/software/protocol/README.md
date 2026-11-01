# 数字帧与 UDP 协议函数

`adda_protocol.c/.h` 为不做 I/O 的 C99 实现，`test_protocol.c` 可独立运行；运行方法见上级板级 README。`test_legacy_compat.c` 仅在显式提供旧 `relay_rf_packet.h` 的 include 目录时编译。

输入帧包含未编码 ASM `1ACFFC1D` 及 128 个卷积编码位，共 160 bit。8 字节正文为版本 1、RX MHz（LE16）、TX MHz（LE16）、seq8、前六字节的 CRC16/CCITT-FALSE（BE16）；频率范围 70–6000 MHz。译码包含全 bit 偏移扫描、最多两个 ASM 错位、极性纠正、64 状态硬判决 Viterbi、解随机化和 CRC。短帧没有尾比特，不能保证任意单比特错误均被恢复。

`ap_rf_packet` 构造既有 26 字节 RF_SET，包含 14 bit 事务序号、RX/TX Hz（BE64）、增益和衰减；ACK 匹配及状态处理仍需调用者执行。解码成功不等于远端已执行。源码测试不验证 ADC、PL、网络或真实板卡。

1 kHz 扩展保持 8 字节正文、160 bit 帧和原 C 结构体布局。版本 `0x81/0xa1/0xa2/0xa3` 分别是改频、开启、停止、查询的旧操作码加 `0x80`。旧 `0x01/0x21/0x22/0x23` 的 MHz 语义和历史 golden 不变。结构体字段 `rx_mhz/tx_mhz` 为兼容保留名称；新版本在线上存放 **kHz 偏移 uint16**，不能直接当作 MHz 使用。

- `0x81/0xa1`：RX LO = 1,979,500,000 + RX偏移 × 1000 Hz，TX LO = 2,169,500,000 + TX偏移 × 1000 Hz；两轴独立取 `100..29900`（含端点）。业务中心比 LO 高 500 kHz，对应 n256 1980..2010 / 2170..2200 MHz 带内、两侧各 100 kHz 固定保护。
- `0xa2/0xa3`：两偏移必须为零，频率换算返回上述基值供既有 UDP 字段通过范围验证；停止/查询不关联或检查当前请求频点。
- `ap_command_validate` 校验版本和相应范围；`ap_command_operation` 返回基础操作码；`ap_command_rx_hz/ap_command_tx_hz` 返回精确 LO Hz，无效命令返回零。编码、解码、ATM2 记录均复用校验器。
- 新改频仍发送旧 26 字节 RF_SET、解析文本 ACK；新控制映射回 UDP `0x21..0x23`，34 字节请求/50 字节 ACK 无需修改 LDSDR。新改频/开启 ACK 容差上限为 10 Hz，旧版保持 10000 Hz；停止/查询不比较频率。

`run_tests.ps1` 包含新四操作的固定正文/帧 golden、边界与 CRC 拒绝、独立频点及相邻 1 kHz、精确 UDP Hz、10 Hz ACK 检查。可选 legacy include 测试还验证原 LDSDR RF_SET 解析器接受新频点的既有 UDP 包。
