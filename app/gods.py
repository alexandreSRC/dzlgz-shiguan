# -*- coding: utf-8 -*-
"""神明 · 神系 · 庙宇档案 —— 内置固定表的转录 + 存档反解码表 + 「神明总表」派生表。

为什么需要这个模块
============================================================
存档里与「神」有关的字段分两类：

  **① 国家层（每国一个）**
    · `Faith_Gods_Sys_Code`  信仰神祇系统编号（= 神系）
    · `Ji_Si_Gods`           祭祀神祇 —— 本国已造的「人造神」列表
    · `Is_Ji_Si_Tong_Zhi`    是否祭祀统治

  **② 神明本体（全世界一份，★ 2026-10-03 新发现）**
    `Save_Controller_Data.json` → `Gods_Arr` / `Gods_Sys_Arr`：**46 位神明**逐条带
    `Code`(sm0001) / `Name` / `Wei_Ge`(位格) / `Wei_Neng_Limit`(威能上限) /
    `Zu_Yu`(族域) / `Godhood_Code_Arr`(神格码 sg) / `Passive_Effect`(威能码 wn)；
    神系表 `Gods_Sys_Arr` 带 `Name` / `Gods_Pos_Limit` / `Gods_Pos_Arr`
    （每位神一行 `{Pos_Name: 主神/佐神/护法神/使神, Gods_Code: sm00xx}`）。

    ⚠️ 本模块旧版（2026-09-29）曾断言「神明名与效果**一个字都不在存档里**」——
      那是**基于旧档**（`Save_All_104` 只见到裸编号）得出的结论，**已被推翻**。
      现在神名 / 位阶 / 威能上限 / 神格码 / 威能码**全部来自存档**。

    ⚠️ 但 `sg` / `wn` **没有名字表**（全档扫过，只有编号被引用，没有定义）。
      它们的名字由「**TapTap 攻略 ↔ 存档**」交叉反解而来，见 `GODHOOD` / `WEI_NENG`。

资料来源（玩家实测 / 界面转录，**非官方文档**）
============================================================
① TapTap 攻略《关于非上古剧本神系清零流程及相关设定》
   作者 **念不勿**，2025-12-24 修订。
   提供：族域↔神系绑定、庙宇容量公式、造神触发条件、附庸继承规则。
② TapTap 攻略《**各族域初始神明的神格与威能**》
   作者 **永生人类**，09-24 修订。
   提供：五系 **46 位神**的位阶 / 神格 / **初始威能** / 全部威能（逐条效果原文）。
③ 本机存档 `Save_All_101` 的 `Save_Controller_Data.Gods_Arr`（神明本体，权威）。

反解方法与证据（`GODHOOD` / `WEI_NENG`）
============================================================
  · **神格 sg**：存档给每位神的 sg 码；攻略给每位神的神格名。
    先用**单码神**（`Godhood_Code_Arr` 只 1 个码）钉死 20 个码，
    多码神再用**集合差**收敛 ⇒ **27/27 个码全部定出，零冲突**。
  · **威能 wn**：存档给每位神的 `Passive_Effect`（码，有序）；攻略给每位神的
    **初始威能**名（有序）。逐位对齐投票 ⇒ 只有「跨神一致」的码才收录。
    结果 **33 码收录 / 1 码丢弃**（`wn0005` 出现 3 票「天命在上」与 1 票
    「神勇灌注」相争 —— 但「神勇灌注」已被 `wn0003` 独占 2 票，出格的是
    **烛龙那条记录本身**，故取 3 票的「天命在上」，并把烛龙标为存疑）。

⚠️ 两位作者均声明「官方逻辑改来改去、时效性不保证」。
   **与游戏内实际表现冲突时，一律以游戏为准。**
"""
from .saveload import Table, Src

