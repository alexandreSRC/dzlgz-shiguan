"""表格页 —— 谱牒层的 Excel 化工作台，**同时兼任「人物页」**（M1 决策 2 + 使用者第 8 问）。

为什么要合并（使用者原话）：
  > 人物和表格这两个 label 的功能似乎也大同小异，你看看是否需要合并，
  > 以表格为基础，合并人物中的不同信息。

原来的分工是：
  · 人物页（实录层）= 选表族 → 看游戏原始表 → 右侧全字段详情
  · 表格页（谱牒层）= 谱牒 11 列 → 批量改 / 改史实 / 改封国

两者确实是**同一件事的两个半张脸**：都是「一个人一行、旁边看详情」。
合并后以表格为**基座**，把人物页的两样东西搬进来：
  1. **右侧档案抽屉**（可折叠）—— 复用 `profiles.Profile`，显示 11 项以上中文档案、
     史实/非史实徽标、关系跳转、后裔数、入谱按钮；
  2. **表族切换**（可选）—— 想看游戏原始表时不必再切页。

保留表格原有全部能力：分级折叠、列排序、批量改、复制粘贴、列设置、单元格编辑。

Excel 对应关系：
  行=人物 列=属性 序号列 分级折叠 自动筛选 冻结首两列
  数据验证下拉 条件格式 区域复制粘贴 祖序自动位移
"""
import logging
import math
import tkinter as tk
from tkinter import ttk

from ..widgets import msgbox as messagebox

from .. import dpi as _dpi
from .. import model
from .. import profiles as PF
from ..labels import plain_name
from ..theme import TIER_NAMES
from ..widgets.kit import FlatButton, est_text_px, input_box, text_label

logger = logging.getLogger(__name__)

# 可编辑列的编辑控件类型
EDIT_KIND = {
    "gender": "enum",
    "fief_title": "enum",
    "historical": "enum",
    "divine": "enum",
    "father": "ref",
    "mother": "ref",
    "spouses": "multi_ref",
    "generation": "num",
    "rank": "num",
    "fief_gen": "num",
    "root_sort": "num",
}

DRAWER_W = _dpi.px(330)              # 右侧档案抽屉宽度


def _tip(widget, text):
    """轻量 Tooltip（表格页独立于 person_view，不能跨模块借它的 Tooltip）。"""
    try:
        from .person_view import Tooltip
        Tooltip(widget, text)
    except Exception:
        pass


def life_text(info, only_death=False):
    """卒年（或「生年 / 卒年」整串）的**统一口径**：真实卒年优先，缺失时用「生年 + 享年」推定。

    ★ 2026-09-26 使用者实测报「A 没修好、很多人仍没卒年」的真因 ——
      游戏对**在世**人物不写卒年（`Ren_End_Time=None`），只写 `Ren_End_Old`（享年）；
      人物页（实录层 `profiles.Profile`）本来就会推算，而**谱牒层的两条路径**
      （表格的 `__life__` 列、档案抽屉的兜底分支）原来只认 `death` 字段
      ⇒ 合并谱里那 23% 的人永远显示「—」。
      ⚠️ 与**判定**逻辑无关：已故涂灰 / 隐藏已故仍只认真实 `death`（见 layout、tree_view）。
    ⚠️ 推定值**不加括注** —— 九十三批续十二使用者裁定「括注一律不要」（依据
      改由「天寿」属性承载）；我当日首版加的「（推定）」已按此撤销。
    """
    birth = str(info.get("birth") or "")
    death = str(info.get("death") or "")
    if not death.strip():
        eo = (info.get("extra") or {}).get("Ren_End_Old")
        if eo not in (None, "", 0):
            d, _why = PF.calc_death(birth, eo)
            if d:
                death = d
    if only_death:
        return death
    bits = [birth or "—", death or "—"]
    grp = info.get("state_group", "")
    if grp:
        bits.append(grp)
    return " / ".join(bits)


def archive_rows(app, name, info):
    """谱牒里某个人 → `(档案行, 实录编号)`。

    这就是「合并人物页的不同信息」的落地。表格页原本只有 11 列裸字段，
    这里把人物页那套**全中文档案**搬进来：智略 / 等级 / 文化 / 性格 / 势力 /
    世代 / 所在 / 生卒（卒年按生年+享年推定）。

    取数链路（按优先级）：
      1. **实录层派生表** `app.record_people` —— 那是 `profiles.Profile`，
         字段最全、口径与人物页完全一致。**按姓名匹配**（谱牒档没有 code 锚点，
         实测《秦末起义·史实》3233 条里带 code 的 0 条）。
      2. 实录层没这个人（纯手写）→ 退回谱牒裸字段 + 中文标签。

    返回 `([(标签, 值)], code)`；`code` 给「入谱 / 查档 / 关系」三条桥用。
    """
    rec = dict(info or {})
    rec["name"] = name
    # --- 1) 去实录层找同名的人（拿最全的档案 + 编号）---
    pool = getattr(app, "record_people", None) or {}
    code = ""
    if pool:
        idx = getattr(app, "_archive_name_index", None)
        if idx is None or len(idx) != len(pool):
            idx = {}
            for c, prof in pool.items():
                nm = ""
                try:
                    nm = prof.name or ""
                except Exception:
                    nm = ""
                if nm:
                    idx.setdefault(nm, c)
            app._archive_name_index = idx
        code = str(idx.get(name, "") or "")
    if code and code in pool:
        try:
            rows = pool[code].rows()
            if rows:
                return rows, code
        except Exception as e:
            logger.warning(f"实录档案派生失败: {e}")

    # --- 2) 兜底：谱牒裸字段（手写人物 / 实录里查无此人）---
    # ★ 2026-09-26：这条兜底路也要会用「生年 + 享年」推定卒年（合并谱里绝大多数
    #   人在绑定的实录槽里查无同名，走的正是这条路 —— 使用者实测报过）。
    rec["__death__"] = life_text(rec, only_death=True)
    out = [("姓名", name)]
    sp = rec.get("spouses") or []
    for zh, key, skip_empty in (
        ("性别", "gender", True),
        ("生年", "birth", True),
        ("卒年", "__death__", True),
        ("世代", "generation", True),
        ("智略等级", "rank", True),
        ("爵位", "fief_title", True),
        ("封国", "state_name", True),
        ("族域", "state_group", True),
        ("君序", "fief_gen", True),
        ("祖序", "root_sort", True),
        ("父亲", "father", True),
        ("母亲", "mother", True),
        ("配偶", "", False),
        ("史实", "historical", True),
        ("神祖", "divine", True),
        ("小传", "bio", True),
        ("备注", "note", True),
    ):
        v = "、".join(sp) if key == "" else rec.get(key)
        if skip_empty and v in (None, "", 0, []):
            continue
        if v in (None, "", []):
            continue
        out.append((zh, v))
    return out, code


