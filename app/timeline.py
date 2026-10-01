# -*- coding: utf-8 -*-
"""时间轴视图 · 纯计算层（不碰 Tkinter，可单测、可被导出图片复用）。

与主树的关系
------------
主树（`layout.py`）的纵轴是**谱系代**（`generation`），实测同一层的人平均跨 443 年，
所以它**不可能**让「生卒年与纵轴对应」。这个模块就是为那件事单独开的：

    y = 绝对年份（生年 × 比例尺），x = 树状发散

x 的排法沿用 v1 `layout.py` 的原班逻辑（`subtree_width` + `_place_tree_person`）：
**父亲居中于孩子之上**，每个孩子的子树独占一段横向区间，后代向两侧散开。

唯一新增的是**碰撞处理**：v1 每代等距，兄弟子树天然不撞；这里 y 变成生年之后
不同支系的时间会交错，所以给每棵子树加了一条「按轮廓找最小不撞偏移」，
不同 y 区间的子树可以互相咬合，比纯按宽度并排省不少横向。
"""
import math
from collections import defaultdict
from dataclasses import dataclass, field

from . import dpi as _dpi
from typing import Callable, Dict, List, Optional, Sequence, Tuple

# ==================================================================== 常量

CARD_W_MIN = _dpi.px(34.0)        # 卡片最小宽度（横排；竖排按 PLATES v 的第二元）
CARD_H = _dpi.px(24.0)            # 卡片高度（横排铭牌；固定，不代表寿命）
GAP = _dpi.px(17.0)               # 卡片之间的最小间隙
MIN_DY = CARD_H + GAP    # 同一列相邻两张卡的最小垂直间距 = 41px

# ------------------------------------------------------------------ 铭牌字号
# 基准字号取**主树节点那一套**（`tree_view` 里 `base = int(15 * scale)`，
# 默认 80% 缩放下就是 15pt）—— 时间轴铭牌原来只有 8pt，比主树小一半，被使用者一眼看出。
# 「弹性」= 框固定、只缩字（和主树 `_fit` 同一个套路）：
#   横排：名字超过 `CARD_W_MAX` 就一级级降字号，直到装得下；
#   竖排：一个字一行，按「字数 × 行高」降到装得进卡片高度。
# 15pt 一个全角字 ≈ 21px、行高 20px —— 卡片高 = 20 + 上下各 2px = 24。
# ★ 2026-09-23 使用者要求「铭牌再窄一些，左右边沿与字的距离参考家谱标准」：
#   横排左右内边距从 12 收到 6（左 2px 爵位色条 + 名字侧面留 3px），
#   竖排卡片宽从 25 收到 22（名字 21px + 左右各 0.5）。尊号/谥号不再占卡宽，
#   一律画到右侧框外（见 timeline_view._draw_card）。
FONT_PT = 15             # 基准字号（= 主树名字字号）
FONT_PT_MIN = 8          # 弹性下限
CARD_PAD_X = _dpi.px(6)           # 横排左右内边距（含左边 2px 爵位色条）—— 2026-09-23 12 → 6
CARD_PAD_Y = _dpi.px(2)           # 横排上下内边距
CARD_W_MAX = _dpi.px(80)          # 横排卡片最大宽：3 字 15pt = 63、4 字 12pt = 68，+12 内边距都塞得下
CHAR_W_EST = _dpi.px(21.0)        # 基准字号下一个全角字的宽度（纯计算层不碰 Tk，只能按这个估）

# 两种铭牌：横排（默认，名字一行读完）与竖排（一个字一行，省横向）。
# 值 = (卡片高, 最小宽)。竖排高按「最多 4 字 × 15pt 行高 20」其实塞不下，
# 所以竖排的文字会走弹性降级（4 字 → 9pt）。竖排宽 = 15pt 一个全角字 21 + 1。
# ★ 2026-09-26 使用者要求「时间家谱的铭牌大小参照代际家谱一样做」：
#   竖排从 54×22 对齐到**代际树节点那一套**（高 60 × 宽 20，字号同为 15pt）——
#   两种视图的铭牌从此同尺寸、同字号，来回切换不再「一大一小」。
PLATES = {
    "h": (CARD_H, CARD_W_MIN),
    "v": (_dpi.px(60.0), _dpi.px(20.0)),     # = 代际树 node_h / name_width（2026-09-26 统一）
}
SIB_GAP = _dpi.px(12.0)           # 兄弟子树之间的最小水平间隙
CHANNEL = _dpi.px(70.0)           # 连线避让的列间通道宽度参考
# 避让时由近及远试的通道距离（× CHANNEL）与上下让位量（px）。
# 分两档：`NEAR_*` 是「快速试」用的（每次几十~上百次判定），远处的不穷举，
# 交给 A* 兜底 —— 穷举每一档会让整体慢好几倍，收益却很小。
CHANNEL_MAGS = (0.34, 0.5, 0.7, 0.85, 1.1, 1.3, 1.6, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0)
LEVEL_OFFSETS = tuple(_dpi.px(v) for v in (6.0, 10.0, 14.0, 20.0, 28.0, 40.0))
NEAR_CHANNEL_MAGS = (0.34, 0.5, 0.7, 1.1)
NEAR_LEVEL_OFFSETS = tuple(_dpi.px(v) for v in (6.0, 10.0, 14.0, 20.0))
LEFT_MARGIN = _dpi.px(70.0)       # 画布左内边距
BOTTOM_MARGIN = _dpi.px(40.0)     # 画布底内边距
TOP_PAD_YEARS = 5        # 视口顶在最早生年之上留几年

SCALE_MIN = 2.43 * _dpi.SCALE         # 几何下限（14 年 × 比例 ≥ 卡片 17 + 间隙 17）
SCALE_MAX = 12.0 * _dpi.SCALE
# ★ 2026-09-23 使用者要求「每一年占的像素再短一点」：默认 5 → 4 px/年。
SCALE_DEFAULT = 4.0 * _dpi.SCALE
MIN_FERTILE_GAP = 14     # 游戏里父子最小生育间隔（年）

