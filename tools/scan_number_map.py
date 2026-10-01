# -*- coding: utf-8 -*-
"""从存档反解「政策/能力 编号 ↔ 中文名」—— 常驻工具。

================================ 为什么存在 ================================
2026-09-22 之前，编号映射靠「游戏内截图 + 界面顺序=数组顺序」逐条人工配对：
670 个政策要 150+ 轮，且反复出错 ——
  · 读屏形近字（蚌/衅、遗/遣、敢/敖、穀/榖、檝櫨/橇檋…）
  · 顺序假设风险（详情卡是 reversed 渲染，方向一反整组错位）
  · 推定键覆盖实证键（dict 字面量后者胜，86=教化同门 就被静默抹掉了）

真相：存档 `Save_KingData/King_Buff_Array` 的**授予记录**里，
      游戏自己就把编号和中文名写在了一起：
        Neng_Li_Or_Zheng_Ce = 0  →  政策，编号在 Zheng_Ce_Data
        Neng_Li_Or_Zheng_Ce = 1  →  能力，编号在 Neng_Li_Data
        Buff_Name                =  中文名（游戏原文）
      交叉验证：`16↔捭阖`、`30↔天下`、`86↔教化同门` 均与既有映射吻合。

================================ 用法 ================================
    python tools/scan_number_map.py                     # 报告写到 _stats/scan_number_map.txt
    python tools/scan_number_map.py --json out.json     # 额外导出结构化结果
    python tools/scan_number_map.py --emit-insert       # 打印可直接粘进 names_map 的代码块
    python tools/scan_number_map.py --base D:\\某目录     # 换槽根目录

================================ 口径 ================================
· **不自动改 names_map** —— 本工具只报告。入库是独立、可审的动作。
· 同号多名 = 冲突，**不自动裁决**，单独列出待人工确认。
· 跨槽重复次数当置信度：≥5 次最可信，1 次需人工核。
· 槽按「游戏写入时间」降序读 —— 游戏改版改名时以新档为准。
"""
import argparse
import ast
import collections
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import names_map as NM      # noqa: E402
from app import saveload as S        # noqa: E402

DEFAULT_BASE = r"D:\DevCache\dzlgz"
STATS_DIR = os.path.join(ROOT, "_stats")
REPORT = os.path.join(STATS_DIR, "scan_number_map.txt")

# 人物表（政能数组在这几张表上）
PERSON_TABLES = ("Save_Ren_Data", "Save_Woman_Data", "Save_ED_Ren_Data",
                 "Save_Chu_Sheng_Data", "Save_Rong_Di_Data")
BUFF_TABLE = "Save_KingData/King_Buff_Array"
SLOT_META = "_shiguan_slots.json"

# 分类值：King_Buff_Array.Neng_Li_Or_Zheng_Ce
KIND_POLICY = 0
KIND_ABILITY = 1


# ------------------------------------------------------------------ 工具
def slot_meta(base):
    """读 `_shiguan_slots.json`（拉档时落的设备写入时间）。没有就返回空。"""
    p = os.path.join(base, SLOT_META)
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def split_codes(v):
    """'7115,7098' / [7115, 7098] / '' → ['7115','7098']。"""
    if v in (None, "", 0, []):
        return []
    if isinstance(v, (list, tuple)):
        out = []
        for x in v:
            out.extend(split_codes(x))
        return out
    s = str(v).strip()
    return [p.strip() for p in s.replace("，", ",").split(",") if p.strip()] if s else []


def _sort_slots(slots, meta):
    """新档优先：按设备写入时间降序；无元数据的排最后。"""
    def key(p):
        name = os.path.basename(p)
        m = meta.get(name) or {}
        return (m.get("device_mtime") or m.get("pulled_at") or "", )
    return sorted(slots, key=lambda p: key(p)[0], reverse=True)


