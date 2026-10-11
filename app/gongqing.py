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
# ★ 2026-10-07 使用者（续七十一）：「秦国韩氏」这个框**先不画**（他要把该族驱逐
#   出去）。驱逐走完、该族从 `Jia_Zu_Map` 里消失后，把这个元组清空即可
#   —— 那时它本来也不会再出现，不需要留着这条豁免。
FRAME_HIDE_TITLES: tuple = ("秦国韩氏",)


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


def ruler_names(slot, king_codes=None):
    """**历代君主**的姓名集合（`King_Str` 解析，存档原文；由远到近，含现任）。

    ★ 2026-10-07 使用者（续七十二）：「**韩广类比韩淑，他俩一样的逻辑，加入关注**」
      —— 韩淑是「秦国韩氏」卿室家主 ⇒ 被公卿自动关注收进去了；**韩广不在任何
      家族的成员表里**（游戏没给他家族边），却同样是秦帝（`King_Str` 第二条）
      ⇒ 只按「家族成员」判据永远收不到他。所以君主得**单独有一条入关注的判据**。

    `king_codes` 给定时只取这些国的；不给则取全部国。**纯读**，不写文件。
    """
    out = set()
    t = slot.table(KING_TABLE) if slot is not None else None
    for r in (t.rows if t else ()):
        if king_codes is not None and str(r.get("King_Code")) not in king_codes:
            continue
        for ent in _parse_king_str(r.get("King_Str")):
            nm = str(ent[0] or "").strip()
            if nm:
                out.add(nm)
    return out


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


def fallen_clans(slot, followed_codes):
    """**曾被按公卿关注、如今已灭族/失爵**的家族 —— 该族全员应取消关注。

    ★ 2026-10-04 使用者：「公卿自动关注加一条规则，**如果该公卿被灭族了，
      则该族全员取消关注**」。

    判据（**全部来自存档实况，不猜**）：
      ① 家族仍在 `Jia_Zu_Map` 里（若整条消失就取不到成员，无从处置）；
      ② 但 `Jia_Zu_Type` **不再属于** {公室, 宗室, 卿室} ⇒ 已失爵 / 被灭；
      ③ 且其成员里**有人正在关注名单上** ⇒ 说明这家确实**曾按公卿被关注过**
         （否则会把一家普通家族误伤 —— 普通家族本来就不该被这条规则碰）。

    实测（`Save_All_1`，2026-10-04）：`Jia_Zu_Map` 203 家里有 **23 家类型为空**，
    但这 23 家的成员**当前无一在关注名单里** ⇒ **本次 0 命中**：
    这条规则是**预防性**的，等哪家真被灭时才动手。

    返回 `[{code, type, xing, shi, king_code, king_name, members, followed}]`：
      · `members` —— 该家**现在**的成员编号（去重排序）；
      · `followed` —— 其中**正被关注**的那部分（调用方据此取消关注）。
    """
    if slot is None or not followed_codes:
        return []
    ft = slot.table(FAMILY_TABLE)
    if ft is None:
        return []
    follow = {str(c) for c in followed_codes}
    meta = _king_meta(slot)
    out = []
    for r in (ft.rows or ()):
        jt = str(r.get("Jia_Zu_Type") or "")
        if jt in CLAN_TYPES:                      # ② 仍是公卿 ⇒ 没灭
            continue
        mem = [str(x) for x in
               ((r.get("Ren_Ke_Data") or {}).get("Cheng_Yuan_Array") or [])]
        if r.get("Jia_Zhu_Code") is not None:
            mem.append(str(r.get("Jia_Zhu_Code")))
        mem = sorted(set(c for c in mem if c))
        if not mem:
            continue
        hit = sorted(c for c in mem if c in follow)
        if not hit:                               # ③ 没人被关注过 ⇒ 不是"我方公卿"
            continue
        kc = str(r.get("King_Code"))
        out.append({"code": r.get("Code"), "type": jt,
                    "xing": str(r.get("Zu_Xing") or ""),
                    "shi": str(r.get("Jia_Shi") or ""),
                    "king_code": kc,
                    "king_name": (meta.get(kc) or {}).get("name") or "",
                    "members": mem, "followed": hit})
    return out