# ============================================================ 一、神系
# 编号 → (名称, 基础神明数 B)。「名称」用**攻略 / 界面**的通行叫法；
# `save_name` 是存档 `Gods_Sys_Arr[].Name` 的原文（两者并不完全一致）。
#   B 的含义见「四、庙宇容量」；「中夏 / 皇天」的 11 已**超过**上限 10，
#   所以中夏国家无法额外造神（攻略原文）。
#
# 证据链（2026-09-29）：
#   ① 攻略给出的「族域 ↔ 神系」初始绑定表；
#   ② 本机存档实测 **125 国**的 (Ren_Zu_Yu, Faith_Gods_Sys_Code) 共 9 组，
#      与 ① **配对完全一致**（连「楚是中夏族域却用太一系」这个例外都对上）；
#   ③ `Gods_Sys_Arr[].Gods_Pos_Arr` 的长度与 B 完全吻合
#      （11 / 10 / 10 / 6 / 9 —— 见 `GOD_SYS` 的 base）。
GOD_SYS = {
    "皇天": {"code": 1, "base": 11, "zu_yu": ("中夏",),
             "save_name": "昊天神系"},
    "东皇太一": {"code": 2, "base": 10, "zu_yu": ("南蛮", "百濮"),
                 "save_name": "太一神系"},
    "帝俊": {"code": 3, "base": 10,
             "zu_yu": ("东夷", "百越", "辰韩", "扶余"),
             "save_name": "帝俊神系"},
    "烛龙": {"code": 4, "base": 6, "zu_yu": ("北狄", "匈奴"),
             "save_name": "烛龙神系"},
    "女娲肠": {"code": 5, "base": 9, "zu_yu": ("西戎", "西域", "象雄"),
               "save_name": "女娲神系"},
}

# 反向索引：编号 → 名称（给 `labels.py` 参考用，勿另抄一份）
GOD_SYS_BY_CODE = {v["code"]: k for k, v in GOD_SYS.items()}
# 反向索引：存档里的神系全名 → 通行叫法
GOD_SYS_BY_SAVE_NAME = {v["save_name"]: k for k, v in GOD_SYS.items()}

# 族域 → 初始神系（**会被地图情况重组**，见「六、继承规则」）
GOD_SYS_OF_ZU_YU = {}
for _name, _info in GOD_SYS.items():
    for _zy in _info["zu_yu"]:
        GOD_SYS_OF_ZU_YU[_zy] = _name


# ============================================================ 二、位阶与威能上限
# 神明由五部分组成：立绘 / 名称 / **位阶** / **神格** / **威能**。
#   · **威能** = 祭祀这位神获得的效果；**祭祀才有效**；
#   · **神格** = 决定这位神**能有哪些**威能（每位神一个到三个）；
#   · **位阶** 与「所拥有神格对应的全部威能」共同决定**威能上限**，两者**取最小值**。
#     （存档字段 `Wei_Neng_Limit` 就是这个上限，`Wei_Ge` 是「位格」。）
GOD_RANKS = ("主神", "佐神", "护法神", "使神")

# 位阶 → 威能上限（原文：主神 3；佐神 1~2；护法神 / 使神 1）
RANK_POWER_CAP = {"主神": 3, "佐神": 2, "护法神": 1, "使神": 1}

# 特例（攻略原文，2026-10-03 转录）：
#   · **皇天神系**：全是**单神格**，威能上限**不受位阶影响** ——
#     神格有多少威能就有多少（所以「后土 / 谷神 / 司中 / 司命」虽非主神也有 3 个威能）。
#   · **后尊的神明**（玩家造的人造神）：无论位阶，**只有一个神格、一个威能**。
#   · 奇观「**五畤原**」供奉的神：威能上限 **+1**，且位阶显示变「主神」
#     （**只是名称变化**，不会因此多出威能数量）。
HUANG_TIAN_NO_RANK_CAP = True
ZUN_GOD_CAP = 1
WU_ZHI_YUAN_BONUS = 1

