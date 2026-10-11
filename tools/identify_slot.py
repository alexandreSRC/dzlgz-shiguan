# -*- coding: utf-8 -*-
"""认「延续槽」—— 从本机缓存的一堆槽里挑出**该续的那一个**（只读）。

为什么需要它（2026-10-03 实测教训）：
  「与谱牒人物重叠率」**不是**判据 —— 一次实测 10 个槽的重叠率全在 82~84%，
  看着都像同一局。真相是那 84% 几乎全是**史实人物**（任何一局秦末档的史实人物
  都相同），根本区分不出局。

真正的判据（本脚本实现的三看）：
  1. **非史实命中率** —— 谱牒里的**非史实人物**是本局随机生成的，跨局不会重合。
     命中 ≈100% ⇒ 同一局；明显偏低（<95%）⇒ 别局或老档。**这是最硬的判据。**
  2. **最晚生年** —— 同局推进时，新出生的人越来越晚，全局生年上限单调递增。
     上限更大 ⇒ 游戏进度更靠后（实测：-150 的槽比 -200 的槽领先 50 年）。
  3. **设备时间** —— 游戏自己写这个档的现实时刻（拉档时存进 `_shiguan_slots.json`
     的 `device_mtime`）。使用者原话：「这个是重要的判断依据」。

用法：
    python tools/identify_slot.py [谱名]      # 默认 秦末起义
"""
import contextlib
import datetime as _dt
import io
import json
import os
import re
import sys

try:
    if getattr(sys.stdout, "buffer", None) is not None:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                      errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tools import import_from_game as IM      # noqa: E402

CACHE = r"__SHIGUAN_CACHE__"
NAME = [a for a in sys.argv[1:] if not a.startswith("-")]
NAME = NAME[0] if NAME else "秦末起义"


def _year(s):
    try:
        return int(str(s).split(",")[0])
    except Exception:
        return None


def latest_birth(slot):
    """全局最晚生年（进度标尺）；扫不出返回 None。"""
    mx = None
    for f in _json_files(slot):
        if os.path.getsize(f) > 8_000_000:
            continue
        try:
            o = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        rows = o if isinstance(o, list) else ([o] if isinstance(o, dict) else [])
        for r in rows:
            if not isinstance(r, dict):
                continue
            for k in ("Ren_Chu_Sheng_Time", "Ren_Start_Time"):
                v = _year(r.get(k))
                if v is not None and (mx is None or v > mx):
                    mx = v
    return mx


def _json_files(slot):
    import glob
    return [f for f in glob.glob(os.path.join(slot, "*.json"))
            if re.search(r"Ren|Wang|King", os.path.basename(f))]


def _parse_mmdt(t):
    """`_shiguan_slots.json` 的 device_mtime → datetime（两种格式都认）。"""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return _dt.datetime.strptime(str(t).strip(), fmt)
        except Exception:
            continue
    return None


def main():
    book = json.load(open(os.path.join(ROOT, "saves", NAME, "family.json"),
                          encoding="utf-8"))
    p = book["people"]
    hist, nonh = set(), set()
    for v in p.values():
        c = str((v or {}).get("code") or "")
        if not c:
            continue
        (hist if (v or {}).get("historical") == "是" else nonh).add(c)

    try:
        meta = json.load(open(os.path.join(CACHE, "_shiguan_slots.json"),
                              encoding="utf-8"))
    except Exception:
        meta = {}

    print("谱牒 %s：%d 人 · 史实 %d · 非史实 %d · 原槽 %s"
          % (NAME, len(p), len(hist), len(nonh),
             (book.get("source") or {}).get("slot")))
    print()
    print("%-14s %-16s %-14s %-9s %-16s %s"
          % ("槽", "非史实命中", "史实命中", "最晚生年", "设备时间", "判定"))
    rows = []
    for s in sorted(os.listdir(CACHE)):
        q = os.path.join(CACHE, s)
        if not os.path.isdir(q) or ".bak" in s:
            continue
        try:
            # load_tables 会打印「族谱表 N 条 …」，这里要把输出表格让出来
            with contextlib.redirect_stdout(io.StringIO()):
                codes = set(IM.load_tables(q))
        except Exception as e:
            print("%-14s 读取失败：%s" % (s, e))
            continue
        a, b = len(hist & codes), len(nonh & codes)
        lb = latest_birth(q)
        rows.append({
            "slot": s, "dir": q,
            "a": a, "b": b,
            "ra": a / max(1, len(hist)), "rb": b / max(1, len(nonh)),
            "lb": lb if lb is not None else -9999,
            "dm": (meta.get(s) or {}).get("device_mtime") or "",
            "same": (b / max(1, len(nonh))) >= 0.95,
        })

    # ★ 2026-10-06 修（本次实盘它建议了 Save_All_2 —— 一个 10-04 的陈留旧槽）：
    #   两处根因：① 缓存目录里**早就被新档覆盖的旧槽**也被当候选；
    #             ② 排序只按「最晚生年」，而旧槽的游戏进度可能反而更靠后
    #                （实测旧槽 -150 > 新槽 -200，于是旧槽被顶到第一位）。
    #   ⇒ ① 只认「设备时间在最新槽 12 小时内」的槽（更旧的标「陈旧缓存」、不进建议）；
    #      ② 排序改为**设备时间优先**（游戏最后写的那个才是该续的），最晚生年次之。
    known = [_parse_mmdt(r["dm"]) for r in rows if _parse_mmdt(r["dm"])]
    newest = max(known) if known else None
    for r in sorted(rows, key=lambda x: (x["dm"], x["lb"]), reverse=True):
        t = _parse_mmdt(r["dm"])
        r["fresh"] = bool(newest) and t is not None \
            and (newest - t) <= _dt.timedelta(hours=12)
        tags = ["同一局" if r["same"] else "— 非同局/老档"]
        if not r["fresh"]:
            tags.append("陈旧缓存")
        print("%-14s %-16s %-14s %-9s %-16s %s"
              % (r["slot"], "%d/%d (%.0f%%)" % (r["b"], len(nonh), r["rb"] * 100),
                 "%d/%d (%.0f%%)" % (r["a"], len(hist), r["ra"] * 100),
                 r["lb"], r["dm"] or "?", " · ".join(tags)))

    cand = [r for r in rows if r["same"] and r["fresh"]]
    if not cand:
        print("\n!! 没有槽同时满足「非史实命中 ≥95%」与「不是陈旧缓存」—— "
              "谱牒可能与现有槽已不同源，别硬续，先问使用者。")
        return
    cand.sort(key=lambda r: (_parse_mmdt(r["dm"]) or _dt.datetime.min, r["lb"]),
              reverse=True)
    top = cand[0]
    print("\n>>> 同一局的槽 %d 个：%s"
          % (len(cand), "、".join(r["slot"] for r in cand)))
    print(">>> 建议续：**%s**（设备时间 %s · 最晚生年 %s）"
          % (top["slot"], top["dm"] or "?", top["lb"] if top["lb"] > -9999 else "?"))
    print('    → python tools\\import_from_game.py --src "%s" --save %s '
          "--prune hist --real-state-only --merge"
          % (top["dir"], NAME))
    print("    （口径 hist ＝ 只收史实；点名的非史实另用 --watch <编号,…> 带上）")


if __name__ == "__main__":
    main()
