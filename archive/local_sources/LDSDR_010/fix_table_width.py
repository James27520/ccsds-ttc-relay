import io
import re

FIX = '''
    t.autofit = False
    _tw = OxmlElement("w:tblW")
    _tw.set(qn("w:w"), str(int(sum(widths) * 567)))
    _tw.set(qn("w:type"), "dxa")
    t._tbl.tblPr.append(_tw)
'''

for path, marker in ((r"E:\LDSDR_010\make_usb_report.py", "    if widths:\n        for r in t.rows:"),
                     (r"E:\LDSDR_010\make_ttc_report.py", "    if widths:\n        for row in t.rows:")):
    t = io.open(path, encoding="utf-8").read()
    if "t.autofit = False" in t:
        print("%s: 已修过" % path)
        continue
    # 在 widths 处理块之前插入
    idx = t.find(marker)
    if idx < 0:
        print("%s: 找不到插入点" % path)
        continue
    # 找到该行所在语句的缩进（4 空格）
    t = t[:idx] + FIX.lstrip("\n") + "\n" + t[idx:]
    io.open(path, "w", encoding="utf-8", newline="\n").write(t)
    print("%s: 已插入 autofit 修复" % path)
