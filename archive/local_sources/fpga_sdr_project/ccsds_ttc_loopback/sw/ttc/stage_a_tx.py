#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stage_a_tx.py -- 阶段 A：把 CCSDS 遥测通过遥测板发出去

流程
----
  电脑 (Python+numpy)
      生成 TM 传输帧 -> 随机化 -> 卷积编码 -> ASM -> BPSK -> SRRC
      -> I/Q int16 文件
          |  scp
          v
  遥测板 (有 iio_writedev，没有 python)
      iio_writedev -u ip:localhost ... < wave.bin

用法
----
    python stage_a_tx.py build              # 只生成波形文件 + 打印参数
    python stage_a_tx.py send               # 生成 + 上传 + 发射
    python stage_a_tx.py send --lo 1000 --att 30 --if 200
    python stage_a_tx.py selfcheck          # 板上自收自环（需要 TX->RX 短接）
"""
import argparse
import os
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ccsds_tm_tx as C

BOARD = "192.168.2.1"
KEY = r"C:\Users\23638\.ssh\id_ed25519_dsh"
WAVE = os.path.join(HERE, "cadu_wave.bin")

SSH = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no",
       "-o", "UserKnownHostsFile=NUL", "-o", "BatchMode=yes",
       "-o", "ConnectTimeout=10", "root@" + BOARD]
SCP = ["scp", "-O", "-i", KEY, "-o", "StrictHostKeyChecking=no",
       "-o", "UserKnownHostsFile=NUL", "-o", "BatchMode=yes"]


def sh(cmd, timeout=180):
    r = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True,
                       timeout=timeout)
    return ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace").strip()


def ssh(cmd, timeout=180):
    return sh(SSH + [cmd], timeout)


def ssh_many(cmds, wait=1.0):
    out = []
    for c in cmds:
        out.append("  $ %-56s -> %s" % (c, ssh(c, 40).replace("\n", " | ")[:70]))
        time.sleep(wait)
    return out


def build_wave(fs, sym_rate, if_hz, n_frames, payload_bytes):
    """生成 n_frames 个连续 TM 帧的 I/Q 波形"""
    frames = b""
    for i in range(n_frames):
        payload = bytes(((i * 7 + j) & 0xFF) for j in range(payload_bytes))
        frames += C.build_tm_frame(scid=0x2A, vcid=0,
                                   mcfc=i & 0xFF, vcfc=(i >> 8) & 0xFF,
                                   data=payload)
    cadu, info = C.build_cadu(frames)
    I, Q = C.cadu_to_iq(cadu, fs=fs, sym_rate=sym_rate, if_hz=if_hz)
    stream = C.iq_interleave(I, Q)
    stream.tofile(WAVE)

    print("  帧数      = %d  (每帧 %d 字节)" % (n_frames, 6 + payload_bytes + 2))
    print("  总数据    = %d 字节" % len(frames))
    print("  CADU      = %d 比特" % len(cadu))
    print("  样点      = %d  (%.1f ms)" % (len(I), len(I) / fs * 1e3))
    print("  文件      = %s  (%d 字节)" % (WAVE, os.path.getsize(WAVE)))
    print("  I 范围    = [%d, %d]   std=%.1f" % (I.min(), I.max(), I.std()))
    print("  fs        = %.3f MSPS" % (fs / 1e6))
    print("  符号率    = %.1f ksym/s" % (sym_rate / 1e3))
    print("  过采样    = %d 样点/符号" % int(round(fs / sym_rate)))
    print("  中频      = %+.1f kHz" % (if_hz / 1e3))
    return len(I), len(cadu)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["build", "send", "selfcheck", "stop"])
    ap.add_argument("--lo", type=float, default=1000.0, help="TX_LO MHz")
    ap.add_argument("--att", type=int, default=30, help="TX 衰减 dB")
    ap.add_argument("--gain", type=int, default=30, help="RX 增益 dB")
    ap.add_argument("--if", dest="if_hz", type=float, default=200.0,
                    help="基带中频 kHz")
    ap.add_argument("--fs", type=float, default=2.5, help="采样率 MSPS")
    ap.add_argument("--sym", type=float, default=250.0, help="符号率 ksym/s")
    ap.add_argument("--frames", type=int, default=200, help="帧数")
    ap.add_argument("--payload", type=int, default=100, help="每帧数据字节")
    ap.add_argument("--reps", type=int, default=8, help="重复发送次数")
    args = ap.parse_args()

    fs = args.fs * 1e6
    sym = args.sym * 1e3
    if_hz = args.if_hz * 1e3

    print("%s" % ("═" * 70))
    print("  阶段 A —— CCSDS 遥测经遥测板发射")
    print("%s\n" % ("═" * 70))

    print("[1] 生成波形")
    nsamp, ncadu = build_wave(fs, sym, if_hz, args.frames, args.payload)

    print("\n[2] 板子连通性")
    print("  " + ssh("echo BOARD_OK; iio_attr -V 2>/dev/null | head -1")[:120])

    if args.action == "build":
        print("\n只生成，未发送。波形文件: %s" % WAVE)
        return 0

    print("\n[3] 上传波形到板子")
    r = sh(SCP + [WAVE, "root@%s:/tmp/wave.bin" % BOARD], timeout=300)
    if r:
        print("  scp: %s" % r[:200])
    sz = ssh("wc -c < /tmp/wave.bin")
    print("  板子上大小 = %s  (本地 %d)  %s"
          % (sz, os.path.getsize(WAVE),
             "✅" if sz.strip() == str(os.path.getsize(WAVE)) else "⚠️ 不一致"))

    if args.action == "stop":
        print("\n停止发射")
        print("  " + ssh("iio_attr -c cf-ad9361-dds-core-lpc altvoltage0 scale 0; "
                         "iio_attr -c cf-ad9361-dds-core-lpc altvoltage1 scale 0; echo DDS_OFF"))
        return 0

    print("\n[4] 配置遥测板（本机 ip: 后端）")
    U = "-u ip:localhost"
    for c in [
        "iio_attr %s -c ad9361-phy altvoltage1 frequency %d" % (U, int(args.lo * 1e6)),
        "iio_attr %s -c ad9361-phy voltage0 sampling_frequency %d" % (U, int(fs)),
        "iio_attr %s -c ad9361-phy voltage0 rf_bandwidth 1000000" % U,
        "iio_attr %s -c ad9361-phy voltage1 rf_bandwidth 1000000" % U,
        "iio_attr %s -i -c ad9361-phy voltage0 gain_control_mode manual" % U,
        "iio_attr %s -i -c ad9361-phy voltage0 hardwaregain %d" % (U, args.gain),
        "iio_attr %s -i -c ad9361-phy voltage1 gain_control_mode manual" % U,
        "iio_attr %s -i -c ad9361-phy voltage1 hardwaregain %d" % (U, args.gain),
        "iio_attr %s -o -c ad9361-phy voltage1 hardwaregain -%d" % (U, args.att),
        "iio_attr %s -c cf-ad9361-dds-core-lpc altvoltage0 scale 0" % U,
        "iio_attr %s -c cf-ad9361-dds-core-lpc altvoltage1 scale 0" % U,
    ]:
        for line in ssh_many([c]):
            print(line)

    print("\n  回读:")
    for k, c in (("TX_LO", "altvoltage1 frequency"), ("采样率", "voltage0 sampling_frequency"),
                 ("TX衰减", "voltage1 hardwaregain")):
        v = ssh("iio_attr %s -c ad9361-phy %s 2>&1 | tail -1" % (U, c))
        print("    %-8s %s" % (k, v[:60]))

    print("\n[5] 发射")
    out_freq = args.lo * 1e6 + if_hz
    print("  预期射频输出中心 = %.4f MHz" % (out_freq / 1e6))
    print("  ★ 请在 CMU200 上设中心 %.1f MHz，span 1 MHz，RBW 10 kHz" % (out_freq / 1e6))
    print("     应该看到约 %.0f kHz 宽的 BPSK 主瓣" % (sym * 1.2 / 1e3))

    if args.action == "send":
        for i in range(args.reps):
            r = ssh("cd /tmp && timeout 60 iio_writedev %s -s %d -b 65536 "
                    "cf-ad9361-dds-core-lpc voltage0 voltage1 < /tmp/wave.bin 2>&1; echo rc=$?"
                    % (U, nsamp), timeout=120)
            print("  第 %d/%d 次: %s" % (i + 1, args.reps,
                                          r.strip().splitlines()[-1][:80] if r.strip() else "?"))
        print("\n  提示：想连续发就多跑几次，或把 --reps 调大")
        print("  停止：python stage_a_tx.py stop")

    elif args.action == "selfcheck":
        print("\n[5b] 自收自环（需要 TX1 -> 衰减器 -> RX1）")
        print("  ⚠️ 必须先确认 TX 衰减已设到安全值（现在 -%d dB）" % args.att)
        ssh("rm -f /tmp/cap.bin")
        r = ssh("timeout 60 iio_readdev %s -s 131072 -b 65536 cf-ad9361-lpc "
                "voltage0 voltage1 > /tmp/cap.bin 2>&1; echo rc=$?" % U, timeout=120)
        print("  抓取: %s" % r.strip().splitlines()[-1][:80])
        sz = ssh("wc -c < /tmp/cap.bin")
        print("  抓到 %s 字节" % sz)
        if sz.strip().isdigit() and int(sz.strip()) > 100000:
            subprocess.run(SCP + ["root@%s:/tmp/cap.bin" % BOARD,
                                  os.path.join(HERE, "cap.bin")], timeout=300)
            raw = np.fromfile(os.path.join(HERE, "cap.bin"), dtype=np.int16)
            I = raw[0::2].astype(float)
            print("  已取回，I.std=%.1f" % I.std())
            print("  用 ccsds_tm_tx 的解码函数分析（下一步实现）")

    return 0


if __name__ == "__main__":
    sys.exit(main())
