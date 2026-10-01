# -*- coding: utf-8 -*-
"""全史册 · 人物字段补齐（不给 App 加机制，只把数据补上）。

人物卡上该有的字段（智略/等级/文化/性格/谥号/表字/继位时间/族谱世代/
所在/官职/政策/能力/特质）在 family.json 里没有 —— 它们只存在于**游戏存档
原文**。本脚本把 32 个 staging 档与它们的源存档重新配对，逐人回捞这些
字段，写进 staging 记录的 `extra` 里；随后由合并器（众数/并集）带进
《全史存档》，人物页「谱牒总谱」的适配层直接透传（**界面零改动**）。
⚠️ 本步必须插在 `stage_extract` 与 `merge_books` **之间**：staging 一旦重建
   而没跑这一步，这些字段就会静默丢失（数据只在 staging 的 `extra` 里）。

配对规则：staging 目录名里存了源槽（`Save_All_N__<源目录mtime>`），
在 D:\\DevCache\\dzlgz 下找**同槽、目录 mtime 最接近**的目录
（备份是用 rename 做的，mtime 原样保留 —— 实测 32/32 全中）。

用法：
  python tools/enrich_staging.py            # 演习：只报告，不写
  python tools/enrich_staging.py --apply    # 写入 staging（带备份）
"""
import argparse
import glob
import io
import json
import os
import re
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools.import_from_game import load_tables, write_atomic   # noqa: E402

DATA = r"D:\DevCache\dzlgz"
STAGING = os.path.join(ROOT, "staging")

# 逐人回捞的字段（全部是存档原文的拼音键名，人物页原生认识它们）
# ⚠️ 收盘名单里**不含 `Ren_Dai_Shu`**（原文族谱世代）：谱牒的世代由合并器
#    按合并血缘图重算（使用者 2026-09-25 裁定），原文那份口径不一，不采纳。
#    （老 staging 里若已写进去，合并器还会再拦一道，见 merge_books.py。）
# ★ 2026-09-26 使用者实证补捞 `Ren_End_Old`（**享年**）：
#   游戏对**在世**人物不写卒年（`Ren_End_Time=None`）但写享年，单档人物页靠
#   「生年 + 享年」推算卒年 —— 所以别的存档看着「人人有卒年」，而合并谱
#   （此前没捞享年）只能显示「—」。捞进来之后：合并器按通用逻辑自动带进
#   《全史存档》，`profiles.Profile` 本来就会用它推算 ⇒ **零界面改动**。
SCALARS = ("Ren_Zhi_Lue", "Ren_Wen_Hua", "Ren_Xing_Ge", "Ren_Leve",
           "Ren_Zun_Hao", "Ren_Biao_Zi", "Ren_Ji_Wei_Time",
           "Ren_Map_Name", "Ren_End_Old")
DICTS = ("Ren_In_Map_Position", "Last_Ren_Official_Position_Data")
ARRAYS = ("Ren_Zheng_Ce_Array", "Ren_Neng_Li_Array", "Buff_Array")
WANT = SCALARS + DICTS + ARRAYS


def filled(v):
    return v not in (None, "", 0, [], {})


# ⚠️ **数值型字段：0 也是真值**。等级 0 = 「庶」，智略 0 是合法分数 ——
#    老判据 `filled()` 把 0 当空，于是源档里每档 1200~2300 名「庶」整片丢了，
#    《全史存档》里勾「庶」（男性等级 lv5）筛出 **0 行**
#    （2026-09-25 使用者报「选中总谱后筛选无效」的成因之一）。
NUMERIC = ("Ren_Leve", "Ren_Zhi_Lue")


def has_value(k, v):
    """这个字段值算不算「有值」——**键相关**：数值型认 0。"""
    if k in NUMERIC:
        return v is not None and v != ""
    return filled(v)


def find_src(slot, tag_time):
    """staging 标签 → 源存档目录（同槽、目录 mtime 最接近）。"""
    best = None
    for d in os.listdir(DATA):
        if not d.startswith(slot):
            continue
        p = os.path.join(DATA, d)
        if not os.path.isdir(p):
            continue
        dt = abs(os.path.getmtime(p) - tag_time)
        if dt <= 300 and (best is None or dt < best[0]):
            best = (dt, p)
    return best[1] if best else None


def main():
    ap = argparse.ArgumentParser(description="全史册 · 人物字段补齐")
    ap.add_argument("--apply", action="store_true", help="真正写回 staging")
    args = ap.parse_args()

    total_files = total_hit = total_miss_person = 0
    for era in sorted(os.listdir(STAGING)):
        for tag in sorted(os.listdir(os.path.join(STAGING, era))):
            d = os.path.join(STAGING, era, tag)
            fp = os.path.join(d, "family.json")
            if not os.path.isfile(fp):
                continue
            m = re.match(r"(Save_All_\d+)__(\d{8})_(\d{6})", tag)
            t = time.mktime(time.strptime(m.group(2) + m.group(3),
                                          "%Y%m%d%H%M%S"))
            src = find_src(m.group(1), t)
            if not src:
                print(f"✗ {era:<8} {tag}  找不到源存档")
                continue
            data = json.load(open(fp, encoding="utf-8"))
            people = data["people"]
            by_code = load_tables(src)
            hit = miss = 0
            for nm, rec in people.items():
                raw = by_code.get(str(rec.get("code")))
                ex = {}
                if raw:
                    for k in WANT:
                        v = raw.get(k)
                        if has_value(k, v):
                            ex[k] = v
                if ex:
                    rec["extra"] = ex
                    hit += 1
                else:
                    rec.pop("extra", None)
                    miss += 1
            total_files += 1
            total_hit += hit
            total_miss_person += miss
            n_z = sum(1 for r in people.values()
                      if filled((r.get("extra") or {}).get("Ren_Zhi_Lue")))
            n_e = sum(1 for r in people.values()
                      if filled((r.get("extra") or {}).get("Ren_End_Old")))
            n_d = sum(1 for r in people.values() if filled(r.get("death")))
            print(f"{era:<8} {tag:<26} 补齐 {hit:>5} / 缺 {miss:>4}"
                  f" · 有智略 {n_z:>5} · 有享年 {n_e:>5} · 原始卒年 {n_d:>5}")
            if args.apply and (hit or miss):
                write_atomic(fp, data, keep_backup=True)
    print(f"\n合计：{total_files} 档 · 补齐 {total_hit} 人次 · 无源数据 {total_miss_person} 人次"
          + ("（已写回）" if args.apply else "（演习，未写回 —— 加 --apply 生效）"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
