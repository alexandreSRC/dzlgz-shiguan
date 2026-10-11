# -*- coding: utf-8 -*-
"""公卿自动关注（＝自动入谱）：复刻 GUI `main.focus_gongqing` 的落盘部分。

做的事（与界面上点一下「自动关注公卿」等价）：
  1. 从存档槽判出**公卿家族**（`app/gongqing.py` 的唯一判据：
     宗庙家族类型 ∈ {公室, 宗室, 卿室} + 该国中夏 + 排除叛军）；
  2. 把「家族本人 + 其父系后裔」`import_codes` 写进谱牒（**批量一次**，绝不逐人调）；
  3. 给这些人在谱里打 `enrolled=True`（入谱标）、把**家族根**加进 `focused_people`（关注名单）；
  4. 已被使用者「取消关注」的人跳过（`unfocused`）。

⚠️ 续谱（merge）之后跑一次 —— 游戏推演会让公卿家族增减（实测 21 → 38 → 47 家）。
⚠️ 史馆开着时不要写盘。

用法：
    python tools/auto_follow_gongqing.py --src "__SHIGUAN_CACHE_E__\\Save_All_1" --save 秦末起义            # 演习
    python tools/auto_follow_gongqing.py --src "__SHIGUAN_CACHE_E__\\Save_All_1" --save 秦末起义 --apply    # 真写
"""
import argparse
import io
import json
import os
import sys

try:
    if getattr(sys.stdout, "buffer", None) is not None:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                      errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.saveload import SaveSlot           # noqa: E402
