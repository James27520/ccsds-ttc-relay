# ADDA 板（Z7ADDALite）组员任务书

> 目标：让 Z7ADDALite 的 DAC 输出一个**中频 100 MHz** 的波形，作为整条演示链路的"射频信号源"。
>
> 对接人：负责接收端的同学（下文称"接收端"）。
> 本文档所有路径基于资料包 `E:\Z7ADDALite\Z7ADDALite资料\`。

---

## 一、你要交付的三样东西

| # | 里程碑 | 验收标准 |
|---|---|---|
| **M1** | 原厂 SIN 例程能跑起来 | 板子正常上电、Vivado 能打开工程、位流能下载、J6 有波形输出 |
| **M2** | 换成 `tone_100m.coe`，输出 100 MHz 单音 | 接收端在某个 LO 上能搜到一个明显单峰（频率可能不等于 100 MHz，**这是正常的**，用来标定 DAC 采样率） |
| **M3** | 换成 `text_hello.coe`，输出 BPSK 文本 | 接收端解出 `hello world` |

**每个里程碑完成后，把"回报数据"（见第五节）发给接收端。**

---

## 二、材料位置

### 你的资料包

```
E:\Z7ADDALite\Z7ADDALite资料\
├── 02硬件资料\
│   ├── 原理图\Z7ADDALite_SCH_RevB.pdf          ← ADC/DAC 部分在 p10、p11
│   ├── ADDA引脚约束\top_pro.xdc
│   └── Z7ADDALite_PIN_ASSIGN.csv
├── 03使用教程手册\
│   ├── 01Z7ADDALite硬件参考手册.pdf            ← 时钟/ADC/DAC 说明在 p8、p9
│   ├── 04Z7ADDALite开箱测试快速使用指南.pdf
│   └── 06ADC_DAC例程使用讲解.pdf
└── 04例程\
    └── ADDA_loop\
        ├── Z7ADDA_SIN_16BIT.zip                ← ★ 用它做基础（Vivado 2018.3）
        ├── Z7ADDA_loop.zip                     ← ADC→DAC 环回（备用）
        └── Z7ADDA_square_wave.zip 等            ← 其他波形例程（备用）
```

### 接收端给你的文件（需要拷给你）

```
tone_100m.coe        ← 标定用单音（假设 DAC 250 MSPS，中频 100 MHz）
text_hello.coe       ← 内容用：BPSK "hello world"，符号率 1.25 MSPS，中频 100 MHz
gen_adda_coe.py      ← 生成器（后续要改频率/改文本时自己跑）
README_组员任务.md    ← 本文档
```

**如果接收端要改参数重新生成：**

```powershell
python gen_adda_coe.py --mode tone --fs 250e6 --if 100e6 --out tone_100m.coe
python gen_adda_coe.py --mode text --fs 250e6 --if 100e6 --text "hello world" --sps 200 --out text_hello.coe
```

---

## 三、硬件事实（先看一遍，避免接错）

### 接口

| 接口 | 丝印 | 类型 | 说明 |
|---|---|---|---|
| **DAC 输出** | **J6、J7** | **SMA** | 2 通道，**直流耦合**，无重构滤波器 |
| ADC 输入 | J4、J5 | SMA | 2 通道，50 Ω，交流耦合 |
| 外部时钟 | ETCK | SMA | 一般不用 |
| 网口 | — | RJ45 千兆 | 可选 |
| USB | JTAG/UART 口 | Type-C | 下载 + 串口 |

### 时钟

```
参考：板上 10 MHz 0.5 ppm TCXO
分配：AD9516（寄存器配置写死在 ad9516_config.v）
PL 时钟：50 MHz（引脚 M19）
⇒ DAC/ADC 的实际采样率由 AD9516 决定，代码里看不出具体数值
⇒ 所以 M2 的"标定"是必须的
```

### 波形机制

```
sin_wave.v:
    addr_reg 从 0 数到 32767 循环
    blk_mem_gen_0 (addra[14:0], douta[15:0])

⇒ ROM 固定 32768 点 × 16 bit
⇒ .coe 内容每 32768 个采样点循环播放一次
⇒ 换波形 = 换 .coe + 重新综合
```

**原厂正弦例程的内容是"半个正弦"（32768 点只装 0.5 个周期）**
⇒ 输出频率只有 Fs/65536（几十 kHz 量级）
⇒ **AD9361 的调谐下限是 70 MHz，所以原厂例程的输出接收端收不到，必须换 .coe**

---

## 四、操作步骤

### M1：先跑通原厂例程

```
1. 解压 Z7ADDA_SIN_16BIT.zip 到本地（路径不要有中文和空格最好）
2. Vivado 2018.3 打开 Z7ADDA_SIN_16BIT\Z7ADDA_SIN_16BIT.xpr
3. 直接 Generate Bitstream（综合 + 实现）
4. Hardware Manager → Open Target → Auto Connect → Program Device
5. 板子 LED 正常、串口（115200）有打印
6. J6 接示波器或万用表，应能看到一个低频正弦
```

**✅ M1 通过后，再动 .coe。**

### M2：换成 100 MHz 单音（**关键：标定 DAC 采样率**）

#### 步骤 A：替换 .coe

**方法 1（推荐）：直接改 IP 里的系数文件**

```
1. 在 Vivado 的 Sources 面板里找到 blk_mem_gen_0（IP）
2. 双击打开 → 切到 "Other Options" 标签页
3. 找到 "Coe File" 一栏 → 点右侧浏览按钮
4. 选择接收端给你的 tone_100m.coe
5. OK 保存
```

**方法 2：覆盖原厂文件**

```
把 tone_100m.coe 改名为 sin32768b16.coe，
覆盖 Z7ADDA_SIN_16BIT\matlab\sin32768b16.coe
（前提是 IP 配置里引用的就是这个路径）
```

#### 步骤 B：强制重新生成 ROM

```
⚠️ 只改 .coe 不重新生成 IP，Vivado 会用缓存里的旧数据！

