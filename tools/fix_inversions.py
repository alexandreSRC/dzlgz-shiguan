# -*- coding: utf-8 -*-
"""谱牒「父子倒挂」清理（宁缺勿猜，不编数字）。

判据：凡「子生年 < 父生年」且父在谱内的边 → 清掉**子**的生年、
      note 追加「生年存疑」。**绝不改动父方，也不编造新数字**。
性质：几乎全是游戏给随机人物（匈奴/西域/辰韩等）编的生年自相矛盾，
      实测 97% 只差 1~5 年；极少数（如《秦末起义》匡繇差 70 年）是游戏自己
      认的父子，一并清子方生年。

⚠️ **续谱（merge）会把生年从新档重新同步回来 ⇒ 倒挂必然复发**
   （实测：清完 0，续谱后又回 124 处）。所以**每次续谱之后都要重跑本脚本**。

用法：
    python tools/fix_inversions.py [谱名]            # 演习（默认 全史存档）
    python tools/fix_inversions.py [谱名] --apply    # 真写（先备份 family.json.bak_*）
"""
import io
import json
import os
import shutil
import sys
import time

try:
    if getattr(sys.stdout, "buffer", None) is not None:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                      errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOK_NAME = [a for a in sys.argv[1:] if not a.startswith("-")]
BOOK = os.path.join(ROOT, "saves",
                    (BOOK_NAME[0] if BOOK_NAME else "全史存档"), "family.json")

# 历史上确认为「疑似同名错接」的边（额外标「父链存疑」，仍不乱指父）——
# 只对老档《全史存档》有意义，其它谱留空即可。
SUSPECT = {("姬录", "姬胡2"), ("姬彖", "姬士2"), ("姬凌", "姬封2")}


def year(s):
    try:
        return int(str(s).split(",")[0])
    except Exception:
        return None


def scan(people):
    out = []
    for n, r in people.items():
        f = r.get("father") or ""
        if not f or f not in people:
            continue
        fb, rb = year(people[f].get("birth")), year(r.get("birth"))
        if fb is not None and rb is not None and rb < fb:
            out.append((n, f, rb, fb, (n, f) in SUSPECT))
    out.sort()
    return out


def main():
    apply = "--apply" in sys.argv
    d = json.load(open(BOOK, encoding="utf-8"))
    p = d["people"]
    pairs = scan(p)
    print("%s 父子倒挂 %d 处：" % (os.path.basename(os.path.dirname(BOOK)), len(pairs)))
    for n, f, rb, fb, sus in pairs:
        print("   %-10s 生%+d ← 父 %-10s 生%+d   %s"
              % (n, rb, f, fb, "父链存疑" if sus else "生年存疑"))
    if not apply:
        print("\n这是**演习**。确认后加 --apply。")
        return
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = BOOK + ".bak_" + ts
    shutil.copy2(BOOK, bak)
    for n, f, _rb, _fb, sus in pairs:
        r = p[n]
        r["birth"] = ""
        note = (r.get("note") or "").strip()
        suffix = "父链存疑" if sus else "生年存疑"
        r["note"] = (note + "；" + suffix) if note else suffix
    with open(BOOK, "w", encoding="utf-8") as fp:
        json.dump(d, fp, ensure_ascii=False, indent=1)
    print("\n已写回，备份：%s" % bak)
    left = len(scan(json.load(open(BOOK, encoding="utf-8"))["people"]))
    print("复核：剩余倒挂 %d 处" % left)


if __name__ == "__main__":
    main()
