# -*- coding: utf-8 -*-
"""M1 桥验收：同进程 查档桥（谱牒 → 实录）与入谱桥（实录 → 谱牒）。

不弹窗、不 mainloop —— 先 stub 掉全部模态框。
"""
import os
import sys
import traceback

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
os.chdir(PROJ)
os.environ["SHIGUAN_HEADLESS"] = "1"

log = []


def w(s):
    log.append(str(s))


import tkinter as tk  # noqa: E402

import tkinter.messagebox as mb  # noqa: E402
for fn in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel"):
    setattr(mb, fn, lambda *a, **k: "ok")
import tkinter.simpledialog as sd  # noqa: E402
sd.askstring = lambda *a, **k: None

import main as M  # noqa: E402

w("=== M1 桥验收 ===")
root = tk.Tk()
root.withdraw()
app = M.ShiguanApp(root)
w(f"启动：页签 {app.view_key} · 实录 {len(app.record_people)} 人 · 谱牒 {len(app.people)} 人")
w("")

# ---- 准备：录一个带 code 的临时谱牒档（现存档都没有 code，M0 只证过机制）----
w("--- 准备 · 建副本谱牒档并先入谱一人（这样谱内才有 code）---")
import shutil  # noqa: E402

import subprocess  # noqa: E402

from app import storage as ST  # noqa: E402

src_save = app.current_save
tmp_save = "_桥验收临时档"
src_dir = os.path.dirname(ST.save_path(src_save))
dst_dir = os.path.dirname(ST.save_path(tmp_save))
allok = True
prep_ok = False
try:
    if os.path.exists(dst_dir):
        shutil.rmtree(dst_dir)
    shutil.copytree(src_dir, dst_dir)
    w(f"已建副本谱牒档：{tmp_save}")

    # 挑一个实录里的史实人物（≤5 位编号），入谱
    #
    # ★ 必须只挑「抽取器四张表里确实有的人」：实录层读了槽里**全部 90 个表族**，
    #   而抽取器只认 族谱表 / 活人表 / 已故表 / 女性表。挑到别的表里的人
    #   （实测挑中过出生表 Save_Chu_Sheng_Data 的 4232 周昌），
    #   `--person` 会直接返回「编号 X 在四张表里都没有找到」→ rc=1。
    #   这是**测试脚本的挑人问题**，不是入谱桥的 bug。
    try:
        import import_from_game as IM
        four_tables = set(IM.load_tables(app.record_slot.root).keys())
    except Exception as _e:
        four_tables = None
        w(f"  （读四张表失败，跳过这层筛选：{_e}）")

    cand = None
    for code, prof in app.record_people.items():
        if not code.isdigit() or len(code) > 5:
            continue
        if four_tables is not None and code not in four_tables:
            continue
        nm2 = prof.name or ""
        if nm2:
            cand = (code, nm2)
            break
    if cand is None:
        w("[FAIL] 实录里找不到史实人物")
        allok = False
    else:
        code0, nm0 = cand
        w(f"先入谱：编号 {code0}　{nm0}")
        importer = os.path.join(PROJ, "tools", "import_from_game.py")
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        p = subprocess.run([sys.executable, importer, "--src", app.record_slot.root,
                            "--save", tmp_save, "--person", str(code0)],
                           capture_output=True, timeout=180, cwd=PROJ, env=env)
        out = (p.stdout or b"").decode("utf-8", "replace").strip()
        w(f"导入器 rc={p.returncode}")
        for line in out.splitlines()[-4:]:
            w(f"    {line}")
        prep_ok = (p.returncode == 0)
        allok = allok and prep_ok
except Exception:
    w("[FAIL] 准备阶段异常：")
    w(traceback.format_exc())
    allok = False

w("")

# ---- 桥一：查档（谱牒 → 实录） ----
w("--- 桥一 · 查档（谱牒 → 实录）---")
if not prep_ok:
    w("[SKIP] 准备失败，跳过查档桥")
