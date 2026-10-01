# -*- coding: utf-8 -*-
"""主题化消息框 —— 与 `tkinter.messagebox` 同 API 的替换品（UI 改进 B5）。

背景：全项目 84 处提示弹窗原来是 Windows 原生灰白样式，与宣纸/墨夜/腾讯蓝
三主题并排非常突兀。本模块提供同名同签名的五个函数：

    showinfo / showwarning / showerror / askyesno / askokcancel
    （签名与原生一致：`showinfo(title, message="", parent=None)`）

所以全部调用点**一行不改**，只要把各文件头部的

    from tkinter import messagebox
换成
    from app.widgets import msgbox as messagebox      # 包内用相对写法

即可整体换肤。

两条铁律（改这文件前先读）
--------------------------------------------------------
1. **无头模式（SHIGUAN_HEADLESS=1）一律委托回 `tkinter.messagebox`。**
   全部验收脚本的桩都打在 `tkinter.messagebox` 模块对象上
   （tools/_m3_ui.py:33、hotkey_check.py:30-34、_m1_accept/_m1_bridge/
   _m1_gui/_m2_merge/snapshot 同款），在调用时才取模块属性，
   所以委托回去桩照常生效 —— 验收行为与改造前完全一致。
   ⚠️ 本模块**不得 import `app.dialogs.forms`**：forms 换肤后也要 import
   本模块，会循环导入。无头判断直接现读环境变量（语义与 forms.headless()
   完全一致，同样是「每次调用都读、不能缓存」——shot2.py 要在中途切换它）。
2. **主题解析失败绝不崩**：从 parent 控件链向上找 `_shiguan_theme`
   （main._build_ui 会 `msgbox.bind(root, theme)` 注册兜底），
   再找不到就退宣纸。换弹窗不能比不换弹窗更脆。
"""
import os
import tkinter as tk

from .kit import FlatButton

_BOUND = {"root": None, "theme": None}

# kind → (默认标题, 主题里的强调色令牌名)
_KIND = {
    "info": ("提示", "accent"),
    "warning": ("警告", "warn"),
    "error": ("错误", "danger"),
    "question": ("确认", "accent"),
    "danger": ("危险操作", "danger"),
}


def bind(root, theme):
    """登记兜底的 root 与当前主题（main._build_ui 每次重建界面时调用）。"""
    _BOUND["root"] = root
    _BOUND["theme"] = theme


def _headless():
    # 现读环境变量，不缓存 —— 与 forms.headless() 同一条纪律
    return os.environ.get("SHIGUAN_HEADLESS") == "1"


def _native():
    """调用时才取 tkinter.messagebox 的属性 —— 验收脚本的桩才能生效。"""
    import tkinter.messagebox as mb
    return mb


def _theme_of(widget):
    w = widget
    while w is not None:
        t = getattr(w, "_shiguan_theme", None)
        if t is not None:
            return t
        w = getattr(w, "master", None)
    return _BOUND["theme"]


def _root_of(parent):
    if parent is not None:
        try:
            return parent.winfo_toplevel()
        except Exception:
            pass
    return _BOUND["root"]


