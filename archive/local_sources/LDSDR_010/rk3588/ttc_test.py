#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ttc_test.py -- 在 RK3588 上运行：测控链路端到端测试

做四件事，结果以 `TTC|<json>` 行输出，供电脑端 ttc_monitor.py 显示：

  ① 读转发板状态（遥测源数据）
  ② 打包成 CCSDS 遥测包 + 调制
  ③ 通过遥测板 TX 发出
  ④ 通过遥测板 RX 收回来 → 解调 → 校验 → 逐字节比对

用法：
    python3 ttc_test.py send          # 只发（CMU200 看）
    python3 ttc_test.py loop          # 发+收（需要射频环回）
    python3 ttc_test.py soft          # 纯软件环回（不用射频）
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from ttc_modem import (FS_DEFAULT, IF_HZ, SYM_RATE, make_ccsds_packet,
                       parse_ccsds_packet, build_frame_bytes, modulate,
                       interleave_iq, demodulate, find_sync_and_parse, crc16)

URI = "usb:"
TX_LO = 1000_000_000
RX_LO = 1000_000_000
FS = 2_500_000
TX_ATT = -60          # ★ 统一用 -60：连上电瞬态都低于 RX 的 +2.5 dBm 损坏阈值
RX_GAIN = 30
WAVE = "/tmp/ttc_wave.bin"
CAP = "/tmp/ttc_cap.bin"
REPS = 40                     # 一帧重复次数（越大单次突发越长）
SEND_SECONDS = 5.0            # 连续发送时长（秒）
CAP_SAMPLES = 524288          # 抓 524288 样点（约 210 ms）


def emit(kind, **kw):
    """输出一行给电脑端"""
    kw["t"] = time.strftime("%H:%M:%S")
    kw["kind"] = kind
    print("TTC|" + json.dumps(kw, ensure_ascii=False))
    sys.stdout.flush()


def run(cmd, timeout=180):
    r = subprocess.run(cmd, shell=True, capture_output=True, timeout=timeout)
    return (r.stdout or b"").decode("utf-8", "replace").strip()


# ---------------------------------------------------------------------
def cfg_board():
    emit("phase", msg="配置遥测板")
    cmds = [
        "iio_attr -u %s -c ad9361-phy altvoltage1 frequency %d" % (URI, TX_LO),
        "iio_attr -u %s -c ad9361-phy altvoltage0 frequency %d" % (URI, RX_LO),
        "iio_attr -u %s -c ad9361-phy voltage0 sampling_frequency %d" % (URI, FS),
        "iio_attr -u %s -c ad9361-phy voltage0 rf_bandwidth 1000000" % URI,
        "iio_attr -u %s -c ad9361-phy voltage1 rf_bandwidth 1000000" % URI,
        "iio_attr -u %s -i -c ad9361-phy voltage0 gain_control_mode manual" % URI,
        "iio_attr -u %s -i -c ad9361-phy voltage0 hardwaregain %d" % (URI, RX_GAIN),
        "iio_attr -u %s -i -c ad9361-phy voltage1 gain_control_mode manual" % URI,
        "iio_attr -u %s -i -c ad9361-phy voltage1 hardwaregain %d" % (URI, RX_GAIN),
        "iio_attr -u %s -o -c ad9361-phy voltage1 hardwaregain %d" % (URI, TX_ATT),
        # 关掉 DDS，避免和 DMA 数据打架
        "iio_attr -u %s -c cf-ad9361-dds-core-lpc altvoltage0 scale 0" % URI,
        "iio_attr -u %s -c cf-ad9361-dds-core-lpc altvoltage1 scale 0" % URI,
    ]
    for c in cmds:
        run(c, timeout=40)
    txg = run("iio_attr -u %s -o -c ad9361-phy voltage1 hardwaregain 2>&1|tail -1" % URI)
    rxg = run("iio_attr -u %s -i -c ad9361-phy voltage0 hardwaregain 2>&1|tail -1" % URI)
    fsr = run("iio_attr -u %s -c ad9361-phy voltage0 sampling_frequency 2>&1|tail -1" % URI)
    emit("cfg", tx_lo=TX_LO, rx_lo=RX_LO, fs=FS, tx_att=TX_ATT, rx_gain=RX_GAIN,
         tx_att_readback=txg.replace(" dB", ""), rx_gain_readback=rxg.replace(" dB", ""),
         fs_readback=fsr)


