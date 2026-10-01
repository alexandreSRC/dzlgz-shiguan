# -*- coding: utf-8 -*-
"""推定世系（虚接）—— 把接不到风巢皇的根，按「同族名 + 生卒年」接到最近的上游。

## 为什么有这一步

《全史存档》由 32 个剧本档合并而来，血缘图有 **489 个连通分量**：一棵大树
（风巢皇一系，11,593 人）+ 488 支孤根。使用者 2026-09-25 裁定：
**按"同族同源"把它们虚接进那棵大树**，但必须
  · 只写**推定**字段（`father_guess` / `guess_note`），**绝不覆盖事实层的 `father`**；
  · 家谱页用**另一类边**（灰色虚线 +「推定世系」标注）单独画，不参与任何逻辑；
  · 家谱页不提供「清空」，但推定记录随谱牒一起导出，作为补充说明。

## 规则（使用者逐条定的）

1. **同源键 = 族名 = 姓 ∪ 氏**（从 `bio` 解析）。为什么不是只比"姓"：
   游戏对同族写法不一致 —— 黎蚩尤=`姜姓黎氏`（黎是氏）、黎真=`黎氏`、
   妇甲=`黎姓妇氏`；只比姓，蚩尤（姜）与黎真（黎）就永远碰不上。
2. **接点 = 同族名、生年更早、且在目标树里、生年最大（时间最近）的那位**；
   优先男性（谱牒按父系单传），没有男性才退到女性。
3. 迭代接入：一支接上后，它的人就成了别的根的候选上游。
4. 少数**按史料/传说直接落定**的（不算推定，写事实层）见 `FACTS`
   —— 使用者裁定「真实史料/传说 > 游戏」。
5. 少数**按生卒年单独裁定**的见 `HANDPICK`。

用法：
  python tools/guess_lineage.py              # 演习：只出报告
  python tools/guess_lineage.py --apply      # 写进谱牒（带备份）
  python tools/guess_lineage.py --book 全史存档
"""
import argparse
import collections
import io
import json
import os
import re
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

from tools.import_from_game import write_atomic                 # noqa: E402

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace")

# 目标树 = 这位所在的分量
ROOT_NAME = "风巢皇"

# ★ 代差下限（年）—— 缺了它，"最近上游"会退化成**接到同龄旁系**上：
#   实测第一版跑出 `姜坦→姜实`（只差 1 年）、`釐亏→姬仲朗`（差 1 年）这种
#   "1 岁之差当父子"，荒谬。父子至少该差出小半代人，取 15 年；
#   最近候选不够，就沿生年向上退到够的那一个；一个都没有 ⇒ 这支不接。
MIN_GAP = 15
# ★ 2026-09-27 使用者拍板（续十八）：虚接代差上限 —— 超过 120 年的
#   「同姓同氏」在时间轴上不可能是父子，一律不接（偃桐/偃应→偃益 900+、
#   缯贺←缯采 396、甘龙→甘父 300 这类全部断开）。
MAX_GAP = 120
# ★ 断开名单（✗21 条处置拍板）：不虚接也不挂靠，留作单节点 ——
#   多为史载人物父无载 + 异国异势力硬凑；含 4 条同名分身（待合并专项）。
NO_HOOK = {"辛甲", "阎乐", "王绾", "将渠", "夏区夫", "卜徒父", "由余",
           "卜商", "到满", "魏冉", "彭仲爽", "辛伯2",
           "曹咎2", "虞卿2", "傅瑕2", "辛胜2",
           "偃桐", "偃应", "缯贺", "龙贾", "骊姬", "庄不识"}
# ★ 势力校正（写盘时应用）：网查发现游戏势力字段与史载相悖的，
#   按史料改正（阎乐=秦咸阳令、将渠=燕相、到满=秦将、夏区夫=陈大夫、
#   彭仲爽=楚令尹、辛甲=周太史、魏冉=穰侯仕秦）。
FACTS_STATE = {"阎乐": "秦", "将渠": "燕", "到满": "秦", "夏区夫": "陈",
               "彭仲爽": "楚", "辛甲": "周", "魏冉": "秦"}

_XING_SHI = re.compile(r"([\u4e00-\u9fff])姓([\u4e00-\u9fff]{1,2})氏")
_XING_ONLY = re.compile(r"([\u4e00-\u9fff])姓")
_SHI_ONLY = re.compile(r"^[^，]{1,14}，([\u4e00-\u9fff]{1,2})氏")

