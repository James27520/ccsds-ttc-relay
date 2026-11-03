#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
deploy_to_rk3588.py -- 把载荷控制程序部署到 RK3588

打包 -> gzip -> base64 -> 通过调试串口以分块写入 -> 校验 md5 -> 解包

用法:
    python deploy_to_rk3588.py                 # 用 COM8
    python deploy_to_rk3588.py COM8
"""

import base64
import hashlib
import io
import os
import sys
import tarfile
import time

sys.path.insert(0, r"E:\LDSDR_010")
from rk_console import RKConsole                          # noqa: E402

SRC = r"E:\LDSDR_010\rk3588"
DEST = "/home/elf/ldsdr"
FILES = ["serial_port.py", "relay_link.py", "ccsds.py", "payload_ctl.py",
         "spectrum.py", "channel_detect.py", "spectrum_tool.py",
         "PROTOCOL.md", "README.md", "SPECTRUM_PROTOCOL.md"]
CHUNK = 700


def build_tarball():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name in FILES:
            p = os.path.join(SRC, name)
            if os.path.exists(p):
                tf.add(p, arcname=name)
    return buf.getvalue()


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM8"

    data = build_tarball()
    md5 = hashlib.md5(data).hexdigest()
    b64 = base64.b64encode(data).decode("ascii")
    print("打包: %d 字节 -> gzip %d -> base64 %d 字符  md5=%s"
          % (sum(os.path.getsize(os.path.join(SRC, f)) for f in FILES
                 if os.path.exists(os.path.join(SRC, f))),
             len(data), len(b64), md5))
    print("分块: %d 字符/块, 共 %d 块" % (CHUNK, (len(b64) + CHUNK - 1) // CHUNK))

    with RKConsole(port) as rk:
        print("\n[1/5] 准备目录")
        print("   ", rk.run("mkdir -p %s && rm -f /tmp/p.b64 && echo ready" % DEST))

        print("[2/5] 分块传输 base64 ...")
        t0 = time.time()
        rk.run("rm -f /tmp/p.b64", wait=0.2)
        n = (len(b64) + CHUNK - 1) // CHUNK
        for i in range(0, len(b64), CHUNK):
            chunk = b64[i:i + CHUNK]
            # 每块一条命令，确保上一块落盘后再发下一块
            rk.run("printf '%%s' '%s' >> /tmp/p.b64" % chunk, wait=0.2, timeout=40)
            k = i // CHUNK + 1
            if k % 5 == 0 or k == n:
                print("      %d/%d 块  (%.1f 秒)" % (k, n, time.time() - t0))
        print("      传输完成，用时 %.1f 秒" % (time.time() - t0))

        print("[3/5] 校验")
        got = rk.run("md5sum /tmp/p.b64 | cut -d' ' -f1", wait=0.4).strip()
        want = hashlib.md5(b64.encode("ascii")).hexdigest()
        print("      远端 %s" % got)
        print("      期望 %s" % want)
        if got != want:
            print("  !! md5 不匹配，传输有误。重跑一次。")
            return 1
        print("      ✅ md5 一致")

        print("[4/5] 解包")
        r = rk.run("base64 -d /tmp/p.b64 > /tmp/p.tgz && "
                   "cd %s && tar xzf /tmp/p.tgz && ls -l" % DEST, wait=0.6, timeout=60)
        print(r)

        print("[5/5] 验证")
        r = rk.run("cd %s && python3 -c \"import serial_port, relay_link, ccsds; "
                   "print('模块导入 OK')\" 2>&1 | tail -3" % DEST, wait=0.6, timeout=60)
        print("   ", r)

    print("\n部署完成 -> %s" % DEST)
    return 0


if __name__ == "__main__":
    sys.exit(main())
