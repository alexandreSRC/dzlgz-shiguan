# -*- coding: utf-8 -*-
"""人物档案 —— 把「一个人」的所有信息整理成固定顺序、可直接显示的样子。

## 这个模块解决什么

原来看人物是在表格里铺一堆列，字段顺序由存档决定，还混着一堆
「（原值 1）」这类调试信息。本模块把人物信息**收敛成一个固定字段序**：

    姓名 · 性别 · 智略 · 等级 · 生年 · 卒年 · 文化 · 性格 · 势力 · 世代 · 所在 · 编号

并且负责三件存档本身没直接给的事：

1. **卒年推算** —— 存档只有 `Ren_Chu_Sheng_Time`（生年）和 `Ren_End_Old`（享年），
   没有卒年字段。本模块用 `生年 + 享年` 算出来。时间格式是 `"-2517,1,0"`（年,月,日），
   公元前年份是负数 —— 注意：**公元前 2517 年 ＋ 享年 96** 得到的是公元前 2421 年，
   不是简单相加的绝对值（公元前年号越大越早，要**减**）。
2. **史实 / 非史实判定** —— 编号位数决定：**≤5 位数 = 史实人物**（游戏写死的），
   **9 位数（1XXXXXXXX 段）= 游戏随机生成**。史实人物优先展示。
3. **容貌隐藏** —— `Ren_Face` 是「身材=胖 / 胡子=LPxu-3」这种内部外观编号，
   游戏里根本看不到具体长相，所以**不显示**。

## 关注世系（始祖 + 后裔）

使用者给某个人封了爵位后，他和他的后裔就值得单独关注。
`lineage_of(code)` 从一个人出发，把**他 + 全部后裔**抽成一棵子图。
数据来源同 `relations.py`（父系链 + 族谱），这里只做「抽取 + 排序」。
"""
import re

try:
    from . import labels as L
except ImportError:                      # 直接跑脚本（非包内导入）时的兜底
    import labels as L

try:
    from . import names_map as NM
except ImportError:                      # 直接跑脚本（非包内导入）时的兜底
    import names_map as NM

# ---------------------------------------------------------------- 显示字段序
# 人物详情面板的字段顺序（使用者指定）
PROFILE_ORDER = (
    ("姓名", "name"),
    ("身份", "identity"),
    ("性别", "sex"),
    ("智略", "zhilue"),
    ("年龄", "age"),
    ("等级", "leve"),
    ("谥号", "shihao"),
    ("生年", "birth"),
    ("卒年", "death"),
    ("余寿", "yushou"),
    ("文化", "wenhua"),
    ("性格", "xingge"),
    ("势力", "shili"),
    ("世代", "daishu"),
    ("所在", "suozai"),
    ("编号", "code"),
)

# 表格列顺序（人物总表）—— 使用者要求：**表格里不列「所在」**（详情面板有），
# 也去掉「史实」列（史实/非史实已由表族本身分开）。
# ★ 2026-09-24 使用者要求：表头改成「…智略 年龄 等级 生年…」，并**删掉末尾的
#   「世代」「编号」**（那两列要横向滚动才看得到，砍掉后基本不必横滚）。
#   「年龄」是新增列（活人 = 本档当年 − 生年；已故者 = 享年），插在智略之后。
# ★ 2026-09-25 使用者要求：「人物界面做出 1 个标签，身份」—— 君主「主」、官员「官」、
#   有谥号的「谥」、**其余留空**（不写「民」，留白更干净）。插在姓名之后。
TABLE_COLS = ("姓名", "身份", "性别", "智略", "年龄", "等级", "生年", "卒年",
              "余寿", "文化", "性格", "势力")

