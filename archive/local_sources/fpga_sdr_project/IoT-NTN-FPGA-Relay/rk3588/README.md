# RK3588 载荷控制链路（CCSDS 简化版）

把地面/信关的遥控指令翻译成载荷参数，并回读遥测。

```
 ┌───────────┐  CCSDS 空间包   ┌─────────────────┐  ASCII CLI   ┌──────────┐
 │ 信关 /    │ ──────────────► │  RK3588         │ ───────────► │  LDSDR   │
 │ 另一个SDR │                 │  payload_ctl.py │              │  载荷    │
 │ 解出的    │ ◄────────────── │                 │ ◄─────────── │          │
 └───────────┘   遥测空间包     └─────────────────┘   STAT 行     └──────────┘
                                         │
                                    USB (FT4232 串口通道)
```

## 零依赖

全部只用 Python 标准库。PC 和 RK3588 上都能直接跑，**不需要 pyserial**。

- Linux → `termios` + `select`
- Windows → `ctypes` 调 `kernel32`

---

## 文件

| 文件 | 作用 |
|---|---|
| `ccsds.py` | CCSDS 空间包编解码、CRC-16/CCITT、流式同步解码器 |
| `serial_port.py` | 跨平台串口（Linux termios / Windows ctypes） |
| `relay_link.py` | 载荷串口命令行协议的 Python 封装 + 频率字换算 |
| `payload_ctl.py` | 主控制台：CCSDS ↔ 载荷命令，命令行工具 |
| `PROTOCOL.md` | 协议规范（APID 分配表、数据域编码） |

---

## 快速开始

### 1. 先跑离线演示（不需要硬件）

```bash
python3 payload_ctl.py demo
```

它会：构造 7 个遥控包 → 拼字节流（故意插垃圾检验同步）→ 流式解码 → 
逐条执行（干跑）→ 生成遥测回包 → 检验 CRC 单比特检错。

期望输出 `全部通过。CCSDS 打包/解码/执行链路可用。`

### 2. 接上载荷

把 LDSDR 的 USB 插到 RK3588（或 PC）上，先确认串口：

```bash
python3 serial_port.py            # 列出串口并逐个探测
# 输出示例： 可用串口: /dev/ttyUSB0, /dev/ttyUSB1, /dev/ttyUSB2
```

自动检测载荷串口：

```bash
python3 relay_link.py             # 会打印"自动检测到: /dev/ttyUSB1"
```

### 3. 常用命令

```bash
# 读状态
python3 payload_ctl.py status

# 切模式
python3 payload_ctl.py mode relay          # bypass / relay / mute / duc_only

# 频偏（Hz）
python3 payload_ctl.py offset 100000       # DUC +100 kHz
python3 payload_ctl.py offset -100000      # DUC −100 kHz
python3 payload_ctl.py offset 100000 -50000   # DUC +100k, DDC −50k

# 数字增益（Q1.11，0x800 = 1.0）
python3 payload_ctl.py gain 0x800 --dc 1

# 射频参数
python3 payload_ctl.py rf 900 1000 20 30   # rxlo txlo rxgain txatt

# 持续监视（丢样自动标红）
python3 payload_ctl.py watch
```

指定串口：`--port /dev/ttyUSB1`（默认自动检测）。
干跑不连硬件：`--dry-run`。

### 4. 走 CCSDS 二进制包

```bash
# 生成一个包到文件
python3 payload_ctl.py mkpkt offset 100000 --out off.bin

# 执行包文件（可含多个包，中间允许有垃圾字节）
python3 payload_ctl.py exec --file off.bin
```

在自己的 RK3588 程序里调用：

```python
from payload_ctl import mk_offset, mk_req_status, Dispatcher
from relay_link import RelayLink

with RelayLink.autodetect() as link:
    disp = Dispatcher(link)
    disp.execute(mk_offset(100_000))          # 下发 +100 kHz
    tm = disp.execute(mk_req_status())        # 取状态遥测
    print(tm.payload.hex(" "))
```

---

## 自动检测是怎么做的

打开串口本身从不失败（端口存在就能打开），所以必须靠**板子应答**才能确认：

探测时发 `auto 0` 再发 `status`，收到含 `STAT` 的回行才算找到载荷。

⚠️ 如果串口打开成功但收不到 `STAT`，最常见的原因是**板子从 SD 卡启动了原厂 Pluto Linux** ——
那时串口上会出现 `pluto login:` 之类的提示。处理办法是重新下载转发程序，或拔掉 SD 卡。

---

## 已知限制

| 限制 | 说明 |
|---|---|
| 波特率 115200 | 当前固件固定。想提速需改 PS 的 UART 配置并重新编译。115200 下 CLI 足够，但**不适合传 IQ 数据**。 |
| 同一时间只能一方占用串口 | GUI、本工具、串口终端不能同时开。 |
| USB 同时承载 JTAG | LDSDR 的 USB 插到 RK3588 后，PC 就不能再 JTAG 了。部署时这不是问题（有 BOOT.bin 自启动）；开发时请插回 PC。 |
| 数据面不经此链路 | 转发样点全在 PL 内闭环，**不经过本工具**。这里只走参数和状态。 |
