"""扁平化 UI 组件工具箱。

Tkinter 原生控件没有圆角/阴影，这里用 tk.Frame + highlightthickness 做 1px 描边、
tk.Label/tk.Button 配 relief=flat 做扁平按钮，尽量贴近效果图的观感。
所有颜色/尺寸都从 Theme 取，不写字面量。
"""
import os
import tkinter as tk
from tkinter import ttk

from ..theme import Theme
from .. import dpi as _dpi


# ---------------------------------------------------------------- Segoe MDL2 图标

MDL2_FONT = "Segoe MDL2 Assets"
_GLYPH_OK_CACHE = {}


def glyph_ok(ch):
    """「Segoe MDL2 Assets」里有没有这个字形（UI 改进 B8 的基建）。

    用 GDI 的 GetGlyphIndicesW + GGI_MARK_NONEXISTING 实测：缺字返回 0xFFFF，
    比「量宽度」可靠 —— 缺字形照样量得出宽度。非 Windows / 任何异常一律
    False，调用方退回纯文字：页签与按钮**绝不能出现方框**。结果按字缓存。
    """
    if ch in _GLYPH_OK_CACHE:
        return _GLYPH_OK_CACHE[ch]
    ok = False
    try:
        if os.name != "nt":
            raise OSError("非 Windows，没有 Segoe MDL2")
        import ctypes
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        hdc = user32.GetDC(0)
        hfont = gdi32.CreateFontW(-20, 0, 0, 0, 400, 0, 0, 0, 0, 0, 0, 0, 0,
                                  MDL2_FONT)
        old = gdi32.SelectObject(hdc, hfont)
        buf = (ctypes.c_ushort * 1)()
        gdi32.GetGlyphIndicesW(hdc, ctypes.c_wchar_p(ch), 1, buf, 0x0001)
        gdi32.SelectObject(hdc, old)
        gdi32.DeleteObject(hfont)
        user32.ReleaseDC(0, hdc)
        ok = bool(buf[0] != 0xFFFF)
    except Exception:
        ok = False
    _GLYPH_OK_CACHE[ch] = ok
    return ok


# ---------------------------------------------------------------- 文字宽度估算

def est_text_px(text, pt):
    """估算一段文字在 `pt` 号字下的像素宽（**不用 Tk 量**）。

    ★ 2026-09-21 加：两个表格要「按内容自动定列宽」（使用者要求
      「表格宽度是否合理，是否会掩盖到字」）。真用 `tkfont.measure` 量：
      实测 9000 次就要 0.7 秒 —— 人物页 8988 行 × 11 列 ≈ 99k 次 = 7 秒，
      卡得没法用。

      改用按字宽估算：中日韩全角字 ≈ 1.0 字宽，ASCII ≈ 0.55 字宽。
      估算值**故意略偏大**（多留 8% 余量），宁可列宽一点点宽，也不切字。
    """
    if not text:
        return 0
    full = sum(1 for ch in str(text) if ord(ch) > 0x2E80)
    half = len(str(text)) - full
    # ★ 2026-09-26 DPI：pt 号字的真实像素宽随系统缩放线性放大，估算跟着乘。
    return (full + half * 0.55) * pt * 1.08 * _dpi.SCALE


# ---------------------------------------------------------------- 统一高度基线

_LINESPACE_CACHE = {}


def _linespace(theme, size, family=None, bold=False):
    """某字号某字重的**行高**（像素）—— 把控件高度钉到统一基线用。

    ★ 2026-09-23 对齐精修：顶栏页签/胶囊、工具栏按钮全部统一 32 高 12 号字。
      高度不用 `winfo_reqheight()` 量（控件未渲染时不可靠、且要 update_idletasks
      强制刷新），改用字体行高**算**出来 —— 结果与渲染无关，可预期、可测试。
      按 (family, size, bold) 缓存。

    ★ 注意：粗体行高比常规**大 1px**（实测 22 vs 21）。所以同一排控件必须同
      字重，否则高度天然差 1px，且像素取整无法弥补（见 label_pad 的说明）。
    """
    fam = family or theme.font_ui_fallback
    key = (fam, size, bool(bold))
    if key not in _LINESPACE_CACHE:
        try:
            import tkinter.font as tkfont
            _LINESPACE_CACHE[key] = tkfont.Font(
                family=fam, size=size,
                weight="bold" if bold else "normal").metrics("linespace")
        except Exception:
            _LINESPACE_CACHE[key] = int(size * 1.6) + (1 if bold else 0)
    return _LINESPACE_CACHE[key]


