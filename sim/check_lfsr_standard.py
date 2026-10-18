"""check_lfsr_standard.py -- 验证 Python 参考实现的随机化序列是 CCSDS 131.0-B 标准序列。

判据:
  1) 前 40 bit == LFSR_REFERENCE_40
  2) 周期 == 255
  3) 前 6 字节 (MSB-first 打包) == FF 48 0E C0 9A 0D
  4) 逐位手工复算一致（独立于 rand_seq 的实现）

退出码 0 = PASS。
"""
import sys
sys.path.insert(0, r"E:\fpga_sdr_project\ccsds_ttc_loopback\sw\ttc")

from ccsds_tm_tx import (rand_seq, RAND_POLY, RAND_POLY_LFSR, RAND_SEED,
                         LFSR_REFERENCE_40)

fail = 0

print("  数学多项式 (文档用) RAND_POLY      = 0x%02X  (taps {0,3,5,7})" % RAND_POLY)
print("  实装 LFSR 掩码      RAND_POLY_LFSR = 0x%02X  (taps {0,2,4,7}, = 0x%02X 位翻转)"
      % (RAND_POLY_LFSR, RAND_POLY))
print("  初值 = 0x%02X" % RAND_SEED)

# 1) 前 40 bit + 前 6 字节
seq = rand_seq(48)
head = "".join(map(str, seq[:40]))
packed = bytearray()
for i in range(6):
    v = 0
    for k in range(8):
        v = (v << 1) | int(seq[i * 8 + k])
    packed.append(v)
print("  前 40 bit : %s" % head)
print("  参考      : %s" % LFSR_REFERENCE_40)
if head == LFSR_REFERENCE_40:
    print("  [PASS] 前 40 bit 命中标准序列")
else:
    print("  [FAIL] 前 40 bit 与标准序列不符"); fail += 1

print("  前 6 字节 : %s" % packed.hex(' ').upper())
if packed.hex().upper() == "FF480EC09A0D":
    print("  [PASS] 前 6 字节 = FF 48 0E C0 9A 0D")
else:
    print("  [FAIL] 前 6 字节不匹配"); fail += 1

# 2) 周期（用全长比对，避免自己跟自己比的假阳性）
long_seq = rand_seq(510)
period = next((k for k in range(1, 255)
               if all(long_seq[i] == long_seq[i % k] for i in range(510))), 255)
print("  周期 : %d" % period)
if period == 255:
    print("  [PASS] 周期 = 255")
else:
    print("  [FAIL] 周期应为 255，实测 %d（错序列的周期是 217）" % period); fail += 1

# 3) 手工独立复算
s = RAND_SEED
man = []
for _ in range(48):
    man.append((s >> 7) & 1)
    fb = ((s >> 0) ^ (s >> 2) ^ (s >> 4) ^ (s >> 7)) & 1
    s = ((s << 1) | fb) & 0xFF
if man == list(seq[:48]):
    print("  [PASS] 手工复算与 rand_seq 一致")
else:
    print("  [FAIL] 手工复算不一致"); fail += 1

print()
print("  RESULT: %s" % ("PASS" if fail == 0 else "FAIL"))
sys.exit(1 if fail else 0)
