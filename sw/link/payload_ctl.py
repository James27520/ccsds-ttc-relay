#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
payload_ctl.py -- 载荷遥控/遥测控制台（CCSDS 简化版）

把 CCSDS 空间包翻译成载荷串口命令，并生成遥测回包。

    ┌────────────┐  CCSDS 空间包   ┌──────────────┐  ASCII CLI   ┌────────┐
    │ 信关/上位机 │ ─────────────► │  RK3588      │ ───────────► │ LDSDR  │
    │ (或另一个   │                │ payload_ctl  │              │ 载荷   │
    │  SDR 解出)  │ ◄───────────── │              │ ◄─────────── │        │
    └────────────┘   遥测空间包     └──────────────┘   STAT 行     └────────┘

用法（RK3588 上，LDSDR 的 USB 插在本机）：
    python3 payload_ctl.py status
    python3 payload_ctl.py mode relay
    python3 payload_ctl.py offset 100000            # DUC +100 kHz
    python3 payload_ctl.py offset -100000           # DUC −100 kHz
    python3 payload_ctl.py gain 0x800
    python3 payload_ctl.py rf 900 1000 0 30         # rxlo txlo rxgain txatt
    python3 payload_ctl.py watch                    # 持续监视丢样
    python3 payload_ctl.py demo                     # CCSDS 全链路演示（不需要硬件）

从 CCSDS 二进制包文件执行：
    python3 payload_ctl.py exec --file cmds.bin

自定义串口 / 波特率：
    python3 payload_ctl.py --port /dev/ttyUSB1 --baud 115200 status
