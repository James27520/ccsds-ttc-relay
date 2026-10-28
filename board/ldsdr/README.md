# LDSDR业务转发：RX IQ默认修正与诊断补丁

本目录维护针对已知原UDP构建的源码补丁、新增头文件、链接脚本及离线测试。
不包含ELF、obj、完整厂商工程或BSP，**不是独立clean build**。
硬件对象为转发板LDSDR（7010_rev3.1），不是发送板7010_AD9363_SDR。
根目录重建入口保留原固定镜像；新增[remote_control](remote_control/README.md)单独构建有限租期镜像，
配合Z7ADDALite与GUI的扩展启停/查询协议使用。新镜像的CLI限制、改频后静音行为与原固定镜像不同，
不可混用操作步骤，实板范围见[本轮验证](../../docs/remote-relay-validation.md)。

## 基线与改动

外部完整UDP构建缓存的`relay_udp.elf`基线SHA256：

```text
c37843bf31165e12124d267f1104f2e5fb22ab1121dfeae22122d8a3bd9183cd
```

`baseline.json`固定原始源文件、复用网络obj、libxil、BSP xparameters，以及补丁、
新增头文件、链接脚本和目标源码的校验和；不匹配即拒绝构建。
`relay_fixed.patch`使用`a/src/...`、`b/src/...`路径，保留原版权文本，应用时严格匹配上下文。
新增头文件单独位于`headers/`，便于审查，不需要另一个probe工作目录。
本目录`.gitattributes`对参与字节校验的补丁、头文件和链接脚本保留原始换行，避免Git自动转换使校验失效。

默认只把`pp_rx_swap_enable`改为0，TX保持1。相对原UDP版本，另保留已验证的
SPI传输错误传播、失败读回防护、安全启动和诊断功能：

- main首个PL操作写mode2；初始化明确设置TX1/TX2均89000mdB、RX增益0，最后保持mute。
- `rfdiag`独立SPI读取0x010/011/012、PLL频率/锁、两RX增益、两TX衰减、BIST/loopback及SPI错误。
- `iqswap rx|tx 0|1`仅在mode2、两TX实际衰减均≥30000mdB时允许；仅RMW0x010的bit6或bit7，
  完整字节回读后更新相应driver缓存位，失败尝试回滚并保持mute。SPI故障时回滚也可能失败，须复查诊断。
- 原`relay_udp.h`、`relay_rf_packet.h`、`relay_rf_control.h`逐字节保留，UDP5005及原地址不变。
  上电静音不代表以后CLI/UDP不能开启或修改RF；互斥控制仍由实验流程负责。

RX0/TX1修正依据是隔离r2固件的有线频谱对照；任何硬件验收均应关联实际加载ELF的hash。
本构建入口不访问硬件、不加载bit、不写SD/Flash，也不自动发射。

## 外部依赖与重建

`--base`指向完整原UDP构建缓存，至少包含原`src/`、`include/`、`lib/libxil.a`、
`obj/`、`generated/`、`deps/ThirdParty/sw_services/lwip202/`、`Xilinx.spec`、
`build_manifest.json`和原`relay_udp.elf`。这些来自对应2018.3厂商BSP及lwIP移植，
复用obj须与匹配的BSP/编译ABI一致。Python仅使用标准库；还需ARM hard-float工具链及native C编译器。
主仓库不复制机器专属大obj。若需完全从零重建，必须另外提供有版本约束的厂商SDK、硬件导出、
BSP生成过程和网络源文件选择；本目录没有声称已经实现这些步骤。

```powershell
python -B board/ldsdr/rebuild.py --base '<完整原UDP构建目录>' --out '<新的外部输出目录>' --host-cc '<本机native-gcc路径>'
# ARM编译器默认读取base/build_manifest.json中的gcc；跨机器可追加：
# --compiler '<匹配ARM编译器路径>'
```

入口沿用隔离fixed构建的编译/链接参数，先校验基线，再复制源至**新的**输出目录、应用补丁、
编译修改源并复用基线网络obj/BSP。所有ELF、obj、日志、manifest及测试结果只写入该输出目录；
拒绝已有输出目录，拒绝在基线或本源码包内输出。不会调用Git、串口、JTAG或网络。

构建自动运行六组native故障注入：双侧/双值及其他位保持、mode和实际衰减门槛、SPI错误、
读回不符/部分写失败回滚、回滚失败与无效输入、修正默认值的可逆诊断。
还校验目标源码、UDP不变、启动首写mute、默认TX1/RX0、链接UDP符号、全部LOAD边界和页表映射，
并比较参考fixed镜像的各LOAD布局与运行时载荷hash。
`offline_verification.json`只表示离线通过。继承的编译警告、原裸机RWX段等会留在日志及验证结果中。

## 地址窗与暖加载限制

`relay_fixed.ld`把完整镜像限制在`0x04000000..0x043FFFFF`；参考布局MMUTable在`0x04028000`，
末端栈`0x0439B530`。实际基线BSP的DDR地址窗是`0x00100000..0x1FFFFFFF`（512MiB配置），
不是1GiB。离线检查确认目标范围与BSP identity映射相容，避开已知r2页表`0x02028000`。

这**不是任意运行环境的暖加载安全保证**。历史r1加载后出现无启动日志和调试APB恢复问题，
其LOAD范围与旧ELF中的页表地址重叠；故障前实际TTBR未取得，因此页表覆盖是高风险候选原因，尚非确定根因。
加载前仍须在精确目标上读取实际TTBR及其表范围，核对LOAD不覆盖活动页表，并处理已知缓存/中断状态。
不要把entry固定、XSDB返回成功或本地页表检查当作板端启动成功。

## 此入口的离线重建记录

本机向新目录`portable_rebuild`成功重建，目标源码与隔离fixed逐字节相同，六组native测试通过；
所有运行时LOAD布局及载荷hash与fixed相同。ELF全文件hash因源码/DWARF路径改变而不同：

```text
参考fixed: 2fed9cd6927a2b364217741d6a02a7219ad582735ccf01b8d7c8f9bf4c50ee06
重建ELF:   bde12cef50ae4ea58f720d23c3d6de41c4415b030987d6fae104717a8b292025
```

完整构建命令和产物hash由输出目录manifest记录；原UDP/r1/r2/fixed镜像均未修改。
