# -*- coding: utf-8 -*-
"""回填**被「时代兜底」抬到当代**的世代（★ 2026-10-11 使用者：「先做回填」）。

## 治什么病

抽取器最后一条兜底是 `世代＝本档开局年那一代的桶`（秦末 → 第 97 代）。它服务的是
「无生年、父链又断的当代路人」—— 对是对的。但游戏族谱表里那条「**显示世代**」占位链
（`X父 / X祖 / X曾 / X高`，编号纯数字、名带后缀、无生年）也被塞了进来，于是
**春秋先祖**（姬阖闾、姬夫差、姜斯、韩起、曾点…）统统被兜到第 97~99 代
＝ 约公元前 200 年；而且一旦落谱，**续谱时还会按「父代 +1」继续往下传**。

## 判据（与 `import_from_game.build` 的「按儿女回推」同源）

只看**谱内自己的父子链 + 生年**，不读存档：

1. 生年 → 应为的世代 `bucket_gen(生年)`（与抽取器同一张桶表）。
2. **坏锚** P：`P 无生年` 且 `P 有儿女` 且 `min(bucket_gen(儿女生年)) - 1 <= P.世代 - 5`
   —— 即「儿女的生年说 P 该早得多，可 P 的世代却晚了一大截」。
   阈值 5：桶表本身只有 ~57% 吻合，留足噪声余量，只抓**明显被抬**的（实测这类偏差 ≥15）。
3. 修正量 `delta = (min(bucket_gen(儿女生年)) - 1) - P.世代`，沿**父边**把整支
   **连续链**（子代 == 父代 + 1）一起平移 —— 手工排过的（不连续）**不碰**。

⚠️ 只动「连续链」，是因为不连续 = 有人手工排过；宁留勿改。
⚠️ 史馆开着时不要写盘。**先跑演习**。

用法：
    python tools/repair_gen.py [谱名]            # 演习（默认 秦末宋兴）
    python tools/repair_gen.py [谱名] --apply    # 真写（先备份 family.json.bak_*）
"""
import io
import json
import os
import shutil
import sys
import time
from collections import defaultdict

try:
    if getattr(sys.stdout, "buffer", None) is not None:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                      errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tools.import_from_game import bucket_gen          # noqa: E402

NAME = [a for a in sys.argv[1:] if not a.startswith("-")]
NAME = NAME[0] if NAME else "秦末宋兴"
BOOK = os.path.join(ROOT, "saves", NAME, "family.json")

MIN_GAP = 5          # 「儿女说该早多少代」才认定为坏锚（桶表噪声余量）


def year_of(info):
    b = str((info or {}).get("birth") or "").split(",")[0].strip()
    try:
        return int(b)
    except (ValueError, TypeError):
        return None


def main():
    apply = "--apply" in sys.argv
    d = json.load(open(BOOK, encoding="utf-8"))
    p = d["people"]

    # 儿女（父优先，父空才认母 —— 与抽取器 `father_get or mother_get` 同口径）
    kids = defaultdict(list)
    for n, r in p.items():
        par = str(r.get("father") or "").strip() or str(r.get("mother") or "").strip()
        if par and par in p and par != n:
            kids[par].append(n)

    bg = {n: bucket_gen(y) for n, r in p.items() if (y := year_of(r)) is not None}

    # ① 找坏锚
    anchors = {}
    for n, r in p.items():
        if n in bg:                       # 自己有生年 ⇒ 不是"定不出来"的那类
            continue
        try:
            g = int(r.get("generation") or 0)
        except (TypeError, ValueError):
            continue
        if g <= 0:
            continue
        cand = [bg[k] for k in kids.get(n, ()) if k in bg]
        if not cand:
            continue
        want = min(cand) - 1
        if want <= g - MIN_GAP:
            anchors[n] = want

    # ② 沿父边平移「连续链」（子代 == 父代 + 1）
    old_gen = {n: (r.get("generation") or 0) for n, r in p.items()}
    changed = {}                          # 名 → (旧, 新)
    for a, want in sorted(anchors.items(),
                          key=lambda kv: -len(kids.get(kv[0], ()))):
        g0 = old_gen.get(a) or 0
        if a in changed:                  # 已被上一支带过
            continue
        delta = want - g0
        if delta == 0:
            continue
        stack = [a]
        seen = set()
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            if cur not in changed:
                changed[cur] = (old_gen.get(cur, 0), old_gen.get(cur, 0) + delta)
            for k in kids.get(cur, ()):
                if k in changed or k in seen:
                    continue
                if (old_gen.get(k) or 0) == (old_gen.get(cur) or 0) + 1:
                    stack.append(k)       # 连续 ⇒ 认定是被带上去的

    print("谱牒 %s：%d 人" % (NAME, len(p)))
    print("  坏锚（无生年、被兜到晚代，儿女生年说该早 ≥%d 代）：%d 个"
          % (MIN_GAP, len(anchors)))
    for a, want in sorted(anchors.items()):
        now = old_gen.get(a, 0)
        n_kid = sum(1 for k in kids.get(a, ()) if k in bg)
        print("    %-14s 世代 %s → %s（Δ%+d；%d 个有生年的儿女作证）"
              % (a, now, want, want - now, n_kid))
    print("  受影响（含连续链上的后代）：%d 人" % len(changed))
    up = sum(1 for _n, (o, w) in changed.items() if w > o)
    print("    其中调早 %d · 调晚 %d" % (len(changed) - up, up))

    # 抽检：把「生年 vs 世代」偏差 ≥5 的人数报出来（改前 / 改后）
    def mismatch(genmap):
        c = 0
        for n, r in p.items():
            y = year_of(r)
            if y is None:
                continue
            g = genmap.get(n, 0) or 0
            if abs(g - bg[n]) >= 5:
                c += 1
        return c
    after = {n: (changed.get(n, (0, old_gen.get(n, 0)))[1]) for n in p}
    print("  体检：世代与生年严重不符者 %d → %d 人"
          % (mismatch(old_gen), mismatch(after)))

    # 目标抽检：这几个是使用者的诊断样本（吴国先祖一支）
    _chk = [n for n in ("姬阖闾父", "姬阖闾", "姬夫差", "姬友", "姜斯父", "姜斯",
                        "曾点父", "曾点", "韩起父", "韩起")
            if n in p and n in changed]
    if _chk:
        print("  抽检：")
        for n in _chk:
            o, w = changed[n]
            print("    %-10s 世代 %s → %s" % (n, o, w))

    if not changed:
        print("\n没有要改的 —— 这一档不需要回填。")
        return
    if not apply:
        print("\n这是**演习**。确认后加 --apply。")
        return

    ts = time.strftime("%Y%m%d_%H%M%S")
    shutil.copy2(BOOK, BOOK + ".bak_" + ts)
    for n, (_o, w) in changed.items():
        p[n]["generation"] = w
    with open(BOOK, "w", encoding="utf-8") as fp:
        json.dump(d, fp, ensure_ascii=False, indent=1)
    print("\n已回填 %d 人（备份 family.json.bak_%s）" % (len(changed), ts))


if __name__ == "__main__":
    main()
