import io

P = r"E:\LDSDR_010\make_ttc_report.py"
t = io.open(P, encoding="utf-8").read()
lines = t.splitlines()

targets = [284, 319, 347, 363, 400, 408, 512]
fixed = 0
for ln in targets:
    if ln - 1 >= len(lines):
        continue
    s = lines[ln - 1]
    if s.count('"') <= 2:
        continue
    first = s.index('"')
    last = s.rindex('"')
    head = s[:first + 1]
    mid = s[first + 1:last].replace('"', "'")
    tail = s[last:]
    lines[ln - 1] = head + mid + tail
    fixed += 1

io.open(P, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
print("已修正 %d 行" % fixed)

# 验证
import ast
try:
    ast.parse(io.open(P, encoding="utf-8").read())
    print("语法 OK")
except SyntaxError as e:
    print("仍有语法错误 line %s: %s" % (e.lineno, e.text))
    # 再找一遍
    for i, ln in enumerate(io.open(P, encoding="utf-8").read().splitlines(), 1):
        s = ln.strip()
        if (s.startswith("P(") or s.startswith("B(")) and s.count('"') > 2:
            print("  %4d: %s" % (i, ln[:110]))
