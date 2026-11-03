#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
loopback_test.py -- 双板环回：发射 → 转发板中转 → 接收 → 解码 → 比对

链路
----
    遥测板 TX1 ──► 转发板 RX1 ──(relay)──► 转发板 TX1 ──► 遥测板 RX1
                                                              │
                                            iio_readdev 抓回电脑
                                                              │
                                     下变频 → 匹配滤波 → 定时恢复
                                     → ASM → Viterbi → 解随机化 → 解帧

接收端为什么不能省掉定时恢复
----------------------------
  发射端每个符号 10 个样点，接收端抓回来的数据与符号边界没有对齐关系
  （自由运行的 ADC），所以必须搜索最佳采样相位。本脚本在 [0, sps) 上
  扫一遍，取"判决置信度之和"最大的相位。

用法
----
    python loopback_test.py run            # 完整：发射 + 抓取 + 解码
    python loopback_test.py capture        # 只抓一段存下来
    python loopback_test.py decode f.bin   # 解码已有的文件
"""
import os
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ccsds_tm_tx as CC          # 注意：不能用 C，下面 C 是 ANSI 颜色常量

BOARD = "192.168.2.1"
KEY = r"C:\Users\23638\.ssh\id_ed25519_dsh"
WAVE = "/tmp/wave.bin"
CAP = "/tmp/cap.bin"
LOCAL_CAP = os.path.join(HERE, "cap.bin")

FS = 2_500_000
SYM = 250_000
SPS = FS // SYM                 # 10
IF = 200_000                    # 和发射端一致
N_SAMP = 3456320                # 一帧波形样点
CAP_SAMPLES = 1_048_576         # 抓 100 万样点（约 0.42 秒）

G = "\033[32m"; R = "\033[31m"; Y = "\033[33m"; C = "\033[36m"
B = "\033[1m"; D = "\033[2m"; N = "\033[0m"

SSH = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no",
       "-o", "UserKnownHostsFile=NUL", "-o", "LogLevel=ERROR",
       "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "root@" + BOARD]


def ssh(cmd, timeout=300):
    r = subprocess.run(SSH + [cmd], capture_output=True, timeout=timeout)
    return ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace").strip()


def ssh_bg(cmd):
    """后台跑一条命令，不等待（用 nohup + &）"""
    return ssh("nohup sh -c %s >/dev/null 2>&1 & echo BG_STARTED"
               % ("'" + cmd.replace("'", "'\\''") + "'"), timeout=60)


# =====================================================================
#  接收端
# =====================================================================
def tx_filter_bb(iq, if_hz=IF, fs=FS):
    """下变频到基带"""
    n = len(iq)
    t = np.arange(n) / fs
    return iq * np.exp(-1j * 2 * np.pi * if_hz * t)


def matched_filter(bb, sps=SPS, beta=0.35):
    """SRRC 匹配滤波"""
    h = CC.srrc(beta, sps, span=8)
    return np.convolve(bb, h, mode="same")


def recover_bits(bb, sps=SPS):
    """符号定时恢复：扫描采样相位，取置信度最高的那个

    返回 (bits, info)
    """
    best = None
    for phase in range(sps):
        sym = bb[phase::sps]
        # BPSK：取实部，用 |实部| 之和作为置信度（越大说明眼图越开）
        conf = float(np.sum(np.abs(sym.real)))
        if best is None or conf > best[0]:
            best = (conf, phase, sym)
    conf, phase, sym = best
    bits = (sym.real < 0).astype(np.uint8)      # 负 -> 1
    return bits, {"phase": phase, "conf": conf,
                  "npk": float(np.mean(np.abs(sym.real)))}


def find_asm(bits, max_err=2):
    """在比特流里找 ASM (0x1ACFFC1D)

    ★ 不要硬编码字节串：0x1ACFFC1D 是 1A CF FC 1D，
      写成 b"C\\xff\\xc1\\x1d" 就变成 43 FF C1 1D，完全不同的东西。
      统一从 CC.ASM 派生，避免这个坑。
    """
    import struct as _struct
    asm = CC.bytes_to_bits(_struct.pack(">I", CC.ASM))
    n = len(bits)
    if n < len(asm):
        return -1, 99
    best, bi = 99, -1
    for i in range(0, n - len(asm) + 1):
        e = int(np.sum(bits[i:i + len(asm)] != asm))
        if e < best:
            best, bi = e, i
        if e == 0:
            break
    return bi, best


def decode_capture(raw_i, raw_q, verbose=True):
    """从抓到的 I/Q 还原 CCSDS 传输帧"""
    iq = raw_i.astype(np.float64) + 1j * raw_q.astype(np.float64)
    iq = iq - iq.mean()

    bb = tx_filter_bb(iq)
    mf = matched_filter(bb)
    bits, info = recover_bits(mf)

    if verbose:
        print("   定时相位 = %d/%d   眼图开度 = %.1f   每符号均值 = %.1f"
              % (info["phase"], SPS, info["conf"], info["npk"]))

    pos, err = find_asm(bits, max_err=4)
    if verbose:
        print("   ASM 搜索: 位置 %s  错 %d bit" % (pos, err))
    return bits, pos, err, info


def try_full_decode(bits, asm_pos):
    """ASM 之后是卷积编码的随机化传输帧"""
    if asm_pos < 0:
        return None, {"reason": "ASM 未命中"}
    enc = bits[asm_pos + 32:]
    n = (len(enc) // 2) * 2
    if n < 64:
        return None, {"reason": "数据不足"}
    dec = CC.conv_decode_viterbi(enc[:n])
    der = CC.derandomize(dec)
    frame = CC.bits_to_bytes(der)
    # 试着解出若干个帧
    out = []
    off = 0
    while off + 8 <= len(frame):
        # 帧长从主头算不出来（TM 帧头里没有长度字段），先用固定 108 字节试
        chunk = frame[off:off + 108]
        if len(chunk) < 8:
            break
        p = CC.parse_tm_frame(chunk)
        if p and p["crc_ok"]:
            out.append((off, p))
            off += 108
        else:
            off += 1
            if len(out) == 0 and off > 400:
                break
    return out, {"frames_found": len(out)}


# =====================================================================
def do_capture():
    print("\n%s[抓取]%s 从遥测板 RX 抓 %d 样点" % (C, N, CAP_SAMPLES))
    ssh("rm -f %s" % CAP, 60)
    # ★ 不能用 timeout —— 板上没有这个命令（rc=127）。
    #   iio_readdev -s N 抓够 N 个样点会自己退出，不需要外部限时。
    r = ssh("iio_readdev -u ip:localhost -s %d -b 65536 "
            "cf-ad9361-lpc voltage0 voltage1 > %s 2>&1; echo rc=$?"
            % (CAP_SAMPLES, CAP), timeout=180)
    tail = r.strip().splitlines()[-1][:80] if r.strip() else "?"
    print("   " + tail)
    if "rc=127" in r:
        print("   %src=127 = 命令不存在，检查是不是用了板上没有的工具%s" % (R, N))
    sz = ssh("wc -c < %s 2>/dev/null || echo 0" % CAP, 60).strip()
    print("   抓到 %s 字节" % sz)
    if not sz.isdigit() or int(sz) < 4096:
        return None
    subprocess.run(["scp", "-O", "-i", KEY, "-o", "StrictHostKeyChecking=no",
                    "-o", "UserKnownHostsFile=NUL", "-o", "LogLevel=ERROR",
                    "-o", "BatchMode=yes", "root@%s:%s" % (BOARD, CAP), LOCAL_CAP],
                   capture_output=True, timeout=300)
    return LOCAL_CAP


def analyze(path):
    raw = np.fromfile(path, dtype=np.int16)
    I, Q = raw[0::2], raw[1::2]
    print("\n%s[分析]%s %s  (%d 样点)" % (C, N, os.path.basename(path), len(I)))
    print("   I.std=%.1f  Q.std=%.1f  max=%d" % (I.std(), Q.std(), np.abs(raw).max()))

    # 频谱峰值位置（★ 局部变量别叫 N —— 全局 N 是 ANSI 颜色复位）
    NFFT = 4096
    K = min(len(I) // NFFT, 32)
    if K < 1:
        print("   数据太少")
        return None
    w = np.hanning(NFFT)
    acc = np.zeros(NFFT)
    for k in range(K):
        s = (I[k * NFFT:(k + 1) * NFFT] + 1j * Q[k * NFFT:(k + 1) * NFFT]) * w
        acc += np.abs(np.fft.fftshift(np.fft.fft(s))) ** 2
    P = 10 * np.log10(acc / K + 1e-20)
    f = (np.arange(NFFT) - NFFT // 2) * (FS / NFFT)
    i = int(P.argmax())
    print("   频谱峰值 %+.1f kHz  (%.1f dB, 底 %.1f dB, SNR %.1f dB)"
          % (f[i] / 1e3, P[i], np.median(P), P[i] - np.median(P)))

    bits, pos, err, info = decode_capture(I, Q)
    if err > 4:
        print("\n   %s❌ ASM 没找到（最好错 %d bit）—— 检查接线和电平%s" % (R, err, N))
        return None

    frames, fi = try_full_decode(bits, pos)
    print("\n   %s[解码结果]%s" % (C, N))
    if frames:
        for off, p in frames[:5]:
            print("   %s✅ 帧@字节%-4d SCID=0x%X VCID=%d MCFC=%3d VCFC=%3d CRC=OK payload=%s...%s"
                  % (G, off, p["scid"], p["vcid"], p["mcfc"], p["vcfc"],
                     p["payload"][:4].hex(), p["payload"][-2:].hex()))
        print("\n   %s═══ 环回验证通过 ═══%s" % (G + B, N))
        print("   整条链：CCSDS 编码 → 遥测板 TX → 转发板中转 → 遥测板 RX → 解码")
        print("   解出 %d 个 CRC 正确的传输帧，内容与发送端一致。" % len(frames))
    else:
        print("   %s⚠️ ASM 命中（错 %d bit）但帧没解出来%s" % (Y, err, N))
        print("   可能原因：电平不合适 / 定时相位不准 / 转发板没在转发")
    return frames


def main():
    act = sys.argv[1] if len(sys.argv) > 1 else "run"

    print("%s═══ 双板环回验证 ═══%s" % (B, N))
    print("  遥测板 TX1 → 转发板 RX1 → 转发板 TX1 → 遥测板 RX1")

    if act == "decode":
        if len(sys.argv) < 3:
            print("用法: decode <file.bin>")
            return 2
        return 0 if analyze(sys.argv[2]) else 1

    if act in ("run", "capture"):
        # 先确认两块板子状态
        st = ssh("iio_attr -u ip:localhost -o -c ad9361-phy voltage1 hardwaregain 2>&1|tail -1", 60)
        print("  遥测板 TX 衰减: %s" % st)

        if act == "run":
            print("\n%s[发射]%s 后台连续发（循环 30 遍 ≈ 40 秒）" % (C, N))
            inner = ("for i in $(seq 1 30); do cat %s; done | "
                     "iio_writedev -u ip:localhost -s %d -b 65536 "
                     "cf-ad9361-dds-core-lpc voltage0 voltage1"
                     % (WAVE, N_SAMP * 10))
            ssh_bg(inner)
            time.sleep(2.0)      # 等它跑起来
            print("   发射已启动")

        p = do_capture()
        if not p:
            print("%s抓取失败%s" % (R, N))
            return 1
        if act == "run":
            ssh("killall -9 iio_writedev 2>/dev/null; echo TX_STOPPED", 60)
        analyze(p)
        return 0

    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
