"""主题令牌 —— 单一定义源（史馆版）。

所有视图只引用这里的令牌，不写字面量颜色/字号/间距。
色值与尺寸取自 design/v2.0-效果图.html 与《史馆 · 合并效果图》（规划 §四）。

史馆在家族树令牌基座上补了两组：
  · 语义色 `ok`/`warn` 与表格斑马纹 `row_even` —— 阅览器表格要用
  · **谱牒层橙金** `edit*`/`bridge` —— 与实录层青绿 `accent` 成对，
    页签与动作按钮靠这组色区分「查阅」与「动笔」（规划 §四 + §简介）
"""
from dataclasses import dataclass, field

from . import dpi as _dpi
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class Theme:
    key: str
    name: str
    short: str          # 顶栏胶囊用的短名（效果图里显示"宣纸"/"墨夜"）
    desc: str

    # ---- 背景 ----
    bg_app: str
    bg_bar: str
    bg_panel: str
    bg_card: str
    bg_input: str
    bg_canvas: str
    bg_hover: str
    bg_sel: str
    chip_bg: str

    # ---- 描边 ----
    border: str
    border_2: str
    grid: str

    # ---- 文字 ----
    text: str
    text_2: str
    text_3: str
    text_inverse: str

    # ---- 主色 / 语义 ----
    accent: str
    accent_2: str
    accent_soft: str
    accent_on: str
    danger: str
    danger_soft: str
    ok: str                      # 语义 · 成功/正向
    warn: str                    # 语义 · 提示/琥珀
    spouse: str
    divine: str
    female: str
    row_even: str                # 表格斑马纹（阅览器表格沿用）
    # ---- 谱牒层（编辑）色：橙金，与实录层青绿 accent 成对 ----
    edit: str
    edit_2: str
    edit_soft: str
    edit_on: str
    bridge: str                  # 桥动作专用（两层次要的强调色）

    # 介绍文本三段配色（与 v1 介绍栏一致：人物名深红 / 封国深绿 / 尊号正红）
    bio_person: str
    bio_state: str
    bio_note: str

    # ---- 画布 ----
    tree_line: str

    # ---- 爵位色 ----
    tier: Dict[str, str]

    # ---- 字体族 ----
    font_ui: str = "Microsoft YaHei UI"
    font_ui_fallback: str = "微软雅黑"
    font_name: str = "KaiTi"          # 楷体：姓名
    font_note: str = "SimSun"          # 宋体：尊号
    font_gen: str = "LiSu"             # 隶书：代数标签

    # ---- 已故行底色（谱牒层表格：有卒年的人整行压一层灰）----
    # 2026-09-21 使用者要求「表格里去世的人物用灰色阴影涂上」。
    # 与斑马纹 bg_canvas/bg_card 是**两套**：已故行不再分奇偶，统一这一色，
    # 否则灰底和斑马纹叠在一起反而看不出「这行是已故」。
    bg_dead: str = ""
    # ---- 「仅显所选」高亮（★ 2026-09-23 使用者要求）----
    # 被右键「选定（仅显所选）」的人在**人物页表格 / 家谱铭牌 / 表格页行**
    # 三处都要一眼认出来。现有语义色已被占满（青绿=实录、橙金=谱牒、
    # 品红=女性与夫妻线、琥珀=提示、正红=危险、灰=已故），故取**紫**这一支：
    # 与上述全部可区分，浅/深两套主题下都够醒目，也不与使用者偏好的天蓝水绿打架。
    focus_hi: str = "#6b5bb5"      # 边框与文字（紫）
    focus_bg: str = "#ece7f8"      # 整格底色（淡紫）

    # ---- 夫妻连线（2026-09-23 使用者要求：淡红虚线折线）----
    # spouse 是品红实线用的强色；连线改淡一档、走虚线，避免和女性红字/危险红抢眼。
    # 空串 = 回退 spouse（旧配置不炸）。
    spouse_line: str = ""

    # ---- 「史」徽标专用色（UI 改进 A3）----
    # 原来借用 divine（深红系），与女性标红、危险红同族难分。
    # 金褐/琥珀与三主题的女性品红、danger 正红、爵位王金都可区分。
    # 空串 = 回退 divine（tree_view 里 `theme.hist or theme.divine`），老配置不炸。
    hist: str = ""

    # ---- 尺寸（效果图实测）----
    # ★ 2026-09-22 使用者反馈：顶栏选中条（药囊）在缩放显示下比文字行高还挤，
    #   「字被 bar 盖住」。按使用者给的选项「把 bar 弄厚一点」办：
    #   顶栏 52→56、工具栏 42→46，配合药囊内边距收紧（shell._Tab / TopBar），
    #   保证 125% DPI 下条高仍有富余，绝不裁字。
    topbar_h: int = 48
    # ★ 2026-09-23 对齐精修：顶栏/工具栏所有控件统一 32 高、12 号字（ctrl_h/
    #   fs_ctrl），工具栏单行 46（32 + 上下 7），不再有组名小字行
    toolbar_h: int = 46
    ctrl_h: int = 32
    # ★ 2026-09-23 288→336：筛选做成等宽两列网格后，每列要放下
    #   「✓ + 4字标签 + 4位计数」（实测选中态需 135px；288 宽只给得出 118px，
    #   320 宽给 134px 仍差 1px）。336 时每列 142px，留 7px 余量，
    #   高 DPI 下字体变宽也不会裁字。
    sidebar_w: int = 336
    statusbar_h: int = 28
    titlebar_h: int = 34          # 系统标题栏（规划 §四 示意，仅存档备用）
    card_radius: int = 8
    pill_h: int = 30
    btn_h: int = 27
    input_h: int = 27
    label_w: int = 58
    scrollbar_w: int = 10

    # ---- 字号 ----
    fs_body: int = 12
    fs_body_sm: int = 11
    fs_title: int = 12
    fs_brand: int = 15
    fs_caption: int = 10
    fs_status: int = 11
    fs_hero: int = 13
    fs_ctrl: int = 12             # 顶栏/工具栏控件统一字号（页签、胶囊、按钮）

    # ---- 画布节点 ----
    node_w: int = 20            # 节点框宽（缩放前）
    node_h: int = 60            # 节点框高（缩放前）
    min_node_font: int = 6      # 名字/尊号字号下限
    node_text_padding: int = 2  # 框内上下留白（缩放前）

    # ---- 画布节点卡片（新版「竖向卡片式」专用）----
    # 经典版用不到这几项；卡片版靠它们把节点画成实心淡底小卡片。
    # 底色必须不透明 —— 节点画在连线之后，正好挡住穿过的连线（互补遮掩）
    node_bg: str = ""           # 卡片底色（空 = 用画布底色）
    node_bd: str = ""           # 卡片描边（空 = 用 border_2）
    node_bar_w: int = 3         # 左侧爵位色条宽（缩放前）
    node_radius: int = 4        # 卡片圆角半径（缩放前）

    # ---- 家族宗支色（与 v1 一致，两套主题共用）----
    branch_bg: List[Tuple[str, str]] = field(default_factory=lambda: [
        ("主脉绿", "#4CAF50"), ("黄色", "#FFEB3B"), ("蓝色", "#2196F3"), ("粉色", "#E91E63"),
        ("紫色", "#9C27B0"), ("橙色", "#FF9800"), ("青色", "#00BCD4"), ("红色", "#F44336"),
        ("棕色", "#795548"), ("灰色", "#607D8B"),
    ])
    branch_fg: List[Tuple[str, str]] = field(default_factory=lambda: [
        ("浅黄", "#FFF9C4"), ("浅蓝", "#BBDEFB"), ("浅粉", "#F8BBD0"), ("浅紫", "#E1BEE7"),
        ("浅橙", "#FFE0B2"), ("浅绿", "#C8E6C9"), ("浅灰", "#E0E0E0"), ("浅棕", "#D7CCC8"),
        ("浅红", "#FFCDD2"), ("浅青", "#B2EBF2"),
    ])

    # ---- ★ 2026-09-26 DPI：界面骨架的像素尺寸随系统缩放换算 ----
    # 感知 DPI 后 Tk 的 pt 字号自动放大（tk scaling），但这些写死的像素
    # 栏高/宽度不会 —— 不跟着乘会在 125%/150% 屏上「字大框小」挤爆。
    # ⚠️ 两类**故意不乘**：
    #   · fs_*（pt 字号）—— Tk 自放大，再乘就双重；
    #   · node_*（画布节点令牌）—— 画布绘制处已经 `× self.scale`，
    #     而 BASE_SCALE 已吃进缩放系数（tree_view），再乘会双重。
    def __post_init__(self):
        for f in ("topbar_h", "toolbar_h", "ctrl_h", "sidebar_w",
                  "statusbar_h", "titlebar_h", "pill_h", "btn_h",
                  "input_h", "label_w", "scrollbar_w", "card_radius"):
            object.__setattr__(self, f, _dpi.px(getattr(self, f)))


