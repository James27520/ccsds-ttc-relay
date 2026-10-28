# TM1 测控状态回传

TM1 是 Z7ADDALite PS 的只读管理状态帧，通过现有 DEBUG USB 串口返回电脑。它用于区分最近解码、UDP 尝试发送和匹配成功 ACK，供演示与问题定位；不是 CCSDS 标准遥测帧，也不代表六线计划中的 DAC/SMA 射频下行已完成。

## 查询与格式

115200 波特串口发送 `telemetry` 加 CRLF。支持该版本的 PS 返回一行 `TM1 ... crc16=HHHH`，随后返回 `CLI_RESULT rc=0`。旧固件不支持时，桌面端明确报错，不用其他日志拼装成功状态。`status` 原接口保持不变。

字段为固定顺序的十进制整数，以一个 ASCII 空格分隔；无缺省字段。最大缓冲区为 1024 字节，包含 CRLF 和 C 字符串结束符。CRC16/CCITT-FALSE：poly=0x1021、init=0xFFFF、无反射、xorout=0；范围从 `TM1` 的 T 到 `spi_valid=0` 的最后一个 0，不包含其后空格、`crc16=` 和 CRLF。CRC 使用四位大写十六进制。主机在版本、长度、字段顺序、整数范围及 CRC 全部正确后才更新界面。

| 顺序 | 字段 | 含义 |
| --- | --- | --- |
| 1 | `uptime_ms events network armed pending decoded applied failures` | PS 毫秒时间、记录事件计数、网络/ARM/待确认标志、解码/成功应用/失败事务计数 |
| 2 | `d_valid d_event d_origin d_air_seq d_rx_mhz d_tx_mhz` | 最近一条通过正文校验并交给控制层的解码记录；不等于已经发送或应用 |
| 3 | `s_valid s_event s_origin s_air_seq s_rx_mhz s_tx_mhz s_udp_seq s_count s_rc` | 最近一次 UDP 发送尝试，包含事务序号、该事务的累计发送次数（包括首次）和本地发送返回码 |
| 4 | `a_valid a_event a_origin a_air_seq a_rx_mhz a_tx_mhz a_udp_seq a_rc a_rx_hz a_tx_hz` | 最近匹配成功 ACK 的指令、事务序号、返回码与 ACK 报告频率 |
| 5 | `spi_valid` | 当前恒为 0；遥控板本身没有独立读取转发板 SPI 的证据 |
| 6 | `crc16` | 上述完整前缀的 CRC |

`origin`：0=UNKNOWN，1=ADC_NORMAL，2=ADC_TEST，3=SYNTHETIC，4=UART_NETTEST。每组 `valid=0` 时其余值没有有效记录含义；不要把初始化的零解释成零频率指令。`d/s/a` 分别保留，可能属于不同事件，必须按来源、空口序号、事务序号和事件号关联，不能按一行中的位置推断三者对应同一条指令。

## 更新与保持规则

- 通过正文校验的解码调用更新 `d_*`；测试来源仍受既有门控约束，不自动产生 RF_SET。
- 每次实际调用 UDP 发送更新 `s_*`。发送返回码为 0 仅表示本地发送函数成功，不能代替远端 ACK。
- 只有地址、端口、报文、事务序号、返回码和频率匹配成功的 ACK 更新 `a_*` 与 applied。错误、过期或不匹配 ACK 不覆盖之前的成功记录；pending/failures 仍反映当前事务结果。
- `telemetry` 查询没有 ARM、网络、RF 或发送副作用。关网络会保留历史成功 ACK；用户断开监控不会清空 PS 状态。
- PS 复位重新初始化全部记录。时间及事件计数为 32 位，毫秒时间约 49.7 天回绕；该版本没有跨重启唯一标识，不能只凭计数识别同一运行周期。
- `selftest` / `waveformtest` 使用本地测试向量，不调用解码接收记录或 UDP 事务入口，因此不伪造最近真实解码记录。

独立 SPI 读回来自桌面发送控制器已持有的 LDSDR 串口，经 `status` / `rfdiag` 返回；使用独立时间戳和单独卡片。它不写入 TM1，也不随新 ACK 自动刷新。该诊断若发现错误，沿业务控制器既有安全停止流程处理，不保持未经确认的发射状态。

## 界面与验证边界

发送端点击“测控状态”，选择遥控板 DEBUG 串口，点击“连接监控”。每 2 秒查询一次；超过 6 秒、断连或查询出错的值明确标为历史。最近 ACK 表示上次成功确认的状态，不保证设备在其后没有被另一入口修改。

主机单元测试覆盖坏 CRC、截断、未知版本、乱序/重复字段、越界、只读命令限制、串口重连与关闭异常。C 测试覆盖记录来源、重试、错误/过期 ACK、边界格式化及独立 CRC 向量。初始化且 `uptime_ms=123`、其余字段为零的完整前缀 CRC 为 `F8E2`。

USB状态阶段的实板证据见[提速与状态回传验收](station-speed-telemetry-validation.md)。该阶段的两根SMA都在业务链，遥控板没有SMA输入或输出；UART_NETTEST与USB TM1结果不能替代ADC_NORMAL遥控输入或DAC射频回传验收。后续新增第三根SMA的DAC实际接收结果单独记录于[测控下行实收](telemetry-rf-validation.md)，不改变本协议的USB管理路径含义。