def _parse_king_str(txt):
    """`King_Str` → [(名, 姓, 谥, 爵, 在位年)]，**顺序由远到近**。

    ★ 2026-10-04 实测定案（这是本轮唯一容易踩错的地方）：
      · 条目分隔符是 **`,`**；**`、` 不是分隔符**，它是「在位年区间」
        （`嬴胡亥|嬴|哀|帝|-209、-207`）—— 按 `、` 拆会把年份当成君主名。
      · 每条 = `名|姓|谥|爵|在位年`；首条常只有名（`皋陶|`）。
      · 由远到近 ⇒ **现任 = 最后一条**，**前任 = 倒数第二条**。
      · 实例：秦 → `皋陶, 嬴胡亥, 嬴子婴, 宋义, 宋襄` ⇒ 现任**宋襄**、前任**宋义**
        （与人物表吻合：`宋襄.父 = 宋义`，父子相继 ✓）。
    """
    out = []
    for seg in str(txt or "").split(","):
        seg = seg.strip()
        if not seg:
            continue
        f = seg.split("|")
        name = f[0].strip()
        if not name:
            continue
        out.append(tuple((f + [""] * 5)[:5]))
    return out


# ---- 世界页「游戏世系」渲染用（★ 2026-10-06 使用者定案） ------------------
# 在位年的写法：`-209、-207` = 前 209 到前 207（公元前用负号）。
# 界面上要显示成 `前209 ~ 前207`，所以这里做一次**纯格式化**，不改数值。
def _fmt_span(span):
    """`-209、-207` → `前209 ~ 前207`；空 → 空串。

    ⚠️ 只做显示格式化，**不推算、不补数字**（守「宁缺勿猜」）：
      缺号、单号、异常写法一律原样返回，让使用者自己看存档原文。
    """
    s = str(span or "").strip()
    if not s:
        return ""
    parts = [p.strip() for p in s.split("、") if p.strip()]
    if len(parts) != 2:
        return s
    def one(x):
        # 已经是「前209」「公元前209」这类成品就原样用；裸数字才补「前」
        if x.startswith("前") or x.startswith("公"):
            return x
        # ⚠️ 存档里公元前是**负数**（`-209`），负号是「公元前」的一部分，
        #   不是负号直接显示 ⇒ 剥掉负号再加「前」，否则会显示成「前-209」。
        return ("前" + x[1:]) if x.startswith("-") else x
    return one(parts[0]) + " ～ " + one(parts[1])


def king_line(name, xing, shi, jue, span):
    """一条君主记录 → 界面一行 `(君主名, 谥号, 爵, 在位年显示)`。

    ★ 使用者 2026-10-06 口径：「**谥号、在位年数写名即可**」——
      即表格里**只要君主名**，谥号与在位年归详情卡的「游戏世系」逐行显示。
    """
    return name


def king_rows(txt):
    """`King_Str` → 详情卡「游戏世系」的**逐行**数据 `[(君主名, 姓, 谥号, 爵, 在位年)]`。

    - 顺序**由远到近**（与 `_parse_king_str` 一致），首行通常是始祖；
    - 首祖那条常常只有名（`皋陶|`），姓/谥/爵为空 ⇒ 界面上留空，不补；
    - 空串 / 无世系串 → 返回 `[]`，由界面显示「**缺**」（使用者 2026-10-06 定案）。
    """
    return [(nm, x, s, j, _fmt_span(sp)) for nm, x, s, j, sp in _parse_king_str(txt)]


