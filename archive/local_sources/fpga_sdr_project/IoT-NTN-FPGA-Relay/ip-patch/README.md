# axi_ctrl IP 寄存器扩展

## 背景

厂商的 `axi_ctrl_v1_0` IP 只暴露 **4 个用户端口**：

```verilog
output wire [6:0]  idelay_en
output wire [4:0]  idelay_tap
output wire [11:0] phase_inc      // DDS 相位增量
output wire        phy_mode
```

地址宽度 `C_S00_AXI_ADDR_WIDTH = 6` → 64 字节 = **16 个 32 位寄存器，只用了 4 个**。

转发数据面需要 5 个控制字 + 3 个只读状态计数器。

## 做法

不改写整个 IP，而是**脚本化打补丁** —— 三处机械修改，幂等、可重复执行：

| 文件 | 改动 |
|---|---|
| `axi_ctrl_v1_0.v` | 加 8 个用户端口 + 实例化连接 |
| `axi_ctrl_v1_0_S00_AXI.v` | 加 8 个用户端口、3 条只读译码（`0x8/0x9/0xA`）、5 条寄存器→端口赋值 |
| `component.xml` | 加对应的 IP-XACT `<spirit:port>` 声明，让新端口出现在 BD 符号上 |

```bash
cd <板卡工程>/repo/axi_ctrl
python patch_axi_ctrl.py
```

脚本会自动备份原文件为 `*.bak`，并在结束时自检 `relay_ddc_freq` 是否真的写进去了。

## 补丁后的寄存器映射

| 偏移 | 名称 | 属性 |
|---|---|---|
| `0x00` | `idelay_en` | R/W（原有） |
| `0x04` | `idelay_tap` | R/W（原有） |
| `0x08` | `phase_inc` | R/W（原有） |
| `0x0C` | `phy_mode` | R/W（原有） |
| `0x10` | `relay_mode` | R/W |
| `0x14` | `relay_ddc_freq` | R/W |
| `0x18` | `relay_duc_freq` | R/W |
| `0x1C` | `relay_gain[11:0]` / `relay_dc_en[12]` | R/W |
| `0x20` | `status_sample_cnt` | **RO** |
| `0x24` | `status_clip_cnt` | **RO** |
| `0x28` | `status_out_cnt` | **RO** |

厂商原有寄存器全部保持不变，**旧的应用代码仍能运行**；地址窗口不变，**不需要改 Vivado 地址编辑器**。

## ⚠️ 关键：Vivado 不会自动发现改动

`design_1.bd` **只保存 `vlnv` 和 `xci_name`，不保存端口列表**（已用 JSON 解析确认）。端口来自「生成的 IP 产物」目录：

```
zynq_dev_fmcomms3.srcs/sources_1/bd/design_1/ip/design_1_axi_ctrl_v1_0_0_1/
```

那是缓存，**不会因为 `component.xml` 变化而失效**。必须删掉强制重建：

```bash
rm -rf <工程>/zynq_dev_fmcomms3.srcs/sources_1/bd/design_1/ip/design_1_axi_ctrl_v1_0_0_1/
rm -rf <工程>/zynq_dev_fmcomms3.ip_user_files/bd/design_1/ip/design_1_axi_ctrl_v1_0_0_1/
rm -rf <工程>/zynq_dev_fmcomms3.cache/
```

然后：

```tcl
update_ip_catalog -rebuild
reset_target    all [get_files design_1.bd]
generate_target all [get_files design_1.bd]
```

**顺序很重要：先重建 IP、再改 BD。**

顺序反了会出现**静默退化**——BD 修改脚本检测不到新端口，会自动改用 `xlconstant` 常量把控制口固定住：转发本身能用，但软件改不了频率字，而且日志里不会有任何错误。

`scripts/build_pl.tcl` 已按正确顺序编排，并在综合前加了一步校验：检查生成的 `axi_ctrl_v1_0_S00_AXI.v` 里是否真的含 `relay_ddc_freq`，不含就直接报错退出，避免浪费一次 10 分钟的综合。

## 替代方案（不推荐）

如果不方便改 IP，`scripts/modify_bd.tcl` 里的 `tie_or_connect` 会在探测不到新端口时自动用常量兜底：

| 端口 | 兜底常量 |
|---|---|
| `ctrl_mode` | 1（转发） |
| `ctrl_dc_en` | 0 |
| `ctrl_gain` | `0x800`（1.0） |
| `ctrl_ddc_freq` / `ctrl_duc_freq` | 0 |

这样转发可以正常跑，但无法运行时改变频率字——**会失去演示数字变频的能力**，只适合作为应急回退。
