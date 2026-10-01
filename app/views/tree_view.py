"""树形主视图 —— 按效果图 ① 实现。

绘制顺序（与效果图一致）：
  世系虚线框 → 代数标签 → 父子连线 → 同代人符号 → 夫妻 U 型线
  → 虚线框标题 → 人物框（爵位描边/装饰线/姓名/史标/封代/尊号）→ 选中浮卡

两套节点版式（只改「怎么画」，不改布局几何，可在设置里切换）：
  classic 经典版   —— 透明框 + 顶部爵位装饰线，v1 原版画法
  card    竖向卡片式 —— 淡底实心卡片 + 左侧爵位色条 + 右上角爵位小字

字号自适应 + 强制单排（规划 6.4）：方框恒定，名字/尊号按字数缩放，
Tkinter 的 create_text 绝不传 width（否则竖排会被折成两列）。
"""
import logging
import tkinter as tk
import tkinter.font as tkfont

from .. import bio as bio_mod
from .. import jue
from .. import layout as L
from .. import model
from ..labels import split_dup
from ..theme import TIER_DECOR, get_node_style
# 中文避头尾折行、小传卡的拼装都抽到 app/widgets/popcard.py 了 —— 时间轴视图要用同一套
from ..widgets.popcard import build_popcard
from ..widgets.kit import est_text_px
from .. import dpi as _dpi

logger = logging.getLogger(__name__)


# 缩放：以 BASE_SCALE 为 100% 基准，默认 80%
# ★ 2026-09-26 DPI：BASE_SCALE 吃进系统缩放系数 —— 画布几何（连线/节点框/
#   边距）全部经 `× self.scale` 换算，乘一次就整体放大；而**字号点数**不能
#   乘（Tk 感知 DPI 后按 pt 自动放大，再乘会双重放大），所以下面所有
#   `int(N * self.scale)` 出字号的地方都 `/ _dpi.SCALE` 还原成逻辑值。
BASE_SCALE = (1.1 ** 3) * _dpi.SCALE
DEFAULT_ZOOM = 0.8
ZOOM_STEP = 0.1
ZOOM_MIN, ZOOM_MAX = 0.3, 2.0


