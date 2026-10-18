#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mode_b_link.py -- 模式 B（经板子）的收发链路

把「PC 组 CCSDS 包 -> 遥测板发射 -> SMA 环回 -> 遥测板接收 -> PC 解出内容」
封装成一个函数，供演示工具 GUI 和命令行测试共用。

硬件前提（本会话已逐项验证）：
  · 板子跑原厂固件，RNDIS 网口 + SSH 可用（plink 口令 analog）
  · TX/RX 本振同频（实测 2400 MHz）
  · TX1A -> RX1A 有环回（实测 DDS 单音 54.8 dB 信噪比）

踩过的坑（都写进代码注释了）：
  1. 必须用【有界管道循环】喂 iio_writedev。文件重定向只会发一遍，
     抓的时候就发完了 —— 发射时长要远大于「启动+抓取」的耗时。
  2. pscp 必须带 -scp（板子没装 sftp-server）。
  3. 板子每次重启换 SSH 主机密钥，每次现抓指纹。
  4. plink 的命令参数里不要放中文/复杂引号，会挂。
"""
import os
import re
import subprocess
import sys
import time

import numpy as np

SW = r"E:\fpga_sdr_project\ccsds_ttc_loopback\sw\ttc"
if SW not in sys.path:
    sys.path.insert(0, SW)
import ccsds_tm_tx as CC                       # noqa: E402
import loopback_test as LB                     # noqa: E402

PLINK = r"D:\PuTTY\plink.exe"
PSCP = r"D:\PuTTY\pscp.exe"
BOARD = "root@192.168.2.1"
PASSWORD = "analog"

# 链路参数（与已验证的软件版一致）
FS = 2_500_000
SYM = 250_000
IF = 200_000
N_SAMP = 3_456_320
CAP_SAMPLES = 262_144

TMP = os.environ.get("TEMP", r"C:\Windows\Temp")
WAVE_LOCAL = os.path.join(TMP, "ccsds_mb_wave.bin")
CAP_LOCAL = os.path.join(TMP, "ccsds_mb_cap.bin")


class ModeBError(Exception):
    pass


class ModeBLink:
    def __init__(self, log=None):
        self.log = log or (lambda s: None)
        self.fp = None

    # ---------------- 底层 ----------------
    def _plink(self, cmd, timeout=240, show=False):
        args = [PLINK, "-ssh", "-batch"]
        if self.fp:
            args += ["-hostkey", self.fp]
        args += ["-pw", PASSWORD, BOARD, cmd]
        r = subprocess.run(args, capture_output=True, timeout=timeout)
        out = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace").strip()
        if show and out:
            for l in out.splitlines():
                self.log("    | " + l[:150])
        return out

    def _scp(self, local, remote, download=False):
        args = [PSCP, "-batch", "-scp"]
        if self.fp:
            args += ["-hostkey", self.fp]
        args += ["-pw", PASSWORD]
        args += ["%s:%s" % (BOARD, remote), local] if download else \
                [local, "%s:%s" % (BOARD, remote)]
        r = subprocess.run(args, capture_output=True, timeout=300)
        if r.returncode != 0:
            self.log("    ! scp 失败: " + ((r.stdout or b"") + (r.stderr or b"")).decode(
                "utf-8", "replace")[:200])
        return r.returncode == 0

    def connect(self):
        r = subprocess.run([PLINK, "-ssh", "-batch", "-pw", PASSWORD, BOARD, "echo P"],
                           capture_output=True)
        m = re.search(r"SHA256:[A-Za-z0-9+/=]+",
                      (r.stdout + r.stderr).decode("utf-8", "replace"))
        if not m:
            raise ModeBError("板子不在线或 SSH 不通（先确认 RNDIS 网口 Up、ping 192.168.2.1 通）")
        self.fp = m.group(0)
        self.log("  板子主机密钥: %s" % self.fp)
        return True

    # ---------------- 主流程 ----------------
    def run(self, payload=None, data_block=None, scid=42, vcid=0, vcfc=0,
            txatt=40, rxgain=30):
        """返回 dict: ok/frame/decoded/payload/data_block/asm_pos/... 等

        data_block: 32 字节遥测参数表数据域。给了就用它（演示工具的路径）；
                    没给则用 payload 文本补齐到 32 字节（命令行测试的路径）。
        """
        self.connect()

        # 1) 组包 + 调制
        #
        # ★ 数据域固定 32 字节（本工程帧格式：6 头 + 32 数据 + 2 FECF = 40 字节）。
        #   实测：短帧（如 14 字节载荷 -> 22 字节帧）在 2.5 MSPS 环回下最后一个
        #   FECF 字节会差 1 bit（Viterbi 尾比特余量不足）；固定 32 字节后完全一致。
        if data_block is not None:
            data = bytes(data_block)[:32].ljust(32, b"\x00")
        else:
            if payload is None:
                payload = "CCSDS-6G-NTN-7010-TTC-FPGA-PORT!"
            data = payload.encode("utf-8")[:32].ljust(32, b"\x00")
        frame = CC.build_tm_frame(scid=scid, vcid=vcid, mcfc=0, vcfc=vcfc,
                                  data=data, fecf=True)
        cadu, _ = CC.build_cadu(frame)
        self.log("  帧 (%d B): %s" % (len(frame), frame.hex()))
        ret = CC.cadu_to_iq(cadu, fs=FS, sym_rate=SYM, beta=0.35, amp=0.6, if_hz=IF)
        if isinstance(ret, tuple) and len(ret) == 2:
            iq = CC.iq_interleave(ret[0], ret[1])
        else:
            iq = ret
        one = np.asarray(iq, dtype=np.int16)
        reps = int(np.ceil(N_SAMP / float(len(one))))
        wave = np.tile(one, reps)[:N_SAMP]
        wave.tofile(WAVE_LOCAL)
        self.log("  波形 %d 样点 (%.1f s @ %.1f MSPS)" % (len(wave), len(wave) / FS, FS / 1e6))

        # 2) 传板子
        if not self._scp(WAVE_LOCAL, "/tmp/mb_wave.bin"):
            raise ModeBError("波形上传失败（pscp -scp）")
        self.log("  波形已上传")

        # 3) 配置
        for c in [
            "iio_attr -u ip:localhost -c ad9361-phy voltage0 sampling_frequency %d" % int(FS),
            "iio_attr -u ip:localhost -c ad9361-phy voltage0 rf_bandwidth 1000000",
            "iio_attr -u ip:localhost -c ad9361-phy voltage1 rf_bandwidth 1000000",
            "iio_attr -u ip:localhost -c ad9361-phy altvoltage0 frequency 2400000000",
            "iio_attr -u ip:localhost -c ad9361-phy altvoltage1 frequency 2400000000",
            "iio_attr -u ip:localhost -i -c ad9361-phy voltage0 gain_control_mode manual",
            "iio_attr -u ip:localhost -i -c ad9361-phy voltage0 hardwaregain %d" % rxgain,
            "iio_attr -u ip:localhost -i -c ad9361-phy voltage1 gain_control_mode manual",
            "iio_attr -u ip:localhost -i -c ad9361-phy voltage1 hardwaregain %d" % rxgain,
            "iio_attr -u ip:localhost -o -c ad9361-phy voltage1 hardwaregain -%d" % txatt,
            "iio_attr -u ip:localhost -c cf-ad9361-dds-core-lpc altvoltage0 scale 0",
            "iio_attr -u ip:localhost -c cf-ad9361-dds-core-lpc altvoltage1 scale 0",
            "iio_attr -u ip:localhost -c cf-ad9361-dds-core-lpc altvoltage2 scale 0",
            "iio_attr -u ip:localhost -c cf-ad9361-dds-core-lpc altvoltage3 scale 0",
        ]:
            self._plink(c)
        self.log("  AD9361 已配置（RX %.1f MSPS / TX 衰减 %d dB / RX 增益 %d dB）"
                 % (FS / 1e6, txatt, rxgain))

        # 4) 发射（管道循环）
        self._plink("killall -9 iio_writedev 2>/dev/null; echo ok")
        total = len(wave) * 10
        inner = ("cd /tmp && nohup sh -c 'for i in $(seq 1 30); do cat /tmp/mb_wave.bin; done | "
                 "iio_writedev -u ip:localhost -s %d -b 65536 "
                 "cf-ad9361-dds-core-lpc voltage0 voltage1' >/tmp/tx.log 2>&1 & echo TX_STARTED"
                 % total)
        self._plink(inner)
        self.log("  发射中（总计 %.1f 秒）..." % (total / float(FS)))
        time.sleep(2.0)

        # 5) 接收
        self._plink("iio_readdev -u ip:localhost -b 65536 -s %d cf-ad9361-lpc voltage0 voltage1 "
                    "> /tmp/mb_cap.bin" % (2 * CAP_SAMPLES), timeout=240)
        self._plink("killall -9 iio_writedev 2>/dev/null; echo TX_STOPPED")
        self.log("  接收完成，取回数据")

        if not self._scp(CAP_LOCAL, "/tmp/mb_cap.bin", download=True):
            raise ModeBError("抓取数据下载失败")

        # 6) 解调译码
        raw = np.fromfile(CAP_LOCAL, dtype=np.int16)
        if len(raw) < 8192:
            raise ModeBError("抓到数据太少（%d）" % len(raw))
        ri = raw[0::2].astype(np.int32)
        rq = raw[1::2].astype(np.int32)
        rms = float(np.sqrt(np.mean(ri.astype(float) ** 2 + rq.astype(float) ** 2)))
        self.log("  抓到 %d 样点，RMS=%.1f" % (len(ri), rms))

        bits, pos, err, dinfo = LB.decode_capture(ri, rq, verbose=False)

        # ★ 路径判定：区分"真的接了 SMA 环回电缆"和"仅靠芯片内部 TX->RX 泄漏"
        #
        #   实测数据（本会话，TX 衰减 40 dB / RX 增益 30 dB）：
        #     接了 TX1A->RX1A 电缆 : RMS = 2446.6   眼图开度 2.35e8   每符号均值 4490.4
        #     没接电缆（内部泄漏） : RMS =   10.9   眼图开度 1.17e6   每符号均值   22.3
        #   相差 225 倍 / 47 dB，所以用 RMS 就能可靠区分。
        #
        #   为什么必须区分：AD9361 是收发一体芯片，TX 输出会通过衬底/封装/PCB
        #   耦合进自己的 RX 输入端，所以【不接线也能解出帧】。
        #   光看"能解出"证明不了电缆有效，必须看电平。
        PATH_CABLE = "直连电缆（TX1A->RX1A）"
        PATH_LEAK = "芯片内部泄漏（未接电缆）"
        path = PATH_CABLE if rms > 100.0 else PATH_LEAK

        if pos < 0:
            return {"ok": False, "reason": "没找到 ASM（检查环回线/增益）",
                    "frame": frame, "rms": rms, "path": path}
        self.log("  ASM @ %d，错 %d bit；定时相位 %d/10 眼图开度 %.0f 每符号均值 %.1f"
                 % (pos, err, dinfo["phase"], dinfo["conf"], dinfo["npk"]))
        self.log("  ★ 射频路径判定：%s（接收 RMS = %.1f）" % (path, rms))

        enc = bits[pos + 32:]
        n = (len(enc) // 2) * 2
        dec = CC.conv_decode_viterbi(enc[:n])
        der = CC.derandomize(dec)
        fb = CC.bits_to_bytes(der)

        decoded = None
        off_found = -1
        for off in range(0, max(1, min(len(fb) - len(frame), 2000))):
            if bytes(fb[off:off + len(frame)]) == frame:
                decoded = bytes(fb[off:off + len(frame)])
                off_found = off
                break
        return {
            "ok": decoded is not None,
            "frame": frame, "decoded": decoded,
            "payload": payload, "data_block": data, "scid": scid, "vcid": vcid, "vcfc": vcfc,
            "asm_pos": pos, "asm_err": err, "phase": dinfo["phase"],
            "conf": dinfo["conf"], "npk": dinfo["npk"], "rms": rms, "path": path,
            "offset": off_found,
            "head": bytes(fb[:64]),
        }


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--payload", default="CCSDS-6G-NTN-7010-TTC-FPGA-PORT!")
    ap.add_argument("--txatt", type=int, default=40)
    ap.add_argument("--rxgain", type=int, default=30)
    a = ap.parse_args()

    link = ModeBLink(log=lambda s: print(s))
    try:
        r = link.run(payload=a.payload, txatt=a.txatt, rxgain=a.rxgain)
    except ModeBError as e:
        print("  [!] %s" % e)
        return 1
    print()
    if r["ok"]:
        print("  ★ 两端逐字节一致（偏移 %d）" % r["offset"])
        print("  解出: %s" % r["decoded"].hex())
        print("  期望: %s" % r["frame"].hex())
        print("  载荷: %s" % r["payload"])
        return 0
    print("  ✗ %s" % r.get("reason", "未解出"))
    print("  解出前 64 字节: %s" % r.get("head", b"").hex())
    return 1


if __name__ == "__main__":
    sys.exit(main())
