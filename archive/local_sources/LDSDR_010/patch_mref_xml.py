#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_mref_xml.py -- 给 bd/mref/relay_dq/component.xml 补上 ch2 端口

BD 把 relay_dq 打包成 module reference 时，端口列表冻结在这个 component.xml。
只改 Verilog 不改它，BD 单元永远只有旧端口（实测：删掉重建也没用）。
"""
import io
import re
import shutil
import xml.etree.ElementTree as ET

P = r"E:\LDSDR_010\zynq_dev_fmcomms3.srcs\sources_1\bd\mref\relay_dq\component.xml"
shutil.copy(P, P + ".bak_ch2")

t = io.open(P, encoding="utf-8").read()
if "ctrl_mode2" in t:
    print("已经打过补丁")
    raise SystemExit(0)

print("现有端口:")
for m in re.finditer(r"<spirit:name>(\w+)</spirit:name>\s*</spirit:port>", t):
    pass
ports = re.findall(r"<spirit:port>\s*<spirit:name>(\w+)</spirit:name>", t)
print("  " + ", ".join(ports))


def grab(name):
    m = re.search(r"[ \t]*<spirit:port>\s*<spirit:name>%s</spirit:name>.*?</spirit:port>\n"
                  % re.escape(name), t, re.S)
    if not m:
        raise SystemExit("找不到模板块: %s" % name)
    return m.group(0)


def make(tmpl, newname):
    old = re.search(r"<spirit:name>(.*?)</spirit:name>", tmpl).group(1)
    return tmpl.replace("<spirit:name>%s</spirit:name>" % old,
                        "<spirit:name>%s</spirit:name>" % newname)


t_vec2 = grab("ctrl_mode")       # in [1:0]
t_s1 = grab("ctrl_dc_en")        # in scalar
t_v12 = grab("ctrl_gain")        # in [11:0]
t_v32 = grab("ctrl_ddc_freq")    # in [31:0]
t_st32 = grab("status_sample_cnt")   # out [31:0]

# 在 ctrl_duc_freq 之后插入 ch2 的输入端口
anchor = grab("ctrl_duc_freq")
ins = (make(t_vec2, "ctrl_mode2") + make(t_s1, "ctrl_dc_en2")
       + make(t_v12, "ctrl_gain2") + make(t_v32, "ctrl_ddc_freq2")
       + make(t_v32, "ctrl_duc_freq2"))
t = t.replace(anchor, anchor + ins, 1)

# 在 status_out_cnt 之后插入 ch2 的状态输出
anchor2 = grab("status_out_cnt")
t = t.replace(anchor2, anchor2 + make(t_st32, "status_sample_cnt2")
              + make(t_st32, "status_clip_cnt2"), 1)

io.open(P, "w", encoding="utf-8", newline="\n").write(t)

t2 = io.open(P, encoding="utf-8").read()
newp = ["ctrl_mode2", "ctrl_dc_en2", "ctrl_gain2", "ctrl_ddc_freq2",
        "ctrl_duc_freq2", "status_sample_cnt2", "status_clip_cnt2"]
for n in newp:
    print("  %-20s %s" % (n, "OK" if ("<spirit:name>%s</spirit:name>" % n) in t2 else "缺失"))
print("总端口数: %d" % len(re.findall(r"<spirit:port>", t2)))
ET.parse(P)
print("XML 解析 OK")
