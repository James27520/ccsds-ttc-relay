import ast
import io

P = r"E:\LDSDR_010\make_ttc_report.py"


def try_parse():
    try:
        ast.parse(io.open(P, encoding="utf-8").read())
        return None
    except SyntaxError as e:
        return e


for it in range(60):
    err = try_parse()
    if err is None:
        print("语法 OK（迭代 %d 次）" % it)
        break
    lines = io.open(P, encoding="utf-8").read().splitlines()
    ln = err.lineno
    # 从报错行往前找语句起点（以 P( / B( / TABLE( / CODE( 开头的行）
    start = None
    for k in range(ln - 1, max(-1, ln - 30), -1):
        s = lines[k].strip()
        if s.startswith(("P(", "B(", "CODE(", "H(", "TABLE(")):
            start = k
            break
    if start is None:
        print("找不到语句起点 @%d: %s" % (ln, err.text))
        break
    # 找到语句结束行（引号数量为偶数的行）
    end = start
    for k in range(start, min(len(lines), start + 30)):
        if lines[k].count('"') % 2 == 0 and lines[k].count('"') > 0:
            end = k
            break
    # 把 start..end 之间的内部引号替换掉：保留每行的第一个和最后一个引号
    changed = 0
    for k in range(start, end + 1):
        s = lines[k]
        if s.count('"') >= 2:
            f = s.index('"')
            l = s.rindex('"')
            if l > f:
                mid = s[f + 1:l].replace('"', "'")
                lines[k] = s[:f + 1] + mid + s[l:]
                changed += 1
    if changed == 0:
        print("无法修正 @%d" % ln)
        break
    io.open(P, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
    print("  迭代 %d: 修正 %d..%d 共 %d 行" % (it, start + 1, end + 1, changed))

err = try_parse()
if err:
    print("结束仍有错误 line %s: %s" % (err.lineno, err.text))
else:
    print("最终语法 OK")