# ------------------------------------------------------------------ 扫描
def scan(base, log):
    """扫全部槽，返回 (seen, rec, n_rows, loaded)。"""
    meta = slot_meta(base)
    slots = _sort_slots(S.list_slots(base), meta)
    log(f"槽根目录: {base}")
    log(f"发现槽 {len(slots)} 个，按设备写入时间新→旧：")
    for p in slots:
        m = meta.get(os.path.basename(p)) or {}
        log(f"    {os.path.basename(p):<18} 游戏写入 {m.get('device_mtime', '(无记录)'):<18}"
            f" 拉到本机 {m.get('pulled_at', '-')}")

    seen_zc, seen_nl = collections.Counter(), collections.Counter()   # 出现过（分母）
    rec_zc, rec_nl = collections.defaultdict(collections.Counter), \
        collections.defaultdict(collections.Counter)                  # 反解（分子）
    n_rows = 0
    loaded = 0

    for sp in slots:
        try:
            slot = S.SaveSlot(sp).load()
        except Exception as e:
            log(f"    ! 跳过 {os.path.basename(sp)}: {e}")
            continue
        loaded += 1
        for tname in PERSON_TABLES:
            t = slot.table(tname)
            if t is None:
                continue
            for r in t.rows:
                for c in split_codes(r.get("Ren_Zheng_Ce_Array")):
                    seen_zc[c] += 1
                for c in split_codes(r.get("Ren_Neng_Li_Array")):
                    seen_nl[c] += 1
        t = slot.table(BUFF_TABLE) or slot.find("King_Buff_Array")
        if t is None:
            continue
        for r in t.rows:
            n_rows += 1
            name = str(r.get("Buff_Name") or "").strip()
            if not name:
                continue
            tv = r.get("Neng_Li_Or_Zheng_Ce")
            if tv == KIND_POLICY:
                v = r.get("Zheng_Ce_Data")
                if v not in (None, "", 0):
                    rec_zc[str(v)][name] += 1
            elif tv == KIND_ABILITY:
                v = r.get("Neng_Li_Data")
                if v not in (None, "", 0):
                    rec_nl[str(v)][name] += 1

    return {"seen": (seen_zc, seen_nl), "rec": (rec_zc, rec_nl),
            "n_rows": n_rows, "loaded": loaded, "total": len(slots)}


def _clean(rec):
    """拆成 (唯一命名, 冲突)。"""
    clean = {c: list(v)[0] for c, v in rec.items() if len(v) == 1}
    conf = {c: dict(v) for c, v in rec.items() if len(v) > 1}
    return clean, conf


def _tier(rec):
    """按跨槽重复次数分层。"""
    t = collections.Counter()
    for names in rec.values():
        if len(names) != 1:
            continue
        n = list(names.values())[0]
        t["≥5 次" if n >= 5 else ("3-4 次" if n >= 3 else ("2 次" if n == 2 else "1 次"))] += 1
    return t


def dup_check():
    """AST 体检 names_map 各字典的重复键 —— 运行时的 dict 看不见这个问题。

    ★ 正是这一步抓到：`86` 同时被写成 教化同门(实证段) 与 烈山为田(推定段)，
      字面量后者胜 → 实证结论被静默覆盖。
    """
    src = open(os.path.join(ROOT, "app", "names_map.py"), encoding="utf-8").read()
    rows = []
    for node in ast.parse(src).body:
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict)):
            continue
        name = getattr(node.targets[0], "id", None)
        if not name:
            continue
        lit = [(k.value, getattr(v, "value", None))
               for k, v in zip(node.value.keys, node.value.values)
               if isinstance(k, ast.Constant)]
        cnt = collections.Counter(k for k, _ in lit)
        dup = [k for k, c in cnt.items() if c > 1]
        conflict = []
        for k in dup:
            vs = [v for kk, v in lit if kk == k]
            if len({str(x) for x in vs}) > 1:
                conflict.append((k, vs))
        rows.append({"name": name, "keys": len(lit), "uniq": len(cnt),
                     "dup": len(dup), "conflict": conflict})
    return rows


def audit(label, clean, known):
    """反解 vs names_map。"""
    k = {str(a): b for a, b in known.items()}
    same = [(c, k[c]) for c in clean if c in k and k[c] == clean[c]]
    diff = [(c, k[c], clean[c]) for c in clean if c in k and k[c] != clean[c]]
    new = {c: clean[c] for c in clean if c not in k}
    missing = sorted([c for c in k if c not in clean],
                     key=lambda x: int(x) if x.isdigit() else 0)
    return {"label": label, "same": same, "diff": diff, "new": new,
            "only_known": missing}


