"""check_frame_gen.py -- 验证 frame_gen 的多帧组帧结果与软件参考逐字节一致。

输入: E:\\ccsds_fpga\\sim\\out\\frame_gen_dut.txt
      每行一帧，40 个空格分隔的十六进制字节（byte0 在前）
      （由 sim/bench/tb_frame_gen2.vhd 导出）

判据（全部必须通过）：
  1. 每帧 40 字节 == Python build_tm_frame(...)  逐字节（含 FECF）
  2. 每帧 FECF 单独复算一致
  3. 每帧头字段（SCID/VCID/OCF/sec_hdr/FHP/MCFC/VCFC）解析正确
  4. MCFC / VCFC 逐帧 +1（真实遥测的必要条件）

退出码 0 = PASS。
"""
import os
import sys

sys.path.insert(0, r"E:\fpga_sdr_project\ccsds_ttc_loopback\sw\ttc")
from ccsds_tm_tx import build_tm_frame, crc16, parse_tm_frame

DUMP = r"E:\ccsds_fpga\sim\out\frame_gen_dut.txt"
PAY_BYTES = 32

# 必须与 tb_frame_gen2.vhd 的 STIM 逐项对应
CASES = [
    dict(scid=0x2A,  vcid=0, ocf=0, sec_hdr=0, fhp=0x000, mode=0),
    dict(scid=0x2A,  vcid=0, ocf=0, sec_hdr=0, fhp=0x000, mode=1),
    dict(scid=0x155, vcid=5, ocf=1, sec_hdr=1, fhp=0x123, mode=2,
         fhp_only=True),
]
# fhp_only=True 的用例：软件参考 build_tm_frame() 把 w56 的 FHP 位域硬编码为 0，
# 因此不能与它逐字节比对；该用例改用【独立位域断言】（见下）。
# 其余字段（SCID/VCID/OCF/副头/MCFC/VCFC/载荷/FECF）仍然全部校验。


def payload_for(mode):
    if mode == 0:
        return bytes((i + 1) & 0xFF for i in range(PAY_BYTES))
    if mode == 1:
        return bytes([0xA5] * PAY_BYTES)
    return bytes(i & 0xFF for i in range(PAY_BYTES))


if not os.path.exists(DUMP):
    print("  [FAIL] %s 不存在（先跑 run_sim.ps1 -Tb tb_frame_gen2）" % DUMP)
    sys.exit(1)

lines = [l.split() for l in open(DUMP) if l.strip()]
rows = [bytes(int(x, 16) for x in ln) for ln in lines]

fail = 0
print("  帧数: 期望 %d, 实测 %d" % (len(CASES), len(rows)))
if len(rows) != len(CASES):
    print("  [FAIL] 帧数不符"); fail += 1

for c, cfg in enumerate(CASES):
    mcfc, vcfc = c, c                      # frame_gen 每帧 +1，从 0 起
    # ocf / sec_hdr 必须传给参考实现，否则 w0 的 OCF 位与 w56 的副头位会差一拍
    exp = build_tm_frame(scid=cfg["scid"], vcid=cfg["vcid"],
                         mcfc=mcfc, vcfc=vcfc,
                         data=payload_for(cfg["mode"]),
                         fecf=True,
                         ocf=bool(cfg["ocf"]),
                         sec_hdr=bool(cfg["sec_hdr"]))
    print()
    print("  --- case %d ---" % c)
    print("    cfg      : SCID=0x%X VCID=%d OCF=%d sec=%d FHP=0x%03X mode=%d"
          % (cfg["scid"], cfg["vcid"], cfg["ocf"], cfg["sec_hdr"], cfg["fhp"], cfg["mode"]))
    if c >= len(rows):
        print("    [FAIL] 该帧缺失"); fail += 1; continue
    dut = rows[c]
    print("    expected : %s" % exp.hex())
    print("    VHDL     : %s" % dut.hex())
    if len(exp) != len(dut):
        print("    [FAIL] 长度 %d != %d" % (len(exp), len(dut))); fail += 1; continue
    if cfg.get("fhp_only"):
        # 独立位域断言（不依赖软件参考的 FHP 处理）
        w0  = int.from_bytes(dut[0:2], "big")
        w56 = int.from_bytes(dut[4:6], "big")
        chk = []
        chk.append(("w0 版本=0",        (w0 >> 14) & 0x3 == 0))
        chk.append(("w0 SCID=0x%X" % cfg["scid"], (w0 >> 4) & 0x3FF == cfg["scid"]))
        chk.append(("w0 VCID=%d" % cfg["vcid"],   (w0 >> 1) & 0x7 == cfg["vcid"]))
        chk.append(("w0 OCF=%d" % cfg["ocf"],     w0 & 0x1 == cfg["ocf"]))
        chk.append(("w56 副头=%d" % cfg["sec_hdr"], (w56 >> 15) & 0x1 == cfg["sec_hdr"]))
        chk.append(("w56 同步=0",       (w56 >> 14) & 0x1 == 0))
        chk.append(("w56 包序=0",       (w56 >> 13) & 0x1 == 0))
        chk.append(("w56 段长=11b",     (w56 >> 11) & 0x3 == 0b11))
        chk.append(("w56 FHP=0x%03X" % cfg["fhp"], w56 & 0x7FF == cfg["fhp"]))
        chk.append(("MCFC=%d" % mcfc,   dut[2] == mcfc))
        chk.append(("VCFC=%d" % vcfc,   dut[3] == vcfc))
        bad = [n for n, ok in chk if not ok]
        for n, ok in chk:
            print("    %s 位域 %s" % ("[PASS]" if ok else "[FAIL]", n))
        if bad:
            fail += 1
    elif exp == dut:
        print("    [PASS] 40 字节逐字节一致（含 FECF）")
    else:
        d = [i for i in range(len(exp)) if exp[i] != dut[i]]
        print("    [FAIL] %d 处不同，首个 @ byte %d (exp=%02x dut=%02x)"
              % (len(d), d[0], exp[d[0]], dut[d[0]]))
        fail += 1
    # FECF
    rx = int.from_bytes(dut[-2:], "big"); cc = crc16(dut[:-2])
    if rx != cc:
        print("    [FAIL] FECF rx=0x%04X calc=0x%04X" % (rx, cc)); fail += 1
    else:
        print("    [PASS] FECF 0x%04X" % rx)
    # 头字段 + MCFC/VCFC 递增
    p = parse_tm_frame(dut)
    ok = (p and p["scid"] == cfg["scid"] and p["vcid"] == cfg["vcid"]
          and p["mcfc"] == mcfc and p["vcfc"] == vcfc and p["crc_ok"]
          and p["payload"] == payload_for(cfg["mode"]))
    if ok:
        print("    [PASS] 头字段解析正确, MCFC=%d VCFC=%d (逐帧 +1)" % (p["mcfc"], p["vcfc"]))
    else:
        got = ("SCID=0x%X VCID=%d MCFC=%d VCFC=%d" % (p["scid"], p["vcid"], p["mcfc"], p["vcfc"])) if p else "解析失败"
        print("    [FAIL] 头字段不符: %s" % got); fail += 1

print()
print("  RESULT: %s" % ("PASS" if fail == 0 else "FAIL"))
sys.exit(1 if fail else 0)
