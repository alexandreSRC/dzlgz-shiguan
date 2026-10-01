# -*- coding: utf-8 -*-
"""真起 GUI，确认窗口活着、五个页签都能切（不 mainloop 太久）。

★ 设 SHIGUAN_HEADLESS=1：首启动若无主题会弹模态框，
  没有 mainloop 时 `wait_window` 会**永久挂住**（踩过）。
  无头开关只影响对话框的阻塞行为，窗口本身照建照重绘 —— 该验的都还在。
"""
import os
import sys
import time
import traceback

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
os.chdir(PROJ)
os.environ["SHIGUAN_HEADLESS"] = "1"

LOG = os.path.join(PROJ, "_stats", "_m1_gui.txt")
log = []


def w(s):
    log.append(f"[{time.time() - T0:6.2f}s] {s}")


T0 = time.time()

import tkinter as tk

import tkinter.messagebox as mb
for fn in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel"):
    setattr(mb, fn, lambda *a, **k: "ok")

import main as M

# ★ 验收脚本不许改用户配置：`switch_view` 内部会 `update_config(view=...)`，
#   跑完使用者的默认页签就变成了最后一次切到的那页。
CFG_BAK = {}
try:
    from app.config import load_config as _lc0
    CFG_BAK = dict(_lc0())
except Exception:
    pass


def restore_cfg():
    try:
        from app import config as _cfgmod
        keep = ("view", "current_record", "current_save")
        kw = {k: CFG_BAK[k] for k in keep if k in CFG_BAK}
        if kw:
            _cfgmod.update_config(**kw)
    except Exception:
        pass


ok = False
try:
    root = tk.Tk()
    app = M.ShiguanApp(root)
    w(f"窗口已建：{root.title()}  {root.geometry()}")
    root.update()
    w(f"winfo_exists={root.winfo_exists()}  已映射={bool(root.winfo_ismapped())}")
    w(f"尺寸 {root.winfo_width()}x{root.winfo_height()}")

    # 逐页签切一遍（带 update，模拟真实重绘）
    for key in M.VIEW_KEYS:
        app.switch_view(key)
        root.update()
        w(f"  页签 {key:<9} ok  view_key={app.view_key}  "
          f"状态栏「{app.statusbar.items['counts'].cget('text')}」")

    # 三主题
    for tkey in ("paper", "tencent", "ink"):
        app.apply_theme(tkey, save=False)
        root.update()
        w(f"  主题 {tkey:<8} ok  {app.theme.name}")

    # 关窗流程（会走 save_data，不该炸）
    app.save_data()
    w("save_data ok")
    root.destroy()
    w("destroy ok")
    ok = True
except Exception:
    w("异常：")
    w(traceback.format_exc())

w("结论：" + ("GUI 全流程正常 ✓" if ok else "有异常 ✗"))
restore_cfg()
with open(LOG, "w", encoding="utf-8") as f:
    f.write("\n".join(log))
print("gui probe done", ok)
