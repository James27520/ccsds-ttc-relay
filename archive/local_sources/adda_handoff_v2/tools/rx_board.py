#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rx_board.py -- 用一块 AD936x 板子（遥控板同款）当接收端：IIO 抓 IQ → PC 解析

为什么走 SSH 而不是本机 libiio
------------------------------
PC 上没有 libiio。板子的 Linux 里自带 iio_attr / iio_readdev，
所以：SSH 进板子 -> 板子里跑 IIO 命令 -> pscp 把抓到的 IQ 拉回 PC -> PC 上做 FFT / 解调。

用法
----
  # 只检查板子和 IIO 是否就绪
  python rx_board.py --check

  # 看频谱（确认 f2 上有信号）
  python rx_board.py --lo 1000 --fft

  # 解调我们用 gen_adda_coe.py 发出来的 BPSK 文本
  python rx_board.py --lo 1000 --demod

  # 自定义参数
  python rx_board.py --lo 2400 --fs 30720000 --bw 4000000 --gain 40 --fft

  # 收到的不对时，把原始 IQ 存下来慢慢看
  python rx_board.py --lo 1000 --save cap.bin --fft

默认
----
  板子 IP     192.168.2.1（USB RNDIS 默认）
  登录        root / analog
  RX1         cf-ad9361-lpc 的 voltage0(I) / voltage1(Q)
  RX LO       altvoltage0（AD9361 的 RX 本振）
  采样率      30.72 MSPS