TIER_NAMES = ["无", "卿", "子", "伯", "侯", "公", "王", "帝"]

# 爵位装饰线（与 v1 一致）
TIER_DECOR = {
    "皇帝": ("#CC0000", "═╤═"),
    "王": ("#FFD700", "═══"),
    "公": ("#9B30FF", "◆─◆"),
    "侯": ("#0044FF", "●─●"),
    "伯": ("#00AA00", "▲─▲"),
    "子": ("#007777", "◇─◇"),
    "卿": ("#555555", "·─·"),
    "无": ("#AAAAAA", "───"),
}

TIER_PRIORITY = {"帝": 8, "王": 7, "公": 6, "侯": 5, "伯": 4, "子": 3, "卿": 2, "无": 1}


PAPER = Theme(
    key="paper",
    name="宣纸 · 精修",
    short="宣纸",
    desc="米黄纸感 + 楷体隶书，与现有爵位配色体系一致，长时间阅读族谱更柔和。",
    bg_app="#eee9df",
    bg_bar="#f8f4e8",
    bg_panel="#f8f4e8",
    bg_card="#fdfaee",
    bg_input="#ffffff",
    bg_canvas="#fffdf7",
    bg_hover="#efe7d7",
    bg_sel="#e4eddc",
    chip_bg="#efe7d7",
    border="#ddd0b8",
    border_2="#c0ae90",
    grid="#e7ddc9",
    text="#2a1a0a",
    text_2="#6b5b45",
    text_3="#7a6a52",
    text_inverse="#ffffff",
    accent="#1f6b4f",
    accent_2="#2e8b62",
    accent_soft="#dceade",
    accent_on="#ffffff",
    danger="#b3261e",
    danger_soft="#f6dedb",
    ok="#2e7d32",
    warn="#b8860b",
    row_even="#faf5e8",
    edit="#c67b1a",
    edit_2="#a8630f",
    edit_soft="#f7e7cf",
    edit_on="#ffffff",
    bridge="#8a5a12",
    spouse="#B03060",
    divine="#C0272D",
    female="#F6D3DA",
    hist="#b8860b",
    bio_person="#8B0000",
    bio_state="#2E7D32",
    bio_note="#CC0000",
    tree_line="#a89880",
    spouse_line="#D990A8",
    node_bg="#faf5e8",
    node_bd="#e2d6bd",
    bg_dead="#e9e4d9",
    focus_hi="#6b4fc4", focus_bg="#efe9ff",
    tier={
        "帝": "#8B0000", "王": "#A9760A", "公": "#7B22CC", "侯": "#0044CC",
        "伯": "#006600", "子": "#007777", "卿": "#3a3a3a",
        # ★ 2026-09-26 使用者反馈「画布上的字有点不清晰」——
        #   绝大多数人无爵，名字原来用 #8a8a8a 中灰，画在米色画布上对比度
        #   不足（加上楷体小字号笔画细）⇒ 发灰发虚。加深到 #5f5f5f，
        #   与「卿」(#3a3a3a) 仍有层次差。
        "无": "#5f5f5f",
    },
)