"""

import argparse
import os
import struct
import sys
import time

import ccsds
from ccsds import (SpacePacket, PacketDecoder, SeqCounter,
                   APID_RELAY_SET, APID_RF_SET, APID_RELAY_MODE,
                   APID_FREQ_OFFSET, APID_DIG_GAIN, APID_REQ_STATUS,
                   APID_STATUS_TM, APID_ACK_TM, APID_NAMES,
                   TYPE_TC, TYPE_TM, MODE_NAME)
from relay_link import (RelayLink, MODE_VALUE, hz_to_word, word_to_hz)


# =====================================================================
#  CCSDS 包  →  载荷动作
# =====================================================================
class Dispatcher(object):
    """把遥控包翻译成载荷串口命令。dry=True 时只打印不执行。"""

    def __init__(self, link=None, dry=False, verbose=False):
        self.link = link
        self.dry = dry
        self.verbose = verbose
        self.seq = SeqCounter()

    def _say(self, s):
        if self.verbose or self.dry:
            print("  " + s)

    # ---------- 单包 ----------
    def execute(self, pkt):
        """执行一个遥控包，返回遥测回包（或 None）。"""
        if pkt.ptype != TYPE_TC:
            self._say("忽略非遥控包: %r" % pkt)
            return None
        h = getattr(self, "_apid_%03X" % pkt.apid, None)
        if h is None:
            self._say("未知 APID 0x%03X，忽略" % pkt.apid)
            return self._ack(pkt.apid, 1, "unknown apid")
        try:
            res = h(pkt.payload)
        except Exception as e:
            self._say("执行失败: %s" % e)
            return self._ack(pkt.apid, 2, str(e))
        if res is None:
            return None
        return self._ack(pkt.apid, 0, res)

    def _ack(self, apid, code, text=""):
        body = struct.pack(">HB", apid & 0x7FF, code & 0xFF) + text.encode("utf-8")[:60]
        return SpacePacket(APID_ACK_TM, body, self.seq.next(APID_ACK_TM), TYPE_TM)

    # ---------- 各 APID 的处理 ----------
    def _apid_100(self, p):        # RELAY_SET
        d = ccsds.dec_relay_set(p)
        self._say("RELAY_SET mode=%d(%s) duc=0x%08X ddc=0x%08X gain=0x%03X dc=%d"
                  % (d["mode"], MODE_NAME.get(d["mode"], "?"), d["duc"], d["ddc"],
                     d["gain"], d["dc"]))
        if self.link:
            self.link.set_mode(d["mode"])
            self.link.set_duc_word(d["duc"])
            self.link.set_ddc_word(d["ddc"])
            self.link.set_gain(d["gain"])
            self.link.set_dc_block(d["dc"])
        return "relay_set ok"

    def _apid_101(self, p):        # RF_SET
        rx, tx, g, a = struct.unpack(">QQBB", p[:18])
        self._say("RF_SET rxlo=%d MHz txlo=%d MHz rxgain=%d dB txatt=%d dB"
                  % (rx // 1000000, tx // 1000000, g, a))
        if self.link:
            self.link.set_lo(rx // 1000000, tx // 1000000)
            self.link.set_rx_gain(g)
            self.link.set_tx_atten(a)
        return "rf_set ok"

    def _apid_102(self, p):        # RELAY_MODE
        m = struct.unpack(">B", p[:1])[0] & 3
        self._say("RELAY_MODE -> %d(%s)" % (m, MODE_NAME.get(m, "?")))
        if self.link:
            self.link.set_mode(m)
        return "mode %d" % m

    def _apid_103(self, p):        # FREQ_OFFSET
        d = ccsds.dec_freq_offset(p)
        self._say("FREQ_OFFSET duc=%+d Hz ddc=%+d Hz" % (d["duc_hz"], d["ddc_hz"]))
        if self.link:
            self.link.set_duc_hz(d["duc_hz"])
            self.link.set_ddc_hz(d["ddc_hz"])
        return "offset ok"

    def _apid_104(self, p):        # DIG_GAIN
        g, dc = struct.unpack(">HB", p[:3])
        self._say("DIG_GAIN gain=0x%03X dc=%d" % (g, dc))
        if self.link:
            self.link.set_gain(g)
            self.link.set_dc_block(dc)
        return "gain ok"

    def _apid_110(self, p):        # REQ_STATUS
        self._say("REQ_STATUS")
        if self.link and not self.dry:
            st = self.link.status()
        else:
            st = _fake_status()
        body = ccsds.enc_status_tm(st.n_in, st.n_out, st.clip, st.rc,
                                   st.mode, st.ddc, st.duc, st.gain)
        return SpacePacket(APID_STATUS_TM, body, self.seq.next(APID_STATUS_TM),
                           TYPE_TM)

    # ---------- 覆盖：直接返回遥测包而不是 ACK ----------
    def execute_raw(self, pkt):
        if pkt.apid == APID_REQ_STATUS:
            return self._apid_110(pkt.payload)
        r = self.execute(pkt)
        return r


# =====================================================================
#  便捷构造函数
# =====================================================================
def mk_relay_set(mode, duc_hz=None, ddc_hz=None, gain=0x800, dc=0, fs=30_720_000):
    duc = hz_to_word(duc_hz, fs) if duc_hz is not None else 0
    ddc = hz_to_word(ddc_hz, fs) if ddc_hz is not None else 0
    m = MODE_VALUE[mode.upper()] if isinstance(mode, str) else int(mode)
    return SpacePacket(APID_RELAY_SET, ccsds.enc_relay_set(m, duc, ddc, gain, dc))


def mk_rf_set(rx_lo_hz, tx_lo_hz, rxgain_db=0, txatt_db=30):
    return SpacePacket(APID_RF_SET,
                       ccsds.enc_rf_set(rx_lo_hz, tx_lo_hz, rxgain_db, txatt_db))


def mk_mode(mode):
    m = MODE_VALUE[mode.upper()] if isinstance(mode, str) else int(mode)
    return SpacePacket(APID_RELAY_MODE, ccsds.enc_mode(m))


def mk_offset(duc_hz, ddc_hz=0):
    return SpacePacket(APID_FREQ_OFFSET, ccsds.enc_freq_offset(duc_hz, ddc_hz))


def mk_req_status():
    # CCSDS 的"包数据长度"字段定义为 n-1 且 n>=1，空包无法表示，
    # 所以请求状态也带 1 字节数据域（0x00 = 请求全部）。
    return SpacePacket(APID_REQ_STATUS, b"\x00")


def _fake_status():
    from relay_link import RelayStatus
    return RelayStatus(dict(mode=1, ddc=0, duc=0, gain=0x800, dc=0, rxgain=0,
                            txatt=30, rxlo=900, txlo=1000, fs=30_720_000,
                            **{"in": 0, "out": 0, "clip": 0, "rc": 0}))


# =====================================================================
#  打印
# =====================================================================
def print_status(st):
    print("  工作模式   : %s (%d)" % (st.mode_name, st.mode))
    print("  DDC 频偏   : %+.1f Hz   (0x%08X)" % (st.ddc_hz, st.ddc))
    print("  DUC 频偏   : %+.1f Hz   (0x%08X)" % (st.duc_hz, st.duc))
    print("  净变换量   : %+.1f Hz" % st.net_hz)
    print("  数字增益   : 0x%03X (%.3f x)   隔直: %s"
          % (st.gain, st.gain / 2048.0, "开" if st.dc else "关"))
    print("  收发本振   : RX %d MHz / TX %d MHz" % (st.rxlo, st.txlo))
    print("  采样率     : %.3f MSPS" % (st.fs / 1e6))
    print("  RX 增益    : %d dB      TX 衰减: %d dB" % (st.rxgain, st.txatt))
    print("  收 / 发    : %d / %d   差 %d" % (st.n_in, st.n_out, st.n_in - st.n_out))
    print("  饱和计数   : %d  (%.4f%%)"
          % (st.clip, 100.0 * st.clip / st.n_in if st.n_in else 0.0))
    rc = {0: "正常", -1: "无 ADC 数据", -2: "无 DAC 输出"}.get(st.rc, "未知")
    print("  健康状态   : %s (rc=%d)" % (rc, st.rc))


def print_tm(pkt):
    if pkt.apid == APID_STATUS_TM:
        d = ccsds.dec_status_tm(pkt.payload)
        print("  收=%d 发=%d 饱和=%d rc=%d 模式=%s ddc=0x%08X duc=0x%08X gain=0x%03X"
              % (d["in_cnt"], d["out_cnt"], d["clip_cnt"], d["rc"],
                 MODE_NAME.get(d["mode"], "?"), d["ddc"], d["duc"], d["gain"]))
    elif pkt.apid == APID_ACK_TM:
        apid, code = struct.unpack(">HB", pkt.payload[:3])
        txt = pkt.payload[3:].decode("utf-8", "replace")
        print("  ACK 针对 0x%03X: %s %s"
              % (apid, "OK" if code == 0 else "失败(%d)" % code, txt))
    elif pkt.apid == APID_SPECTRUM_TM:
        d = ccsds.dec_spectrum_tm(pkt.payload)
        print("  频谱: %d 个频点, fs=%d" % (len(d["bins_db"]), d["fs"]))
    else:
        print("  TM %r" % pkt)


# =====================================================================
#  主程序
# =====================================================================
def open_link(args):
    if args.port:
        return RelayLink(args.port, args.baud, verbose=args.verbose)
    return RelayLink.autodetect(baud=args.baud, verbose=args.verbose)


def main():
    ap = argparse.ArgumentParser(
        description="LDSDR 载荷遥控控制台（CCSDS 简化版）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    ap.add_argument("--port", help="串口设备，缺省自动检测")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="只构造并打印 CCSDS 包，不连硬件")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("status", help="读一次完整状态")
    sub.add_parser("watch", help="持续监视（丢样自动检测）").add_argument(
        "--interval", type=float, default=2.0)
    sub.add_parser("demo", help="CCSDS 全链路演示，不需要硬件")

    p = sub.add_parser("mode", help="切工作模式")
    p.add_argument("mode", choices=["bypass", "relay", "mute", "duc_only",
                                    "0", "1", "2", "3"])

    p = sub.add_parser("offset", help="设频偏（Hz）")
    p.add_argument("duc_hz", type=int)
    p.add_argument("ddc_hz", type=int, nargs="?", default=0)

    p = sub.add_parser("gain", help="数字增益（0x000~0xFFF，0x800=1.0）")
    p.add_argument("value")
    p.add_argument("--dc", type=int, default=0, help="隔直 0/1")

    p = sub.add_parser("rf", help="射频参数")
    p.add_argument("rx_lo_mhz", type=int)
    p.add_argument("tx_lo_mhz", type=int)
    p.add_argument("rxgain_db", type=int, default=0)
    p.add_argument("txatt_db", type=int, default=30)

    p = sub.add_parser("exec", help="执行 CCSDS 二进制包文件")
    p.add_argument("--file", required=True)

    p = sub.add_parser("mkpkt", help="生成 CCSDS 二进制包到文件")
    p.add_argument("kind", choices=["relay", "mode", "offset", "status"])
    p.add_argument("args", nargs="*")
    p.add_argument("--out", required=True)

    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        return 1
    if args.cmd == "demo":
        return demo()
    if args.cmd == "mkpkt":
        return mkpkt(args)

    # ---- 需要链路的命令 ----
    link = None
    if not args.dry_run:
        try:
            link = open_link(args).open()
        except Exception as e:
            print("打开链路失败: %s" % e, file=sys.stderr)
            return 2
    disp = Dispatcher(link, dry=args.dry_run, verbose=args.verbose)

    try:
        if args.cmd == "status":
            if link:
                print_status(link.status())
            else:
                print_status(_fake_status())

        elif args.cmd == "watch":
            print("持续监视，Ctrl-C 退出\n")
            prev = None
            while True:
                st = link.status()
                line = ("  %s  in=%-12d out=%-12d Δin=%-10s Δout=%-10s "
                        "clip=%-8d 净变换=%+.0fHz %s"
                        % (time.strftime("%H:%M:%S"), st.n_in, st.n_out,
                           "-", "-", st.clip, st.net_hz,
                           "OK" if st.rc == 0 else "rc=%d" % st.rc))
                if prev:
                    din = st.n_in - prev.n_in
                    dout = st.n_out - prev.n_out
                    line = line.replace("Δin=%-10s" % "-", "Δin=%-10d" % din)
                    line = line.replace("Δout=%-10s" % "-", "Δout=%-10d" % dout)
                    if din != dout:
                        line += "   <<< 丢样!"
                print(line)
                prev = st
                time.sleep(args.interval)

        elif args.cmd == "mode":
            m = args.mode if args.mode.isdigit() else MODE_VALUE[args.mode.upper()]
            print("  mode -> %s" % MODE_NAME[int(m)])
            if link:
                link.set_mode(int(m))

        elif args.cmd == "offset":
            print("  DUC %+d Hz (0x%08X)   DDC %+d Hz (0x%08X)"
                  % (args.duc_hz, hz_to_word(args.duc_hz),
                     args.ddc_hz, hz_to_word(args.ddc_hz)))
            if link:
                link.set_duc_hz(args.duc_hz)
                if args.ddc_hz:
                    link.set_ddc_hz(args.ddc_hz)
                st = link.status()
                print("  读回: DUC %+.1f Hz  DDC %+.1f Hz" % (st.duc_hz, st.ddc_hz))

        elif args.cmd == "gain":
            g = int(args.value, 0)
            print("  gain 0x%03X (%.3f x)  隔直=%d" % (g, g / 2048.0, args.dc))
            if link:
                link.set_gain(g)
                link.set_dc_block(args.dc)

        elif args.cmd == "rf":
            print("  RX_LO %d MHz  TX_LO %d MHz  RX增益 %d dB  TX衰减 %d dB"
                  % (args.rx_lo_mhz, args.tx_lo_mhz, args.rxgain_db, args.txatt_db))
            if link:
                link.set_lo(args.rx_lo_mhz, args.tx_lo_mhz)
                link.set_rx_gain(args.rxgain_db)
                link.set_tx_atten(args.txatt_db)

        elif args.cmd == "exec":
            data = open(args.file, "rb").read()
            dec = PacketDecoder()
            pkts = dec.feed(data)
            print("  解出 %d 个包" % len(pkts))
            for pk in pkts:
                print("  -> %r" % pk)
                tm = disp.execute_raw(pk)
                if tm:
                    print("  <- %r" % tm)
        return 0
    except KeyboardInterrupt:
        print("\n已停止")
        return 0
    except Exception as e:
        print("错误: %s" % e, file=sys.stderr)
        return 3
    finally:
        if link:
            link.close()


# =====================================================================
def mkpkt(args):
    if args.kind == "relay":
        pk = mk_relay_set("relay")
    elif args.kind == "mode":
        pk = mk_mode(args.args[0] if args.args else "relay")
    elif args.kind == "offset":
        pk = mk_offset(int(args.args[0]))
    else:
        pk = mk_req_status()
    data = pk.pack(sync=True)
    open(args.out, "wb").write(data)
    print("  已写 %s (%d 字节)" % (args.out, len(data)))
    print("  %r" % pk)
    print("  hex: %s" % data.hex(" "))
    return 0


# =====================================================================
def demo():
    """CCSDS 全链路演示：打包 → 字节流 → 解码 → 执行(干跑) → 遥测。"""
    print("=" * 70)
    print(" CCSDS 简化版全链路演示（不需要硬件）")
    print("=" * 70)

    print("\n[1] 构造遥控包")
    pkts = [
        mk_mode("relay"),
        mk_offset(100_000),
        mk_offset(-100_000),
        mk_dig_gain_pkt(0x800, 1),
        mk_rf_set(900_000_000, 1_000_000_000, 20, 30),
        mk_relay_set("relay", duc_hz=480_000, ddc_hz=0, gain=0x800, dc=0),
        mk_req_status(),
    ]
    for p in pkts:
        print("  %-46r  %2d 字节" % (p, len(p.pack())))
        print("       %s" % p.pack().hex(" "))

    print("\n[2] 拼成字节流（模拟串口/空口收到的数据）")
    frames = [p.pack(sync=True) for p in pkts]
    junk = b"\x00\xff\x12"                      # 故意插入垃圾，检验同步能力
    stream = junk + frames[0] + junk + b"".join(frames[1:3]) + junk \
             + b"".join(frames[3:])
    print("  流长度 %d 字节，内含 %d 处垃圾（都插在包边界上）"
          % (len(stream), 3))

    print("\n[3] 流式解码")
    dec = PacketDecoder()
    got = dec.feed(stream)
    print("  解出 %d 个包（应为 %d）" % (len(got), len(pkts)))
    assert len(got) == len(pkts), "解码数量不对"

    print("\n[4] 执行（dry-run，不连硬件）")
    disp = Dispatcher(link=None, dry=True, verbose=True)
    for p in got:
        tm = disp.execute_raw(p)
        if tm:
            print_tm(tm)

    print("\n[5] CRC 检错能力")
    good = mk_offset(100_000).pack()
    bad = bytearray(good)
    bad[8] ^= 0x01
    try:
        SpacePacket.unpack(bytes(bad))
        print("  !! 单比特错误未被检出（不应该）")
        return 1
    except ValueError as e:
        print("  单比特翻转被正确检出: %s" % e)

    print("\n" + "=" * 70)
    print(" 全部通过。CCSDS 打包/解码/执行链路可用。")
    print("=" * 70)
    return 0


def mk_dig_gain_pkt(gain, dc):
    return SpacePacket(APID_DIG_GAIN, ccsds.enc_dig_gain(gain, dc))


if __name__ == "__main__":
    sys.exit(main())
