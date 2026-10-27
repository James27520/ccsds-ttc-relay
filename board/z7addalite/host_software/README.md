# Z7ADDALite 串口监控

安装本目录 `requirements.txt` 的 PySerial，使用带 Tkinter 的 Python 运行 `adda_monitor.py`。程序可通过环境的 `PYTHONPATH` 找第三方包，无需复制依赖进仓库。

界面启动不枚举或打开串口；连接不自动发送查询或控制命令。默认串口 115200/8N1，打开前关闭 DTR/RTS，不使用流控。断开串口不改变板端 ARM。状态仅依据收到的板端日志显示，UDP 发送尝试与 ACK 确认分开；来源标签不能独立证明 ADC 硬件或捕获元数据有效。界面持久显示`last_decoded`（最近有效解码，不代表已执行）和`last_ack`（最近ACK确认）；这些值来自板端报告，不是PLL遥测，实际频率另以LDSDR独立SPI读回核验。

按钮包括 `status`、`selftest`、`waveformtest`、网络开关、ARM、采集/取消、`decode`、自动采集及 `nettest`。自检使用 SYNTHETIC 来源；实际采集与自动转发需要匹配 PL/PS 固件。网络初始化不等于 PHY 链路可用；频率、SEQ、增益、衰减输入有严格边界校验。真实串口命令按操作者明确点击执行。自动采集固定为normal、A通道、k=0；模式、通道和k下拉框仅用于单次采集。

仓库根目录运行 `python -B -m unittest discover -s board/z7addalite/host_software -p test_monitor.py -v`。测试仅使用 fake 串口与隐藏 Tk 窗口，不枚举、连接或控制真实硬件。测试通过不代表 M2 或端到端链路通过。

完整会话日志可在启动时指定新文件，父目录须已存在，已有文件不会覆盖：

```powershell
python board/z7addalite/host_software/adda_monitor.py --log-file '<已存在目录中的新日志文件>'
```

15项fake单测通过。早期GUI已实测status、selftest、waveformtest、normal/training采集及空输入decode；UART_NETTEST双板控制另经串口命令验证，GUI nettest按钮仍未实测。

2026-10-28实际GUI连接COM10，读取status并启动network/auto。真实ADC_NORMAL指令901/1000 MHz、seq81收到ACK，LDSDR独立SPI读回900999998/1000000000 Hz。GUI停止auto后，发送新的900/1000 MHz、seq83；06:43:20及06:43:42两次status均为decoded=132、applied=9、pending=0、failures=0，auto=ARM=0，SPI保持901/1000 MHz。重新GUI auto on后，seq83被接收并ACK，SPI恢复900000000/1000000000 Hz。本轮共两次成功真实ADC控制事务，没有使用GUI nettest。

最终network/auto/ARM关闭，decoded=180、applied=10、pending=0、failures=0；发送板LO关闭、buffer=0、两路TX衰减89 dB、DDS全零，LDSDR mode=2、TX衰减89 dB。未修改PL/PS或启动介质。结果限当前实物与有线100.5 MHz工作点，业务RF及长期连续运行仍待验收。见 [GUI实板控制摘要](../../../docs/validation/2026-10-28-gui-loop.json) 与 [最新验证记录](../../../docs/validation.md)。
