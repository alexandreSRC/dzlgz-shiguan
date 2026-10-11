# -*- coding: utf-8 -*-
"""本地化层的守卫 —— 「码 ↔ 中文」映射表的覆盖率与一致性自检。

为什么要它
============================================================
本工具干的事，本质就是**给游戏存档建一份本地化文件**：把存档里的编号与
拼音字段名，一对一映射成中文。散在 app/ 各处的映射表合起来就是这份「本地化文件」：

    labels.FIELD                  字段名 → 中文
    labels.VALUE                  值码   → 中文（按字段分组）
    labels.CHINESE_ENUM_FIELDS    值本身即中文的字段（不用映射）
    gods.GODHOOD / WEI_NENG       神明：神格码 sg / 威能码 wn
    gods.WEI_NENG_EFFECT          威能 → 效果原文
    names_map.ZHENG_CE_CODES      政策编号 → 名
    names_map.NENG_LI_CODES       能力编号 → 名
    xref.RULES / ARRAY_RULES      编号 → 人名 / 城名 / 国名 / 家族（引用解析）
    catalog.FAMILIES / COLUMNS / FAMILY_NOTE   表族名 / 默认列 / 用途

**建一次、处处引用** —— 所以必须有个守卫盯着三件事：

  ① **覆盖率**：存档里实际出现的东西是不是都有中文（不许漏译）；
  ② **一一对应**：码表与存档**双向**吻合（不许有码没名，也不许有名没码）；
  ③ **唯一性**：同一个码不许在两处被映射成不同的中文（同码两译 = 静默出错）。

用法
============================================================
    python tools/check_labels.py                    # 用 config 里的当前实录槽
    python tools/check_labels.py --src __SHIGUAN_CACHE_E__\\Save_All_101
    python tools/check_labels.py --src ... --json out.json

报告写到 `_stats/check_labels.txt`（**不走管道**，中文会被二次处理）；
**有缺口时退出码 1**，可直接挂进冒烟 / CI。

口径
============================================================
· **只报告，不自动改** —— 入库是独立、可审的动作（与 `scan_number_map.py` 同规）。
· 「译不出」的判据取**标签里还混着 ASCII**：`Ai_*` → 「AI内容」是有意保留的，
  故 `ALLOW_ASCII_ALIAS` 白名单里的字段不算缺口。
· 引用解析率**不要求 100%**：存档字段版本间会漂移，低于阈值只**告警**不判失败
  （阈值见 `XREF_WARN_RATE`）。
"""
import argparse
import collections
import io
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import catalog as C          # noqa: E402
from app import gods as GD            # noqa: E402
from app import labels as L           # noqa: E402
from app import names_map as NM       # noqa: E402
from app import saveload as S         # noqa: E402
from app import xref as XR            # noqa: E402

STATS_DIR = os.path.join(ROOT, "_stats")
REPORT = os.path.join(STATS_DIR, "check_labels.txt")

# 「标签里含 ASCII」是有意保留的字段（AI 就是 AI），不算缺口
ALLOW_ASCII_ALIAS = {"Ai_Content", "Ai_Must_Content", "Player_Ai_Content",
                     "Ai_Every_Month_Content", "Ai_Content_List"}
# 引用解析率低于此值就告警（不判失败）
XREF_WARN_RATE = 0.95

# **已知缺口**：这些字段的值确实还没译，但**不是漏做，是宁缺勿猜**——
# 表里的键是「未证实」的（实测出现的是另一批值），照实留空比编一个像样的错中文强。
# 记在这里，守卫才能既盯住新缺口、又不必为已登记的旧缺口天天亮红灯。
KNOWN_GAPS = {
    "Hu_Ben_Type": "表内 1/2 未证实；实测出现 4/6/8/9/10/11 —— 留空",
    "Liang_Yi_Type": "同上",
    "San_Jun_Type": "同上",
    # ---- 以下 6 项是 2026-10-03 首次全量自检查出的，**确无证据可依**，故登记而非编造：
    "Neng_Li_Data": "12 个能力码（189/192/193/195/305/307…）在存档里从没带过 "
                    "`Buff_Name` ⇒ 无处反解（`scan_number_map.py` 也报「能力：无」）",
    "Neng_Li_Or_Zheng_Ce": "增益类别实测 33 种，`labels` 已译 15 种；余 18 种无名字证据",
    "Class_Type": "值 0（×6）无证据（表内只确认过 1=在世）",
    "Zui_Level": "值 0（×10）无证据（表内 1~4 本就标着「未证实」）",
    "King_Jue_Wei_Code": "值 0（×2）无证据",
    "Memorial_Ren_Jue_Wei_New": "爵位别名（同 King_Jue_Wei_Code），缺的也正是同一个值 0",
    "Level": "⚠️ **字段名跨表复用**（建筑等级 / 单位等级 …各是一套码），"
             "单一全局表覆盖不了它 —— 值 5 属另一套口径，要按表分别映射",
    "Type": "⚠️ 同上一类：**字段名跨表复用**。军表里是**枚举名字符串**"
            "（`Hu_Ben`/`Liang_Yi`/`San_Jun`，已译 虎贲/两翼/三军），"
            "别处的 `Type` 却是**数字码**（1/0/2/3/50001…）—— 一张表覆盖不了两种口径",
}
# 抽样上限：表族很大时只扫前 N 行（覆盖字段名足够，跑得快）
ROW_CAP = 200
LIST_CAP = 80