def rulers(slot):
    """各国**君主世系** → `[{guo, cur, prev, cur_xing, seq}]`（只含世系 ≥1 条的国）。

    ⚠️ **不要**用 `Save_KingData.King_Last_Ren_Code` 当前任 —— 实测 32 例**全部对不上**
       （秦：世系串说前任=宋义，该字段却指向「新垣札」，且多数国解析不出人名）。
       前任只能用 `King_Str` 的**倒数第二条**（见 `_parse_king_str`）。
    """
    if slot is None:
        return []
    k = slot.table(KING_TABLE)
    stamp = (len(k.rows) if k else -1,)
    if getattr(slot, "_gq_rulers_stamp", None) == stamp:
        return getattr(slot, "_gq_rulers", [])
    out = []
    for r in (k.rows if k else ()):
        seq = _parse_king_str(r.get("King_Str"))
        if not seq:
            continue
        out.append({"guo": str(r.get("King_Name") or ""),
                    "cur": seq[-1][0],
                    "cur_xing": seq[-1][1],
                    "prev": seq[-2][0] if len(seq) > 1 else "",
                    "seq": [x[0] for x in seq]})
    slot._gq_rulers_stamp = stamp
    slot._gq_rulers = out
    return out


def filler_exception(slot, name, people=None):
    """**宗室填充人的君主例外**（使用者 2026-10-04 裁定）。

    原话：「宗室填充人**不入谱**；**除非他成了君主**，那么就挂靠他在该国
    **前任君主**旁边、算**同代人**的族人。」

    ⇒ 他是某国**现任君主**时返回
      `{"guo": 国名, "prev": 前任君主名, "prev_gen": 前任的世代或 None}`；
      否则返回 `None`（调用方保持原规则：跳过这个填充人）。

    为什么需要这个例外：填充人被判「跳过」的依据是**谱内没有任何家族边**，
    而**继位不产生任何家族边** ⇒ 单靠「日后成婚/生子就自愈」兜不住他，
    他会被当成孤点一直浮在画布外。

    ⚠️ 本档（`Save_All_2`）实测**命中 0 人** —— 现任君主 6 位全是有父有配偶的
      正常人。与 `fallen_clans` 同类，是**预防性**规则：等谁真以填充人之身
      继位时才动手。
    """
    if not name or slot is None:
        return None
    for r in rulers(slot):
        if r["cur"] != name:
            continue
        prev = r["prev"]
        prev_gen = None
        if people and prev:
            pv = people.get(prev) or {}
            prev_gen = pv.get("generation")
        return {"guo": r["guo"], "prev": prev, "prev_gen": prev_gen}
    return None


import re

_PH_SUFFIX = re.compile(r"(父|祖|曾|高)$")


def _rec_is_placeholder(code, by_code):
    """占位祖先空壳（与 `tools.import_from_game._is_ph_code` **同判据**：
    编号带 父/祖/曾/高 后缀、且记录缺 `Ren_Sex` 或查无此人）。
    app 侧不 import tools —— 自带一份轻实现，惯例见 `app/storage.py` 同款注释。"""
    code = str(code or "")
    if not code or not _PH_SUFFIX.search(code):
        return False
    r = by_code.get(code)
    if r is None:
        return True
    return "Ren_Sex" not in r


