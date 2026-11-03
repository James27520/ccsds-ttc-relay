#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
relay_fifo.py -- 用命名管道让两个设备常开，实现接近连续的转发

原理：
  普通循环  读(开设备→流→关) → 写(开设备→流→关) → 读 → ...   每轮 450ms 开销
  FIFO 方案 读设备常开 ──管道──► 写设备常开                     开销只付一次

关键：采样率必须降到 reader 跟得上的水平（实测 reader 上限 ~3.36 MSPS）
"""
import subprocess, sys, time

BOARD, USER = "192.168.2.1", "root"
KEY = r"C:\Users\23638\.ssh\id_ed25519_dsh"
SSH = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no",
       "-o", "UserKnownHostsFile=/dev/null", "-o", "BatchMode=yes",
       "-o", "ConnectTimeout=10", "%s@%s" % (USER, BOARD)]
D0 = "/sys/bus/iio/devices/iio:device0"

FS = 2083333           # 下限，给 reader 留余量
BUF = 32768

act = sys.argv[1] if len(sys.argv) > 1 else "start"


def sh(c, t=180):
    r = subprocess.run(SSH + [c], capture_output=True, timeout=t)
    return (r.stdout or b"").decode("utf-8", "replace").strip() or \
           (r.stderr or b"").decode("utf-8", "replace").strip()


if act == "stop":
    print(sh("pkill -f iio_readdev; pkill -f iio_writedev; pkill -f relay.sh; "
             "rm -f /tmp/fifo; "
             "for c in 0 1 2 3; do "
             "echo 0 > /sys/bus/iio/devices/iio:device3/scan_elements/in_voltage${c}_en; "
             "echo 0 > /sys/bus/iio/devices/iio:device2/scan_elements/out_voltage${c}_en; "
             "done; echo STOPPED"))
    sys.exit(0)

print("=" * 76)
print(" FIFO 连续转发")
print("=" * 76)

print("\n[0] 清理旧进程")
print("  " + sh("pkill -f relay.sh; pkill -f iio_readdev; pkill -f iio_writedev; "
                "rm -f /tmp/fifo; sleep 1; echo ok"))

print("\n[1] 采样率降到 %d Hz（reader 跟得上的水平）" % FS)
print("  " + sh("echo %d > %s/in_voltage_sampling_frequency; "
                "cat %s/in_voltage_sampling_frequency" % (FS, D0, D0)).replace("\n", " "))
print("  带宽 " + sh("echo 1000000 > %s/in_voltage_rf_bandwidth; "
                     "echo 1000000 > %s/out_voltage_rf_bandwidth; "
                     "cat %s/in_voltage_rf_bandwidth" % (D0, D0, D0)).replace("\n", " "))

print("\n[2] 本振 / 增益")
print("  RX_LO " + sh("echo 900000000 > %s/out_altvoltage0_RX_LO_frequency; "
                      "cat %s/out_altvoltage0_RX_LO_frequency" % (D0, D0)).replace("\n", " "))
print("  TX_LO " + sh("echo 1000000000 > %s/out_altvoltage1_TX_LO_frequency; "
                      "cat %s/out_altvoltage1_TX_LO_frequency" % (D0, D0)).replace("\n", " "))
print("  RX增益 " + sh("echo manual > %s/in_voltage0_gain_control_mode; "
                       "echo 20 > %s/in_voltage0_hardwaregain; "
                       "cat %s/in_voltage0_hardwaregain" % (D0, D0, D0)).replace("\n", " "))
print("  TX衰减 " + sh("echo -30 > %s/out_voltage0_hardwaregain; "
                       "cat %s/out_voltage0_hardwaregain" % (D0, D0)).replace("\n", " "))

print("\n[3] 使能通道（RX 收 / TX 发）")
print("  " + sh("for c in 0 1 2 3; do "
                "echo 0 > /sys/bus/iio/devices/iio:device3/scan_elements/in_voltage${c}_en; "
                "echo 0 > /sys/bus/iio/devices/iio:device2/scan_elements/out_voltage${c}_en; done; "
                "echo 1 > /sys/bus/iio/devices/iio:device3/scan_elements/in_voltage0_en; "
                "echo 1 > /sys/bus/iio/devices/iio:device3/scan_elements/in_voltage1_en; "
                "echo 1 > /sys/bus/iio/devices/iio:device2/scan_elements/out_voltage0_en; "
                "echo 1 > /sys/bus/iio/devices/iio:device2/scan_elements/out_voltage1_en; "
                "echo RX=$(cat /sys/bus/iio/devices/iio:device3/scan_elements/in_voltage0_en)"
                "$(cat /sys/bus/iio/devices/iio:device3/scan_elements/in_voltage1_en) "
                "TX=$(cat /sys/bus/iio/devices/iio:device2/scan_elements/out_voltage0_en)"
                "$(cat /sys/bus/iio/devices/iio:device2/scan_elements/out_voltage1_en)"))

print("\n[4] 建立 FIFO 并启动常开转发")
r = sh("cat > /tmp/fifo_relay.sh <<'EOS'\n"
       "#!/bin/sh\n"
       "# 设备常开，FIFO 直通\n"
       "BK=%d\n"
       "rm -f /tmp/fifo\n"
       "mkfifo /tmp/fifo\n"
       "iio_writedev -b $BK cf-ad9361-dds-core-lpc voltage0 voltage1 < /tmp/fifo &\n"
       "WPID=$!\n"
       "sleep 0.5\n"
       "iio_readdev -b $BK cf-ad9361-lpc voltage0 voltage1 > /tmp/fifo &\n"
       "RPID=$!\n"
       "echo \"writer=$WPID reader=$RPID\"\n"
       "wait $RPID\n"
       "EOS\n"
       "chmod +x /tmp/fifo_relay.sh; echo written" % BUF, t=60)
print("  " + r.replace("\n", "\n  "))

print("\n[5] 后台启动")
print("  " + sh("(setsid /tmp/fifo_relay.sh > /tmp/fr.log 2>&1 &); sleep 4; "
                "echo '--- 进程 ---'; ps | grep '[i]io_' | head -4; "
                "echo '--- 日志 ---'; cat /tmp/fr.log | head -5", t=120).replace("\n", "\n  "))

print("\n[6] 观察 8 秒，看进程是否稳定（不掉、不报错）")
print("  " + sh("for i in 1 2 3 4; do sleep 2; "
                "echo -n \"t=${i}x2s  reader=$(ps | grep -c '[i]io_readdev') \"; "
                "echo \"writer=$(ps | grep -c '[i]io_writedev')\"; done", t=120).replace("\n", "\n  "))

print("\n[7] CPU 占用")
print("  " + sh("top -b -n 1 2>/dev/null | head -12", t=60))

print("\n" + "=" * 76)
print(" 如果进程稳定，现在 CMU200 上的 1000.1 MHz 应该是【连续】的载波了")
print(" 停止： python relay_fifo.py stop")
print("=" * 76)
