# -*- coding: utf-8 -*-
"""M1 验收：五页签全可进 + 三主题全过。

真起 Tk 窗口（不 mainloop），逐个页签 build + apply_theme，记录异常。
自写报告，不走 PowerShell 管道（编码坑）。

★ 必须设 SHIGUAN_HEADLESS=1（见下方 os.environ），否则首启动会弹出
  主题选择模态框（`wait_window`），在没有 mainloop 的进程里**永久挂死**。
"""
import os
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
os.chdir(PROJ)

# 必须在 import 任何 app 模块之前设好 —— 无头开关是 import 时读的环境变量
os.environ["SHIGUAN_HEADLESS"] = "1"

import traceback

log = []


def w(s):
    log.append(str(s))


# ★ 验收脚本**不许改用户配置**：本脚本为了验「五页签全可进」会反复
#   `app.switch_view(...)`（内部 `update_config(view=...)`），还会显式
#   `update_config(view="table")` 做冷启动回归 —— 跑完把默认页签、当前档
#   留在验收用的值上，使用者下次启动就会莫名其妙停在别的页。
#   这里开头存一份、收尾还原（与 tools/shot2.py 同一套路）。
_CFG_BAK = {}
try:
    from app.config import load_config as _lc0
    _CFG_BAK = dict(_lc0())
except Exception:
    pass
_KEEP_KEYS = ("view", "current_record", "current_save")


def _restore_cfg():
    try:
        from app import config as _cfgmod
        kw = {k: _CFG_BAK[k] for k in _KEEP_KEYS if k in _CFG_BAK}
        if kw:
            _cfgmod.update_config(**kw)
    except Exception:
        pass


import tkinter as tk  # noqa: E402

# 双保险：messagebox / simpledialog 也一并静音
import tkinter.messagebox as _mb  # noqa: E402


def _silent(*a, **k):
    return "ok"


for _fn in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel"):
    setattr(_mb, _fn, _silent)

import tkinter.simpledialog as _sd  # noqa: E402
_sd.askstring = _silent
_sd.askinteger = _silent

from app.contract import VIEWS, VIEW_KEYS  # noqa: E402
from app.theme import THEMES  # noqa: E402

w("=== M1 验收：四页签 × 三主题 ===")
w(f"无头模式：SHIGUAN_HEADLESS={os.environ.get('SHIGUAN_HEADLESS')}")
w(f"页签契约：{VIEW_KEYS}")
w("")

root = tk.Tk()
root.withdraw()
w(f"Tk 版本：{tk.TkVersion}")

try:
    import main as M
    app = M.ShiguanApp(root)
    w("[OK] ShiguanApp 装配完成")
    w(f"     实录槽 {app.record_slot.name if app.record_slot else '(无)'}"
      f" · 剧本 {app.record_era} · 实录 {len(app.record_people)} 人")
    w(f"     谱牒档 {app.current_save or '(无)'} · 谱牒 {len(app.people)} 人")
