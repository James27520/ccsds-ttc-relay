"""check_lfsr_vhdl.py -- 比对 VHDL 仿真导出的 LFSR 序列与 Python 参考实现。

输入: E:\\ccsds_fpga\\sim\\out\\lfsr_bits.txt
      由 sim/bench/tb_lfsr.vhd 导出，每行一个 16 bit 无符号十进制字，
      MSB-first（即 dat_o 的最高 16 位在前）。

判据: 160 bit 逐位一致 + 命中 CCSDS 标准前 40 bit。
退出码 0 = PASS。
"""
import os
import sys
sys.path.insert(0, r"E:\fpga_sdr_project\ccsds_ttc_loopback\sw\ttc")

from ccsds_tm_tx import rand_seq, LFSR_REFERENCE_40

DUMP = r"E:\ccsds_fpga\sim\out\lfsr_bits.txt"

if not os.path.exists(DUMP):
    print("  [FAIL] 找不到 %s（先跑 run_sim.ps1 -Tb tb_lfsr）" % DUMP)
    sys.exit(1)

words = [int(l.strip()) for l in open(DUMP) if l.strip()]
fpga = []
for w in words:
    for k in range(15, -1, -1):
        fpga.append((w >> k) & 1)

n = len(fpga)
py = list(rand_seq(n))

print("  VHDL 导出 : %d bit (%d 个 16 bit 字)" % (n, len(words)))
print("  前 6 字节 : %s" % " ".join("%02X" % w for w in
      [sum(fpga[i * 8 + k] << (7 - k) for k in range(8)) for i in range(min(6, n // 8))]))
print("  前 40 bit : %s" % "".join(map(str, fpga[:40])))
print("  Python    : %s" % "".join(map(str, py[:40])))

fail = 0
if fpga == py:
    print("  [PASS] VHDL 与 Python 逐位一致 (%d bit)" % n)
else:
    d = [i for i in range(n) if fpga[i] != py[i]]
    print("  [FAIL] 有 %d 处不一致，首个 @ bit %d" % (len(d), d[0]))
    fail += 1

if "".join(map(str, fpga[:40])) == LFSR_REFERENCE_40:
    print("  [PASS] 命中 CCSDS 标准前 40 bit")
else:
    print("  [FAIL] 未命中标准序列")
    fail += 1

print()
print("  RESULT: %s" % ("PASS" if fail == 0 else "FAIL"))
sys.exit(1 if fail else 0)
