# 电脑端 GUI、协议和工具审查

日期：2026-10-26。基线：`ccsds-ttc-relay/main`，提交 `132889d8e232d5d7d8e360340aa5e17d7f5abfd8`。本次只读源码，没有启动会访问板卡的 GUI、串口探测、SSH 或射频测试脚本。以下路径相对于克隆仓库；静态发现尚未作为运行故障复现。

## 可复用的现有软件

| 目录/文件 | 已有能力 | 后续使用方式 |
| --- | --- | --- |
| `sw/gui/ccsds_demo_gui.py` | Tkinter 参数编辑、发射帧十六进制、接收参数表、日志，A/B/C 三种演示入口 | 在现有界面上整理设备接口、状态与收发流程，先恢复可运行性 |
| `sw/ccsds/ccsds_tm_tx.py` | TM 组帧/CRC、随机化、卷积编译码、BPSK、SRRC、I/Q 样点生成 | 保留为软件参考与测试向量生成器；新增文本载荷时显式定义布局 |
| `sw/ccsds/tm_params.py` | 32 字节参数区、relay/tm 两组字段、编解码及校验 | 保留字段描述机制；与真实硬件能力核对后定义映射 |
| `sw/link/ccsds.py`、`PROTOCOL.md` | 自定义 Space Packet 格式、APID、RF_SET 等参数编码 | 为旧固件提供明确标记的兼容编码器，不静默改变线格式 |
| `sw/link/payload_ctl.py` | APID 分派到 LDSDR 串口命令，生成应答 | 抽出业务命令模型，新增 UDP 适配时复用已验证的旧 UDP 实现 |
| `sw/link/relay_link.py`、`serial_port.py` | Windows/POSIX 串口、CLI 状态、频移字换算和控制 | 保留调试后端；禁止把自动探测作为纯只读设备发现 |
| `sw/tools/mode_b_link.py` | Linux/IIO 波形上传、收集 I/Q、PC 解码 | 仅作为匹配 Linux/IIO 固件的后端，不能当作 ADDA 网络驱动 |
| `sw/tools/ccsds_mode_b_test.py`、`board_loopback_test.py` | 调制帧过板、单音采集与 FFT 分析方法 | 参数化后用于对应设备的阶段实验 |
| `sw/tools/cmu200_demo.py`、`tx_path_probe.py`、`verify_leakage.py` | 仪器演示、TX 通路探测、泄漏/电缆路径辨识 | 保留为实验工具，记录运行条件和观测点 |
| `sw/tools/verify_relay_net.py` | SSH、Telnet、IIO 等网络探测 | 不是已经实现的 UDP RF_SET 服务，也不提供 ADDA 数据上传 |

已阅读以上 14 个 Python 文件、协议文档，以及 README、LICENSE 和忽略规则。另在本机旧工程找到仓库遗漏的 `fpga_sdr_project/ccsds_ttc_loopback/sw/ttc/loopback_test.py`，检查了其解调接口与固定帧假设；它含旧路径、密钥路径和 108 字节帧假设，需核对后选择性恢复，不能整份直接当作新 GUI 依赖。仓库五张系统说明图已查看，均为说明性框图，并非新增实测证据。

## GUI 不是空白，但尚未适配这次系统

`ccsds_demo_gui.py:31–38` 仍向 `E:\fpga_sdr_project\ccsds_ttc_loopback\sw\ttc` 和 `E:\ccsds_fpga\tools` 添加导入路径。应改成仓库内可安装/可启动的包和配置，而不是在本机复制旧盘符布局。

- 模式 A 是电脑上的调制、信道和解码。较长计算在事件回调中执行，应放到工作线程/进程，主线程负责界面更新。
- 模式 B 调用 `ModeBLink`，通过 PuTTY/SSH、SCP 和 Linux IIO 访问原设备。它需要仓库未提交的 `loopback_test.py`，还有硬编码工具路径、地址和运行参数。工作线程中读取 Tk 控件也应改为由主线程生成一次参数快照。
- 模式 C 在 `:553–567` 仅弹窗说明固定帧 PL 和 ILA 操作，明确不把电脑参数送进 FPGA。不能把这个按钮当作已完成的板上动态收发功能。
- GUI 没有 ADDA 设备后端，没有 ADC 原始数据网络协议，没有持续波形/频谱采集界面。
- `channel()` 接到的样点来自 int16 量化路径，转 float 后再次乘 32767，存在重复幅度缩放风险；修复前应以独立数值向量验证。
- `show_result()` 的 CRC 显示比较接收尾部与发送 CRC，不能代替对接收帧重新计算 CRC；长度和全载荷一致性也要单独判断。

