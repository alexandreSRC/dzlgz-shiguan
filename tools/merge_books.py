# -*- coding: utf-8 -*-
"""全史册工程 · 跨档合并器（第七十批）—— 把 staging 里的 N 个剧本档并成《全史存档》。

一句话：**横向按 `Ren_Code` 去重、纵向按血缘并集，事实众数裁决、身份上报待裁。**

实测口径（2026-09-25，32 档 / 76840 条 / 13527 人）：
  · 姓名、性别、生年、卒年 —— 跨档**零值冲突**（只有「一档有、一档无」的覆盖面差异）；
  · `generation`（世代）—— 61% 跨档不一致 ⇒ **不投票，按合并后的血缘图重算**；
  · 势力/世系/封国/封代 —— 38%~84% 不一致，且语义是「**他在这盘里挂着哪国宗庙**」
    （周文王姬昌在七国之乱档是「朝鲜王」）⇒ **只保留全档一致的**，其余留空并进清单；
  · 小传 —— 全部重新生成（旧文本含单档语境的「为某国国君」）；
  · 重名序数跨档会漂（414 例，其中 413 例只是序数不同）⇒ **先剥序数、合并后统一重编号**。

用法：
  python tools/merge_books.py                 # 演习：只出报告，写到 _scratch/
  python tools/merge_books.py --apply         # 落盘 saves/全史存档/
  python tools/merge_books.py --report-lines 200
"""
import argparse
import glob
import heapq
import io
import json
import os
import re
import sys
import time
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools.import_from_game import cn_num, write_atomic   # noqa: E402

STAGING = os.path.join(ROOT, "staging")
BOOK = "全史存档"

_DIGITS = re.compile(r"\d+$")
_SHI = re.compile(r"^[^，]{1,12}，([^，。]{1,6})氏")

# 扩展字段里「数值型」的几个：**0 也是真值**（等级 0 = 庶、智略 0 是合法分数）。
# 把它们当空，庶就会整片丢掉（详见 enrich_staging.py 同名说明）。
_NUMERIC_EXTRA = ("Ren_Leve", "Ren_Zhi_Lue")


def _extra_filled(k, v):
    """扩展字段的「有值」判据 —— 数值型认 0。"""
    if k in _NUMERIC_EXTRA:
        return v is not None and v != ""
    return filled(v)


# ---------------------------------------------------------------- 基础工具
def base_name(nm):
    """剥掉重名序数（「张买2」→「张买」）。"""
    return _DIGITS.sub("", nm or "")


def filled(v):
    return v not in (None, "", 0, [], {})


def vote(counter):
    """众数：票数最多；并列时取**值较小**的那个（保证可复现）。"""
    if not counter:
        return None
    top = max(counter.values())
    return sorted(k for k, v in counter.items() if v == top)[0]


def year_of(v):
    """'−1152,7,0' / [-1152,7,0] → −1152（取不到返回 None）。"""
    if v is None or v == "":
        return None
    if isinstance(v, (list, tuple)) and v:
        v = v[0]
    p = str(v).split(",")[0].strip()
    try:
        return int(float(p))
    except ValueError:
        return None


def ytext(y):
    if y is None:
        return ""
    return f"前{abs(y)}年" if y < 0 else f"{y}年"


def load_staging():
    docs = []
    for era in sorted(os.listdir(STAGING)):
        d1 = os.path.join(STAGING, era)
        if not os.path.isdir(d1):
            continue
        for tag in sorted(os.listdir(d1)):
            p = os.path.join(d1, tag, "family.json")
            if not os.path.isfile(p):
                continue
            data = json.load(open(p, encoding="utf-8"))
            people = data["people"]
            docs.append({
                "era": era, "slot": data["source"].get("slot", "?"),
                "start_year": data["source"].get("start_year"),
                "path": os.path.relpath(p, ROOT).replace("\\", "/"),
                "people": people,
                "by_name": {nm: str(r.get("code")) for nm, r in people.items()},
            })
    return docs