_out = []


def w(s=""):
    _out.append(s)


def has_ascii(s):
    return bool(re.search(r"[A-Za-z]", str(s or "")))


# ---------------------------------------------------------------- 本地化层清单

def table_inventory():
    """本地化层的全部「码 ↔ 中文」表 —— 一眼看全，避免重复造表。"""
    return [
        ("labels.FIELD", "字段名 → 中文", len(L.FIELD)),
        ("labels.VALUE", "值码 → 中文（%d 个字段）" % len(L.VALUE),
         sum(len(v) for v in L.VALUE.values())),
        ("labels.CHINESE_ENUM_FIELDS", "值本身即中文（不用映射）",
         len(L.CHINESE_ENUM_FIELDS)),
        ("gods.GOD_SYS", "神系", len(GD.GOD_SYS)),
        ("gods.GODHOOD", "神明 · 神格码 sg", len(GD.GODHOOD)),
        ("gods.WEI_NENG", "神明 · 威能码 wn", len(GD.WEI_NENG)),
        ("gods.WEI_NENG_EFFECT", "神明 · 威能 → 效果原文", len(GD.WEI_NENG_EFFECT)),
        ("names_map.ZHENG_CE_CODES", "政策编号 → 名", len(NM.ZHENG_CE_CODES)),
        ("names_map.NENG_LI_CODES", "能力编号 → 名", len(NM.NENG_LI_CODES)),
        ("xref.RULES", "标量引用 → 名字", len(XR.RULES)),
        ("xref.ARRAY_RULES", "数组引用 → 名字", len(XR.ARRAY_RULES)),
        ("catalog.FAMILIES", "表族 → 中文名 / 分类", len(C.FAMILIES)),
        ("catalog.COLUMNS", "表族 → 默认列", len(C.COLUMNS)),
        ("catalog.FAMILY_NOTE", "表族 → 用途", len(C.FAMILY_NOTE)),
    ]


# ---------------------------------------------------------------- 扫存档

def scan_slot(slot):
    """把槽里出现过的字段名、值、神明码、引用值都收下来。"""
    fnames = collections.Counter()
    values = collections.defaultdict(collections.Counter)
    god = {"sg": set(), "wn": set()}
    refs = collections.defaultdict(lambda: [0, 0])       # 字段 → [可解析, 总数]

    def walk(v):
        if isinstance(v, dict):
            for k, x in v.items():
                ks = str(k)
                fnames[ks] += 1
                # ⚠️ 值要**保原类型**：`labels.VALUE` 里大量表用的是 **int 键**
                #   （`Ren_Sex = {0:"男"}`）。第一版把值 `str()` 化了 ⇒ 整节
                #   「值未覆盖 18 个字段」全是假阳性（`"0"` 当然查不到 `0`）。
                if isinstance(x, (str, int, float)) and not isinstance(x, bool):
                    values[ks][x] += 1
                if ks == "Godhood_Code_Arr":
                    god["sg"] |= {c.strip() for c in str(x).split(",") if c.strip()}
                if ks == "Passive_Effect":
                    god["wn"] |= {c.strip() for c in str(x).split(",") if c.strip()}
                if ks in XR.RULES and not isinstance(x, (dict, list)):
                    ri = refs[ks]
                    ri[1] += 1
                    if xr is not None and xr.lookup(XR.RULES[ks], x) is not None:
                        ri[0] += 1
                if ks in XR.ARRAY_RULES and isinstance(x, list):
                    ri = refs[ks]
                    for e in x[:30]:
                        if isinstance(e, (dict, list)):
                            continue
                        ri[1] += 1
                        if xr is not None and xr.lookup(XR.ARRAY_RULES[ks], e) is not None:
                            ri[0] += 1
                walk(x)
        elif isinstance(v, list):
            for x in v[:LIST_CAP]:
                walk(x)

    xr = None
    try:
        xr = XR.XRef.build(slot)
    except Exception:
        pass
    for t in slot.tables.values():
        for r in t.rows[:ROW_CAP]:
            walk(r)
    return fnames, values, god, refs, xr