YEAR_START_DEFAULT = -2500
YEAR_END_DEFAULT = 1000
ERA_TAIL_MARGIN = _dpi.px(30)     # 「本档最晚年」之后再留几年，免得最后一屏贴边（见 year_bounds）

# 朝代分界：只记每个朝代的**起始年**，终点取下一个的起始年 - 1。
# 一律用真实历史，不受开局年份影响。
# ★ 2026-09-22 使用者裁定：前 2070 之前标「上古」（原「传说时代」全改）。
ERA_STARTS: List[Tuple[str, int]] = [
    ("上古", -99999),
    ("夏", -2070),
    ("商", -1600),
    ("西周", -1046),
    ("春秋", -770),
    ("战国", -475),
    ("秦", -221),
    ("汉", -206),
    ("三国", 221),
    ("晋", 281),
    ("南北朝", 421),
    ("隋", 590),
    ("唐", 619),
    ("五代", 908),
    ("宋", 961),
]


# ==================================================================== 年份 / 朝代

def to_int(v) -> Optional[int]:
    """存档里的生卒年是字符串（可能是 '' / '-2455' / 脏值）。转不了就返回 None。"""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int):
        return v
    s = str(v).strip()
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


# 生年的合理区间。游戏时间线是涿鹿之战（约前 2500）到王莽篡汉（公元 23），
# 前 4000 ~ 公元 2000 已经绰绰有余。
# 实测脏值很多：手写的「上古时代」档里有 `-24301001`（像是「-2430」和某个编号拼在一起了），
# 直接拿来算会把画布撑到 1 亿像素高。
YEAR_PLAUSIBLE = (-4000, 2000)


def birth_year(info) -> Optional[int]:
    """取一个**可信**的生年；脏值一律当作「没有生年」。

    ★ 2026-09-22：谱牒里的 birth 升级成了完整「年,月,日」三元组（`-446,9,0`），
      `to_int` 转不了带逗号的串。这里先取第一段（年）再转 —— 否则所有
      带月日的谱牒在时间轴上全部显示「无生年数据」（南越崛起档就是这个症状）。
    """
    raw = (info or {}).get("birth")
    y = to_int(str(raw).split(",")[0].strip()) if isinstance(raw, str) else to_int(raw)
    if y is None or not (YEAR_PLAUSIBLE[0] <= y <= YEAR_PLAUSIBLE[1]):
        return None
    return y


def _in_cycle(n: str, father_of: Dict[str, str]) -> bool:
    """沿父链上溯，若回到走过的点，说明 n 的祖先里成环（存档脏数据）。

    成环的人谁也当不了根，直接当根处理（丢掉它的父边），否则会：
      · 从 roots 出发永远走不到 → 这些人拿不到坐标（实测秦末档有）
      · 递归 place() 无限下钻
    """
    seen = set()
    cur = father_of.get(n)
    while cur is not None:
        if cur in seen:
            return True
        seen.add(cur)
        cur = father_of.get(cur)
    return False


def era_of(year: int) -> str:
    """年份 → 朝代名。"""
    name = ERA_STARTS[0][0]
    for nm, start in ERA_STARTS:
        if year >= start:
            name = nm
        else:
            break
    return name


def era_segments(y0: float, y1: float) -> List[Tuple[str, int, int]]:
    """视口年份区间 → [(朝代名, 起年, 止年)]（含端点，按时间升序）。

    用于左侧朝代色带；视口跨越多个朝代时自动分段。
    """
    lo, hi = int(math.floor(y0)), int(math.ceil(y1))
    if hi < lo:
        return []
    out: List[Tuple[str, int, int]] = []
    for i, (nm, start) in enumerate(ERA_STARTS):
        nxt = ERA_STARTS[i + 1][1] - 1 if i + 1 < len(ERA_STARTS) else hi
        seg_lo, seg_hi = max(start, lo), min(nxt, hi)
        if seg_lo <= seg_hi:
            out.append((nm, seg_lo, seg_hi))
    return out


def year_bounds(years: Sequence[int], now: Optional[int] = None) -> Tuple[int, int]:
    """视口年份范围（时间轴纵轴 + 顶部全览缩略轴都用它）。

    **起点要动态扩** —— 使用者定的起点是前 2500，但上古档最老的人在前 2580，
    写死前 2500 会把他切在画布外。

    **终点按本档实际走到哪年**（★ 2026-09-21 改）——
    原来终点写死 `YEAR_END_DEFAULT = 1000`，于是春秋开局的全览轴也一路画到隋唐，
    使用者原话：「时代全览中的时代也是变动的，比如春秋开局，他只能反应春秋开局
    当年及之前的时代，而后的战国秦汉则不存在」。现在：
      · `now`（存档当前年份，`saveload.game_year` 取）优先；
      · 取不到就用**最晚生年**兜底；
      · 两者都没有才退回默认终点。
    另留 `ERA_TAIL_MARGIN` 年余量，免得最后那几年被切在轴外。
    """
    lo = YEAR_START_DEFAULT
    if years:
        lo = min(lo, min(years) - 20)
    base = now if now is not None else (max(years) if years else None)
    if base is None:
        return lo, YEAR_END_DEFAULT
    hi = base + ERA_TAIL_MARGIN
    if years:
        # 生年比「现在」晚一点是可能的（当年出生 / 遗腹子），
        # 但脏数据（实测有 `-24301001` 这种拼接值）不能把画布撑开，所以封顶。
        hi = max(hi, min(max(years) + ERA_TAIL_MARGIN, base + 120))
    return lo, max(hi, lo + 50)


# ==================================================================== 比例尺

def pick_scale(viewport_h: float, min_gap_years: int = MIN_FERTILE_GAP,
               card_h: float = CARD_H) -> float:
    """几何下限：父子卡片不挤。14 年 × 比例 ≥ 卡片 + 间隙。"""
    need = (card_h + card_h) / max(min_gap_years, 1)
    return max(SCALE_MIN, min(SCALE_MAX, need))