# ⚠️ 「消除治下所有灾害」**不包括火灾**（火灾是后加的，无法靠祭祀消除）。
DISASTER_EXCEPTION = "火灾"
# 攻略里带 `*` 的神 = **初始威能少于全部威能**（存档 `Passive_Effect` 只记初始那批）。


# ============================================================ 三、反解码表
# 神格码 sg → 单字神格名（27 码全定，零冲突；方法与证据见模块头）。
GODHOOD = {
    "sg0001": "天", "sg0002": "地", "sg0003": "农", "sg0004": "序",
    "sg0005": "医", "sg0006": "风", "sg0007": "雨", "sg0008": "春",
    "sg0009": "夏", "sg0010": "秋", "sg0011": "冬", "sg0012": "生",
    "sg0013": "死", "sg0014": "水", "sg0016": "战", "sg0017": "日",
    "sg0018": "月", "sg0019": "山", "sg0020": "海", "sg0022": "牛",
    "sg0025": "龙", "sg0026": "蛇", "sg0033": "凤", "sg0034": "龟",
    "sg0035": "鹿", "sg0036": "财", "sg0037": "蚕",
}

# 威能码 wn → 威能名（33 码收录）。
WEI_NENG = {
    "wn0001": "疗愈病痛", "wn0002": "长生不老", "wn0003": "神勇灌注",
    "wn0004": "战神记忆", "wn0005": "天命在上", "wn0006": "持正守中",
    "wn0007": "秩序之神", "wn0008": "摒翳诸灾", "wn0009": "屏翳虫害",
    "wn0010": "屏翳地震", "wn0011": "屏翳旱灾", "wn0012": "屏翳风灾",
    "wn0013": "屏翳洪涝", "wn0014": "屏翳瘟疫", "wn0015": "屏翳杂草",
    "wn0016": "屏翳雪灾", "wn0017": "屏翳霜冻", "wn0019": "屏翳蝗灾",
    "wn0020": "屏翳冰雹", "wn0021": "屏翳鼠灾", "wn0022": "增贤启智",
    "wn0025": "远航之志", "wn0027": "生命之神", "wn0028": "农业之神",
    "wn0029": "滋育山林", "wn0031": "屏翳病害", "wn0032": "屏翳雀害",
    "wn0033": "降下瘟疫", "wn0035": "死亡之神", "wn0036": "降下旱灾",
    "wn0037": "滋育沼泽", "wn0039": "悠游岁月", "wn0040": "协助密谋",
}

# 威能名 → 效果原文（攻略 ② 逐条转录；祭祀后生效）。
WEI_NENG_EFFECT = {
    "天命在上": "我方天命 +1~10",
    "摒翳诸灾": "消除治下当年全部灾害，火灾除外",
    "持正守中": "我方正统 +3~10",
    "屏翳地震": "消除治下当年地震灾害",
    "屏翳冰雹": "消除治下当年冰雹灾害",
    "屏翳杂草": "消除治下当年杂草灾害",
    "屏翳病害": "消除治下当年病害灾害",
    "屏翳雀害": "消除治下当年雀害灾害",
    "屏翳虫害": "消除治下当年虫害灾害",
    "屏翳瘟疫": "消除治下当年瘟疫灾害",
    "屏翳鼠灾": "消除治下当年鼠灾灾害",
    "屏翳风灾": "消除治下当年风灾灾害",
    "屏翳旱灾": "消除治下当年旱灾灾害",
    "屏翳霜冻": "消除治下当年霜冻灾害",
    "屏翳蝗灾": "消除治下当年蝗灾灾害",
    "屏翳洪涝": "消除治下当年洪涝灾害",
    "屏翳雪灾": "消除治下当年雪灾灾害",
    "农业之神": "我方当年粮食产量 +1%~10%",
    "秩序之神": "我方稳定值 +3~10",
    "生命之神": "我方随机城邑百姓生育 +0.1%~0.5%",
    "疗愈病痛": "随机消除我方 1~3 名宗亲、朝臣、门客的全部疾病状态",
    "增贤启智": "我方随机宗亲成员智略 +1",
    "神勇灌注": "我方全军士气 +3~10",
    "战神记忆": "我方全军经验 +3~10",
    "长生不老": "10% 概率我方国君寿命 +1（女娲肠为 30%）",
    "降下瘟疫": "敌方随机 1 座城邑发生瘟疫灾害",
    "降下旱灾": "敌方随机 1 座城邑发生旱灾灾害",
    "死亡之神": "敌方随机城邑百姓生育 -0.1%~-0.5%",
    "滋育山林": "我方随机城邑山林比例 +1%~5%",
    "滋育沼泽": "我方随机 1 座城邑沼泽比例 +1%~5%",
    "悠游岁月": "我方当年随机城邑舒适 +10~30",
    "协助密谋": "我方全部谍网进度 +10",
    "远航之志": "我方当年海路行军速度 +5%~15%",
}

