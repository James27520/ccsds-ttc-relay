#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pluto_siggen.py -- 把旧遥控板（7010_AD9363_SDR）当"模拟基站信号发生器"

角色（架构 V2）
--------------
  遥控板 = 模拟基站的射频前端：PC 生成波形 → libiio 写 TX → 100 MHz 中频发出
  内容两种：
    cmd     : CCSDS 控制帧，body 只有 8 字节（ver + rx_lo + tx_lo + seq + CRC16）
    payload : 业务内容（文本），未编码，AA AA 前导 + len + text + CRC16
    tone    : 单音，用于标定频率/测衰减

与 ADDA 接收端的约定（见 docs/ADDA_PS_DEMOD_SPEC.md）
---------------------------------------------------
  TX LO      = --lo（默认 100 MHz）
  基带偏移   = --ifoff（默认 +0.5 MHz，避开本振泄漏）
  ⇒ 信号中心 = lo + ifoff = 100.5 MHz
  符号率     = --sym（默认 100 kSPS）
  编码       : 随机化 → 卷积 1/2（K=7, G1=1111001, G2=1011011, 第二路取反）→ 前置 ASM 1ACFFC1D
  CADU       = 32(ASM) + 2×64 = 160 bit（对应 1.6 ms @100 kSPS）
  映射       : bit0 → +1, bit1 → -1（BPSK）
  成形       : SRRC，β=0.35，占用带宽 ≈ 135 kHz

用法
----
  # 先离线验证（不连板子），把波形存下来看看
  python pluto_siggen.py --mode cmd --rx 100 --tx 2450 --no-tx --save cmd.bin

  # 真正发射（持续 20 秒）
  python pluto_siggen.py --mode cmd --rx 100 --tx 2450 --seconds 20

  # 发业务内容（给转发板中继用）
  python pluto_siggen.py --mode payload --text "hello world" --seconds 20

  # 单音标定
  python pluto_siggen.py --mode tone --seconds 5

  # 只看板子当前 TX 状态
  python pluto_siggen.py --check