def _scroll_text(parent, theme, text):
    """长文本容器：**限高 + 纵向滚动**（对话框不超出屏幕，按钮始终可见）。

    设计取舍：
    - 限高取「屏幕高 × 0.55」再压到 160~620px —— 保证按钮一定在屏内；
    - 滚动条是 ttk 自绘（与项目一致）；滚轮**只绑在自身控件**上，
      **不用 `bind_all`**（那会在对话框销毁后留下全局绑定 —— 本项目踩过
      这类"隐藏的全局副作用"）。
    """
    from tkinter import ttk

    try:
        screen_h = parent.winfo_toplevel().winfo_screenheight()
    except Exception:
        screen_h = 900
    height = max(160, min(620, int(screen_h * 0.55)))

    wrap = tk.Frame(parent, bg=theme.bg_card)
    wrap.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
    canvas = tk.Canvas(wrap, bg=theme.bg_card, highlightthickness=0, bd=0,
                       width=460, height=height)
    sb = ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=sb.set)
    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    sb.pack(side=tk.RIGHT, fill=tk.Y)

    inner = tk.Label(canvas, text=text, bg=theme.bg_card, fg=theme.text,
                     justify=tk.LEFT, anchor="nw", wraplength=430,
                     font=(theme.font_ui_fallback, theme.fs_body))
    canvas.create_window((0, 0), window=inner, anchor="nw")
    inner.bind("<Configure>",
               lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

    def _wheel(e):
        canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        return "break"

    canvas.bind("<MouseWheel>", _wheel)
    inner.bind("<MouseWheel>", _wheel)
    return canvas


def _show(kind, title, message, parent, buttons, main_kind="primary"):
    """窗口模式：画一个主题化的模态框。

    `buttons = [(文字, 返回值, 是否主按钮), ...]`，主按钮排最右（Windows 惯例）。
    `main_kind`：主按钮样式 —— 普通确认 primary（青绿实心），危险确认 danger
    （软红底红字，2026-09-23 成熟产品惯例：破坏性动作的主按钮一眼见红）。
    Enter = 主按钮，Esc = 末一个按钮（取消）。返回所点按钮的返回值。
    """
    root = _root_of(parent)
    if root is None:
        # 连 root 都没有（理论上只在无头测试出现）→ 退回原生，保底不崩
        return None
    theme = _theme_of(parent) or _theme_of(root)
    if theme is None:
        from ..theme import get_theme
        theme = get_theme("paper")

    dlg = tk.Toplevel(root)
    dlg.transient(parent if parent is not None else root)
    dlg.title(title or _KIND[kind][0])
    dlg.configure(bg=theme.bg_card)
    dlg.resizable(False, False)

    body = tk.Frame(dlg, bg=theme.bg_card)
    body.pack(fill=tk.BOTH, expand=True, padx=16, pady=(14, 12))

    head = tk.Frame(body, bg=theme.bg_card)
    head.pack(fill=tk.X)
    tk.Frame(head, bg=getattr(theme, _KIND[kind][1], theme.accent),
             width=4, height=16).pack(side=tk.LEFT, padx=(0, 8))
    tk.Label(head, text=title or _KIND[kind][0], bg=theme.bg_card, fg=theme.text,
             font=(theme.font_ui_fallback, theme.fs_hero, "bold")).pack(side=tk.LEFT)

    if message:
        txt = str(message)
        # ★ 2026-09-29：长说明（世界页「字段说明」讲宗庙/神系，实测 1276 字
        #   / 45 行；`wraplength=420` 折行后可达 80+ 行）会把对话框撑得比
        #   屏幕还高，底部的按钮点不到。
        #   ⇒ 超过阈值时改用**限高 + 可滚动**的容器；**短文本走原路径，
        #   行为逐像素不变**（84 处调用点依赖这个弹窗，不能整体改样）。
        if len(txt) > 900 or (txt.count("\n") + 1) > 26:
            _scroll_text(body, theme, txt)
        else:
            tk.Label(body, text=txt, bg=theme.bg_card, fg=theme.text,
                     justify=tk.LEFT, wraplength=420,
                     font=(theme.font_ui_fallback, theme.fs_body)).pack(
                         fill=tk.X, anchor="w", pady=(8, 0))

    btns = tk.Frame(body, bg=theme.bg_card)
    btns.pack(fill=tk.X, pady=(14, 0))
    result = {"v": None}

    def _done(v):
        result["v"] = v
        try:
            dlg.grab_release()
        except Exception:
            pass
        dlg.destroy()

    spec = list(buttons)
    for label, value, is_main in spec:
        FlatButton(btns, theme, text=label,
                   kind=main_kind if is_main else "default", padx=14,
                   command=lambda v=value: _done(v)).pack(side=tk.RIGHT, padx=(6, 0))

    main_value = spec[0][1] if spec else None
    esc_value = spec[-1][1] if len(spec) > 1 else main_value
    dlg.bind("<Return>", lambda e: (_done(main_value), "break")[1])
    dlg.bind("<Escape>", lambda e: (_done(esc_value), "break")[1])

    dlg.update_idletasks()
    try:
        px, py = (parent if parent is not None else root).winfo_rootx(), \
                 (parent if parent is not None else root).winfo_rooty()
        pw = (parent if parent is not None else root).winfo_width()
        ph = (parent if parent is not None else root).winfo_height()
        dlg.geometry(f"+{max(0, px + max(0, (pw - dlg.winfo_width()) // 2))}"
                     f"+{max(0, py + max(0, (ph - dlg.winfo_height()) // 3))}")
    except tk.TclError:
        pass
    dlg.deiconify()
    dlg.grab_set()
    dlg.wait_window()
    return result["v"]


# ============================================================ 五个同名入口

def showinfo(title, message="", parent=None):
    if _headless():
        return _native().showinfo(title, message, parent=parent)
    return _show("info", title, message, parent, (("确定", "ok", True),))


def showwarning(title, message="", parent=None):
    if _headless():
        return _native().showwarning(title, message, parent=parent)
    return _show("warning", title, message, parent, (("确定", "ok", True),))


def showerror(title, message="", parent=None):
    if _headless():
        return _native().showerror(title, message, parent=parent)
    return _show("error", title, message, parent, (("确定", "ok", True),))


def askyesno(title, message="", parent=None):
    if _headless():
        return bool(_native().askyesno(title, message, parent=parent))
    return bool(_show("question", title, message, parent,
                      (("是", True, True), ("否", False, False))))


def askokcancel(title, message="", parent=None):
    if _headless():
        return bool(_native().askokcancel(title, message, parent=parent))
    return bool(_show("question", title, message, parent,
                      (("确定", True, True), ("取消", False, False))))


def ask_confirm(title, message="", ok_text="确定", cancel_text="取消", parent=None):
    """普通确认框：动词主按钮（青绿 primary），如「新建」「续写」「移除」。

    危险动作用 `ask_danger`（红色主按钮），普通动作本函数。
    无头模式委托回原生 `askokcancel` —— 验收桩照常生效。
    """
    if _headless():
        return bool(_native().askokcancel(title, message, parent=parent))
    return bool(_show("question", title, message, parent,
                      ((ok_text, True, True), (cancel_text, False, False))))


def ask_danger(title, message="", ok_text="删除", cancel_text="取消", parent=None):
    """危险操作确认（2026-09-23 UI 重规划）：红色主按钮 + 动词文案。

    成熟产品惯例：破坏性动作的确认框，主按钮显示动作本身（「删除」「清空」）
    而不是含糊的「是/确定」，且样式见红 —— 手滑前多一道颜色防线。

    无头模式委托回原生 `askyesno` —— 项目验收脚本的桩最普遍打在 askyesno 上
    （hotkey_check / snapshot 都返回 True），换 API 后验收行为与旧版一致。
    """
    if _headless():
        return bool(_native().askyesno(title, message, parent=parent))
    return bool(_show("danger", title, message, parent,
                      ((ok_text, True, True), (cancel_text, False, False)),
                      main_kind="danger"))
