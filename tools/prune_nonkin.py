# -*- coding: utf-8 -*-
"""按「入谱口径」清理**旧谱**：删掉不该在谱里的非史实人物（★ 2026-10-03 定案）。

口径（使用者原话）：
    「非史实人物只有是史实人物后裔、或者被我关注的人物的后裔才入谱」＋「不要亲家」

判据：
  1. 种子 = 全部**史实** ∪ **关注名单**（`focused_people`，不是续谱名单 `source.watch`）。
  2. **只沿「父」边下走**本支（纯父系；女儿作为叶子收下，但**不往下牵**）。
  3. 再**补入**（且**不再从它们外延**）：已保留者的**母亲**、已保留**男性**的**配偶**。
  4. ⇒ 岳父、女婿、外甥等**亲家一概不进**。

★ 2026-10-07 新增**删除闸**（使用者：「这样的情况，你要加规则核实」）：
  判某人「可删」之前，**回存档原文核一遍 `Parent`**（`tools/save_parents.py`，
  与体检 `verify_book.py` 共用同一份判据）：
    · 存档记了**真父母**（非「媵妾」占位、非假祖先壳）、且该父母**在保留集里**
      ⇒ 这人不是外人，是**父/母边没带进谱**（宋珩：存档父=宋太皇，谱里父=''）
      ⇒ **一律不许删**，转列「⚠ 待补父边」，提示先回填。
    · 存/取不到槽、或存在上述缺口 ⇒ **拒绝 --apply**（核实不了就不删）。
  ★ 同日使用者裁定（问「父母本身是非史实路人、不在谱的，留不留」）：
    「**这种一律不入谱，除非我加了关注**」—— 即：父母**不在谱**的（无论真父母
    还是假祖先壳）一律照删；他手动关注的会落进种子集 `focused_people` 自然保留。

⚠️ 抽取端（`tools/import_from_game.py` 的 2b 步）用同一套判据；
   **两端必须一致**，否则续谱时谱内重名组与新抽对不上 →「待人工确认」暴涨。
   本脚本用于**清存量**旧谱；新抽端由 import_from_game 负责。
⚠️ 史馆开着时不要写盘（会像七十一批那样被关窗口覆盖）。

用法：
    python tools/prune_nonkin.py [谱名]            # 演习（默认 秦末起义）
    python tools/prune_nonkin.py [谱名] --apply    # 真写（先备份 family.json.bak_*）
"""
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
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tools import save_parents as SP          # noqa: E402

NAME = [a for a in sys.argv[1:] if not a.startswith("-")]
NAME = NAME[0] if NAME else "秦末起义"
BOOK = os.path.join(ROOT, "saves", NAME, "family.json")


def compute_keep(p, seeds):
    """返回 (保留集, 父系本支人数, 补家人数)。"""
    kids = defaultdict(list)                 # 父 → 子（只认父亲边）
    for n, r in p.items():
        f = str(r.get("father") or "").strip()
        if f and f in p and f != n:
            kids[f].append(n)
    keep, st = set(), list(seeds)
    while st:
        x = st.pop()
        if x in keep:
            continue
        keep.add(x)
        st.extend(kids.get(x, ()))
    n_spine = len(keep)
    add = set()                              # 补家人（母亲 / 男性的配偶），不外延
    for n in keep:
        m = str(p[n].get("mother") or "").strip()
        if m in p:
            add.add(m)
        if p[n].get("gender") != "女":
            for s in (p[n].get("spouses") or []):
                if s in p and s != n:
                    add.add(s)
    keep |= add
    return keep, n_spine, len(add)


