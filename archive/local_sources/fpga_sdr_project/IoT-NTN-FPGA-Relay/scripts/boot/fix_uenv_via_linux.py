#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_uenv_via_linux.py -- 登录板子 Linux，挂载 SD 卡，修正 uEnv.txt 里的 uenvcmd

板子能读卡就能写卡，这条路比在 U-Boot 里折腾简单得多。
"""

import sys
import time

sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from serial_port import SerialPort                       # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM5"
RES = r"E:\LDSDR_010\fix_uenv_result.txt"


def rd(sp, secs):
    t0 = time.time()
    o = bytearray()
    while time.time() - t0 < secs:
        d = sp.read()
        if d:
            o += d
        else:
            time.sleep(0.04)
    return bytes(o)


def cmd(sp, c, wait=2.0):
    sp.write(c + "\r\n")
    raw = rd(sp, wait).decode("utf-8", "replace")
    out = []
    for l in raw.splitlines():
        s = l.strip()
        if s and s != c:
            out.append(s)
    return "\n".join(out)


def main():
    f = open(RES, "w", encoding="utf-8")

    def W(s):
        print(s)
        f.write(s + "\n")
        f.flush()

    sp = SerialPort(PORT, 115200)
    time.sleep(0.3)
    sp.read()

    W("=== 1. 登录 ===")
    b = bytearray()
    t0 = time.time()
    sp.write("\r\n")
    while time.time() - t0 < 150:
        d = sp.read()
        if d:
            b += d
        if b"login:" in b or b"# " in b:
            break
        time.sleep(0.1)
    if b"login:" in b:
        sp.write("root\r\n"); time.sleep(1.5); rd(sp, 1)
        sp.write("analog\r\n"); time.sleep(3.0); rd(sp, 1)
    sp.write("stty -echo; echo SHELL_OK\r\n"); time.sleep(1.5)
    if b"SHELL_OK" not in rd(sp, 1):
        W("  !! 没进 shell"); f.close(); sp.close(); return 1
    W("  已进 shell")

    W("\n=== 2. 挂载 SD 卡 ===")
    W(cmd(sp, "mkdir -p /mnt/sd && mount -t vfat /dev/mmcblk0p1 /mnt/sd && echo MOUNTED", 3.0))

    W("\n=== 3. 当前 uenvcmd / relayboot 行 ===")
    W(cmd(sp, "grep -n -E '^(uenvcmd|relayboot)=' /mnt/sd/uEnv.txt", 2.0))

    W("\n=== 4. 修正 uenvcmd 为 'run relayboot' ===")
    # 删掉旧的 uenvcmd 行，追加正确的（避免 sed 特殊字符问题）
    W(cmd(sp, "grep -v '^uenvcmd=' /mnt/sd/uEnv.txt > /tmp/u.new", 2.0))
    W(cmd(sp, "echo 'uenvcmd=run relayboot' >> /tmp/u.new", 1.5))
    W(cmd(sp, "wc -c /tmp/u.new", 1.5))

    W("\n=== 5. 确保 relayboot 存在且正确 ===")
    W(cmd(sp, "grep -c '^relayboot=' /tmp/u.new", 1.5))
    # 若没有 relayboot 就补一条
    W(cmd(sp, "grep -q '^relayboot=' /tmp/u.new || echo "
             "'relayboot=echo RELAY_START; load mmc 0 0x1000000 relay.bit; "
             "fpga loadb 0 0x1000000 2083846; load mmc 0 0x2000000 relay.elf; "
             "bootelf 0x2000000' >> /tmp/u.new", 2.0))

    W("\n=== 6. 写回 SD 卡 ===")
    W(cmd(sp, "cp /tmp/u.new /mnt/sd/uEnv.txt && sync && echo COPIED", 4.0))
    W(cmd(sp, "grep -n -E '^(uenvcmd|relayboot)=' /mnt/sd/uEnv.txt", 2.0))
    W(cmd(sp, "wc -c /mnt/sd/uEnv.txt", 1.5))

    W("\n=== 7. 卸载 ===")
    W(cmd(sp, "sync; umount /mnt/sd && echo UNMOUNTED", 4.0))

    W("\n=== 8. reboot 验证自动启动 ===")
    sp.write("reboot\r\n")
    out = rd(sp, 55)
    txt = out.decode("utf-8", "replace")
    W(txt[-2500:])

    W("\n" + "=" * 66)
    if "RELAY_START" in txt:
        W(" ✅ relayboot 被执行了")
    if "relay enabled" in txt or "rxlo" in txt or "PL relay" in txt:
        W(" ✅✅ 转发应用自动启动成功 —— 上电即工作")
    elif "Running uenvcmd" in txt:
        W(" ⚠️ uenvcmd 执行了但没起来，看上面")
    else:
        W(" ⚠️ 仍未自动执行")
    W("=" * 66)
    f.close()
    sp.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
