import sys, time, re
sys.path.insert(0, r"E:\LDSDR_010")
sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from rk_console import RKConsole
from serial_port import SerialPort

PW = "elf"
LDSDR = SerialPort("COM5", 115200)


def ldsdr(cmd, wait=1.5):
    LDSDR.write(cmd + "\r\n")
    time.sleep(wait)
    t = LDSDR.read().decode("ascii", "replace")
    return "\n".join(s.replace("LD>", "").strip()
                     for s in t.splitlines()
                     if s.replace("LD>", "").strip() and s.strip() != cmd)


time.sleep(0.4); LDSDR.read()
LDSDR.write("\r\n"); time.sleep(0.5)
LDSDR.write("stty -echo 2>/dev/null; export PS1='LD> '\r\n"); time.sleep(1.0)
LDSDR.read()

with RKConsole("COM8") as rk:
    def S(cmd, wait=1.2, timeout=120):
        return rk.run("echo %s | sudo -S %s 2>&1" % (PW, cmd), wait=wait, timeout=timeout)

    print("=== 1. 在 3588 上造 200MB 文件并起 HTTP 服务 ===")
    print(S("dd if=/dev/zero of=/tmp/big.bin bs=1M count=200 2>&1 | tail -1"))
    print(rk.run("cd /tmp && (nohup python3 -m http.server 8000 >/tmp/http.log 2>&1 &) ; "
                 "sleep 1.5; ss -ltn 2>/dev/null | grep 8000 || echo 'listening?'",
                 wait=1.5, timeout=40))

    print("\n=== 2. LDSDR 用 wget 拉这个文件（约 200 MB）===")
    LDSDR.write("wget -O /dev/null http://192.168.10.2:8000/big.bin 2>&1\r\n")
    t0 = time.time()
    acc = bytearray()
    while time.time() - t0 < 90:
        d = LDSDR.read()
        if d:
            acc += d
        txt = acc.decode("ascii", "replace")
        if "saved" in txt or "100%" in txt or "error" in txt.lower():
            break
        time.sleep(0.1)
    print("  " + txt.strip().replace("\r", "")[-600:])

    print("\n=== 3. 解析速率 ===")
    ms = re.findall(r"\(([\d.]+)\s*([kMG]?B)/s\)", txt)
    if ms:
        v, u = ms[-1]
        mul = {"B": 1e-6, "kB": 1e-3, "MB": 1.0, "GB": 1000.0}.get(u, 1.0)
        mbs = float(v) * mul
        print("  >>> 实测吞吐 ≈ %.1f MB/s  =  %.0f Mbps" % (mbs, mbs * 8))
    else:
        print("  没解析到速率，原始输出见上")
        print("  用时 %.1f 秒" % (time.time() - t0))

    print("\n=== 4. 关掉 HTTP 服务 ===")
    print(S("pkill -f 'http.server' 2>&1; rm -f /tmp/big.bin; echo cleaned"))

LDSDR.close()