# ------------------------------------------------------------------ 报告
def build_report(res, log):
    seen_zc, seen_nl = res["seen"]
    rec_zc, rec_nl = res["rec"]
    log("")
    log(f"扫描：{res['loaded']}/{res['total']} 个槽载入成功，"
        f"{res['n_rows']} 条授予记录")
    log("")
    log("=" * 74)
    log("一、反解结果")
    log("=" * 74)
    clean_zc, conf_zc = _clean(rec_zc)
    clean_nl, conf_nl = _clean(rec_nl)
    log(f"  政策：{len(clean_zc)} 个编号拿到唯一名字（冲突 {len(conf_zc)} 个）"
        f"  分层 {dict(_tier(rec_zc))}")
    log(f"  能力：{len(clean_nl)} 个编号拿到唯一名字（冲突 {len(conf_nl)} 个）"
        f"  分层 {dict(_tier(rec_nl))}")
    log("")
    log("=" * 74)
    log("二、覆盖率（对「存档里实际出现过」的编号）")
    log("=" * 74)
    for label, seen, clean, conf in (("政策", seen_zc, clean_zc, conf_zc),
                                     ("能力", seen_nl, clean_nl, conf_nl)):
        uniq = {c for c in seen if c}
        got = [c for c in uniq if c in clean]
        miss = [c for c in uniq if c not in clean]
        pct = 100.0 * len(got) / max(len(uniq), 1)
        log(f"  【{label}】出现过 {len(uniq)} 个 → 反解可命名 {len(got)} 个"
            f"（{pct:.1f}%），仍缺 {len(miss)} 个（含 {len(conf)} 个「有记录但同号多名」）")
    log("")
    log("=" * 74)
    log("三、与 names_map 审计")
    log("=" * 74)
    audits = {}
    for label, clean, known in (("政策", clean_zc, NM.ZHENG_CE_CODES),
                                ("能力", clean_nl, NM.NENG_LI_CODES)):
        a = audit(label, clean, known)
        audits[label] = a
        log(f"  【{label}】names_map {len(known)} 条 · 反解 {len(clean)} 条")
        log(f"      一致 {len(a['same'])} · 不一致 {len(a['diff'])} · "
            f"可新增 {len(a['new'])} · names_map 独有 {len(a['only_known'])}")
        if a["diff"]:
            log("      —— 不一致明细（反解=存档原文，names_map=人工/推定）——")
            for c, kn, rc in sorted(a["diff"], key=lambda x: int(x[0]) if x[0].isdigit() else 0):
                hit = rec_zc if label == "政策" else rec_nl
                cnt = list(hit[c].values())[0] if c in hit else 0
                log(f"         {c:<6} names_map={kn:<12} 存档={rc:<12}（存档名出现 {cnt} 次）")
    log("")
    log("=" * 74)
    log("四、names_map 内部健康检查（AST 解析源码，运行时看不见）")
    log("=" * 74)
    for row in dup_check():
        flag = "  ⚠️ 有值冲突" if row["conflict"] else ""
        log(f"  {row['name']:<18} 键 {row['keys']:>4}  去重 {row['uniq']:>4}  "
            f"重复 {row['dup']:>2}{flag}")
        for k, vs in row["conflict"]:
            log(f"      ⚠️ 键 {k!r} 被写了多次，字面量后者胜 → 实际生效 = {vs[-1]!r}")
            log(f"         全部写法：{vs}")
    log("")
    log("=" * 74)
    log("五、冲突项（同号多名，需人工确认，未自动裁决）")
    log("=" * 74)
    for label, conf in (("政策", conf_zc), ("能力", conf_nl)):
        if not conf:
            log(f"  【{label}】无")
            continue
        log(f"  【{label}】{len(conf)} 个")
        for c, names in sorted(conf.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0):
            top = sorted(names.items(), key=lambda x: -x[1])
            log(f"     {c:<6} " + " | ".join(f"{n}×{k}" for n, k in top[:6]))
    return clean_zc, clean_nl, audits


def emit_insert(clean_zc, clean_nl, audits):
    """打印可直接粘进 names_map 的键值块（只含可新增部分）。"""
    out = []
    for label, clean, a, tgt in (("政策", clean_zc, audits["政策"], "ZHENG_CE_CODES"),
                                 ("能力", clean_nl, audits["能力"], "NENG_LI_CODES")):
        new = a["new"]
        if not new:
            continue
        out.append(f"# -------- 以下 {len(new)} 条可插入 {tgt} --------")
        out.append(f"    # —— 存档反解（King_Buff_Array 授予记录，游戏原文）{time.strftime('%Y-%m-%d')} ——")
        # 按编号数值序排列，便于比对
        lines, cur = [], []
        for c in sorted(new, key=lambda x: int(x) if x.isdigit() else 0):
            cur.append(f'{c}: "{new[c]}"')
            if len(cur) == 3:
                lines.append("    " + ", ".join(cur) + ",")
                cur = []
        if cur:
            lines.append("    " + ", ".join(cur) + ",")
        out.extend(lines)
        out.append("")
    return "\n".join(out)


