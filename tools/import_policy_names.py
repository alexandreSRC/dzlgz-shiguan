# -*- coding: utf-8 -*-
"""从**游戏本体**补全政策名：APK 政策表 → `app/names_map.py` 的 `ZHENG_CE_CODES`。

为什么要这个工具（2026-09-30 使用者报「还有没解释出来的政策名啊」）：
  项目里的政策名原来是**人工对截图**一条条录的（779 条），
  而游戏本体里有一张**完整的政策表**（1585 条）——
  `assets/assets/resources/import/48/48283ae0-…json` 的 `Zheng_Ce_Data_New`：

      {"Zheng_Ce_Code":7375,"Zheng_Ce_Name":"山乡水肆",
       "Zheng_Ce_Cheng_Ben_Xian_Neng":"0", …,
       "YX":{"Liang_Shi_Shou_Ru":2,"Mu_Cai_Chan_Liang":10,
             "Shou_Pi_Chan_Liang":30,"Liang_Shi_Chan_Liang":3}}

  ⇒ **以游戏原文为准**（规约：宁缺勿猜、尽量搜资料），不再靠截图配对。

用法：
    python tools/import_policy_names.py                 # 只报告差异（默认）
    python tools/import_policy_names.py --apk <path>    # 指定 APK
    python tools/import_policy_names.py --write         # 真的写进 names_map.py
    python tools/import_policy_names.py --json out.json # 导出差异

★ 只**追加项目缺的编号**；**已存在的编号一律不动**
  （同号不同名的 94 条是项目**有意**加的前缀，如
   `202 文军建制卫` ↔ 游戏 `卫` —— 单字在界面里会歧义，不能覆盖）。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)

DEFAULT_APK = os.path.join("_scratch", "game", "ztz.apk")
ZC_ENTRY = ("assets/assets/resources/import/48/"
            "48283ae0-f044-4b16-ac98-b7f446644196.json")
NM_PATH = os.path.join("app", "names_map.py")

# names_map 里的插入锚点：`ZHENG_CE_CODES` 的最后一条 + 收尾大括号。
# 这个组合在文件里唯一（同一个键只允许出现一处，见项目的 AST 体检）。
INSERT_ANCHOR = '    7701: "后尊政治",\n}'


def read_game_table(apk: str) -> dict[int, str]:
    """从 APK 读游戏政策表 → {编号: 名称}。"""
    if not os.path.exists(apk):
        raise SystemExit("找不到 APK：%s\n先 `adb pull` 出来，或用 --apk 指定。" % apk)
    z = zipfile.ZipFile(apk)
    raw = z.read(ZC_ENTRY).decode("utf-8", "replace")
    out: dict[int, str] = {}
    for m in re.finditer(
            r'\{"Zheng_Ce_Code":(\d+),"Zheng_Ce_Name":"([^"]*)"', raw):
        out[int(m.group(1))] = m.group(2)
    if not out:
        raise SystemExit("在 APK 里没解析出政策表 —— 游戏可能更新了资源布局。")
    return out


def diff_against_project(game: dict[int, str]):
    from app import names_map as NM
    proj = NM.ZHENG_CE_CODES
    only_game = {c: n for c, n in game.items() if c not in proj}
    only_proj = {c: n for c, n in proj.items() if c not in game}
    diff = {c: (proj[c], game[c]) for c in game if c in proj and proj[c] != game[c]}
    return only_game, only_proj, diff


def render_block(add: dict[int, str], date: str) -> str:
    """生成可插入的代码块（每行 3 条，便于比对）。"""
    lines = [
        "    # ---- 游戏本体政策表补全（%s，来源：APK `Zheng_Ce_Data_New`）----" % date,
        "    #      以游戏原文为准（此前人工对截图的 779 条保留不动；",
        "    #      同号不同名的 94 条是项目有意加的前缀，如 202=文军建制卫 ↔ 游戏=卫）。",
    ]
    cur: list[str] = []
    for c in sorted(add):
        cur.append('%d: %s' % (c, json.dumps(add[c], ensure_ascii=False)))
        if len(cur) == 3:
            lines.append("    " + ", ".join(cur) + ",")
            cur = []
    if cur:
        lines.append("    " + ", ".join(cur) + ",")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apk", default=DEFAULT_APK)
    ap.add_argument("--write", action="store_true", help="写进 app/names_map.py")
    ap.add_argument("--json", default="", help="把差异导出为 JSON")
    ap.add_argument("--date", default="2026-09-30")
    args = ap.parse_args()

    game = read_game_table(args.apk)
    only_game, only_proj, diff = diff_against_project(game)
    print("游戏表 %d 条 · 项目表 %d 条" % (len(game), len(__import__(
        "app.names_map", fromlist=["x"]).ZHENG_CE_CODES)))
    print("  仅游戏有（要补） %d" % len(only_game))
    print("  仅项目有        %d" % len(only_proj))
    print("  同号不同名      %d（保留项目值，不动）" % len(diff))

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"only_game": {str(k): v for k, v in only_game.items()},
                       "only_proj": {str(k): v for k, v in only_proj.items()},
                       "diff": {str(k): v for k, v in diff.items()}},
                      f, ensure_ascii=False, indent=1)
        print("差异已导出 →", args.json)

    if not only_game:
        print("没有要补的 —— 已是最新。")
        return

    if not args.write:
        print("\n（未写入。加 --write 才会改 app/names_map.py）")
        print(render_block(dict(list(only_game.items())[:15]), args.date))
        print("  … 共 %d 条" % len(only_game))
        return

    with io.open(NM_PATH, encoding="utf-8") as f:
        src = f.read()

    # 幂等：**只在 `ZHENG_CE_CODES` 这一段**里扫已有编号。
    #   ⚠️ 不能全文扫 —— `NENG_LI_CODES` 也有 `1: "…"` 这类行，
    #   全文扫会把「政策 1」误判成已存在（第一版就这么错了）。
    head = "ZHENG_CE_CODES = {"
    i0 = src.find(head)
    i1 = src.find("\n}\n", i0)
    if i0 < 0 or i1 < 0:
        raise SystemExit("定位不到 ZHENG_CE_CODES 的范围，拒绝写入。")
    seg = src[i0:i1]
    already = {int(m) for m in re.findall(r'^\s*(\d+): ', seg, re.M)}
    add = {c: n for c, n in only_game.items() if c not in already}
    if not add:
        print("全部编号都已存在，无需插入。")
        return
    if INSERT_ANCHOR not in src:
        raise SystemExit("找不到插入锚点（`ZHENG_CE_CODES` 的结尾），"
                         "请手工合并：\n" + render_block(add, args.date)[:400])
    assert src.count(INSERT_ANCHOR) == 1, "锚点不唯一，拒绝写入"
    # ⚠️ 锚点必须**原样保留**（它含最后一条政策 7701）——
    #   第一版用 `replace(锚点, block + "}")` 把 7701 那行吃掉了。
    block = render_block(add, args.date)
    src = src.replace(INSERT_ANCHOR, block.rstrip("\n") + "\n" + INSERT_ANCHOR, 1)
    with io.open(NM_PATH, "w", encoding="utf-8") as f:
        f.write(src)
    print("已写入 %d 条 → %s" % (len(add), NM_PATH))


if __name__ == "__main__":
    main()
