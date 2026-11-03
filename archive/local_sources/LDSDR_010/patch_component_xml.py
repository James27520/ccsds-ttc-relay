#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_component_xml.py -- 给 axi_ctrl 的 component.xml 补上 ch2 端口定义

BD 认识的端口来自 component.xml，不是 Verilog。改了 Verilog 不改这里，
modify_bd.tcl 就看不到新端口。
"""
import io
import re
import shutil

P = r"E:\LDSDR_010\repo\axi_ctrl\component.xml"
shutil.copy(P, P + ".bak_ch2")

t = io.open(P, encoding="utf-8").read()

if "relay_mode2" in t:
    print("已经打过补丁，退出")
    raise SystemExit(0)


def grab(name):
    """取出某个端口的完整 XML 块"""
    m = re.search(r"[ \t]*<spirit:port>\s*<spirit:name>%s</spirit:name>.*?</spirit:port>\n"
                  % re.escape(name), t, re.S)
    if not m:
        raise SystemExit("找不到端口模板块: %s" % name)
    return m.group(0)


def make(tmpl, newname):
    """复制模板、换名字"""
    return tmpl.replace("<spirit:name>%s</spirit:name>" %
                        re.search(r"<spirit:name>(.*?)</spirit:name>", tmpl).group(1),
                        "<spirit:name>%s</spirit:name>" % newname)


t_out_vec = grab("relay_mode")        # out [1:0]
t_out_32 = grab("relay_ddc_freq")     # out [31:0]
t_out_12 = grab("relay_gain")         # out [11:0]
t_out_s = grab("relay_dc_en")         # out scalar
t_in_32 = grab("status_sample_cnt")   # in [31:0]

# ---- 在 relay_dc_en 之后插入 ch2 的输出端口 ----
anchor = grab("relay_dc_en")
ins = (make(t_out_vec, "relay_mode2") + make(t_out_32, "relay_ddc_freq2")
       + make(t_out_32, "relay_duc_freq2") + make(t_out_12, "relay_gain2")
       + make(t_out_s, "relay_dc_en2"))
t = t.replace(anchor, anchor + ins, 1)

# ---- 在 status_out_cnt 之后插入 ch2 的状态输入端口 ----
anchor2 = grab("status_out_cnt")
t = t.replace(anchor2, anchor2 + make(t_in_32, "status_sample_cnt2")
              + make(t_in_32, "status_clip_cnt2"), 1)

io.open(P, "w", encoding="utf-8", newline="\n").write(t)

# ---- 验证 ----
t2 = io.open(P, encoding="utf-8").read()
for n in ("relay_mode2", "relay_ddc_freq2", "relay_duc_freq2", "relay_gain2",
          "relay_dc_en2", "status_sample_cnt2", "status_clip_cnt2"):
    print("  %-20s %s" % (n, "OK" if ("<spirit:name>%s</spirit:name>" % n) in t2 else "缺失"))
print("总端口数: %d" % t2.count("<spirit:port>"))

# ---- XML 合法性 ----
import xml.etree.ElementTree as ET
ET.parse(P)
print("XML 解析 OK")
