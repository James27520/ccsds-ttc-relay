#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
flash_sd_via_uart.py -- 不用读卡器，通过串口把 BOOT.bin 写进板子自己的 SD 卡

原理：
    板子从 SD 卡启动原厂 Linux → Linux 能访问 /dev/mmcblk0p1 (FAT)
    → 用串口控制台把镜像传进去（uuencode，纯可打印字符，不怕控制台）
    → 板子自己 uudecode 并覆盖 SD 卡上的 BOOT.bin

流程：
    1. 登录板子 Linux (root/analog)
    2. 关回显、挂载 SD 卡 FAT 分区
    3. 备份原厂 BOOT.bin -> BOOT_orig.bin（如果还没备份过）
    4. cat > /tmp/BOOT.uu   然后分块喂 uuencode 文本（带 XON/XOFF 流控）
    5. uudecode -> /tmp/BOOT.bin
    6. 校验大小 + md5
    7. cp 到 /mnt/sd/BOOT.bin，sync
    8. 再次校验

用法：
    python flash_sd_via_uart.py                 # 用默认路径
    python flash_sd_via_uart.py COM5 E:\\LDSDR_010\\BOOT.bin
    python flash_sd_via_uart.py --encodetest    # 只测编解码，不连硬件
"""

import hashlib
import os
import sys
import time

sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from serial_port import SerialPort                       # noqa: E402

SRC = r"E:\LDSDR_010\BOOT.bin"
PORT = "COM5"
BAUD = 115200

XON, XOFF = 0x11, 0x13
CHUNK = 384                     # 每次发送的字节数
CHUNK_PAUSE = 0.012             # 块间停顿


# ------------------------------------------------------------------ uuencode
def uuencode(data, name="BOOT.bin"):
    """标准 POSIX uuencode。字符集 0x20-0x5F，不含控制字符。"""
    out = ["begin 644 %s" % name]
    for off in range(0, len(data), 45):
        blk = data[off:off + 45]
        n = len(blk)
        line = [chr((n & 0x3F) + 0x20)]
        for i in range(0, n, 3):
            g = blk[i:i + 3]
            g = g + b"\x00" * (3 - len(g))
            v = (g[0] << 16) | (g[1] << 8) | g[2]
            for s in (18, 12, 6, 0):
                line.append(chr(((v >> s) & 0x3F) + 0x20))
        out.append("".join(line))
    out.append("`")
    out.append("end")
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------ shell
class Board(object):
    def __init__(self, port, baud=BAUD, echo=True):
        self.sp = SerialPort(port, baud)
        self.echo = echo
        self.buf = bytearray()
        time.sleep(0.3)
        self.sp.read()

    def pump(self, secs):
        t0 = time.time()
        while time.time() - t0 < secs:
            d = self.sp.read()
            if d:
                self.buf += d
                if self.echo:
                    sys.stdout.write(d.decode("utf-8", "replace"))
                    sys.stdout.flush()

    def wait_for(self, needles, timeout=25.0):
        if isinstance(needles, bytes):
            needles = (needles,)
        t0 = time.time()
        while time.time() - t0 < timeout:
            self.pump(0.25)
            for n in needles:
                if n in self.buf:
                    return n
        return None

    def clear(self):
        del self.buf[:]

    def send(self, s):
        self.sp.write(s + "\r\n")

    def sh(self, cmd, wait=2.0, quiet=True):
        """跑一条命令，返回去掉回显的输出文本。"""
        self.clear()
        self.send(cmd)
        self.pump(wait)
        txt = self.buf.decode("utf-8", "replace")
        if quiet:
            skip = cmd.strip()
            keep = []
            for l in txt.splitlines():
                t = l.strip()
                if not t or t == skip:
                    continue
                if t in ("READY>", ">", "#", "$") or t.endswith("READY>"):
                    continue
                keep.append(t)
            return "\n".join(keep)
        return txt

    def login(self, user="root", password="analog"):
        self.clear()
        self.sp.write("\r\n")
        got = self.wait_for((b"login: ", b"# ", b"$ ", b"> "), timeout=8)
        if got in (b"# ", b"$ ", b"> "):
            return True
        if got is None:
            return False
        self.clear()
        self.send(user)
        got = self.wait_for((b"Password: ", b"# ", b"$ ", b"> "), timeout=8)
        if got in (b"# ", b"$ ", b"> "):
            return True
        if got is None:
            return False
        self.clear()
        self.send(password)
        got = self.wait_for((b"# ", b"$ ", b"> ", b"Login incorrect"), timeout=10)
        return got in (b"# ", b"$ ", b"> ")

    def send_stream(self, text, progress=True):
        """把文本按块喂进正在运行的 `cat > file`，处理 XON/XOFF 流控。"""
        data = text.encode("ascii")
        total = len(data)
        sent = 0
        t0 = time.time()
        paused = False
        while sent < total:
            n = min(CHUNK, total - sent)
            self.sp.write(data[sent:sent + n])
            sent += n

            # 处理流控：串口里回来的 XOFF 表示板子缓冲区满了
            d = self.sp.read()
            if d:
                if XOFF in d:
                    paused = True
                if XON in d:
                    paused = False
            if paused:
                time.sleep(0.05)
            else:
                time.sleep(CHUNK_PAUSE)

            if progress and sent % (CHUNK * 200) < CHUNK:
                el = time.time() - t0
                pct = 100.0 * sent / total
                eta = (el / sent) * (total - sent) if sent else 0
                sys.stdout.write("\r  发送 %5.1f%%  %d/%d 字节  已用 %.0fs  剩余约 %.0fs   %s"
                                 % (pct, sent, total, el, eta,
                                    "PAUSED" if paused else "      "))
                sys.stdout.flush()
        print()
        return sent

    def close(self):
        self.sp.close()


# ------------------------------------------------------------------ 主流程
def encodetest():
    src = SRC if os.path.exists(SRC) else None
    if src:
        raw = open(src, "rb").read()
    else:
        raw = bytes(range(256)) * 20
    enc = uuencode(raw)
    print("原始 %d 字节 -> uuencode %d 字节 (膨胀 %.2fx)"
          % (len(raw), len(enc), len(enc) / float(len(raw))))
    lines = enc.splitlines()
    print("首行: %s" % lines[0])
    print("次行: %s" % lines[1][:70])
    print("末两行: %s / %s" % (lines[-2], lines[-1]))
    bad = [c for c in enc if not (c == "\n" or 0x20 <= ord(c) <= 0x5F)]
    print("含控制字符: %s" % (set(bad) if bad else "无  OK"))
    try:
        import binascii
        print("Python 端无 uudecode 可对照，改为与 shell 端比对 md5")
    except Exception:
        pass
    return 0


def main():
    if "--encodetest" in sys.argv:
        return encodetest()

    port = sys.argv[1] if len(sys.argv) > 1 else PORT
    src = sys.argv[2] if len(sys.argv) > 2 else SRC

    if not os.path.exists(src):
        print("找不到镜像: %s" % src); return 1
    raw = open(src, "rb").read()

    # 用 Zynq 启动镜像的魔数做一次自检
    magic = int.from_bytes(raw[32:36], "little")
    print("=" * 70)
    print(" 通过串口把 BOOT.bin 写进板子 SD 卡")
    print("=" * 70)
    print(" 镜像 : %s" % src)
    print(" 大小 : %d 字节" % len(raw))
    print(" 魔数 : 0x%08X  %s" % (magic, "OK" if magic == 0xAA995566 else "!! 不对"))
    print(" md5  : %s" % hashlib.md5(raw).hexdigest())
    print()
    if magic != 0xAA995566:
        print(" 镜像魔数不对，中止。"); return 1

    enc = uuencode(raw)
    print(" uuencode 后 %d 字节，预计传输 %.1f 分钟"
          % (len(enc), len(enc) / 11520.0 / 60.0))
    print()

    print(" 打开串口 %s ..." % port)
    t0 = time.time()
    b = None
    while time.time() - t0 < 90:
        try:
            b = Board(port, BAUD, echo=False)
            break
        except OSError as e:
            print("   %s 占用中，3 秒后重试（请关掉 relay_gui / 串口终端）" % e)
            time.sleep(3)
    if b is None:
        print(" 串口一直打不开"); return 1

    try:
        print(" 登录 ...")
        if not b.login():
            print(" 登录失败"); return 1
        print(" 登录成功")

        b.sh("stty -echo -onlcr ixon ixoff", wait=0.8)
        print(" 已关闭回显，开启流控")

        r = b.sh("mkdir -p /mnt/sd; mount | grep -q '/mnt/sd' || "
                 "mount -t vfat /dev/mmcblk0p1 /mnt/sd; echo MNT=$(mount|grep -c /mnt/sd)", wait=2.0)
        print(" 挂载 SD 卡: %s" % r.replace("\n", " | ")[:90])
        if "MNT=0" in r:
            print(" 挂载失败，中止"); return 1

        r = b.sh("ls /mnt/sd", wait=2.0)
        print(" SD 卡内容: %s" % r.replace("\n", " ")[:110])

        # 备份原厂镜像（只做一次）
        r = b.sh("if [ -f /mnt/sd/BOOT.bin ] && [ ! -f /mnt/sd/BOOT_orig.bin ]; "
                 "then cp /mnt/sd/BOOT.bin /mnt/sd/BOOT_orig.bin && echo BACKED; "
                 "elif [ -f /mnt/sd/BOOT_orig.bin ]; then echo ALREADY; "
                 "else echo NOFILE; fi", wait=3.0)
        print(" 备份原厂 BOOT.bin -> BOOT_orig.bin : %s" % r.replace("\n", " ")[:80])

        # 开始接收
        b.clear()
        b.send("cat > /tmp/BOOT.uu")
        time.sleep(0.8)
        print("\n 开始传输（约 5 分钟，请勿打断）...")
        b.send_stream(enc)
        b.sp.write("\x04")          # Ctrl-D 结束 cat
        time.sleep(2.0)
        b.pump(1.5)

        r = b.sh("ls -l /tmp/BOOT.uu", wait=2.0)
        print(" 接收完成: %s" % r.replace("\n", " ")[:90])

        print(" 解码 ...")
        r = b.sh("cd /tmp && uudecode -o /tmp/BOOT.bin /tmp/BOOT.uu; echo RC=$?", wait=4.0)
        print(" %s" % r.replace("\n", " ")[:110])

        r = b.sh("ls -l /tmp/BOOT.bin", wait=2.0)
        print(" %s" % r.replace("\n", " ")[:110])

        r = b.sh("md5sum /tmp/BOOT.bin 2>/dev/null || cksum /tmp/BOOT.bin", wait=6.0)
        print(" 板子校验: %s" % r.replace("\n", " ")[:110])
        ok = hashlib.md5(raw).hexdigest() in r

        if not ok:
            print("\n !! md5 不匹配 —— 传输有误，不写入 SD 卡")
            print("    板子: %s" % r[:80])
            print("    本地: %s" % hashlib.md5(raw).hexdigest())
            return 2

        print("\n md5 匹配 ✓  写入 SD 卡 ...")
        r = b.sh("cp /tmp/BOOT.bin /mnt/sd/BOOT.bin && sync && echo COPIED", wait=8.0)
        print(" %s" % r.replace("\n", " ")[:80])

        r = b.sh("ls -l /mnt/sd/BOOT.bin /mnt/sd/BOOT_orig.bin; sync", wait=3.0)
        print(" SD 卡最终状态:")
        for l in r.splitlines():
            print("   %s" % l[:100])

        r = b.sh("md5sum /mnt/sd/BOOT.bin", wait=8.0)
        print(" 写回后校验: %s" % r.replace("\n", " ")[:100])

        print("\n" + "=" * 70)
        print(" 完成！现在给板子断电再上电，它就会直接跑我们的转发器")
        print("=" * 70)
        print(" 恢复原厂固件: 在板子 Linux 里执行")
        print("   mount -t vfat /dev/mmcblk0p1 /mnt/sd && \\")
        print("   cp /mnt/sd/BOOT_orig.bin /mnt/sd/BOOT.bin && sync")
        return 0
    finally:
        b.close()


if __name__ == "__main__":
    sys.exit(main())