else:
    app.switch_save(tmp_save)
    root.update_idletasks()
    picked = None
    for nm, info in app.people.items():
        if str(info.get("code", "")).strip():
            picked = (nm, str(info["code"]).strip())
            break
    if picked is None:
        w(f"[FAIL] 备份档里仍没有带 code 的人（谱牒 {len(app.people)} 人）")
        allok = False
    else:
        nm, code = picked
        w(f"取谱牒人物：{nm}（code={code}）")
        try:
            app.switch_view("person")
            root.update_idletasks()
            hit = app.person_view.locate_person(code=code, name=nm, info=app.people[nm])
            sel = app.person_view.table.selection()
            w(f"[{'OK ' if hit else 'FAIL'}] locate_person 命中={hit} · 表族={app.person_view.cur_family}")
            w(f"[{'OK ' if sel else 'FAIL'}] 表格已选中行={bool(sel)}")
            allok = allok and bool(hit) and bool(sel)
        except Exception:
            w("[FAIL] 查档桥异常：")
            w(traceback.format_exc())
            allok = False

w("")

# ---- 桥二：入谱（实录 → 谱牒）—— 再入一个不同的人，验证防重与增量 ----
w("--- 桥二 · 入谱（实录 → 谱牒）---")
if not prep_ok:
    w("[SKIP] 准备失败，跳过入谱桥")
else:
    try:
        before = len(app.people)
        codes_in = {str(v.get("code", "")) for v in app.people.values()}
        cand2 = None
        for code, prof in app.record_people.items():
            if not code.isdigit() or len(code) > 5 or code in codes_in:
                continue
            # ★ 与桥一同一条护栏：抽取器只认 族谱表/活人表/已故表/女性表，
            #   实录层却有 90 个表族。挑到只在别的表里的人（实测 4232 周昌
            #   只挂在出生表 Save_Chu_Sheng_Data）→ `--person` 返回 rc=1，
            #   测试会误报成「入谱桥坏了」。桥一早就加了这层筛选，桥二漏了。
            if four_tables is not None and code not in four_tables:
                continue
            nm2 = prof.name or ""
            if nm2:
                cand2 = (code, nm2)
                break
        if cand2 is None:
            w("[SKIP] 找不到第二个待入谱人物")
        else:
            code2, nm2 = cand2
            importer = os.path.join(PROJ, "tools", "import_from_game.py")
            env = dict(os.environ, PYTHONIOENCODING="utf-8")
            p = subprocess.run([sys.executable, importer, "--src", app.record_slot.root,
                                "--save", tmp_save, "--person", str(code2)],
                               capture_output=True, timeout=180, cwd=PROJ, env=env)
            app.load_data()
            root.update_idletasks()
            after = len(app.people)
            found = any(str(v.get("code", "")) == str(code2) for v in app.people.values())
            w(f"入谱 {code2}　{nm2}：rc={p.returncode} · 谱牒 {before} → {after} 人 · 已在谱内={found}")
            allok = allok and found and p.returncode == 0

            # 防重：同一个人再入一次，人数不该变
            p2 = subprocess.run([sys.executable, importer, "--src", app.record_slot.root,
                                 "--save", tmp_save, "--person", str(code2)],
                                capture_output=True, timeout=180, cwd=PROJ, env=env)
            app.load_data()
            root.update_idletasks()
            again = len(app.people)
            w(f"[{'OK ' if again == after else 'FAIL'}] 重复入谱不增：{after} → {again}")
            allok = allok and (again == after)
    except Exception:
        w("[FAIL] 入谱桥异常：")
        w(traceback.format_exc())
        allok = False

w("")

# ---- 清理 ----
try:
    app.switch_save(src_save)
    root.update_idletasks()
    shutil.rmtree(dst_dir, ignore_errors=True)
    w(f"已清理副本档，切回 {src_save}（{len(app.people)} 人）")
except Exception:
    w("[WARN] 清理副本档失败：")
    w(traceback.format_exc())

w("")
w("结论：" + ("全部通过 ✓" if allok else "有失败项 ✗"))
root.destroy()

with open(os.path.join(PROJ, "_stats", "_m1_bridge.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(log))
print("bridge done", allok)