def filler_codes(by_code, members=None):
    """**宗室填充人编号集**（实录层原始字段版，2026-10-05 使用者裁定）。

    诸侯国（新封建 + 开局既有）会被游戏塞 **3-5 个宗室填充人**——无父母、
    无配偶、无子女的孤立节点，用于避免诸侯绝嗣。**男女都算**（`Ren_Sex`
    不看）。这批人**连谱牒都不进**——《大宋天下》实测：续四十一版过滤只挡了
    「关注/入谱标」，`need` 里仍带着他们 ⇒ 整批导入 ⇒ 画布上照旧浮出孤点
    （「隐藏非史」一关就现形）。

    判据（实录层原始字段，导**入之前**就能判）：
      · 无**真**父母 —— `Father_Code` / `Parent.Father.Ren_Code`（母版同构）；
        ⚠️ 指向**占位空壳**（编号带 父/祖/曾/高 后缀）的父边**不算边**
        （实测 52 人 100% 挂在占位假父亲名下）；
      · 无配偶（`Ren_Pei_Ou_Code_Array` 空）；
      · 无子女（没有任何一行的真父母编号指向他）；
      · **非史实** —— 编号 9 位（史实编号 ≤5 位，与人物卡「史/非史」徽标
        同一口径）⇒ 刘泽（20012）这类无边的**真史实**不误伤。
    子女/配偶边在实录里出现的那一天起就不是填充人了——自愈。
    ⚠️ **君主例外不在这里**：继位不产生家族边，本函数兜不住「以填充人之身
      继位」的人 —— 调用方（`main.focus_gongqing` / `tools/auto_follow_gongqing`）
      用 `filler_exception()` 逐人放行。
    """
    def _real_parents(r):
        out = []
        for base, nest in (("Father_Code", "Father"), ("Mother_Code", "Mother")):
            p = str(r.get(base) or "").strip() or \
                str(((r.get("Parent") or {}).get(nest) or {}).get("Ren_Code") or "").strip()
            if p and not _rec_is_placeholder(p, by_code):
                out.append(p)
        return out

    parents = set()
    for _c, r in by_code.items():
        parents.update(_real_parents(r))
    out = set()
    for c, r in by_code.items():
        if members is not None and str(c) not in members:
            continue
        if len(str(c)) <= 5:            # 史实编号 ≤5 位，永不判填充
            continue
        if _real_parents(r):
            continue
        if r.get("Ren_Pei_Ou_Code_Array"):
            continue
        if str(c) in parents:
            continue
        out.add(str(c))
    return out


# ============================================================ 家族框（2026-10-04 定案）
# 使用者口径（原话整理）：
#   · 「历史上的框和现实的框分开做了……**同一波人，肯定就一个框**」⇒ 不再分
#     「世系框 / 家族框」两套，**一个家一个框**，两个来源并成一份成员名单；
#   · 「只做公卿 —— **有诸侯国的或者是卿室的**」⇒ `Jia_Zu_Type` ∈ {公室, 宗室, 卿室}；
#     **庶家 / 平民家族（类型为空）不框**；
#   · 「**保留 2 人成框**」；
#   · 「**世系这俩字也不要了**」⇒ 公室「X公族」/ 宗室「X国」/ 卿室「X氏」；
#   · 「某A不可能既是1成员又是2成员，**这你得识别**」⇒ 一人只归一框。
FRAME_CLAN_TYPES = ("公室", "宗室", "卿室")


def _married_out(info):
    """这个人算不算「**嫁出去的女性**」—— 女性 + 已被摆到丈夫名下。

    ★ 2026-10-06 使用者裁定：「**这些人女性只要嫁出去就不入世系框**」。
      判据取 `associate_of` / `associate_type == "spouse"`（`tools/attach_lone_wives.py`
      写的那三个字段）—— 它记录的正是「画布上她跟在丈夫旁边」这个事实。
      嫁出去的女儿落点在**夫家区域**，若还算娘家家族框的成员，框就会被从本族
      一路撑到夫家（实测「秦国刘氏」被刘琳/刘珑/刘瑾/刘雯/刘露 撑到 26194px 宽）。

    ⚠️ 只剔「被挂到丈夫名下」的：**娶进来的媳妇**（史实、有父、没有 `associate_of`）
      不受影响 —— 她们本来就长在本族区域，不进框反而丢人。
    """
    if str(info.get("gender") or "") != "女":
        return False
    if str(info.get("associate_type") or "") != "spouse":
        return False
    return bool(str(info.get("associate_of") or "").strip())


