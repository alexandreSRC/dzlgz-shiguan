# -*- coding: utf-8 -*-
"""把「孤立的非史实女性」挂靠到丈夫名下（★ 2026-10-03 使用者裁定）。

问题（实测）：非史实女性里有一批**在谱内没有父、也没有母** —— 她们是谱内某人的
**妻子 / 母亲**，但 `app/layout.py:158-162` 把「无父无母」的人一律当**根节点**，
于是她们在画布上各自画成一个**独立的孤立根节点**（只有一条夫妻 U 线牵到丈夫）。
一本谱实测 246 人（另有 1 个真孤儿）。

根因：画布唯一那道「别当根」的闸门只认 **`associate_of`**
（`layout.py:176-177` 可见性、`layout.py:388-393` 不入 roots），
而抽取/续谱**从来不写**这个字段 —— 只有界面手工「添加同代人(配偶)」才写
（`app/dialogs/forms.py:443-449`：`spouses=[丈夫]` + `associate_of=丈夫`
+ `associate_type="spouse"`）。本工具就是把这条既有约定**批量补上**。

做法（不删人、不动夫妻/母子关系，只加三个字段）：
  · `associate_of`   = 锚点（丈夫）
  · `associate_type` = "spouse"
  · `associate_rank` = 她在**丈夫那份 `spouses` 列表里的位次**（1、2、3…）
    ⇒ 同一个丈夫挂多个妻子时，画布按这个位次从左到右排
       （`layout.py:505` 就是 `sort(key=associate_rank)`）。
       **配偶边实测 100% 双向**，所以「她的丈夫」与「丈夫的妻子表」总能对上。

锚点怎么选（一个女人有多个丈夫时，实测 21 人 2 个、2 人 3 个）：
  ① 若她谱内子女的**父亲唯一**、且那人是她配偶 ⇒ 用他（她会挨着自己那支子女）；
  ② 否则取「男方把她排得最靠前」的那个丈夫（她在某人表里是正妻）；
  ③ 再不然按名字定序（保证结果稳定，不随字典顺序变）。

用法：
    python tools/attach_lone_wives.py [谱名]                      # 演习（默认 秦末起义）
    python tools/attach_lone_wives.py [谱名] --apply              # 真写（先备份）
    python tools/attach_lone_wives.py [谱名] --apply --drop-orphans
        # 连**真孤儿**（非史实女性·一条边都没有）一起删掉。使用者 2026-10-03 用过一次
        # （删「韩音」）；默认**不删**，因为「被关注的光杆」可能是他有意留的。

⚠️ 续谱不会自动补这个字段 ⇒ **每次续谱后重跑一次**（同 `fix_inversions.py`）。
⚠️ 史馆开着时不要写盘。
"""
import argparse
import io
import json
import os
import shutil
import sys
import time
from collections import defaultdict

try:
    if getattr(sys.stdout, "buffer", None) is not None:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                      errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def female(r):
    return str((r or {}).get("gender") or "") == "女"


def is_hist(r):
    return (r or {}).get("historical") == "是"


def build_index(people):
    """→ (母/父 → 子女, 被记为配偶者 → [本人])"""
    kids, sp_ref = defaultdict(list), defaultdict(list)
    for n, r in people.items():
        for k in ("father", "mother"):
            v = str((r or {}).get(k) or "").strip()
            if v:
                kids[v].append(n)
        for s in ((r or {}).get("spouses") or []):
            if s:
                sp_ref[s].append(n)
    return kids, sp_ref


def pick_anchor(name, people, kids):
    """选锚点（丈夫）；取不到返回 ""。规则见模块头。"""
    sps = [s for s in ((people[name] or {}).get("spouses") or []) if s in people]
    if not sps:
        return ""
    faths = {str((people[k] or {}).get("father") or "") for k in kids.get(name, [])}
    faths = {f for f in faths if f and f in people and f in sps}
    if len(faths) == 1:
        return next(iter(faths))

    def his_rank(s):
        lst = (people[s] or {}).get("spouses") or []
        return (lst.index(name) if name in lst else 999, s)

    return sorted(sps, key=his_rank)[0]