# ★ 2026-09-25 使用者裁定（《全史存档》）：**跨 2500 年的合并谱不写年龄与余寿**。
#   原因：这两列的参照年是「本档走到哪一年」（`Profile.NOW_YEAR`），
#   一份由 32 个剧本档合并出来的谱没有单一参照年 —— 算出来必然是错的。
#   机制：谱牒 `source.hide_cols` 里点名要隐藏的列名，人物页据此少画这几列
#   （见 `views/person_view._hidden_cols`）。这里只提供纯函数，不碰界面。
def visible_table_cols(hidden=None):
    """TABLE_COLS 去掉 `hidden` 里点名的列。"""
    h = set(hidden or ())
    return tuple(c for c in TABLE_COLS if c not in h)

# 每个字段的「鼠标悬停解释」—— 显示在表头/详情label上，替代括号注释。
FIELD_HELP = {
    "姓名": "史书上或游戏里显示的名字。",
    "身份": "君主标「主」、官员标「官」、有谥号的标「谥」；其余留空（普通平民）。",
    "性别": "男女。女性等级走另一套码表（美佳淑丽良）。",
    "智略": "人物的智力/谋略数值，越大越强。",
    "年龄": "活了多少年（已故者按真实卒年算，即享年）。参照年是**本档走到哪一年**，"
            "与「余寿」同源；没有生年的人显示「—」。",
    "等级": "身份等级。男：庶下中上邦；女：美佳淑丽良；另有圣、神、将、臣、君、豪。",
    "谥号": "死后追称的字（如「庄襄」「怀」「孝」）。存档里只有少数人有，多为已故国君。",
    "生年": "出生年份，格式为「公元前年.月」，如 −1106.01。",
    "卒年": "死亡年份。存档里没有这个字段，本工具用「生年 + 享年」推算。",
    "余寿": "还剩多少年可活（享年 − 已活年数）。本档走到哪一年由存档决定；"
            "行底色随余寿渐变：越长寿越绿，越将尽越红。",
    "文化": "所属文化圈（河洛、岐山、江淮、法家、儒家等）。",
    "性格": "性格标签，一个字（仁、智、勇、贪等）。",
    "势力": "所属势力（家族或国）。",
    "世代": "族谱中的世代序号。**−1 表示始祖**（这一支最早的那位）。",
    "所在": "当前所在位置（家族宅院、客馆、门舍等）。",
    "编号": "游戏内部的人物编号（ID）。≤5 位数是史实人物，9 位数是随机生成。",
}

# 永远不显示的字段（看了也没用 / 游戏里看不到）
HIDDEN_FIELDS = {
    "Ren_Face",          # 容貌：内部外观编号，游戏里看不见
    "Face_Name", "Face_Str",
    "Ren_Face_Array",
}

# 「（原值 x）」这类调试后缀一律不显示
SHOW_RAW_SUFFIX = False


# ---------------------------------------------------------------- 编号分类
def code_digits(code):
    """编号的十进制位数。不是数字返回 0。"""
    try:
        return len(str(abs(int(str(code).strip()))))
    except (TypeError, ValueError):
        return 0


def is_historical(code) -> bool:
    """**史实人物**判定：编号 ≤ 5 位数，或**非纯数字编号**。

    实测（三个档一致）：
      · ≤5 位数 = 游戏写死的历史人物（徐福 162 / 姬重耳 2306 / 姜石年 60004）
      · 9 位数 `1XXXXXXXX` = 游戏随机生成的路人（100000013）
      · ★ 2026-09-25 使用者裁定：**字母编号**（`QIN001` 章蟜 / `WEI001` 公叔痤…）
        同样是游戏**写死的具名人物**（虽然取自电视剧里的杜撰角色），归**史实**。
        原来 `code_digits()` 对它们得 0，于是「≤5 位=史实」「9 位=随机」两条
        都套不上，全落进「非史」—— 《全史存档》里因此凭空多出 **10 个「非史人物」**
        （QIN001~007 / WEI001~003），这也是总谱上那「非史 10」的由来。
    空编号不算史实。

    ★ 2026-09-26 审查修复：编号以 **父/祖/曾/高** 结尾的是游戏硬造的占位祖先
      空壳（`100000202父`，tools 侧 `PLACEHOLDER_SUFFIX` 同判），**不是真人** ——
      七十四批「非纯数字归史实」没排除它们，于是这类空壳被判成史实：
      人物页史实计数虚高、「刷新体检」按史实豁免把它们批量补进谱
      （五十六批刚清掉的东西又回来了）。与 `tools.import_from_game.is_hist`
      的口径从此一致。
    """
    c = str(code or "").strip()
    if not c:
        return False
    if c[-1] in "父祖曾高":      # 占位祖先空壳（100000202父）—— 不是真人
        return False
    d = code_digits(c)
    if d == 0:              # 非纯数字（QIN001 / WEI001…）—— 具名人物，算史实
        return True
    return d <= 5


