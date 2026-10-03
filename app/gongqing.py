# -*- coding: utf-8 -*-
"""公卿家族 —— **存档实证**判据（家族总表 + 国表族域）。

## 这个模块解决什么

使用者要三件事，全都依赖同一个问题的答案「**谁是公卿**」：
  · A 人物页表格把公卿家族成员标「卿」、筛选加「仅显公卿」；
  · B 公卿家族自动关注（＝自动入谱）、同宗共祖一并关注；
  · C 卿室家族单独配色（原来配的是灰、且判据是姓氏启发式）。
所以判据**只写这一份**，三处复用。

## 口径（三层过滤，缺一不可；2026-10-02 使用者裁定）

```
① Jia_Zu_Type ∈ {公室, 宗室, 卿室}      ← 家族总表（游戏自己的权威标记）
② 该国 Zu_Yu == 0（中夏）                ← 排掉少数民族（`Save_KingData` 的族域）
③ 国名不含「叛军」                        ← 使用者追加：「叛军也不算公卿」
```

`Save_All_101` 实测：原始 123 家（宗室 101 / 卿室 19 / 公室 3）→ **过滤后 21 家 /
140 名成员**（楚 17 卿室 + 秦 1 卿室 + 秦宗室/公室 + 楚宗室）。
宗室之所以有 101 家，是因为存档里 **103 国每国一家王族**（不是标记错）。

## 数据来源（实测字段）

· `Jia_Zu_Controller/Jia_Zu_Map`：`Code`（家族编号）/ `Jia_Zu_Type` /
  `Jia_Shi`（氏）/ `Zu_Xing`（姓）/ `King_Code`（隶属国）/ `Jia_Zhu_Code`（家主）/
  `Ren_Ke_Data.Cheng_Yuan_Array`（**成员人物编号列表**）。
· `Save_KingData`（一国一文件）：`King_Code` / `King_Name` / `Zu_Yu`（族域）。

⚠️ `Jia_Zu_Controller/Jia_Zu_Guan_Xi_Map`（家族两两关系）本档 **821 行的
   `Tong_Xing`/`Yin_Qin`/`Guan_Xi` 全是 None**（只有两个家族编号）——
   **不可用**，所以「同宗」只能按**同姓 + 同氏**判（见 `same_clan_pairs`）。

本模块**纯读**，不写任何文件。
"""
CLAN_TYPES = ("公室", "宗室", "卿室")
FAMILY_TABLE = "Jia_Zu_Controller/Jia_Zu_Map"
KING_TABLE = "Save_KingData"
REBEL_MARK = "叛军"


def _king_meta(slot):
    """→ {King_Code(str): {"name": 国名, "zu_yu": 族域(str)}}。"""
    out = {}
    t = slot.table(KING_TABLE) if slot is not None else None
    for r in (t.rows if t else ()):
        kc = r.get("King_Code")
        if kc is None:
            continue
        out[str(kc)] = {"name": str(r.get("King_Name") or ""),
                        "zu_yu": str(r.get("Zu_Yu"))}
    return out


def _stamp(slot):
    """缓存键 = 两张源表的行数（换槽/重拉档 → 行数一变即失效）。"""
    f = slot.table(FAMILY_TABLE) if slot is not None else None
    k = slot.table(KING_TABLE) if slot is not None else None
    return (len(f.rows) if f else -1, len(k.rows) if k else -1)


def clans(slot):
    """三层过滤后的**公卿家族**列表（结果按槽缓存）。

    每项：`{code, type, shi, xing, king_code, king_name, jia_zhu, members}`
    —— `members` 是**去重排序**的编号字符串列表（含家主）。
    槽为空 / 没有家族表 → `[]`（调用方据此不显示任何公卿标记）。
    """
    if slot is None:
        return []
    stamp = _stamp(slot)
    if getattr(slot, "_gq_stamp", None) == stamp:
        return getattr(slot, "_gq_clans", [])
    meta = _king_meta(slot)
    ft = slot.table(FAMILY_TABLE)
    out = []
    for r in (ft.rows if ft else ()):
        jt = str(r.get("Jia_Zu_Type") or "")
        if jt not in CLAN_TYPES:
            continue
        kc = str(r.get("King_Code"))
        m = meta.get(kc) or {}
        if m.get("zu_yu") != "0":                     # ② 非中夏
            continue
        if REBEL_MARK in (m.get("name") or ""):        # ③ 叛军
            continue
        mem = [str(x) for x in
               ((r.get("Ren_Ke_Data") or {}).get("Cheng_Yuan_Array") or [])]
        if r.get("Jia_Zhu_Code") is not None:
            mem.append(str(r.get("Jia_Zhu_Code")))
        out.append({"code": r.get("Code"), "type": jt,
                    "shi": str(r.get("Jia_Shi") or ""),
                    "xing": str(r.get("Zu_Xing") or ""),
                    "king_code": kc, "king_name": m.get("name") or "",
                    "jia_zhu": (str(r["Jia_Zhu_Code"])
                                if r.get("Jia_Zhu_Code") is not None else ""),
                    "members": sorted(set(c for c in mem if c))})
    slot._gq_stamp = stamp
    slot._gq_clans = out
    return out


def clan_members(slot):
    """**公卿家族**全部成员的编号集合（公室 + 宗室 + 卿室，共 21 家）。"""
    s = set()
    for f in clans(slot):
        s |= set(f["members"])
    return s


def qing_members(slot):
    """**卿室**家族成员的编号集合（C 的专用口径 —— 卿族色只给卿室）。

    宗室/公室是**王族**，其成员该按王/国君上色，不该染成「卿」色。
    """
    s = set()
    for f in clans(slot):
        if f["type"] == "卿室":
            s |= set(f["members"])
    return s


def same_clan_pairs(fams):
    """家族列表里**同宗**的两两配对 —— 判据：同姓 + 同氏（且非同一家）。

    ⚠️ 游戏的家族关系表（`Jia_Zu_Guan_Xi_Map`）本档没有同姓/姻亲内容，
      所以只能按「同姓 + 同氏」这一条硬判据；本档命中 4 对：
      陈×2、刘×2、吕×2、项×2（另有嬴×2 两家姓氏相同）。
    """
    out = []
    n = len(fams or ())
    for i in range(n):
        a = fams[i]
        if not a.get("shi") or not a.get("xing"):
            continue
        for j in range(i + 1, n):
            b = fams[j]
            if (a["shi"] == b.get("shi") and a["xing"] == b.get("xing")
                    and a.get("code") != b.get("code")):
                out.append((a, b))
    return out
