# 组员任务书 V2 —— ADDA 板当"遥控板"

> **角色变了**：ADDA 不再是信号源，而是**遥控指令接收机**。
> 它用 ADC 收 100.5 MHz 中频的 CCSDS 指令，在 **PS 里用 C 解调**，
> 解出两个频率（接收频段 / 转发频段），然后通过网线控制转发板。
>
> **DAC 不再需要。ADC 变成核心。** 所以之前"删掉 ADC 来收敛时序"的做法**作废**。

---

## 你要交付的四件事

| # | 里程碑 | 验收标准 |
|---|---|---|
| **M1** | 位流时序收敛（ADC 必须保留并正确工作） | `WNS ≥ 0, WHS ≥ 0, TNS = 0` |
| **M2** | ADC 采集通路：÷8 抽取 + BRAM + AXI，PS 能读到数据 | PS 读出 65536 点，不是全 0 / 全满 |
| **M3** | PS 里用 C 解调出两个频率 | 用金标准向量验证通过，现场收到 `rx=100 tx=2450` |
| **M4** | 把频率发给转发板 | 转发板回 `OK rxlo=100 txlo=2450` |

---

## M1：时序收敛（最关键，先做这个）

### 先说结论：为什么原例程必然违例

```
厂商报告（7z020-clg484-2 上跑的）：
  WNS = -4.888 ns   TNS = -512.994   637/11701 端点失败

按时钟拆：
  adc_dco_p (250 MHz)  WNS -1.300   591 个失败   ← 全部在这里
  clk_out1 (10 MHz)    +89.8        0
  clk_out2 (200 MHz)   —            0

⇒ 违例集中在 ADC 的 250 MHz 数据域
⇒ 而且那还是 -2 速度等级，你的板子是 -1，只会更差
```

### P0（10 分钟）：器件改对

```
Vivado → Settings → Project → Part 改成：
    xc7z010clg400-1
或 Tcl：
    set_property part xc7z010clg400-1 [current_project]
```

**原例程是 `7z020-clg484-2`，速度等级和封装都不对。**

### P1（核心）：ADC 反序列化 1:2 → 1:8

**现在：**
```verilog
ADC_RX_selectio_wiz #(parameter SYS_W = 14, DEV_W = 28)   // 1:2
⇒ 织体时钟 = DCO = 250 MHz   ← 时序杀手
```

**改成 1:8：**
```
双击 ADC_RX（selectio_wiz）→ SERIALIZATION_FACTOR 改为 1:8
⇒ DEV_W = 14 × 8 = 112
⇒ 织体时钟 = 250 / 4 = 62.5 MHz（DDR 下 1:8 相当于降到 1/4）
```

**⚠️ 改完下游 phy 逻辑要相应处理"每拍 8 个样点"的拼接与顺序。**

**如果 1:8 不好改，先试 1:4（织体 125 MHz），通常也能收敛。**

### P2：把 ILA 移出高时钟域

```
现在：connect_debug_port u_ila_0/clk [get_nets adc_data_clk]   ← 250 MHz
⇒ 改到低时钟域采样，或者干脆删掉（调试完再临时加）
```

### P3：修约束

```tcl
# ① 删掉这条（它在掩盖问题，不是解决问题）
set_multicycle_path -hold -from [get_clocks adc_dco_p] -to [get_clocks adc_dco_p] 2

# ② 检查 DAC 的生成时钟是否真的建起来了（现在 report_clocks 里没有 dac_dci_p）
report_clocks
# 如果 DAC 不再使用，把 DAC 相关约束整段删掉更干净

# ③ input_delay 现值是拍脑袋的 0.5/1.0 ns，按 AD9643 手册的 tSKEW 算，
#    或者用 IDELAY 扫描找眼图中心再反算
```

### 验收

```tcl
report_timing_summary -file ts.rpt
# 要求：WNS ≥ 0, WHS ≥ 0, TNS = 0
check_timing -verbose
# 要求：没有 no_clock / no_input_delay / no_output_delay
```

---

## M2：ADC 采集通路

### 要加的东西

```
① ÷8 boxcar 抽取（250 → 31.25 MSPS）
     always @(posedge clk_adc) begin
         acc <= acc + sample;
         if (cnt == 7) begin acc <= 0; we <= 1; din <= acc[18:3]; end
     end
   ⚠️ 用 250 MHz 域做累加，但只写 31.25 MHz 的 BRAM，逻辑很轻

② BRAM：65536 × 16 bit = 128 KB
     位宽 16（ADC 是 14 bit，左对齐即可）
     深度 65536 → 2.1 ms @31.25 MSPS，足够装 1 整帧

③ AXI BRAM Controller（标准 IP），地址建议 0x43C10000
     ⚠️ 和 axi_ctrl（0x43C00000）错开

④ 捕获控制寄存器（可放在 axi_ctrl 里）
     bit0: 写 1 启动捕获
     bit1: 读 1 表示完成
     bit2: 循环模式 / 单次模式
```

**⚠️ BRAM 预算**：Z-7010 共 2.16 Mbit。原波形 ROM 占 64 KB —— **DAC 不用了，删掉它腾空间**。128 KB 采集用掉 1.05 Mbit，留一半余量。

### 验收

```
PS 里 mmap 0x43C10000，读 65536 个 uint16：
  · 不是全 0，不是全 0x3FFF
  · 有噪声起伏（std > 几个 LSB）
```

---

