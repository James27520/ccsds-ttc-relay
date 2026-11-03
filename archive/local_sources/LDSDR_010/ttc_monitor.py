#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ttc_monitor.py -- 电脑端测控链路监视界面

通过 3588 的调试串口 (COM8)：
  1. 把 ttc_modem.py / ttc_test.py 传到 3588
  2. 运行测试
  3. 实时解析 3588 输出的 TTC|<json> 行，显示结构化的测试过程与结论

用法：
    python ttc_monitor.py            # 默认 COM8
    python ttc_monitor.py COM8 loop  # 发+收环回
    python ttc_monitor.py COM8 soft  # 纯软件环回
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, r"E:\LDSDR_010")
from rk_console import RKConsole

# ---------------- 颜色 ----------------
R = "\033[31m"; G = "\033[32m"; Y = "\033[33m"; C = "\033[36m"
B = "\033[1m"; D = "\033[2m"; N = "\033[0m"


def hr(ch="═", n=76):
    print(ch * n)


def hdr(title, right=""):
    hr()
    pad = n = 76 - len(title) - len(right) - 2
    print("  %s%s%s%s" % (B, title, N, " " * max(1, n) + right))
    hr()


def kv(k, v, color=""):
    print("   %-14s %s%s%s" % (k, color, v, N if color else ""))


def ok(v):
    return (G + "✅ " + N) if v else (R + "❌ " + N)


LOCAL = r"E:\LDSDR_010\rk3588"
FILES = ["ttc_modem.py", "ttc_test.py", "ttc_fsk_test.py"]
REMOTE = "/tmp/ttc"


# ---------------------------------------------------------------------
def upload(rk):
    print("%s[上传]%s 把测试程序传到 3588 ..." % (C, N))
    rk.run("mkdir -p %s" % REMOTE, wait=0.5)
    import base64
    okc = 0
    for fn in FILES:
        p = os.path.join(LOCAL, fn)
        if not os.path.exists(p):
            print("   %s 找不到 %s" % (ok(False), fn))
            continue
        data = open(p, "rb").read()
        b64 = base64.b64encode(data).decode("ascii")
        rk.run("rm -f %s/%s.b64" % (REMOTE, fn), wait=0.3)
        CH = 640
        for i in range(0, len(b64), CH):
            rk.run("printf '%%s' '%s' >> %s/%s.b64" % (b64[i:i + CH], REMOTE, fn),
                   wait=0.25, timeout=40)
        rk.run("base64 -d %s/%s.b64 > %s/%s && rm -f %s/%s.b64"
               % (REMOTE, fn, REMOTE, fn, REMOTE, fn), wait=0.6)
        sz = rk.run("wc -c < %s/%s" % (REMOTE, fn), wait=0.4)
        good = sz.strip().isdigit() and int(sz.strip()) == len(data)
        print("   %s %-16s %d 字节" % (ok(good), fn, len(data)))
        okc += 1 if good else 0
    return okc == len(FILES)


# ---------------------------------------------------------------------
def run_test(rk, mode):
    if mode == "fsk":
        script = "ttc_fsk_test.py"
        cmd = "cd %s && python3 %s 2>&1" % (REMOTE, script)
    else:
        cmd = "cd %s && python3 ttc_test.py %s 2>&1" % (REMOTE, mode)
    # ★ 先杀掉残留进程，否则会抢 DMA 设备导致"没有波形"
    rk.run("kill -9 $(ps | grep -E '[t]tc_spectrum|[t]tc_fsk|[i]io_readdev' "
           "| awk '{print $1}') 2>/dev/null; sleep 1; "
           "echo -n 'SS '; ps | grep -cE '[t]tc_spectrum|[i]io_readdev'",
           wait=2.5, timeout=40)
    print("%s[运行]%s %s\n" % (C, N, cmd))
    rk.sp.write(cmd + "\r\n")

    buf = bytearray()
    state = {}
    t0 = time.time()
    tmo = 600
    while time.time() - t0 < tmo:
        d = rk.sp.read()
        if d:
            buf += d
        txt = rk._clean(bytes(buf))
        while "\n" in txt:
            line, txt = txt.split("\n", 1)
            line = line.strip()
            if line.startswith("TTC|"):
                try:
                    ev = json.loads(line[4:])
                except Exception:
                    continue
                state = handle(ev, state)
            elif line and not line.startswith("python3") and "cd /tmp" not in line:
                if line not in ("RKCON>",) and not line.startswith("M="):
                    print("   %s%s%s" % (D, line[:110], N))
        buf = bytearray(txt.encode("utf-8", "replace"))
        if state.get("_done"):
            break
        time.sleep(0.05)
    # 收尾
    rest = rk._rd(1.0)
    return state


