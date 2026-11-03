import sys, time
sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from serial_port import SerialPort

for port in ("COM4", "COM5", "COM6"):
    try:
        sp = SerialPort(port, 115200)
        time.sleep(0.3)
        sp.read()
        sp.write("\r\n")
        time.sleep(0.6)
        pre = sp.read()
        sp.write("status\r\n")
        time.sleep(1.2)
        out = sp.read()
        both = (pre + out).decode("ascii", "replace")
        flag = ""
        if "STAT" in both:
            flag = "  <== LDSDR 载荷！"
        elif "login:" in both:
            flag = "  <== Linux 登录提示"
        elif "Pluto>" in both or "U-Boot" in both:
            flag = "  <== U-Boot"
        print("%-6s OK%s" % (port, flag))
        for l in both.splitlines():
            s = l.strip()
            if s:
                print("        %s" % s[:110])
            if s.startswith("STAT"):
                break
        sp.close()
    except Exception as e:
        print("%-6s 打不开: %s" % (port, e))
