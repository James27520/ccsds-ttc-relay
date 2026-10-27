# 遥控板 M2 最小快照 ABI 提案

2026-10-27。状态：ABI v1 已按主任务、C/R 审查意见冻结；实现/BD/实板验收仍待完成。工程仅在 `telecontrol_system` 中实现，`fpga_125_candidate` 的 M1 源与报告保持冻结。

已对齐 `ps_software/adda_ps_core.h` 的 `aps_decode_samples()`：PS 适配器先验证本 ABI 的冻结快照，再复制 131072 个 int16 到 DDR；只有 normal 模式真实读回通过、元数据完整且无捕获错误，才允许使用 `APS_ADC_NORMAL`。图样捕获始终为 `APS_ADC_TEST`。平台提供现有 `aps_io.log/udp_send`，不改解调核心。R 已确认尚无另一套 capture/MMIO ABI。

## 固定硬件与内存合同

- ADC 双通道各标称 125 MSPS，DDR 1:8，31.25 MHz 向量含 4A+4B；固定通道与时间位置 k=0..3，每向量选一个样点，总抽取 4，输出标称 31.25 MSPS。
- 14 bit 二补码符号扩展到 int16，不左移；小端。32 bit RAM 字低半字是先到样点，高半字是后到样点。每快照固定 131072 样点、65536 字、262144 字节。
- 控制基址候选 `0x43C00000`，64 KiB aperture；BRAM `0x44000000..0x4403FFFF`，256 KiB。须由新 BD 验证地址无重叠，再从同一 JSON 生成 C/Verilog 常量。这里不是旧 BSP 的地址。
- 全部 MMIO 为对齐 32 bit；控制写仅接受 WSTRB=1111，其他写响应 SLVERR 且不动作；未定义地址/写只读寄存器响应 SLVERR。AXI BRAM 映射在 PS 中按非缓存 Device/Strongly-ordered 配置。读取快照前后核验状态/epoch，并使用平台内存屏障。
- 单一缓冲：DONE/FAILED 后 RAM 和全部 SNAPSHOT 字段保持到 RELEASE。ARM 不自动释放上一个快照；busy/DONE/FAILED 时的 ARM 拒绝且不改变 RAM 或快照。

## 寄存器（32 bit；字段未定义位读零、写须零）