def is_generated(code) -> bool:
    """非史实（游戏随机生成）—— 只有**纯数字且 >5 位**才算。"""
    return code_digits(code) > 5


def kind_of(code) -> str:
    """→ 「史实」/「生成」/「未知」（空编号）。"""
    if not str(code or "").strip():
        return "未知"
    return "史实" if is_historical(code) else "生成"


# ---------------------------------------------------------------- 身份标签
def identity_of(rec) -> str:
    """身份标签：**主**（君主）/ **谥**（有谥号）/ **官**（有职位）/ ""（留空）。

    ★ 2026-09-25 使用者要求：「做出 1 个标签，身份 —— 君主的写主、官员的写官、
      其他的写民」，随后裁定「其他的**留空**更好」。
    判据全在本人记录里、不需联表（2026-09-25 实测本档 6670 条人物记录）：
      · **主** —— `Ren_Ji_Wei_Time` 继位时间非空：148 人，样本全是君主
        （陈胜、武臣、田儋、韩广、嬴子婴、熊心、挛鞮冒顿）；
      · **谥** —— `Ren_Zun_Hao` 谥号非空：187 人，样本全是国君
        （田法章、嬴异人、姬嵬、姬午、姜贷）；
      · **官** —— `Last_Ren_Official_Position_Data.职位编号 ≠ 0`：181 人，
        样本是官员将领（韩信、张良、陈平、季布、项伯）。
    优先级 **主 > 谥 > 官**（三者实测几乎不重叠：主∩谥 仅 2 人、主∩官 23、
    谥∩官 3 —— 怎么定影响都极小）。
    ⚠️ `职位编号 = 0` 的 1561 人**不是平民**（实测有等级，如叔孙通「中」），
       只是「有等级但未任具体职位」—— 按使用者裁定归入留空。

    ★ 抽成模块级函数（2026-09-25）：「谱牒总谱」的筛选计数要按**行**统计身份，
      不能为 13,526 人各造一个 `Profile` 对象。
    """
    rec = rec or {}
    if str(rec.get("Ren_Ji_Wei_Time") or "").strip():
        return "主"
    if str(rec.get("Ren_Zun_Hao") or "").strip():
        return "谥"
    pos = rec.get("Last_Ren_Official_Position_Data")
    if isinstance(pos, dict) and pos.get("Zhi_Wei_Code") not in (None, 0, "0"):
        return "官"
    return ""


# ---------------------------------------------------------------- 时间 & 卒年
# ★ 代码改进 A13（2026-09-22）：时间解析/格式化的唯一实现在 labels.py
#   （`_time_parts` / `fmt_year_month` / `humanize_time`），这里只留
#   calc_death 需要的薄封装 —— 此前两处各持一份，纯年份串行为还不一致。

def _parse_time(v):
    """`"-2517,1,0"` → `(年, 月)`；兼容纯年份 `"-2500"`。实现在 labels。"""
    p = L._time_parts(v)
    return None if p is None else (p[0], p[1])


