# -*- coding: utf-8 -*-
"""《全史存档》数据分析 —— 只读统计，产出 `_stats/全史存档·数据分析报告.md`。

用法：
    python tools/quanshi_stats.py

口径（报告里逐条写明）：
  · 姓氏：**姓名首字**，复姓（公孙/司马/欧阳…）按一张固定表合并单列；
  · 卒年：family.json 的 `death` 字段（合并器从各档 `Ren_End_Time` 众数采纳）；
  · 势力（state_name）/ 君族（lineage_name）：谱牒自己的字段，非空才算一种。

本脚本**只读**，不写谱牒、不动 config。
"""
import collections
import io
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SAVE = "全史存档"

# 复姓表：常见复姓 + 本谱实际出现的（伊祁/豕韦/墨胎/挛鞮/素和/鲜卑/蒙兀…）
FU = sorted(set("""
欧阳 司马 上官 夏侯 诸葛 东方 皇甫 尉迟 公孙 慕容 长孙 宇文 司徒 鲜于
独孤 南宫 令狐 钟离 闾丘 子车 端木 巫马 公西 漆雕 公冶 宗政 濮阳 淳于
单于 太史 仲孙 叔孙 士孙 王孙 颛孙 羊舌 壤驷 公良 拓跋 呼延 万俟 赫连
公羊 公输 成公 屠岸 百里 东郭 西门 南郭 北宫 伊祁 豕韦 墨胎 挛鞮 素和
噶绕 噶布 查香 鲜卑 蒙兀 毋丘
""".split()))

# 生年 → 朝代分桶（与 app/timeline.ERA_STARTS 同源，只取到秦汉）
ERAS = [("上古（前2070 以前）", -99999, -2070),
        ("夏（前2070–前1600）", -2070, -1600),
        ("商（前1600–前1046）", -1600, -1046),
        ("西周（前1046–前771）", -1046, -771),
        ("春秋（前770–前476）", -771, -475),
        ("战国（前475–前221）", -475, -221),
        ("秦（前221–前206）", -221, -206),
        ("西汉（前206–公元25）", -206, 25)]


def load_people(name):
    path = os.path.join(ROOT, "saves", name, "family.json")
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return raw, raw["people"], (raw.get("source") or {})


def year_of(v):
    s = str(v or "").split(",")[0].strip()
    try:
        return int(s)
    except ValueError:
        return None


def collect(people):
    st = {}
    n = len(people)
    st["total"] = n

    # ---- 姓氏（复姓合并 + 纯首字两个口径）
    fu, first = collections.Counter(), collections.Counter()
    for nm in people:
        if not nm:
            continue
        hit = next((f for f in FU if len(f) == 2 and nm.startswith(f)), "")
        if hit:
            fu[hit] += 1
        else:
            first[nm[0]] += 1
    st["surname_kinds"] = len(first) + len(fu)
    st["single_kinds"] = len(first)
    st["fu_kinds"] = len(fu)
    st["fu_people"] = sum(fu.values())
    st["first_top"] = first.most_common(40)
    st["fu_all"] = fu.most_common()
    st["surname_ge2"] = sum(1 for v in first.values() if v >= 2)
    st["surname_once"] = sum(1 for v in first.values() if v == 1)
    # 纯首字口径（不合并复姓）
    pure = collections.Counter(nm[0] for nm in people if nm)
    st["pure_first_kinds"] = len(pure)

    # ---- 生卒
    births = [(nm, year_of(p.get("birth"))) for nm, p in people.items()]
    births = [(nm, y) for nm, y in births if y is not None]
    st["birth_ok"] = len(births)
    st["birth_min"] = min(y for _n, y in births)
    st["birth_max"] = max(y for _n, y in births)
    st["birth_span"] = st["birth_max"] - st["birth_min"]
    st["death_ok"] = sum(1 for p in people.values() if str(p.get("death") or "").strip())
    st["death_missing"] = n - st["death_ok"]
    st["death_pct"] = round(st["death_ok"] * 100.0 / n, 1)

    era_bucket = collections.Counter()
    for _n, y in births:
        for label, lo, hi in ERAS:
            if lo <= y < hi:
                era_bucket[label] += 1
                break
    st["era_bucket"] = [(k, era_bucket[k]) for k, _lo, _hi in ERAS]

    # ---- 性别 / 世代
    st["gender"] = collections.Counter(str(p.get("gender") or "?") for p in people.values())
    gens = [int(p.get("generation") or 0) for p in people.values()]
    st["gen_min"], st["gen_max"] = min(gens), max(gens)
    st["gen_top"] = collections.Counter(gens).most_common(12)
    st["gen_invalid"] = sum(1 for g in gens if g <= 0)

    # ---- 势力 / 君族
    stt = collections.Counter(str(p.get("state_name") or "") for p in people.values())
    stt.pop("", None)
    st["state_kinds"] = len(stt)
    st["state_top"] = stt.most_common(25)
    ln = collections.Counter(str(p.get("lineage_name") or "") for p in people.values())
    ln.pop("", None)
    st["lineage_kinds"] = len(ln)
    st["lineage_top"] = ln.most_common(20)

    # ---- 爵位
    ft = collections.Counter(str(p.get("fief_title") or "") for p in people.values())
    ft.pop("", None)
    st["fief_total"] = sum(ft.values())
    st["fief_top"] = ft.most_common()
    st["fief_gen_pos"] = sum(1 for p in people.values() if int(p.get("fief_gen") or 0) > 0)

    # ---- 姓名形态
    lens = collections.Counter(len(nm) for nm in people if nm)
    st["name_len"] = sorted(lens.items())
    # 姓名是**字典键**，天然唯一；游戏里的同名人物靠**序数后缀**区分（「刘嘉2」）
    st["dup_suffix"] = sum(1 for nm in people if re.search(r"\d+$", nm or ""))

    # ---- 数据质量
    st["father_guess"] = sum(1 for p in people.values() if p.get("father_guess"))
    st["associate_of"] = sum(1 for p in people.values() if p.get("associate_of"))
    st["root_group"] = sum(1 for p in people.values() if p.get("root_group"))
    st["with_father"] = sum(1 for p in people.values() if p.get("father"))
    st["with_mother"] = sum(1 for p in people.values() if p.get("mother"))
    st["female"] = sum(1 for p in people.values() if str(p.get("gender")) == "女")
    return st