def _round_rect(canvas, x1, y1, x2, y2, r, **kw):
    """圆角矩形。

    Tkinter 的 create_rectangle 只有直角，这里用「顶点重复 + smooth」的平滑
    多边形近似圆角，是 Canvas 上的标准做法。r<=0 时退回普通矩形。
    """
    r = max(0.0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    if r <= 0:
        return canvas.create_rectangle(x1, y1, x2, y2, **kw)
    return canvas.create_polygon(
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
        smooth=True, **kw)


# 中文避头尾折行、小传卡的拼装都抽到 app/widgets/popcard.py 了 —— 时间轴视图要用同一套


class TreeView:
    def __init__(self, parent, theme, master):
        """parent: 容器 Frame; master: App 控制器（提供 people / root / 回调）。"""
        self.master = master
        self.theme = theme

        outer = tk.Frame(parent, bg=theme.bg_canvas)
        outer.pack(fill=tk.BOTH, expand=True)

        # ★ 2026-09-28 使用者要求：「画布很宽，我左右拖动画布的时候，这个代际汉字
        #   数字不要被拖走，我要参考」—— 原先「第 X 代」是画在主画布 x=20 的普通
        #   图元，横向一拖就跟着跑出视野。改为**左侧独立的「代数条」**：
        #     · 只有纵向滚动（`scrollregion` 的 y 范围与主画布**完全一致**），
        #       水平方向恒定不动 —— 左右拖画布它纹丝不动；
        #     · 纵向由 `_on_yscroll` 与主画布同步，仍与每一代的行对齐。
        self.ruler = tk.Canvas(outer, bg=theme.bg_canvas, highlightthickness=0,
                               bd=0, width=_dpi.px(50))
        self.ruler.pack(side=tk.LEFT, fill=tk.Y)
        self.ruler.bind("<MouseWheel>", lambda e: self._on_wheel(e))

        self.canvas = tk.Canvas(outer, bg=theme.bg_canvas, highlightthickness=0,
                                bd=0, cursor="hand2")
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._vbar = tk.Scrollbar(outer, orient=tk.VERTICAL, command=self.canvas.yview,
                                  bg=theme.border_2, troughcolor=theme.bg_panel,
                                  activebackground=theme.accent, highlightthickness=0,
                                  bd=0, width=theme.scrollbar_w, relief=tk.FLAT)
        # ★ 2026-09-26 按需绘制：滚轮 / 滚动条 / `scan_dragto` 拖动**都会**触发
        #   x/y scrollcommand —— 在这里挂钩安排补画，才叫"拖到哪、哪就补上"。
        #   （原先滚动与拖动**完全不触发任何重绘**，拖到未画区域永远空白。）
        self.canvas.configure(yscrollcommand=self._on_yscroll)
        self._vbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._hbar = tk.Scrollbar(outer, orient=tk.HORIZONTAL, command=self.canvas.xview,
                                  bg=theme.border_2, troughcolor=theme.bg_panel,
                                  activebackground=theme.accent, highlightthickness=0,
                                  bd=0, relief=tk.FLAT)
        self.canvas.configure(xscrollcommand=self._on_xscroll)
        self._hbar.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.bind("<Configure>", lambda _e: self._schedule_paint(), add="+")

        self.lay = None
        self.person_rect = {}
        self.scale = BASE_SCALE * DEFAULT_ZOOM
        self._user_zoomed = False     # 手动缩放过就不再自动放大铺满（2026-09-23）
        self.selected = None
        self.search_hits = []       # 搜索命中的人名（按存档顺序）
        self.search_index = -1      # 当前停在哪个命中上，-1 = 还没开始跳
        self._pop_widget = None
        self._zoom_after_id = None
        self._line_factor_cache = {}
        self._state_boxes = []
        self._qing_boxes = []
        # ★ 2026-09-26 按需绘制（启动优化 + 修「拖动不补」）：
        #   画布上**只留「视口 ± 半屏」里的人**（含其连线）——滚出去就删、滚进来就补。
        #   不再追求"把 13,526 人全画完"：全量绘制在真窗口要几十秒（79k item），
        #   期间画布大片空白（使用者报的「显示不全」），且滚动/拖动不触发重绘。
        self._paint_job = None         # 待跑的重排作业
        self._drawn_links = set()      # 已画的连线条目（判重）
        self._drawn_people = set()     # 已画的人
        # ★ 2026-09-26 修「父子不连线」：按需绘制的删补有个方向性缺口 ——
        #   连线归「子」所有（子画自己向上的父/母线），父滚出视口被淘汰时
        #   `delete(p_父)` 会把「已画子女」的父线一并带走；父滚回来时只重画
        #   自己向上的线，**向下到已画子女的线没人补**（子女已画、不会被再处理）。
        #   修法：_draw_people 补「向下」方向（父/母/推定父 → 子），需要三张
        #   反向索引（子索引 / 推定父反查 / 义亲反查），在 `_draw` 里按谱重建。
        self._children_index = {}
        self._guess_rev = {}
        self._assoc_rev = {}

        self.canvas.bind("<ButtonPress-1>", self._on_click)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonPress-3>", self._on_right_click)
        self.canvas.bind("<MouseWheel>", self._on_wheel)

    # ================================================================ 渲染
    @property
    def node_style(self):
        """当前节点版式（classic | card）。存在 config 里，改完重绘即生效。"""
        return get_node_style(self.master.cfg.get("node_style", ""))

    def _pinned(self):
        """豁免过滤的名单 = 手动「选定」的人 ∪ **跳转目标**。

        ★ 2026-09-30 使用者报：「**有时候从人物表格里页双击人物还是定位不到
          家谱的铭牌**」。真因：目标在谱牒里，却被任一层过滤挡住
          （隐藏非史 / 隐藏逝者 / 仅显入谱 / 画布截断），
          而 `scroll_to` 对"不在画布上的人"是静默 return ⇒ 看着像双击坏了。

          原来只有「选定」的人穿透过滤层（`m.focused`），双击跳转的目标**不在
          那个名单里**，所以"有时"（勾了某层过滤时）就定位不到。

          修法：把跳转目标单独钉住 —— **不并进 `m.focused`**（那是使用者自己
          的选定名单，跳一次就往里塞人会污染它），而是走独立属性 `_jump_pin`。
        """
        m = self.master
        out = set(m.focused)
        pin = getattr(m, "_jump_pin", None)
        if pin and pin in (m.people or {}):
            out.add(pin)
        return out

    def rerender(self, skip_collision=False):
        """重算布局并整体重绘。"""
        m = self.master
        self.lay = L.compute_layout(
            m.people,
            scale=self.scale,
            hidden_non_historical=m.hidden_non_historical,
            cutoff_person=m.cutoff_person,
            skip_collision=skip_collision,
            hide_dead=m.hide_dead,
            focus_list=m.focused if getattr(m, "focus_only", False) else None,
            # ★ 2026-09-23 手动「选定」的人穿透所有过滤层（隐藏非史/隐藏逝者/
            #   仅显入谱）—— 否则选定已故者或未入谱者时画布无变化，看着像按钮坏了。
            # ★ 2026-09-30 起并入「跳转目标」钉子，见 `_pinned()`。
            pinned_list=self._pinned(),
            # ★ 2026-09-23 画布默认只画点名过的人（入谱 / 加入族谱）。
            #   选定的人也在 pinned_list 里并进来了（见上）。
            enrolled_list=(m.enrolled_set()
                           if getattr(m, "enrolled_only", True) else None),
            # ★ 2026-09-24 侧栏「隐藏非史」全局开关（勾上隐藏全部非史实人物）
            hide_nohist_all=getattr(m, "hide_nohist_all", False),
        )
        self._draw()
        # ★ 2026-09-23 使用者要求「过滤后空白的画布都隐藏」：隐藏逝者 / 仅显所选
        #   后内容可能只剩一小块，视口里大半是空白画布 —— 内容不满一屏时自动
        #   放大铺满（用户手动缩放过就尊重手调，不再动）。
        if not self._user_zoomed:
            vh = self.canvas.winfo_height()
            content_h = self.lay.scroll_y_end - self.lay.scroll_y_start
            if vh > 50 and content_h < vh - 20 and content_h > 0:
                k = (vh - 20) / content_h
                new_scale = min(self.scale * k, BASE_SCALE * ZOOM_MAX)
                if new_scale > self.scale * 1.02:
                    self.scale = new_scale
                    self.lay = L.compute_layout(
                        m.people,
                        scale=self.scale,
                        hidden_non_historical=m.hidden_non_historical,
                        cutoff_person=m.cutoff_person,
                        skip_collision=skip_collision,
                        hide_dead=m.hide_dead,
                        focus_list=m.focused if getattr(m, "focus_only", False) else None,
                        pinned_list=self._pinned(),
                        enrolled_list=(m.enrolled_set()
                                       if getattr(m, "enrolled_only", True) else None),
                        hide_nohist_all=getattr(m, "hide_nohist_all", False),
                    )
                    self._draw()

    def _draw(self):
        c = self.canvas
        c.delete("all")
        self.person_rect.clear()
        theme, lay, people = self.theme, self.lay, self.master.people
        if lay is None or not lay.positions:
            c.config(scrollregion=(0, 0, 0, 0))
            return

        c.config(scrollregion=(0, lay.scroll_y_start, lay.scroll_x, lay.scroll_y_end))
        # ★ 2026-09-26 爵称口径（app/jue.py）：周以前按**尊号**、西周以后按**实际爵位**、
        #   夏商周天子一律「王」、帝色只给上古与秦以后。一次算好全谱（13,526 人），
        #   别在逐节点循环里反复算朝代。
        jue.install_from_save(getattr(self.master, "current_save", ""))
        self._tier_of = jue.tier_colors_for(people)
        node_h = lay.node_h
        nw = lay.name_width

        # 1) 世系虚线框
        self._state_boxes, self._qing_boxes = L.state_group_boxes(
            people, lay, theme.tier, tier_of=self._tier_of)
        # ★ 2026-09-26 使用者：「虚接线跟 X 国世系的边框线区分得不是很明显」。
        #   方案（使用者当场同意）：**世系框 = 长划虚线 + 加粗**（"框"感），
        #   把"点线感"让给推定线（见下面 3b，点划线 + 两端圆点）。
        for min_x, min_y, max_x, max_y, color, _ in self._state_boxes:
            c.create_rectangle(min_x, min_y, max_x, max_y, fill="", outline=color,
                               width=int(2.8 * self.scale), dash=(12, 5),
                               tags="boxframe")
        for min_x, min_y, max_x, max_y, color, _ in self._qing_boxes:
            c.create_rectangle(min_x, min_y, max_x, max_y, fill="", outline=color,
                               width=int(1.5 * self.scale), dash=(2, 2),
                               tags="boxframe")
        # 6) 框标题（★ 2026-09-26 移到这里与框同层）—— 原来在连线之后画，
        #    「标题压连线」；改分批绘制后靠 tag 分层维持这个次序（见 _draw_people）：
        #    link < node < boxtitle < searchhit < popcard。
        # ★ 2026-09-26 遮挡排查（使用者截图：「姬姓智氏世系」压住「史」徽标）：
        #   · 标题条画进**框顶带**（min_y+2 起、框边距 20px 内），不在框外 ——
        #     框外上方是上一代/邻支的节点领地，横竖都会撞；
        #   · x **居左**（框内第一行起点节点居中，左侧空白正好放标题）；
        #   · 画之前用「节点 y 带桶」做碰撞检查 —— 真撞就**整条放弃**：
        #     宁可少一个标题，也不让黑底白字压在别人名字上。
        band = {}
        BH = 20
        for nm, (x, y) in lay.positions.items():
            k = int(y // BH)
            band.setdefault(k, []).append((x - nw / 2, y - node_h / 2,
                                           x + nw / 2, y + node_h / 2))

        def band_hit(x0, y0, x1, y1):
            for k in range(int(y0 // BH), int(y1 // BH) + 1):
                for (a0, b0, a1, b1) in band.get(k, ()):
                    if not (x1 <= a0 or a1 <= x0 or y1 <= b0 or b1 <= y0):
                        return True
            return False

        # ★ 2026-09-28 全项目整理（第 2 批，铁律②「没有任何汉字被遮盖」）：
        #   世系框标题原来 `tw = min(len(title) * 14 * self.scale, 框宽 - 4)` ——
        #   ① 是**估算**（scale<1 时低估：4 字实际约 52px、却按 45px 画）；
        #   ② 被夹到框宽后**色条变窄而白字不缩**，两端溢出到**浅色画布**上 ⇒
        #      白字消失（与时间轴铭牌已修过的是同型 bug）。
        #   现在用 `kit.est_text_px` 估宽（该函数**故意偏大 8% —— 宁宽不切**），
        #   放不下就**缩字号**：字永远在色条之内，绝不截断、绝不溢出。
        for min_x, min_y, max_x, _, color, title in self._state_boxes:
            if not title:
                continue
            _th, _fs = 16, 10 * self.scale / _dpi.SCALE
            avail = max(24.0, max_x - min_x - 4)
            need = est_text_px(title, _fs) + 10
            if need > avail:
                _fs = max(6.0, _fs * avail / need)
                need = est_text_px(title, _fs) + 10
            tw = min(need, avail)
            cx = min_x + tw / 2 + 8
            ty = min_y + 2 * self.scale
            if band_hit(cx - tw / 2, ty, cx + tw / 2, ty + _th):
                continue
            c.create_rectangle(cx - tw / 2, ty, cx + tw / 2, ty + _th,
                               fill=color, outline=color, tags="boxtitle")
            c.create_text(cx, ty + _th / 2, text=title,
                          font=(theme.font_gen, int(_fs)), fill="#ffffff",
                          tags="boxtitle")
        for min_x, min_y, max_x, _, color, title in self._qing_boxes:
            if not title:
                continue
            _th, _fs = 14, 9 * self.scale / _dpi.SCALE
            avail = max(24.0, max_x - min_x - 4)
            need = est_text_px(title, _fs) + 10
            if need > avail:
                _fs = max(6.0, _fs * avail / need)
                need = est_text_px(title, _fs) + 10
            tw = min(need, avail)
            cx = min_x + tw / 2 + 8
            ty = min_y + 2 * self.scale
            if band_hit(cx - tw / 2, ty, cx + tw / 2, ty + _th):
                continue
            c.create_rectangle(cx - tw / 2, ty, cx + tw / 2, ty + _th,
                               fill=color, outline=color, tags="boxtitle")
            c.create_text(cx, ty + _th / 2, text=title,
                          font=(theme.font_gen, int(_fs)), fill="#ffffff",
                          tags="boxtitle")

        # 2) 代数标签
        # ★ 2026-09-28 代数标签改画到左侧**独立的代数条**（`self.ruler`）上 ——
        #   原先画在主画布 x=20，横向拖动画布会被一起拖走（使用者：「不要被拖走，
        #   我要参考」）。scrollregion 的 y 范围与主画布完全一致 ⇒ 纵向仍然对齐。
        r = self.ruler
        r.delete("all")
        # ★ 2026-09-28 使用者报「第 X 代被盖住了」——真因两条，都在这里：
        #   ① 轴条宽度写死 `_dpi.px(50)`；
        #   ② 轴标签字号乘了 `self.scale`（**画布缩放**）。
        #   轴是**标尺**，字号本不该跟画布缩放走；一旦缩放调大，「一〇〇」这类
        #   三位代数就撑破 50px 的窄条，被画布左右边缘**裁掉**（看着就是"被盖住"）。
        #   修：字号固定（只跟 DPI，不跟缩放）；宽度按**最长标签**动态算。
        GEN_FS = 13                                    # 标尺字号：固定，不随缩放
        labels = [f"第\n{model.num_to_chinese(d)}\n代"
                  for d in range(lay.min_depth, lay.max_depth + 1)]
        widest = max((len(s.split("\n")[1]) for s in labels), default=2)
        rw = max(_dpi.px(50), int(widest * GEN_FS * 1.15 + _dpi.px(12)))
        try:
            r.configure(width=rw)
        except Exception:
            pass
        r.config(scrollregion=(0, lay.scroll_y_start, rw, lay.scroll_y_end))
        for d, text in zip(range(lay.min_depth, lay.max_depth + 1), labels):
            y_pos = lay.scroll_y_start + lay.top_margin + (d - lay.min_depth) * lay.level_height
            r.create_text(rw / 2, y_pos, text=text,
                          font=(theme.font_gen, GEN_FS, "bold"),
                          fill=theme.text)
        try:
            r.yview_moveto(self.canvas.yview()[0])   # 重绘后与主画布纵向对齐
        except Exception:
            pass

        # 3) 连线 + 7) 人物框：**按需绘制**（★ 2026-09-26）
        #    一次性遍历 13,526 人要画 79k 个 canvas item（真窗口实测 70~86 秒）；
        #    改为「画布上只留视口 ± 半屏内的人」（见 `_paint_viewport`）：
        #      · 打开只画视口内 ⇒ 秒开，且一开就有内容；
        #      · 滚到 / 拖到哪就补哪、走远的删掉 ⇒ 永远不空白、item 数恒定；
        #      · 滚轮 / 滚动条 / scan 拖动 / 跳转都会触发重排。
        #    层次靠 tag 维持（每批末尾统一提升）：
        #      link < node < boxtitle < searchhit < popcard
        self._drawn_links = set()
        self._drawn_people = set()
        # ★ 2026-09-26 修「父子不连线」（见 __init__）：整重绘时按谱重建三张
        #   反向索引 —— 子索引（父/母 → 子女）、推定父反查、义亲反查。
        self._children_index = {}
        self._guess_rev = {}
        self._assoc_rev = {}
        for n, info in people.items():
            f = info.get("father", "")
            m = info.get("mother", "")
            if f:
                self._children_index.setdefault(f, []).append(n)
            if m and m != f:
                self._children_index.setdefault(m, []).append(n)
            g = info.get("father_guess")
            if g:
                self._guess_rev.setdefault(g, []).append(n)
            a = info.get("associate_of")
            if a:
                self._assoc_rev.setdefault(a, []).append(n)
        # 整重绘 = 画布已清空：按需绘制重算「视口 ± 半屏」该有谁（不再全量补完）
        self._paint_viewport()
        # ★ 2026-09-26 按需绘制后必须补这一步：谱系的**左上角常常是空白**
        #   （始祖居中、后代向两侧散开），视口停在 (0,0) 时**这屏一个人都没有**
        #   —— 打开就是一块白板。这屏没人就把视图移到内容起点（最上一代最左者）。
        #   ⚠️ 判据是「**视口内**没人」（不是"画布上没人"：兜底会画几个，
        #   但那几个常常在视口外，等于没画）；且只在整重绘时判 —— 用户自己
        #   滚到空白区时不能把镜头抢回来。
        vx0, vy0, vx1, vy1 = self._viewport_rect()
        if not any(vx0 <= x <= vx1 and vy0 <= y <= vy1
                   for x, y in lay.positions.values()):
            # 定位到**人最多的世系框**的中心 —— 别停在"最上一代最左者"那种
            # 孤零零的先祖上（实测那样打开只见一个"风伏羲"和一条长虚线）。
            if self._state_boxes:
                bx0, by0, bx1, by1 = max(
                    ((b[0], b[1], b[2], b[3]) for b in self._state_boxes),
                    key=lambda e: (e[2] - e[0]) * (e[3] - e[1]))
                self._center_on((bx0 + bx1) / 2.0, (by0 + by1) / 2.0)
            else:
                top = min(lay.positions,
                          key=lambda n: (lay.positions[n][1], lay.positions[n][0]))
                self.scroll_to(top)

        # 8) 搜索命中环（画在节点之上、浮卡之下）
        self._paint_hits()

        # 9) 选中浮卡
        if self.selected in lay.positions:
            self._mark_selected(self.selected, True)
            self._draw_popcard()

    # ------------------------------------------------- 分批绘制（启动优化）
    def _viewport_rect(self):
        """画布当前视口（画布坐标）：(x0, y0, x1, y1)。

        画布还没拿到尺寸时（启动首帧常见 1×1）退回一个「首屏大小」的假视口 ——
        否则首屏没人可画、要等第一批补画（用户会觉得"打开了但一片空白"）。
        """
        c = self.canvas
        vw = max(c.winfo_width(), 1)
        vh = max(c.winfo_height(), 1)
        if vw < 50 or vh < 50:
            vw, vh = 1200, 800
        vx, vy = c.canvasx(0), c.canvasy(0)
        return vx, vy, vx + vw, vy + vh

    def _draw_people(self, names):
        """画一批人：节点 + 与已画节点相关的连线（判重）。

        ★ 2026-09-26 启动优化：`_draw` 不再一次性画完 13,526 人（真窗口下
          79k 个 canvas item、要几十秒），改为「首屏立即 + 其余分批」。
        层次：先画 link 再画 node，批末按 tag 统一提层 ——
          link < node < boxtitle < searchhit < popcard。
        """
        if not names:
            return
        c, theme = self.canvas, self.theme
        lay, people = self.lay, self.master.people
        node_h = lay.node_h
        pos = lay.positions
        drawn = self._drawn_links
        gfill = theme.text_3
        sp_line = theme.spouse_line or theme.spouse
        sel = self.selected
        sym = int(15 * self.scale / _dpi.SCALE * 0.7)
        for name in names:
            info = people.get(name) or {}
            if name not in pos:
                continue
            x2, y2 = pos[name]
            # ---- 父子 / 母子线 ----
            # ★ 2026-09-26 按需绘制：连线的 tag 一律带上**两端的人名**
            #   （`p_父` / `p_子`）—— 任一端滚出视口被淘汰时，整条线随 tag 一起
            #   删掉；否则会留下悬空线（另一端已不在画布上）。
            if not info.get("hide_parent_line"):
                dad = info.get("father", "")
                if dad in pos and ("f", dad, name) not in drawn:
                    drawn.add(("f", dad, name))
                    x1, y1 = pos[dad]
                    c.create_line(x1, y1 + node_h / 2, x2, y2 - node_h / 2,
                                  fill=theme.tree_line, width=int(2 * self.scale),
                                  tags=("link", f"p_{name}", f"p_{dad}"))
                mom = info.get("mother", "")
                if mom in pos and ("m", mom, name) not in drawn:
                    drawn.add(("m", mom, name))
                    x1, y1 = pos[mom]
                    c.create_line(x1, y1 + node_h / 2, x2, y2 - node_h / 2,
                                  fill=theme.spouse, dash=(4, 2),
                                  width=int(1 * self.scale),
                                  tags=("link", f"p_{name}", f"p_{mom}"))
            # ---- 推定世系（点划线 + 两端圆点；与选中相关时加字）----
            g = info.get("father_guess", "")
            if g and g in pos and ("g", g, name) not in drawn:
                drawn.add(("g", g, name))
                x1, y1 = pos[g]
                near = (name == sel or g == sel)
                c.create_line(x1, y1 + node_h / 2, x2, y2 - node_h / 2,
                              fill=gfill,
                              width=max(2, int((2.2 if near else 1.8) * self.scale)),
                              dash=(7, 3, 1, 3),
                              tags=("link", f"p_{name}", f"p_{g}"))
                r_dot = max(2, int(2.6 * self.scale))
                for _px, _py in ((x1, y1 + node_h / 2), (x2, y2 - node_h / 2)):
                    c.create_oval(_px - r_dot, _py - r_dot, _px + r_dot, _py + r_dot,
                                  fill=gfill, outline="",
                                  tags=("link", f"p_{name}", f"p_{g}"))
                if near:
                    c.create_text((x1 + x2) / 2, (y1 + y2) / 2, text="推定世系",
                                  font=(theme.font_ui_fallback,
                                        int(12 * self.scale / _dpi.SCALE * 0.8)),
                                  fill=gfill,
                                  tags=("linktext", f"p_{name}", f"p_{g}"))
            # ---- 同代人符号（夫妻♥ / 朋友友）----
            ref = info.get("associate_of", "")
            atype = info.get("associate_type", "clan")
            if (atype != "clan" and ref and ref != name and ref in pos
                    and ("a",) + tuple(sorted((name, ref))) not in drawn):
                drawn.add(("a",) + tuple(sorted((name, ref))))
                x1, y1 = pos[ref]
                mid_x = (x1 + x2) / 2
                bottom_y = max(y1, y2) + node_h / 2 + 1 + sym / 2
                text = "♥" if atype == "spouse" else "友"
                color = theme.spouse if atype == "spouse" else theme.accent
                c.create_text(mid_x, bottom_y, text=text,
                              font=(theme.font_name, sym, "bold"), fill=color,
                              tags=("linktext", f"p_{name}", f"p_{ref}"))
            # ---- 跨树夫妻 U 型线（对称关系，判重）----
            for s in (info.get("spouses") or []):
                key = ("s",) + tuple(sorted((name, s)))
                if s in pos and key not in drawn:
                    drawn.add(key)
                    x1, y1 = pos[name]
                    x3, y3 = pos[s]
                    b1, b2 = y1 + node_h / 2, y3 + node_h / 2
                    drop_y = max(b1, b2) + 8 * self.scale
                    c.create_line(x1, b1, x1, drop_y, x3, drop_y, x3, b2,
                                  fill=sp_line,
                                  width=max(1, int(1.5 * self.scale)),
                                  dash=(4, 2),
                                  tags=("link", f"p_{name}", f"p_{s}"))
                    c.create_text((x1 + x3) / 2, drop_y + 2 * self.scale, text="♥",
                                  font=(theme.font_name,
                                        int(15 * self.scale / _dpi.SCALE * 0.85), "bold"),
                                  fill=sp_line,
                                  tags=("linktext", f"p_{name}", f"p_{s}"))
            # ---- 向下：子女连线（父/母/推定父 → 已在布局的子女）----
            # ★ 2026-09-26 修「父子不连线」（使用者截图：魏击/魏挚与魏罃/魏缓/
            #   魏长卿之间断线）：连线归「子」所有，父滚出视口被淘汰时
            #   `delete(p_父)` 把已画子女的父线一并带走；父滚回来时本循环只重画
            #   「父自己向上」的线，向下到**已画子女**的线没人补。用三张反向索引
            #   在这里补齐（`drawn` 判重保证与子女自己的向上线不会重复）。
            for child in self._children_index.get(name, ()):
                if child not in pos or child == name:
                    continue
                cinfo = people.get(child) or {}
                if cinfo.get("hide_parent_line"):
                    continue
                cx, cy = pos[child]
                if cinfo.get("father") == name:
                    key = ("f", name, child)
                    if key in drawn:
                        continue
                    drawn.add(key)
                    c.create_line(x2, y2 + node_h / 2, cx, cy - node_h / 2,
                                  fill=theme.tree_line, width=int(2 * self.scale),
                                  tags=("link", f"p_{child}", f"p_{name}"))
                elif cinfo.get("mother") == name:
                    key = ("m", name, child)
                    if key in drawn:
                        continue
                    drawn.add(key)
                    c.create_line(x2, y2 + node_h / 2, cx, cy - node_h / 2,
                                  fill=theme.spouse, dash=(4, 2),
                                  width=int(1 * self.scale),
                                  tags=("link", f"p_{child}", f"p_{name}"))
            for child in self._guess_rev.get(name, ()):
                if child not in pos:
                    continue
                cinfo = people.get(child) or {}
                if (cinfo.get("father_guess") != name
                        or cinfo.get("hide_parent_line")):
                    continue
                key = ("g", name, child)
                if key in drawn:
                    continue
                drawn.add(key)
                cx, cy = pos[child]
                near = (child == sel or name == sel)
                c.create_line(x2, y2 + node_h / 2, cx, cy - node_h / 2,
                              fill=gfill,
                              width=max(2, int((2.2 if near else 1.8) * self.scale)),
                              dash=(7, 3, 1, 3),
                              tags=("link", f"p_{child}", f"p_{name}"))
                r_dot = max(2, int(2.6 * self.scale))
                for _px, _py in ((x2, y2 + node_h / 2), (cx, cy - node_h / 2)):
                    c.create_oval(_px - r_dot, _py - r_dot,
                                  _px + r_dot, _py + r_dot,
                                  fill=gfill, outline="",
                                  tags=("link", f"p_{child}", f"p_{name}"))
                if near:
                    c.create_text((x2 + cx) / 2, (y2 + cy) / 2, text="推定世系",
                                  font=(theme.font_ui_fallback,
                                        int(12 * self.scale / _dpi.SCALE * 0.8)),
                                  fill=gfill,
                                  tags=("linktext", f"p_{child}", f"p_{name}"))
            for dep in self._assoc_rev.get(name, ()):
                if dep not in pos or dep == name:
                    continue
                dinfo = people.get(dep) or {}
                ref2 = dinfo.get("associate_of", "")
                atype2 = dinfo.get("associate_type", "clan")
                if atype2 == "clan" or not ref2 or ref2 != name:
                    continue
                key = ("a",) + tuple(sorted((name, dep)))
                if key in drawn:
                    continue
                drawn.add(key)
                dx, dy = pos[dep]
                mid_x = (x2 + dx) / 2
                bottom_y = max(y2, dy) + node_h / 2 + 1 + sym / 2
                text = "♥" if atype2 == "spouse" else "友"
                color = theme.spouse if atype2 == "spouse" else theme.accent
                c.create_text(mid_x, bottom_y, text=text,
                              font=(theme.font_name, sym, "bold"), fill=color,
                              tags=("linktext", f"p_{dep}", f"p_{name}"))
            # ---- 节点 ----
            if name not in self._drawn_people:
                self._drawn_people.add(name)
                self._draw_node(name, x2, y2, node_h, lay.name_width)
        # 批末统一提层（线 < 节点 < 连线文字 < 框题 < 命中环 < 浮卡）
        # ★ 2026-09-28 全项目整理（第 2 批，铁律②「没有任何汉字被遮盖」）：
        #   新增 **`linktext` 层** —— 「推定世系 / ♥ / 友」这几个字原来挂在 `link`
        #   tag 上，而 `link` **永不在提层列表里**（它含大量连线，必须留在节点之下），
        #   于是这些字被后画的 `node` 不透明矩形（女性粉底 / 已故灰底）压住 ——
        #   与「名字被粉底盖」是**同一个病根，只是换了 tag**。
        #   现在文字单独一层，且**在 node 之上**（线仍在节点之下，层次不变）。
        # ★ 2026-09-28：`locatering`（「定位人物」的琥珀闪圈）也放进提层序列的
        #   最后 —— 否则按需绘制重排时它会被 node/box 压住，跳过来的人找不到
        #   那块牌子（使用者报「定位不到」的一半就是"看不见闪圈"）。
        for tag in ("node", "linktext", "boxtitle", "searchhit", "popcard",
                    "locatering"):
            try:
                c.tag_raise(tag)
            except Exception:
                pass

    def _schedule_paint(self, delay=40):
        """安排一次「按需绘制」重排（去抖）——滚动/拖动会连发，别每像素算一次。

        ⚠️ `TreeView` 是**普通对象**（不是 tk 控件）—— 必须走 `canvas.after`；
        踩过：写成 `self.after(...)` 直接 AttributeError，被兜底 except 吃掉，
        结果永远不补画（实测一万多人一动不动）。
        """
        if getattr(self, "_paint_job", None) is not None:
            return
        try:
            self._paint_job = self.canvas.after(delay, self._run_paint)
        except Exception:
            self._paint_job = None

    def _run_paint(self):
        self._paint_job = None
        self._paint_viewport()

    def _on_yscroll(self, *args):
        self._vbar.set(*args)             # 原行为：滚动条滑块位置
        # ★ 2026-09-28 代数条**只**跟随纵向滚动（横向拖画布它不动）——
        #   两边的 scrollregion y 范围一致，所以同一套 (first, last) 直接可用。
        try:
            self.ruler.yview_moveto(args[0])
        except Exception:
            pass
        self._schedule_paint()            # 视口变了 → 安排补画

    def _on_xscroll(self, *args):
        self._hbar.set(*args)
        self._schedule_paint()

    def _paint_viewport(self):
        """按需绘制：画布上**只留「视口 ± 半屏」里的人**（连同他们的连线）。

        取代了"把全谱 13,526 人分批画完"的旧方案（使用者实测它有三个病：
        打开后画不完、滚动不补、拖动不补）：
          · 打开只画视口内（几百人）⇒ 秒开，且**一开就有内容**；
          · 滚到 / 拖到哪里，下一拍就补哪里、把走远的删掉 ⇒ **永远不空白**；
          · canvas item 数恒定在几千 ⇒ 拖动不会越拖越沉。
        线随人走：连线的 tag 带两端人名（`p_父` / `p_子`），删人时整条一并删干净。
        """
        if self.lay is None or not self.lay.positions:
            return
        c = self.canvas
        pos = self.lay.positions
        vx0, vy0, vx1, vy1 = self._viewport_rect()
        pad_x, pad_y = (vx1 - vx0) * 0.5, (vy1 - vy0) * 0.5
        x0, y0, x1, y1 = vx0 - pad_x, vy0 - pad_y, vx1 + pad_x, vy1 + pad_y
        keep = {n for n, (x, y) in pos.items() if x0 <= x <= x1 and y0 <= y <= y1}

        # ---- 淘汰（tag 带两端人名，删一个名字就把「沾亲」的线一并带走）----
        gone = [n for n in self._drawn_people if n not in keep]
        for n in gone:
            try:
                c.delete(f"p_{n}")
            except Exception:
                pass
            self._drawn_people.discard(n)
            self.person_rect.pop(n, None)
        if gone:
            gone_set = set(gone)
            self._drawn_links = {k for k in self._drawn_links
                                 if not (gone_set & set(k))}

        # ---- 补齐（由视口中心向外；单拍最多 800 人，多余的下拍继续）----
        # ⚠️ 曾经在这里给「视口内没人」做个兜底（画最近的一小撮免得白板）——
        #   结果是死循环：那些人在视口外，下一拍又被淘汰、再兜底再画。
        #   「打开时别白板」由 `_draw` 末尾的**自动定位到内容起点**负责（只做一次）。
        todo = [n for n in keep if n not in self._drawn_people]
        if todo:
            cx, cy = (vx0 + vx1) / 2.0, (vy0 + vy1) / 2.0
            todo.sort(key=lambda n: abs(pos[n][0] - cx) + abs(pos[n][1] - cy))
            try:
                self._draw_people(todo[:800])
            except Exception as e:
                # 某个人画不出来也不能拖垮整拍（跳过他，下一拍还会再遇到）
                logger.warning("按需绘制跳过一批：%r", e)
            if len(todo) > 800:
                self._schedule_paint(1)

        # ---- 选中标记与搜索命中环跟着补（刚补画的人身上还没有这些装饰）----
        if gone or todo:
            if self.selected in keep:
                try:
                    self._mark_selected(self.selected, True)
                except Exception:
                    pass
            if self.search_hits:
                try:
                    self._paint_hits()
                except Exception:
                    pass

    # ---------------------------------------------------------------- 节点
    def _line_factor(self, family, weight="bold"):
        key = (family, weight)
        if key not in self._line_factor_cache:
            probe = tkfont.Font(family=family, size=10, weight=weight)
            self._line_factor_cache[key] = probe.metrics("linespace") / 10.0
        return self._line_factor_cache[key]

    def _fit(self, text, family, base, usable_h, weight="bold"):
        """把竖排文字压进固定高度（方框恒定，只缩字号）。"""
        if not text or base <= 0:
            return base
        factor = self._line_factor(family, weight)
        return max(self.theme.min_node_font, min(base, int(usable_h / (factor * len(text)))))

    def _draw_dup_mark(self, c, cx, cy, base_name, dup, name_size, tags=None):
        """重名序数角标：小号**灰**字，贴在名字**最后一个字的右上角**（像幂）。

        ★ 2026-09-22 使用者：「改成数字右上角角标灰色123吧，像幂一样那种」。
          原来是带圈数字、贴在**右下角**、跟名字同色 —— 现在改成
          纯数字 + 右上角 + 灰色（`theme.text_3`），字号按名字的 0.62 倍。

        竖排文本是「一个字一行」，整块以 (cx, cy) 为中心：
          最后一行中心 y = cy + (N-1) × 行高 / 2
          最后一字的右缘 x = cx + 字宽 / 2
        角标就落在这个点的**右上方**一点点。
        """
        lf = self._line_factor(self.theme.font_name, "bold")
        # 全角汉字宽 ≈ 字号 × (96/72)，Tk 的 point→pixel 就是这个比例
        cw = name_size * 96.0 / 72.0
        n = max(1, len(base_name))
        size = max(7, int(round(name_size * 0.62)))
        c.create_text(cx + cw * 0.52,
                      cy + (n - 1) * lf * name_size / 2.0 - name_size * 0.32,
                      text=dup, font=(self.theme.font_name, size, "bold"),
                      fill=self.theme.text_3, anchor="center", tags=tags)

    def _node_outline(self, name):
        """节点常规描边色。

        经典版：宗支色优先（v1 原版画法），无宗支色则用通用描边 —— 保持原样。
        卡片版：一律中性描边。卡片上已经有一条左侧爵位色条在表达颜色，
        再让描边走宗支色就是两套配色系统叠在同一个节点上，纯粹是视觉噪音。
        """
        theme = self.theme
        # ★ 2026-09-23「选定」高亮：描边也走紫，与底色一起把这个人挑出来
        #   （经典样式没有底色兜底，全靠这条描边）
        if self._is_focused(name):
            return theme.focus_hi
        if self.node_style == "card":
            return theme.node_bd or theme.border_2
        info = self.master.people.get(name)
        if not info:
            return theme.border_2
        bg = info.get("bg_color", "")
        if bg:
            cmap = dict(theme.branch_fg + theme.branch_bg)
            if bg in cmap:
                return cmap[bg]
        return theme.border_2

    def _card_fill(self, name):
        """卡片式节点底色：**选定 > 已故灰 > 女性粉 > 主题卡片底色**。

        ★ 2026-09-23 使用者要求：被「选定（仅显所选）」的人在画布上一眼认出来，
          用**紫色**（theme.focus_bg，与青绿/橙金/品红/琥珀/正红/灰都不撞）。
          优先级最高 —— 它是使用者刚亲手点过的，必须压过已故灰与女性粉。
        """
        info = self.master.people.get(name) or {}
        if self._is_focused(name):
            return self.theme.focus_bg
        # ★ 2026-09-26：本谱若声明「不涂已故灰」（全谱），就不压灰
        #   —— 判据与开关都在 `storage.hide_dead_shade`（四处同规）。
        from .. import storage as _st
        if info.get("death") and not _st.hide_dead_shade(
                getattr(self.master, "current_save", "")):
            return self.theme.bg_dead or self.theme.bg_card
        if info.get("gender", "") == "女":
            return self.theme.female
        return self.theme.node_bg or self.theme.bg_canvas

    def _is_focused(self, name):
        """这个人是否在「选定」高亮集合里（三处高亮共用同一判据）。

        ★ 2026-09-23 使用者纠正：集合 = 手动选定的人 **+ 其全部男性后裔**
          （纯父系谱系）—— 他要看的是「他的谱系」，不是光一个人。
          与是否勾选「仅显所选」无关：那个勾只管过不过滤。
        """
        return name in self.master.focus_set()

    def _draw_node(self, name, x, y, node_h, nw):
        theme = self.theme
        c = self.canvas
        info = self.master.people[name]
        gender = info.get("gender", "")
        # ★ 2026-09-26：上色用爵称走 app/jue.py 的史观口径（不再直接用原文爵位）
        tier = self._tier_of.get(name) or info.get("fief_title", "")
        is_card = self.node_style == "card"

        # ★ 2026-09-26 二修：`lay.node_h = BASE_NODE_H * scale`（layout.py:431）
        #   **已经是乘过缩放的物理像素**，不能再乘 DPI 系数 —— 昨晚误当逻辑值
        #   又乘了一道，可用高度虚大 1.5 倍，_fit 几乎不再缩字，
        #   4 字人名顶满溢出框外（使用者实测「4 字名不再小于 3 字名」）。
        #   本式与物理行高 factor（linespace/10）同尺，原样即正确。
        usable_h = node_h - 2 * theme.node_text_padding * self.scale
        base = int(15 * self.scale / _dpi.SCALE)
        # ★ 2026-09-22 重名序数（纯数字）拆出来单独画成**小号灰字角标**，
        #   贴在名字最后一字的**右上角** —— 它不再算进竖排字数里，
        #   所以字号按**基名**算（基名短一个字，字能更大一点）。
        base_name, dup = split_dup(name)
        name_size = self._fit(base_name, theme.font_name, base, usable_h)

        left, top = x - nw / 2, y - node_h / 2
        right, bottom = x + nw / 2, y + node_h / 2
        tags = ("node", f"p_{name}")
        # 色条最小 2px：缩到 30% 时 3px * 0.3 会被取整兜成 1px，爵位靠颜色区分就废了。
        # 姓名右移半个条宽，视觉上才是正的（按取整后的实际条宽算，小缩放下不会偏）。
        bar = max(2, int(theme.node_bar_w * self.scale)) if is_card else 0
        name_dx = bar / 2

        if is_card:
            # 淡底实心卡 + 圆角；实心底色画在连线之后，正好挡住穿框的线
            rect = _round_rect(c, left, top, right, bottom,
                               theme.node_radius * self.scale,
                               fill=self._card_fill(name),
                               outline=self._node_outline(name),
                               width=int(1 * self.scale), tags=tags)
            # 左侧爵位色条：上下各内缩半个圆角，免得戳出圆角之外
            inset = theme.node_radius * self.scale / 2
            c.create_rectangle(left, top + inset, left + bar, bottom - inset,
                               fill=theme.tier.get(tier, theme.tier["无"]),
                               outline="", tags=tags)
        else:
            # ★ 2026-09-22 已故铭牌压 bg_dead 灰（使用者要求，与表格/时间轴同一判据）；
            #   经典版原本透明，女性粉让位给已故灰 —— 名字颜色仍按性别走
            from .. import storage as _st2
            dead = bool(info.get("death")) and not _st2.hide_dead_shade(
                getattr(self.master, "current_save", ""))
            rect = c.create_rectangle(left, top, right, bottom,
                                      fill=(theme.bg_dead or "") if dead
                                      else (theme.female if gender == "女" else ""),
                                      outline=self._node_outline(name),
                                      width=int(1 * self.scale), tags=tags)
            decor = TIER_DECOR.get(tier)
            if decor:
                c.create_line(left + 2, top, right - 2, top,
                              fill=decor[0], width=int(2 * self.scale))

        self.person_rect[name] = rect

        # ★ 2026-09-21 使用者要求「女性角色名字在任何地方都标红」。
        #   所以女性一律用 spouse 色，压过爵位色（女性持爵极少，红字更好认）。
        if gender == "女":
            name_color = theme.spouse
        else:
            name_color = theme.tier.get(tier, theme.text)
            note = info.get("note") or ""
            if info.get("divine") == "是" or "神" in note or note.endswith("氏"):
                name_color = theme.divine
        note = info.get("note") or ""
        # 竖排单列：逐字换行，绝不传 width
        # ★ 2026-09-26 使用者实测「拖到女性角色那里名字不显示」——真因是**这些
        #   create_* 一个都没带 `tags`**：批末 `tag_raise("node")` 只提升带 node
        #   tag 的矩形，于是名字/「史」徽标/世代数字/尊号全被压在**后来画的
        #   不透明矩形**之下。男性节点底是透明（`fill=""`）所以看不出来，
        #   女性是粉底、已故是灰底 —— 正好把名字盖得严严实实。
        #   现在一律带上 `tags`（= node + p_人名），既跟着提层，也随人一起删。
        c.create_text(x + name_dx, y, text="\n".join(base_name),
                      font=(theme.font_name, name_size, "bold"), fill=name_color,
                      tags=tags)
        if dup:
            self._draw_dup_mark(c, x + name_dx, y, base_name, dup, name_size,
                                tags=tags)

        if info.get("historical", "是") == "是":
            hs = int(base * 0.7)
            hx, hy = x - nw / 4, y - node_h / 2 - 4 - hs / 2
            pad = 2
            c.create_rectangle(hx - hs / 2 - pad, hy - hs / 2 - pad,
                               hx + hs / 2 + pad, hy + hs / 2 + pad,
                               fill=theme.bg_canvas, outline=theme.bg_canvas,
                               tags=tags)
            c.create_text(hx, hy, text="史", font=(theme.font_name, hs, "bold"),
                          fill=theme.hist or theme.divine, tags=tags)

        fg = info.get("fief_gen", 0)
        if fg > 0:
            fs = int(base * 0.7)
            gx, gy = x + nw / 4, y + node_h / 2 + 4 + fs / 2
            pad = 2
            c.create_rectangle(gx - fs / 2 - pad, gy - fs / 2 - pad,
                               gx + fs * len(str(fg)) / 2 + pad, gy + fs / 2 + pad,
                               fill=theme.bg_canvas, outline=theme.bg_canvas,
                               tags=tags)
            c.create_text(gx, gy, text=str(fg),
                          font=("Arial Narrow", fs, "bold"), fill=theme.text_2,
                          tags=tags)

        if note:
            nsize = self._fit(note, theme.font_note, int(base * 0.7), usable_h)
            c.create_text(x + nw / 2 + 6, y, text="\n".join(note),
                          font=(theme.font_note, nsize, "bold"),
                          fill=theme.spouse if gender == "女" else theme.text_2,
                          tags=tags)

    # ---------------------------------------------------------------- 选中态
    def _mark_selected(self, name, on):
        """选中高亮。经典版只加粗红描边；卡片版整卡高亮（描边 + 淡底）。"""
        rect = self.person_rect.get(name)
        if rect is None:
            return
        theme = self.theme
        if not on:
            self.canvas.itemconfig(rect, outline=self._node_outline(name),
                                   width=int(1 * self.scale))
            if self.node_style == "card":
                self.canvas.itemconfig(rect, fill=self._card_fill(name))
            return
        if self.node_style == "card":
            self.canvas.itemconfig(rect, outline=theme.danger,
                                   width=int(2 * self.scale),
                                   fill=theme.danger_soft)
        else:
            self.canvas.itemconfig(rect, outline=theme.danger,
                                   width=int(3 * self.scale))

    # ---------------------------------------------------------------- 浮卡
    def hide_popcard(self):
        """清掉浮卡（画布图元 + 内嵌控件）。"""
        self.canvas.delete("popcard")
        if self._pop_widget is not None:
            try:
                self._pop_widget.destroy()
            except tk.TclError:
                pass
            self._pop_widget = None

    def _draw_popcard(self):
        """选中人物小传卡：卡片本身由 `widgets/popcard.build_popcard` 拼，
        这里只负责「摆在哪」—— ★ 2026-09-23 改为固定贴在**视口右下角**
        （原来是锚节点右侧，滚动/缩放时卡片乱跑；右下角不遮人）。"""
        self.hide_popcard()

        name = self.selected
        lay = self.lay
        if not name or lay is None or name not in lay.positions:
            return

        built = build_popcard(self.canvas, self.theme, self.master.people, name)
        if built is None:
            return
        card, w, h = built

        vw = self.canvas.winfo_width()
        vh = self.canvas.winfo_height()
        if vw > 50 and vh > 50:
            # 视口右下角：贴画布当前可见区的右下，留 12px 边距
            px = self.canvas.canvasx(0) + vw - w - 12
            py = self.canvas.canvasy(0) + vh - h - 12
        else:
            x, y = lay.positions[name]
            px = x + lay.name_width / 2 + 10
            py = y - lay.node_h / 2
        self.canvas.create_window(px, py, window=card, anchor="nw", tags="popcard")
        self._pop_widget = card

    # ---------------------------------------------------------------- 搜索命中
    def set_search_hits(self, hits, current=None):
        """登记搜索命中集合。登记后每次重绘都会把命中节点标出来。"""
        self.search_hits = [n for n in hits if n in self.master.people]
        self.search_index = self.search_hits.index(current) if current in self.search_hits else -1

    def clear_search_hits(self):
        self.search_hits = []
        self.search_index = -1
        self.canvas.delete("searchhit")

    def _paint_hits(self):
        """命中环：当前停留的一枚是实线粗环，其余是虚线细环。

        环画在节点外侧，不遮姓名；颜色走主题主色，与"选中"的红色描边区分开
        （当前命中同时也是选中项，两套标记叠在一起正好互相印证）。
        """
        c = self.canvas
        c.delete("searchhit")
        if self.lay is None or not self.search_hits:
            return
        theme = self.theme
        pad = 4 * self.scale
        for i, name in enumerate(self.search_hits):
            pos = self.lay.positions.get(name)
            if pos is None:         # 被过滤/截断隐藏了，画布上没有这个节点
                continue
            x, y = pos
            current = (i == self.search_index)
            kw = {} if current else {"dash": (3, 2)}
            c.create_rectangle(
                x - self.lay.name_width / 2 - pad, y - self.lay.node_h / 2 - pad,
                x + self.lay.name_width / 2 + pad, y + self.lay.node_h / 2 + pad,
                outline=theme.accent_2 if current else theme.accent,
                width=int((3 if current else 2) * self.scale),
                # ★ 2026-09-26 按需绘制：环也带上人名 tag —— 人滚出视口被删时，
                #   环跟着一起删（否则画布上会留下一个悬空圈）
                tags=("searchhit", f"p_{name}"), **kw)

    def goto_hit(self, step):
        """在命中之间逐个跳转，返回跳到的名字。

        step: 0 第一个 / +1 下一个（循环）/ -1 上一个（循环）。
        命中里可能有一部分被隐藏了（非史实后裔、截断、祖先不在可见区），
        只在画布上真实存在的节点之间跳，免得跳到一片空白处。
        """
        if self.lay is None or not self.search_hits:
            return None
        avail = [n for n in self.search_hits if n in self.lay.positions]
        if not avail:
            return None
        cur = self.search_hits[self.search_index] \
            if 0 <= self.search_index < len(self.search_hits) else None
        if step and cur in avail:
            idx = (avail.index(cur) + (1 if step > 0 else -1)) % len(avail)
        else:
            idx = 0 if step >= 0 else len(avail) - 1
        target = avail[idx]
        self.search_index = self.search_hits.index(target)
        self.master.select_person(target)      # 侧栏 / 选中高亮 / 浮卡一起跟上
        self.scroll_to(target)
        self._paint_hits()
        return target

    # ================================================================ 交互
    def _hit(self, x, y):
        for item in self.canvas.find_overlapping(x - 10, y - 10, x + 10, y + 10):
            for tag in self.canvas.gettags(item):
                if tag.startswith("p_"):
                    return tag[2:]
        return None

    def highlight_selection(self):
        """只更新描边/底色，不整树重绘。"""
        for name in self.person_rect:
            self._mark_selected(name, name == self.selected)

    def _center_on(self, x, y, _tries=0):
        """把视图中心移到画布坐标 (x, y)，并立刻重排一次（别等人对着空白等去抖）。

        ★ 2026-09-28 使用者报「**双击人物转家谱页后 定位不到家族树上的人**」——
          真因就在这里：从人物页双击跳过来时，`switch_view("tree")` 刚把画布
          **建出来**，`winfo_width()` 还是 1（首帧未定尺）。原来遇到这种情况直接
          按 1400×860 **估算**着滚 —— 等真实尺寸定下来，视口早就偏了，
          人根本没在屏幕中央（状态栏还说"已定位"）。
          现在：**尺寸未定就等一帧再来**（最多 5 次），拿到真实尺寸才滚。
        """
        if self.lay is None:
            return
        vw = self.canvas.winfo_width()
        vh = self.canvas.winfo_height()
        if (vw < 50 or vh < 50) and _tries < 5:
            try:
                self.canvas.after_idle(
                    lambda: self._center_on(x, y, _tries + 1))
            except Exception:
                pass
            return
        if vw < 50 or vh < 50:            # 兜底：始终拿不到尺寸就按常规窗口估
            vw, vh = 1400, 860
        total_w = max(1, self.lay.scroll_x)
        total_h = max(1, self.lay.scroll_y_end - self.lay.scroll_y_start)
        self.canvas.xview_moveto(max(0.0, (x - vw / 2) / total_w))
        self.canvas.yview_moveto(max(0.0, (y - self.lay.scroll_y_start - vh / 2) / total_h))
        self._paint_viewport()

    def scroll_to(self, name):
        if self.lay is None or name not in self.lay.positions:
            return
        self._center_on(*self.lay.positions[name])

    def export_full(self, path_prefix, on_progress=None, max_side=16000):
        """★ 2026-09-27 v3 整块画布导出（使用者思路：虚拟超级大屏）。

        收起侧栏 → 把主窗口临时拉成「画布全宽 × 全高」的超级大窗
        （Windows 允许窗口超出物理屏幕；上限 16000px = 显存上限），
        PrintWindow (PW_RENDERFULLCONTENT) 让窗口自己渲染进缓冲 ——
        被遮挡、超出屏幕都正确，一屏全收（代数标签在画布坐标系里）。
        画布超过 16000px 才沿该方向分屏。内容不缩放，分辨率与屏上一致。
        """
        import math
        from PIL import Image
        from app import wincap
        if self.lay is None:
            raise RuntimeError("画布还没有布局（先打开一个谱牒）")
        c = self.canvas
        top = c.winfo_toplevel()
        total_w = max(1, int(self.lay.scroll_x))
        total_h = max(1, int(self.lay.scroll_y_end - self.lay.scroll_y_start))
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
            new_w = min(max_side, max(rel_x + total_w + 12, c.winfo_width()))
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
                    self._paint_viewport()
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
            self._paint_viewport()
        return files

    def flash_node(self, name):
        """★ 2026-09-26「定位人物」：在目标铭牌外画一圈琥珀色高亮框，
        2.6 秒后自动消失 —— 画布上人多，光居中还是找不着那块牌子
        （使用者报「双击跳过来找不到节点」）。"""
        if self.lay is None or name not in self.lay.positions:
            return
        c = self.canvas
        c.delete("locatering")
        x, y = self.lay.positions[name]
        nw = max(self.lay.name_width, 40) * 1.5
        nh = max(self.lay.node_h, 40) * 1.15
        # ★ 2026-09-27：闪圈加粗加长（2.6s → 6s）—— 使用者仍报找不到节点
        c.create_rectangle(x - nw / 2 - 7, y - nh / 2 - 7,
                           x + nw / 2 + 7, y + nh / 2 + 7,
                           outline="#e6a23c", width=max(3, int(3 * _dpi.SCALE)),
                           tags="locatering")
        c.tag_raise("locatering")
        if getattr(self, "_locate_job", None):
            try:
                c.after_cancel(self._locate_job)
            except Exception:
                pass
        self._locate_job = c.after(6000, lambda: c.delete("locatering"))

    def zoom(self, direction):
        """缩放。direction: 1 放大 / -1 缩小 / 0 回到 100%。按 10% 步进。"""
        self._user_zoomed = True      # 手动缩放后不再自动铺满（2026-09-23）
        if direction == 0:
            ratio = 1.0
        else:
            cur = self.scale / BASE_SCALE
            ratio = round(cur + ZOOM_STEP * (1 if direction > 0 else -1), 2)
            ratio = max(ZOOM_MIN, min(ZOOM_MAX, ratio))
        self.scale = BASE_SCALE * ratio
        self.rerender(skip_collision=True)
        self.master.on_layout_changed()
        return self.scale

    def zoom_percent(self):
        return round(self.scale / BASE_SCALE * 100)

    # ---------------------------------------------------------------- 事件
    def _on_click(self, event):
        self.canvas.scan_mark(event.x, event.y)
        name = self._hit(self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        if name:
            self.master.select_person(name)
        else:
            self.master.clear_selection()

    def _on_drag(self, event):
        self.canvas.scan_dragto(event.x, event.y, gain=1)
        # 拖动中也要排补画（scan_dragto 不一定触发 scrollcommand）
        self._schedule_paint()

    def _on_wheel(self, event):
        if event.state & 4:  # Ctrl + 滚轮 = 缩放
            if self._zoom_after_id:
                self.master.root.after_cancel(self._zoom_after_id)
            self._zoom_after_id = self.master.root.after(80, lambda: self.zoom(1 if event.delta > 0 else -1))
            self._zoom_after_id = None
        else:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_right_click(self, event):
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
