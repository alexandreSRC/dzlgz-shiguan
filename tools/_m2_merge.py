# -*- coding: utf-8 -*-
"""M2 续谱验收：增量合并（「自动续谱」闭环）的九条断言。

对着**真实存档**跑：Save_All_1（秦末起义）× 谱牒《秦末起义·史实》的副本。
产出 `_stats/_m2_merge.txt`。

断言（对应《自动续谱闭环实施计划》§四）：
  1 演习后 family.json 哈希不变（零写盘）
  2 真写后手写值逐字段相等
  3 新增者都带编号；谱内没有编号的人只能是「谱内独有」的旧人
  4 无悬空引用（父 / 母 / 配偶都指向在册的人）
  5 备份存在、可读、人数 = 旧人数
  6 source.slot 未变，last_merge 已更新
  7 连做两次，第二次「新增 0」
  8 封国/爵位/世系**只写新人，老人一律不动**（a 老人沿用旧值 / b 旧错判样本原样留住
    / c 新人照写抽取值）—— ★ 2026-09-21 使用者裁决，与旧版「以抽取为准」相反
  9 GUI 层：run_extend 写回后 undo 一步回到续谱前
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJ, "tools"))
sys.path.insert(0, PROJ)
os.chdir(PROJ)

# ★ 2026-09-21：基础谱牒不再写死《秦末起义·史实》—— 使用者会删档（实测把那部删了）。
#   改成「自动挑一部**带 source、且来源槽目录真的存在**的谱牒」来当底座。
def _pick_base():
    from app import storage as _S
    for _n in _S.list_saves():
        _src = _S.load_source(_n) or {}
        _p = str(_src.get("slot_path") or "")
        if _p and os.path.isdir(_p):
            return _n, _p
    return "", ""


BASE, SLOT = _pick_base()
TMP = "_m2_续谱验收"
PRUNE = ["--prune", "hist", "--real-state-only"]

log = []
fails = []


def w(s):
    log.append(str(s))
    print(s)


def step(name, ok, detail=""):
    w(f"[{'OK' if ok else 'FAIL'}] {name}" + (f"　{detail}" if detail else ""))
    if not ok:
        fails.append(name)
    return ok


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()[:16]


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def run_merge(apply=False):
    cmd = [sys.executable, os.path.join(PROJ, "tools", "import_from_game.py"),
           "--src", SLOT, "--save", TMP] + PRUNE + ["--merge"]
    if apply:
        cmd.append("--apply")
    p = subprocess.run(cmd, capture_output=True, cwd=PROJ,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    return p.returncode, (p.stdout or b"").decode("utf-8", "replace")


def run_build():
    """先做一次**整档导入**，自己造一份底座谱牒。

    ★ 2026-09-21：不再复制使用者现有的谱牒当底座 —— 他会删档（实测把
      《秦末起义·史实》删了，测试直接 FileNotFoundError），
      而且不同底座的人数/编码情况不同，断言会跟着飘。
      现在由测试**自己抽一份**，与使用者的数据完全解耦。
    """
    cmd = [sys.executable, os.path.join(PROJ, "tools", "import_from_game.py"),
           "--src", SLOT, "--save", TMP] + PRUNE
    p = subprocess.run(cmd, capture_output=True, cwd=PROJ,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    return p.returncode, (p.stdout or b"").decode("utf-8", "replace")


def num(out, label):
    m = re.search(rf"{label}\s+(\d+)", out)
    return int(m.group(1)) if m else None


def main():
    import import_from_game as IM

    w("=" * 62)
    w("=== M2 续谱验收（增量合并 · 自动续谱闭环）===")
    w("=" * 62)

    if not os.path.isdir(SLOT):
        w(f"× 找不到实录槽 {SLOT}，跳过。")
        return 1
    w(f"来源槽：{os.path.basename(SLOT)}")

    # ---------------- 准备：自己抽一份底座（不碰使用者的谱牒）----------------
    dst_dir = os.path.join(PROJ, "saves", TMP)
    path = os.path.join(dst_dir, "family.json")
    if os.path.exists(dst_dir):
        shutil.rmtree(dst_dir)
    w(f"\n先整档导入，自建底座谱牒《{TMP}》…")
    rc0, out0 = run_build()
    if rc0 != 0 or not os.path.isfile(path):
        w(f"× 底座建档失败（rc={rc0}）：\n{out0[-1500:]}")
        return 1

    data = load(path)
    people = data["people"]
    w(f"底座谱牒档：{TMP}（{len(people)} 人）")

    # 手工留痕：挑「没有重名序数」的人（这类人在新抽里必然唯一，认得出来）
    uniq = [n for n in people if IM.base_of(n) == n]
    hand = {}
    for n in uniq[:5]:
        hand[n] = {"bio": "【手工】我写的小传", "note": "【手工】尊号",
                   "rank": 7, "root_sort": 3, "color": "#123456"}
        people[n].update(hand[n])
    demoted = uniq[5:7]
    for n in demoted:
        people[n]["historical"] = "否"
    dad = ""
    dad_i = 7
    for i, n in enumerate(uniq[7:], start=7):
        if people[n].get("father") in people:
            people[n]["father"] = uniq[0]
            dad, dad_i = n, i
            break
    # 删 3 人：新抽里还在 → 续谱时应当作为「新增」回来（这是「自动续谱」的正题）
    gone = uniq[dad_i + 1:dad_i + 4]
    for n in gone:
        people.pop(n, None)
    # 加 1 个存档里没有的人（纯手写）→ 续谱时必须原样保留
    hand_made = "手写人物·守谱"
    people[hand_made] = {
        "father": "", "mother": "", "color": "", "bg_color": "",
        "note": "【手工新增】", "gender": "男", "generation": 1,
        "historical": "否", "divine": "否", "birth": "-100", "death": "",
        "rank": 0, "spouses": [], "associate_of": "", "associate_type": "",
        "associate_rank": 0, "state_group": "", "state_name": "",
        "fief_title": "", "fief_gen": 0, "root_sort": 0,
        "bio": "【手工新增】这一条是我自己写进去的，续谱不许删。",
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    w(f"手工留痕：{len(hand)} 人写 小传/尊号/排行7/祖序3/配色 · "
      f"{len(demoted)} 人改标「非史实」 · 1 人（{dad}）改父亲为「{uniq[0]}」")
    w(f"删 {len(gone)} 人（{('、'.join(gone))}）→ 应作为「新增」回来 · "
      f"加 1 个纯手写人物「{hand_made}」→ 必须保留")

    old_people = load(path)["people"]
    n_old = len(old_people)
    src_before = dict(load(path).get("source") or {})
    h_before = digest(path)

    # ---------------- 1. 演习零写盘 ----------------
    w("\n--- ① 演习 ---")
    rc, out = run_merge(apply=False)
    w("\n".join(out.strip().splitlines()[-22:]))
    step("① 演习退出码为 0", rc == 0, f"rc={rc}")
    step("① 演习后 family.json 哈希不变（零写盘）",
         digest(path) == h_before, f"{h_before} → {digest(path)}")
    baks = [f for f in os.listdir(dst_dir) if f.startswith("family.json.bak_")]
    step("① 演习连备份都不建", not baks, f"发现 {len(baks)} 个备份")

    dry_add = num(out, "新增")
    dry_upd = num(out, "更新")
    dry_kept = num(out, "保留")
    dry_pend = num(out, "待人工确认")
    w(f"      演习读数：新增 {dry_add} · 更新 {dry_upd} · 保留 {dry_kept} · "
      f"待确认 {dry_pend}")

    # ---------------- 2~6. 真写 ----------------
    w("\n--- ② 备份并写回 ---")
    rc, out = run_merge(apply=True)
    w("\n".join(out.strip().splitlines()[-24:]))
    step("② 写回退出码为 0", rc == 0, f"rc={rc}")

    new_people = load(path)["people"]
    added = num(out, "新增")
    kept = num(out, "保留")
    pend = num(out, "待人工确认")

    # 2. 手写值逐字段相等
    bad = []
    for n, want in hand.items():
        if n not in new_people:
            bad.append(f"{n} 丢了")
            continue
        for k, v in want.items():
            if new_people[n].get(k) != v:
                bad.append(f"{n}.{k}: {new_people[n].get(k)!r} ≠ {v!r}")
    step("② 手写值逐字段相等（小传/尊号/排行/祖序/配色）",
         not bad, "；".join(bad[:4]) or f"{len(hand)} 人 × 5 字段全对")

    bad = [n for n in demoted if new_people.get(n, {}).get("historical") != "是"]
    step("② 只升不降：改标「非史实」的人被升回「是」", not bad, str(bad))

    step("② 血缘冻结：手改的父亲保住了",
         dad in new_people and new_people[dad].get("father") == uniq[0],
         f"{dad}.father = {new_people.get(dad, {}).get('father')!r}")

    # 3. 新增者都带编号
    nocode = [n for n, v in new_people.items() if not v.get("code")]
    step("③ 新增 > 0（删掉的人被抽回来了）", (added or 0) > 0,
         f"新增 {added} · 预期 ≥ {len(gone)}")
    step("③ 删掉的人确实回来了", all(n in new_people for n in gone),
         "；".join(n for n in gone if n not in new_people) or "、".join(gone))
    step("③ 纯手写人物没被删", hand_made in new_people,
         f"{hand_made} 在册" if hand_made in new_people else "丢了")
    step("③ 无编号的人只等于「谱内独有」数",
         len(nocode) == (kept or 0),
         f"无编号 {len(nocode)}（{nocode[:3]}）· 谱内独有 {kept}")
    step("③ 人数守恒：旧 + 新增 = 新",
         len(new_people) == n_old + (added or 0),
         f"{n_old} + {added} = {len(new_people)}")

    # 4. 无悬空
    dang = []
    for n, v in new_people.items():
        for k in ("father", "mother"):
            t = str(v.get(k) or "")
            if t and t not in new_people:
                dang.append(f"{n}.{k}→{t}")
        for s in (v.get("spouses") or []):
            if s not in new_people:
                dang.append(f"{n}.spouse→{s}")
    step("④ 无悬空引用（父/母/配偶都在册）", not dang,
         "；".join(dang[:4]) or "全部命中")

    # 5. 备份
    baks = sorted(f for f in os.listdir(dst_dir) if f.startswith("family.json.bak_"))
    ok_bak = False
    detail = f"发现 {len(baks)} 个"
    if baks:
        try:
            b = load(os.path.join(dst_dir, baks[-1]))
            ok_bak = len(b.get("people") or {}) == n_old
            detail = f"{baks[-1]} · {len(b.get('people') or {})} 人"
        except Exception as e:
            detail = f"读不出：{e}"
    step("⑤ 备份存在、可读、人数 = 旧人数", ok_bak, detail)

    # 6. source
    src_after = load(path).get("source") or {}
    step("⑥ source.slot 未变", src_after.get("slot") == src_before.get("slot"),
         f"{src_before.get('slot')} → {src_after.get('slot')}")
    step("⑥ last_merge 已更新", bool(src_after.get("last_merge")),
         str(src_after.get("last_merge")))

    # 8. 封国 / 爵位 / 世系：只写新人，老人一律不动
    #    ★ 2026-09-21 使用者裁决，本条**与旧版断言相反**：
    #      旧版要求「以抽取为准」把旧错判（嬴异人=帝 / 任敖=汉王…）自动修掉；
    #      使用者现在明确「每次续谱，只更新新人物，老人物我自己会调整」，
    #      所以这些旧值必须**原样留住**，一个字都不许被抽取结果覆盖。
    w("\n--- ③ 封国 / 爵位 / 世系：只写新人，老人一律不动 ---")
    # 8a 老人物：合并后与旧谱逐字段相等
    bad = []
    for n in old_people:
        if n not in new_people:
            continue
        for k in IM.FACT_KEEP:
            if k in old_people[n] and new_people[n].get(k) != old_people[n].get(k):
                bad.append(f"{n}.{k}: {new_people[n].get(k)!r}≠旧值"
                           f"{old_people[n].get(k)!r}")
                if len(bad) >= 5:
                    break
        if len(bad) >= 5:
            break
    step("⑧a 老人物的封国/爵位/世系沿用旧值（不被抽取覆盖）",
         not bad, "；".join(bad[:5]) or f"{len(old_people)} 位老人 × 5 字段全对")

    # 8b 具体的旧错判样本：必须原样留住（这正是使用者要的「我自己会调整」）
    #
    # ★ 2026-09-22：这七个字面值是**秦末起义档**（Save_All_1）的错判样本。
    #   底座改成「自动挑一部带 source 的谱牒」之后，挑中的不一定是那盘
    #   （实测落到 Save_All_4002《三十六国》），这批人虽在谱里、字段却是空的 ——
    #   拿秦末的字面值去比必然假红。所以：
    #     · 底座就是那盘（Save_All_1）→ 比字面值（原来的回归护栏）
    #     · 否则 → 比「与底座逐字相等」（＝不许被抽取覆盖，这才是本条的真语义）
    kept_checks = (("嬴异人", "fief_title", "帝"), ("嬴政", "fief_title", "帝"),
                   ("嬴胡亥", "fief_title", "帝"), ("任敖", "fief_title", "王"),
                   ("灌婴", "fief_title", "王"), ("蔺康", "state_name", "燕"),
                   ("严阙", "state_name", "秦"))
    _is_qinmo = os.path.basename(str(SLOT)) == "Save_All_1"
    bad2 = []
    n_kept_checked = 0
    for n, k, want in kept_checks:
        v = new_people.get(n)
        old = old_people.get(n)
        if v is None or old is None:
            continue            # ★ 换底座谱牒后这些人可能不在谱里 —— 跳过，不算失败
        n_kept_checked += 1
        if v.get(k, "") != old.get(k, ""):
            bad2.append(f"{n}.{k}={v.get(k, '')!r}≠底座值{old.get(k, '')!r}")
        elif _is_qinmo and v.get(k, "") != want:
            bad2.append(f"{n}.{k}={v.get(k, '')!r}≠{want!r}")
    step("⑧b 旧错判样本原样留住（改不改由使用者决定）",
         not bad2, "；".join(bad2[:5]) or
         (f"{n_kept_checked} 项字面值全留" if _is_qinmo
          else f"{n_kept_checked} 项与底座逐字相等"
               f"（底座是 {os.path.basename(str(SLOT))}，秦末的字面值样本不适用）"))

    # 8c 新人：必须写上抽取结果（首次读档要能读出来，例如「嬴胡亥 = 皇帝」）
    fresh_people, _st, _n2c, _gs = IM.build(
        SLOT, None, "hist", True, history=True, watch=[])
    fresh_by_code = {str(v.get("code")): v for v in fresh_people.values()
                     if v.get("code")}
    bad3 = []
    n_new_checked = 0
    for n in gone:                      # gone 是「被删掉、续谱时作为新增回来」的那批
        v = new_people.get(n)
        if v is None:
            bad3.append(f"{n} 没回来")
            continue
        fv = fresh_by_code.get(str(v.get("code") or ""))
        if fv is None:
            continue
        n_new_checked += 1
        for k in IM.FACT_KEEP:
            if v.get(k, "") != fv.get(k, ""):
                bad3.append(f"{n}.{k}={v.get(k, '')!r}≠抽取值{fv.get(k, '')!r}")
    step("⑧c 新人的封国/爵位/世系照写抽取值",
         not bad3 and n_new_checked > 0,
         "；".join(bad3[:5]) or f"抽查 {n_new_checked} 位新人全对")

    # ---------------- 7. 连做两次 ----------------
    w("\n--- ④ 再续一次（应「新增 0」）---")
    rc, out2 = run_merge(apply=True)
    add2 = num(out2, "新增")
    upd2 = num(out2, "更新")
    kept2 = num(out2, "保留")
    step("⑦ 第二次「新增 0」", add2 == 0, f"新增 {add2} · 更新 {upd2} · 保留 {kept2}")
    step("⑦ 第二次无待确认", num(out2, "待人工确认") == 0,
         f"待确认 {num(out2, '待人工确认')}")
    n_second = len(load(path)["people"])
    step("⑦ 人数不再增长", n_second == len(new_people),
         f"{len(new_people)} → {n_second}")

    # ---------------- 9. GUI：撤销栈 ----------------
    w("\n--- ⑤ GUI 层：写回后 Ctrl+Z 一步撤销 ---")
    os.environ["SHIGUAN_HEADLESS"] = "1"
    import tkinter as tk
    import tkinter.messagebox as mb
    for fn in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel"):
        setattr(mb, fn, lambda *a, **k: "ok")
    import main as M
    root = tk.Tk()
    root.withdraw()
    app = M.ShiguanApp(root)
    app.switch_save(TMP)
    n_before = len(app.people)
    ok, gout = app.run_extend(apply=True, prune="hist")
    n_after = len(app.people)
    step("⑨ run_extend 走通", ok, f"{n_before} → {n_after} 人")
    app.undo()
    n_undo = len(app.people)
    disk_after_undo = len(load(path)["people"])
    step("⑨ undo 一步回到续谱前", n_undo == n_before and disk_after_undo == n_before,
         f"内存 {n_undo} · 磁盘 {disk_after_undo} · 期望 {n_before}")

    # ---------------- 收尾 ----------------
    w("")
    w("=" * 62)
    if fails:
        w(f"未通过 {len(fails)} 项：")
        for f in fails:
            w("  · " + f)
    else:
        w("九条断言全部通过。")
    w("=" * 62)

    os.makedirs(os.path.join(PROJ, "_stats"), exist_ok=True)
    with open(os.path.join(PROJ, "_stats", "_m2_merge.txt"), "w",
              encoding="utf-8") as f:
        f.write("\n".join(log) + "\n")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