## M3：PS 里用 C 解调（核心工作）

### 依据文档（都在包里）

| 文档 | 内容 |
|---|---|
| **`LINK_PROTOCOL_PHY.md`** | **协议全文 + 三组金标准测试向量** ← 最重要 |
| `ADDA_PS_DEMOD_SPEC.md` | 预算、C 程序结构、降级路径 |

### 要实现的 11 步

```
① ADC 250 MSPS 采样
② ÷8 抽取 → 31.25 MSPS          100.5 MHz 混叠到 6.75 MHz
③ 平方律载波恢复                 z=x²，找 13.5 MHz 线，除 2
④ 下变频到 0 Hz
⑤ SRRC 匹配滤波（β=0.35）
⑥ 抽取到符号                    sps = 312.5 → 用 312/313 + 1/8 相位搜索
⑦ ASM 相关（1ACFFC1D，容错 ≤2 bit）
⑧ Viterbi（K=7，128 状态）
⑨ 解随机化
⑩ CRC16（CCITT-FALSE）
⑪ 取 rx_lo / tx_lo
```

### ⚠️ 两个必须照做的点（我们踩过的坑）

**① 载波恢复必须用平方律，不能用 FFT 找最强谱线**
```
实测：FFT 找峰误差 25 kHz = 符号率/4
  ⇒ 每符号转 90°，判决全错，怎么调都解不出
平方律：
  z = x²  →  2f_c 处出现谱线（数据 ±1 被平方消掉）
  抛物线插值 → 精度从半个 bin 提到 1/20 bin
  f_c = 谱线频率 / 2
```

**② 极性要两种都试**
```
发射约定：bit0 → +1, bit1 → -1
但空口有 180° 相位模糊 ⇒ 两种极性都试，以 CRC 通过为准
```

### 验收：用金标准向量（逐比特核对）

**你的 C 实现对以下三个输入，CADU 必须与表中完全一致：**

| rx | tx | seq | body | **CADU（20 字节）** |
|---|---|---|---|---|
| 100 | 2450 | 0 | `01640092090077ab` | `1acffc1dbcd9014c82bf4b2c0b3894c10ddfdc50` |
| 120 | 1000 | 1 | `017800e8030118f9` | `1acffc1dbcd902e425bf7178a92646027b434d99` |
| 2400 | 2450 | 7 | `0160099209077d3d` | `1acffc1dbcd90178796fe89c0b3894fb8771de0a` |

**⇒ 如果不一致，先查：随机化的位序（bit7 抽头）、G2 是否取反、字节序（小端）、CRC 的大端。**

---

## M4：控制转发板

```
拿到 rx/tx 后，发：  lo <rx> <tx>
```

**⚠️ 转发板现在的控制口是串口（FT4232H），ADDA 的 PS 有没有 USB host 还没确认。**

| 情况 | 做法 |
|---|---|
| ADDA 有 USB host | 接转发板的 USB 串口，直接发 `lo` |
| 没有 USB host | 转发板加 lwIP TCP 服务，或转发板跑 Linux 后走 ssh；ADDA 走网线发 |

**这个先确认，再决定 M4 怎么写。**

---

## 测试工具（包里都有）

### 造测试波形（在你自己的 PC 上跑，或者让对接人要）

```powershell
# 生成控制帧波形（不上板，只看数据）
python pluto_siggen.py --mode cmd --rx 100 --tx 2450 --no-tx --save cmd.bin

# 打印 body / CADU / 时长，和自己的 C 实现对照
```

### Python 参考实现（你的 C 可以逐行对照）

```powershell
# 用已知频偏和 SNR 测试解调
python rx_board.py --help
```

**`rx_board.py` 里的 `demod_text()` 就是接收流程的 Python 版，包含平方律 + 定时搜索 + 极性搜索。**
**建议：先把 C 实现的结果和它对比，一致了再上硬件。**

---

## 每步回报模板（发回给对接人）

```
【里程碑】M1 / M2 / M3 / M4
【做了什么】
【Vivado】器件____   WNS____ WHS____ TNS____
【report_clocks】有没有 250 MHz 织体时钟：有/没有
【采集】PS 读到 ____ 点，std=____（非 0 非满）
【解调】金标准向量 3/3 对 / __ 对
        现场收到的 rx=____ tx=____  CRC OK/FAIL
【控制】转发板回：____
【问题】错误信息关键 3 行
```

---

## 硬件纪律（别踩坑）

```
✅ SMA 电缆连接，不用天线（100 MHz 是 FM 广播频段，禁止辐射）
✅ 输入端串 50 dB 衰减器（对接人那边配）
✅ 先 40~50 dB，用 RMS 判读后微调
❌ 不要直连，不要只串 10~20 dB
❌ 不要在 ADC 输入端加直流偏置（ADC 默认交流耦合，50 Ω）
```

---

## 优先级（时间紧就按这个顺序）

```
1. M1 时序收敛（不收敛后面全做不了）
2. M2 采集通路（能读到数据就有底）
3. M3 解调里最简单的部分：先只做"平方律找频偏 + FFT 看谱"，确认看到 6.75 MHz 的峰
4. M3 完整解调
5. M4 控制转发板

降级路径（时间不够时）：
   · Viterbi 太慢 → 改不编码，ASM + 8B + CRC 直接 BPSK
   · 定时恢复难 → 符号率降到 25 kSPS
   · DDC 复杂 → 实信号直接和 ASM 波形做相关
```
