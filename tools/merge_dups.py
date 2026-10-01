# -*- coding: utf-8 -*-
"""同名分身合并（★ 2026-09-27 使用者拍板立项）。

网查（九十三批续十六/十七）确认以下「数字后缀」人物与无后缀本名是
**同一史载人物的游戏重复生成**（姓氏还互相矛盾），合并到本名记录：

    曹咎2→曹咎 · 虞卿2→虞卿 · 傅瑕2→傅瑕 · 辛胜2→辛胜 · 江乙2→江乙 · 殷通2→殷通

合并动作（--apply，写盘前自动备份）：
  1. 全谱把指向分身的引用改指本名（father/mother/spouse/associate_of/父链）；
  2. 分身名下的推定字段（father_guess/associate_of/guess_note）删除
     —— 推定层由 guess_lineage 统一重建；
  3. 删除分身记录。
⚠️ 数字后缀 ≠ 都是分身：游戏对**真实重名**也加序数（如 姬去齐），所以
   本表只收录**网查实证的同人物重复**，不做事后泛化。
"""
import argparse
import collections
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

DUPS = {"曹咎2": "曹咎", "虞卿2": "虞卿", "傅瑕2": "傅瑕",
        "辛胜2": "辛胜", "江乙2": "江乙", "殷通2": "殷通"}
REF_KEYS = ("father", "mother", "spouse", "associate_of")
GUESS_KEYS = ("father_guess", "associate_of", "guess_note")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    fp = os.path.join(ROOT, "saves", "全史存档", "family.json")
    payload = json.load(open(fp, encoding="utf-8"))
    people = payload["people"]

    rep = []
    for dup, keep in DUPS.items():
        if dup not in people:
            rep.append(f"跳过 {dup}：不在谱内（可能已合并）")
            continue
        if keep not in people:
            rep.append(f"跳过 {dup}：本名 {keep} 不在谱内")
            continue
        n_ref = 0
        for nm, r in people.items():
            for k in REF_KEYS:
                if r.get(k) == dup:
                    r[k] = keep
                    n_ref += 1
            # 父链数组形态（spouses 等）
            sp = r.get("spouses")
            if isinstance(sp, list) and dup in sp:
                r["spouses"] = [keep if x == dup else x for x in sp]
                n_ref += 1
        # 分身自身的推定字段清掉（推定层由 guess_lineage 重建）
        for k in GUESS_KEYS:
            people[keep].pop(k, None)
        rep.append(f"合并 {dup} → {keep}：改引用 {n_ref} 处，删除分身")
        del people[dup]

    print("\n".join(rep))
    if not a.apply or a.dry:
        print("（--dry：没有写盘）")
        return
    bak = fp + time.strftime(".bak_%Y%m%d_%H%M%S")
    shutil.copy(fp, bak)
    tmp = fp + ".tmp"
    json.dump(payload, open(tmp, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    os.replace(tmp, fp)
    print(f"已写 {fp}（备份 {os.path.basename(bak)}）；"
          f"谱内现 {len(people)} 人 —— 请紧接着跑 guess_lineage --apply 重建推定层")


if __name__ == "__main__":
    main()