def read_relay_status():
    """从转发板（串口）读状态，作为遥测源数据"""
    for dev in ("/dev/ttyUSB1", "/dev/ttyUSB0", "/dev/ttyUSB2", "/dev/ttyUSB3"):
        if not os.path.exists(dev):
            continue
        try:
            run("stty -F %s 115200 raw -echo -crtscts 2>/dev/null" % dev, timeout=10)
            r = run("(timeout 1.2 cat %s > /tmp/ttc_rx.txt &) ; sleep 0.2; "
                    "printf 'status\\r\\n' > %s; sleep 1.3; "
                    "grep -m1 STAT /tmp/ttc_rx.txt" % (dev, dev), timeout=20)
            if "STAT" in r:
                return dev, r.split("STAT", 1)[1].strip()
        except Exception:
            pass
    return None, None


def make_telemetry():
    """构造遥测包"""
    dev, stat = read_relay_status()
    if stat:
        emit("relay", dev=dev, raw=stat[:120])
        # 从 STAT 行里抽几个字段
        kv = {}
        for tok in stat.split():
            if "=" in tok:
                k, v = tok.split("=", 1)
                kv[k] = v
        payload = bytes([
            1,                                        # 模式 relay
            int(kv.get("dc", "0")) & 0xFF,
            (int(kv.get("gain", "0x800"), 16) >> 8) & 0xFF,
            int(kv.get("gain", "0x800"), 16) & 0xFF,
            (int(kv.get("in", "0")) >> 16) & 0xFF,    # 收计数低 3 字节
            (int(kv.get("in", "0")) >> 8) & 0xFF,
            int(kv.get("in", "0")) & 0xFF,
            int(kv.get("rc", "0")) & 0xFF,
        ])
        src = "转发板状态 @ %s" % dev
    else:
        payload = bytes([1, 0, 0x08, 0x00, 0x11, 0x22, 0x33, 0x00])
        src = "无转发板，用示例数据"
    return payload, src


# ---------------------------------------------------------------------
def do_soft():
    emit("phase", msg="纯软件环回（不碰射频）")
    payload, src = make_telemetry()
    pkt = make_ccsds_packet(0x200, payload, seq=1, ptype=1)
    emit("packet", src=src, apid=0x200, n=len(pkt), hex=pkt.hex())
    frame = build_frame_bytes(pkt)          # ★ 必须加前导+同步字
    emit("frame", n=len(frame), hex=frame.hex())
    I, Q = modulate(frame, fs=FS)
    bits = demodulate(I, Q, fs=FS)
    ok, info, pk = find_sync_and_parse(bits)
    if pk:
        emit("result", ok=ok, apid=pk["apid"], crc=pk["crc_ok"],
             match=(pk["payload"] == payload),
             tx=payload.hex(), rx=pk["payload"].hex(),
             sync_at=info.get("sync_at_byte"))
    else:
        emit("result", ok=False, reason=info.get("reason"))
    emit("done", msg="纯软件环回结束（未使用射频）")
    return 0


def do_tone(on=True):
    """用硬件 DDS 发连续单音 —— 最无歧义的发射验证

    连续、无突发间隙、频率精确已知。频谱仪慢慢调都能看到。
    """
    if not on:
        emit("phase", msg="关闭 DDS 单音")
        for ch in ("altvoltage0", "altvoltage1", "altvoltage2", "altvoltage3"):
            run("iio_attr -u usb: -c cf-ad9361-dds-core-lpc %s scale 0" % ch, timeout=40)
        emit("result", ok=True, sent=True, msg="DDS 已关闭")
        emit("done", msg="单音已停")
        return 0

    cfg_board()
    emit("phase", msg="开启硬件 DDS 连续单音")
    for ch in ("altvoltage0", "altvoltage1"):
        run("iio_attr -u usb: -c cf-ad9361-dds-core-lpc %s frequency %d" % (ch, IF_HZ),
            timeout=40)
        run("iio_attr -u usb: -c cf-ad9361-dds-core-lpc %s scale 0.5" % ch, timeout=40)
        run("iio_attr -u usb: -c cf-ad9361-dds-core-lpc %s raw 2048" % ch, timeout=40)
    fr = run("iio_attr -u usb: -c cf-ad9361-dds-core-lpc altvoltage0 frequency 2>&1|tail -1")
    sc = run("iio_attr -u usb: -c cf-ad9361-dds-core-lpc altvoltage0 scale 2>&1|tail -1")
    txg = run("iio_attr -u usb: -o -c ad9361-phy voltage1 hardwaregain 2>&1|tail -1")
    out_hz = TX_LO + IF_HZ
    emit("tone", tx_lo=TX_LO, if_hz=IF_HZ, out_hz=out_hz,
         dds_freq=fr.strip(), dds_scale=sc.strip(), tx_att=txg.strip())
    emit("result", ok=True, sent=True,
         msg="连续单音已开启：%.4f MHz，DDS 幅度 %s，TX 衰减 %s"
             % (out_hz / 1e6, sc.strip(), txg.strip()))
    emit("done", msg="DDS 会一直发（连续，无间隙）。CMU200 慢慢调即可。停止用 toneoff")
    return 0