def calc_death(birth, end_old):
    """卒年 = 生年 + 享年。

    ⚠️ 公元前年份是**负数**，直接相加即可：
       生年 -2517、享年 96 → -2517 + 96 = -2421 → 「公元前 2421 年」
    这正是游戏逻辑（越晚的年份在公元前段数值越大/越接近 0）。

    返回 (中文文本, 说明) ；算不出来返回 (None, 原因)。
    """
    bp = _parse_time(birth)
    if bp is None:
        return None, "无生年"
    try:
        old = int(end_old)
    except (TypeError, ValueError):
        return None, "无享年"
    if old <= 0:
        return None, "享年为 0"
    by, bm = bp
    if by == 0:
        return None, "生年为 0"
    dy = by + old
    if dy == 0:
        dy = 1 if by < 0 else 0        # 没有公元 0 年，错开一格
    text = L.fmt_year_month(dy, bm)
    return text, f"生年+享年 {old}"

def _raw_codes(v):
    """编号列表（逗号分隔串或真列表）→ int 列表；解析不出的跳过。"""
    if isinstance(v, str):
        items = [s.strip() for s in v.split(",") if s.strip()]
    else:
        items = list(v or [])
    out = []
    for it in items:
        try:
            out.append(int(str(it).strip()))
        except (TypeError, ValueError):
            continue
    return out


def _code_list(v, table, prefix):
    """编号列表（存档里是逗号分隔串，也兼容真列表）→ 中文名列表。

    查得到表的翻成中文，查不到兜底成「政策#7585」这类占位名（等截图补验）。
    """
    if isinstance(v, str):
        items = [s.strip() for s in v.split(",") if s.strip()]
    else:
        items = list(v or [])
    out = []
    for it in items:
        try:
            code = int(str(it).strip())
        except (TypeError, ValueError):
            continue
        out.append(table.get(code) or f"{prefix}#{code}")
    return out