# ------------------------------------------------------------------ 事实层落定
# 使用者裁定「真实史料/传说是第一根据」⇒ 这几条**不算推定**，写事实层。
#   姒华胥（华胥氏）：传说伏羲、女娲之母 ⇒ 同代挂风燧人 + 补伏羲/女娲的「母」。
#   西陵女嫘（嫘祖）：《史记·五帝本纪》黄帝元妃、生玄嚣与昌意
#     ⇒ 配偶姬轩辕 + 补姬玄嚣/姬昌意的「母」（书里两人正好都在第 15 代）。
#
# ★ 2026-09-30 新增 `father` 一类 —— 使用者：「虚接里面**有根据的**查查，
#   按照真实历史来」。此前 FACTS 只有 associate/spouse/mother，没用到 father，
#   于是史料明载的父子关系也被当成"推定"，被同族名规则**错接**。
#
#   实测案例 · 子周（宋父周，孔子直系先祖）：
#     《孔子家语·本姓解》「宋湣公(子共)生弗父何，**何生宋父周**，
#       宋父周生世子胜，胜生正考父，正考父生孔父嘉……始以孔为氏。」
#     · 总谱里 `子周` 的 `father` 为空 ⇒ 被自动推定接给 **箕野**（箕国君主，
#       子姓箕氏）—— 同姓"子"而已，**与宋国不是一支，错**；
#     · 总谱里这条线的下游**一环不缺**：子世2(=世子胜) → 子正考(=正考父)
#       → 孔嘉(=孔父嘉) → 孔木(=木金父) → 孔睾(=睾夷) → 孔防叔 → 孔伯夏
#       → 孔纥(=叔梁纥) → 孔子 → 孔鲤 → 孔伋；
#     · 只能接 `子共`（宋湣公，世代 48 / 生 -970，与子周 -895 差 75 年）——
#       **中间真实还有「弗父何」一代，游戏未收录** ⇒ 隔代这一事实记进
#       `father_note`，不遮掩。
FACTS = {
    "associate": {"姒华胥": "风燧人", "西陵女嫘": "姬轩辕"},
    "spouse": {"姬轩辕": "西陵女嫘"},
    "mother": {"风伏羲": "姒华胥", "风女娲": "姒华胥",
               "姬玄嚣": "西陵女嫘", "姬昌意": "西陵女嫘"},
    # 父：{子: 父} —— 写事实层 `father`，并清掉该人身上可能存在的推定父。
    "father": {"子周": "子共", "西乞术": "蹇叔"},
}

# 史料落定的父，逐条附一句依据（写进 `father_note`，供后人复核）。
FACT_FATHER_NOTE = {
    "子周": "《孔子家语·本姓解》「何生宋父周」——宋湣公(子共)一系；"
            "真实中间尚有「弗父何」一代，游戏未收录，故直接接子共。",
    "西乞术": "杜预注《左传》崤之战：西乞术为蹇叔之子（孟明视、西乞术、"
              "白乙丙三帅同出）；蹇叔在谱（秦穆公上大夫）——网查后史料实接。",
}

# ------------------------------------------------------------------ 按生卒年裁定
# 使用者 2026-09-25：「赤将按游戏生卒年定为契的亲近祖辈的**同代人**；
#   契诟虚接，按生卒年判断虚接给谁。」
#   契的祖辈链（实测）：子玄契(18,-2098)→姬俊(17,-2148)→姬蟜极(16,-2188)
#     →姬玄嚣(15,-2228)→姬轩辕(14,-2246)
#   赤将子舆(14,-2219) ⇒ 与姬轩辕同代（差 27 年）
#   契诟(16,-2196)     ⇒ 按生卒年最近的上游 = 姬玄嚣(15,-2228)
HANDPICK = {
    "associate": {"赤将子舆": "姬轩辕"},
    "father_guess": {"契诟": "姬玄嚣"},
}

# ------------------------------------------------------------------ 强制挂靠
# ★ 2026-09-30 使用者逐条指示：这些人**不做虚接（父子），改挂靠（同代人）**：
#   彭越 —— 「可能是大彭国后裔，**太远了实在靠不上了就算了**」⇒ 挂靠同势力
#   任敖 —— 「**挂靠到同势力的人身上，以同代人身份**」
FORCE_HOOK = {"彭越", "任敖"}