1. 右键 blk_mem_gen_0 → Reset Output Products
2. 右键 blk_mem_gen_0 → Generate Output Products → Generate
3. 确认没有报错
4. Generate Bitstream
```

#### 步骤 C：下载并接线

```
1. 下载位流
2. J6 用 SMA 线接出来
3. ★ 必须串衰减器：先接 40 dB（两个 20 dB，或 30+10）
4. 另一端接接收端的 RX1（SMA）
```

**⚠️ 纪律：ADDA 的 DAC 满量程可能到 +10 dBm，AD9361 的 RX 最大只能吃 +2.5 dBm。**
**不串衰减直接接，可能烧掉接收板前端。**

#### 步骤 D：告诉接收端，让它测

**接收端会做：**
```
扫 LO（70~500 MHz 范围），找那个单峰，记录实测频率
```

**然后计算真实 DAC 采样率：**
```
真实 Fs = 250 MSPS × (实测频率 / 100 MHz)

例：假设 250 MSPS、目标 100 MHz、实测 87.3 MHz
    ⇒ 真实 Fs = 250 × 87.3 / 100 = 218.25 MSPS
```

**然后接收端会给你一个新文件（例如 `tone_100m_fs218.coe`），你再走一遍 A/B/C。**

**✅ 这一步做完，DAC 采样率就标定好了，以后所有波形都精确。**

### M3：换成文本波形

```
1. 用接收端给的 text_hello.coe（或自己生成，--sps 200）
2. 同 M2 的步骤 A、B、C
3. 下载后保持接线不变
4. 接收端跑：
     python rx_board.py --lo <标定后的中频> --demod --sym-rate 1.25e6
5. 应该解出：hello world
```

**⚠️ 注意：中频 100 MHz 是"目标值"，标定后可能是 98.7 MHz 之类的实际值。
接收端的 LO 要设成【转发板实际输出频率】，不是死记 100。**

---

## 五、每次都要回报的数据（复制这个模板）

```
【里程碑】M1 / M2 / M3
【用的文件】原厂 sin / tone_100m.coe / text_hello.coe / 其他
【Vivado】版本 2018.3，综合实现是否通过：是/否
         有无时序违例 WNS：____ ns
【位流】下载成功：是/否
【接线】J6 接的是：SMA 电缆 → 衰减 ____ dB → 接收板 RX1 / 天线 / 示波器
【板子现象】LED：____    串口打印：____
【测量】如有示波器/频谱仪：
        输出频率 ≈ ____ MHz
        Vpp ≈ ____ V
        波形是否像正弦：是/否
【问题】遇到什么报错（贴关键几行）
```

---

## 六、和接收端的接口约定

| 项 | 约定值 | 备注 |
|---|---|---|
| **中频** | 100 MHz（**标定后可能微调**） | 必须 ≥ 70 MHz（AD9361 下限） |
| **DAC 采样率** | 待标定（先假设 250 MSPS） | M2 完成后确定 |
| **波形格式** | `.coe`，radix=10，**32768 点**，16 bit 有符号 | 与原厂一致 |
| **内容编码** | BPSK + SRRC(β=0.35)，帧 `AA AA \| len \| text \| CRC16` | 接收端解调同格式 |
| **符号率** | 1.25 MSPS（`--sps 200`） | 占用带宽约 1.7 MHz |
| **连接方式** | SMA 电缆 + 衰减器 | **不要用天线**（100 MHz 是 FM 广播频段，违法） |
| **衰减** | 起步 40 dB，按接收端 RMS 调整 | RMS 目标 1000~5000 |

---

## 七、常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| **J6 没波形** | 位流没下来 / 地址没跑 / DAC 时钟没配 | 先确认 M1 原厂例程能出波形 |
| **波形频率不对** | .coe 换了但 IP 没重新生成 | 必须 `Reset Output Products` 再 `Generate` |
| **接收端只看到噪声** | 输出低于 70 MHz（Fs 比预期低）/ 衰减太大 | 把实测频率告诉接收端，让它扫 LO |
| **接收端 RMS 爆表** | 衰减不够 | 加到 50~60 dB |
| **Vivado 综合报 ROM 初始化错误** | .coe 点数不等于 32768 或含非法字符 | 用接收端提供的文件，不要手工改 |
| **中文路径报错** | Vivado 对中文路径敏感 | 把工程解压到纯英文路径 |

---

## 八、一句话总结

```
先 M1 确认板子好 → 再 M2 换单音并标定采样率 → 再 M3 换文本
每次都是：换 .coe → Reset/Generate Output Products → Generate Bitstream → 下载
接线永远串衰减器，永远用 SMA 电缆，不要用天线
```