def do_send(loop=False):
    cfg_board()
    payload, src = make_telemetry()
    pkt = make_ccsds_packet(0x200, payload, seq=1, ptype=1)
    emit("packet", src=src, apid=0x200, n=len(pkt), hex=pkt.hex())

    frame = build_frame_bytes(pkt)          # ★ 必须加前导+同步字
    emit("frame", n=len(frame), hex=frame.hex())
    I, Q = modulate(frame, fs=FS, reps=REPS)
    stream = interleave_iq(I, Q)
    stream.tofile(WAVE)
    burst_ms = len(I) / FS * 1e3
    emit("wave", n=len(I), ms=burst_ms, bytes=os.path.getsize(WAVE), reps=REPS)

    emit("phase", msg="连续发送 %.0f 秒（每次突发 %.0f ms）" % (SEND_SECONDS, burst_ms))
    txs = []
    t0 = time.time()
    k = 0
    while time.time() - t0 < SEND_SECONDS:
        k += 1
        r = run("timeout 60 iio_writedev -u %s -s %d -b %d cf-ad9361-dds-core-lpc "
                "voltage0 voltage1 < %s 2>&1; echo rc=$?" % (URI, len(I), len(I), WAVE),
                timeout=90)
        rc = r.splitlines()[-1] if r else "?"
        txs.append(rc)
        if k <= 3 or k % 10 == 0:
            emit("tx", n=k, rc=rc, el=time.time() - t0)
    allok = all("rc=0" in t for t in txs)
    emit("txsum", count=k, ok=allok, seconds=time.time() - t0)

    if not loop:
        emit("result", ok=allok, sent=True,
             msg="共发送 %d 次，累计 %.1f 秒" % (k, time.time() - t0),
             reason=None if allok else "有 iio_writedev 返回非 0")
        emit("done", msg="请到 CMU200 上看 1000.2 MHz 有没有信号（建议开 Max Hold）")
        return 0

    # ---- 环回收 ----
    emit("phase", msg="接收环回信号")
    run("rm -f %s" % CAP, timeout=10)
    t0 = time.time()
    run("timeout 60 iio_readdev -u %s -s %d -b 262144 cf-ad9361-lpc "
        "voltage0 voltage1 > %s 2>/dev/null" % (URI, CAP_SAMPLES, CAP), timeout=90)
    el = time.time() - t0
    sz = os.path.getsize(CAP) if os.path.exists(CAP) else 0
    emit("rx", bytes=sz, samples=sz // 4, ms=el * 1e3)
    if sz < 4096:
        emit("result", ok=False, reason="没收到数据")
        return 1

    raw = np.fromfile(CAP, dtype=np.int16)
    I2, Q2 = raw[0::2].astype(np.int16), raw[1::2].astype(np.int16)
    emit("rxstat", istd=float(I2.astype(float).std()), imax=int(abs(I2).max()),
         qstd=float(Q2.astype(float).std()))
    bits = demodulate(I2, Q2, fs=FS)
    ok, info, pk = find_sync_and_parse(bits)
    if pk:
        emit("result", ok=ok, apid=pk["apid"], crc=pk["crc_ok"],
             match=(pk["payload"] == payload),
             tx=payload.hex(), rx=pk["payload"].hex(),
             sync_at=info.get("sync_at_byte"))
    else:
        emit("result", ok=False, reason=info.get("reason"), bits=len(bits))
    emit("done", msg="环回测试结束")
    return 0


if __name__ == "__main__":
    act = sys.argv[1] if len(sys.argv) > 1 else "soft"
    if act == "soft":
        sys.exit(do_soft())
    if act == "tone":
        sys.exit(do_tone(True))
    if act == "toneoff":
        sys.exit(do_tone(False))
    sys.exit(do_send(loop=(act == "loop")))
