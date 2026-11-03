# ADDA 板 PS 端 CCSDS 解调规范

> 背景：架构 V2 —— ADDA 板当"遥控板"，用 ADC 收 100 MHz 中频的 CCSDS 指令，
> 在 **PS（ARM Cortex-A9）里用 C 解调**，解出两个频率后通过网线控制转发板。
>
> 关键简化：控制内容只有**接收频段**和**转发频段**两个数 → 帧极短 → 符号率可降到 100 kSPS
> → PS 上跑完整 CCSDS 链（含 Viterbi）绰绰有余。

---

## 一、控制帧格式（比完整遥测帧短得多）

```
字段            长度   内容
--------------  ----   ------------------------------------------
ASM             4 B    1A CF FC 1D        （CCSDS 标准同步字，不编码）
版本            1 B    0x01
rx_lo_mhz       2 B    uint16 小端        ← 接收频段（MHz）
tx_lo_mhz       2 B    uint16 小端        ← 转发频段（MHz）
序号            1 B    递增，用于去重
CRC16           2 B    CCITT-FALSE        （poly 0x1021, init 0xFFFF）
--------------  ----   ------------------------------------------
body 小计       8 B    64 bit
```

**编码与成帧（沿用 CCSDS 131.0-B 的做法）：**

```
body 8 B = 64 bit
  → 卷积编码 1/2（K=7, G1=1111001, G2=1011011, 第二路取反）
  → 128 bit
  → 前面加 ASM 32 bit
  → CADU = 160 symbol
```

**示例帧（rx=100 MHz, tx=2450 MHz, seq=0）：**

```
body   = 01 | 64 00 | 92 09 | 00 | <CRC16>
         ↑ver  ↑100    ↑2450   ↑seq
CADU   = 1ACFFC1D + conv_encode(body)
```

---

## 二、时间与数据量预算

| 项 | 值 | 说明 |
|---|---|---|
| 符号率 | **100 kSPS** | 低到 PS 能实时处理，高到帧够短 |
| CADU 长度 | 160 symbol | 8B body + 1/2 编码 + ASM |
| 单帧时长 | **1.6 ms** | 160 / 100k |
| 建议重复 | 3 帧 | 提高捕获概率 |
| 总时长 | **4.8 ms** | 约 5 ms |
| ADC 采样率 | 250 MSPS | AD9516 决定，不改 |
| FPGA 抽取 | **÷8 → 31.25 MSPS** | 简单累加抽取（boxcar），20 行 Verilog |
| 100 MHz 中频在 31.25 MSPS 下的位置 | **6.25 MHz**（混叠） | 100 − 3×31.25 = 6.25 |
| 实际信号中心（TX LO 100 + 基带偏移 0.5） | **100.5 MHz → 混叠到 6.75 MHz** | 100.5 − 3×31.25 = 6.75 |
| 捕获深度 | **65536 样点**（推荐起步） | 2.1 ms @31.25 MSPS，至少含 1 整帧 |
| 上限深度 | 131072 样点 | 4.2 ms（约 2.6 帧），但 BRAM 几乎占满 |
| BRAM 占用 | 65536 × 16 bit = **128 KB** | 1.05 Mbit，Z-7010 共 2.16 Mbit，**留出余量** |
| ⚠️ 注意 | 原设计的波形 ROM 占 64 KB（32768×16） | DAC 不再使用，删掉它可腾出空间 |
| 占用带宽 | 135 kHz（β=0.35） | 很窄，SNR 好 |

**⚠️ 关于混叠**：÷8 的 boxcar 会在 31.25 MSPS 下把 100 MHz 折到 6.25 MHz。
因为阶段 1（收指令）时转发板静音、只有遥控板在发，所以折过来的只有我们自己的信号。
如果要更干净，可把抽取改成 ÷16（→15.625 MSPS，中频折到 6.25 MHz，数据减半）。

---

