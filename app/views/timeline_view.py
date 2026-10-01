# -*- coding: utf-8 -*-
"""时间轴视图 —— 纵轴 = 绝对年份（生年），横轴 = 树状发散。

与主树并列的第二个视图（顶栏 `[树形 | 时间轴 | 表格]`），**不替换主树**：
主树的纵轴是「谱系代」，实测同代人平均跨 443 年，天生不可能让生卒年与纵轴对应。

设计要点
--------
· 卡片 34×17px，**上沿 = 出生年**；厚度固定，不代表寿命（已定稿，不画寿命线）
· x 沿用 v1 `layout.py` 的排法：父亲居中于孩子之上、后代向两侧散开
· 连线一律画在**卡片之下**，所以即使压到卡也只是被挡住，不会糊在文字上
· **视口裁剪**：只画看得见的那几十~几百张卡（20000×28000 的全量画布也秒开）
· 左侧朝代带 + 顶部全览缩略轴，缩略轴上绿框 = 当前视口
"""
import tkinter as tk
import tkinter.font as tkfont
from tkinter import Scrollbar

from .. import dpi as _dpi
from .. import jue
from .. import timeline as T
from .. import saveload as S
from ..labels import split_dup
from ..widgets.popcard import build_popcard

RAIL_W = _dpi.px(88)              # 左侧朝代带宽度
# ★ 2026-09-26 使用者要求：全览缩略条从「顶部横向」改为「左沿纵向」——
#   原话「画布上沿横向的可滑动的全部时代，其实应该放画布左沿可拖动，因为上下
#   拖动才是时间变动」。时间轴的纵轴才是年份，条子竖过来与画布同向、
#   视口框一眼对得上。`MINI_W` = 条宽；`MINI_LABEL_H` = 顶端「全览」标签的高度。
MINI_W = _dpi.px(38)
MINI_LABEL_H = _dpi.px(30)
MINI_TICK_YEARS = (-2600, -2070, -1600, -1046, -475, -221, 1, 1000)
GRID_STEPS = (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000)
# 竖排铭牌在这个比例尺以上，连线才能全部绕开卡片（实测 4.4 起直斜线为 0）
V_PLATE_MIN_SCALE = 4.4 * _dpi.SCALE


def _nice_step(min_px_per_label: float, scale: float) -> int:
    """挑一个让刻度之间至少隔 min_px_per_label 像素的「整数年」步长。"""
    for s in GRID_STEPS:
        if s * scale >= min_px_per_label:
            return s
    return GRID_STEPS[-1]


def _fmt_year(y: int) -> str:
    return f"前 {-y}" if y < 0 else f"公元 {y}"


def _fmt_short(y: int) -> str:
    return f"前{-y}" if y < 0 else f"{y}"


def _era_label(name: str) -> str:
    """朝代带上的名字：单字朝代补「朝」字（秦朝/汉朝/夏朝/商朝）。

    ★ 2026-09-23 使用者要求「显示秦朝 漢朝」—— 单字（秦/汉/夏/商）后面加「朝」，
      多字名（西周/春秋/战国…）本身已可读，不再加。
    """
    return name + "朝" if len(name) == 1 else name