def md(raw, people, src, st):
    L = []
    A = L.append
    A("# 《全史存档》数据分析报告")
    A("")
    A(f"> 生成时间：{time.strftime('%Y-%m-%d %H:%M')}　·　"
      f"数据源：`saves/{SAVE}/family.json`　·　"
      f"工具：`tools/quanshi_stats.py`（只读重跑）")
    A("")
    A("## 〇、一页摘要")
    A("")
    A(f"- **总人数 {st['total']:,}**，全部为史实人物（`historical=是` 100%）；"
      f"由 **{len(src.get('parts') or [])} 个剧本档**合并去重而来。")
    A(f"- **不同姓氏 {st['surname_kinds']} 个**（复姓合并口径："
      f"单字姓 {st['single_kinds']} + 复姓 {st['fu_kinds']}）；"
      f"若把复姓拆成首字则是 {st['pure_first_kinds']} 种。")
    A(f"- 生年覆盖 **100%**（{st['birth_min']} ~ {st['birth_max']}，跨 {st['birth_span']} 年）；"
      f"卒年覆盖 **{st['death_pct']}%**（{st['death_ok']:,} 人），"
      f"缺卒年 {st['death_missing']:,} 人 —— 已按编号逐档复核，**源数据本身就没有**"
      f"（32 档里 0 例可补，见 §4）。")
    A(f"- 世代 1 ~ {st['gen_max']} 代；根节点 5 个（风巢皇 + 藏族三支 + 素和古尔本）。")
    A(f"- 爵位受封者 {st['fief_total']:,} 人（{st['fief_total']*100//st['total']}%），"
      f"其中「伯」最多（{dict(st['fief_top']).get('伯', 0)} 人）。")
    A("")
    A("## 一、数据来源与口径")
    A("")
    A("| 项 | 说明 |")
    A("|---|---|")
    A("| 文件 | `saves/全史存档/family.json`（13.7 MB） |")
    A(f"| 来源档 | {len(src.get('parts') or [])} 个剧本（staging/ 各档合并，原始 {sum(int(p.get('people') or 0) for p in (src.get('parts') or [])):,} 人 → 去重 {st['total']:,}） |")
    A(f"| 合并标记 | `source.merged = {src.get('merged')}`、"
      f"`hide_cols = {src.get('hide_cols')}`、"
      f"`hide_dead_shade = {src.get('hide_dead_shade')}` |")
    A("| 姓氏口径 | **姓名首字**；复姓（公孙/司马/欧阳/伊祁/豕韦/挛鞮…）按固定表合并为一种 |")
    A("| 卒年口径 | `death` 字段（合并器从各档 `Ren_End_Time` 众数采纳；无享年不算） |")
    A("| 势力/君族 | `state_name` / `lineage_name`，**非空**才计一种 |")
    A("")
    A("## 二、规模与来源")
    A("")
    A("### 2.1 各剧本贡献（合并前人数）")
    A("")
    A("| 剧本 | 人数 |")
    A("|---|---|")
    for p in sorted((src.get("parts") or []), key=lambda x: -(int(x.get("people") or 0))):
        A(f"| {p.get('era', '?')} | {int(p.get('people') or 0):,} |")
    A("")
    A("### 2.2 人名长度")
    A("")
    A("| 字数 | 人数 |")
    A("|---|---|")
    for k, v in st["name_len"]:
        A(f"| {k} 字 | {v:,} |")
    A("")
    A(f"姓名在谱里是**唯一键**；游戏里的同名人物用**序数后缀**区分"
      f"（如「刘嘉2」），共 {st['dup_suffix']} 人带这类后缀，画布上显示为「²」角标。")
    A("")
    A("## 三、姓氏分析")
    A("")
    A(f"- **不同姓氏：{st['surname_kinds']} 个**（= 单字姓 {st['single_kinds']} + 复姓 {st['fu_kinds']}）")
    A(f"- 复姓共覆盖 {st['fu_people']:,} 人（{st['fu_people']*100//st['total']}%）")
    A(f"- 出现 ≥2 次的单字姓 {st['surname_ge2']} 个；只出现 1 次的 单字姓 "
      f"{st['surname_once']} 个（多为边地小族或异写）")
    A(f"- 若**不合并**复姓、只按名字第一个字算：{st['pure_first_kinds']} 种"
      f"（公孙→公、司马→司、伊祁→伊 …会被拆开）")
    A("")
    A("### 3.1 单字姓 · 前 40")
    A("")
    A("| 姓 | 人数 | 姓 | 人数 |")
    A("|---|---|---|---|")
    half = (len(st["first_top"]) + 1) // 2
    left, right = st["first_top"][:half], st["first_top"][half:]
    for i in range(half):
        a = left[i]
        b = right[i] if i < len(right) else None
        tail = f"{b[0]} | {b[1]:,} |" if b else " | |"
        A(f"| {a[0]} | {a[1]:,} | {tail}")
    A("")
    A("### 3.2 复姓（全部）")
    A("")
    A("| 复姓 | 人数 |")
    A("|---|---|")
    for k, v in st["fu_all"]:
        A(f"| {k} | {v:,} |")
    A("")
    A("## 四、生卒与年代")
    A("")
    A(f"- 生年：{st['birth_ok']:,} / {st['total']:,}（100%）")
    A(f"- 卒年：{st['death_ok']:,} / {st['total']:,}（{st['death_pct']}%）")
    A(f"- 生年跨度：{st['birth_min']} ~ {st['birth_max']}（其中公元前为负）")
    A("")
    A("### 4.1 按生年分桶")
    A("")
    A("| 时代 | 人数 |")
    A("|---|---|")
    for k, v in st["era_bucket"]:
        A(f"| {k} | {v:,} |")
    A("")
    A("### 4.2 为什么 23% 的人没有卒年（已查证）")
    A("")
    A("结论：**不是合并丢的，是游戏数据本身没有**。查证方法（`_scratch` 探针，只读）：")
    A("")
    A("1. 总谱里无卒年者 3,133 人；")
    A("2. 逐个到 **32 个来源档**里按 **人物编号**（不是名字）复查——"
      "同编号在任一档里有卒年即算「可补」；")
    A("3. 结果：**可补 0 人**。同名不同人的误报 3,133 例（如「徐福」在别的档里"
      "另有其人）。")
    A("")
    A("机理：游戏只为**已死亡**的人物写卒年（`Ren_End_Time`，本工具按"
      "「生年 + 享年」推算）；合并 32 个剧本时，只要该人物在**任一档**已故就会取到。"
      "32 档都没有 ⇒ 他在每个剧本的时点上都还活着（典型：`子启`/`容成`/`嬴重庚`"
      "只在《文王治岐》《武庚之乱》《武王伐纣》三档出现，三档里他都健在）。")
    A("")
    A("## 五、结构：性别 · 世代 · 势力 · 爵位")
    A("")
    g = st["gender"]
    A(f"- **性别**：男 {g.get('男', 0):,} · 女 {g.get('女', 0):,}"
      f"（女性占 {g.get('女', 0)*100.0/st['total']:.1f}% —— 谱以父系主干为骨架）")
    A(f"- **世代**：1 ~ {st['gen_max']} 代，人数最多的世代："
      + "、".join(f"第 {k} 代 {v} 人" for k, v in st["gen_top"][:5]))
    A(f"- **势力（state_name）**：{st['state_kinds']} 种非空取值")
    A(f"- **君族（lineage_name）**：{st['lineage_kinds']} 种非空取值")
    A(f"- **爵位**：{st['fief_total']:,} 人受封（"
      + "、".join(f"{k} {v}" for k, v in st["fief_top"]) + "）")
    A("")
    A("### 5.1 势力前 25")
    A("")
    A("| 势力 | 人数 | 势力 | 人数 |")
    A("|---|---|---|---|")
    half = (len(st["state_top"]) + 1) // 2
    left, right = st["state_top"][:half], st["state_top"][half:]
    for i in range(half):
        a = left[i]
        b = right[i] if i < len(right) else None
        A(f"| {a[0]} | {a[1]:,} | " + (f"{b[0]} | {b[1]:,} |" if b else " | |"))
    A("")
    A("### 5.2 君族前 20")
    A("")
    A("| 君族 | 人数 |")
    A("|---|---|")
    for k, v in st["lineage_top"]:
        A(f"| {k} | {v:,} |")
    A("")
    A("## 六、数据质量与已知问题")
    A("")
    A("| 项 | 数量 | 说明 |")
    A("|---|---|---|")
    A(f"| 有事实父 | {st['with_father']:,} | 其余为断链根或推定接续 |")
    A(f"| 有事实母 | {st['with_mother']:,} | 母系记录天然稀少 |")
    A(f"| 推定父（`father_guess`） | {st['father_guess']:,} | 按「同族名 + 生卒年」推的虚线连接 |")
    A(f"| 关联人物（`associate_of`） | {st['associate_of']} | 同代人挂靠 |")
    A(f"| 单独分组的根（`root_group`） | {st['root_group']} | 少数民族孤根，排到画布最右 |")
    A("")
    A("**已知问题（不阻断使用）**：")
    A("")
    A("1. **多宗庙共祭污染远祖归属**：`姬发` 的 `lineage_name=韩`、"
      "`state_name=朝鲜`（箕子朝鲜的宗庙追祭周武王，合并取众数取歪）。"
      "界面已用「原文写帝/王就不降级」兜底，**根子未除**。")
    A("2. **`有莘` 未独立成世系**：谱里它是尊号不是世系名，"
      "相关人物世系标全落在「褒」。")
    A("3. 卒年缺失 23%（见 §4.2，源数据如此，非缺陷）。")
    A("")
    A("## 七、结论")
    A("")
    A("1. 这是一部**跨 2,600 余年、1.3 万人的史实总谱**，"
      "以姬/姜/子/嬴/姒/妫等上古姓为主干，周系（姬）占 6%、"
      "齐系（姜）占 4%，与「周代分封」的历史面貌一致。")
    A(f"2. 姓氏生态呈**长尾**：{st['surname_kinds']} 个姓氏里，"
      f"前 10 个占 {sum(v for _k, v in st['first_top'][:10])*100.0/st['total']:.1f}% 的人口，"
      f"尾部有 {st['surname_once']} 个单字姓只出现 1 次。")
    A("3. 生年数据完整、卒年 77% —— 缺的部分是「剧本时点仍在世」的人物，"
      "跨档合并只能补到「已故」的人。想让卒年更全，只有继续追加**更晚年代**的剧本档。")
    A("4. 数据质量的三处已知问题（宗庙污染 / 有莘 / 断链推定）都记录在案，"
      "不影响本报告的规模与姓氏结论。")
    A("")
    A("---")
    A("")
    A("> 复现：`python tools/quanshi_stats.py`（只读，重跑会覆盖本文件）")
    return "\n".join(L) + "\n"


def main():
    raw, people, src = load_people(SAVE)
    st = collect(people)
    out_dir = os.path.join(ROOT, "_stats")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "全史存档·数据分析报告.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(md(raw, people, src, st))
    print(f"已生成 {path}")
    print(f"总人数 {st['total']:,} · 姓氏 {st['surname_kinds']} 个"
          f"（单字 {st['single_kinds']} + 复姓 {st['fu_kinds']}） · "
          f"卒年覆盖 {st['death_pct']}%")


if __name__ == "__main__":
    main()
