# -*- coding: utf-8 -*-
"""史馆 · 人物页（实录层，只读）—— 从「存档阅览器」gui.py 移植。

实录层的核心视图。与原阅览器的差别（规划 §四 + D1）：
  · 不再自带顶栏/状态栏 —— 外壳（shell.py）统一提供，本视图只画**主体三栏**
  · 侧栏迁到外壳的 `side_host`（288px，与谱牒页同宽）
  · 「⇱ 入谱」不再拉外部进程，直接调 `app.push_to_book()`（同进程写入谱牒档）
  · 新增「⌂ 查档」反查：桥的另一头（谱牒 → 实录）落到这里

设计原则沿用（与 labels.py 一致）：
  **字段名 100% 译成中文；字段值只译有实证依据的，没证据就原样显示。**
"""
import json
import math
import re
import os
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, ttk

from .. import catalog as C
from .. import dpi as _dpi
from .. import labels as L
from .. import profiles as PF
from .. import record_derive as RD
from .. import relations as R
from .. import saveload as S
from .. import storage
from .. import xref as XR
from ..widgets import msgbox as messagebox
from ..widgets.kit import (Card, ChipRow, FlatButton, chip as kit_chip,
                           est_text_px, hsep, input_box, text_label, tip)

APP_TITLE = "大周列国志 · 存档阅览器"

MAX_ROWS = 20000          # ★ 2026-09-25：《全史存档》13,526 人要能整表列出


def split_hint(text):
    """把标题里的「（……）」解释摘出来 → `(正文, 解释)`。

    ★ 2026-09-21 使用者要求「最好把解释说明的括号文字都改成 tooltip」。
      表族标签里的「（派生视图）」「（未登记）」都是解释，正文不该带着它们，
      鼠标停上去才显示。
    """
    out, hint, buf, depth = [], [], [], 0
    for ch in (text or ""):
        if ch == "（":
            depth += 1
            if depth == 1:
                buf = []
            continue
        if ch == "）" and depth:
            depth -= 1
            if depth == 0 and buf:
                hint.append("".join(buf))
            continue
        (buf if depth else out).append(ch)
    return "".join(out).strip(), "\n".join(hint)

HEAVY_FIELDS = {
    "Ren_Face", "Ren_Ke_Data", "Shu_Yuan_Data", "Wai_Jia_Data",
    "Official_System_Mgr_Obj", "Jia_Zu_Jue_Wei_Data", "Parent",
    "Map_Build_Data", "Land_Allocation", "Map_Cheng_Fang_Array",
    "Map_Jie_Ceng_Obj", "Map_Buff_Array", "Map_Jun_Dui_Array",
    "Map_Wen_Hua_Array", "Map_Zhi_Du_Map", "Zhan_Ling_Data",
    "Jun_Dui_Data", "Buff_Array", "Weapon_Arr", "Bing_Zhong_Pei_E",
    "King_Buff_Array", "King_Zheng_Ing_Array", "Zheng_Ce_Shu_Array",
    "Genealogy_Ren_Record_Array", "Map_Tag", "Zui_Ming_Xing_Fa_Array",
}
MUTE_FIELDS = PF.HIDDEN_FIELDS


# ★ 2026-09-28 全项目整理（第 1 批）：**三套 Tooltip 收敛成一套**。
#   这里原本有一份 55 行的自制实现（Toplevel + overrideredirect + 硬编码
#   `#3a3a3a`），`shell.py` 里还有第二套（`_show_tip` / `_hide_tip`），而
#   `widgets/kit.py` 的 `tip()` 才是设计系统里的那一份
#   （`world_view` / `table_view` 一直在用）。
#   三者签名一致（widget, text, delay）⇒ **直接别名，调用点一处不用改**。
Tooltip = tip


# 生卒年时间排序的解析（年.月，如 -192.12 / 57.08）
_CHRONO_RE = re.compile(r"^(-?\d{1,4})(?:\.(\d{1,2}))?$")