# ---------------------------------------------------------------- 人物档案
class Profile:
    """一个人的可显示档案。字段顺序由 `PROFILE_ORDER` 固定。"""

    # ★ 2026-09-24 加：本档「现在走到哪一年」（公元前为负，`saveload.game_year`）。
    #   余寿 = 享年 −（当年 − 生年），所以整张表要有一个共同参照年。
    #   由 `record_derive.derive()` 在载入实录槽时设一次（类属性，全表共用）——
    #   放实例属性上会随 3500 次构造重复设，而且换槽时要挨个刷。
    NOW_YEAR = None

    __slots__ = ("code", "raw", "name", "sex", "zhilue", "leve", "birth",
                 "death", "death_note", "end_old", "tianshou",
                 "wenhua", "xingge", "shili",
                 "daishu", "suozai", "historical", "kind", "sources",
                 "zhengce", "nengli", "buff",
                 "zhengce_info", "nengli_info", "buff_info")

    def __init__(self, code, rec, xref=None, era="上古"):
        self.code = str(code)
        self.raw = rec or {}
        r = self.raw
        # ★ 2026-09-26 使用者实测「人物页总表卒年仍空」的真因：
        #   **谱牒层的人 (`family.json`) 把存档原文藏在 `extra` 里**
        #   （`{code, ..., extra: {Ren_End_Old: 78, Ren_Zhi_Lue: 100, ...}}`），
        #   而这里所有取值原来只读**顶层** —— 于是 `Ren_End_Old` 取不到、
        #   卒年推不出来（顶层只有真实卒年 `death`，姜榆罔那种才显示）。
        #   统一走 `gv()`：先顶层、再 extra，两者当同一张表用。
        ex = r.get("extra") or {}

        def gv(*keys):
            for k in keys:
                v = r.get(k)
                if v not in (None, ""):
                    return v
                v = ex.get(k)
                if v not in (None, ""):
                    return v
            return None

        self.name = r.get("Ren_Name") or r.get("name") or self._build_name(r)
        self.sex = gv("Ren_Sex")
        self.zhilue = gv("Ren_Zhi_Lue")
        self.leve = gv("Ren_Leve")
        # ★ 2026-09-25 加 `birth`/`death`/`state_name`/`generation` 回退：
        #   《全史存档》等合并谱的人物走「谱牒总谱」派生表进人物页时，
        #   行记录是 family.json 风格（birth/death/state_name/generation），
        #   不是存档原文风格（Ren_Chu_Sheng_Time/...）。实录行没有这些键，
        #   回退对它们零影响。
        self.birth = gv("Ren_Chu_Sheng_Time", "Born_Time", "birth")
        self.wenhua = gv("Ren_Wen_Hua")
        self.xingge = gv("Ren_Xing_Ge")
        self.shili = gv("Ren_Shi_Li_1", "Ren_Shi_Li", "state_name")
        self.daishu = gv("Ren_Dai_Shu", "Generations", "generation")

        # 卒年：**真实记录优先**，没有才用「生年 + 享年」推算
        # ★ 2026-09-26 使用者实证：「其他存档没死的也能记录卒年」——游戏对
        #   **在世**人物不写 `Ren_End_Time`，但写 `Ren_End_Old`（享年），
        #   单档人物页就是靠它推算出卒年的。所以判据改成：
        #     ① 有真实卒年（存档直接记录）→ 用它；
        #     ② 没有、但有享年 → 推算（在世者显示的就是这个"推算卒年"）；
        #     ③ 都没有 → 空。
        #   （原来「有享年就先推算」会把已故者的真实卒年盖掉，实测徐福
        #     真实 −208 / 推算 −185 会打架，故调换优先级。）
        direct = gv("Ren_End_Time", "Dead_Time", "death")
        end_old = gv("Ren_End_Old")
        self.end_old = end_old
        if direct:
            self.death = direct
            self.death_note = "存档直接记录"
        elif end_old not in (None, ""):
            self.death, self.death_note = calc_death(self.birth, end_old)
        else:
            self.death = None
            self.death_note = "无享年"

        # ★ 2026-09-26 新属性「天寿」= 享年（使用者要求：详情卡列于卒年之下、
        #   余寿之上，取代被裁掉的「（生年+享年 X）」括注）。三级来源：
        #   ① 存档原始享年 Ren_End_Old；② 推算卒年的注释「生年+享年 76」里
        #   的数；③ 都没有但生卒俱在 → 卒年 − 生年（公元前负数相减，与
        #   calc_death 同规）。
        self.tianshou = None
        if self.end_old not in (None, ""):
            try:
                self.tianshou = int(self.end_old)
            except (TypeError, ValueError):
                pass
        elif self.death_note and "享年" in str(self.death_note):
            try:
                self.tianshou = int(str(self.death_note).split("享年")[1].strip())
            except (ValueError, IndexError):
                pass
        if self.tianshou is None and self.death and self.birth:
            _dy = _parse_time(self.death)
            _bp = _parse_time(self.birth)
            if _dy and _bp:
                self.tianshou = max(0, _dy[0] - _bp[0])

        # 所在：优先地名，其次城编号补名
        self.suozai = self._resolve_suozai(r, xref)

        self.historical = is_historical(self.code)
        self.kind = kind_of(self.code)
        self.sources = [r.get("_source")] if r.get("_source") else []

        # 政策 / 能力 / 特质（编号 → 名字+类型+效果，唯一实现在 names_map.py）
        # ★ 2026-09-22：详情卡要展示**说明/效果**，条目为 (名字, (类型, 说明) | None)；
        #   zhengce/nengli/buff 三个纯名字列表保留给 rows()/表格等旧调用方。
        self.zhengce_info = [NM.zhengce_info(c) for c in _raw_codes(r.get("Ren_Zheng_Ce_Array"))]
        self.nengli_info = [NM.nengli_info(c) for c in _raw_codes(r.get("Ren_Neng_Li_Array"))]
        self.buff_info = [
            NM.buff_info(b.get("Buff_Name"), b.get("Neng_Li_Or_Zheng_Ce"))
            for b in (r.get("Buff_Array") or [])
            if isinstance(b, dict) and b.get("Buff_Name")
        ]
        self.zhengce = [n for n, _ in self.zhengce_info]
        self.nengli = [n for n, _ in self.nengli_info]
        self.buff = [n for n, _ in self.buff_info]

    # -- 内部 ---------------------------------------------------------
    @staticmethod
    def _build_name(r):
        shi = r.get("Ren_Shi") or r.get("Ren_Xing") or ""
        ming = r.get("Ren_Ming") or ""
        full = (shi + ming).strip()
        return full or None

    @staticmethod
    def _resolve_suozai(r, xref):
        """所在 → 中文。`Ren_In_Map_Position` 里有现成的汉语位置（「家族宅院家宅」），
        没有就退到城池编号补名字。"""
        pos = r.get("Ren_In_Map_Position")
        if isinstance(pos, dict):
            txt = pos.get("Ren_In_Map_Position")
            if txt:
                return L.strip_rich(str(txt))
        nm = r.get("Ren_Map_Name")
        if nm:
            return L.strip_rich(str(nm))
        c = r.get("Ren_Cheng_Shi_Code")
        if c not in (None, ""):
            if xref is not None:
                hit = xref.lookup("city", c)
                if hit:
                    return hit
            return f"城 {c}"
        return None

    # -- 输出 ---------------------------------------------------------
    @property
    def sex_label(self):
        """性别中文（「男」/「女」/「—」）。

        ★ 2026-09-22 加：`views/person_view._person_detail` 里一直写的是
          `p.sex_label`，但 `Profile` **从来没有这个属性** —— 于是每次点开人物卡
          都在这一行抛 `AttributeError`，卡片只剩标题和「来源」，
          下面的身份/关系全空（使用者报「人物信息卡为什么没有信息了」）。
          名字跟 `relations.Person.sex_label` 保持一致，两处语义相同。
        """
        return {0: "男", 1: "女"}.get(self.sex, "—")

    @property
    def yushou(self):
        """余寿 = 享年 −（本档当年 − 生年）。算不出来返回 None。

        ★ 2026-09-24 加（使用者要求：「根据剩余寿命，在人物界面用颜色或其他方式
          做个区分，比如还有 60 年寿命那么就绿得发亮」）。
          参照年 `NOW_YEAR` 是**本档走到哪一年**，见类属性说明。
          · 已故表里的人没有享年（只有直接的卒年）→ 算不出来，返回 None；
          · 享年为 0 / 无生年 / 还没载入存档 → None。
          负数 = 按寿命推算他已经该死了（存档没同步），照实显示。
        """
        now = Profile.NOW_YEAR
        if now is None:
            return None
        bp = _parse_time(self.birth)
        if bp is None or bp[0] == 0:
            return None
        try:
            # ★ 2026-09-26：改读 `self.end_old`（顶层或 extra，同一张表）
            old = int(self.end_old)
        except (TypeError, ValueError):
            return None
        if old <= 0:
            return None
        return old - (now - bp[0])

    @property
    def age(self):
        """年龄 = 活了多少年；没有生年返回 None。

        ★ 2026-09-24 使用者要求：人物表加一列「年龄」（插在智略之后）。
          与「余寿」共用同一个参照年（`NOW_YEAR` = 本档走到哪一年）：
          · **活人** —— 当年 − 生年（他现在多少岁）；
          · **已故者** —— 卒年 − 生年（＝享年）。必须用存档记录的真实卒年，
            否则会算出「他今天该多大」，那是错的。
          生年缺失 / 还没载入存档 → None（显示「—」，不猜）。
        """
        bp = _parse_time(self.birth)
        if bp is None or bp[0] == 0:
            return None
        ref = Profile.NOW_YEAR
        if self.death_note == "存档直接记录":        # 已故：改用真实卒年
            dp = _parse_time(self.death)
            if dp is not None and dp[0] != 0:
                ref = dp[0]
        if ref is None:
            return None
        years = ref - bp[0]
        return years if years >= 0 else None

    @property
    def shihao(self):
        """谥号（死后追称的字）。存档里只有少数人有 —— 多为已故国君。

        ★ 2026-09-25 使用者要求：「有谥号的人是死亡的君主，作用比较少但是
          写个谥字吧，他们的谥号写到人物卡里」。
        """
        return str(self.raw.get("Ren_Zun_Hao") or "").strip()

    @property
    def identity(self):
        """身份标签「主 / 谥 / 官 / 留空」—— 判据见模块级 `identity_of()`。"""
        return identity_of(self.raw)

    def value_of(self, key):
        """按 PROFILE_ORDER 的 key 取值（已中文化）。"""
        if key == "name":
            return self.name
        if key == "identity":
            return self.identity
        if key == "shihao":
            return self.shihao or "—"
        if key == "sex":
            return self.sex_label
        if key == "zhilue":
            # ★ 2026-09-25 修：原来直接把值返回 —— 存档里没有这个字段时
            #   （最典型：**已故表**根本没有 `Ren_Zhi_Lue`）会显示成字面
            #   「None」，在详情卡与表格里都很扎眼。缺值一律走「—」。
            return self.zhilue if self.zhilue is not None else "—"
        if key == "age":
            v = self.age
            return "—" if v is None else v
        if key == "leve":
            return L.leve_label(self.leve) or "—"
        if key == "birth":
            return L.humanize_time(self.birth) or "—"
        if key == "death":
            # death 有两种来路：算出的人类可读文本 / 存档里的原始时间串
            if not self.death:
                return "—"
            if self.death_note == "存档直接记录":
                return L.humanize_time(self.death) or "—"
            return self.death
        if key == "yushou":
            v = self.yushou
            return "—" if v is None else v
        if key == "wenhua":
            return self.wenhua or "—"
        if key == "xingge":
            return self.xingge or "—"
        if key == "shili":
            return self.shili or "—"
        if key == "daishu":
            # ⚠️ 世代 -1 就是**始祖**（这一支最早的那位）
            if self.daishu is None:
                return "—"
            if self.daishu == -1:
                return "始祖"
            return self.daishu
        if key == "suozai":
            return self.suozai or "—"
        if key == "code":
            return self.code
        return "—"

    def rows(self):
        """→ [(中文字段名, 显示值), ...]，顺序即 PROFILE_ORDER。

        ★ 2026-09-26：「天寿」（享年）紧随「卒年」插入 —— 使用者要求
          「放在余寿之上、卒年之下」。不进 PROFILE_ORDER（人物表格不加列）。
        """
        out = []
        for zh, k in PROFILE_ORDER:
            out.append((zh, self.value_of(k)))
            if zh == "卒年":
                out.append(("天寿",
                            "—" if self.tianshou is None else self.tianshou))
        return out

    def __repr__(self):
        return f"<Profile {self.code} {self.name}>"


