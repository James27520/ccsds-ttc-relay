# LDSDR：100 MHz 有线输入与 2450 MHz 输出审查

日期：2026-10-26。范围：本机历史工程、原理图文本、验证日志和 ADI 官方技术文档。此次未连接串口/JTAG/网口、未修改设备、未跑构建或硬件测试。以下本地路径以 `C:/Users/Lu/Desktop/全国大学生嵌入式芯片与系统设计竞赛` 为根。

## 结论与决策

**100 MHz 输入、2450 MHz 输出是值得优先做受控单向试验的候选，尚不能写成已验证直连方案。** 不能仅凭“AD9363 规格最低 325 MHz”断言完全不能接收 100 MHz；也不能仅凭软件写着 AD9361 就保证 70 MHz–6 GHz 的板级性能。

用户已确认当前实物始终是同一块 LDSDR，本报告不再从目录名称推断实物身份。历史交接称其射频芯片为 AD9363；程序按 AD9361 兼容配置运行。现有证据支持“使用扩展调谐配置的 AD936x 板”，不足以独立证明封装实际完整料号或 100 MHz 接收性能。

100 MHz 的工程吸引力是可以先验证 ADDA 较低的模拟频点，省去先实现约 350 MHz 插值/搬频方案的复杂度；其代价是 LDSDR 接收端处在 AD9363 官方保证范围之外。2450 MHz 则落在 AD9363 的规定频段内。是否能直连应由两板实际通带、电平、频谱和短帧接收结果决定；此阶段没有证据要求立即购买外部混频器。

## 1. 芯片型号、驱动 ID、读回结果分别证明什么

| 证据 | 可证明内容 | 不可据此证明 |
| --- | --- | --- |
| `fpga_sdr_project/项目交接文档.md:28` 写“AD9363-BBCZ，2R2T LVDS” | 历史开发者对 LDSDR 射频器件的描述 | 本次看到了封装丝印或核实了完整采购料号 |
| `LDSDR_010/原理图_文字提取.txt:3890、4473` 仅写 `AD936x`，网名包含 `AD9363_RST` | 同族器件设计及命名 | 板上必然焊接 AD9361 或 AD9363 的哪个订货后缀 |
| `LDSDR_010/zynq_dev_fmcomms3.sdk/9361/src/main.c:93`、`relay_udp_work/vendor_sdk/9361/src/main.c:116` 设置 `ID_AD9361` | 软件选择 AD9361 配置分支 | 焊接芯片已被自动识别为 AD9361 |
| `relay_udp_work/vendor_sdk/9361/src/config.h:53–55` 设置 AD9361_DEVICE=1、AD9363A_DEVICE=0 | 编译时选择 | 产品物料清单 |
| 同目录 `ad9361_api.c:117` 直接赋值 `phy->dev_sel=init_param->dev_sel` | 设备种类来自传入参数 | 自动读取完整器件型号 |
| `ad9361_api.c:522–528` 读取 0x037，仅比较 PRODUCT_ID_MASK；`ad9361.h:859–860` 为 mask=0xF8、ID=0x08 | 同族产品 ID 与 revision 检查成功 | 区分所有 AD9361/3/4 产品等级、规格或板级匹配 |
| `udp_deploy_final_20261018.json:5` 打印 `AD936x Rev 2 successfully initialized` | 该驱动初始化通过 | “实际硅片就是 AD9361”，或该板在 100 MHz 已实测 |

