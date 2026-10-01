# -*- coding: utf-8 -*-
"""实录层 · 派生视图（人物合并总表 / 史实筛分表）。

从 `views/person_view.py` 里搬出来的 —— 这段逻辑**不碰任何控件**，
只依赖「槽 + 关系图 + 交叉引用」，所以应该在**载入实录槽时**就跑，
而不是等「人物」页被打开才跑。

为什么必须搬：
  默认页签可以是「表格」「家谱」；那些页不会建 PersonView。
  派生表若只在 PersonView 里建，状态栏「实录 N 人」就会是 0，
  「查档桥」也会因为 `record_people` 空而失效。

对外只有一个函数：
  `derive(slot, rel, xref, era)` → `(people, hist_count)`  推导并挂回 slot.tables
"""
import logging

from . import catalog as C
from . import profiles as PF
from . import saveload as S

logger = logging.getLogger(__name__)

# 参与合并的人物表族（顺序即优先级：先出现的字段更权威）
#
# ★ 2026-09-21 移除 `Save_ED_Ren_Data`（曾译「人物 · 已故（旧表）」）。
#   实测它与 `Save_Ren_Data` / `Save_Chu_Sheng_Data` 的**字段 schema 完全相同**
#   （Class_Type/Ren_Code/…/Parent 共 26 个字段一一对应），只是分表存放
#   （118 条 vs 3568 / 16 条）—— 是同一批数据的分片，不是独立概念。
#   单独挂一个「已故（旧表）」的树节点只会误导（0.4 版遗留的猜测性命名）。
#   合并总表本来就会把这批人收进来，所以直接从这里去掉，不影响召回。
PERSON_TABLES = ("Save_Ren_Data", "Save_Dead_Ren_Data", "Save_Woman_Data",
                 "Save_Chu_Sheng_Data")

MERGE_NAME = "人物 · 合并总表"
HIST_NAME = "人物 · 史实人物"
GEN_NAME = "人物 · 非史实"
FOLLOW_NAME = "人物 · 关注世系"
# ★ 2026-09-25：《全史存档》等合并谱的「谱牒总谱」—— 把 family.json 的人物
#   适配成实录风格派生表挂进人物页（见 attach_book_table）。
BOOK_NAME = "人物 · 谱牒总谱"


def attach_book_table(slot, people, label=""):
    """把谱牒 `people` 适配成实录风格行，挂成人物页可渲染的派生表（幂等）。

    ★ 使用者需求：总谱的一万多人要能在**人物页**查、看、跳家谱。
      适配的字段 = 谱牒自带（编号/姓名/性别/生卒/世代/势力/称号）
      ＋ `extra` 里由 `enrich_staging` 从各档存档原文回捞的那批
      （智略/等级/文化/性格/谥号/表字/继位时间/所在/官职/政策/能力/特质）。
      取不到就留空 —— 人物页显示「—」，**绝不编造**（值码宁缺勿猜）。
    ★ 2026-09-25 使用者裁定：`世代` 一律用**合并器重算的** `generation`，
      `extra` 里那份原文族谱世代（`Ren_Dai_Shu`）**不采纳** —— 它是「单个剧本
      档里族谱的第几代」，跨 32 档口径不一（实测嬴政：原文 71 / 合并 82），
      采纳它会让「人物页」与「家谱页」两个世代数打架。
      幂等：重复调用覆盖同名表；换到非合并谱时由调用方 pop 掉。
    """
    if slot is None or not people:
        return False
    rows = []
    for nm, v in people.items():
        code = str(v.get("code") or "")
        if not code:
            continue
        g = v.get("gender")
        row = {
            "Ren_Code": code,
            "Ren_Name": nm,
            "Ren_Sex": 0 if g == "男" else (1 if g == "女" else ""),
            "Ren_Chu_Sheng_Time": v.get("birth") or "",
            "Ren_End_Time": v.get("death") or "",
            "Ren_Dai_Shu": v.get("generation"),
            "Ren_Shi_Li_1": v.get("state_name") or "",
            "Ren_Zun_Hao": v.get("note") or "",
            "_来源表": label or "谱牒",
        }
        # ★ 2026-09-26：`extra` 里的**存档原文扩展字段**（enrich_staging 回捞：
        #   智略/等级/文化/性格/谥号/表字/继位时间/所在/官职/政策/能力/特质）
        #   **原样透传** —— 人物页原生认识这些键，无需任何新机制。
        #   ⚠️ 这里的名单里**故意不含** `Ren_Dai_Shu`：世代见下面那句。
        #   ★★ 2026-09-26 补 `Ren_End_Old`（享年）—— 使用者三报「总谱大量
        #   卒年显示 —」的最后一条断点就在这：enrich/merge 都落了盘、
        #   `Profile` 也按「真实卒年 → 生年+享年推算」排好了优先级，
        #   唯独这张白名单没放行享年 ⇒ 没录到死亡记录的人（在世者居多）
        #   到达 Profile 时 `end_old=None` ⇒ 推算无从谈起 ⇒ 「—」。
        ex = v.get("extra") or {}
        for k in ("Ren_Zhi_Lue", "Ren_Wen_Hua", "Ren_Xing_Ge", "Ren_Leve",
                  "Ren_Zun_Hao", "Ren_Biao_Zi", "Ren_Ji_Wei_Time",
                  "Ren_Map_Name", "Ren_In_Map_Position", "Ren_End_Old",
                  "Last_Ren_Official_Position_Data", "Ren_Zheng_Ce_Array",
                  "Ren_Neng_Li_Array", "Buff_Array"):
            if k not in ex:
                continue
            val = ex[k]                 # ⚠️ 别用 v —— 外层 v 是人物记录本身
            # ★ 数值型字段「0」也是真值：等级 0 = **庶**、智略 0 是合法分数、
            #   享年 0 = 当年夭折（也是真卒年）。
            #   老判据把 0 当空 ⇒ 庶整片透传不出去 ⇒ 总谱勾「庶」筛出 0 行
            #   （2026-09-25 使用者报「筛选无效」的最后一处漏网）。
            if val in (None, "", [], {}):
                continue
            if val == 0 and k not in ("Ren_Leve", "Ren_Zhi_Lue", "Ren_End_Old"):
                continue
            row[k] = val
        # ★ 世代取**合并器重算的** `generation`（使用者 2026-09-25 裁定），
        #   它是唯一在 32 档之间统一过的世代；只有它缺失时才退回原文那份。
        gen = v.get("generation")
        row["Ren_Dai_Shu"] = gen if gen not in (None, "") else ex.get("Ren_Dai_Shu")
        rows.append(row)
    t = S.Table(name=BOOK_NAME,
                label=f"人物 · 谱牒总谱（{label}）" if label else BOOK_NAME)
    t.rows = rows
    t.srcs = [S.Src("（谱牒）") for _ in rows]
    t.files = ["（谱牒）"]
    slot.tables[BOOK_NAME] = t
    return True