def label_pad(theme, h, size=None, family=None, bold=False):
    """让**单个 Label**（FlatButton 那种）总高恰好 = h 的纵向内边距。

    Label 总高 = 行高 + 2×pady + 2×描边。
    """
    return max(0, (h - 2 - _linespace(theme, size or theme.fs_ctrl, family, bold)) // 2)


def frame_pad(theme, h, size=None, family=None, bold=False):
    """让**Frame 套 Label**（_Tab / Pill 那种）总高恰好 = h 的纵向内边距。

    总高 = (行高 + Label 自带上下 pady 2) + 2×pady + 2×描边。
    """
    return max(0, (h - 4 - _linespace(theme, size or theme.fs_ctrl, family, bold)) // 2)


# ---------------------------------------------------------------- 悬停解释框

def tip(widget, text, delay=380):
    """给任意控件挂一个鼠标悬停解释框（返回控件本身，方便链式调用）。

    ★ 2026-09-21 使用者要求：「最好把解释说明的括号文字都改成 tooltip」。
      于是界面上凡是 `（……）` 里的**解释性**文字，一律从正文里挪到这里，
      正文只留主体（「谱牒档」而不是「谱牒档（目的 · 可编辑）」）。
      · 数据自带的括号（人名、尊号里的）不动
      · 空态提示（「（一个槽也没有）」）不是解释，留在正文

    实现上刻意不用 ttk 的 Tooltip 组件（没有），也不引第三方：
    一个 `Toplevel` + `overrideredirect`，鼠标离开或按下即销毁。
    """
    if not text:
        return widget
    box = {"after": None, "win": None}

    def _cancel():
        if box["after"] is not None:
            try:
                widget.after_cancel(box["after"])
            except tk.TclError:
                pass
            box["after"] = None

    def _hide(_e=None):
        _cancel()
        w = box["win"]
        if w is not None:
            try:
                w.destroy()
            except tk.TclError:
                pass
            box["win"] = None

    def _show():
        if box["win"] is not None:
            return
        try:
            x = widget.winfo_rootx() + 14
            y = widget.winfo_rooty() + widget.winfo_height() + 4
        except tk.TclError:
            return
        win = tk.Toplevel(widget)
        win.wm_overrideredirect(True)
        win.wm_geometry(f"+{x}+{y}")
        try:
            win.attributes("-topmost", True)
        except tk.TclError:
            pass
        frm = tk.Frame(win, bg="#3a3a3a", bd=1, relief=tk.SOLID)
        frm.pack()
        tk.Label(frm, text=text, bg="#3a3a3a", fg="#f5f5f5", justify=tk.LEFT,
                 wraplength=_dpi.px(340), font=("微软雅黑", 10),
                 padx=8, pady=5).pack()
        box["win"] = win

    def _enter(_e=None):
        _cancel()
        box["after"] = widget.after(delay, _show)

    widget.bind("<Enter>", _enter, add="+")
    widget.bind("<Leave>", _hide, add="+")
    widget.bind("<ButtonPress>", _hide, add="+")
    return widget


# ---------------------------------------------------------------- ttk 样式

def apply_ttk_style(root, theme: Theme):
    """把 ttk 控件（Combobox/Scrollbar/Entry）调成主题色。"""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", font=(theme.font_ui_fallback, theme.fs_body))

    style.configure(
        "TCombobox",
        fieldbackground=theme.bg_input,
        background=theme.bg_card,
        foreground=theme.text,
        arrowcolor=theme.text_2,
        bordercolor=theme.border,
        lightcolor=theme.border,
        darkcolor=theme.border,
        insertcolor=theme.text,
        padding=2,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", theme.bg_input), ("disabled", theme.bg_panel)],
        foreground=[("disabled", theme.text_3)],
        bordercolor=[("focus", theme.accent)],
        arrowcolor=[("active", theme.accent)],
    )
    root.option_add("*TCombobox*Listbox.background", theme.bg_card)
    root.option_add("*TCombobox*Listbox.foreground", theme.text)
    root.option_add("*TCombobox*Listbox.selectBackground", theme.accent)
    root.option_add("*TCombobox*Listbox.selectForeground", theme.accent_on)
    root.option_add("*TCombobox*Listbox.font", (theme.font_ui_fallback, theme.fs_body))

    style.configure(
        "Vertical.TScrollbar",
        background=theme.border_2,
        troughcolor=theme.bg_panel,
        bordercolor=theme.bg_panel,
        arrowcolor=theme.text_2,
        width=theme.scrollbar_w,
    )
    style.configure(
        "Horizontal.TScrollbar",
        background=theme.border_2,
        troughcolor=theme.bg_panel,
        bordercolor=theme.bg_panel,
        arrowcolor=theme.text_2,
    )
    style.map(
        "Vertical.TScrollbar",
        background=[("active", theme.accent)],
    )
    style.map(
        "Horizontal.TScrollbar",
        background=[("active", theme.accent)],
    )

    style.configure("TEntry", fieldbackground=theme.bg_input, foreground=theme.text,
                    bordercolor=theme.border, insertcolor=theme.text, padding=2)
    style.configure("Treeview",
                    background=theme.bg_card, fieldbackground=theme.bg_card,
                    foreground=theme.text, bordercolor=theme.border,
                    rowheight=_dpi.px(24), font=(theme.font_ui_fallback, theme.fs_body))
    # ★ 2026-09-24：横向内距给 0 —— 行内容本身没有横向内距（Treeview.padding
    #   未设 = 0），而 Treeview.Heading 的 clam 默认是 3，表头汉字会比单元格
    #   汉字右移 3px（人物页原来写 6px，更明显）。使用者要求左沿齐平。
    style.configure("Treeview.Heading",
                    background=theme.bg_card, foreground=theme.text_2,
                    relief="flat", padding=(0, 3),
                    font=(theme.font_ui_fallback, theme.fs_body_sm, "bold"))
    style.map("Treeview.Heading", background=[("active", theme.bg_hover)])
    return style


# ---------------------------------------------------------------- 基础盒子

def hsep(parent, theme: Theme, color=None):
    """1px 水平分隔线。"""
    return tk.Frame(parent, height=1, bg=color or theme.border)


def vsep(parent, theme: Theme, color=None, height=20):
    return tk.Frame(parent, width=1, height=height, bg=color or theme.border)


def text_label(parent, theme: Theme, text="", size=None, bold=False, fg=None, bg=None,
               font_family=None, **kw):
    return tk.Label(parent, text=text, bg=bg or theme.bg_panel, fg=fg or theme.text,
                    font=(font_family or theme.font_ui_fallback, size or theme.fs_body,
                          "bold" if bold else "normal"),
                    bd=0, highlightthickness=0, **kw)


# ---------------------------------------------------------------- 按钮

_BTN_KINDS = {
    # kind: (背景, 前景, 边框, hover背景, 加粗)
    "default": ("bg_card", "text", "border_2", "bg_hover", False),
    "primary": ("accent", "accent_on", "accent", "accent_2", True),
    # ★ 2026-09-23 危险按钮统一「软红底 + 红字红边 + 粗体」：三主题（paper/ink/
    #   tencent）的 danger_soft 与 danger 对比度全部成立，比旧灰白底红字更像
    #   危险动作该有的样子（删除选中 / 清空封国 / 彻底删除槽 / 危险确认框主按钮）
    "danger":  ("danger_soft", "danger", "danger", "danger_soft", True),
    "ghost":   ("bg_bar", "text_2", "bg_bar", "bg_hover", False),
    "soft":    ("accent_soft", "accent", "accent", "accent_soft", True),
    "tool":    ("bg_card", "text_2", "border", "bg_hover", False),
    # 史馆：谱牒层（橙金）动作 —— 与实录层青绿 primary 成对
    "edit":    ("edit_soft", "edit_2", "edit", "edit_soft", True),
    "record":  ("accent_soft", "accent", "accent", "accent_soft", True),
    # ★ 2026-09-27 使用者要求「定位人物」跟旁边过滤胶囊**同款格式、只把字加粗变红**：
    #   底色与 hover 完全照 ChipRow 未选中胶囊（bg_hover / accent_soft），
    #   边框用面板底色（视觉上隐形，与胶囊一致），字走 danger 红 + 粗体。
    "locate":  ("bg_hover", "danger", "bg_card", "accent_soft", True),
}


class FlatButton(tk.Label):
    """扁平按钮（用 Label 实现，完全可控的底色/前景/hover）。"""

    def __init__(self, parent, theme: Theme, text="", command=None, kind="default",
                 width=None, height=None, padx=10, size=None, icon="", vpady=0, h=None,
                 bold=None):
        """`h`：目标总高（像素）。给了就按字体行高算出纵向内边距，使按钮
        恰好 h 高 —— 工具栏统一传 `theme.ctrl_h`（32），与顶栏页签/胶囊齐平
        （2026-09-23 对齐精修）。

        `bold`：覆盖 kind 的默认字重。★ 同一排控件**必须同字重** —— 粗体的
        行高比常规大 1px，而像素取整无法让两者同时等于目标高（h-2-linespace
        的奇偶性对不上），实测「橙金·粗体」按钮 32、「灰色·常规」按钮 31，
        下沿差 1px。工具栏一律传 bold=True 消除残差。
        """
        self.theme = theme
        self.kind = kind
        self.command = command
        self._enabled = True
        self._active = False

        bg_key, fg_key, bd_key, hv_key, bold_default = _BTN_KINDS.get(
            kind, _BTN_KINDS["default"])
        self._bg = getattr(theme, bg_key)
        self._fg = getattr(theme, fg_key)
        self._bd = getattr(theme, bd_key)
        self._hv = getattr(theme, hv_key)

        size = size or theme.fs_body_sm
        self._bold = bold_default if bold is None else bool(bold)
        if h:
            vpady = label_pad(theme, h, size, bold=self._bold)
        super().__init__(
            parent,
            text=(f"{icon} {text}".strip() if icon else text),
            bg=self._bg, fg=self._fg,
            font=(theme.font_ui_fallback, size, "bold" if self._bold else "normal"),
            bd=0, highlightthickness=1,
            highlightbackground=self._bd, highlightcolor=self._bd,
            padx=padx, pady=vpady, cursor="hand2",
        )
        if height:
            self.configure(height=height)
        if width:
            self.configure(width=width)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    # ---- 外观状态 ----
    def set_active(self, active: bool, accent=None, accent_on=None):
        """用于分段控件/开关按钮的选中态。

        史馆：`accent`/`accent_on` 可覆盖选中色 —— 谱牒层页签要走橙金而不是青绿。
        """
        self._active = active
        if active:
            bg = accent or self.theme.accent
            fg = accent_on or self.theme.accent_on
            self.configure(bg=bg, fg=fg, highlightbackground=bg)
        else:
            self.configure(bg=self._bg, fg=self._fg, highlightbackground=self._bd)

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        if not enabled:
            self.configure(fg=self.theme.text_3, cursor="arrow")
        else:
            self.configure(fg=self._fg, cursor="hand2")

    def set_text(self, text):
        self.configure(text=text)

    # ---- 事件 ----
    def _on_enter(self, _=None):
        if self._enabled and not self._active:
            self.configure(bg=self._hv)

    def _on_leave(self, _=None):
        if self._enabled and not self._active:
            self.configure(bg=self._bg)

    def _on_click(self, _=None):
        if self._enabled and self.command:
            self.command()


# ---------------------------------------------------------------- 卡片

class Card(tk.Frame):
    """带标题条的卡片：竖色条 + 标题 + 右侧计数 + 内容区。"""

    def __init__(self, parent, theme: Theme, title="", count_text=None, padding=6):
        super().__init__(parent, bg=theme.bg_card, highlightthickness=1,
                         highlightbackground=theme.border, highlightcolor=theme.border, bd=0)
        self.theme = theme

        head = tk.Frame(self, bg=theme.bg_card)
        head.pack(fill=tk.X)
        self.head = head

        bar = tk.Frame(head, width=3, height=12, bg=theme.accent)
        bar.pack(side=tk.LEFT, padx=(11, 7), pady=6)
        bar.pack_propagate(False)

        self.title_label = text_label(head, theme, title, size=theme.fs_title, bold=True,
                                      fg=theme.text_2, bg=theme.bg_card)
        self.title_label.pack(side=tk.LEFT, pady=6)

        self.count_label = text_label(head, theme, count_text or "", size=theme.fs_body_sm,
                                      fg=theme.text_3, bg=theme.bg_card)
        self.count_label.pack(side=tk.RIGHT, padx=(0, 11))

        tk.Frame(self, height=1, bg=theme.border).pack(fill=tk.X)

        self.body = tk.Frame(self, bg=theme.bg_card)
        self.body.pack(fill=tk.BOTH, expand=True, padx=11, pady=padding)

    def set_count(self, text):
        self.count_label.configure(text=text)

    def set_title(self, text):
        self.title_label.configure(text=text)


# ---------------------------------------------------------------- 顶栏胶囊

class Pill(tk.Frame):
    """顶栏胶囊：小标签 + 值 + ▼。

    史馆：`kind="record"`（青绿·实录槽）/ `kind="edit"`（橙金·谱牒档）——
    双下拉各带自己的色点，顶栏一眼分清哪枚是只读、哪枚能改。
    """

    def __init__(self, parent, theme: Theme, label="", value="", command=None,
                 kind="default", width=None, h=None):
        """定高 `h`（默认 ctrl_h=32）—— 与页签段、工具栏按钮同高同字号
        （2026-09-23 对齐精修）。"""
        if kind == "primary":
            bg, fg, bd = theme.accent, theme.accent_on, theme.accent
            label_fg = theme.accent_on
        elif kind == "ghost":
            bg, fg, bd = theme.bg_bar, theme.text_2, theme.bg_bar
            label_fg = theme.text_3
        elif kind == "record":
            bg, fg, bd = theme.bg_card, theme.text, theme.accent
            label_fg = theme.accent
        elif kind == "edit":
            bg, fg, bd = theme.bg_card, theme.text, theme.edit
            label_fg = theme.edit
        else:
            bg, fg, bd = theme.bg_card, theme.text, theme.border
            label_fg = theme.text_3

        super().__init__(parent, bg=bg, highlightthickness=1,
                         highlightbackground=bd, highlightcolor=bd, bd=0)
        self.theme = theme
        self.command = command
        self._bg = bg

        inner = tk.Frame(self, bg=bg)
        # ★ 字重统一粗体：与页签段、工具栏按钮同字重，行高才一致（见 label_pad）
        inner.pack(padx=11, pady=frame_pad(theme, h or theme.ctrl_h, theme.fs_ctrl,
                                           bold=True))
        self.inner = inner

        if label:
            self.label_widget = tk.Label(inner, text=label, bg=bg, fg=label_fg,
                                         font=(theme.font_ui_fallback, theme.fs_ctrl,
                                               "bold"), bd=0)
            self.label_widget.pack(side=tk.LEFT, padx=(0, 6))
        else:
            self.label_widget = None

        self.value_widget = tk.Label(inner, text=value, bg=bg, fg=fg,
                                     font=(theme.font_ui_fallback, theme.fs_ctrl,
                                           "bold"), bd=0)
        self.value_widget.pack(side=tk.LEFT)

        self.caret_widget = tk.Label(inner, text="▼" if command else "", bg=bg, fg=label_fg,
                                     font=(theme.font_ui_fallback, 7), bd=0)
        self.caret_widget.pack(side=tk.LEFT, padx=(6, 0))

        for w in (self, inner, self.value_widget, self.caret_widget):
            w.bind("<Button-1>", self._on_click)
            w.configure(cursor="hand2" if command else "arrow")
        if self.label_widget is not None:
            self.label_widget.bind("<Button-1>", self._on_click)

        if width:
            self.configure(width=width)
        # 高度已由内边距定死；宽度自然跟随内容 —— 存档名变长（set_value）
        # 时 Tk 自动重新布局，无需任何回调，也不会死循环

    def set_value(self, text):
        self.value_widget.configure(text=text)

    def _on_click(self, _=None):
        if self.command:
            self.command()


# ---------------------------------------------------------------- 小徽标

def chip(parent, theme: Theme, text, fg=None, bg=None, tip_text=None,
         size=None, padx=6, pady=1):
    """**小徽标**（比 `Pill` 小一号）：卡片里的条目名、「史实」「女性」这类标记。

    ★ 2026-09-28 全项目整理（第 6 批）：这个样式原来在**三处各写一遍** ——
      `person_view._info_cell` 的政策/能力/特质条目、`table_view` 的
      史实/女性/神祖徽标、`popcard` 的爵位小标，都是
      `tk.Label(..., highlightthickness=1, highlightbackground=border, padx=6,
      pady=1, font=(font_ui_fallback, fs_body_sm))`。抽成一处后，颜色、内边距、
      字号以后只有一个出处。

    ⚠️ 不要用 `Pill` 代替：那是**顶栏胶囊**（`ctrl_h=32` 高 + 粗体 + ▼），
      尺寸语义不同（塞进卡片里会大一号）。
    `tip_text` 给了就自动挂悬停说明（走 `kit.tip`）。
    """
    lab = tk.Label(parent, text=str(text), bg=bg or theme.bg_card,
                   fg=fg or theme.text,
                   cursor="hand2" if tip_text else "arrow",
                   highlightthickness=1, highlightbackground=theme.border,
                   highlightcolor=theme.border, bd=0, padx=padx, pady=pady,
                   font=(theme.font_ui_fallback, size or theme.fs_body_sm))
    if tip_text:
        tip(lab, tip_text)
    return lab


# ---------------------------------------------------------------- 分段控件

class _Tab(tk.Frame):
    """分段控件的复合按钮：MDL2 图标（可选）+ 文字，整体可点（UI 改进 B8）。

    原来图标与文字挤在一个 Label 里，图标字符（⌂♣⛨…）在部分系统渲染成方框；
    现在图标走 Segoe MDL2 Assets 独立 Label，且只有经 `glyph_ok` 验证过的
    才会传进来 —— 缺字自动退纯文字，绝不出现方框。
    """

    def __init__(self, parent, theme: Theme, text="", icon="", command=None, padx=14,
                 h=30, size=None):
        """定高 `h`（默认 30 = Segmented 32 外框减 2 描边）。高度由「字体行高
        + 算出的内边距」决定，宽度自然跟随内容 —— 不用 pack_propagate 锁死、
        也不量 reqwidth，渲染前后都稳定（2026-09-23 对齐精修）。"""
        super().__init__(parent, bg=theme.bg_card, highlightthickness=1,
                         highlightbackground=theme.bg_card,
                         highlightcolor=theme.bg_card, bd=0)
        self.theme = theme
        self.command = command
        self._active = False
        self._base_bg = theme.bg_card
        self._base_fg = theme.text_2
        self._bd = theme.bg_card
        self.configure(cursor="hand2")

        fs = size or theme.fs_ctrl
        # ★ 字重统一粗体：与工具栏按钮同字重，行高才一致（见 label_pad 说明）
        inner = tk.Frame(self, bg=theme.bg_card)
        inner.pack(padx=padx, pady=frame_pad(theme, h, fs, bold=True))
        self._inner = inner
        self._icon_lab = None
        if icon:
            self._icon_lab = tk.Label(inner, text=icon, bg=theme.bg_card,
                                      fg=theme.text_2, font=(MDL2_FONT, fs))
            self._icon_lab.pack(side=tk.LEFT, padx=(0, 5))
        self._text_lab = tk.Label(inner, text=text, bg=theme.bg_card, fg=theme.text_2,
                                  font=(theme.font_ui_fallback, fs, "bold"))
        self._text_lab.pack(side=tk.LEFT)

        clickables = [self, inner, self._text_lab]
        if self._icon_lab is not None:
            clickables.append(self._icon_lab)
        for w in clickables:
            w.bind("<Button-1>", self._on_click)
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)

    def _on_click(self, _e=None):
        if self.command:
            self.command()

    def _on_enter(self, _e=None):
        if not self._active:
            self._paint(bg=self.theme.bg_hover)

    def _on_leave(self, _e=None):
        if not self._active:
            self._paint(bg=self._base_bg)

    def _paint(self, bg=None, fg=None, bd=None):
        bg = bg or self._base_bg
        fg = fg or self._base_fg
        bd = bd or self._bd
        self.configure(bg=bg, highlightbackground=bd, highlightcolor=bd)
        self._inner.configure(bg=bg)
        self._text_lab.configure(bg=bg, fg=fg)
        if self._icon_lab is not None:
            self._icon_lab.configure(bg=bg, fg=fg)

    def set_active(self, active, accent=None, accent_on=None):
        """选中态按所属层上色（实录青绿 / 谱牒橙金），与旧 FlatButton 接口一致。"""
        self._active = bool(active)
        if self._active:
            self._base_bg = accent or self.theme.accent
            self._base_fg = accent_on or self.theme.accent_on
            self._bd = self._base_bg
        else:
            self._base_bg = self.theme.bg_card
            self._base_fg = self.theme.text_2
            self._bd = self.theme.bg_card
        self._paint(bg=self._base_bg, fg=self._base_fg, bd=self._bd)


class Segmented(tk.Frame):
    """[人物 | 家谱 | …] 分段切换。items = [(key, text, icon), ...]，`"-"` 为分隔线。

    史馆加了两件事：
      · 支持 `"-"` 元素 —— 实录层（青绿）与谱牒层（橙金）两组之间断开，
        一眼看出哪几个页签是「查阅」、哪几个是「动笔」
      · 激活态按**该页签所属层**上色 —— 实录页青绿、谱牒页橙金
    UI 改进 B8：按钮换成 `_Tab` 复合控件，`icon` 传 MDL2 码点
    （调用方负责先过 `glyph_ok`；传空串就是纯文字，外观与旧版等价）。
    """

    def __init__(self, parent, theme: Theme, items, command=None, active="tree",
                 layer_of=None, h=None, tab_padx=14, size=None):
        """定高 `h`（默认 ctrl_h=32）—— 外框 32 与顶栏胶囊、工具栏按钮同高
        （2026-09-23 对齐精修）。高度靠内部 `_Tab`（h-2）撑出来，宽度自然；
        `tab_padx` 控制每格左右留白，各页签等距（使用者要求「四词间隙一致」）。"""
        h = h or theme.ctrl_h
        super().__init__(parent, bg=theme.bg_card, highlightthickness=1,
                         highlightbackground=theme.border, highlightcolor=theme.border,
                         bd=0)
        self.theme = theme
        self.command = command
        self.layer_of = layer_of or {}
        self.buttons = {}
        inner = tk.Frame(self, bg=theme.bg_card)
        inner.pack(padx=0, pady=0)
        for item in items:
            if item == "-":
                sp = tk.Frame(inner, bg=theme.border_2, width=1, height=h - 16)
                sp.pack(side=tk.LEFT, padx=8)
                continue
            key, text, icon = item
            layer = self.layer_of.get(key, "record")
            btn = _Tab(inner, theme, text=text, icon=icon or "",
                       command=lambda k=key: self._select(k), padx=tab_padx,
                       h=h - 2, size=size)
            btn.pack(side=tk.LEFT)
            btn._layer = layer
            self.buttons[key] = btn
        self._active = active
        self.set_active(active)

    def _accent_for(self, key):
        return (self.theme.edit, self.theme.edit_on) \
            if self.layer_of.get(key) == "edit" \
            else (self.theme.accent, self.theme.accent_on)

    def _select(self, key):
        self.set_active(key)
        if self.command:
            self.command(key)

    def set_active(self, key):
        self._active = key
        for k, btn in self.buttons.items():
            bg, fg = self._accent_for(k)
            btn.set_active(k == key, accent=bg, accent_on=fg)


# ---------------------------------------------------------------- 表单行

def input_box(parent, theme: Theme, textvariable=None, width=None, placeholder="",
              readonly=False):
    """统一外观的输入框（Entry）。"""
    if textvariable is None:
        textvariable = tk.StringVar()
    ent = tk.Entry(
        parent, textvariable=textvariable, bd=0, highlightthickness=1,
        highlightbackground=theme.border, highlightcolor=theme.accent,
        bg=theme.bg_input, fg=theme.text, insertbackground=theme.text,
        font=(theme.font_ui_fallback, theme.fs_body), relief=tk.FLAT,
        readonlybackground=theme.bg_input,
    )
    if width:
        ent.configure(width=width)
    if readonly:
        ent.configure(state="readonly")
    return ent


def combo_box(parent, theme: Theme, values=None, textvariable=None, width=None,
              readonly=True):
    """统一样式的下拉框（ttk.Combobox）。

    `readonly=False` 时可编辑 —— 使用者既能从下拉里挑已有的，也能直接打一个新名字
    （续谱对话框「手动指定目标谱牒」就是靠它，2026-09-22）。
    配色走 `apply_ttk_style` 配好的 "TCombobox"，这里不重复配。
    """
    cb = ttk.Combobox(parent, values=values or [], textvariable=textvariable,
                      width=width or 10, state="readonly" if readonly else "normal",
                      font=(theme.font_ui_fallback, theme.fs_body))
    return cb


def attach_placeholder(entry, theme: Theme, text, var=None):
    """给 Entry 加占位提示（失焦且为空时显示灰色提示）。"""
    var = var or entry.cget("textvariable")
    state = {"showing": False}

    def show():
        if entry.get() == "":
            state["showing"] = True
            entry.configure(fg=theme.text_3)
            entry.insert(0, text)

    def hide(_=None):
        if state["showing"]:
            state["showing"] = False
            entry.delete(0, tk.END)
            entry.configure(fg=theme.text)

    entry.bind("<FocusIn>", hide)
    entry.bind("<FocusOut>", lambda e: show())
    show()

    def real_value():
        # ★ 2026-09-29：原来只看 `state["showing"]` —— 而它**只在焦点进出时更新**，
        #   于是「用代码写值（`var.set(...)`）而不是用户手打」时，
        #   `showing` 仍是 True，`real_value()` 会**假报空**。
        #   （家谱页「⌖ 定位人物」要读这个搜索框，踩到的就是这个。）
        #   现在补一层：显示态下若框里的内容**不是占位符本身**，那就是真值。
        if not state["showing"]:
            return entry.get()
        v = entry.get()
        return "" if v == text else v

    entry.real_value = real_value
    entry.placeholder_text = text      # 供调用方识别占位文案（勿与真值混淆）
    return entry


class RadioRow(tk.Frame):
    """一组单选（男/女、是/否）。"""

    def __init__(self, parent, theme: Theme, variable, options, command=None, gap=14):
        super().__init__(parent, bg=theme.bg_card)
        self.theme = theme
        self.variable = variable
        self.indicators = {}
        self.labels = {}
        for value, text in options:
            holder = tk.Frame(self, bg=theme.bg_card)
            holder.pack(side=tk.LEFT, padx=(0, gap))
            dot = tk.Canvas(holder, width=13, height=13, bg=theme.bg_card,
                            highlightthickness=0, bd=0)
            dot.pack(side=tk.LEFT, padx=(0, 5))
            lab = tk.Label(holder, text=text, bg=theme.bg_card, fg=theme.text,
                           font=(theme.font_ui_fallback, theme.fs_body), bd=0, cursor="hand2")
            lab.pack(side=tk.LEFT)
            self.indicators[value] = dot
            self.labels[value] = lab
            for w in (dot, lab, holder):
                w.bind("<Button-1>", lambda e, v=value: self._pick(v))
        self.command = command
        self.variable.trace_add("write", lambda *_: self.refresh())
        self.refresh()

    def _pick(self, value):
        self.variable.set(value)
        if self.command:
            self.command()

    def refresh(self):
        cur = self.variable.get()
        for value, dot in self.indicators.items():
            dot.delete("all")
            on = (value == cur)
            color = self.theme.accent if on else self.theme.border_2
            dot.create_oval(1, 1, 12, 12, outline=color, width=1.5)
            if on:
                dot.create_oval(4, 4, 9, 9, outline="", fill=self.theme.accent)
            self.labels[value].configure(
                fg=self.theme.accent if on else self.theme.text,
                font=(self.theme.font_ui_fallback, self.theme.fs_body,
                      "bold" if on else "normal"))


class ChipRow(tk.Frame):
    """一排小胶囊（过滤开关）。

    选中时前缀一个「✓」、未选中时补两个空格（宽度不跳），
    后面可以挂一个计数后缀（`set_suffix`）—— 人物筛选那几个勾选框就靠它。
    """

    def __init__(self, parent, theme: Theme, items, command=None, gap=6,
                 size=None, pad=9, grid_cols=None):
        """`grid_cols`：把胶囊排成 N 列**等宽格子**（uniform 列），格子大小
        完全一致、文字左对齐 —— 人物页筛选「出生记录 9」短也不会把右边
        的格子挤歪（2026-09-23 使用者要求「像固定表格」）。
        items 里 text=None 的项渲染为空白占位格。
        """
        super().__init__(parent, bg=theme.bg_card)
        self.theme = theme
        self.command = command
        self.chips = {}
        self._size = size or theme.fs_body_sm
        self._text = {}
        self._suffix = {}
        if grid_cols:
            for c in range(grid_cols):
                self.columnconfigure(c, weight=1, uniform="_chipcol")
        for i, (key, text) in enumerate(items):
            if text is None:
                continue                    # 空白占位格（保持网格对齐）
            lab = tk.Label(self, text=text, bg=theme.chip_bg,
                           fg=theme.text_2, font=(theme.font_ui_fallback, self._size),
                           bd=0, highlightthickness=1,
                           highlightbackground=theme.bg_card,
                           padx=pad, pady=3, cursor="hand2",
                           anchor="w" if grid_cols else "center")
            if grid_cols:
                r, c = divmod(i, grid_cols)
                lab.grid(row=r, column=c, sticky="ew", padx=3, pady=(0, gap))
            else:
                lab.pack(side=tk.LEFT, padx=(0, gap))
            lab.bind("<Button-1>", lambda e, k=key: self._toggle(k))
            self.chips[key] = lab
            self._text[key] = text
        self._state = {k: False for k, _t in items if _t is not None}

    def _toggle(self, key):
        self._state[key] = not self._state[key]
        self.refresh()
        if self.command:
            self.command(key, self._state[key])

    def set_state(self, key, value):
        self._state[key] = value
        self.refresh()

    def set_suffix(self, key, text):
        """给某个胶囊挂一段尾巴（一般用来显示计数）。"""
        self._suffix[key] = text or ""
        self.refresh()

    def set_all(self, value):
        for k in self._state:
            self._state[k] = bool(value)
        self.refresh()

    def refresh(self):
        for key, lab in self.chips.items():
            on = self._state[key]
            lab.configure(
                text=("✓ " if on else "  ") + self._text[key] + self._suffix.get(key, ""),
                bg=self.theme.accent_soft if on else self.theme.bg_hover,
                fg=self.theme.accent if on else self.theme.text_2,
                highlightbackground=self.theme.accent if on else self.theme.bg_card,
                font=(self.theme.font_ui_fallback, self._size,
                      "bold" if on else "normal"),
            )
