#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
handover_to_3588.py -- 把遥测板交给 3588 之前的准备
（趁 PC 现在还能同时够到 3588 和遥测板）

做四件事：
  1. 确认遥测板能独立启动（插到 3588 后要自己起来）
  2. 在 3588 上生成 SSH 密钥
  3. 把 3588 的公钥装到遥测板上
  4. 从 3588 实测 ssh 到遥测板
另外把遥测板复位到干净状态（停 DDS）
"""
import subprocess, sys, time

BOARD, USER = "192.168.2.1", "root"
KEY_PC = r"C:\Users\23638\.ssh\id_ed25519_dsh"
SSH_PC = ["ssh", "-i", KEY_PC, "-o", "StrictHostKeyChecking=no",
          "-o", "UserKnownHostsFile=/dev/null", "-o", "BatchMode=yes",
          "-o", "ConnectTimeout=10", "%s@%s" % (USER, BOARD)]

sys.path.insert(0, r"E:\LDSDR_010")
from rk_console import RKConsole


def newboard(cmd, t=120):
    r = subprocess.run(SSH_PC + [cmd], capture_output=True, timeout=t)
    return (r.stdout or b"").decode("utf-8", "replace").strip() or \
           (r.stderr or b"").decode("utf-8", "replace").strip()


print("=" * 76)
print(" 一、遥测板能否独立启动（插到 3588 后要自己起来）")
print("=" * 76)
print("  内核      : " + newboard("uname -r"))
print("  启动模式  : " + newboard("cat /proc/cmdline | head -c 200"))
print("  根文件系统: " + newboard("mount | grep ' / ' | head -1"))
print("console 串口: " + newboard("ls /dev/ttyGS* /dev/ttyS* 2>/dev/null | tr '\\n' ' '"))
print("  USB gadget: " + newboard("ls /sys/class/udc/ 2>/dev/null; "
                                 "cat /sys/kernel/config/usb_gadget/*/idVendor 2>/dev/null"))
print("  当前 DDS  : " + newboard(
    "iio_attr -c cf-ad9361-dds-core-lpc altvoltage0 scale 2>&1 | head -1"))

print("\n" + "=" * 76)
print(" 二、清理遥测板：停 DDS，恢复安静状态")
print("=" * 76)
print("  " + newboard("pkill -f iio_ 2>/dev/null; "
                      "iio_attr -c cf-ad9361-dds-core-lpc altvoltage0 scale 0 2>&1|head -1; "
                      "iio_attr -c cf-ad9361-dds-core-lpc altvoltage1 scale 0 2>&1|head -1; "
                      "echo 'DDS 已停'"))

# ----------------------------------------------------------------------
print("\n" + "=" * 76)
print(" 三、在 3588 上生成 SSH 密钥")
print("=" * 76)
with RKConsole("COM8") as rk:
    r = rk.run("ls -l ~/.ssh/id_ed25519_ttc 2>/dev/null || echo NOKEY", wait=0.6, timeout=40)
    print("  " + r.replace("\n", "\n  "))
    if "NOKEY" in r or "No such" in r:
        print("\n  生成中 ...")
        print("  " + rk.run("mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
                            "ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_ttc -N '' "
                            "-C 'rk3588->ttc' 2>&1 | tail -3", wait=3.0, timeout=90))
    pub = rk.run("cat ~/.ssh/id_ed25519_ttc.pub", wait=0.6, timeout=40).strip()
    print("\n  3588 的公钥:")
    print("    %s" % pub[:110])

    print("\n" + "=" * 76)
    print(" 四、把 3588 的公钥装到遥测板")
    print("=" * 76)
    # 用 PC 的中转：PC 已经有遥测板的免密
    if pub and pub.startswith("ssh-"):
        half = len(pub) // 2
        print("  " + newboard("grep -q '%s' /root/.ssh/authorized_keys 2>/dev/null && "
                              "echo '已存在' || echo '需添加'" % pub[:40]))
        newboard("mkdir -p /root/.ssh && chmod 700 /root/.ssh")
        newboard("printf '%%s' '%s' >> /root/.ssh/authorized_keys" % pub[:half])
        newboard("printf '%%s\\n' '%s' >> /root/.ssh/authorized_keys" % pub[half:])
        print("  authorized_keys 现有 %s 行" %
              newboard("wc -l < /root/.ssh/authorized_keys"))
        print("  含 rk3588->ttc : %s" %
              newboard("grep -c 'rk3588->ttc' /root/.ssh/authorized_keys"))

        print("\n" + "=" * 76)
        print(" 五、从 3588 实测 SSH 到遥测板")
        print("=" * 76)
        r = rk.run("ssh -i ~/.ssh/id_ed25519_ttc -o StrictHostKeyChecking=no "
                   "-o UserKnownHostsFile=/dev/null -o BatchMode=yes "
                   "-o ConnectTimeout=8 root@192.168.2.1 "
                   "'uname -r; hostname; iio_info 2>/dev/null | grep -m1 hw_model' 2>&1",
                   wait=3.0, timeout=90)
        print("  " + r.replace("\n", "\n  "))
    else:
        print("  !! 没拿到公钥")

    print("\n" + "=" * 76)
    print(" 六、3588 当前的网络接口（插上遥测板后会多一个）")
    print("=" * 76)
    print("  " + rk.run("ip -br addr 2>&1", wait=0.6, timeout=40).replace("\n", "\n  "))
    print("\n  USB 设备:")
    print("  " + rk.run("lsusb 2>&1", wait=0.6, timeout=40).replace("\n", "\n  "))

print("\n" + "=" * 76)
print(" 准备好了。现在可以把遥测板的 USB 拔下来插到 3588 上。")
print(" ⚠️ 注意：遥测板要单独供电（3588 的 USB 口可能供不起）")
print("=" * 76)
