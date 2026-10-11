# -*- coding: utf-8 -*-
"""谱牒健康度核对（只读，不改盘）—— 续谱/清理之后必跑一次。

核对项：
  人数 / 女性数 · **父子倒挂** · 悬空父/母引用 · 悬空配偶引用 ·
  孤立非史实女性 · **父/母边缺口**（存档有、谱里空） ·
  source.slot / merge_count · 关注人数

用法：
    python tools/verify_book.py [谱名]        # 默认 秦末起义
"""
import io
import json
import os
import sys

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


def main():
    path = os.path.join(ROOT, "saves", NAME, "family.json")
    d = json.load(open(path, encoding="utf-8"))
    p = d["people"]

    def y(s):
        try:
            return int(str(s).split(",")[0])
        except Exception:
            return None

    inv = 0
    for n, r in p.items():
        f = r.get("father") or ""
        if f and f in p:
            fb, rb = y(p[f].get("birth")), y(r.get("birth"))
            if fb is not None and rb is not None and rb < fb:
                inv += 1
    dang = sum(1 for r in p.values() for k in ("father", "mother")
               if str(r.get(k) or "") and str(r.get(k)) not in p)
    dsp = sum(1 for r in p.values() for s in (r.get("spouses") or [])
              if s not in p)

    kids, sps = {}, {}
    for n, r in p.items():
        for k in ("father", "mother"):
            v = str(r.get(k) or "").strip()
            if v:
                kids.setdefault(v, []).append(n)
        for s in (r.get("spouses") or []):
            if s:
                sps.setdefault(s, []).append(n)
    lone = 0        # 真孤儿：非史实女性且一条边都没有
    rootfem = 0     # ★ 无父无母 **且没挂靠** ⇒ 画布上会被当「根节点」画成孤立节点
    for n, r in p.items():
        if str(r.get("gender") or "") != "女" or r.get("historical") == "是":
            continue
        if str(r.get("father") or "") in p or str(r.get("mother") or "") in p:
            continue
        # ★ 2026-10-06 母系家主（女君主+入赘，如韩淑）**本就要当根** —— 她自立
        #   门户、孩子姓随她（判据同 `app/layout._uzheng_family`），不是「该挂靠
        #   却没挂」的孤立女性。`attach_lone_wives` 也已豁免她。
        _fam = str(n)[:1]
        if any(str(_k)[:1] == _fam
               and str((p.get(_k) or {}).get("father") or "")[:1] != _fam
               for _k in kids.get(n, ())):
            continue
        if not r.get("associate_of"):
            rootfem += 1
        if any(s in p for s in (r.get("spouses") or [])):
            continue
        if kids.get(n) or sps.get(n):
            continue
        lone += 1

    # ★ 2026-10-07 新增：**父/母边缺口**哨兵 —— 「存档记了父/母、父母在谱内、
    #   谱里该边却是空」应为 **0**。宋珩（存档父=宋太皇，谱里父=''）就是这一类：
    #   边没带进谱 ⇒ 他被当「无父无母」跳过自动关注、又被列进可删名单。
    #   判据只写一份，见 tools/save_parents.py（prune_nonkin 的删除闸共用它）。
    slot = SP.slot_dir(NAME)
    gap = []
    if not slot:
        slot_note = "取不到实录槽（未绑 / 本机无缓存）"
    else:
        slot_note = os.path.basename(slot)
        try:
            gap = SP.parent_gaps(p, SP.load_index(slot))
        except Exception as e:
            slot_note += "（读槽失败：%s）" % e

    print("谱牒 %s" % NAME)
    print("  人数 %d · 女性 %d"
          % (len(p), sum(1 for r in p.values()
                         if str(r.get("gender") or "") == "女")))
    print("  倒挂 %d · 悬空父/母 %d · 悬空配偶 %d · 真孤儿 %d · 会成根的非史女性 %d"
          % (inv, dang, dsp, lone, rootfem))
    print("  父/母边缺口 %d（存档有父/母、父母在谱、谱里边空）—— 槽 %s"
          % (len(gap), slot_note))
    for n, side, pc, pn, tgt in gap[:12]:
        print("      %s 的%s：存档=(%s,%s) → 应连谱内「%s」"
              % (n, "父" if side == "father" else "母", pc or "-", pn or "-", tgt))
    if len(gap) > 12:
        print("      …还有 %d 人" % (len(gap) - 12))
    print("  source.slot %s · merge_count %s · 关注 %d"
          % ((d.get("source") or {}).get("slot"),
             (d.get("source") or {}).get("merge_count"),
             len(d.get("focused_people") or [])))
    print("  （前三项、「真孤儿」、「会成根的非史女性」与「父/母边缺口」都应为 0；"
          "后两者分别由 tools/attach_lone_wives.py、tools/import_from_game.py 处理）")


if __name__ == "__main__":
    main()
