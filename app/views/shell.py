"""三段式外壳：顶栏 52 / 侧栏 288 / 状态栏 28，按《史馆 · 合并效果图》实现。

史馆相对家族树的三处改动（规划 §四）：
  1. 分段控件 3 页签 → **5 页签**，青绿组（人物·世界＝实录层）与
     橙金组（家谱·时间轴·表格＝谱牒层）之间插一条分隔
  2. 右侧「存档▾」→ **★ 双层来源选择器**：青绿「实录槽▾」+ 橙金「谱牒档▾」
  3. 状态栏左端常驻 **双层计数** `实录 9106 · 谱牒 3233`
"""
import tkinter as tk

from .. import dpi as _dpi
from ..contract import APP_VER, VIEWS, VIEW_GAP_AFTER, VIEW_LAYER
from ..widgets.kit import (Card, ChipRow, FlatButton, Pill, RadioRow, Segmented,
                           attach_placeholder, combo_box, glyph_ok, hsep, input_box,
                           text_label, tip as hover_tip, vsep)

# 页签图标（UI 改进 B8）：候选码点 import 后立即经 kit.glyph_ok 运行时验证，
# 验证不过的键**不显示图标**（纯文字，与旧版外观一致）—— 绝不出现方框。
_TAB_GLYPH_CANDIDATES = {
    "person": ("\uE77B", "\uE716"),          # Contact / People
    "tree": ("\uE716", "\uE8A5"),            # People(两人) / Document
    "world": ("\uE774", "\uE809"),           # Globe
    "table": ("\uE8A5", "\uE71D"),           # Document / AllApps
}
# ★ 2026-09-22 使用者反馈：「人物 家谱那一排 菜单的 bar 把字都盖住了」——
#   MDL2 符号（小人/∝/日历）挤在汉字旁边视觉发杂，页签退回**纯文字**。
#   验证基建（kit.glyph_ok）与候选表原样保留，想再开图标把开关改 True 即可。
TAB_ICONS = False
TAB_GLYPHS = {}
if TAB_ICONS:
    for _k, _cands in _TAB_GLYPH_CANDIDATES.items():
        for _c in _cands:
            if glyph_ok(_c):
                TAB_GLYPHS[_k] = _c
                break