from app import gongqing as GQ              # noqa: E402
from app import storage                     # noqa: E402
from tools import import_from_game as IM    # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="公卿自动关注（入谱 + 关注名单）")
    ap.add_argument("--src", required=True, help=r"存档槽目录，如 __SHIGUAN_CACHE__\Save_All_1")
    ap.add_argument("--save", default="秦末起义", help="谱牒名（默认 秦末起义）")
    ap.add_argument("--apply", action="store_true", help="真写（不加=演习）")
    a = ap.parse_args()
    SRC, SAVE = a.src, a.save

    slot = SaveSlot(SRC).load()
    fams = GQ.clans(slot)
    print("公卿家族：%d 家（卿室 %d / 宗室 %d / 公室 %d）"
          % (len(fams),
             sum(1 for f in fams if f["type"] == "卿室"),
             sum(1 for f in fams if f["type"] == "宗室"),
             sum(1 for f in fams if f["type"] == "公室")))

    book_path = storage.save_path(SAVE)
    d = json.load(open(book_path, encoding="utf-8"))
    people = d["people"]
    code2name = {str((v or {}).get("code") or ""): nm
                 for nm, v in people.items() if (v or {}).get("code")}
    canvas = storage.load_canvas_state(SAVE)
    unfocused = set(canvas.get("unfocused") or [])

    by_code = IM.load_tables(SRC)
    roots = set()
    for f in fams:
        roots |= set(f["members"])
    skipped = {c for c in roots if code2name.get(str(c)) in unfocused}
    roots -= skipped
    need = set()
    for c in roots:
        if c in by_code:
            need |= set(IM._male_line(by_code, c))
    # ★ 2026-10-07 使用者（续七十二）：「**韩广类比韩淑，他俩一样的逻辑，加入
    #   关注**」—— 韩广不在任何家族的成员表里（游戏没给他家族边），却同样是
    #   秦帝（`King_Str` 第二条）⇒ 家族成员判据永远收不到他。补一条：
    #   **国君（`King_Str` 历代君主）一并关注＋入谱**。见 `GQ.ruler_names`。
    _and_rc = {str(f.get("king_code")) for f in fams
               if f.get("king_code") is not None}
    _name2code = {nm: c for c, nm in code2name.items()}
    _rcodes = {_name2code.get(n, "") for n in GQ.ruler_names(slot, _and_rc)}
    _rcodes = {c for c in _rcodes if c and code2name.get(c) not in unfocused}
    ruler_add = len(_rcodes - roots)
    roots |= _rcodes
    need |= _rcodes
    print("国君（King_Str 历代君主）补关注 %d 人" % ruler_add)
    # ★ 2026-10-05 使用者裁定：宗室填充人**连谱牒都不进**（判据唯一实现
    #   `gongqing.filler_codes`；君主例外照旧在关注环节放行）。与
    #   `main.focus_gongqing` 同一批修的同一道闸。
    _fillers = GQ.filler_codes(by_code, members=need)
    _ruler_codes = {str(r.get("code")) for r in GQ.rulers(slot)}
    _fillers -= _ruler_codes
    if _fillers:
        need -= _fillers
        print("宗室填充人（无任何家族边，不导入）：%d 人" % len(_fillers))
    print("入谱（本人+父系后裔）：%d 人；因取消关注跳过 %d 人"
          % (len(need), len(skipped)))

    # ★ 2026-10-04 使用者：「公卿自动关注加一条规则，**如果该公卿被灭族了，
    #   则该族全员取消关注**」。判据见 `app/gongqing.fallen_clans`
    #   （家族仍在 Jia_Zu_Map 里、但类型不再是公室/宗室/卿室、且成员有人正被关注）。
    #   ⚠️ 放在 `--apply` 关口**之前**，演习就能看到它报了几家。
    fallen = GQ.fallen_clans(slot, need)
    if fallen:
        print("灭族/失爵家族 %d 家（将取消关注其成员）：" % len(fallen))
        for f in fallen:
            print("   %-4s %-8s %s%s 国=%s → %d 人"
                  % (f["type"] or "(无类型)", f["code"], f["xing"], f["shi"],
                     f["king_name"], len(f["followed"])))
    else:
        print("灭族/失爵家族：**0 家**（无需取消关注）")

    if not a.apply:
        print("\n这是**演习**。确认后加 --apply。")
        return

    rc, _a, _u = IM.import_codes(SRC, sorted(need), SAVE, by_code=by_code)
    if rc != 0:
        print("!! 入谱失败 rc=%d" % rc)
        return
    d = json.load(open(book_path, encoding="utf-8"))
    people = d["people"]
    names_need = {nm for nm, v in people.items()
                  if str((v or {}).get("code") or "") in need}
    # ★ 2026-10-04 与 GUI 同规（`main.focus_gongqing`）：**宗室填充人**不关注、不入谱标。
    #   诸侯国（新封建 + 开局既有）会被游戏塞 3-5 个**无父无母无配偶无子女**的孤立节点
    #   （用途只是避免绝嗣）。判据 = 在**谱内没有任何家族边**。
    #   ⚠️ 必须在 import 之后判（那时字段才统一成 father/mother/spouses）。
    #   本工具原先缺这条 ⇒ 会漏进新档新生的填充人（旧的靠 `unfocused` 挡）。
    _has_child = set()
    for _v in people.values():
        for _k in ("father", "mother"):
            _p = (_v or {}).get(_k)
            if _p:
                _has_child.add(_p)
    filler_skip = 0
    filler_king = 0
    lone_skip = 0
    enrolled_add = 0

    def _filler(v, c):
        """宗室填充人（谱内无任何家族边）—— 旧口径。"""
        return (not v.get("father") and not v.get("mother")
                and not v.get("spouses") and c not in _has_child)

    def _lone_nonhist(v):
        """★ 2026-10-07 使用者（续七十一）：「**非史实、孤立的公卿男女，除非当了
        诸侯或者我点了关注，否则要从「公卿自动关注」这条规则里去掉**」⇒ 判据 =
        **非史实 + 无父无母**。⚠️ 有配偶 / 有子女都**不算**豁免 —— 实测那批媵妾
        全都有配偶，正是靠旧判据（`_filler`，要求「四无」）漏进来的。"""
        if str(v.get("father") or "") or str(v.get("mother") or ""):
            return False
        return str(v.get("historical") or "否") != "是"

    def _king_exception(nm, v):
        """**君主例外**（使用者 2026-10-04 裁定，与 `main.focus_gongqing` 同规）：

        「宗室填充人**不入谱**；**除非他成了君主**，那么就挂靠他在该国**前任君主**
        旁边、算**同代人**的族人。」⇒ 他确是某国现任君主时**不跳过**，并写
        `associate_of=前任` / `associate_type="clan"`（族人）/ `generation=前任世代`。
        判据唯一实现：`app/gongqing.filler_exception`（前任 = `King_Str` 倒数第二条）。
        """
        exc = GQ.filler_exception(slot, nm, people)
        if not exc:
            return False
        v["associate_of"] = exc["prev"]
        v["associate_type"] = "clan"
        if exc.get("prev_gen") is not None:
            v["generation"] = exc["prev_gen"]
        return True

    for nm, v in people.items():
        c = str((v or {}).get("code") or "")
        if c not in need:
            continue
        if _filler(v, c) or _lone_nonhist(v):
            if not _king_exception(nm, v):
                if _lone_nonhist(v):
                    lone_skip += 1
                else:
                    filler_skip += 1
                continue
            filler_king += 1
        if not v.get("enrolled"):
            v["enrolled"] = True
            enrolled_add += 1
    focused = list(canvas.get("focused_people") or [])
    focus_add = 0
    for nm in names_need:
        c = str(people[nm].get("code") or "")
        _v = people[nm] or {}
        if _filler(_v, c) or _lone_nonhist(_v):
            if not _king_exception(nm, _v):
                continue                   # 宗室填充人 / 非史孤立者：不关注
        if c in roots and nm not in focused and nm not in unfocused:
            focused.append(nm)
            focus_add += 1
    # 灭族家族 → 全员取消关注（同时记 `unfocused`：自动关注永不回加）
    gone = []
    for f in fallen:
        for c in f["followed"]:
            nm = code2name.get(str(c))
            if not nm or nm not in focused:
                continue
            focused.remove(nm)
            unfocused.add(nm)
            gone.append(nm)
    if fallen:
        print("灭族/失爵家族 %d 家 → 取消关注 %d 人：%s"
              % (len(fallen), len(gone), "、".join(gone[:12])))
    else:
        print("灭族/失爵家族：0 家（本次无需取消关注）")

    storage.write_save(SAVE, people, d.get("cutoff_person"),
                       canvas={"focused_people": focused,
                               "unfocused": list(unfocused),
                               "hidden_non_historical":
                                   [k for k, v in
                                    (canvas.get("hidden_non_historical") or {}).items()
                                    if v]})
    print("入谱标新增 %d · 关注新增 %d（总关注 %d）· 滤除宗室填充人 %d"
          "· 滤除非史孤立者 %d · 国君补关注 %d · 君主例外放行 %d"
          % (enrolled_add, focus_add, len(focused), filler_skip, lone_skip,
             ruler_add, filler_king))
    if gone:
        print("　（灭族/失爵取消关注 %d 人：%s）" % (len(gone), "、".join(gone[:10])))


if __name__ == "__main__":
    main()