TREE_TABLE = "Save_KingData"
TREE_OFFSET = 2000          # 政策树 Code = 政策编号 + 2000


def export_tree(base, log):
    """导出存档里的政策树结构（流派 → 树支 → 政策编号）→ `_stats/policy_tree.json`。

    `Save_KingData.Zheng_Ce_Shu_Array` 是**按流派分组**的政策树，
    `Code = 政策编号 + 2000`（儒 9187→7187、道 9218→7218，与 names_map 核对全中）。

    ★ 为什么这个导出很重要：它给出每个流派的**连续编号区间**
      （九大诸子各 31 个连续、方国七流各 13 个连续），
      于是「**一流派一截图**」才成立 —— 一图配 13 或 31 个编号，
      而且可以按**树支位置**与游戏界面逐一比对，没有顺序歧义。
      （旧办法「一人一截图」既要 150+ 轮，又有 reversed 渲染的错位风险。）
    """
    flow_codes = collections.defaultdict(collections.Counter)
    flow_struct = {}
    scanned = 0
    for sp in S.list_slots(base):
        try:
            slot = S.SaveSlot(sp).load()
        except Exception:
            continue
        t = slot.table(TREE_TABLE)
        if t is None:
            continue
        for r in t.rows:
            tree = r.get("Zheng_Ce_Shu_Array")
            if not isinstance(tree, list):
                continue
            for grp in tree:
                if not isinstance(grp, dict):
                    continue
                wen = str(grp.get("Wen_Hua") or "").strip()
                if not wen:
                    continue
                tmp, n = [], 0
                for br in (grp.get("Shu_Zi") or []):
                    codes = []
                    for item in (br.get("Zheng_Ce") or []):
                        c = item.get("Code") if isinstance(item, dict) else None
                        if isinstance(c, int) and c > TREE_OFFSET:
                            codes.append(c - TREE_OFFSET)
                    if codes:
                        tmp.append(codes)
                        n += len(codes)
                if not n:
                    continue
                scanned += 1
                for cs in tmp:
                    for c in cs:
                        flow_codes[wen][c] += 1
                if wen not in flow_struct or n > sum(len(x) for x in flow_struct[wen]):
                    flow_struct[wen] = tmp

    log("")
    log("=" * 74)
    log("附：政策树（`Save_KingData.Zheng_Ce_Shu_Array`，Code = 编号 + 2000）")
    log("=" * 74)
    log(f"  {len(flow_codes)} 个流派 · {sum(len(v) for v in flow_codes.values())} 条记录")
    log(f"  {'流派':<10}{'编号数':>6}  {'编号区间':<16}{'已配':>5}{'待配':>5}")
    total_gap = 0
    for wen in sorted(flow_codes, key=lambda k: min(flow_codes[k])):
        cs = sorted(flow_codes[wen])
        known = [c for c in cs if c in NM.ZHENG_CE_CODES]
        gap = len(cs) - len(known)
        total_gap += gap
        log(f"  {wen:<10}{len(cs):>6}  {cs[0]}–{cs[-1]:<12}{len(known):>5}{gap:>5}")
    log(f"  → 政策树范围内待配合计 {total_gap} 个")
    log("    对齐用法：照游戏**政策树界面**截图，按树支顺序与下面的结构比对")

    out = os.path.join(STATS_DIR, "policy_tree.json")
    os.makedirs(STATS_DIR, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"流派": {k: sorted(v) for k, v in flow_codes.items()},
                   "树结构": flow_struct},
                  f, ensure_ascii=False, indent=1)
    log(f"  树结构已导出 → {out}")
    return out


# ---------------------------------------------------------------- 效果类别档案
# ★ 2026-09-22 新增：`King_Buff_Array` 不只有政策/能力两种，实际有 15 种类别码
#   （`Neng_Li_Or_Zheng_Ce`）。每组都自带 `Buff_Name`（游戏原文），
#   所以这里能**零人工**拿到「类别码 → 编号 → 中文名」全表。
KIND_LABEL = {
    0: "政策", 1: "能力", 2: "祭祀", 3: "外交盟约", 6: "状态增益", 7: "政体",
    8: "政治格局", 9: "文物", 16: "奇观", 30: "天时", 31: "技术积累",
    32: "兵种传统", 40: "技术", 102: "年号", 103: "辅政",
}