class TopBar(tk.Frame):
    """应用顶栏：品牌 | [人物|家谱|时间轴|世界|表格] | 实录▾ 谱牒▾ 主题▾ 同步 ⚙"""

    def __init__(self, parent, theme, callbacks, view="person",
                 record_name="", book_name="", theme_name=""):
        super().__init__(parent, bg=theme.bg_bar, height=theme.topbar_h)
        self.pack_propagate(False)
        self.theme = theme
        self.callbacks = callbacks

        inner = tk.Frame(self, bg=theme.bg_bar)
        inner.pack(fill=tk.BOTH, expand=True)

        # ── 左段：品牌区，宽度**跟随实际侧栏宽** ──
        # 「史」字绿框左缘（x=8）与下方侧栏卡片左缘对齐；右边界 = 画布左缘 ——
        # 页签、工具栏按钮全部从这条竖线起跑（2026-09-23 对齐精修）。
        # ★ 2026-09-28 使用者报「这里的人物bar 能不能左沿跟代际对齐啊」：
        #   原文写过 `width=theme.sidebar_w` —— 但侧栏装在**可拖拽的
        #   PanedWindow** 里（`sashwidth=6`），主区左缘其实是
        #   `侧栏宽 + 拖动条宽`，于是**工具条比页签左移了一条 sash**（6px），
        #   用户一拖更错。现在品牌区宽度由 `set_brand_width()` 按**实际**
        #   侧栏宽同步（见 main 的 `_sync_brand_width`）。
        self.brandzone = tk.Frame(inner, bg=theme.bg_bar, width=theme.sidebar_w)
        self.brandzone.pack(side=tk.LEFT, fill=tk.Y)
        self.brandzone.pack_propagate(False)
        brandzone = self.brandzone
        brand = tk.Frame(brandzone, bg=theme.bg_bar)
        # ★ 2026-09-23 anchor="w"：不加它时 expand 会把 brand 在 brandzone 里
        #   **水平居中**，于是「史」绿框左缘跑到 (336-内容宽)/2+8 ≈ 56px，
        #   与下方侧栏卡片的左缘（8px）明显错开 —— 使用者反馈「很不和谐」。
        brand.pack(padx=8, expand=True, anchor="w")
        mark = tk.Label(brand, text="史", bg=theme.accent, fg=theme.accent_on,
                        font=(theme.font_gen, 16), width=2, height=1)
        mark.pack(side=tk.LEFT)
        text_label(brand, theme, "大周列国志 · 史馆", size=theme.fs_brand, bold=True,
                   bg=theme.bg_bar).pack(side=tk.LEFT, padx=(9, 6))
        # ★ 版本号单一定义源是 contract.APP_VER（2026-09-22 升 2.0），
        #   这里不再写死，避免下次升版漏改
        ver = tk.Label(brand, text=f"{APP_VER} 版", bg=theme.accent_soft, fg=theme.accent,
                       font=(theme.font_ui_fallback, 10, "bold"), padx=6)
        ver.pack(side=tk.LEFT)

        # 视图分段：四页签等距（不再插组分隔线 —— 使用者要求四词间隙一致）
        # ★ 图标换成经运行时验证的 Segoe MDL2 码点（B8）；验证不过 = 纯文字
        items = [(key, label, TAB_GLYPHS.get(key, "")) for key, label, icon, _layer in VIEWS]
        self.segmented = Segmented(inner, theme, items=items,
                                   command=callbacks.get("switch_view"), active=view,
                                   layer_of=VIEW_LAYER)
        # 无左边距：段左缘 = 品牌区右缘 = 画布左缘
        self.segmented.pack(side=tk.LEFT, pady=8)

        # 右侧：一个「存档」胶囊 + 续谱 + 设置（全部 32 高、12 号字，与页签同规）
        right = tk.Frame(inner, bg=theme.bg_bar)
        right.pack(side=tk.RIGHT, padx=(0, 12), pady=8)

        self.pill_settings = Pill(right, theme, label="", value="⚙",
                                  command=callbacks.get("settings"))
        self.pill_settings.pack(side=tk.RIGHT, padx=(8, 0))
        self.pill_settings.value_widget.configure(
            font=(theme.font_ui_fallback, theme.fs_ctrl, "bold"))

        # ★ 续谱（橙金 · 编辑色）：拉档 → 抽取 → 增量合并写回，一键完成。
        self.pill_extend = Pill(right, theme, label="", value="⟲ 续谱", kind="edit",
                                command=callbacks.get("extend"))
        self.pill_extend.pack(side=tk.RIGHT, padx=(8, 0))

        # ★ 存档（青绿）：一个入口管两层 —— 谱牒（目的）+ 实录槽（来源）。
        #   原来「实录▾」「谱牒▾」两个下拉并排占位，甲方说得对：它俩本来就是
        #   一件事的两头（谱牒是目的，实录是来源），合成一个才不啰嗦。
        self.pill_archive = Pill(right, theme, label="存档", value="（无）",
                                 kind="record", command=callbacks.get("open_archive"))
        self.pill_archive.pack(side=tk.RIGHT, padx=(8, 0))

        # ★ 2026-09-26：**页面统计句不在这里** —— 使用者裁定统一放**底部状态栏**
        #   （`StatusBar` 的 `gen` 格，见 main._update_status）。顶栏这条空白带
        #   曾试挂一版计数，窄窗口仍会被页签 + 胶囊挤掉，故整体撤除。

        # 底部 1px 分隔
        hsep(self, theme).pack(side=tk.BOTTOM, fill=tk.X)

    # ---------------------------------------------------------------- 更新
    def set_view(self, view):
        self.segmented.set_active(view)

    def set_brand_width(self, px):
        """把品牌区宽度对齐到**实际**主区左缘。

        ★ 2026-09-28 使用者：「这里的人物bar 能不能左沿跟代际对齐啊，
          不是说尽量都对齐吗」—— 页签靠品牌区右边界定位，工具条最左控件挂在
          主区里；侧栏可拖拽 ⇒ 主区左缘是动态的。由 `main._sync_brand_width`
          传入**实测**差值（主区左缘 − 顶栏左缘），页签外框就与工具条最左控件
          （家谱页是「代际|时间」段）永远同一条竖线。
        ⚠️ 这个方法**必须挂在 `TopBar`** —— 第一版我误加到了 `ToolBar` 上，
          那边没有 `brandzone`，每次调用都 `AttributeError` 被兜底 `except`
          **静默吞掉**，表现是"改了代码但一点没变"（量出来品牌区仍是 504）。
        """
        try:
            self.brandzone.configure(width=max(0, int(px)))
        except Exception:
            pass

    def set_archive(self, book, record, tip=""):
        """「存档」胶囊显示当前工作上下文：谱牒（目的）→ 实录（来源）。"""
        text = f"{book or '（无谱牒）'} → {record or '（无实录）'}"
        self.pill_archive.set_value(text)
        self._tip(self.pill_archive,
                  "存档 = 谱牒（目的 · 可编辑）+ 实录槽（来源 · 只读）\n"
                  "点一下切换；切谱牒会自动带上它绑定的实录槽。\n" + (tip or ""))

    # ---------------------------------------------------------------- 统计计数
    # ★ 2026-09-26：家谱 / 时间轴 / 表格页的统计句**不在这里** —— 使用者裁定
    #   统一落底部状态栏（`StatusBar` 的 `gen` 格，填充口 `main._update_status`）。
    #   顶栏这一版计数器（三档自适应 + 悬停看全）已整体撤除：窄窗口下它照样会被
    #   页签与「存档」胶囊挤掉，而状态栏那一条永远放得下整句。

    # ★ 2026-09-28 全项目整理（第 1 批）：此处原有**第二套**自制悬停提示
    #   （`_tip` + `_show_tip` + `_hide_tip`，40 行、硬编码 `#3a3a3a`）。
    #   本模块顶部早就 import 了 `kit.tip as hover_tip`，收敛成一行别名即可，
    #   调用点（`self._tip(...)`）一处不用改。
    _tip = staticmethod(hover_tip)



