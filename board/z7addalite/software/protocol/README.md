# 数字帧与 UDP 协议函数

`adda_protocol.c/.h` 为不做 I/O 的 C99 实现，`test_protocol.c` 可独立运行；运行方法见上级板级 README。`test_legacy_compat.c` 仅在显式提供旧 `relay_rf_packet.h` 的 include 目录时编译。

输入帧包含未编码 ASM `1ACFFC1D` 及 128 个卷积编码位，共 160 bit。8 字节正文为版本 1、RX MHz（LE16）、TX MHz（LE16）、seq8、前六字节的 CRC16/CCITT-FALSE（BE16）；频率范围 70–6000 MHz。译码包含全 bit 偏移扫描、最多两个 ASM 错位、极性纠正、64 状态硬判决 Viterbi、解随机化和 CRC。短帧没有尾比特，不能保证任意单比特错误均被恢复。

`ap_rf_packet` 构造既有 26 字节 RF_SET，包含 14 bit 事务序号、RX/TX Hz（BE64）、增益和衰减；ACK 匹配及状态处理仍需调用者执行。解码成功不等于远端已执行。源码测试不验证 ADC、PL、网络或真实板卡。
