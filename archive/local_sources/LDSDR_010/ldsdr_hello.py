import sys
import time

sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from serial_port import SerialPort

for port in ("COM5", "COM4", "COM6"):
    print("=" * 70)
    print("尝试 %s ..." % port)
    try:
        sp = SerialPort(port, 115200)
    except Exception as e:
        print("  打不开: %s" % e)
        continue
    time.sleep(0.5)
    sp.read()

    sp.write("\r\n")
    time.sleep(0.8)
    out = sp.read().decode("utf-8", "replace")
    print("  唤醒输出: %r" % out[-160:])

    for cmd in ("help", "status", "mode", "gain"):
        sp.write(cmd + "\r\n")
        time.sleep(0.9)
        r = sp.read().decode("utf-8", "replace")
        r = r.replace("\r", "")
        lines = [l for l in r.splitlines() if l.strip()]
        print("  $ %-8s -> %s" % (cmd, " | ".join(lines[:4])[:180]))
        if cmd == "help" and ("mode" in r or "gain" in r):
            print("      ★ 这个口有 CLI")
    sp.close()