class ToolBar(tk.Frame):
    """主视图工具条（高 46，单行 · 2026-09-23 对齐精修）。

    本控件挂在 main_area 里（main_area 左缘 = 画布左缘 = 顶栏品牌区右缘），
    故 inner 不再留左内边距 —— 最左控件与画布、顶栏页签同一条竖线起跑。

      · 所有控件统一 32 高、12 号字（ctrl_h / fs_ctrl），与顶栏同规；
      · 组间只留一条通高竖线，**不画组名小字**（使用者 2026-09-23 拍板删除）；
      · 家谱页最左是「代际|时间」模式段（与按钮同高同字号）；
      · 右端「⋯」溢出固定（★ 2026-09-26：页面统计句统一收在**底部状态栏**
        `StatusBar` 的 `gen` 格 —— 原来挂在本条右端，被「⋯」挤成「可见 1…」）。
        命令一个不减。

    参数：
      groups   = [(组名（仅作注释，不显示）, [spec, ...]), ...]；
                 spec = (key, text, command [, kind][, tip])。
      mode_seg = (items, active, command) → 最左模式段（家谱页专用）。
    """

    def __init__(self, parent, theme, groups, overflow=None, mode_seg=None):
        super().__init__(parent, bg=theme.bg_bar, height=theme.toolbar_h)
        self.pack_propagate(False)
        self.theme = theme
        inner = tk.Frame(self, bg=theme.bg_bar)
        inner.pack(fill=tk.BOTH, expand=True, padx=(0, 12))

        # ── 最左：模式段（家谱页），与按钮同高同字号 ──
        self.mode_seg = None
        if mode_seg:
            items, active, cmd = mode_seg
            self.mode_seg = Segmented(inner, theme, items=items, command=cmd,
                                      active=active,
                                      layer_of={k: "edit" for k, _t, _i in items})
            self.mode_seg.pack(side=tk.LEFT, padx=(0, 6), pady=7)
            vsep(inner, theme).pack(side=tk.LEFT, fill=tk.Y, pady=7, padx=(2, 6))

        # ── 按钮组：单行，组间竖线，全部 32 高 12 号字（与顶栏同规）──
        self.buttons = {}
        for gi, (_gname, specs) in enumerate(groups):
            if gi:
                vsep(inner, theme).pack(side=tk.LEFT, fill=tk.Y, pady=7, padx=6)
            for spec in specs:
                key, text, command = spec[0], spec[1], spec[2]
                kind = spec[3] if len(spec) > 3 else "tool"
                btn = FlatButton(inner, theme, text=text, command=command,
                                 kind=kind, padx=10, h=theme.ctrl_h,
                                 size=theme.fs_ctrl, bold=True)
                btn.pack(side=tk.LEFT, padx=2, pady=7)
                if len(spec) > 4 and spec[4]:
                    hover_tip(btn, spec[4])
                self.buttons[key] = btn

        # ── 右端固定：⋯ 溢出（页面统计句在**底部状态栏**，★ 2026-09-26）──
        self._overflow = list(overflow or [])
        self._menu = None
        if self._overflow:
            FlatButton(inner, theme, text="⋯", command=self._open_overflow,
                       kind="tool", padx=9, h=theme.ctrl_h,
                       size=theme.fs_ctrl, bold=True).pack(side=tk.RIGHT,
                                                           padx=(2, 6), pady=7)

        hsep(self, theme).pack(side=tk.BOTTOM, fill=tk.X)

    def _open_overflow(self):
        """点开「⋯」溢出菜单（每次重建条目，主题跟随换肤）。"""
        theme = self.theme
        if self._menu is None:
            self._menu = tk.Menu(self, tearoff=0)
        menu = self._menu
        menu.delete(0, "end")
        menu.configure(bg=theme.bg_card, fg=theme.text,
                       activebackground=theme.accent_soft,
                       activeforeground=theme.accent,
                       font=(theme.font_ui_fallback, theme.fs_body), bd=1)
        for _key, text, command, *_rest in self._overflow:
            menu.add_command(label=text, command=command)
        x = self.winfo_rootx() + self.winfo_width() - 40
        y = self.winfo_rooty() + self.winfo_height()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def set_button_text(self, key, text):
        """改某个按钮的字（快捷键切抽屉后要把「⬓/⬔」同步过来）。"""
        btn = self.buttons.get(key)
        if btn is None:
            return
        try:
            btn.configure(text=text)
        except Exception:
            pass


class StatusBar(tk.Frame):
    """状态栏（高 28）：双层计数 │ 选中 │ 谱内统计 │ 来源 │ 提示

    两个常驻锚点：
      · 左端 **双层计数** `实录 9106 · 谱牒 3233` —— 两层视角永远同屏可见
        （规划 §四）。实录用青绿、谱牒用橙金，和顶栏两枚下拉一一对应。
      · ★ 2026-09-26 使用者裁定：家谱 / 时间轴 / 表格页的**统计句**也落在这里
        （`gen` 格）。它原来是挂在主区工具栏右端，被「⋯」和一排按钮挤成
        「可见 1…」；状态栏这一条放得下整句，不留半截数字。
    """

    def __init__(self, parent, theme):
        super().__init__(parent, bg=theme.bg_bar, height=theme.statusbar_h)
        self.pack_propagate(False)
        self.theme = theme
        hsep(self, theme).pack(side=tk.TOP, fill=tk.X)

        inner = tk.Frame(self, bg=theme.bg_bar)
        inner.pack(fill=tk.BOTH, expand=True, padx=4)
        self.inner = inner
        self.items = {}
        self.colors = {}

        self._add("counts", "实录 — · 谱牒 —", color="dual")
        self._add("sel", "未选中")
        # ★ 2026-09-26：家谱 / 时间轴 / 表格页的**完整统计句**都写这一格
        #   （谱内 N 人 · 根节点 R · 可见 A–B 代 / 时间轴视口… · 连线 K 条 /
        #    谱牒 N 行 · 显示 M 行）—— 填充口只有 main._update_status 一处。
        self._add("gen", "—")
        self._add("source", "实录槽 — ｜ 谱牒档 —")
        # UI 改进 C12：「已保存 HH:MM」格删除 —— 保存瞬间 hint 已报过一次，
        # 常驻格信息价值低，省出宽度给 source（双层来源才是常驻锚点）。
        self._add("hint", "", last=True)

    def _add(self, key, text, last=False, color=None):
        lab = tk.Label(self.inner, text=text, bg=self.theme.bg_bar, fg=self.theme.text_2,
                       font=(self.theme.font_ui_fallback, self.theme.fs_status), bd=0)
        lab.pack(side=tk.LEFT, padx=12)
        if not last:
            vsep(self.inner, self.theme, height=14).pack(side=tk.LEFT)
        self.items[key] = lab
        if color:
            self.colors[key] = color

    def set(self, key, text, accent=False):
        lab = self.items.get(key)
        if lab is None:
            return
        lab.configure(text=text,
                      fg=self.theme.accent if accent else self.theme.text_2)

    def set_counts(self, record=None, book=None):
        """双层计数：`实录 9106 · 谱牒 3233`。

        左端常驻（规划 §四）—— 不管当前在哪一页，两层各自有多少人永远看得见。
        """
        lab = self.items.get("counts")
        if lab is None:
            return
        rt = "—" if record is None else f"{record}"
        bt = "—" if book is None else f"{book}"
        lab.configure(text=f"实录 {rt}　·　谱牒 {bt}", fg=self.theme.text)


