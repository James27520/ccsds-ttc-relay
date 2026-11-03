import os, re
from collections import defaultdict

HW = r"E:\7010_AD9363_开源资料\hardware"


def strings(data, minlen=4):
    out, cur = [], []
    for b in data:
        if 32 <= b < 127:
            cur.append(chr(b))
        else:
            if len(cur) >= minlen:
                out.append("".join(cur))
            cur = []
    if len(cur) >= minlen:
        out.append("".join(cur))
    return out


KEY = re.compile(r"TCM1|HHM|SAW|LPF|BPF|JTX|BALUN|BALFHB|ADT[12]|LDB|SYBP|BFCN|"
                 r"2450|1950|2140|2400|0868|0889|18P|RFLPF", re.I)
MODEL = re.compile(r"\b(TCM1[-\w+]*|HHM[-\w+]*|JTX[-\w+]*|BALFHB[-\w+]*|"
                   r"ADT[12][-\w+]*|SAW[A-Z0-9]*[-\w+]*|SYBP[-\w+]*|LDB[-\w+]*)\b")

print("=" * 78)
print(" 新板射频相关元件型号提取")
print("=" * 78)

allmodels = defaultdict(set)
for fn in sorted(os.listdir(HW)):
    p = os.path.join(HW, fn)
    if not os.path.isfile(p):
        continue
    raw = open(p, "rb").read()
    ss = strings(raw, 4)
    ms = set()
    for s in ss:
        for m in MODEL.finditer(s):
            ms.add(m.group(1))
        # 直接是型号的短串
        t = s.strip()
        if re.match(r"^(TCM1|HHM|JTX|BALFHB|ADT[12]|SYBP|LDB)[-\w+]{2,}$", t):
            ms.add(t)
    if ms:
        print("\n  【%s】" % fn)
        for m in sorted(ms):
            print("     %s" % m)
            allmodels[m].add(fn)

print("\n" + "=" * 78)
print(" 汇总")
print("=" * 78)
for m in sorted(allmodels):
    print("  %-28s 出现在: %s" % (m, ", ".join(sorted(allmodels[m]))[:90]))

# 再看 08 BALUN 里 TCM1 附近的内容
print("\n" + "=" * 78)
print(" 08 BALUN.SchDoc 里所有含 TCM1 的字符串")
print("=" * 78)
raw = open(os.path.join(HW, "08 BALUN.SchDoc"), "rb").read()
for s in strings(raw, 3):
    if "TCM1" in s.upper():
        print("  %r" % s[:120])

# 在整块 PCB 里找完整型号（那里的注释最全）
print("\n" + "=" * 78)
print(" PCB 文件里的完整型号（最权威）")
print("=" * 78)
raw = open(os.path.join(HW, "ZYNQ7020_AD9364_V2.PcbDoc"), "rb").read()
ss = strings(raw, 4)
models = set()
for s in ss:
    for m in re.finditer(r"\b(TCM1-[\w+]+|HHM[\w-]+|JTX[\w-]+|BALFHB[\w-]+|"
                         r"SAW[\w-]+|SYBP[\w-]+|LDB[\w-]+)\b", s):
        models.add(m.group(1))
for m in sorted(models):
    print("  %s" % m)
if not models:
    # 退化：找所有像型号的
    print("  (未匹配到，打印含关键字的原始串)")
    for s in ss:
        if re.search(r"TCM1|HHM|SAW|JTX|BALUN", s, re.I) and len(s) < 70:
            print("    %r" % s)