def initial_scale(span_years: int, viewport_h: float) -> float:
    """初始比例：优先「一屏看完」；一屏装不下就用默认值。

    ⚠️ 装不下时**不要**硬压到 SCALE_MIN —— 实测秦末档跨 2370 年，压到 2.43 会连人都看不清，
    而且横向反而更宽（子树咬合变差，26352px vs 19658px）。默认 5 px/年，该滚就滚。
    """
    if span_years <= 0 or viewport_h <= 0:
        return SCALE_DEFAULT
    fit = viewport_h / span_years
    if fit >= SCALE_MIN:
        return max(SCALE_MIN, min(SCALE_DEFAULT, fit))
    return SCALE_DEFAULT


def clamp_scale(s: float) -> float:
    return max(SCALE_MIN, min(SCALE_MAX, s))


def card_width(name: str) -> float:
    """估计横排卡片的宽度（视图会用真实字体量一遍再传进来）。

    纯计算层不碰 Tkinter，所以按基准字号一个全角字 ≈ 21px 估；
    超过 `CARD_W_MAX` 就说明会触发弹性降级，这里直接返回上限。
    """
    return max(CARD_W_MIN, min(CARD_W_MAX, CHAR_W_EST * len(name) + CARD_PAD_X))


# ==================================================================== 空间网格

