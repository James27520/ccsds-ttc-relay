# CCSDS 遥测 · 双板环回验证工程

在 FPGA-SDR 卫星转发器平台上，验证 **CCSDS 遥测下行链路** 从软件编码到真实射频、
再经转发板中继、最后解调译码的完整闭环。

## 硬件

| 板子 | 主芯片 | 射频 | 角色 |
|---|---|---|---|
| **遥测板** | Zynq-7010 | AD9363 | CCSDS 发射 / 接收（stock PlutoSDR 固件 + libiio） |
| **转发板** | Zynq-7010 | AD9363 (2R2T) | 双通道透明转发（PL 实现，本工程用作中继） |

## 链路

```
Python 生成 TM 传输帧 (CCSDS 132.0-B)
    ↓ CRC-16 FECF
    ↓ 伪随机化
    ↓ 卷积编码 (7,1/2)
    ↓ ASM 插入 (0x1ACFFC1D)
    ↓ BPSK 映射 + SRRC 成形
    ↓ +200 kHz 中频
遥测板 TX1 ──1000.2 MHz──► 转发板 RX1 (RX_LO=1000)
                              ↓ 基带 +200 kHz
                           转发板 TX1 (TX_LO=1000)
                              ↓ 1000.2 MHz
遥测板 RX1 ◄──────────────────┘
    ↓ iio_readdev 抓回电脑
    ↓ 自动频偏搜索 → 下变频
    ↓ SRRC 匹配滤波 → 符号定时恢复
    ↓ ASM 搜索 → Viterbi 译码
    ↓ 解随机化 → 解传输帧
    ↓ CRC-16 校验
✅ 8 个帧，逐字节一致
```

## 目录

```
ccsds_ttc_loopback/
├── README.md
├── docs/         报告
├── sw/
│   ├── ttc/      遥测板侧：CCSDS 编解码 + 板子控制
│   └── relay/    转发板侧：双通道验证 + 构建/烧录脚本
├── fw/           转发板 PL 源码（relay_*.v）
├── data/         实测数据
└── figs/         报告插图
```

## 快速开始

```powershell
# 协议链软件自检（不需要硬件）
python sw\ttc\ccsds_tm_tx.py selftest

# 接收链自检（SNR 10 dB 仍可解）
python sw\ttc\test_rx_chain.py

# 双板安全配置
python sw\ttc\arm_loopback.py

# 链路通断诊断（约 20 秒）
python sw\ttc\diag_link.py

# 自动频偏搜索解码
python sw\ttc\auto_decode.py
```

## 关键参数

| 参数 | 值 |
|---|---|
| 采样率 | 2.5 MSPS |
| 符号率 | 250 ksym/s |
| 过采样比 | 10 |
| 中频 | +200 kHz |
| 调制 | BPSK |
| 成形滤波 | SRRC, β=0.35 |
| 信道编码 | 卷积 (7,1/2), G1=0x79, G2=0x5B |
| 随机化 | LFSR h(x)=x⁸+x⁷+x⁵+x³+1, 初值 0xFF |
| 同步字 | 0x1ACFFC1D |
| 帧结构 | 6 字节主头 + 数据 + 2 字节 CRC-16 |

## 电平预算（代替物理衰减器）

| 环节 | 电平 | 对端耐压 | 余量 |
|---|---|---|---|
| 遥测板 TX → 转发板 RX | −23 dBm | +2.5 dBm | 25 dB |
| 转发板 TX → 遥测板 RX | −53 dBm | +2.5 dBm | 55 dB |

⚠️ **唯一的风险是转发板上电瞬态 +4.5 dBm**（超过接收端耐压 2 dB）。
**接线状态下不要重启转发板。** 串一个 30 dB SMA 衰减器可彻底消除。

## 板子上的工具限制（踩过的坑）

```
✅ 有: iio_writedev  iio_readdev  iio_attr  kill  killall  pidof  ps
❌ 没有: pkill   timeout   python
```

## 已知问题

1. 转发板 `rxgain ≥ 15` 会持续饱和（4 秒 45 万次）——安全值 ≤ 10
2. 转发板 CLI 的 `rate` 命令曾把 `30.72` 截断成 `30`（已修复）
3. 接收端需要自动频偏搜索，硬编码中频会解不出帧

## 许可

- 本工程代码：自行编写部分可自由使用
- CCSDS FPGA 参考（`euryspace`）：MIT
- ADI HDL 参考设计：ADI BSD / GPL-2.0 双许可
