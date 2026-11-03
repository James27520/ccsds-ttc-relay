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

with RKConsole("COM8") as rk:
    def S(cmd, wait=1.2, timeout=180):
        return rk.run("echo %s | sudo -S %s 2>&1" % (PW, cmd), wait=wait, timeout=timeout)

    print("=== 准备 500 MB 文件 + HTTP 服务 ===")
    print(S("dd if=/dev/zero of=/tmp/big.bin bs=1M count=500 2>&1 | tail -1"))
    print(rk.run("cd /tmp && (nohup python3 -m http.server 8000 >/tmp/http.log 2>&1 &); "
                 "sleep 1.5; ss -ltn | grep 8000", wait=1.5, timeout=40))

    print("\n=== LDSDR 下载并用 date 精确计时 ===")
    LDSDR.write("S=$(date +%s.%N); wget -q -O /dev/null "
                "http://192.168.10.2:8000/big.bin; E=$(date +%s.%N); "
                "echo \"ELAPSED=$(echo $E - $S | bc 2>/dev/null || echo NA)\"\r\n")
    t0 = time.time()
    acc = bytearray()
    while time.time() - t0 < 180:
        d = LDSDR.read()
        if d:
            acc += d
        txt = acc.decode("ascii", "replace")
        if "ELAPSED=" in txt or "LD>" in txt:
            break
        time.sleep(0.1)
    print("  " + txt.strip().replace("\r", "")[-400:])

    el = None
    m = re.search(r"ELAPSED=([\d.]+)", txt)
    if m:
        el = float(m.group(1))
    if el and el > 0.1:
        size = 500 * 1024 * 1024
        mbs = size / el / 1e6
        print("\n  >>> 500 MiB / %.2f 秒" % el)
        print("  >>> 实测吞吐 = %.1f MB/s  =  %.0f Mbps" % (mbs, mbs * 8))
        print("\n  === 对比 ===")
        print("  UART 115200        :      0.0115 MB/s")
        print("  本次以太网          : %10.1f MB/s   （快 %.0f 倍）" % (mbs, mbs / 0.0115))
        print("  30.72MSPS IQ(int8) :      61.4 MB/s    -> %s"
              % ("可以传原始 IQ！" if mbs > 61.4 else "不够传原始 IQ，需抽取"))
        print("  30.72MSPS IQ(int16):     122.9 MB/s    -> %s"
              % ("可以传" if mbs > 122.9 else "不够，需 int8 或抽取"))
    else:
        print("  没能精确计时（BusyBox 可能没有 bc）")

    print("\n=== 清理 ===")
    print(S("pkill -f 'http.server'; rm -f /tmp/big.bin; echo cleaned", wait=1.5, timeout=60))

LDSDR.close()