INK = Theme(
    key="ink",
    name="墨夜",
    short="墨夜",
    desc="深灰蓝底 + 腾讯蓝主色，接近纯黑的画布已提亮，夜里看不刺眼。",
    bg_app="#1b1f24",
    bg_bar="#22272e",
    bg_panel="#22272e",
    bg_card="#2a3038",
    bg_input="#2f3640",
    bg_canvas="#191d22",
    bg_hover="#333b45",
    bg_sel="#1f4a5c",
    border="#3a424c",
    border_2="#4c5763",
    grid="#2f363f",
    text="#e6edf3",
    text_2="#a9b6c4",
    text_3="#7f8c9b",
    text_inverse="#0b1016",
    accent="#12b7f5",
    accent_2="#4dd0e1",
    accent_soft="#14394a",
    accent_on="#0b1016",
    danger="#ff7b72",
    danger_soft="#3a2222",
    ok="#56d364",
    warn="#e3b341",
    row_even="#252b32",
    edit="#e3a341",
    edit_2="#c78a2d",
    edit_soft="#3d2f18",
    edit_on="#0b1016",
    bridge="#ffb95e",
    spouse="#f472a8",
    divine="#ff8a8a",
    female="#4a2f3d",
    hist="#e3b341",
    bio_person="#ff9d8a",
    bio_state="#7ee0a8",
    bio_note="#ff8a8a",
    tree_line="#7a8b9c",
    spouse_line="#f9aecb",
    node_bg="#1f2c38",
    node_bd="#35485c",
    bg_dead="#171b20",
    focus_hi="#b9a6ff", focus_bg="#2b2440",
    chip_bg="#333b45",
    tier={
        "帝": "#ff7b72", "王": "#e3b341", "公": "#b392f0", "侯": "#79c0ff",
        "伯": "#56d364", "子": "#56d4dd", "卿": "#adbac7", "无": "#8b98a5",
    },
)

