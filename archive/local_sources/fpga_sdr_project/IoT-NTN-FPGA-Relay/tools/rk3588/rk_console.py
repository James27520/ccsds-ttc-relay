#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rk_console.py -- 通过调试串口操作 RK3588 的可复用模块

把「登录 elf2-desktop → 执行命令 → 取回输出」封装成 Python 接口，
以后所有在 3588 上的部署、探测、测试都可以用它自动化。

用法：
    from rk_console import RKConsole
    with RKConsole("COM8") as rk:
        print(rk.run("uname -a"))
        print(rk.run("ls /dev/ttyUSB*"))
        rk.put_text("hello", "/tmp/x.txt")     # 传小文件
"""

import os
import re
import time

import sys
sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from serial_port import SerialPort                       # noqa: E402

# 终端控制序列（括号粘贴模式等）要去掉，否则会污染输出
ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x1b[=>]|\r")
# 提示符：任意以 $ # 或 > 结尾的行（覆盖 RK> 、elf@elf2-desktop:~$ 等）
PROMPT = re.compile(r"(?:^|\n)[^\n]*?[$#>][ \t]*$")


class RKConsole(object):
    def __init__(self, port="COM8", baud=115200, user="elf", passwd="elf", verbose=False):
        self.port = port
        self.baud = baud
        self.user = user
        self.passwd = passwd
        self.verbose = verbose
        self.sp = None
        self.ps1 = "RKCON> "

    # ------------------------------------------------------------------
    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *a):
        self.close()

    # ------------------------------------------------------------------
    def _rd(self, secs):
        t0 = time.time()
        o = bytearray()
        while time.time() - t0 < secs:
            d = self.sp.read()
            if d:
                o += d
            else:
                time.sleep(0.03)
        return bytes(o)

    def _clean(self, b):
        t = b.decode("utf-8", "replace")
        t = ANSI.sub("", t)
        return t

    # ------------------------------------------------------------------
    def open(self):
        self.sp = SerialPort(self.port, self.baud)
        time.sleep(0.4)
        self.sp.read()

        self.sp.write("\r\n")
        buf = bytearray()
        state = "probe"
        t0 = time.time()
        while time.time() - t0 < 30:
            d = self.sp.read()
            if d:
                buf += d
            txt = self._clean(bytes(buf))

            if state == "probe":
                if "login:" in txt:
                    state = "user"
                    self.sp.write(self.user + "\r\n")
                    buf = bytearray()
                elif PROMPT.search(txt):
                    # 已经登录着（上次会话留下的），直接用
                    state = "ready"
                    buf = bytearray()
            elif state == "user":
                if "Password:" in txt:
                    state = "pass"
                    self.sp.write(self.passwd + "\r\n")
                    buf = bytearray()
            elif state == "pass":
                if "incorrect" in txt.lower():
                    raise RuntimeError("密码错误")
                if PROMPT.search(txt):
                    state = "ready"
                    buf = bytearray()

            if state == "ready":
                break
            time.sleep(0.05)

        if state != "ready":
            raise RuntimeError("登录失败，最后输出: %r" % self._clean(bytes(buf))[-300:])

        # 关掉回显和括号粘贴，设固定提示符
        self.sp.write("stty -echo -icanon 2>/dev/null; "
                      "export PS1='%s'; unset PROMPT_COMMAND\r\n" % self.ps1)
        time.sleep(1.0)
        self._rd(0.5)

        # 自检：空回车应当立刻回到提示符
        self.sp.write("\r\n")
        t = self._clean(self._rd(0.6))
        if self.ps1 not in t and PROMPT.search(t) is None and t.strip():
            raise RuntimeError("提示符设置异常，收到: %r" % t[-200:])
        return self

    def close(self):
        if self.sp:
            try:
                self.sp.close()
            except Exception:
                pass
            self.sp = None

    # ------------------------------------------------------------------
    def run(self, cmd, wait=1.2, timeout=60.0):
        """执行一条命令，返回去掉提示符和回显的纯输出。

        标记符技巧：标记拆成 `M=ZQ123; ...; echo ${M}Z$?`，
        这样**命令行回显里不会出现完整的标记串**，避免串口回显导致提前返回。
        """
        tag = "ZQ%d" % int(time.time() * 1000 % 1000000)
        endmark = tag + "Z"
        full = "M=%s; %s; echo ${M}Z$?" % (tag, cmd)
        self.sp.write(full + "\r\n")

        buf = bytearray()
        t0 = time.time()
        while time.time() - t0 < timeout:
            d = self.sp.read()
            if d:
                buf += d
                if endmark in self._clean(bytes(buf)):
                    break
            else:
                time.sleep(0.03)
                if time.time() - t0 > wait and not buf:
                    break

        txt = self._clean(bytes(buf))
        lines = []
        ptok = self.ps1.strip()
        for l in txt.splitlines():
            s = l.replace(ptok, "").strip()
            if not s:
                continue
            if s == full.strip() or s == cmd.strip():
                continue
            if endmark in s:
                m = re.search(re.escape(endmark) + r"(\d+)", s)
                self.last_rc = int(m.group(1)) if m else None
                pre = s[:s.index(endmark)].strip()
                if pre:
                    lines.append(pre)
                continue
            # 丢掉回显体的首尾碎片
            if s.startswith("M=" + tag):
                s = s[len("M=" + tag):].lstrip("; ").strip()
                if not s:
                    continue
            lines.append(s)
        if self.verbose:
            print("[rk] $ %s" % cmd)
            for l in lines:
                print("      %s" % l)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    def put_text(self, text, dst):
        """把一段文本写到 3588 上（用 base64，避免特殊字符问题）。"""
        import base64
        b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
        self.run("rm -f %s.b64" % dst, wait=0.3)
        # 分块追加，避免单行过长
        CH = 480
        for i in range(0, len(b64), CH):
            chunk = b64[i:i + CH]
            self.run("printf '%%s' '%s' >> %s.b64" % (chunk, dst), wait=0.25, timeout=20)
        self.run("base64 -d %s.b64 > %s && rm -f %s.b64 && wc -c %s" % (dst, dst, dst, dst),
                 wait=0.5, timeout=30)
        return self.run("wc -c < %s" % dst)


if __name__ == "__main__":
    with RKConsole(verbose=True) as rk:
        print(rk.run("hostname"))
        print(rk.run("ls /dev/ttyUSB*"))
