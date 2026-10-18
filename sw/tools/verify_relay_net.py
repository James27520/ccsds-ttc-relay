#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_relay_net.py -- 验证转发板能否被以太网控制

目标回答三个问题：
  ① 转发板的 eth0 能不能起来、能不能 ping 通
  ② 能不能 SSH 进去
  ③ 进去之后，能不能驱动那个串口 CLI（或直接配 AD9361）

用法（先按下面把网线接好、IP 配好）：
   python verify_relay_net.py --board 192.168.1.20

环境准备（一次性）：
   1. 用网线把转发板的 RJ45 接到电脑（直连或经交换机）
   2. 电脑这块网卡设静态 IP：192.168.1.10 / 255.255.255.0
   3. 转发板 IP 需要设成 192.168.1.20 —— 通过 COM5 的 CLI 设不了 IP，
      所以要么转发板固件默认就有 IP，要么需要先在串口里想办法。
      ★ 如果转发板本来就跑 DHCP 或固定 IP，先 ping 一下这两个试：
         192.168.1.10（固件固定 IP，ZC706 那套）
         192.168.1.20
"""
import argparse
import socket
import subprocess
import sys
import time


def run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout,
                           shell=isinstance(cmd, str))
        out = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace").strip()
        return r.returncode, out
    except Exception as e:
        return -1, str(e)


def ping(ip, n=2):
    rc, out = run(["ping", "-n", str(n), "-w", "1000", ip])
    return rc == 0, out


def tcp_probe(ip, port, timeout=2.0):
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((ip, port))
        return True
    except Exception:
        return False
    finally:
        s.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", default="192.168.1.20")
    ap.add_argument("--pc-ip", default="192.168.1.10")
    ap.add_argument("--user", default="root")
    ap.add_argument("--passwd", default="analog")
    a = ap.parse_args()

    print("=" * 74)
    print("  转发板以太网控制可行性验证")
    print("=" * 74)
    print("  板子 IP  : %s" % a.board)
    print("  电脑 IP  : %s（请确认已设在这块网卡上）" % a.pc_ip)
    print()

    # ---- 1) 电脑侧网卡 ----
    print("-- 1) 电脑侧网卡/IP 检查 --")
    rc, out = run(["powershell", "-NoProfile", "-Command",
                   "Get-NetIPAddress -AddressFamily IPv4 | "
                   "Where-Object {$_.IPAddress -notmatch '^127\\.'} | "
                   "ForEach-Object { \"{0} {1}/{2}\" -f $_.InterfaceAlias,$_.IPAddress,$_.PrefixLength }"])
    for line in out.splitlines():
        print("   | " + line)
    if a.pc_ip not in out:
        print("   ⚠️ 没找到 %s，请先把电脑这块网卡配成该 IP" % a.pc_ip)
    print()

    # ---- 2) ARP / ping ----
    print("-- 2) 有没有 ARP 记录（插了网线的话应该能看到板子）--")
    rc, out = run(["arp", "-a"])
    for line in out.splitlines():
        if "192.168." in line:
            print("   | " + line.strip())
    print()

    print("-- 3) ping 板子 --")
    ok, out = ping(a.board)
    print("   ping %s : %s" % (a.board, "通 ✓" if ok else "不通 ✗"))
    if not ok:
        # 试一下固件固定 IP
        for alt in ("192.168.1.10", "192.168.2.1"):
            if alt == a.pc_ip:
                continue
            ok2, _ = ping(alt, 1)
            print("   ping %s : %s" % (alt, "通 ✓" if ok2 else "不通"))
            if ok2:
                print("   ★ 板子可能在 %s，用 --board %s 重跑" % (alt, alt))
        print()
        print("   ⚠️ ping 不通时的排查顺序：")
        print("      1. 网线插的是转发板的 RJ45 吗（不是 USB）")
        print("      2. 电脑这块网卡 IP 设了吗（%s/24）" % a.pc_ip)
        print("      3. 转发板的 eth0 起来了吗（看它启动日志有没有 link up）")
        print("      4. 转发板固件是不是根本没配 IP")
        return 1
    print()

    # ---- 4) 端口探测 ----
    print("-- 4) 端口探测 --")
    for port, name in ((22, "SSH"), (23, "telnet"), (80, "http"),
                       (30431, "iiod（libiio 网络后端）"), (5555, "自定义")):
        r = tcp_probe(a.board, port)
        print("   %-5d %-26s %s" % (port, name, "开 ✓" if r else "关"))
    print()

    # ---- 5) SSH 试连 ----
    print("-- 5) SSH 试连（用 plink，支持口令）--")
    plink = r"D:\PuTTY\plink.exe"
    probe = subprocess.run([plink, "-ssh", "-batch", "-pw", a.passwd,
                            "%s@%s" % (a.user, a.board), "echo SSH_OK; uname -a"],
                           capture_output=True, timeout=25)
    txt = ((probe.stdout or b"") + (probe.stderr or b"")).decode("utf-8", "replace")
    import re
    m = re.search(r"SHA256:[A-Za-z0-9+/=]+", txt)
    if m:
        fp = m.group(0)
        print("   抓到主机密钥: %s，重试..." % fp)
        probe = subprocess.run([plink, "-ssh", "-batch", "-hostkey", fp,
                                "-pw", a.passwd, "%s@%s" % (a.user, a.board),
                                "echo SSH_OK; uname -a"], capture_output=True, timeout=25)
        txt = ((probe.stdout or b"") + (probe.stderr or b"")).decode("utf-8", "replace")
    for line in txt.strip().splitlines()[:8]:
        print("   | " + line[:130])
    if "SSH_OK" not in txt:
        print("   ✗ SSH 不通 —— 以太网控制这条路暂时走不通")
        return 2
    print("   ✓ SSH 通了")
    print()

    # ---- 6) 关键：SSH 里能不能驱动 CLI ----
    print("-- 6) ★ 关键测试：SSH 会话里能不能驱动串口 CLI --")
    cmds = [
        ("ip -o addr show", "看板子自己的网络配置"),
        ("ps aux 2>/dev/null | grep -iE 'relay|cli' | grep -v grep",
         "找 CLI 程序"),
        ("ls -l /dev/ttyPS* /dev/ttyS* 2>/dev/null", "看串口设备"),
        ("ls -l /dev/ttyFT* /dev/ttyUSB* /dev/ttyACM* 2>/dev/null", "看 USB 串口"),
        ("cat /proc/cmdline", "看内核命令行（console=在哪）"),
    ]
    for c, why in cmds:
        r = subprocess.run([plink, "-ssh", "-batch", "-hostkey", fp,
                            "-pw", a.passwd, "%s@%s" % (a.user, a.board), c],
                           capture_output=True, timeout=25)
        out = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace").strip()
        print("   $ %s   (%s)" % (c, why))
        for line in out.splitlines()[:10]:
            print("      | " + line[:120])
        print()

    # ---- 7) 试着从 SSH 写 CLI 的串口 ----
    print("-- 7) 试着从 SSH 会话直接给 CLI 发命令 --")
    print("   （如果 CLI 是程序在读写某个 tty，写那个 tty 可能就能驱动它）")
    for dev in ("/dev/ttyPS0", "/dev/ttyS0"):
        c = ("printf 'status\\r\\n' > %s 2>&1 && echo WROTE_OK || echo WROTE_FAIL" % dev)
        r = subprocess.run([plink, "-ssh", "-batch", "-hostkey", fp,
                            "-pw", a.passwd, "%s@%s" % (a.user, a.board), c],
                           capture_output=True, timeout=20)
        out = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace").strip()
        print("   写 %-14s -> %s" % (dev, out.splitlines()[-1][:100] if out else "(空)"))

    print()
    print("=" * 74)
    print("  结论怎么读：")
    print("   · 第 5 步 SSH 不通      → 以太网控制暂时不通，要么配 IP，要么退回串口")
    print("   · SSH 通但第 6 步找不到 CLI → CLI 可能是裸机程序，网络驱动不了")
    print("   · 第 7 步能写 tty 且 CLI 有反应 → 可以从遥控板/电脑远程控制 ✓")
    print("   · 第 7 步写不进去（设备忙） → 需要改转发板固件加网络接口")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