class Sidebar(tk.Frame):
    """侧栏 288：过滤 / 人物信息 / 关系 / 爵位封国 / 操作。

    控件与 v1 一一对应，保证现有编辑能力不丢。
    """

    def __init__(self, parent, theme, app):
        super().__init__(parent, bg=theme.bg_panel, width=theme.sidebar_w)
        self.pack_propagate(False)
        self.theme = theme
        # 注意：不能叫 self.master，那是 tkinter 的保留属性（父控件链），
        # 覆盖它会让事件分发时 _root() 解析失败
        self.app = app

        # 底部固定区（操作卡片常驻可见，不随滚动条滚走）
        self.footer = tk.Frame(self, bg=theme.bg_panel)
        self.footer.pack(side=tk.BOTTOM, fill=tk.X)
        vsep(self, theme, color=theme.border).place(relx=1.0, rely=0, relheight=1.0, anchor="ne")

        # 可滚动容器
        self.canvas = tk.Canvas(self, bg=theme.bg_panel, highlightthickness=0, bd=0,
                                width=theme.sidebar_w)
        scroll = tk.Scrollbar(self, orient=tk.VERTICAL, command=self.canvas.yview,
                              bg=theme.border_2, troughcolor=theme.bg_panel,
                              activebackground=theme.accent, highlightthickness=0, bd=0,
                              width=theme.scrollbar_w, relief=tk.FLAT)
        self.inner = tk.Frame(self.canvas, bg=theme.bg_panel)
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw",
                                  width=theme.sidebar_w - theme.scrollbar_w)
        self.canvas.configure(yscrollcommand=scroll.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        def _wheel(event):
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        # ★ 2026-09-23 修「侧栏没法上下滚」：旧代码把 bind_all 挂在 canvas 的
        # <Enter>、<Leave> 上 —— 而卡片是 canvas 的子控件，鼠标一移到卡片上
        # 就触发 canvas 的 Leave（穿入子控件），滚轮立刻被解绑。结果鼠标停在
        # 内容上（滚动时最正常的位置）滚轮反而死了。
        # 新办法：进入整个侧栏就绑全局滚轮；Leave 后延时核对指针是否真的出了
        # 侧栏矩形，没出（只是穿到子控件）就保留绑定。
        def _arm(_e=None):
            self.canvas.bind_all("<MouseWheel>", _wheel)

        def _disarm(_e=None):
            self.after(60, self._wheel_check_out)

        # 给侧栏整棵控件树挂一个共享 bindtag：进入任何子控件都算「在侧栏内」，
        # 控件之间穿行触发的 Leave 经 _wheel_check_out 指针核对后不会误解绑
        self._wheel_tag = "_SidebarWheelZone"
        self.bind_class(self._wheel_tag, "<Enter>", _arm)
        self.bind_class(self._wheel_tag, "<Leave>", _disarm)

        self._build()

        def _tag(widget):
            tags = list(widget.bindtags())
            tags.append(self._wheel_tag)
            widget.bindtags(tags)
            for ch in widget.winfo_children():
                _tag(ch)
        _tag(self)

        # ★ 2026-09-23 恢复筛选 chip 选中态 + 侧边栏滚动位置（持久化需求）
        if hasattr(app, "on_sidebar_ready"):
            app.on_sidebar_ready(self)

    def _wheel_check_out(self):
        """Leave 后核对：指针真出了侧栏矩形才解绑滚轮（穿行子控件不解）。"""
        try:
            px, py = self.winfo_pointerxy()
            x, y = self.winfo_rootx(), self.winfo_rooty()
            inside = (x <= px < x + self.winfo_width()
                      and y <= py < y + self.winfo_height())
        except tk.TclError:
            inside = False
        if not inside:
            self.canvas.unbind_all("<MouseWheel>")

    def default_scroll_y(self):
        """默认滚动比例：★ 2026-09-26 使用者改口「一打开默认拉到最底下」——
        「操作」按钮（保存/删除/查档）直接可见。（原默认是「当前宗支」贴顶，
        那是为了少滚一屏看筛选；本条以使用者最新要求为准。）"""
        return 1.0

    def _build(self):
        theme, m = self.theme, self.app
        pad = {"padx": 8, "pady": (5, 0)}

        # === 过滤 ===
        self.card_filter = Card(self.inner, theme, "过滤", f"{len(m.people)} 人")
        self.card_filter.pack(fill=tk.X, **pad)
        body = self.card_filter.body

        row = tk.Frame(body, bg=theme.bg_card)
        row.pack(fill=tk.X)
        self.var_search = tk.StringVar()
        self.entry_search = input_box(row, theme, self.var_search)
        self.entry_search.pack(fill=tk.X, ipady=3)
        attach_placeholder(self.entry_search, theme, "姓名 / 尊号 / 封国…")
        self.entry_search.bind(
            "<Return>",
            lambda e: m.do_search(getattr(self.entry_search, "real_value",
                                          self.var_search.get)()))

        self.var_hist = tk.StringVar(value="全部")
        self.var_tier = tk.StringVar(value="全部")
        self.var_state = tk.StringVar(value="全部")
        self.filter_combos = {}
        for key, label, var in (("hist", "史实", self.var_hist),
                                ("tier", "爵位", self.var_tier),
                                ("state", "封国", self.var_state)):
            r = tk.Frame(body, bg=theme.bg_card)
            r.pack(fill=tk.X, pady=(5, 0))
            tk.Label(r, text=label, bg=theme.bg_card, fg=theme.text_2, width=4, anchor="w",
                     font=(theme.font_ui_fallback, theme.fs_body)).pack(side=tk.LEFT)
            cb = combo_box(r, theme, values=["全部"], textvariable=var, width=10)
            cb.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0), ipady=1)
            cb.bind("<<ComboboxSelected>>", lambda e: m.apply_filters())
            self.filter_combos[key] = cb

        # ★ 2026-09-27 使用者要求：「定位人物」要跟左边「隐藏非史」等**同款格式、
        #   严格平行**，六格形成「两派三列对称」的格局 —— 于是把两行合成
        #   **一个 ChipRow 的 3 列等宽网格**（2 行 × 3 列；`uniform` 列是**父容器
        #   级**的，只有同一个 ChipRow 里才能真正逐列对齐，两个独立 ChipRow
        #   各排各的会歪）。
        #   · 旧名 `chips` / `chips_focus` 保留为**同一实例的别名** ⇒ main.py 里
        #     那五处 `set_state` 调用点一个都不用改；
        #   · 右下第 6 格留空（`("__locate__", None)` 占位），由「定位人物」按钮
        #     grid 进去 —— 它是**命令**（点了居中+闪圈）不是开关，进 items 会被
        #     当成 toggle 翻转状态。
        self.chips = ChipRow(body, theme,
                             items=[("branch", "当前宗支"),
                                    ("nohist", "隐藏非史"),
                                    ("dead", "隐藏逝者"),
                                    ("enrolled", "仅显入谱"),
                                    ("focus", "仅显所选"),
                                    ("__locate__", None)],   # 占位：右下格
                             command=m.on_chip_toggle, size=10, pad=7, grid_cols=3)
        self.chips.pack(fill=tk.X, pady=(5, 0))
        self.chips_focus = self.chips          # 兼容旧引用（同一实例）
        # 同款胶囊外观（kind="locate"：底色/hover 照未选中胶囊）+ 粗体红字。
        # ★ 2026-09-28 使用者指出「上下字与字要对齐」——两个要点：
        #   ① 胶囊在 grid 模式下是**左对齐**（`anchor="w"`），按钮默认是居中
        #      ⇒ 必须 `anchor="w"`，否则第三列上下两格文字不齐；
        #   ② 胶囊文字恒带 **2 个字符前缀**（选中「✓ 」/ 未选中两空格，宽度不跳），
        #      按钮要跟它对齐就得补同样两个空格。
        self.locate_btn = FlatButton(self.chips, theme, text="  定位人物",
                                     command=m.locate_person, kind="locate",
                                     size=10, padx=7, vpady=3)
        self.locate_btn.configure(anchor="w")
        self.locate_btn.grid(row=1, column=2, sticky="ew", padx=3, pady=(0, 6))
        hover_tip(self.chips,
                  "当前宗支：只画选中人物所在宗支。\n"
                  "隐藏非史：**隐藏全部非史实人物**（取消勾选即全部恢复）。\n"
                  "隐藏逝者：隐藏已故人物（祖孙之间唯一在世的桥接节点会保留）。\n"
                  "仅显入谱：只画家谱里「点过入谱 / 加入族谱」的人（默认勾选）。\n"
                  "仅显所选：只画右键「选定」的人及其男性后裔（可多选）。")

        # === 人物信息 ===
        self.card_info = Card(self.inner, theme, "人物信息")
        self.card_info.pack(fill=tk.X, **pad)
        body = self.card_info.body

        self.var_name = tk.StringVar()
        self.entry_name = self._row(body, "姓名", lambda p: input_box(p, theme, self.var_name))

        r = tk.Frame(body, bg=theme.bg_card)
        r.pack(fill=tk.X, pady=(3, 0))
        tk.Label(r, text="性别", bg=theme.bg_card, fg=theme.text_2, width=4, anchor="w",
                 font=(theme.font_ui_fallback, theme.fs_body)).pack(side=tk.LEFT)
        self.var_gender = tk.StringVar(value="男")
        RadioRow(r, theme, self.var_gender, [("男", "男"), ("女", "女")],
                 command=m.on_gender_change).pack(side=tk.LEFT, padx=(8, 0))

        r = tk.Frame(body, bg=theme.bg_card)
        r.pack(fill=tk.X, pady=(3, 0))
        tk.Label(r, text="代数", bg=theme.bg_card, fg=theme.text_2, width=4, anchor="w",
                 font=(theme.font_ui_fallback, theme.fs_body)).pack(side=tk.LEFT)
        self.var_gen = tk.StringVar()
        self.combo_gen = combo_box(r, theme, values=[str(i) for i in range(1, 101)],
                                   textvariable=self.var_gen, width=5)
        self.combo_gen.pack(side=tk.LEFT, padx=(8, 10), ipady=1)
        tk.Label(r, text="排行", bg=theme.bg_card, fg=theme.text_2,
                 font=(theme.font_ui_fallback, theme.fs_body)).pack(side=tk.LEFT)
        self.var_rank = tk.StringVar()
        self.combo_rank = combo_box(r, theme, values=[""] + [str(i) for i in range(1, 101)],
                                    textvariable=self.var_rank, width=5)
        self.combo_rank.pack(side=tk.LEFT, padx=(8, 0), ipady=1)

        r = tk.Frame(body, bg=theme.bg_card)
        r.pack(fill=tk.X, pady=(3, 0))
        tk.Label(r, text="史实", bg=theme.bg_card, fg=theme.text_2, width=4, anchor="w",
                 font=(theme.font_ui_fallback, theme.fs_body)).pack(side=tk.LEFT)
        self.var_hist_person = tk.StringVar(value="否")
        RadioRow(r, theme, self.var_hist_person, [("是", "是"), ("否", "否")],
                 command=m.on_historical_change).pack(side=tk.LEFT, padx=(8, 0))

        r = tk.Frame(body, bg=theme.bg_card)
        r.pack(fill=tk.X, pady=(3, 0))
        tk.Label(r, text="神祖", bg=theme.bg_card, fg=theme.text_2, width=4, anchor="w",
                 font=(theme.font_ui_fallback, theme.fs_body)).pack(side=tk.LEFT)
        self.var_divine = tk.StringVar(value="否")
        RadioRow(r, theme, self.var_divine, [("是", "是"), ("否", "否")],
                 command=m.on_divine_change).pack(side=tk.LEFT, padx=(8, 0))

        self.var_note = tk.StringVar()
        self.entry_note = self._row(body, "尊号", lambda p: input_box(p, theme, self.var_note))

        # ★ 2026-09-23 生卒年：原 `width=6`（约 42px）连「-373,9,0」都放不下，
        #   数字被裁在框外；改成 `pack(fill=X, expand=True)` 平分剩余宽度后
        #   又**生年框过长**（使用者反馈「你怎么把生年的框弄那么长」）。
        #   现在改 grid 两列等宽：`uniform="bd"` 保证生年框与卒年框**同宽**，
        #   末列 `padx=(8, 0)` 使**卒年框右沿 = 尊号框右沿**（同一条竖线）。
        #   ⚠️ 必须给 `width=6` 兜住请求宽度：Entry 缺省宽 20 字，两框请求宽度
        #   加起来超出侧栏可用宽，pack/grid 都会把后面的控件裁没（实测卒年框
        #   整个消失，只剩标签）。给了小请求宽度，多出来的宽度由 weight 均分。
        r = tk.Frame(body, bg=theme.bg_card)
        r.pack(fill=tk.X, pady=(3, 0))
        r.columnconfigure(1, weight=1, uniform="bd")
        r.columnconfigure(3, weight=1, uniform="bd")
        tk.Label(r, text="生年", bg=theme.bg_card, fg=theme.text_2, width=4,
                 anchor="w", font=(theme.font_ui_fallback, theme.fs_body)).grid(
                     row=0, column=0, sticky="w")
        self.var_birth = tk.StringVar()
        input_box(r, theme, self.var_birth, width=6).grid(row=0, column=1, sticky="ew",
                                                          padx=(8, 0), ipady=1)
        # 卒年标签与「代数 / 排行」那行的第二个标签同款（自然宽 + 左 10 间距），
        # 这样两框的左内距一致（都是 8）→ **框宽严格相等**，卒年框右沿又正好
        # 落在 r 的右沿（= 尊号框右沿）。
        tk.Label(r, text="卒年", bg=theme.bg_card, fg=theme.text_2, anchor="w",
                 font=(theme.font_ui_fallback, theme.fs_body)).grid(
                     row=0, column=2, sticky="w", padx=(8, 0))
        self.var_death = tk.StringVar()
        input_box(r, theme, self.var_death, width=6).grid(row=0, column=3, sticky="ew",
                                                          padx=(8, 0), ipady=1)

        # === 关系 ===
        self.card_rel = Card(self.inner, theme, "关系")
        self.card_rel.pack(fill=tk.X, **pad)
        body = self.card_rel.body
        self.var_father = tk.StringVar()
        self.combo_father = self._combo_row(body, "父亲", self.var_father)
        self.var_mother = tk.StringVar()
        self.combo_mother = self._combo_row(body, "母亲", self.var_mother)
        self.var_spouse = tk.StringVar()
        r = tk.Frame(body, bg=theme.bg_card)
        r.pack(fill=tk.X, pady=(3, 0))
        tk.Label(r, text="配偶", bg=theme.bg_card, fg=theme.text_2, width=4, anchor="w",
                 font=(theme.font_ui_fallback, theme.fs_body)).pack(side=tk.LEFT)
        self.combo_spouse = combo_box(r, theme, textvariable=self.var_spouse, width=10)
        self.combo_spouse.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0), ipady=1)
        FlatButton(r, theme, text="×", command=m.remove_spouse, kind="default",
                   padx=6).pack(side=tk.LEFT, padx=(4, 0))

        # === 爵位封国 ===
        self.card_tier = Card(self.inner, theme, "爵位封国")
        self.card_tier.pack(fill=tk.X, **pad)
        body = self.card_tier.body
        # ★ 2026-09-23 对齐精修：四格合并进**同一个 grid**，四列宽度钉死。
        #   原先上下两行是两个独立 Frame 各自 pack，而 ttk.Combobox 比 Entry
        #   宽出一个下拉箭头 —— 同样 width=4，像素宽并不相等，于是第二列
        #   起点对不上（使用者反馈「下面的两个跟上面两个没有对齐」）。
        #   现在：标签列 / 框列各自定宽，框包一层定宽容器（Combobox 与 Entry
        #   字符宽算法不同，只有包容器才能让两类控件像素宽真正一致）。
        g = tk.Frame(body, bg=theme.bg_card)
        g.pack(fill=tk.X)
        # ★ 2026-09-26 二修：minsize 随 DPI 换算，且两个「框列」给 weight=1
        #   （holder 改 sticky="ew"）—— 原来四列全是写死的逻辑像素（合计约 262px），
        #   侧栏被 DPI 拉宽到 504 后右半就空了（使用者报「右边成空白」）。
        #   现在框列平分剩余宽度：任何缩放、任何侧栏宽都左右顶满、两列等宽对称。
        LBL_W = _dpi.px(int(theme.fs_body * 4.8))   # 容得下最长的「封国 / 君序」
        BOX_W = _dpi.px(74)
        BOX_H = theme.ctrl_h - 6
        for _c, _w in ((0, LBL_W), (1, BOX_W), (2, LBL_W), (3, BOX_W)):
            g.columnconfigure(_c, minsize=_w)
        g.columnconfigure(1, weight=1)
        g.columnconfigure(3, weight=1)

        def _tier_lbl(row, col, text):
            # ★ 2026-09-28 全项目整理（第 3 批，铁律①「尽量汉字左对齐」）：
            #   侧栏各卡的标签原来是**一半右对齐**（`_row` / `_combo_row` / 内联
            #   那几处 `anchor` 取 `e`）、**一半左对齐**（这里），而且这里还**未定宽**
            #   ⇒ 同栏内值列起点参差。现在侧栏标签**统一** `width=4 + anchor="w"`：
            #   一条左沿线、值列起点整齐（"爵位 / 封国 / 祖序" 左沿与
            #   "姓名 / 性别 / 代数" 完全同一条线）。
            tk.Label(g, text=text, bg=theme.bg_card, fg=theme.text_2,
                     width=4, anchor="w",
                     font=(theme.font_ui_fallback, theme.fs_body)
                     ).grid(row=row, column=col, sticky="w",
                            pady=(0 if row == 0 else 4, 0))

        def _tier_box(row, col):
            holder = tk.Frame(g, bg=theme.bg_card, width=BOX_W, height=BOX_H)
            holder.grid(row=row, column=col, sticky="ew",
                        pady=(0 if row == 0 else 4, 0))
            # 子控件是 pack 放的 → 用 pack_propagate 锁尺寸（见生卒年处的说明）
            holder.pack_propagate(False)
            return holder

        _tier_lbl(0, 0, "爵位")
        self.var_tier_person = tk.StringVar()
        self.combo_tier = combo_box(_tier_box(0, 1), theme,
                                    values=["", "无", "卿", "子", "伯", "侯", "公", "王", "帝"],
                                    textvariable=self.var_tier_person, width=4)
        self.combo_tier.pack(fill=tk.BOTH, expand=True)
        self.combo_tier.bind("<<ComboboxSelected>>", lambda e: m.on_tier_change())

        _tier_lbl(0, 2, "封国")
        self.var_state_person = tk.StringVar()
        input_box(_tier_box(0, 3), theme, self.var_state_person, width=6).pack(
            fill=tk.BOTH, expand=True)

        # ★ 2026-09-28 使用者裁定：这个字段的显示名从「封国代数」改为「**君序**」
        #   （`fief_gen` 字段本身不动 —— 只改界面文案）。
        _tier_lbl(1, 0, "君序")
        self.var_fief_gen = tk.StringVar()
        input_box(_tier_box(1, 1), theme, self.var_fief_gen, width=4).pack(
            fill=tk.BOTH, expand=True)

        _tier_lbl(1, 2, "祖序")
        self.var_root_sort = tk.StringVar()
        self.combo_root_sort = combo_box(_tier_box(1, 3), theme,
                                         values=[""] + [str(i) for i in range(1, 101)],
                                         textvariable=self.var_root_sort, width=4)
        self.combo_root_sort.pack(fill=tk.BOTH, expand=True)
        self.combo_root_sort.bind("<<ComboboxSelected>>", lambda e: m.on_root_sort_change())

        # === 操作（常驻底部，不随滚动条滚走）===
        self.card_ops = Card(self.footer, theme, "操作")
        self.card_ops.pack(fill=tk.X, padx=8, pady=(6, 8))
        grid = tk.Frame(self.card_ops.body, bg=theme.bg_card)
        grid.pack(fill=tk.X)
        specs = [("添加始祖", m.open_add_ancestor, "default"),
                 ("添加子嗣", m.open_add_child, "default"),
                 ("保存修改", m.save_modification, "primary"),
                 ("删除选中", m.delete_selected, "danger")]
        for i, (text, cmd, kind) in enumerate(specs):
            btn = FlatButton(grid, theme, text=text, command=cmd, kind=kind, padx=6)
            btn.grid(row=i // 2, column=i % 2, sticky="ew", padx=2, pady=2, ipady=4)
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        # M0 查档桥：带存档编号跳档案阅览器（人物没有 code 字段时按钮会给提示）
        # 括号里的说明挪到悬停（使用者 2026-09-21 要求）
        _v = FlatButton(self.card_ops.body, theme, text="⌖ 查档",
                        command=m.open_viewer, kind="default", padx=6)
        _v.pack(fill=tk.X, pady=(6, 0), ipady=4)
        hover_tip(_v, "跳到「人物」页并定位到这个人（按存档编号查）。\n"
                      "人物没有编号时（纯手写）按钮会提示查不到。")

    def set_focus_btn(self, on):
        """同步「仅显所选」chip 的选中态（勾选后变主色 ✓，再点取消）。"""
        try:
            self.chips_focus.set_state("focus", bool(on))
        except Exception:
            pass

    # ---------------------------------------------------------------- 小工具
    def _row(self, body, label, builder):
        """一行：**左对齐**标签 + 由 builder 在行内创建的控件。

        ★ 2026-09-28 全项目整理（第 3 批）：标签原为右对齐（`anchor` 取 `e`），
          与侧栏另一半卡片的左对齐标签**两套对齐线** —— 统一成左对齐 + 定宽 4 字。

        builder 必须用传入的父控件创建控件——Tk 的 pack(in_=...) 跨父容器会出问题。
        """
        r = tk.Frame(body, bg=self.theme.bg_card)
        r.pack(fill=tk.X, pady=(3, 0))
        tk.Label(r, text=label, bg=self.theme.bg_card, fg=self.theme.text_2, width=4,
                 anchor="w", font=(self.theme.font_ui_fallback, self.theme.fs_body)).pack(side=tk.LEFT)
        widget = builder(r)
        widget.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0), ipady=1)
        return widget

    def _combo_row(self, body, label, var):
        r = tk.Frame(body, bg=self.theme.bg_card)
        r.pack(fill=tk.X, pady=(3, 0))
        tk.Label(r, text=label, bg=self.theme.bg_card, fg=self.theme.text_2, width=4,
                 anchor="w", font=(self.theme.font_ui_fallback, self.theme.fs_body)).pack(side=tk.LEFT)
        cb = combo_box(r, self.theme, textvariable=var, width=10)
        cb.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0), ipady=1)
        return cb

    # ---------------------------------------------------------------- 刷新
    def refresh_filter_choices(self, tiers, states):
        """刷新史实/爵位/封国下拉的可选值。"""
        self.filter_combos["hist"].configure(values=["全部", "是", "否"])
        self.filter_combos["tier"].configure(values=["全部"] + list(tiers))
        self.filter_combos["state"].configure(values=["全部"] + list(states))

    def current_filters(self):
        """(搜索词, 史实, 爵位, 封国, 只看当前宗支, 隐藏非史实后裔, 隐藏已故)

        搜索框带占位提示，占位文字会被写进 StringVar，必须走 real_value() 取值。
        """
        real = getattr(self.entry_search, "real_value", None)
        search = (real() if callable(real) else self.var_search.get()).strip()
        return (search, self.var_hist.get(), self.var_tier.get(),
                self.var_state.get(), self.chips._state.get("branch", False),
                self.chips._state.get("nohist", False),
                self.chips._state.get("dead", False))

    def fill_person(self, info, name):
        """把选中人物的数据灌进侧栏。"""
        self.var_name.set(name)
        self.var_gender.set(info.get("gender", "男"))
        self.var_gen.set(str(info.get("generation", "")) if info.get("generation") else "")
        rank = info.get("rank", 0)
        self.var_rank.set(str(rank) if rank else "")
        self.var_hist_person.set(info.get("historical", "否"))
        self.var_divine.set(info.get("divine", "否"))
        self.var_note.set(info.get("note", ""))
        self.var_birth.set(info.get("birth", ""))
        self.var_death.set(info.get("death", ""))
        self.var_father.set(info.get("father", ""))
        self.var_mother.set(info.get("mother", ""))
        spouses = info.get("spouses", [])
        self.var_spouse.set("、".join(spouses) if spouses else "")
        self.var_tier_person.set(info.get("fief_title", ""))
        self.var_state_person.set(info.get("state_name", ""))
        fg = info.get("fief_gen", 0)
        self.var_fief_gen.set(str(fg) if fg else "")
        rs = info.get("root_sort", 0)
        self.var_root_sort.set(str(rs) if rs else "")

    def clear_person(self):
        for var in (self.var_name, self.var_gen, self.var_rank, self.var_note,
                    self.var_birth, self.var_death, self.var_father, self.var_mother,
                    self.var_spouse, self.var_tier_person, self.var_state_person,
                    self.var_fief_gen, self.var_root_sort):
            var.set("")
        self.var_gender.set("男")
        self.var_hist_person.set("否")
        self.var_divine.set("否")