def frame_groups(slot, people, lineage_groups=None):
    """**公卿家族 → 虚线框分组**（两个家谱共用这一份判据）。

    返回 `[{"key", "title", "members", "type", "guo"}]`（按人数降序）。

    成员口径 = **`Jia_Zu_Map` 的开局编号成员**（`Cheng_Yuan_Array` ＋ `Jia_Zhu_Code`，
    公室/宗室另按 `King_Str` 并入历任君主 —— 见下）。

    ⚠️⚠️ **2026-10-07 更正一条错结论（别再犯）**：
      本函数曾写着「家族表**不记前任国君** —— 实测『宗室·冯』家主是冯代（第 2 代
      冯伯），**第 1 代冯伯冯解敢（编号 4255）在 215 家里一个字都没有**」，并据此
      加了「并上整条宗庙世系」那一手。**那是错的**：
      · 在当前槽 `Save_All_1` 上实测，`Jia_Zu_Map` 里 `Code=1000113`
        （**宗室**·氏冯·姓姬）的 **`Jia_Zhu_Code` 就是 `4255` = 冯解敢**，
        且他是 `Cheng_Yuan_Array` 的**第一条**成员 ⇒「冯国」框本来就有他。
      · 所以那句「一个字都没有」既没有可查出处、也与存档原文相反 ——
        多半是当年拿**另一个槽**、或只看了一眼家主字段就下了结论。
      · 教训：**下结论前必须回存档原文核一遍**（本项目的铁律「不许编造·要带可查出处」）。
    ⚠️ 另一条**保留**的实证（2026-10-07 现量）：公室/宗室的 `Cheng_Yuan_Array`
      **完全不含君主** —— 15 家 · 21 位 `King_Str` 君主，**在成员表里 0 个**
      ⇒ 下面「按 `King_Str` 并入历任君主」那一步**必须留着**，否则国君会在框外。
    ⚠️ **一人只归一框**（`used`）：使用者要求「这你得识别」。

    标题：公室「X公族」· 宗室「X国」· 卿室「X氏」（X = 国名 / 氏）。
    """
    if slot is None:
        return []
    fam = slot.table(FAMILY_TABLE)
    if fam is None:
        return []
    king = slot.table(KING_TABLE)
    guo = {str(r.get("King_Code")): str(r.get("King_Name") or "")
           for r in (king.rows if king else ())}
    code2name = {str((v or {}).get("code") or ""): n
                 for n, v in (people or {}).items() if (v or {}).get("code")}
    lins = {k: set(v) for k, v in (lineage_groups or {}).items()}

    # ★ 2026-10-06 入赘家庭（女君主+入赘）：判据复用 `layout._uzheng_family`
    #   （gongqing 与 layout 无环依赖，延迟 import 即可）。
    from . import layout as _L
    _uz_kids, _matri, _chost = _L._uzheng_family(people or {})

    # ★★ 2026-10-04 **性能**：本函数被视图放在**全量重绘**（`tree_view._draw` /
    #   `timeline_view` 的 rerender）里调用，而它要扫`Jia_Zu_Map` + 遍历
    #   「世系 ∪ 家族」⇒ 拖动画布时反复重绘 = 反复全量扫（使用者实测「拖动很卡」）。
    #   ⇒ 与 `clans` / `rulers` 同一套手法**按槽缓存**；键里带上 people 规模与
    #   世系组数量，换档/重导入自然失效。
    stamp = (len(fam.rows), len(people or {}), len(lins),
             tuple(sorted(lins))[:8] if lins else ())
    if getattr(slot, "_gq_frame_stamp", None) == stamp:
        return getattr(slot, "_gq_frames", [])

    used, out = set(), []
    for r in (fam.rows or ()):
        t = str(r.get("Jia_Zu_Type") or "")
        if t not in FRAME_CLAN_TYPES:
            continue                       # 庶家 / 平民 / 空类型 ⇒ 不框
        codes = [str(x) for x in
                 ((r.get("Ren_Ke_Data") or {}).get("Cheng_Yuan_Array") or [])]
        if r.get("Jia_Zhu_Code") is not None:
            codes.append(str(r["Jia_Zhu_Code"]))
        mem = {code2name[c] for c in codes if c in code2name}
        # ★ 2026-10-06 母系家主（女君主+入赘）的家族**拆两框**（使用者裁定：
        #   「韩淑进秦国框、她的子女开韩氏框」）：
        #   · 框A「君主的国」= 家主 + 吸收的世系（韩淑 + 韩广 → 「秦国」）；
        #   · 框B「韩氏」= 家主的**全部孩子**（母亲是她且姓随母），不进框A。
        jz_name = (code2name.get(str(r.get("Jia_Zhu_Code")))
                   if r.get("Jia_Zhu_Code") is not None else "")
        matri_kids = set()
        is_matri = bool(jz_name and jz_name in _matri)
        if is_matri:
            matri_kids = {n for n, v in (people or {}).items()
                          if str(v.get("mother") or "") == jz_name
                          and n in _uz_kids}
            mem = {n for n in mem if n not in _uz_kids}
            # 并上**同 lineage 的君主**（韩广）—— `_lineage_groups` 会把无父无母
            # 的君主按父系连通块拆成「周秦/汉秦」两块（韩淑、韩广各自一块），
            # 靠世系吸收收不到韩广；这里直接按 lineage 并进来，框A 才有「秦国」
            # 该有的两任君主。世系吸收一步跳过（口径不同，别让「周秦」单独收）。
            jz_lin = (people.get(jz_name) or {}).get("lineage_name") or ""
            if jz_lin:
                mem |= {n for n, v in (people or {}).items()
                        if (v or {}).get("lineage_name") == jz_lin and n != jz_name}
        # ★ 2026-10-07 **撤销「并上世系」**（使用者纠正：「**你的刘氏为什么从姬俊
        #   开始算，不是说了吗，公卿家族只算游戏里面开局的编号家族人数？你上到
        #   第几代去了**」）——
        #   原实现（2026-10-04 加，依据「家族没有冯解敢，那么冯国框就有他，
        #   2选1也得选啊」）是 `mem |= ln`：把与该家有交集的**整条宗庙世系**
        #   并进框。代价实测：**270 人凭空进框**，最刺眼的是「秦国刘氏」——
        #   刘邦的宗庙世系是「箕」，一路连到上古 **姬俊（生 -2148）**，于是刘氏框
        #   被撑成 y 跨 1.2 万 px（从帝喾一直框到汉初）。
        #   ⇒ **家族框成员 = `Jia_Zu_Map` 的开局编号成员**（`Cheng_Yuan_Array`
        #     ＋ `Jia_Zhu_Code`），**不再吸收世系**。
        #   ⚠️ 当年「冯解敢」那个用例**已经不吃这条了**：他本身就在编号成员里
        #     （冯国 fam1000113 编号 21 人含他，且他是**家主** `Jia_Zhu_Code`）。
        #     —— 也就是说**当年那条立论本身就是错的**（详见本函数 docstring 的
        #     「2026-10-07 更正一条错结论」）。
        #   ⚠️ 若将来要「同族族人」也能进框，正确做法是**另立一条有界判据**
        #     （例如只收不比本族最老者更老的族人），而不是整条世系并进来。
        # ★★ 2026-10-07 使用者裁定（第 1 条）：「三个秦帝因为爵位等级（都是帝）
        #   应该是挨着的，**一个大框就能框住**」——
        #   按 `King_Str`（存档权威君主序列，由远到近）把**该国的历任君主**
        #   一并并入该国的国框（公室/宗室）。实测秦：序列 = 皋陶 · 嬴胡亥 ·
        #   韩广 · 韩淑 · 宋义 · 宋襄 · 乐正克 · 龙且 ⇒ 框内原本只有后四位
        #   （宋义/宋襄/乐正克/龙且），三位秦帝（嬴胡亥/韩广/韩淑）**没有任何框**
        #   —— 因为一百一十二批那次是靠打在旧《大宋天下》档上的 `lineage='秦'`
        #   数据补丁，档删了补丁就丢了；而按 guo=「嬴」匹配也对不上号。
        #   现在直接吃存档原文（`_parse_king_str`，108 批已解析），不依赖补丁、
        #   不猜、不改数据。只对**公室/宗室**（王族）做 —— 卿室的氏框不吸君主。
        if t in ("公室", "宗室") and r.get("King_Code") is not None:
            _kc = str(r.get("King_Code"))
            for _kr in (king.rows if king else ()):
                if str(_kr.get("King_Code")) != _kc:
                    continue
                for _row in _parse_king_str(_kr.get("King_Str")):
                    _nm = _row[0]
                    if _nm in (people or {}):
                        mem.add(_nm)
        # ★ 2026-10-06 使用者裁定「这些人女性只要嫁出去就不入世系框」——
        #   先剔已嫁女性（判据见 `_married_out`），再走「一人只归一框」。
        mem = {n for n in mem if not _married_out(people.get(n) or {})}
        mem -= used                         # 一人只归一框
        # ★ 2026-10-06 框B：母系家主的「氏」框（韩氏）—— 子女开氏框。
        #   **独立于框A**：框A 若不足 2 人，不影响框B 成立 —— 原来的写法把框B
        #   放在框A 的 `continue` 之后，框A 不达标就整个跳过、框B 一起没了
        #   （实测「韩氏」框就是这么丢的）。
        if matri_kids:
            matri_kids -= used
            if len(matri_kids) >= 2:
                fam_shi = str(r.get("Jia_Shi") or "")
                clan_title = fam_shi if fam_shi.endswith("氏") else (fam_shi + "氏")
                used |= matri_kids
                out.append({"key": "fam%s_clan" % r.get("Code"),
                            "title": clan_title, "members": sorted(matri_kids),
                            "type": "卿室", "guo": "",
                            "jia_zhu": jz_name})
        # 「保留 2 人成框」——**公室例外**（使用者 2026-10-04 裁定 B 方案）：
        #   「B 各画，现在只有 1 人，**以后会有后代**」。实测本档「公室·嬴」
        #   谱内只有秦质 1 人（国=嬴、姓嬴、氏秦），若按 2 人门槛就被丢掉、
        #   秦质一个框都没有 ⇒ 公室**1 人也成框**，等他有了后代自然长起来。
        if len(mem) < (1 if t == "公室" else 2):
            continue
        used |= mem
        shi = str(r.get("Jia_Shi") or "")
        gn = guo.get(str(r.get("King_Code")), "") or str(r.get("Zu_Xing") or "")
        # 标题**从大到小**：国 → 氏。使用者 2026-10-04：
        #   「不要出现 `·` 这种符号，我们是很古朴的历史脚本……同国同氏同性质，
        #    那就**汉字同名**吧（编码肯定不一样，相当于本地化就做同名），
        #    改成『**秦刘氏**』这种，从大到小排列」。
        #   ⇒ 卿室 = 国名 + 氏 + 「氏」（氏已带「氏」字就不重复加）。
        #   ⚠️ **故意允许同名**：两家「秦刘氏」就是两家，靠 `key`（家族编号）区分，
        #      不靠标题；下游必须用 `key` 建字典（见 `layout.state_group_boxes`）。
        #   ⚠️ 若家族名**自带地名**（如「彭城刘氏」），那另说 —— 待实测确认字段。
        # 使用者 2026-10-04 二次裁定：
        #   「X刘氏 / X宋氏 比较难听，**还是加个国吧：X国刘氏 / X国宋氏**这样」；
        #   「**宗室还是写国家**，比如 X国」；「**公室就写 X国公族**」；
        #   「**啥也没有的刘氏就保持两个字**」。
        #   ⇒ 卿室 = 国 + 「国」 + 氏 + 「氏」（秦国刘氏 / 嬴国宋氏）
        #      宗室 = 国 + 「国」（秦国）
        #      公室 = 国 + 「国公族」（秦国公族）
        #      无国   = 氏 + 「氏」（刘氏，两个字）
        if t == "公室":
            title = gn + "国公族" if gn else shi + "公族"
        elif t == "宗室":
            title = gn + "国" if gn else shi + "国"
        else:
            base = shi if shi.endswith("氏") else (shi + "氏")
            title = (gn + "国" + base) if gn else base
        out.append({"key": "fam%s" % r.get("Code"), "title": title,
                    "members": sorted(mem), "type": t, "guo": gn,
                    "jia_zhu": code2name.get(
                        str(r.get("Jia_Zhu_Code")) if r.get("Jia_Zhu_Code") is not None
                        else "", "")})
    # 标题**不再做区分**（使用者：「同国同氏同性质，那就汉字同名吧」）——
    # 谁是哪一家，由 `key`（家族编号）负责，**不靠标题**。
    # ⚠️ 所以下游**必须用 `key` 建字典**，按标题建会吞掉同名的那一家（实测 54 → 50 ✗）。
    # ★ 2026-10-07 使用者（续七十一）：「秦国韩氏」**先不画框**（他要驱逐该族）。
    #   摆在本函数**最末**过滤：① 标题在 `FRAME_HIDE_TITLES` 里的整框去掉；
    #   ② 其成员的 `used` 早已生效 ⇒ 不会被别的家族吸收、也不会残留小框。
    if FRAME_HIDE_TITLES:
        out = [f for f in out if f["title"] not in FRAME_HIDE_TITLES]
    out.sort(key=lambda f: -len(f["members"]))
    slot._gq_frame_stamp = stamp          # ★ 性能：缓存（见函数中部说明）
    slot._gq_frames = out
    return out


