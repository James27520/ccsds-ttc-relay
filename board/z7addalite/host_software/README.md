# Z7ADDALite 串口监控

安装本目录 `requirements.txt` 的 PySerial，使用带 Tkinter 的 Python 运行 `adda_monitor.py`。程序可通过环境的 `PYTHONPATH` 找第三方包，无需复制依赖进仓库。

界面启动不枚举或打开串口；连接不自动发送查询或控制命令。默认串口 115200/8N1，打开前关闭 DTR/RTS，不使用流控。断开串口不改变板端 ARM。状态仅依据收到的板端日志显示，UDP 发送尝试与 ACK 确认分开；来源标签不能独立证明 ADC 硬件或捕获元数据有效。

按钮包括 `status`、`selftest`、`waveformtest`、网络开关、ARM、采集/取消、`decode`、自动采集及 `nettest`。自检使用 SYNTHETIC 来源；实际采集与自动转发需要匹配 PL/PS 固件。网络初始化不等于 PHY 链路可用；频率、SEQ、增益、衰减输入有严格边界校验。真实串口命令按操作者明确点击执行。

仓库根目录运行 `python -B -m unittest discover -s board/z7addalite/host_software -p test_monitor.py -v`。测试仅使用 fake 串口与隐藏 Tk 窗口，不枚举、连接或控制真实硬件。测试通过不代表 M2 或端到端链路通过。

实际串口已在最终r4c固件验证status、selftest、waveformtest、normal采集、空输入decode及training采集，来源与就绪状态显示正确，未发送RF_SET。10项fake测试继续覆盖离线行为。全通道内部快照另经板端与独立DDR检查通过；真实中频输入及UDP闭环仍待验收。见 [最新验证记录](../../../docs/validation.md)。