# ⚠️ 已知存疑：烛龙的 `Passive_Effect`（wn0022,wn0005,wn0001）与攻略给的
#   初始威能（增贤启智 / 神勇灌注 / 疗愈病痛）对不齐 —— 两头都被别的神
#   独立印证过，只有中间那条对不上。**照录存档，不替它改**。
DUBIOUS_GODS = {"烛龙"}


def godhood_name(codes):
    """`"sg0001,sg0004"` → `"天 · 序"`（未收录的码原样保留，不猜）。"""
    if isinstance(codes, (list, tuple)):
        items = [str(x).strip() for x in codes]
    else:
        items = [x.strip() for x in str(codes or "").split(",")]
    out = [GODHOOD.get(c, c) for c in items if c]
    return " · ".join(out)


def wei_neng_name(codes):
    """`"wn0005,wn0008"` → `"天命在上 · 摒翳诸灾"`（未收录的码原样保留）。"""
    if isinstance(codes, (list, tuple)):
        items = [str(x).strip() for x in codes]
    else:
        items = [x.strip() for x in str(codes or "").split(",")]
    out = [WEI_NENG.get(c, c) for c in items if c]
    return " · ".join(out)


def wei_neng_effect(codes):
    """威能码 → 效果原文；查不到的名留名字、不给效果（宁缺勿猜）。"""
    if isinstance(codes, (list, tuple)):
        items = [str(x).strip() for x in codes]
    else:
        items = [x.strip() for x in str(codes or "").split(",")]
    out = []
    for c in items:
        if not c:
            continue
        nm = WEI_NENG.get(c, c)
        eff = WEI_NENG_EFFECT.get(nm)
        out.append(f"{nm}（{eff}）" if eff else nm)
    return "；".join(out)


def wei_neng_rows(codes):
    """威能码 → **结构化行** `[{"威能": 名, "效果": 原文}]`。

    ★ 2026-10-03 使用者：「这一页表格思维呢？」—— 详情卡里「威能效果」原先是
      一整句 `A（…）；B（…）；C（…）`，读起来是一坨文字。返回**列表套字典**，
      详情卡就会按 `_sub_table` 画成**方框表格**（自带表头与滚动条）。
    未收录的码照留码、效果留空 —— 宁缺勿猜。
    """
    if isinstance(codes, (list, tuple)):
        items = [str(x).strip() for x in codes]
    else:
        items = [x.strip() for x in str(codes or "").split(",")]
    out = []
    for c in items:
        if not c:
            continue
        nm = WEI_NENG.get(c, c)
        out.append({"威能": nm, "效果": WEI_NENG_EFFECT.get(nm, "")})
    return out


# ============================================================ 四、庙宇容量
# 攻略给出的经验公式（**非官方公式**）：
#     T    = 庙宇神明总数上限（通常 10；「戴金面罩青铜人头像」文物可 +2）
#     B    = 该神系的基础神明数（见 GOD_SYS 的 base）
#     Amax = 玩家可造「人造神」上限 = 5（硬性）
#     A    = 已造数量
#     S    = 当前神明总数 = B + A
#     还能造几个 = max(0, min(T − B, Amax))
MIAO_TOTAL_LIMIT = 10          # T
GOD_CREATE_LIMIT = 5           # Amax
MIAO_LIMIT_BONUS_NOTE = "「戴金面罩青铜人头像」文物可再 +2（未计入默认值）"


