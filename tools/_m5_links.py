# -*- coding: utf-8 -*-
"""验收 · 父链与年份完整性（_m5）。

三件事，只读、不写存档、不碰 config：

  1. **按名回捞错接**（必须 0）：实录里这个人引用的**父编号**不在本谱内，
     却被接成了同名的另一个人 —— 2026-10-02 修的 `import_from_game.resolve_parent`
     就是这个坑（姬结→姬宁 2406、姬宋→姬午 2036…）。判据：实录父编号 C 不在谱内，
     而谱内 father 字段 = 那个编号在实录里的名字。
  2. **父子年代倒挂**：儿子生年早于父亲。清单只作**提示** —— 已实测一类是
     **游戏数据自身矛盾**（父的子女数组里有这个儿子，如匡繇/匡文），不是链错。
  3. **大数年**（必须 0）：生/卒年的年份部分超过 5 位 —— 早期入库把「年,月,日」
     压成 `年*10000+月*100+日` 的遗留（2026-10-02 已还原 8 处）。
     判据：`|年| >= 100000`。

用法：
    python tools/_m5_links.py                # 全部谱牒
    python tools/_m5_links.py 秦末起义        # 只查指定谱牒

报告自己写文件（UTF-8）：`_stats/_m5_links.txt`。
退出码：错接 > 0 或 大数年 > 0 → 1；否则 0。
"""
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAVES = os.path.join(ROOT, "saves")
PERSON_TABLES = ("Save_Ren_Data", "Save_Dead_Ren_Data", "Save_Chu_Sheng_Data",
                 "Save_ED_Ren_Data", "Save_Female_Ren_Data", "Save_Birth_Ren_Data")
LOG = []


def say(s=""):
    print(s)
    LOG.append(str(s))


def year(s):
    try:
        return int(str(s).split(",")[0])
    except Exception:
        return None


def father_ref(rec):
    """实录记录里这个人引用的父：返回 (编号, 名字)。"""
    fc = str(rec.get("Father_Code") or "").strip()
    fn = str(rec.get("Father_Name") or "").strip()
    if fc and fc != "-1":
        return fc, fn
    par = (rec.get("Parent") or {}).get("Father") or {}
    return str(par.get("Ren_Code") or "").strip(), str(par.get("Ren_Name") or "").strip()


def slot_people(path):
    sys.path.insert(0, ROOT)
    from app.saveload import SaveSlot
    slot = SaveSlot(path).load()
    idx = {}
    for tn in PERSON_TABLES:
        t = slot.table(tn)
        if not t:
            continue
        for row in t.rows:
            c = str(row.get("Ren_Code") or "").strip()
            if c and c not in idx:
                idx[c] = row
    return idx


def check(book_name):
    p = os.path.join(SAVES, book_name, "family.json")
    if not os.path.isfile(p):
        return 0, 0, 0
    d = json.load(open(p, encoding="utf-8"))
    people = d.get("people", {})
    code2name = {r.get("code"): n for n, r in people.items() if r.get("code")}
    say("\n########## %s（%d 人）" % (book_name, len(people)))

    # ---- 3. 大数年 ----
    big = []
    for n, r in people.items():
        for k in ("birth", "death"):
            y = year(r.get(k))
            if y is not None and abs(y) >= 100000:
                big.append((n, k, r.get(k)))
    say("  3 大数年：%d 处 %s" % (len(big), big[:6] if big else ""))

    # ---- 2. 倒挂 ----
    inv = []
    for n, r in people.items():
        f = r.get("father") or ""
        if not f or f not in people:
            continue
        fb, rb = year(people[f].get("birth")), year(r.get("birth"))
        if fb is not None and rb is not None and rb < fb:
            inv.append((rb - fb, n, rb, f, fb))
    inv.sort()
    say("  2 父子年代倒挂：%d 处" % len(inv))
    for gap, n, rb, f, fb in inv:
        say("      %-8s 生%+d ← 父 %-8s 生%+d（早 %d 年）" % (n, rb, f, fb, -gap))

    # ---- 1. 按名回捞错接 ----
    sp = (d.get("source") or {}).get("slot_path") or ""
    if not sp or not os.path.isdir(sp):
        say("  1 按名回捞错接：跳过（本机没有对应实录槽）")
        return 0, len(inv), len(big)
    idx = slot_people(sp)
    bad = []
    for n, r in people.items():
        c = r.get("code")
        rec = idx.get(str(c)) if c else None
        if not rec:
            continue
        fc, fn = father_ref(rec)
        if not fc or fc in code2name:
            continue
        linked = r.get("father") or ""
        if linked and linked == fn:
            bad.append((n, fc, fn, people.get(linked, {}).get("code")))
    say("  1 按名回捞错接：%d 处" % len(bad))
    for n, fc, fn, lc in bad:
        say("      %-8s 实录父=%s(%s) → 谱内接到同名 %s(%s)" % (n, fc, fn, fn, lc))
    return len(bad), len(inv), len(big)


def main():
    want = [a for a in sys.argv[1:] if not a.startswith("-")]
    say("=" * 62)
    say("验收 · 父链与年份完整性（_m5）  %s" % os.path.basename(ROOT))
    say("=" * 62)
    tot_bad = tot_big = 0
    books = want or sorted(os.listdir(SAVES))
    for b in books:
        if not os.path.isdir(os.path.join(SAVES, b)):
            continue
        bad, inv, big = check(b)
        tot_bad += bad
        tot_big += big
    say("\n" + "=" * 62)
    say("总结：按名回捞错接 %d 处 · 大数年 %d 处 · FAILS %d"
        % (tot_bad, tot_big, tot_bad + tot_big))
    say("（父子年代倒挂只作提示，需逐条结论）")

    out = os.path.join(ROOT, "_stats", "_m5_links.txt")
    try:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write("\n".join(LOG))
        print("报告已写：%s" % out)
    except Exception as e:
        print("报告写入失败：%r" % (e,))
    sys.exit(1 if (tot_bad + tot_big) else 0)


if __name__ == "__main__":
    main()