# 族谱表里的人物 —— 字段名与原表不同，要改名后并入
GENEALOGY_RENAME = {
    "Born_Time": "Ren_Chu_Sheng_Time",
    "Dead_Time": "Ren_End_Time",
    "Generations": "Ren_Dai_Shu",
}
GENEALOGY_FOLDED = ("Father_Code", "Father_Name", "Mother_Code", "Mother_Name",
                    "Memorial_Ren_Sex")


def _genealogy_rows(slot):
    """族谱表里的人物 —— 摊平 `Genealogy_Ren_Record_Array` 并改名后并入。

    注意：族谱表的人物**存档本身就没写智略与等级**，这里也不去猜。
    """
    t = slot.table("Jia_Zu_Genealogy")
    if not t:
        return []
    label = C.label_of_family("Jia_Zu_Genealogy")
    out = []
    for gi, (g, gsrc) in enumerate(zip(t.rows, t.srcs)):
        for pi, r in enumerate(g.get("Genealogy_Ren_Record_Array") or []):
            if not isinstance(r, dict) or not r.get("Ren_Code"):
                continue
            row = {GENEALOGY_RENAME.get(k, k): v for k, v in r.items()}
            for k in GENEALOGY_FOLDED:
                row.pop(k, None)
            fam = {"Ren_Code": r.get("Father_Code") or "",
                   "Ren_Name": r.get("Father_Name") or ""}
            mom = {"Ren_Code": r.get("Mother_Code") or "",
                   "Ren_Name": r.get("Mother_Name") or ""}
            if any(fam.values()) or any(mom.values()):
                row["Parent"] = {"Father": fam, "Mother": mom}
            if r.get("Memorial_Ren_Sex") == "女":
                row["Ren_Sex"] = 1
            if not row.get("Ren_Name"):
                row["Ren_Name"] = (f"{r.get('Ren_Shi') or r.get('Ren_Xing') or ''}"
                                   f"{r.get('Ren_Ming') or ''}")
            out.append((row, f"{gsrc.file} · 第 {gi} 条族谱 · 谱系第 {pi} 位（{label}）"))
    return out