"""
import argparse
import os
import re
import struct
import subprocess
import sys
import time

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "ccsds"))

import ccsds_tm_tx as CC          # noqa: E402

PLINK = r"D:\PuTTY\plink.exe"
PSCP = r"D:\PuTTY\pscp.exe"

DEF_IP = "192.168.2.1"
DEF_USER = "root"
DEF_PW = "analog"

ASM = 0x1ACFFC1D
PREAMBLE = b"\xaa\xaa"


# ===========================================================================
#  控制帧（只含两个频率）
# ===========================================================================
def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def build_ctrl_body(rx_mhz, tx_mhz, seq=0, ver=1):
    """8 字节 body: ver(1) + rx_lo(u16 LE) + tx_lo(u16 LE) + seq(1) + crc16(2 BE)"""
    body = bytes([ver & 0xFF]) + struct.pack("<H", rx_mhz & 0xFFFF) \
           + struct.pack("<H", tx_mhz & 0xFFFF) + bytes([seq & 0xFF])
    return body + struct.pack(">H", crc16(body))


def parse_ctrl_body(body):
    ver = body[0]
    rx = struct.unpack_from("<H", body, 1)[0]
    tx = struct.unpack_from("<H", body, 3)[0]
    seq = body[5]
    crc = struct.unpack_from(">H", body, 6)[0]
    return dict(ver=ver, rx_mhz=rx, tx_mhz=tx, seq=seq,
                crc_ok=(crc16(body[:6]) == crc))


# ===========================================================================
#  波形生成
# ===========================================================================
def mod_ccsds(body, fs, sym_rate, beta, amp, if_hz):
    """body → 随机化 → 卷积 1/2 → ASM → BPSK+SRRC → 中频 → int16 交织流"""
    cadu, info = CC.build_cadu(body, randomize_data=True)
    I, Q = CC.cadu_to_iq(cadu, fs=fs, sym_rate=sym_rate, beta=beta,
                         amp=amp, if_hz=if_hz)
    return cadu, info, CC.iq_interleave(I, Q)


def mod_payload(text, fs, sym_rate, beta, amp, if_hz):
    """文本 → AA AA | len | text | CRC16 → BPSK+SRRC（未编码，便于接收端简单解调）"""
    tb = text.encode("utf-8")
    frame = PREAMBLE + bytes([len(tb) & 0xFF]) + tb + struct.pack(">H", crc16(tb))
    bits = CC.bytes_to_bits(frame)
    sps = max(2, int(round(fs / sym_rate)))
    sym = np.where(np.asarray(bits) == 0, 1.0, -1.0)
    up = np.zeros(len(sym) * sps)
    up[::sps] = sym
    h = CC.srrc(beta, sps, span=8)
    bb = np.convolve(up, h, mode="same")
    pk = np.max(np.abs(bb)) or 1.0
    bb = bb / pk
    if if_hz:
        t = np.arange(len(bb)) / fs
        bb = bb * np.exp(1j * 2 * np.pi * if_hz * t)
    scale = amp * 32767.0 * 0.7
    I = np.clip(np.real(bb) * scale, -32768, 32767).astype(np.int16)
    Q = np.clip(np.imag(bb) * scale, -32768, 32767).astype(np.int16)
    return frame, CC.iq_interleave(I, Q)


def mod_tone(fs, if_hz, amp, n=None):
    n = n or int(fs * 0.01)
    t = np.arange(n) / fs
    s = amp * 0.7 * np.cos(2 * np.pi * if_hz * t)
    I = np.clip(s * 32767, -32768, 32767).astype(np.int16)
    Q = np.zeros(n, dtype=np.int16)
    return CC.iq_interleave(I, Q)


# ===========================================================================
#  遥控板（Pluto 固件）控制
# ===========================================================================
class SigGenBoard(object):
    def __init__(self, ip, user, pw):
        self.ip, self.user, self.pw = ip, user, pw
        self.fp = None

    def _run(self, cmd, extra=None, timeout=120):
        a = [PLINK, "-ssh", "-batch"] + (extra or []) + \
            ["-pw", self.pw, "%s@%s" % (self.user, self.ip), cmd]
        r = subprocess.run(a, capture_output=True, timeout=timeout)
        return ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace")

    def connect(self):
        out = self._run("echo __OK__", timeout=25)
        m = re.search(r"SHA256:[A-Za-z0-9+/=]+", out)
        if m:
            self.fp = m.group(0)
            out = self._run("echo __OK__", timeout=25, extra=["-hostkey", self.fp])
        if "__OK__" not in out:
            raise RuntimeError("SSH 不通：%s" % out.strip()[:200])
        return True

    def sh(self, cmd, timeout=120, show=False):
        out = self._run(cmd, extra=(["-hostkey", self.fp] if self.fp else None),
                        timeout=timeout).strip()
        if show and out:
            for l in out.splitlines()[:15]:
                print("      | " + l[:140])
        return out

    def push(self, local, remote):
        a = [PSCP, "-batch", "-scp"] + (["-hostkey", self.fp] if self.fp else [])
        a += ["-pw", self.pw, local, "%s@%s:%s" % (self.user, self.ip, remote)]
        return subprocess.run(a, capture_output=True, timeout=300).returncode == 0

    def configure(self, lo_hz, fs, bw, txatt_db):
        for c in [
            "iio_attr -u ip:localhost -c ad9361-phy voltage1 sampling_frequency %d" % int(fs),
            "iio_attr -u ip:localhost -c ad9361-phy voltage1 rf_bandwidth %d" % int(bw),
            "iio_attr -u ip:localhost -c ad9361-phy altvoltage1 frequency %d" % int(lo_hz),
            "iio_attr -u ip:localhost -o -c ad9361-phy voltage1 hardwaregain -%d" % int(txatt_db),
            # 关掉 DDS，避免它往 TX 上叠单音
            "iio_attr -u ip:localhost -c cf-ad9361-dds-core-lpc altvoltage0 scale 0",
            "iio_attr -u ip:localhost -c cf-ad9361-dds-core-lpc altvoltage2 scale 0",
        ]:
            self.sh(c)
        return self.sh(
            "iio_attr -u ip:localhost -c ad9361-phy altvoltage1 frequency; "
            "iio_attr -u ip:localhost -c ad9361-phy voltage1 sampling_frequency")

    def start_stream(self, remote_file, repeats, nbytes, background=True):
        cmd = ("killall -9 iio_writedev 2>/dev/null; cd /tmp && "
               "%s sh -c 'for i in $(seq 1 %d); do cat %s; done | "
               "iio_writedev -u ip:localhost -s %d -b 65536 "
               "cf-ad9361-dds-core-lpc voltage0 voltage1' >/tmp/siggen.log 2>&1 &"
               % ("nohup" if background else "", repeats, remote_file, nbytes))
        return self.sh(cmd)

    def stop_stream(self):
        return self.sh("killall -9 iio_writedev 2>/dev/null; echo STOPPED")


# ===========================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default=DEF_IP)
    ap.add_argument("--user", default=DEF_USER)
    ap.add_argument("--pw", default=DEF_PW)

    ap.add_argument("--mode", choices=["cmd", "payload", "tone"], default="cmd")
    ap.add_argument("--rx", type=int, default=100, help="控制帧：接收频段 MHz")
    ap.add_argument("--tx", type=int, default=2450, help="控制帧：转发频段 MHz")
    ap.add_argument("--text", default="hello world", help="payload 模式的内容")

    ap.add_argument("--lo", type=float, default=100.0, help="TX 本振 MHz")
    ap.add_argument("--ifoff", type=float, default=0.5, help="基带偏移 MHz（避开本振泄漏）")
    ap.add_argument("--fs", type=float, default=2.5e6, help="TX 采样率 Hz")
    ap.add_argument("--sym", type=float, default=100e3, help="符号率 Hz")
    ap.add_argument("--bw", type=float, default=500e3, help="TX 射频带宽 Hz")
    ap.add_argument("--beta", type=float, default=0.35)
    ap.add_argument("--amp", type=float, default=0.6)
    ap.add_argument("--txatt", type=int, default=30, help="TX 衰减 dB")

    ap.add_argument("--seconds", type=float, default=20.0, help="发射时长")
    ap.add_argument("--repeat", type=int, default=0, help="波形重复次数（0=按 seconds 自动算）")
    ap.add_argument("--save", default=None, help="把 IQ 存到本地文件")
    ap.add_argument("--no-tx", action="store_true", help="只生成波形，不上板")
    ap.add_argument("--check", action="store_true", help="只查板子当前状态")
    a = ap.parse_args()

    print("=" * 76)
    print("  遥控板 = 模拟基站信号发生器")
    print("=" * 76)
    print("  板子    : %s@%s" % (a.user, a.ip))
    print("  模式    : %s" % a.mode)
    print("  TX LO   : %.3f MHz" % a.lo)
    print("  基带偏移: %+.3f MHz  ⇒  信号中心 %.3f MHz" % (a.ifoff, a.lo + a.ifoff))
    print("  采样率  : %.3f MSPS" % (a.fs / 1e6))
    print("  符号率  : %.1f kSPS  (每符号 %.1f 点)" % (a.sym / 1e3, a.fs / a.sym))
    print("  TX 衰减 : %d dB" % a.txatt)

    if a.check:
        b = SigGenBoard(a.ip, a.user, a.pw)
        try:
            b.connect()
            print("\n  ✓ SSH 通")
            b.sh("iio_info -s 2>&1 | head -6", show=True)
            print("\n  -- 当前 TX 配置 --")
            b.sh("iio_attr -u ip:localhost -c ad9361-phy altvoltage1 frequency; "
                 "iio_attr -u ip:localhost -c ad9361-phy voltage1 sampling_frequency; "
                 "iio_attr -u ip:localhost -o -c ad9361-phy voltage1 hardwaregain", show=True)
        except Exception as e:
            print("\n  ✗ %s" % str(e)[:200])
            return 2
        return 0

    # ---------------- 生成波形 ----------------
    if_hz = a.ifoff * 1e6
    print()
    if a.mode == "cmd":
        body = build_ctrl_body(a.rx, a.tx, seq=0)
        info_p = parse_ctrl_body(body)
        print("  -- 控制帧 --")
        print("    body (8B) : %s" % body.hex())
        print("    解析回读  : ver=%d rx=%d MHz tx=%d MHz seq=%d crc=%s"
              % (info_p["ver"], info_p["rx_mhz"], info_p["tx_mhz"],
                 info_p["seq"], "OK" if info_p["crc_ok"] else "FAIL"))
        cadu, info, iq = mod_ccsds(body, a.fs, a.sym, a.beta, a.amp, if_hz)
        print("    CADU 比特 : %d  (ASM 32 + conv %d)"
              % (info["cadu_bits"], info["conv_bits"]))
        print("    CADU 十六进制(前16B): %s"
              % np.packbits(cadu[:128]).tobytes().hex())
        frame_ms = info["cadu_bits"] / a.sym * 1e3
        print("    单帧时长  : %.2f ms" % frame_ms)
    elif a.mode == "payload":
        frame, iq = mod_payload(a.text, a.fs, a.sym, a.beta, a.amp, if_hz)
        print("  -- 业务内容 --")
        print("    文本     : %r" % a.text)
        print("    帧       : %s" % frame.hex())
        print("    帧长     : %d 字节" % len(frame))
    else:
        iq = mod_tone(a.fs, if_hz, a.amp)
        print("  -- 单音 --")

    nsamp = len(iq) // 2
    print()
    print("  -- 波形 --")
    print("    复样点   : %d  (%.3f ms)" % (nsamp, nsamp / a.fs * 1e3))
    print("    占用带宽 : ≈ %.1f kHz" % (a.sym * (1 + a.beta) / 1e3))
    print("    峰值幅度 : %d / 32767" % int(np.max(np.abs(iq))))

    if a.save:
        iq.tofile(a.save)
        print("    已保存   : %s (%d 字节)" % (a.save, os.path.getsize(a.save)))

    if a.no_tx:
        print("\n  --no-tx：不上板")
        return 0

    # ---------------- 上板发射 ----------------
    repeats = a.repeat or max(1, int(round(a.seconds * a.fs / nsamp)))
    total_s = repeats * nsamp / a.fs
    print()
    print("  -- 发射 --")
    print("    单次时长 : %.2f ms" % (nsamp / a.fs * 1e3))
    print("    重复次数 : %d  ⇒  总时长 %.1f 秒" % (repeats, total_s))

    b = SigGenBoard(a.ip, a.user, a.pw)
    try:
        b.connect()
        print("    ✓ SSH 通")
        rd = b.configure(a.lo * 1e6, a.fs, a.bw, a.txatt)
        print("    ✓ 已配置（回读 LO/采样率）: %s" % rd.replace("\n", " "))
        local = os.path.join(os.environ.get("TEMP", "."), "siggen_iq.bin")
        iq.tofile(local)
        if not b.push(local, "/tmp/siggen_iq.bin"):
            raise RuntimeError("波形上传失败")
        print("    ✓ 波形已上传")
        b.start_stream("/tmp/siggen_iq.bin", repeats, len(iq) * 2)
        print("    ✓ 已开始发射，持续 %.1f 秒" % total_s)
        print("    接收端现在应该能在 %.3f MHz 上看到信号"
              % (a.lo + a.ifoff))
        print("    （Ctrl+C 可提前停止）")
        t0 = time.time()
        while time.time() - t0 < total_s:
            time.sleep(1.0)
        b.stop_stream()
        print("    ✓ 发射结束")
    except KeyboardInterrupt:
        print("\n    停止中...")
        try:
            b.stop_stream()
        except Exception:
            pass
    except Exception as e:
        print("    ✗ %s" % str(e)[:200])
        return 3

    print()
    print("=" * 76)
    return 0


if __name__ == "__main__":
    sys.exit(main())