def export_kinds(base, log):
    """导出 `King_Buff_Array` 全部类别码 → 编号↔中文名。"""
    from collections import defaultdict
    pairs = defaultdict(lambda: defaultdict(set))
    extra = defaultdict(lambda: defaultdict(set))
    for sn in _sort_slots([s for s in os.listdir(base)
                           if os.path.isdir(os.path.join(base, s))], slot_meta(base)):
        p = os.path.join(base, sn)
        try:
            slot = S.SaveSlot(p).load()
        except Exception:
            continue
        t = slot.table("Save_KingData")
        if t is None:
            continue
        for r in t.rows:
            for it in (r.get("King_Buff_Array") or []):
                if not isinstance(it, dict):
                    continue
                k = it.get("Neng_Li_Or_Zheng_Ce")
                # ★ 编号存在哪个字段，按类别分派（2026-09-22 实测）：
                #   kind=0 政策 → `Zheng_Ce_Data`；kind=1 能力 → `Neng_Li_Data`；
                #   kind=40 技术 → `Buff_Code`（形如 `Technology_1103`）；
                #   kind=16 奇观 → `Qi_Guan_Code`。混用会得到「编号只有 1 个」的假象。
                if k == 0:
                    code = it.get("Zheng_Ce_Data")
                elif k == 1:
                    code = it.get("Neng_Li_Data")
                else:
                    code = it.get("Buff_Code")
                if code in (None, ""):
                    for alt in ("Qi_Guan_Code", "Map_Code"):
                        if it.get(alt) not in (None, ""):
                            code = it.get(alt)
                            break
                key = str(code)
                if it.get("Buff_Name"):
                    pairs[k][key].add(str(it["Buff_Name"]))
                for f in ("Qi_Guan_Code", "Map_Code"):
                    if it.get(f) not in (None, ""):
                        extra[k][key].add("%s=%s" % (f, it[f]))

    log("")
    log("=" * 74)
    log("附二：King_Buff_Array 类别码档案（Neng_Li_Or_Zheng_Ce）")
    log("=" * 74)
    log("")
    for k in sorted(pairs, key=lambda x: (x is None, x)):
        d = pairs[k]
        log("★ kind=%s  %s   编号 %d 个 / 名字 %d 个"
            % (k, KIND_LABEL.get(k, "?"), len(d),
               len({n for s in d.values() for n in s})))
        for code in sorted(d, key=lambda x: (len(x), x)):
            ex = sorted(extra[k].get(code, []))[:2]
            log("  %-22s %s%s" % (code, "、".join(sorted(d[code])),
                                  ("   [" + "; ".join(ex) + "]") if ex else ""))
        log("")
    return pairs


def main():
    ap = argparse.ArgumentParser(description="从存档反解政策/能力编号↔中文名")
    ap.add_argument("--base", default=DEFAULT_BASE, help="实录槽根目录")
    ap.add_argument("--json", default="", help="把反解结果导出到该 JSON")
    ap.add_argument("--emit-insert", action="store_true", help="打印可粘贴的代码块")
    ap.add_argument("--tree", action="store_true", help="附：导出政策树结构")
    ap.add_argument("--kinds", action="store_true",
                    help="附：导出 King_Buff_Array 全部类别码档案（15 类）")
    ap.add_argument("--quiet", action="store_true", help="不打印报告正文")
    args = ap.parse_args()

    lines = []

    def log(s=""):
        lines.append(str(s))
        if not args.quiet:
            print(s, flush=True)

    log("=" * 74)
    log("大周列国志 · 史馆 —— 编号反解报告")
    log(f"生成时间 {time.strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 74)
    log("")
    res = scan(args.base, log)
    clean_zc, clean_nl, audits = build_report(res, log)
    if args.tree:
        export_tree(args.base, log)
    if args.kinds:
        export_kinds(args.base, log)

    os.makedirs(STATS_DIR, exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    if args.json:
        rec_zc, rec_nl = res["rec"]
        _, conf_zc = _clean(rec_zc)
        _, conf_nl = _clean(rec_nl)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"政策": clean_zc, "能力": clean_nl,
                       "政策_冲突": conf_zc, "能力_冲突": conf_nl,
                       "政策_新增": audits["政策"]["new"],
                       "能力_新增": audits["能力"]["new"],
                       "政策_不一致": audits["政策"]["diff"],
                       "能力_不一致": audits["能力"]["diff"]},
                      f, ensure_ascii=False, indent=1)

    if args.emit_insert:
        block = emit_insert(clean_zc, clean_nl, audits)
        print("")
        print(block)
        with open(os.path.join(ROOT, "_scratch", "_insert_block.txt"), "w",
                  encoding="utf-8") as f:
            f.write(block)

    print("")
    print(f"报告已写入 {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
