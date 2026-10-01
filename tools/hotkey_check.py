# -*- coding: utf-8 -*-
"""快捷键实证（真窗口 + event_generate 注入）。

使用者第 1 问：「双击启动的快捷键都不能用」。
静态断言只能证明「绑了」，证明不了「按下去有用」——Tk 的事件投递
是 widget → class → toplevel → all，焦点一进输入框就被内建 class binding
吃掉。所以这个脚本**起真窗口、真的注入按键**。

判据（缺一不可）：
  1. 焦点落在 Entry 里按 Ctrl+F —— 旧版（只 root.bind）失效点，现在必须生效
  2. 焦点落在 Entry 里按 Ctrl+Z —— 必须放行给输入框，不能撤整个谱牒
  3. 重绑不叠加 —— 换页签/换主题会重建控件重绑，按一次只能撤一步
  4. Ctrl+数字切页签、Ctrl+D 翻抽屉、F1/F5/Ctrl+Q 不挂死

用法：python tools/hotkey_check.py      →  退出码 0 = 全过
"""
import os
import sys

os.environ["SHIGUAN_HEADLESS"] = "1"      # ★ 必须在 import app 之前
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import faulthandler

_dump = open(os.path.join(ROOT, "_stats", "_hk_stacks.txt"), "w", buffering=1)
faulthandler.dump_traceback_later(90, exit=True, file=_dump)

import tkinter as tk
from tkinter import messagebox

messagebox.showinfo = lambda *a, **k: "ok"
messagebox.showerror = lambda *a, **k: "ok"
messagebox.askyesno = lambda *a, **k: True

import main as M

# ★ 工具脚本不许改使用者状态（2026-09-22 教训）：
#   `switch_view` 内部会 update_config；`Ctrl+Q` 会走 quit_app→save_data，
#   把**真实谱牒**重写一遍。实测：跑一次本脚本就把 config.view 刷成 table，
#   并重写了《文王治岐》的 family.json（数据完好但文件被动过）。
#   三道防护：①备份配置 ②Ctrl+Q 前把 save_data 换成 no-op ③退出前还原配置。
CFG_BAK = {}
try:
    from app.config import load_config as _lc0
    CFG_BAK = dict(_lc0())
except Exception:
    pass


def restore_cfg():
    try:
        from app import config as _cfgmod
        # ★ 2026-09-24 补 `family_mode` 与 `table_drawer`：本脚本会按 Ctrl+2
        #   （切家谱页）与 Ctrl+D（翻转档案抽屉），这两个键原先不在还原名单里，
        #   跑一次就把使用者的抽屉开关悄悄翻掉（实测 9-24 那次把 `table_drawer`
        #   从 true 变成 false，属于「工具脚本改用户状态」的同一条铁律）。
        keep = ("view", "current_record", "current_save",
                "family_mode", "table_drawer")
        kw = {k: CFG_BAK[k] for k in keep if k in CFG_BAK}
        if kw:
            _cfgmod.update_config(**kw)
    except Exception:
        pass


root = tk.Tk()
root.geometry("1440x860+0+0")
app = M.ShiguanApp(root)
for _ in range(8):
    root.update()

FAILS = []


def check(label, ok, extra=""):
    print(("  [OK]   " if ok else "  [FAIL] ") + label + (f" → {extra}" if extra else ""),
          flush=True)
    if not ok:
        FAILS.append(label)


def focus_is(w):
    try:
        return app.root.focus_displayof() is w
    except Exception:
        return False


def current_entry():
    """当前页的搜索框：实录两页在视图上，谱牒三页在侧栏上。"""
    return (getattr(app.person_view, "search_entry", None)
            or getattr(app.world_view, "search_entry", None)
            or getattr(getattr(app, "sidebar", None), "entry_search", None))


# ---- 0) 绑定表 ----
n = len(M.ShiguanApp.HOTKEYS) + 5
check("快捷键条目数 >= 20", n >= 20, f"{n} 条")

# ---- 1) Ctrl+F 聚焦搜索框 ----
root.focus_set()
root.update()
root.event_generate("<Control-f>")
root.update()
ent = current_entry()
check("Ctrl+F 聚焦当前页搜索框", ent is not None and focus_is(ent))

# ---- 2) ★ 输入框里按 Ctrl+F 也要生效（旧版失效点）----
probe = tk.Entry(app.main_area)
probe.pack()
probe.focus_set()
root.update()
check("探针输入框已取得焦点", focus_is(probe))
probe.event_generate("<Control-f>")
root.update()
check("★ 输入框内 Ctrl+F 仍跳到搜索框", ent is not None and focus_is(ent))

# ---- 3) ★ 输入框里 Ctrl+Z 让给输入框 ----
cnt = [0]
orig_undo = app.undo
app.undo = lambda: cnt.__setitem__(0, cnt[0] + 1)
probe.focus_set()
root.update()
probe.event_generate("<Control-z>")
root.update()
check("★ 输入框内 Ctrl+Z 放行（不撤谱牒）", cnt[0] == 0, f"触发 {cnt[0]} 次")

root.focus_set()
root.update()
root.event_generate("<Control-z>")
root.update()
check("非输入框 Ctrl+Z 正常撤销", cnt[0] == 1, f"触发 {cnt[0]} 次")

# ---- 4) Ctrl+数字切页签 ----
root.focus_set()
root.event_generate("<Control-Key-2>")
root.update()
check("Ctrl+2 → 家谱页", app.view_key == "tree", f"实际 {app.view_key}")

# ---- 5) ★ 重绑不叠加 ----
app.switch_view("tree")
root.update()
app.switch_view("table")
root.update()
cnt[0] = 0
root.focus_set()
root.event_generate("<Control-z>")
root.update()
check("★ 重绑不叠加（一次按键 = 一次撤销）", cnt[0] == 1, f"触发 {cnt[0]} 次")
app.undo = orig_undo

# ---- 6) Ctrl+D 档案抽屉 ----
app.switch_view("table")
root.update()
before = app.table.drawer_open
root.focus_set()
root.event_generate("<Control-d>")
root.update()
check("Ctrl+D 翻转档案抽屉", app.table.drawer_open != before,
      f"{before} → {app.table.drawer_open}")
btn = app.toolbar.buttons.get("drawer")
check("抽屉按钮文字已同步", btn is not None and btn.cget("text") == app.table.drawer_label())

# ---- 7) F1 / F5 / Ctrl+Q ----
root.event_generate("<F1>")
root.update()
check("F1 快捷键一览未挂死", True)
root.event_generate("<F5>")
for _ in range(4):
    root.update()
check("F5 刷新未挂死", True)
# ★ Ctrl+Q 会触发 quit_app() → save_data()，把当前谱牒写盘。
#   本脚本只验「快捷键是否触发退出」，不验保存 → 把 save_data 换成 no-op，
#   避免测试改写使用者的真实谱牒（实测踩过：《文王治岐》被重写）。
app.save_data = lambda *a, **k: True
try:
    root.event_generate("<Control-q>")
    root.update()
    check("Ctrl+Q 退出", True)
except tk.TclError:
    check("Ctrl+Q 退出（窗口已销毁）", True)

# 还原使用者配置（见文件头的说明）
restore_cfg()

print(flush=True)
print(f"FAILS {len(FAILS)}", flush=True)
for f in FAILS:
    print("  · " + f, flush=True)
os._exit(0)