def main():
    apply = "--apply" in sys.argv
    d = json.load(open(BOOK, encoding="utf-8"))
    p = d["people"]
    foc = [n for n in (d.get("focused_people") or []) if n in p]
    hist = [n for n, r in p.items() if r.get("historical") == "是"]
    seeds = list(dict.fromkeys(hist + foc))

    keep, n_spine, n_add = compute_keep(p, seeds)
    gone = [n for n in p if n not in keep]

    # ---- 删除闸：回存档核 Parent（判据见 tools/save_parents.py）-----------
    slot = SP.slot_dir(NAME)
    idx, slot_note = {}, "取不到实录槽（未绑 / 本机无缓存）"
    if slot:
        slot_note = os.path.basename(slot)
        try:
            idx = SP.load_index(slot)
        except Exception as e:
            slot_note += "（读槽失败：%s）" % e
    gaps = SP.parent_gaps(p, idx, keep=keep) if idx else []
    gone_set = set(gone)
    protect = [g for g in gaps if g[0] in gone_set]      # 父/母在保留集 ⇒ 该留

    # ★ 2026-10-07 新增**断后闸**：某人在**保留集里还有子女**指着他当父/母 ⇒ 不删。
    #   缘起（一百二十八批）：删掉 挛鞮图力古尔 / 韩平 / 金泳庆 后，他们那 5 个
    #   **在关注名单里**的女儿（挛鞮索隆高娃 / 挛鞮乌兰娜仁 / 挛鞮格日乐 /
    #   韩椒2 / 金静那）**父边一断就成了无父的孤立根节点**（体检：真孤儿 2→5、
    #   会成根的非史女性 6→8）。这 3 位父亲本身「非史实、父母不在谱」，
    #   按口径确实不该**关注**（自动关注也确实跳过了他们），但他们是**保留集里
    #   那些人的父亲** —— 删了他，孩子就成了孤儿 ⇒ 留作家族结构的锚点，不关注。
    keep_children = set()
    for _n, _r in p.items():
        if _n not in keep:
            continue
        for _k in ("father", "mother"):
            _v = str(_r.get(_k) or "")
            if _v:
                keep_children.add(_v)
    hold = sorted(n for n in gone if n in keep_children and n not in {g[0] for g in protect})

    prot_names = {g[0] for g in protect} | set(hold)
    deletable = [n for n in gone if n not in prot_names]
    # 另有真父母、但父母**不在谱**的 —— 仍按口径可删，只是单独报出来给人过目
    loose = []
    if idx:
        for n in deletable:
            if any((pc or pn) and not tgt
                   for _s, pc, pn, tgt in SP.resolve(p[n], idx, p)):
                loose.append(n)

    print("谱牒 %s：总 %d · 史实 %d · 关注(在谱内) %d"
          % (NAME, len(p), len(hist), len(foc)))
    print("  父系本支 %d + 补家人 %d = 保留 %d（非史实 %d）"
          % (n_spine, n_add, len(keep),
             sum(1 for n in keep if p[n].get("historical") != "是")))
    print("  删除 %d（史实 %d，应为 0）"
          % (len(deletable), sum(1 for n in deletable
                                 if p[n].get("historical") == "是")))
    if deletable:
        print("  删除样例：", "、".join(deletable[:16]))
    if protect:
        print("\n⚠ 待补父边（**不删**）%d 人 —— 存档父母在谱内、谱里该边却是空"
              "（宋珩那一类，边没带进谱）：" % len(protect))
        for n, side, pc, pn, tgt in protect[:20]:
            print("    %s 的%s：存档=(%s,%s) → 应连谱内「%s」"
                  % (n, "父" if side == "father" else "母",
                     pc or "-", pn or "-", tgt))
        if len(protect) > 20:
            print("    …还有 %d 人" % (len(protect) - 20))
    if hold:
        print("\n◆ 留作家族结构（**不删**；仍不关注）%d 人 —— 保留集里还有人"
              "指着他们当父/母，删了他们就成了没爹的孤立根：" % len(hold))
        print("    " + "、".join(hold[:20]) + ("…" if len(hold) > 20 else ""))
    if loose:
        print("  （另有 %d 人存档记了真父母、但父母**不在谱** ⇒ 按口径"
              "**一律不入谱**，除非已关注：%s%s）"
              % (len(loose), "、".join(loose[:12]), "…" if len(loose) > 12 else ""))
    print("  核实源：%s" % slot_note)

    if not apply:
        print("\n这是**演习**。确认后加 --apply。")
        return
    if not idx:
        print("\n→ **拒绝写盘**：核实不了存档（%s）。核实通过再删。" % slot_note)
        return
    if protect:
        print("\n→ **拒绝写盘**：存在 %d 人父/母边缺口（上面「待补父边」）。"
              "先跑「续谱 / 刷新体检」把父边补上，再回来清。" % len(protect))
        return
    if not deletable:
        print("\n没有要删的 —— 谱牒已经符合口径。")
        return

    ts = time.strftime("%Y%m%d_%H%M%S")
    shutil.copy2(BOOK, BOOK + ".bak_" + ts)
    for n in deletable:
        p.pop(n, None)
    fixed = 0
    for n, r in p.items():                   # 清悬空引用
        sp = [s for s in (r.get("spouses") or []) if s in p]
        if len(sp) != len(r.get("spouses") or []):
            r["spouses"] = sp
            fixed += 1
        for k in ("father", "mother"):
            v = str(r.get(k) or "")
            if v and v not in p:
                r[k] = ""
                fixed += 1
    nf = len(d.get("focused_people") or [])
    d["focused_people"] = [n for n in (d.get("focused_people") or []) if n in p]
    with open(BOOK, "w", encoding="utf-8") as fp:
        json.dump(d, fp, ensure_ascii=False, indent=1)
    print("\n已删 %d 人（备份 family.json.bak_%s）" % (len(deletable), ts))
    print("  清悬空引用 %d 条 · 关注名单 %d → %d"
          % (fixed, nf, len(d["focused_people"])))


if __name__ == "__main__":
    main()