# ---------------------------------------------------------------- 唯一性

def code_spaces():
    """每个「**码空间**」= 一套互相排斥的码表。

    ⚠️ 判冲突**必须在同一码空间内比**：政策 `11`=登众制、能力 `11`=无为、
    等级 `11`=神 —— 三个 `11` 是三套独立码，**不是冲突**
    （第一版判据按码字符串全局比，误报 128 条全是这类跨空间碰撞）。
    真正要抓的是：**同一个码空间被两个地方各定义了一份**，且两边不一致。
    返回 [(空间名, 来源标签, {码: 中文})]。
    """
    out = [
        ("Godhood_Code_Arr", "gods.GODHOOD", GD.GODHOOD),
        ("Passive_Effect", "gods.WEI_NENG", GD.WEI_NENG),
        ("Zheng_Ce_Data", "names_map.ZHENG_CE_CODES", NM.ZHENG_CE_CODES),
        ("Neng_Li_Data", "names_map.NENG_LI_CODES", NM.NENG_LI_CODES),
    ]
    for field, tb in L.VALUE.items():
        out.append((field, "labels.VALUE[%s]" % field, tb))
    return out


def uniqueness_conflicts():
    """同一**码空间**被多处定义且不一致 —— 这才是静默出错。"""
    by_space = collections.defaultdict(list)
    for space, src, tb in code_spaces():
        by_space[space].append((src, tb))

    out = []
    for space, defs in by_space.items():
        if len(defs) < 2:
            continue
        base_src, base = defs[0]
        diffs = []
        for src, tb in defs[1:]:
            keys = set(base) | set(tb)
            for k in sorted(keys, key=str):
                if base.get(k) != tb.get(k):
                    diffs.append((k, base_src, base.get(k), src, tb.get(k)))
        if diffs:
            out.append((space, diffs))
    return out


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser(description="本地化层（码 ↔ 中文）覆盖率与一致性自检")
    ap.add_argument("--src", default="", help="实录槽目录（默认取 config.current_record）")
    ap.add_argument("--json", default="", help="额外导出结构化结果到该文件")
    a = ap.parse_args()

    src = a.src
    if not src:
        try:
            src = json.load(open(os.path.join(ROOT, "config.json"),
                                 encoding="utf-8")).get("current_record") or ""
        except Exception:
            src = ""

    w("=" * 74)
    w("本地化层自检 · check_labels.py   %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    w("=" * 74)
    w()
    w("① 本地化层清单（**建一次、处处引用** —— 别在别处再抄一份）")
    w("-" * 74)
    for name, desc, n in table_inventory():
        w("   %-30s %-26s %5d 条" % (name, desc, n))
    w()

    fails = []

    conflicts = uniqueness_conflicts()
    w("② 唯一性：同一个**码空间**是否被两处定义、且两边不一致")
    w("-" * 74)
    if conflicts:
        w("   !! %d 个码空间存在冲突定义：" % len(conflicts))
        for space, diffs in conflicts[:20]:
            w("      [%s] %d 处不一致" % (space, len(diffs)))
            for k, s1, z1, s2, z2 in diffs[:6]:
                w("         %-10s %s=%r  vs  %s=%r" % (k, s1, z1, s2, z2))
        fails.append("码空间冲突 %d 处" % len(conflicts))
    else:
        w("   [OK] 各码空间定义唯一、互不矛盾")
    w()

    if not src or not os.path.isdir(src):
        w("!! 没有实录槽（%s）—— 只做了静态检查，覆盖率跳过" % (src or "未配置"))
        _finish(a.json, fails)
        return
    slot = S.SaveSlot(src).load()
    w("② 扫描实录槽：%s" % src)
    w("   %d 个表族" % len(slot.tables))
    w()

    fnames, values, god, refs, xr = scan_slot(slot)

    w("③ 字段名覆盖率（目标 100%；`Ai_*` 与白名单除外）")
    w("-" * 74)
    miss = sorted(k for k in fnames
                  if has_ascii(L.field_label(k)) and k not in ALLOW_ASCII_ALIAS)
    w("   出现过的字段名 %d 个；**译不出 %d 个**" % (len(fnames), len(miss)))
    for k in miss[:60]:
        w("      %-34s ×%-6d 现译作 %r" % (k, fnames[k], L.field_label(k)))
    if len(miss) > 60:
        w("      …（还有 %d 个）" % (len(miss) - 60))
    if miss:
        fails.append("字段名未译 %d 个" % len(miss))
    else:
        w("   [OK] 字段名 100% 中文")
    w()

    w("④ 值覆盖：已登记 `labels.VALUE` 的字段，值是不是都能译")
    w("-" * 74)
    vmiss, known = [], []
    for field, tb in sorted(L.VALUE.items()):
        cnt = values.get(field)
        if not cnt:
            continue
        # ⚠️ 值**本身就是中文**的不算缺口：存档里同一字段会混着「码」与「已译名」
        #   （实测 `Zu_Yu` 既有 `0`/`6` 这样的码，也有 `中夏`/`北狄` 这样的现成汉字）。
        bad = [(v, n) for v, n in cnt.most_common()
               if L.code_of(field, v) is None
               and re.search(r"[A-Za-z0-9]", str(v))]
        if not bad:
            continue
        (known if field in KNOWN_GAPS else vmiss).append((field, bad))
    if vmiss:
        for field, bad in vmiss[:25]:
            w("   !! %-26s 未覆盖 %d 种值：%s"
              % (field, len(bad),
                 "、".join("%s×%d" % (v, n) for v, n in bad[:6])))
        fails.append("值未覆盖 %d 个字段" % len(vmiss))
    if known:
        for field, bad in known:
            w("   ~~ %-26s 已知缺口（已登记，宁缺勿猜）：%s —— %s"
              % (field, "、".join("%s×%d" % (v, n) for v, n in bad[:4]),
                 KNOWN_GAPS[field]))
    if not vmiss:
        w("   [OK] 除已登记的已知缺口外，值全部可译")
    w()

    w("⑨ 字段名别名：同一套码是否挂了两个名字（存档换名，码表没跟上）")
    w("-" * 74)
    w("   （判据：某字段**没有**自己的码表，但它的值 ≥98% 落在另一个字段的码表里。")
    w("     2026-10-03 实测踩过：`Save_KingData.Zu_Yu` 是族域码，码表却挂在")
    w("     `Ren_Zu_Yu` 名下 ⇒ `code_of(\"Zu_Yu\", 6)` 查不到，族域显示成裸码「6」而不「北狄」。）")
    aliases = alias_candidates(values)
    if aliases:
        for field, best, tot in aliases[:10]:
            w("   ?? %-24s ×%-6d 疑似 = %s"
              % (field, tot, " 或 ".join("%s (%.0f%%)" % (o, r * 100) for o, r in best)))
        w("      ⇒ 确认后在 `labels.VALUE` 里让它**指向同一张表**"
          "（`VALUE[\"X\"] = VALUE[\"Y\"]`）。")
        w("   （**只告警、不判失败**：整数码表会互相「吞」值 —— 大码表能把任意小整数"
          "都算命中，是否真别名要看字段语义，不能自动裁决。）")
    else:
        w("   [OK] 未发现「同表异名」的字段")
    w()

    w("⑧ 不变式：**有专属码表的字段，不许再登记成引用**")
    w("-" * 74)
    w("   （否则 `_fmt_val` 会用「引用名」覆盖掉正确的「码表中文」——")
    w("     2026-10-03 实测踩过：`Faith_Gods_Sys_Code` 当国名解，神系码 4 显示成「匈奴」；")
    w("     `Zheng_Ce_Code` 当城名解，44994 条政策只有 30.5% 碰巧命中。）")
    both = sorted(f for f in L.VALUE if f in XR.RULES)
    if both:
        for f in both:
            w("   !! %-28s 既在 labels.VALUE 又在 xref.RULES(%s)"
              % (f, XR.RULES[f]))
        fails.append("字段兼有码表与引用 %d 个" % len(both))
    else:
        w("   [OK] 无字段同时挂码表与引用")
    w()

    w("⑤ 引用解析率（低于 %.0f%% 只告警 —— 字段版本会漂移）" % (XREF_WARN_RATE * 100))
    w("-" * 74)
    low = []
    for field, (ok, tot) in sorted(refs.items()):
        if not tot:
            continue
        rate = ok / tot
        mark = "[OK]  " if rate >= XREF_WARN_RATE else "!! 低"
        w("   %s %-30s %5d/%5d (%.1f%%)"
          % (mark, field, ok, tot, rate * 100))
        if rate < XREF_WARN_RATE:
            low.append((field, rate))
    if not refs:
        w("   （本槽没扫到引用字段）")
    w()

    w("⑥ 神明码一一对应（码表 ↔ 存档，**双向**）")
    w("-" * 74)
    for kind, kod in (("sg", GD.GODHOOD), ("wn", GD.WEI_NENG)):
        save = god[kind]
        lack = sorted(save - set(kod))
        extra = sorted(set(kod) - save)
        w("   存档 %s %d 个 · 码表 %d 个" % (kind, len(save), len(kod)))
        w("      有码没名（码表缺）：%s" % ("、".join(lack) if lack else "无"))
        w("      有名没码（本档没见到）：%s" % ("、".join(extra) if extra else "无"))
        if lack:
            fails.append("神明 %s 码表缺 %d 个" % (kind, len(lack)))
    w()

    w("⑦ 神明总表（世界页侧栏「国家 · 神明 · 总表」）")
    w("-" * 74)
    try:
        rows = GD.god_rows(slot)
        w("   派生表 %s：%d 行" % (GD.GOD_TABLE, len(rows)))
        w("   表族登记：%s / 分类 %s / 默认列 %d 个"
          % (C.label_of_family(GD.GOD_TABLE), C.category_of_family(GD.GOD_TABLE),
             len(C.COLUMNS.get(GD.GOD_TABLE, ()))))
        if not rows:
            fails.append("神明总表为空")
        else:
            w("   [OK] 可生成")
    except Exception as e:
        w("   !! 生成失败：%r" % (e,))
        fails.append("神明总表异常")
    w()

    _finish(a.json, fails)


def alias_candidates(values, threshold=0.98, min_distinct=3, max_distinct=12,
                     min_total=20, max_owner=40):
    """侦测「同一套码挂在不同字段名上」—— 存档换名、码表没跟上。

    `Save_KingData.Zu_Yu`（族域，值 0/6/7…）与 `Ren_Zu_Yu` 就是一对：
    码表只登记在后者名下，前者一律译不出。这类**不需要逐个去发现**，
    全档一比就全出来 —— 这正是「本地化文件」该有的自动化。
    返回 [(字段, [(码表主人, 命中率)], 出现次数)]。
    """
    out = []
    for field, cnt in values.items():
        if field in L.VALUE or field in L.CHINESE_ENUM_FIELDS:
            continue
        # 码字段的取值集合**必须小**：几十个值的必是数量/等级，不是码。
        if not (min_distinct <= len(cnt) <= max_distinct):
            continue
        tot = sum(cnt.values())
        if tot < min_total:
            continue
        hits = []
        for owner, tb in L.VALUE.items():
            # 母表也要小 —— 1637 条的整数码表会把任意小整数都「吞」成命中。
            if owner == field or not (2 <= len(tb) <= max_owner):
                continue
            keys = set(tb)
            sk = {str(k) for k in keys}
            hit = sum(n for v, n in cnt.items() if v in keys or str(v) in sk)
            if hit / tot >= threshold:
                hits.append((owner, hit / tot))
        if hits:
            out.append((field, sorted(hits, key=lambda x: -x[1])[:3], tot))
    return sorted(out, key=lambda x: -x[2])


def _finish(json_path, fails):
    w("=" * 74)
    if fails:
        w("结果：**%d 项失败**" % len(fails))
        for f in fails:
            w("   · %s" % f)
    else:
        w("结果：**全绿**（本地化层覆盖完整、一一对应、无同码两译）")
    w("=" * 74)
    os.makedirs(STATS_DIR, exist_ok=True)
    text = "\n".join(_out) + "\n"
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(text)
    if json_path:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({"fails": fails, "ok": not fails}, f,
                      ensure_ascii=False, indent=2)
    # 报告不走管道：中文经 PowerShell 管道会被二次处理成乱码
    print(text)
    print("报告已写：%s" % REPORT)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