## 三、FPGA 侧最小改动（组员做）

**目标：把 ADC 采到的 250 MSPS 数据降到 31.25 MSPS，存进 BRAM，PS 能读。**

```
① 位流时序先收敛（P0 器件 + P1 反序列化 1:8）
② 加一级抽取：每 8 个样点累加一次（boxcar）
     always @(posedge clk250) begin
         acc <= acc + sample;      // 16 bit → 加宽到 19 bit
         if (cnt == 7) begin
             acc <= 0;
             bram_we <= 1;
             bram_din <= acc[18:3];   // 右移 3 位防溢出
         end
     end
③ 加 BRAM + AXI BRAM Controller（标准 IP，Vivado 里两个都能直接拖）
     BRAM: 32 bit 位宽 × 32768 深度 = 128 KB（存 I/Q 或实数都够）
     地址：0x43C00000 附近（和 axi_ctrl 错开）
④ 加捕获控制寄存器（写 1 启动，读 bit0 = 完成）
⑤ PS 侧用 /dev/mem 映射 BRAM，读 131072 个 16 bit 样点
```

**工作量估计：2~3 天（如果时序已经收敛）。**

---

## 四、PS 侧 C 解调程序结构

**总运算量估算（关键）：**

| 步骤 | 运算量 | A9 @667 MHz 耗时 |
|---|---|---|
| 读 131072 样点（/dev/mem） | 拷贝 256 KB | < 5 ms |
| 数字下变频 6.25 MHz（NCO 查表 + 复乘） | 131K × ~8 ops | ~5 ms |
| 抽取到 1 MSPS（÷31，多级） | 131K | ~5 ms |
| ASM 相关（32 bit，滑动） | 4.2K × 32 | < 1 ms |
| 比特判决 + Viterbi（3200 symbol） | 3200 × 64 状态 | ~10 ms |
| 解扰 + CRC + 解析 | 微小 | < 1 ms |
| **合计** | | **< 30 ms** ✓ |

**⇒ 完全可以在 PS 上跑，甚至可以每秒重试 30 次。**

**C 程序结构：**

```c
// adda_rx.c  (PS 侧，PetaLinux 用户态)

#define BRAM_ADDR   0x43C00000
#define NSAMP       131072
#define FS_DEC      31250000.0     // 抽取后采样率
#define IF_ALIAS    6250000.0      // 100 MHz 在 31.25 MSPS 下的混叠位置
#define SYM_RATE    100000.0
#define SPS         (FS_DEC / SYM_RATE)   // 312.5

int main(void)
{
    // 1) 映射 BRAM
    int fd = open("/dev/mem", O_RDWR | O_SYNC);
    uint16_t *buf = mmap(NULL, NSAMP*2, PROT_READ, MAP_SHARED, fd, BRAM_ADDR);

    // 2) 触发捕获（写寄存器），等完成标志
    trigger_capture();
    wait_done();

    // 3) 数字下变频 + 抽取 → 得到复基带
    static complex_t bb[8192];
    ddc_decimate(buf, NSAMP, IF_ALIAS, FS_DEC, SYM_RATE, bb, &nbb);

    // 4) 找 ASM（1ACFFC1D，容错 2 bit）
    int pos = find_asm(bb, nbb, ASM_WORD, 2);
    if (pos < 0) return 1;

    // 5) 比特判决 → Viterbi → 解扰 → 取 8 字节 body
    uint8_t body[8];
    if (decode_cadu(bb + pos, body) < 0) return 2;

    // 6) CRC
    if (crc16(body, 6) != (body[6] << 8 | body[7])) return 3;

    // 7) 取两个频率
    uint16_t rx_mhz = body[1] | (body[2] << 8);
    uint16_t tx_mhz = body[3] | (body[4] << 8);
    printf("rx=%u MHz  tx=%u MHz\n", rx_mhz, tx_mhz);

    // 8) 通过网线控制转发板
    relay_send(rx_mhz, tx_mhz);

    return 0;
}
```

