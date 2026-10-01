# -*- coding: utf-8 -*-
"""开发用：起史馆窗口 → 切到指定页签 → 截图。

    python tools/shot2.py <页签> <输出png> [槽目录] [谱牒名] [宽] [高]

页签 = person / tree / timeline / world / table

为什么单独写一个而不是改 tools/shot.py：那个是 v0.4 阅览器时代的，
`app.gui` 在 M1 已拆成 `app/views/*`，留着做历史参照。
本脚本用**新的装配层**（main.ShiguanApp）+ 直接切页，不依赖左导航点选。
"""
import os
import sys
import faulthandler
import tkinter as tk

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ★ 抓图必须有真窗口；不能走 headless 开关（那会跳掉主题弹窗逻辑）
os.environ["SHIGUAN_HEADLESS"] = "0"

# 挂死时把栈 dump 到文件，避免"静默挂住"（本项目的经典坑）
_DUMP = os.path.join(HERE, "_shot2_stacks.txt")
_dumpf = open(_DUMP, "w")
faulthandler.dump_traceback_later(60, exit=True, file=_dumpf)

view = sys.argv[1] if len(sys.argv) > 1 else "timeline"
out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "_shot2.png")
slot = sys.argv[3] if len(sys.argv) > 3 else ""
save = sys.argv[4] if len(sys.argv) > 4 else ""
W = int(sys.argv[5]) if len(sys.argv) > 5 else 0
H = int(sys.argv[6]) if len(sys.argv) > 6 else 0

from main import ShiguanApp                                  # noqa: E402
from app import wincap                                       # noqa: E402
from app.config import update_config                         # noqa: E402

root = tk.Tk()
root.geometry("%dx%d+0+0" % (W or 1500, H or 940))
app = ShiguanApp(root)
try:
    root.attributes("-topmost", True)
    root.lift()
except Exception:
    pass

# ★ 谱牒 / 槽的切换**不在这里做** —— 首启动的模态主题框还没弹出来，
#   此时切页/换档会和后面的 `_stage2_close_then_switch` 打架（前者被覆盖）。
#   统一放到 `_stage2` 里，弹窗消化掉之后一次做干净。

# ★ 截图工具**不许改用户配置**：`switch_view` / `switch_save` / `open_record`
#   内部都会 `update_config(...)`，跑一次截图就把使用者的默认页签和当前档改掉
#   （实测：config.view 被刷成 table）。这里记下原值，`_finish` 时还原。
_CFG_BAK = {}
try:
    from app.config import load_config as _lc
    _CFG_BAK = dict(_lc())
except Exception:
    pass


def _restore_cfg():
    try:
        from app import config as _cfgmod
        # ★ 2026-09-26：补 `family_mode` —— 截「时间轴」会把家谱页切到 time 模式，
        #   不还原就改了使用者的默认模式（与 view / current_save 同一条铁律）。
        keep = ("view", "current_record", "current_save", "family_mode")
        kw = {k: _CFG_BAK[k] for k in keep if k in _CFG_BAK}
        if kw:
            _cfgmod.update_config(**kw)
    except Exception:
        pass


# 输出路径统一成绝对路径（子进程 cwd 可能不同）
if not os.path.isabs(out):
    out = os.path.join(ROOT, out)
os.makedirs(os.path.dirname(out), exist_ok=True)

_DONE = [False]
# ★ 闸门：`_do_shot` 只认闸门放行的那一次。
#   踩过的坑：`for … root.update()` 会推进真实时间并执行**已到期的定时器**，
#   `after(2800, _finish)` 之类可能被重入触发，把 _DONE 先置 True，
#   于是真正的截图那次直接 return，PNG 根本没落地。用闸门而不用 _DONE 自守：
#   只有 `_stage2` 末尾显式 `_ARM[0] = True; _do_shot()` 才算数。
_ARM = [False]
# 兜底定时器 id（正常路径会在 _finish 里 cancel）
_FALLBACK = [None]


def _do_shot():
    if not _ARM[0] or _DONE[0]:
        return
    _DONE[0] = True
    # 截图前把待处理的绘制全部落盘，避免抓到「画了一半」的中间态
    try:
        root.update_idletasks()
    except Exception:
        pass
    print("SHOT_VIEW_AT_CAPTURE %s" % app.view_key, flush=True)
    try:
        w, h = wincap.capture_widget_to_png(root, out)
        print("SHOT_OK %s %dx%d" % (out, w, h), flush=True)
    except Exception as e:
        print("SHOT_ERR", repr(e), flush=True)
    _finish()


def _finish():
    """收尾：还原配置 → 取消栈定时器 → 关窗 → 直接 `os._exit(0)`。

    ★ 不能用 `sys.exit` —— tkinter 清理期可能钩住进程，截图脚本会变成僵尸。
    """
    faulthandler.cancel_dump_traceback_later()
    _restore_cfg()
    try:
        if _FALLBACK[0]:
            root.after_cancel(_FALLBACK[0])
    except Exception:
        pass
    try:
        root.destroy()
    except Exception:
        pass
    try:
        _dumpf.close()
    except Exception:
        pass
    os._exit(0)


# ---------------------------------------------------------------------------
# ★ 关键：ShiguanApp 首启动会 `after(200, open_theme_picker)` 弹**模态**对话框，
#   而模态框内部是 `wait_window()` —— 只要没有人去关它，`root.update()` 就会
#   永久卡死（本项目最经典的坑，见 app/dialogs/forms.py::headless）。
#   所以截图必须先跑一轮事件循环把弹窗消化掉（自动关闭），再切页截图。
# ---------------------------------------------------------------------------
_THEME_DLG = [None]