def handle(ev, st):
    k = ev.get("kind")
    if k == "phase":
        print("\n%s%s%s" % (B, ev["msg"], N))
    elif k == "cfg":
        txlo = ev.get("tx_lo", ev.get("lo"))
        rxlo = ev.get("rx_lo", ev.get("lo"))
        if txlo:
            kv("TX_LO", "%.3f MHz" % (txlo / 1e6))
        if rxlo:
            kv("RX_LO", "%.3f MHz" % (rxlo / 1e6))
        kv("采样率", "%.3f MSPS" % (ev["fs"] / 1e6))
        if ev.get("t_bit_ms"):
            kv("FSK", "f0=%.0f kHz  f1=%.0f kHz  %.0f ms/bit (%.0f bit/s)"
               % (ev["f0"] / 1e3, ev["f1"] / 1e3, ev["t_bit_ms"], ev["rate"]))
        kv("TX 衰减", "%s  (回读 %s)" % (ev.get("tx_att"), ev.get("tx_att_readback", "-")))
        kv("RX 增益", "%s  (回读 %s)" % (ev.get("rx_gain"), ev.get("rx_gain_readback", "-")))
    elif k == "relay":
        kv("来源", ev["dev"])
        print("   %s%s%s" % (D, ev["raw"], N))
    elif k == "packet":
        kv("遥测源", ev.get("src", "遥控包（FSK）"))
        kv("APID", "0x%03X" % ev["apid"])
        n = ev.get("n", ev.get("pkt_len"))
        if n:
            kv("包长", "%d 字节" % n)
        if ev.get("frame_len"):
            kv("成帧", "%d 字节 = 前导+同步字+包+CRC   共 %d bit，发送需 %.1f 秒"
               % (ev["frame_len"], ev["bits"], ev["dur_s"]))
        print("   %s%s%s" % (D, ev["hex"], N))
    elif k == "frame":
        kv("成帧", "%d 字节  前导4+同步4+包+CRC2" % ev["n"])
        print("   %s%s%s" % (D, ev["hex"], N))
    elif k == "wave":
        if ev.get("frame_s"):
            kv("FSK 波形", "%d 样点  %d 字节  一帧 %.2f 秒"
               % (ev["samples"], ev["bytes"], ev["frame_s"]))
        else:
            kv("波形", "%d 样点  (%.1f ms)  %d 字节"
               % (ev.get("n", ev.get("samples", 0)), ev.get("ms", 0), ev["bytes"]))
    elif k == "ctx":
        kv("libiio 上下文", "TX=%s  RX=%s" % (ev["tx"], ev["rx"]))
    elif k == "txon":
        kv("TX 已启动", "%d 字节，循环缓冲区（硬件无限重复）" % ev["bytes"])
    elif k == "txoff":
        kv("TX", "已停止")
    elif k == "tx":
        kv("发送 #%d" % ev["n"], ev["rc"])
    elif k == "rx":
        kv("接收", "%d 样点  (%.1f ms)  %d 字节"
           % (ev["samples"], ev["ms"], ev["bytes"]))
    elif k == "txsum":
        kv("发送汇总", "%d 次  累计 %.1f 秒  %s"
           % (ev["count"], ev["seconds"], "全部 rc=0" if ev["ok"] else "有失败"))
    elif k == "tone":
        hr("─")
        print("   %s连续单音已开启%s" % (G + B, N))
        kv("TX_LO", "%.4f MHz" % (ev["tx_lo"] / 1e6))
        kv("中频", "+%.1f kHz" % (ev["if_hz"] / 1e3))
        kv("★ 输出频率", "%.4f MHz" % (ev["out_hz"] / 1e6))
        kv("DDS 幅度寄存器", ev["dds_scale"])
        kv("TX 衰减", ev["tx_att"])
        hr("─")
    # ---------- FSK 遥控遥测验证 ----------
    elif k == "txdone":
        kv("发送完成", "%d bit，用时 %.1f 秒" % (ev["bits"], ev["el"]))
    elif k == "rxstat":
        if "stds" in ev:
            kv("接收通道 std", str(ev["stds"]))
        else:
            kv("电平", "I.std=%.0f  max=%d  Q.std=%.0f"
               % (ev["istd"], ev["imax"], ev["qstd"]))
    elif k == "chan":
        kv("选用通道", "ch%d  (std=%.1f)" % (ev["ch"], ev["std"]))
    elif k == "spectrum":
        kv("接收频谱底", "%.1f dB" % ev["noise"])
        kv("最强 8 个峰", "  ".join("%+.1fk(%.0f)" % (f, d) for f, d in ev["top"]))
    elif k == "bands":
        kv("频带能量", "150kHz 带 %.1f dB   400kHz 带 %.1f dB   直流带 %.1f dB(相对底)"
           % (ev["f0_db"], ev["f1_db"], ev["dc_db"]))
    elif k == "search":
        kv("相位搜索", "试了 %d 个偏移 × %d bit，最好错 %d bit"
           % (ev["probes"], ev["step"], ev["best_err"]))
    elif k == "demod":
        kv("解调", "%d 样点，%d 样点/bit，共 %d bit，偏移 %s"
           % (ev["samples"], ev["spb"], ev["bits"], ev.get("offset", "-")))
    elif k == "bits":
        kv("判决输出", "%d bit" % ev["n"])
    elif k == "sync":
        if ev["found_at"] >= 0:
            kv("同步字", "%s 命中于 bit %d（错 %d bit）"
               % (G + "0x1ACFFC1D" + N, ev["found_at"], ev["err"]))
        else:
            kv("同步字", "%s未找到%s" % (R, N))
    elif k == "ber":
        c = G if ev["ber"] < 1e-3 else (Y if ev["ber"] < 0.01 else R)
        kv("误码率", "%s%.4f%s  (%d/%d bit 错)"
           % (c, ev["ber"], N, ev["errors"], ev["total"]))
    elif k == "result":
        hr("─")
        if ev.get("sent"):
            print("   %s%s%s" % ((G if ev.get("ok") else R), ev.get("msg", ""), N))
            print("   %s发射链路已执行 —— 请到 CMU200 上确认 1000.2 MHz 有没有信号%s" % (C, N))
            if ev.get("reason"):
                print("   %s%s%s" % (R, ev["reason"], N))
        elif ev.get("ok"):
            print("   %s同步字命中%s   字节偏移 %s" % (G, N, ev.get("sync_at", "?")))
            print("   %sAPID = 0x%03X%s" % (G, ev["apid"], N))
            print("   %sCRC-16 校验通过%s" % (G, N))
            if ev.get("match"):
                print("   %s内容逐字节一致%s" % (G + B, N))
            else:
                print("   %s内容不一致%s" % (R + B, N))
            if ev.get("tx"):
                print("     发送: %s" % ev["tx"])
                print("     接收: %s" % ev.get("rx", "?"))
        else:
            print("   %s未通过%s  原因: %s" % (R, N, ev.get("reason", "?")))
        hr("─")
        st["result"] = ev
    elif k == "done":
        print("\n%s%s%s" % (B, ev.get("msg", ""), N))
        st["_done"] = True
    return st