TENCENT = Theme(
    key="tencent",
    name="腾讯蓝",
    short="腾讯蓝",
    desc="桌面客户端风格：浅灰底 + 白色卡片 + 腾讯蓝主色，干净通透，长时间看族谱不累。",
    bg_app="#eef0f2",
    bg_bar="#f7f8fa",
    bg_panel="#f7f8fa",
    bg_card="#ffffff",
    bg_input="#ffffff",
    bg_canvas="#fbfcfd",
    bg_hover="#e8f4fd",
    bg_sel="#d6ecfb",
    border="#e3e6ea",
    border_2="#c9d0d8",
    grid="#eef1f4",
    text="#1f2329",
    text_2="#5a6472",
    text_3="#7b8694",
    text_inverse="#ffffff",
    accent="#12b7f5",
    accent_2="#0aa0e0",
    accent_soft="#e3f5fe",
    accent_on="#ffffff",
    danger="#e54545",
    danger_soft="#fdecec",
    ok="#2e7d32",
    warn="#b8860b",
    row_even="#f7f9fb",
    edit="#c67b1a",
    edit_2="#a8630f",
    edit_soft="#fbf0dd",
    edit_on="#ffffff",
    bridge="#8a5a12",
    spouse="#d81b60",
    divine="#d4380d",
    female="#fde8ef",
    hist="#b8860b",
    bio_person="#c62828",
    bio_state="#2e7d32",
    bio_note="#d32f2f",
    tree_line="#b8c2cc",
    spouse_line="#ea92ad",
    node_bg="#ffffff",
    node_bd="#e3e6ea",
    bg_dead="#eceef1",
    focus_hi="#6b4fc4", focus_bg="#efe9ff",
    chip_bg="#eef1f4",
    tier={
        "帝": "#c62828", "王": "#b8860b", "公": "#7b22cc", "侯": "#1565c0",
        "伯": "#2e7d32", "子": "#00838f", "卿": "#424242",
        # ★ 同 paper：无爵名字加深（浅灰白底上对比不足）
        "无": "#616161",
    },
)

THEMES = {"paper": PAPER, "tencent": TENCENT, "ink": INK}
DEFAULT_THEME = "paper"

# 画布节点版式：只改「怎么画」，不改布局几何
#   classic 经典版 —— 透明框 + 顶部爵位装饰线（v1 原版画法）
#   card    竖向卡片式 —— 淡底卡片 + 左侧爵位色条 + 右上角爵位小字
NODE_STYLES = [("classic", "经典版"), ("card", "竖向卡片式")]
DEFAULT_NODE_STYLE = "classic"


def get_node_style(key: str) -> str:
    """按 key 取节点版式；未知 key 回落到默认版式。"""
    return key if key in dict(NODE_STYLES) else DEFAULT_NODE_STYLE


def get_theme(key: str) -> Theme:
    """按 key 取主题；未知 key 回落到默认主题。"""
    return THEMES.get(key or "", THEMES[DEFAULT_THEME])


def ui_font(theme: Theme, size: int = None, bold: bool = False):
    """界面字体元组（微软雅黑系列）。"""
    return (theme.font_ui_fallback, size or theme.fs_body, "bold" if bold else "normal")