GUI 第一版应清楚显示“软件模拟 / ADDA 实采 / LDSDR 读回”来源。模拟温度、电压和姿态字段不能表现成真实板卡遥测值。断线、等待、拒绝、应用成功和读回成功应有不同状态，成功提示必须能追溯到对应设备应答。

## 三种消息不可混用

| 层/格式 | 当前代码含义 | 集成要求 |
| --- | --- | --- |
| GUI 参数 TM 帧 | 6 字节帧头 + 32 字节参数区 + 2 字节 FECF；参数小端 16 位布局 | 40 字节是传输帧布局，不是旧 RF_SET 命令；文本载荷与控制参数需要类型标记 |
| `sw/link` 自定义 Space Packet | 6 字节包头、可变负载及 CRC，APID 区分业务 | 必须明确包与 TM/TC 帧的封装关系和协议版本 |
| 本机已验证 UDP RF_SET | 固定 26 字节；大端 RX Hz、TX Hz、RX gain、TX attenuation | 继续兼容旧头值、长度值、CRC 和 ASCII 应答；扩展功能用新版本/新命令 |

参数表默认目标频率是 5785 MHz，且只有一个目标频率；旧 RF_SET 是一组 RX LO/TX LO。参数表的发射增益也不等同于 RF_SET 的衰减。更关键的是 `tm_params.py:38` 的模式枚举为“透明/再生/解调再调制/备份”，而 `relay_link.py:35–38` 是“BYPASS/RELAY/MUTE/DUC_ONLY”。直接复制数值会改变含义。

`ccsds.py:38–39` 使用 TC=0、TM=1，且包长度按 payload 长度减一写入、未计尾部 CRC。这是现有自定义兼容格式，不能直接声称是严格 CCSDS Space Packet。CCSDS 133.0-B-2（含勘误）4.1.3.3.2.3 规定 TM=0、TC=1；4.1.3.5 规定长度为整个 Packet Data Field 字节数减一。若 CRC 放在包头之后的该数据域，需计入长度。后续如采用规范格式，必须同时升级生产端、转发/遥控端和黄金向量，旧 RF_SET 保留明确兼容入口。[规范原文](https://ccsds.org/Pubs/133x0b2e2.pdf)

`payload_ctl.py` 当前依靠串口 `lo` 命令设频，并把 Hz 整除成 MHz；成功字符串不是独立 SPI 读回证据。本机 `relay_udp_work` 已有更完整的改频、读回和失败恢复实现，应优先整理进设备适配层。部分解码函数对短报文补零，应用于真实控制前必须拒绝长度错误，不能把缺失字段当成有效零值。

## 第一阶段修改顺序（本轮尚未实施）

1. 恢复包导入和工具配置，补依赖清单；先启动无硬件的 GUI 模式。
2. 固定独立黄金向量，覆盖帧长、CRC、端序、错误类型、参数范围；区分标准格式与旧自定义格式。
3. 抽出设备后端、命令状态和采样记录模型。GUI 不直接拼接 SSH/串口命令。
4. 从 GUI 输入 `helloworld`，先完成离线编码→解码→接收 CRC 重算与逐字节比较；再接 ADDA 的波形缓冲和采集接口。
5. 加入旧 LDSDR UDP 后端以及请求/应答关联、超时、真实读回显示；模式/频率映射经统一接口文档确认。
6. 实板验证以明确连接图、固件哈希、采样率、频点、增益、原始采样和接收内容留证。不能用软件自环替代板间通信。

GUI 先沿用 Tkinter；是否改为 PySide6 取决于后续连续绘图和交互要求，当前没有必要为简单文本首通重写界面。[Tkinter 线程模型](https://docs.python.org/3/library/tkinter.html#threading-model)可作为后台任务与事件队列设计依据。
