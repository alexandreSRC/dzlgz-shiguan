# -*- coding: utf-8 -*-
"""显示审计 —— 全表族扫「① 没译的码 ② 该拆成表的复合串」。

为什么要它
============================================================
使用者 2026-10-03：先指出「族域显示裸码 6」「庙主题显示 68656」，
再指出「国世系一长串」「威能效果一坨文字」，最后问
「**你能否检查一下其他菜单和页码，这两个问题似乎普遍存在**」。

这两类毛病**不能靠一个个点开看**去发现 —— 全表族一扫描就都出来了：

  ① **没译的码**：单元格里还混着 ASCII（`sg0001` / `sm0022` / `Qin` …），
     或者字段名是 `*_Code` / `*_Type` 却没有码表、值又全是不明整数。
  ② **该拆成表的**：单元格是「列表套字典」（本该画成子表），
     或是一长串被 `；|,、` 拼起来的复合串（本该拆列）。

用法
============================================================
    python tools/audit_display.py                 # 用 config 当前实录槽
    python tools/audit_display.py --src ... --top 25
报告写 `_stats/audit_display.txt`（不走管道 —— 中文会被二次处理）。

口径
============================================================
· **只报告，不动数据**（与 `scan_number_map.py` / `check_labels.py` 同规）。
· 纯数字**不算**「没译」（兵力 166494 本来就该是数字）；
  只有「含 ASCII 字母」或「码类字段上的不明整数」才计入。
· 逐表抽样 `ROW_CAP` 行，够看清字段全貌、又不至于跑很久。
"""
import argparse
import collections
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import labels as L          # noqa: E402
from app import saveload as S        # noqa: E402

STATS_DIR = os.path.join(ROOT, "_stats")
REPORT = os.path.join(STATS_DIR, "audit_display.txt")
ROW_CAP = 120
LIST_CAP = 40
SEP_RE = re.compile(r"[；;|｜,，、]")
_out = []


def w(s=""):
    _out.append(s)


def walk(v, fam, field, codes, combos, depth=0):
    """递归收：值里的「没译」与「该拆表」。"""
    if depth > 8:
        return
    if isinstance(v, dict):
        for k, x in v.items():
            walk(x, fam, str(k), codes, combos, depth + 1)
        return
    if isinstance(v, list):
        # 列表套字典 ⇒ 本该是一张子表
        if v and isinstance(v[0], dict):
            combos[(fam, field, "列表套字典")] += 1
            for x in v[:3]:
                for k, y in x.items():
                    walk(y, fam, str(k), codes, combos, depth + 1)
            return
        for x in v[:LIST_CAP]:
            walk(x, fam, field, codes, combos, depth + 1)
        return
    # ---- 标量 ----
    if v is None or isinstance(v, bool) or v == "":
        return
    s = str(v)
    if L.is_id_field(field) or field in L.INTERNAL_IDS:
        return
    if L.code_of(field, v) is not None:
        return
    # ⚠️ 先剥富文本再判 ASCII：`<color=#851D12>秦</color>得到 30` 在**界面里本来就
    #   会被 `strip_rich` 剥掉**（labels 的 decode 路径），第一版审计没走那条路，
    #   于是误报了一大批（`Record_Text`）。这里与界面口径对齐。
    s = L.strip_rich(s)
    if re.search(r"[A-Za-z]", s):
        codes[(fam, field, s[:26])] += 1
    elif len(s) >= 30 and len(SEP_RE.findall(s)) >= 3:
        combos[(fam, field, "复合串")] += 1


def main():
    ap = argparse.ArgumentParser(description="全表族显示审计：没译的码 / 该拆表的复合串")
    ap.add_argument("--src", default="")
    ap.add_argument("--top", type=int, default=25)
    a = ap.parse_args()

    src = a.src
    if not src:
        try:
            src = json.load(open(os.path.join(ROOT, "config.json"),
                                 encoding="utf-8")).get("current_record") or ""
        except Exception:
            src = ""

    w("=" * 76)
    w("显示审计 · audit_display.py   %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    w("=" * 76)
    if not src or not os.path.isdir(src):
        w("!! 没有实录槽（%s）" % (src or "未配置"))
        _finish()
        return
    slot = S.SaveSlot(src).load()
    w("实录槽：%s（%d 个表族）" % (src, len(slot.tables)))
    w()

    codes = collections.Counter()
    combos = collections.Counter()
    for name, t in slot.tables.items():
        for r in t.rows[:ROW_CAP]:
            if not isinstance(r, dict):
                continue
            for k, v in r.items():
                walk(v, name, str(k), codes, combos)
        if name == "神明 · 总表":
            continue

    w("① 没译的码（单元格里还混着 ASCII）—— 按出现次数排")
    w("-" * 76)
    w("   %-30s %-22s %-24s %s" % ("表族", "字段", "样例原值", "次数"))
    for (fam, field, sample), n in codes.most_common(a.top):
        w("   %-30s %-22s %-24s %d" % (fam[:30], field[:22], sample, n))
    if not codes:
        w("   [OK] 没扫到含 ASCII 的裸值")
    w()
    w("   小计：%d 处不同（表族·字段·值）" % len(codes))
    w()

    w("② 该拆成表的（列表套字典 / 长复合串）")
    w("-" * 76)
    w("   %-30s %-26s %-12s %s" % ("表族", "字段", "类型", "次数"))
    for (fam, field, kind), n in combos.most_common(a.top):
        w("   %-30s %-26s %-12s %d" % (fam[:30], field[:26], kind, n))
    if not combos:
        w("   [OK] 没扫到")
    w()
    w("   小计：%d 处不同（表族·字段·类型）" % len(combos))

    _finish()


def _finish():
    w("=" * 76)
    os.makedirs(STATS_DIR, exist_ok=True)
    text = "\n".join(_out) + "\n"
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(text)
    print(text)
    print("报告已写：%s" % REPORT)


if __name__ == "__main__":
    main()
