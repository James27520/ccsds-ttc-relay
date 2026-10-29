# LDSDR 有限租期远端转发固件

本目录实现 `docs/remote-relay-control.md` 的 34 字节命令、50 字节二进制 ACK，
沿用 `169.254.9.10:5005`。这是在已验证 RX0/TX1 fixed 修正版上的独立 RAM 构建；
不改动原 `board/ldsdr/rebuild.py`、补丁、哈希清单或冻结外部基线。

`relay_remote_packet.h` 负责严格长度、APID、版本、保留位、CRC 和范围检查。
`relay_remote_control.h` 管理单调序号、重复/冲突、64 位板端租期及故障锁存。
`relay_remote_board.h` 对接实际 PL mode、SPI-backed 双路增益/衰减/LO 回读和有限 UART 命令。
`relay_remote_udp.h` 保留旧 RF_SET 分发，且格式错误的新命令不会进入旧命令执行路径。

开启不调谐 LO，要求实际 LO 与请求相差不超过 10 kHz，并核对双路电平及 mode。
所有关断路径先写 PL mode2，再尽力写两路 89000 mdB 和增益0，并核对读回。
任一操作或读回失败锁存故障，本次启动内禁止再次开启。重复包不重执行、不续租；
曾成功开启后到期/取消的最近同包请求返回 -6。失败开启的同包重发保留原失败返回码。
历史到期 bit2 是粘滞标记，可与后来有效租期 bit1 并存；fault bit3 禁止开启。

旧 RF_SET 执行前取消租期并完成安全静音，随后保留其请求频率/增益/衰减设置，
最终仍强制 mode2；失败则完整安全关断并锁存。旧 26 字节格式及文本 ACK 保留。
UART 只接受 `status`/`r`、`rfdiag`、`help`/`?`、`stop`/`mode 2`/`txatt 89`/`rxgain 0`。
后三个兼容静音命令均执行完整安全关断；所有其他写命令明确拒绝。
`status` 保留原 STAT 行并附实际回读快照，`rfdiag` 保留原独立只读诊断文本。

每轮 UART 最多接收16字节、执行一个命令；bare-metal 的 hash-pinned GEM input 每轮最多
处理一个包。主循环在 UART/网络处理前后检查截止，接收和状态回报也检查截止。
这是有界协作轮询实现；未增加独立硬件 watchdog，也未声称可以在 CPU 停止或外设卡死时按时关断。

## 离线重建

Python 标准库、原 hash-pinned 完整 UDP 缓存、ARM hard-float GCC 和 native GCC 必需。
所有产物写入新的外部目录；已有输出、基线或源码目录一律拒绝。构建首先通过原入口重建
`fixed_reference` 并验证全部原检查，再复制并叠加远控源码，验证新镜像。
不会调用串口、JTAG、网络、下载、SD/Flash 操作或 Git。

```powershell
python -B board/ldsdr/remote_control/rebuild.py `
  --base D:/RelayTools/work/relay_udp2026 `
  --out D:/RelayTools/work/remote_relay_20261029/ldsdr_relocated02 `
  --host-cc D:/AMDDesignTools/2026.1/tps/mingw/10.0.0/win64.o/nt/bin/gcc.exe
```

上例输出已存在，复现时给 `--out` 一个新的名称。ARM 编译器默认来自基线 manifest，
也可指定 `--compiler`。输出包括源文件、编译命令/日志、测试结果、ELF/map/反汇编及
`build_manifest.json`、`offline_verification.json`。不把二进制或大 obj 放入主仓库。

## 已完成的离线验证

`ldsdr_relocated02/relay_remote.elf` SHA256：

```text
fab74c01703e37b99d46e4e4251a28b1835742f07285b67f49c2c64530ba90af
```

12组协议/状态机故障测试、5组板适配测试、22项源码/布局检查全部通过。
覆盖逐字节 CRC 损坏、范围、序号冲突/过期/不回卷、失败事务消费序号、重复不续租、
准确到期边界、查询不续租、取消后重发、每个开启写步骤故障、回读/双路不符、
静音失败锁存、读取跨截止点、32位 uptime 回卷、counter-only SPI 故障、CLI 洪泛预算及旧 RF_SET。
原 fixed 入口的6组故障测试及全部原布局/LOAD载荷检查也通过。

新链接窗口为 `0x04800000..0x04bfffff`，entry `0x04800000`，
MMUTable `0x04828000`，末端栈 `0x04b9b530`。
三个 LOAD 分别从 `0x04800000`、`0x04828000`、`0x04900000` 开始，
末段内存结束 `0x04b9b530`，不覆盖旧 fixed 的 `0x04000000..0x043fffff` 窗口。
BSP DDR 范围及新窗口的 identity 页表映射已离线验证。
继承的驱动格式警告、未使用参数/部分初始化警告及 RWX LOAD 警告记录在日志中。

离线检查不代替加载前的精确目标 TTBR、活动页表及内存占用核验，也不代替缓存/中断处理。
早先 `ldsdr/` 试构建使用旧 `0x04000000` 窗口，已被 relocated02 替代。
本轮在外部台架脚本中核对旧活动页表后，已将 relocated02 临时加载到 RAM，
真实 UDP 启停、双路状态回读及十秒超时静音通过，见[实板记录](../../../docs/remote-relay-validation.md)。
后续真实ADC_NORMAL查询、开启、停止及DAC状态回报也已通过；另行接回业务线后，两段文本实收、主动停止负例及当前工作点削顶零增量通过，见同一实板记录。两阶段不是并发验收。
运行新镜像时活动页表也位于新窗口，不能无条件重复同地址暖加载。