# ---------------------------------------------------------------- 合并主体
def merge(docs):
    """→ (people, 报告数据)。people 仍是 {最终姓名: 记录}。"""
    appear = defaultdict(list)          # code -> [(doc, name, rec)]
    for d in docs:
        for nm, rec in d["people"].items():
            appear[str(rec.get("code"))].append((d, nm, rec))

    codes = sorted(appear, key=lambda c: (len(c), c))
    out_db = {}
    rep = {
        "conflict": defaultdict(list),   # 关键词 -> [(code, 明细)]
        "n_appear": Counter(),
        "adopt": Counter(),              # 身份字段的采纳人数
    }

    for code in codes:
        rows = appear[code]
        rep["n_appear"][len(rows)] += 1

        # ---- 1. 姓名（剥序数后投票）----
        cn = Counter(base_name(nm) for _d, nm, _r in rows)
        name = vote(cn)
        if len(cn) > 1:
            rep["conflict"]["姓名"].append(
                (code, sorted(cn.items(), key=lambda x: -x[1])))

        # ---- 2. 事实字段：非空众数 ----
        def fact(key, norm=lambda v: v):
            c = Counter()
            for _d, _nm, r in rows:
                v = r.get(key)
                if filled(v):
                    c[norm(v)] += 1
            if len(c) > 1:
                rep["conflict"][key].append(
                    (code, sorted(c.items(), key=lambda x: -x[1])))
            return vote(c)

        gender = fact("gender")
        birth = fact("birth", lambda v: json.dumps(v, ensure_ascii=False))
        death = fact("death", lambda v: json.dumps(v, ensure_ascii=False))
        birth = json.loads(birth) if birth else ""
        death = json.loads(death) if death else ""
        rank = fact("rank")
        divine = fact("divine")
        note = fact("note")
        st_group = fact("state_group")

        # ---- 3. 血缘：把父/母**解析成编号**再投票 ----
        def kin(key):
            c = Counter()
            missing = 0
            for d, _nm, r in rows:
                pnm = r.get(key)
                if not filled(pnm):
                    continue
                pc = d["by_name"].get(pnm)
                if pc is None:
                    missing += 1
                else:
                    c[pc] += 1
            if len(c) > 1:
                rep["conflict"]["血缘_" + key].append(
                    (code, sorted(c.items(), key=lambda x: -x[1])))
            return vote(c), dict(c), missing

        father, f_all, f_miss = kin("father")
        mother, m_all, m_miss = kin("mother")

        # ---- 4. 配偶：并集（解析成编号）----
        sp = set()
        for d, _nm, r in rows:
            for snm in (r.get("spouses") or []):
                sc = d["by_name"].get(snm)
                if sc:
                    sp.add(sc)

        # ---- 5. 身份：分字段「非空众数」采纳（并列弃权，冲突照旧上报）----
        #   ★ 2026-09-25 架构评审后修订：初版「四元组全档一致才写」过严 ——
        #   爵位字符（王/公/侯/伯/子/帝）跨剧本基本稳定，实测 2431 个有爵者
        #   能恢复 2335 个；而四元组整体一致的只剩 6800。改成**逐字段投票**：
        #   · 爵位/势力/世系：非空众数，唯一才采纳，并列弃权；
        #   · 封代：只在势力（或世系）采纳后，**在匹配该势力的档里**投，
        #     唯一才写（封代离开势力没有意义）；
        #   · 宗庙归属跨剧本会漂（周文王在七国之乱档挂朝鲜宗庙），众数给的是
        #     「最常被挂的宗庙」，所有不一致照旧进《身份裁决清单》。
        combos = Counter()
        for _d, _nm, r in rows:
            key = (r.get("state_name") or "", r.get("lineage_name") or "",
                   r.get("fief_title") or "", r.get("fief_gen") or 0)
            if any(key[:3]) or key[3]:
                combos[key] += 1
        if len(combos) > 1:
            rep["conflict"]["身份"].append(
                (code, sorted(combos.items(), key=lambda x: -x[1])))

        def field_vote(getter):
            c = Counter()
            for _d, _nm, r in rows:
                v = getter(r)
                if filled(v):
                    c[v] += 1
            if not c:
                return None
            top = max(c.values())
            cands = [k for k, v in c.items() if v == top]
            return cands[0] if len(cands) == 1 else None

        f_title = field_vote(lambda r: r.get("fief_title"))
        f_state = field_vote(lambda r: r.get("state_name"))
        f_lin = field_vote(lambda r: r.get("lineage_name"))
        f_gen = 0
        if f_state or f_lin:
            g = Counter()
            for _d, _nm, r in rows:
                if ((f_state and r.get("state_name") == f_state)
                        or (f_lin and r.get("lineage_name") == f_lin)):
                    v = r.get("fief_gen")
                    if filled(v):
                        g[v] += 1
            if len(g) == 1:
                f_gen = next(iter(g))
        ident = (f_state or "", f_lin or "", f_title or "", f_gen or 0)
        if f_title:
            rep["adopt"]["爵位"] = rep["adopt"].get("爵位", 0) + 1
        if f_state:
            rep["adopt"]["势力"] = rep["adopt"].get("势力", 0) + 1
        if f_lin:
            rep["adopt"]["世系"] = rep["adopt"].get("世系", 0) + 1
        if f_gen:
            rep["adopt"]["封代"] = rep["adopt"].get("封代", 0) + 1

        # ---- 5b. 原文扩展字段（enrich_staging 从各档存档回捞）----
        #   人物卡上该有的字段（智略/等级/文化/性格/谥号/表字/继位/族谱世代/
        #   所在/官职/政策/能力/特质）family.json 原本没有 —— 由
        #   tools/enrich_staging.py 从 32 个源存档逐人回捞到 `extra`。
        #   合并口径：标量/字典 = 非空众数（并列取**开局年最晚**的档 =
        #   人物最后状态）；数组（政策/能力/特质）= **并集**（一生所见全收）。
        keys = set()
        for _d, _nm, r in rows:
            keys |= set(r.get("extra") or {})
        extra = {}
        for k in sorted(keys):
            #   ★ 2026-09-25 使用者裁定：**世代用合并器重算的 `generation`**，
            #   原文的族谱世代 `Ren_Dai_Shu` **不采纳** —— 它是「单个剧本档里
            #   族谱的第几代」，跨 32 档口径不一（实测嬴政：原文 71 / 合并 82），
            #   带进谱牒只会让「人物页」与「家谱页」两个世代数打架。
            if k == "Ren_Dai_Shu":
                continue
            items = []
            for _d, _nm, r in rows:
                v = (r.get("extra") or {}).get(k)
                if _extra_filled(k, v):
                    items.append((_d.get("start_year") or -99999, v))
            if not items:
                continue
            if isinstance(items[0][1], list):
                seen_, out_ = set(), []
                for _y, it in items:
                    canon = json.dumps(it, ensure_ascii=False, sort_keys=True)
                    if canon not in seen_:
                        seen_.add(canon)
                        out_.append(it)
                extra[k] = out_
            else:
                c = Counter(json.dumps(v, ensure_ascii=False, sort_keys=True)
                            for _y, v in items)
                top = max(c.values())
                cands = [s for s, n in c.items() if n == top]
                if len(cands) > 1:                 # 并列 → 取最晚档
                    pick = max(
                        (y, json.dumps(v, ensure_ascii=False, sort_keys=True))
                        for y, v in items
                        if json.dumps(v, ensure_ascii=False,
                                      sort_keys=True) in cands)[1]
                else:
                    pick = cands[0]
                extra[k] = json.loads(pick)
                if len(c) > 1:
                    rep["conflict"]["extra_" + k].append(
                        (code, sorted(c.items(), key=lambda x: -x[1])))
        if extra:
            rep["adopt"]["扩展字段"] = rep["adopt"].get("扩展字段", 0) + 1
            for k, n in (("Ren_Zhi_Lue", "智略"), ("Ren_Wen_Hua", "文化"),
                         ("Ren_Xing_Ge", "性格"), ("Ren_Leve", "等级"),
                         ("Ren_Zun_Hao", "谥号"),
                         ("Ren_Zheng_Ce_Array", "政策"),
                         ("Ren_Neng_Li_Array", "能力"),
                         ("Buff_Array", "特质"),
                         ("Last_Ren_Official_Position_Data", "官职")):
                if filled(extra.get(k)):
                    rep["adopt"]["ext_" + n] = rep["adopt"].get("ext_" + n, 0) + 1

        # ---- 6. 氏（从小传里抠，用于重生成小传）----
        shi = Counter()
        for _d, _nm, r in rows:
            m = _SHI.match(str(r.get("bio") or ""))
            if m:
                shi[m.group(1)] += 1
        shi = vote(shi) or ""

        out_db[code] = {
            "code": code, "name": name,
            "gender": gender or "", "birth": birth, "death": death,
            "rank": rank or 0, "divine": divine, "note": note or "",
            "state_group": st_group or "",
            "father_code": father, "mother_code": mother,
            "spouse_codes": sorted(sp, key=lambda c: (len(c), c)),
            "ident": ident,
            "extra": extra,
            "shi": shi,
            "n_docs": len(rows),
            "eras": sorted({d["era"] for d, _n, _r in rows}),
            "birth_year": year_of(birth),
            "father_all": f_all, "mother_all": m_all,
            "father_missing": f_miss, "mother_missing": m_miss,
        }

    # ---- 6b. 清「占位假人」：名字以 父/祖/曾/高 结尾、又无生卒的空壳 ----
    #   游戏会给「某某之父」硬造一个只有名字的假人（实测：田广明父 66313，
    #   编号还在史实号段里，项目现行的**编号后缀**判据抓不到它）。
    #   三重条件防误伤：① 名字以后缀结尾；② 无生年**且**无卒年
    #   （真史实如 嫫祖/庆父 有完整生卒）；③ 剥掉后缀后的本名也在谱里
    #   （「田广明父」→「田广明」在谱）。命中的从谱里剔除，其子女的父/母
    #   链接就地断开 —— 子女改按自己的生年锚定。
    all_names = {out_db[c]["name"] for c in codes}
    placeholders = set()
    for c in codes:
        x = out_db[c]
        if (x["name"].endswith(("父", "祖", "曾", "高"))
                and not filled(x["birth"]) and not filled(x["death"])):
            base = x["name"][:-1]          # 剥掉后缀字：「田广明父」→「田广明」
            if base and base in all_names:
                placeholders.add(c)
    if placeholders:
        for c in placeholders:
            nm = out_db[c]["name"]
            for other in codes:
                if other in placeholders or other == c:
                    continue
                x = out_db[other]
                if x["father_code"] == c:
                    x["father_code"] = None
                if x["mother_code"] == c:
                    x["mother_code"] = None
            rep.setdefault("placeholders", []).append(
                (c, nm, out_db[c]["birth_year"]))
    codes = [c for c in codes if c not in placeholders]

    # ---- 7. 世代：多源最长路 DP + 生年锚定（★ 架构评审 v3 定稿）----
    #   为什么不能投票：同一个张新（66766）在五个档里量出 65/48/97 ——
    #   每档只收「该档在场的人」，父链长度各异；投票只会选中某一档的局部答案。
    #
    #   此前两版都败在「组件 + 单锚点」：v1 把 462 个断链根压成第 1 代；
    #   v2 婚姻并网后又把霍仲孺（断链根）吸进上古组件、同样落成第 1 代。
    #   定稿模型改成**每个顶各自锚定 + 最长路下传**：
    #   ① 「顶」（无父/母在谱者）按**自己的生年**在滚动参考曲线（已定稿者的
    #      生年→世代散点）上取中位数，窗口 ±3 年起、×3 扩到 ±4000；
    #      顶按生年升序处理 —— 最早的顶（风巢皇 生前2580）无曲线可依，
    #      自然 = 第 1 代，与游戏自带标尺 GEN_CENTER（第1代=前2580）对齐；
    #   ② 非顶者 = max(父, 母) + 1，**全部父母定稿后才定稿**（工作清单）——
    #      子 > 父/母 由构造保证；娶入的母亲按自己的生年落位，不再被夫家吸走；
    #   ③ 环上等极少数兜底按生年插值，计数上报。
    kids = defaultdict(list)
    rem = {}
    for c in codes:
        ps = {p for p in (out_db[c]["father_code"], out_db[c]["mother_code"])
              if p and p in out_db}
        rem[c] = len(ps)
        for p in ps:
            kids[p].append(c)

    ref_Y, ref_G = [], []            # 已定稿者的（生年, 世代）参考曲线

    def add_ref(c):
        b = out_db[c]["birth_year"]
        if b is not None:
            i = bisect_left(ref_Y, b)
            ref_Y.insert(i, b)
            ref_G.insert(i, gen_final[c])

    def interp(birth):
        w = 3
        while w <= 4000:
            i, j = bisect_left(ref_Y, birth - w), bisect_right(ref_Y, birth + w)
            if j > i:
                gs = sorted(ref_G[i:j])
                return gs[len(gs) // 2]
            w *= 3
        return None

    gen_final = {}
    rep["anchor"] = {"tops": 0, "interp": 0, "no_birth": 0, "first": 0,
                     "cycle": 0}

    def finalize(c, g):
        """定稿一人：记值、进参考曲线、解锁子女（连锁到不能再连锁）。"""
        gen_final[c] = g
        add_ref(c)
        stack = [c]
        while stack:
            x = stack.pop()
            for ch in kids.get(x, []):
                if ch in gen_final:
                    continue
                rem[ch] -= 1
                if rem[ch]:
                    continue          # 还有父母没定稿，等
                gs = [gen_final[p] for p in
                      (out_db[ch]["father_code"], out_db[ch]["mother_code"])
                      if p and p in out_db]
                gen_final[ch] = (max(gs) + 1) if gs else 1
                add_ref(ch)
                stack.append(ch)

    # 顶按生年升序入堆（无生年排最后）
    heap = [((out_db[c]["birth_year"] if out_db[c]["birth_year"] is not None
              else 99999), c) for c in codes if rem[c] == 0]
    heapq.heapify(heap)
    while heap:
        _b, c = heapq.heappop(heap)
        if c in gen_final:
            continue
        rep["anchor"]["tops"] += 1
        b = out_db[c]["birth_year"]
        a = interp(b) if (b is not None and ref_Y) else None
        if a is not None:
            rep["anchor"]["interp"] += 1
        else:
            if b is None:
                rep["anchor"]["no_birth"] += 1
            elif not ref_Y:
                rep["anchor"]["first"] += 1
            a = 1
        finalize(c, a)

    # 兜底：环上等没被连锁到的人（极少数）—— 按生年插值，且尊重已定稿的父母
    for c in sorted((c for c in codes if c not in gen_final),
                    key=lambda c: (out_db[c]["birth_year"] is None,
                                   out_db[c]["birth_year"] or 0)):
        rep["anchor"]["cycle"] += 1
        b = out_db[c]["birth_year"]
        cand = [interp(b)] if (b is not None and ref_Y) else []
        cand += [gen_final[p] + 1 for p in
                 (out_db[c]["father_code"], out_db[c]["mother_code"])
                 if p and p in out_db and p in gen_final]
        finalize(c, max(cand) if cand else 1)
    for code in codes:
        out_db[code]["generation"] = gen_final[code]

    rep["depth_hist"] = Counter(out_db[c]["generation"] for c in codes)
    rep["roots"] = sum(1 for c in codes
                       if not out_db[c]["father_code"]
                       and not out_db[c]["mother_code"])

    # 硬不变量：有父/母在谱的人，世代必须**严格大于**父/母（布局的前提）
    bad = []
    for c in codes:
        for p in (out_db[c]["father_code"], out_db[c]["mother_code"]):
            if p in out_db and out_db[c]["generation"] <= out_db[p]["generation"]:
                bad.append((c, p))
    rep["gen_violations"] = bad
    rep["unresolved"] = sum(1 for c in codes
                            if out_db[c]["father_missing"] or out_db[c]["mother_missing"])

    # ---- 8. 重名重编号（跨档统一）----
    groups = defaultdict(list)
    for code in codes:
        groups[out_db[code]["name"]].append(code)
    final_name = {}
    rep["dup_groups"] = 0
    for nm, cs in groups.items():
        if len(cs) == 1:
            final_name[cs[0]] = nm
            continue
        rep["dup_groups"] += 1
        cs.sort(key=lambda c: (out_db[c]["birth_year"] is None,
                               out_db[c]["birth_year"] or 0,
                               len(c), c))
        for i, c in enumerate(cs):
            final_name[c] = nm if i == 0 else nm + str(i + 1)
    rep["dup_members"] = sum(len(cs) for cs in groups.values() if len(cs) > 1)

    # ---- 9. 落成记录（父/母/配偶换成最终姓名）----
    kids = defaultdict(list)
    for code in codes:
        for key in ("father_code", "mother_code"):
            p = out_db[code][key]
            if p:
                kids[p].append(code)

    people = {}
    for code in codes:
        x = out_db[code]
        nm = final_name[code]
        ident = x["ident"] or ("", "", "", 0)
        st, ln, ti, fg = ident
        people[nm] = {
            "code": code,
            "father": final_name.get(x["father_code"], ""),
            "mother": final_name.get(x["mother_code"], ""),
            "gender": x["gender"],
            "generation": x["generation"],
            "historical": "是",
            "divine": x["divine"],
            "birth": x["birth"],
            "death": x["death"],
            "rank": x["rank"],
            "spouses": [final_name[c] for c in x["spouse_codes"]
                        if c in final_name],
            "state_group": x["state_group"],
            "state_name": st,
            "lineage_name": ln,
            "fief_title": ti,
            "fief_gen": fg,
            "note": x["note"],
            "bio": "",
        }
        if x.get("extra"):                 # 原文扩展字段（智略/等级/政策…）
            people[nm]["extra"] = x["extra"]
        people[nm]["bio"] = make_bio(nm, x, kids.get(code, []), final_name)
    return people, out_db, rep


# ---------------------------------------------------------------- 小传重生成
def make_bio(nm, x, kid_codes, final_name):
    """合并版小传：只说**站得住**的话 —— 姓名/氏、生卒、一致身份、婚育。

    ⚠️ 按使用者裁定：**不写年龄、不写享年、不写余寿**（全史谱跨 2500 年，
       没有单一参照年，写出来就是错的）。
    """
    sents = []
    sents.append(f"{nm}，{x['shi']}氏。" if x["shi"] else nm + "。")

    by, dy = year_of(x["birth"]), year_of(x["death"])
    if by is not None and dy is not None:
        sents.append(f"约生于{ytext(by)}，卒于{ytext(dy)}。")
    elif by is not None:
        sents.append(f"约生于{ytext(by)}。")
    elif dy is not None:
        sents.append(f"卒于{ytext(dy)}。")

    st, ln, ti, fg = x["ident"] or ("", "", "", 0)
    mid = ""
    if ti and (st or ln):
        mid = f"为{st or ln}国君"
        if fg:
            mid += f"，第{cn_num(fg)}代"
        mid += f"，爵为{ti}"
    elif ti:
        mid = f"爵为{ti}"
    elif st or ln:
        mid = f"属{st or ln}"
    if x["note"]:
        mid = (mid + "，" if mid else "") + x["note"]
    mid = (mid + "，" if mid else "") + "史传有载"
    sents.append(mid + "。")

    wed = ""
    sp = [final_name[c] for c in x["spouse_codes"][:3] if c in final_name]
    if sp:
        wed = ("娶" if x["gender"] != "女" else "适") + "、".join(sp)
    kn = [final_name[c] for c in kid_codes[:3] if c in final_name]
    if kn:
        wed += ("，" if wed else "") + \
               ("有子" if x["gender"] != "女" else "生子") + "、".join(kn)
    if wed:
        sents.append(wed + "。")
    return "".join(sents)


# ---------------------------------------------------------------- 报告
def build_reports(people, db, rep, docs, lines):
    L = []
    A = L.append
    A("《全史存档》合并报告" + " " * 20 + time.strftime("%Y-%m-%d %H:%M"))
    A("=" * 78)
    A(f"来源档数 {len(docs)} · 抽取记录 {sum(len(d['people']) for d in docs)} 条")
    A(f"去重后人数 {len(people)}")
    A(f"跨档复现：出现在 ≥2 档的 {len(people) - rep['n_appear'].get(1, 0)} 人")
    A(f"根源（父母都不在谱）{rep['roots']} 人")
    A(f"世代不变量（子 > 父）：违例 {len(rep['gen_violations'])} 例"
      + ("  ✅" if not rep["gen_violations"] else "  ⚠️"))
    A(f"父母引用未解析（父/母名字在该档没找到人）：{rep['unresolved']} 人")
    ph = rep.get("placeholders") or []
    A(f"占位假人剔除（名字带 父/祖/曾/高 后缀且无生卒）：{len(ph)} 人"
      + ("　" + "、".join(n for _c, n, _b in ph[:6]) + ("…" if len(ph) > 6 else "")
         if ph else ""))
    an = rep.get("anchor", {})
    A(f"世代锚定：顶 {an.get('tops', 0)} 个 —— 按生年插值 {an.get('interp', 0)} ·"
      f" 最早者锚1 {an.get('first', 0)} · 无生年兜底 {an.get('no_birth', 0)} ·"
      f" 环上兜底 {an.get('cycle', 0)}")
    g1 = [db[c]["birth_year"] for c in db
          if "generation" in db[c]
          and db[c]["generation"] == 1 and db[c]["birth_year"] is not None]
    if g1:
        A(f"第 1 代共 {len(g1)} 人，最晚生者 前{abs(min(g1))}"
          + ("  ✅（都是上古始祖）" if min(g1) <= -2000 else "  ⚠️（有晚生者混入！）"))
    A("")
    A("【各字段跨档值冲突】（只在「两边都有值」之间比）")
    for k in ("姓名", "gender", "birth", "death", "rank", "note", "divine",
              "state_group", "身份", "血缘_father", "血缘_mother"):
        n = len(rep["conflict"].get(k, []))
        A(f"    {k:<14}{n:>6} 人")
    A("")
    A("【身份采纳（分字段众数，并列弃权）】")
    for k in ("爵位", "势力", "世系", "封代"):
        A(f"    {k:<6}{rep.get('adopt', {}).get(k, 0):>6} 人")
    A("【原文扩展字段采纳（众数/并集，来自各档存档原文）】")
    for k in ("智略", "文化", "性格", "等级", "谥号", "政策", "能力", "特质", "官职"):
        A(f"    {k:<6}{rep.get('adopt', {}).get('ext_' + k, 0):>6} 人")
    A("")
    A("【世代（锚定后）分布】")
    hist = rep["depth_hist"]
    A("    " + "  ".join(f"第{g}代:{n}" for g, n in sorted(hist.items())[:12])
      + (f"  …共 {len(hist)} 档" if len(hist) > 12 else ""))
    A("")
    A("【重名】")
    A(f"    重名组 {rep['dup_groups']} 组 · 涉及 {rep['dup_members']} 人"
      f"（合并后统一重编号）")
    A("")
    A("【抽样核对】")
    for nm in ("风女娲", "姬昌", "嬴政", "刘邦"):
        if nm in people:
            p = people[nm]
            A(f"    {nm}：生 {p['birth']} 卒 {p['death']} 世代 {p['generation']} "
              f"势力 {p['state_name'] or '—'} 爵 {p['fief_title'] or '—'}")
            A(f"        {p['bio']}")
    A("")

    # ---- 身份裁决清单 ----
    A("=" * 78)
    A(f"身份裁决清单（{len(rep['conflict'].get('身份', []))} 人 · 下面前 {lines} 人）")
    A("格式：编号｜姓名｜档数 ‖ 组合(票数) —— 「众数候选」= 票最多的那条")
    A("-" * 78)
    for code, combos in sorted(rep["conflict"].get("身份", []),
                               key=lambda x: -len(x[1]))[:lines]:
        nm = db[code]["name"]
        A(f"{code}｜{nm}｜{db[code]['n_docs']} 档")
        for (st, ln, ti, fg), n in combos[:6]:
            A(f"      势力 {st or '—':<5} 世系 {ln or '—':<6} 爵 {ti or '—':<4} "
              f"封代 {fg:<3} （{n} 档）")
        if len(combos) > 6:
            A(f"      …另 {len(combos) - 6} 种")
    A("")

    # ---- 血缘争议清单 ----
    kin = [(c, d) for c, d in rep["conflict"].get("血缘_father", [])] + \
          [(c, d) for c, d in rep["conflict"].get("血缘_mother", [])]
    A("=" * 78)
    A(f"血缘争议清单（{len(kin)} 人 · 前 {lines} 人）—— 同一人在不同档里父亲/母亲不同")
    A("格式：编号｜姓名｜档数‖ 候选父(母)编号(票数)")
    A("-" * 78)
    for code, detail in kin[:lines]:
        A(f"{code}｜{db[code]['name']}｜{db[code]['n_docs']} 档‖ " +
          " vs ".join(f"{k}({v} 票)" for k, v in detail[:5]))
    A("")

    # ---- 姓名异常 ----
    nms = rep["conflict"].get("姓名", [])
    A("=" * 78)
    A(f"姓名跨档不一致（{len(nms)} 人 · 前 {lines} 人）—— 多为重名序数漂移")
    A("-" * 78)
    for code, cnt in nms[:lines]:
        A(f"{code}｜" + " / ".join(f"{k}({v})" for k, v in cnt))
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="全史册 · 跨档合并器")
    ap.add_argument("--apply", action="store_true", help="真正落盘 saves/全史存档/")
    ap.add_argument("--with-guess", action="store_true",
                        help="落盘后自动跟跑 guess_lineage --apply 重建推定层"
                        "（五十四批教训：忘跟跑 = 推定边无声丢失，故串成一步）")
    ap.add_argument("--report-lines", type=int, default=60)
    args = ap.parse_args()

    docs = load_staging()
    if not docs:
        print("× staging 是空的，先跑 tools/stage_extract.py")
        return 1
    print(f"读入 {len(docs)} 档 …")
    people, db, rep = merge(docs)
    print(f"合并完成：{len(people)} 人")

    text = build_reports(people, db, rep, docs, args.report_lines)
    out_dir = (os.path.join(ROOT, "saves", BOOK) if args.apply
               else os.path.join(ROOT, "_scratch"))
    os.makedirs(out_dir, exist_ok=True)
    rp = os.path.join(out_dir, "合并报告.txt")
    open(rp, "w", encoding="utf-8").write(text)

    if args.apply:
        payload = {
            "people": people,
            "cutoff_person": None,
            "source": {
                "merged": True,
                "title": BOOK,
                "parts": [{"era": d["era"], "slot": d["slot"],
                           "start_year": d["start_year"], "path": d["path"],
                           "people": len(d["people"])} for d in docs],
                "imported": time.strftime("%Y-%m-%d %H:%M"),
                "prune": "hist",
                "hide_cols": ["年龄", "余寿"],
                # ★ 2026-09-26 使用者裁定：合并谱跨 2500 年、人人皆死，
                #   「已故灰」不携带信息 ⇒ 本谱声明不涂（家谱/时间轴/表格/人物页
                #   四处同规，见 app.storage.hide_dead_shade）。
                "hide_dead_shade": True,
                "note": f"由 {len(docs)} 个剧本档合并；世代按合并血缘图重算；"
                        f"身份只保留全档一致的",
            },
        }
        fp = os.path.join(out_dir, "family.json")
        # ★ 2026-09-26 审查修复（H5）：合并是**整本重建**，原 payload 不带
        #   画布状态键 —— 使用者在《全史存档》上点过的「选定」名单
        #   （focused_people / hidden_non_historical，2026-09-24 起按谱牒存）
        #   会被一次重跑合并整个清掉。与 import_from_game.run_merge /
        #   import_codes 的约定对齐：画布键整份带回。
        old = {}
        if os.path.exists(fp):
            try:
                with open(fp, encoding="utf-8") as f:
                    old = json.load(f) or {}
            except Exception as e:
                print(f"⚠ 旧 family.json 读不出（画布键带不回来）：{e}")
        for _k in ("focused_people", "hidden_non_historical"):
            if isinstance(old, dict) and old.get(_k):
                payload[_k] = old[_k]
                print(f"  已带回画布键 {_k}（{len(old[_k])} 条）")
        write_atomic(fp, payload, keep_backup=True)
        print(f"已写 {fp}")
        # ★ 2026-09-26 审查修复（H5）：重建必清推定字段（father_guess /
        #   associate_of / guess_note / root_group）—— 七十八批的「顺序坑」。
        #   原来只靠人记得「merge → guess_lineage」，这里明说一句，
        #   免得推定边悄悄消失。
        if os.path.exists(fp) and isinstance(old, dict) and \
                any(v.get("father_guess") for v in (old.get("people") or {}).values()):
            print("⚠ 本谱旧版带推定世系字段（father_guess 等），重建后已清 ——")
            print("  请紧接着跑 `python tools/guess_lineage.py --apply` 恢复推定边。")
        if a.with_guess:
            # ★ 2026-09-27 五十四批教训落地：merge 是「重建」，必清推定字段，
            #   靠人记得跟跑 guess_lineage 一忘就丢几百条边（且毫无声响）——
            #   现在串成一步：落盘后自动重建推定层。
            import subprocess
            gl = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "guess_lineage.py")
            print("== 自动跟跑 guess_lineage --apply（重建推定层）==")
            rc = subprocess.call([sys.executable, "-X", "utf8", gl,
                                  "--book", "全史存档", "--apply"])
            if rc == 0:
                print("推定层重建完成（merge + guess_lineage 一条龙）。")
            else:
                print(f"⚠ guess_lineage 退出码 {rc} —— 请手动重跑！", flush=True)
    print(f"报告：{rp}")
    print()
    print(text[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