# 史料也是"黄帝时人"、且族名上游不够一代 ⇒ 一律按同代人挂黄帝（不等同推定父子）：
#   仓颉 —— 黄帝史官（《说文解字·叙》"黄帝之史仓颉"）；
#   俞跗 —— 黄帝时良医（《史记·扁鹊仓公列传》"医有俞跗"）。
HANDPICK["associate"].update({"仓颉": "姬轩辕", "俞跗": "姬轩辕"})

# ★ 使用者裁定「少数民族保留独立家族树」⇒ 这几支**不自动推定接枝**。
#   淳维 按使用者 2026-09-25 的裁定**按游戏处理**（游戏写他姜姓 ⇒ 照游戏接姜姓线），
#   所以**不在**排除表里；史料冲突（《史记》说他是夏后氏苗裔/姒姓）已记进日志备查。
EXCLUDE_ROOTS = {"素和古尔本", "格萨尔洛布扎堆", "丹玛向叉",
                 "雍仲伦珠扎巴"}

# ★ 「同代人（朋友/配偶）」挂点 —— 使用者裁定：
#   幽泉 / 圭祖 / 戎吴 等**上下游都够不上**的，找「年龄最相近的合适的人」当同代人；
#   嫪毐 固定挂 **赵姬**（始皇生母，史载嫪毐与太后私通）。
#   走既有机制 `associate_of`（家谱页把同代人排在同一排、带"友"标记），
#   **不写父链、不当推定父子**。
FRIENDS_FIXED = {"嫪毐": "赵姬"}
FRIEND_ROOTS = ("幽泉", "圭祖", "戎吴")     # 其余按"同代+同性+生年最近"自动挑


def pick_friend(people, name, tree):
    """给「朋友/同代人」挑挂点：**同代（世代相同）优先 → 同性 → 生年最接近**。"""
    me = people.get(name) or {}
    g, y, sex = me.get("generation"), year_of(me), me.get("gender")
    if y is None:
        return None, ""
    best, best_key = None, None
    for c in tree:
        if c == name:
            continue
        cy = year_of(people[c])
        if cy is None:
            continue
        key = (0 if people[c].get("generation") == g else 1,
               0 if people[c].get("gender") == sex else 1,
               abs(cy - y))
        if best_key is None or key < best_key:
            best, best_key = c, key
    if best is None:
        return None, ""
    return best, (f"同代人：{best}（第{people[best].get('generation')}代·生"
                  f"{year_of(people[best])}，{name}生{y}，"
                  f"差 {abs(year_of(people[best]) - y)} 年）")


def clan_keys(bio):
    """→ 族名集合（姓 ∪ 氏）；认不出给空集。"""
    bio = str(bio or "")
    out = set()
    m = _XING_SHI.search(bio)
    if m:
        out |= {m.group(1), m.group(2)}
    else:
        m = _XING_ONLY.search(bio)
        if m:
            out.add(m.group(1))
        m = _SHI_ONLY.match(bio)
        if m:
            out.add(m.group(1))
    return {t for t in out if t}


def shi_of(bio):
    """→ 「氏」一个字（"风厉鸟，风氏" → 风；"英布，嬴姓英氏" → 英）。

    ★ 2026-09-30：同氏判定必须认**氏**。原来只比 `clan_keys` 的集合交集，
       而 `风厉鸟，风氏` 这种**只有氏、没写姓**的写法交集恒为 1，
       同氏族人（风丘萤、风封胥…）全被误判成"仅同姓"。
    """
    bio = str(bio or "")
    m = _XING_SHI.search(bio)
    if m:
        return m.group(2)
    m = _SHI_ONLY.match(bio)
    return m.group(1) if m else ""


def xing_shi_pair(bio):
    """bio → (姓, 氏)；认不出给空串（★ 2026-09-27 姓校验用）。"""
    bio = str(bio or "")
    m = _XING_SHI.search(bio)
    if m:
        return (m.group(1), m.group(2))
    m = _SHI_ONLY.match(bio)
    if m:
        return ("", m.group(1))
    m = _XING_ONLY.search(bio)
    return (m.group(1), "") if m else ("", "")