class _Grid:
    """按 x / y 分桶，给连线避让做碰撞检测用。

    3233 人下朴素两两比对是 O(n²)，会拖到几十秒；分桶后每次查询只碰几个桶。
    `card_h` 跟着铭牌样式走（横排 17 / 竖排 54），判定一律用它，不能写死。
    """

    XCELL = 64          # > 最大卡片宽

    def __init__(self, boxes: Sequence[Tuple[float, float, float]],
                 card_h: float = CARD_H):
        self.ch = card_h
        self.YCELL = card_h
        self.by_x = defaultdict(list)
        self.by_y = defaultdict(list)
        for (cx, cy, w) in boxes:
            self.by_x[int(cx // self.XCELL)].append((cx, cy, w))
            self.by_y[int(cy // self.YCELL)].append((cx, cy, w))

    def hit_v(self, x: float, ya: float, yb: float, skip=()) -> bool:
        """竖线 x、y∈[ya,yb] 是否穿过某张卡。**ya/yb 谁大谁小都行**。"""
        return bool(self.blockers_v(x, ya, yb, skip))

    def blockers_v(self, x: float, ya: float, yb: float, skip=()) -> List[Tuple[float, float]]:
        """竖线 x、y∈[ya,yb] 挡路的卡：(卡上沿 y, 卡下沿 y)，按 y 升序。

        `skip` 是 (x, y) 集合（起终点那两张卡），跳过它们 —— 走 `skip` 而不是每次
        重新过滤一遍全部卡片，是 3233 人档里 2957 条连线能算得动的关键。
        """
        if ya > yb:                      # 生年倒挂的连线是反着传的，这里统一一下
            ya, yb = yb, ya
        ch = self.ch
        out = []
        for b in {int(x // self.XCELL), int((x + 1) // self.XCELL),
                  int((x - 1) // self.XCELL)}:
            for (cx, cy, w) in self.by_x.get(b, ()):
                if skip and (cx, cy) in skip:
                    continue
                if abs(x - cx) < w / 2 and ya < cy + ch and yb > cy:
                    out.append((cy, cy + ch))
        out.sort()
        return out

    def hit_h(self, y: float, xa: float, xb: float, skip=()) -> bool:
        """横线 y、x∈[xa,xb] 是否**穿过**某张卡。

        上下边界用严格不等号：沿着卡片边缘走不算穿卡 —— 否则「绕到子卡上沿再进来」
        这种走法会被自己的终点卡挡住（实测 `子南弥牟 → 子南固` 就是这个）。
        """
        lo, hi = (xa, xb) if xa <= xb else (xb, xa)
        ch = self.ch
        for b in (int(y // ch), int((y - ch + 1) // ch)):
            for (cx, cy, w) in self.by_y.get(b, ()):
                if skip and (cx, cy) in skip:
                    continue
                if cy < y < cy + ch and lo < cx + w / 2 and hi > cx - w / 2:
                    return True
        return False


# ==================================================================== 布局结果

@dataclass
class Layout:
    scale: float = SCALE_DEFAULT
    year0: int = YEAR_START_DEFAULT                    # 画布最顶端对应的年份
    card_h: float = CARD_H                             # 铭牌高度（横排 17 / 竖排 54）
    positions: Dict[str, Tuple[float, float]] = field(default_factory=dict)
    years: Dict[str, int] = field(default_factory=dict)
    widths: Dict[str, float] = field(default_factory=dict)
    # 连线的**端点**是急件算出来的；**路径**是惰性的（见 path_for）。
    # 3233 人的档里把 2957 条全算一遍要 480ms，而一屏只看得到两三百条 ——
    # 所以只算看得见的那些，其余等真要画了再算。
    link_pairs: List[Tuple[str, str, float, float, float, float]] = field(default_factory=list)
    width: float = 0.0
    height: float = 0.0
    unplaced: List[str] = field(default_factory=list)  # 没有生年、进不了时间轴的人
    shift_count: int = 0                               # 为了不撞而右移的子树数
    _paths: Dict[str, Tuple[List[Tuple[float, float]], str]] = field(default_factory=dict)
    _grid: Optional[_Grid] = None
    _pair_of: Dict[str, Tuple[str, str, float, float, float, float]] = field(default_factory=dict)
    _bus: Dict[str, Optional[float]] = field(default_factory=dict)
    _kinds: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    # ★ 2026-09-22 母亲连线：attach_mother = 挂在母亲枝下的子（无父，主线即母线，
    #   画虚线）；_mother_pair_of = 父母都在时「母亲 → 子」的额外虚线（母线 keyed by 子）。
    attach_mother: set = field(default_factory=set)
    mother_extra: List[Tuple[str, str]] = field(default_factory=list)
    _mother_pair_of: Dict[str, Tuple[str, str, float, float, float, float]] = field(default_factory=dict)

    # ---- 惰性路由 ----
    def _ensure_grid(self) -> _Grid:
        if self._grid is None:
            self._grid = _Grid([(self.positions[n][0], self.positions[n][1], self.widths[n])
                                for n in self.positions], self.card_h)
        return self._grid

    def path_for(self, child: str) -> Tuple[List[Tuple[float, float]], str]:
        """某条父子连线的折线（带缓存）。线的两端卡在判定里会被跳过。"""
        hit = self._paths.get(child)
        if hit is not None:
            return hit
        pair = self._pair_of.get(child)
        if pair is None:
            return [], ""
        f, n, x1, y1, x2, y2 = pair
        skip = (self.positions[f], self.positions[n])
        pts, kind = _route(x1, y1, x2, y2, self._ensure_grid(), self._bus.get(n), skip)
        self._paths[child] = (pts, kind)
        self._kinds[kind] += 1
        return self._paths[child]

    def path_for_mother(self, child: str) -> Tuple[List[Tuple[float, float]], str]:
        """「母亲 → 子」额外虚线的折线（父母都在时才有；带缓存，key 加 m: 前缀）。

        ★ 2026-09-22 使用者要求：母亲连线也做 —— 与族谱同款语义
        （族谱里母线本就是虚线、婚姻色）。
        """
        key = "m:" + str(child)
        hit = self._paths.get(key)
        if hit is not None:
            return hit
        pair = self._mother_pair_of.get(str(child))
        if pair is None:
            return [], ""
        m, n, x1, y1, x2, y2 = pair
        skip = (self.positions[m], self.positions[n])
        pts, kind = _route(x1, y1, x2, y2, self._ensure_grid(), None, skip)
        self._paths[key] = (pts, kind)
        self._kinds[kind] += 1
        return self._paths[key]

    def route_all(self):
        """把全部连线都算出来（自检、快照、导出图片用）。"""
        for (_, n, _, _, _, _) in self.link_pairs:
            self.path_for(n)

    @property
    def links(self) -> List[Tuple[str, str, List[Tuple[float, float]]]]:
        """全部连线（会触发全量路由）。"""
        self.route_all()
        return [(f, n, self._paths[n][0]) for (f, n, _, _, _, _) in self.link_pairs]

    @property
    def links_same_x(self) -> int:
        return self._kinds["v"]

    @property
    def links_folded(self) -> int:
        return self._kinds["fold"]

    @property
    def links_channel(self) -> int:
        return self._kinds["channel"]

    @property
    def links_short(self) -> int:
        return self._kinds["short"]

    @property
    def links_diagonal(self) -> int:
        return self._kinds["diagonal"]

    def year_at(self, y: float) -> float:
        return self.year0 + y / self.scale

    def y_of(self, year: float) -> float:
        return (year - self.year0) * self.scale


# ==================================================================== 主流程

def compute(people, scale: float = SCALE_DEFAULT,
            width_of: Callable[[str], float] = card_width,
            sib_gap: float = SIB_GAP, card_h: float = CARD_H) -> Layout:
    """算时间轴布局。people 为 {姓名: 人物 dict}，与 model 的字段一致。

    `card_h` 跟着铭牌样式走（横排 17 / 竖排 54）—— 卡片高度决定了同列最小间距，
    所以它必须参与布局，不能只在绘制时改。
    """
    scale = clamp_scale(scale)
    lay = Layout(scale=scale, card_h=card_h)

    years: Dict[str, int] = {}
    for name, info in people.items():
        b = birth_year(info)
        if b is None:
            lay.unplaced.append(name)
        else:
            years[name] = b
    lay.years = years
    if not years:
        return lay

    lay.year0 = min(years.values()) - TOP_PAD_YEARS
    # ★ 2026-09-26 使用者实测「时间家谱铭牌明显比代际家谱矮胖」的真因：
    #   这里曾写 `max(CARD_W_MIN, width_of(n))` —— `CARD_W_MIN=34` 是**横排**的
    #   最小可读宽度，却把竖排的 20 顶成了 34（比代际树的 name_width=20 宽 70%）。
    #   宽度下限交给 `width_of` 自己（视图层的 `_card_w`：竖排 20 / 横排按名字量，
    #   纯计算层的默认 `card_width()` 内部已有 `CARD_W_MIN` 兜底），这里不再插手。
    lay.widths = {n: max(1.0, width_of(n)) for n in years}

    def ypx(n: str) -> float:
        return (years[n] - lay.year0) * scale

    # ---- 建树（只认都在时间轴上的人；成环的当根，见 _in_cycle）----
    # ★ 2026-09-22 使用者要求「母亲连线也做」：无父挂母（与族谱布局同一条规则，
    #   主线画虚线）；父母都在时子挂在父亲枝下、母亲另画一条虚线（族谱同款）。
    mother_of = {n: ((people.get(n) or {}).get("mother") or "") for n in years}
    parent_of = {}
    attach_mother = set()
    mother_extra: List[Tuple[str, str]] = []
    for n in years:
        f = ((people.get(n) or {}).get("father") or "")
        m = mother_of[n]
        f_in = f in years and f != n
        m_in = m in years and m != n
        if not f_in and m_in:
            parent_of[n] = m
            attach_mother.add(n)
        else:
            parent_of[n] = f
        if m_in and parent_of[n] != m:
            mother_extra.append((m, n))
    kids, roots = {}, []
    for n in years:
        p = parent_of[n]
        if p and p in years and p != n and not _in_cycle(n, parent_of):
            kids.setdefault(p, []).append(n)
        else:
            roots.append(n)
    for p in kids:
        kids[p].sort(key=lambda n: (years[n], n))
    roots.sort(key=lambda n: (years[n], n))
    lay.attach_mother = attach_mother
    lay.mother_extra = mother_extra

    # ---- 后序：子树宽度 + 父亲居中于孩子之上 + 轮廓避让 ----
    # 轮廓按 y 分桶存「该桶内最大右边缘」，查最小不撞偏移是 O(1)。
    def _right_in(prof: Dict[int, float], y: float) -> float:
        lo = int((y - card_h + 1) // card_h)
        hi = int((y + card_h - 1) // card_h)
        best = float("-inf")
        for b in range(lo, hi + 1):
            v = prof.get(b)
            if v is not None and v > best:
                best = v
        return best

    def place(node: str):
        """返回 (members, node_xc)。members = [(name, y, xc, w)]，局部坐标未归一。"""
        ks = kids.get(node)
        if not ks:
            return [(node, ypx(node), 0.0, lay.widths[node])], 0.0
        members: List[Tuple[str, float, float, float]] = []
        kid_xc: List[float] = []
        prof: Dict[int, float] = {}
        for k in ks:
            m, kx = place(k)
            off = 0.0
            for (_, y2, x2, w2) in m:
                need = _right_in(prof, y2) + sib_gap - (x2 - w2 / 2.0)
                if need > off:
                    off = need
            if off > 1e-6:
                lay.shift_count += 1
            for (nm2, y2, x2, w2) in m:
                members.append((nm2, y2, x2 + off, w2))
                b = int(y2 // card_h)
                r = x2 + off + w2 / 2.0
                if r > prof.get(b, float("-inf")):
                    prof[b] = r
            kid_xc.append(kx + off)
        node_xc = (kid_xc[0] + kid_xc[-1]) / 2.0      # ← 父亲居中于孩子之上
        yn, wn = ypx(node), lay.widths[node]
        # 正常情况下父亲的生年一定早于所有后代（游戏内至少差 14 年），居中不会撞。
        # 但存档里有个别父子只差一两年，这时居中会让父亲的卡压在后代上 —— 就近挪开。
        node_xc = _free_x(node_xc, yn, wn, members, card_h)
        members.append((node, yn, node_xc, wn))
        return members, node_xc

    allm: List[Tuple[str, float, float, float]] = []
    prof: Dict[int, float] = {}
    for r in roots:
        m, _ = place(r)
        off = 0.0
        for (_, y2, x2, w2) in m:
            need = _right_in(prof, y2) + sib_gap - (x2 - w2 / 2.0)
            if need > off:
                off = need
        if off > 1e-6:
            lay.shift_count += 1
        for (nm2, y2, x2, w2) in m:
            allm.append((nm2, y2, x2 + off, w2))
            b = int(y2 // card_h)
            r = x2 + off + w2 / 2.0
            if r > prof.get(b, float("-inf")):
                prof[b] = r

    min_left = min(x2 - w2 / 2.0 for (_, _, x2, w2) in allm)
    for (nm, y2, x2, w2) in allm:
        lay.positions[nm] = (x2 - min_left + LEFT_MARGIN, y2)

    lay.width = max(x2 - min_left + LEFT_MARGIN + w2 / 2.0 for (_, _, x2, w2) in allm) \
        + LEFT_MARGIN / 2
    lay.height = max(y for _, y in lay.positions.values()) + card_h + BOTTOM_MARGIN

    # ---- 连线的**端点**（急件）。**路径**留给 path_for 惰性算 ----
    _build_link_pairs(years, parent_of, lay)
    _build_mother_pairs(lay, lay.card_h)
    return lay


def _build_link_pairs(years: Dict[str, int], parent_of: Dict[str, str], lay: Layout):
    """只算连线的起止边，不算路径。

    为什么分开：3233 人的档里 2957 条连线全路由一遍要 480ms，而一屏只看得到两三百条。
    位置（这一步）只要 65ms，路由改成惰性之后缩放立刻跟手。
    ★ 2026-09-22：入参从 father_of 改为 parent_of（无父挂母），母线见
      `_build_mother_pairs`。
    """
    # 同父多子 → 阶梯式总线：横向段高度在「父卡下沿」与「最低那个子卡上沿」之间等分。
    # 只处理「子卡在父卡下方」的正常情形；生年倒挂的少数条用中点，不参与阶梯。
    ch = lay.card_h
    kids: Dict[str, List[str]] = defaultdict(list)
    for n in years:
        f = parent_of.get(n, "")
        if f not in years:
            continue
        fx, fy = lay.positions[f]
        cx, cy = lay.positions[n]
        if abs(fx - cx) > 1e-6 and cy >= fy + ch:
            kids[f].append(n)
    bus: Dict[str, float] = {}
    for f, ks in kids.items():
        lo = lay.positions[f][1] + ch + 6.0
        hi = min(lay.positions[k][1] for k in ks) - 6.0
        if hi <= lo:
            for k in ks:
                bus[k] = (lo + hi) / 2.0
            continue
        step = (hi - lo) / (len(ks) + 1)
        for i, k in enumerate(ks):
            bus[k] = lo + step * (i + 1)

    for n in sorted(years, key=lambda x: (years[x], x)):
        f = parent_of.get(n, "")
        if f not in years or f == n:
            continue
        fx, fy = lay.positions[f]
        cx, cy = lay.positions[n]
        # 起止边按「子卡在父卡哪一侧」定：正常连父下沿→子上沿；
        # **生年倒挂**的父子（子卡整张在父卡之上，实测秦末档 6 条）要连父上沿→子下沿，
        # 否则线是从两张卡中间穿出去的，路由全线失效、只剩直斜线。
        if cy + ch <= fy:
            x1, y1, x2, y2 = fx, fy, cx, cy + ch
        else:
            x1, y1, x2, y2 = fx, fy + ch, cx, cy
        pair = (f, n, x1, y1, x2, y2)
        lay.link_pairs.append(pair)
        lay._pair_of[n] = pair
        lay._bus[n] = bus.get(n)
        # 退化情形：两张卡紧挨着（横缝 ≤3px 且纵向重叠）。这条「连线」就是相邻两卡之间
        # 的一小段，画最短的直线即可 —— 它本来也不可能绕，不算遮挡缺陷。
        gap = abs(cx - fx) - (lay.widths[f] + lay.widths[n]) / 2.0
        if gap <= 3.0 and abs(cy - fy) < ch:
            lay._paths[n] = ([(x1, y1), (x2, y2)], "short")
            lay._kinds["short"] += 1


def _build_mother_pairs(lay: Layout, ch: float):
    """「母亲 → 子」额外虚线的端点（父母都在时才有；挂在母亲枝下的那条就是
    主线，不重复画）。起止边规则与父线相同（生年倒挂连上沿）。"""
    for (m, n) in getattr(lay, "mother_extra", []):
        if m not in lay.positions or n not in lay.positions:
            continue
        mx, my = lay.positions[m]
        cx, cy = lay.positions[n]
        if cy + ch <= my:
            x1, y1, x2, y2 = mx, my, cx, cy + ch
        else:
            x1, y1, x2, y2 = mx, my + ch, cx, cy
        lay._mother_pair_of[n] = (m, n, x1, y1, x2, y2)


def _free_x(xc: float, y: float, w: float, members, card_h: float = CARD_H,
            step: float = 9.0, limit: int = 80) -> float:
    """给一张卡找一个不与 members 相撞的 x，从 xc 开始向左右就近找。

    只在一处会用到：**个别父子的生年几乎同年**（游戏内一般 ≥14 年，存档里却有条目
    父子只差一两年）。这时「父亲居中于孩子之上」会让父亲的卡正好压在后代的卡上，
    只能就近挪开，牺牲一点居中。
    """
    def clashes(x):
        for (_, y2, x2, w2) in members:
            if abs(y - y2) < card_h and abs(x - x2) < (w + w2) / 2.0:
                return True
        return False

    if not clashes(xc):
        return xc
    for k in range(1, limit + 1):
        if not clashes(xc + k * step):
            return xc + k * step
        if not clashes(xc - k * step):
            return xc - k * step
    return xc


def _levels(lo: float, hi: float, my: Optional[float]) -> List[float]:
    """「下—横—下」的横向段候选高度：先贴一端、再贴另一端、最后中点。

    同父多子的 `my`（阶梯式总线）优先 —— 那样多个兄弟的横向段不会挤在一个高度。
    """
    out: List[float] = []
    if my is not None and lo < my < hi:
        out.append(my)
    span = hi - lo
    if span > 1.0:
        out += [lo + span * k / 15.0 for k in range(1, 15)]
        out += [hi - span * k / 15.0 for k in range(1, 15)]
    out.append((lo + hi) / 2.0)
    return out


def _route(x1: float, y1: float, x2: float, y2: float, grid: _Grid,
           my: Optional[float] = None, skip=()) -> Tuple[List[Tuple[float, float]], str]:
    """返回 (折线顶点列表, 类型)。

    y1 = 起点卡的那条边，y2 = 终点卡的那条边。**两者谁大谁小都行** ——
    生年倒挂的父子就是 y2 < y1（线要往上走），所以下面一律先取 lo/hi 再按方向走。

    `skip` = 起终点两张卡的 (x, y)，判定时跳过它们（否则线会「挡在」自己端点卡上）。

    依次尝试：
      v        同 x 且一路无阻挡 → 一条竖线
      fold     「下—横—下」三段折，横向段高度在 lo~hi 之间扫
      channel  S 形：从列间通道绕过去（同列被挡时也用它横向让开）
      astar    局部稀疏网格寻路（只要存在不穿卡的路径就找得到）
      diagonal 理论上到不了；真到了记为缺陷，自检会报出来
    """
    same_x = abs(x1 - x2) < 1e-6
    lo, hi = (y1, y2) if y1 <= y2 else (y2, y1)

    if same_x and not grid.hit_v(x1, lo, hi, skip):
        return [(x1, y1), (x1, y2)], "v"

    if not same_x:
        for lv in _levels(lo, hi, my):
            if grid.hit_v(x1, y1, lv, skip) or grid.hit_h(lv, x1, x2, skip) \
                    or grid.hit_v(x2, lv, y2, skip):
                continue
            return [(x1, y1), (x1, lv), (x2, lv), (x2, y2)], "fold"

    # S 形。同列被挡时 x2 == x1，横向让开再绕回来，所以偏移要正负都试。
    # 这里只试**近处**的通道与让位量：能把绝大多数连线的代价压到几十次判定以内。
    # 远处通道不在这里穷举 —— 穷举一次要几千次判定，而真正难缠的交给下面的 A* 更划算。
    fwd = 1.0 if same_x or x2 > x1 else -1.0
    step = -1.0 if y2 < y1 else 1.0          # 沿行进方向往前让
    offsets = [fwd * CHANNEL * f for f in NEAR_CHANNEL_MAGS] + \
              [-fwd * CHANNEL * f for f in NEAR_CHANNEL_MAGS]
    for off in offsets:
        xc = x1 + off
        for a_off in NEAR_LEVEL_OFFSETS:
            for b_off in NEAR_LEVEL_OFFSETS:
                ya, yb = y1 + step * a_off, y2 - step * b_off
                if (yb - ya) * step <= 0:
                    continue
                if grid.hit_v(x1, y1, ya, skip) or grid.hit_h(ya, x1, xc, skip) \
                        or grid.hit_v(xc, ya, yb, skip) or grid.hit_h(yb, xc, x2, skip) \
                        or grid.hit_v(x2, yb, y2, skip):
                    continue
                return ([(x1, y1), (x1, ya), (xc, ya), (xc, yb), (x2, yb), (x2, y2)],
                        "channel")

    if same_x:
        # 同列的竖线被中间某张卡挡住了 → 在挡路卡旁边做一次「小让位」（凸起再回来）
        pts = _bump_around(x1, lo, hi, grid, skip)
        if pts:
            return (pts if y1 <= y2 else list(reversed(pts))), "channel"

    # 兜底：局部 A* 寻路。**「连线不能从卡上压过去」是硬要求**，
    # 所以这里宁可贵一点，也不能退回直斜线（直斜线正是「连线被卡片遮挡」的来源）。
    pts = _route_astar(x1, y1, x2, y2, grid, skip=skip)
    if pts:
        return pts, "channel"

    # 理论上到不了这里；真到了就画直斜线并计入 links_diagonal，自检会把它当缺陷报出来
    return [(x1, y1), (x2, y2)], "diagonal"


def _thin(vals: List[float], min_sep: float, keep: Tuple[float, ...]) -> List[float]:
    """把挨得太近的候选通道线合并掉，控制网格规模（密集区里卡片边缘会挤成一堆）。

    `keep` 里的值（起点/终点的坐标）必须原样保留，否则起终点会不在网格上。
    """
    out: List[float] = []
    for v in sorted(vals):
        if v in keep:
            out.append(v)
        elif not out or v - out[-1] >= min_sep:
            out.append(v)
        elif v - out[-1] < min_sep:
            out[-1] = (out[-1] + v) / 2.0
    return sorted(set(out) | set(keep))


def _route_astar(x1: float, y1: float, x2: float, y2: float, grid: _Grid,
                 pad: float = 3.0, span: float = CHANNEL * 6,
                 skip=()) -> Optional[List[Tuple[float, float]]]:
    """局部稀疏网格上的正交寻路（兜底）。

    折线与通道都是「先定横向段高度、再找列间通道」的固定套路，密集区里两者都撞墙时就没招了。
    这里换成真正的寻路：把候选通道线取成「每张卡的左右边缘外 3px」和「上下边缘外 3px」，
    在这些线上跑 A*，**只要存在一条不穿卡的正交路径就一定能找到**。

    只在固定套路失败时才调用（实测占比 < 1%）。**必须便宜** —— 一屏两三百条连线里
    哪怕只有几十条走这里，单次几十毫秒也会让缩放明显卡顿，所以下面把网格与访问量都卡得很紧。

    注：竖排铭牌（卡高 54）下失败率明显更高，但**放大窗口没用**（实测把 span 与预算
    按卡高放大 2.5 倍，结果一模一样）—— 那是因为**确实不存在**不穿卡的通路：
    卡片一高，"水平的空白巷道"就几乎没有了。这是几何必然，不是参数问题。
    """
    xlo, xhi = (x1, x2) if x1 <= x2 else (x2, x1)
    ylo, yhi = (y1, y2) if y1 <= y2 else (y2, y1)
    boxes = []
    for b in grid.by_x.values():
        for (cx, cy, w) in b:
            if skip and (cx, cy) in skip:
                continue
            if xlo - span <= cx <= xhi + span and ylo - 60 <= cy <= yhi + 60:
                boxes.append((cx, cy, w))
    ch = grid.ch
    if len(boxes) > 1500:                    # 窗口太乱，寻路也不划算
        return None

    xs: List[float] = [x1, x2]
    ys: List[float] = [y1, y2]
    for (cx, cy, w) in boxes:
        if ylo < cy + ch and yhi > cy:       # 只关心夹在父子之间的卡
            xs.append(cx - w / 2.0 - pad)
            xs.append(cx + w / 2.0 + pad)
        ys.append(cy - pad)
        ys.append(cy + ch + pad)
    raw_x = [v for v in xs if xlo - span <= v <= xhi + span]
    raw_y = [v for v in ys if ylo - 1e-6 <= v <= yhi + 1e-6]
    # 候选线太多就逐步「粗化」：间距小于 6px 的通道本来就窄得不能用，
    # 密集区里卡片边缘会挤成上万条候选，不粗化的话光建网格就要几十毫秒。
    xs, ys = [], []
    for sep in (6.0, 14.0, 26.0, 45.0, 80.0):
        xs = _thin(raw_x, sep, (x1, x2))
        ys = _thin(raw_y, sep, (y1, y2))
        if len(xs) * len(ys) <= 16000:
            break
    if not xs or not ys:
        return None
    xi = {v: i for i, v in enumerate(xs)}
    yi = {v: i for i, v in enumerate(ys)}
    if x1 not in xi or x2 not in xi or y1 not in yi or y2 not in yi:
        return None

    start = (xi[x1], yi[y1])
    goal = (xi[x2], yi[y2])
    n_x, n_y = len(xs), len(ys)

    def clear_v(i, j):        # (xs[i], ys[j]) → (xs[i], ys[j+1])
        return not grid.hit_v(xs[i], ys[j], ys[j + 1], skip)

    def clear_h(i, j):        # (xs[i], ys[j]) → (xs[i+1], ys[j])
        return not grid.hit_h(ys[j], xs[i], xs[i + 1], skip)

    def heur(i, j):
        return (abs(xs[i] - x2) + abs(ys[j] - y2))

    import heapq
    INF = float("inf")
    dist = {start: 0.0}
    prev = {}
    pq = [(heur(*start), 0.0, start)]
    seen = set()
    budget = 8000                        # 访问上限：超了就放弃（宁可退回直斜线也别卡住）
    while pq and budget > 0:
        budget -= 1
        _, g, cur = heapq.heappop(pq)
        if cur in seen:
            continue
        seen.add(cur)
        if cur == goal:
            break
        i, j = cur
        moves = []
        if j + 1 < n_y and clear_v(i, j):
            moves.append(((i, j + 1), ys[j + 1] - ys[j]))
        if j - 1 >= 0 and clear_v(i, j - 1):
            moves.append(((i, j - 1), ys[j] - ys[j - 1]))
        if i + 1 < n_x and clear_h(i, j):
            moves.append(((i + 1, j), xs[i + 1] - xs[i]))
        if i - 1 >= 0 and clear_h(i - 1, j):
            moves.append(((i - 1, j), xs[i] - xs[i - 1]))
        for nxt, cost in moves:
            ng = g + cost
            if ng < dist.get(nxt, INF):
                dist[nxt] = ng
                prev[nxt] = cur
                heapq.heappush(pq, (ng + heur(*nxt), ng, nxt))
    if goal not in dist:
        return None

    path = [goal]
    while path[-1] != start:
        path.append(prev[path[-1]])
    path.reverse()
    pts = [(xs[i], ys[j]) for (i, j) in path]
    # 合并同向的相邻段，避免出现一串无意义的折点
    out = [pts[0]]
    for p in pts[1:]:
        if len(out) >= 2:
            (ax, ay), (bx, by) = out[-2], out[-1]
            if (ax == bx == p[0]) or (ay == by == p[1]):
                out[-1] = p
                continue
        out.append(p)
    return out


def _bump_around(x: float, y1: float, y2: float, grid: _Grid, skip=(),
                 max_bumps: int = 3) -> Optional[List[Tuple[float, float]]]:
    """同列竖线绕开挡路的卡：在每张挡路卡旁边横向凸出再回来。

    挡路卡旁边有没有缝，是**搜出来的**而不是猜的 —— 子树之间是 12px 咬合排布的，
    固定偏移量（比如固定往右 35px）十有八九正撞在邻列的卡上。

    返回 None 表示让不开（调用方退回「压在卡上但画在卡片之下」的竖线）。
    """
    pts: List[Tuple[float, float]] = [(x, y1)]
    cur = y1
    for (bt, bb) in grid.blockers_v(x, y1, y2, skip):
        if bb <= cur:                       # 上一段已经绕过去了
            continue
        if len(pts) // 4 >= max_bumps:
            return None
        done = False
        for step in range(1, 26):          # 由近及远找缝（最远 ±200px）
            for sgn in (1.0, -1.0):
                xc = x + sgn * step * 8.0
                for up in NEAR_LEVEL_OFFSETS:
                    for dn in NEAR_LEVEL_OFFSETS:
                        ya = max(cur, bt - up)
                        yb = min(bb + dn, y2)
                        if ya >= yb:
                            continue
                        # 只查「绕这一张卡」这四条线段；**不要**顺手查 (cur→y2)，
                        # 因为后面还有挡路卡，那一查必然失败（实测 蒙武 → 蒙毅 就死在这）。
                        if grid.hit_v(x, cur, ya, skip) or grid.hit_h(ya, x, xc, skip) \
                                or grid.hit_v(xc, ya, yb, skip) \
                                or grid.hit_h(yb, xc, x, skip):
                            continue
                        pts += [(x, ya), (xc, ya), (xc, yb), (x, yb)]
                        cur, done = yb, True
                        break
                    if done:
                        break
                if done:
                    break
            if done:
                break
        if not done:
            return None
    if grid.hit_v(x, cur, y2, skip):        # 尾部校验：剩下的这段也得干净
        return None
    pts.append((x, y2))
    return pts


# ==================================================================== 自检

def self_check(lay: Layout) -> Dict[str, int]:
    """程序化自检 —— **不能靠眼看**。

    效果图第一版的「连线穿过风雷方那张卡」就是肉眼在缩略图上完全看不出来、
    被这段检查抓出来的。指标：

      card_hits    卡片相交对数（必须 0）
      link_hits    折线（非 diagonal）穿卡处数（必须 0）
      diagonal     避让不开、退回直斜线的连线数。**不算缺陷** —— v1 就是直斜线，
                   且连线一律画在卡片之下，压到卡只是被挡住。作为回归指标看着就行。
    """
    names = list(lay.positions)
    boxes = [(lay.positions[n][0], lay.positions[n][1], lay.widths[n]) for n in names]
    grid = _Grid(boxes, lay.card_h)
    ch = lay.card_h

    card_hits = 0
    for i in range(len(boxes)):
        ax, ay, aw = boxes[i]
        for j in range(i + 1, len(boxes)):
            bx, by, bw = boxes[j]
            if abs(ax - bx) < (aw + bw) / 2 and not (
                    ay + ch <= by or by + ch <= ay):
                card_hits += 1

    link_hits = 0
    for f, n, pts in lay.links:
        if len(pts) == 2 and abs(pts[0][0] - pts[1][0]) > 1e-6:
            continue                                # 直斜线，按 v1 的规矩不查
        for (px, py), (qx, qy) in zip(pts, pts[1:]):
            if abs(px - qx) < 1e-6:
                if grid.hit_v(px, min(py, qy), max(py, qy)):
                    if not _owns(px, py, qy, lay, f) and not _owns(px, py, qy, lay, n):
                        link_hits += 1
            else:
                if grid.hit_h(py, px, qx) and not _owns_h(py, px, qx, lay, f) \
                        and not _owns_h(py, px, qx, lay, n):
                    link_hits += 1

    return {"card_hits": card_hits, "link_hits": link_hits,
            "diagonal": lay.links_diagonal}


def _owns(x, y_a, y_b, lay: Layout, card: str) -> bool:
    """竖线落在 card 这张卡的范围里 —— 那是它的起点/终点，不算穿卡。"""
    if card not in lay.positions:
        return False
    cx, cy = lay.positions[card]
    if abs(x - cx) >= lay.widths[card] / 2:
        return False
    lo, hi = min(y_a, y_b), max(y_a, y_b)
    return lo < cy + lay.card_h and hi > cy


def _owns_h(y, x_a, x_b, lay: Layout, card: str) -> bool:
    """横线落在 card 这张卡的范围里 —— 同上，起终点不算穿卡。

    实测 `王错 → 鬼谷子`：两张卡只差 2px，折线的横向段必然贴着子卡的上沿走，
    不豁免的话会被误判成「穿卡」。
    """
    if card not in lay.positions:
        return False
    cx, cy = lay.positions[card]
    if not (cy - 1e-6 <= y <= cy + lay.card_h + 1e-6):
        return False
    lo, hi = min(x_a, x_b), max(x_a, x_b)
    return lo < cx + lay.widths[card] / 2 and hi > cx - lay.widths[card] / 2