def _close_modal():
    """把最上层的模态 Toplevel 关掉（等价于用户点确认）。"""
    try:
        forms_mod = sys.modules.get("app.dialogs.forms")
        if forms_mod is not None and hasattr(forms_mod, "headless"):
            # 借 headless 开关让 finish() 直接 destroy 而不 wait_window
            os.environ["SHIGUAN_HEADLESS"] = "1"
    except Exception:
        pass
    for wdg in root.winfo_children():
        if isinstance(wdg, tk.Toplevel):
            try:
                wdg.destroy()
            except Exception:
                pass


def _stage1_pump():
    """第一轮：让 after(200) 的主题弹窗先弹出来。"""
    try:
        root.update()
        for wdg in root.winfo_children():
            if isinstance(wdg, tk.Toplevel):
                _THEME_DLG[0] = wdg
        print("STAGE1_OK dlg=%s" % (_THEME_DLG[0] is not None), flush=True)
    except Exception as e:
        import traceback
        print("STAGE1_ERR %r" % (e,), flush=True)
        print(traceback.format_exc(), flush=True)


def _stage2_close_then_switch():
    # ★ 整个 stage2 包一层：Tk 的 after 回调里抛异常**不会打印任何东西**，
    #   只会静默跳过后续语句（本项目最阴的坑之一）。必须自己兜住并打出来。
    try:
        _stage2_body()
    except Exception as e:
        import traceback
        print("STAGE2_ERR %r" % (e,), flush=True)
        print(traceback.format_exc(), flush=True)
        _finish()


def _stage2_body():
    print("STAGE2_ENTER view_key=%s target=%s" % (app.view_key, view), flush=True)
    _close_modal()
    root.update()
    # 指定谱牒 / 槽（不指定就用 config 里的）
    if save:
        app.switch_save(save)
    if slot:
        app.open_record(os.path.join(r"D:\DevCache\dzlgz", slot))
    root.update()
    print("STAGE2_AFTER_LOAD view_key=%s" % app.view_key, flush=True)
    # ★ `switch_view` 在「目标 = 当前页签」时是**空操作**（直接 return）。
    #   而 config 里存的 view 会随上次运行漂移 —— 实测踩过：
    #   config.view 恰好是 table 时，`shot2.py timeline` 与 `shot2.py table`
    #   会截出**两张一模一样的表页图**。所以这里先强制归零到一个不同的页，
    #   再切到目标页，保证真的重建了一次视图。
    # ★ 2026-09-26 修：`timeline` 是老页签名 —— 2026-09-23 起「时间轴」已并入
    #   「家谱」页（view=tree + family_mode=time）。原来这里在 switch_view **之后**
    #   兜底写 `update_config(view="timeline")`，那是个**非法 view**，重建后主区
    #   **一片空白**（实测截出来的时间轴图只有背景色，误判成"这功能没做"）。
    #   ⚠️ 用局部变量 `target`：直接给模块级 `view` 赋值会触发 UnboundLocalError
    #   （同函数前面 `if app.view_key == view` 就读不到它了）。
    target = view
    if target == "timeline":
        target = "tree"
        app.family_mode = "time"
        app.cfg = update_config(view="tree", family_mode="time")
    if app.view_key == target:
        other = "person" if target != "person" else "tree"
        print("STAGE2_ALREADY_THERE -> bounce via %s" % other, flush=True)
        app.switch_view(other)
        print("STAGE2_BOUNCED view_key=%s" % app.view_key, flush=True)
        root.update()
        print("STAGE2_BOUNCE_PUMPED", flush=True)
    app.switch_view(target)
    print("STAGE2_SWITCHED view_key=%s" % app.view_key, flush=True)
    root.update()
    print("STAGE2_PUMPED", flush=True)
    # 兜底：万一 switch_view 仍因某种原因没生效，直接改 cfg 重建
    if app.view_key != target:
        print("STAGE2_FORCE cfg view=%s" % target, flush=True)
        app.cfg = update_config(view=target)
        app._build_main_view()
        if getattr(app, "topbar", None) is not None:
            app.topbar.set_view(target)
    for _ in range(12):
        root.update()
        root.update_idletasks()
    print("SHOT_VIEW %s" % app.view_key, flush=True)
    # ★ 截图由**本函数末尾显式调用**，不用独立的 `after(900, _do_shot)`。
    #   踩过的坑：`for … root.update()` 会推进真实时间并执行已到期的定时器，
    #   而 `after(900, …)` 到期后**在 _stage2 中途**就被拉起来 → 截图先于切页完成，
    #   三张图哈希一模一样（实测 f3fcb5956a06 ×3）。顺序化调用才是可靠的。
    _ARM[0] = True
    _do_shot()
    # ★ `_do_shot` 里已经 `_finish()` 且 `os._exit(0)`，走不到这里；
    #   留着是为了万一将来改成不退出时仍能收尾。
    _finish()


root.after(320, _stage1_pump)
root.after(560, _stage2_close_then_switch)
# ★ 兜底收尾**不能**用一个短的绝对定时器。
#   踩过的坑：`root.update()` 会推进真实时间，`open_record`（读档+派生 8988 人，
#   实测 ~2 秒）加上多次 update 累计早已越过 2800ms，于是兜底定时器在
#   **切页途中**到期 → 提前 `os._exit`，PNG 根本没落地，
#   而且现场一点痕迹都没有（栈是空的，因为不是挂死）。
#   改法：时限放宽到 25 秒，且正常路径 `_do_shot` 里会 cancel 掉它。
_FALLBACK[0] = root.after(25000, _finish)

for _ in range(6):
    root.update()
    root.update_idletasks()

root.mainloop()
_finish()