# ---------------------------------------------------------------- 世系
class Lineage:
    """一个人的「世系」= 他 + 全部后裔（含女儿支）。

    `graph` 传 `relations.RelationGraph`。
    """

    def __init__(self, graph):
        self.g = graph

    def descendants(self, code, max_depth=200):
        """广度优先收集全部后裔。返回 [(depth, code), ...]（不含始祖本人）。

        ★ 代码改进 B3（2026-09-22）：帽从 12 提到 200 —— 世代替缨 68 代、
          上古谱系更深，12 代帽会把第 13 代以后的后裔漏出「关注世系」。
          seen 集合本就防环，取到穷尽也安全。
        """
        seen = {str(code)}
        out = []
        frontier = [str(code)]
        depth = 0
        while frontier and depth < max_depth:
            depth += 1
            nxt = []
            for c in frontier:
                for kid in self.g.children_of(c):
                    k = str(kid)
                    if k in seen:
                        continue
                    seen.add(k)
                    out.append((depth, k))
                    nxt.append(k)
            frontier = nxt
        return out

    def of(self, code):
        """→ {"始祖": Person, "成员": [(depth, Person), ...], "总数": n}"""
        root = self.g.people.get(str(code))
        desc = self.descendants(code)
        members = []
        for d, c in desc:
            p = self.g.people.get(c)
            if p is not None:
                members.append((d, p))
        return {"始祖": root, "成员": members, "总数": len(members) + (1 if root else 0)}