| Offset | 名称 / 访问 | 定义 |
|---:|---|---|
| 00 | MAGIC / RO | `0x54434C31`，遥控板 capture v1 身份 |
| 04 | ABI_VERSION / RO | `0x00010000`；冻结前仍为提案 |
| 08 | COMMAND / WO | 单次完整字写；1 ARM，2 RELEASE，3 APPLY_MODE，4 ABORT。一次只执行一个命令 |
| 0C | STATUS / RO | [3:0] phase；bit4 ADC_verified，5 training_valid，6 stream_valid，7 clock_alive；8 config_busy，9 capture_error；其余零 |
| 10 | LAST_COMMAND_RESULT / RO | 每次 COMMAND 更新：0 accepted，1 invalid_command，2 bad_state/busy，3 bad_argument，4 not_verified，5 not_trained，6 clock_unavailable。拒绝不破坏正在冻结的快照 |
| 14 | CAPTURE_ERROR / RO | 0 无；1 abort，2 FIFO overflow，3 source clock timeout，4 config/stream invalidated，5 FIFO epoch mismatch，6 bad last/count，7 arm handshake timeout。只在捕获 FAILED 时有效，RELEASE 清零 |
| 18 | REQUEST_EPOCH / RW | 仅 IDLE 可写；ARM 原子锁存，非零且不可与上次成功接受的 epoch 相同。32 bit 回绕由 PS 跳过零 |
| 1C | REQUEST_SELECT / RW | 仅 IDLE 可写；bit0 channel A=0/B=1，[2:1] k=0..3。parity 不是由软件随意声明的字段 |
| 20 | SNAPSHOT_EPOCH / RO | 接受 ARM 后锁存编号；只有 DONE 且 error=0 可消费为成功快照 |
| 24 | SNAPSHOT_SELECT / RO | ARM 锁存 channel/k，[8] 实测 A 所在 parity（word0 为 A=0、word1 为 A=1）；其余零 |
| 28 | SAMPLE_COUNT / RO | 固定 131072；ABI v1 不开放可变长度 |
| 2C | SAMPLES_WRITTEN / RO | 全局 clk25 域实际 RAM 写入完成字数×2，至少 18 bit；DONE 应等于 131072；失败时冻结已提交的偶数样点数 |
| 30 | SAMPLE_FORMAT / RO | 固定 `0x00010E10`：格式 v1 / source14 / container16；定义同时包含二补码符号扩展、无移位、小端、低半字较早 |
| 34 | ADC_RATE_HZ / RO | 125000000，标称配置而非计量值 |
| 38 | OUTPUT_RATE_HZ / RO | 31250000，标称配置而非计量值 |
| 3C | CAPTURE_BYTES / RO | 262144 |
| 40 | REQUEST_MODE / RW | 仅 IDLE 可写；0 NORMAL（A0D=00/B0D=00），1 TRAINING（测试码由本构建训练算法指定并在原始诊断中发布）；启动默认 TRAINING |
| 44 | ACTIVE_MODE / RO | 0/1；bit31 valid。只有对应 ADC 寄存器读回全通过才置 valid |
| 48 | CONFIG_EPOCH / RO | 每次配置尝试完成后均自增（包括失败），跳过零；与 diag/valid 原子发布，包括启动配置 |
| 4C | SNAPSHOT_CONFIG_EPOCH / RO | ARM 时锁存 CONFIG_EPOCH |
| 50 | SNAPSHOT_FLAGS / RO | bit0 normal_verified，1 training_verified，2 training_valid，3 clock_alive_at_arm，4 capture_success（仅 DONE 置1）；模式位最多一个置1。失败永不置 capture_success |
| 54 | TRAINING_STATUS / RO | bit0 valid，bit1 A parity，bit2 failed，[15:8] 训练算法编号（0 未定/无，1 PN9），bits[31:16] 已连续通过图样向量数（饱和）。训练结果由接收逻辑产生，不由 PS 寄存器写入 |
| 58..64 | LIVE_DIAG0..3 / RO | 最新完成的原始读回 bundle，低字在低地址；112 bit 沿用 M1 顺序，最高16 bit零。config_busy=0、读取前后 CONFIG_EPOCH 一致时可作为稳定 bundle |
| 68..74 | SNAPSHOT_DIAG0..3 / RO | ARM 时冻结 LIVE_DIAG，用于捕获来源审计；normal/test 的 0D 读值随模式更新，不能一直套用 M1 常量 |
| 78 | FRAMEWORK_BUILD_ID / RO | JSON/源码签核时分配的构建标识，用于日志绑定；不代替 SHA256 manifest |

Phase：0 IDLE，1 ARMING（等待源域接受），2 CAPTURING，3 DRAINING（源已结束、FIFO/RAM尚未完成），4 DONE，5 FAILED，6 CONFIGURING，7 RELEASING。IDLE 不等于可 ARM，仍须 verified/trained/clock/stream 均有效。APPLY_MODE 只允许 IDLE；ARM 只允许 IDLE 且 REQUEST_MODE 已成为有效 ACTIVE_MODE。ABORT 仅作用于 ARMING/CAPTURING/DRAINING，转 FAILED；RELEASE 仅作用于 DONE/FAILED，先进入 RELEASING，源停止确认并清理旧 FIFO 项后才回 IDLE；不修改 ADC 配置、parity、FIFO 源时钟。若源时钟已停止则不得伪造已清理，可保持失败等待重新初始化。

COMMAND 按 AXI 写提交顺序处理。参数写入到命令之间必须加 PS 屏障。接受 ARM 时同时冻结 epoch/select/config_epoch/mode/readback；直到 RELEASE，参数/模式命令一律拒绝。配置变化与捕获不会并发。BRAM Port B 仅软件读取（首版不提供 PS 写测试模式，避免把软件数据混为 ADC 来源）。

## 训练和模式切换

