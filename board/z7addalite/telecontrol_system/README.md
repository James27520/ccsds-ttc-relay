# 遥控 PL 冻结输入 r4c

本目录仅保存重建输入：`src/`、`constraints/`、`abi/`、`scripts/`、`vendor/` 和 `sim/*.sv`，硬件输入（RTL、XDC、ABI、BD、testbench）与冻结 r4c 对应文件逐字节相同，列在 `SOURCE_MANIFEST.json`。仓库版 AXIL/PN9、冻结构建/采集/导出 runner 及 fixture 生成器已单独改为可迁移入口，支撑文件列在 `REPRO_MANIFEST.json`；两份清单不混用；仓库 runner 的显式修改不包含在冻结硬件 hash 中。未包含原始 CSV 或历史报告。目标器件 `xc7z020clg484-2`。r4c完整M2已通过临时JTAG上板的全通道/四个k内部测试快照验证；normal仅完成格式和切换检查，未接外部信号。

最终实现WNS/WHS/WPWS=+0.483/+0.022/+0.264 ns，TNS/THS/TPWS=0，DRC=0；56条ADC输入路径齐全，198个动态mailbox端点全部具有有效20 ns约束、最差余量18.128 ns。CDC-10/12复位置位与8级释放链、CDC-11保持bundle合并位已人工复核；具体理由与板端边界见 [验证记录](../../../docs/validation.md)。

在仓库根目录，以 PowerShell 调用：

```powershell
$env:VIVADO_BIN = '<Vivado安装目录>\bin'
pwsh -File board/z7addalite/telecontrol_system/scripts/run_frozen_build.ps1 -RunName r4c_rebuild -OutputRoot C:\fpga_build
```

需要 Vivado 2026.1，`VIVADO_BIN` 必须包含 `vivado.bat`、`xvlog.bat`、`xelab.bat`、`xsim.bat`。也可显式传 `-VivadoBin <目录>`；未设置环境变量或参数时从 PATH 查找工具，缺失则明确报错。`OutputRoot` 必须为纯 ASCII 路径，`RunName` 仅可包含英文字母、数字、下划线或连字符，且对应目录不得已存在。脚本把构建输入及归档的 PN9 fixture/参考模块复制到 `OutputRoot/RunName`，因此可从中文仓库路径启动，在 ASCII 工作目录实际构建。

入口依次运行不依赖外部 CSV 的 `run_capture_sim.ps1` 合成采集回归、平台 BD 创建、综合、布局布线和 signoff 检查；每阶段检查冻结输入 SHA256。输出位于该运行目录的 `build/`、`reports/` 等目录。它不自动执行 bitstream 导出；审阅路由后证据及清单后，才在输出运行目录调用 `scripts/export_reviewed.ps1 -Reviewed`（工具定位同样支持 `-VivadoBin`、环境变量或 PATH），生成 `artifacts/` 的最终 bit/XSA/ps7_init 及清单。构建或导出均不代表硬件验收。

`run_capture_sim.ps1` 可在复制后的 ASCII 工作目录单独执行，支持 `-VivadoBin`、`VIVADO_BIN` 或 PATH。`run_config_runtime.ps1` 使用显式 `-VivadoBin <目录>`。不要在冻结构建运行目录重新生成 ABI 或修改输入，否则清单检查将失败。

独立 AXIL/PN9 回归在仓库根目录运行：

```powershell
pwsh -File board/z7addalite/telecontrol_system/scripts/run_axil_sim.ps1 -VivadoBin '<Vivado安装目录>\bin'
pwsh -File board/z7addalite/telecontrol_system/scripts/pn9_run_sim.ps1 -VivadoBin '<Vivado安装目录>\bin' -Python python -UseFrozenFixtures
```

两个入口支持 `-VivadoBin` / `VIVADO_BIN`，未指定时从 PATH 查找 `xvlog.bat`；不再默认个人安装路径。`-OutputRoot <新ASCII目录>` 可指定输出，默认在系统临时目录创建唯一子目录，将仿真输入复制后执行。PN9 的 `-Python` 默认读取 `PYTHON` 或使用 PATH 的 `python`，只依赖 Python 标准库。

`sim/pn9_fixtures/pn9_real_00..02.mem` 保存三份历史实测 CSV 的 112-bit captured_words，每份 4096 行、122880 字节；`sim/pn9_fixtures/pn9_fixture_manifest.json` 保留原 CSV SHA256、fixture SHA256、诊断值与抽取方法。默认 `-UseFrozenFixtures` 逐项校验并复用 `sim/pn9_fixtures/` 的五份 mem（3 份实际捕获派生输入、合成输入、511 状态递推输入），无需旧 CSV、分析器或 ADI 方程模块参与执行；这是离线重放，不是新实测。`scripts/analyze_adc_pn9.py` 保留原分析器，新增 CSV 校验可运行 `python scripts/pn9_generate_fixtures.py --output <目录> --capture <00.csv> --capture <01.csv> --capture <02.csv>`（从本目录），检查 CSV 来源 SHA、诊断/ready/计数连续性、PN9/checker 及抽取结果一致。历史输入来源是内部 PN9/checker，不能证明当前候选的模拟输入或正常模式接收。

`reference/axi_ad9643_pnmon_2016_r1.v` 为字节不变的 ADI 参考模块，完整保留原版权、许可证与免责声明。可选重生成器验证其 SHA256 后提取独立 30-bit PN9 方程，重新生成全 511 非零状态和 4096 组合成向量；传 `-UseFrozenFixtures:$false` 可在 runner 中启用这一流程，真实捕获部分仍复用校验过的归档输入。RTL/testbench 未修改。更新 r4c 前的仓库版 PN9 回归通过 45288 assertions、23 acquisitions、3 份历史捕获及合成故障/模式测试；AXIL 回归通过 4740 checks、202 accepted writes、65536 RAM words。主冻结构建仍只自动调用 capture 回归；需要完整回归时另运行这两个入口。

本次 r4c 归档已在临时 ASCII 工作目录以 Vivado 2026.1 重跑独立采集合成回归：`PASS CAPTURE checks=786634 full_captures=4 samples=524288`，覆盖 overflow/epoch/clockstop/abort/late_last/rearm；不涉及真实 ADC 或网络。

依赖与来源：`vendor/zynq_petaLinux.bd` 为已有厂商 PS7 BD（记录原工具版本 2018.3），由 `create_platform.tcl` 导入并添加 AXI 互连。构建依赖 Vivado 的 Processing System 7、SmartConnect、Clocking Wizard、ILA、XPM 及仿真库。该 BD 未附独立许可证或上游来源说明，后续分发前需补充来源与许可记录；这里不推断其授权范围。PN9 RTL 注释引用 ADI `hdl_2016_r1 axi_ad9643_pnmon.v` 的打包约定，参考模块及来源 URL/SHA 已归档；使用约束见其文件头，分析器仅使用 Python 标准库。

`.gitattributes` 禁用本板归档文件的自动换行转换，以便 Git checkout 后仍可核对逐字节 SHA256。