class TableView:
    def __init__(self, parent, theme, master):
        self.parent = parent
        self.theme = theme
        self.master = master
        self.columns = list(model.TABLE_COLUMNS)
        self.rows = []              # 当前显示的人物名（有序）
        self.search_text = ""
        self.sort_field = None
        self.sort_desc = False
        self.collapsed = set()      # 折叠的始祖
        self._editor = None
        self._edit_info = None
        # 计数回调由 App 在界面建好后注入（★ 2026-09-26 起落在**底部状态栏**
        # `StatusBar` 的 `gen` 格，见 `main._set_gen_stat`）—— 收一句完整统计文案。
        # 不能直接去找主区工具栏控件 —— 切视图时旧控件已销毁、新的还没建，
        # 直接访问会 TclError（这就是"点表格没反应"的根因）。
        self.counter_cb = None
        # ---- 合并进来的「人物页」能力：右侧档案抽屉 ----
        self.drawer_open = bool(master.cfg.get("table_drawer", True))
        self.drawer = None
        self.drawer_body = None
        self._drawer_name = None

        self._build()
        self.refresh()

    # ---------------------------------------------------------------- 构建
    def _build(self):
        theme = self.theme
        # 批量操作栏（选中多行时出现）
        # ★ UI 改进 B6：批量改爵位/封国/史实是**谱牒层动笔**，走橙金 edit 色；
        #   批量删除是危险动作，走 danger 红 —— 不再与查阅青绿混用
        self.bulkbar = tk.Frame(self.parent, bg=theme.edit_soft, height=38)
        self.bulkbar.pack_propagate(False)
        inner = tk.Frame(self.bulkbar, bg=theme.edit_soft)
        inner.pack(fill=tk.BOTH, expand=True, padx=12)
        self.bulk_label = tk.Label(inner, text="", bg=theme.edit_soft, fg=theme.edit_2,
                                   font=(theme.font_ui_fallback, theme.fs_body, "bold"))
        self.bulk_label.pack(side=tk.LEFT)
        tk.Frame(inner, width=1, height=20, bg=theme.edit).pack(side=tk.LEFT, padx=10)
        for text, cmd, kind in (("批量设爵位", self.batch_set_tier, "edit"),
                                ("批量设封国", self.batch_set_state, "edit"),
                                ("批量设史实", self.batch_set_historical, "edit"),
                                ("批量删除", self.batch_delete, "danger")):
            FlatButton(inner, theme, text=text, command=cmd, kind=kind,
                       padx=10).pack(side=tk.LEFT, padx=3, pady=6)
        FlatButton(inner, theme, text="取消选择", command=self._clear_selection,
                   kind="default", padx=10).pack(side=tk.RIGHT, pady=6)

        # 表格容器
        # ★ 表格和抽屉放进一个 grid 容器里，抽屉占固定列（minsize 保证不被挤扁）。
        #   不能两个都用 pack：Treeview 的**请求宽度**是各列宽之和（实测 1137px），
        #   pack 会先把这 1137 分给它，抽屉只剩 25px —— 实测踩过。
        #   grid 的 `columnconfigure(minsize=...)` 才能真正锁住抽屉宽度。
        body = tk.Frame(self.parent, bg=theme.bg_canvas)
        body.pack(fill=tk.BOTH, expand=True)
        self.body = body
        # ★ 2026-09-22 使用者报「为什么那么大段空白？为什么不是一整页表格？」。
        #   根因：body 用了 grid 放 wrap，但**没给 body 配行/列权重** ——
        #   `wrap.grid(sticky="nsew")` 于是只按**请求尺寸**放置，
        #   而 Treeview 的请求高度就是它默认的 10 行 → 表格只占顶部一小条，
        #   下面全是空白。给 body 配 1 权重，wrap 才会被撑满整页。
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

        wrap = tk.Frame(body, bg=theme.bg_canvas)
        wrap.grid(row=0, column=0, sticky="nsew")

        cols = [c[0] for c in self.columns]
        last = cols[-1]
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings", selectmode="extended")
        for key, title, width, readonly in self.columns:
            self.tree.heading(key, text=title, command=lambda k=key: self.sort_by(k))
            # ★ 2026-09-21：宽度不再只用写死的值 —— `_fit_columns()` 会按**真实内容**
            #   重算一遍（写死的值实测有三列会切字，见那个函数的说明）。
            #   `stretch` 只留给**最后一列**吃余量（窗口变宽时填满右边），
            #   其余固定 —— 否则一列变宽就把后面的列挤出可视区。
            self.tree.column(key, width=width, minwidth=40, anchor="w",
                             stretch=(key == last))

        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(wrap, orient="horizontal", command=self.tree.xview)
        self.hsb = hsb
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)

        # 条件格式（行级 tag）
        # ⚠️ 优先级：Tk 的 Treeview 里同一个 option 被多个 tag 设置时，谁生效**没有
        #   靠得住的顺序保证**。所以「已故」不用叠加的方式，而是**整行换一套 tag**：
        #   已故 → ("dead", …)，未故 → ("odd"/"even", …)。这样灰底永远不会被斑马纹盖掉。
        self._focused_set = set()          # 「选定」高亮名单（refresh 里更新）
        self.tree.tag_configure("odd", background=theme.bg_canvas)
        self.tree.tag_configure("even", background=theme.bg_card)
        self.tree.tag_configure("dead", background=theme.bg_dead or theme.bg_canvas)
        self.tree.tag_configure("female", foreground=theme.spouse)
        self.tree.tag_configure("nohist", foreground=theme.text_3)
        # ★ 2026-09-23「选定」高亮：紫底紫字，与家谱铭牌/时间轴铭牌/人物页表格
        #   同一判据同一颜色（theme.focus_bg/focus_hi）。最后 configure =
        #   优先级最高，压过 odd/even/dead 三套底。
        self.tree.tag_configure("focus", background=theme.focus_bg,
                                foreground=theme.focus_hi)

        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Return>", self._on_double_click)
        self.tree.bind("<Control-c>", lambda e: self.copy_selection())
        self.tree.bind("<Control-v>", lambda e: self.paste_from_clipboard())
        self.tree.bind("<Configure>", self._on_tree_configure)

        # ---- 右侧档案抽屉（从人物页合并过来）----
        # 布局：wrap 先 pack(side=LEFT, expand)，drawer 再 pack(side=RIGHT, 定宽)。
        # 想切换显示时用 pack_forget / pack 重排，不能 destroy（要保住内部控件状态）。
        self._build_drawer()

    def _build_drawer(self):
        """右侧档案抽屉：把人物页那套「全中文档案 + 关系 + 后裔 + 入谱」搬进来。

        它跟表格共享同一个选中行 —— 点表格任意一行，右边立刻出这个人的档案。
        """
        th = self.theme
        d = tk.Frame(self.body, bg=th.bg_panel, width=DRAWER_W)
        d.pack_propagate(False)
        self.drawer = d

        # 头：标题 + 折叠按钮
        head = tk.Frame(d, bg=th.bg_panel)
        head.pack(fill=tk.X)
        self.drawer_title = tk.Label(head, text="档案", anchor="w",
                                     font=(th.font_ui_fallback, th.fs_title, "bold"),
                                     bg=th.bg_panel, fg=th.text)
        self.drawer_title.pack(side=tk.LEFT, padx=(12, 4), pady=(8, 4))
        self.drawer_sub = tk.Label(head, text="", anchor="e", bg=th.bg_panel,
                                   fg=th.text_3,
                                   font=(th.font_ui_fallback, th.fs_body_sm))
        self.drawer_sub.pack(side=tk.RIGHT, padx=(4, 12), pady=(10, 4))

        # 动作条（关系 / 关注 / 入谱）
        acts = tk.Frame(d, bg=th.bg_panel)
        acts.pack(fill=tk.X, padx=12, pady=(0, 4))
        self.drawer_acts = acts

        tk.Frame(d, bg=th.border, height=1).pack(fill=tk.X)

        # 可滚动档案体
        holder = tk.Frame(d, bg=th.bg_panel)
        holder.pack(fill=tk.BOTH, expand=True)
        self.drawer_canvas = tk.Canvas(holder, highlightthickness=0, bd=0,
                                       bg=th.bg_panel)
        ds = ttk.Scrollbar(holder, orient="vertical",
                           command=self.drawer_canvas.yview)
        self.drawer_canvas.configure(yscrollcommand=ds.set)
        self.drawer_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                                padx=(8, 0), pady=(0, 8))
        ds.pack(side=tk.RIGHT, fill=tk.Y, pady=(0, 8), padx=(0, 4))
        self.drawer_body = tk.Frame(self.drawer_canvas, bg=th.bg_panel)
        self.drawer_canvas.create_window((0, 0), window=self.drawer_body,
                                         anchor="nw")
        self.drawer_body.bind(
            "<Configure>",
            lambda e: self.drawer_canvas.configure(
                scrollregion=self.drawer_canvas.bbox("all")))
        for w in (self.drawer_canvas, self.drawer_body):
            w.bind("<MouseWheel>",
                   lambda e: self.drawer_canvas.yview_scroll(
                       int(-e.delta / 120) * 2, "units"))

        if self.drawer_open:
            self._show_drawer()
        self._fill_drawer(None)

    def _show_drawer(self):
        """展开抽屉：锁住第 1 列的 minsize，先把宽度拿到手再排内容。"""
        self.drawer.grid(row=0, column=1, sticky="nsew")
        self.body.columnconfigure(1, minsize=DRAWER_W, weight=0)
        self.body.rowconfigure(0, weight=1)
        self.body.columnconfigure(0, weight=1)

    def _hide_drawer(self):
        self.drawer.grid_forget()
        self.body.columnconfigure(1, minsize=0, weight=0)
        self.body.rowconfigure(0, weight=1)
        self.body.columnconfigure(0, weight=1)

    def toggle_drawer(self):
        """折叠 / 展开档案抽屉（工具条按钮）。"""
        self.drawer_open = not self.drawer_open
        if self.drawer_open:
            self._show_drawer()
            self._on_select()
        else:
            self._hide_drawer()
        try:
            from ..config import update_config
            update_config(table_drawer=self.drawer_open)
        except Exception as e:
            logger.warning(f"保存抽屉开关失败: {e}")
        return self.drawer_label()

    def drawer_label(self):
        return "档案 ⬓" if self.drawer_open else "档案 ⬔"

    def _hint(self, text):
        """UI 改进 D15：低价值告知走状态栏 hint，不再弹窗打断。"""
        sb = getattr(self.master, "statusbar", None)
        if sb is not None:
            sb.set("hint", text)

    def _clear_drawer(self):
        for w in self.drawer_body.winfo_children():
            w.destroy()

    def _field_line(self, zh_label, val, note="", fg=None):
        """档案体里的一行「标签 = 值」，标签等宽、提示走 Tooltip。

        ★ 2026-09-28 全项目整理（第 3 批，铁律①「尽量汉字左对齐」）：
          标签原为**右对齐**（`anchor="e"` + `minsize=86`），而同一抽屉里的
          **标题**与**值**都是左对齐 ⇒ 抽屉里存在两条对齐线，标签左沿比标题
          更靠右、参差不齐。现在标签改为**定宽 4 字 + 左对齐**：抽屉内
          标题 / 标签 / 值共用一条左沿线，值列起点也一致。
        """
        t = self.theme
        line = tk.Frame(self.drawer_body, bg=t.bg_panel)
        line.pack(fill=tk.X, padx=6, pady=1)
        line.columnconfigure(0, weight=0)
        line.columnconfigure(1, weight=1)
        lb = tk.Label(line, text=zh_label, bg=t.bg_panel, fg=t.text_3, width=4,
                      anchor="w", font=(t.font_ui_fallback, t.fs_body_sm))
        lb.grid(row=0, column=0, sticky="nw")
        help_txt = PF.FIELD_HELP.get(zh_label)
        if help_txt:
            lb.configure(cursor="hand2")
            _tip(lb, help_txt)
        shown = "—" if val in (None, "") else str(val)
        tk.Label(line, text=shown + (f" {note}" if note else ""), bg=t.bg_panel,
                 fg=fg or t.text, anchor="w", justify=tk.LEFT,
                 wraplength=DRAWER_W - 130,
                 font=(t.font_ui_fallback, t.fs_body)).grid(row=0, column=1,
                                                            sticky="w", padx=(2, 0))

    def _fill_drawer(self, name):
        """把选中人物写成档案。`name is None` → 显示引导语。"""
        self._clear_drawer()
        self._drawer_name = name
        t = self.theme
        for w in self.drawer_acts.winfo_children():
            w.destroy()

        if not name or name not in self.master.people:
            self._drawer_code = ""
            self.drawer_title.configure(text="档案", fg=t.text)
            self.drawer_sub.configure(text="")
            text_label(self.drawer_body, t, "点左边任意一行，这里显示这个人的档案。\n\n"
                       "档案项与「人物」页完全一致 —— 已合并，不必再切页。",
                       size=t.fs_body_sm, fg=t.text_3, justify=tk.LEFT,
                       wraplength=DRAWER_W - 40).pack(anchor="w", padx=10, pady=12)
            return

        info = self.master.people[name]
        rows, code = archive_rows(self.master, name, info)
        self._drawer_code = code
        # 女性人名标红（使用者要求「女性角色名字在任何地方都标红」）
        self.drawer_title.configure(
            text=str(name),
            fg=t.spouse if info.get("gender", "") == "女" else t.text)
        self.drawer_sub.configure(
            text=f"编号 {code}" if code else "谱内人物")
        if not code:
            # 括号里的说明挪到悬停（使用者 2026-09-21 要求）
            _tip(self.drawer_sub, "谱内人物 · 实录查无 —— 这条只在你的谱牒里，"
                                  "对应的游戏存档里找不到这个人（手写的，或已被筛掉）。")

        # 动作条：入谱 / 查档（谱牒层 → 实录层的两条桥）
        # ★ UI 改进 B6：入谱=写谱牒（橙金 edit），关系/查档=读实录（青绿 record）
        FlatButton(self.drawer_acts, t, text="⇱ 入谱", kind="edit", padx=10,
                   command=self._drawer_push).pack(side=tk.LEFT, padx=(0, 4), pady=2)
        FlatButton(self.drawer_acts, t, text="◈ 关系", kind="record", padx=10,
                   command=self._drawer_relations).pack(side=tk.LEFT, padx=(0, 4), pady=2)
        FlatButton(self.drawer_acts, t, text="⌖ 查档", kind="record", padx=10,
                   command=self._drawer_locate).pack(side=tk.LEFT, pady=2)

        # 史实 / 非史实 + 女性 + 谱内标记
        badge = tk.Frame(self.drawer_body, bg=t.bg_panel)
        badge.pack(fill=tk.X, padx=6, pady=(4, 4))
        hist = (info.get("historical", "否") == "是")
        bl = tk.Label(badge, text="● 史实人物" if hist else "○ 非史实人物",
                      bg=t.bg_panel, fg=t.accent if hist else t.text_3,
                      # ★ weight 必须是 "bold"/"normal"，不能直接填 bool（Tcl 报 unknown font style）
                      font=(t.font_ui_fallback, t.fs_body_sm, "bold" if hist else "normal"))
        bl.pack(side=tk.LEFT)
        _tip(bl, "史实人物：编号 ≤5 位，是游戏写死的历史人物。\n"
                 "非史实人物：编号 9 位，由游戏随机生成。")
        if info.get("gender") == "女":
            tk.Label(badge, text=" 女 ", bg=t.bg_card, fg=t.spouse, padx=4,
                     font=(t.font_ui_fallback, t.fs_body_sm)).pack(side=tk.LEFT, padx=(8, 0))
        if info.get("divine") == "是":
            tk.Label(badge, text=" 神祖 ", bg=t.edit_soft, fg=t.edit_2, padx=4,
                     font=(t.font_ui_fallback, t.fs_body_sm, "bold")).pack(
                         side=tk.LEFT, padx=(8, 0))

        # 爵位色条
        tier = info.get("fief_title", "")
        if tier and t.tier.get(tier):
            tk.Frame(self.drawer_body, bg=t.tier[tier], height=3).pack(
                fill=tk.X, padx=6, pady=(0, 6))

        # ★ 档案正文优先走实录层 Profile（与人物页同一套中文口径）
        #   女性亲属的名字标红（使用者要求「女性角色名字在任何地方都标红」）——
        #   这里只能整行一个颜色（Label 限制），所以「这一行全是女性」时才标红。
        for zh, val in rows:
            fg = None
            if zh in ("母亲", "配偶", "女儿"):
                names = [x for x in str(val or "").split("、") if x]
                if names and all((self.master.people.get(n) or {}).get("gender") == "女"
                                 for n in names):
                    fg = t.spouse
            self._field_line(zh, val, fg=fg)

        self.drawer_body.update_idletasks()
        self.drawer_canvas.yview_moveto(0)

    # ------------------------------------------------ 档案抽屉的三个动作
    def _drawer_push(self):
        """⇱ 入谱：把抽屉里这个人写进当前谱牒档（实录 → 谱牒 那条桥）。"""
        name = self._drawer_name
        if not name:
            return
        code = getattr(self, "_drawer_code", "") or ""
        if not code:
            self._hint("入谱：这个人在实录里查不到编号，入不了谱"
                       "（纯手写的谱内人物本来就已经在谱里）。")
            return
        push = getattr(self.master, "push_to_book", None)
        if callable(push):
            push(code, name)
        else:
            self._hint("入谱：此版本还没有接上入谱桥。")

    def _drawer_relations(self):
        """◈ 关系：调人物页的关系图（关系网按存档的父/母/配偶算）。"""
        code = getattr(self, "_drawer_code", "") or ""
        if not code:
            self._hint("关系：这个人在实录里查不到编号，看不了关系图"
                       "（关系网是按存档里的父/母/配偶字段算的）。")
            return
        pv = getattr(self.master, "person_view", None)
        show = getattr(pv, "show_relations", None)
        if callable(show):
            show(code)
            return
        # 人物页还没建过（默认页签不是它）→ 切到人物页再显示
        try:
            self.master.switch_view("person")
            pv = getattr(self.master, "person_view", None)
            if pv and hasattr(pv, "show_relations"):
                pv.show_relations(code)
            else:
                self._hint("关系：没有可用的关系图入口。")
        except Exception as e:
            logger.warning(f"切人物页看关系失败: {e}")

    def _drawer_locate(self):
        """⌖ 查档：在实录层定位这个编号（谱牒 → 实录 那条桥）。"""
        code = getattr(self, "_drawer_code", "") or ""
        if not code:
            self._hint("查档：这个人在实录里查不到编号，无法定位。")
            return
        try:
            self.master.switch_view("person")
            pv = getattr(self.master, "person_view", None)
            if pv and hasattr(pv, "_goto_code"):
                pv._goto_code(code)
            else:
                self._hint(f"查档：实录里查不到编号 {code}。")
        except Exception as e:
            logger.warning(f"切人物页定位失败: {e}")

    def _on_tree_configure(self, _=None):
        self._hide_editor()
        self._sync_hscroll()

    def _sync_hscroll(self):
        """列总宽没超出可视宽度就不显示横向滚动条。

        原先滚动条常驻，明明 1108 < 1137 也占着底部一行；这里按内容宽度决定显隐。
        列有 stretch，窗口变宽时最后一列会自动吃掉余量，所以总宽要实时读。
        """
        avail = self.tree.winfo_width()
        if avail <= 1:          # 还没完成布局，宽度不可信
            return
        total = sum(self.tree.column(c[0], "width") for c in self.columns)
        if total <= avail:
            self.hsb.grid_remove()
        elif not self.hsb.winfo_ismapped():
            self.hsb.grid()

    # ---------------------------------------------------------------- 数据
    def _filtered_names(self):
        m = self.master
        search, hist, tier, state, branch_only, nohist, no_dead = m.sidebar.current_filters()
        names = list(m.people.keys())

        if search:
            low = search.lower()
            names = [n for n in names
                     if low in n.lower()
                     or low in (m.people[n].get("note", "") or "").lower()
                     or low in (m.people[n].get("state_name", "") or "").lower()]
        if hist != "全部":
            names = [n for n in names if m.people[n].get("historical", "否") == hist]
        if tier != "全部":
            names = [n for n in names if m.people[n].get("fief_title", "") == tier]
        if state != "全部":
            names = [n for n in names if m.people[n].get("state_name", "") == state]
        if nohist:
            # ★ 2026-09-24 与画布同口径：勾「隐藏非史」= 只留史实人物。
            #   （原来这里只删「hidden_non_historical 记过的支系」里的非史实后裔 ——
            #     而那份名单只在**恰好选中节点**时才会被写入，于是勾了也没反应。）
            names = [n for n in names if m.people[n].get("historical") == "是"]
        if no_dead:
            names = [n for n in names if not (m.people[n].get("death") or "")]
        if branch_only and m.selected_node:
            branch = model.get_subtree(m.people, model.root_ancestor(m.people, m.selected_node))
            names = [n for n in names if n in branch]

        # 排序：默认按"宗支顺序 + 代数 + 排行"，与树形视图一致
        if self.sort_field:
            key = self.sort_field
            names.sort(key=lambda n: _sort_key(m.people[n].get(key), self.sort_desc),
                       reverse=self.sort_desc)
        else:
            names.sort(key=self._tree_order_key)
        return names

    def _tree_order_key(self, name):
        """按始祖顺序 → 代数 → 排行，让表格行序与树形一致。"""
        info = self.master.people[name]
        root = model.root_ancestor(self.master.people, name)
        root_sort = self.master.people.get(root, {}).get("root_sort", 0) or 999
        return (root_sort, root, info.get("generation", 0) or 999,
                info.get("rank", 0) or 999, name)

    def _visible_names(self):
        """在排序结果上应用折叠。"""
        names = self._filtered_names()
        if not self.collapsed:
            return names
        hidden = set()
        for r in self.collapsed:
            hidden |= model.get_descendants(self.master.people, r)
        return [n for n in names if n not in hidden]

    def _fit_columns(self, names):
        """按**真实内容**重算列宽，保证不切字（★ 2026-09-21 使用者要求）。

        写死的列宽实测有三列会切字（按当前谱牒量的）：
          姓名      130 < 实际 131（深层级的竖线前缀很长）
          配偶       84 < 实际 112（多个配偶用「、」连起来）
          生年/卒年  90 < 实际 187（生年 / 卒年 / 族域三段拼一格）
        所以改成「量一遍内容再定宽」，夹在 `[min, max]` 之间。

        ⚠️ 只用**估算**（`kit.est_text_px`），不调 `tkfont.measure`：
          实测 measure 9000 次要 0.7 秒，这里 3000 人 × 17 列根本跑不动。
          估算函数刻意多留 8% 余量，宁可略宽不切字。

        只在**数据变了**（人数或列集合变了）时重算 —— 不然每敲一个搜索字
        都要重算一遍。返回是否真的重算了。
        """
        sig = (len(names), tuple(c[0] for c in self.columns))
        if getattr(self, "_fit_sig", None) == sig:
            return False
        self._fit_sig = sig
        pt = self.theme.fs_body
        hpt = self.theme.fs_body_sm
        for key, title, _w, _ro in self.columns:
            head = est_text_px(title, hpt) + 30          # 表头 + 排序留白（含 B7 的 ▲▼）
            # ★ 2026-09-22 使用者报「表格的栏怎么这么薄」。
            #   原来下限写死 44px —— 那只够塞下两个 12pt 汉字，17 列里 11 列都卡在
            #   这个下限上（母亲 / 配偶 / 爵位 / 封代 / 祖序 / 神祖 / 介绍 …），
            #   看着像一排细缝。现在下限改成「表头文字 + 28px」且不低于 56px：
            #   空列也至少能把表头舒舒服服放下。
            lo = max(56.0, head + 12)
            need = head
            if key == "__seq__":
                need = max(need, est_text_px(str(len(names)), pt) + 16)
            else:
                for n in names:
                    need = max(need, est_text_px(self._cell_text(n, self.master.people[n], key), pt) + 18)
            # ⚠️ 必须 ceil 不能 int：`int(83.1)` = 83 —— 差这 0.1px 就切字
            #   （实测「尊号 · 谥号」表头需要 83.1px，正好被截成 83px）。
            self.tree.column(key, width=int(math.ceil(max(lo, min(need, 260)))))
        return True

    def refresh(self):
        m = self.master
        names = self._visible_names()
        self.rows = names
        self.tree.delete(*self.tree.get_children())
        # 列宽按内容自适应（数据没变就跳过，见 `_fit_columns`）
        self._fit_columns(list(m.people.keys()))

        depths = {}
        # ★ 2026-09-23「选定」高亮名单（选定人 + 其男性后裔，见 app.focus_set）
        self._focused_set = m.focus_set()
        for name in names:
            depths[name] = self._depth_of(name)

        for i, name in enumerate(names):
            info = m.people[name]
            values = []
            for key, _, _, _ in self.columns:
                # 序号列取显示顺序（1 起）：原先这一列恒为空，白占了一列宽度
                values.append(str(i + 1) if key == "__seq__"
                              else self._cell_text(name, info, key))
            # 已故（有卒年）整行压灰底 —— 使用者要求「去世的人物用灰色阴影涂上」。
            # 判据是**谱牒里的卒年字段**（谱牒层没有「活人表/已故表」可依）。
            # ★ 2026-09-26：全谱声明「不涂已故灰」时按斑马纹走（见 storage.hide_dead_shade）
            from .. import storage as _st
            _dead = bool(info.get("death")) and not _st.hide_dead_shade(
                getattr(m, "current_save", ""))
            tags = ["dead" if _dead else ("even" if i % 2 else "odd")]
            # ★ 2026-09-23「选定」高亮（见 tag_configure 处的说明）
            if name in self._focused_set:
                tags.append("focus")
            if info.get("gender") == "女":
                tags.append("female")
            elif info.get("historical", "否") == "否":
                tags.append("nohist")
            self.tree.insert("", "end", iid=name, values=values, tags=tuple(tags))

        self._update_bulkbar()
        self._update_counter()
        self._update_headings()
        self._sync_hscroll()

    def _update_headings(self):
        """把当前排序列与方向标在表头上（UI 改进 B7，纯显示）。"""
        for key, title, _w, _ro in self.columns:
            if key == self.sort_field:
                mark = " ▼" if self.sort_desc else " ▲"
            else:
                mark = ""
            self.tree.heading(key, text=title + mark)

    def _depth_of(self, name):
        d = 0
        cur = name
        people = self.master.people
        while d < 200:
            dad = people[cur].get("father", "")
            mom = people[cur].get("mother", "")
            nxt = dad if dad in people else (mom if mom in people else "")
            if not nxt:
                break
            cur = nxt
            d += 1
        return d

    def _cell_text(self, name, info, key):
        if key == "__seq__":
            return ""
        if key == "__name__":
            # 层级用竖线符号画出来。原来每层一个空格，最多 6 层也只有 24px 左右，
            # 看着跟平铺一样；换成竖线后同样的宽度里能一眼看出父子关系。
            depth = min(6, self._depth_of(name))
            prefix = "│" * depth
            if model.get_children(self.master.people, name):
                prefix += ("▸" if name in self.collapsed else "▾")
            # 重名序数归一成数字（老档的「王贲①」→「王贲1」）——
            # 纯文本控件做不了角标，至少让表格与画布上是同一个数
            return prefix + plain_name(name)
        if key == "__bio__":
            return "✎" if info.get("bio") else "◎"
        if key == "__life__":
            # ★ 2026-09-26：改走统一口径（真实卒年优先、缺失用生年+享年推定）——
            #   原来直接取 death 字段，合并谱里 23% 的人永远「—」（使用者实测报过）。
            return life_text(info)
        if key == "spouses":
            # 配偶 / 父母都是**谱牒里的名字**，同样把重名序数归一成数字（只影响显示）
            return "、".join(plain_name(s) for s in info.get("spouses", []) if s)
        if key in ("father", "mother"):
            return plain_name(info.get(key, "") or "") if info.get(key) else ""
        if key in ("generation", "rank", "fief_gen", "root_sort"):
            v = info.get(key, 0)
            return "" if not v else str(v)
        return info.get(key, "") or ""

    def _update_counter(self):
        # ★ 口径统一（使用者 2026-09-21）：这里必须写明**谱牒**。
        #   人物页那个「共 N 人」是**实录**口径（合并总表，含只在族谱表里的人），
        #   本页是谱牒档（family.json）的行数，两层天生不同数。
        #   原来两处都只写「共 …」，使用者一眼看去会以为是同一个数（2590 vs 2175）。
        if self.counter_cb is not None:
            # ★ 2026-09-26：这句落**底部状态栏**（`gen` 格，落点 `main._set_gen_stat`）——
            #   与 `_update_status` 的表格分支同格式，两处写同一句（幂等）；
            #   状态栏那一行放得下整句，不必再准备缩略档。
            n_all, n_show = len(self.master.people), len(self.rows)
            self.counter_cb(f"谱牒 {n_all} 行 · 显示 {n_show} 行")

    # ---------------------------------------------------------------- 选择
    def _selected_names(self):
        return list(self.tree.selection())

    def _on_select(self, _=None):
        sel = self._selected_names()
        self._update_bulkbar()
        if len(sel) == 1:
            self.master.selected_node = sel[0]
            self.master.sidebar.fill_person(self.master.people[sel[0]], sel[0])
            self.master._update_status()
        # ★ 档案抽屉只认「单选」——多选时显示引导语，避免误以为档案属于整批
        self._fill_drawer(sel[0] if len(sel) == 1 else None)

    def select_name(self, name):
        if name in self.tree.get_children(""):
            self.tree.selection_set(name)
            self.tree.see(name)

    def _clear_selection(self):
        self.tree.selection_remove(*self.tree.selection())
        self._update_bulkbar()

    def _update_bulkbar(self):
        n = len(self._selected_names())
        if n > 1:
            self.bulk_label.configure(text=f"已选 {n} 行")
            if not self.bulkbar.winfo_ismapped():
                self.bulkbar.pack(fill=tk.X, before=self.parent.winfo_children()[1])
        else:
            self.bulkbar.pack_forget()

    # ---------------------------------------------------------------- 排序
    def sort_by(self, key):
        if key in ("__seq__",):
            return
        if self.sort_field == key:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_field = key
            self.sort_desc = False
        self.refresh()

    # ---------------------------------------------------------------- 编辑
    def _on_double_click(self, event=None):
        row = self.tree.identify_row(event.y) if event is not None and hasattr(event, "y") else None
        col = self.tree.identify_column(event.x) if event is not None and hasattr(event, "x") else None
        if not row or not col:
            sel = self._selected_names()
            if len(sel) != 1:
                return
            row, col = sel[0], "#2"
        idx = int(col.replace("#", "")) - 1
        if idx < 0 or idx >= len(self.columns):
            return
        key, title, _, readonly = self.columns[idx]

        # 姓名列 → 折叠/展开；介绍列 → 打开介绍编辑
        if key == "__name__":
            if model.get_children(self.master.people, row):
                self.toggle_collapse(row)
            return
        if key == "__bio__":
            from ..dialogs import forms
            forms.bio_dialog(self.master, row)
            return
        if readonly or key not in EDIT_KIND:
            return
        self._start_edit(row, idx, key, EDIT_KIND[key])

    def _hide_editor(self):
        if self._editor is not None:
            try:
                self._editor.destroy()
            except tk.TclError:
                pass
            self._editor = None
            self._edit_info = None

    def _start_edit(self, name, idx, key, kind):
        self._hide_editor()
        bbox = self.tree.bbox(name, f"#{idx + 1}")
        if not bbox:
            return
        x, y, w, h = bbox
        theme = self.theme
        info = self.master.people[name]

        if kind == "enum":
            if key == "fief_title":
                options = TIER_NAMES
            elif key == "gender":
                options = ["男", "女"]
            else:
                options = ["是", "否"]
            var = tk.StringVar(value=info.get(key, "") or "")
            editor = ttk.Combobox(self.tree, values=options, textvariable=var, state="readonly")
        elif kind in ("ref", "multi_ref"):
            if kind == "multi_ref":
                options = [n for n in self.master.people if n != name]
                var = tk.StringVar(value="、".join(info.get("spouses", [])))
            else:
                want = "男" if key == "father" else "女"
                options = [""] + [n for n, i in self.master.people.items()
                                  if i.get("gender") == want and n != name]
                var = tk.StringVar(value=info.get(key, "") or "")
            editor = ttk.Combobox(self.tree, values=options, textvariable=var)
        else:
            var = tk.StringVar(value=str(info.get(key, "") or ""))
            editor = input_box(self.tree, theme, var)

        editor.place(x=x, y=y, width=max(w, 90), height=h)
        editor.focus_set()
        self._editor = editor
        self._edit_info = (name, key, kind, var)

        def commit(_=None):
            self._commit_edit()
        editor.bind("<Return>", commit)
        editor.bind("<FocusOut>", commit)
        editor.bind("<Escape>", lambda e: self._hide_editor())

    def _commit_edit(self):
        if self._edit_info is None:
            return
        name, key, kind, var = self._edit_info
        raw = var.get()
        self._hide_editor()
        if name not in self.master.people:
            return
        info = self.master.people[name]

        if kind == "num":
            try:
                value = int(raw) if str(raw).strip() else 0
            except ValueError:
                value = 0
        elif kind == "multi_ref":
            value = [s for s in raw.replace(",", "、").split("、") if s in self.master.people]
        else:
            value = raw

        if key == "gender":
            info["gender"] = value or "男"
        elif key == "fief_title":
            info["fief_title"] = value
            if value == "无":
                info["fief_gen"] = 0
        elif key in ("historical", "divine"):
            info[key] = value or "否"
        elif key in ("father", "mother"):
            if value and model.would_create_cycle(self.master.people, name, value):
                messagebox.showwarning("提示", f"「{value}」是 {name} 的后代，会造成循环引用")
                return
            info[key] = value
        elif key == "spouses":
            info["spouses"] = value
        elif key == "generation":
            old = info.get("generation", 0)
            if value and old and value != old:
                delta = value - old
                for d in model.get_descendants(self.master.people, name):
                    self.master.people[d]["generation"] = \
                        self.master.people[d].get("generation", 1) + delta
            info["generation"] = value
        elif key == "root_sort":
            old = info.get("root_sort", 0)
            model.shift_root_sorts(self.master.people, value, old, exclude_name=name)
            info["root_sort"] = value
        else:
            info[key] = value

        info["state_group"] = (info.get("state_name", "") + info.get("fief_title", "")) \
            if info.get("state_name") and info.get("fief_title") else ""

        self.master._record(f"表格修改: {name}.{key}")
        self.master.save_data()
        self.refresh()
        if self.master.tree is not None:
            self.master.tree.rerender()
            self.master.on_layout_changed()

    # ---------------------------------------------------------------- 折叠
    def toggle_collapse(self, name):
        if name in self.collapsed:
            self.collapsed.discard(name)
        else:
            self.collapsed.add(name)
        self.refresh()

    def expand_all(self):
        self.collapsed.clear()
        self.refresh()

    def collapse_all(self):
        self.collapsed = {n for n in self.master.people
                          if model.get_children(self.master.people, n)}
        self.refresh()

    # ---------------------------------------------------------------- 增删
    def add_row(self):
        from ..dialogs import forms
        forms.add_ancestor_dialog(self.master)

    def batch_delete(self):
        names = self._selected_names()
        if not names:
            return
        gone_all = set()
        for n in names:
            gone_all |= model.get_subtree(self.master.people, n)
        if not messagebox.ask_danger("删除行",
                                     f"确定删除选中的 {len(names)} 行？\n"
                                     f"（连同其全部后裔，共 {len(gone_all)} 人，不可恢复）",
                                     ok_text="删除"):
            return
        gone = gone_all
        self.master._record(f"表格批量删除 {len(gone)} 人")
        model.remove_people(self.master.people, gone)
        self.master.selected_node = None
        self.master.save_data()
        self.master._refresh_all()

    def _batch_set(self, key, value, label):
        names = self._selected_names()
        if not names:
            return
        for n in names:
            self.master.people[n][key] = value
            if key == "fief_title" and value == "无":
                self.master.people[n]["fief_gen"] = 0
        self.master._record(f"表格批量{label}: {len(names)} 人")
        self.master.save_data()
        self.master._refresh_all()

    def batch_set_historical(self):
        self._batch_set("historical", "是", "设史实")

    def batch_set_tier(self):
        from tkinter import simpledialog
        value = simpledialog.askstring("批量设爵位", f"输入爵位（{'/'.join(TIER_NAMES)}）：",
                                       parent=self.master.root)
        if value in TIER_NAMES:
            self._batch_set("fief_title", value, "设爵位")
        elif value:
            self._hint("爵位取值不合法（可选：无/卿/子/伯/侯/公/王/帝）")

    def batch_set_state(self):
        from tkinter import simpledialog
        value = simpledialog.askstring("批量设封国", "输入封国名：", parent=self.master.root)
        if value is not None:
            self._batch_set("state_name", value.strip(), "设封国")

    # ---------------------------------------------------------------- 剪贴板
    def copy_selection(self):
        names = self._selected_names() or self.rows
        if not names:
            return
        headers = [c[1] for c in self.columns if c[0] not in ("__seq__",)]
        lines = ["\t".join(headers)]
        for n in names:
            info = self.master.people[n]
            cells = []
            for c in self.columns:
                if c[0] == "__seq__":
                    continue
                # 姓名列去掉层级装饰（竖线 / 折叠箭头）：那是屏幕上的视觉提示，
                # 粘进 Excel 应该是干净的名字，来回倒一遍也不会多出奇怪的前缀
                cells.append(n if c[0] == "__name__"
                             else self._cell_text(n, info, c[0]))
            lines.append("\t".join(cells))
        self.master.root.clipboard_clear()
        self.master.root.clipboard_append("\n".join(lines))
        self._hint(f"已复制 {len(names)} 行，可直接粘贴到 Excel。")

    def paste_from_clipboard(self):
        try:
            raw = self.master.root.clipboard_get()
        except tk.TclError:
            self._hint("剪贴板为空，先去 Excel 复制一段表格")
            return
        rows = [line.split("\t") for line in raw.strip().splitlines() if line.strip()]
        if not rows:
            return
        from ..dialogs import forms
        forms.paste_dialog(self.master, rows)

    def open_column_settings(self):
        messagebox.showinfo("列设置", "列显示/隐藏与拖拽调序将在下一阶段提供。\n"
                                      "当前可直接拖动表头边界调整列宽。")

    def set_search(self, text):
        self.search_text = text
        self.refresh()


def _sort_key(value, desc):
    """排序键：数字与文本分别处理，空值排最后。"""
    if value in ("", None):
        return (1, 0)
    if isinstance(value, (int, float)):
        return (0, value)
    if isinstance(value, list):
        value = "、".join(value)
    try:
        return (0, float(value))
    except (TypeError, ValueError):
        return (0, str(value))
