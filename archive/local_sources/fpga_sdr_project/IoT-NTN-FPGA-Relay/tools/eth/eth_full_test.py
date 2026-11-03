import sys, time, re
sys.path.insert(0, r"E:\LDSDR_010")
sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from rk_console import RKConsole
from serial_port import SerialPort

PW = "elf"
LDSDR = SerialPort("COM5", 115200)


def sh(cmd, wait=1.5):
    LDSDR.write(cmd + "\r\n"); time.sleep(wait)
    t = LDSDR.read().decode("ascii", "replace")
    return "\n".join(s.replace("LD>", "").strip() for s in t.splitlines()
                     if s.replace("LD>", "").strip() and s.strip() != cmd)


time.sleep(0.4); LDSDR.read()
LDSDR.write("\r\n"); time.sleep(0.5)
LDSDR.write("stty -echo 2>/dev/null; export PS1='LD> '\r\n"); time.sleep(1.0); LDSDR.read()

print("=== 1. 反向 ping：LDSDR -> 3588 ===")
print(sh("ping -c 3 -W 2 192.168.10.2", 5.0))
print(sh("ip neigh show dev eth0", 1.0))

with RKConsole("COM8") as rk:
    def R(cmd, wait=0.8, timeout=60):
        return rk.run(cmd, wait=wait, timeout=timeout)

    def S(cmd, wait=1.2, timeout=120):
        return rk.run("echo %s | sudo -S %s 2>&1" % (PW, cmd), wait=wait, timeout=timeout)

    print("\n=== 2. 3588 起 HTTP 服务（200 MB 文件）===")
    print(S("dd if=/dev/zero of=/tmp/big.bin bs=1M count=200 2>&1 | tail -1"))
    print(R("cd /tmp && (nohup python3 -m http.server 8000 >/tmp/http.log 2>&1 &) ; "
            "sleep 1.5; ss -ltn | grep 8000", wait=1.5, timeout=40))

    print("\n=== 3. LDSDR 用 wget 拉（测吞吐）===")
    LDSDR.write("wget -O /dev/null http://192.168.10.2:8000/big.bin 2>&1\r\n")
    t0 = time.time()
    acc = bytearray()
    while time.time() - t0 < 120:
        d = LDSDR.read()
        if d:
            acc += d
        txt = acc.decode("ascii", "replace")
        if "saved" in txt or "100%" in txt or "error" in txt.lower() or "refused" in txt:
            break
        time.sleep(0.1)
    el = time.time() - t0
    print("  " + txt.strip().replace("\r", "")[-500:])

    print("\n=== 4. 速率 ===")
    ms = re.findall(r"\(([\d.]+)\s*([kMG]?B)/s\)", txt)
    if ms:
        v, u = ms[-1]
        mul = {"B": 1e-6, "kB": 1e-3, "MB": 1.0, "GB": 1000.0}.get(u, 1.0)
        mbs = float(v) * mul
        print("  >>> 实测吞吐 ≈ %.1f MB/s  =  %.0f Mbps" % (mbs, mbs * 8))
    else:
        mb = re.search(r"(\d{6,})\s+bytes", txt)
        if mb and el > 1:
            mbs = int(mb.group(1)) / el / 1e6
            print("  >>> 实测 %.1f MB/s（%.1f 秒）" % (mbs, el))
        else:
            print("  没解析到，用时 %.1f 秒" % el)

    print("\n=== 5. 清理 ===")
    print(S("pkill -f 'http.server' 2>&1; rm -f /tmp/big.bin 2>&1; echo cleaned",
            wait=1.5, timeout=60))

LDSDR.close()