def derive(slot, rel, xref, era="上古", followed=None):
    """推导「人物 · 合并总表」+「史实/非史实筛分表」，返回 code → Profile。

    幂等：重复调用只会覆盖自己产出的那几张派生表，不动原始表族。
    """
    if slot is None:
        return {}, 0

    # ★ 2026-09-24：人物页表格的「余寿」列要一个共同参照年 —— 本档走到哪一年。
    #   放 `Profile` 的类属性上一次设好（见 profiles.Profile.NOW_YEAR）。
    #   取不到（手写谱牒没绑存档）就留 None，余寿列显示「—」，不报错。
    try:
        PF.Profile.NOW_YEAR = S.game_year(slot)
    except Exception:
        PF.Profile.NOW_YEAR = None

    merged, order = {}, []

    def feed(key, row, src_label):
        if key not in merged:
            merged[key] = dict(row)
            merged[key]["_来源"] = src_label
            order.append(key)
        else:
            for k, v in row.items():
                if not merged[key].get(k):
                    merged[key][k] = v

    for tname in PERSON_TABLES:
        t = slot.table(tname)
        if not t:
            continue
        for row, src in zip(t.rows, t.srcs):
            code = str(row.get("Ren_Code") or "")
            if not code:
                continue
            feed(code, row, src.label())
            merged[code].setdefault("_来源表", C.label_of_family(tname))

    for row, where in _genealogy_rows(slot):
        code = str(row["Ren_Code"])
        feed(code, row, where)
        merged[code].setdefault("_来源表", C.label_of_family("Jia_Zu_Genealogy"))

    # 补「父名/母名/子女数」—— 先查合并表内的姓名，再查关系图
    by_code = {str(r.get("Ren_Code")): r.get("Ren_Name", "") for r in merged.values()}
    if rel is not None:
        for code, r in merged.items():
            prof = rel.profile(code)
            f = prof["父"]
            if f and f[0].person:
                r["_父名"] = f[0].person.name
            m = prof["母"]
            if m:
                r["_母名"] = (m[0].note if m[0].placeholder
                              else (m[0].person.name if m[0].person else ""))
            kids = prof["子女"]
            if kids:
                r["_子女数"] = len(kids)

    for r in merged.values():
        par = r.get("Parent") or {}
        if isinstance(par, dict):
            f = par.get("Father") or {}
            if isinstance(f, dict) and f.get("Ren_Code") and not r.get("_父名"):
                r["_父名"] = by_code.get(str(f["Ren_Code"])) or f.get("Ren_Name", "")
            m = par.get("Mother") or {}
            if isinstance(m, dict) and m.get("Ren_Code") and not r.get("_母名"):
                r["_母名"] = by_code.get(str(m["Ren_Code"])) or m.get("Ren_Name", "")

    # 挂回槽，并挪到最前（人物页导航「全部人物」排在第一位）
    t = S.Table(name=MERGE_NAME, label="人物 · 合并总表（派生视图）")
    t.rows = [merged[k] for k in order]
    t.srcs = [S.Src("（合并视图）") for _ in order]
    t.files = ["（合并视图）"]
    slot.tables[MERGE_NAME] = t
    slot.tables.move_to_end(MERGE_NAME, last=False)

    people = {}
    for k in order:
        people[k] = PF.Profile(k, merged[k], xref, era)
    for tname in PERSON_TABLES:
        tt = slot.table(tname)
        if not tt:
            continue
        for r in tt.rows:
            c = str(r.get("Ren_Code") or "")
            if c and c not in people:
                people[c] = PF.Profile(c, r, xref, era)

    hist = _split(slot, merged, order, rel, followed or set())
    logger.info(f"派生视图：合并 {len(people)} 人 · 史实 {hist}")
    return people, hist


def _split(slot, merged, order, rel, followed):
    """把合并表切成「史实 / 非史实 / 关注世系」三张。"""
    src_rows = [merged[k] for k in order]
    hist, gen = [], []
    for r in src_rows:
        code = str(r.get("Ren_Code") or "")
        (hist if PF.is_historical(code) else gen).append(r)

    def put(name, label, rows):
        if not rows:
            slot.tables.pop(name, None)
            return
        nt = S.Table(name=name, label=label)
        nt.rows = list(rows)
        nt.srcs = [S.Src("（派生·史实筛分）") for _ in rows]
        nt.files = ["（派生·史实筛分）"]
        slot.tables[name] = nt

    put(HIST_NAME, HIST_NAME, hist)
    put(GEN_NAME, GEN_NAME, gen)

    followed = {str(f) for f in (followed or []) if str(f)}
    if followed and rel is not None:
        lin = PF.Lineage(rel)
        keep = set()
        for f in followed:
            keep.add(str(f))
            for _d, c in lin.descendants(f):
                keep.add(str(c))
        rows = [r for r in src_rows if str(r.get("Ren_Code") or "") in keep]
        put(FOLLOW_NAME, f"人物 · 关注世系（{len(followed)} 位始祖）", rows)
    else:
        slot.tables.pop(FOLLOW_NAME, None)
    return len(hist)