# ---------------------------------------------------------------------
def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM8"
    mode = sys.argv[2] if len(sys.argv) > 2 else "soft"

    hdr("测控链路端到端测试",
        time.strftime("%H:%M:%S"))
    print("   3588 调试口 %s    测试模式 %s" % (port, mode))

    try:
        with RKConsole(port) as rk:
            if not upload(rk):
                print("\n%s上传失败，中止%s" % (R, N))
                return 2
            st = run_test(rk, mode)
    except Exception as e:
        print("\n%s出错: %s%s" % (R, e, N))
        return 3

    hr()
    r = st.get("result")
    if r and r.get("sent"):
        print("  %s结论：发射已执行%s —— 现在去 CMU200 确认 1000.2 MHz 的信号"
              % (G + B, N))
    elif r and r.get("ok"):
        print("  %s结论：测控链路测试通过 —— 遥测生成/发送/接收/校验 全部正确%s"
              % (G + B, N))
    elif r:
        print("  %s结论：未通过 —— %s%s" % (R + B, r.get("reason", "?"), N))
    else:
        print("  %s结论：没有拿到结果%s" % (Y, N))
    hr()
    if r and r.get("sent"):
        return 0
    return 0 if (r and r.get("ok")) else 1


if __name__ == "__main__":
    sys.exit(main())
