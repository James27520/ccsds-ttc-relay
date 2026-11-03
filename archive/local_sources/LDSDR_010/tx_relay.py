#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tx_relay.py -- 配置发射 + 启动/停止板内软件转发

转发原理：RX_LO=900.0 / TX_LO=1000.0，
          CMU200 的 900.1MHz 落到基带 +100kHz，
          同样的 +100kHz 从 TX 出去就是 1000.1MHz —— IQ 直接透传，不做频移。
"""
import subprocess, sys, time

BOARD, USER = "192.168.2.1", "root"
KEY = r"C:\Users\23638\.ssh\id_ed25519_dsh"
SSH = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no",
       "-o", "UserKnownHostsFile=/dev/null", "-o", "BatchMode=yes",
       "-o", "ConnectTimeout=10", "%s@%s" % (USER, BOARD)]

RX_LO, TX_LO, FS = 900_000_000, 1000_000_000, 4_000_000
D0 = "/sys/bus/iio/devices/iio:device0"
D2 = "/sys/bus/iio/devices/iio:device2/scan_elements"   # TX DMA
D3 = "/sys/bus/iio/devices/iio:device3/scan_elements"   # RX DMA


def sh(cmd, timeout=120):
    r = subprocess.run(SSH + [cmd], capture_output=True, text=True, timeout=timeout)
    return ((r.stdout or "").strip() or (r.stderr or "").strip())


act = sys.argv[1] if len(sys.argv) > 1 else "setup"

if act == "stop":
    print(sh("pkill -f relay.sh; pkill -f iio_readdev; pkill -f iio_writedev; "
             "rm -f /tmp/relay.sh /tmp/buf.bin; echo stopped"))
    sys.exit(0)

print("=" * 74)
print(" 配置收 + 发，准备软件转发")
print("=" * 74)

print("\n[1] 采样率 / 带宽（RX 侧设，TX 共用）")
print("  " + sh("echo %d > %s/in_voltage_sampling_frequency; cat %s/in_voltage_sampling_frequency"
                % (FS, D0, D0)).replace("\n", " "))
print("  " + sh("echo 1000000 > %s/in_voltage_rf_bandwidth; "
                "echo 1000000 > %s/out_voltage_rf_bandwidth; "
                "cat %s/in_voltage_rf_bandwidth" % (D0, D0, D0)).replace("\n", " "))

print("\n[2] 本振")
print("  RX_LO " + sh("echo %d > %s/out_altvoltage0_RX_LO_frequency; "
                     "cat %s/out_altvoltage0_RX_LO_frequency" % (RX_LO, D0, D0)).replace("\n", " "))
print("  TX_LO " + sh("echo %d > %s/out_altvoltage1_TX_LO_frequency; "
                     "cat %s/out_altvoltage1_TX_LO_frequency" % (TX_LO, D0, D0)).replace("\n", " "))

print("\n[3] 增益")
print("  RX 增益模式 " + sh("echo manual > %s/in_voltage0_gain_control_mode; "
                           "cat %s/in_voltage0_gain_control_mode" % (D0, D0)).replace("\n", " "))
print("  RX 增益 10dB " + sh("echo 10 > %s/in_voltage0_hardwaregain; "
                             "cat %s/in_voltage0_hardwaregain" % (D0, D0)).replace("\n", " "))
print("  TX 衰减可用范围 " + sh("cat %s/out_voltage0_hardwaregain_available" % D0))
print("  TX 衰减当前 " + sh("cat %s/out_voltage0_hardwaregain" % D0).replace("\n", " "))
# 先设成较大衰减（保守，保护仪器）
print("  设 TX 衰减 -30dB " + sh("echo -30 > %s/out_voltage0_hardwaregain 2>&1; "
                                "cat %s/out_voltage0_hardwaregain" % (D0, D0)).replace("\n", " "))

print("\n[4] 使能扫描通道")
print("  RX " + sh("for c in voltage0 voltage1 voltage2 voltage3; do "
                  "echo 0 > %s/in_${c}_en; done; "
                  "echo 1 > %s/in_voltage0_en; echo 1 > %s/in_voltage1_en; "
                  "for f in %s/*_en; do echo -n \"$(basename $f)=\"; cat $f; done"
                  % (D3, D3, D3, D3)).replace("\n", " "))
print("  TX " + sh("for c in voltage0 voltage1 voltage2 voltage3; do "
                  "echo 0 > %s/out_${c}_en; done; "
                  "echo 1 > %s/out_voltage0_en; echo 1 > %s/out_voltage1_en; "
                  "for f in %s/*_en; do echo -n \"$(basename $f)=\"; cat $f; done"
                  % (D2, D2, D2, D2)).replace("\n", " "))

print("\n[5] 单次 TX 测试（写一段单音进去，确认通路）")
r = sh("cat > /tmp/relay.sh <<'EOF'\n"
       "#!/bin/sh\n"
       "# 板内软件转发：RX -> TX，IQ 直接透传（频移由 LO 差值完成）\n"
       "N=%d\n" % 8192 +
       "while true; do\n"
       "  iio_readdev -s $N -b $N cf-ad9361-lpc voltage0 voltage1 > /tmp/buf.bin 2>/dev/null\n"
       "  [ -s /tmp/buf.bin ] || continue\n"
       "  iio_writedev -s $N -b $N cf-ad9361-dds-core-lpc voltage0 voltage1 < /tmp/buf.bin 2>/dev/null\n"
       "done\n"
       "EOF\n"
       "chmod +x /tmp/relay.sh; echo 脚本已写入; wc -c /tmp/relay.sh")
print("  " + r.replace("\n", "\n  "))

print("\n[6] 启动转发循环（后台）")
print("  " + sh("pkill -f relay.sh 2>/dev/null; "
                "(setsid /tmp/relay.sh >/tmp/relay.log 2>&1 &); sleep 2; "
                "ps | grep -c '[r]elay.sh'; echo ---; cat /tmp/relay.log | head -3"))

print("\n[7] 验证数据在流（等 3 秒看 buf 有没有更新）")
print("  " + sh("date +%s; ls -l /tmp/buf.bin 2>/dev/null; sleep 3; "
                "date +%s; ls -l /tmp/buf.bin 2>/dev/null").replace("\n", "\n  "))

print("\n" + "=" * 74)
print(" 转发循环已启动。请到 CMU200 上把分析仪设到 1000.1 MHz 看有没有信号。")
print(" 停止： python tx_relay.py stop")
print("=" * 74)