# ★ 2026-09-27 使用者裁定（续十六网查后）：
#   ① 「同氏」必须是**同姓同氏** —— 双方姓可知且不同 ⇒ 不同源，不得虚接
#      （网查实证：孔达(姞孔)→孔伯夏(子孔) 等 A 类 7 条全部错接）。
#   ② 游戏 bio 姓与史料相悖时：**非孤立节点按游戏**，**孤立节点按史料**。
#      史料姓/氏写在这里（仅孤立节点——无事实父/母/子/配偶——生效）：
FACTS_XING = {
    "胥臣": ("姬", "胥"), "蹇叔": ("", "蹇"), "甘龙": ("", "甘"),
    # ★ 2026-09-27 续二十（乙类补齐）：孤立且史料姓明确的再加 6 人 ——
    #   仇氏出自仇牧（宋公族子姓）· 暴氏姬姓（暴国，韩将暴鸢）·
    #   曹氏主源姬姓（曹叔振铎后）· 倪氏出郳国（曹姓）· 颜氏出邾武公颜（曹姓）。
    "仇牧": ("子", "仇"), "仇濮宿": ("子", "仇"),
    "暴鸢": ("姬", "暴"), "曹无伤": ("姬", "曹"),
    "倪良": ("曹", "倪"), "颜聚": ("曹", "颜"),
}


def year_of(rec):
    try:
        return int(str(rec.get("birth") or "").split(",")[0])
    except (ValueError, IndexError):
        return None


def load_people(book):
    fp = os.path.join(PROJ, "saves", book, "family.json")
    return fp, json.load(open(fp, encoding="utf-8"))


def components(people):
    """并查集分量（父/母边）。"""
    parent = {n: n for n in people}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for nm, r in people.items():
        for k in ("father", "mother"):
            o = r.get(k)
            if o and o in people:
                ra, rb = find(nm), find(o)
                if ra != rb:
                    parent[rb] = ra
    comp = collections.defaultdict(set)
    for nm in people:
        comp[find(nm)].add(nm)
    return comp


