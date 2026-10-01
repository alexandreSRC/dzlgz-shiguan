#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""大周列国志存档 → 家族树 family.json（多表合并版）

存档位置（MuMu 自带 adb）
----------------------
    /data/data/com.xinlanzaoyi.ztz.mi/files/2023011702767223_Save_Files\\Save_All_<N>/
注意那个反斜杠是目录名的一部分（游戏自己的路径 bug），取文件时要单引号包住整条路径。

人物分散在 **多张表** 里，只读族谱表会漏掉一大半：
    Jia_Zu_Genealogy_*.json   族谱表：家谱谱系（父系链、世代、氏名）
    Save_Ren_Data_*.json      活人表：在世者，含配偶/子女/等级/智略/心性/流派
    Save_Dead_Ren_Data_*.json 已故表：同上，已故者
    Save_Woman_Data_*.json    女性表：女性人物（族谱表里几乎没有）
    Save_Chu_Sheng_Data*.json 出生表：新生儿 / 开局新生成的人物
    Save_ED_Ren_Data*.json    旧人物表：字段与活人表一致，新档里会单独装人
                              （后两张是 2026-09-24 补的，见 TABLES 处的说明）

抽取规则（与使用者逐条确认过）
----------------------------
1. **合并**：族谱表的人全要；另外几张表只取「史实人物」或「男性且有后裔」的，
   否则会把整个世界几千个路人都灌进来。
2. **史实**：Ren_Code 是 5 位数字（实测号段 60000~61407）或以「始祖」开头。
   拿现有存档验证：精确率 100%、召回 100%，零误报。游戏 UI 上这类人物带【史传】按钮。
3. **世代**：这不是年龄轴，是**谱系深度**。
   只有各族「始祖」按出生年落到桶里定位；其余人一律「父亲的世代 + 1」。
   （游戏里 14 岁就能生子，所以同龄人可能差好几代 —— 不能拿年龄去套所有人。）
4. **爵位/封国/封代**：来自宗庙牌位（受封时的爵位，不是后来升上去的）。
5. **配偶**：Ren_Pei_Ou_Code_Array。
6. **小传**：以**身份**为主线 —— 某国第几代国君 / 该国国君之子（公子）/
   之孙（公孙）/ 公族，后面接生卒、婚育、品性。谱系上的「第几代」不写：
   它跟「第几代国君」是两套数，混在一起只会互相打架。
   等级/智略/心性/流派这些没有对应字段的信息，也融进同一段文字里。

用法
----
    # 整档导入（覆盖式建档，第一次用）
    python tools/import_from_game.py --src "<槽目录>" --save "存档名"
    # 增量续谱（在已有谱上接着写，保留手写内容）—— 默认演习，加 --apply 才写盘
    python tools/import_from_game.py --src "<槽目录>" --save "存档名" \
        --prune hist --real-state-only --merge
    python tools/import_from_game.py --src "<槽目录>" --save "存档名" \
        --prune hist --real-state-only --merge --apply
    # 对拍 / 单人入谱
    python tools/import_from_game.py --src "<槽目录>" --save "存档名" --compare "上古时代"
    python tools/import_from_game.py --src "<槽目录>" --save "存档名" --person 2276