M1 的一次实板 parity 不能直接硬编码为新 M2 位流每次上电的 parity。M2 在 CLKDIV 域检查两个 parity 候选，仅一个候选连续通过 128 向量才锁存 training_valid/parity；失败保持不可 ARM，并在 ILA/状态提供原始向量。训练检查为独立模块，不做自动 BITSLIP，不掩盖 lane 错位。

2026-10-27 实板观察到 M1 A ramp 每码重复两次递减，B checker 严格交替。ADI 员工在 [AD9643 test modes](https://ez.analog.com/data_converters/high-speed_adcs/f/q-a/21871/ad9643-test-modes) 解释数字图样递减正常，却对相同重复现象建议排查采样时序；因此不能仅放宽 ramp 条件就判正确。主任务正在独立 PN9 诊断，M2 训练比较器将在真实序列验证后采用相应算法，暂不实现未经验证的 +1/-1 规则。此项不改变 ABI 字段，只决定 TRAINING_STATUS.algorithm 和 TRAINING 模式读回值。

APPLY_MODE 只更改 local 0D 与 FF transfer，分别选择 A/B 写入并读回；保持 DCO、BUFR 和 ISERDES 连续，不以 config_done 下降重置解串器。开始切换撤销 stream_valid，读回成功且丢弃 32 个 CLKDIV 向量后恢复。训练到 normal 的成功切换保留同一 framing 的 parity；若时钟停止、系统复位、IDELAY ready 丢失，撤销 training_valid，必须重新完整启动/训练。运行时请求 TRAINING 要重新验证 128 向量。失败 APPLY_MODE 原子发布失败诊断、增加 CONFIG_EPOCH、清除 ACTIVE_MODE.valid/stream_valid/training_valid 并回 IDLE；后续只允许重新 APPLY_MODE(TRAINING)，normal 请求在未训练时拒绝。模式读回应同时检查 M1 已有 10 项格式/时钟/索引字段，不仅检查 0D。

## CDC、完成条件与故障

源域只保留选择、训练、小计数、32 bit 两样点打包和异步 FIFO。每 FIFO 项建议携带 {last, epoch[31:0], data[31:0]}，宽 65、深 1024；入 FIFO 的两个样点必须属于同一 ARM。clk25 域持续接收并验证 epoch，写 65536 次 BRAM 后才置 DONE；最后标记和计数不一致即 FAILED。done 不从源域“采够”标志直接生成。

ARM/STOP/源完成通过 toggle+稳定 bundle 握手，BUSY 期间 bundle 保持；跨域错误由锁存事件握手，不直接读取变化中的多 bit 计数。全局 clk25 heartbeat watchdog 监测 DCO 活动；超时应锁存失效、阻止成功并要求重新训练。FIFO 复位需在 source/read 两个域均等待 XPM reset-busy 结束，不能在已停止的源时钟下声称重置完成。下一 ARM 需确认旧 epoch 的数据已清理且握手回到空闲，不能仅清 RAM 写地址。

## 第一版验收边界

先完成 PS7/GP0/AXI-Lite/BRAM 和纯数字捕获仿真，再在已验证 M1 输入时序上整合。训练样点的抽取验收以最终获证实的原始序列按 k/4 抽取为黄金参考，不再把 ramp +4 当预设；B checker 应为单个固定 2AAA 或1555，切相邻 k 应换值。验证连续多次 epoch、busy 命令拒绝、快照冻结、abort、overflow、停源时钟、最后一个 FIFO 字延迟、配置无效和正常模式读回。PS 读取前后 DONE/epoch/config_epoch/flags 必须一致，数据复制到 DDR 后才能 RELEASE。

本提案未证明模拟信号接收、解调、网络或时延；PS7 配置沿用 ADDA 厂商 Linux BD 的实际 DDR/UART/ENET0 引脚，并新增 GP0。不得使用 LDSDR BSP、不得假定已有 Linux。


冻结后的功能字义/地址/格式变化必须增加 ABI_VERSION；构建标识变化不改变 ABI。BD 地址目前仍待最终验证，最终 XSA 必须与这里一致，否则重新冻结地址。