"""
import argparse
import os
import re
import subprocess
import sys
import time

import numpy as np

# Windows 中文控制台默认 GBK，脚本里有 ✓/✗ 等字符会抛 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PLINK = r"D:\PuTTY\plink.exe"
PSCP = r"D:\PuTTY\pscp.exe"

DEF_IP = "192.168.2.1"
DEF_USER = "root"
DEF_PW = "analog"

# 与 gen_adda_coe.py / demo_master.py 保持一致的文本帧格式
PREAMBLE = b"\xaa\xaa"


# ---------------------------------------------------------------------------
class Board(object):
    def __init__(self, ip, user, pw):
        self.ip, self.user, self.pw = ip, user, pw
        self.fp = None

    def _plink(self, cmd, timeout=60, extra=None):
        a = [PLINK, "-ssh", "-batch"] + (extra or []) + \
            ["-pw", self.pw, "%s@%s" % (self.user, self.ip), cmd]
        r = subprocess.run(a, capture_output=True, timeout=timeout)
        return ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace")

    def connect(self):
        out = self._plink("echo __OK__", timeout=25)
        m = re.search(r"SHA256:[A-Za-z0-9+/=]+", out)
        if m:
            self.fp = m.group(0)
            out = self._plink("echo __OK__", timeout=25, extra=["-hostkey", self.fp])
        if "__OK__" not in out:
            raise RuntimeError("SSH 不通：%s" % out.strip()[:200])
        return True

    def sh(self, cmd, timeout=120, show=False):
        out = self._plink(cmd, timeout=timeout,
                          extra=(["-hostkey", self.fp] if self.fp else None)).strip()
        if show and out:
            for l in out.splitlines()[:20]:
                print("      | " + l[:140])
        return out

    def pull(self, remote, local):
        a = [PSCP, "-batch", "-scp"] + (["-hostkey", self.fp] if self.fp else [])
        a += ["-pw", self.pw, "%s@%s:%s" % (self.user, self.ip, remote), local]
        r = subprocess.run(a, capture_output=True, timeout=300)
        return r.returncode == 0


# ---------------------------------------------------------------------------
def fft_report(iq, fs, top=6):
    """
    IQ 复信号的单边谱。
    iq 可以是复数组，也可以是实数数组（实数时自动按实信号处理）。
    """
    x = np.asarray(iq)
    complex_in = np.iscomplexobj(x)
    if not complex_in:
        x = x.astype(np.float64)
    n = min(len(x), 1 << 16)
    win = np.hanning(n)
    X = np.fft.fftshift(np.abs(np.fft.fft(x[:n] * win)))
    f = np.fft.fftshift(np.fft.fftfreq(n, 1.0 / fs))
    p = 20 * np.log10(X / (np.max(X) + 1e-12) + 1e-12)
    idx = np.argsort(p)[::-1]
    picked = []
    for i in idx:
        if all(abs(f[i] - f[j]) > fs / n * 20 for j in picked):
            picked.append(i)
        if len(picked) >= top:
            break
    rms = float(np.sqrt(np.mean(np.abs(x) ** 2)))
    print("    RMS = %.1f   (满量程 32767)   点数 = %d   模式 = %s" %
          (rms, len(x), "IQ 复信号" if complex_in else "实数"))
    # 噪声底估计（取中位数）
    floor = float(np.median(p))
    print("    噪声底（中位）= %.1f dB，峰值高出 %.1f dB" % (floor, 0.0 - floor))
    print("    相对峰值（dB）      频率偏移")
    for i in picked:
        print("      %8.1f dB      %+12.1f Hz" % (p[i], f[i]))
    return p, f


def _cfo_coarse(x, fs):
    """
    BPSK 载波粗估：把中频信号平方，2f_c 处会出现一条谱线（数据 ±1 被平方消掉），
    再用抛物线插值把精度从"半个 bin"提到"1/20 bin"。
    前提：f_c < fs/4（我们的实际场景：PC 侧近零中频、ADDA 侧 6.75 MHz @31.25 MSPS 都满足）。
    """
    z = x * x
    n = min(len(z), 1 << 15)
    Z = np.fft.fftshift(np.abs(np.fft.fft(z[:n] * np.hanning(n))))
    f = np.fft.fftshift(np.fft.fftfreq(n, 1.0 / fs))
    i = int(np.argmax(Z))
    d = 0.0
    if 0 < i < len(Z) - 1:
        a, b, c = Z[i - 1], Z[i], Z[i + 1]
        den = a - 2 * b + c
        if abs(den) > 1e-12:
            d = 0.5 * (a - c) / den
    df = f[1] - f[0]
    return float(f[i] + d * df) / 2.0


def _ddc(x, fs, f0):
    t = np.arange(len(x)) / fs
    return x * np.exp(-2j * np.pi * f0 * t)


def _decimate_to_symbols(bb, sps_real, beta=0.35):
    """匹配滤波（SRRC）+ 按分数 sps 抽取到符号点，返回实部序列"""
    sps = max(2, int(round(sps_real)))
    h = srrc_local(beta, sps)
    mf = np.convolve(bb.real, h, mode="same") + 1j * np.convolve(bb.imag, h, mode="same")
    pos = np.arange(0, len(mf) - 1, sps_real)
    if len(pos) < 64:
        return None
    i0 = pos.astype(int)
    frac = pos - i0
    return mf[i0] * (1 - frac) + mf[np.minimum(i0 + 1, len(mf) - 1)] * frac


def srrc_local(beta=0.35, sps=10, span=8):
    """本地版 SRRC（避免依赖 ccsds 模块路径）"""
    N = span * sps
    t = (np.arange(-N // 2, N // 2 + 1)) / float(sps)
    h = np.zeros_like(t)
    for i, ti in enumerate(t):
        if abs(ti) < 1e-8:
            h[i] = 1.0 - beta + 4 * beta / np.pi
        elif abs(abs(ti) - 1.0 / (4 * beta)) < 1e-6:
            h[i] = (beta / np.sqrt(2)) * (
                (1 + 2 / np.pi) * np.sin(np.pi / (4 * beta)) -
                (1 - 2 / np.pi) * np.cos(np.pi / (4 * beta)))
        else:
            num = np.sin(np.pi * ti * (1 - beta)) + 4 * beta * ti * np.cos(np.pi * ti * (1 + beta))
            den = np.pi * ti * (1 - (4 * beta * ti) ** 2)
            h[i] = num / den
    return h / np.sqrt(np.sum(h ** 2))


def _cfo_fine(sym, fs, sym_rate):
    """
    平方律精估 BPSK 残余频偏。
      s_k = A·e^{j(2πΔf·k·T + φ)}
      s_k² 的相位每符号前进 4πΔf·T  ⇒  Δf = Δφ / (4πT)
    对 ±1 的数据不敏感（平方后恒为 +1）。
    """
    if sym is None or len(sym) < 32:
        return 0.0
    z = sym ** 2
    z = z / (np.abs(z) + 1e-12)
    d = z[1:] * np.conj(z[:-1])
    dphi = np.angle(np.mean(d))
    T = 1.0 / sym_rate
    return dphi / (4 * np.pi * T)


def demod_text(iq, fs, sym_rate=None, verbose=True):
    """
    解调 BPSK 文本帧：[AA AA][len][text][CRC16]

    流程（对应 ADDA 板 PS 侧要实现的部分）：
      1) FFT 粗频偏
      2) 下变频 + SRRC 匹配滤波 + 抽取到符号点
      3) ★ 平方律精估残余频偏（粗估的误差足以让 100 符号后完全反相）
      4) 用修正后的频偏重做 2)
      5) 定时（相位 1/8 步进）与极性（±）二维搜索，找 AA AA + CRC
    """
    x = np.asarray(iq)
    if not np.iscomplexobj(x):
        x = x.astype(np.float64)
    if len(x) < 2048:
        return None

    f0 = _cfo_coarse(x, fs)

    # 过采样比：已知符号率就直接用，否则扫描
    if sym_rate and sym_rate > 0:
        sps0 = fs / sym_rate
        cand = [sps0]
    else:
        sps0 = 25.0
        cand = list(np.arange(max(2.0, sps0 * 0.5), sps0 * 2.0, max(0.05, sps0 / 100.0)))
        cand = cand[:400]

    # ---- 精估频偏（在 sps0 下做一次即可）----
    bb = _ddc(x, fs, f0)
    syms = _decimate_to_symbols(bb, sps0)
    df = _cfo_fine(syms, fs, sym_rate) if (sym_rate and syms is not None) else 0.0
    if verbose:
        print("    粗频偏 %+.0f Hz，精估修正 %+.1f Hz ⇒ %.0f Hz" % (f0, df, f0 + df))
    f0 += df

    bb = _ddc(x, fs, f0)
    best = None
    for sps in cand:
        sym = _decimate_to_symbols(bb, sps)
        if sym is None:
            continue
        sr = sym.real
        for kk in range(8):
            off = int(round(kk * sps / 8.0))
            s = sr[off:]
            if len(s) < 80:
                continue
            # 极性：发射端 bit0 -> +1；空口有 180° 多义性，两种都试
            for pol in (0, 1):
                bits = (s < 0).astype(np.uint8) if pol == 0 else (s > 0).astype(np.uint8)
                r = _extract(bits)
                if r[1]:
                    txt, _, crc_ok = r
                    score = (100000 if crc_ok else 0) + len(txt)
                    if best is None or score > best[0]:
                        best = (score, txt, sps, off, crc_ok, f0)
    if best is None:
        return None
    score, txt, sps, off, crc_ok, f0 = best
    return txt, sps, off, crc_ok, f0


def _crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def _extract(bits):
    """在比特流里找 AA AA 前导，取出长度和文本，验 CRC"""
    by = np.packbits(bits[: (len(bits) // 8) * 8]).tobytes()
    for i in range(len(by) - 4):
        if by[i] != 0xAA or by[i + 1] != 0xAA:
            continue
        ln = by[i + 2]
        if ln == 0 or ln > 200 or i + 3 + ln + 2 > len(by):
            continue
        body = by[i + 3: i + 3 + ln]
        crc = (by[i + 3 + ln] << 8) | by[i + 4 + ln]
        if _crc16(body) == crc:
            try:
                return body.decode("utf-8"), True, True
            except Exception:
                pass
        # 即使 CRC 不过，也返回可疑结果供排查
        try:
            return body.decode("utf-8", "replace"), True, False
        except Exception:
            continue
    return None, False, False


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default=DEF_IP)
    ap.add_argument("--user", default=DEF_USER)
    ap.add_argument("--pw", default=DEF_PW)
    ap.add_argument("--lo", type=float, default=1000.0, help="RX 本振 MHz")
    ap.add_argument("--fs", type=float, default=30_720_000.0, help="采样率 Hz")
    ap.add_argument("--bw", type=float, default=2_000_000.0, help="RF 带宽 Hz")
    ap.add_argument("--gain", type=int, default=30, help="RX 增益 dB (0..76)")
    ap.add_argument("--samples", type=int, default=262144, help="抓多少个复样点")
    ap.add_argument("--check", action="store_true", help="只检查环境")
    ap.add_argument("--fft", action="store_true", help="显示频谱")
    ap.add_argument("--demod", action="store_true", help="尝试解调文本帧")
    ap.add_argument("--sym-rate", type=float, default=0.0,
                    help="已知符号率 Hz（强烈建议给，解调又快又准）")
    ap.add_argument("--save", default=None, help="把 IQ 存到本地文件")
    a = ap.parse_args()

    print("=" * 76)
    print("  接收端：IIO 抓 IQ → PC 解析")
    print("=" * 76)
    print("  板子      : %s@%s" % (a.user, a.ip))
    print("  RX LO     : %.1f MHz" % a.lo)
    print("  采样率    : %.2f MSPS" % (a.fs / 1e6))
    print("  RF 带宽   : %.2f MHz" % (a.bw / 1e6))
    print("  RX 增益   : %d dB" % a.gain)
    print("  抓取长度  : %d 复样点" % a.samples)

    b = Board(a.ip, a.user, a.pw)
    try:
        b.connect()
        print("\n  ✓ SSH 已连上")
    except Exception as e:
        print("\n  ✗ %s" % str(e)[:200])
        print("\n  排查：")
        print("    1. 板子 USB 插的是 OTG 口（不是 JTAG 口），线能传数据")
        print("    2. 板子启动完成（30~60 秒），PC 出现 RNDIS 网卡")
        print("    3. PC 网卡 IP 是 192.168.2.x，能 ping 通 %s" % a.ip)
        return 2

    print("\n-- IIO 设备 --")
    out = b.sh("iio_info -s 2>&1 | head -25", show=True)

    print("\n-- 当前 RX 配置 --")
    b.sh("iio_attr -u ip:localhost -c ad9361-phy voltage0 sampling_frequency; "
         "iio_attr -u ip:localhost -c ad9361-phy voltage0 rf_bandwidth; "
         "iio_attr -u ip:localhost -c ad9361-phy altvoltage0 frequency", show=True)

    if a.check:
        return 0

    print("\n-- 配置 RX1（LO %.1f MHz）--" % a.lo)
    cmds = [
        "iio_attr -u ip:localhost -c ad9361-phy voltage0 sampling_frequency %d" % int(a.fs),
        "iio_attr -u ip:localhost -c ad9361-phy voltage0 rf_bandwidth %d" % int(a.bw),
        "iio_attr -u ip:localhost -c ad9361-phy voltage0 rf_port_select A_BALANCED",
        "iio_attr -u ip:localhost -i -c ad9361-phy voltage0 gain_control_mode manual",
        "iio_attr -u ip:localhost -i -c ad9361-phy voltage0 hardwaregain %d" % a.gain,
        "iio_attr -u ip:localhost -c ad9361-phy altvoltage0 frequency %d" % int(a.lo * 1e6),
    ]
    for c in cmds:
        b.sh(c)
    b.sh("iio_attr -u ip:localhost -c ad9361-phy altvoltage0 frequency; "
         "iio_attr -u ip:localhost -c ad9361-phy voltage0 sampling_frequency", show=True)

    print("\n-- 抓取 %d 复样点 --" % a.samples)
    # 注意：iio_readdev 的 -s 单位是【每通道样点数】，对 I/Q 两通道即复样点数。
    # 不要在 Python 侧再乘 2 或乘 4。
    t0 = time.time()
    b.sh("iio_readdev -u ip:localhost -b 65536 -s %d cf-ad9361-lpc voltage0 voltage1 > /tmp/rx.bin"
         % a.samples, timeout=180)
    print("   板侧抓取完成（%.1f 秒）" % (time.time() - t0))

    local = os.path.join(os.environ.get("TEMP", "."), "rx_cap.bin")
    if not b.pull("/tmp/rx.bin", local):
        print("  ✗ 拉取失败")
        return 3
    iq = np.fromfile(local, dtype=np.int16)
    # I/Q 交织 → 复数
    c = iq[0::2].astype(np.float64) + 1j * iq[1::2].astype(np.float64)
    print("   收到 %d 复样点，RMS = %.1f" %
          (len(c), float(np.sqrt(np.mean(np.abs(c) ** 2)))))
    if len(c) < 1024:
        print("  ✗ 样点太少，抓取可能失败（检查 iio_readdev 是否报错）")
        return 4

    if a.save:
        iq.tofile(a.save)
        print("   已保存: %s  (%d 字节)" % (a.save, os.path.getsize(a.save)))

    if a.fft or not a.demod:
        print("\n-- 频谱（IQ 单边谱，相对峰值）--")
        fft_report(c, a.fs)

    if a.demod:
        print("\n-- 解调文本帧 --")
        r = demod_text(c, a.fs, sym_rate=(a.sym_rate or None))
        if r is None:
            print("   未找到可解的内容")
            print("   可能原因：")
            print("     · 转发板还没把 f1 搬到 f2（检查 lo 命令）")
            print("     · 接收本振不是 f2")
            print("     · 信号太弱（看上面 RMS，目标 1000~5000）")
            print("     · 过载（RMS 接近 30000 就加衰减）")
        else:
            txt, sps, ph, crc_ok, f0 = r
            print("   文本     : %r" % txt)
            print("   符号率估 : %.3f kSPS  (每符号 %.2f 样点, 相位偏移 %d)" % (a.fs / sps / 1e3, sps, ph))
            print("   频偏     : %+.0f Hz" % f0)
            print("   CRC      : %s" % ("通过 ✓" if crc_ok else "未通过 ✗"))
            if crc_ok:
                print("\n   ★ 转发内容解出成功")
    print()
    print("=" * 76)
    return 0


if __name__ == "__main__":
    sys.exit(main())