"""
import argparse
import base64
import glob
import json
import math
import os
import re
import shutil
import sys
import time
from collections import Counter, defaultdict, deque

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ★ 代码改进 C1（2026-09-22）：剧本判定的唯一实现在 app/era.py ——
#   本文件可被子进程当 CLI 调起，era.py 不依赖 tkinter，两边共用安全。
from app.era import era_of as _era_of
from app.era import parse_bc_year as _parse_bc_year

PLACEHOLDER_SUFFIX = re.compile(r"(父|祖|曾|高)$")
ALPHA_CODE = re.compile(r"[A-Za-z]+\d{1,4}")      # QIN001 这类字母前缀的史实号
JUE_CODE = {1: "帝", 3: "王", 4: "公", 5: "侯", 6: "伯", 7: "子", 53: "卿"}
JUE_CHARS = "帝王公侯伯子男卿"

# 世代锚点：只有「始祖」按出生年落桶。桶中心是从现有家族树反推的
# （第1代 −2580 … 第8代 −2425，实测吻合度 57%，其余靠父子链 +1 修正）
GEN_CENTER = {1: -2580, 2: -2547, 3: -2516, 4: -2491,
              5: -2467, 6: -2443, 7: -2434, 8: -2425}
GEN_STEP = -25          # 桶中心之间的大致间隔（负数，年代递减）

TABLES = {
    "族谱表": "Jia_Zu_Genealogy_*.json",
    "活人表": "Save_Ren_Data_*.json",
    "已故表": "Save_Dead_Ren_Data_*.json",
    "女性表": "Save_Woman_Data_*.json",
    # ★ 2026-09-24 使用者要求补上这两张（原「四表」漏人）：
    #   · 出生表 —— 新生儿 / 开局新生成的人物。实测「白水长渊（61393）」的完整
    #     记录只在这一张里，其余四表一处都没有 → 父亲在谱、儿子不在谱。
    #     app 侧的 `record_derive.PERSON_TABLES` **本来就含它**，只有抽取器漏了。
    #   · 旧人物表 `Save_ED_Ren_Data` —— 字段 schema 与活人表完全一致（26 个字段
    #     一一对应）。2026-09-21 曾判「是同一批数据的分片，合并总表会收进来，
    #     不影响召回」而移除；但**新档里它确实单独装人**（实测 Save_All_101 的
    #     18 人在其余四表里一处都查不到），这条假设在新档上已不成立。
    #   顺序即优先级：放最后，让前四张表的字段优先。
    "出生表": "Save_Chu_Sheng_Data*.json",
    "旧人物表": "Save_ED_Ren_Data*.json",
}


# ==================================================================== 格式检查

def sniff_format(path):
    with open(path, "rb") as f:
        head = f.read(4)
    if head[:1] in (b"{", b"["):
        return "json"
    if all(c in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=\r\n"
           for c in head):
        return "encrypted"
    return "unknown"


def check_slot(src):
    if not os.path.isdir(src):
        print(f"× 目录不存在: {src}")
        return False
    if glob.glob(os.path.join(src, "*.json")):
        return True
    txts = glob.glob(os.path.join(src, "*.txt"))
    if txts:
        print("× 这是游戏「云端下载」的存档，无法解析。")
        if sniff_format(txts[0]) == "encrypted":
            blob = base64.b64decode(open(txts[0], "rb").read())
            c = Counter(blob)
            h = -sum((v / len(blob)) * math.log2(v / len(blob)) for v in c.values())
            print(f"  实测：Base64 解出 {len(blob)} 字节，熵 {h:.4f}/8（加密特征）")
        print("  解决：在游戏里【载入】它，过一个回合让它自动存档，")
        print("        游戏会把明文写回本地槽（.json），那时就能读了。")
        return False
    print(f"× 目录里没有 .json: {src}")
    return False


# ==================================================================== 读四张表

# ---- 选择性 JSON 读取缓存（代码改进 B2，2026-09-22）----
# 流水线里族谱表被完整解析 3 遍（load_tables / ancestor_codes / ancestor_of_code），
# 宗庙与 KingData 各 2 遍（load_titles / load_king_lineage / load_states）。
# 只缓存**会被重复读的小表**（谱表 / KingData / 宗庙 / 家族总表）；
# 人物四表（单遍的大文件）不缓存，免得内存白涨。
# 键带 mtime，文件一换自动失效；条目超 200 整体清空；读失败不缓存（下次重试）。
_CACHEABLE = re.compile(r"^(Jia_Zu_Genealogy_|Save_KingData)")
_CACHEABLE_EXACT = ("Zong_Miao_Controller.json", "Jia_Zu_Controller.json")
_JSON_CACHE = {}


def _read(f):
    name = os.path.basename(f)
    if name not in _CACHEABLE_EXACT and not _CACHEABLE.match(name):
        try:
            with open(f, encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return None
    try:
        mtime = os.path.getmtime(f)
    except OSError:
        return None
    key = (os.path.abspath(f), mtime)
    hit = _JSON_CACHE.get(key)
    if hit is not None:
        return hit
    try:
        with open(f, encoding="utf-8") as fh:
            obj = json.load(fh)
    except Exception:
        return None
    if len(_JSON_CACHE) > 200:
        _JSON_CACHE.clear()
    _JSON_CACHE[key] = obj
    return obj


def load_tables(src):
    """读四张表，统一成 {code: rec}，rec 里加 _tbl 标记来源。"""
    by_code = {}
    for tbl, pat in TABLES.items():
        n = 0
        for f in sorted(glob.glob(os.path.join(src, pat))):
            o = _read(f)
            if o is None:
                continue
            if tbl == "族谱表":
                items = [r for g in (o if isinstance(o, list) else [])
                         for r in (g.get("Genealogy_Ren_Record_Array") or [])]
            else:
                items = [it for it in (o if isinstance(o, list) else [])
                         if isinstance(it, dict)]
            for it in items:
                c = str(it.get("Ren_Code", ""))
                if not c:
                    continue
                n += 1
                if c not in by_code:
                    by_code[c] = dict(it, _tbl=tbl)
                else:
                    # 同一个人常同时出现在多张表里：族谱表记谱系（父系链、世代），
                    # 活人/已故/女性表记配偶、子女、等级、智略… 只留第一条会把
                    # 另外几张表的字段丢掉（实测配偶从 156 人掉到 2 人）。
                    # 所以合并：先来的优先，后来的只补空缺。
                    # ★ 2026-09-26 审查修复（M3）：判据里原来有 0 —— 「0 当空」
                    #   这个毛病在本项目咬过三次（七十三批：等级 0=庶、智略 0 是
                    #   合法分），这里是第四处漏网：先到的表写入 0（真值），后表
                    #   的非零值会把它顶掉，违反「先来的优先」。0 从空集合去掉。
                    cur = by_code[c]
                    for k, v in it.items():
                        if k == "_tbl":
                            continue
                        old = cur.get(k)
                        if old in (None, "", [], {}) and v not in (None, "", [], {}):
                            cur[k] = v
        print(f"    {tbl:<5s} {n:>5} 条")
    return by_code


# ==================================================================== 字段小工具

def name_of(rec):
    return rec.get("Ren_Name") or \
        f"{rec.get('Ren_Shi') or rec.get('Ren_Xing') or ''}{rec.get('Ren_Ming','')}"


def born_of(rec):
    for k in ("Born_Time", "Ren_Chu_Sheng_Time"):
        v = rec.get(k)
        if isinstance(v, str) and v:
            p = v.split(",")[0].strip()
            if p.lstrip("-").isdigit():
                return int(p)
    return None


def born_time_of(rec):
    """生年+月+日的**原始完整串**（如 `-2487,1,0`，0 日 = 不详）。

    与 `born_of` 同款遍历，但保留月日 —— 谱牒的 `birth` 字段要存完整
    年月日（显示层再人性化），而 `born_of` 的 int 年份仍留给世代落桶用。
    找不到返回 ""。
    """
    for k in ("Born_Time", "Ren_Chu_Sheng_Time"):
        v = rec.get(k)
        if isinstance(v, str) and v:
            return v
    return ""


def died_of(rec):
    for k in ("Dead_Time", "Ren_End_Time"):
        v = rec.get(k)
        if isinstance(v, str) and v:
            return v
    return ""


def is_placeholder_ancestor(code):
    """`始祖XX` —— 游戏为「让每个族谱都有个根」硬造的占位始祖，**不是真人**。

    判据来自族谱表的世代区间：真族谱记的是 `-5~0`、`0~103` 这种；
    而以占位始祖开头的族谱一律是 `97~103`（上古时代档 170/151 个族谱、
    秦末起义档 141/151 个都是这一档），那是游戏内部分配的假深度。

    这些名字本身也不是人名，是**尊号**：游戏写「巢皇」，其实指的是「风巢皇」；
    写「华胥」，指的是「姒华胥」。真人另有数字 Code 的记录在册。
    所以它们既不进人物名单，也不当世代锚点 —— 否则会出现
    「风巢皇 的族谱始祖是 巢皇」这种自相矛盾（真人认一个假人当祖宗）。
    """
    return str(code or "").startswith("始祖")


def is_hist(code):
    """史实人物 —— 判据是**号段**，不是名字。

    实测「秦末起义」档，号段分得极干净：

    | Code | 数量 | 是什么 | 例子 |
    |---|---|---|---|
    | 1~5 位数字 | 3259 | **史实人物** | 陈胜=7045、项羽=7013、嬴政=2276、赵高=8873 |
    | `始祖XX` | 22 | 占位始祖（**不是人**，见 is_placeholder_ancestor） |
    | 字母前缀 + 数字 | 4 | 少数秦国史实人物 | QIN001 章蟜、QIN002 甘龙 |
    | 9 位数字 | 3953 | 程序生成的路人 | 100000150 嬴涔 |
    | 10 位带 父/祖/曾/高 | 1756 | 为凑显示世代凭空造的占位祖先 | 100000150父 |

    游戏 UI 上带【史传】按钮的就是这一批，可人工抽查对得上。
    （「上古时代」那个老档的史实号段是 60000~61407，所以判据只能按**位数**，
    不能写死前缀 —— 两个档的号段完全不重叠。）
    """
    c = str(code or "")
    if is_placeholder_ancestor(c):
        return False
    if c.isdigit():
        return len(c) <= 5
    return bool(ALPHA_CODE.fullmatch(c))


_CN = "零一二三四五六七八九"


def cn_num(i):
    """1→一 2→二 … 11→十一 21→二十一（**小传行文**用）。"""
    if i <= 0:
        return ""
    if i < 10:
        return _CN[i]
    if i == 10:
        return "十"
    if i < 20:
        return "十" + _CN[i % 10]
    return _CN[i // 10] + "十" + (_CN[i % 10] if i % 10 else "")


# 重名序数 —— 三个时代的写法都见过，**现行是纯数字**：
#   中文数字（最老：风会胜一 / 风会胜二十一）→ 读起来像名字的一部分，弃用
#   带圈数字（上一版：风会胜①）→ 一眼是编号，但使用者嫌不好看，弃用
#   纯数字（现行：风会胜1）→ 由渲染层缩成小号**灰**字贴在名字最后一字的
#     **右上角**（像幂），见 `views/tree_view._draw_dup_mark` /
#     `views/timeline_view._draw_dup_mark`
#   （使用者 2026-09-22：「改成数字右上角角标灰色123吧，像幂一样那种」）
# `_DUP_CIRCLED` 只留给「认老档」——不再用来生成名字。
_DUP_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def dup_num(i):
    """重名序数：1→"1" 2→"2" …（**纯数字，没有上限**）。

    ⚠️ **只给名字用**。小传行文里「第几代国君」「此为其几」仍然走 `cn_num` ——
       那里必须是「一/二/三」，写成「第1代」就不成话了。
    """
    return str(i) if i > 0 else ""


def guo_name(g):
    """封国名在存档里不带「国」字（存的是「雷」「巢」），行文时要补上。
    例外：叛军、某某氏 这类本来就不是国，加了反而怪。"""
    if not g or g.endswith("国") or g.endswith("氏") or g.endswith("军"):
        return g
    return g + "国"


def is_female(rec):
    return bool(rec.get("Memorial_Ren_Sex")) or bool(rec.get("Ren_Sex")) or \
        rec.get("_tbl") == "女性表"


def is_book_placeholder(rec):
    """谱牒里这条记录是不是**游戏硬造的占位祖先空壳** —— 续谱时该清掉。

    ★ 2026-09-24 使用者要求：判据修好只保证**新抽**不再带它们，**已经写进谱的
      老数据不会自己消失**（《满天星斗·自动测试》实测还留着 17 条，风巢皇名下
      因此仍挂着 20 个「儿子」）。所以合并时按下面的判据把旧记录也清一遍。

    判据（对着实测数据定的：谱内 17 条空壳全部命中，对照组 0 命中）：
      · 编号以 父/祖/曾/高 结尾 —— 游戏给「某某之父」槽位的编号
      · 且**没有生年** —— 这批空壳在人物表里只有 {编号, 名字} 两个字段，
        连性别都没有，更不会有生年；对照的非史实真人一律带生年
      · 且不是史实人物 —— 史实一律豁免（「嫫祖 / 圭祖」这类真名本身就以
        「祖」结尾，但它们的编号是数字，编号判据本来也不会命中，双保险）
    """
    code = str((rec or {}).get("code") or "")
    if not PLACEHOLDER_SUFFIX.search(code):
        return False
    if (rec or {}).get("historical") == "是":
        return False
    return not str((rec or {}).get("birth") or "").strip()


def ancestor_codes(src):
    """各族谱的始祖 Code 集合 —— 世代计算的锚点。

    跳过 `始祖XX` 这类占位始祖（见 is_placeholder_ancestor）：它们不是人，
    拿它们锚定等于让整族谱挂在一个假祖宗上。跳过后该族谱会走下面的兜底
    —— 改用「该族谱里最年长的真实成员的生年」当锚点。
    """
    out = set()
    for f in sorted(glob.glob(os.path.join(src, "Jia_Zu_Genealogy_*.json"))):
        o = _read(f)
        for g in (o if isinstance(o, list) else []):
            ac = str(g.get("Ancestor_Code", "") or "")
            if ac and not is_placeholder_ancestor(ac):
                out.add(ac)
    return out


def ancestor_of_code(src):
    """{人物 Code: 所属族谱的始祖 Code}。

    游戏会为凑够显示世代，给每个人凭空造一串「某某父/某某祖/某某曾/某某高」的
    占位祖先（Code 和名都带后缀）。这些不是真人，剔除后父子链就断了 ——
    用这张表把断掉的支系接回该族谱的始祖。

    值为空串表示该族谱的始祖是占位始祖（不是人），此时不接 —— 交给兜底逻辑。
    """
    out = {}
    for f in sorted(glob.glob(os.path.join(src, "Jia_Zu_Genealogy_*.json"))):
        o = _read(f)
        for g in (o if isinstance(o, list) else []):
            ac = str(g.get("Ancestor_Code", "") or "")
            if is_placeholder_ancestor(ac):
                ac = ""
            for r in g.get("Genealogy_Ren_Record_Array") or []:
                c = str(r.get("Ren_Code", ""))
                if c:
                    out.setdefault(c, ac)
    return out


# ==================================================================== 爵位 / 封国

def parse_time(raw):
    """'-2485,3,26' → (-2485, 3, 26)，用于按即位时间排序；解析不了返回 None。"""
    if not isinstance(raw, str) or not raw.strip():
        return None
    parts = [p.strip() for p in raw.split(",")]
    try:
        y = int(parts[0])
    except (ValueError, IndexError):
        return None
    mo = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    d = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    return (y, mo, d)


def is_placeholder_memorial(m):
    """判断一张宗庙牌位是不是**游戏硬造的占位祖先**。

    实测秦宗庙 72 张牌位里混着 12 张这样的：

        code=60170 '嬴赞皇' 父=60169 → code=60169 '嬴上启' 父=60168
        → … → code=60178 '嬴轩' 父=60177 → code=60177 '嬴轩父' 父=60176
        → code=60176 '嬴轩祖' → code=60175 '嬴轩曾' → code=60174 '嬴中衍'

    名字带「父 / 祖 / 曾 / 高」后缀，是游戏为凑够**显示世代**
    （每张牌位都带 Ren_Generations = 72,71,70… 连续编号）而凭空插进父链的。
    真实的秦先祖链是 `嬴蜚廉(9198) → 嬴中潏(60179) → 嬴轩(60178)`，
    中间被塞了 4 个假的。

    判据用的是**名 + Code 都带后缀**（与整档导入的 `_is_ph` 同口径）：
    只有一边带后缀的可能是真名（如「嫫祖」「圭祖」这类真名本身以「祖」结尾）。
    """
    name = str(m.get("Memorial_Ren_Ming") or "")
    code = str(m.get("Memorial_Code") or "")
    return bool(PLACEHOLDER_SUFFIX.search(name)) and \
        bool(PLACEHOLDER_SUFFIX.search(code))


def load_titles(src):
    """宗庙牌位 + 国君表 → {姓名: [记录]}。

    两处的性质完全不同，必须分开看待：
      · 宗庙（Zong_Miao_Controller）—— 牌位，**含后世追封的远祖**。雷宗庙里就
        同时供着 燧人/巢皇/羲皇/雷方（无即位时间，爵都是伯）和真正的君主 元明。
      · 国君表（Save_KingData）—— **实际即位的实录**，带在位起止年份。
    同一个人两处都有时以国君表为准（见 pick_title），否则会把「追封的国」
    当成他的封国，世系框就会横跨半个画面。

    ★★ `Memorial_Ren_Now_King_Name` 是**「此人属于哪国君主家族」的权威答案 ★★
    ------------------------------------------------------------------
    实测 1487 张牌位，该字段与所属宗庙名（去掉「宗庙」二字）**100% 一致**
    （0 个例外）—— 例如秦宗庙里每一张牌位都写着 `Memorial_Ren_Now_King_Name='秦'`。

    「宗庙」本就是**该国家族的祖庙**，换句话说：**进庙 = 是这家的人**。
    这才是「X国世系」的正确判据，而不是「在X国出仕」或「住在X国城市」。
    `load_king_lineage()` 直接吃这一点来建真实君主世系。

    ★ `Memorial_Ren_Jue_Wei_New` 在宗庙语境里**不分皇帝与王** ——
    实测秦宗庙 72 张牌位这个字段**全是 1（帝）**，连秦始皇的高祖父嬴皋陶都是。
    所以**不能用它当爵位**。皇帝/王的区别看 `Memorial_Ren_Zun_Hao`：
      嬴政  尊号「始皇」      → 皇帝
      嬴异人 尊号「秦庄襄王」   → 王
      嬴柱  尊号「秦孝文王」   → 王
    见 `zun_hao_rank()`。

    「封代」（某国第几代君主）的算法：**该国有即位记录的人按即位时间排序，从 1 起**。
    追封的先祖没有即位时间，封代记 0、不参与排序 —— 这正是要的效果：
    燧人、羲皇这类被后世追认的远祖不占君主序号。

    为什么不用 King_Generations：游戏新版把那个字段弄丢了，实测全是 None，
    所以只能靠即位时间自己排。

    ★ `Ren_Generations` **不要当世代用**：它是「游戏显示用的连续编号」
    （秦宗庙从 1 到 72 一路连号，中间那 12 个占位祖先也各占一号），
    数值本身没有谱系含义。真世代要靠父子链推。
    """
    out = defaultdict(list)
    p = os.path.join(src, "Zong_Miao_Controller.json")
    if os.path.exists(p):
        zm = _read(p) or {}
        for z in zm.get("All_King_Zong_Miao_Array", []) or []:
            # 键名在游戏更新里改过：老 All_King_Memorial_Array / 新 All_Memorial_Array
            arr = z.get("All_Memorial_Array")
            if arr is None:
                arr = z.get("All_King_Memorial_Array")
            arr = arr or []
            # 该国「实际即位者」按时间排序 → 封代
            dated = sorted(
                ((parse_time(m.get("Memorial_Ren_Become_Time")), i)
                 for i, m in enumerate(arr)
                 if parse_time(m.get("Memorial_Ren_Become_Time"))),
                key=lambda x: x[0])
            fief_rank = {idx: n + 1 for n, (_t, idx) in enumerate(dated)}
            for i, m in enumerate(arr):
                nm = f"{m.get('Jia_Shi') or m.get('Zu_Xing') or ''}" \
                     f"{m.get('Memorial_Ren_Ming','')}"
                if not nm:
                    continue
                out[nm].append({
                    "guo": (m.get("Memorial_Ren_Now_King_Name") or "").strip(),
                    "jue": JUE_CODE.get(m.get("Memorial_Ren_Jue_Wei_New"), ""),
                    "king_gen": m.get("King_Generations"),
                    "ren_gen": m.get("Ren_Generations"),
                    "fief_gen": fief_rank.get(i, 0),
                    "become": m.get("Memorial_Ren_Become_Time", ""),
                    "shu": (m.get("Jia_Shi") or m.get("Zu_Xing") or "").strip(),
                    "zong": z.get("Zong_Miao_Name", ""),
                    "src": "zong",
                })
    for f in sorted(glob.glob(os.path.join(src, "Save_KingData_*.json"))):
        k = _read(f)
        if not isinstance(k, dict):
            continue
        guo = k.get("King_Name", "")
        # King_Str 是**该国全部在位记录**，逗号分隔；单条形如
        #   「风巢皇|风||公|-2484、-2483」= 名|姓|氏|爵|即位年、离位年
        # 老代码直接 split("|") 再把 s[2]/s[1] 拼在名前，多段时整个错位，
        # 于是国君表从来没匹配上（巢皇 一直被当成「巢·伯」而非「风·公」）。
        reigns = []
        for seg in (k.get("King_Str") or "").split(","):
            seg = seg.strip()
            if not seg:
                continue
            p = seg.split("|")
            if len(p) < 4 or not p[0].strip():
                continue
            span = (p[4] if len(p) > 4 else "").split("、")
            begin = span[0].strip() if span and span[0].strip() else ""
            reigns.append({"name": p[0].strip(), "jue": p[3].strip(), "begin": begin})
        dated = sorted(((parse_time(r["begin"]), i) for i, r in enumerate(reigns)
                        if parse_time(r["begin"])), key=lambda x: x[0])
        fief_rank = {idx: n + 1 for n, (_t, idx) in enumerate(dated)}
        for i, r in enumerate(reigns):
            out[r["name"]].append({
                "guo": guo, "jue": r["jue"],
                "king_gen": None, "ren_gen": None,
                "fief_gen": fief_rank.get(i, 0),
                "become": r["begin"], "shu": "", "zong": "", "src": "king",
            })
    return out


def pick_title(cands, ren_gen):
    """同名多条时消歧。只认「实录」：国君表，或宗庙里带即位时间的牌位。

    为什么不能退而取第一条：宗庙里有一类**氏为空的附祭条目** —— 每个宗庙都会
    把 羲皇、巢皇、燧人 这些共同远祖抄一份进来（'巢皇' 一个人就出现在 11 个
    宗庙里），国和爵各写各的。落到谁头上全看遍历顺序，之前就是这么让
    巢皇 变成「巢·伯」、羲皇 变成「雷·伯」的 —— 世系框因此横跨整个画面。

    没当过君主就没有封国，这是对的结果：风燧人、风雷方 在游戏里只是被追认的
    远祖，封国留空，世子系框自然收紧到真正即位的那几代。
    """
    if not cands:
        return {}
    for sub in ([c for c in cands if c.get("src") == "king"],
                [c for c in cands if c.get("become")]):
        if not sub:
            continue
        for c in sub:
            if ren_gen is not None and c.get("ren_gen") == ren_gen:
                return c
        return sub[0]
    return {}


# ============================================================ 君主世系（宗庙真相源）

def zun_hao_rank(zun_hao):
    """尊号 → 实际爵位（「皇帝 / 王」这个区分就靠它）。

    存档里现成的，**不用查历史** —— 实测秦宗庙：

        code=2276 始皇嬴政     尊号='始皇'      → 皇 / 帝
        code=2275 秦庄襄王嬴异人  尊号='秦庄襄王'   → 王
        code=2274 秦孝文王嬴柱    尊号='秦孝文王'   → 王
        code=2273 秦昭襄王嬴稷    尊号='秦昭襄王'   → 王
        code=2268 秦惠文王嬴驷    尊号='秦惠文王'   → 王（他之前秦是公）

    使用者说的「嬴政开始称帝，他本人与二世是皇帝、他父亲则是王」
    跟存档**完全吻合**。之所以现在全被写成皇帝，是因为错用了
    `Memorial_Ren_Jue_Wei_New` —— 那个字段在宗庙里一律是 1。

    规则：尊号含「皇」或「帝」→ 帝；含「王」→ 王；含「公」→ 公；
    「侯 / 伯 / 子 / 男」同理；「西陲大夫」这类无爵位的职位名 → 空。
    """
    s = str(zun_hao or "").strip()
    if not s:
        return ""
    # 「秦庄襄王」—— 王的判据是**末字**，不是包含（否则「王翦」类人名会误判，
    # 不过尊号字段里本来只放尊号，这里保守取末字更稳）
    for ch, jue in (("帝", "帝"), ("皇", "帝"), ("王", "王"),
                    ("公", "公"), ("侯", "侯"), ("伯", "伯"),
                    ("子", "子"), ("男", "男"), ("君", "君")):
        if ch in s:
            # 「侯」可能出现在「西陲大夫」这类里？实测没有；
            # 但「秦嬴」这种尊号没有爵位字，会自然落到末尾返回空
            return jue
    return ""


def inherit_rank(code, lineage, memo=None):
    """尊号缺失时**沿父链继承**爵位 —— 落实使用者那句「嬴政与二世是皇帝」。

    存档实测：秦二世胡亥 `Memorial_Ren_Zun_Hao` 是**空的**，
    而他的父亲嬴政尊号「始皇」（= 帝）。使用者明确说过「他本身和二世是皇帝」。

    判据：秦制是**一世一元、同制相承**（始皇帝 → 二世皇帝都是皇帝），
    所以尊号空的人取**最近的、有尊号的父辈**的爵位，**但只承「帝」不下延**：
    嬴政之父嬴异人尊号「秦庄襄王」→ 王，绝不会因为儿子称帝而被追认为皇帝。

    ★ **两个必须的护栏**（实测踩出来的）：
      1. **只承「帝」不承其他** —— 王是各人自己的尊号，父子不同谥是常态，
         硬继承会把「秦孝公」写成「秦王」。
      2. **必须同一宗庙** —— 父链会跨庙（实测 姬蟜极 / 黄帝轩辕 这些共同
         远祖被 8 个以上宗庙各抄一份，父链于是从秦庙走到楚庙）。
         不加这条护栏，`姬蟜极` 会因为链上挂到「黄帝」而被封帝，
         实测凭空造出 300 多个假皇帝（352 → 20）。
    """
    if memo is None:
        memo = {}
    if code in memo:
        return memo[code]
    memo[code] = ""                        # 防环
    v = lineage.get(code)
    if v is None:
        return ""
    if v["rank"]:
        memo[code] = v["rank"]
        return v["rank"]
    fc = v.get("father_code") or ""
    if fc and fc not in ("", "-1"):
        up_v = lineage.get(fc)
        # 护栏②：父不在同一宗庙 → 不继承（跨庙父链是「共同远祖」抄本间的假连接）
        if up_v is not None and up_v.get("miao") == v.get("miao"):
            # 护栏①：只承帝制（王/公/侯是各人自己的尊号，父子不同谥是常态）
            #
            # ★ 护栏③ **只走一步**（不递归）：实测秦宗庙父链一路通到「黄帝轩辕」
            #   （尊号=黄帝），递归上去会让整段上古先祖（蜚廉/中潏/轩/衍…）
            #   全部继承成「帝」—— 那 195 个假皇帝就是这么来的。
            #   使用者的原话只要求「**他本身和二世**是皇帝」，即**紧邻的一代**：
            #   嬴政（始皇，帝）→ 胡亥（承父为帝）✓
            #   嬴政 → 嬴异人（自有尊号「秦庄襄王」= 王，根本走不到继承）✓
            #   嬴异人 → 嬴柱（自有尊号，同上）✓
            #   于是「只承紧邻的帝父」既满足需求，又不会往上传染。
            if up_v["rank"] == "帝":
                memo[code] = "帝"
                return "帝"
    return ""


def load_king_lineage(src):
    """★ 真实的君主世系 —— 从宗庙牌位建，**这才是「X国世系」的唯一真相源**。

    为什么要新写一个而不是继续用 load_states 的血缘口径
    ---------------------------------------------------
    使用者原话：「**不是在某国出仕或在某国的城市就有世系，必须是该国君主的家族**」。
    但现在的代码干的是「父亲在秦国 → 儿子也是秦人」，于是：

        任敖（刘邦御史大夫）  → 汉**王**
        灌婴（汉开国功臣）    → 汉**王**
        夏侯玄（夏侯婴之子）  → 汉
        严阙 / 严卓（秦臣）   → 秦**帝**
        蔺康（蔺氏，赵国大夫） → 燕**王**
        姒鹿郢（越王勾践一族） → 匈奴

    这条「父系继承」把封国当成了**户口**。封国不是户口，是**受封**。

    本函数的口径
    ------------
    只信宗庙：`All_King_Zong_Miao_Array[].All_Memorial_Array[]`，每张牌位自带
    `Memorial_Ren_Now_King_Name`（实测 1487/1487 与所属宗庙一致）。
    即「**进了这家祖庙 = 是这家的人**」。

    返回
    ----
    `{Ren_Code: {...}}`，每人：
        guo      国名（"秦"）
        miao     宗庙名（"秦宗庙"）
        zun      尊号（"始皇" / "秦庄襄王"）
        jue      宗庙牌位上的爵位码（一律 1，仅留档备查，**别直接用**）
        rank     由尊号推出的真实爵位（"帝" / "王" / "公" / ""）
        fief_gen 该国第几代**实际即位**君主（按即位时间排序；追封与占位记 0）
        born / become / dead  生年 / 即位 / 卒年
        father_code  牌位自己的父链（**真链，用于世代推导**）
        is_placeholder  是否游戏硬造的占位祖先（名字带父/祖/曾/高）
        is_zushi   是否始祖庙（InPut_Miao == "始祖庙"）
        common_ancestor  是否**多庙共祭的共同远祖**（★ 见下方「共祭 ≥3 庙」说明）

    ★ 占位祖先**照样返回**（带 is_placeholder=True）：它们虽然不是真人，
    但**占着父链的位置**，世代推导时要用它们当「跳板」把真人接上；
    只是不给它们写谱、不给封国。
    """
    p = os.path.join(src, "Zong_Miao_Controller.json")
    if not os.path.exists(p):
        return {}
    o = _read(p) or {}
    # ★ 2026-09-25：**建国年表**（`Save_KingData.Jian_Guo_Year`）——
    #   给「分封第一代」定基准用（见下方 rebase 那段）。
    #   这是**游戏自己写的字段**，不是我们算的。
    guo_jian = {}
    for _f in sorted(glob.glob(os.path.join(src, "Save_KingData_*.json"))):
        _k = _read(_f)
        if isinstance(_k, dict) and _k.get("King_Name") is not None:
            _y = _k.get("Jian_Guo_Year")
            if isinstance(_y, (int, float)):
                guo_jian[_k["King_Name"]] = int(_y)
    out = {}
    for z in o.get("All_King_Zong_Miao_Array") or []:
        miao = str(z.get("Zong_Miao_Name") or "")
        arr = z.get("All_Memorial_Array")
        if arr is None:
            arr = z.get("All_King_Memorial_Array")
        arr = arr or []
        # ★ 2026-09-25 核对：**宗庙名 ≠ 国名** —— 楚国的宗庙叫「熊宗庙」、
        #   秦国的另一座叫「将宗庙」，所以不能拿 `miao.replace("宗庙","")` 当国名。
        #   改用牌位自带的 `Memorial_Ren_Now_King_Name`（当今国名），与项目里
        #   「定国看 Now_King_Name」这条铁律一致。
        #   ⚠️ 但实测本档：秦宗庙的牌位写「秦」✓，**熊宗庙写的就是「熊」、
        #      将宗庙写「将」** —— 那是**游戏给该势力的显示名**（拿氏当势力名），
        #      并非历史上的「楚」「秦」。两处来源在多数宗庙里是一致的，
        #      所以本改动不改变现有结果；要显示成「楚国」得另加人工史补国名层
        #      （见 `history_states.json`，目前只补了 代/塞/梁/汉/淮南/翟/西楚/韩）。
        _guo_cnt = defaultdict(int)
        for _m in arr:
            _g = str(_m.get("Memorial_Ren_Now_King_Name") or "").strip()
            if _g:
                _guo_cnt[_g] += 1
        guo = (max(_guo_cnt, key=_guo_cnt.get) if _guo_cnt
               else miao.replace("宗庙", ""))

        # ★★ 2026-09-25 「封代」改用牌位自带的 `Generations` 字段 ★★
        #   这才是**游戏自己算的「该封国第几代」**，也正是使用者要的
        #   「就像周初分封一样，**从分封第一代开始算起**」。
        #
        #   实测（Save_All_103，1193 张牌位）：
        #     · 每座宗庙恰有一张 `Generations == 1`（= 开国/受封第一代），
        #       127 座庙 **100% 覆盖**；
        #     · 同一庙内该字段**严格连续**：秦 1..33、宋 1..7、箕 1..38；
        #     · 沿父链**严格递增** —— 553 组父子对比对，0 违例；
        #     · **全部存档都带此字段**（含 .bak 死档），无兼容问题。
        #   实例：嬴政 = 秦第 **30** 代、嬴胡亥 = 31；而本局（−208 年）才受封的
        #   「熊」「将」两国，其君 **熊心 / 将闾 都是第 1 代** ✓
        #
        #   `Generations == -1` = **不属于本封国世代**（受封之前的同族先世）。
        #   熊宗庙里 熊启 / 熊槐 / 楚威王 全是 −1 —— 他们确实是熊氏先王，
        #   但不是**熊国**的世代，所以封代记 0。风巢皇等共祭远祖同样是 −1。
        #
        #   旧口径为什么必须废掉：`_real_depth` 数的是**家族沿父链的真人个数**，
        #   不是**封国世代**。秦宗庙牌位连贯才勉强近似；换成「熊」这种本局才
        #   分封的国就荒谬 —— 熊心被写成「熊国第 80 代国君」，而它 −208 年
        #   才受封。使用者报的就是这个。
        #
        #   ⚠️ `Generations`（封国世代）与 `Ren_Generations`（游戏显示的**连续
        #   编号**，占位祖先也占号，熊心=80）不是一回事，后者仍不可当世代用。
        fief_rank = {}
        for i, m in enumerate(arr):
            if is_placeholder_memorial(m):
                continue
            _g = m.get("Generations")
            fief_rank[i] = _g if isinstance(_g, int) and _g > 0 else 0

        # ★★ 2026-09-25 「**从分封第一代开始算起**」（使用者裁定）★★
        #   `Generations` 是**宗庙这一条线**的世代号，不等于**本封国**的世代号。
        #   铁证：宋宗庙 的 Gen 1..4 是游戏硬造的**占位祖先**（子纠高/曾/祖/父），
        #   于是宋义被记成「第 5 代」—— 可是宋国 `Jian_Guo_Year = −207`
        #   而宋义的即位年**也是 −207**：他分明是**始封之君，应当是第 1 代**。
        #   （建国年与即位年都能从存档直接读到，见 `guo_jian`。）
        #
        #   判据（只在「重新受封」的国上命中，老国完全不受影响）：
        #     若某位国君的**即位年 == 本国建国年** → 他就是始封之君，以他为第 1 代
        #     重定基准（该国内所有封代同减 offset），其后的按 `Generations` 递增。
        #   实测：熊 −208 / 将 −208 / 宋 −207 命中（本局新分封）；
        #   秦 −886、蜀 −2022、箕 −1046、月氏 −500 等国建国年与任何即位年都不重合
        #   → **一位都不动**。
        _jgy = guo_jian.get(guo)
        if _jgy is not None:
            _fo_i, _fo_g = None, 0
            for i, m in enumerate(arr):
                _bt = parse_time(m.get("Memorial_Ren_Become_Time"))
                _gi = fief_rank.get(i, 0)
                if _bt and _gi > 0 and _bt[0] == _jgy:
                    if _fo_i is None or _gi < _fo_g:
                        _fo_i, _fo_g = i, _gi
            if _fo_i is not None and _fo_g > 1:
                _off = _fo_g - 1
                fief_rank = {i: (v - _off if v > _off else 0)
                             for i, v in fief_rank.items()}

        if not any("Generations" in m for m in arr):
            # 老档兜底（实测现有存档 100% 带该字段，这段只为防格式回退）：
            # 有即位记录的按即位时间排，其余退到父链真人深度。
            dated = sorted(
                ((parse_time(m.get("Memorial_Ren_Become_Time")), i)
                 for i, m in enumerate(arr)
                 if parse_time(m.get("Memorial_Ren_Become_Time"))
                 and not is_placeholder_memorial(m)),
                key=lambda x: x[0])
            fief_rank = {idx: n + 1 for n, (_t, idx) in enumerate(dated)}

            def _real_depth(idx):
                """沿父链数**真人**（跳过占位祖先），到自己为止。"""
                d, cur, guard = 0, idx, 0
                while cur is not None and guard < 200:
                    guard += 1
                    m = arr[cur]
                    if not is_placeholder_memorial(m):
                        d += 1
                    fc = str(m.get("Father_Code") or "").strip()
                    nxt = None
                    for j, mm in enumerate(arr):
                        if str(mm.get("Memorial_Code") or "").strip() == fc:
                            nxt = j
                            break
                    cur = nxt
                return d

            for i, m in enumerate(arr):
                if is_placeholder_memorial(m):
                    continue
                fief_rank[i] = _real_depth(i)

        for i, m in enumerate(arr):
            code = str(m.get("Memorial_Code") or "").strip()
            if not code:
                continue
            zun = str(m.get("Memorial_Ren_Zun_Hao") or "").strip()
            rec = {
                "guo": guo,
                "miao": miao,
                "zun": zun,
                "jue": JUE_CODE.get(m.get("Memorial_Ren_Jue_Wei_New"), ""),
                "rank": zun_hao_rank(zun),
                "fief_gen": fief_rank.get(i, 0),
                "born": m.get("Memorial_Ren_Born_Time") or "",
                "become": m.get("Memorial_Ren_Become_Time") or "",
                "dead": m.get("Memorial_Ren_Dead_Time") or "",
                "father_code": str(m.get("Father_Code") or "").strip(),
                "father_name": str(m.get("Father_Name") or "").strip(),
                "is_placeholder": is_placeholder_memorial(m),
                "is_zushi": str(m.get("InPut_Miao") or "") == "始祖庙",
                "name": str(m.get("Memorial_Ren_Ming") or ""),
                "shi": str(m.get("Jia_Shi") or "").strip(),
            }
            # ★ 同一个真人可能被**多个宗庙**共用（实测 风巢皇/黄帝轩辕/太昊伏羲/
            #   雷祖燧人 这四位出现在秦、楚、魏、匈奴、齐… 每一个宗庙里，
            #   是全天下的共同远祖）。谁先被遍历到就归谁 —— 会写成「箕」这种
            #   莫名其妙的结果。所以：**已存在且还没定下国时，保留第一次的
            #   归属**；若两次归属不同，标记为「多庙共祭」，由调用方决定
            #   是否给它写封国（通常应当留空：共同远祖不属于任何一国）。
            if code in out:
                prev = out[code]
                if prev["guo"] != guo:
                    prev["shared"] = True
                    prev.setdefault("shared_with", set()).add(guo)
                    # 真人优先于占位祖先占位
                    if prev["is_placeholder"] and not rec["is_placeholder"]:
                        rec["shared"] = True
                        rec.setdefault("shared_with", set()).add(prev["guo"])
                        out[code] = rec
                continue
            out[code] = rec

    # ★★ 2026-09-24：把「多庙共祭」分成两档 —— 使用者原话「宗庙里风巢皇是祖先，
    #    但不说明他是秦国的第一代君主」，裁定「宗庙祖先不计入当前存档该国世系」。
    #    实测（Save_All_1，1096 张真人牌位）：
    #      · 共祭 **2** 庙的 50 人，全是**同族两庙重复**（齐 ↔ 田齐/陈、楚 ↔ 魏…），
    #        齐宗庙那一长串 圉/燮/灵/孝… 都是正经国君 —— 动了就是破坏。
    #      · 共祭 **≥3** 庙的 25 人，才是全天下的**共同远祖**：
    #        巢皇/燧人/伏羲/少典… 共祭 8 庙，共工 17 庙，先牧 16 庙。
    #    所以判据取「共祭 ≥3 庙」（`shared_with` 记的是**别的**庙，故 +1）。
    #    这批人**不给封国、不给封代、不写世系** —— 他们不属于任何一国。
    for _rec in out.values():
        _rec["common_ancestor"] = (1 + len(_rec.get("shared_with") or ())) >= 3
    return out


def king_gen_of(code, lineage, memo=None):
    """宗庙内部的**真实世代**（沿牌位的 Father_Code 往上数）。

    宗庙牌位的 `Father_Code` 是**真父链**（实测秦宗庙从胡亥 2279 一路
    指到始祖风巢皇 60000 无一断裂），所以可以稳定推出世代 ——
    比 `Ren_Generations`（游戏显示编号，占位祖先也占号）可靠得多。

    占位祖先照样参与计数：它们代表「被省略的世代」，不数会让下面的人世代偏浅。
    返回 None 表示这个人不在任何宗庙里。
    """
    if memo is None:
        memo = {}
    seen = set()
    chain = []
    cur = str(code)
    while cur and cur in lineage and cur not in seen:
        if cur in memo:
            base = memo[cur]
            for j, x in enumerate(reversed(chain)):
                memo[x] = base + j + 1
            return memo[str(code)]
        seen.add(cur)
        chain.append(cur)
        fc = lineage[cur].get("father_code") or ""
        if fc in ("", "-1"):
            memo[cur] = 1                      # 始祖
            for j, x in enumerate(reversed(chain[:-1])):
                memo[x] = 2 + j
            return memo[str(code)]
        cur = fc
    if not chain:
        return None
    # 链断（父不在宗庙里）：退化成「祖先假定为 1」
    for j, x in enumerate(reversed(chain)):
        memo[x] = j + 1
    return memo[str(code)]


def load_states(src):
    """游戏里「谁属于哪个国」+ **每个国的爵位等级**。

    | 来源 | 是什么 | 覆盖 |
    |---|---|---|
    | 宗庙 / 国君表 | 真受封过的人（见 load_titles） | 少，但最硬 |
    | `Ren_Shi_Li_1` 字段 | 人物当前的**势力**（陈胜=张楚、刘邦=汉、田横=齐） | 只覆盖当代在世者 |
    | 族谱 → 家族 → 国 | **血统归属**：每个族谱有 `Genealogy_Code`，家族表用它换到 `King_Code`，再换到国名 | 历代祖先都算 |

    第三条是挖出来的：`Jia_Zu_Controller.Jia_Zu_Map[]` 每项带
    `King_Code` + `Jia_Shi` + `Ren_Ke_Data.Cheng_Yuan_Array`；
    `Save_KingData_*.json` 带 `King_Code` + `King_Name`。两边用 `King_Code` 对上，
    就得到「家族 → 国」「氏 → 国」。

    **国爵**（`King_Jue_Wei_Code`）是这一轮新增的关键：
    `Save_KingData_*.json` 每个国都带一个爵位等级，用的是**和人物爵位同一套编码**
    （`1=帝 3=王 4=公 5=侯 6=伯 7=子 53=卿`）。实测对得上：
    上古时代档 宋/秦=帝、风/雷/子=王、商/姌/姮=侯、巢/苗/鬼=伯；
    秦末档 秦=帝、沛=公（刘邦正是沛公）、张楚=王（陈胜正是张楚王）。

    这正好落实「**有国的肯定有爵位**」：拿国爵能反过来验证一个名字是不是国。

    返回 (人物→国, 氏→国（只留唯一对应）, 游戏认识的全部国名, 国→国爵)。
    """
    kc2guo = {}
    guo2jue = {}
    for f in sorted(glob.glob(os.path.join(src, "Save_KingData_*.json"))):
        o = _read(f)
        if isinstance(o, dict) and o.get("King_Code") is not None:
            nm = o.get("King_Name", "")
            kc2guo[o["King_Code"]] = nm
            if nm:
                guo2jue[nm] = JUE_CODE.get(o.get("King_Jue_Wei_Code"), "")
    all_guo = {g for g in kc2guo.values() if g}

    p = os.path.join(src, "Jia_Zu_Controller.json")
    fam = {}
    if os.path.exists(p):
        o = _read(p) or {}
        for z in o.get("Jia_Zu_Map") or []:
            fam[z.get("Code")] = z

    def guo_of_family(code):
        z = fam.get(code)
        return kc2guo.get(z.get("King_Code"), "") if z else ""

    guo_of_code, shi2guo = {}, defaultdict(set)
    for code, z in fam.items():
        g = guo_of_family(code)
        if not g:
            continue
        if z.get("Jia_Shi"):
            shi2guo[z["Jia_Shi"]].add(g)
        for c in (z.get("Ren_Ke_Data") or {}).get("Cheng_Yuan_Array") or []:
            guo_of_code.setdefault(str(c), g)
    for f in sorted(glob.glob(os.path.join(src, "Jia_Zu_Genealogy_*.json"))):
        o = _read(f)
        for g in (o if isinstance(o, list) else []):
            gun = guo_of_family(g.get("Genealogy_Code"))
            if not gun:
                continue
            shi = (g.get("Genealogy_Name") or "").split("氏")
            if len(shi) >= 2 and shi[0]:
                shi2guo[shi[0].split("姓")[-1]].add(gun)
            for r in g.get("Genealogy_Ren_Record_Array") or []:
                c = str(r.get("Ren_Code", ""))
                if c:
                    guo_of_code.setdefault(c, gun)
    # 一个氏只对应一个国才敢用；「姬」这种横跨魏韩燕鲁卫的不能硬归
    shi2guo = {k: next(iter(v)) for k, v in shi2guo.items() if len(v) == 1}
    return guo_of_code, shi2guo, all_guo, guo2jue


HISTORY_STATES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "history_states.json")


def load_history_states():
    """人工历史知识层：取「秦末实有」那一组（见文件内的完整说明）。

    为什么要单独一个文件、单独一段代码：**让「人工补的」和「从存档抽的」分得清**。
    游戏只为当前活跃的 151 个政权登记国爵，所以韩/汉/蔡/梁/西楚 这些
    「历史上是国、这盘已不是活跃国」的名字查不到爵位，按判据只能留空。
    这个文件把那一小批补回来，条目可手改、可删。

    返回 {国名: 爵位}。文件缺失或格式不对就返回空 —— 不影响主流程。
    """
    o = _read(HISTORY_STATES_FILE)
    if not isinstance(o, dict):
        return {}
    out = {}
    for name, v in (o.get("states_秦末实有") or {}).items():
        if isinstance(v, dict) and v.get("jue"):
            out[name] = v["jue"]
    return out


# ==================================================================== 小传

def make_bio(nm, rec, title, spouse_names, kid_names, is_hist_flag, female,
             dup=None, kin=("", "", 0), state_name="", fief_title=""):
    """把零散信息写成一段连贯的传记。

    原则：
      · 少用句号 —— 一个意思一句话，别把每个字段都断成独立短句
      · 不出现「（心性…，智略…）」这种括号堆数据的尾巴，改成正常行文
      · **写身份，不写谱系代数**：小传里「第几代」是噪音（而且跟「第几代国君」
        撞车），真正要说清的是 国君 / 公子 / 公孙 —— 见下 kin
      · **封国以调用方为准**（state_name / fief_title）：严格口径会把「氏」过滤掉，
        小传不能还用 title 里的原始名字，否则两面打架
      · ★ **爵位只在宗庙口径下才写**：`fief_title` 现在是「宗庙尊号推出的爵位」，
        非君主一律为空 —— 这一点由调用方保证（见 build 第 6 步）
      · 年份统一「前XXXX年」
      · 没信息的部分整句省掉，不留空壳
    """
    sents = []

    # ① 开篇：姓名 + 姓/氏（谱系第几代不写，见下方 ③ 的身份）
    xing = (rec.get("Ren_Xing") or "").strip()
    shi = (rec.get("Ren_Shi") or "").strip()
    if not shi:
        shi, xing = xing, ""
    if xing and shi and xing != shi:
        head = f"{nm}，{xing}姓{shi}氏"
    elif shi:
        head = f"{nm}，{shi}氏"
    else:
        head = nm
    if dup:
        idx, tot = dup
        head += f"（同名者共{tot}人，此为其{cn_num(idx)}）"
    sents.append(head + "。")

    # ② 生卒
    bw, dw = born_of(rec), died_of(rec)
    by = f"前{abs(bw)}年" if bw is not None else ""
    dy = ""
    if dw:
        p = str(dw).split(",")[0].strip()
        if p.lstrip("-").isdigit():
            y = int(p)
            dy = f"前{abs(y)}年" if y < 0 else f"{y}年"
    if by and dy:
        sents.append(f"约生于{by}，卒于{dy}。")
    elif by:
        sents.append(f"约生于{by}。")
    elif dy:
        sents.append(f"卒于{dy}。")

    # ③ 身份：国君 / 公子 / 公孙 / 公族 + 爵位 + 史实
    #    「某国第几代国君」才是这个游戏里真正的身份标签；血统上离那位国君
    #    几步就决定了叫 公子/公孙，再远的旁支统称公族。
    #    ★ 这条链是**纯父系**，所以必然落在同一座宗庙内 —— 与「世系只认宗庙」
    #      的口径天然一致（非君族的人 kinship 返回空，不会硬塞一个国给他）。
    kind, kguo, kgen = kin
    kguo = guo_name(kguo)
    # 用调用方定好的 state_name / fief_title，而不是 title 里的原始值 ——
    # 严格口径下「项」这类氏会被过滤掉（不是国），小传必须跟着留空，
    # 否则会出现「封国栏是空、小传却写受封于项国」的自相矛盾。
    guo, jue = state_name, fief_title
    mid = ""
    # ★★ 2026-09-25 恢复「第 N 代」—— 上一版删掉它，是因为当时的数字来自
    #   `_real_depth`（**家族父链上的真人个数**），不可信：熊心被写成
    #   「熊国第八十代国君」，而它 −208 年才受封。
    #   现在 `fief_gen` 换成**牌位自带的 `Generations`**（游戏给的「本封国
    #   第几代」，也就是使用者要的「从分封第一代开始算起」），数字可信了，
    #   写出来才有信息量：嬴政 = 秦国第三十代、熊心 = 熊国第一代。
    #   `kgen == 0` = **受封之前的同族先王**（如熊宗庙里的熊槐）—— 他是这家
    #   的人、有爵位，但不是本封国的世代，所以只说国君、不提代数。
    _gen = f"第{cn_num(kgen)}代" if kgen else ""
    if kind == "国君":
        mid = f"为{guo_name(guo) or kguo}{_gen}国君"
        if jue:
            mid += f"，爵为{jue}"
    elif kind == "公子":
        mid = (f"为{kguo}{_gen}国君之女" if female
               else f"为{kguo}{_gen}国君之子，公子")
    elif kind == "公孙":
        mid = (f"为{kguo}{_gen}国君之孙女" if female
               else f"为{kguo}{_gen}国君之孙，公孙")
    elif kind == "公族":
        mid = f"为{kguo}公族"
    elif guo and jue:
        # 兜底：有宗庙爵位却不在任何国君世系上
        mid = f"受封于{guo_name(guo)}，爵为{jue}"
    if is_hist_flag:
        mid = (mid + "，") if mid else ""
        mid += "史传有载"
    if mid:
        sents.append(mid + "。")

    # ④ 婚育（男曰娶、女曰适）
    wed = ""
    if spouse_names:
        wed = ("娶" if not female else "适") + "、".join(spouse_names[:3])
    if kid_names:
        wed += ("，" if wed else "") + \
               ("有子" if not female else "生子") + "、".join(kid_names[:3])
    if wed:
        sents.append(wed + "。")

    # ⑤ 品性：心性 / 智略 / 所学 —— 正常行文，不再塞括号
    # 流派字段混了两种取值：地名（江淮/河汾/川峡）与学派（道家/兵家）。
    # 「学在道家」不通，所以按有没有「家」字分两种说法。
    traits = []
    xg = (rec.get("Ren_Xing_Ge") or "").strip()
    zh = rec.get("Ren_Zhi_Lue")
    wh = (rec.get("Ren_Wen_Hua") or "").strip()
    if xg:
        traits.append(f"性{xg}")
    if zh is not None:
        traits.append(f"智略{zh}")
    if wh:
        traits.append(f"宗{wh}" if wh.endswith("家") else f"学在{wh}")
    if traits:
        sents.append("，".join(traits) + "。")

    return "".join(sents)


def in_year(raw):
    """'-2488,12,0' → '公元前2488年'；没法解析就原样返回。"""
    p = str(raw).split(",")[0].strip()
    if p.lstrip("-").isdigit():
        y = int(p)
        return f"公元前{abs(y)}年" if y < 0 else f"{y}年"
    return str(raw)


# ==================================================================== 主流程

def build(src, seeds=None, prune="none", real_state=False, history=True,
          watch=None):
    """整档抽取。

    `watch` = 续谱名单（存档编号）。使用者口径：「除了史实人物全部摘录进来以外，
    只有我选定的某个或某几个非史实人物才需要续其谱系，其他的非史实人物则可以
    一直忽略不计」—— 所以名单里的人和他们的**父系后裔链**会被额外收进来。

    返回 `(people, stats, name2code, gen_src)`：
      people    —— {姓名: 记录}，记录里带 `code`（存档编号）
      stats     —— 统计
      name2code —— {姓名: 存档编号}
      gen_src   —— {存档编号: 世代来源}（父链 / 生年落桶 / 接回始祖）
    """
    print("  读取人物各表：")
    by_code = load_tables(src)
    print(f"  合并去重后 {len(by_code)} 人")

    # ---- 1. 有后裔 & 筛选 ----
    kids_code = Counter()
    kids_name = Counter()
    for c, r in by_code.items():
        fc = str(r.get("Father_Code") or "")
        if fc:
            kids_code[fc] += 1
        par = (r.get("Parent") or {}).get("Father") or {}
        v = str(par.get("Ren_Code") or "").strip()
        if v:
            kids_code[v] += 1
        v2 = str(par.get("Ren_Name") or "").strip()
        if v2:
            kids_name[v2] += 1

    def has_kid(c):
        return bool(kids_code.get(c)) or bool(kids_name.get(name_of(by_code[c])))

    core = {c for c, r in by_code.items() if r.get("_tbl") == "族谱表"}
    # 占位祖先要剔掉，两类：
    #   ① `始祖XX` —— 游戏为「让族谱有个根」硬造的占位始祖，名字是尊号不是人名
    #      （写「巢皇」，其实指「风巢皇」；写「华胥」，其实指「姒华胥」）。
    #      真人另有数字 Code 的记录在册，所以这些一律不取。
    #   ② Code 和名都带「父/祖/曾/高」的，是游戏为凑显示世代造的假人
    #      （如 Code=100000005父 / 名=「风武亥父」）。
    #   ③ Code 带后缀、但记录只有「编号 + 名字」两个字段（无性别）的，同样是假人
    #      —— 这批的名是**像样的名字**（Code=100000202父 / 名=「风瞿皇」），
    #      光看名字认不出来，要看**记录形状**（见下面 _is_ph 的说明）。
    # 但有两类必须留：
    #   · Code 带后缀而记录是**完整的**（有性别 / 生年）—— 真祖先
    #   · 史实人物 —— 「嫫祖」「圭祖」这类真名本身就以「祖」结尾，会被误杀
    def _is_ph(c):
        if is_placeholder_ancestor(c):
            return True
        if is_hist(c):
            return False
        if not PLACEHOLDER_SUFFIX.search(c):
            return False
        r = by_code[c]
        # ★ 2026-09-24 修「最新档刚开局，风巢皇就有 20 个儿子」（满天星斗档实测）：
        #   游戏为凑够族谱**显示世代**，会给每个人凭空补一串「某某父/祖/曾/高」
        #   的占位祖先。其中一批**只有编号带后缀、名却是像样的名字**
        #   （Code=100000202父 / 名=「风瞿皇」），原来「编号和名都带后缀才算假人」
        #   的判据把这类全放过了 —— 它们又照族谱表的 `Father_Code` 挂在始祖名下，
        #   画布上就凭空多出 18 个儿子（风巢皇实际只有 2 个：其
        #   `Ren_Zi_Nv_Code_Array` = [60816, 60001]，人物表里 `Parent.Father`
        #   指向 60000 的也正好只有这 2 人）。
        #   决定性判据是**记录的形状**：这些占位祖先在人物表里只有
        #   {Ren_Code, Ren_Name} 两个字段（无性别 / 无生年 / 无相貌），而真人
        #   一律带 `Ren_Sex`。三个档实测：完整记录（>4 字段）里缺 Ren_Sex 的
        #   **0 条**（5618 + 3458 + 1124），而编号带父/祖/曾/高的记录
        #   **100% 缺 Ren_Sex**（888 + 56 + 288）—— 零误杀。
        if "Ren_Sex" not in r:
            return True
        return bool(PLACEHOLDER_SUFFIX.search(str(r.get("Ren_Ming", ""))))

    ph = {c for c in core if _is_ph(c)}
    core -= ph
    extra = {c for c, r in by_code.items()
             if r.get("_tbl") != "族谱表" and c not in ph
             and (is_hist(c) or (not is_female(r) and has_kid(c)))}
    keep = core | extra
    # （减号用 ASCII —— U+2212 在 GBK 管道下 print 会 UnicodeEncodeError）
    print(f"  族谱表 {len(core) + len(ph)} 人 - 占位祖先 {len(ph)} 人（全要） "
          f"+ 额外三表筛选后 {len(extra)} 人 = {len(keep)} 人")

    # ---- 1b. 续谱名单：点名要收的人 + 其父系后裔链 ----
    # 使用者的口径：非史实人物默认一个都不要，**只有我点名的**才收，
    # 而且要收的是「他这一支」（父系单传，与 D11 一致；女儿作为叶子收进来、
    # 不再往下传）。所以这里只沿 Father_Code 走。
    # ★ 2026-09-21 使用者明确「后裔纯父系，不含女儿支」——
    #   下面的 kids_map 走的就是 Father_Code，与这条一致，无需再改。
    watch_keep = set()
    if watch:
        kids_map = defaultdict(list)
        for _c, _r in by_code.items():
            # ★ 2026-09-24：**占位祖先一律不参与父系后裔链**。
            #   否则「修判据」白修 —— 上面 core 里剔掉的假人，会被这条链
            #   从 by_code 里原样捞回来（实测风巢皇那 18 个假儿子照旧出现）。
            #   它们既不当孩子（_c），也不当父辈（_fc）：一条挂在始祖名下的
            #   占位祖先会把「始祖的儿子」凭空造出来。
            if _c in ph:
                continue
            _fc = str(_r.get("Father_Code") or "").strip() or str(
                ((_r.get("Parent") or {}).get("Father") or {}).get("Ren_Code") or "").strip()
            if _fc and _fc not in ph:
                kids_map[_fc].append(_c)
        added = set()
        named_hit = []
        for _w in watch:
            _w = str(_w).strip()
            if not _w or _w not in by_code:
                continue
            named_hit.append(_w)
            stack, seen = [_w], set()
            while stack:
                x = stack.pop()
                if x in seen:
                    continue
                seen.add(x)
                added.add(x)
                stack.extend(kids_map.get(x, []))
        # ★ 2026-09-21 修：`watch_keep` 必须收**点名的人 + 他整条父系后裔链**，
        #   不能先 `-= keep` 再算 —— 那样「本来就在 keep 里」的点名者会被排除在外，
        #   随后 `--prune hist` 一剪（keep = 只留史实）就把他一起剪掉了，
        #   实测点名 3 人只剩 1 人活下来。
        #   现在：`new_ones` 只用来报「多收了几个人」，`watch_keep` 收全部。
        new_ones = added - keep
        keep |= added
        if added:
            print(f"  续谱名单：点名 {len(watch)} 人（命中 {len(named_hit)}）"
                  f" → 连同父系后裔多收 {len(new_ones)} 人"
                  f"（其中史实 {sum(1 for c in new_ones if is_hist(c))}）")
        watch_keep = {c for c in added if c in by_code}

    # ---- 1c. 补回「只被引用、没有本人记录」的祖先（2026-09-25 使用者点名）----
    #   起因：使用者问「穆王巡游的族谱存档**没有风女娲**？」
    #   查证结论：女娲在本档里**根本没有本人记录** —— 她只以
    #   `Mother_Code / Mother_Name` 的形式被引用（全档 60 处，父亲是风伏羲、
    #   儿子是风少典）。而 `resolve_parent` 要求父母**在 keep 里**才认，
    #   所以这类人永远进不了谱。
    #   实测**每个档都恰好只有 2 位**这样的祖先，且**风女娲(60038) 三个档全有**
    #   （另一个是 姒女蟜 61138，或 姬穆 70819）—— 缺口小而稳定，值得补。
    #   这里按**存档原文里的名字**给她们补一条最小记录（不猜任何其它字段）。
    #   ⚠️ 编号不含 父/祖/曾/高 ⇒ `is_book_placeholder` 不会把他们当占位空壳清掉。
    #   ⚠️ 性别只在「只被当母亲引用」时才记女（走女性表那条判据，见 `is_female`）。
    _ref_f, _ref_m = {}, {}
    for _c in keep:
        _rec = by_code[_c]
        for _rc, _rn, _dst in (("Father_Code", "Father_Name", _ref_f),
                               ("Mother_Code", "Mother_Name", _ref_m)):
            _pc = str(_rec.get(_rc) or "").strip()
            _pn = str(_rec.get(_rn) or "").strip()
            if _pc and _pc != "-1" and _pn and _pc not in keep:
                _dst.setdefault(_pc, _pn)
    _syn = set()
    for _pc in set(_ref_f) | set(_ref_m):
        if _pc in by_code:
            continue            # 有本人记录（只是没进 keep）→ 不动，交给既有逻辑
        _pn = _ref_m.get(_pc) or _ref_f.get(_pc)
        _r = {"Ren_Code": _pc, "Ren_Name": _pn, "_synth": True}
        if _pc in _ref_m and _pc not in _ref_f:
            _r["_tbl"] = "女性表"
        by_code[_pc] = _r
        keep.add(_pc)
        _syn.add(_pc)
    if _syn:
        print(f"  补回「只被引用、无本人记录」的祖先 {len(_syn)} 人："
              f"{'、'.join(by_code[c]['Ren_Name'] for c in sorted(_syn))}")

    # ---- 2. 父母（Code 优先；回退到名字，只在唯一时） ----
    name2codes = defaultdict(list)
    for c in keep:
        name2codes[name_of(by_code[c])].append(c)

    def resolve_parent(rec):
        parts = []
        for k, ck in (("Father_Code", "Father"), ("Mother_Code", "Mother")):
            fc = str(rec.get(k) or "").strip()
            parts.append(fc if fc in keep else "")
        if not any(parts):
            par = rec.get("Parent") or {}
            for i, key in enumerate(("Father", "Mother")):
                if parts[i]:
                    continue
                d = par.get(key) or {}
                rc = str(d.get("Ren_Code") or "").strip()
                if rc in keep:
                    parts[i] = rc
                else:
                    rn = str(d.get("Ren_Name") or "").strip()
                    cs = name2codes.get(rn) or []
                    if len(cs) == 1:
                        parts[i] = cs[0]
        return parts[0], parts[1]

    father_get = {c: resolve_parent(by_code[c])[0] for c in keep}
    mother_get = {c: resolve_parent(by_code[c])[1] for c in keep}

    # ---- 3. 名字（氏+名；重名缀中文序数） ----
    titles_all = load_titles(src)      # 重名排序要看有没有爵位，先读出来
    base = {c: name_of(by_code[c]) for c in keep}
    groups = defaultdict(list)
    for c, n in base.items():
        groups[n].append(c)

    # 重名：名字后面**不加解释性后缀**，只缀一个中文序数（一/二/三…），
    # 同时在传记里点明「同名者共几人、此为其几」。
    # 存档结构是 {姓名: 记录}，同名会互相覆盖，所以必须靠这个序数区分开。
    def _rank(c):
        r = by_code[c]
        jue = bool(pick_title(titles_all.get(name_of(r)),
                              r.get("Ren_Generations")).get("jue"))
        # 排首位的是「史实 → 有爵位 → 生年早」，它保留不带序数的原名
        return (not is_hist(c), not jue, born_of(r) or 0, str(c))

    final, bios_name, dup_info, dup_names = {}, {}, {}, 0
    for n, cs in groups.items():
        if len(cs) == 1:
            final[cs[0]] = n
            continue
        dup_names += len(cs)
        order = sorted(cs, key=_rank)
        for i, c in enumerate(order):
            # 都缀序数（风会胜1 / 风会胜2），只给后面几个缀会读成「第一个叫风会胜、
            # 第二个叫风会胜1」，反而串了。传记开头用不带序数的本名。
            # ★ 序数是**纯数字**（使用者 2026-09-22 要求），渲染层会把它缩成
            #   小号灰字贴在名字最后一字的**右上角**（像幂）。
            final[c] = n + dup_num(i + 1)
            bios_name[c] = n
            dup_info[c] = (i + 1, len(order))

    # ---- 4. 世代：始祖按出生年落桶，其余 = 父亲 + 1 ----
    anc = ancestor_codes(src)
    anc_of = ancestor_of_code(src)

    def is_ph(c):
        return bool(PLACEHOLDER_SUFFIX.search(str(c or "")))

    gen = {}
    # ★ 世代是**怎么定出来的** —— 增量续谱时要靠它决定信不信新抽的世代：
    #   只有「父链」「生年落桶」两种来源才允许覆盖谱牒里已有的世代，
    #   兜底来源（接回始祖）保留原值，免得每次续谱都把手工排好的代数推歪。
    gen_src = {}
    for c in keep:
        if c in anc:
            y = born_of(by_code[c])
            if y is not None:
                gen[c] = bucket_gen(y)
                gen_src[c] = "生年落桶"
    # 有 8 个始祖自己没记生年（22 个里只有 14 个能直接锚定），
    # 于是它下面的整支都接不上。用「该族谱里最年长的成员的生年」当代理 ——
    # 始祖本来就是这一支里最早的人。
    zu_of = defaultdict(list)
    for c in keep:
        a = anc_of.get(c)
        if a:
            zu_of[a].append(c)
    for a in anc:
        if a in gen or a not in keep:
            continue
        years = [born_of(by_code[c]) for c in zu_of.get(a, [])]
        years = [y for y in years if y is not None]
        if years:
            gen[a] = bucket_gen(min(years))
            gen_src[a] = "生年落桶"
    print(f"  始祖锚定 {len([a for a in anc if a in gen])} / {len(anc)} 个")

    # 依次三招定代（优先级从可靠到近似）：
    #   ① 父亲 +1（最可靠，游戏父子链是真的）
    #   ② 自己出生年落桶（父辈是占位祖先、链断了时用；占位链代表"被省略的世代"，
    #      步数并不等于你树里压缩后的代数，所以按生年更接近你的排法）
    #   ③ 接回该族谱始祖 +1（连生年都没有时才用，兜底）
    unresolved = [c for c in keep if c not in gen]
    for _ in range(12):
        changed = False
        for c in unresolved:
            if c in gen:
                continue
            f = father_get[c] or mother_get[c]
            if f and f in gen:
                gen[c] = gen[f] + 1
                gen_src[c] = "父链"
                changed = True
        if not changed:
            break
    chained = len([c for c in unresolved if c in gen])

    rest = [c for c in unresolved if c not in gen]
    fallback = 0
    for c in rest:
        y = born_of(by_code[c])
        if y is not None:
            gen[c] = bucket_gen(y)
            gen_src[c] = "生年落桶"
            fallback += 1

    rest = [c for c in rest if c not in gen]
    relinked = 0
    for c in rest:
        r = by_code[c]
        fc = str(r.get("Father_Code") or "")
        if not fc:
            fc = str(((r.get("Parent") or {}).get("Father") or {}).get("Ren_Code") or "")
        if fc and is_ph(fc) and fc not in keep:
            a = anc_of.get(c)
            if a and a in gen and a != c:
                gen[c] = gen[a] + 1
                gen_src[c] = "接回始祖"
                relinked += 1

    # ★ 2026-09-25：上面 1c 补回的祖先**没有生年、父链也空**，若不管，
    #   会被下面的「时代兜底」塞到**本档时代**那一代（女娲本该在最顶上 ——
    #   她丈夫风伏羲、儿子风少典都在前 26 世纪那一排）。
    #   她们唯一可靠的锚点是**儿女**（母亲 Code → 儿女的世代 − 1）。
    #   ⚠️ 必须放在 `unresolved` 那句**之前** —— 否则「时代兜底」会按**早就算好的
    #      旧名单**把这里刚定出来的世代覆盖掉（第一版就是这么写错的：
    #      回推确实跑了 2 人，但结果仍是兜底的 66/97 代）。
    #   ⚠️ 反查要**父母各查一次** —— 只查「父优先的那一个」会漏掉母亲这一侧
    #      （风少典的父是风伏羲，于是永远找不到女娲）。
    _syn_kids = {}
    if _syn:
        _kids_of = defaultdict(list)
        for _c in keep:
            for _p in (father_get.get(_c), mother_get.get(_c)):
                if _p:
                    _kids_of[_p].append(_c)
        _n = 0
        for _c in _syn:
            _kc = list(_kids_of.get(_c, []))
            _syn_kids[_c] = _kc
            _ks = [gen[k] for k in _kc if k in gen]
            if _ks:
                gen[_c] = max(1, min(_ks) - 1)
                gen_src[_c] = "按儿女回推"
                _n += 1
        if _n:
            print(f"  补回的祖先按儿女回推世代 {_n} 人")

    unresolved = [c for c in keep if c not in gen]
    print(f"  世代：① 父子链 {chained} 人 · ② 出生年 {fallback} 人 · "
          f"③ 接回始祖 {relinked} 人 · 定不出来 {len(unresolved)} 人")

    # ★ 2026-09-22 修「为什么到秦末汉初还有人能排到第一代去」。
    #   原来这 75 人是**不填**的，最后由 `"generation": max(1, gen.get(c, 1))`
    #   兜成第 1 代 —— 于是卫氏朝鲜档（前 194）里那批没生年、父链也接不上的人，
    #   在画布上全挤到最顶端那一排，跟上古始祖并排。
    #   现在改成按**这个存档的时代**兜底：读剧本开局年落桶（前 194 → 第 97 代），
    #   和同档里有生年的人落在同一层。读不到开局年就退到「已定世代的中位数」。
    #   来源标「时代兜底」——**不在 GEN_TRUSTED 里**，续谱时不会拿它去覆盖
    #   使用者手工排好的代数（与「接回始祖」同一待遇）。
    if unresolved:
        anchor_year = detect_start_year(src)
        if anchor_year is None:
            vals = sorted(gen.values())
            anchor = vals[len(vals) // 2] if vals else 1
            why = "已定世代中位数"
        else:
            anchor = bucket_gen(anchor_year)
            why = f"开局年 {anchor_year}"
        for c in unresolved:
            gen[c] = anchor
            gen_src[c] = "时代兜底"
        print(f"  （定不出来的 {len(unresolved)} 人按存档时代兜底 → 第 {anchor} 代"
              f"，依据：{why}）")

    # ---- 4c. 始祖限定 + 三条入谱规则 ----
    # 你说过：树小是因为「只有选定的始祖才往下谱写」。所以这里分两步 ——
    #   1) 只保留这些始祖的父系后裔
    #   2) 后裔里再按三条规则筛：
    #        ① 有爵位 → 必入谱
    #        ② 无爵、又无男性后裔的男性 → 不入谱（= 把不能延续香火的枝端剪掉）
    #        ③ 史实 → 必入谱
    # 效果上就是「剪叶子」：把没名气又断了香火的枝端去掉，主干和名人全留。
    def has_jue(c):
        r = by_code[c]
        return bool(pick_title(titles_all.get(name_of(r)),
                               r.get("Ren_Generations")).get("jue"))

    sons = defaultdict(list)
    for c in keep:
        f = father_get[c]
        if f:
            sons[f].append(c)

    def has_male_son(c):
        return any(not is_female(by_code[s]) for s in sons.get(c, []))

    # seeds 是姓名（从参考存档的根节点读来的），这里要换成 Code 才能比对
    seed_codes = []
    for s in (seeds or []):
        for c in name2codes.get(s, []):
            if c in keep and c not in seed_codes:
                seed_codes.append(c)
    if prune == "hist":
        # 只收史实人物（试用新开局时的口径：其余几千个程序生成的路人一概不要）。
        # 这里不做始祖限定 —— 史实人物本来就横跨所有支系，再按始祖砍一刀是多余的。
        keep_line = {c for c in keep if is_hist(c)}
        print(f"  只收史实人物：{len(keep)} 人 → {len(keep_line)} 人")
        keep = keep_line
    elif seed_codes:
        desc, stack = set(), list(seed_codes)
        while stack:
            x = stack.pop()
            for ch in sons.get(x, []):
                if ch not in desc:
                    desc.add(ch)
                    stack.append(ch)
        line = set(seed_codes) | desc

        # 始祖后代里怎么剪，由 --prune 决定：
        #   anon（默认）不剪男性；只把「非史实、又无爵位」的女性挡在谱外
        #              —— 你说过「只有史实女角色才写上」
        #   none      谁都收（会把大量无名女性也灌进来，只适合做全集备查）
        #   male-son  额外剪掉「无爵位 + 无男性后裔 + 非史实」的男性（你说这条不要）
        keep_line = set(line)
        if prune != "none":
            keep_line = {c for c in line
                         if not is_female(by_code[c]) or has_jue(c) or is_hist(c)}
        if prune == "male-son":
            keep_line = {c for c in keep_line
                         if has_jue(c) or is_hist(c)
                         or (not is_female(by_code[c]) and has_male_son(c))}
        # 规则③「史实必入谱」是硬规则：史实人物不管属不属于选定始祖的父系，
        # 一律收进来。少了这一步会漏掉 11 个（始祖农皇/凤后/华胥/嫫祖/巢皇/
        # 幽泉/羲皇 + 姒明先/姒系居/幽泉/姑浦湜 —— 他们所在的氏不在种子支系里）。
        hist_all = {c for c in keep if is_hist(c)}
        keep_line |= hist_all

        # 嫁出去但本身有名的（史实/有爵位）也收进来
        for c in keep - line:
            if has_jue(c) or is_hist(c):
                p = father_get[c] or mother_get[c]
                if p in keep_line:
                    keep_line.add(c)
        print(f"  始祖 {len(seed_codes)} 个 → 父系后裔 {len(line)} 人 → "
              f"剪枝方式 [{prune}] + 史实必入(+{len(hist_all)}) 后留 {len(keep_line)} 人")
        keep = keep_line
    else:
        print("  （未指定始祖，跳过始祖限定）")

    # ★ 续谱名单**必须活过剪枝**：上面 `prune=hist` 那一步是
    #   `keep = {c for c in keep if is_hist(c)}`，会把点名的非史实人物全砍掉 ——
    #   而「点名要收他这一支」正是这份名单存在的理由。
    if watch and watch_keep:
        back = watch_keep - keep
        if back:
            keep |= back
            print(f"  续谱名单不参与剪枝：把 {len(back)} 人放回名单")

    # ---- 4b. 补父子连线 ----
    # 上一轮剪枝 + 剔除占位祖先后，有些人的父辈不在最终名单里了 ——
    # 世代已经算好，但 father 空着画出来会散成几百个孤零零的根。
    # 沿父系往上找到最近一个还在名单里的祖先接上，保证树连通。
    lifted = 0
    for c in keep:
        if father_get[c] in keep or mother_get[c] in keep:
            continue
        cur, hops = father_get[c] or mother_get[c], 0
        while cur and hops < 60:
            nxt = father_get.get(cur) or mother_get.get(cur)
            if nxt in keep:
                father_get[c] = nxt
                lifted += 1
                break
            cur, hops = nxt, hops + 1
    print(f"  补回父子连线：{lifted} 人上溯到最近的祖先")

    # ---- 4c. 续谱名单：根节点排最前 + 代数取「同龄史实中位数」 ----
    # 使用者 2026-09-21 口径（原话）：
    #   「我所选定的非史实角色入谱后在画布上的根节点排在最靠前，按照我选定的顺序排序，
    #     他们的代数看史实角色同龄（加减 3 岁）人代数的中位数确定」
    #   「如果加减三岁一个史实人物都没有，那么就加减 10 岁直到有史实人物」
    #   「（中位数算完要服从父链）可以」
    #
    # 所以：
    #   ① `root_sort` 按**名单顺序**给 1、2、3…（`layout.get_root_sort_key` 里
    #      正数优先，所以这批人自动排在所有史实根节点之前）
    #   ② 代数 = 同龄**史实人物**代数的中位数；窗口 3 → 10 → 20 → 30… 逐级放大
    #      直到取到样本（一个人都没有时不动，留 4d 的父链结果）
    #   ③ 「服从父链」由下面的 4d 统一保证 —— 这里只写 `gen`，
    #      父亲若在册，4d 会把它改回「父亲 + 1」，正是使用者要的优先级
    #   只对**点名的本人**生效；他们的后裔照旧「父亲 + 1」，不必各算各的。
    watch_ordered = [c for c in (str(x).strip() for x in (watch or [])) if c in keep]
    root_sort_of = {c: i + 1 for i, c in enumerate(watch_ordered)}

    def _median(vals):
        s = sorted(vals)
        n = len(s)
        if not n:
            return None
        mid = n // 2
        return float(s[mid]) if n % 2 else (s[mid - 1] + s[mid]) / 2.0

    hist_gen = []
    for c in keep:
        if not is_hist(c):
            continue
        y = born_of(by_code[c])
        if y is not None:
            hist_gen.append((y, gen.get(c, 1)))

    median_used, no_sample = 0, []
    for c in watch_ordered:
        y = born_of(by_code[c])
        if y is None or not hist_gen:
            no_sample.append(name_of(by_code[c]))
            continue
        delta = 3
        pick = [g for (hy, g) in hist_gen if abs(hy - y) <= delta]
        while not pick and delta < 2000:
            delta = 10 if delta < 10 else delta + 10      # 3 → 10 → 20 → 30 …
            pick = [g for (hy, g) in hist_gen if abs(hy - y) <= delta]
        if not pick:
            no_sample.append(name_of(by_code[c]))
            continue
        med = _median(pick)
        gen[c] = max(1, int(round(med)))
        gen_src[c] = "同龄史实中位数"
        median_used += 1
    if watch_ordered:
        print(f"  续谱名单：{len(watch_ordered)} 位点名人物按选定顺序排最前（root_sort 1…）；"
              f"其中 {median_used} 位按「同龄史实中位数」定代"
              + (f"；{len(no_sample)} 位没有同龄史实样本（{'、'.join(no_sample[:5])}）"
                 if no_sample else ""))

    # ---- 4d. 世代与父子链对齐 ----
    # 为什么必须做：树形布局的 y 坐标**直接就是 generation**
    # （layout.calc_depth 里 depth[person] = generation），父子必须分层、父在上。
    #
    # ★ 这里用「父子链 +1 主导」而不是「生年主导」，是实测选出来的，不是随手写的：
    #   使用者手写的 488 人里，能对上游戏的 411 人 —— 用本算法世代一致 408/411（99%）；
    #   换成「按生年落桶」只有 296/411（72%），而且用他的数据反过来校准桶心也只到 58%。
    #   原因：**「代」是谱系深度，天生不等于时间**。同一代的人生年能差几百上千年
    #   （游戏里 14 岁就能生子，各支系繁衍速率差很多）。实测：
    #     · 本算法       秦末档同层生年平均跨度 452 年
    #     · 生年主导算法  75 年（但代价是与使用者手写只剩 72% 一致）
    #     · **游戏自己的 Ren_Dai_Shu 也是 277 年**（85 层里最宽一层跨 383 年）
    #   所以「代 ≠ 年」是这个游戏的设定，不是算法缺陷。纵轴要按时间画的话，
    #   得另外做（见设计中「时间轴视图」一节），不能用 generation。
    #
    #   使用者的口径原文也支持这个顺序：「没有生年，只看他出现在游戏里的大致时间，
    #   跟着父亲加 1 代」—— 先父子、再谈时间。
    parent_of = {c: (father_get.get(c) or mother_get.get(c)) for c in keep}
    kids_of = defaultdict(list)
    for c in keep:
        if parent_of[c] in keep:
            kids_of[parent_of[c]].append(c)
    queue = deque(c for c in keep if parent_of[c] not in keep)
    done = set()
    while queue:
        x = queue.popleft()
        if x in done:
            continue
        done.add(x)
        gx = gen.get(x, 1)
        gen[x] = gx
        for ch in kids_of.get(x, []):
            if ch not in done:
                gen[ch] = gx + 1
                queue.append(ch)
    bad = sum(1 for c in keep
              if parent_of[c] in keep and gen.get(c) != gen[parent_of[c]] + 1)
    # 4d 的对齐会把「父在册」的人统一改成「父 +1」—— 这类人的世代来源就是父子链，
    # 不管它先前是落桶还是接始祖定出来的。
    for c in keep:
        if parent_of.get(c) in keep:
            gen_src[c] = "父链"
    print(f"  世代与父子链对齐：不一致 {bad} 人")

    # ---- 5. 爵位 / 封国 ----
    titles = load_titles(src)

    # ★★ 君主世系（宗庙真相源）—— 「X国世系」的**唯一**判据 ★★
    #
    # 使用者原话：「不是在某国出仕或在某国的城市就有世系，必须是该国君主的家族」。
    # 之前用的是「氏→国 + 父系继承」，那是**户籍口径**，会把
    #   任敖（刘邦御史大夫）→ 汉王、灌婴（汉功臣）→ 汉王、
    #   严阙（秦臣）→ 秦帝、蔺康（赵国大夫）→ 燕王
    # 全部冤枉成王族。现在换成宗庙口径：
    #   进了这家祖庙 = 是这家的人（`Memorial_Ren_Now_King_Name` 实测 1487/1487 一致）。
    lineage = load_king_lineage(src)
    lin_real = {c: v for c, v in lineage.items() if not v["is_placeholder"]}
    print(f"  宗庙牌位 {len(lineage)} 张（真人 {len(lin_real)} · "
          f"占位祖先 {len(lineage) - len(lin_real)}）· "
          f"涉及 {len({v['guo'] for v in lin_real.values()})} 个国有真实世系")
    # 尊号继承缓存（胡亥无尊号 → 承父「始皇」为帝）
    rank_memo = {}

    def king_rank(c):
        """这个人由宗庙推出的**真实爵位**（皇帝 / 王 / 公 / …）。

        空字符串 = 他不是君主，或尊号里没有爵位信息（如「西陲大夫」「秦嬴」）。
        """
        v = lineage.get(c)
        if v is None:
            return ""
        return inherit_rank(c, lineage, rank_memo)

    # 氏 → 国 映射（**降级为兜底**，只在没有宗庙记录时才用）。
    # 不是即位的国君就没有宗庙牌位，之前退而拿「氏」当封国，结果同一国被拆成两个世系框
    # （方雷亚明 氏=方雷 → 封国「方雷」，可他明明是雷国的人）。
    # 这里从宗庙反推：某个氏只在一个国做过君主，就把该氏的人归到那个国。
    # 「风」这种跨多国的氏（风、雷、巢都有）则不硬归，保持原样。
    shi2guo = defaultdict(set)
    for _cands in titles.values():
        for _t in _cands:
            if _t.get("guo") and _t.get("shu"):
                shi2guo[_t["shu"]].add(_t["guo"])
    shi2guo = {k: next(iter(v)) for k, v in shi2guo.items() if len(v) == 1}

    # 真封国的另外两条实录链路：势力字段 + 族谱→家族→国
    guo_of_code, clan_shi2guo, all_guo, guo2jue = load_states(src)
    print(f"  真封国来源：族谱/家族 {len(guo_of_code)} 人 · 家族氏→国 {len(clan_shi2guo)} 条 · "
          f"游戏认识的国 {len(all_guo)} 个 · 有国爵的 {sum(1 for j in guo2jue.values() if j)} 个")
    # 人工历史知识层（可关）：补上「历史上是国、游戏未登记」的那一小批
    hist_states = load_history_states() if (real_state and history) else {}
    if hist_states:
        print(f"  史补国名 {len(hist_states)} 个（人工知识层，非存档抽取）："
              f"{'、'.join(sorted(hist_states))}")

    # ---- 6. 配偶 / 子女 ----
    # 先把每人的封国/爵位算好（国君身份和写小传都要用），避免重复查表
    t_of = {c: pick_title(titles.get(name_of(by_code[c])),
                          by_code[c].get("Ren_Generations")) for c in keep}
    # ★ king_of 只认**宗庙**：这个人是哪一国的第几代君主。
    #   不再用 pick_title 的 fief_gen（那是「同一姓名在国君表里排第几」，
    #   跟宗庙的世代序号不是一回事，而且极易被同名远祖污染）。
    #   ★ 2026-09-24：共同远祖不算「某国君主」—— 否则小传会写
    #     「为秦国第一代国君」（使用者报的就是这一句）。
    king_of = {}
    for c in keep:
        v = lineage.get(c)
        # ★ 2026-09-25：判据同样**去掉 `fief_gen`**（改成庙籍）。旧口径下这个
        #   门闸恒真，所以「谁是国君」的判定逐人不变；而封代改真以后，
        #   受封之前的同族先王封代是 0 —— 若还拿它当门闸，他们的子孙就再也
        #   认不到「国君」，「公子 / 公孙」的身份会整片塌掉。
        #   封代为 0 的先王在文案里只说「为X国国君」，不带「第N代」（见 make_bio）。
        if v and not v["is_placeholder"] and not v.get("common_ancestor"):
            king_of[c] = (v["guo"], v.get("fief_gen") or 0)

    def kinship(c):
        """这个人离最近的国君有多远 —— 小传的身份标签就靠它。

        国君本人 → 国君；父亲是国君 → 公子；祖父是国君 → 公孙；
        再往下的旁支后人统称公族。**不**往「第N代国君的M世孙」上继续数：
        那正是「第几代人不重要」里说的那种噪音。
        """
        if c in king_of:
            return ("国君",) + king_of[c]
        cur, d, seen = father_get.get(c), 0, set()
        while cur and cur not in seen and d < 15:
            seen.add(cur)
            d += 1
            if cur in king_of:
                g, n = king_of[cur]
                return ("公子" if d == 1 else "公孙" if d == 2 else "公族", g, n)
            cur = father_get.get(cur)
        return ("", "", 0)

    people = {}
    hist = 0
    hist_used = 0               # 用了「史补国名」的人数（人工知识层，单独统计便于审计）
    titled_state = set()        # 有「宗庙/国君表」明确封国的人 → 世系归并的锚点
    had_cand = set()            # 有封国候选名的人（哪怕候选不是真国）→ 不参与父系继承
    for c in keep:
        r = by_code[c]
        nm = final[c]
        if nm in people:
            nm += "#2"
        shi = (r.get("Ren_Shi") or r.get("Ren_Xing") or "").strip()
        fa, mo = father_get[c], mother_get[c]
        # 父/母必须在最终名单里才写名字。上溯找不到在册祖先时 father_get 仍指着一个
        # 已被剪掉的 Code，直接取名会写出一条指向不存在人物的父子线（脏引用）。
        father = final.get(fa, "") if fa in keep else ""
        mother = final.get(mo, "") if mo in keep else ""
        if father == nm:
            father = ""
        if mother == nm:
            mother = ""

        t = t_of[c]
        guo, jue = t.get("guo", ""), t.get("jue", "")
        # 封代 = 该国的第几代君主（见 load_titles 的说明：按即位时间排序，追封记 0）
        fief_gen = t.get("fief_gen", 0)
        if guo:
            titled_state.add(c)
        if is_hist(c):
            hist += 1

        # 配偶：spouses 字段**只能填树内的节点** —— 程序在 model.normalize 里
        # 会把「指向不存在的人」的配偶引用清掉（这是既定设计，用于清理脏数据），
        # 所以填了也白填。不在树里的配偶（多为嫁入的外族女性）改用小传承载，
        # 小传是自由文本，不会被清理。
        sp_in = []          # 只放树内的人 → 写进 spouses
        sp_all = []         # 全部（含不在树里的）→ 写进小传
        for pc in (r.get("Ren_Pei_Ou_Code_Array") or []):
            pcs = str(pc)
            # 必须**同时**在 final（有名字）和 keep（最终名单）里。只查 final 不行 ——
            # final 是剪枝前的名单，配偶可能已被始祖限定/剪枝剔掉，
            # 那样写出来的就是指向不存在人物的脏引用，程序打开时会静默清掉
            # （实测老档有 188 条，配偶数因此在打开后从 136 掉到 13）。
            if pcs in final and pcs in keep:
                sp_in.append(final[pcs])
                sp_all.append(final[pcs])
            elif pcs in by_code:
                sp_all.append(name_of(by_code[pcs]))
        # 子女（只收谱内的人，因为要连父子线）
        kids = [final[kc] for kc in (r.get("Ren_Zi_Nv_Code_Array") or [])
                if str(kc) in final]
        # ★ 2026-09-25：1c 补回的祖先没有子女数组，用唯一的线索 —— 反查到的儿女
        #   （否则小传只剩「风女娲。史传有载。」一句，太单薄）。
        if c in _syn_kids:
            kids = [final[kc] for kc in _syn_kids[c] if kc in final]

        zun = (r.get("Zun_Hao") or r.get("Ren_Zun_Hao") or "").strip()
        shi_hao = (r.get("Shi_Hao") or "").strip()
        note = zun or (f"谥{shi_hao}" if shi_hao else "")
        if not note and guo and jue:
            note = guo + jue

        # ---- 封国 + 爵位 ----
        # ★★ 优先级（2026-09-21 重定，核心改革）★★
        #
        #   ① **宗庙**（lineage）—— 唯一权威。「进了这家祖庙 = 是这家的人」。
        #      只认**带封代（fief_gen>0）的真人**，即真正即位过的君主；
        #      追封远祖（黄帝/燧人/伏羲/巢皇）虽在庙里但**不占任何一国的封国**
        #      —— 他们被 8 个以上的宗庙共祭（实测「共祭 85 张牌位」），
        #      归给谁都是错的。
        #
        #   ② **势力字段** `Ren_Shi_Li_1` —— 在世者的实际效忠对象（刘邦集团的
        #      功臣都是「汉」）。**这是「出仕」不是「世系」**：写进 state_name
        #      便于查「这人当时在谁手下」，但绝不据此认定他属于该国王族。
        #
        #   ③ 族谱血统 / 氏→国 —— 仅作最后兜底，且必须落在游戏登记过的国里。
        #
        # ★ **父系继承已彻底删除**（原第 7 步）。它把封国当户口，是
        #   「任敖=汉王、灌婴=汉王、严阙=秦帝、蔺康=燕王、姒鹿郢=匈奴」
        #   这一大批错判的根源。使用者说得对：封国是**受封**，不是继承来的。
        lin = lineage.get(str(c))
        if lin and not lin["is_placeholder"] and lin.get("common_ancestor"):
            # ①a 多庙共祭的共同远祖（巢皇/燧人/伏羲/少典/共工…）：**不给封国、
            #    不给封代**。★ 2026-09-24 修：这一档原来写在 ① 的后面，
            #    而 ① 的判据是 `fief_gen` —— 共同远祖在宗庙里父链深度 ≥1，
            #    `fief_gen` 恒为真，于是永远被 ① 先截走，写成「先遍历到哪个
            #    宗庙就归哪个国」（巢皇 → 秦·第1代），小传也跟着写
            #    「为秦国第一代国君」。使用者报「这个问题反复好多次了」就是这个。
            #    现在把它提到 ① 前面，①b 才真正生效。
            state_name, jue, fief_gen = "", "", 0
        elif lin and not lin["is_placeholder"]:
            # ① 真·宗庙君主
            #   ★ 2026-09-25：**判据去掉 `fief_gen` 这个门闸**。原来「封代 > 0」
            #   只是「进庙真人」的代理判据（旧口径下每个非占位牌位的封代都 ≥ 1，
            #   两者完全等价）。现在封代改成游戏给的「本封国第几代」，
            #   **受封之前的同族先世会变成 0**（熊启 / 熊槐 / 楚威王…）——
            #   若仍拿封代当门闸，这批先王会被误降级成「非君主」，
            #   连爵位（王）和封国一起丢掉。改用**庙籍**当判据：进庙的真人
            #   就是这家君族。因为旧口径下门闸恒真，本改动**逐人零变化**。
            state_name = lin["guo"]
            # ★ 爵位**只能用尊号推出来的**（king_rank）。绝不回退到
            #   `lin["jue"]`（= Memorial_Ren_Jue_Wei_New）—— 实测那个字段
            #   在宗庙里**一律是 1（帝）**，回退就会把楚国从「熊严（王）」
            #   到「熊佐（帝）」这种同一条父链上的王侯全写成帝
            #   （实测会凭空造出 365 个「帝」）。
            #   尊号推不出爵位的（尊号空 / 只是「西陲大夫」这类职位名）就留空，
            #   **宁缺勿猜** —— 空着他仍然是「秦宗庙第 N 代」，身份没丢。
            # ★ 2026-09-25：尊号推不出爵位时，**用该国的国爵兜底**。
            #   实测使用者新拉的「穆王巡游」档：265 位国君里 **244 位（92%）没有爵位**
            #   （箕 / 蜀 / 徐 / 薛 / 褒… 这些国的牌位压根不写尊号），而国爵表是现成的
            #   （箕=子 · 齐=侯 · 蜀=王 · 宋=公 · 楚=子）—— 正合「有国的肯定有爵位」。
            #   使用者原话：「每一代国君的爵位**大差不差都是一样的**」。
            #   ⚠️ 只给**本国世代里的君主**（封代 > 0）兜底。受封之前的同族先王
            #   （封代 0，如熊宗庙里的熊槐）**不用**国爵 —— 他们不是这个封国的君，
            #   套上「熊国国爵=伯」只会把一位楚王写成伯（实测会误伤 248 人）。
            #   ⚠️ 非君主（走 ② 档的）仍然一律留空 —— 那条纪律是为了挡
            #   「任敖=汉王」那种父系继承的错判，不适用于**封国的君**。
            jue = king_rank(c)
            if not jue and lin.get("fief_gen"):
                jue = guo2jue.get(lin["guo"], "")
            fief_gen = lin["fief_gen"]
            titled_state.add(c)
        else:
            # ② / ③ 非君主：只记「势力」，不写封国
            #   （共同远祖已在 ①a 截走；占位祖先本来就走这里）
            shi_li = (r.get("Ren_Shi_Li_1") or "").strip()
            if real_state:
                cand = shi_li or guo_of_code.get(str(c), "") \
                    or clan_shi2guo.get(shi, "") or shi2guo.get(shi, "")
                known = all_guo | set(hist_states)
                state_name = cand if cand in known else ""
                if state_name and state_name in hist_states:
                    hist_used += 1
            else:
                state_name = shi2guo.get(shi) or shi
            # 非君主的爵位一律留空 —— 之前从国爵表补「汉王」就是这么来的
            jue, fief_gen = "", 0
            if state_name:
                had_cand.add(nm)

        # ---- 世系归属（独立体系，与「势力」分开）----
        # ★ 使用者原话：「不是在某国出仕或在某国的城市就有世系，
        #   **必须是该国君主的家族**」。
        #
        #   所以这里分两个字段，**不要再混为一个**：
        #     `lineage_name` 世系  —— 只认宗庙。是这家祖庙的人才有值。
        #                             空 = 不是任何国家的君族。
        #     `state_name`   势力  —— 他当时效忠谁（刘邦的功臣都写「汉」）。
        #                             这是「出仕」，跟世系无关。
        #   `fief_title`（爵位）也只在宗庙口径下才有值。
        #
        #   历史上「国君 → 公子 → 公孙 → 公族」的推断（kinship）走的也是
        #   纯父系，所以必然落在同一祖庙内 —— 与世系口径天然一致。
        #
        #   ★ 2026-09-24：**多庙共祭的共同远祖不写世系**（使用者裁定「宗庙祖先
        #     不计入当前存档该国世系，有需要我自己改」）。巢皇/燧人/伏羲 被 8 个
        #     宗庙共祭，挂在任何一国的「X国世系」框里都是错的。
        lineage_name = ""
        if lin and not lin["is_placeholder"] and not lin.get("common_ancestor"):
            # ★ 2026-09-25：**不再以 `fief_gen` 为条件**。「进庙 = 是这家的人」
            #   与「受封后第几代」是两件事：熊启 / 熊槐 是熊宗庙的人（有世系），
            #   但不是**熊国**的世代（Generations = −1 → 封代 0）。旧代码把两者
            #   绑在一起，封代一改真，这一整批先世就会丢掉世系。
            #   （旧口径下每个非占位牌位封代都 ≥ 1，所以本改动逐人零变化。）
            lineage_name = lin["guo"]
        people[nm] = {
            "father": father, "mother": mother,
            "color": "", "bg_color": "", "note": note,
            "gender": "女" if is_female(r) else "男",
            "generation": max(1, gen.get(c, 1)),
            "historical": "是" if is_hist(c) else "否",
            "divine": "是" if c in anc else "否",
            "birth": born_time_of(r),
            "death": str(died_of(r)) if died_of(r) else "",
            "rank": 0, "spouses": sp_in,
            "associate_of": "", "associate_type": "", "associate_rank": 0,
            "state_group": (state_name + jue) if (state_name and jue) else "",
            "state_name": state_name,
            "lineage_name": lineage_name,
            "fief_title": jue, "fief_gen": fief_gen,
            # ★ 续谱名单点名的人按**选定顺序**拿 1、2、3…（见第 4c 步）；
            #   其余一律 0，交给 layout 的姓氏表 / 999 兜底排序。
            "root_sort": root_sort_of.get(c, 0),
            "bio": make_bio(bios_name.get(c, nm), r, t, sp_all, kids,
                            is_hist(c), is_female(r),
                            dup=dup_info.get(c), kin=kinship(c),
                            state_name=state_name, fief_title=jue),
            # ★ 存档编号（Ren_Code）—— 「谱牒 ↔ 实录」的唯一锚点（规划 D4）。
            #   以前只有单人入谱写它，整档抽取不写，于是桥只能靠「姓名+性别+生年」
            #   模糊匹配，一重名就连错人。现在整档抽取也写。
            "code": c,
            # ★ 2026-09-24：抽取器**内部标记**（多庙共祭的共同远祖）。
            #   只给续谱的合并阶段用（见 `_merge_rec`），**不写进谱牒** ——
            #   由 `_strip_internal()` 在落盘前摘掉，免得污染手写家族树格式。
            "common_ancestor": "是" if (lin and lin.get("common_ancestor")) else "",
        }

    # ---- 7. （已删除）父系继承封国 ----
    # 原逻辑：「父亲在某国，儿子默认也在」——先秦世卿世禄，看着合理。
    # **但它是错的，且是本项目最大的一个 bug 来源。**
    #
    # 封国不是户口，是**受封**。父在秦、子却可能只是秦的臣民（甚至别国的客卿）。
    # 实测它造成的错判：
    #     任敖（刘邦御史大夫）    → 汉**王**
    #     灌婴（汉开国功臣）      → 汉**王**
    #     夏侯玄（夏侯婴之子）    → 汉
    #     严阙 / 严卓（秦臣）     → 秦**帝**
    #     蔺康（蔺氏，赵国大夫）  → 燕**王**
    #     姒鹿郢（越王勾践一族）  → 匈奴
    # 使用者的原话判据：「不是在某国出仕或在某国的城市就有世系，
    # **必须是该国君主的家族**」—— 所以世系只认宗庙（见第 6 步 ①），
    # 继承这条路径整条删除。
    inherited = 0      # 保留字段以兼容既有报告格式，恒为 0

    # ★ 续谱用的两份索引：
    #   name2code —— 姓名 → 存档编号（合并时按姓名兜底认人用）
    #   gen_src   —— 编号 → 世代来源（决定要不要拿新抽的世代覆盖谱牒里的旧值）
    name2code = {n: v.get("code", "") for n, v in people.items() if v.get("code")}
    stats = {"total": len(people), "hist": hist,
             "titled": sum(1 for v in people.values() if v["fief_title"]),
             "renamed": dup_names, "no_gen": len([c for c in keep if c not in gen]),
             "titled_state": len(titled_state), "inherited": inherited,
             "hist_state": hist_used,
             "lineage": len(lin_real)}
    return people, stats, name2code, gen_src


def bucket_gen(year):
    """出生年 → 世代桶（只用于「始祖」锚定）。

    桶心是按「上古时代」那版存档反推的（第1代 −2580 … 第8代 −2425）。
    但别的存档时间跨度完全不同（秦末起义档从 −2700 一路到 −200），落在已知窗口
    之外就按同一个步长往外推：不推的话，比 −2425 晚的人**全部挤进第8代**，
    而树形布局的 y 坐标正是 generation —— 三千多人会被压成一条横线。
    """
    lo, hi = min(GEN_CENTER), max(GEN_CENTER)
    if year > GEN_CENTER[hi]:
        return hi + max(1, round((year - GEN_CENTER[hi]) / -GEN_STEP))
    if year < GEN_CENTER[lo]:
        return max(1, lo - max(1, round((GEN_CENTER[lo] - year) / -GEN_STEP)))
    return min(GEN_CENTER, key=lambda g: abs(GEN_CENTER[g] - year))


# ==================================================================== 剧本判定

def detect_era(src):
    """判断这个槽属于哪个剧本 —— 判据唯一实现在 `app/era.py`（代码改进 C1）。

    这里只负责把**扁平目录**里的数据读成行列表：
      · `Save_Wang_Chao_Data.json`（列表，实测长度 2）
      · `Save_KingData_*.json`（全世界 151 国，一国一个文件）
    本文件要被子进程当 CLI 调起、不能 import 主程序（会拉进 tkinter）；
    era.py 不依赖 tkinter，两边共用安全。
    （关键认知：151 国的 King_Stage **同时代并存**，见 era.py 模块头。）
    """
    wc = _read_json(os.path.join(src, "Save_Wang_Chao_Data.json"))
    wc_rows = wc if isinstance(wc, list) else ([wc] if isinstance(wc, dict) else [])
    kd_rows, rec_rows = [], []
    for f in sorted(glob.glob(os.path.join(src, "Save_KingData_*.json"))):
        o = _read_json(f)
        if not isinstance(o, dict):
            continue
        kd_rows.append(o)
        if os.path.basename(f) == "Save_KingData_0.json":
            rec0 = o.get("King_Stage_Record")
            if isinstance(rec0, list) and rec0:
                rec_rows = rec0
    return _era_of(wc_rows, rec_rows, kd_rows)


def _read_json(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


_START_YEAR_CACHE = {}


def _scan_start_year(src):
    """扫全档求「开局年」：先看各国的 `King_Stage_Record[0]` 取**最早**；
    一本都没有就退到顶层时间字段，同样取最早。"""
    primary, fallback = [], []
    for f in sorted(glob.glob(os.path.join(src, "Save_KingData_*.json"))):
        o = _read_json(f)
        if not isinstance(o, dict):
            continue
        rec = o.get("King_Stage_Record")
        if isinstance(rec, list) and rec:
            y = _parse_bc_year((rec[0] or {}).get("Start_Time"))
            if y is not None:
                primary.append(y)
                continue
        for k in ("Start_Time", "War_Creat_Time", "Record_Time"):
            y = _parse_bc_year(o.get(k))
            if y is not None:
                fallback.append(y)
                break
    if primary:
        return min(primary)
    return min(fallback) if fallback else None


def detect_start_year(src, refresh=False):
    """这个槽**开局是哪一年**（公元前为负）。

    ★ 2026-09-22 修（B 批第 1 条）：**不再单点读 `Save_KingData_0.json`**。
      原实现假设「0 号文件那一国就是最早开局的」。实测 12 个槽 / 28 个备份：
      **该假设今天恰好成立**（0 号文件的 rec0 恰好等于全档最早值），
      但它依赖**文件名顺序**这种不该依赖的东西 —— 一旦 0 号文件缺失、
      或那一国是中途才出现的，年份就会偏晚，进而把剧本认成后一本。
      现改为**扫全档取最早**，并加**按目录 mtime 的缓存**
      （实测读全档 0.02~0.14s/槽，命中缓存 0s；槽列表会反复调这个函数）。

    ⚠️ 与 `app/saveload.game_year()` 不是一回事，别混用：
      · 本函数读 `King_Stage_Record[0].Start_Time` = **开局年**
        （实测 Save_All_1 = 前 209 = 秦末起义；Save_All_4001 = 前 194 = 卫氏朝鲜）
      · `saveload.game_year()` 读 `Save_Zhan_Zheng_Data.Start_Time` = **当前年份**
        （实测 Save_All_4001 = 前 188，中间走过了 6 年）
      查剧本用**开局年**（本函数）；时间轴「时代全览」右端用**当前年份**。

    ★ 实测口径（2026-09-22，供后续判断依据是否够用）：
      · 同一槽内各国 `rec[0]` **并不一致**（Save_All_3 最早 -1092 / 最晚 -1084）
        → **取最小**才是剧本开局年。
      · 同槽 `rec0 最早` 与表内开局年**多数分毫不差**，但也有漂移：
        `Save_All_100/2`（满天星斗）检出 -2494，表内 -2500，**漂移 6 年**。
      · `rec[0].Name`（「圣人阶段」等）只有**先民/礼法/方国/圣人**四种，
        **粒度太粗，不能用来区分剧本**；存档里也**没有任何剧本名/编号字段**。
    """
    try:
        key = (os.path.abspath(src), os.path.getmtime(src))
    except OSError:
        key = None
    if key is not None and not refresh and key in _START_YEAR_CACHE:
        return _START_YEAR_CACHE[key]
    y = _scan_start_year(src)
    if key is not None:
        if len(_START_YEAR_CACHE) > 256:      # 长会话别无限涨
            _START_YEAR_CACHE.clear()
        _START_YEAR_CACHE[key] = y
    return y


# ==================================================================== 比对

def compare(people, save_name):
    p = os.path.join(ROOT, "saves", save_name, "family.json")
    if not os.path.exists(p):
        print(f"  （找不到存档 {save_name}）")
        return
    old = json.load(open(p, encoding="utf-8"))
    old = old.get("people", old)
    hit = [n for n in old if n in people]
    print()
    print("=" * 70)
    print(f"与「{save_name}」({len(old)} 人) 比对")
    print("=" * 70)
    print(f"  同名命中   {len(hit)} / {len(old)}  ({len(hit)*100//max(1,len(old))}%)")
    if not hit:
        return
    for label, key in (("性别", "gender"), ("父亲", "father"), ("封国", "state_name")):
        same = sum(1 for n in hit if old[n].get(key) == people[n].get(key))
        print(f"  {label}一致{'':<2}{same}/{len(hit)}")
    # 世代
    same = sum(1 for n in hit if old[n].get("generation") == people[n].get("generation"))
    off = Counter(old[n].get("generation", 0) - people[n].get("generation", 0)
                  for n in hit)
    print(f"  世代一致   {same}/{len(hit)}  ({same*100//len(hit)}%)"
          f"   误差分布 {dict(sorted(off.items()))}")
    # 史实
    ty = [n for n in old if old[n].get("historical") == "是"]
    ok = sum(1 for n in ty if people.get(n, {}).get("historical") == "是")
    fp = sum(1 for n in old if old[n].get("historical") == "否"
             and people.get(n, {}).get("historical") == "是")
    print(f"  史实：你标是 {len(ty)} → 命中 {ok}；误报 {fp}")
    # 爵位
    bj = [n for n in hit if old[n].get("fief_title") and people[n].get("fief_title")]
    oj = sum(1 for n in bj if old[n]["fief_title"] == people[n]["fief_title"])
    print(f"  爵位：两边都有 {len(bj)} → 一致 {oj}"
          f"（{oj*100//max(1,len(bj))}%）")
    # 配偶
    bs = [n for n in hit if old[n].get("spouses") and people[n].get("spouses")]
    os_ = sum(1 for n in bs if set(old[n]["spouses"]) <= set(people[n]["spouses"]))
    print(f"  配偶：两边都有 {len(bs)} → 你的配偶被游戏覆盖 {os_}")


# ==================================================================== 增量续谱

# 手写优先：谱牒里非空就**永不**被新抽的值覆盖
# （与 import_single 同口径，另加 rank / root_sort —— 排序是手工排的，最忌被冲）
HAND_FIELDS = ("bio", "note", "color", "bg_color",
               "associate_of", "associate_type", "associate_rank",
               "hide_parent_line", "rank", "root_sort")

# 只升不降：允许 否→是，禁止 是→否（保护手标的史实 / 神祖）
UPGRADE_FIELDS = ("historical", "divine")

# 实证优先·清空式：新抽的是空，意味着「他不是」这个**结论**，必须把旧值清掉。
# ★ 2026-09-21 使用者裁决后**已清空**：原来这里装着
#   `state_name / state_group / lineage_name / fief_title / fief_gen`，
#   每次续谱都用游戏抽出来的值覆盖谱牒 —— 正是它把使用者手改的爵位冲掉的。
#   使用者原话：「每次续谱，只更新新人物，老人物我自己会调整」。
#   所以这五个字段改走 `FACT_KEEP`（见下），FACT_CLEAR 留空表以保留调用点。
FACT_CLEAR = ()

# 封国 / 爵位 / 世系 —— **只写新人，老人一律不动**（使用者 2026-09-21 裁决）。
#
# 为什么单独列一组、而不是并进 HAND_FIELDS：
#   · HAND_FIELDS 的语义是「手写字段」（小传/注释/配色/祖序），判据是「旧值非空就留」；
#   · 这一组的判据是「**旧记录里有没有这个键**」——
#     手写老谱（从旧版家族树导入）根本没有这些键 → 照写新抽的（首次读档要能读出来，
#     例如「嬴胡亥 = 皇帝」）；
#     已经有键的（不管是上次抽取写的还是使用者手改的）→ 一律保留旧值。
#   这个区别就是使用者那句「X 国世系第一次读档的时候就这么处理，如果是更新一个存档，
#   则以我原有的存档为主」。
#
# ⚠️ 代价（已知并接受）：旧版曾用「清空式」自动修正的错判
#   （嬴异人=帝 / 任敖=汉王 / 蔺康=燕王 …）以后**不会再被自动修掉**，
#   要使用者自己在表格页改。使用者明确表示「老人物我自己会调整」。
FACT_KEEP = ("state_name", "state_group", "lineage_name", "fief_title", "fief_gen")

# ---------------------------------------------------------------------------
# 【历史爵位知识层 · 人工记录，不参与自动抽取】
# 使用者 2026-09-21 口述，留档备查（他说「你不会自己搜索，所以我才需要自己设定」）：
#   · 夏、商、周三朝，君主都是**王**爵。
#   · 秦（示例，供手动设爵时对照）：
#       秦仲及其前   —— 西垂大夫（附庸），相当于**子**爵
#       秦襄公 ～ 秦惠文王之前 —— **伯**爵（死后尊称「公」，如秦穆公/秦庄公）
#       秦惠文王（嬴驷）～ 秦二世 —— **王**爵
#       秦始皇、秦二世 —— **皇帝**（仅此二人）
#       恶来及商代以前 —— 社会地位不明，按普通人处理
#       传说时代 —— 有一些古帝
# 注意：**不要**据此自动给宗庙里所有国君发爵位 ——
#   西周时期的诸侯是公/侯/伯/子/男，只有周天子是王；
#   异族宗庙（匈奴/丁零/月氏…）的君主也不适用。
#   这一段只在人工设爵时当参考，抽取器仍然只认宗庙尊号。
# ---------------------------------------------------------------------------

# 实证优先·补齐式：新抽的是空只是「没记」，保留旧值，别把已有实证抹了
FACT_FILL = ("gender", "birth", "death")

# 血缘冻结：父子 / 母子关系是**不变量**（游戏里一个人的父亲不会变），
# 所以旧值非空就保留 —— 既保住手工修正过的连线，也不会被重新抽取推歪；
# 旧值为空时用新抽的补上（补全断根）。
KIN_FIELDS = ("father", "mother")

# 只有这两种来源定出来的世代才允许覆盖谱牒里的旧值
GEN_TRUSTED = ("父链", "生年落桶")

# 重名序数的尾巴 —— **三个时代的写法都要认**，老档不能认不回来：
#   中文数字（最老：王贲二 / 王贲二十一）· 带圈数字（上一版：王贲②）·
#   纯数字（现行：王贲2）· 更老的退路 `(21)`
# ★ 认不出的后果：`base_of("风会胜2")` 会返回它自己 → 「同名不同人」的分组
#   彻底失效，续谱时那批没编号的老记录就再也认不回自己了。
_CN_ORD = re.compile(r"(?:[一二三四五六七八九十]{1,3}|[①-⑳]|\d{1,3}|\(\d{1,3}\))$")


def base_names(name):
    """姓名可能缀了重名序数（王贲二 / 王贲② / 王贲2）→ 给出可能的基名，长的在前。

    最后一项一定是原名本身，方便调用方判断「有没有缀过序数」。
    """
    out = []
    for k in (5, 4, 3, 2, 1):          # 到 5：`(21)` 这种退路是 4 个字符
        if len(name) > k and _CN_ORD.fullmatch(name[-k:]):
            if name[:-k] not in out:
                out.append(name[:-k])
    out.append(name)
    return out


def base_of(name):
    """取基名（没有序数就是自己）。"""
    bs = base_names(name)
    return bs[0] if len(bs) > 1 else name


def _filled(v):
    """这个值算不算「有内容」—— 空串 / None / 空表 / 0 都算没有。"""
    return v not in ("", None, [], 0)


# 代码改进 D6（2026-09-22）：family.json 的备份只攒不删会无限膨胀
# （工作日志九记录过实测已攒 4 份、要手删）。写回成功后自动清理，保留最近
# MAX_BAKS 份。⚠️ 槽级 `.bak_<时间戳>` 目录（拉档退路）**不在此列**，另议。
MAX_BAKS = 10


def _prune_baks(path, keep=MAX_BAKS):
    d = os.path.dirname(path)
    base = os.path.basename(path)
    baks = sorted(glob.glob(os.path.join(d, base + ".bak_*")),
                  key=os.path.getmtime, reverse=True)
    for old in baks[keep:]:
        try:
            os.remove(old)
            print(f"  清理旧备份：{os.path.basename(old)}（保留最近 {keep} 份）")
        except OSError:
            pass


def write_atomic(path, payload, keep_backup=True):
    """原子写：备份 → 校验备份可读 → 写 tmp → os.replace 替换。

    备份名沿用项目习惯 `family.json.bak_<YYYYMMDD_HHMMSS>`；写回成功后自动
    只留最近 `MAX_BAKS` 份（代码改进 D6）。
    返回备份文件路径（没备份则空串）。任何一步失败都抛，且不留半截文件。
    """
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = ""
    if keep_backup and os.path.exists(path):
        bak = f"{path}.bak_{ts}"
        shutil.copy2(path, bak)
        with open(bak, encoding="utf-8") as f:
            json.load(f)            # 备份必须能读回来，否则宁可不写
    tmp = f"{path}.tmp_{ts}"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    _prune_baks(path)
    return bak


def _match_old_to_fresh(old, fresh_people, fresh_by_code, fresh_groups, report):
    """认人：把每条旧记录锚到一条新记录上。返回 {旧姓名: 新姓名}。

    四级判据，**唯一才连**；连不上的一律进「待确认」，两边原样保留、不连线。
      A 编号命中（稳态：续过谱的档走这条）
      B 姓名在谱中恰好 1 人 + 性别一致 + 生年（都非空时）相等
      C 姓名完全同名 + 该基名的重名组**两边人数一致** → 按同名锚定
        （序数是按「史实→有爵位→生年→编号」排出来的，人员集合没变时位置就稳定）
      D 重名组人数变了 → 用「性别 + 生年 + 父名」过滤，只剩 1 个才连
    """
    old2fresh = {}
    taken = {}                       # 新姓名 → 旧姓名（防两条旧记录抢同一个人）
    old_groups = defaultdict(int)
    for n in old:
        old_groups[base_of(n)] += 1

    def _ok_birth(a, b):
        return (not a) or (not b) or str(a) == str(b)

    def _ok_father(ov, nv):
        of = base_of(str(ov.get("father") or ""))
        nf = base_of(str(nv.get("father") or ""))
        return (not of) or (not nf) or of == nf

    def _claim(on, fn, how):
        if fn in taken and taken[fn] != on:
            report["pending"].append(
                (on, "与「%s」争同一条新记录" % taken[fn]))
            return False
        old2fresh[on] = fn
        taken[fn] = on
        report[how] += 1
        return True

    for on, ov in old.items():
        # A. 编号命中
        code = str(ov.get("code") or "").strip()
        if code and code in fresh_by_code:
            _claim(on, fresh_by_code[code], "anchor_code")
            continue

        fv = fresh_people.get(on)
        if fv is not None:
            g_old = old_groups[base_of(on)]
            g_new = len(fresh_groups.get(base_of(on), []))
            ok_common = (str(ov.get("gender") or "") == str(fv.get("gender") or "")
                         and _ok_birth(ov.get("birth"), fv.get("birth")))
            # B. 姓名唯一命中
            if g_new == 1 and ok_common:
                _claim(on, on, "anchor_name")
                continue
            # C. 同名 + 重名组人数一致 → 位置稳定，按同名锚定
            if g_new == g_old and ok_common and _ok_father(ov, fv):
                _claim(on, on, "anchor_dup")
                continue

        # D. 重名组 + 性别 + 生年 + 父名
        cands = list(fresh_groups.get(base_of(on), []))
        if cands:
            of = base_of(str(ov.get("father") or ""))
            picked = []
            for fn in cands:
                nv = fresh_people[fn]
                if str(nv.get("gender") or "") != str(ov.get("gender") or ""):
                    continue
                if not _ok_birth(ov.get("birth"), nv.get("birth")):
                    continue
                nf = str(nv.get("father") or "")
                if of and nf and base_of(nf) != of:
                    continue
                picked.append(fn)
            if len(picked) == 1:
                _claim(on, picked[0], "anchor_dup")
                continue

        if cands:
            # 有候选但定不下来 → 真·待确认（不自动连线）
            report["pending"].append(
                (on, "新档里有 %d 个候选，定不出是哪一个" % len(cands)))
        else:
            # 新档里根本没有这个人 → 谱内独有（手写的 / 已被筛掉的），原样保留。
            # 这不叫「待确认」：没什么可确认的，它就该留着。
            report["orphan"].append(on)
    return old2fresh


def _stale_gen_1(ov, og, gen_src_of_code):
    """旧世代是不是「上一版代码把定不出来的人兜成第 1 代」留下的？

    三个条件**同时**成立才算（详见 `_merge_rec` 里调用处的说明）：
      · 新抽的世代来源是「时代兜底」—— 这人在新算法里仍属「定不出来」那一批
      · 旧值正好是 1
      · 他没生年、没父亲、也不是神祖

    第 3 条是关键：手写的「第 1 代」= 认他是本谱始祖，
    那就必然要么勾了「神祖」、要么有生年或父系可查 —— 三条不可能同时成立。
    """
    if gen_src_of_code != "时代兜底":
        return False
    try:
        if int(og) != 1:
            return False
    except (TypeError, ValueError):
        return False
    if _filled(ov.get("birth")) or _filled(ov.get("father")):
        return False
    return ov.get("divine") != "是"


def _merge_rec(ov, fv, code, gen_src, report):
    """一条旧记录 + 一条新记录 → 合并后的一条。规则见规划 §2.2。"""
    rec = dict(fv)
    # 手写优先
    for k in HAND_FIELDS:
        if _filled(ov.get(k)):
            rec[k] = ov[k]
            report["hand_kept"] += 1
    # 只升不降
    for k in UPGRADE_FIELDS:
        if ov.get(k) == "是":
            rec[k] = "是"
            if fv.get(k) != "是":
                report["upgraded"] += 1
    # 实证优先·清空式：新抽的空就是**结论**（「他不是君主」），
    # 这里强制把键写进 rec，后面的「未知字段兜底」就不会再把旧值搬回来了。
    # （FACT_CLEAR 现在是空表 —— 见它的说明。）
    for k in FACT_CLEAR:
        rec[k] = fv.get(k, "")
    # ★ 封国 / 爵位 / 世系：**只写新人，老人一律不动**（使用者 2026-09-21 裁决）。
    #   判据是「旧记录里有没有这个键」，不是「旧值是否为空」——
    #   `fief_gen = 0`（明确不是君主）也是要保留的结论，不能被新值顶掉。
    for k in FACT_KEEP:
        if k in ov:
            if ov[k] != fv.get(k):
                report["fact_kept"] += 1
            rec[k] = ov[k]
        else:
            rec[k] = fv.get(k, "")
    # ★★ 2026-09-24：多庙共祭的**共同远祖**要修掉，不吃 FACT_KEEP 的「老人物不动」。
    #   为什么可以破例：这几个字段对这批人是**旧版抽取器按「先遍历到哪个宗庙就
    #   归哪个」写下的机器错判**（巢皇 → 秦·第1代、共工 → 越裳·第1代），
    #   不是使用者手改的爵位 —— 而 FACT_KEEP 护的正是手改值（见它的说明）。
    #   使用者原话：「宗庙里风巢皇是祖先，但不说明他是秦国的第一代君主，
    #   这个问题反复好多次了有解决的办法吗？」—— 光改抽取器只能管新人，
    #   老谱牒里那几条会一直留着，所以这里一并清掉。
    if fv.get("common_ancestor") == "是":
        for k in ("state_name", "state_group", "lineage_name", "fief_title"):
            rec[k] = ""
        rec["fief_gen"] = 0
        # 小传只在**旧文本确实在自称「某国第N代国君」**时才换成新写的，
        # 免得把使用者自己润过的句子冲掉。
        if fv.get("bio") and "代国君" in str(ov.get("bio") or ""):
            rec["bio"] = fv["bio"]
            report["ancestor_bio"] = report.get("ancestor_bio", 0) + 1
        report["ancestor_fixed"] = report.get("ancestor_fixed", 0) + 1
    # 实证优先·补齐式：新抽的空只是没记，保留旧值
    for k in FACT_FILL:
        if not _filled(rec.get(k)) and _filled(ov.get(k)):
            rec[k] = ov[k]
    # ★ 生卒年月日升级（2026-09-22）：存量谱牒的 birth 是**老抽取器**写的，
    #   只有年（如 `-1380`），月日丢了。续谱抽到带月日的新值（含逗号，如
    #   `-1380,6,10`）时，用新值补全 —— 只动 birth，不碰 gender/death。
    #   老档兼容：新值不带逗号（同样只有年）时保持原样，不降级。
    if _filled(fv.get("birth")) and "," in fv["birth"]:
        ob = rec.get("birth")
        if not (isinstance(ob, str) and "," in ob):
            rec["birth"] = fv["birth"]
            report["fact_upgraded"] += 1
    # 血缘冻结：旧值非空就留旧值（关系改写在第 4 步统一做）
    for k in KIN_FIELDS:
        if _filled(ov.get(k)):
            rec[k] = ov[k]
            report["kin_kept"] += 1
    # 世代：只有可信来源才覆盖
    og, ng = ov.get("generation"), fv.get("generation")
    if _filled(og) and _filled(ng):
        if gen_src.get(str(code)) in GEN_TRUSTED:
            if abs(int(ng) - int(og)) > 2:
                report["gen_jump"] += 1
        elif _stale_gen_1(ov, og, gen_src.get(str(code))):
            # ★ 2026-09-22：修「不应该有第一代人的那个 bug 还在」。
            #   上一版代码对「定不出来」的人不填世代，最后由
            #   `"generation": max(1, gen.get(c, 1))` 兜成**第 1 代**；
            #   修好之后新建的档已经是对的，但**那时候已经建好的谱牒**
            #   里那一批人仍然是 1 —— 而「时代兜底」不在 GEN_TRUSTED 里，
            #   续谱会把旧值 1 原样保留，于是使用者看到的 bug「还在」。
            #   这里开一个**极窄的口子**：旧值正好是 1、新来源是「时代兜底」、
            #   而且这人**没生年、没父亲、也不是神祖** —— 三个条件同时成立时，
            #   那个 1 只可能是上一版代码兜出来的，允许用时代兜底修掉。
            #   手写值不会满足这三条：把某人设成第 1 代 = 认他是本谱始祖，
            #   那要么勾了「神祖」，要么有生年/父系可查。
            rec["generation"] = ng
            report["gen_fixed"] = report.get("gen_fixed", 0) + 1
        else:
            rec["generation"] = og
            report["gen_kept"] += 1
    # 旧档里新档没有的未知字段（含以后新增的手工字段）原样保留
    for k, v in ov.items():
        if k not in rec:
            rec[k] = v
    # ★ 2026-09-21：这里原来统计「封国/爵位被修正了几条」——
    #   现在封国/爵位对老人物是**只保留、不修正**（FACT_KEEP），所以那个计数恒为 0，
    #   改成在 FACT_KEEP 那一循环里统计「沿用旧值的条数」，见 report["fact_kept"]。
    return rec


def _strip_internal(people):
    """摘掉抽取器的**内部标记** —— 谱牒格式必须跟使用者手写的家族树兼容，
    多一个键就可能让导入方挑食。目前只有一个：`common_ancestor`。"""
    for v in people.values():
        v.pop("common_ancestor", None)
    return people


def merge_into(old_raw, fresh_people, gen_src=None, meta=None):
    """增量合并：把新抽的 fresh 并进已有谱牒 old_raw。

    返回 `(people, cutoff, source, report)`。

    铁律（规划 §二 + 使用者 2026-09-21 裁决）：
      · **绝不删除** old 独有的人
      · 手写字段（HAND_FIELDS）只要 old 非空，永不被 fresh 覆盖
      · **封国 / 爵位 / 世系（FACT_KEEP）：只写新人，老人一律不动** ——
        使用者原话「每次续谱，只更新新人物，老人物我自己会调整」。
        判据是「旧记录里有没有这个键」（见 FACT_KEEP 的说明）。
      · 生卒 / 性别仍按补齐式更新（FACT_FILL），世代只信可信来源
      · 认人只认编号；没编号时按「姓名 + 性别 + 生年 + 父名」唯一匹配，
        匹配不唯一的一律「待确认」：两边原样保留、不连线
      · 全程不调用 `model.normalize`，免得触发祖序重排把手工排序冲掉
    """
    gen_src = gen_src or {}
    meta = dict(meta or {})
    old = (old_raw or {}).get("people") or {}
    cutoff = (old_raw or {}).get("cutoff_person")
    src = dict((old_raw or {}).get("source") or {})

    report = {"old": len(old), "fresh": len(fresh_people),
              "anchor_code": 0, "anchor_name": 0, "anchor_dup": 0,
              "added": 0, "updated": 0, "kept": 0, "renamed": 0, "purged": [],
              "upgraded": 0, "fact_fixed": 0, "fact_kept": 0,
              "fact_upgraded": 0,
              "ancestor_fixed": 0, "ancestor_bio": 0,
              "hand_kept": 0, "kin_kept": 0,
              "gen_kept": 0, "gen_jump": 0, "gen_fixed": 0,
              "rel_father": 0, "rel_mother": 0, "rel_spouse": 0,
              "dangling_father": [], "dangling_spouse": [],
              "collision": 0, "pending": [], "orphan": []}

    # ---- 1. 索引 ----
    # ★ 2026-09-24 占位祖先空壳**在认人之前**就从旧档里剔掉（判据见
    #   is_book_placeholder）。不能留到「谱内独有」那一步才清 —— 它们会先被
    #   「按姓名唯一匹配」认成真人的前身：实测假「风穷右」（编号 100000203父）
    #   匹配上了新档里真「风穷右」（100016110），于是真人继承了假父亲的
    #   「风巢皇」（血缘沿用旧值），画布上仍多一个儿子。
    _purged = [n for n, v in old.items() if is_book_placeholder(v)]
    if _purged:
        _purged_set = set(_purged)
        old = {n: v for n, v in old.items() if n not in _purged_set}
        # ★ 2026-09-26 审查修复（M2）：清了空壳还要清**指向它们的引用**。
        #   原来孩子的 father 悬空保留（只在报告里记账）：
        #   ① KIN_FIELDS「血缘冻结」看到旧值非空就把悬空名原样留下去，
        #      fresh 的真父链永远进不来（五十六批「风穷右」那例是手动改回的）；
        #   ② 画布上孩子变孤儿根。这里清空引用 → 合并时走 fresh 的真父链。
        _n_ref = 0
        for _v in old.values():
            for _k in ("father", "mother"):
                if str(_v.get(_k) or "") in _purged_set:
                    _v[_k] = ""
                    _n_ref += 1
        report["purged_refs"] = _n_ref
        report["purged"] = _purged

    fresh_by_code = {str(v.get("code")): n for n, v in fresh_people.items()
                     if v.get("code")}
    fresh_groups = defaultdict(list)
    for n in fresh_people:
        fresh_groups[base_of(n)].append(n)

    # ---- 2. 认人 ----
    old2fresh = _match_old_to_fresh(old, fresh_people, fresh_by_code,
                                    fresh_groups, report)

    # ---- 3. 组装：新抽的当底，旧的按锚点叠上去 ----
    people = {}
    for fn, fv in fresh_people.items():
        people[fn] = dict(fv)

    final_name = {}                  # 旧姓名 → 合并后的姓名
    # 顺序不能反：先把**认得出来**的叠上去，再放「谱内独有」的。
    # 反过来的话，独有记录会先占住某个姓名键，随后被合并结果覆盖掉，等于丢数据。
    for on in old:
        fn = old2fresh.get(on)
        if fn is None:
            continue
        people[fn] = _merge_rec(old[on], fresh_people[fn],
                                fresh_people[fn].get("code"), gen_src, report)
        final_name[on] = fn
        report["updated"] += 1
        if on != fn:
            report["renamed"] += 1

    for on in old:
        if on in old2fresh:
            continue
        # 旧档独有 → 原样保留，一个字段都不动
        # （占位祖先空壳在上面第 1 步就已经剔掉了，走不到这里）
        key = on
        while key in people:
            key += "#2"
            report["collision"] += 1
        people[key] = dict(old[on])
        final_name[on] = key
        report["kept"] += 1

    report["added"] = len(fresh_people) - report["updated"]

    # ---- 4. 关系重写（防悬空）----
    #   顺序不能反：必须先定完最终姓名，再统一改引用。
    for v in people.values():
        f = str(v.get("father") or "")
        if f and f in final_name and final_name[f] != f:
            v["father"] = final_name[f]
            report["rel_father"] += 1
        m = str(v.get("mother") or "")
        if m and m in final_name and final_name[m] != m:
            v["mother"] = final_name[m]
            report["rel_mother"] += 1
        sp = v.get("spouses") or []
        if sp:
            new = []
            for s in sp:
                t = final_name.get(s, s)
                if t != s:
                    report["rel_spouse"] += 1
                if t not in new:
                    new.append(t)
            v["spouses"] = new

    # 悬空：父母指向不在册者 → 保留名字但记账（树按根节点处理，不毁手写）
    #       配偶指向不在册者 → 删掉并记账（model.normalize 反正会静默删）
    for n, v in people.items():
        for k in ("father", "mother"):
            t = str(v.get(k) or "")
            if t and t not in people:
                report["dangling_father"].append((n, k, t))
        sp = [s for s in (v.get("spouses") or []) if s in people]
        for s in (v.get("spouses") or []):
            if s not in people:
                report["dangling_spouse"].append((n, s))
        v["spouses"] = sp

    # ---- 5. 来源元数据 ----
    if meta.get("slot"):
        src["slot"] = meta["slot"]
    if meta.get("slot_path"):
        src["slot_path"] = meta["slot_path"]
    if meta.get("era"):
        src["era"] = meta["era"]
    if meta.get("prune"):
        src["prune"] = meta["prune"]
    if meta.get("real_state_only") is not None:
        src["real_state_only"] = bool(meta["real_state_only"])
    src["last_merge"] = time.strftime("%Y-%m-%d %H:%M")
    src["merge_count"] = int(src.get("merge_count") or 0) + 1
    src["imported"] = src.get("imported") or src["last_merge"]
    return _strip_internal(people), cutoff, src, report


def format_report(report, meta=None, dry_run=True):
    """把合并报告排成给人看的汉字文本（不用 emoji）。"""
    meta = meta or {}
    L = []
    L.append("=" * 62)
    L.append("续谱报告" + ("（演习 · 未写盘）" if dry_run else "（已写回）"))
    L.append("=" * 62)
    if meta.get("save"):
        L.append(f"  谱牒档    {meta['save']}")
    if meta.get("slot"):
        L.append(f"  实录槽    {meta['slot']}")
    if meta.get("prune"):
        L.append(f"  抽取口径  {meta['prune']}"
                 + ("（只留真封国）" if meta.get("real_state_only") else ""))
    L.append(f"  谱牒人数  {report['old']} → 新抽 {report['fresh']}")
    L.append("")
    L.append(f"  新增      {report['added']} 人（都带编号，桥可直达）")
    L.append(f"  更新      {report['updated']} 人"
             f"（其中改名 {report['renamed']} 人）")
    L.append(f"  保留      {report['kept']} 人（谱内独有，一个字段都不动）")
    if report["purged"]:
        # ★ 2026-09-24：占位祖先空壳（游戏为凑显示世代造的假人）**清掉** ——
        #   它们是「始祖凭空多出十几个儿子」的老根，判据见 is_book_placeholder。
        L.append(f"  清理      {len(report['purged'])} 人"
                 f"（占位祖先空壳，游戏硬造的假人）")
        L.append(f"            {'、'.join(report['purged'][:8])}"
                 + ("…" if len(report["purged"]) > 8 else ""))
    if report["orphan"]:
        L.append(f"            新档里没有这些人，原样留着："
                 f"{'、'.join(report['orphan'][:8])}"
                 + ("…" if len(report["orphan"]) > 8 else ""))
    L.append("")
    L.append("  认人依据："
             f"按编号 {report['anchor_code']} · "
             f"按姓名 {report['anchor_name']} · "
             f"按重名组 {report['anchor_dup']}")
    L.append(f"  手写字段保留 {report['hand_kept']} 条 · "
             f"升为史实 {report['upgraded']} 条")
    if report["fact_upgraded"]:
        L.append(f"  生卒补全年月日 {report['fact_upgraded']} 条")
    L.append(f"  封国/爵位/世系沿用旧值 {report['fact_kept']} 条"
             f"（★ 老人物一律不动，只有新人才写抽取值）")
    if report.get("ancestor_fixed"):
        # ★ 2026-09-24：共同远祖不吃「老人物不动」—— 旧版把它们按「先遍历到
        #   哪个宗庙就归哪个」写成了某国第N代（巢皇 → 秦·第1代），属机器错判。
        L.append(f"  共同远祖归零 {report['ancestor_fixed']} 人"
                 f"（多庙共祭，清掉封国/封代/世系"
                 + (f"；小传改写 {report['ancestor_bio']} 条"
                    if report.get("ancestor_bio") else "") + "）")
    if report["gen_kept"] or report["gen_jump"] or report.get("gen_fixed"):
        L.append(f"  世代保留旧值 {report['gen_kept']} 人 · "
                 f"世代跳变 >2 代 {report['gen_jump']} 人"
                 + (f" · 修掉旧版「兜成第 1 代」{report['gen_fixed']} 人"
                    if report.get("gen_fixed") else ""))
    L.append(f"  关系改写：父 {report['rel_father']} · "
             f"母 {report['rel_mother']} · 配偶 {report['rel_spouse']}"
             f"（血缘沿用旧值 {report['kin_kept']} 条）")
    if report["collision"]:
        L.append(f"  重名冲突另存 {report['collision']} 人（缀 #2）")
    if report["dangling_spouse"]:
        L.append(f"  配偶指向谱外被移除 {len(report['dangling_spouse'])} 条")
    if report["dangling_father"]:
        L.append(f"  父母指向谱外 {len(report['dangling_father'])} 条"
                 f"（保留名字，按根节点显示）")
    pend = report["pending"]
    L.append("")
    if pend:
        L.append(f"  待人工确认 {len(pend)} 人（**没有自动连线**，两边原样保留）：")
        for nm, why in pend[:20]:
            L.append(f"    · {nm}　{why}")
        if len(pend) > 20:
            L.append(f"    … 其余 {len(pend) - 20} 人见报告文件")
    else:
        L.append("  待人工确认 0 人")
    L.append("=" * 62)
    return "\n".join(L)


def run_merge(path, fresh_people, gen_src, src_meta, args):
    """续谱主流程：读旧档 → 合并 → 演习出报告 / --apply 备份后写回。

    返回退出码：0 正常 · 1 出错 · 2 需 --force 而未给。
    """
    old_raw = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                old_raw = json.load(f)
        except Exception as e:
            print(f"× 读不出谱牒档：{e}")
            return 1
    old_people = (old_raw or {}).get("people") or {}
    if not old_people:
        print("× 谱牒档不存在或还没有人 —— 续谱是「在已有的谱上接着写」，"
              "首次建档请用整档导入（不带 --merge）。")
        return 1

    # 人数比闸门：口径不一致（比如建档用 hist、这次用默认 anon）
    # 会让新抽人数暴涨，凭空多出几千个不相干的人。
    ratio = len(fresh_people) / max(1, len(old_people))
    if not args.force and (ratio > 2.0 or ratio < 0.5):
        print(f"× 抽取口径对不上：新抽 {len(fresh_people)} 人 vs "
              f"谱牒 {len(old_people)} 人（{ratio:.2f} 倍）。")
        print("  多半是 --prune 与建档时不一致（秦末档建档用的是 hist）。")
        print("  确认无误要强行继续，加 --force。")
        return 2

    people, cutoff, source, report = merge_into(
        old_raw, fresh_people, gen_src, src_meta)
    meta = {"save": args.save, "slot": src_meta.get("slot"),
            "prune": src_meta.get("prune"),
            "real_state_only": src_meta.get("real_state_only")}
    text = format_report(report, meta, dry_run=not args.apply)
    print()
    print(text)

    # 报告落盘 —— 演习也落，待确认清单要能逐条看
    rp = args.report or os.path.join(
        os.path.dirname(path),
        "merge_report_%s.txt" % time.strftime("%Y%m%d_%H%M%S"))
    try:
        with open(rp, "w", encoding="utf-8") as f:
            f.write(text + "\n")
            if report["pending"]:
                f.write("\n待人工确认清单（全量，这些**没有自动连线**）：\n")
                for nm, why in report["pending"]:
                    f.write(f"  {nm}\t{why}\n")
            if report["orphan"]:
                f.write("\n谱内独有清单（新档里没有，原样保留）：\n")
                for nm in report["orphan"]:
                    f.write(f"  {nm}\n")
            for n, k, t in report["dangling_father"]:
                f.write(f"  悬空父母\t{n}\t{k}\t{t}\n")
        print(f"  报告已存：{rp}")
    except Exception as e:
        print(f"  （报告落盘失败，不影响续谱：{e}）")

    if not args.apply:
        print()
        print("  这是**演习**，一个字节都没写。确认无误后加 --apply 真写。")
        return 0

    # ★ 2026-09-24：画布状态（选定名单 / 按支系隐藏名单）**整份原样带过去**。
    #   这两个键现在是谱牒级的（原来在全局 config，会串到别的书 —— 见
    #   storage 模块头）。续谱只重抽人物，绝不该把使用者在画布上点的选定清掉。
    wpayload = {"people": people, "cutoff_person": cutoff, "source": source}
    for _k in ("focused_people", "hidden_non_historical"):
        if isinstance(old_raw, dict) and old_raw.get(_k):
            wpayload[_k] = old_raw[_k]
    bak = write_atomic(path, wpayload)
    print()
    print(f"  已写回：{path}")
    print(f"  已备份：{bak or '（原文件不存在，无需备份）'}")
    print(f"  谱内人数 {len(old_people)} → {len(people)}")
    return 0


# ==================================================================== 单人入谱（M0 桥）

def _is_ph_code(c, by_code):
    """占位祖先空壳（编号带 父/祖/曾/高 且记录缺 `Ren_Sex`）。

    与 `build` 1b / `_is_ph` 同一条判据（五十三批实测：编号带后缀的记录
    100% 缺 Ren_Sex，完整真人 0 条缺）。★ 2026-09-26 审查修复：
    `_male_line` 与 `import_codes` 这两条链原来漏了它 —— 空壳无性别
    会被 `is_female` 判成男性，「入谱 / 刷新体检」把假儿子整批写回谱牒
    （五十六批刚清掉的东西又回来）。只修判据不修链，等于没修。
    """
    c = str(c or "")
    if not PLACEHOLDER_SUFFIX.search(c):
        return False
    r = by_code.get(c)
    if r is None:
        return True                     # 编号带后缀、表里查无此人 → 不是真人
    return "Ren_Sex" not in r


def _male_line(by_code, root_code):
    """本人 + 全部男性后裔（纯父系：只沿「他作为父亲」的边下探）。

    ★ 2026-09-22 使用者裁定：「入谱时，我需要他本人且他所有男性后裔全部入谱」
    —— 女儿不入谱、更不下传（与续谱名单 D11 纯父系口径一致）。
    ★ 2026-09-26 审查修复：占位祖先空壳**不参与父系后裔链**（与 build 1b 同规）
    —— 原来它们无性别、被当男性一路下探，「入谱」会把占位假儿子整批收进谱。
    """
    kids_map = defaultdict(list)
    for c, r in by_code.items():
        if _is_ph_code(c, by_code):
            continue                    # 假儿子：既不当孩子
        fc = str(r.get("Father_Code") or "").strip() or \
            str(((r.get("Parent") or {}).get("Father") or {}).get("Ren_Code") or "").strip()
        if fc and not _is_ph_code(fc, by_code):     # 也不挂在假父亲名下
            kids_map[fc].append(c)
    out, seen = [], set()
    stack = [str(root_code)]
    while stack:
        x = stack.pop()
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
        for k in kids_map.get(x, []):
            if not is_female(by_code.get(k, {})):
                stack.append(k)
    return out


def import_single(src, code, save_name, lineage=False):
    """把存档里编号=code 的人并入目标 family.json（阅览器「⇱ 入谱」桥的另一端）。

    ★ 2026-09-22 使用者裁定三件事：
      · `lineage=True`：**本人 + 全部男性后裔**一次入谱 —— 女儿不入谱不下传
        （纯父系，与续谱名单口径一致）；一次读档、一次写盘。
      · 断根（谱内无父）者的世代按**生年落桶**（与整档导入同源的 bucket_gen）：
        此前用 max+1，每入谱一次就多沉一代，同代的几位「皇」被排得乱七八糟。
      · 母亲在谱内（按编号认出）→ 写 mother 连母线；谱内查不到留空。

    与整档导入 build() 的分工：这里不筛人 —— 只把点名者合成记录：
      · 名字沿用 name_of 的氏+名规则，重名缀纯数字序数（与整档口径一致）
      · 父亲只在「其 code 已在谱内」时连线，否则断根当根节点
      · 字段口径与 build() 一致，另多写一个 `code`（D4 锚点：匹配只认编号）
      · 已在谱内（按 code 认出；或唯一同名且无编号者视为同一人）→ 补全实证字段，
        保留手工痕迹（bio/note/color/关联字段不覆盖）
      · 封国宁缺勿猜：只认「宗庙/国君表」里国爵俱在的。
    """
    code = str(code).strip()
    by_code = load_tables(src)
    if code not in by_code:
        print(f"× 编号 {code} 在四张表里都没有找到（槽目录：{src}）")
        return 1
    codes = _male_line(by_code, code) if lineage else [code]
    rc, _added, _updated = import_codes(src, codes, save_name, by_code=by_code)
    return rc


def import_codes(src, codes, save_name, by_code=None):
    """批量并入多个编号（一次读档、一次写盘）；返回 `(rc, 新增, 更新)`。

    ★ 2026-09-22「刷新体检」共用入口：main 进程内直接调（`_read` 的选择性
      缓存让连续调用只读一遍人物表）。`import_single` 是它的单人便捷形态，
      字段口径、合并规则完全一致（见那边的裁定说明）。
    """
    codes = [str(c).strip() for c in (codes or []) if str(c).strip()]
    if by_code is None:
        by_code = load_tables(src)
    codes = [c for c in codes if c in by_code]
    # ★ 2026-09-26 审查修复：占位祖先空壳一律不入谱 —— 「刷新体检」的补人
    #   名单、续谱名单的父系链都可能把它们带进来（此前 import_codes 是直写
    #   family.json 的旁路，不过 merge_into 的 is_book_placeholder 闸门）。
    _ph = [c for c in codes if _is_ph_code(c, by_code)]
    if _ph:
        codes = [c for c in codes if c not in set(_ph)]
        print(f"  跳过占位祖先空壳 {len(_ph)} 人：{'、'.join(str(by_code[c].get('Ren_Name') or c) for c in _ph[:6])}"
              + ("…" if len(_ph) > 6 else ""))
    if not codes:
        print("× 这些编号在四张表里都没有找到")
        return 1, 0, 0
    titles = load_titles(src)

    path = os.path.join(ROOT, "saves", save_name, "family.json")
    people, cutoff = {}, None
    old_raw = {}                   # 整份 raw（写回时要带着 source 一起回写）
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            old_raw = json.load(f)
        people = old_raw.get("people", {}) or {}
        cutoff = old_raw.get("cutoff_person")

    max_gen = max([v.get("generation", 0) for v in people.values()] or [0])
    added = updated = 0
    first_nm = ""
    # ★ 2026-09-26 审查修复：code→姓名 索引原来在循环内**逐人重建**
    #   （O(补人数 × 谱内人数)，「刷新体检」补几百人时是几百万次迭代）
    #   —— 移到循环外建一次，循环内新增/补编号时增量维护。
    code2name = {str(v.get("code")): n for n, v in people.items() if v.get("code")}
    for i, c in enumerate(codes):
        r = by_code[c]
        nm0 = name_of(r)
        tgt = code2name.get(c)
        linked_by = "编号 code"
        if tgt is None:
            same = [n for n, v in people.items() if n == nm0 and not v.get("code")]
            if len(same) == 1:
                tgt = same[0]          # 唯一同名且无编号 → 认定同一人，补上编号
                linked_by = "唯一同名（补 code）"
        if tgt is None and nm0 in people:
            n0 = 2
            while nm0 + dup_num(n0) in people:
                n0 += 1
            nm0 = nm0 + dup_num(n0)    # 重名缀序数，与整档导入同规（纯数字）

        t = pick_title(titles.get(name_of(r)), r.get("Ren_Generations"))
        jue, guo = t.get("jue", ""), t.get("guo", "")
        fief_gen = t.get("fief_gen", 0)
        state_name = guo if (guo and jue) else ""

        fa_code = str(r.get("Father_Code") or "").strip() or \
            str(((r.get("Parent") or {}).get("Father") or {}).get("Ren_Code") or "").strip()
        fa_name = code2name.get(fa_code, "")
        mo_code = str(r.get("Mother_Code") or "").strip() or \
            str(((r.get("Parent") or {}).get("Mother") or {}).get("Ren_Code") or "").strip()
        mo_name = code2name.get(mo_code, "")   # 母亲只在谱内时连线
        if fa_name:
            gen = people[fa_name]["generation"] + 1
        else:
            y = born_of(r)
            gen = max(1, bucket_gen(y) if y is not None else max_gen + 1)

        sp_in, sp_all = [], []
        for pc in (r.get("Ren_Pei_Ou_Code_Array") or []):
            pcs = str(pc)
            if pcs in code2name:
                sp_in.append(code2name[pcs])
                sp_all.append(code2name[pcs])
            elif pcs in by_code:
                sp_all.append(name_of(by_code[pcs]))

        zun = (r.get("Zun_Hao") or r.get("Ren_Zun_Hao") or "").strip()
        shi_hao = (r.get("Shi_Hao") or "").strip()
        note = zun or (f"谥{shi_hao}" if shi_hao else "")
        if not note and guo and jue:
            note = guo + jue

        female = is_female(r)
        kids = [name_of(by_code[str(kc)]) for kc in (r.get("Ren_Zi_Nv_Code_Array") or [])
                if str(kc) in by_code]
        bio = make_bio(nm0, r, t, sp_all, kids, is_hist(c), female,
                       state_name=state_name, fief_title=jue)

        rec = {
            "father": fa_name, "mother": mo_name,
            "color": "", "bg_color": "", "note": note,
            "gender": "女" if female else "男",
            "generation": gen,
            "historical": "是" if is_hist(c) else "否",
            "divine": "否",
            "birth": born_time_of(r),
            "death": str(died_of(r)) if died_of(r) else "",
            "rank": 0, "spouses": sp_in,
            "associate_of": "", "associate_type": "", "associate_rank": 0,
            "state_group": (state_name + jue) if (state_name and jue) else "",
            "state_name": state_name,
            "fief_title": jue, "fief_gen": fief_gen,
            "root_sort": 0,
            "bio": bio,
            "code": c,
        }

        if tgt:
            op = people[tgt]
            for k, v in rec.items():
                if k in ("bio", "note", "color", "bg_color", "associate_of",
                         "associate_type", "associate_rank", "hide_parent_line"):
                    continue                # 手工痕迹不覆盖
                if k == "generation" and not fa_name:
                    continue                # 断根者世代不覆盖（手工排好的不动）
                if v in ("", 0, [], None) and op.get(k):
                    continue                # 新值是空的不覆盖已有实证
                op[k] = v
            people[tgt] = op
            nm0 = tgt
            updated += 1
        else:
            people[nm0] = rec
            max_gen = max(max_gen, gen)
            added += 1
        if i == 0:
            first_nm = f"{nm0}（编号 {c}，{linked_by}）"
        code2name[str(c)] = nm0          # 索引增量维护（新增 / 补编号都可能改名）

    # ★ 写回必须**整份 raw 回写**，不能只 dump {people, cutoff} ——
    #   那样会把 `source`（谱牒 ↔ 实录的对应关系）冲掉，切谱牒时就配不上槽了。
    #   （顺带修了个潜伏 bug：原实现更新已有的人时用 `old` 复用了 raw 变量名，
    #     导致 source 判断永远为假 —— 更新式入谱会把 source 冲掉。）
    #   ★ 2026-09-24：画布状态（选定名单 / 按支系隐藏名单）同理必须带过去 ——
    #     入谱只是加人，不该把画布上点过的选定清掉。
    raw = {"people": people, "cutoff_person": cutoff}
    if isinstance(old_raw, dict):
        if old_raw.get("source"):
            raw["source"] = old_raw["source"]
        for _k in ("focused_people", "hidden_non_historical"):
            if old_raw.get(_k):
                raw[_k] = old_raw[_k]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # ★ 2026-09-26 审查修复（H4）：原来这里也是裸 `open(path, "w")` ——
    #   无备份、非原子，写一半崩了就是整本谱牒损坏（与 storage.write_save
    #   同病，七十一批「18:22 成果被覆盖」事故的同源隐患）。统一走
    #   write_atomic：备份 → 校验备份可读 → 写 tmp → os.replace。
    bak = write_atomic(path, raw, keep_backup=True)
    print("=" * 70)
    if len(codes) > 1:
        print(f"入谱完成（共 {len(codes)} 人）：{first_nm}")
    else:
        print(f"入谱完成：{first_nm}")
    print(f"  新增 {added} · 更新 {updated}；谱内总人数 {len(people)}")
    print(f"  写入：{path}")
    print(f"  备份：{bak or '（原文件不存在，无需备份）'}")
    print("=" * 70)
    return 0, added, updated


# ==================================================================== main

def main():
    ap = argparse.ArgumentParser(description="大周列国志 → 家族树（多表合并）")
    ap.add_argument("--src", required=True)
    ap.add_argument("--save", default="")
    ap.add_argument("--seeds", default="",
                    help="始祖名单，逗号分隔；不给则从 --seeds-from 的树根节点自动取")
    ap.add_argument("--seeds-from", default="",
                    help="从哪个存档读根节点当始祖（默认上古时代）")
    ap.add_argument("--prune", default="anon",
                    choices=["none", "male-son", "anon", "hist"],
                    help="筛人方式：hist 只收史实人物 / none 全要 / "
                         "male-son 剪无男嗣的男性 / anon（默认）再剪匿名女性")
    ap.add_argument("--real-state-only", action="store_true",
                    help="只保留真封国（宗庙 / 势力），不再拿氏当封国；"
                         "没有真封国的人留空")
    ap.add_argument("--no-history-states", action="store_true",
                    help="不用人工史补国名（tools/history_states.json）。"
                         "默认只在沙盒全局用，见 --history-states")
    ap.add_argument("--history-states", action="store_true",
                    help="强制启用人工史补国名。★ 2026-09-22 起**默认只在沙盒全局启用**："
                         "那张表是按秦末起义（前 209）的**全局**整理的，"
                         "用到沙盒局部/争霸/家族模式上会凭空补出这盘根本不存在的国"
                         "（实测卫氏朝鲜档：存档国表里一条「汉」都没有，"
                         "却被补成「汉国 · 王」，画布上多出一个「汉国世系」框）")
    ap.add_argument("--era", default="",
                    help="剧本名（秦末 / 上古）。不填则自动判 —— 判据同 main.py "
                         "的 _detect_era（王朝纪元 → 分段起点年 → 玩家国阶段）")
    ap.add_argument("--compare", default="")
    ap.add_argument("--watch", default="",
                    help="续谱名单：逗号分隔的存档编号。名单里的人（以及他们的"
                         "父系后裔链）会被额外收进谱，**不受 --prune 剪枝影响**。"
                         "使用者的口径：非史实人物默认一个都不要，只有点名的才收。")
    ap.add_argument("--person", default="",
                    help="单人入谱（M0 桥）：把这一个 Ren_Code 的人并入 --save 的 "
                         "family.json，不做整档抽取；配合阅览器「⇱ 入谱」按钮使用")
    ap.add_argument("--lineage", action="store_true",
                    help="配合 --person：本人 + 全部男性后裔一次入谱（纯父系，女儿不入谱"
                         "不下传）。★ 2026-09-22 使用者裁定，入谱按钮默认带整支")
    # ---- 增量续谱（自动续谱闭环）----
    ap.add_argument("--merge", action="store_true",
                    help="增量续谱：把新抽的人物**合并**进 --save 的 family.json，"
                         "保留手写的小传/注释/配色/祖序，绝不删除谱内独有的人。"
                         "默认是**演习**（只出报告、不写盘），要真写再加 --apply")
    ap.add_argument("--apply", action="store_true",
                    help="配合 --merge：真正写盘（先自动备份 family.json）")
    ap.add_argument("--force", action="store_true",
                    help="越过人数比闸门（新抽人数与谱牒人数相差 2 倍以上时默认拒绝）")
    ap.add_argument("--report", default="",
                    help="续谱报告的落盘路径（默认 saves/<谱名>/merge_report_<时间>.txt）")
    args = ap.parse_args()

    if not check_slot(args.src):
        return 1

    # 单人入谱：不需要 seeds / prune 那一套，直接走桥
    if args.person:
        if not args.save:
            print("× 单人入谱需要 --save 指定谱牒档名")
            return 1
        return import_single(args.src, args.person, args.save,
                             lineage=bool(args.lineage))

    seeds = [s.strip() for s in args.seeds.split(",") if s.strip()]
    if args.prune == "hist":
        pass                      # 只收史实，不需要始祖名单
    elif not seeds:
        ref = args.seeds_from or "上古时代"
        p = os.path.join(ROOT, "saves", ref, "family.json")
        if os.path.exists(p):
            old = json.load(open(p, encoding="utf-8"))
            old = old.get("people", old)
            seeds = [n for n, v in old.items()
                     if not v.get("father") and not v.get("mother")]
            print(f"  始祖名单：从「{ref}」的 {len(seeds)} 个根节点取")
        else:
            print(f"  （找不到参考存档「{ref}」，不做始祖限定）")

    watch = [s.strip() for s in args.watch.split(",") if s.strip()]

    # ★ 2026-09-22 使用者报「卫氏朝鲜是局部剧本，没有汉国，为什么画布上写了汉国世系框」。
    #   根因：`tools/history_states.json` 的「秦末实有」组是按**秦末起义（前 209）全局**
    #   整理的人工知识层，原先对所有存档默认启用。卫氏朝鲜是**沙盒局部**（前 194），
    #   存档势力名单里有「汉 / 张楚 / 西楚 / 项」这一批 —— 它们在这盘里**不是国**
    #   （实测该档 `Save_KingData_*` 国表里「汉」命中 0 条），却被史补层补成
    #   「国 + 王爵」，画布上就凭空多出一个「汉国世系」框。
    #   改成：**只有沙盒全局（号段 1-999）才默认启用**；局部 / 争霸 / 家族一律关掉。
    #   想强制要，加 `--history-states`。
    if args.no_history_states:
        use_history = False
    elif args.history_states:
        use_history = True
    else:
        try:
            from sync_from_mumu import slot_mode
            use_history = (slot_mode(os.path.basename(os.path.normpath(args.src)))
                           == "沙盒全局")
        except Exception:
            use_history = True
        if not use_history:
            print("  （非沙盒全局：不用人工史补国名 —— 只认游戏自己登记过的国）")

    people, stats, name2code, gen_src = build(
        args.src, seeds, args.prune, args.real_state_only,
        history=use_history, watch=watch)
    if not people:
        print("× 没解析出人物")
        return 1

    if args.compare:
        compare(people, args.compare)

    if not args.save:
        print("（未指定 --save，只分析不落盘）")
        return 0

    out = os.path.join(ROOT, "saves", args.save)
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, "family.json")

    src_meta = {
        "slot": os.path.basename(os.path.normpath(args.src)),
        "slot_path": os.path.abspath(args.src),
        "era": args.era or detect_era(args.src),
        "imported": time.strftime("%Y-%m-%d %H:%M"),
        "prune": args.prune,
        "real_state_only": bool(args.real_state_only),
    }

    # ============================================================ 增量续谱
    if args.merge:
        return run_merge(path, people, gen_src, src_meta, args)

    # 整档覆盖（老口径，续谱请改用 --merge）
    _strip_internal(people)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"people": people, "cutoff_person": None,
                   "source": src_meta}, f,
                  ensure_ascii=False, indent=2)

    gs = [v["generation"] for v in people.values()]
    print()
    print("=" * 70)
    print(f"已写出：{path}")
    print("=" * 70)
    print(f"  人物总数  {len(people)}")
    print(f"  世代范围  第{min(gs)} ~ 第{max(gs)} 代"
          f"（定不出世代的 {stats['no_gen']} 人）")
    print(f"  女性      {sum(1 for v in people.values() if v['gender'] == '女')}")
    print(f"  史实人物  {stats['hist']}")
    print(f"  有爵位    {stats['titled']}")
    print(f"  有封国    {sum(1 for v in people.values() if v['state_name'])}"
          f"（受封实录 {stats['titled_state']} 人 · 父系继承 {stats['inherited']} 人"
          f" · 史补 {stats['hist_state']} 人）")
    print(f"  有配偶    {sum(1 for v in people.values() if v['spouses'])}")
    print(f"  有生年    {sum(1 for v in people.values() if v['birth'])}")
    print(f"  有小传    {sum(1 for v in people.values() if v['bio'])}")
    print(f"  重名加限定词 {stats['renamed']} 人")
    print()
    print("  样例：")
    for nm in list(people)[:6]:
        v = people[nm]
        print(f"    {nm:<14s} 第{v['generation']}代 {v['gender']} "
              f"{v['state_name'] or '—':<6s} {v['fief_title'] or '—':<3s} "
              f"{'史' if v['historical'] == '是' else '  '} "
              f"生{v['birth'] or '—':<7s} 配{'、'.join(v['spouses'][:2]) or '—'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())