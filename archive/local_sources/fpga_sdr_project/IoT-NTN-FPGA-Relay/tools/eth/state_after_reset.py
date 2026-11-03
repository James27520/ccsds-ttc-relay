import sys, time
sys.path.insert(0, r"E:\LDSDR_010")
sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from rk_console import RKConsole
from serial_port import SerialPort

print("=" * 70)
print(" 复位后的系统状态")
print("=" * 70)

# --- LDSDR ---
print("\n【LDSDR】")
sp = SerialPort("COM5", 115200)
time.sleep(0.4); sp.read()
sp.write("\r\n"); time.sleep(0.6)
pre = sp.read().decode("ascii", "replace")
sp.write("status\r\n"); time.sleep(1.5)
out = sp.read().decode("ascii", "replace")
both = pre + out
if "STAT" in both:
    print("  ✅ 转发器已恢复运行")
    for l in both.splitlines():
        if l.strip().startswith("STAT"):
            print("     %s" % l.strip()[:118])
            break
elif "login:" in both:
    print("  ⚠️ 停在 Linux 登录提示（原厂系统还在）")
elif "Pluto>" in both:
    print("  ⚠️ 停在 U-Boot 提示符")
else:
    print("  输出: %r" % both[-200:])
sp.close()

# --- 3588 ---
print("\n【RK3588】")
with RKConsole("COM8") as rk:
    print("  主机名   :", rk.run("hostname", wait=0.4).strip())
    print("  eth0     :", rk.run("ip -br addr show eth0 2>&1", wait=0.5).strip() or "(无)")
    print("  网口速率 : %s Mbps, carrier=%s" % (
        rk.run("cat /sys/class/net/eth0/speed 2>&1", wait=0.3).strip(),
        rk.run("cat /sys/class/net/eth0/carrier 2>&1", wait=0.3).strip()))
    p = rk.run("ping -c 2 -W 2 192.168.10.1 2>&1", wait=1.2, timeout=40)
    print("  ping LDSDR:", "通" if "0% packet loss" in p else "不通  (%s)"
          % (p.splitlines()[-1][:60] if p.splitlines() else ""))
    print("  已有程序 :", rk.run("ls /home/elf/ldsdr/ 2>&1 | tr '\\n' ' '", wait=0.5).strip())
    print("  USB 串口 :", rk.run("ls /dev/ttyUSB* 2>&1 | tr '\\n' ' '", wait=0.4).strip() or "(无 —— USB 在电脑上)")