except Exception:
    w("[FAIL] ShiguanApp 装配失败：")
    w(traceback.format_exc())
    root.destroy()
    with open(os.path.join(PROJ, "_stats", "_m1_accept.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(log))
    raise SystemExit(1)

w("")

# ---- 逐页签 ----
ok_views = []
for key, label, icon, layer in VIEWS:
    try:
        app.switch_view(key)
        root.update_idletasks()
        entered = (app.view_key == key)
        # 视图对象确实建起来了
        # ★ 2026-09-23 家谱页双模式（四十批合并）：gen→tree 实例 / time→timeline
        #   实例，二者建起一个即算数
        attr = {"person": "person_view", "world": "world_view",
                "tree": ("tree", "timeline"), "table": "table"}[key]
        names = attr if isinstance(attr, tuple) else (attr,)
        built = any(getattr(app, a, None) is not None for a in names)
        good = entered and built
        ok_views.append(good)
        w(f"[{'OK ' if good else 'FAIL'}] 页签 {key:<8} {label:<4} 层={layer:<6} "
          f"view_key={app.view_key} 视图已建={built}")
    except Exception:
        ok_views.append(False)
        w(f"[FAIL] 页签 {key} 异常：")
        w(traceback.format_exc())

w("")

# ---- 逐主题 ----
ok_themes = []
for tkey in THEMES:
    try:
        app.apply_theme(tkey, save=False)
        root.update_idletasks()
        good = (app.theme.key == tkey)
        ok_themes.append(good)
        # 主题切换后当前页签还能用
        probe = "person" if app.view_key == "person" else app.view_key
        app.switch_view("person")
        root.update_idletasks()
        app.switch_view(probe)
        root.update_idletasks()
        w(f"[{'OK ' if good else 'FAIL'}] 主题 {tkey:<8} {app.theme.name:<8} "
          f"切页往返正常={app.view_key == probe}")
    except Exception:
        ok_themes.append(False)
        w(f"[FAIL] 主题 {tkey} 异常：")
        w(traceback.format_exc())

w("")

# ---- 顶栏：一个「存档」胶囊 + 续谱 + 设置（2026-09-21 改版）----
# 原来「实录▾ 谱牒▾ 主题▾ ⇅同步」四个胶囊并排 —— 甲方裁定：谱牒是目的、
# 实录是来源，本来就是一件事的两头，合成一个「存档」；同步并进「续谱」；
# 主题菜单多余（默认宣纸，设置里能换）。
ok_ui = []
try:
    tb = app.topbar
    checks = {
        "存档胶囊": hasattr(tb, "pill_archive"),
        "续谱按钮": hasattr(tb, "pill_extend"),
        "设置胶囊": hasattr(tb, "pill_settings"),
        "已删实录胶囊": not hasattr(tb, "pill_record"),
        "已删谱牒胶囊": not hasattr(tb, "pill_book"),
        "已删主题胶囊": not hasattr(tb, "pill_theme"),
        "已删同步按钮": not hasattr(tb, "pill_sync"),
        "四页签分段": len(tb.segmented.buttons) == 4,
    }
    for k, v in checks.items():
        ok_ui.append(v)
        w(f"[{'OK ' if v else 'FAIL'}] 顶栏 {k}")
    _at = tb.pill_archive.value_widget.cget("text")
    _has_both = ("→" in _at) and bool(app.current_save)
    ok_ui.append(_has_both)
    w(f"[{'OK ' if _has_both else 'FAIL'}] 存档胶囊显示「谱牒 → 实录」：{_at}")
except Exception:
    w("[FAIL] 顶栏检查异常：")
    w(traceback.format_exc())

# ---- 状态栏双层计数 ----
try:
    lab = app.statusbar.items.get("counts")
    txt = lab.cget("text") if lab else ""
    good = "实录" in txt and "谱牒" in txt
    ok_ui.append(good)
    w(f"[{'OK ' if good else 'FAIL'}] 状态栏双层计数：{txt}")
except Exception:
    w("[FAIL] 状态栏检查异常：")
    w(traceback.format_exc())

w("")
allok = all(ok_views) and all(ok_themes) and all(ok_ui)
w(f"页签 {sum(ok_views)}/{len(ok_views)} · 主题 {sum(ok_themes)}/{len(ok_themes)}"
  f" · 外壳 {sum(ok_ui)}/{len(ok_ui)}")
w("")

# ---- 冷启动回归：默认页签不是「人物」时，实录层也要自动载入 ----
w("=== 回归：默认页签=表格 时冷启动 ===")
try:
    import importlib
    from app import config as cfgmod
    cfgmod.update_config(view="table")
    importlib.reload(M)
    app2 = M.ShiguanApp(root)
    slot_name = app2.record_slot.name if app2.record_slot else "(无)"
    n_rec = len(app2.record_people)
    good = app2.view_key == "table" and n_rec > 0
    w(f"[{'OK ' if good else 'FAIL'}] 默认页签 {app2.view_key} · 实录槽 {slot_name}"
      f" · 实录 {n_rec} 人 · 谱牒 {len(app2.people)} 人")
    cnt = app2.statusbar.items["counts"].cget("text")
    w(f"[{'OK ' if '9106' in cnt or '实录 0' not in cnt else 'FAIL'}] 状态栏计数：{cnt}")
    allok = allok and good
    app2.root.destroy()
except Exception:
    w("[FAIL] 冷启动回归异常：")
    w(traceback.format_exc())
    allok = False

w("")
w("结论：" + ("全部通过 ✓" if allok else "有失败项 ✗"))

try:
    root.destroy()
except Exception:
    pass

# ★ 还原使用者配置（见文件开头的说明）
_restore_cfg()

with open(os.path.join(PROJ, "_stats", "_m1_accept.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(log))
print("accept done", allok)
