# -*- coding: utf-8 -*-
"""M1 · 外壳统一 —— 契约包。

史馆 = 实录层（只读，来自存档阅览器）× 谱牒层（可编辑，来自家族树 v2.0）。
本模块只放**两层共用的中性定义**，不导入任何一个视图，避免循环依赖。

术语（规划 D13 全汉字化）：
  · 实录 = 游戏存档，只读；「实录槽」= 一个 Save_All_N 目录
  · 谱牒 = family.json，可编辑；「谱牒档」= saves/<名>/
"""
import os
import sys


def _base_dir():
    """基准目录 = **放数据的那个目录**（`saves/`、`config.json`、`staging/` 都在这）。

    ★ 2026-09-30 打包（PyInstaller）后必须走 `sys.frozen` 分支：
      单文件 exe 会把 Python 代码解到临时目录 `_MEIPASS`，此时
      `__file__` 指向**临时目录** —— 若沿用它当基准，
      `saves/` 与 `config.json` 会写进临时目录，**程序一退出就没了**
      （正是"打包后存档丢失"这类事故的根源）。
      冻结时改用 **exe 所在目录**，于是把 exe 放在项目根目录，
      `saves/` 就在它旁边，与源码运行时完全一致。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(here)


BASE_DIR = _base_dir()
RESOURCE_DIR = BASE_DIR

# 实录槽默认搜索根（与阅览器一致：模拟器导出目录）
RECORD_BASES = [
    r"D:\DevCache\dzlgz",
    r"D:\DevCache",
]


APP_NAME = "大周列国志 · 史馆"
APP_VER = "2.0"
WINDOW_SIZE = "1440x860"
WINDOW_TITLE = f"{APP_NAME} {APP_VER}"

# ---- 四页签：键 / 中文名 / 图标 / 层（record=实录 族 edit=谱牒族）----
# ★ 2026-09-23 使用者要求「时间轴和家谱改名为家谱，两种模式」：
#   独立「时间轴」页签取消，「家谱」页签内用模式切换（代际=原家谱 / 时间=原时间轴），
#   由 config.family_mode 决定（见 main._build_main_view 的 key=="tree" 分支）。
VIEWS = (
    ("person",   "人物",   "⌂", "record"),
    ("tree",     "家谱",   "♣", "edit"),
    ("world",    "世界",   "⛨", "record"),
    ("table",    "表格",   "▦", "edit"),
)
VIEW_KEYS = tuple(v[0] for v in VIEWS)
VIEW_LABEL = {v[0]: v[1] for v in VIEWS}
VIEW_LAYER = {v[0]: v[3] for v in VIEWS}
DEFAULT_VIEW = "person"

# 家谱页签的两种显示模式（2026-09-23）：
#   "gen"  代际 —— 原「家谱」页（树形，纵轴=谱系代）
#   "time" 时间 —— 原「时间轴」页（纵轴=绝对年份）
# 显示名不带括号（使用者要求「括号里不要写」）。
FAMILY_MODES = ("gen", "time")
FAMILY_MODE_LABEL = {"gen": "代际", "time": "时间"}
# （老 view 键 → 模式 的迁移映射原来在这里，全项目无人引用 —— 2026-09-26
#   审查删除；迁移逻辑实际写在 main.__init__ 里，见「view: timeline 已取消」。）

# 分隔线位置：青绿组（实录）与橙金组（谱牒）之间
VIEW_GAP_AFTER = "tree"      # 该键之前插分隔（人物·家谱 | 世界·表格）
LAYER_ICON = {"record": "青绿 · 实录层（只读）", "edit": "橙金 · 谱牒层（可编辑）"}

LAYER_NAME = {"record": "实录", "edit": "谱牒"}
