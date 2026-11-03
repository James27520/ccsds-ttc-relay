# 早期RTL仿真工具

本目录保留早期7010/AD936X链路的CCSDS编码、随机化和环回实验，不是当前双电脑桌面站的启动目录。

若干PowerShell、Python及testbench仍硬编码原开发机的 `E:\ccsds_fpga`，仿真还依赖对应工具版本、工作库和输入文件。源码在此保留供追溯，不据此宣称克隆仓库后可以直接运行全部旧仿真。

当前验证入口：

- [ADDA采集PL](../board/z7addalite/telecontrol_system/README.md)
- [ADDA下行PL](../board/z7addalite/telemetry_downlink/README.md)
- [LDSDR转发PL与NCO验证](../board/ldsdr/pl/README.md)
- [LDSDR业务补偿](../board/ldsdr/doppler/README.md)
- [桌面站使用](../docs/two-computer-guide.md)

修改旧仿真环境时应在独立输出目录工作，先核对源文件、工具及输出路径；旧实验结果的范围见[历史验证记录](../docs/legacy-validation.md)。