def people_stats(slot, book_codes=None, watch_codes=None):
    """人物筛选勾选框后面那些数字。

    口径**必须与人物页的筛选完全一致**，否则「显示 3998」和「勾了筛出 4001」
    对不上，比不显示数字还糟：
      史实 / 非史  —— 编号位数（`PF.is_historical`，与 `_split` 同源）
      男性 / 女性  —— `Ren_Sex`（0 男 / 1 女，与 `relations.Person.sex_label` 同）
      在世 / 已故  —— 所在表族（活人表/女性表/出生表=在世、已故表=已故）
      出生记录     —— 编号出现在出生表（`Save_Chu_Sheng_Data`）里
      谱牒内       —— 编号在谱牒里（`book_codes`）
      续谱名单     —— 编号在续谱名单里（`watch_codes`）

    ★ 2026-09-21 修「选了在世还是好多不在世的」：
      原实现 `alive_of.get(code, True)` —— **查不到就算在世**。
      但合并总表里有一大批人只存在于**族谱表**（实测 Save_All_1：8988 人里
      2150 人只挂族谱表），而 `RelationGraph` 给这拨人一律记 `alive=False`。
      于是「筛选口径说他在世、详情卡说他已经死了」，两边打架。
      现在改成**默认已故**（不在活人/女性/出生三张表里就是已故），与关系图完全同口径。
      实测三张表互不重叠（活人表∩已故表 = 0），所以「先来优先」其实不起作用，
      这里保留按 PERSON_TABLES 顺序扫只是为了让 code 去重。
    """
    if slot is None:
        return {}
    t = slot.table(MERGE_NAME)
    if t is None:
        return {}

    alive_of = {}
    born_codes = set()
    for tname in PERSON_TABLES:
        tt = slot.table(tname)
        if tt is None:
            continue
        al = tname != "Save_Dead_Ren_Data"
        for r in tt.rows:
            c = str(r.get("Ren_Code") or "")
            if not c:
                continue
            if c not in alive_of:
                alive_of[c] = al
            if tname == "Save_Chu_Sheng_Data":
                born_codes.add(c)

    book = {str(c) for c in (book_codes or ())}
    watch = {str(c) for c in (watch_codes or ())}
    s = {"全部": 0, "史实": 0, "非史": 0, "男性": 0, "女性": 0,
         "在世": 0, "已故": 0, "出生记录": 0, "谱牒内": 0, "续谱名单": 0}
    for r in t.rows:
        code = str(r.get("Ren_Code") or "")
        if not code:
            continue
        s["全部"] += 1
        s["史实" if PF.is_historical(code) else "非史"] += 1
        s["女性" if str(r.get("Ren_Sex")) == "1" else "男性"] += 1
        s["在世" if alive_of.get(code, False) else "已故"] += 1
        if code in born_codes:
            s["出生记录"] += 1
        if code in book:
            s["谱牒内"] += 1
        if code in watch:
            s["续谱名单"] += 1
    return s


def book_stats(rows, alive_of=None, born_codes=None, book_codes=None,
               watch_codes=None):
    """「人物 · 谱牒总谱」那张表的筛选计数。

    ★ 2026-09-25 使用者报「选中总谱后筛选无效」的根因：筛选栏数字与状态栏
      一律走 `people_stats(slot, ...)`（**实录槽**口径），而总谱是另一批人 ——
      于是出现「命中 13526 / 共 11874 人」这种自相矛盾的读数，使用者当然觉得
      筛选没生效。这里与 `people_stats` **同一套口径、同一套键名**，
      只把统计对象换成谱牒自己的行。

    ⚠️ 「在世/已故」沿用调用方给的 `alive_of`（`_filter_ctx` 已给总谱的人按
       **卒年**兜过底）；「出生记录」= 编号在本档出生表里 —— 谱牒没有出生表，
       所以这项基本恒 0，是**如实反映**，不是漏算。
    """
    alive_of = alive_of or {}
    born = {str(c) for c in (born_codes or ())}
    book = {str(c) for c in (book_codes or ())}
    watch = {str(c) for c in (watch_codes or ())}
    s = {"全部": 0, "史实": 0, "非史": 0, "男性": 0, "女性": 0,
         "在世": 0, "已故": 0, "出生记录": 0, "谱牒内": 0, "续谱名单": 0,
         "非平民": 0}
    for r in (rows or ()):
        code = str(r.get("Ren_Code") or "")
        if not code:
            continue
        s["全部"] += 1
        s["史实" if PF.is_historical(code) else "非史"] += 1
        s["女性" if str(r.get("Ren_Sex")) == "1" else "男性"] += 1
        s["在世" if alive_of.get(code, False) else "已故"] += 1
        if code in born:
            s["出生记录"] += 1
        if code in book:
            s["谱牒内"] += 1
        if code in watch:
            s["续谱名单"] += 1
        if PF.identity_of(r):
            s["非平民"] += 1
    return s
