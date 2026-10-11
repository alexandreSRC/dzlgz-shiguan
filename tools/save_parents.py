# -*- coding: utf-8 -*-
"""存档「父母」原文索引 —— 给**谱牒体检**与**删除闸**共用的一份判据。

为什么单列一份：两个工具都要回答同一个问题 ——
「**这个人存档里记了父母没有？记的是谁？**」
  · `tools/verify_book.py` —— 体检哨兵：报「存档有父/母、父母在谱、谱里边却空」；
  · `tools/prune_nonkin.py` —— 删除闸：判某人「可删」之前回原文核一遍，
    有真父母在谱内 ⇒ **一律不许删**（宋珩就是这么差点被删的：存档
    `Parent.Father = (宋太皇, 100000000)`，谱里却是空父）。
两处各写一份必然漂移，所以只写这一份（惯例同 `tools/import_from_game.py`）。

判据（与导入端 `import_from_game.resolve_parent` / `_is_ph` **同口径**）：
  · 取人物表（活人/已故/女性/出生/旧人物）的 `Parent.Father / Parent.Mother`
    = `{Ren_Code, Ren_Name}`；**并**取族谱表 `Jia_Zu_Genealogy_*` 的
    `Father_Code/Name`、`Mother_Code/Name` —— 两边互补取并集。
    实测（Save_All_102）「刘雯 / 姚秋 / 姚萋」**只**出现在族谱表里，
    光读人物表会把她们当「查无此人」。
  · **占位不算父母**：
      - 名字属 `app.relations.PLACEHOLDER_NAMES`（"媵妾" / "无名" / "不详"）；
      - 编号带 父/祖/曾/高 后缀、且表里查无此人或该记录缺 `Ren_Sex`
        （游戏为凑显示世代凭空造的假祖先，如 `100005184父` = 金泳庆的假父亲）。
  · 编号非空（且 != `-1`）⇒ **只认编号**，认不出就是「不在谱」；
    编号缺失时才允许按名回捞 —— 与导入端一致，防「按名接错人」。

⚠️ **纯读**：只读 json，不载槽（不用 `SaveSlot`）、不写盘。
"""
import glob
import json
import os
import re

try:
    from app.contract import RECORD_BASES
except Exception:                     # 兜底：只在本机缓存里找
    RECORD_BASES = [r"__SHIGUAN_CACHE__", r"__SHIGUAN_CACHE_ROOT__"]

try:
    from app.relations import PLACEHOLDER_NAMES
except Exception:
    PLACEHOLDER_NAMES = {"媵妾", "无名", "不详", "", None}

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 与 import_from_game 的人物表同口径（族谱表单列，见下）
PERSON_FILES = ("Save_Ren_Data_*.json", "Save_Dead_Ren_Data_*.json",
                "Save_Woman_Data_*.json", "Save_Chu_Sheng_Data*.json",
                "Save_ED_Ren_Data*.json")
GEN_FILE = "Jia_Zu_Genealogy_*.json"

PH_SUFFIX = re.compile(r"(父|祖|曾|高)$")


def book_path(book):
    return os.path.join(ROOT, "saves", book, "family.json")


def slot_dir(book):
    """谱名 → 该谱绑定的**本机实录槽目录**；取不到返回 ""（不硬猜）。

    口径同 `main._slot_for_save` 的 ①：先认 `source.slot_path`（绝对路径），
    再认 `source.slot`（槽名，到 `RECORD_BASES` 里找同名目录）。
    """
    try:
        with open(book_path(book), encoding="utf-8") as f:
            src = (json.load(f).get("source") or {})
    except Exception:
        return ""
    for key in ("slot_path", "slot"):
        v = str(src.get(key) or "").strip()
        if not v:
            continue
        if os.path.isdir(v):
            return v
        for base in RECORD_BASES:
            cand = os.path.join(base, os.path.basename(v))
            if os.path.isdir(cand):
                return cand
    return ""


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _clean(code, name, by_code):
    """(编号, 名) → 真父母则返回 `(编号, 名)`，占位 / 空返回 `None`。"""
    c = str(code or "").strip()
    n = str(name or "").strip()
    if n in PLACEHOLDER_NAMES:               # "媵妾" 这类占位名
        return None
    if c and c != "-1":
        if PH_SUFFIX.search(c):              # 带 父/祖/曾/高 ⇒ 查是不是假祖先壳
            r = by_code.get(c)
            if r is None or "Ren_Sex" not in r:
                return None
        return (c, n)
    if c in ("", "-1") and n:                # 无编号、有名（真名）⇒ 只留名
        return ("", n)
    return None                              # 编号空 + 名空 / 名占位