def free_slots(sys_name, made=0, total_limit=MIAO_TOTAL_LIMIT):
    """该神系**还能造几个**「人造神」。

    `sys_name` 神系名（见 `GOD_SYS`）；`made` 已造数量 A。
    返回 0 表示不能再造（如「中夏—皇天」B=11 已超上限）。
    """
    info = GOD_SYS.get(sys_name)
    if not info:
        return None
    left = total_limit - info["base"]
    return max(0, min(left, GOD_CREATE_LIMIT - made))


# ============================================================ 五、造神事件
# 满足以下条件时会触发「尊奉为神」事件（攻略实测结论）：
CREATE_EVENTS = [
    ("①", "评级为「上 / 佳」「邦 / 美」的**宗室**成员自然死亡",
     "仅在先民、方国阶段"),
    ("②", "评级为「神祖 / 圣人 / 名君 / 名臣 / 名将 / 豪杰 / 哲妇 / 国色」的成员自然死亡",
     "仅在先民、方国阶段"),
    ("③", "功勋 ≥ 100 的**朝臣**自然死亡", "**全阶段**皆可触发"),
    ("④", "「异神降临」事件", "**仅先民阶段**触发"),
]

# ============================================================ 六、继承规则
# 攻略新结论（取代早期的「附庸继承母国神系」）：
INHERIT_NOTE = (
    "分封附庸按「**族域—神系**」配对继承，**不必然继承母国**；"
    "叛军仍继承母国神系。一旦地图上该族域的原国家全灭、"
    "或「新配对」占多数，配对会被改写（如「中夏—皇天」→「中夏—烛龙」），"
    "此后该族域新分封 / 复国的国家都遵新配对。"
)

# ============================================================ 七、祭祀类型
# 界面「祭祀选择」底部有三个选项。⚠️ 它们对应存档 `Memorial_Type` 的哪个编号
# **没有证据**（本档只见到值 `1` / `2`），所以**不做编号映射**。
MEMORIAL_TYPES = ("祭神", "祭五帝", "祭祖")

# ============================================================ 八、神系清零（玩法）
CLEAR_SYS_NOTE = (
    "非上古剧本开局即有初始神系且多半满额。清零流程：用「夺取神像」名分宣战"
    "→ 战后在败国神系里挑一位神 → 切旁观灭自己 → 他国占我城邑产生复国主义"
    "→ 切该国 → 宣战并求和选「承诺复国」→ 复国势力主祭为「无」，神系清零。"
    "新版本补充：**只需有对应的复国主义**即可，不必再走「摧毁神系再复国」。"
)


# ============================================================ 九、神明总表（派生成表，挂进世界页）
GOD_TABLE = "神明 · 总表"


def _dig(obj, key, depth=0):
    """在嵌套 dict / list 里找第一个 key（存档把 Gods_Arr 埋在 `[10]/Data` 下）。"""
    if depth > 12:
        return None
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            hit = _dig(v, key, depth + 1)
            if hit is not None:
                return hit
    elif isinstance(obj, list):
        for v in obj:
            hit = _dig(v, key, depth + 1)
            if hit is not None:
                return hit
    return None