class PersonView:
    """人物页（实录层）：左侧表族导航 + 中间表格 + 右详情（含固定操作条）。"""

    PERSON_TABLES = ["Save_Ren_Data", "Save_Dead_Ren_Data", "Save_Woman_Data",
                     "Save_Chu_Sheng_Data"]
    GENEALOGY_RENAME = {
        "Born_Time": "Ren_Chu_Sheng_Time",
        "Dead_Time": "Ren_End_Time",
        "Generations": "Ren_Dai_Shu",
    }
    GENEALOGY_FOLDED = ("Father_Code", "Father_Name", "Mother_Code", "Mother_Name",
                        "Memorial_Ren_Sex")
    # ★ 2026-09-25 修：把《全史存档》的「人物 · 谱牒总谱」也列进导航。
    #   上一版只把它挂进了 `slot.tables`，却**漏了这份名单** —— 表在、导航没有，
    #   使用者根本点不到（于是只能看「全部人物」那张实录槽的表：非史实一大堆、
    #   已故者在存档的已故表里本就没有智略/等级/势力 ⇒ 满屏「—」）。
    #   非合并谱没有这张表，`_nav_order` 里那句 `n in tables` 自会把它滤掉。
    #   `world_view` 也吃这份名单（用它跳过人物类表族），一并受益。
    PERSON_ORDER = ("人物 · 合并总表", "人物 · 关注世系", RD.BOOK_NAME)
    PERSON_NAV_LABEL = {
        "人物 · 合并总表": "全部人物",
        "人物 · 关注世系": "续谱名单",
        RD.BOOK_NAME: "谱牒总谱",
    }
    PERSON_VIEW_FAMILIES = {"人物 · 合并总表", "人物 · 史实人物", "人物 · 非史实",
                            "人物 · 关注世系", RD.BOOK_NAME}
    PERSON_RAW_TABLES = {"Save_Ren_Data", "Save_Dead_Ren_Data", "Save_Woman_Data",
                         "Save_Chu_Sheng_Data"}

    # ---- 人物筛选（勾选框）----
    # 使用者原话：「史实、非史、男女、生死几乎都是二选一，是否可以以画对号的方式
    # 自由选取」。所以三个二选一维度做成**可勾选**（组内或、组间与、整组不勾＝不限），
    # 标签一律 4 字，看着才齐。
    FILTER_GROUPS = (
        (("hist", "史实人物"), ("gen", "非史人物")),
        (("male", "男性人物"), ("female", "女性人物")),
        (("alive", "在世人物"), ("dead", "已故人物")),
    )
    # 单选项：不参与「组内或」，勾上就是「只留满足它的」。标签一律 4 字。
    # ★ 2026-09-25 使用者要求：「在筛选栏的出生记录左侧加个隐藏平民，把出生记录
    #   放在右侧，记得弄平行对称」。实际渲染是把所有 chip **展平成两列等宽网格**
    #   （见 `_build_sidebar`），所以「插到出生记录左侧」＝把这 4 项排成
    #   `隐藏平民｜出生记录` / `已入谱牒｜续谱名单`：两行各 2 格、**正好对称**，
    #   原先那个「奇数补空格子」也随之消失。
    #   原先拆两行是因为三个挤一行放不下（侧栏 288px）—— 现在一行仍是 2 格，不变。
    FILTER_SINGLES = (("civil", "隐藏平民"), ("born", "出生记录"),
                      ("book", "已入谱牒"), ("watch", "续谱名单"))
    FILTER_SINGLE_ROWS = ((("civil", "隐藏平民"), ("born", "出生记录")),
                          (("book", "已入谱牒"), ("watch", "续谱名单")))
    # ★ 2026-09-28 使用者要求：「丁」从上面那张网格**搬进「男性等级」组**
    #   （截图圈的就是它，原先单占末尾一格、右边空着）。名字保持一个字，
    #   判据不动 —— 依然是**年龄 ≥ 15 的成丁**（见 FILTER_LEVELS 与 _pass_filter）。

    # ---- 男性等级（★ 2026-09-24 使用者要求）----
    #   原话：「筛选中增加男性等级选项让我可以快速定位到邦上等等」，
    #   并裁定「邦上中下其实邦对应君臣将豪圣神，前者把后者囊括就行了」——
    #   所以「邦」= 4 邦 + 5将 6臣 7君 8豪 10圣 11神（一档全收）。
    #   女性段（100+）不在本组口径内：组一旦勾上，女性人物自然被滤掉
    #   （要单看女性，用上面「女性人物」那一组）。
    #   组内或、整组不勾＝不限 —— 与上面三组同规。
    FILTER_LEVELS = (
        ("lv1", "邦", (4, 5, 6, 7, 8, 10, 11)),
        ("lv2", "上", (3,)),
        ("lv3", "中", (2,)),
        ("lv4", "下", (1,)),
        ("lv5", "庶", (0,)),
        # ★ 2026-09-28「丁」并入本组（使用者要求搬到这里）。⚠️ 它是**年龄**维度
        #   （≥15 岁）不是等级码 —— 第三元给空元组占位（`lv in ()` 恒假，不会误命中），
        #   真正的判定在 `_pass_filter` 里按 `Profile.age` 单独算；组内仍「或」。
        #   6 项正好排成 3 列 × 2 行，比原来 5 项（3+2）更整齐。
        ("ding", "丁", ()),
    )

    # 勾选框的**英文键 → `people_stats` 的中文键**（2026-09-21 修「一排 0」）。
    # 原来直接 st.get("hist") 取中文键的字典，永远取到 0。
    FILTER_COUNT_KEY = {
        "hist": "史实", "gen": "非史",
        "male": "男性", "female": "女性",
        "alive": "在世", "dead": "已故",
        "born": "出生记录", "book": "谱牒内", "watch": "续谱名单",
        # ★ 2026-09-25 「隐藏平民」的计数 = **非平民人数**（勾上后剩这些），
        #   与其它单选项「勾上后剩这些」的语义一致。这个键由 `_filter_ctx`
        #   直接补进 `_stats`（`people_stats` 不认识这个维度）。
        "civil": "非平民",
        "ding": "丁",
    }

    # ---- 余寿行底色（★ 2026-09-24 使用者要求）----
    #   原话：「根据剩余寿命，在人物界面用颜色或其他方式做个区分，比如还有
    #   60 年寿命那么就绿得发亮」「不能渐变的等级更多些吗？5 年一个等级？」。
    #   ttk.Treeview **不能给单个格子着色**（tag 只作用于整行），所以做成
    #   **整行底色**：余寿越长越绿、越短越红。
    #   优先级：选定紫 > 已故灰 > 余寿底色 > 斑马纹（见 `_render_table`）。
    YUSOU_STEP = 5          # 5 年一档
    YUSOU_BUCKETS = 11      # 0~54 年共 11 档，≥55 年一律最亮绿（再往上没差别）
    # 色相锚点：红（将尽）→ 黄（中点）→ 绿（长寿）。
    # ★ 关键是**每个锚点的 G−R 严格递增**（−82 → 0 → +77）——
    #   底色是常数，锚点插值 + 固定掺比之后整条带子才单调，
    #   不会出现「档 1 比档 0 还红」这种倒退（第一版就栽在这里）。
    YUSOU_ANCHORS = ((242, 160, 154), (235, 235, 140), (124, 201, 126))
    YUSOU_MIX_LIGHT = 0.62  # 浅色主题掺比（0 = 原底色，1 = 纯色相）
    YUSOU_MIX_DARK = 0.30   # 深色主题掺比 —— 掺太狠会让浅色正文糊在底色里

    # ---------------------------------------------------------------- 生命周期
    def __init__(self, holder, side_host, theme, app):
        """holder: 主视图容器；side_host: 外壳的侧栏容器（本视图自己填）；app: 主控制器。"""
        self.app = app
        self.root = app.root
        self.theme = theme
        self.side_host = side_host

        self.slot = None
        self.rel = None
        self.xref = None
        self.cur_family = None
        self.rows = []
        self.row_srcs = []
        self.all_pairs = []
        self.sort_key = None
        self.sort_desc = False
        self._fonts = {}
        self._nav_index = {}
        self._hist = []
        self._in_lineage = False
        self.mode = tk.StringVar(value="表格")

        self.people = {}
        self.followed = set()

        self._build(holder, side_host)
        self._apply_theme()
        # 实录槽由主控制器持有 —— 已载入就直接挂上（重建视图不该重读 30MB 存档）
        if app.record_slot is not None:
            self.attach(app.record_slot)
        else:
            self._autoload()

    def _autoload(self):
        """兜底自动载入 —— 正常路径是 `ShiguanApp._autoload_record()` 先载好。

        走投无路时（比如脚本里单独 new 一个 PersonView）才从这里找槽；
        找不到就只在状态栏说明，不弹窗、不报错。
        """
        app = self.app
        path = app.cfg.get("current_record") or ""
        if not (path and os.path.isdir(path)):
            slots = app.scan_record_slots()
            path = slots[0] if slots else ""
        if not path:
            self.set_status("没找到实录槽，点顶栏「实录」挑一个存档目录", warn=True)
            return
        if not app.open_record(path):
            self.set_status("这个实录槽读不了（可能是云端加密档）", warn=True)
            return
        self.attach(app.record_slot)

    def attach(self, slot):
        """把主控制器载好的实录槽接进来。

        载入 + 推导都只有 `app.open_record()` 一处，本视图**只接现成的**：
        `app.record_people` 是已推好的 code → Profile，
        `slot.tables` 里已挂好「合并总表 / 史实筛分表」。
        视图重建（换主题、切页签）因此不会再跑一遍推导 —— 30MB 存档不能重读。
        """
        self.slot = slot
        self.rel = self.app.record_rel
        self.xref = self.app.record_xref
        self.followed = set(self.app.followed_codes())
        era = getattr(self.app, "record_era", None) or "上古"
        PersonView._era = era

        # 派生表已由 app 推好；万一没有（比如单独 new 本视图）就自己补一次
        if not self.app.record_derived:
            self.app.refresh_record_derive(self.followed)
        self.people = self.app.record_people or {}
        # ★ 2026-09-28 全项目整理（第 1 批）：不再建 `PF.Lineage` 索引 ——
        #   它唯一的消费者是已删除的「世系视图」，而构造它要**遍历全谱**。
        # ★ 2026-09-24：余寿列要的参照年（本档走到哪一年）。正常路径由
        #   `record_derive.derive()` 设好，这里兜一次底（单独 new 本视图时）。
        try:
            PF.Profile.NOW_YEAR = S.game_year(slot)
        except Exception:
            PF.Profile.NOW_YEAR = None
        self._filter_ctx()          # 筛选要的旁路数据 + 各项计数
        self._update_follow_label()
        self._build_nav()
        # ★ 2026-09-24 接上主控制器记下的现场（表族 / 排序 / 搜索 / 两处滚动）；
        #   没存过时它自己会退回「选第一张表」。
        self.app.restore_person_view(self)
        warn = f"　⚠ {len(slot.warnings)} 个文件没读进来" if slot.warnings else ""
        self.set_status(f"{slot.name}　·　{slot.summary()}"
                        f"　·　人物 {len(self.people)} 人{warn}")

    def count_people(self):
        return len(self.people) if self.people else None

    def status_gen_text(self):
        n = len(self.people)
        if not n:
            return "未载入实录槽"
        hist = len(self.slot.tables.get("人物 · 史实人物", ()).rows) \
            if self.slot and self.slot.tables.get("人物 · 史实人物") else 0
        return f"实录 {n} 人（史实 {hist}）"

    # ---------------------------------------------------------------- 字体
    def font(self, family, size, bold=False):
        key = (family, size, bold)
        f = self._fonts.get(key)
        if f is None:
            f = tkfont.Font(family=family, size=size, weight="bold" if bold else "normal")
            self._fonts[key] = f
        return f

    def _fs(self, name, fallback):
        return getattr(self.theme, name, fallback)

    # ---------------------------------------------------------------- 构建
    def _build(self, holder, side_host):
        th = self.theme
        self._build_sidebar(side_host)

        body = holder
        self.body = body

        # 中间：表格
        mid = tk.Frame(body, bg=th.bg_app)
        self.mid = mid
        self.table_title = tk.Label(mid, text="（先选一个表族）", anchor="w",
                                    font=self.font(th.font_ui_fallback,
                                                   self._fs("fs_title", 13), True),
                                    bg=th.bg_app, fg=th.text)
        self.table_title.pack(fill=tk.X, padx=10, pady=(8, 4))
        # 标题里的「（……）」解释走悬停（使用者 2026-09-21 要求）；
        # 文本每次导航时更新，所以 Tooltip 只建一次、之后改 `.text` 即可。
        self._title_tip = Tooltip(self.table_title, "")

        wrap = tk.Frame(mid, bg=th.bg_app)
        wrap.pack(fill=tk.BOTH, expand=True, padx=(8, 4), pady=(0, 6))
        # ★ 2026-09-28（排查「跳转闪一下变空白」）：试过加 `exportselection=False`
        #   —— **ttk.Treeview 不支持这个选项**（`unknown option "-exportselection"`），
        #   那是 tk.Listbox / tk.Text 的东西。真因另找（见 `_on_row` 的保险）。
        self.table = ttk.Treeview(wrap, show="headings", selectmode="browse")
        vs = ttk.Scrollbar(wrap, orient="vertical", command=self.table.yview)
        hs = ttk.Scrollbar(wrap, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        self.table.bind("<<TreeviewSelect>>", lambda e: self._on_row())
        # ★ 2026-09-23「仅显所选」：人物页表格行也能右键「选定」（用名字匹配谱牒）
        self.table.bind("<Button-3>", self._on_row_right)
        # ★ 2026-09-24 双击一行 → 跳到「家谱」页代际模式，落到他的铭牌上
        self.table.bind("<Double-1>", self._on_row_double)

        # 右：详情
        # ★ 2026-09-26 写死 452 → _dpi.px(380)：150% 屏上信息卡偏窄，
        #   按钮排不下被裁（使用者圈报）；宽度也让给信息卡（表格列可拉伸）。
        # ★ 2026-09-28 详情卡改**两栏**（左「基本档案」/ 右「亲属关系 + 上溯 +
        #   所在编号」）—— 380 只够一栏，加宽到 560（150% 屏上约 840 物理像素）。
        right = tk.Frame(body, bg=th.bg_panel, width=_dpi.px(560))
        right.pack(side=tk.RIGHT, fill=tk.Y)
        right.pack_propagate(False)
        self.right = right

        headwrap = tk.Frame(right, bg=th.bg_panel)
        headwrap.pack(fill=tk.X)
        self.headwrap = headwrap
        # ★ 2026-09-28 使用者：「人物名下面那么大空间你不填补，非要往下再占空间？」
        #   —— 姓名右侧那片横向空白正好放「史实/非史实 + 谱」徽标
        #   （Excel 行1 就是 `人物卡 | 姓名 | 徽标` 横向排开），徽标不再单独占一行。
        # ★ 2026-09-28 使用者（第二轮，我上一轮理解错了）：「你不是放上面好好的吗，
        #   也不占空间，你怎么又把定位到表格放下面去了？我不是说只是对齐吗？」
        #   —— 对：**原位不动**（标题行右侧），只解决"左沿没跟『选定人物』平行"。
        #   要对齐，前提是**标题行与下面那张卡左右边界完全一致**：
        #     卡片：`dv.pack(padx=(8,0))` + 纵向滚动条 `padx=(0,4)`
        #     ⇒ 内容区左 8 / 右 4+滚动条宽
        #   而标题行原来是 `padx=12`（左右各 12）⇒ **必然差几像素**。
        #   这里把初值设成同一组，运行期再由 `_sync_title_row()` 按**实测坐标**
        #   校正（滚动条实际宽度只有量出来才准）。
        self.title_row = tk.Frame(headwrap, bg=th.bg_panel)
        self.title_row.pack(fill=tk.X, padx=(8, 4 + th.scrollbar_w), pady=(8, 4))
        self.detail_title = tk.Label(self.title_row, text="全字段详情", anchor="w",
                                     font=self.font(th.font_ui_fallback,
                                                    self._fs("fs_title", 13), True),
                                     bg=th.bg_panel, fg=th.text)
        self.detail_title.pack(side=tk.LEFT)
        self.badge_holder = tk.Frame(self.title_row, bg=th.bg_panel)
        self.badge_holder.pack(side=tk.LEFT, padx=(8, 0))

        # ★ 2026-09-28 使用者：「你这叫堆垃圾代码，你隐藏了我看不到了就好了是吧」
        #   —— 说得对。原来这里挂着一整条按钮条 `act_bar`（五颗按钮 + 一套
        #   "一行放不下就换行"的流式排布 `_place_act_btn` / `_act_rows`），
        #   其中**三颗早已被卡片上那排新按钮取代**：
        #       ◈ 看关系 → 右栏「亲属关系」段
        #       ⇱ 入谱   → 「立即入谱」
        #       ✦ 选定   → 「选定人物」
        #   我却只把它们"藏起来"、留着整条空 Frame 白占一行高（就是红圈那条）。
        #   现在：**删掉框架、删掉那三颗按钮和整套流式排布**，只留两颗真正
        #   不可替代的（← 返回上一页 / ⌖ 定位到表格），直接挂在**标题行右侧**，
        #   与「来源」同行，不额外占任何高度。
        self.detail_src = tk.Label(self.title_row, text="", anchor="w",
                                   justify=tk.LEFT, bg=th.bg_panel, fg=th.text_3,
                                   font=self.font(th.font_ui_fallback,
                                                  self._fs("fs_body_sm", 10)))
        self.detail_src.pack(side=tk.LEFT, padx=(12, 0))
        # ★ 2026-09-28 使用者：「定位到表格 bar 的左沿跟『选定人物』的左沿平行，
        #   bar 等大」—— 它**仍在标题行右侧**（那是"上面好好的、也不占空间"的原位），
        #   但要与卡片里的「选定人物」对齐：卡片那排按钮是**6 列网格、各跨 2 格**，
        #   所以「选定人物」的左沿 = 卡片左缘 + 卡片宽 × 4/6。
        #   ⇒ 这里给定位按钮做一个**与卡片两格等宽的槽**（宽度由
        #   `_sync_title_row()` 按实测的卡片宽 ÷ 3 同步），按钮填满槽：
        #   左沿、宽度、文字左沿（`anchor="w"`）三者全与「选定人物」一致。
        self.title_slot = tk.Frame(self.title_row, bg=th.bg_panel, width=1)
        self.title_slot.pack_propagate(False)
        # `padx=(0, 6)` 必须与 `_mini_act` 的格子内边距**同值** ——
        # 「选定人物」是 `grid(..., padx=(0, 6))`，它的右缘因此离卡片右缘 6px；
        # 槽也留 6px，槽里的按钮右缘才与它齐平，配合"槽宽 = 按钮实测宽"
        # ⇒ **左沿重合**（这一步是"量出来的"，不是"算出来的"）。
        self.title_slot.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 6))
        self.locate_btn = self._mini_btn(self.title_slot, "定位到表格",
                                         self._locate_current)
        self.back_btn = self._mini_btn(self.title_row, "← 返回上一页", self._rel_back)
        self.back_btn.pack(side=tk.RIGHT, padx=(6, 0))

        self.dv = tk.Canvas(right, highlightthickness=0, bd=0, bg=th.bg_panel)
        dvs = ttk.Scrollbar(right, orient="vertical", command=self.dv.yview)
        self.dv.configure(yscrollcommand=dvs.set)
        self.dv.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 0), pady=(0, 8))
        dvs.pack(side=tk.RIGHT, fill=tk.Y, pady=(0, 8), padx=(0, 4))
        self.detail_inner = tk.Frame(self.dv, bg=th.bg_panel)
        # ★ 2026-09-28 使用者红圈报「右侧一大片空白，两排单元格为什么空着」──
        #   真因**不是**多余的单元格，而是：Canvas 里的 window **默认按内容需求定宽**
        #   （`create_window` 不给 width 就是这样）。内容一旦不宽（左栏值都短、
        #   右栏又加了 wraplength），整张表就只占左边一段，右边留白。
        #   ⇒ 把内层 Frame 的宽**始终钉死为画布宽**（内容少也铺满）。
        self._detail_win = self.dv.create_window((0, 0), window=self.detail_inner,
                                                anchor="nw")
        def _on_dv_configure(e):
            self.dv.itemconfigure(self._detail_win, width=e.width)
            # 卡片宽度变了 ⇒ 标题行边界与「定位到表格」槽宽跟着重新对齐
            self._sync_title_row()
        self.dv.bind("<Configure>", _on_dv_configure)
        self.detail_inner.bind(
            "<Configure>", lambda e: self.dv.configure(scrollregion=self.dv.bbox("all")))
        for w in (self.dv, self.detail_inner):
            w.bind("<MouseWheel>",
                   lambda e: self.dv.yview_scroll(int(-e.delta / 120) * 2, "units"))

        # 中间栏最后 pack（它带 expand，必须排在定宽栏之后）
        mid.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def _build_sidebar(self, side_host):
        """实录页侧栏：人物 / 筛选 / 搜索 三张卡片（2026-09-23 UI 重规划）。

        与谱牒页侧栏（shell.Sidebar）同款 Card 风格 —— 标题竖色条 + 灰字标题
        + 卡体内距统一，四页一套面孔。
        「实录层 · 只读」标记由工具栏最左的层级徽章接管（不再重复挂在这里）。
        """
        th = self.theme
        side = tk.Frame(side_host, bg=th.bg_panel, width=th.sidebar_w)
        side.pack(fill=tk.BOTH, expand=True)
        self.side = side
        pad = {"padx": 8, "pady": (6, 0)}

        # === 人物（表族导航：全部人物 / 续谱名单）===
        self.card_nav = Card(side, th, "人物")
        self.card_nav.pack(fill=tk.X, **pad)
        navwrap = tk.Frame(self.card_nav.body, bg=th.bg_card)
        navwrap.pack(fill=tk.X)
        # height=2：只有「全部人物 / 续谱名单」两行，给足两行就行，多了会空一大片
        self.nav = ttk.Treeview(navwrap, show="tree", selectmode="browse", height=2)
        self.nav.grid(row=0, column=0, sticky="nsew")
        navwrap.columnconfigure(0, weight=1)
        self.nav.bind("<<TreeviewSelect>>", lambda e: self._on_nav())

        # === 筛选：三个二选一维度做成勾选（打 ✓），可多选、可全不勾＝不限 ===
        self.card_filter = Card(side, th, "筛选")
        self.card_filter.pack(fill=tk.X, **pad)
        fbox = tk.Frame(self.card_filter.body, bg=th.bg_card)
        fbox.pack(fill=tk.X)
        # ★ 2026-09-23 对齐精修：全部筛选做成**一张等宽两列的固定表格**
        #   （原先是 5 个独立 ChipRow，每行按内容自适应宽 —— 于是「出生记录 9」
        #   这种短计数会把右边那格往左拽，与上面的格子对不齐，像坏掉的表格）。
        #   现在 9 个选项共用一行 ChipRow、grid_cols=2 等宽列：格子大小一致、
        #   左对齐，空位留白。组内或/组间与的判定逻辑不受影响（仍读 FILTER_GROUPS）。
        self.chips = {}
        self._chip_rows = []
        _grid_items = []
        for grp in self.FILTER_GROUPS:
            _grid_items.extend(list(grp))
        for grp in self.FILTER_SINGLE_ROWS:
            _grid_items.extend(list(grp))
        if len(_grid_items) % 2:                 # 奇数补一格空白，保持网格整齐
            _grid_items.append(("_blank", None))
        row = ChipRow(fbox, th, items=_grid_items, gap=6, pad=7, grid_cols=2,
                      size=th.fs_body_sm, command=lambda *a: self._on_filter())
        row.pack(fill=tk.X)
        self._chip_rows.append(row)
        for k, _t in _grid_items:
            if k != "_blank":
                self.chips[k] = row

        # ★ 2026-09-24 使用者要求：「筛选中增加男性等级选项让我可以快速定位到
        #   邦上等等」。单独一行（5 格等宽 3 列，两行放得下）——
        #   挤进上面那张 2 列表格会把「邦/上/中/下/庶」拆到三行去。
        #   不挂计数后缀：`people_stats` 没有按等级分档，且单字格放不下。
        tk.Label(fbox, text="男性等级", anchor="w", bg=th.bg_card, fg=th.text_3,
                 font=(th.font_ui_fallback, th.fs_body_sm)).pack(
            fill=tk.X, pady=(5, 3))
        self.chips_level = ChipRow(
            fbox, th, items=[(k, t) for k, t, _c in self.FILTER_LEVELS],
            gap=6, pad=7, grid_cols=3, size=th.fs_body_sm,
            command=lambda *a: self._on_filter())
        self.chips_level.pack(fill=tk.X)
        for k, _t, _c in self.FILTER_LEVELS:
            self.chips[k] = self.chips_level

        hitrow = tk.Frame(fbox, bg=th.bg_card)
        hitrow.pack(fill=tk.X, pady=(2, 0))
        self.hit_lbl = tk.Label(hitrow, text="", anchor="w", bg=th.bg_card,
                                fg=th.accent,
                                font=(th.font_ui_fallback, th.fs_body_sm, "bold"))
        self.hit_lbl.pack(side=tk.LEFT)
        for text, cmd in (("全选", lambda: self._set_all_filters(True)),
                          ("清空", lambda: self._set_all_filters(False))):
            FlatButton(hitrow, th, text=text, command=cmd, kind="default",
                       padx=6, size=th.fs_body_sm).pack(side=tk.RIGHT, padx=(4, 0))

        # === 搜索（底部常驻）===
        foot = tk.Frame(side, bg=th.bg_panel)
        foot.pack(side=tk.BOTTOM, fill=tk.X)
        self.card_search = Card(foot, th, "搜索")
        self.card_search.pack(fill=tk.X, padx=8, pady=(6, 8))
        self.search_var = tk.StringVar()
        ent = input_box(self.card_search.body, th, self.search_var)
        ent.pack(fill=tk.X, ipady=3)
        ent.bind("<Return>", lambda e: self._apply_filter())
        self.search_var.trace_add("write", lambda *a: self._apply_filter())
        self.search_entry = ent

        self.follow_lbl = tk.Label(self.card_search.body, text="", anchor="w",
                                   bg=th.bg_card, fg=th.accent,
                                   wraplength=_dpi.px(232), justify=tk.LEFT,
                                   font=(th.font_ui_fallback, th.fs_body_sm))
        self.follow_lbl.pack(fill=tk.X, pady=(5, 0))
        Tooltip(self.follow_lbl,
                "续谱名单＝你点名要收的非史实人物。\n"
                "非史实人物默认一个都不收；点名的那几位会连同他们的\n"
                "纯父系后裔一起抽进谱（不含女儿支）。\n"
                "增删入口：选中人物 → 点工具栏「加入族谱」。")

    # ---------------------------------------------------------------- 筛选逻辑
    def _filter_on(self, key):
        row = self.chips.get(key)
        return bool(row and row._state.get(key))

    def _set_all_filters(self, value):
        for row in self._chip_rows:
            row.set_all(value)
        # ★ 2026-09-24：等级组**不参与「全选」** —— 5 档全勾等于「只留男性且
        #   有等级的」，会把女性整片滤掉，跟「全选 = 什么都不限」对不上。
        #   所以两个按钮都把它清掉（不勾 = 不限），语义才自洽。
        self.chips_level.set_all(False)
        # ★ 2026-09-25 把这条规矩**补全到所有「收窄型」单选项**（此前只处理了
        #   等级组）。实测点「全选」会得到 **0 行**：出生记录 / 已入谱牒 /
        #   续谱名单三个「只留」型同时勾上就是三重交集，人可能一个不剩 ——
        #   这与「全选 = 什么都不限」完全矛盾。隐藏平民（勾上即收窄）同理。
        for key in ("born", "book", "watch", "civil"):
            row = self.chips.get(key)
            if row is not None:
                row.set_state(key, False)
        self._on_filter()

    def _on_filter(self):
        self._apply_filter()

    def _pass_filter(self, row, code):
        """三个二选一维度：**组内或、组间与、整组不勾＝不限**。"""
        for grp in self.FILTER_GROUPS:
            keys = [k for k, _t in grp]
            if not any(self._filter_on(k) for k in keys):
                continue
            hit = False
            if "hist" in keys:
                ish = PF.is_historical(code)
                hit = (ish and self._filter_on("hist")) or \
                      ((not ish) and self._filter_on("gen"))
            elif "male" in keys:
                isf = str(row.get("Ren_Sex")) == "1"
                hit = (isf and self._filter_on("female")) or \
                      ((not isf) and self._filter_on("male"))
            elif "alive" in keys:
                # 默认已故 —— 与 `RelationGraph` 同口径（只在族谱表里的人算已故）。
                # 见 `_filter_ctx` 的说明：原来默认 True，勾「在世」会混进已故祖先。
                al = self._alive_of.get(code, False)
                hit = (al and self._filter_on("alive")) or \
                      ((not al) and self._filter_on("dead"))
            if not hit:
                return False
        # 男性等级 ＋ 丁（★ 2026-09-28 合并成一组）：组内或、整组不勾＝不限。
        # 「邦」一档已把 将/臣/君/豪/圣/神 囊括进来（见 FILTER_LEVELS）；
        # 「丁」是**年龄**维度（≥15 岁），与等级档并列同组 —— 勾「丁」＝只要成丁，
        # 勾「邦」＝只要邦级，两个都勾＝二者之一（组内或）。
        if any(self._filter_on(k) for k, _t, _c in self.FILTER_LEVELS):
            try:
                lv = int(row.get("Ren_Leve"))
            except (TypeError, ValueError):
                lv = None
            hit = any(self._filter_on(k) and lv in codes
                      for k, _t, codes in self.FILTER_LEVELS)
            if not hit and self._filter_on("ding"):
                _age = getattr(self.people.get(code), "age", None)
                hit = isinstance(_age, (int, float)) and _age >= 15
            if not hit:
                return False
        if self._filter_on("born") and code not in self._born_codes:
            return False
        if self._filter_on("book") and code not in self._book_codes:
            return False
        if self._filter_on("watch") and code not in self.followed:
            return False
        # ★ 2026-09-25 「隐藏平民」：勾上就只留身份非空的人（主 / 谥 / 官）。
        #   （「丁」的判定已并到上面的等级组 —— 2026-09-28 搬组时一起挪。）
        if self._filter_on("civil") and code not in self._non_civil_codes:
            return False
        return True

    def _filter_ctx(self):
        """筛选要用的两组旁路数据：在世/已故、出生表 / 谱牒里的编号。

        在世/已故按四张表的先后**先来优先**，与 `relations.RelationGraph`
        同一套口径 —— 口径不一致的话「显示 3998」和「勾了筛出 4001」会对不上。

        ★ 2026-09-21 修：默认值由 `True` 改成 `False`。
          合并总表里有一大批人**只在族谱表**里（实测 Save_All_1：8988 人里 2150 人），
          关系图给这拨人记的是 `alive=False`（已故），而这里原来查不到就当在世，
          于是勾「在世人物」仍会混进一堆已经死掉的祖先。
          实测三张表（活人/女性/出生）与已故表互不重叠，所以「先来优先」实际不起作用。
        """
        self._alive_of = {}
        self._born_codes = set()
        if self.slot is not None:
            for tname in ("Save_Ren_Data", "Save_Dead_Ren_Data",
                          "Save_Woman_Data", "Save_Chu_Sheng_Data"):
                t = self.slot.table(tname)
                if t is None:
                    continue
                al = tname != "Save_Dead_Ren_Data"
                for r in t.rows:
                    c = str(r.get("Ren_Code") or "")
                    if not c:
                        continue
                    if c not in self._alive_of:
                        self._alive_of[c] = al
                    if tname == "Save_Chu_Sheng_Data":
                        self._born_codes.add(c)
        # ★ 2026-09-25：「谱牒总谱」里的人不在实录槽里，在世/已故按**卒年**判
        #   （setdefault：实录槽有记载的人以存档为准，不覆盖）。
        bt = self.slot.table(RD.BOOK_NAME)
        if bt is not None:
            for r in bt.rows:
                c = str(r.get("Ren_Code") or "")
                if c and c not in self._alive_of:
                    # ★ 2026-09-26：改按 **Profile 卒年**（含「生年+享年」推算）
                    #   判在世 —— 原来只认原始卒年字段，全谱里推算出卒年的
                    #   3133 人全被算成「在世」（使用者：全谱没有死人）。
                    _rp = (self.app.record_people or {}).get(c)
                    if _rp is not None:
                        self._alive_of[c] = not bool(_rp.death)
                    else:
                        self._alive_of[c] = not bool(
                            str(r.get("Ren_End_Time") or "").strip())
        try:
            self._book_codes = {str(v.get("code")) for v in (self.app.people or {}).values()
                                if v.get("code")}
        except Exception:
            self._book_codes = set()
        # ★ 2026-09-25：**计数与「隐藏平民」的口径必须跟着当前表走**。
        #   总谱（《全史存档》那一万多人）与实录槽是两批人 ——
        #   原来一律按实录槽算，于是总谱上显示「共 11874 人」（实录槽），
        #   筛选栏数字也全是实录层口径（史实 4806 / 非史 7068 / 男性 10825…），
        #   而表里明明 13526 行 ⇒ 使用者看着就像「筛选没生效」。
        bt = self.slot.table(RD.BOOK_NAME)
        if self.cur_family == RD.BOOK_NAME and bt is not None:
            self._stats = RD.book_stats(bt.rows, self._alive_of,
                                        self._born_codes, self._book_codes,
                                        self.followed)
            # 「隐藏平民」也得按**这张表**的行算（否则会拿实录槽的集合去筛总谱，
            # 勾上只剩两边都有的人 —— 数字 1776 与结果 158 对不上的那种错）。
            self._non_civil_codes = {str(r.get("Ren_Code") or "")
                                     for r in bt.rows if PF.identity_of(r)}
        else:
            # 计数只在换槽 / 换名单 / 换表时算一次 —— 每敲一个字都重算不值当
            self._stats = RD.people_stats(self.slot, self._book_codes,
                                          self.followed)
            # 「隐藏平民」要的集合：身份非空的人（主 / 谥 / 官）。
            #   判据在 `Profile.identity` 里（本人记录即可判，不联表）；
            #   总谱那批走上面那个分支、按**行**算（见 `book_stats`）。
            try:
                self._non_civil_codes = {
                    str(c) for c, p in (self.people or {}).items()
                    if getattr(p, "identity", "")}
            except Exception:
                self._non_civil_codes = set()
            # ★ 「隐藏平民」的计数（非平民人数）直接补进结果字典 —— 这样计数渲染
            #   （`_refresh_filter_counts`）不必为这一项开特例。
            if isinstance(self._stats, dict):
                self._stats["非平民"] = len(self._non_civil_codes)
        self._ctx_family = self.cur_family

    def _refresh_filter_counts(self):
        """勾选框后面的数字 —— 走 `record_derive.people_stats`，口径与筛选同源。

        ★ 2026-09-21 修「每个后面都有个 0」：
          `people_stats` 返回的键是**中文**（史实/非史/男性/女性/在世/已故/…），
          而这里原来直接拿勾选框的**英文键**（hist/gen/male/…）去 `st.get(key, 0)`，
          键名对不上 → 每一项都取到默认值 0（截图里那一排 0 就是这么来的）。
          现在过一层 `FILTER_COUNT_KEY` 显式映射。
        """
        st = dict(getattr(self, "_stats", None) or {})
        # ★ 2026-09-26 「丁」的计数：Profile.age ≥ 15 的人数（people_stats
        #   不认识这个维度，这里从 record_people 直算）。
        try:
            st["丁"] = sum(1 for _p in (self.people or {}).values()
                          if isinstance(getattr(_p, "age", None), (int, float))
                          and _p.age >= 15)
        except Exception:
            pass
        # ★ 2026-09-21 使用者要求「把所有选项都对齐」：
        #   计数必须**定宽右对齐**，否则「出生记录 16」和「史实人物 3245」位数不同，
        #   同一列的两个胶囊会错开（实测第二列起点随左侧计数位数左右漂）。
        #   宽度取全部计数里最长的那个位数 —— 换存档时数字变长也不会错位。
        w = max([len(str(v)) for v in st.values()] or [1])
        for row in self._chip_rows:
            for key in list(row._state):
                zh = self.FILTER_COUNT_KEY.get(key, key)
                row.set_suffix(key, f"  {st.get(zh, 0):>{w}d}")
        # ★ 2026-09-28 使用者裁定：「丁」格**只要一个字**，后面那串数字去掉
        #   （原话「不要括号里的字，一个字当按钮名」）—— 等级组一概不挂计数，
        #   `_chip_rows` 也遍历不到 chips_level，这里刻意什么都不做。
        #   ⚠️ 计数只是**不显示**：`_filter_ctx` 仍把 `st["丁"]`（age ≥ 15 的人数）
        #   算好放进统计，勾选判定与它同源，随时要恢复显示只加一行即可。
        self.hit_lbl.configure(
            text=f"命中 {len(self.all_pairs)} / 共 {st.get('全部', 0)} 人")


    def toolbar_groups(self):
        """工具栏分组（2026-09-23 对齐精修）：名单（橙金·写）→ 表格 → 帮助。

        「加入族谱」是写动作（写的是续谱名单），按颜色语义走橙金。
        按钮文案从「加入续谱名单」缩到 4 字（使用者要求：能短就短）。
        """
        return [
            ("名单", [
                ("follow", "加入族谱", self._toggle_follow_current, "edit",
                 "把当前人物加入自动续谱名单（续谱时连同其纯父系后裔一起抽取）"),
            ]),
            ("表格", [
                ("fold", "展开全部", self._expand_all, "tool", "展开表格全部折叠的分组"),
            ]),
            ("帮助", [
                ("help", "字段说明", self._show_help, "tool", "查看各字段的含义与取值说明"),
                ("reload", "重新载入", self._reload, "tool", "从本机缓存重新读取实录"),
            ]),
            # ★ 2026-09-24 使用者要求：把「清空封国」从**表格页**搬到**人物页
            #   「重新载入」后面**（那是他清理提取脏数据时的顺手位置）。
            ("危险", [
                ("clearstates", "清空封国", self.app.clear_all_states, "danger",
                 "一键清除本谱牒档所有人物的封国与世系（爵位与小传保留）"),
            ]),
        ]

    # ---------------------------------------------------------------- 主题
    def _apply_theme(self):
        t = self.theme
        for w in (self.body, self.mid):
            w.configure(bg=t.bg_app)
        for w in (self.right, self.side, self.headwrap, self.title_row):
            w.configure(bg=t.bg_panel)
        self.table_title.configure(bg=t.bg_app, fg=t.text)
        self.detail_title.configure(bg=t.bg_panel, fg=t.text)
        self.detail_src.configure(bg=t.bg_panel, fg=t.text_3)
        self.dv.configure(bg=t.bg_panel)
        self.detail_inner.configure(bg=t.bg_panel)
        self.search_entry.configure(bg=t.bg_input, fg=t.text, insertbackground=t.text,
                                    highlightbackground=t.border_2, highlightcolor=t.accent)
        self._paint_act_bar()

        st = ttk.Style()
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure("Treeview", background=t.bg_card, fieldbackground=t.bg_card,
                     foreground=t.text, rowheight=_dpi.px(23), borderwidth=0,
                     font=(t.font_ui_fallback, t.fs_body_sm))
        # ★ 2026-09-24 使用者报「姓名 / 性别栏的汉字和下面内容的汉字左沿不平行」。
        #   根因：`Treeview` 的行内容**没有横向内距**（Treeview.padding 未设 = 0），
        #   而 `Treeview.Heading` 默认 padding 是 3（clam），这里原来写的是 6 ——
        #   于是表头汉字整体比单元格汉字右移 6px。横向内距改成 0 即左沿齐平，
        #   纵向留 4 给表头一点呼吸。
        st.configure("Treeview.Heading", background=t.bg_bar, foreground=t.text_2,
                     relief="flat", padding=(0, 4),
                     font=(t.font_ui_fallback, t.fs_body_sm, "bold"))
        st.map("Treeview.Heading", background=[("active", t.bg_hover)])
        st.map("Treeview", background=[("selected", t.bg_sel)],
               foreground=[("selected", t.text)])
        st.configure("Vertical.TScrollbar", background=t.border_2, troughcolor=t.bg_panel,
                     borderwidth=0, arrowcolor=t.text_2)
        st.configure("Horizontal.TScrollbar", background=t.border_2, troughcolor=t.bg_panel,
                     borderwidth=0, arrowcolor=t.text_2)
        st.configure("Nav.Treeview", background=t.bg_card, fieldbackground=t.bg_card,
                     foreground=t.text, rowheight=_dpi.px(22), borderwidth=0,
                     font=(t.font_ui_fallback, max(9, t.fs_body_sm - 1)))
        st.map("Nav.Treeview", background=[("selected", t.bg_sel)],
               foreground=[("selected", t.text)])
        self.nav.configure(style="Nav.Treeview")
        self.table.tag_configure("odd", background=t.row_even)
        # ★ 2026-09-24 余寿档位底色（见 YUSOU_* 说明）。配置在 dead/focus **之前**，
        #   让已故灰、选定紫仍然压得住（本行内容本身也只在两者都不适用时才挂 ys）。
        for _k in range(self.YUSOU_BUCKETS):
            self.table.tag_configure(f"ys{_k}",
                                     background=self._yusou_color(t.bg_card, _k))
        # ★ 2026-09-23 实录层表格补齐两套标注：
        #   dead 已故灰底（与谱牒层表格同一判据来源，见 `_filter_ctx._alive_of`）
        #   focus「选定」高亮 —— 紫底紫字（theme.focus_bg/focus_hi），
        #   与家谱铭牌、时间轴铭牌、谱牒层表格**同一判据同一颜色**，
        #   在满屏几千行里一眼找到自己点过的人。tag 最后 configure = 优先级最高，
        #   会压过 odd/dead 两套底。
        self.table.tag_configure("dead", background=t.bg_dead or t.bg_card)
        self.table.tag_configure("focus", background=t.focus_bg,
                                 foreground=t.focus_hi)
        # ★ 2026-09-23 使用者要求「史实角色加黑」区分（Treeview 单元格做不了
        #   「右上角小角标」，改用颜色区分）：非史实人物整行文字压灰，
        #   史实人物保持正文色 —— 与谱牒层表格的 nohist tag 同一套做法。
        self.table.tag_configure("nohist", foreground=t.text_3)
        self._bind_nav_tip()
        self._build_nav()

    def _bind_nav_tip(self):
        if getattr(self, "_nav_tip_bound", False):
            return
        self._nav_tip_bound = True
        st = {"w": None}

        def motion(e):
            iid = self.nav.identify_row(e.y)
            txt = self.nav.item(iid, "text") if iid else ""
            cur = st.get("w")
            if cur is not None:
                cur.destroy()
                st["w"] = None
            if not iid or not txt:
                return
            w = tk.Toplevel(self.nav)
            w.wm_overrideredirect(True)
            w.wm_geometry(f"+{e.x_root + 12}+{e.y_root + 16}")
            tk.Label(w, text=txt, bg="#3a3a3a", fg="#f5f5f5", padx=6, pady=3,
                     font=(self.theme.font_ui_fallback, 10)).pack()
            st["w"] = w

        def leave(_e=None):
            cur = st.get("w")
            if cur is not None:
                cur.destroy()
                st["w"] = None

        self.nav.bind("<Motion>", motion, add="+")
        self.nav.bind("<Leave>", leave, add="+")

    # ---------------------------------------------------------------- 载入
    def _reload(self):
        if self.slot:
            p = self.slot.root
            self.slot = None
            if self.app.open_record(p):
                self.attach(self.app.record_slot)

    def _progress(self, done, total, name):
        if done % 40 == 0 or done == total:
            self.set_status(f"载入中… {done}/{total}　{name}")

    # ---------------------------------------------------------------- 派生表
    # 合并总表 / 史实筛分表 / 族谱摊平 —— 全部搬到 `app/record_derive.py`，
    # 由 `ShiguanApp.open_record()` 在**载入实录槽时**就跑（不依赖本页被打开）。
    # 本视图只接 `app.record_people`，不再自己推。

    # ---------------------------------------------------------------- 续谱名单
    # 语义已升级：★ 收藏的这些人既用于「看其后裔」，也是**续谱时要额外收的人**
    # （抽取器 `--watch`，连同其父系后裔一起抽进谱）。
    def set_followed(self, codes):
        self.followed = {str(c) for c in codes if str(c)}
        # 推到主控制器：落盘到谱牒的 source.watch + 派生表重推
        self.app.set_followed_codes(self.followed)
        self.people = self.app.record_people or {}
        self._filter_ctx()
        self._update_follow_label()
        self._build_nav()
        # ★ 2026-09-24 使用者要求：「在右侧的加入族谱点了一下以后，自动跳到
        #   续谱名单一栏，不要自动跳」。原来这里会 `goto_family("人物 · 关注世系")`
        #   —— 不光把表格切走，`goto_family` 还会**清掉搜索框**、重选第一行，
        #   等于把使用者的现场整个打断。现在只更新计数与导航行，不切表。
        #   （要看续谱名单，自己点左侧导航那一行即可。）

    def toggle_follow(self, code):
        code = str(code)
        self.followed.discard(code) if code in self.followed else self.followed.add(code)
        self.set_followed(self.followed)

    def _toggle_follow_current(self):
        code = self._current_code()
        if code:
            self.toggle_follow(code)
        else:
            self.set_status("先选中一个人物", warn=True)

    def _update_follow_label(self):
        """续谱名单那一行 —— 括号里的解释已挪到悬停（使用者 2026-09-21 要求）。"""
        n = len(self.followed)
        self.follow_lbl.configure(text=f"★ 续谱名单：{n} 人")

    # ---------------------------------------------------------------- 导航
    def _nav_order(self):
        """表族导航。

        常规两张：**全部人物**（合并总表）与**续谱名单**（点名那几支的后裔）；
        《全史存档》这类**合并谱**多一张 **谱牒总谱**（谱牒自己那一万多人，
        跨 32 个剧本、没有单一实录槽 —— 见 `record_derive.attach_book_table`）。
        原来那几张人物派生表（史实 / 非史实 / 在世 / 女性 / 已故 / 出生记录）
        不再单独列 —— 它们的语义已经被上面的勾选框完全覆盖，
        同一件事摆两个入口只会让人不知道该点哪个。
        """
        if self.slot is None:
            return []
        tables = self.slot.tables
        picked = [n for n in self.PERSON_ORDER if n in tables]
        items = [(n, tables[n]) for n in picked]
        return [("人物", items)] if items else []

    def _build_nav(self):
        """填表族导航行。

        ★ 2026-09-21：不再插「人物 (总)」这个父节点 —— 多一层展开/收起只会
          白占一行高度（使用者：「表族…太空了这一栏」）。现在是**平铺行**，
          与筛选块合成一个「人物」区。
        ★ 2026-09-25：行数不再写死两行 —— 合并谱多一张「谱牒总谱」，最多三行
          （谱牒总谱 / 全部人物 / 续谱名单）。按实际行数给高度：既不留空，
          也不会把第三行挤到看不见（导航本来就可滚动）。
        """
        self.nav.delete(*self.nav.get_children())
        self._nav_index = {}
        rows = 0
        for _cat, items in self._nav_order():
            for name, t in sorted(items, key=lambda x: -len(x[1])):
                lbl = self.PERSON_NAV_LABEL.get(name) or t.label or C.label_of_family(name)
                kind = "史实" if name == "人物 · 史实人物" else \
                       ("非史实" if name == "人物 · 非史实" else "")
                tail = f"　·　{kind}" if kind else ""
                kid = self.nav.insert("", "end", text=f"{lbl}　{len(t)}{tail}")
                self._nav_index[kid] = name
                rows += 1
        self.nav.configure(height=max(2, rows))

    def _rebuild_nav(self):
        self._build_nav()
        self._select_first_family()

    def _select_first_family(self):
        kids = self.nav.get_children()
        if not kids:
            return
        self.nav.selection_set(kids[0])
        self.nav.see(kids[0])

    def _on_nav(self):
        sel = self.nav.selection()
        if not sel:
            return
        name = self._nav_index.get(sel[0])
        if name:
            self.cur_family = name
            self.sort_key = None
            t = self.slot.tables[name]
            lbl, hint = split_hint(t.label or C.label_of_family(name))
            tail = "" if name in (t.label or "") else f"　·　表名 {name}"
            self.table_title.configure(text=f"{lbl}　·　{len(t)} 条{tail}")
            self._title_tip.text = hint
            self._apply_filter()

    def goto_family(self, name, select_code=None):
        if self.slot is None or name not in self.slot.tables:
            return False
        for kid, nm in self._nav_index.items():
            if nm == name:
                self.nav.selection_set(kid)
                self.nav.see(kid)
                break
        self.cur_family = name
        self.sort_key = None
        self.search_var.set(str(select_code) if select_code is not None else "")
        self._apply_filter()
        if select_code is not None:
            kids = self.table.get_children()
            if kids:
                self.table.selection_set(kids[0])
                # 2026-09-29：从别处跳过来（查档 / 定位人物 / 亲属链接）也要**居中**
                self._center_table_row(kids[0])
        return True

    # ---------------------------------------------------------------- 表格
    def _columns(self):
        t = self.slot.tables[self.cur_family]
        if self.cur_family in self.PERSON_VIEW_FAMILIES \
                or self.cur_family in self.PERSON_RAW_TABLES:
            return self._person_columns()
        spec = C.COLUMNS.get(self.cur_family)
        if spec is None:
            for k, v in C.COLUMNS.items():
                if k.split("/")[-1] == self.cur_family.split("/")[-1]:
                    spec = v
                    break
        if spec is None:
            flat = [f for f in t.fields if f not in HEAVY_FIELDS and f not in MUTE_FIELDS]
            spec = [(f, 110, False) for f in flat[:C.FALLBACK_COLS]]
        return [(key, w, right) for key, w, right in spec if key in t.fields]

    def _person_columns(self):
        """人物页的列（键 / 宽 / 是否右对齐）。

        ★ 2026-09-21：宽度改成**按实际内容算**（`_fit_person_cols`）。
          原来写死的宽度是按秦末档试出来的，换存档（姓名更长 / 势力名更长）
          就会切字 —— 使用者原话「表格宽度是否合理，是否会掩盖到字」。
        """
        widths = self._fit_person_cols()
        # 余寿跟智略/年龄一样是数字，右对齐（表头也跟着右对齐，左沿才齐）
        right = {"智略", "年龄", "余寿"}
        return [(f"_p:{c}", widths.get(c, 92), c in right)
                for c in self._visible_cols()]

    # ---- 余寿配色（★ 2026-09-24）----------------------------------------
    @staticmethod
    def _rgb(c):
        return [int(c[i:i + 2], 16) for i in (1, 3, 5)]

    @staticmethod
    def _hex(rgb):
        return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(v)))) for v in rgb)

    @classmethod
    def _mix(cls, c1, c2, t):
        """两个 `#rrggbb` 之间线性插值（t=0 取 c1，t=1 取 c2）。"""
        a, b = cls._rgb(c1), cls._rgb(c2)
        return cls._hex([a[i] + (b[i] - a[i]) * t for i in range(3)])

    @classmethod
    def _yusou_color(cls, bg, k):
        """第 k 档（0 = 将尽，越大越长寿）在底色 `bg` 上染出来的颜色。

        做法：先在 `YUSOU_ANCHORS`（红→黄→绿）上按档位取一个色相，
        再按**固定掺比**往底色里掺。掺比按底色亮度二选一 ——
        浅色主题掺 0.62（看得清那层色），深色主题只掺 0.30（不然浅色正文
        糊在底色里）。

        因为锚点的 G−R 严格递增、底色与掺比都是常数，整条带子**必然单调**：
        余寿越长，绿得越明显。调色时务必守住这条（乱改锚点会倒退）。
        """
        span = max(1, cls.YUSOU_BUCKETS - 1)
        a = cls.YUSOU_ANCHORS
        t = k / span
        if t <= 0.5:
            lo, hi, u = a[0], a[1], t / 0.5
        else:
            lo, hi, u = a[1], a[2], (t - 0.5) / 0.5
        hue = [lo[i] + (hi[i] - lo[i]) * u for i in range(3)]
        brgb = cls._rgb(bg)
        lum = 0.299 * brgb[0] + 0.587 * brgb[1] + 0.114 * brgb[2]
        m = cls.YUSOU_MIX_LIGHT if lum > 140 else cls.YUSOU_MIX_DARK
        return cls._hex([brgb[i] + (hue[i] - brgb[i]) * m for i in range(3)])

    @classmethod
    def _yusou_bucket(cls, years):
        """余寿（年）→ 档位；算不出来返回 None。"""
        if years is None:
            return None
        return max(0, min(int(years) // cls.YUSOU_STEP, cls.YUSOU_BUCKETS - 1))

    def _yusou_of(self, code, row):
        """这个人的余寿（年）—— 见 `profiles.Profile.yushou`。"""
        p = self.people.get(str(code))
        if p is None:
            p = PF.Profile(str(code), row, self.xref, PersonView._era)
        return p.yushou

    def _fit_person_cols(self):
        """量一遍合并总表的内容，给出每列该多宽（结果按数据签名缓存）。

        列宽 = max(表头, 抽样行的值) + 内边距，夹在 [44, 240]。

        ⚠️ 抽样而不是全量：全量 8988 行 × 11 列 ≈ 99k 次取值 + 估算，
          实测要几百毫秒；而这几列的取值集合都很小（性别/等级/文化/性格/势力
          是枚举，生卒年是日期，姓名会重复），抽 1500 行就能覆盖到最长值。
          估算用 `kit.est_text_px`（不用 tkfont.measure，那个 9000 次要 0.7 秒）。
        """
        visible = self._visible_cols()
        sig = (len(self.people), visible)
        if getattr(self, "_pcol_sig", None) == sig and getattr(self, "_pcol_w", None):
            return self._pcol_w

        keymap = {zh: k for zh, k in PF.PROFILE_ORDER}
        rows = list(self.people.values())
        step = max(1, len(rows) // 1500)
        sample = rows[::step][:1500]
        pt = self.theme.fs_body
        hpt = self.theme.fs_body_sm
        # ★ 2026-09-25 这两条常数是「空间分配」的总闸（使用者：「注意 UI 和空间分配」）：
        #   · COL_PAD 12 —— 列内左右各 6px 留白。原来 16 偏阔，11 列白让 44px。
        #   · COL_MIN 30 —— 列宽下限。原来 44 是「按最长内容」时代留下的粗值：
        #     单字列（性别/等级/性格 值只 1 字）与三位数（智略/年龄/余寿）本来
        #     只要 34px 上下，六个列合计白占 60px。
        COL_PAD, COL_MIN = 12, 30
        widths = {}
        # ★ 2026-09-25 使用者：「姓名显示 4 个字就够了」「够用就行」——
        #   姓名列**固定按 4 个字**定宽（不再按最长值、也不按分位数）。
        #   本档 8611 人的名字中位只 3 字，而按最长值（9 字）会把这一列撑到
        #   129px，对绝大多数行都是浪费。超出的名字尾巴被裁一点，
        #   点行看右侧详情卡仍是全名。
        # ★ 2026-09-26 使用者改口：「人物界面的人物姓名栏原来是 4 个汉字的
        #   宽度，现在改为 **5 个汉字** 宽度」—— 全谱里四字名（如「涂山狐祖」
        #   「格萨尔洛布扎堆」这类）比单剧本档多得多，4 字会把它们裁掉。
        NAME_CHARS = 5
        for zh in visible:
            need = est_text_px(zh, hpt) + COL_PAD
            k = keymap.get(zh, "")
            if zh == "姓名":
                need = max(need, est_text_px("文" * NAME_CHARS, pt) + COL_PAD)
            elif k:
                for p in sample:
                    try:
                        need = max(need,
                                   est_text_px(str(p.value_of(k) or ""), pt) + COL_PAD)
                    except Exception:
                        continue
            # ★ 2026-09-26 使用者实测：生年/卒年两列「有点不够用」，各再加宽
            #   约 1 个汉字 —— 数字串（如「-2174.12」）在 Treeview 单元格里
            #   另有自身内边距，按最长值 + COL_PAD 定宽仍会差一点点裁尾。
            if zh in ("生年", "卒年"):
                need += est_text_px("文", pt)
            # ★ 向上取整：`int()` 会把 35.76 截成 35，表头「性别」正好差 0.8px 被裁
            #   （实测 6 个两字表头全中招）。宁可多给 1px。
            widths[zh] = math.ceil(max(COL_MIN, min(need, 240)))
        self._pcol_sig, self._pcol_w = sig, widths
        return widths

    def _hidden_cols(self):
        """本谱牒声明要**隐藏的列**（`source.hide_cols`）。

        ★ 2026-09-25 使用者裁定：《全史存档》由 32 个剧本档合并而来，跨 2500 年，
          「年龄/余寿」的参照年（本档走到哪一年）根本不存在 ⇒ 这两列不画。
          按谱名缓存 —— 切谱牒时才重读一次 source。
        """
        name = getattr(self.app, "current_save", "") or ""
        if getattr(self, "_hide_cache_name", None) == name:
            return self._hide_cols
        hidden = ()
        if name:
            try:
                src = storage.load_source(name) or {}
                h = src.get("hide_cols")
                if isinstance(h, (list, tuple)):
                    hidden = tuple(str(x) for x in h)
            except Exception:
                hidden = ()
        self._hide_cache_name, self._hide_cols = name, hidden
        return hidden

    def _visible_cols(self):
        return PF.visible_table_cols(self._hidden_cols())

    def _cell_for(self, colkey, row, code):
        if colkey.startswith("_p:"):
            zh = colkey[3:]
            p = self.people.get(str(code))
            if p is None:
                p = PF.Profile(code, row, self.xref, PersonView._era)
            keymap = {zhname: k for zhname, k in PF.PROFILE_ORDER}
            return p.value_of(keymap.get(zh, ""))
        return None

    def _apply_filter(self):
        if self.slot is None or self.cur_family is None:
            return
        t = self.slot.tables[self.cur_family]
        q = self.search_var.get().strip().lower()
        is_person = (self.cur_family in self.PERSON_VIEW_FAMILIES
                     or self.cur_family in self.PERSON_RAW_TABLES)
        # ★ 2026-09-25：换表族会改变**计数与旁路集合的口径**
        #   （实录层 ↔ 谱牒总谱是两批人）—— 只在"换表"时重算一次，
        #   搜索框每敲一个字都重算 13k 行不值当。
        if is_person and getattr(self, "_ctx_family", None) != self.cur_family:
            self._filter_ctx()
        pairs = []
        for r, s in zip(t.rows, t.srcs):
            if q and not self._hit(r, q):
                continue
            # 勾选筛选只作用于人物表族；翻别的表族（国家 / 城池…）时不掺和
            if is_person and not self._pass_filter(r, str(r.get("Ren_Code") or "")):
                continue
            pairs.append((r, s))
        self.all_pairs = pairs
        self._render_table()
        if is_person:
            self._refresh_filter_counts()
        else:
            self.hit_lbl.configure(text=f"命中 {len(pairs)} 条")

    @staticmethod
    def _hit(row, q):
        for v in row.values():
            if isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False)
            if q in str(v).lower():
                return True
        return False

    def _render_table(self):
        tv = self.table
        tv.delete(*tv.get_children())
        if self.slot is None or self.cur_family is None:
            return
        cols = self._columns()
        self._cols = cols
        hidden_cols = self._hidden_cols()      # 本谱声明隐藏的列（年龄/余寿）
        tv["columns"] = [c[0] for c in cols]
        for key, w, right in cols:
            head = key[3:] if key.startswith("_p:") else C.label_of(key)
            tv.heading(key, text=head, anchor="e" if right else "w",
                       command=lambda k=key: self._sort_by(k))
            # ★ 2026-09-25 列宽一律固定（`stretch=False`）—— 使用者裁定「够用就行」：
            #   姓名列不再随窗口变宽（此前它 stretch 会独吞全部剩余宽度，
            #   窗口越大越宽，看着就像「姓名栏越来越宽」）。
            # ★ 2026-09-26 改回 stretch：固定宽在宽屏下右侧空白一大片
            #   （使用者报「中间空白一大片」）—— 各列均摊剩余宽度，不再留白。
            tv.column(key, width=w, anchor="e" if right else "w", stretch=True)
        self._bind_header_tip(tv, cols)

        person_view = (self.cur_family in self.PERSON_VIEW_FAMILIES
                       or self.cur_family in self.PERSON_RAW_TABLES)
        # ★ 2026-09-23 使用者要求：人物页默认按「智略」从高到低排。
        #   点表头排序照旧 —— `sort_key` 非空时用使用者的选择，空时才是默认。
        sort_key, sort_desc = self.sort_key, self.sort_desc
        # ★ 2026-09-24 存的排序列可能已经不在表里了（比如被删掉的「世代」）——
        #   失效就退回默认，免得整张表因为一个取不到值的键而「看着没排」。
        if sort_key is not None and sort_key not in {k for k, _w, _r in cols}:
            sort_key = None
        if sort_key is None and person_view:
            sort_key, sort_desc = "_p:智略", True
        pairs = list(self.all_pairs)
        if sort_key:
            if sort_key in ("_p:生年", "_p:卒年"):
                # ★ 2026-09-26 时间轴排序（含降序）：空值永远垫底，
                #   降序用「取负的时间键」而不是 reverse（reverse 会把
                #   空值键 (1, …) 翻到最前）。
                def _ckey(pair, _desc=sort_desc):
                    r = pair[0]
                    v = str(self._cell_for(sort_key, r,
                                           str(r.get("Ren_Code") or "")) or "")
                    m = _CHRONO_RE.match(v.strip())
                    if not m:
                        return (1, 0)
                    t = int(m.group(1)) * 12 + int(m.group(2) or 1)
                    return (0, -t if _desc else t)
                pairs.sort(key=_ckey)
            elif sort_desc and sort_key in self.NUM_DESC_COLS:
                # 数值列降序：有数值的从高到低，没数值的（无智略 / 无生年）垫底。
                # 直接 `reverse=True` 会把空值键 (1, 0.0, "") 翻到最前，故单独给键。
                pairs.sort(key=lambda p: self._num_desc_key(p[0], sort_key))
            else:
                pairs.sort(key=lambda p: self._sort_val(p[0], sort_key),
                           reverse=sort_desc)
        shown = pairs[:MAX_ROWS]
        focused_set = self.app.focus_set()
        for i, (r, _src) in enumerate(shown):
            tags = []
            dead = False
            ys = None                   # 余寿档位（★ 2026-09-24）
            if person_view:
                code = str(r.get("Ren_Code") or "")
                vals = [str(self._cell_for(key, r, code) or "") for key, _w, _r in cols]
                # ★ 2026-09-23 实录层标注（与谱牒层表格同款）：
                #   已故灰底 —— `_alive_of` 查不到默认 False（已故，与筛选同口径）
                # ★ 2026-09-26：全谱声明「不涂已故灰」时不挂 dead 底
                #   （见 app.storage.hide_dead_shade，四处同规）
                dead = (bool(code) and not self._alive_of.get(code, False)
                        and not storage.hide_dead_shade(
                            getattr(self.app, "current_save", "")))
                focused = bool(code) and code in focused_set
                if dead:
                    tags.append("dead")
                if focused:
                    tags.append("focus")
                # 余寿底色只在**既非已故、又非选定**时才挂 —— 免得跟灰/紫抢，
                # 也省得依赖 tag 优先级的实现细节。
                # ★ 2026-09-25：本谱若声明隐藏「余寿」（如《全史存档》），
                #   就不该再算它的档位、更不该挂底色。
                if not dead and not focused and "余寿" not in hidden_cols:
                    ys = self._yusou_bucket(self._yusou_of(code, r))
                # ★ 2026-09-23「史实加黑」：非史实整行文字压灰（史实保持正文色）
                if code and not PF.is_historical(code):
                    tags.append("nohist")
            else:
                vals = [self._cell(r.get(key, ""), key) for key, _w, _r in cols]
            # 已故行不再叠斑马纹（与谱牒层表格同款：整行统一灰底）；
            # 有余寿底色的行也不用斑马纹（那层色就是它的区分）
            if ys is not None:
                tags.append(f"ys{ys}")
            elif i % 2 and not dead:
                tags.append("odd")
            tv.insert("", "end", iid=str(i), values=vals, tags=tuple(tags))
        # ★ 2026-09-23 选中行标红：用户要的是「人物界面被选中（点击选中的行）变红」，
        #   不是「仅显所选」名单红 —— 名单红已撤销，选中红在 `_on_row` 里动态加
        self._sel_iid = None
        self.rows = [p[0] for p in shown]
        self.row_srcs = [p[1] for p in shown]
        extra = ""
        if len(pairs) > MAX_ROWS:
            extra = f"　⚠ 仅示前 {MAX_ROWS} 行（共 {len(pairs)} 行），请搜索缩小范围"
        t = self.slot.tables[self.cur_family]
        hint = "" if t.rows else "　（空表）"
        # 状态栏同样把「（未登记）」这类解释摘掉（使用者 2026-09-21 要求）
        fam_plain, _fam_hint = split_hint(C.label_of_family(self.cur_family))
        self.set_status(f"{fam_plain}：共 {len(t.rows)} 条，"
                        f"当前显示 {len(shown)} 条{extra}{hint}")

    def _bind_header_tip(self, tv, cols):
        help_map = {}
        for key, _w, _r in cols:
            txt = PF.FIELD_HELP.get(key[3:] if key.startswith("_p:") else C.label_of(key))
            if txt:
                help_map[key] = txt
        self._head_help = help_map
        if getattr(self, "_head_tip_bound", False):
            return
        self._head_tip_bound = True
        htip = {"w": None}

        def motion(e):
            if e.y > 26:
                tip_off()
                return
            cid = tv.identify_column(e.x)
            idx = int(cid[1:]) - 1 if cid and cid.startswith("#") and cid[1:].isdigit() else None
            key = self._cols[idx][0] if idx is not None and 0 <= idx < len(self._cols) else None
            txt = getattr(self, "_head_help", {}).get(key)
            tip_off()
            if not txt:
                return
            w = tk.Toplevel(tv)
            w.wm_overrideredirect(True)
            w.wm_geometry(f"+{e.x_root + 12}+{e.y_root + 18}")
            frm = tk.Frame(w, bg="#3a3a3a", bd=1, relief=tk.SOLID)
            frm.pack()
            tk.Label(frm, text=txt, bg="#3a3a3a", fg="#f5f5f5", justify=tk.LEFT,
                     wraplength=_dpi.px(340), font=("微软雅黑", 10), padx=8, pady=5).pack()
            htip["w"] = w

        def tip_off():
            cur = htip.get("w")
            if cur is not None:
                cur.destroy()
                htip["w"] = None

        tv.bind("<Motion>", motion, add="+")
        tv.bind("<Leave>", lambda e: tip_off(), add="+")

    @staticmethod
    def _cell(v, field="") -> str:
        if v is None:
            return ""
        if isinstance(v, dict):
            if not v:
                return "（空）"
            if len(v) == 1:
                only = next(iter(v.values()))
                if not isinstance(only, (dict, list)):
                    return str(only)[:70]
            if all(not isinstance(x, (dict, list)) for x in v.values()):
                s = " · ".join(f"{L.field_label(k)}:{x if x != '' else '—'}"
                               for k, x in v.items())
            else:
                s = f"（{len(v)} 项）"
            return s[:70]
        if isinstance(v, list):
            if not v:
                return "（空）"
            if all(not isinstance(x, (dict, list)) for x in v):
                return ("、".join(str(x) for x in v))[:70]
            return f"（{len(v)} 项）"
        return str(PersonView._decode_ctx(field, v).text)[:70]

    @staticmethod
    def _decode_ctx(field, v):
        era = getattr(PersonView, "_era", "秦末")
        if field == "Ren_Zu_Yu":
            zh = L.region_of(v, era)
            if zh:
                return L.Decoded(zh, "已译码")
        return L.decode(field, v)

    _era = "秦末"

    # ★ 2026-09-24 数值型列的降序一律要「空值垫底」（见 `_num_desc_key`）。
    #   智略是第五十批的老账，「年龄」「余寿」是同一类，一并管起来。
    NUM_DESC_COLS = ("_p:智略", "_p:年龄", "_p:余寿")

    def _num_desc_key(self, row, colkey):
        """数值列降序专用键：数值 → (0, -值)；空 / 非数值 → (1, 0)，垫底。

        ★ 由第五十批的「智略降序」键泛化而来。`_sort_val` 对非数值返回
          `(1, 0.0, s)`，直接 `reverse=True` 会把这批空值**翻到最前** ——
          「从高到低」变成「一群没数据的人打头」。新增的「年龄」列（没有生年
          的人显示「—」）一上来就复现了这个坑，所以走这条专用键。
        """
        code = str(row.get("Ren_Code") or "")
        try:
            return (0, -float(self._cell_for(colkey, row, code)))
        except (TypeError, ValueError):
            return (1, 0.0)

    def _sort_val(self, row, key=None):
        key = self.sort_key if key is None else key
        if key and key.startswith("_p:"):
            code = str(row.get("Ren_Code") or "")
            zh = key[3:]
            if zh == "世代":
                p = self.people.get(code)
                if p is not None and p.daishu is not None:
                    return (0, float(p.daishu), "")
            v = self._cell_for(key, row, code)
            # ★ 2026-09-26 使用者报：生卒年排序把「-192.12」当普通数字比 ——
            #   负号把月份方向翻转，公元前同一年里 12 月反而排在 1 月后面。
            #   改按**时间轴键 = 年×12 + 月**：公元前负数连续、无公元 0 年也
            #   无碍（前1年12月=0、公元1年1月=13，顺序正确）。
            if zh in ("生年", "卒年") and isinstance(v, str):
                _m = _CHRONO_RE.match(v.strip())
                if _m:
                    _y = int(_m.group(1))
                    _mm = int(_m.group(2) or 1)
                    return (0, _y * 12 + _mm, "")
            if isinstance(v, str):
                try:
                    return (0, float(v), "")
                except ValueError:
                    return (1, 0.0, v)
            if isinstance(v, (int, float)):
                return (0, float(v), "")
            return (1, 0.0, str(v or ""))
        v = row.get(key)
        if isinstance(v, (dict, list)):
            return json.dumps(v, ensure_ascii=False)
        if isinstance(v, (int, float)):
            return (0, v, "")
        s = str(v or "")
        try:
            return (0, float(s), "")
        except ValueError:
            return (1, 0.0, s)

    def _sort_by(self, key):
        if self.sort_key == key:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_key, self.sort_desc = key, False
        self._render_table()

    def _selected_index(self):
        sel = self.table.selection()
        if not sel:
            return None
        try:
            return int(sel[0])
        except ValueError:
            return None

    def _on_row_double(self, event=None):
        """双击表格行 → 跳到「家谱」页的代际模式，滚到该人的铭牌上。

        ★ 2026-09-24 使用者要求。两处容易踩的坑在这里挡住：
          ① 人物页是**实录层**（几千人），画布画的是**谱牒层** —— 实录里绝大
             多数人没入谱，而 `scroll_to` 对不认识的名字是**静默 return**，
             看着就像双击坏了（与四十九批「点选定没反应」同源）。
          ② 锚点必须是 **code**，不是姓名 —— 谱牒人名可能与实录不同
             （重名加中文序数、使用者还会手改）。
        ⚠️ 调 `goto_main_tree` 会触发 `_build_main_view` **销毁本视图**，
           所以先把要用的东西全取出来；调用之后不要再碰 self。
        """
        if event is not None:
            iid = self.table.identify_row(event.y)
            if iid:
                self.table.selection_set(iid)
        idx = self._selected_index()
        if idx is None or idx < 0 or idx >= len(self.rows):
            return
        row = self.rows[idx]
        code = str(row.get("Ren_Code") or "")
        name = str(row.get("Ren_Name") or row.get("King_Name")
                   or row.get("Map_Name") or row.get("Name") or "").strip()
        app = self.app
        if not code:
            self.set_status("这一行没有编号，无法定位到家谱", warn=True)
            return
        if code not in getattr(self, "_book_codes", set()):
            messagebox.showwarning(
                "他还没入谱",
                f"「{name}」只在实录层（游戏存档）里有，\n"
                "而家谱画布画的是谱牒层里的人。\n\n"
                "请先在人物页点「⇱ 入谱」，或点「加入族谱」把他加进来，\n"
                "之后双击就能跳到他的铭牌。",
                parent=self.app.root)
            self.set_status(f"「{name}」还没入谱 —— 先点「⇱ 入谱」", warn=True)
            return
        book_name = app.book_name_of_code(code)
        if not book_name:
            self.set_status(f"「{name}」在谱牒里找不到对应记录，无法定位", warn=True)
            return
        app.goto_main_tree(book_name, from_person=True)

    # ---------------------------------------------------------------- 详情
    def _on_row(self):
        # ★ 2026-09-23 选中行标红：上次选中行先摘掉 focus tag，再给当前选中行加上。
        #   Treeview 的 selection 高亮（bg_sel）是背景色，用户要名字也红才醒目。
        tv = self.table
        try:
            if getattr(self, "_sel_iid", None) is not None:
                tags = list(tv.item(self._sel_iid, "tags"))
                if "focus" in tags:
                    tags.remove("focus")
                    tv.item(self._sel_iid, tags=tuple(tags))
        except tk.TclError:
            pass
        sel = self.table.selection()
        if sel:
            try:
                iid = sel[0]
                tags = list(tv.item(iid, "tags"))
                if "focus" not in tags:
                    tags.append("focus")
                tv.item(iid, tags=tuple(tags))
                self._sel_iid = iid
            except tk.TclError:
                self._sel_iid = None
        else:
            self._sel_iid = None
        # ★ 2026-09-28 使用者实测报：「跳转**闪了一下就空白了**」——
        #   `_selection_set` 之后，若焦点不在表格（我们是从卡片里点人名跳过来的），
        #   Tk 的 `exportselection` 会把选中"交给剪贴板"并随之清空 ⇒ 又一次
        #   `<<TreeviewSelect>>` 触发，这里拿到 `None` ⇒ `_show_detail(None)`
        #   把刚渲染好的卡片**清空**（= 闪一下变空白）。
        #   两道保险：① 表格已设 `exportselection=False`（选中不随焦点丢）；
        #   ② 这里**拿到 None 就不动卡片**（没有选中 ≠ 该清空 —— 清空是"查无此人"的语义）。
        _i = self._selected_index()
        if _i is not None:
            self._show_detail(_i)

    def _on_row_right(self, event):
        """右键表格行：弹菜单 —— 主项是「选定（仅显所选）」（匹配谱牒人名）。"""
        iid = self.table.identify_row(event.y)
        if not iid:
            return
        try:
            idx = int(iid)
        except ValueError:
            return
        if idx < 0 or idx >= len(self.rows):
            return
        row = self.rows[idx]
        name = str(row.get("Ren_Name") or row.get("King_Name")
                   or row.get("Map_Name") or row.get("Name") or "").strip()
        if not name:
            return
        t = self.theme
        menu = tk.Menu(self, tearoff=0,
                       font=(t.font_ui_fallback, t.fs_body),
                       bg=t.bg_card, fg=t.text,
                       activebackground=t.accent_soft, activeforeground=t.accent)
        if name in getattr(self.app, "people", {}):
            if name in getattr(self.app, "focused", []):
                menu.add_command(label="✓ 已选定（再点取消）",
                                 command=lambda: self.app.toggle_focus(name))
            else:
                menu.add_command(label="选定（仅显所选）",
                                 command=lambda: self.app.toggle_focus(name))
        else:
            menu.add_command(label=f"「{name}」不在当前谱牒里", state="disabled")
        menu.add_separator()
        menu.add_command(label="查看详情", command=lambda: self._show_detail(idx))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _show_detail(self, idx):
        for w in self.detail_inner.winfo_children():
            w.destroy()
        self._in_lineage = False
        if idx is None or idx >= len(self.rows):
            self.detail_src.configure(text="")
            self._paint_act_bar()
            return
        t = self.theme
        row = self.rows[idx]
        src = self.row_srcs[idx] if idx < len(self.row_srcs) else S.Src("")
        name = row.get("Ren_Name") or row.get("King_Name") or row.get("Map_Name") \
            or row.get("Name") or row.get("Jia_Shi") or ""
        # ★ 2026-09-28 使用者：「合并视图 整文件删了」——
        #   派生总表（`record_derive.MERGE_NAME`）**没有真实文件**：它的
        #   `Src("（合并视图）")` 只是占位（`path=()` ⇒ `label()` 会补出
        #   「（整文件）」），显示成「来源：（合并视图）（整文件）」纯属噪音。
        #   ⇒ **凡文件名被「（）」包起来的（派生态 / 空占位）一律不显示来源**。
        _src_txt = src.label() if src is not None else ""
        if _src_txt.startswith("（"):
            _src_txt = ""
        self.detail_src.configure(text=f"来源：{_src_txt}" if _src_txt else "")
        self.detail_title.configure(text=str(name) if name else f"第 {idx} 条", fg=t.text)
        self._clear_badge()               # 非人物行：清掉上一个人的「史实/谱」徽标

        tier = ""
        jwt = row.get("King_Jue_Wei_Code")
        if isinstance(jwt, int):
            tier = L.code_of("King_Jue_Wei_Code", jwt) or ""
        if tier:
            tk.Frame(self.detail_inner, bg=t.tier.get(tier, t.text_2), height=3
                     ).pack(fill=tk.X, padx=6, pady=(2, 6))

        code = row.get("Ren_Code")
        is_person = code not in (None, "") and (
            self.cur_family in self.PERSON_VIEW_FAMILIES
            or self.cur_family in self.PERSON_RAW_TABLES
            or ("Ren_Zhi_Lue" in row or "Ren_Leve" in row))
        if is_person:
            self._person_detail(str(code), row)
            return

        if code not in (None, "") and self.rel is not None:
            self._rel_button(code)
        for key, val in row.items():
            if key in ("_来源",) or key in MUTE_FIELDS:
                continue
            self._field_line(key, val)
        self.detail_inner.update_idletasks()
        self.dv.yview_moveto(0)
        self._paint_act_bar()

    def _person_detail(self, code, row):
        p = self.people.get(code) or PF.Profile(code, row, self.xref, PersonView._era)
        t = self.theme
        # 女性人名标红（使用者要求「女性角色名字在任何地方都标红」）
        if p.sex_label == "女":
            self.detail_title.configure(fg=t.spouse)

        # ★ 徽标画进**标题行**（姓名右侧），不再在 detail_inner 里独占一行
        badge = self.badge_holder
        for _w in badge.winfo_children():
            _w.destroy()
        hist = p.historical
        bl = tk.Label(badge, text="● 史实人物" if hist else "○ 非史实人物", bg=t.bg_panel,
                      fg=t.accent if hist else t.text_3,
                      font=self.font(t.font_ui_fallback, t.fs_body_sm, hist))
        bl.pack(side=tk.LEFT)
        Tooltip(bl, "史实人物：编号 ≤5 位，是游戏写死的历史人物。\n"
                    "非史实人物：编号 9 位，由游戏随机生成。")
        # 谱牒内标记（两层共有的人）
        if self._in_book(code):
            tk.Label(badge, text=" 谱 ", bg=t.edit_soft, fg=t.edit_2, padx=5,
                     font=(t.font_ui_fallback, t.fs_body_sm, "bold")).pack(side=tk.LEFT, padx=(8, 0))

        # ★ 2026-09-26 使用者问「入谱按钮也没有了」：实录层详情卡此前没有
        #   「⇱ 入谱」—— 而这正是桥的核心动作（实录 → 谱牒，立即写档）。
        #   现在补上并放第一位（primary）。
        # ★ 2026-09-28 使用者裁定：「入谱」与「加入族谱」字面都朝"谱"、看不出区别
        #   —— 两者真实差别是**时机**，于是改成同尾不同前缀、字面对立；
        #   并且（同一天第二条）「三个按钮的汉字要在其单元格正中心，看着有点歪」
        #   ⇒ 改走**三格等宽网格**（uniform 列），`tk.Button` 自带居中即压格心；
        #   图标一律去掉（它白占一个字宽、破「字数一致」），三个按钮清一色 4 字：
        #   立即入谱 / 预约入谱 / 选定人物。
        # ⚠️⚠️ 2026-09-28 第二次返工 —— 上一版改「每行三个 pack(expand+fill=X)」
        #   也不行：`expand` 是**按需求比例**分剩余宽（不是等分）！实测萧何那张卡
        #     · 按钮行（需求相近）→ [442, 443, 443] ✓ 等宽，看着挺好；
        #     · 政策行（chips 多）→ [384, 252, 692] ✗ 中格被挤瘪、右格撑开、
        #       chips 溢出到邻格 —— 正是使用者截图看到的乱象。
        #   正解不是 pack 也不是"每行一个 grid"，而是**三行共用同一个 grid**：
        #   按钮 row0 / 政策 row1 / 后裔 row2，且
        #     · `columnconfigure(weight=1, uniform="actcol")` —— uniform 只在
        #       **同一容器**内生效，拆成两个 Frame 就各算各的（那是最初错位的原因）；
        #     · `sticky="ew"` —— 让格子吃满列宽，而不是按内容撑。
        #   再配「每格最多 2 个 chip、多的收成 ＋N」把需求压住（信息密度也顺带均衡）。
        # ══════════ 统一网格：整张卡 = 一张 6 列的表（Excel 思维）══════════
        # ★ 2026-09-28 使用者定稿：「你就把整个脚本的人物面板设想成一个 excel
        #   表格，然后该合并就合并、该左对齐就左对齐，这样左右上下所有元素都在
        #   单元格里，一点也不乱，单元格的大小标准定死！」
        #   ⇒ **6 列等宽**（列宽 = 卡片宽 ÷ 6，由表定死，**不由内容决定**）：
        #      · 按钮各跨 2 列 ⇒ 三格天然等宽（0-1 / 2-3 / 4-5）；
        #      · 政策 / 能力 / 特质 整行跨 6 列 ⇒ 条目再多也撑不破；
        #      · 两栏：左 0-2 / 右 3-5 ⇒ 天然 50/50，且**共用同一套行号**（左右并排）；
        #      · 标签列（0 / 3）定宽 4 字 ⇒ 上下所有标签左沿一条线。
        #   所有元素都 grid 到**这一张表**里，不再有"各自的 Frame 各自算宽"。
        gh = tk.Frame(self.detail_inner, bg=t.bg_panel)
        gh.pack(fill=tk.BOTH, expand=True)
        GC = 6
        for _c in range(GC):
            gh.columnconfigure(_c, weight=1, uniform="cell")
        W_CELL = max(1, _dpi.px(560) // GC)     # 单列宽（写死）
        W_VAL = W_CELL * 2 - _dpi.px(6)         # 值列（跨 2 列）可用宽
        R = 0                                    # 行游标
        b_push = self._mini_act(
            gh, "立即入谱",
            lambda c=code, n=str(getattr(p, "name", "") or ""):
                self.app.push_to_book(c, n), primary=True,
            col=0, row=R, span=2)
        Tooltip(b_push, "把这位连同其全部男性后裔**立刻**写进当前谱牒档，\n"
                        "写完家谱页 / 画布马上就能看到（不弹确认框）。")
        followed = code in self.followed
        b_fol = self._mini_act(gh, "已预约" if followed else "预约入谱",
                               lambda c=code: self.toggle_follow(c),
                               col=2, row=R, span=2)
        Tooltip(b_fol, "**不马上写谱**：先把他这一支记进「续谱名单」，\n"
                       "等下次点「续谱」时才连同父系后裔一起抽进谱。")
        # ★ 2026-09-26 使用者问「选定按钮在哪里」：实录层详情卡此前**没有**
        #   「选定」按钮（那行按钮只长在谱牒总谱卡上）—— 现在补上。
        _nm = str(getattr(p, "name", "") or "")
        _on = _nm in set(self.app.focused)
        b_foc = self._mini_act(gh, "已选定" if _on else "选定人物",
                               lambda: self._toggle_focus_card(_nm, b_foc),
                               primary=_on, col=4, row=R, span=2)
        Tooltip(b_foc, "加进「仅显所选」名单（可多选）：人物页按名单过滤，\n"
                       "画布上的谱系同步高亮（实录层人物需入谱后才上画布）。")
        # ★ 标题行里的「定位到表格」要跟它**左沿重合、等宽** —— 把它记下来给
        #   `_sync_title_row()` 量宽度（它的宽度受 6 列网格影响，只能实测）。
        self._last_act_btn = b_foc
        # ★ 2026-09-28 删除「◈ 关系」按钮 —— 关系已并进右栏，不必再切页去看。
        R += 1
        # ⚠️ 2026-09-28 撤回：上一轮把「定位到表格」搬到卡片网格里占了一整行 ——
        #   使用者：「你不是放上面好好的吗，也不占空间，你怎么又把定位到表格放到
        #   下面去了？我不是说只是对齐吗？」⇒ 已放回**标题行右侧**，
        #   对齐改由 `title_slot`（与卡片两格等宽的槽）+ `_sync_title_row()`
        #   的实测同步完成。
        # ★ 缺图标是刻意的：`⌖` 会让汉字左沿比「选定人物」右移一个字宽。
        # 政策 / 能力 / 特质：**各占一行、整行跨 6 列**（Excel 里的"左右合并"
        # 单元格）—— 这三行内容变长，只有整行才撑不破（使用者三次裁定）。
        for _i, (zh, infos) in enumerate((("政策", p.zhengce_info),
                                          ("能力", p.nengli_info),
                                          ("特质", p.buff_info))):
            self._info_cell(gh, zh, infos, R + _i)
        R += 3
        # ★ 2026-09-28 使用者要求删除「后裔 N」按钮：「这个信息已经体现在卡片里了」
        #   —— 右栏的「子女 / 后代下推」段就是这份信息，按钮纯属重复。
        #   （`_show_lineage` 保留：右键菜单等处仍在用。）

        # ──── 两栏：左 0-2「基本档案」/ 右 3-5「亲属关系 + 上溯」────
        # 两栏**共用同一套行号**（左栏占列 0-2、右栏占列 3-5）⇒ 同一行左右并排，
        # 行高自然对齐；列宽各 3 格是表的硬约束 ⇒ 天然 50/50，内容撑不动它。
        rL = rR = R          # 两栏各自的行游标（都从当前行起步）

        def _cap(host, text, col, row):
            """段落小标题（一律 4 字）—— 与字段标签同一条左沿（标签都定宽 4 字）。"""
            tk.Label(host, text=text, bg=t.bg_panel, fg=t.text_3, anchor="w",
                     font=self.font(t.font_ui_fallback, t.fs_body_sm)
                     ).grid(row=row, column=col, columnspan=3, sticky="w",
                            padx=(6, 0), pady=(6, 2))

        # —— 左栏：基本档案 ——
        _cap(gh, "基本档案", 0, rL)
        rL += 1
        # ★ 2026-09-25：详情卡也跟着本谱的 `hide_cols` 走 ——
        #   《全史存档》声明隐藏「年龄/余寿」，详情卡就不该再列这两行。
        hidden_cols = self._hidden_cols()
        for zh, val in p.rows():
            if zh in hidden_cols or zh in ("所在", "编号"):
                continue
            self._field_line_zh(zh, val, parent=gh, row=rL, col=0, wrap=W_VAL)
            rL += 1
        # ⚠️ 政策 / 能力 / 特质**不在这里** —— 已挪到上方、整行跨 6 列（见 `_info_cell`）。

        # —— 右栏：亲属关系 → 父系上溯 ——
        _cap(gh, "亲属关系", 3, rR)
        rR += 1
        prof = self.rel.profile(code) if self.rel is not None else {}
        # 「兄弟姐妹」是 4 字，破对称 ⇒ 按性别**拆成「兄弟」「姐妹」**两行（各 2 字）。
        sibs = prof.get("兄弟姐妹") or []
        bros = [r for r in sibs if getattr(r.person, "sex_label", "") == "男"]
        sis = [r for r in sibs if getattr(r.person, "sex_label", "") != "男"]
        for kind, title in (("父", "父系"), ("母", "母系"),
                            ("配偶", "配偶"), ("子女", "子女")):
            # ★ 2026-09-28 使用者：「不要解释说明，配偶无就写无」
            #   —— 原来的长句提示（"存档里未记载配偶（此档绝大多数人都没有）。"）
            #   一律去掉，空段就一个字：无。
            rR = self._rel_section(title, prof.get(kind) or [], parent=gh, row=rR,
                                   col=3, wrap=W_VAL, empty_hint="无")
        rR = self._rel_section("兄弟", bros, parent=gh, row=rR, col=3, wrap=W_VAL)
        rR = self._rel_section("姐妹", sis, parent=gh, row=rR, col=3, wrap=W_VAL)
        if self.rel is not None:
            anc = self.rel.ancestors(code, depth=5)
            if anc:
                rR = self._rel_chain("父系上溯", [(pp, f"−{d} 世") for d, pp in anc],
                                     parent=gh, row=rR, col=3, wrap=W_VAL)
            des = self.rel.descendants(code, depth=2)
            if des:
                rR = self._rel_chain("后代下推",
                                     [(pp, f"+{d} 世") for d, pp in des[:40]],
                                     more=len(des) - 40 if len(des) > 40 else 0,
                                     parent=gh, row=rR, col=3, wrap=W_VAL)
        # ★ 2026-09-28 使用者：「删除所在编号这个信息吧，没什么用」—— 整段去掉
        #   （左栏也不再补回来，两处都不显示了）。

        self.detail_inner.update_idletasks()
        self._sync_title_row()
        # ⚠️ 必须再排一次 idle：`_sync_title_row` 要量「选定人物」的**实际宽度**，
        #   而此刻 grid 还没把列宽分配完（量到的是 1）⇒ 只能退回"卡片宽÷3"的
        #   估算值（实测那种情况下是 271，真值是 342）。idle 后再量一次就准了。
        self.dv.after_idle(self._sync_title_row)
        self.dv.yview_moveto(0)
        self._paint_act_bar()

    def _clear_badge(self):
        """清空标题行右侧的徽标（非人物行 / 世系视图也要清，否则残留上一个人的）。"""
        holder = getattr(self, "badge_holder", None)
        if holder is None:
            return
        for w in holder.winfo_children():
            w.destroy()

    def _in_book(self, code):
        """这个人是否已在当前谱牒档里（按 code 锚点比）。"""
        code = str(code or "")
        if not code:
            return False
        for rec in (self.app.people or {}).values():
            if str(rec.get("code", "") or "") == code:
                return True
        return False

    def _mini_act(self, parent, text, cmd, primary=False, col=None,
                  row=0, span=1):
        """详情卡上的一排小按钮 —— 直接走设计系统的 **`kit.FlatButton`**。

        ★ 2026-09-28 全项目整理（第 5 批）：原来这里是手搓 `tk.Button` + 手动
          设 bg/fg 与 active-background（又一套配色口径，与 kit 的 hover /
          高度基线都不一致）。
          `FlatButton` 才是项目自己的按钮组件（含 hover、`kind` 语义、
          `label_pad` 统一高度），这里只留一层**布局壳**：
            · `col=None` ⇒ `pack`（就地一行）；
            · 给了 `col` ⇒ 落进详情卡的 6 列网格。
          并且必须 `grid` + `sticky="ew"`：`pack(expand)` 是**按需求比例**分宽，
          内容一多就把邻格挤扁（实测过 [384, 252, 692]）。
          `primary` 映射 `kind="primary"`（主色实底），否则 `default`。
        """
        b = FlatButton(parent, self.theme, text=text, command=cmd,
                       kind="primary" if primary else "default",
                       padx=8, h=self.theme.ctrl_h)
        # ★ 2026-09-28 使用者：「汉字左沿平行」—— 卡内按钮一律**文字左对齐**
        #   （`FlatButton` 是 `tk.Label` 的壳，`anchor` 直接生效）。
        #   一串上下相邻的按钮从此共一条**汉字左沿**，而不是各自居中、各偏各的。
        b.configure(anchor="w")
        if col is None:
            b.pack(side=tk.LEFT, padx=(0, 6))
        else:
            b.grid(row=row, column=col, columnspan=span, sticky="ew",
                   padx=(0, 6))
        return b

    def _info_cell(self, parent, zh_label, infos, row_idx):
        """「政策 / 能力 / 特质」**各占一行、整行左右合并**（Excel 式单元格）。

        ★ 2026-09-28 使用者裁定（第三次，也是最对的一次）：
          「你非得一行写完，政策一多你就扩展右侧空间？你不会写三行吗？
           按照 excel，上面一个左右合并的单元格写」——
          横排三格从根上就是错的：**内容永远会撑破固定宽度**（实测 [384,252,692]）。
          改成三行、每行 `columnspan=3`（整行归它）⇒ 条目再多也排得开，
          按钮行则保持等宽三格（那是**定长**文字，不变量）。
        标签定宽 4 字 ⇒ 三行的值列起点对齐。
        内容渲染与 `_field_line_info` 同规（名字后带类型徽标、悬停出说明；
        没实测过的条目只提示"暂未录入"，绝不猜）。
        """
        t = self.theme
        cell = tk.Frame(parent, bg=t.bg_panel)
        # 整行合并：`column=0` + `columnspan=6` ⇒ 整行 6 格宽度全归它
        cell.grid(row=row_idx, column=0, columnspan=6, sticky="ew",
                  padx=(6, 6), pady=(3, 0))
        tk.Label(cell, text=zh_label, bg=t.bg_panel, fg=t.text_3, anchor="w",
                 width=4, font=self.font(t.font_ui_fallback, t.fs_body_sm)
                 ).pack(side=tk.LEFT)
        if not infos:
            tk.Label(cell, text="—", bg=t.bg_panel, fg=t.text,
                     font=self.font(t.font_note, t.fs_body_sm)).pack(side=tk.LEFT)
            return
        holder = tk.Frame(cell, bg=t.bg_panel)
        holder.pack(side=tk.LEFT)
        # 整行宽度归它 ⇒ 一行放得下 6 个 chip；再多的收成「＋N」（悬停列出全部）
        for name, info in infos[:6]:
            # ★ 2026-09-28 全项目整理（第 6 批）：徽标改走 **`kit.chip`** ——
            #   原来这里手拼 `tk.Label` + highlight 边框（同一套样式还在
            #   `table_view` 的史实/女性徽标、`popcard` 的爵位小标里各写一遍）。
            #   顺带消掉一个隐患：原代码在循环里用局部变量名 `tip`，
            #   **遮蔽**了模块级从 kit 引入的 `tip()`。
            if not info:
                _ch = kit_chip(holder, t, name,
                               tip_text=f"{zh_label} · 编号条目"
                                        "（游戏内悬停说明暂未录入）")
            else:
                _kind, _desc = info
                _tip_txt = f"【{_kind}】{name}" if _kind else name
                if _desc:
                    _tip_txt += f"\n{_desc}"
                _ch = kit_chip(holder, t, name,
                               fg=t.accent if _desc else t.text_2,
                               tip_text=_tip_txt)
            _ch.pack(side=tk.LEFT, padx=(0, 4), pady=1)
        if len(infos) > 6:
            # 收入「＋N」：字数恒定，宽度需求可控；悬停看全部（信息一条不丢）
            _n = len(infos) - 6
            m = tk.Label(holder, text=f"＋{_n}", bg=t.bg_panel, fg=t.text_3,
                         cursor="hand2", padx=2, pady=1,
                         font=self.font(t.font_ui_fallback, t.fs_body_sm))
            m.pack(side=tk.LEFT, padx=(0, 4), pady=1)
            Tooltip(m, f"{zh_label} · 另有 {_n} 项：\n"
                       + "、".join(_nm for _nm, _ in infos[6:]))

    # ★ 2026-09-28 全项目整理（第 1 批）：删除 `_field_line_info` ——
    #   它已被 `_info_cell`（政策/能力/特质三行整行版）完全取代，
    #   全仓（含 tools / main）无任何调用，只在本文件的 docstring 里被提到过。

    def _field_line_zh(self, zh_label, val, note="", parent=None, row=None,
                       col=0, wrap=None):
        t = self.theme
        # ★ 2026-09-28 详情卡改**两栏**（左「基本档案」/ 右「亲属关系 + 上溯 +
        #   所在编号」）——这行要能画在整卡上（旧调用），也要能画进某一栏里。
        host = parent if parent is not None else self.detail_inner
        line = tk.Frame(host, bg=t.bg_panel) if row is None else host
        if row is None:
            line.pack(fill=tk.X, padx=6, pady=1)
        # ★ 2026-09-28（网格化）：标签占**列 col**（定宽 4 字）、值占**列 col+1..col+2**
        #   —— 列宽由**表**定死（`uniform="cell"`），标签左沿与段落标题同一条线，
        #   值列起点在两栏里都一致（这是"Excel 思维"的直接收益）。
        lb = tk.Label(line, text=zh_label, bg=t.bg_panel, fg=t.text_3, anchor="w",
                      width=4, font=self.font(t.font_ui_fallback, t.fs_body_sm))
        # ★ 2026-09-28 使用者：「人物卡单元格里面的字号统一…数字用 arrial 字体」
        #   —— 字号一律 `fs_body_sm`（与全卡同号）；**纯数字/序号的值走 Arial**
        #   （数字笔画清瘦、位数对齐好看），含中文的值仍用中文字体。
        # ★ 2026-09-28 全项目整理（第 3 批尾巴，截图目检抓到）：**空值也要有字**。
        #   原来直接 `str(val)`，空值就是一片空白 —— 使用者目检时看到「身份」
        #   「势力」后面空着，像"没加载出来"。统一写「无」，与亲属段的
        #   「配偶 无 / 姐妹 无」同口径（铁律：不写解释，空就是「无」）。
        _vs = str(val).strip() or "无"
        _num = _vs != "无" and all(ch in "0123456789./,:+-−×° " for ch in _vs)
        # ⚠️ 这里**不能**用 `width=`：Tk 的 Label `width` 是**固定字符宽 + 超出裁掉**，
        #   与 `wraplength`（折行）同时给时 **width 优先**，长值（"彭绥英 · 男/等级 上/史"）
        #   会被裁成"男/等纟"（实测）。所以只给 wraplength，宽度交给列。
        vl = tk.Label(line, text=_vs, bg=t.bg_panel, fg=t.text, anchor="w",
                      justify=tk.LEFT,
                      wraplength=wrap or _dpi.px(200),
                      font=self.font("Arial" if _num else t.font_note,
                                     t.fs_body_sm))
        if row is None:
            lb.pack(side=tk.LEFT, anchor="nw")
            vl.pack(side=tk.LEFT, padx=(2, 0))
        else:
            lb.grid(row=row, column=col, sticky="nw", padx=(6, 0), pady=1)
            vl.grid(row=row, column=col + 1, columnspan=2, sticky="w",
                    padx=(2, 0), pady=1)
        help_txt = PF.FIELD_HELP.get(zh_label)
        if help_txt:
            try:
                lb.configure(cursor="hand2")
            except tk.TclError:
                pass
            Tooltip(lb, help_txt)
        if note:
            nb = tk.Label(line, text=note, bg=t.bg_panel, fg=t.text_3, anchor="w",
                          font=self.font(t.font_ui_fallback, max(9, t.fs_body_sm - 1)))
            if row is None:
                nb.pack(side=tk.LEFT, padx=(6, 0))
            else:
                nb.grid(row=row, column=col + 3, sticky="w", padx=(6, 0))

    def _toggle_focus_card(self, nm, btn):
        """详情卡上的「选定人物」：切换名单并原位刷新按钮状态。

        ★ 2026-09-28 全项目整理（第 5 批）：按钮改走 `kit.FlatButton` 之后，
          状态刷新也走**它自己的 API**（`set_text` / `set_active`）——
          再手改 `bg/fg` 会绕过 FlatButton 的常态/hover 配色（hover 后
          颜色会「跳回去」）。
        """
        if not nm:
            return
        self.app.toggle_focus(nm)
        on = nm in set(self.app.focused)
        if hasattr(btn, "set_text"):
            btn.set_text("已选定" if on else "选定人物")
            btn.set_active(on)
        else:                                   # 兜底：万一传进来的是别的控件
            t = self.theme
            btn.configure(text="已选定" if on else "选定人物",
                          bg=t.accent if on else t.bg_card,
                          fg=t.accent_on if on else t.text_2)

    # ★ 2026-09-28 全项目整理（第 1 批）：删除「世系视图」（`_show_lineage` +
    #   `_lineage_row`）—— 它**唯一的入口**是详情卡上那颗「后裔 N」按钮，而那颗
    #   按钮已按要求删除（这份信息由右栏「子女 / 后代下推」承担），此后全仓
    #   （含 main / tools / 右键菜单）**零调用**。
    #   日后想恢复这个视图，从右键菜单接一个入口即可（`profiles.Lineage` 保留）。

    def _field_line(self, key, val):
        # ★ 2026-09-28 全项目整理（第 3 批，铁律①「尽量汉字左对齐」）：
        #   本方法（**非人物**分支）原来标签**右对齐**（`anchor="e"` +
        #   `columnconfigure(0, minsize=104)`），而**人物**分支走 `_field_line_zh`
        #   （标签左对齐 + 定宽 4 字）—— 同一个「全字段详情」面板里两套对齐线，
        #   切换行时整个面板的标签会左右横跳。现在统一：**标签定宽 4 字 + 左对齐**，
        #   与 `_field_line_zh` 完全同规。
        t = self.theme
        line = tk.Frame(self.detail_inner, bg=t.bg_panel)
        line.pack(fill=tk.X, padx=6, pady=1)
        line.columnconfigure(0, weight=0)
        line.columnconfigure(1, weight=1)
        derived = str(key).startswith("_")
        tk.Label(line, text=C.label_of(key), bg=t.bg_panel, width=4,
                 fg=t.accent if derived else t.text_3, anchor="w",
                 font=self.font(t.font_ui_fallback, t.fs_body_sm)
                 ).grid(row=0, column=0, sticky="nw")
        tk.Label(line, text=self._fmt_val(key, val), bg=t.bg_panel,
                 fg=t.text if not derived else t.accent, anchor="w", justify=tk.LEFT,
                 wraplength=_dpi.px(300), font=self.font(t.font_note, t.fs_body_sm)
                 ).grid(row=0, column=1, sticky="w", padx=(2, 0))

    def _rel_button(self, code):
        t = self.theme
        line = tk.Frame(self.detail_inner, bg=t.bg_panel)
        line.pack(fill=tk.X, padx=6, pady=(2, 6))
        b = tk.Button(line, text="◈ 查看此人关系",
                      command=lambda c=str(code): self.show_relations(c),
                      relief=tk.FLAT, bd=0, cursor="hand2",
                      font=self.font(t.font_ui_fallback, t.fs_body_sm))
        b.configure(padx=10, pady=3, bg=t.accent, fg=t.accent_on, activebackground=t.accent)
        b.pack(anchor="w")
        Tooltip(b, "父母 · 配偶 · 子女 · 兄弟姐妹 —— 点里面的人名可以一路跳过去。")

    def _fmt_val(self, key, v):
        if isinstance(v, dict):
            if not v:
                return "（空）"
            return "\n".join(f"{L.field_label(k)}：{self._fmt_val(k, x)}" for k, x in v.items())
        if isinstance(v, list):
            if not v:
                return "（空）"
            if all(not isinstance(x, (dict, list)) for x in v):
                shown = "、".join(str(x) for x in v[:24])
                s = shown + (f"　…共 {len(v)} 项" if len(v) > 24 else "")
                if self.xref is not None:
                    named = self.xref.resolve_many(key, v)
                    if named:
                        s += "\n→ " + "、".join(f"{n}" for _c, n in named)
                return s
            out = []
            for x in v[:10]:
                if isinstance(x, dict):
                    inner = "；".join(f"{L.field_label(k)}={self._fmt_val(k, y)}"
                                      for k, y in x.items())
                    out.append("· " + inner)
                else:
                    out.append("· " + str(x))
            return "\n".join(out) + (f"\n…共 {len(v)} 项" if len(v) > 10 else "")
        if v is None:
            return "—"
        if v == "":
            return "（空）"
        text = self._decode_ctx(key, v).text
        if self.xref is not None and key not in XR.SELF_FIELDS:
            hit = self.xref.resolve(key, v)
            if hit:
                text += f"　→ {hit[1]}"
        return text

    # ---------------------------------------------------------------- 关系视图
    def show_relations(self, code):
        if self.rel is None:
            return
        self.mode.set("关系")
        p = self.rel.get(code)
        if p is None:
            if not self._hist or self._hist[-1] != str(code):
                self._hist.append(str(code))
            self._show_missing_person(code)
            self._paint_act_bar()
            return
        if not self._hist or self._hist[-1] != str(code):
            self._hist.append(str(code))

        t = self.theme
        for w in self.detail_inner.winfo_children():
            w.destroy()
        self._in_lineage = False
        self.detail_title.configure(text=f"关系 · {p.name}")
        _lv = L.leve_label(p.level) if p.level is not None else "—"
        _hd = "史实" if PF.is_historical(p.code) else "非史实"
        self.detail_src.configure(
            text=f"编号 {p.code}　{p.sex_label}　{'在世' if p.alive else '已故'}"
                 f"　等级 {_lv}　{_hd}　{p.culture or '—'}")

        prof = self.rel.profile(p.code)
        for kind, title in (("父", "父系"), ("母", "母系"), ("配偶", "配偶"),
                            ("子女", "子女"), ("兄弟姐妹", "兄弟姐妹")):
            self._rel_section(title, prof.get(kind) or [], empty_hint={
                "母": "存档里未记载生母。游戏对「生母不入谱」会写占位「媵妾」。",
                "配偶": "存档里未记载配偶（此档绝大多数人都没有）。",
            }.get(kind, "无"))

        anc = self.rel.ancestors(p.code, depth=5)
        if anc:
            self._rel_chain("父系上溯", [(pp, f"{d} 世") for d, pp in anc])
        des = self.rel.descendants(p.code, depth=2)
        if des:
            self._rel_chain("后代下推", [(pp, f"+{d} 世") for d, pp in des[:40]],
                            more=len(des) - 40 if len(des) > 40 else 0)

        tk.Label(self.detail_inner,
                 text="点任意人名即可跳转过去，一路可以追到祖宗或后代。\n"
                      "要回上一页，点最上方的「← 返回上一页」。",
                 bg=t.bg_panel, fg=t.text_3, justify=tk.LEFT, anchor="w",
                 font=self.font(t.font_ui_fallback, t.fs_body_sm), wraplength=_dpi.px(390)
                 ).pack(fill=tk.X, padx=8, pady=(10, 6))
        self.detail_inner.update_idletasks()
        self.dv.yview_moveto(0)
        self._paint_act_bar()
        self.set_status(f"关系视图　·　{p.name}（编号 {p.code}）")

    def _rel_back(self):
        if getattr(self, "_in_lineage", False):
            self._show_detail(self._selected_index())
            return
        if self.mode.get() == "关系" and len(self._hist) > 1:
            self._hist.pop()
            code = self._hist[-1]
            self._hist.pop()
            self.show_relations(code)
        else:
            self._hist = []
            self.mode.set("表格")
            self._show_detail(self._selected_index())

    def _locate(self, code):
        """定位到该人的表格行（切表 + 选中 + 展开详情卡）。返回是否成功。"""
        if self.goto_family("人物 · 合并总表", select_code=code):
            self.mode.set("表格")
            return True
        self.set_status("找不到人物合并总表", warn=True)
        return False

    def _center_table_row(self, iid):
        """把表格某一行滚到**视口正中**。

        ★ 2026-09-29 使用者：「在人物框里点他父母儿女的超链接，人物卡会到新页面，
          但**人物表格没动** —— 能否一并定位到新任务、放中间居中？」
          真因：`Treeview.see()` 只保证"这一行可见"，**行本来就在可视区时它什么
          都不做**（于是看起来"表格没动"）。这里按行号算出目标滚动位置让它居中。
        ⚠️ 行高各主题不同，优先问 ttk 样式；拿不到再按 20 估。
        """
        tv = self.table
        try:
            kids = tv.get_children()
            if iid not in kids:
                return
            n = len(kids)
            if n <= 1:
                return
            idx = kids.index(iid)
            try:
                rh = int(tv.tk.call("ttk::style", "lookup", "Treeview",
                                    "-rowheight") or 20)
            except Exception:
                rh = 20
            rh = max(1, rh)
            vh = max(1, tv.winfo_height())
            visible = max(1, vh // rh)
            if n <= visible:            # 一屏就装得下，无需滚动
                return
            top = max(0, min(n - visible, idx - visible // 2))
            tv.yview_moveto(float(top) / float(n))
        except tk.TclError:
            pass

    def _index_of_code(self, code):
        """当前表格行里，编号为 `code` 的那一行下标（找不到返回 None）。

        ⚠️ 不能用 `search_var` + `_apply_filter` 代替：那个搜索框是**按姓名**匹配的
        （喂编号进去搜不到 —— 实测 `_locate("7033")` 后表格为空、卡片没变），
        所以要按编号找就得在 `self.rows` 上直接比 `Ren_Code`。
        """
        code = str(code)
        for i, row in enumerate(self.rows):
            if str(row.get("Ren_Code") or "") == code:
                return i
        return None

    def _jump_relative(self, code):
        """点亲属名字 → **跳到那个人的档案卡**（而不是切到"关系视图"）。

        ★ 2026-09-28 使用者实测报：「**我在这里点了父亲的名字链接，应该跳转到
          父亲的该页面啊**」—— 原来亲属行的人名绑的是 `show_relations()`，
          它切到的是**关系链视图**（把此人当中心重新列一圈亲戚），与"点进这个人"
          完全是两回事。
        现在按两步走，都不依赖搜索框：
          ① 当前表里按编号找行 → 选中 + **显式刷卡片**（不指望 TreeviewSelect 回调）；
          ② 找不到才切到「人物 · 合并总表」再找一遍；
          ③ 仍找不到（跨档 / 未入表）才退回关系视图并说明原因。
        （想看"关系"仍可走表格右键菜单的「看关系」，语义不丢。）
        """
        code = str(code)

        def _select(idx):
            # ★ 顺序很要紧：**先渲染卡片，再让表格跟随选中**。
            #   `table.selection_set()` 会**同步**触发 `<<TreeviewSelect>>`（回调
            #   `_on_row` 里又是一次 `_show_detail`）—— 若先选中后渲染，真机上
            #   回调可能按"旧状态"改写/清空刚渲染的卡片（使用者看到的
            #   「**闪了一下就空白了**」）。改成：
            #     ① 卡片先渲染成目标人物（这是用户要的结果，最先保证）；
            #     ② 选中放到 `after_idle` —— 等这一轮事件跑完再对齐表格，
            #        它引发的回调刷的也是**同一个人**，不会打脸。
            self.mode.set("表格")
            self._show_detail(idx)
            # 状态栏留一句痕迹：万一卡片还是空的，看一眼状态栏就能分清
            # 「压根没跳过去」和「跳过去了但卡片没画出来」。
            try:
                _nm = str((self.rows[idx] or {}).get("Ren_Name") or "")
                if _nm:
                    self.set_status(f"已跳到「{_nm}」（编号 {code}）")
            except Exception:
                pass

            def _sync():
                try:
                    kids = self.table.get_children()
                    if 0 <= idx < len(kids):
                        # ★ 2026-09-29：改用**居中**（`see()` 只保证可见 —— 行本来
                        #   就在可视区时它什么都不做，使用者看着就是"表格没动"）。
                        self._center_table_row(kids[idx])
                        self.table.selection_set(kids[idx])
                except tk.TclError:
                    pass

            try:
                self.table.after_idle(_sync)
            except Exception:
                _sync()
            return True

        idx = self._index_of_code(code)
        if idx is not None:
            _select(idx)
            return
        if self.goto_family("人物 · 合并总表", select_code=None):
            idx = self._index_of_code(code)
            if idx is not None:
                _select(idx)
                return
        self.set_status("此人不在「人物 · 合并总表」里，改为显示关系视图", warn=True)
        self.show_relations(code)

    def _goto_code(self, code):
        """M0 查档桥入口（保留 CLI 约定）：跳到这个人的档案。"""
        if self.slot is None:
            self.set_status("还没有载入实录槽，无法定位编号 " + str(code), warn=True)
            return False
        self._locate(str(code))
        if not self.rows:
            self.set_status(f"编号 {code} 在当前实录槽（{self.slot.name}）里没有找到", warn=True)
            return False
        return True

    def locate_person(self, code="", name="", info=None):
        """查档桥（谱牒 → 实录）：优先按 code，无 code 则按姓名匹配。

        返回 True 表示定位成功。这是 M1「同进程两层」的核心收益 ——
        不再拉起外部程序，直接切页签 + 定位 + 选中。
        """
        if self.slot is None:
            return False
        if code:
            return self._goto_code(code)
        if name:
            hit = self.rel.search(name, limit=1) if self.rel else []
            if hit:
                self._goto_code(hit[0][0])
                return True
        return False

    def _mini_btn(self, parent, text, cmd):
        """标题行右侧的小按钮（← 返回上一页 / 定位到表格）—— 同样走 `FlatButton`。

        ★ 2026-09-28 全项目整理（第 5 批）：原来也是手搓 `tk.Button`（第三套配色）。
        ★ 2026-09-28 当晚补：使用者「不是说汉字也左对齐吗 跟下面的」——
          「定位到表格」以前**居中**（Label 默认 anchor=center），于是即使按钮
          左沿与「选定人物」重合，**汉字左沿仍差半格**（342 宽差约 70px）。
          这里与 `_mini_act` 用**同一套规格**：`padx=8` + `anchor="w"`
          ⇒ 两个按钮同宽同左沿时，汉字左沿自动落在同一条竖线上。
        """
        b = FlatButton(parent, self.theme, text=text, command=cmd,
                       kind="default", padx=8, h=self.theme.ctrl_h)
        b.configure(anchor="w")
        return b

    # ---- 标题行右侧的两个按钮 ----
    def _paint_act_bar(self):
        """只负责标题行右侧两颗按钮的**可见性与配色**。

        ★ 2026-09-28 清理（使用者：「你这叫堆垃圾代码」）：这里原来管着五颗按钮，
        外加一套"一行放不下就换行"的流式排布（`_place_act_btn` / `_act_rows`）。
        其中三颗的功能早就搬进了卡片按钮行和右栏：
            ◈ 看关系 → 右栏「亲属关系」段
            ⇱ 入谱   → 「立即入谱」
            ✦ 选定   → 「选定人物」
        ——属于**死代码**，连同那套排布一并删除。留下的两颗都是卡片里替代不了的：
          · ← 返回上一页：关系页 / 世系页里退回人物卡；
          · ⌖ 定位到表格：从家谱/时间轴跳过来后，回到表格里的那一行。
        两颗都挂在**标题行右侧**（与「来源」同行），不占任何额外高度。
        """
        t = self.theme
        self.back_btn.pack_forget()
        self.locate_btn.pack_forget()
        if (self.mode.get() == "关系") or getattr(self, "_in_lineage", False):
            self.back_btn.pack(side=tk.RIGHT, padx=(6, 0))
        if self._current_code():
            # 填满 `title_slot`（＝卡片两格宽）⇒ 与「选定人物」等宽、左沿重合
            self.locate_btn.pack(fill=tk.X)
        self.back_btn.configure(bg=t.accent, fg=t.accent_on,
                                activebackground=t.bg_hover,
                                activeforeground=t.accent_on)

    def _sync_title_row(self):
        """标题行的左右边界 ≡ 卡片内容区；槽宽 ≡ 卡片两格（全部量实测）。

        ★ 2026-09-28 使用者：「定位到表格 的左沿要跟『选定人物』左沿平行」，
          而它必须**留在标题行**（"放上面好好的、也不占空间"）。要对齐，
          两个容器的左右边界就得**完全一致**：卡片是
          `dv.pack(padx=(8,0))` + 纵向滚动条 `padx=(0,4)`，而滚动条的实际
          宽度由 ttk 自绘、**不等于 `scrollbar_w`** ⇒ 公式必偏。
          ⇒ 一律量实测坐标：
              · `title_row` 的左右内边距 = (卡片左缘 − 标题行左缘,
                                            标题行右缘 − 卡片右缘)
              · `title_slot` 宽 = 卡片宽 ÷ 3（＝ 6 列网格里的两格）
        """
        try:
            dv, hw = self.dv, self.headwrap
            x_dv, x_hw = dv.winfo_rootx(), hw.winfo_rootx()
            left = x_dv - x_hw
            right = (x_hw + hw.winfo_width()) - (x_dv + dv.winfo_width())
            self.title_row.pack_configure(padx=(max(0, left), max(0, right)))
            # ⚠️ 槽宽**必须量**「选定人物」按钮的实际宽度，不能按"卡片宽 ÷ 3"算：
            #   实测卡片 813 时按钮宽是 **342**（≈1026/3），而 813÷3 只有 271 ——
            #   因为 6 列网格的列宽在本项目里仍受内容需求影响。
            btn = getattr(self, "_last_act_btn", None)
            if btn is not None and btn.winfo_width() > 1:
                self.title_slot.configure(width=btn.winfo_width())
            else:
                w = dv.winfo_width()
                if w > 30:
                    self.title_slot.configure(width=max(1, int(w / 3)))
        except Exception:
            pass

    def _current_code(self):
        if self.mode.get() == "关系" and self._hist:
            return self._hist[-1]
        idx = self._selected_index()
        if idx is None or idx < 0 or idx >= len(self.rows):
            return None
        c = self.rows[idx].get("Ren_Code")
        return str(c) if c not in (None, "") else None

    def _locate_current(self):
        code = self._current_code()
        if code:
            self._locate(code)
        else:
            self.set_status("这一行不是人物，无法定位", warn=True)

    def _relations_current(self):
        code = self._current_code()
        if code:
            self.show_relations(code)
        else:
            self.set_status("这一行不是人物，没有关系可看", warn=True)

    # ---- ★ 桥：入谱（实录 → 谱牒）----
    def _push_to_book(self):
        code = self._current_code()
        if not code:
            self.set_status("这一行不是人物，无法入谱", warn=True)
            return
        p = self.people.get(code)
        nm = getattr(p, "name", "") or code
        self.app.push_to_book(code, nm)

    def _rel_section(self, title, rels, empty_hint="无", parent=None, row=None,
                     col=3, wrap=None):
        """一个亲属段（标题 + 若干行）。

        传 `row` 时落进**统一网格**，并**返回下一行号**（调用方接着排）；
        不传则退回旧的 pack 行为（兼容别处调用）。
        """
        t = self.theme
        host = parent if parent is not None else self.detail_inner
        r = row
        head = tk.Frame(host, bg=t.bg_panel)
        # ★ 2026-09-28 使用者：「人物卡单元格里面的字号统一，必要时加粗」
        #   —— 段头从 `fs_body` 收到 `fs_body_sm`（与全卡同号），只靠**加粗**区分层级。
        tk.Label(head, text=f"{title}　{len(rels) if rels else ''}", bg=t.bg_panel,
                 fg=t.text, anchor="w",
                 font=self.font(t.font_ui_fallback, t.fs_body_sm, True)).pack(side=tk.LEFT)
        if r is None:
            head.pack(fill=tk.X, padx=6, pady=(8, 2))
        else:
            head.grid(row=r, column=col, columnspan=3, sticky="w",
                      padx=(6, 0), pady=(8, 2))
            r += 1
        if not rels:
            e = tk.Label(host, text=f"　{empty_hint}", bg=t.bg_panel, fg=t.text_3,
                         anchor="w", justify=tk.LEFT,
                         wraplength=wrap or _dpi.px(210),
                         font=self.font(t.font_note, t.fs_body_sm))
            if row is None:
                e.pack(fill=tk.X, padx=10)
                return None
            e.grid(row=r, column=col, columnspan=3, sticky="w", padx=(10, 6))
            return r + 1
        for rel in rels[:40]:
            if row is None:
                self._rel_row(rel, parent=host, kind_label=title)
            else:
                self._rel_row(rel, parent=host, kind_label=title, row=r, col=col,
                              wrap=wrap)
                r += 1
        if len(rels) > 40:
            m = tk.Label(host, text=f"　…共 {len(rels)} 位", bg=t.bg_panel,
                         fg=t.text_3, anchor="w",
                         font=self.font(t.font_ui_fallback, t.fs_body_sm))
            if row is None:
                m.pack(fill=tk.X, padx=10)
                return None
            m.grid(row=r, column=col, columnspan=3, sticky="w", padx=(10, 6))
            r += 1
        return None if row is None else r

    def _rel_row(self, rel, parent=None, kind_label=None, row=None, col=3,
                 wrap=None):
        """一个亲属行。

        ★ 2026-09-28（网格化第二版）：网格模式下**行内容也拆成两格** ——
          标签占列 `col`（定宽 4 字，与左栏标签同规格）、值占列 `col+1..col+2`
          （`wraplength=wrap`）。上一版把整行塞进一个跨 3 列的 Frame：Frame 的
          **内容需求**照样能把列撑宽（实测中缝跑到表宽 41% 处），等于没定死。
        """
        t = self.theme
        host = parent if parent is not None else self.detail_inner
        # ★ 行首标签按**段名**走（兄弟 / 姐妹）—— 原始 kind 是「兄弟姐妹」四个字，
        #   放进拆开后的「姐妹」段里既重复又破对称。
        kb_txt = f"{kind_label or rel.kind}　"
        if row is not None:
            tk.Label(host, text=kb_txt, bg=t.bg_panel, fg=t.text_3, anchor="w",
                     width=4, font=self.font(t.font_ui_fallback, t.fs_body_sm)
                     ).grid(row=row, column=col, sticky="nw", padx=(6, 0), pady=1)
            if rel.placeholder:
                vb = tk.Label(host, text=f"{rel.note}", bg=t.bg_panel, fg=t.text_3,
                              anchor="w", justify=tk.LEFT,
                              wraplength=wrap or _dpi.px(200),
                              font=self.font(t.font_note, t.fs_body_sm))
                vb.grid(row=row, column=col + 1, columnspan=2, sticky="w",
                        padx=(2, 0), pady=1)
                Tooltip(vb, "占位 · 非真人 —— 存档里只留了一个名字（如「媵妾」），"
                            "没有这个人。")
                return
            p = rel.person
            if p is None:
                tk.Label(host, text="（查不到）", bg=t.bg_panel, fg=t.text_3,
                         anchor="w",
                         font=self.font(t.font_ui_fallback, t.fs_body_sm)
                         ).grid(row=row, column=col + 1, columnspan=2, sticky="w",
                                padx=(2, 0), pady=1)
                return
            txt, fg, can_jump = self._rel_text(rel)
            lb = tk.Label(host, text=txt, bg=t.bg_panel, fg=fg, anchor="w",
                          justify=tk.LEFT,
                          wraplength=wrap or _dpi.px(200),
                          cursor="hand2" if can_jump else "arrow",
                          font=self.font(t.font_ui_fallback, t.fs_body_sm, can_jump))
            lb.grid(row=row, column=col + 1, columnspan=2, sticky="w",
                    padx=(2, 0), pady=1)
            if can_jump:
                lb.bind("<Button-1>", lambda e, c=p.code: self._jump_relative(c))
            return
        # ── 兼容：旧的 pack 行（别处调用）──
        line = tk.Frame(host, bg=t.bg_panel)
        line.pack(fill=tk.X, padx=(14, 6), pady=1)
        tk.Label(line, text=kb_txt, bg=t.bg_panel, fg=t.text_3,
                 font=self.font(t.font_ui_fallback, t.fs_body_sm)).pack(side=tk.LEFT)
        if rel.placeholder:
            lb = tk.Label(line, text=f"{rel.note}", bg=t.bg_panel, fg=t.text_3,
                          font=self.font(t.font_note, t.fs_body_sm))
            lb.pack(side=tk.LEFT)
            # 括号里的说明挪到悬停（使用者 2026-09-21 要求）
            Tooltip(lb, "占位 · 非真人 —— 存档里只留了一个名字（如「媵妾」），"
                        "没有这个人。")
            return
        p = rel.person
        if p is None:
            tk.Label(line, text="（查不到）", bg=t.bg_panel, fg=t.text_3,
                     font=self.font(t.font_ui_fallback, t.fs_body_sm)).pack(side=tk.LEFT)
            return
        txt, fg, can_jump = self._rel_text(rel)
        lb = tk.Label(line, text=txt, bg=t.bg_panel, fg=fg,
                      cursor="hand2" if can_jump else "arrow",
                      font=self.font(t.font_ui_fallback, t.fs_body_sm, can_jump))
        lb.pack(side=tk.LEFT)
        if can_jump:
            lb.bind("<Button-1>", lambda e, c=p.code: self._jump_relative(c))

    def _rel_text(self, rel):
        """亲属行的「显示文本 / 颜色 / 可否跳转」—— 两种模式共用一份口径。"""
        t = self.theme
        p = rel.person
        extra = []
        if p.sex is not None:
            extra.append(p.sex_label)
        if not p.alive:
            extra.append("已故")
        if p.level is not None:
            lv = L.leve_label(p.level)
            if lv:
                extra.append(f"等级 {lv}")
        if PF.is_historical(p.code):
            # ★ 2026-09-28 使用者要求：两栏卡片空间紧，「史实」简化成一个「史」
            extra.append("史")
        txt = p.name + (f"　·　{'/'.join(extra)}" if extra else "")
        can_jump = bool(self.rel.get(p.code))
        # 女性人名标红（使用者要求「女性角色名字在任何地方都标红」），压过「可跳转」的青色
        fg = t.spouse if p.sex_label == "女" else (t.accent if can_jump else t.text)
        return txt, fg, can_jump

    def _rel_chain(self, title, pairs, more=0, parent=None, row=None, col=3,
                   wrap=None):
        """直系链（父系上溯 / 后代下推）。传 `row` 时落格并返回下一行号。"""
        t = self.theme
        host = parent if parent is not None else self.detail_inner
        r = row
        head = tk.Frame(host, bg=t.bg_panel)
        tk.Label(head, text=title, bg=t.bg_panel, fg=t.text, anchor="w",
                 font=self.font(t.font_ui_fallback, t.fs_body_sm, True)).pack(side=tk.LEFT)
        if r is None:
            head.pack(fill=tk.X, padx=6, pady=(8, 2))
        else:
            head.grid(row=r, column=col, columnspan=3, sticky="w",
                      padx=(6, 0), pady=(8, 2))
            r += 1
        for p, tag in pairs:
            line = tk.Frame(host, bg=t.bg_panel)
            if row is None:
                line.pack(fill=tk.X, padx=(14, 6), pady=1)
            else:
                line.grid(row=r, column=col, columnspan=3, sticky="ew",
                          padx=(14, 6), pady=1)
                r += 1
            tk.Label(line, text=f"{tag}　", bg=t.bg_panel, fg=t.text_3, width=5,
                     anchor="w", font=self.font(t.font_ui_fallback, t.fs_body_sm)
                     ).pack(side=tk.LEFT)
            can_jump = bool(self.rel.get(p.code))
            name_fg = t.spouse if p.sex_label == "女" else (t.accent if can_jump else t.text)
            lb = tk.Label(line, text=p.name, bg=t.bg_panel,
                          fg=name_fg, anchor="w", justify=tk.LEFT,
                          wraplength=wrap or _dpi.px(210),
                          cursor="hand2" if can_jump else "arrow",
                          font=self.font(t.font_ui_fallback, t.fs_body_sm, can_jump))
            lb.pack(side=tk.LEFT)
            if can_jump:
                lb.bind("<Button-1>", lambda e, c=p.code: self._jump_relative(c))
        if more > 0:
            m = tk.Label(host, text=f"　…还有 {more} 位", bg=t.bg_panel, fg=t.text_3,
                         anchor="w", font=self.font(t.font_ui_fallback, t.fs_body_sm))
            if row is None:
                m.pack(fill=tk.X, padx=10)
            else:
                m.grid(row=r, column=col, columnspan=3, sticky="w", padx=(10, 6))
                r += 1
        return None if row is None else r

    def _show_missing_person(self, code):
        t = self.theme
        for w in self.detail_inner.winfo_children():
            w.destroy()
        self.detail_title.configure(text="关系")
        self.detail_src.configure(text=f"编号 {code}")
        tk.Label(self.detail_inner,
                 text=f"当前实录槽里没有编号 {code} 的人物记录。\n\n"
                      f"常见原因有两个：\n"
                      f"　· 这个人只作为别人的「父亲」「兄弟」被提到过，\n"
                      f"　　游戏没给他单独建档；\n"
                      f"　· 或者他属于另一个存档 —— 换档之后编号会变。\n\n"
                      f"点最上方的「← 返回上一页」可以退回去。",
                 bg=t.bg_panel, fg=t.text_3, justify=tk.LEFT, anchor="w",
                 font=self.font(t.font_ui_fallback, t.fs_body_sm), wraplength=_dpi.px(390)
                 ).pack(fill=tk.X, padx=10, pady=10)

    def _expand_all(self):
        if "人物 · 非史实" in self.slot.tables and not self.show_generated.get():
            self.show_generated.set(True)
        self._rebuild_nav()
        self.set_status("已展开全部（含非史实人物）")

    # ---------------------------------------------------------------- 帮助
    def _show_help(self):
        messagebox.showinfo(
            "字段说明 · 实录层",
            "实录层把存档里的每个字段都译成了中文。\n\n"
            "【字段名】100% 中文化 —— 实测出现的字段名全部有中文标签。\n\n"
            "【字段值】只翻译有实证依据的，比如：\n"
            "　· 性别 0=男 1=女（用「纯女性表」反证过）\n"
            "　· 等级（男）0=庶 1=下 2=中 3=上 4=邦；5=将 6=臣 10=圣 11=神\n"
            "　· 等级（女）100=美 101=佳 102=淑 103=丽 104=良（码大者高）\n"
            "　· 爵位 3=王 5=侯 7=子（与上古档的国世系文本逐一对上）\n"
            "　证据不足的数字码会**原样显示**，不会编一个像样的错中文。\n\n"
            "【人物信息】\n"
            "　· **卒年 = 生年 + 享年**（存档没存卒年，是本工具算的）\n"
            "　· **容貌不显示** —— 那是内部外观编号，游戏里根本看不到\n"
            "　· 日期一律紧凑格式（`-1106.01`）\n\n"
            "【史实 / 非史实】\n"
            "　· 编号 ≤5 位 = 史实人物；9 位 = 游戏随机生成\n\n"
            "【两座桥】\n"
            "　· ⇱ 入谱：把这个人的已知字段写进当前**谱牒档**（family.json）\n"
            "　· 谱牒层里右键「⌖ 查档」可以跳回这里\n\n"
            "【只读铁律】实录层不提供任何写盘功能，不会改动你的游戏存档。")

    def _render_empty(self):
        self.table.delete(*self.table.get_children())
        self.nav.delete(*self.nav.get_children())
        self.table_title.configure(text="（未载入）")
        for w in self.detail_inner.winfo_children():
            w.destroy()

    def set_status(self, text, warn=False):
        sb = getattr(self.app, "statusbar", None)
        if sb is not None:
            sb.set("hint", text, accent=not warn)
