#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ttc_fsk_test.py -- 遥控遥测闭环验证（在 3588 上运行，单进程 libiio）

关键设计
--------
① 用 libiio 的循环缓冲区(cyclic)把整帧 FSK 波形一次推进 TX DMA，
   硬件自动无限重复 -> 发送是连续的，接收随时能抓到。
② 收发在同一个 iio.Context 里，不会互相抢 USB 设备。
③ FSK 判频不需要相干 I/Q，绕开通道布局问题，结果无歧义。

链路
----
  造 CCSDS 遥控包 -> FSK 调制 -> 循环缓冲区 -> TX
   ->〔TX-RX 短接线〕-> RX -> 抓 IQ -> 分窗 FFT 判频 -> 找同步字
   -> 解 CCSDS -> 校验 CRC -> 逐字节比对
"""
import json
import os
import subprocess
import sys
import time

import numpy as np

sys.path.insert(0, "/tmp/ttc")
from ttc_modem import crc16, make_ccsds_packet, parse_ccsds_packet

URI = "usb:"
LO = 1000_000_000
FS = 2_500_000
F0 = 150_000            # bit 0
F1 = 400_000            # bit 1
T_BIT = 0.004           # 4 ms/bit -> 250 bit/s
SYNC = 0x1ACFFC1D
PRE = 0xAA


def emit(kind, **kw):
    kw["t"] = time.strftime("%H:%M:%S")
    kw["kind"] = kind
    print("TTC|" + json.dumps(kw, ensure_ascii=False))
    sys.stdout.flush()


def sh(cmd, timeout=120):
    r = subprocess.run(cmd, shell=True, capture_output=True, timeout=timeout)
    return (r.stdout or b"").decode("utf-8", "replace").strip()


def bits_of(data):
    out = []
    for b in bytearray(data):
        for i in range(7, -1, -1):
            out.append((b >> i) & 1)
    return out


def build_wave(bits):
    """把 bit 流做成 FSK 基带波形，返回交错 int16 (I,Q,I,Q...)"""
    spb = int(T_BIT * FS)
    t = np.arange(spb) / FS
    segs = []
    for b in bits:
        f = F0 if b == 0 else F1
        segs.append(np.exp(1j * 2 * np.pi * f * t))
    bb = np.concatenate(segs)
    I = np.clip(np.real(bb) * 8000, -32768, 32767).astype(np.int16)
    Q = np.clip(np.imag(bb) * 8000, -32768, 32767).astype(np.int16)
    out = np.empty(2 * len(I), dtype=np.int16)
    out[0::2] = I
    out[1::2] = Q
    return out, spb


def main():
    # ---------- 配置 ----------
    emit("phase", msg="配置遥测板")
    for c in ["-c ad9361-phy altvoltage1 frequency %d" % LO,
              "-c ad9361-phy altvoltage0 frequency %d" % LO,
              "-c ad9361-phy voltage0 sampling_frequency %d" % FS,
              "-c ad9361-phy voltage0 rf_bandwidth 1000000",
              "-c ad9361-phy voltage1 rf_bandwidth 1000000",
              "-i -c ad9361-phy voltage0 gain_control_mode manual",
              "-i -c ad9361-phy voltage0 hardwaregain 60",
              "-i -c ad9361-phy voltage1 gain_control_mode manual",
              "-i -c ad9361-phy voltage1 hardwaregain 60",
              "-o -c ad9361-phy voltage1 hardwaregain -40",
              "-c cf-ad9361-dds-core-lpc altvoltage0 scale 0",
              "-c cf-ad9361-dds-core-lpc altvoltage1 scale 0"]:
        sh("iio_attr -u %s %s" % (URI, c), timeout=40)
    emit("cfg", lo=LO, fs=FS, f0=F0, f1=F1, t_bit_ms=T_BIT * 1e3,
         rate=1.0 / T_BIT, tx_att=-40, rx_gain=60)

    # ---------- 造包 ----------
    payload = bytes([0x01, 0x04, 0x00, 0x00, 0x00, 0x08, 0x00, 0x00])
    pkt = make_ccsds_packet(0x100, payload, seq=1, ptype=0)
    frame = (bytes([PRE]) + SYNC.to_bytes(4, "big") + pkt
             + crc16(pkt).to_bytes(2, "big"))
    bits = bits_of(frame)
    emit("packet", apid=0x100, pkt_len=len(pkt), frame_len=len(frame),
         bits=len(bits), dur_s=len(bits) * T_BIT, hex=frame.hex())

    wave, spb = build_wave(bits)
    emit("wave", samples=len(bits) * spb, bytes=wave.nbytes,
         frame_s=len(bits) * T_BIT)

    # ---------- 打开上下文 ----------
    import iio
    ctx = iio.Context(URI)
    tx = ctx.find_device("cf-ad9361-dds-core-lpc")
    rx = ctx.find_device("cf-ad9361-lpc")
    emit("ctx", tx=tx.name, rx=rx.name)

    # ---------- TX：循环缓冲区 ----------
    emit("phase", msg="启动 TX 循环缓冲区（硬件自动重复）")
    for ch in tx.channels:
        if ch.output:
            ch.enabled = True
    txbuf = iio.Buffer(tx, len(bits) * spb, True)      # cyclic
    txbuf.write(bytearray(wave.tobytes()))             # ★ 必须可写缓冲区
    txbuf.push()
    emit("txon", bytes=wave.nbytes, cyclic=True)
    time.sleep(0.6)

    # ---------- RX：抓若干帧 ----------
    n_rx = int(FS * (len(bits) * T_BIT) * 2.2)         # 约 2.2 帧
    emit("phase", msg="接收 %d 样点（约 %.2f 秒）" % (n_rx, n_rx / FS))
    for nm in ("voltage0", "voltage1"):
        ch = rx.find_channel(nm)
        if ch:
            ch.enabled = True
    for nm in ("voltage2", "voltage3"):
        ch = rx.find_channel(nm)
        if ch:
            ch.enabled = False
    rxbuf = iio.Buffer(rx, n_rx, False)
    t0 = time.time()
    rxbuf.refill()
    el = time.time() - t0
    data = rxbuf.read()
    emit("rx", samples=n_rx, ms=el * 1e3, bytes=len(data))

    # ---------- 关 TX ----------
    try:
        txbuf.cancel()
    except Exception:
        pass
    emit("txoff")

    # ---------- 解调 ----------
    raw = np.frombuffer(data, dtype=np.int16)
    chs = [raw[i::2].astype(np.float64) for i in range(2)]
    stds = [float(c.std()) for c in chs]
    emit("rxstat", stds=[round(s, 1) for s in stds])
    ci = int(np.argmax(stds))
    c = chs[ci]
    c = c - c.mean()
    emit("chan", ch=ci, std=round(stds[ci], 1))

    # 每 bit 的参考复指数（直接相关，比 FFT 快得多）
    # 加 Hann 窗：抑制直流/本振泄漏造成的频谱泄漏
    t = np.arange(spb) / FS
    wnd = np.hanning(spb)
    r0 = np.exp(-1j * 2 * np.pi * F0 * t) * wnd
    r1 = np.exp(-1j * 2 * np.pi * F1 * t) * wnd

    def judge(seg):
        """返回 0/1 和信心比"""
        e0 = abs(np.dot(seg, r0)) ** 2
        e1 = abs(np.dot(seg, r1)) ** 2
        return (0 if e0 >= e1 else 1), (max(e0, e1) / (min(e0, e1) + 1e-9))

    def demod_at(offset, nbits):
        b = np.empty(nbits, dtype=np.uint8)
        for k in range(nbits):
            s = offset + k * spb
            seg = c[s:s + spb]
            if len(seg) < spb:
                return b[:k]
            b[k] = judge(seg)[0]
        return b

    # ---------- 诊断：接收信号的频谱长什么样 ----------
    N = 8192
    K = min(len(c) // N, 200)
    acc = np.zeros(N)
    w8 = np.hanning(N)
    for k in range(K):
        acc += np.abs(np.fft.fftshift(np.fft.fft(c[k*N:(k+1)*N] * w8)))**2
    P = 10*np.log10(acc/K + 1e-20)
    fz = (np.arange(N) - N//2) * (FS/N)
    nb = float(np.median(P))
    top = np.argsort(P)[-8:][::-1]
    emit("spectrum", noise=round(nb, 1),
         top=[(round(float(fz[i]/1e3), 1), round(float(P[i]-nb), 1)) for i in top])
    b0 = np.abs(fz - F0) < 15000
    b1 = np.abs(fz - F1) < 15000
    bd = np.abs(fz) < 15000
    emit("bands",
         f0_db=round(float(P[b0].max()-nb), 1),
         f1_db=round(float(P[b1].max()-nb), 1),
         dc_db=round(float(P[bd].max()-nb), 1))

    # ---------- 搜索 bit 相位偏移 ----------
    emit("phase", msg="搜索 bit 相位偏移")
    sbits = np.array(bits_of(SYNC.to_bytes(4, "big")))
    nprobe = min(300, len(c) // spb - 40)
    step = max(1, spb // 60)
    best = (99, -1, 0)
    for off in range(0, spb, step):
        bb = demod_at(off, nprobe)
        if len(bb) < len(sbits):
            continue
        for s in range(0, len(bb) - len(sbits)):
            e = int(np.sum(bb[s:s + len(sbits)] != sbits))
            if e < best[0]:
                best = (e, off, s)
            if e == 0:
                break
        if best[0] == 0:
            break
    emit("search", best_err=best[0], offset=best[1], step=step, probes=nprobe)
    if best[0] > 2:
        emit("result", ok=False,
             reason="搜索 %d 个相位偏移后仍找不到同步字（最好错 %d bit）" % (spb // step, best[0]))
        emit("done", msg="失败")
        return 1

    # ---------- 用最佳偏移完整解调 ----------
    off, spos = best[1], best[2]
    emit("phase", msg="用最佳偏移 %d 完整解调" % off)
    arr = demod_at(off, len(c) // spb)
    emit("demod", samples=len(c), spb=spb, bits=len(arr), offset=off)
    found = spos
    ferr = int(np.sum(arr[found:found + len(sbits)] != sbits))
    emit("sync", found_at=found, err=ferr, ok=(ferr <= 2))

    # ---------- 解包 ----------
    need = (len(pkt) + 2) * 8
    db = arr[found + len(sbits):found + len(sbits) + need]
    if len(db) < need:
        emit("result", ok=False, reason="数据位不够")
        emit("done", msg="失败")
        return 1
    rxbytes = bytes(bytearray(np.packbits(db).tolist()))
    rx_pkt, rx_crc = rxbytes[:len(pkt)], rxbytes[len(pkt):len(pkt) + 2]

    ref = np.array(bits_of(pkt + crc16(pkt).to_bytes(2, "big")))
    nerr = int(np.sum(db != ref))
    ber = nerr / float(need)
    emit("ber", ber=ber, errors=nerr, total=need)

    cc = crc16(rx_pkt)
    rr = int.from_bytes(rx_crc, "big")
    ok = (cc == rr) and (rx_pkt[6:] == payload)
    emit("result", ok=bool(ok), apid=int.from_bytes(rx_pkt[:2], "big") & 0x7FF,
         crc_ok=(cc == rr), crc_rx=rr, crc_calc=cc,
         match=(rx_pkt[6:] == payload), ber=ber,
         tx=payload.hex(), rx=rx_pkt[6:].hex(),
         rx_pkt=rx_pkt.hex(), tx_pkt=pkt.hex())
    emit("done", msg="FSK 遥控遥测闭环验证结束")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