def god_rows(slot):
    """从已载入的实录槽里摊出**一位神一行**的 `Gods_Arr` 表；取不到返回 []。

    列全部来自存档原文；`神格` / `威能` 两列把 sg / wn 码**译成人话**
    （未收录的码原样留码，绝不猜）。
    """
    t = slot.table("Save_Controller_Data") if slot is not None else None
    if t is None:
        return []
    arr = sysarr = None
    for row in t.rows:
        arr = arr or _dig(row, "Gods_Arr")
        sysarr = sysarr or _dig(row, "Gods_Sys_Arr")
    if not arr or not sysarr:
        return []
    base = {}
    for it in arr:
        b = (it or {}).get("Gods_Base_Data") or {}
        if b.get("Code"):
            base[b["Code"]] = b

    rows = []
    for s in sysarr:
        save_name = str(s.get("Name") or "")
        sys_cn = GOD_SYS_BY_SAVE_NAME.get(save_name, save_name)
        for pos in (s.get("Gods_Pos_Arr") or []):
            b = base.get(pos.get("Gods_Code")) or {}
            nm = str(b.get("Name") or "")
            row = {
                "神系": sys_cn,
                "神名": nm,
                "位阶": str(pos.get("Pos_Name") or ""),
                "位格": b.get("Wei_Ge"),
                "威能上限": b.get("Wei_Neng_Limit"),
                "族域": str(b.get("Zu_Yu") or ""),
                "神格": godhood_name(b.get("Godhood_Code_Arr")),
                "威能": wei_neng_name(b.get("Passive_Effect")),
                # ★ 2026-10-03 使用者：「这一页表格思维呢？」——
                #   「威能效果」原来是一整句 `A（…）；B（…）；C（…）`，又是"乱糟糟
                #   的一大片"。改成**结构化行**，详情卡按 `_sub_table` 画成
                #   **方框表格「威能 ｜ 效果」**（列名短、可滚动、不截断）。
                "威能效果": wei_neng_rows(b.get("Passive_Effect")),
                "始王": str(((b.get("Appear_King") or {}) or {}).get("King_Name") or ""),
                # 存档原文是 `子,妘,己,娥,风,嬴,娥`（半角逗号）—— 中文列表用顿号
                "后裔族姓": "、".join(
                    [x for x in str(b.get("Hou_Yi_Zu_Xing") or "").replace("，", ",")
                     .split(",") if x]),
            }
            # ⚠️ **不再输出 `神格码` / `威能码` / `编号`** —— 使用者定的规矩是
            #   「编号列一律不显示」，而这三列既与 `神格` / `威能` / `神名` 完全重复、
            #   又是裸码（`sg0001` / `wn0005` / `sm0022`）；上表也一个字都不显示它们。
            if nm in DUBIOUS_GODS:
                row["存疑"] = "烛龙记录与攻略对不齐"
            rows.append(row)
    return rows


def attach_table(slot):
    """把「神明 · 总表」挂进槽（幂等）。照 `record_derive.attach_book_table` 的做法。

    神明**不在存档的表族里**（埋在 `Save_Controller_Data` 的嵌套中），所以
    摊平成一张派生表挂上去，世界页的表格 / 详情卡 / 搜索就都能直接用。
    """
    if slot is None:
        return False
    rows = god_rows(slot)
    if not rows:
        slot.tables.pop(GOD_TABLE, None)
        return False
    t = Table(name=GOD_TABLE, label=GOD_TABLE)
    t.rows = rows
    t.srcs = [Src("（存档 · Gods_Arr）") for _ in rows]
    t.files = ["Save_Controller_Data.json"]
    slot.tables[GOD_TABLE] = t

    # ★ 2026-10-03：顺手把「神祇编号（sm00xx）→ 神名」登记进 `labels` 的值码表 ——
    #   世界页到处出现 `Gods_Code`（如宗庙表的 `Gods_Pos_Arr`），译成神名才算
    #   「建立对等关系」。**单一来源仍是这里的 Gods_Arr**，故不能写死在 labels.py；
    #   表是游戏内置、跨档相同，每次挂表刷一遍即可。
    #   （函数内 import：`labels` 顶层 import 了 `gods`，模块级会循环导入。）
    try:
        from . import labels as _L
        _L.VALUE["Gods_Code"] = {str(b.get("Code")): str(b.get("Name") or "")
                                 for b in base.values() if b.get("Code")}
    except Exception:
        pass
    return True