def collect(people):
    """→ (待挂靠 [名], 真孤儿 [名])"""
    kids, sp_ref = build_index(people)
    attach, orphans = [], []
    for n, r in people.items():
        if not female(r) or is_hist(r):
            continue
        if str((r or {}).get("father") or "") in people:
            continue
        if str((r or {}).get("mother") or "") in people:
            continue
        if (r or {}).get("associate_of"):
            continue                      # 已挂靠过，别覆盖
        # ★ 2026-10-06 母系家主（女君主+入赘，如韩淑）**不挂丈夫** —— 她自立
        #   门户、孩子姓随她（见 `app/layout._uzheng_family`）；把她挂到丈夫名
        #   下会拆散整个入赘家庭（使用者报「家谱绘制大乱」的那一例）。
        fam = str(n)[:1]
        if any(str(k)[:1] == fam
               and str((people.get(k) or {}).get("father") or "")[:1] != fam
               for k in kids.get(n, ())):
            continue
        sps = [s for s in ((r or {}).get("spouses") or []) if s in people]
        if sps or kids.get(n) or sp_ref.get(n):
            attach.append(n)
        else:
            orphans.append(n)
    return attach, orphans


def main():
    ap = argparse.ArgumentParser(description="把孤立的非史实女性挂靠到丈夫名下")
    ap.add_argument("book", nargs="?", default="秦末起义", help="谱牒名")
    ap.add_argument("--apply", action="store_true", help="真写（不加=演习）")
    ap.add_argument("--drop-orphans", action="store_true",
                    help="连真孤儿（一条边都没有的非史实女性）一起删掉")
    a = ap.parse_args()

    path = os.path.join(ROOT, "saves", a.book, "family.json")
    d = json.load(open(path, encoding="utf-8"))
    p = d["people"]
    kids, _ = build_index(p)

    attach, orphans = collect(p)
    plan, n_nosp = [], 0
    for n in attach:
        anc = pick_anchor(n, p, kids)
        if not anc:
            n_nosp += 1
            continue
        lst = (p[anc] or {}).get("spouses") or []
        plan.append((n, anc, lst.index(n) + 1 if n in lst else 999))
    plan.sort(key=lambda x: (x[1], x[2], x[0]))

    anchors = defaultdict(list)
    for n, anc, rk in plan:
        anchors[anc].append(n)

    print("谱牒 %s：%d 人" % (a.book, len(p)))
    print("  待挂靠的非史实女性 %d 人（无父无母、有夫/有子女）" % len(plan))
    print("    落在 %d 个锚点（丈夫）上" % len(anchors))
    if n_nosp:
        print("    !! 其中 %d 人选不出锚点（配偶都不在谱内），跳过" % n_nosp)
    top = sorted(anchors.items(), key=lambda kv: -len(kv[1]))[:5]
    for h, ws in top:
        print("    %-10s 挂 %d 人：%s" % (h, len(ws), "、".join(ws[:9])))
    print("  真孤儿（一条边都没有的非史实女性）%d 人：%s"
          % (len(orphans), "、".join(orphans) or "无"))
    if orphans and not a.drop_orphans:
        print("    （默认不动它们；要删加 --drop-orphans）")
    multi = [n for n in attach
             if len([s for s in ((p[n] or {}).get("spouses") or [])
                     if s in p]) > 1]
    print("  其中「多夫」者 %d 人（锚点按『子女之父→男方排位→名字』定序）"
          % len(multi))

    if not a.apply:
        print("\n这是**演习**。确认后加 --apply。")
        return

    ts = time.strftime("%Y%m%d_%H%M%S")
    shutil.copy2(path, path + ".bak_" + ts)
    for n, anc, rk in plan:
        p[n]["associate_of"] = anc
        p[n]["associate_type"] = "spouse"
        p[n]["associate_rank"] = rk
    dropped = []
    if a.drop_orphans and orphans:
        dropped = list(orphans)
        for n in dropped:
            p.pop(n, None)
        for n, r in p.items():                      # 清悬空引用
            for k in ("father", "mother"):
                if str((r or {}).get(k) or "") == "":
                    continue
                if str(r[k]) not in p:
                    r[k] = ""
            sp = [s for s in ((r or {}).get("spouses") or []) if s in p]
            if len(sp) != len((r or {}).get("spouses") or []):
                r["spouses"] = sp
        if d.get("focused_people"):
            d["focused_people"] = [n for n in d["focused_people"] if n in p]
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(d, fp, ensure_ascii=False, indent=1)
    print("\n已写回（备份 family.json.bak_%s）" % ts)
    print("  挂靠 %d 人；删除真孤儿 %d 人 %s"
          % (len(plan), len(dropped), "、".join(dropped) if dropped else ""))


if __name__ == "__main__":
    main()
