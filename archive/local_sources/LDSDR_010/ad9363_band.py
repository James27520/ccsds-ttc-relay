import re, zlib, os

PDF = r"E:\7010_AD9363_开源资料\Document\AD9363.pdf"
b = open(PDF, "rb").read()
print("AD9363.pdf  %d 字节  FlateDecode=%d  /Image=%d"
      % (len(b), len(re.findall(rb'FlateDecode', b)), b.count(b'/Image')))

streams = []
for m in re.finditer(rb"stream\r?\n", b):
    s = m.end(); e = b.find(b"endstream", s)
    if e < 0: continue
    raw = b[s:e]
    try: streams.append(zlib.decompress(raw))
    except Exception: streams.append(raw)

def pdf_text(data):
    out = []
    for m in re.finditer(rb"\((?:\\.|[^\\()])*\)\s*Tj|\[(?:[^\[\]]|\\.)*\]\s*TJ", data):
        parts = re.findall(rb"\((?:\\.|[^\\()])*\)", m.group(0))
        out.append(b"".join(x[1:-1] for x in parts).decode("latin-1"))
    return out

txt = []
for s in streams:
    txt += pdf_text(s)
joined = "\n".join(x for x in txt if x.strip())
print("提取 %d 字符" % len(joined))
if len(joined) < 200:
    print("(子集字体编码，文本层提不出来，改看 raw 流)")

# 直接在解压流里找频率范围的数字
print("\n=== 搜频段描述 ===")
KW = ["RF tuning range", "tuning range", "MHz to", "to 3.8", "to 2.7",
      "325", "650", "3800", "2700", "6000", "BBCZ", "ABCZ"]
for s in streams:
    t = s.decode("latin-1")
    for kw in KW:
        for m in re.finditer(re.escape(kw), t):
            a = max(0, m.start() - 90); z = min(len(t), m.end() + 90)
            seg = re.sub(r"[\x00-\x1f]", " ", t[a:z])
            seg = re.sub(r"\s+", " ", seg).strip()
            if len(seg) > 20:
                print("  [%s] ...%s..." % (kw, seg[:160]))

print("\n=== 仓库 README 里的说法（对照）===")
r = open(r"E:\7010_AD9363_开源资料\README_CN.md", encoding="utf-8").read()
for l in r.splitlines():
    if re.search(r"AD9363|Band|MHz|GHz|ABCZ|BBCZ", l):
        print("  " + l.strip()[:110])
