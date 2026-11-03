import os, re, io

D = r"E:\7010_AD9363_开源资料"
HW = os.path.join(D, "hardware")

print("=" * 76)
print(" 一、归属判定：哪块板？")
print("=" * 76)
KEYS = ["FT4232", "FT2232", "USB3320", "RTL8211", "W25Q256", "AD9363", "AD9361",
        "XC7Z010", "XC7Z020", "BALUN", "TCM1", "ADT1", "BALFHB", "JTX", "MABA",
        "2450BL", "HHM", "LPF", "BPF", "SAW"]
for fn in sorted(os.listdir(HW)):
    p = os.path.join(HW, fn)
    if not os.path.isfile(p):
        continue
    raw = open(p, "rb").read()
    txt = raw.decode("latin-1")
    # Altium SchDoc 里字符串有 UTF-16 也有 ASCII，两种都扫
    u16 = raw.decode("utf-16-le", "ignore")
    found = {}
    for k in KEYS:
        c = txt.count(k) + u16.count(k)
        if c:
            found[k] = c
    if found:
        print("  %-40s %s" % (fn, ", ".join("%s×%d" % (k, v) for k, v in sorted(found.items()))))

print()
print("=" * 76)
print(" 二、巴伦型号挖掘（08 BALUN.SchDoc）")
print("=" * 76)
p = os.path.join(HW, "08 BALUN.SchDoc")
raw = open(p, "rb").read()
print("  文件 %d 字节" % len(raw))

def strings_of(data, minlen=4):
    # ASCII 可打印串
    out = set()
    cur = []
    for b in data:
        if 32 <= b < 127:
            cur.append(chr(b))
        else:
            if len(cur) >= minlen:
                out.add("".join(cur))
            cur = []
    if len(cur) >= minlen:
        out.add("".join(cur))
    return out

s_ascii = strings_of(raw, 4)
s_u16 = strings_of(raw.decode("utf-16-le", "ignore").encode("latin-1", "ignore"), 4)

# 找像元件型号的串
pat = re.compile(r"^[A-Z][A-Z0-9]{1,7}[-+][0-9A-Z]{2,8}[A-Z0-9+]*$|"
                 r"^(TCM|ADT|BALFHB|JTX|MABA|HHM|DEA|LDB|RF|LPF|BPF|SYBP|BFCN)[-0-9A-Za-z+]*$")
print("\n  疑似巴伦型号（ASCII 层）:")
cand = sorted(x for x in s_ascii if pat.match(x))
for x in cand:
    print("    %s" % x)
if not cand:
    print("    (没找到)")

print("\n  含 BALUN/TCM/ADT/变压器 关键字的串:")
for x in sorted(s_ascii | s_u16):
    if re.search(r"BALUN|TCM|ADT1|ADT2|BALFHB|XFMR|TRANSFORM|JTX|MABA|HHM", x, re.I) and len(x) < 60:
        print("    %s" % x)

print("\n  所有像『位号+型号』的短串（前 60 个，看看有没有 L7/L8 的值）:")
short = sorted(x for x in s_ascii if 3 <= len(x) <= 22)
for x in short[:60]:
    print("    %s" % x)