class TimelineView:
    """parent: 容器 Frame; master: App 控制器（提供 people / cfg / 回调）。"""

    def __init__(self, parent, theme, master):
        self.master = master
        self.theme = theme

        self.lay = None
        self.scale = T.SCALE_DEFAULT
        # 铭牌样式：'h' 横排（名字一行读完）/ 'v' 竖排（一个字一行，省横向）
        # ★ 2026-09-22 使用者要求「时间轴的铭牌默认为竖排」—— 默认值 h → v。
        #   竖排省横向，同一屏能放下更多人，也更容易避开连线（见 4.4 px/年 那条注释）。
        self.plate = master.cfg.get("timeline_plate", "v")
        if self.plate not in T.PLATES:
            self.plate = "v"
        self.selected = None
        self._zoom_job = None
        self._pending_anchor = (None, None)
        self._user_zoomed = False
        self._framed = False          # 有没有把镜头对到内容上（用户一动就不再自动对）
        self._span = 0
        self._anchor = None           # Ctrl+滚轮缩放时钉住的「光标下的年份与世界 x」
        self._cache = {}              # 比例尺 → 布局（来回缩放不用重算）
        self._state_boxes = []        # ★ 2026-09-23 世系框（rerender 里算好，redraw 里画）
        self._pop_widget = None       # 小传浮卡的内嵌 Frame
        self._pop_at = None           # 浮卡在画布坐标里的位置
        self._press = (0, 0, 0.0, 0.0)
        self._visible_count = 0
        self.range_start, self.range_end = T.YEAR_START_DEFAULT, T.YEAR_END_DEFAULT

        self._fonts_cache = {}        # 字号 → tkfont.Font（量宽度用）
        self._size_cache = {}         # 人名 → 该人名的弹性字号
        self.font_rail = tkfont.Font(family=theme.font_gen, size=9, weight="bold")
        self.font_tick = tkfont.Font(family=theme.font_ui_fallback, size=7)
        self.font_mini = tkfont.Font(family=theme.font_ui_fallback, size=7)

        outer = tk.Frame(parent, bg=theme.bg_canvas)
        outer.pack(fill=tk.BOTH, expand=True)

        # ---- 左沿「全览」纵向缩略条 + 朝代带 + 主画布 ----
        body = tk.Frame(outer, bg=theme.bg_canvas)
        body.pack(fill=tk.BOTH, expand=True)

        # ★ 2026-09-26：全览条竖过来放**最左**（使用者要求，理由见 MINI_W 注释）
        self.mini = tk.Canvas(body, bg=theme.bg_card, width=MINI_W,
                              highlightthickness=0, bd=0, cursor="hand2")
        self.mini.pack(side=tk.LEFT, fill=tk.Y)
        self.mini.bind("<Button-1>", self._on_mini_click)
        self.mini.bind("<B1-Motion>", self._on_mini_drag)
        self.mini.bind("<Configure>", lambda e: self._draw_mini())

        # ★ 2026-09-26 使用者要求：朝代带宽度 = 「前2350」实测宽 + 1 个汉字，
        #   文字居中 —— 比写死的 RAIL_W 窄，把宽度还给画布。
        self.rail_w = max(56, int(self.font_tick.measure("前2350")
                                 + self.font_tick.measure("字") + 10))
        self.rail = tk.Canvas(body, bg=theme.bg_card, width=self.rail_w,
                              highlightthickness=0, bd=0)
        self.rail.pack(side=tk.LEFT, fill=tk.Y)
        # 「全览」标签横跨「全览条 + 朝代带」双栏（点它 = 全览适配）
        self.rail.bind("<Button-1>", self._on_rail_click)

        self.canvas = tk.Canvas(body, bg=theme.bg_canvas, highlightthickness=0,
                                bd=0, cursor="hand2")
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.vbar = Scrollbar(body, orient=tk.VERTICAL, command=self._yview,
                              bg=theme.border_2, troughcolor=theme.bg_panel,
                              activebackground=theme.accent, highlightthickness=0,
                              bd=0, width=theme.scrollbar_w, relief=tk.FLAT)
        self.vbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.hbar = Scrollbar(outer, orient=tk.HORIZONTAL, command=self._xview,
                              bg=theme.border_2, troughcolor=theme.bg_panel,
                              activebackground=theme.accent, highlightthickness=0,
                              bd=0, relief=tk.FLAT)
        self.hbar.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.configure(yscrollcommand=self._on_yscroll,
                              xscrollcommand=self._on_xscroll)

        self.canvas.bind("<Configure>", self._on_configure)
        self.canvas.bind("<ButtonPress-1>", self._on_click)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<Double-Button-1>", self._on_double)
        self.canvas.bind("<ButtonPress-3>", self._on_right_click)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Shift-MouseWheel>", self._on_wheel_shift)
        self.canvas.bind("<Control-MouseWheel>", self._on_wheel_ctrl)

    # ================================================================ 尺寸
    def _game_year(self):
        """本档「走到哪一年」—— 时代全览的右端就停在这里（见 `timeline.year_bounds`）。

        优先问**绑定的实录槽**（存档自己记的当前年份）；问不到就返回 None，
        由 `year_bounds` 退回「最晚生年 + 余量」。取不到不该报错 —— 手写谱牒
        没绑存档时这条路径是常态。
        """
        slot = getattr(self.master, "record_slot", None)
        if slot is None:
            return None
        try:
            return S.game_year(slot)
        except Exception:
            return None

    def _viewport(self):
        return max(self.canvas.winfo_width(), 1), max(self.canvas.winfo_height(), 1)

    @property
    def _ready(self):
        return self.lay is not None and self.lay.positions

    # ================================================================ 布局
    def rerender(self, keep_scale=True, cache_ok=False):
        """重算布局。缩放变化后调它；平移不必重算。

        `cache_ok`：缩放时允许命中「同一比例尺上次算过的布局」—— 来回缩放就不用反复重算。
        改数据（`_refresh_all`）时必须传 False，否则会拿到过期布局。
        """
        people = self.master.people
        # ★ 2026-09-23 手动「选定」的人穿透所有过滤层（与主树同规）—— 否则
        #   选定已故者或未入谱者时画布无变化，使用者会以为「选定点了没反应」
        _pin = set(getattr(self.master, "focused", ()) or ())
        # 画布默认只画点名过的人（入谱 / 加入族谱）
        if getattr(self.master, "enrolled_only", True):
            keep_enr = set(self.master.enrolled_set()) | _pin
            people = {n: v for n, v in people.items() if n in keep_enr}
        if getattr(self.master, "hide_dead", False):
            people = {n: v for n, v in people.items()
                      if not (v or {}).get("death") or n in _pin}
        # ★ 2026-09-24 侧栏「隐藏非史」全局开关（与主树同规：勾上隐藏全部
        #   非史实人物；手动「选定」的人照旧穿透）
        if getattr(self.master, "hide_nohist_all", False):
            people = {n: v for n, v in people.items()
                      if (v or {}).get("historical") == "是" or n in _pin}
        if getattr(self.master, "focus_only", False):
            foc = set(getattr(self.master, "focused", ()))
            if foc:
                # ★ 2026-09-23 与主树同规：只跟 father 边（纯父系谱系，不含女儿支）
                child_map = {n: [] for n in people}
                for n in people:
                    d = people[n].get("father", "") or ""
                    if d in child_map:
                        child_map[d].append(n)
                keep = set()
                q = list(foc)
                while q:
                    cur = q.pop(0)
                    if cur in keep or cur not in people:
                        continue
                    keep.add(cur)
                    for c in child_map.get(cur, []):
                        if c not in keep:
                            q.append(c)
                for n in list(keep):
                    for s in (people[n].get("spouses") or []):
                        if s in people:
                            keep.add(s)
                people = {n: v for n, v in people.items() if n in keep}
            else:
                people = {}
        if not cache_ok:
            self._cache.clear()
            self._size_cache.clear()      # 换档 / 换铭牌 → 弹性字号要重算
        years = [y for y in (T.birth_year(v) for v in people.values()) if y is not None]
        self._span = (max(years) - min(years)) if years else 0
        refit = False
        if not keep_scale or not self._user_zoomed:
            _, vh = self._viewport()
            new = T.initial_scale(self._span, max(vh - 30, 200))
            refit = abs(new - self.scale) > 1e-6 or self.lay is None
            self.scale = new
        if refit:
            self._framed = False
        self.range_start, self.range_end = T.year_bounds(years, now=self._game_year())

        key = round(self.scale, 4)
        cached = self._cache.get(key)
        if cached is not None:
            self.lay = cached
        else:
            self.lay = T.compute(people, scale=self.scale, width_of=self._card_w,
                                 card_h=T.PLATES[self.plate][0])
            if len(self._cache) >= 3:
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = self.lay

        w = max(self.lay.width, 10)
        h = max(self.lay.height, 10)
        # ★ 2026-09-23 使用者要求「过滤后空白的画布都隐藏」：内容比视口矮时
        #   自动放大比例把它铺满（hide_dead / 仅显所选后只剩一小段年，视口
        #   里大半是空白画布，就是这个症状）。用户手动缩放过就不动（尊重手调）。
        if not self._user_zoomed and years:
            _, vh = self._viewport()
            if h < vh - 20:
                span2 = max(self._span, 1)
                fit = T.clamp_scale((vh - 20) / span2)
                if fit > self.scale * 1.02:
                    self.scale = fit
                    self._cache.clear()
                    self._size_cache.clear()
                    self.lay = T.compute(people, scale=self.scale,
                                         width_of=self._card_w,
                                         card_h=T.PLATES[self.plate][0])
                    self._cache[round(self.scale, 4)] = self.lay
                    w = max(self.lay.width, 10)
                    h = max(self.lay.height, 10)
        self.canvas.configure(scrollregion=(0, 0, w, h))
        self.rail.configure(scrollregion=(0, 0, self.rail_w, h))
        # ★ 2026-09-23 世系框（「X世系」大圈）：口径与主树一致 —— 只认
        #   lineage_name（宗庙世系 = 君主家族），老档无此字段回退 state_name。
        #   ★ 必须传 `self.master.people`（全量）而不是上面过滤过的局部 `people`：
        #   框的成员由 `positions`（可见的人）决定，而 lineage_name 要能从全量里查到。
        #   过滤后的 people 只剩在世者，而在世者多半没有宗庙世系（世系记在历代
        #   君主身上）→ 一个框都画不出来（实测框数 = 0，使用者反馈「时间家谱
        #   也要有 X 国世系」）。代际树本来就是这个口径，这里对齐它。
        try:
            from .. import layout as L
            from .. import jue as jue_mod
            # ★ 这里必须写 `self.theme` —— rerender 作用域内**没有**局部 `theme`
            #   （只有 redraw/_draw_mini 里才有），原来写 `theme.tier` 直接
            #   NameError，又被下面的 `except Exception` 静静吞掉，于是
            #   时间轴永远 0 个世系框（这是「时间家谱看不到 X 国世系」的真凶）。
            # ★ 2026-09-26（M1）：框色接 **tier_of** 上色爵称（主树八十二批已接，
            #   时间轴漏了）—— 与铭牌同一口径，一次算好全谱映射再传入。
            jue_mod.install_from_save(getattr(self.master, "current_save", ""))
            tier_map = jue_mod.tier_colors_for(self.master.people)
            self._tier_map = tier_map
            self._state_boxes = L.state_group_boxes_timeline(
                self.master.people, self.lay.positions, self.lay.widths,
                self.lay.card_h, self.theme.tier,
                # ★ 2026-09-23 与代际同规：退让阈值要用**真字宽**（9pt 隶书约 13px），
                #   原来写死的 8.0 偏小 → 框明明放不下整题也硬写全称。
                char_w=self.font_rail.measure("世"), tier_of=tier_map)
        except Exception:
            self._state_boxes = []
        self._draw_mini()
        self.redraw()          # 镜头定位不在这里做 —— 见 _on_configure
        self._draw_popcard()   # 重排后浮卡要跟着卡片挪位置
        return self.lay

    def _scroll_to_content(self):
        """把视口对到「人最密的那一屏」。

        不能只按最早出生的人定位：时间轴全宽两万像素、视口只占 5%，而人往往扎堆在中段
        （实测秦末档最早的人生在前 2580，那一段是空的，初始会停在「本屏 0 人」）。
        """
        vw, vh = self._viewport()
        if not self._ready or vw < 50 or vh < 50:
            return                                # 画布还没真正布局好，视口算出来是错的
        self._framed = True
        items = sorted(self.lay.positions, key=lambda n: (self.lay.years[n], n))
        ys = [self.lay.years[n] for n in items]
        win = max(vh / self.scale, 1.0)           # 一屏覆盖多少年
        median = ys[len(ys) // 2]
        best_i = best_n = 0
        best_key = None
        j = 0
        for i in range(len(ys)):
            j = max(j, i)
            while j < len(ys) and ys[j] <= ys[i] + win:
                j += 1
            n = j - i
            # 并列时取离「全体生年中位」近的那一屏 —— 秦末档有好几个年份都挤了 22 人，
            # 随便取最早的那个会落到一个没什么内容的角落上。
            key = (n, -abs((ys[i] + ys[j - 1]) / 2.0 - median))
            if best_key is None or key > best_key:
                best_key, best_i, best_n = key, i, n
        window = items[best_i:best_i + best_n]
        xs = sorted(self.lay.positions[n][0] for n in window)
        mid_x = xs[len(xs) // 2]                  # 这一屏里横向也取中位，别贴边
        pick = min(window, key=lambda n: abs(self.lay.positions[n][0] - mid_x))
        x, y = self.lay.positions[pick]
        total_w = max(self.lay.width, 1)
        total_h = max(self.lay.height, 1)
        self.canvas.xview_moveto(max(0.0, min(1.0, (x - vw / 2) / total_w)))
        self.canvas.yview_moveto(max(0.0, min(1.0, (y - vh / 2) / total_h)))
        self.rail.yview_moveto(self.canvas.yview()[0])
        self.redraw()

    # ------------------------------------------------ 铭牌：弹性字号 + 卡片绘制
    def _fonts(self, size):
        f = self._fonts_cache.get(size)
        if f is None:
            f = tkfont.Font(family=self.theme.font_name, size=size, weight="bold")
            self._fonts_cache[size] = f
        return f

    def _flex_size(self, name):
        """弹性字号：基准 `T.FONT_PT`（15pt，与主树节点一致），装不下就一级级降。

        「框固定、只缩字」—— 和主树 `tree_view._fit` 同一个套路：
          横排：一个字一行地量宽度，超过 `CARD_W_MAX` 就降；
          竖排：一个字一行地摞，`字数 × 行高` 超过卡片高就降。
        """
        if self.plate == "v":
            room = T.PLATES["v"][0] - 2 * T.CARD_PAD_Y
            for s in range(T.FONT_PT, T.FONT_PT_MIN - 1, -1):
                if len(name) * self._fonts(s).metrics("linespace") <= room:
                    return s
            return T.FONT_PT_MIN
        room = T.CARD_W_MAX - T.CARD_PAD_X
        for s in range(T.FONT_PT, T.FONT_PT_MIN - 1, -1):
            if self._fonts(s).measure(name) <= room:
                return s
        return T.FONT_PT_MIN

    def _size_of(self, name):
        s = self._size_cache.get(name)
        if s is None:
            s = self._flex_size(name)
            self._size_cache[name] = s
        return s

    def _card_w(self, name):
        """卡片宽度。竖排 = 名字列宽（贴字，不再给尊号让位）；
        横排 = 名字文字宽 + 极窄内边距。

        ★ 2026-09-22 使用者要求「人物尊号、爵位显示比照族谱也做出来」：
          爵位 = 卡左爵位色条；尊号 = 名字旁小字。
        ★ 2026-09-23 使用者要求「铭牌再窄一些」+「有尊号/谥号放在右侧的框外」：
          尊号/谥号不再计入卡片宽度 —— 宽了只会把卡片撑开，
          现在一律画到右框外（见 `_draw_card`）。竖排名字居中，横排名字贴左。
        """
        info = self.master.people.get(name) or {}
        if self.plate == "v":
            return T.PLATES["v"][1]
        # 重名序数（纯数字）现在是**右上角角标**，只额外占半个字宽，不按整字算
        base_name, dup = split_dup(name)
        size = self._size_of(base_name)
        w = self._fonts(size).measure(base_name) + T.CARD_PAD_X
        if dup:
            w += size * 96.0 / 72.0 * 0.5
        return max(T.PLATES["h"][1], w)

    def _draw_card(self, name, x, y, w):
        c, theme = self.canvas, self.theme
        half = w / 2.0
        ch = self.lay.card_h
        sel = (name == self.selected)
        info = self.master.people.get(name) or {}
        # ★ 2026-09-26：上色用爵称走 app/jue.py 的史观口径（周以前按尊号 /
        #   西周以后按实际爵位（国爵）/ 夏商周天子一律「王」/ 帝色只给上古与秦以后）。
        #   ⚠️ 与主树（tree_view._draw_node）同规：**全谱一次算好**（rerender 里
        #   `self._tier_map = jue.tier_colors_for(...)`），逐卡只查表。
        #   原来这里直接写 `jue.tier_for(...)` 却没 import jue，而且每卡都调
        #   `install_from_save`（会读整本谱牒）—— 结果时间轴一画卡片就
        #   `NameError: name 'jue' is not defined`，画布空白（使用者报「时间家谱
        #   没做」的真凶，2026-09-26 修）。
        tier = (getattr(self, "_tier_map", None) or {}).get(name)
        if tier is None:
            tier = jue.tier_for(info)
        color = theme.tier.get(tier) or theme.tier.get("无", "#8a8a8a")
        # ★ 2026-09-22 使用者要求「已经去世的人物铭牌框里面用灰色阴影」——
        #   判据与表格页完全一致：**谱牒里的卒年字段**（谱牒层没有活人表/已故表可依）。
        #   优先级：选中（主色）> 已故（灰）> 常态（卡片色）。
        # ★ 2026-09-26：全谱声明「不涂已故灰」时不压灰（四处同规，
        #   见 app.storage.hide_dead_shade）
        from .. import storage as _st
        dead = bool(info.get("death")) and not _st.hide_dead_shade(
            getattr(self.master, "current_save", ""))
        # ★ 2026-09-23「选定」高亮（与家谱/表格同一判据、同一紫色）：
        #   集合 = 选定人 + 其全部男性后裔（纯父系谱系，见 app.focus_set）
        focus = name in self.master.focus_set()
        # ★ 2026-09-26 决选 6B/7C（使用者拍板）：
        #   · 6B 已故 = **爵色填底 + 灰字**（不再灰底压爵色）；
        #   · 7C 女性 = **爵色淡底**（调淡保证红字可读）+ 红名不变；
        #   · 真有爵才填（tier 必须是主题爵色表里的键，防「神」类杂称误填）。
        tier_fill = (bool(color) and tier in theme.tier
                     and tier not in ("", "无") and not (sel or focus))
        female = info.get("gender", "") == "女"
        if sel:
            fill = theme.accent_soft
        elif focus:
            fill = theme.focus_bg
        elif dead and tier_fill:
            fill = color
        elif dead:
            fill = theme.bg_dead or theme.bg_card
        elif tier_fill and female:
            fill = self._tint(color)
        elif tier_fill:
            fill = color
        else:
            fill = theme.bg_card
        # ★ 2026-09-28 全项目整理（第 2 批，铁律②「没有任何汉字被遮盖」）：
        #   本函数的矩形与文字原来**一个 tag 都没带**，而时间轴也**没有任何提层
        #   机制** ⇒ 后画的**右邻卡矩形**盖住本卡**卡外右侧的尊号**、下邻卡矩形
        #   盖住**卡下方的封代数字**（这两个字都在卡片之外，最容易被后画的卡吃掉）。
        #   现在分两层：矩形 `platebg`、文字 `platetext`，在批末统一提层。
        _pt = ("platebg", f"p_{name}")
        _tt = ("platetext", f"p_{name}")
        c.create_rectangle(x - half, y, x + half, y + ch,
                           fill=fill,
                           outline=(theme.accent if sel
                                    else (theme.focus_hi if focus else theme.border_2)),
                           width=2 if (sel or focus) else 1, tags=_pt)
        # ★ 2026-09-26 使用者要求：爵位色不再只画**左沿一道竖杠**，改成**四边描边**
        #   （上下左右都带色）。竖排铭牌只有 20px 宽，色框压在内侧会把名字挤没，
        #   所以直接沿卡片外沿画 2px；选中/聚焦时让位给主色边框（不然看不见选中）。
        if color and not tier_fill and not (sel or focus):
            c.create_rectangle(x - half, y, x + half, y + ch,
                               fill="", outline=color, width=2, tags=_pt)
        # 竖排铭牌一个字一行 —— Tk 的 create_text 不支持竖写，用换行手动摞
        # ★ 2026-09-22 重名序数（纯数字）拆出来画成**右上角的小号灰字角标**
        #   （与主树同一套做法）—— 原来它占整整一行，竖排时看着像名字里多了一个字。
        base_name, dup = split_dup(name)
        size = self._size_of(base_name)
        # ★ 2026-09-22 尊号小字（比照族谱）：竖排在名字右侧一列（名字左移让位），
        #   横排贴卡片右缘；女性尊号也标红。
        # ★ 2026-09-23 使用者要求「有尊号/谥号放在右侧的框外」—— 尊号不占卡宽，
        #   竖排名字回中间，横排名字贴左；尊号一律画在右框外侧 2px 起。
        note = info.get("note") or ""
        if self.plate == "v":
            name_x = x
            text = "\n".join(base_name)
        else:
            name_x = x - half + 2
            text = base_name
        # ★ 2026-09-21 使用者要求「女性角色名字在任何地方都标红」——
        #   原来一律 theme.text，时间轴上认不出谁是女性。
        # ★ 2026-09-26 追加（使用者实测截图）：自动黑/白在中等明度的爵色
        #   （绿/紫/青/金棕）上字发糊 —— 填色铭牌**统一白字 + 深色描影**，
        #   浅色底（王金）也靠描影保住轮廓；已故用洗白灰仍算「灰字示亡」。
        name_shadow = None
        if dead and tier_fill:
            name_fg = "#d8d3c6"             # 决选 6B：灰字示亡（描影兜底可读）
            name_shadow = True
        elif female:
            name_fg = theme.spouse          # 决选 7C：女性红名不变（淡底无需影）
        elif tier_fill:
            name_fg = "#ffffff"
            name_shadow = True
        else:
            name_fg = theme.text
        # ★ 2026-09-26 修横牌溢出：竖排居中没错，横排的 name_x 是**左缘**，
        #   却也用 center 锚 —— 半个名字挂到框外去了（使用者报「横牌字溢出」）。
        if name_shadow:
            c.create_text(name_x + 1.5, y + ch / 2.0 + 1.5, text=text,
                          font=self._fonts(size), fill="#2f2a24",
                          anchor="center" if self.plate == "v" else "w",
                          tags=_tt)
        c.create_text(name_x, y + ch / 2.0, text=text,
                      font=self._fonts(size), fill=name_fg,
                      anchor="center" if self.plate == "v" else "w", tags=_tt)
        if note:
            ns = max(7, min(9, size - 3))
            nfg = theme.spouse if info.get("gender", "") == "女" else theme.text_2
            c.create_text(x + half + 2, y + ch / 2.0, text="\n".join(note),
                          font=self._fonts(ns), fill=nfg, anchor="w", tags=_tt)
        if dup:
            self._draw_dup_mark(c, name_x, y + ch / 2.0, base_name, dup, size,
                                vertical=(self.plate == "v"), tags=_tt)
        # ★ 2026-09-22 封代角标（比照族谱节点下的封代数字）
        if info.get("fief_gen", 0) > 0:
            c.create_text(x, y + ch + 7, text=str(info["fief_gen"]),
                          font=self.font_tick, fill=theme.text_2, tags=_tt)

    def _draw_dup_mark(self, c, cx, cy, base_name, dup, name_size, vertical=True,
                       tags=None):
        """重名序数角标：小号**灰**字，贴在名字**最后一个字的右上角**（像幂，同主树）。

        ★ 2026-09-22 使用者：「改成数字右上角角标灰色123吧，像幂一样那种」。
          原来是带圈数字、贴在右下角、跟名字同色。
        竖排：一个字一行，最后一行中心 y = cy + (N-1) × 行高 / 2，右缘 x = cx + 字宽/2。
        横排：一行文字以 (cx, cy) 为中心，右缘 x = cx + 半宽。
        """
        f = self._fonts(name_size)
        size = max(7, int(round(name_size * 0.62)))
        if vertical:
            lf = f.metrics("linespace") / float(name_size)
            n = max(1, len(base_name))
            px = cx + name_size * 96.0 / 72.0 * 0.52
            py = cy + (n - 1) * lf * name_size / 2.0 - name_size * 0.32
        else:
            px = cx + f.measure(base_name) / 2.0 + name_size * 0.18
            py = cy - name_size * 0.34
        c.create_text(px, py, text=dup, font=self._fonts(size),
                      fill=self.theme.text_3, anchor="center", tags=tags)

    @staticmethod
    def _tint(bg_hex, f=0.62):
        """爵色 → 淡底（向白色调 f 比例），给女性红名当底（决选 7C）。"""
        try:
            r = int(bg_hex[1:3], 16); g = int(bg_hex[3:5], 16); b = int(bg_hex[5:7], 16)
        except Exception:
            return bg_hex
        return "#%02x%02x%02x" % (int(r + (255 - r) * f),
                                  int(g + (255 - g) * f),
                                  int(b + (255 - b) * f))

    @staticmethod
    def _contrast_text(bg_hex):
        """底色明暗 → 黑字或白字（填色铭牌上保证名字可读）。"""
        try:
            r = int(bg_hex[1:3], 16); g = int(bg_hex[3:5], 16); b = int(bg_hex[5:7], 16)
        except Exception:
            return None
        return "#1f1f1f" if (r * 299 + g * 587 + b * 114) >= 140000 else "#ffffff"

    @property
    def card_h(self):
        return self.lay.card_h if self.lay is not None else T.PLATES[self.plate][0]

    def export_full(self, path_prefix, on_progress=None, max_side=16000):
        """★ 2026-09-27 v3 时间家谱整块导出：超级大窗 + 左沿朝代带。

        与代际树同法（收侧栏 → 超级大窗 → PrintWindow 一屏全收），
        窗口宽度额外含朝代带，落图时把带子拼在左沿。
        """
        import math
        from PIL import Image
        from app import wincap
        if self.lay is None:
            raise RuntimeError("时间轴还没有布局（先打开一个谱牒）")
        c, rail = self.canvas, self.rail
        top = c.winfo_toplevel()
        total_w = max(1, int(self.lay.width))
        total_h = max(1, int(self.lay.height))
        rail_w = max(rail.winfo_width(), 1)
        saved_geom = top.geometry()
        was_zoomed = (top.state() == "zoomed")
        saved_max = top.wm_maxsize()
        top.wm_maxsize(max_side, max_side)
        try:
            if was_zoomed:
                top.state("normal")
            # ① 收起侧栏（画布顶到窗口左缘），量出新的 rel 偏移
            self.master.export_chrome(True)
            top.update()
            rel_x = c.winfo_rootx() - top.winfo_rootx()
            rel_y = c.winfo_rooty() - top.winfo_rooty()
            # ② 窗口拉成「画布全尺寸 + 边距」的超级大窗（等效虚拟大屏）
            new_w = min(max_side, max(rel_x + rail_w + total_w + 12,
                                      c.winfo_width()))
            new_h = min(max_side, max(rel_y + total_h + 12, c.winfo_height()))
            top.geometry(f"{new_w}x{new_h}+0+0")
            top.update()
            top.update()          # 二次 update：等工具栏收稳再量 rel 偏移
            rel_x = c.winfo_rootx() - top.winfo_rootx()
            rel_y = c.winfo_rooty() - top.winfo_rooty()
            vis_w = max(50, new_w - rel_x)
            vis_h = max(50, new_h - rel_y)
            n_cols = max(1, math.ceil(total_w / vis_w))
            n_rows = max(1, math.ceil(total_h / vis_h))
            files = []
            for ri in range(n_rows):
                for ci in range(n_cols):
                    x0, y0 = ci * vis_w, ri * vis_h
                    if on_progress:
                        on_progress(ri * n_cols + ci + 1)
                    c.xview_moveto(min(x0 / total_w, 1.0))
                    c.yview_moveto(min(y0 / total_h, 1.0))
                    rail.yview_moveto(c.yview()[0])
                    self.redraw()          # 时间轴按视口画卡，滚动后必须重画
                    c.update(); c.update()
                    w_img, h_img, bgra = wincap.capture_widget(
                        c, prefer_printwindow=True)
                    img = Image.frombuffer(
                        "RGBA", (w_img, h_img), bgra, "raw", "BGRA").convert("RGB")
                    vis_w2, vis_h2 = wincap.real_visible_size(
                        img, rel_x, rel_y, vis_w, vis_h)
                    out = img.crop((rel_x, rel_y,
                                    rel_x + min(vis_w2, total_w - x0),
                                    rel_y + min(vis_h2, total_h - y0)))
                    rr_x = rail.winfo_rootx() - top.winfo_rootx()
                    rr_y = rail.winfo_rooty() - top.winfo_rooty()
                    rail_img = img.crop((rr_x, rr_y,
                                         rr_x + rail_w, rr_y + out.height))
                    full = Image.new("RGB", (rail_w + out.width, out.height),
                                     "#f7f2e7")
                    full.paste(rail_img, (0, 0))
                    full.paste(out, (rail_w, 0))
                    out = full
                    fp = path_prefix + (".png" if n_cols * n_rows == 1 else
                                        f"_r{ri + 1}c{ci + 1}.png")
                    out.save(fp)
                    files.append((fp, out.width, out.height))
        finally:
            self.master.export_chrome(False)
            top.wm_maxsize(*saved_max)
            if was_zoomed:
                top.state("zoomed")
            else:
                top.geometry(saved_geom)
            top.update()
            self.redraw()
        return files

    def toggle_plate(self):
        """横排 ⇄ 竖排。卡片高度变了，同列最小间距也变，所以必须重排。"""
        self.plate = "v" if self.plate == "h" else "h"
        self.master.apply_timeline_plate(self.plate)
        return self.plate

    def plate_label(self):
        """★ 2026-09-23 使用者要求：按钮只写当前状态两个字 ——「竖牌」/「横牌」。

        原来叫「铭牌 竖排」（5 字），又长又挡右边的内容；去掉「铭牌」二字后
        与左侧「适应/定位」等两字钮对称，也省出宽度。点一下切到另一态。
        """
        return "横牌" if self.plate == "h" else "竖牌"

    # ================================================================ 绘制
    def redraw(self):
        c = self.canvas
        c.delete("all")
        if not self._ready:
            return
        theme, lay = self.theme, self.lay
        vw, vh = self._viewport()
        vx0 = c.canvasx(0)
        vy0 = c.canvasy(0)
        vx1, vy1 = vx0 + vw, vy0 + vh

        # ---- 1) 朝代带（跟随纵向滚动，横向固定）----
        self._draw_rail()

        # ---- 2) 年格线 ----
        step = _nice_step(58, self.scale)
        ytop = lay.year_at(max(vy0 - lay.card_h, 0))
        ybot = lay.year_at(vy1)
        yr = int(ytop // step) * step
        while yr <= ybot:
            yy = lay.y_of(yr)
            if vy0 - 20 <= yy <= vy1 + 20:
                c.create_line(0, yy, max(vx1, vw) + 4000, yy, fill=theme.grid)
                c.create_text(6, yy - 7, text=_fmt_short(yr), anchor="w",
                              font=self.font_tick, fill=theme.text_3)
            yr += step

        # ---- 3) 世系虚线框（★ 2026-09-23 使用者要求时间轴也显示「X国世系」大圈）----
        # 画在连线与卡片**之下**：卡片不透明，线在卡里被挡，框也一样 —— 先画框，
        # 后面画的连线/卡片自然盖在上面，框就只是背景轮廓，不会糊住文字。
        # 框标题压色块、贴在框顶，卡片画完后仍可见（标题区没有卡片）。
        for min_x, min_y, max_x, max_y, color, title in self._state_boxes:
            if max_x < vx0 or min_x > vx1 or max_y < vy0 or min_y > vy1:
                continue
            c.create_rectangle(min_x, min_y, max_x, max_y, fill="", outline=color,
                               width=1, dash=(4, 3))
            if title:
                # ★ 2026-09-23 使用者反馈「世系 bar 不是弹性的」：原来按
                #   `len(title) * 8.0` 估宽，而 9pt 隶书的实际字宽约 13px ——
                #   实测「朝鲜世系」文字 52px 而色条只有 32px，白字两端溢出到
                #   浅色画布上**根本看不见**，看着就像「XX世系」缺了字。
                #   改成按真字体量宽（+10 内边距），色条随文字伸缩；仍夹在框内。
                tw = min(self.font_rail.measure(title) + 10, max_x - min_x - 4)
                cx = min_x + (max_x - min_x) / 2
                c.create_rectangle(cx - tw / 2, min_y, cx + tw / 2, min_y + 13,
                                   fill=color, outline=color)
                c.create_text(cx, min_y + 7, text=title,
                              font=self.font_rail, fill="#ffffff")

        # ---- 4) 连线（**画在卡片之下**；只算看得见的那几条，其余惰性）----
        # ★ 2026-09-22 使用者要求「母亲连线也做」：挂在母亲枝下的主线画
        #   婚姻色虚线；父母都在时母亲另有一条虚线（与族谱同款语义）。
        margin = 220.0          # 绕行折线可能超出两端点包围盒，留足余量
        ends = []               # 连线的接入点，等卡片画完再补小圆点
        attach_m = getattr(lay, "attach_mother", ())

        def _in_vp(ax, ay, bx, by):
            return not (max(ax, bx) < vx0 - margin or min(ax, bx) > vx1 + margin
                        or max(ay, by) < vy0 - margin or min(ay, by) > vy1 + margin)

        for (f, n, ax, ay, bx, by) in lay.link_pairs:
            if n in attach_m:
                continue                # 挂母线在下面单独画虚线
            if not _in_vp(ax, ay, bx, by):
                continue
            pts = lay.path_for(n)[0]
            if not pts:
                continue
            c.create_line(*[v for p in pts for v in p],
                          fill=theme.tree_line, width=1)
            ends.append((pts[0], pts[-1]))
        for n in attach_m:
            pair = lay._pair_of.get(n)
            if pair is None:
                continue
            _f, _n, ax, ay, bx, by = pair
            if not _in_vp(ax, ay, bx, by):
                continue
            pts = lay.path_for(n)[0]
            if not pts:
                continue
            c.create_line(*[v for p in pts for v in p],
                          fill=theme.spouse, width=1, dash=(3, 2))
            ends.append((pts[0], pts[-1]))
        for _m, n in getattr(lay, "mother_extra", ()):
            pair = lay._mother_pair_of.get(n)
            if pair is None:
                continue
            _f, _n, ax, ay, bx, by = pair
            if not _in_vp(ax, ay, bx, by):
                continue
            pts = lay.path_for_mother(n)[0]
            if not pts:
                continue
            c.create_line(*[v for p in pts for v in p],
                          fill=theme.spouse, width=1, dash=(3, 2))
            ends.append((pts[0], pts[-1]))

        # ---- 4) 卡片 ----
        n_vis = 0
        drawn = []                     # 本屏真正画出来的卡片（算间距用）
        drawn_names = []
        for name, (x, y) in lay.positions.items():
            if y < vy0 - lay.card_h or y > vy1:
                continue
            w = lay.widths[name]
            if x + w / 2 < vx0 or x - w / 2 > vx1:
                continue
            n_vis += 1
            drawn.append((x, y, w))
            drawn_names.append(name)
            self._draw_card(name, x, y, w)
        # ★ 2026-09-28 全项目整理（第 2 批，铁律②「没有任何汉字被遮盖」）：
        #   时间轴原本**完全没有层级管理** —— 卡片矩形与名字/尊号/封代都不带 tag，
        #   于是**后画的右邻卡矩形**盖住本卡**卡外右侧的尊号**、下邻卡矩形盖住
        #   **卡下方的封代数字**（这两个字都画在卡片之外，最容易被后画的卡吃掉）。
        #   现在：矩形 → `platebg`（另带人名 tag，随人一起删）；文字 → `platetext`。
        #   本屏所有卡画完，把 `platetext` 提到 `platebg` 之上 ⇒ 字永远在底之上。
        for _tag in ("platebg", "platetext"):
            try:
                self.canvas.tag_raise(_tag)
            except Exception:
                pass
        self._visible_count = n_vis
        drawn_set = set(drawn_names)

        # ---- 4.5) 夫妻红线（2026-09-22 使用者要求）----
        # 只连两端都在本屏的配偶；线形按使用者裁定改成**天平状折线**
        # （族谱同款 U 型：两卡下沿各垂一段、中间一根横杆、杆下一颗 ♥），
        # 直愣愣的斜线不好看。去重：配偶关系对称，只从字典序小的一端画一次。
        # ★ 2026-09-23：改淡红虚线（spouse_line 空串回退 spouse）。
        sp_line = theme.spouse_line or theme.spouse
        chh = lay.card_h
        for name in drawn_names:
            info = self.master.people.get(name) or {}
            for s in (info.get("spouses") or []):
                if not s or s <= name or s not in drawn_set:
                    continue
                x1, y1 = lay.positions[name]
                x2, y2 = lay.positions[s]
                w1, w2 = lay.widths[name], lay.widths[s]
                if x1 <= x2:
                    lx, rx = x1 + w1 / 2, x2 - w2 / 2
                    b1, b2 = y1 + chh, y2 + chh
                else:
                    lx, rx = x2 + w2 / 2, x1 - w1 / 2
                    b1, b2 = y2 + chh, y1 + chh
                if rx - lx < 2:
                    continue            # 两卡几乎同列，U 型没有意义
                drop = max(b1, b2) + 5.0
                c.create_line(lx, b1, lx, drop, rx, drop, rx, b2,
                              fill=sp_line, width=1, dash=(4, 2))
                c.create_text((lx + rx) / 2, drop + 8, text="♥",
                              font=self._fonts(10), fill=sp_line)

        # ---- 5) 连线接入点（画在卡片**之上**）----
        # 卡片是不透明的，线在卡里必然被挡；在接口处点一个小圆点，
        # 「这条线接上了这张卡」才一眼看得出来。
        # ★ 但**缩得越小越不能画** —— 全档两万人时一屏就有上百上千个端点，
        #   这个 3px 的实心圆点铺开后整块画布全是麻点，远看就是「很多白点」，
        #   把朝代色和卡片框全糊掉了（使用者原话：后期朝代画布上很不清晰有很多白点）。
        #   判据用「本屏卡片占横向的比例」：占了半屏以上说明卡挤成一片，
        #   此时补点只会变噪点；卡还稀疏时补点才有「接口对上」的信息量。
        END_DOT_MAX = 240
        cards_px = sum(d[2] for d in drawn)
        vw_px = max(vx1 - vx0, 1.0)
        sparse = (len(drawn) <= 40) or (cards_px <= vw_px * 0.5)
        if drawn and len(drawn) <= END_DOT_MAX and sparse:
            for (p, q) in ends:
                for (ex, ey) in (p, q):
                    if vx0 - 6 <= ex <= vx1 + 6 and vy0 - 6 <= ey <= vy1 + 6:
                        c.create_oval(ex - 1.5, ey - 1.5, ex + 1.5, ey + 1.5,
                                      fill=theme.tree_line, outline="")

        # ---- 5.5) 竖排低比例警示牌（UI 改进 B9，由状态栏文案改到画布角落）----
        # 实测：竖排铭牌（卡高 54→**60**，2026-09-26 与代际家谱统一后复测：
        # 3.0~6.0 px/年 直斜线全为 0，4.4 这个阈值继续沿用，只是更保守）；
        # 更低时卡片把水平空白巷道挤没了，会有几十条连线只能从卡上压过去（几何必然）。
        if self.plate == "v" and self.scale < V_PLATE_MIN_SCALE:
            txt = "竖排铭牌在此缩放下部分连线绕不开 · 放大或换横排"
            tw = 260
            c.create_rectangle(vx1 - tw - 8, vy1 - 30, vx1 - 8, vy1 - 8,
                               fill=theme.bg_card, outline=theme.warn, width=1)
            c.create_text(vx1 - tw // 2 - 8, vy1 - 19, text=txt,
                          fill=theme.warn, font=self.font_mini)

        # ---- 6) 小传浮卡（重挂回来；Canvas 的 delete("all") 只删图元，不销毁内嵌控件）----
        self._rehang_popcard()

    # ================================================================ 小传浮卡
    def hide_popcard(self):
        self.canvas.delete("popcard")
        if self._pop_widget is not None:
            try:
                self._pop_widget.destroy()
            except tk.TclError:
                pass
            self._pop_widget = None
        self._pop_at = None

    def _draw_popcard(self):
        """选中人物的小传卡。卡片由 `widgets/popcard` 拼（与主树同一套），
        这里只管摆位 —— ★ 2026-09-23 改为固定贴在**视口右下角**（与主树一致）。"""
        self.hide_popcard()
        name = self.selected
        if not name or not self._ready or name not in self.lay.positions:
            return
        built = build_popcard(self.canvas, self.theme, self.master.people, name)
        if built is None:
            return
        card, w, h = built
        vw = self.canvas.winfo_width()
        vh = self.canvas.winfo_height()
        if vw > 50 and vh > 50:
            px = self.canvas.canvasx(0) + vw - w - 12
            py = self.canvas.canvasy(0) + vh - h - 12
        else:
            x, y = self.lay.positions[name]
            half = self.lay.widths[name] / 2.0
            px = x + half + 10
            py = y + self.lay.card_h / 2.0 - 30
        self._pop_at = (px, py)
        self.canvas.create_window(px, py, window=card, anchor="nw", tags="popcard")
        self._pop_widget = card

    def _rehang_popcard(self):
        """`canvas.delete("all")` 会删掉浮卡的窗口图元（但内嵌控件还活着）。
        重挂回原位置即可 —— 平移缩放时它跟着卡片走，没必要每次重建整张卡。"""
        if self._pop_widget is not None and self._pop_at is not None:
            self.canvas.create_window(self._pop_at[0], self._pop_at[1],
                                      window=self._pop_widget, anchor="nw",
                                      tags="popcard")

    def _draw_rail(self):
        """朝代带（左侧可拖动那根）：★ 2026-09-26 二修为**全程绝对坐标**。

        原来只画「当前视口那几年」，画完靠 yview 同步跟手 —— 往下拖过一屏，
        带子上没画过的年份就是空白（使用者报「从前 2350 往下没有了」）。
        全程也就几十个色块 + 上百根刻度，随视口重画毫无压力。
        顶端的「全览」标签钉在视口顶（每拍重画），与最左全览条连成横跨双栏的头。
        """
        r, theme, lay = self.rail, self.theme, self.lay
        if lay is None:
            return
        r.delete("all")
        w = self.rail_w
        h = max(self.lay.height, 1.0)
        r.create_rectangle(0, 0, w, h + 10, fill=theme.bg_card, outline="")
        ya, yb = lay.year_at(0), lay.year_at(h)
        taken = []                                    # 朝代名占用的纵向位置
        for name, s2, e in T.era_segments(ya, yb):
            top = max(lay.y_of(s2), -1)
            bot = min(lay.y_of(e + 1), h + 1)
            if bot <= top:
                continue
            color = ERA_COLORS.get(name, "#8d7f6a")
            r.create_rectangle(0, top, w, bot, fill=color, outline="")
            if bot - top >= 46:
                cy = (top + bot) / 2
                taken.append(cy)
                r.create_text(w / 2, cy, text=_era_label(name), fill="#ffffff",
                              font=self.font_rail)

        # 年份刻度（白色，压在色带上）：相邻刻度 ≥ 200px；与朝代名撞上就让开
        step = _nice_step(200, self.scale)
        yr = int(ya // step) * step
        while yr <= yb:
            yy = lay.y_of(yr)
            if 8 <= yy <= h - 8 and all(abs(yy - cy) > 13 for cy in taken):
                r.create_text(w / 2, yy, text=_fmt_short(yr), fill="#ffffff",
                              font=self.font_tick)
            yr += step
        r.create_line(w - 1, 0, w - 1, h, fill=theme.border)

        # 「全览」标签：钉在视口顶部（跨双栏头的右半，左半在最左全览条上）
        vy0 = self.canvas.canvasy(0)
        r.create_rectangle(0, vy0, w, vy0 + MINI_LABEL_H,
                           fill=theme.bg_panel, outline="")
        r.create_text(w / 2, vy0 + MINI_LABEL_H / 2, text="全览",
                      fill=theme.text_2, font=self.font_mini)
        r.create_line(0, vy0 + MINI_LABEL_H, w, vy0 + MINI_LABEL_H,
                      fill=theme.border)

    def _on_rail_click(self, e):
        """点朝代带顶部的「全览」标签 = 全览适配（与全览条同动作）。"""
        if e.y <= MINI_LABEL_H:
            self.fit_to_window()

    # ================================================================ 缩略轴
    def _mini_geom(self):
        """缩略条的**有效画带高度**。顶端 MINI_LABEL_H 一格留给「全览」标签。"""
        h = max(self.mini.winfo_height(), 1)
        return max(h - MINI_LABEL_H, 1), self.range_end - self.range_start

    def _year_to_mini_y(self, year):
        """年份 → 缩略条上的 y（纵向：年份越大越往下，与画布同向）。"""
        h, span = self._mini_geom()
        if span <= 0:
            return MINI_LABEL_H
        return MINI_LABEL_H + (year - self.range_start) / span * h

    def _draw_mini(self):
        """纵向全览条：色带/刻度/红虚线全部按**高度**比例画（2026-09-26 竖排化）。"""
        m, theme = self.mini, self.theme
        m.delete("all")
        full = max(m.winfo_height(), 1)
        if full < 40:
            return
        w = max(m.winfo_width(), 1)
        # 顶端「全览」标签
        m.create_rectangle(0, 0, w, MINI_LABEL_H, fill=theme.bg_panel, outline="")
        m.create_text(w / 2, MINI_LABEL_H / 2, text="全览",
                      fill=theme.text_2, font=self.font_mini)
        m.create_line(0, MINI_LABEL_H, w, MINI_LABEL_H, fill=theme.border)
        # 朝代色带（高度按年数比例）
        for name, s, e in T.era_segments(self.range_start, self.range_end):
            ya = self._year_to_mini_y(max(s, self.range_start))
            yb = self._year_to_mini_y(min(e + 1, self.range_end))
            if yb - ya < 0.5:
                continue
            color = ERA_COLORS.get(name, "#8d7f6a")
            m.create_rectangle(2, ya, w - 2, yb, fill=color, outline="")
            if yb - ya >= 34:                   # 段够高才写名字（竖排一字一行）
                m.create_text(w / 2, (ya + yb) / 2,
                              text="\n".join(_era_label(name)),
                              fill="#ffffff", font=self.font_mini)
        # 刻度（横线；年份文字在东侧的朝代带上已有，这里不重复挤）
        for y in MINI_TICK_YEARS:
            if not (self.range_start <= y <= self.range_end):
                continue
            py = self._year_to_mini_y(y)
            m.create_line(3, py, w - 3, py, fill="#ffffff", width=1)
        # 本档最晚的生年：再往下就是「这盘还没走到」的部分（红虚线分隔）
        if self.lay is not None and self.lay.years:
            last = max(self.lay.years.values())
            py = self._year_to_mini_y(last)
            m.create_line(0, py, w, py, fill=theme.danger, width=1, dash=(3, 2))
        self._draw_mini_viewbox()

    def _draw_mini_viewbox(self):
        """视口框（纵向）：当前视口覆盖哪几年，画在缩略条上。"""
        m = self.mini
        m.delete("viewbox")
        if not self._ready:
            return
        c = self.canvas
        w = max(m.winfo_width(), 1)
        _vw, vh = self._viewport()
        ya = self.lay.year_at(c.canvasy(0))
        yb = self.lay.year_at(c.canvasy(0) + vh)
        ta = self._year_to_mini_y(max(ya, self.range_start))
        tb = self._year_to_mini_y(min(yb, self.range_end))
        if tb - ta < 3:
            tb = ta + 3
        # ★ 不要用 stipple 点阵当「半透明底」——Tk 没有 alpha，
        #   点阵叠在已上色的朝代条上远看是一片麻点（实测被使用着一眼看穿）。
        #   只描边 + 上下各压一条 2px 实心短横条表示视口边界。
        m.create_rectangle(2, ta, w - 2, tb, outline=self.theme.accent, width=2,
                           fill="", tags="viewbox")
        m.create_rectangle(2, ta, w - 2, min(ta + 2, tb),
                           fill=self.theme.accent, outline="", tags="viewbox")
        m.create_rectangle(2, max(tb - 2, ta), w - 2, tb,
                           fill=self.theme.accent, outline="", tags="viewbox")

    def _on_mini_click(self, event):
        self._jump_to_mini(event.y)

    def _on_mini_drag(self, event):
        self._jump_to_mini(event.y)

    def _jump_to_mini(self, my):
        """点/拖纵向缩略条 → 把视口挪到那一年（上下才是时间）。"""
        if not self._ready:
            return
        self._touch()
        h, span = self._mini_geom()
        if h <= 0:
            return
        year = self.range_start + max(my - MINI_LABEL_H, 0) / h * span
        _, vh = self._viewport()
        half = (vh / self.scale) / 2.0
        y = self.lay.y_of(year - half)
        total = max(self.lay.height, 1)
        self.canvas.yview_moveto(max(0.0, min(1.0, y / total)))
        self.rail.yview_moveto(self.canvas.yview()[0])
        self.redraw()
        self._sync_mini()          # 拖动绿框 / 点缩略条：绿框跟着走到新位置

    # ================================================================ 滚动
    def _touch(self):
        """用户动过视口 —— 之后别再自动把镜头拉回去。"""
        self._framed = True

    def _yview(self, *args):
        self._touch()
        self.canvas.yview(*args)
        self.rail.yview_moveto(self.canvas.yview()[0])
        self.redraw()
        self._sync_mini()

    def _xview(self, *args):
        self._touch()
        self.canvas.xview(*args)
        self.redraw()

    def _on_yscroll(self, first, last):
        self.vbar.set(first, last)
        self.rail.yview_moveto(first)
        # ★ 2026-09-21：拖右侧滚动条也要挪全览上的绿框。
        #   原来只有 `_draw_mini()` 末尾画一次绿框，而滚动条这条路径连 `redraw()`
        #   都不走 —— 使用者看到的就是「绿框永远钉在上古那一段，不跟画布走」。
        self._sync_mini()

    def _on_xscroll(self, first, last):
        self.hbar.set(first, last)

    def _sync_mini(self):
        """只重画缩略轴上的绿框（视口框）。

        绿框 = 「当前视口覆盖哪几年」，任何一次纵向滚动都要跟着走。
        单独抽出来是因为它比重画整条缩略轴便宜得多（删 3 个图元 + 画 3 个图元），
        可以挂在每一个滚动路径上而不心疼。
        """
        self._draw_mini_viewbox()

    def _on_wheel(self, event):
        self._touch()
        self.canvas.yview_scroll(int(-event.delta / 120) * 3, "units")
        self.rail.yview_moveto(self.canvas.yview()[0])
        self.redraw()
        self._sync_mini()
        return "break"

    def _on_wheel_shift(self, event):
        self._touch()
        self.canvas.xview_scroll(int(-event.delta / 120) * 3, "units")
        self.redraw()
        return "break"

    def _on_wheel_ctrl(self, event):
        """以鼠标位置为锚点缩放。

        锚的是「光标下的**年份** + 世界坐标 x」，**不是**「光标下那个人」——
        树状发散的 x 会随比例尺重新排布，钉人的话缩放后那个人可能被排到画布最左边，
        视图被迫夹到边界，反而跳得更厉害。锚年份是精确的（年份与比例尺无关），
        锚世界 x 保证横向视觉上不跳。
        """
        if not self._ready:
            return "break"
        year = self.lay.year_at(self.canvas.canvasy(event.y))
        wx = self.canvas.canvasx(event.x)
        self._anchor = (year, wx, event.x, event.y)
        factor = 1.25 if event.delta > 0 else 1 / 1.25
        self.set_scale(self.scale * factor)
        return "break"

    def _on_configure(self, event):
        """画布尺寸定了才知道「一屏能装多少年」，初始比例与镜头定位都在这里做。"""
        if not self._user_zoomed and self._span:
            want = T.initial_scale(self._span, max(event.height - 30, 200))
            if self.lay is None or abs(want - self.scale) > 1e-3:
                self.rerender(keep_scale=False)
                self.master.on_layout_changed()
                return
        if self.lay is None:
            self.rerender()
            return
        if not self._user_zoomed and not self._framed:
            # 首次拿到真实尺寸时补一次镜头定位：after_idle 那次画布可能还是 1×1，
            # 那时候算出来的视口是错的（实测秦末档会因此停在空白处「本屏 0 人」）。
            self._draw_mini()
            self._scroll_to_content()
            self.master.on_layout_changed()
            return
        self._draw_mini()
        self.redraw()
        self.master.on_layout_changed()

    # ================================================================ 鼠标
    def _hit(self, x, y):
        if not self._ready:
            return None
        best = None
        for name, (cx, cy) in self.lay.positions.items():
            w = self.lay.widths[name]
            if cy <= y <= cy + self.card_h and cx - w / 2 <= x <= cx + w / 2:
                best = name
                break
        return best

    def _on_click(self, event):
        self._press = (event.x, event.y, self.canvas.canvasx(0), self.canvas.canvasy(0))
        name = self._hit(self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        if name:
            self.master.select_person(name)
        else:
            self.master.clear_selection()

    def _on_drag(self, event):
        """拖动空白 = 平移（不依赖 scan_dragto，因为我改了 scrollregion 的用法）。"""
        if not self._ready:
            return
        self._touch()
        px, py, cx0, cy0 = self._press
        dx, dy = event.x - px, event.y - py
        total_w = max(self.lay.width, 1)
        total_h = max(self.lay.height, 1)
        vw, vh = self._viewport()
        nx = max(0.0, min(1.0, (cx0 - dx) / total_w))
        ny = max(0.0, min(1.0, (cy0 - dy) / total_h))
        self.canvas.xview_moveto(nx)
        self.canvas.yview_moveto(ny)
        self.rail.yview_moveto(self.canvas.yview()[0])
        self.redraw()
        self._sync_mini()          # 拖画布平移：绿框要跟着走

    def _on_double(self, event):
        name = self._hit(self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        if name:
            self.master.select_person(name)
            self.master.goto_main_tree(name)

    def _on_right_click(self, event):
        """右键铭牌：弹菜单（与家谱同一套，含「选定（仅显所选）」）。"""
        name = self._hit(self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        if not name:
            return
        self.master.select_person(name)
        menu = self.master.build_context_menu(name)
        if menu is not None:
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

    # ================================================================ 缩放
    def set_scale(self, scale, anchor_year=None, anchor_px=None):
        scale = T.clamp_scale(scale)
        if abs(scale - self.scale) < 1e-6:
            return
        self._touch()
        self.scale = scale
        self._user_zoomed = True
        if self._zoom_job is not None:
            self.canvas.after_cancel(self._zoom_job)
        self._zoom_job = self.canvas.after(90, self._apply_zoom)

    def _apply_zoom(self):
        """重算布局，并把锚点（光标下的年份与世界 x）放回原来的像素位置。"""
        self._zoom_job = None
        anchor = self._anchor
        self.rerender(keep_scale=True, cache_ok=True)
        if not self._ready:
            self.master.on_layout_changed()
            return
        total_w = max(self.lay.width, 1)
        total_h = max(self.lay.height, 1)
        if anchor:
            year, wx, px, py = anchor
            tx = wx - px                       # 横向：世界坐标不动，视觉上不跳
            ty = self.lay.y_of(year) - py      # 纵向：光标下的年份保持不动（精确）
            self.canvas.xview_moveto(max(0.0, min(1.0, tx / total_w)))
            self.canvas.yview_moveto(max(0.0, min(1.0, ty / total_h)))
            self.rail.yview_moveto(self.canvas.yview()[0])
            self.redraw()
        self.master.on_layout_changed()

    def zoom(self, direction):
        """工具条用：1 放大 / -1 缩小 / 0 回到默认比例。

        工具条没有鼠标位置，就锚**视口中心**，这样按钮缩放和滚轮缩放手感一致。
        """
        if direction == 0:
            self._user_zoomed = False
            self._anchor = None
            self.rerender(keep_scale=False)
            self.master.on_layout_changed()
        else:
            if self._ready:
                vw, vh = self._viewport()
                cx, cy = vw / 2.0, vh / 2.0
                self._anchor = (self.lay.year_at(self.canvas.canvasy(cy)),
                                self.canvas.canvasx(cx), cx, cy)
            self.set_scale(self.scale * (1.3 if direction > 0 else 1 / 1.3))
        return self.scale

    def zoom_percent(self):
        return round(self.scale / T.SCALE_DEFAULT * 100)

    def fit_to_window(self):
        """把整个年份范围压进视口高度。"""
        _, vh = self._viewport()
        span = max(self.range_end - self.range_start, 1)
        self.scale = T.clamp_scale(vh / span)
        self._user_zoomed = True
        self.rerender(keep_scale=True)
        self.master.on_layout_changed()

    # ================================================================ 选中
    def select(self, name):
        # 取消选中时先收掉浮卡：再走 redraw 会把旧卡「重挂」回来
        if name is None:
            self.hide_popcard()
        self.selected = name
        self.redraw()
        self._draw_popcard()

    def reset_scale(self):
        """回到「按视口自动适应」的比例（换存档时用，别沿用上一档的缩放）。"""
        self._user_zoomed = False

    def scroll_to(self, name):
        if not self._ready or name not in self.lay.positions:
            return
        self._touch()
        x, y = self.lay.positions[name]
        vw, vh = self._viewport()
        total_w = max(self.lay.width, 1)
        total_h = max(self.lay.height, 1)
        self.canvas.xview_moveto(max(0.0, min(1.0, (x - vw / 2) / total_w)))
        self.canvas.yview_moveto(max(0.0, min(1.0, (y - vh / 2) / total_h)))
        self.rail.yview_moveto(self.canvas.yview()[0])
        self.redraw()

    def status_text(self):
        """状态栏中间那段（视口年份 + 比例尺 + 本屏人数）。"""
        if not self._ready:
            return "时间轴 · 无生年数据"
        vw, vh = self._viewport()
        ya = self.lay.year_at(self.canvas.canvasy(0))
        yb = self.lay.year_at(self.canvas.canvasy(0) + vh)
        n = getattr(self, "_visible_count", 0)
        txt = (f"视口 {_fmt_year(int(ya))} ~ {_fmt_year(int(yb))} · "
               f"{self.scale:.2f} px/年 · 本屏 {n} 人 · "
               f"全档 {len(self.lay.years)} 人有生年")
        # UI 改进 B9：竖排低比例警告已改画在画布右下角（redraw 第 5.5 步），
        # 状态栏不再拖一句尾巴。
        return txt


# 朝代色带（与效果图第 ⑩ 节同一套）；「上古」原「传说时代」（2026-09-22 使用者裁定）
ERA_COLORS = {
    "上古": "#8d7f6a", "夏": "#a08a63", "商": "#b58a4a", "西周": "#c08b3e",
    "春秋": "#b3612f", "战国": "#9c4a2a", "秦": "#5a4a6a", "汉": "#1f6b4f",
    "三国": "#3a6b8a", "晋": "#4a7a9a", "南北朝": "#5a7a8a", "隋": "#6a8a7a",
    "唐": "#8a7a3a", "五代": "#7a6a4a", "宋": "#6a7a5a",
}