def family_ranks(slot, frames):
    """**家族框 → 排序爵位**（两个家谱的根节点排序共用这一份判据）。

    口径（★ 2026-10-07 使用者：「刘氏并不是帝级，他是公卿家族」）：
      · **卿室 = 卿**（2）；
      · **公室 / 宗室 = 本国现行爵位** —— 取该国 `King_Str` **最后一条**的爵
        （由远到近，末条＝现任），经 `theme.TIER_PRIORITY` 折成数；
      · 查不到国 / 爵 → 0（沉到最后）。
    为什么不用成员的**历史称号**（note/上色爵称）：刘盈的「汉惠帝」会把整个
    卿室家族抬成帝级 —— 那是历史头衔，游戏里他只是卿室成员。

    ★ 2026-10-11：从 `timeline_view` 里搬出来成为共享函数 —— 代际家谱的
      根节点排序现在也要用它（使用者：同姓同氏聚一起、组间按爵位）。
    """
    from .theme import TIER_PRIORITY
    guo_rank = {}
    t = slot.table(KING_TABLE) if slot is not None else None
    for row in (t.rows if t else ()):
        ents = _parse_king_str(row.get("King_Str") or "")
        if ents:
            guo_rank[str(row.get("King_Name") or "")] = \
                TIER_PRIORITY.get(str(ents[-1][3] or "").strip(), 1)
    out = {}
    for f in (frames or ()):
        if f.get("type") == "卿室":
            out[f["key"]] = TIER_PRIORITY.get("卿", 2)
        else:
            out[f["key"]] = guo_rank.get(f.get("guo") or "", 0)
    return out


def succession_map(slot):
    """`{现任: 前任}` —— 继任链的**权威顺序**（存档 `King_Str`，由远到近）。

    ★ 2026-10-07 使用者：卒年启发式在「多帝并立」的奇观档会锚错（实测韩淑差点
      锚到她丈夫龙且：同 note 且卒年更近）⇒ 改用存档原文的相邻两条。
    ★ 2026-10-11：从 `timeline_view` 搬成共享函数（代际/时间轴同源）。
    """
    out = {}
    t = slot.table(KING_TABLE) if slot is not None else None
    for row in (t.rows if t else ()):
        prev = None
        for ent in _parse_king_str(row.get("King_Str") or ""):
            nm = str(ent[0] or "").strip()
            if not nm:
                continue
            if prev:
                out.setdefault(nm, prev)
            prev = nm
    return out


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
