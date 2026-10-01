# -*- coding: utf-8 -*-
"""史馆 · 世界页（实录层，只读）—— 从「存档阅览器」gui.py 移植。

与人物页共用同一套表格/详情渲染（PersonView），差别只有两处：
  · 侧栏导航换成**全表族分类树**（国家 / 城池 / 家族 / 外交 / 战斗 / 贸易 / 世界 / 其他）
  · 不显示「非史实」开关与「关注世系」—— 世界页没有人物语义

继承 PersonView 而不是复制一遍：两者的表格、详情、关系、入谱逻辑完全一致，
只有导航与工具栏不同（这是 M1 拆分时最省事也最不易分岔的切法）。
"""
import tkinter as tk
from tkinter import ttk

from .. import catalog as C
from ..widgets.kit import Card, input_box
from .person_view import PersonView, Tooltip


class WorldView(PersonView):
    """世界页：国家 · 城池 · 家族 · 外交 · 宗庙……（实录层，不常用但要在）。"""

    def _build_sidebar(self, side_host):
        """世界页侧栏：表族分类树 + 搜索（2026-09-23 与全项目同款 Card 风格）。"""
        th = self.theme
        side = tk.Frame(side_host, bg=th.bg_panel, width=th.sidebar_w)
        side.pack(fill=tk.BOTH, expand=True)
        self.side = side
        pad = {"padx": 8, "pady": (6, 0)}

        # === 表族（分类树，占满剩余高度）===
        self.card_nav = Card(side, th, "表族")
        self.card_nav.pack(fill=tk.BOTH, expand=True, **pad)
        navwrap = tk.Frame(self.card_nav.body, bg=th.bg_card)
        navwrap.pack(fill=tk.BOTH, expand=True)
        self.nav = ttk.Treeview(navwrap, show="tree", selectmode="browse")
        nvs = ttk.Scrollbar(navwrap, orient="vertical", command=self.nav.yview)
        self.nav.configure(yscrollcommand=nvs.set)
        self.nav.grid(row=0, column=0, sticky="nsew")
        nvs.grid(row=0, column=1, sticky="ns")
        navwrap.rowconfigure(0, weight=1)
        navwrap.columnconfigure(0, weight=1)
        self.nav.bind("<<TreeviewSelect>>", lambda e: self._on_nav())

        # === 搜索（底部常驻）===
        foot = tk.Frame(side, bg=th.bg_panel)
        foot.pack(side=tk.BOTTOM, fill=tk.X)
        self.card_search = Card(foot, th, "搜索")
        self.card_search.pack(fill=tk.X, padx=8, pady=(6, 8))
        # 括号里的说明挪到悬停（使用者 2026-09-21 要求）
        Tooltip(self.card_search.title_label, "只在这张表里搜，不会跨表族搜。")
        self.search_var = tk.StringVar()
        ent = input_box(self.card_search.body, th, self.search_var)
        ent.pack(fill=tk.X, ipady=3)
        ent.bind("<Return>", lambda e: self._apply_filter())
        self.search_var.trace_add("write", lambda *a: self._apply_filter())
        self.search_entry = ent
        self.show_generated = tk.BooleanVar(value=True)   # 世界页无此概念，占位
        self.follow_lbl = tk.Label(self.card_search.body, text="", bg=th.bg_card)

    def status_gen_text(self):
        n = len(self.slot.tables) if self.slot else 0
        return f"世界 {n} 个表族"

    def toolbar_groups(self):
        """工具栏分组（2026-09-23 UI 重规划）：数据 → 帮助（与人物页同位）。"""
        return [
            ("数据", [
                ("reload", "重新载入", self._reload, "tool", "从本机缓存重新读取实录"),
            ]),
            ("帮助", [
                ("help", "字段说明", self._show_help, "tool", "查看各字段的含义与取值说明"),
            ]),
        ]

    def _nav_order(self):
        """世界页：除人物族以外的全部分类。

        ★ 2026-09-22 修 bug：此前这里另有一张 `pretty` 映射表，写的是
          「战斗 / 贸易 / 世界 / 其他」——那是 v1 时代的旧分类，而
          `catalog.CATEGORIES` 早已改成「军事 / 文化 / 其它」。两者对不上时
          `pretty.get(cat, cat)` 会静默退化成英文 key，导航上就会冒出
          `Culture` 这类中英混排的分组名。**分类名只有 `CATEGORIES` 一个来源**，
          不要再在视图里另抄一份。
        """
        if self.slot is None:
            return []
        groups = {}
        for name, t in self.slot.tables.items():
            if name in self.PERSON_ORDER or name.startswith("_"):
                continue
            if C.category_of_family(name) == "人物":
                continue
            groups.setdefault(C.category_of_family(name), []).append((name, t))
        out = []
        for cat in C.CATEGORIES:
            if cat == "人物":
                continue
            if cat in groups:
                out.append((cat, groups.pop(cat)))
        for cat, v in groups.items():
            out.append((cat, v))
        return out

    def _build_nav(self):
        self.nav.delete(*self.nav.get_children())
        self._nav_index = {}
        # ★ 2026-09-22：表族用途说明 —— 悬停哪一行就显示那一行的说明。
        #   Treeview 没有「按行 setToolTip」，所以用一个**共享 tooltip** +
        #   `<Motion>` 里 `identify_row(y)` 查当前行来改文本（Tooltip._show
        #   每次读 `self.text`，所以改属性即可生效）。
        self._nav_note = {}
        for cat, items in self._nav_order():
            total = sum(len(t) for _, t in items)
            node = self.nav.insert("", "end", text=f"{cat}　({total})", open=True)
            for name, t in sorted(items, key=lambda x: -len(x[1])):
                lbl = t.label or C.label_of_family(name)
                kid = self.nav.insert(node, "end", text=f"{lbl}　{len(t)}")
                self._nav_index[kid] = name
                note = (C.note_of_family(name)
                        or C.note_of_family(name.split("/")[0]))
                if note:
                    self._nav_note[kid] = f"{lbl}\n{note}"
        tip = getattr(self, "_nav_tip", None)
        if tip is None:
            tip = Tooltip(self.nav, "")
            self._nav_tip = tip

            def _follow(e):
                try:
                    iid = self.nav.identify_row(e.y)
                except Exception:
                    iid = ""
                tip.text = self._nav_note.get(iid, "") if iid else ""
            self.nav.bind("<Motion>", _follow, add="+")

    def _show_help(self):
        from ..widgets import msgbox as messagebox
        cats = " · ".join(c for c in C.CATEGORIES if c != "人物")
        messagebox.showinfo(
            "字段说明 · 世界页",
            "世界页收的是人物以外的全部表族：\n"
            f"　{cats}。\n\n"
            "用法和人物页一样：左边选表族，中间看表格，右边看某一条的全部字段。\n"
            "表名可以鼠标悬停看用途（多数表都写了一句「它是干什么的」），\n"
            "表头与字段名也都可以悬停看解释。\n\n"
            "【宗庙 · 祭祀 · 神系】← 存档里这些字段都收到了哪\n"
            "　· **神系** = `Faith_Gods_Sys_Code`（信仰神祇系统编号）：整国共用一个神系，\n"
            "　　同一神系的国家「一荣俱荣、一损俱损」。\n"
            "　· **神明** = `God_Code` / `Gods_Code`（神祇编号）。\n"
            "　· **庙宇** = `All_Miao_Array`（全庙表：始祖庙 / 高祖庙…，带 `Miao_Level` 庙等级）。\n"
            "　· **牌位** = `All_Memorial_Array`（全祭祀表）：被供奉的列祖列宗，\n"
            "　　每条带生卒、受封时间、当今国名与国都 —— 详情卡里逐条展开。\n"
            "　· **人造神** = `Ji_Si_Gods`（祭祀神祇）：玩家自己造的神；空数组 = 还没造过。\n"
            "　· **宗室评级** = `Now_King_Evaluate`（当今国君评价）—— 评级会触发造神事件。\n\n"
            "【庙宇容量的经验公式】（来源见下，**非官方文档**）\n"
            "　T = 庙宇总数上限（通常 10）　B = 该神系的基础神明数\n"
            "　Amax = 玩家可造神上限（5）　A = 已造数量\n"
            "　当前总数 S = B + A；**还能造几个 = max(0, min(T − B, Amax))**\n\n"
            "【族域 ↔ 神系 初始绑定】（同上来源）\n"
            "　中夏 → 皇天（B=11，已超上限，不能再造）\n"
            "　东夷 / 百越 / 辰韩 / 扶余 → 帝俊（B=10，满额）\n"
            "　北狄 / 匈奴 → 烛龙（B=6，**有余量可造神**）\n"
            "　南蛮 / 百濮 → 东皇太一（B=10，满额）\n"
            "　西戎 / 西域 / 象雄 → 女娲肠（B=9）\n\n"
            "【造神事件触发条件】（同上来源，① ② 仅先民 / 方国阶段，③ 全阶段）\n"
            "　① 评级为上 / 佳、邦 / 美的**宗室**成员自然死亡\n"
            "　② 评级为神祖 / 圣人 / 名君 / 名臣 / 名将 / 豪杰 / 哲妇 / 国色 的成员自然死亡\n"
            "　③ 功勋 ≥ 100 的**朝臣**自然死亡\n"
            "　④「异神降临」事件：仅先民阶段\n\n"
            "【继承规则】（同上来源）分封附庸按「**族域—神系**」配对继承，\n"
            "　不必然继承母国；叛军仍继承母国。原配对（中夏—皇天）在当地族域国家\n"
            "　全灭后可能被「新配对」取代（如中夏—烛龙）。\n\n"
            "⚠️ 以上「神系」段落的机制来自玩家 **念不勿** 的 TapTap 攻略\n"
            "　《关于非上古剧本神系清零流程及相关设定》（2025-12-24 修订）。\n"
            "　作者本人声明「测试结果常被官方调整、时效性不保证」，\n"
            "　**请以游戏内实际表现与官方说明为准**；本工具只做字段呈现，不参与战斗规则。\n\n"
            "【只读】实录层不提供任何写盘功能，不会改动你的游戏存档。")