def main():
    ap = argparse.ArgumentParser(description="推定世系（虚接）")
    ap.add_argument("--book", default="全史存档")
    ap.add_argument("--apply", action="store_true", help="写进谱牒（带备份）")
    args = ap.parse_args()

    fp, data = load_people(args.book)
    people = data["people"]

    # ★ 2026-09-30：**先把史料落定的父应用到内存**，再算分量 ——
    #   否则 `子周` 那支（孔氏 64 人）会因盘上父位为空而仍被当成独立分量，
    #   报告里显示"仍接不上"，看着像没修（其实写盘后才连上）。
    #   这里只改内存；真正写盘在末尾统一做（带 `wrote` 计数与备份）。
    _pre = 0
    for _nm, _dad in (FACTS.get("father") or {}).items():
        if _nm in people and _dad in people:
            people[_nm]["father"] = _dad
            _pre += 1
    if _pre:
        print("史料落定父（先应用后算分量）：%d 条" % _pre)

    comp = components(people)
    tree = set(comp[next(iter([k for k, v in comp.items() if ROOT_NAME in v]))])
    print(f"《{args.book}》：{len(people)} 人 · 分量 {len(comp)} 个 · "
          f"{ROOT_NAME}那棵树 {len(tree)} 人")

    # ---- 待接的根：**每一个**「书内没有事实父母」的人（不只是每个分量最早那个）----
    #   ⚠️ 第一版只取"每分量最早的那个根"，于是一个分量里有多个根时
    #      （实测《全史存档》根节点只从 494 降到 10 就是这个原因），
    #      其余的根仍被画成独立根。改为**逐个根**处理。
    todo = []
    for members in comp.values():
        for m in members:
            if people[m].get("father") in people or people[m].get("mother") in people:
                continue
            todo.append((members, m))
    todo.sort(key=lambda it: year_of(people[it[1]]) if year_of(people[it[1]]) is not None
              else 9999)

    # ★ 2026-09-30：史料能直接定父的（`FACTS["father"]`）**不参与自动推定** ——
    #   否则会被"同族名 + 生年"规则抢走（实测：子周被错接给箕野）。
    #   它们走下面 FACTS 通道，写**事实层**并附依据。
    _fact_dads = set(FACTS.get("father") or {})
    if _fact_dads:
        _skip = sorted(k for _m, k in todo if k in _fact_dads)
        todo = [it for it in todo if it[1] not in _fact_dads]
        if _skip:
            print("史料落定父（不参与自动推定）：%s" % "、".join(_skip))
    # 使用者指定「改挂靠」的：**留在 todo 里**（挂靠分支要用），
    # 只是虚接循环里跳过它们。
    _force = set(FORCE_HOOK)

    # 事实子表（防环用：一次建好，别在循环里扫全谱）
    kids_fact = collections.defaultdict(list)
    for n, r in people.items():
        for k in ("father", "mother"):
            p = r.get(k)
            if p and p in people:
                kids_fact[p].append(n)

    # ★ 2026-09-27：孤立节点（无事实父/母/子/配偶）按史料姓/氏
    #   （FACTS_XING）；非孤立按游戏。锚定两处统一取用。
    def _isolated(nm, rec):
        if rec.get("father") or rec.get("mother") or rec.get("spouse"):
            return False
        if kids_fact.get(nm):
            return False
        return True

    def _xkeys(nm, rec):
        ov = FACTS_XING.get(nm)
        if ov and _isolated(nm, rec):
            return {t for t in ov if t}
        return clan_keys(rec.get("bio"))

    def _xshi(nm, rec):
        ov = FACTS_XING.get(nm)
        if ov and _isolated(nm, rec):
            return ov[1]
        return shi_of(rec.get("bio"))

    # ---- 迭代接枝 ----
    guesses = {}          # 根名 → (推定父, 说明)
    rounds = []
    while True:
        moved = []
        for item in list(todo):
            members, root = item
            if root in EXCLUDE_ROOTS or root in NO_HOOK:
                continue        # 少数民族/冲突未决/拍板断开 —— 不自动接
            # ★ 2026-09-30 使用者规则：**游戏里无父也无子 ⇒ 不是始祖，不虚接**，
            #   留给后面的「同代人挂靠」（实测这类占 378/479 条）。
            if not kids_fact.get(root):
                continue
            # 使用者点名「改挂靠」的，同样不虚接
            if root in _force:
                continue
            rk = _xkeys(root, people[root])
            ry = year_of(people[root])
            if ry is None or not rk:
                continue
            # 防环：不能把某人接到**他自己的后裔**底下（分量内有多个根时可能撞上）
            bad, q = {root}, [root]
            while q:
                cur = q.pop()
                for ch in kids_fact.get(cur, ()):
                    if ch not in bad:
                        bad.add(ch)
                        q.append(ch)
            best = best_y = None
            best_key = None
            s_r = xing_shi_pair(people[root].get("bio"))
            if root in FACTS_XING and _isolated(root, people[root]):
                s_r = FACTS_XING[root]
            for cand in tree:
                if cand in bad:
                    continue
                if not (_xkeys(cand, people[cand]) & rk):
                    continue
                cy = year_of(people[cand])
                if (cy is None or cy >= ry or (ry - cy) < MIN_GAP
                        or (ry - cy) > MAX_GAP):
                    continue
                if not people[cand].get("gender") == "男":
                    continue
                # ★ 2026-09-27「同氏」= **同姓同氏**：氏相同，且（任一方姓
                #   不可知，或姓相同）——网查 A 类实证：姞孔≠子孔。
                s_c = xing_shi_pair(people[cand].get("bio"))
                if cand in FACTS_XING and _isolated(cand, people[cand]):
                    s_c = FACTS_XING[cand]
                if s_r[0] and s_c[0] and s_r[0] != s_c[0]:
                    continue                     # 姓不同 ⇒ 不同源，不虚接
                ck = _xkeys(cand, people[cand])
                same_shi = bool(_xshi(root, people[root])
                                and _xshi(root, people[root])
                                == _xshi(cand, people[cand]))
                key = (0 if same_shi else 1, -cy)      # 同姓同氏排前；再按生年接近
                if best_key is None or key < best_key:
                    best, best_y, best_key = cand, cy, key
            if best is not None:
                moved.append((item, best, sorted(rk & clan_keys(
                    people[best].get("bio")))))
        if not moved:
            break
        rounds.append(len(moved))
        for item, best, _k in moved:
            members, root = item
            guesses[root] = (best, f"推定：同姓同氏『{_k[0]}』，"
                                   f"{best}生{year_of(people[best])}早于"
                                   f"{root}生{year_of(people[root])}")
            tree |= members
            todo.remove(item)
        if len(rounds) > 20:
            break

    # ---- 同代人挂靠（无父无子 / 接不上祖先的）----
    #   ★ 使用者 2026-09-30：
    #     「无头无尾的以及靠不上别人的人，就根据历史，让他们做**同时代同势力
    #       的同代人**，有这个机制，相当于**挂靠在风巢皇始祖树上**」
    #     「彭越、任敖**挂靠到同势力的人身上，以同代人身份**」
    #   ⇒ 依据顺序：**同势力 → 同氏 → 同姓 → 仅同代**；生年窗口 ±60 年。
    hooks = {}                     # 根名 → 挂靠对象
    _bysort = sorted([(year_of(r), n) for n, r in people.items()
                      if year_of(r) is not None])
    _ys = [t[0] for t in _bysort]
    # 已有专用裁定的，不参与通用挂靠（否则会覆盖使用者早先定好的同代人）
    _pre_handled = (set(FRIEND_ROOTS) | set(FRIENDS_FIXED)
                    | set(HANDPICK["associate"]) | set(FACTS["associate"])
                    | set(FACTS.get("father") or {}))
    for members, root in todo:
        if root in EXCLUDE_ROOTS or root in NO_HOOK                 or root in guesses or root in hooks:
            continue
        if root in _pre_handled:
            continue
        r = people[root]
        ry = year_of(r)
        if ry is None:
            continue
        my_st = r.get("state_name") or ""
        rshi = _xshi(root, r)
        rk = _xkeys(root, r)
        s_r = xing_shi_pair(r.get("bio"))
        if root in FACTS_XING and _isolated(root, r):
            s_r = FACTS_XING[root]
        import bisect as _bs
        lo = _bs.bisect_left(_ys, ry - 60)
        hi = _bs.bisect_right(_ys, ry + 60)
        best, best_key = None, None
        for j in range(lo, hi):
            cy, cn = _bysort[j]
            if cn == root or cn in members:
                continue
            c = people[cn]
            same_st = 0 if (my_st and (c.get("state_name") or "") == my_st) else 1
            # ★ 2026-09-27：同氏 rank 也要**同姓**（异姓同氏 = 不同源，
            #   网查 A 类实证）——异姓同氏降为 rank 3（不挂）。
            _s_c = xing_shi_pair(c.get("bio"))
            if cn in FACTS_XING and _isolated(cn, c):
                _s_c = FACTS_XING[cn]
            _xing_diff = bool(_s_c[0] and s_r[0] and _s_c[0] != s_r[0])
            if rshi and _xshi(cn, c) == rshi and not _xing_diff:
                rank = 1
            elif rk and (_xkeys(cn, c) & rk) and not _xing_diff:
                rank = 2
            else:
                rank = 3
            rank = 0 if not same_st else rank       # 同势力最优先
            key = (rank, same_st, abs(cy - ry))
            if best_key is None or key < best_key:
                best, best_key = cn, key
        # ★ 只挂"有依据"的：同势力 / 同氏 / 同姓。三者都不沾 ⇒ 不挂，
        #   宁可让它独立成根，也不乱点鸳鸯（实测这类 150 条，全是硬凑）。
        if best is not None and best_key is not None and best_key[0] != 3:
            hooks[root] = best

    # 去互挂：A→B 且 B→A 时只留一条 —— **保留"晚辈挂长辈"那条**，
    # 删掉"长辈挂晚辈"（后者不合常理：年长者不该以年轻者为锚）。
    # ⚠️ 2026-09-30 踩过：第一版写成 `if ya >= yb: pop(a)`，
    #    正好把晚辈那一条删了（任敖→任嚣 被删，任嚣→任敖 反而留下）。
    for a in list(hooks):
        b = hooks.get(a)
        if not b or hooks.get(b) != a:
            continue
        ya, yb = year_of(people[a]), year_of(people[b])
        if ya is None or yb is None:
            hooks.pop(a, None)          # 拿不准就删当前这条
            continue
        # a 比 b 年轻（生年更晚）⇒ 保留 a→b（晚辈挂长辈），删掉 b→a
        if ya >= yb:
            hooks.pop(b, None)
        else:
            hooks.pop(a, None)

    # ---- 手工裁定 ----
    for root, anchor in HANDPICK["associate"].items():
        if root in people:
            guesses[root] = (None, f"同代人：{anchor}（按游戏生卒年）")
    for root, anc in HANDPICK["father_guess"].items():
        if root in people:
            guesses[root] = (anc, f"推定父：{anc}（按游戏生卒年，时间最近的上游）")

    print(f"接枝轮次 {rounds} ⇒ 自动推定 {len(guesses)} 支 · "
          f"树 {len(tree)} 人")
    print("\n推定清单（前 16 条，含代差）：")
    for root, (dad, note) in list(guesses.items())[:16]:
        print(f"   {root:<10} → {dad or '（同代人）':<10} 差 "
              f"{abs((year_of(people.get(dad, {})) or 0) - (year_of(people[root]) or 0))}"
              f" 年　{note}")
    print("\n按史料/传说**直接落定**（不算推定）：")
    for nm in FACTS["associate"]:
        print(f"   {nm} —— 同代人 {FACTS['associate'][nm]}"
              f"（并为 {[k for k, v in FACTS['mother'].items() if v == nm]} 之母）")
    for nm, dad in (FACTS.get("father") or {}).items():
        if nm in people and dad in people:
            print(f"   {nm}（第{people[nm].get('generation')}代·生"
                  f"{year_of(people[nm])}） —— **父 {dad}**（第"
                  f"{people[dad].get('generation')}代·生{year_of(people[dad])}）"
                  f"　依据：{FACT_FATHER_NOTE.get(nm, '史料')}")
    print("\n按生卒年**单独裁定**：")
    for nm, anc in HANDPICK["associate"].items():
        print(f"   {nm}（第{people[nm].get('generation')}代·生"
              f"{year_of(people[nm])}） —— 同代人 {anc}（第"
              f"{people[anc].get('generation')}代·生{year_of(people[anc])}）")
    for nm, anc in HANDPICK["father_guess"].items():
        print(f"   {nm}（第{people[nm].get('generation')}代·生"
              f"{year_of(people[nm])}） —— 推定父 {anc}（第"
              f"{people[anc].get('generation')}代·生{year_of(people[anc])}）")
    # ---- 「同代人（朋友/配偶）」挂点 ----
    friend_anchor = {}
    for root in FRIEND_ROOTS:
        if root not in people:
            continue
        anchor, note = pick_friend(people, root, tree)
        if anchor:
            guesses[root] = (None, note)
            friend_anchor[root] = anchor
    for root, anchor in FRIENDS_FIXED.items():
        if root in people and anchor in people:
            guesses[root] = (None, f"同代人·配偶：{anchor}"
                                   f"（第{people[anchor].get('generation')}代）"
                                   f"——史载其与太后私通")
            friend_anchor[root] = anchor

    print("\n按「同代人（朋友/配偶）」挂点（不写父链）：")
    for root, anchor in friend_anchor.items():
        print(f"   {root}（第{people[root].get('generation')}代·生"
              f"{year_of(people[root])}） —— 同代人 {anchor}"
              f"（第{people[anchor].get('generation')}代·生"
              f"{year_of(people[anchor])}）")

    print("\n按「同代人挂靠」（无父无子 / 靠不上祖先的）：%d 条" % len(hooks))
    _hstat = collections.Counter()
    for root, anchor in hooks.items():
        c = people[anchor]
        same_st = (people[root].get("state_name") or "") == (c.get("state_name") or "")
        same_shi = bool(shi_of(people[root].get("bio"))
                        and shi_of(people[root].get("bio")) == shi_of(c.get("bio")))
        same_xing = bool(clan_keys(people[root].get("bio"))
                         & clan_keys(c.get("bio")))
        _hstat["同势力" if same_st else
               ("同氏" if same_shi else ("同姓" if same_xing else "其他"))] += 1
    for k, v in _hstat.most_common():
        print("   %-6s %3d 条" % (k, v))
    print("   （样例，前 10）")
    for root, anchor in list(hooks.items())[:10]:
        print("     %-10s → %-10s 差 %s 年"
              % (root, anchor,
                 abs((year_of(people[anchor]) or 0) - (year_of(people[root]) or 0))))

    handled = (set(HANDPICK["associate"]) | set(HANDPICK["father_guess"])
               | set(FACTS["associate"]) | set(FACTS.get("father") or {})
               | set(FRIENDS_FIXED) | set(FRIEND_ROOTS) | set(hooks))
    todo = [it for it in todo if it[1] not in handled]
    print("\n仍接不上的：")
    for members, root in sorted(todo, key=lambda i: -len(i[0])):
        print(f"   {root:<12} 族名{sorted(clan_keys(people[root].get('bio')))} "
              f"第{people[root].get('generation')}代 · {len(members)} 人")

    if not args.apply:
        print("\n（演习，未写盘 —— 加 --apply 生效）")
        return 0

    # ---- 写盘 ----
    # ★ 2026-09-30 踩过的坑：本脚本**只写新值、不清旧值**，于是上一次留下的
    #   `father_guess` / `associate_of` 会和这一次的结果并存（实测：
    #   `任敖` 本轮该挂靠，盘上却留着上一轮的"虚接 任崇"；
    #   `任嚣→任敖` 这条互挂在上一轮写下后，本轮去重删了内存里的，盘上没删）。
    #   ⇒ 重建推定层：先全谱清空，再按本轮结果写回。
    _cleared = 0
    for _n, _r in people.items():
        for _k in ("father_guess", "associate_of", "guess_note"):
            if _r.get(_k) is not None:
                _r.pop(_k, None)
                _cleared += 1
    if _cleared:
        print("清理旧推定字段：%d 处" % _cleared)
    # ★ 势力校正（网查拍板）：按史料改 state_name
    _st_fix = 0
    for _nm, _st in FACTS_STATE.items():
        _r = people.get(_nm)
        if _r is not None and _r.get("state_name") != _st:
            print(f"势力校正：{_nm} {_r.get('state_name')!r} → {_st!r}")
            _r["state_name"] = _st
            _st_fix += 1
    if _st_fix:
        print(f"势力校正共 {_st_fix} 人")
    wrote = 0
    for root, (dad, note) in guesses.items():
        if dad:
            people[root]["father_guess"] = dad
            people[root]["guess_note"] = note
            wrote += 1
        else:
            people[root]["associate_of"] = (
                friend_anchor.get(root) or HANDPICK["associate"].get(root) or "")
            people[root]["guess_note"] = note
            wrote += 1
    for nm, ref in FACTS["associate"].items():
        if nm in people:
            people[nm]["associate_of"] = ref
            people[nm]["guess_note"] = f"同代人：{ref}（按史料/传说）"
            wrote += 1
    # ★ 同代人挂靠（不做父子，只标明"同时代同势力"，家谱页把两人排同一排）
    for root, anchor in hooks.items():
        c = people[anchor]
        same_st = (people[root].get("state_name") or "") == (c.get("state_name") or "")
        people[root]["associate_of"] = anchor
        people[root]["guess_note"] = (
            f"同代人挂靠：{anchor}（{'同势力' if same_st else '同代'}"
            f"·生{year_of(c)}，差 "
            f"{abs((year_of(c) or 0) - (year_of(people[root]) or 0))} 年）")
        people[root].pop("father_guess", None)   # 明确不做推定父子
        wrote += 1
    for nm, sp in FACTS["spouse"].items():
        if nm in people:
            lst = people[nm].setdefault("spouses", [])
            if sp not in lst:
                lst.append(sp)
    for nm, mom in FACTS["mother"].items():
        if nm in people:
            people[nm]["mother"] = mom
            people[nm]["mother_note"] = "按史料/传说落定（非推定）"
    # ★ 史料落定的父（写**事实层**）—— 并**清掉该人身上可能存在的推定父**，
    #   否则事实边与推定边两层打架（家谱页会同时画实线与灰虚线）。
    for nm, dad in (FACTS.get("father") or {}).items():
        if nm in people and dad in people:
            people[nm]["father"] = dad
            people[nm]["father_note"] = FACT_FATHER_NOTE.get(nm, "按史料落定（非推定）")
            people[nm].pop("father_guess", None)
            people[nm].pop("guess_note", None)
            wrote += 1
    # ★ 2026-09-26 使用者要求：少数民族孤根「放风巢皇节点的右侧去」——
    #   给它们打 `root_group = separate`，布局把这类根排到最后（画布最右）。
    for _m, _r in todo:
        if _r in EXCLUDE_ROOTS:
            people[_r]["root_group"] = "separate"
            wrote += 1
    data.setdefault("source", {})["guess_note"] = (
        "含推定世系（father_guess / associate_of）：见《推定世系清单》")
    write_atomic(fp, data, keep_backup=True)
    print(f"\n已写 {fp}（推定 {wrote} 条，带备份）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