def load_index(src):
    """槽目录 → `{code: {"father": (编号, 名), "mother": (编号, 名)}}`。

    占位父母已剔掉（值可能是 `None`；两边都空的人**不进表**）。
    `code` 用**存档原文编号**（字符串），与谱内 `code` 字段对得上。
    """
    if not src or not os.path.isdir(src):
        return {}
    by_code = {}                             # 只为判「带后缀的编号是不是假人」
    for pat in PERSON_FILES + (GEN_FILE,):
        for f in sorted(glob.glob(os.path.join(src, pat))):
            o = _read_json(f)
            if o is None:
                continue
            if not isinstance(o, list):
                o = [o]
            for g in o:
                if not isinstance(g, dict):
                    continue
                items = (g.get("Genealogy_Ren_Record_Array")
                         if "Genealogy_Ren_Record_Array" in g else None)
                if items is None:
                    items = [g]
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    c = str(it.get("Ren_Code") or "").strip()
                    if c and c not in by_code:
                        by_code[c] = it

    out = {}
    for c, r in by_code.items():
        par = r.get("Parent") or {}
        pf, pm = par.get("Father") or {}, par.get("Mother") or {}
        # 人物表的 Parent 优先；族谱表的 Father_Code/Name 只在前面没给时补
        f = _clean(pf.get("Ren_Code") or r.get("Father_Code"),
                   pf.get("Ren_Name") or r.get("Father_Name"), by_code)
        m = _clean(pm.get("Ren_Code") or r.get("Mother_Code"),
                   pm.get("Ren_Name") or r.get("Mother_Name"), by_code)
        if f or m:
            out[c] = {"father": f, "mother": m}
    return out


def _target(pc, pn, people, book_by_code):
    """存档里的父母 → **谱内应连的人名**（不在谱返回 ""）。

    与导入端 `resolve_parent` 同口径：**有编号就只认编号**，编号认不出
    也不按名猜（防「按名接错人」，见 `import_from_game.resolve_parent`）；
    只有编号缺失时才按名回捞（谱内键就是姓名，直接查）。
    """
    if pc:
        return book_by_code.get(pc, "")
    if pn and pn in people:
        return pn
    return ""


def resolve(person, index, people, book_by_code=None):
    """一人 → `[(边('father'/'mother'), 存档父编号, 存档父名, 谱内应连名或'')]`。

    只回**存档记了真父母**的那些（占位已剔）；`谱内应连名` 为空 = 父母不在谱。
    """
    if book_by_code is None:
        book_by_code = {str(v.get("code")): n for n, v in people.items()
                        if str(v.get("code") or "").strip()}
    c = str(person.get("code") or "").strip()
    pr = index.get(c) if c else None
    if not pr:
        return []
    out = []
    for side in ("father", "mother"):
        pc, pn = (pr.get(side) or ("", ""))
        out.append((side, pc, pn, _target(pc, pn, people, book_by_code)))
    return out


def parent_gaps(people, index, keep=None):
    """谱内**父边缺口**：存档有父/母、父母在谱、谱里该边却空。

    → `[(谱内名, 'father'/'mother', 存档父编号, 存档父名, 谱内应连名)]`
    `keep` 给定时，只报「应连的人**也在 keep 里**」的那些（删除闸用 ——
    父母本身也要被删的话，留着孩子只能是个孤儿）。
    """
    book_by_code = {str(v.get("code")): n for n, v in people.items()
                    if str(v.get("code") or "").strip()}
    out = []
    for n, r in people.items():
        if not str(r.get("code") or "").strip():
            continue
        for side, pc, pn, tgt in resolve(r, index, people, book_by_code):
            if not tgt:
                continue                     # 父母不在谱 ⇒ 断根合理，不算缺口
            if keep is not None and tgt not in keep:
                continue
            if str(r.get(side) or "").strip():
                continue                     # 边已在
            out.append((n, side, pc, pn, tgt))
    return out
