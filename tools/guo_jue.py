# -*- coding: utf-8 -*-
"""国爵 / 建国年 汇总 —— 从各档存档的 `Save_KingData_*.json` 抽「国 → 爵位」。

★ 2026-09-26 使用者裁定（第 2 / 6 项）：
  **五等爵始于周**（史料：「五等爵位……形成于西周时期」），所以「周及以后的诸侯
  按**实际爵位**上色」，而实际爵位 = **国爵**（`King_Jue_Wei_Code`）——
  齐=侯、宋=公、楚=子。人物身上的 `fief_title` 存的是游戏按**尊号**推的爵位
  （齐君死后尊称「齐桓公」→ 公），**周以后不能拿它当爵位用**。
  （`import_from_game` 里国爵本来就有，只是排在尊号**后面**兜底，永远用不上。）

产出（写进谱牒 `source`，不动 people）：
  · `guo_jue`     = {国: {朝代: 爵称}}   —— 按**档的朝代**分层（秦国爵在战国档是
                    「王」、秦末档是「帝」，分层才不会被混成一个）
  · `guo_founded` = {国: 建国年}          —— 给「封代重编号」当锚点（第 1 项）

读的是 `D:\\DevCache\\dzlgz` 下的**全部档**（不止 32 档）：样本越多众数越稳。
用法：python tools/guo_jue.py --apply [--dry]
"""
import argparse
import collections
import glob
import io
import json
import os
import shutil
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.jue import coarse_era                                  # noqa: E402
from app.timeline import era_of                                 # noqa: E402
from tools.import_from_game import JUE_CODE, detect_start_year   # noqa: E402

DATA_DIR = r"D:\DevCache\dzlgz"
# ★ 2026-09-26：主缓存目录可能被挪走（实测整目录改名成「旧导出_…」）——
#   找不到就回退到同级的 dzlgz* 目录里最新的那个。
if not os.path.isdir(DATA_DIR):
    import glob as _g
    _cand = sorted(_g.glob(os.path.join(os.path.dirname(DATA_DIR), "dzlgz*")),
                   key=os.path.getmtime)
    if _cand:
        DATA_DIR = _cand[-1]
BOOK = "全史存档"
SAVE_FP = os.path.join(ROOT, "saves", BOOK, "family.json")


def scan():
    """扫全部槽：国 → 朝代 → 爵位众数；国 → 建国年众数。"""
    jue_votes = collections.defaultdict(collections.Counter)
    found_votes = collections.defaultdict(collections.Counter)
    slots = 0
    for d in sorted(glob.glob(os.path.join(DATA_DIR, "Save_All_*"))):
        if not os.path.isdir(d):
            continue
        files = sorted(glob.glob(os.path.join(d, "Save_KingData_*.json")))
        if not files:
            continue
        try:
            y0 = detect_start_year(d)
        except Exception:
            y0 = None
        # ★ 存**细朝代**（西周/春秋/战国/秦/汉…）＋粗朝代两把钥匙：
        #   秦国的国爵在春秋是「公」、战国是「王」、秦代是「帝」，
        #   只按粗朝代「周」分层会被混成一个。
        era = era_of(y0) if y0 is not None else ""
        era_keys = (era, coarse_era(era)) if era else ()
        slots += 1
        for f in files:
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    o = json.load(fh)
            except Exception:
                continue
            if not isinstance(o, dict):
                continue
            nm = (o.get("King_Name") or "").strip()
            if not nm:
                continue
            jue = JUE_CODE.get(o.get("King_Jue_Wei_Code"), "")
            if jue:
                for _e in era_keys:
                    jue_votes[nm][(_e, jue)] += 1
            jy = o.get("Jian_Guo_Year")
            try:
                jy = int(str(jy).split(",")[0])
            except (TypeError, ValueError):
                jy = None
            if jy is not None and -4000 <= jy <= 2000:
                found_votes[nm][jy] += 1
    print(f"  扫了 {slots} 个槽")
    guo_jue, guo_founded, flat = {}, {}, {}
    for nm, c in jue_votes.items():
        by_era = {}
        for (era, jue), n in c.items():
            if era:
                by_era.setdefault(era, collections.Counter())[jue] += n
        guo_jue[nm] = {e: cc.most_common(1)[0][0] for e, cc in by_era.items()}
        flat[nm] = c.most_common(1)[0][0][1]        # 众数（无朝代信息时兜底）
    for nm, c in found_votes.items():
        guo_founded[nm] = c.most_common(1)[0][0]
    return guo_jue, flat, guo_founded


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="写进谱牒 source")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    print(f"== 抽国爵（源：{DATA_DIR}）==")
    guo_jue, flat, guo_founded = scan()
    print(f"  国 {len(guo_jue)} 个 · 有建国年 {len(guo_founded)} 个")
    for nm in ("齐", "宋", "楚", "燕", "鲁", "晋", "秦", "陈", "卫", "蔡",
               "曹", "郑", "吴", "越", "韩", "赵", "魏", "田齐"):
        if nm in guo_jue:
            print(f"    {nm:<4} {guo_jue[nm]} · 建国年 {guo_founded.get(nm, '?')}")
    if not a.apply or a.dry:
        print("（--dry：没有写盘）")
        return
    with open(SAVE_FP, "r", encoding="utf-8") as f:
        payload = json.load(f)
    bak = SAVE_FP + time.strftime(".bak_%Y%m%d_%H%M%S")
    shutil.copy(SAVE_FP, bak)
    src = payload.setdefault("source", {})
    src["guo_jue"] = guo_jue
    src["guo_jue_flat"] = flat
    src["guo_founded"] = guo_founded
    src["guo_jue_note"] = ("国爵（King_Jue_Wei_Code）按档的朝代分层 —— 周及以后"
                           "诸侯上色用；建国年（Jian_Guo_Year）给封代重编号当锚点")
    tmp = SAVE_FP + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    os.replace(tmp, SAVE_FP)
    print(f"  已写 {SAVE_FP}\n  备份 {os.path.basename(bak)}")


if __name__ == "__main__":
    main()
