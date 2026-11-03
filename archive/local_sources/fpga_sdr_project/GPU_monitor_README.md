# RK3588 GPU 频谱检测原型

固定链路：CMU RF2 发射 900.100 MHz → SDR RX1；接收中心 900 MHz。
本程序只接收，不发送，也不改变之前转发程序。

把 `gpu_spectrum_monitor.py` 和已有的 `sdr_spectrum_tk.py` 放在 3588 同一目录。
后者仅用于自动发现 USB SDR，不会启动窗口。

## 安装到独立环境

```bash
sudo apt install python3-venv ocl-icd-opencl-dev
python3 -m venv --system-site-packages ~/gpu-sdr-env
~/gpu-sdr-env/bin/python -m pip install pyopencl
```

不要 sudo pip，不要替换现有 Mali 驱动。若安装失败，保留完整错误。
环境可访问原 Python 的系统/用户包；若 adi/iio 导入失败，需要检查实际包路径和版本，
不要盲目升级已正常使用的 libiio。

## GPU 验证

```bash
~/gpu-sdr-env/bin/python ~/gpu_spectrum_monitor.py check
```

确认列出的 GPU 是 Mali-G610。程序不回退 CPU。
FFT 结果相对误差阈值 2e-4，验证失败直接停止。
输出 GPU 核函数耗时、总耗时中位数/P95、NumPy 参考耗时。
4096 点、50% 重叠、8帧批次对应 6.5536 ms 的稳态批次间隔。
首次8帧需要7.3728 ms输入。处理延迟还需加缓冲/USB等开销。
总 GPU 时间低于6.5536 ms只是必要预算检查，不证明实时无丢样。
NumPy参考不是优化后的CPU性能上限。当前radix-2内核用于可验证原型，后续可换优化FFT库。

## 接收监测

关闭其他 SDR 程序，断开 TX 回传线，仅保留 CMU RF2 → SDR RX1。

```bash
~/gpu-sdr-env/bin/python ~/gpu_spectrum_monitor.py live --seconds 120
```

先按提示关闭 CMU RF OUTPUT（不必关仪器），回车采集3秒噪声基线。
再按提示开启900.100 MHz信号，回车开始检测。
不要在检测中途改SDR增益；改增益需要重新采集基线。

默认允许带900.075–900.125 MHz；有效监测区域约899.4–900.6 MHz，
忽略中心±3kHz，避免把残余直流误判。带外异常指规则外能量，不是法律判断。
25kHz检测区域按频点离散化；允许带边界拆分统计。
区域总功率超过噪声基线10dB时视作候选占用，连续3帧越界告警，10帧无越界清除。
帧重叠使各帧并非独立统计试验；门限需按实测误报率/漏检率调整。

测试：900.100 MHz时允许带内有占用；关闭源占用应下降；
保持幅度把CMU源改900.200 MHz时应出现越界候选；恢复900.100 MHz后应解除。
不自动控制SDR发射。接收源过弱、窗泄漏、漂移、噪声基线变化都会影响判别。

输出到运行目录 `gpu_monitor_output`：
- benchmark.json：实际GPU和性能结果。
- baseline.npz：基线频谱与增益。
- detections.jsonl：逐批检测、样点编号、处理耗时。
- spectrum_latest.csv：最近一批平均PSD，单位数字counts平方/Hz，非dBm。

当前为同步接收/计算的原型。打印的delivered速率和软件样点编号不证明硬件无丢样；
若处理速度不足，会有采样丢失风险。后续接独立接收队列、GPU双缓冲和溢出监测。
连续全链路转发仍需另行验证；自动阻断需对原始IQ延迟缓冲并绑定检测结果。