**需要移植的算法块（都在我们的 Python 里有参考实现）：**

| 函数 | 参考 | 说明 |
|---|---|---|
| `ddc_decimate` | 无 | NCO + 复乘 + 多级抽取（CIC 或 boxcar） |
| `find_asm` | `ccsds_tm_tx.py` | 32 bit 滑动相关，容错 ≤2 bit |
| `viterbi` | `ccsds_tm_tx.py` | K=7, rate 1/2，64 状态 |
| `derandomize` | `ccsds_tm_tx.py` | LFSR x^8+x^7+x^5+x^3+1，种子 0xFF |
| `crc16` | `ccsds_tm_tx.py` | CCITT-FALSE |
| `relay_send` | `relay_link.py` | TCP 到转发板（或先走串口） |

**⚠️ 时序恢复（timing recovery）是唯一有点难度的部分。**
**简化办法：因为我们知道符号率是 100 kSPS、采样率是 31.25 MSPS（sps = 312.5），可以对 312~313 这几种整数 sps × 8 个相位暴力搜索，取 ASM 命中且 CRC 通过的那个。**

---

## 五、验收标准

| 阶段 | 判据 |
|---|---|
| **R1：ADC 采集通路通** | PS 能读出 131072 个样点，数据不是全 0 / 全满幅 |
| **R2：DDC 通** | 在 6.25 MHz 处看到明显的谱峰（用 FFT 打印） |
| **R3：ASM 捕获** | 找到 `1ACFFC1D`，错 ≤2 bit |
| **R4：解出 body** | 打印出 rx/tx 两个频率，CRC 通过 |
| **R5：控制转发板** | 串口/网口收到 `lo <rx> <tx>`，转发板回 OK |

---

## 六、降级路径（如果时间不够）

| 卡在哪 | 降级方案 | 代价 |
|---|---|---|
| Viterbi 移植慢 | **改成不编码**：ASM + 8B body + CRC，直接 BPSK | 失去 CCSDS 编码合规性，但帧格式仍是 CCSDS 风格 |
| 时序恢复难 | **降低符号率到 25 kSPS**，sps 变成 1250，容差大很多 | 帧变长到 6.4 ms，捕获窗口要加大 |
| DDC 太复杂 | **直接用实信号相关**（跳过 IQ）：把 6.25 MHz 的信号乘以已知的 32 bit ASM 波形做匹配滤波 | 运算量略大，但代码简单 |
| ADC 捕获逻辑难 | 先用 ILA 抓一段（几万点）验证 DDC，再上 BRAM | 只能离线验证，不能闭环 |

---

## 七、和转发板的控制接口

**PS 解出两个频率后，最简单的做法：**

```c
// 方式 A：TCP（如果转发板以后加了 lwIP）
tcp_send("lo 100 2450\n");

// 方式 B：先走串口（转发板现在的 CLI，最省事）
//   但 ADDA 的 PS 要接转发板的 USB 串口 —— 需要 USB host，可能没有
//   ⇒ 若没有 USB host，走方式 A 或让转发板跑 Linux 后 ssh
```

**⚠️ 这是下一个要确认的硬件问题：ADDA 的 PS 有没有 USB host 口？**
**如果没有，就只能走网线（转发板需要 lwIP 或 Linux）。**

---

## 八、一句话总结

```
帧：ASM + ver + rx_lo(2B) + tx_lo(2B) + seq + CRC = 8B body
符号率 100 kSPS → 单帧 1.6 ms，重复 3 帧 = 5 ms
FPGA：÷8 抽取 + 131072 深 BRAM + AXI（256 KB，刚好装满 Z-7010 的 BRAM）
PS：下变频 + 抽取 + ASM 相关 + Viterbi + CRC → 打印两个频率 → 控转发板
总运算量 < 30 ms，A9 完全够
```
