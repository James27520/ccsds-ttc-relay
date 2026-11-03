#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
watch_usb.py -- 盯住 RK3588，等 FT4232 (LDSDR) 出现

用法: python watch_usb.py [COM8] [最长等待秒数]
"""

import sys
import time

sys.path.insert(0, r"E:\LDSDR_010")
from rk_console import RKConsole                          # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM8"
LIMIT = float(sys.argv[2]) if len(sys.argv) > 2 else 600.0


def main():
    with RKConsole(PORT) as rk:
        print("开始监听 RK3588 的 USB（最多 %.0f 秒）..." % LIMIT)
        t0 = time.time()
        last = ""
        n = 0
        while time.time() - t0 < LIMIT:
            n += 1
            r = rk.run("lsusb 2>/dev/null | grep -c 0403:6011 || true", wait=0.4, timeout=20)
            cnt = r.strip().split()[-1] if r.strip() else "0"
            devs = rk.run("ls /dev/ttyUSB* 2>/dev/null | tr '\\n' ' '", wait=0.3, timeout=20)
            cur = "cnt=%s devs=%s" % (cnt, devs.strip())
            if cur != last:
                print("  [%6.1f 秒] %s" % (time.time() - t0, cur))
                last = cur
            if cnt not in ("0", ""):
                print("\n✅ FT4232 出现了！")
                print(rk.run("lsusb | grep 0403", wait=0.4))
                print("串口: %s" % rk.run("ls -l /dev/ttyUSB*", wait=0.4))
                # 立刻试一下哪个口是载荷
                for i in range(4):
                    dev = "/dev/ttyUSB%d" % i
                    r2 = rk.run(
                        "stty -F %s 115200 raw -echo -crtscts 2>/dev/null; "
                        "(timeout 1.2 cat %s > /tmp/w.%d 2>/dev/null &); sleep 0.2; "
                        "printf 'status\\r\\n' > %s; sleep 1.3; head -c 120 /tmp/w.%d"
                        % (dev, dev, i, dev, i), wait=0.6, timeout=20)
                    first = (r2.splitlines() or [""])[0][:90]
                    mark = "  ← 就是它" if "STAT" in first else ""
                    print("   %s -> %s%s" % (dev, first if first.strip() else "(无应答)", mark))
                return 0
            time.sleep(2.0)
        print("\n超时，%d 次轮询都没看到 FT4232。" % n)
        return 1


if __name__ == "__main__":
    sys.exit(main())
