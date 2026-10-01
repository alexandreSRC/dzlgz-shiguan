# -*- coding: utf-8 -*-
"""全史册工程 · staging 抽取器（第七十批）。

用途：使用者逐剧本做新档，本脚本对每个新槽做**一次性史实全量抽取**，
落盘到 ``staging/`` 暂存区 —— 等所有剧本都抽完，再由合并器统一归并成《全史册》。

设计约定：
  * 抽取口径 ``--prune hist``（只收史实人物，男女都收 —— 全史册的既定口径）；
  * 落盘位置 ``staging/<剧本名>/<槽名>__<源目录mtime>/family.json``；
    **源目录 mtime 就是游戏写入时刻**，同一份内容重跑是幂等覆盖，不会堆目录；
  * family.json 与谱牒层**同构**（``people`` + ``source``）—— 合并器和五视图
    都能直接吃；但放在 ``staging/`` 而不是 ``saves/``，App 不会把它列进谱牒；
  * 只读存档、只写 staging —— **不碰 config / saves / 模拟器**（工具纪律第 8 条）。

用法：
  python tools/stage_extract.py --src Save_All_110        # 槽名或完整路径
  python tools/stage_extract.py --list                    # 看已抽取清单
"""
import argparse
import io
import json
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools.import_from_game import (          # noqa: E402
    build, check_slot, detect_start_year, write_atomic)
from app import scenarios                     # noqa: E402

DATA_DIR = r"D:\DevCache\dzlgz"
STAGING = os.path.join(ROOT, "staging")


def resolve_src(s):
    """槽名（Save_All_N）→ 完整路径。"""
    if os.path.isdir(s):
        return os.path.abspath(s)
    cand = os.path.join(DATA_DIR, s)
    if os.path.isdir(cand):
        return cand
    print(f"× 找不到槽：{s}（既不是目录，也不在 {DATA_DIR} 下）")
    return None


def slot_mode(name):
    """槽号 → 争霸类型（与续谱对话框同一套号段规则）。"""
    import re
    m = re.match(r"Save_All_(\d+)", name)
    if not m:
        return "?"
    v = int(m.group(1))
    if v <= 999:
        return "沙盒全局"
    if v <= 1999:
        return "争霸模式"
    if v <= 4999:
        return "沙盒局部"
    if v <= 5999:
        return "家族模式"
    return "?"


def extract(src):
    slot = os.path.basename(os.path.normpath(src))
    if not check_slot(src):
        return 1

    start_year = detect_start_year(src, refresh=True)
    sc = scenarios.scenario_match(start_year)
    era = sc[0] if sc and sc[0] else "认不出"
    drift = sc[2] if sc else None

    print(f"  开局年：前{-start_year}" if start_year < 0 else f"  开局年：{start_year}")
    print(f"  剧本：{era}" + (f"（漂移 {drift} 年）" if drift else ""))

    people, stats, _name2code, _gen_src = build(src, [], "hist", False,
                                                history=(slot_mode(slot) == "沙盒全局"))
    if not people:
        print("× 没解析出人物（槽是空的或还是加密态）")
        return 1

    n_hist = sum(1 for v in people.values() if v.get("historical") == "是")
    n_f = sum(1 for v in people.values() if v.get("gender") == "女")

    # 目录键：剧本 + 槽 + 源目录 mtime（游戏写入时刻）—— 幂等
    src_mtime = int(os.path.getmtime(src))
    tag = time.strftime("%Y%m%d_%H%M%S", time.localtime(src_mtime))
    out_dir = os.path.join(STAGING, era, f"{slot}__{tag}")
    os.makedirs(out_dir, exist_ok=True)

    payload = {
        "people": people,
        "source": {
            "slot": slot,
            "slot_path": os.path.abspath(src),
            "era": era,
            "start_year": start_year,
            "mode": slot_mode(slot),
            "scenario_drift": drift,
            "src_mtime": src_mtime,
            "imported": time.strftime("%Y-%m-%d %H:%M"),
            "prune": "hist",
        },
    }
    path = os.path.join(out_dir, "family.json")
    write_atomic(path, payload, keep_backup=False)
    json.dump(payload["source"], open(os.path.join(out_dir, "meta.json"),
                                      "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"  抽取 {len(people)} 人（史实 {n_hist} · 女 {n_f}）→ {path}")
    return 0


def listing():
    if not os.path.isdir(STAGING):
        print("（staging 还是空的）")
        return
    total = 0
    print(f"{'剧本':<12}{'槽':<22}{'开局年':>7}  {'人数':>5}  抽取时间")
    print("-" * 76)
    for era in sorted(os.listdir(STAGING)):
        d1 = os.path.join(STAGING, era)
        if not os.path.isdir(d1):
            continue
        for tag in sorted(os.listdir(d1)):
            meta_p = os.path.join(d1, tag, "meta.json")
            fam_p = os.path.join(d1, tag, "family.json")
            if not os.path.isfile(fam_p):
                continue
            try:
                meta = json.load(open(meta_p, encoding="utf-8"))
                people = json.load(open(fam_p, encoding="utf-8")).get("people", {})
            except Exception:
                print(f"{era:<12}{tag:<22}{'?':>7}  {'?':>5}  （family.json 读不出）")
                continue
            y = meta.get("start_year")
            yy = f"前{-y}" if isinstance(y, int) and y < 0 else str(y)
            total += len(people)
            print(f"{era:<12}{meta.get('slot', '?'):<22}{yy:>7}  {len(people):>5}  "
                  f"{meta.get('imported', '?')}")
    print("-" * 76)
    print(f"合计 {total} 人次（未去重 —— 去重由合并器做）")


def main():
    ap = argparse.ArgumentParser(description="全史册 staging 抽取器")
    ap.add_argument("--src", default="", help="槽名（Save_All_N）或完整路径")
    ap.add_argument("--list", action="store_true", help="列出已抽取的档")
    args = ap.parse_args()
    if args.list:
        listing()
        return 0
    if not args.src:
        print("× 需要 --src（槽名或路径），或 --list")
        return 1
    src = resolve_src(args.src)
    if not src:
        return 1
    return extract(src)


if __name__ == "__main__":
    sys.exit(main())
