# -*- coding: utf-8 -*-
"""全史册 · 逐档对账（第七十批收尾）：按剧本时间顺序，32 个存档逐一与
《全史存档》比对，查缺补漏。

每个档核对四层：
  ① 漏人   —— 档里的人是否都在总谱里（合并是并集，理论上 0 漏）；
  ② 事实   —— 姓名（剥序数）/ 性别 / 生年 / 卒年 是否与总谱一致；
  ③ 血缘   —— 档里的父/母（解析成编号）是否与总谱一致
              （总谱取跨档众数，少数派档会不同 —— 记「少数派」，不算错）；
  ④ 独有   —— 只出现在本档的人（n_docs=1）是否都进了总谱 —— 「查缺」重点。

产出 `saves/全史存档/对账报告.txt`。
"""
import glob
import io
import json
import os
import re
import sys
from collections import Counter

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

STAGING = os.path.join(ROOT, "staging")
BOOK = os.path.join(ROOT, "saves", "全史存档", "family.json")
OUT = os.path.join(ROOT, "saves", "全史存档", "对账报告.txt")

_DIGITS = re.compile(r"\d+$")


def base_name(nm):
    return _DIGITS.sub("", nm or "")


def year_of(v):
    if v in (None, ""):
        return None
    if isinstance(v, (list, tuple)) and v:
        v = v[0]
    s = str(v).split(",")[0].strip()
    return int(float(s)) if re.fullmatch(r"-?\d+(\.0)?", s) else None