补充型号边界：ADI AD9363 Rev.D 的订货表（第 32 页）列 `AD9363ABCZ`，而历史交接用了 `AD9363-BBCZ`。这说明完整后缀应由清晰封装照片或原厂/板厂 BOM核对；**不能据此断定用户拿错板，更不能据此判器件真伪**。本轮在项目目录内未找到能够辨认该实物射频芯片丝印的历史照片或匹配 BOM。根目录 `e19773b77a1237dbe75c2383af0388bb.jpg` 已视觉检查，是手绘链路纸张，并非芯片照片。参考：[AD9363 数据手册，p.32](https://www.analog.com/media/en/technical-documentation/data-sheets/ad9363.pdf)。

历史 `new_board_caps.txt` 中的 `hw_model ... AD9361`、`frequency_available [70000000 ... 6000000000]` 同样是固件描述和可设置范围；它不是物理芯片鉴定，也不能拿文件名判断当前另有一块实物。

## 2. 官方规格与 100 MHz 的准确定位

| 器件/文档 | 官方可确认范围 | 对当前候选的含义 |
| --- | --- | --- |
| AD9361 Rev.G 第 1 页 | RX 70 MHz–6 GHz；TX 47 MHz–6 GHz | 如果物料确为 AD9361，100 MHz RX 与2450 MHz TX均在器件频率范围内，但板级匹配仍需验证 |
| AD9363 Rev.D 第 1、3、4 页 | 收发 325 MHz–3.8 GHz；通道带宽最高20 MHz | 按现有历史器件描述规划时，100 MHz属于规格外候选；2450 MHz在范围内 |
| ADI 官方 Pluto 扩展说明 | 默认保证范围325–3800 MHz；固件可扩展至70 MHz–6 GHz，但性能不保证 | 说明100 MHz并非毫无依据的尝试；不能把Pluto个案直接升级为当前LDSDR板级保证 |

来源：[AD9361 数据手册](https://www.analog.com/media/en/technical-documentation/data-sheets/AD9361.pdf)、[AD9363 数据手册](https://www.analog.com/media/en/technical-documentation/data-sheets/ad9363.pdf)、[ADI Expand the Frequency and RF Ports](https://analogdevicesinc.github.io/system-level/solutions/platforms/pluto/setup/hacking/)。最后一项明确区分保证范围与扩展配置；其 Linux/U-Boot 命令不是让本项目改刷 Pluto 固件的要求。

本地驱动也体现同样区别：`ad9361.c:920–933` 在 `ID_AD9363A` 分支拒绝低于325 MHz或高于3.8 GHz，其余分支按70 MHz–6 GHz检查；常量见 `ad9361.h:2846–2850`。`relay_rf_packet.h:60–61` 同样放行70 MHz–6 GHz。当前选择 `ID_AD9361`，因此100 MHz可以穿过软件参数检查。**参数接受、PLL锁定、收到射频信号、完成低误码数据传输是四个不同层级。**

本地设置本振的路径在 `ad9361.c:6823` 会等待 VCO_LOCK；读回路径 `ad9361_api.c:853–858、1493–1498` 调用时钟重算，`ad9361.c:6715–6723` 读取分频/整数/小数寄存器后计算频率。该读回比仅回显命令强，但仍不是频谱仪对实际 RF 的测量，也不包含板上巴伦损耗、噪声系数或动态范围测量。

## 3. 接收匹配网络与资料来源限制

`LDSDR_010/原理图_文字提取.txt:4012–4069` 包含 RX1、RX2、L7/L8 的六引脚变压器符号以及 C91/C92、C93/C94=18 pF，连接到 RX1A、RX2A 差分输入。文本没有巴伦订货型号，也没有网络 S 参数。`3890` 处器件符号仅为 AD936x。

**该文本处在LDSDR目录，不等于已完成对实物装配的一一核对。** 同目录 `analyze_repo.py:3` 和 `extract_parts.py:4` 指向历史 `E:/7010_AD9363_开源资料/hardware`，并尝试从 `08 BALUN.SchDoc`、`ZYNQ7020_AD9364_V2.PcbDoc` 提取型号；本机当前资料目录仅有原理图PDF，未找到这些原始Altium文件及相应BOM。因此，现有文本可用于识别通用匹配结构，不能保证全部元件值对应实物版本。

本轮先前已视觉核对 `7010_AD9363_SDR/硬件资料/原理图.pdf` 第15页，类似SMA—巴伦—18 pF—RF端口结构确实存在。但用户提供的资料包与LDSDR已验证工程之间仍需器件和引脚适配；不能从这页直接推算当前整板100 MHz插损。

用 `|Xc|=1/(2πfC)` 计算，单个18 pF电容在100 MHz约88.4 Ω、325 MHz约27.2 Ω、2450 MHz约3.61 Ω。该数字提示低频匹配值得重视，**不能**据此把网络简化为一个“50 Ω×18 pF高通”后宣布100 MHz阻断：巴伦变比、漏感、寄生、电容连接位置及芯片复数输入阻抗共同决定响应。即使损耗增加，窄带有线短帧仍可能有足够链路余量。

ADI UG-570 第61–62页说明RF端口需要外部匹配，LNA输入阻抗随频率变化；第68页说明匹配网络应按应用设计。官方匹配资料也要求使用端口S参数与适合频段的巴伦。[UG-570](https://www.analog.com/media/en/technical-documentation/user-guides/AD9361_Reference_Manual_UG-570.pdf)、[General RF Front End Matching Methodology](https://ez.analog.com/rf/wide-band-rf-transceivers/design-support/a/documents/DO26507/general-rf-front-end-matching-methodology)。

## 4. 本地是否已经测过100 MHz

本轮对 `LDSDR_010`、`relay_udp_work`、`fpga_sdr_project` 的源码、Markdown、JSON、文本、日志和CSV做了定向检索；未找到100 MHz RF输入下的原始IQ、输入源参数、频谱截图和对应判据组合。命中项主要是：

- AXI/ILA的100 MHz数字时钟，不能作为100 MHz射频验证。
- 驱动重新校准的100 MHz频差阈值，不能作为接收频点。
- 900.100 MHz输入、1000.100 MHz输出；这里“.100”是100 kHz偏移，不是100 MHz载波。
- `LDSDR_010/rf_verify_dualch.py:30–31` 计划RX LO=900 MHz、TX LO=1000 MHz，它是测试脚本而非100 MHz通过记录。
- `fpga_sdr_project/IoT-NTN-FPGA-Relay/docs/02-调试报告.md:471–474` 声称900.100→1000.100 MHz及-36.6 dBm；只作为原文历史陈述。
- `fpga_sdr_project/relay_log.txt:2` 是2140→2350 MHz软件转发运行文本，不是100 MHz测量。

本会话可追溯的2026-10-18七项UDP验证在 `relay_udp_work/verification_logs/udp_rf_verified_final_20261018.json`，LO围绕900/1000 MHz变化。`firmware/release_manifest.json:14` 明确无RF频谱测量。故目前结论是“**未找到100 MHz实测证据**”，不是“已测100 MHz不通”。

## 5. 需要纠正的方案表述

| 表述 | 准确结论 |
| --- | --- |
| “AD9361能70 MHz–6 GHz，所以这块LDSDR保证100 MHz可用” | AD9361的RX范围说法正确；当前完整物料型号未独立核实，历史称AD9363，软件ID不等于物料。100 MHz可以试，但需板级验收。 |
| “AD9363低于325 MHz绝对不能工作” | 官方存在扩展配置，但不保证性能。宜标为实验频点，不应直接否决或写成规格内能力。 |
| “5.8 GHz与2.45 GHz都可直接作为当前板的保证工作频率” | 5.8 GHz在AD9361 RX/TX范围内，但超出AD9363规定范围；不能借用另一型号的规格。若任务没有5.8 GHz必要性，首版2450 MHz证据更充分。ADDA也不能因DAC标1 GSPS便被认为能直接输出5.8 GHz。 |
| “两个RX、两个TX的四个本振可分别随意设置” | RX1/2共用接收LO，TX1/2共用发射LO；RX和TX两个LO彼此可不同。独立数字DDC/DUC只能在瞬时通带内搬移。 |
| “同一芯片可同时RX1=100 MHz、RX2=2450 MHz，TX1=2450 MHz、TX2=100 MHz” | 对单片此架构不可同时实现：两个RX相隔2.35 GHz远超共同接收通带，TX同理。单向100→2450可先测；双向反向频率需时分重调或不同频率规划/额外射频链，不能由现有双路RTL自动解决。 |
| “输入载波恰好等于LO就必然产生LO泄漏，因此零中频不可用” | 输入单音等于RX LO会变成DC，易受DC校正抑制、与DC偏置混淆。LO泄漏和DC偏置是非理想项，并非由这一相等条件凭空产生。零中频是该芯片正常架构；首个单音验收采用低IF，方便区分真实信号与中心尖峰。 |
| “频谱中心有峰，或者UDP ACK成功，就证明透传成功” | 中心峰可能是泄漏；ACK只验控制。需源开关、频率小步移动、电平比例变化和最终CRC/载荷比对。 |

共享LO直接见 [AD9363 数据手册，第28页](https://www.analog.com/media/en/technical-documentation/data-sheets/ad9363.pdf) 的 Receiver、Transmitter、RF PLLs段。该结构允许FDD同时接收和发射，但不会增加独立合成器数量。

DC相关本地证据：`ad9361_api.c:506–508` 默认开启芯片RF/BB DC跟踪和正交跟踪；UG-570第11页说明BB DC跟踪采用高通反馈环。LDSDR `relay_path.v:163–195` 另有可选数字DC去除；当前PL默认值及10/18日志为 `dc=0`（`axi_ctrl_v1_0_S00_AXI.v:259–262`、`udp_deploy_final_20261018.json:2`），这只关闭PL级功能，并不自动关闭芯片内部DC跟踪。[UG-570，第11页](https://www.analog.com/media/en/technical-documentation/user-guides/AD9361_Reference_Manual_UG-570.pdf)。

## 6. 建议的100 MHz判定实验（待执行）

以下是具体可复核的实验设计，本轮没有执行。先只做单向单通道，保持另一通道静音/妥善端接；使用既有LDSDR已验证启动与寄存器基线，不为100 MHz试验换刷资料包固件。

### 6.1 频率与链路表

| 阶段 | 输入/配置 | 应观察到什么 |
| --- | --- | --- |
| ADDA输出单独检查 | 100.000 MHz低幅连续正弦，已知50 Ω负载 | 在板端确认实际频率、幅度、100 MHz基波与DAC镜像/谐波 |
| LDSDR先只接收 | RX LO=99.000 MHz；输入100.000 MHz；DDC/DUC先为0 | 原始接收IQ中出现约+1 MHz信号；I/Q符号约定若反向，先用正负频点变化确认 |
| 验证频率响应 | 输入保持100 MHz，RX LO小步改变；再固定LO、小步改变源 | 基带峰按差频关系移动，而非一直停在0 Hz或某个固定杂散 |
| 单向转发 | 保持RX LO=99 MHz，TX LO=2449 MHz，数字净频移0 | 正常复数映射下输出2450 MHz；此候选须用频谱确认实际I/Q符号 |
| 数据演示 | 单音通过后，在100 MHz附近加窄带成形BPSK/既有帧结构 | 2450 MHz侧解调出helloworld及CRC；记录成功率、输入电平和带宽 |

理想频率关系为 `fout=LOtx+(fin-LOrx)+数字净频移`，具体DDC/DUC符号以源码和单音实测为准。若要LO固定100/2450 MHz，也可先用100.100 MHz输入、2450.100 MHz输出完成偏频验证；这不是声称已验证恰好100/2450 MHz载波。

99 MHz和100 MHz都属于按AD9363规格判断的扩展候选。保持约1 MHz低IF的目的只是避免第一步陷入DC尖峰歧义，不会消除低于325 MHz的模拟性能不确定性。所选样率、模拟带宽和数字滤波必须完整容纳低IF与调制带宽。

### 6.2 电平和仪器条件

1. ADDA先对50 Ω终端测幅度，再连接LDSDR，按测得值配置数字幅度和固定衰减。可以把LDSDR端约-40至-30 dBm的单音作为保守起测值，MGC从低/中增益起调，以可测SNR且无裁剪为准；这是实验选择，不是AD9363的规格化最佳电平。
2. AD9363 RF输入峰功率绝对最大值为+2.5 dBm（数据手册第15页），不能作为工作目标。若ADDA的1.2 Vpp确实落在50 Ω负载上，正弦平均功率约+5.56 dBm；因此不可直接套用厂商满幅例程。开路值和端接值必须分清。
3. 前期只看接收IQ或仪器观测，TX保持静音；转发时TX经足够衰减接50 Ω测量设备/接收机。不要把两个发射端互接。
4. 2450 MHz输出需要能覆盖该频段的测量设备或独立接收机；ADDA的250 MSPS ADC不能仅凭“会欠采样”就被当作2.45 GHz测量仪。若只有两块板、没有可用接收观测路径，只能完成100 MHz输入侧验证，不能宣称全链输出验收完成。
5. 若用ILA/板端IQ快照观察，应保存原始IQ和元数据。现有RF_SET UDP只有控制响应，不会自动提供IQ流；PL计数器增长也不能代替接收信号存在性证明。

### 6.3 通过、失败与证据保存

- 先保存当前固件hash、采样率、带宽、LO读回、端口选择、增益、衰减和DC跟踪状态。记录ADDA实际100 MHz输出谱与LDSDR输入端功率，避免把源端未正确产生100 MHz误判成接收板不支持。
- 在至少两个小步频率和三个输入电平上重复：开源时出现目标峰、关源/断开并端接时消失；输入电平改变10 dB时未压缩区输出变化接近10 dB。固定MGC以便比较，不能让AGC掩盖幅度关系。
- 有低频源谐波/DAC镜像时，应确认输入频率变化Δf后目标峰变化Δf。若变化为2Δf/3Δf等，应排查谐波混频；不能凭一个峰判断收到100 MHz基波。
- 先查PLL配置/锁定与校准返回，再查RF输入路径、RX IQ、PL输出IQ、2450 MHz RF，逐段定位。不能把“读回100 MHz、但无信号”直接归因于芯片最低频率。
- 单音通过后，建议以1000个已知短帧做第一阶段记录，期望无CRC失败和载荷错误，并记录时长、每帧长度、SNR/误差指标。此数量是演示验收建议，不是严谨BER保证；可靠性目标另行定义。
- 若100 MHz失败而已知在规格内的对照频点成功，应检查输入匹配/扩展模式性能，再评估约350 MHz直连候选或具体外部变频方案。没有该对照证据前不直接下购买结论。

## 7. 研究范围和未解决事项

已读：LDSDR与UDP工程的设备选择、驱动限频/产品ID/本振设置读回、DC跟踪与PL DC路径；历史原理图关键文本和溯源脚本；最终UDP日志/manifest；历史交接射频/短帧段落；项目图片清单及根目录手绘照片。官方阅读AD9361 Rev.G频段、AD9363 Rev.D规格/本振/极限/订货表、UG-570的DC跟踪与RF匹配章节、ADI Pluto扩展说明。

仍未知：实物RF封装完整丝印及对应BOM、当前实装巴伦型号、100 MHz下板级匹配与噪声/动态范围、ADDA实际100 MHz输出质量、可用于2450 MHz输出验收的测量设备。上述未知属于待取证事项，不改变“用户一直使用同一块LDSDR”的事实。

## 8. 用户现有条件与首轮实施收敛

本报告初稿后，用户补充：两板已供电，SMA尚未互连；只有两根普通短SMA线，无衰减器、仪器或第三块板。主agent另已得到LDSDR的JTAG目标 `0ABC01A / xc7z010` 和COM13；这是主agent本轮取证，本研究agent没有访问硬件。

因此第6节的仪器流程应分级实施：**先ADDA DAC1→LDSDR RX1，用LDSDR现有ILA观察接收IQ，暂不需要第二根SMA线。** ADDA测试位流由其他agent准备默认静音和不超过1/128数字幅度的限制。若厂家1.2 Vpp满幅和50 Ω端接条件成立，1/128幅度对应约9.375 mVpp、约-36.58 dBm；这只是设计预算，仍须确认DAC路径没有额外增益或绕过限制的内部测试源，不能称为已校准电平。

如果随后接LDSDR TX1→ADDA ADC1做局部环回，LDSDR先大衰减，并把返回载频放在ADDA已验证可接收的范围。它能进一步验证转发与回读，但**不能借此宣称2450 MHz输出已测通过**。当LDSDR RX LO和TX LO相同时还需按驱动正常设置路径处理校准；源码 `ad9361.c:6825` 对FDD中相同LO的VCO pulling已有专门表选择逻辑，不应只直接改寄存器跳过驱动。

### 实物端口位置证据

- 当前本机没有找到可辨认该LDSDR实物RF芯片及SMA丝印的照片。根目录历史JPG是纸上链路图；`fpga_sdr_project` 中docx的8张内嵌媒体经SHA256核对均与其 `figs/` 或 `ccsds_ttc_loopback/docs/figs/` 的报告插图一致，不是新增的实物照片。
- `fpga_sdr_project/项目交接文档.md:35` 只说明第一组是RX1+TX1，`56` 行写RX1→TX1，没有“左上/右上/上下排列”的证据。逻辑端口名可确认，物理方位不可据此猜测。
- `LDSDR_010/make_ttc_report.py:202–208` 所称TCM1-63AX+巴伦明确位于历史“遥测板硬件”章节，不能跨归属当作LDSDR的已核实物料。当前7010资料包照片也不用于替代LDSDR实物接线图。
- 实际接线必须以该实物清晰的RX1/TX1丝印或对应实物照片为准。没有这些证据时，研究侧无法给出准确的“第几个/哪个方向”的接头位置。

### 既有ILA可观测点

静态读取 `LDSDR_010/zynq_dev_fmcomms3.runs/impl_2/ad9361_top.ltx`：ILA实例 `inst_design_1_wrapper/design_1_i/ila_0`，UUID `BC5517451F915CD9B468EF63D7F10767`。主agent使用时需核对其与已加载bitstream匹配。

| probe | 网络 | 用途 |
| --- | --- | --- |
| 1 | `ad9361_phy_0_adc_d1q1_valid` | RX1样点有效 |
| 4 / 5 | `ad9361_phy_0_adc_data_d1 / adc_data_q1`，12 bit | RX1原始I/Q |
| 2 | `ad9361_phy_0_adc_d2q2_valid` | RX2样点有效 |
| 6 / 7 | `ad9361_phy_0_adc_data_d2 / adc_data_q2`，12 bit | RX2原始I/Q，可辅助排查物理通道映射 |
| 0 | `relay_dq_0_dac_valid` | TX样点有效 |
| 8 / 9 | `relay_dq_0_dac_data_d1 / dac_data_q1`，12 bit | TX1数字输出 |
| 10 / 11 | `relay_dq_0_dac_data_d2 / dac_data_q2`，12 bit | TX2数字输出 |

LTX只证明探针定义存在，不证明当下已加载硬件有相同核心；采样导出应按相应valid筛选，不能把ILA时钟频率直接当成IQ样率。第一线验证保存源开/关与频移对照的IQ，比直接接第二线后仅观察波形更能定位100 MHz输入是否真正收到。

