#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ccsds_mode_b_test.py -- 模式 B 真实过板测试：PC 生成 CCSDS 波形 -> 遥测板发射
                        -> SMA 环回 -> 遥测板接收 -> PC 解调译码 -> 显示内容

这是「电脑写参数 -> 软件组 CCSDS 包 -> 发给遥控板 -> 另一边显示接收内容」
这条演示流程的【真机版本】。

硬件前提（都已验证）：
  · 板子跑原厂固件，RNDIS + SSH 可用
  · TX/RX 本振同频（实测都是 2400 MHz）
  · TX1A -> RX1A 有环回（实测 DDS 单音环回 54.8 dB 信噪比）

关键点（踩过的坑）：
  · 必须用【文件重定向】`< wave.bin` 而不是管道喂 iio_writedev，
    这样 TX 缓冲区是循环的 —— iio_writedev 退出后 FPGA 还在持续发射。
    用管道的话发射只有几十毫秒，抓的时候早就发完了。
  · pscp 必须带 -scp（板子没装 sftp-server）。
  · 板子每次重启会换 SSH 主机密钥，所以每次现抓指纹。

用法:
  python ccsds_mode_b_test.py
  python ccsds_mode_b_test.py --payload "HELLO-2026"
"""
import argparse
import os
import re
import subprocess
import sys
import time

import numpy as np

SW = r"E:\fpga_sdr_project\ccsds_ttc_loopback\sw\ttc"
sys.path.insert(0, SW)
import ccsds_tm_tx as CC            # noqa: E402
import loopback_test as LB          # noqa: E402  复用已验证的解调/译码函数

PLINK = r"D:\PuTTY\plink.exe"
PSCP = r"D:\PuTTY\pscp.exe"
BOARD = "root@192.168.2.1"
PW = "analog"

FS = 2_500_000
SYM = 250_000
IF = 200_000
N_SAMP = 3_456_320          # 发射波形长度（和软件版一致，保证 TX 缓冲足够长）
CAP_SAMPLES = 262_144       # 抓 26 万样点（105 ms @2.5MSPS），必须远小于发射时长

LOCAL = r"E:\ccsds_fpga\out"
WAVE = os.path.join(LOCAL, "mb_wave.bin")
CAPB = os.path.join(LOCAL, "mb_cap.bin")

FP = None


def hostkey():
    r = subprocess.run([PLINK, "-ssh", "-batch", "-pw", PW, BOARD, "echo P"],
                       capture_output=True)
    m = re.search(r"SHA256:[A-Za-z0-9+/=]+",
                  (r.stdout + r.stderr).decode("utf-8", "replace"))
    return m.group(0) if m else None


def sh(cmd, timeout=240, show=False):
    args = [PLINK, "-ssh", "-batch"]
    if FP:
        args += ["-hostkey", FP]
    args += ["-pw", PW, BOARD, cmd]
    r = subprocess.run(args, capture_output=True, timeout=timeout)
    out = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace").strip()
    if show and out:
        for line in out.splitlines():
            print("    | %s" % line[:150])
    return out


def scp(local, remote, download=False):
    args = [PSCP, "-batch", "-scp"]
    if FP:
        args += ["-hostkey", FP]
    args += ["-pw", PW]
    args += ["%s:%s" % (BOARD, remote), local] if download else [local, "%s:%s" % (BOARD, remote)]
    r = subprocess.run(args, capture_output=True, timeout=300)
    if r.returncode != 0:
        print("    ! scp 失败: %s" % ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace")[:200])
    return r.returncode == 0


def main():
    global FP
    ap = argparse.ArgumentParser()
    ap.add_argument("--payload", default="CCSDS-6G-NTN-7010-TTC-FPGA-PORT!")
    ap.add_argument("--txatt", type=int, default=40)
    ap.add_argument("--rxgain", type=int, default=30)
    a = ap.parse_args()

    print("=" * 76)
    print("  模式 B：PC 组 CCSDS 包 -> 遥测板发射 -> 环回 -> 板子接收 -> PC 解出内容")
    print("=" * 76)

    FP = hostkey()
    print("  板子主机密钥: %s" % FP)
    if not FP:
        print("  [!] 板子不在线")
        return 1

    # ---- 1) PC 侧组包 ----
    print("\n-- 1) PC 侧：参数 -> CCSDS 包 --")
    payload = a.payload.encode("utf-8")[:32]
    frame = CC.build_tm_frame(scid=42, vcid=0, mcfc=0, vcfc=0, data=payload, fecf=True)
    cadu, info = CC.build_cadu(frame)
    print("  载荷      : %s" % payload.decode("utf-8", "replace"))
    print("  帧 (%d B) : %s" % (len(frame), frame.hex()))
    print("  CADU      : %d bit" % len(cadu))

    # ---- 2) 调制 ----
    print("\n-- 2) BPSK 调制（%.1f MSPS / %.0f ksym/s / SRRC beta=0.35 / IF %.0f kHz）--"
          % (FS / 1e6, SYM / 1e3, IF / 1e3))
    ret = CC.cadu_to_iq(cadu, fs=FS, sym_rate=SYM, beta=0.35, amp=0.6, if_hz=IF)
    I, Q = ret if isinstance(ret, tuple) else (ret, None)
    iq = CC.iq_interleave(I, Q) if Q is not None else np.asarray(I)
    one = np.asarray(iq, dtype=np.int16)
    print("  一遍波形 %d 样点" % len(one))
    reps = int(np.ceil(N_SAMP / float(len(one))))
    wave = np.tile(one, reps)[:N_SAMP]
    wave.tofile(WAVE)
    print("  发射波形 %d 样点 (%d 遍) = %.1f ms @ %.1f MSPS"
          % (len(wave), reps, len(wave) / FS * 1e3, FS / 1e6))

    # ---- 3) 传输 ----
    print("\n-- 3) 传到板子 --")
    if not scp(WAVE, "/tmp/mb_wave.bin"):
        return 1
    sh("ls -l /tmp/mb_wave.bin", show=True)

    # ---- 4) 配置 AD9361 ----
    print("\n-- 4) 配置 AD9361（%.1f MSPS，本振 2400 MHz）--" % (FS / 1e6))
    for c in [
        "iio_attr -u ip:localhost -c ad9361-phy voltage0 sampling_frequency %d" % int(FS),
        "iio_attr -u ip:localhost -c ad9361-phy voltage0 rf_bandwidth 1000000",
        "iio_attr -u ip:localhost -c ad9361-phy voltage1 rf_bandwidth 1000000",
        "iio_attr -u ip:localhost -c ad9361-phy altvoltage0 frequency 2400000000",
        "iio_attr -u ip:localhost -c ad9361-phy altvoltage1 frequency 2400000000",
        "iio_attr -u ip:localhost -i -c ad9361-phy voltage0 gain_control_mode manual",
        "iio_attr -u ip:localhost -i -c ad9361-phy voltage0 hardwaregain %d" % a.rxgain,
        "iio_attr -u ip:localhost -i -c ad9361-phy voltage1 gain_control_mode manual",
        "iio_attr -u ip:localhost -i -c ad9361-phy voltage1 hardwaregain %d" % a.rxgain,
        "iio_attr -u ip:localhost -o -c ad9361-phy voltage1 hardwaregain -%d" % a.txatt,
        # DDS 关掉，否则会和我们的波形叠加
        "iio_attr -u ip:localhost -c cf-ad9361-dds-core-lpc altvoltage0 scale 0",
        "iio_attr -u ip:localhost -c cf-ad9361-dds-core-lpc altvoltage1 scale 0",
        "iio_attr -u ip:localhost -c cf-ad9361-dds-core-lpc altvoltage2 scale 0",
        "iio_attr -u ip:localhost -c cf-ad9361-dds-core-lpc altvoltage3 scale 0",
    ]:
        sh(c)
    for k, c in (("RX gain", "-i -c ad9361-phy voltage0 hardwaregain"),
                 ("TX att ", "-o -c ad9361-phy voltage1 hardwaregain"),
                 ("RX 采样率", "-c ad9361-phy voltage0 sampling_frequency")):
        print("  %s = %s" % (k, sh("iio_attr -u ip:localhost %s" % c)))

    # ---- 5) 发射（★ 有界管道循环，和软件版验证过的写法一致）----
    print("\n-- 5) 发射（★ 管道循环；文件重定向只会发一遍，抓的时候就没了）--")
    sh("killall -9 iio_writedev 2>/dev/null; echo cleaned")
    passes = 30
    total = len(wave) * 10
    print("  循环 %d 遍喂管道，iio_writedev -s %d 样点 = %.1f 秒"
          % (passes, total, total / float(FS)))
    inner = ("cd /tmp && nohup sh -c 'for i in $(seq 1 %d); do cat /tmp/mb_wave.bin; done | "
             "iio_writedev -u ip:localhost -s %d -b 65536 "
             "cf-ad9361-dds-core-lpc voltage0 voltage1' >/tmp/tx.log 2>&1 & echo TX_STARTED"
             % (passes, total))
    sh(inner)
    time.sleep(2.0)      # 等它跑起来；发射总时长十几秒，余量充足
    print("  发射进程数 = %s" % sh("ps | grep '[i]io_writedev' | wc -l"))
    print("  tx.log: %s" % sh("cat /tmp/tx.log 2>/dev/null | head -3"))

    # ---- 6) 接收 ----
    print("\n-- 6) 抓接收数据（%d 样点）--" % CAP_SAMPLES)
    sh("iio_readdev -u ip:localhost -b 65536 -s %d cf-ad9361-lpc voltage0 voltage1 "
       "> /tmp/mb_cap.bin" % (2 * CAP_SAMPLES), timeout=240)
    sh("ls -l /tmp/mb_cap.bin", show=True)

    # ---- 7) 停发 + 取回 ----
    sh("killall -9 iio_writedev 2>/dev/null; echo TX_STOPPED")
    print("\n-- 7) 取回数据 --")
    if not scp(CAPB, "/tmp/mb_cap.bin", download=True):
        return 1

    # ---- 8) 解调译码 ----
    print("\n-- 8) PC 侧解调译码 --")
    raw = np.fromfile(CAPB, dtype=np.int16)
    if len(raw) < 8192:
        print("  [!] 数据太少 (%d)" % len(raw))
        return 1
    ri = raw[0::2].astype(np.int32)
    rq = raw[1::2].astype(np.int32)
    print("  %d 个复数样点, RMS=%.1f" % (len(ri), np.sqrt(np.mean(ri.astype(float)**2 + rq.astype(float)**2))))

    bits, pos, err, dinfo = LB.decode_capture(ri, rq)
    if pos < 0:
        print("\n  ✗ 没找到 ASM —— 检查环回线/增益")
        return 1

    enc = bits[pos + 32:]
    n = (len(enc) // 2) * 2
    dec = CC.conv_decode_viterbi(enc[:n])
    der = CC.derandomize(dec)
    fb = CC.bits_to_bytes(der)

    print("\n-- 9) 逐字节比对 --")
    found = 0
    for off in range(0, min(len(fb) - len(frame), 2000)):
        if bytes(fb[off:off + len(frame)]) == frame:
            print("  ★ 在偏移 %d 处解出与发送端【逐字节一致】的帧" % off)
            found += 1
            if found >= 3:
                break
    if found:
        print("\n  【接收端解出的内容】")
        print("    %s" % frame.hex())
        print("  【原始载荷】")
        print("    %s" % payload.decode("utf-8", "replace"))
        print("\n  ★★★ 模式 B（经板子）验证成功：PC 组包 -> 板子发射 -> 环回 -> 解出内容 ★★★")
        return 0
    print("  解出的前 64 字节: %s" % bytes(fb[:64]).hex())
    print("  期望帧          : %s" % frame.hex())
    print("\n  ✗ 没找到完全一致的帧（可能有误码）")
    return 1


if __name__ == "__main__":
    sys.exit(main())