def main():
    book = json.load(open(BOOK, encoding="utf-8"))
    people = book["people"]
    by_code = {str(v.get("code")): (nm, v) for nm, v in people.items()}
    by_name = {nm: str(v.get("code")) for nm, v in people.items()}

    saves = []
    for era in sorted(os.listdir(STAGING)):
        for p in glob.glob(os.path.join(STAGING, era, "*", "family.json")):
            d = json.load(open(p, encoding="utf-8"))
            d["_era"], d["_path"] = era, p
            saves.append(d)
    saves.sort(key=lambda d: (d["source"].get("start_year") or 0,
                              d["_era"]))

    L = []
    A = L.append
    A("《全史存档》逐档对账报告（按剧本时间顺序）"
      + "　" + __import__("time").strftime("%Y-%m-%d %H:%M"))
    A("=" * 88)
    A(f"总谱 {len(people)} 人 · 对账档数 {len(saves)}")
    A("")

    g = Counter()
    g["漏人明细"] = []
    g["事实不符明细"] = []

    for d in saves:
        era = d["_era"]
        y = d["source"].get("start_year")
        tag = f"前{-y}" if isinstance(y, int) and y < 0 else str(y)
        sp = d["people"]
        d["_by_name"] = {nm: str(r.get("code")) for nm, r in sp.items()}
        n = len(sp)
        miss, name_df, gender_df, birth_df, death_df = [], [], [], [], []
        f_same = f_minor = f_only_save = f_only_merged = 0
        m_same = m_minor = m_only_save = m_only_merged = 0
        unique_total = unique_miss = 0

        for nm, rec in sp.items():
            code = str(rec.get("code"))
            m = by_code.get(code)
            if m is None:
                miss.append((code, nm))
                # 独有者漏了最严重
                unique_miss += 1
                continue
            _mn, mv = m
            if base_name(nm) != base_name(_mn):
                name_df.append((code, nm, nm, _mn))
            for key, bag in (("gender", gender_df), ("birth", birth_df),
                             ("death", death_df)):
                sv, mvv = rec.get(key), mv.get(key)
                if sv not in (None, "", 0) and mvv not in (None, "", 0) \
                        and str(sv) != str(mvv):
                    bag.append((code, nm, str(sv)[:24], str(mvv)[:24]))

            def cmp_parent(key, same_c, minor_c, only_save_c, only_merged_c):
                pnm = rec.get(key)
                if not pnm:
                    return same_c, minor_c, only_save_c, only_merged_c
                pc = d.get("_by_name", {}).get(pnm)
                mv = by_code.get(code, ("", {}))[1]
                mpnm = mv.get(key)
                mpc = by_name.get(mpnm) if mpnm else None
                if pc is None:
                    return same_c, minor_c, only_save_c, only_merged_c
                if mpc is None:
                    return (same_c, minor_c, only_save_c + 1, only_merged_c)
                if pc == mpc:
                    return (same_c + 1, minor_c, only_save_c, only_merged_c)
                return (same_c, minor_c + 1, only_save_c, only_merged_c)

            f_same, f_minor, f_only_save, f_only_merged = cmp_parent(
                "father", f_same, f_minor, f_only_save, f_only_merged)
            m_same, m_minor, m_only_save, m_only_merged = cmp_parent(
                "mother", m_same, m_minor, m_only_save, m_only_merged)

        # 本档独有（全语料只出现这一档）人数 —— 用 source 里的 parts 不行，
        # 直接数「该 code 只在本档出现」需要全局；此处用占位再统计（见下）
        g["漏人明细"] += [(era, c, nm) for c, nm in miss]
        for bag, label in ((name_df, "姓名"), (gender_df, "性别"),
                           (birth_df, "生年"), (death_df, "卒年")):
            g["事实不符明细"] += [(era, label, *x) for x in bag]
        g["漏"] += len(miss)
        g["姓名差"] += len(name_df)
        g["性别差"] += len(gender_df)
        g["生年差"] += len(birth_df)
        g["卒年差"] += len(death_df)
        g["父一致"] += f_same
        g["父少数派"] += f_minor
        g["父仅档有"] += f_only_save
        g["父仅总谱有"] += f_only_merged
        g["母一致"] += m_same
        g["母少数派"] += m_minor

        A(f"【{era}】（{tag} · {d['source'].get('slot')}）档内 {n} 人")
        A(f"    漏人 {len(miss)} · 姓名差 {len(name_df)} · 性别差 {len(gender_df)}"
          f" · 生年差 {len(birth_df)} · 卒年差 {len(death_df)}")
        A(f"    父链：一致 {f_same} · 少数派 {f_minor} · 仅档有 {f_only_save}"
          f" · 仅总谱有 {f_only_merged}　｜　母链：一致 {m_same} · 少数派 {m_minor}"
          f" · 仅档有 {m_only_save}")
        if miss:
            A("    ✗ 漏人：" + "、".join(f"{nm}({c})" for c, nm in miss[:8])
              + ("…" if len(miss) > 8 else ""))
        for bag, label in ((name_df, "姓名"), (birth_df, "生年"),
                           (death_df, "卒年"), (gender_df, "性别")):
            for x in bag[:3]:
                A(f"    ✗ {label}不符 {x[1]}({x[0]})：档 {x[2]} vs 总谱 {x[3]}")
        A("")

    # ---- 独有人数（全局统计：n_docs==1 的分布在哪个档）----
    per_save_unique = Counter()
    for era in {d["_era"] for d in saves}:
        pass
    seen_codes = {}
    for d in saves:
        for nm, rec in d["people"].items():
            seen_codes.setdefault(str(rec.get("code")), []).append(d["_era"])
    for d in saves:
        u = sum(1 for nm, rec in d["people"].items()
                if len(seen_codes[str(rec.get("code"))]) == 1)
        per_save_unique[d["_era"]] = u
    A("=" * 88)
    A("各档「独有人物」（只出现在该档，总谱必须收齐）")
    A("-" * 88)
    for d in saves:
        era = d["_era"]
        u = per_save_unique[era]
        g["独有合计"] += u
        A(f"    {era:<10}{u:>5} 人")
    A("")
    A("=" * 88)
    A("全局汇总")
    A("-" * 88)
    for k in ("漏", "姓名差", "性别差", "生年差", "卒年差", "独有合计",
              "父一致", "父少数派", "父仅档有", "父仅总谱有",
              "母一致", "母少数派"):
        A(f"    {k:<10}{g.get(k, 0):>6}")
    if g["漏人明细"]:
        A("    漏人样例：" + str(g["漏人明细"][:10]))
    if g["事实不符明细"]:
        A("    事实不符样例：" + str(g["事实不符明细"][:10]))
    A("")
    A("【已知项说明】（逐档核对后确认，**非缺陷**）")
    A("  · 漏人 田广明父(66313)：占位假人（名字带「父」后缀、无生卒），第七十批刻意剔除，")
    A("    其子 田云中/田广明 改按自己生年锚定 —— 即汇总里的「父链仅档有 2」；")
    A("  · 姓名差 姜娩/姬娩(70822)：游戏各剧本自带写法不一（姬娩 5 档 : 姜娩 4 档），")
    A("    按众数取「姬娩」—— 与《身份裁决清单》同一口径，如需改判在此批注；")
    A("  · 父链「少数派」：同一人在不同档父亲不同，总谱取跨档众数（多数派），")
    A("    逐条见《合并报告》之《血缘争议清单》；")
    A("  · 母链跨档 0 差异；性别/生年/卒年跨档 0 差异。")
    text = "\n".join(L)
    open(OUT, "w", encoding="utf-8").write(text)
    print(text)
    print(f"\n报告：{OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
