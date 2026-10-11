# -*- coding: utf-8 -*-
"""爵称口径 —— 「铭牌 / 表格 / 世系框」该按什么爵称上色。

★ 2026-09-26 使用者裁定（附史料核对，见《项目日志》第七十九批）：

  1. **五等爵（公侯伯子男）始于西周**；商代只有侯、甸、男等「外服」，
     并不是五等爵。⇒ **周以前（上古 / 夏 / 商）拿「尊号」当爵位上色**，
     **西周以后按实际爵位等级上色**。
     史料：《五等爵位》《公侯伯子男》——「五等爵位……形成于西周时期」；
     「商代已有侯、甸、男等『外服』诸侯」。
  2. **夏、商、周的天子一律「王」**。商王**生前称王**，死后才被追尊为
     「帝」——「帝」是**死后神号**（史料：「商朝君主生前称王，死后称帝」），
     所以天子不给「帝」色。
  3. **「帝」色只给两种人**：① **上古**（三皇五帝 —— 后人追赠的圣王号）
     ② **秦始皇以后**（前 221 起，「帝」是帝号；《史记》：「采上古『帝』位号，
     号曰皇帝」）。

⚠️ 本模块**只算「显示用爵称」，不改数据** —— `fief_title`（存档原文爵位）
   原样保留，详情卡/小传仍显示原文口径；标识色按上面这套史观走。
"""
import json
import os
from typing import Dict

from .timeline import era_of, to_int

# 爵称（由尊到卑）；「男」在游戏数据里极少但史料有，一并备着
JUE_ORDER = ("帝", "王", "公", "侯", "伯", "子", "男", "卿")

# 尊号里出现这些字 → 视为该爵称（顺序 = 优先级：帝 > 王 > 公 > 侯 > 伯 > 子 > 男）
_ZUNHAO_MAP = (("皇", "帝"), ("帝", "帝"), ("王", "王"), ("公", "公"),
               ("侯", "侯"), ("伯", "伯"), ("子", "子"), ("男", "男"))

# 粗朝代：西周/春秋/战国 都算「周」（使用者原话「按开始分封的时代分：
# 周朝赵 / 汉朝赵」）
_COARSE = {"西周": "周", "春秋": "周", "战国": "周", "秦": "秦", "西汉": "汉",
           "东汉": "汉", "三国": "三国", "晋": "晋", "南北朝": "南北朝",
           "隋": "隋", "唐": "唐", "五代": "五代", "宋": "宋"}
# 粗朝代名 → 世系框标题用的前缀（**不加「朝」字** —— 使用者 2026-09-26 裁定；
# 且西周/春秋/战国一律并成「周」）
_PREFIX = {"上古": "上古", "夏": "夏", "商": "商", "周": "周", "秦": "秦",
           "汉": "汉", "三国": "三国", "晋": "晋", "南北朝": "南北朝",
           "隋": "隋", "唐": "唐", "五代": "五代", "宋": "宋"}

# 王朝名（天子判据）：世系/势力 == 这三家 ⇒ 按「王」上色
_DYNASTY = ("夏", "商", "周")

# 国爵表（`tools/guo_jue.py` 抽、谱牒 `source` 存；界面启动时 install 进来）
_GUO_JUE: Dict[str, Dict[str, str]] = {}      # {国: {朝代: 爵称}}
_GUO_JUE_FLAT: Dict[str, str] = {}            # {国: 爵称}（众数兜底）

# ★ 2026-10-02（C 批）**卿室家族成员**的编号集合 —— 由 `main` 在载入实录槽后
#   用 `app/gongqing.qing_members()` 注入（存档实证：家族总表的 `Jia_Zu_Type`）。
#   与国爵表同款思路：模块级注入、按槽刷新，未注入（无槽 / 导出的合并谱）时为空。
_QING_CODES: set = set()


def install_qing_codes(codes) -> None:
    """注入「卿室家族成员」编号集合（`None` / 空 ⇒ 清空，退回姓氏启发式）。

    只收**卿室**：宗室 / 公室是王族，其成员该按王/国君上色，不染「卿」色。
    """
    global _QING_CODES
    _QING_CODES = {str(c) for c in (codes or ()) if str(c)}


def install_guo_jue(src) -> None:
    """从谱牒 `source` 注入国爵表（切谱牒时调一次）。"""
    global _GUO_JUE, _GUO_JUE_FLAT
    if isinstance(src, dict):
        _GUO_JUE = src.get("guo_jue") or {}
        _GUO_JUE_FLAT = src.get("guo_jue_flat") or {}
    else:
        _GUO_JUE, _GUO_JUE_FLAT = {}, {}
# 「真王朝时代」—— 只有这些年份区间里才认天子（战国以后周天子名存实亡，
# 秦/汉的君族也可能在宗庙世系里带「周」字，见 is_tianzi 注释）
_TIANZI_ERAS = ("夏", "商", "西周", "春秋")


def coarse_era(era: str) -> str:
    """细朝代（西周/春秋/战国…）→ 粗朝代（周/汉/…）。"""
    return _COARSE.get(era, era or "")


def era_prefix(era: str) -> str:
    """朝代 → 世系框标题前缀（「周」「汉」…）。

    ★ 2026-09-26 使用者：① 西周/春秋/战国 **基本上算一个朝代** ⇒ 一律并成「周」；
      ② **「X朝X国」的「朝」字不要** ⇒ 前缀不带「朝」。
    """
    c = coarse_era(era)
    return _PREFIX.get(c, c)


def branch_name(guo: str, shi: str) -> str:
    """同一国多支时的**支名**（如齐分成「姜齐」「田齐」）。

    ★ 2026-09-26 使用者：「周朝齐国不是已经分姜齐和田齐了吗」——
      所以同名的各支要用**氏 + 国名**命名，而不是「周齐（妫满）」这种。
      支名可手改：`tools/jue_history.json` 里的 `_支名` 段，形如
      `{"齐": {"姜": "姜齐", "妫": "田齐"}}`；表里没有就按「氏 + 国名」拼，
      氏取不到则退回 `guo`（调用方负责兜底）。
    """
    _ensure_history()
    m = (_HIST_BRANCH or {}).get(guo) or {}
    if shi and shi in m:
        return str(m[shi])
    return f"{shi}{guo}" if shi else guo


def zunhao_tier(*texts) -> str:
    """从尊号 / 小传里抽爵称。

    使用者口径：「上古夏商时期的**尊号就是爵位**，可以按照尊号给色」。
    实测样本：`西周惠公`→公、`南公`→公、`虞公`→公、`帝辛`→帝、`商王`→王、
    `秦始皇`→帝（"皇"也算）。
    """
    for t in texts:
        s = str(t or "")
        if not s:
            continue
        for word, jue in _ZUNHAO_MAP:
            if word in s:
                return jue
    return ""


def era_of_info(info, cutoff_year=None) -> str:
    """这个人的朝代。

    ★ 判据顺序（2026-09-26 修正，实测踩过）：**受封/继位时间 → 卒年 → 生年**。
      只用生年会错：姜尚生于前 1146（商），但**封齐在周初** —— 按生年他会被
      算成「商」，于是走「尊号当爵位」的老规矩，永远显示不出「齐世代为侯」。
      实测同病：姬发/姬旦/姬昌 全落在「商」。
      `Ren_Ji_Wei_Time` 是 `enrich_staging` 回捞的存档原文继位时间。
    """
    r = info or {}
    ex = r.get("extra") or {}
    y = None
    #   ★ 顺序：**卒年 → 受封/继位时间 → 生年**。卒年最能代表「这个人属于哪个
    #     时代」：嬴政若按继位时间（前 246 称秦王）会落进「战国」，
    #     按卒年（前 210）才是「秦」⇒ 才拿得到「帝」色。
    for cand in (r.get("death"), ex.get("Ren_Ji_Wei_Time"), r.get("birth")):
        try:
            y = to_int(str(cand or "").split(",")[0].strip())
        except Exception:
            y = None
        if y is not None and -4000 <= y <= 2000:
            break
        y = None
    if y is None:
        y = cutoff_year
    return era_of(y) if y is not None else ""


def is_tianzi(info, era: str = "") -> bool:
    """是不是**该王朝的天子**（夏/商/周）—— 天子一律「王」（第 2 条）。

    判据：世系（`lineage_name`）或势力（`state_name`）就是王朝名本身。
    诸侯（齐/鲁/燕…）不受影响，照走自己的爵位。

    ⚠️ 两道闸（都是实测踩出来的）：
      · **只认「真王朝时代」**（夏/商/西周/春秋）。战国以后周天子已名存实亡，
        而秦君族这类「挂在周宗庙下的君族」世系里带「周」字 —— 不设这道闸，
        嬴政会被判成周天子、拿不到「帝」色（实测中招）。
      · 纣王卒于前 1046，正好压在商/周分界上（按卒年算成西周）—— 他世系是
        「商」，靠这条判据兜住，才不会从「王」掉回「帝」。
    """
    r = info or {}
    ln = str(r.get("lineage_name") or "")
    sn = str(r.get("state_name") or "")
    if ln not in _DYNASTY and sn not in _DYNASTY:
        return False
    if era and era not in _TIANZI_ERAS:
        return False
    return True


_installed_name = None


def install_from_save(save_name) -> None:
    """按谱名装国爵表（按名缓存 —— 切谱牒时才重读一次 `source`）。

    谱牒文件有几 MB，`load_source` 要整读一次，所以**不能**在渲染循环里调。
    """
    global _installed_name
    name = str(save_name or "")
    if name == _installed_name:
        return
    _installed_name = name
    if not name:
        install_guo_jue(None)
        return
    try:
        from . import storage
        install_guo_jue(storage.load_source(name))
    except Exception:
        install_guo_jue(None)


_HIST: Dict[str, list] = {}
_HIST_BRANCH: Dict[str, dict] = {}      # {国: {氏: 支名}}（`_支名` 段）
_HIST_LOADED = False
_HIST_FP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "tools", "jue_history.json")


def _ensure_history() -> None:
    """读一次人工史料爵位层（`tools/jue_history.json`）。"""
    global _HIST, _HIST_LOADED
    if _HIST_LOADED:
        return
    _HIST_LOADED = True
    global _HIST_BRANCH
    try:
        with open(_HIST_FP, "r", encoding="utf-8") as f:
            o = json.load(f)
        _HIST = {k: v for k, v in (o or {}).items()
                 if not k.startswith("_") and isinstance(v, list)}
        _HIST_BRANCH = (o or {}).get("_支名") or {}
    except Exception as e:
        _HIST = {}
        _HIST_BRANCH = {}
        # ⚠️ 别让"史料层全废"无声无息（2026-09-26 踩过：漏个逗号，静默失效）
        print(f"⚠️ jue_history.json 读取失败，史料层本次不生效：{e}")


def _year_of(info):
    """这个人该用哪一年去查爵位区间：**卒年 → 受封/继位时间 → 生年**。

    与 `era_of_info` 同序（一致性优先）。用卒年而不是即位年：
    例如齐威王前 356 即位（当时还是侯），前 334 才「徐州相王」——
    按即位年他会一辈子停在侯。
    """
    r = info or {}
    ex = r.get("extra") or {}
    for cand in (r.get("death"), ex.get("Ren_Ji_Wei_Time"), r.get("birth")):
        try:
            y = to_int(str(cand or "").split(",")[0].strip())
        except Exception:
            y = None
        if y is not None and -4000 <= y <= 2000:
            return y
    return None


def _hist_jue_of(info, year) -> str:
    """史料爵位（按年份区间）。取不到返回 ""。"""
    if year is None:
        return ""
    _ensure_history()
    if not _HIST:
        return ""
    r = info or {}
    # 与国爵同规矩：**只认世系（君族）名，不认势力名** —— 势力是「效忠谁」，
    # 齐国公族的势力也是「齐」，拿它查史料的国爵会把「平定」这一支染成王
    # （使用者：「平定的世系成王了？」）。
    for key in ("lineage_name",):
        g = str(r.get(key) or "")
        rows = _HIST.get(g)
        if not rows:
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            lo, hi = row.get("from"), row.get("to")
            if lo is not None and year < lo:
                continue
            if hi is not None and year >= hi:
                continue
            j = str(row.get("jue") or "")
            if j:
                return j
    return ""


def is_qing_clan(info) -> bool:
    """是不是**卿族**（某国的卿大夫家族，而非国君族）——上「卿」色用。

    ★ 2026-09-26 使用者：「**卿族有单独的颜色，能确认一下最好**」——
      当时只有姓氏启发式（世系名以「氏」结尾），卿色从未真正落到实证的人身上。

    ★ 2026-10-02（C 批）使用者：「卿室家族可以配色，之前不是配的灰色吗？」
      ⇒ 判据改成**存档实证优先**，顺序如下：
        ① 尊号/注释里带「卿」—— 游戏**自己标了**的（荀息=「姬姓荀氏卿」），最硬；
        ② 编号在 `install_qing_codes()` 注入的**卿室家族成员**集合里 —— 实证；
        ③ 上面两条都**没有证据**时（无实录槽、纯手写人物、导出的合并谱：
           集合为空）才退回老的「世系名以『氏』结尾」启发式 —— 不倒退旧档观感。
      已有爵位（`fief_title`）的人**不覆盖**（国君/受封者的爵位优先）；
      **本人带爵称或继位记录**（如刘盈 = 汉惠帝，却在刘氏「卿室」名下）也不覆盖 ——
      卿是「非君主」的身份，实测踩过这个坑（见下）。
    """
    r = info or {}
    if r.get("fief_title"):
        return False                     # 已有爵位（国君/受封者）不覆盖
    # ★ 2026-10-02（C 批 · 实证检验当场抓到的错）：**别把国君/有爵称者染成卿色**。
    #   实测：`刘盈`（**汉惠帝**）在《秦末起义》档里挂在「刘氏**卿室**」（刘邦一族
    #   被登记在楚之下）—— 只按家族判就会把这位皇帝染成「卿」。所以先看**本人**：
    #   尊号/注释里带 帝/王/公/侯/伯/子/男，或本人有**继位记录**（`Ren_Ji_Wei_Time`）
    #   ⇒ 他不是卿，按自己的爵称上色（卿是「非君主」的身份，与既有纪律
    #   「非君主的爵位一律留空」同源）。
    if zunhao_tier(r.get("note"), r.get("zunhao")):
        return False
    _ex = r.get("extra") if isinstance(r.get("extra"), dict) else {}
    if (_ex or {}).get("Ren_Ji_Wei_Time") or r.get("Ren_Ji_Wei_Time"):
        return False
    if "卿" in str(r.get("note") or ""):
        return True
    code = str(r.get("code") or "").strip()
    if _QING_CODES:
        return bool(code) and code in _QING_CODES
    # 无实证（没有实录槽 / 未注入）→ 退回启发式：世系名以「氏」结尾 = 卿大夫家族
    return str(r.get("lineage_name") or "").endswith("氏")


def _guo_jue_of(info, era: str = "") -> str:
    """这个人所属国的**国爵**（齐=侯、宋=公、楚=子）；取不到返回 ""。

    表由 `tools/guo_jue.py` 从各档 `Save_KingData_*.json` 抽出、写进谱牒
    `source.guo_jue`，界面启动时用 `install_guo_jue(src)` 注入本模块。
    查表顺序：**该人的朝代（细）→ 粗朝代 → 该国的众数**。
    """
    r = info or {}
    # ★ 2026-09-26 修：**国爵只给该国的君主**（`fief_gen > 0`）。
    #   原先不设这道闸，于是「齐国」这个国爵被套给了**齐国公族里的非君主**
    #   （实测「平定」世系那 9 人 —— 姜齐末年的公族，被染成**王**色），
    #   而他们根本没当过国君。这与导入器既有的纪律
    #   「非君主的爵位一律留空」也是一致的。
    if not (r.get("fief_gen") or 0) > 0:
        return ""
    # ★ 而且**只认世系（君族）名，不认势力名**：势力是「他效忠谁」（齐国公族
    #   的势力也是「齐」），拿它套国爵会把「平定」这一支的公族染成王色
    #   （实测「平定」世系 9 人全是王 —— 使用者：「平定的世系成王了？」）。
    for key in ("lineage_name",):
        g = str(r.get(key) or "")
        if not g:
            continue
        per = _GUO_JUE.get(g)
        if isinstance(per, dict):
            for e in (era, coarse_era(era)):
                if e and per.get(e):
                    return per[e]
        if _GUO_JUE_FLAT.get(g):
            return _GUO_JUE_FLAT[g]
    return ""


# 朝代号（用于判断「尊号点名的朝代」与「本人所处朝代」是否一致）。
# 取粗朝代名，顺序 = 由早到晚 **不重要**（只取第一个命中的）。
_DYNASTY_WORDS = ("上古", "夏", "商", "周", "秦", "汉", "三国", "晋",
                  "南北朝", "隋", "唐", "五代", "宋")


def _zunhao_live(info, era: str) -> str:
    """本档**可用**的尊号爵称 —— 尊号里点名的朝代与本人所处朝代不符时作废。

    ★ 2026-10-11 使用者（附截图）：「**汉惠帝刘盈其实是历史上的大汉皇帝，
      但在这个时代他就是普通人**，却给他标帝色了，好像这样的问题反复出现」。

      根因：`note`（尊号）在本档里可能装着**后世 / 预置的历史头衔** ——
      《大周列国志》的 Memorial 尊号字段会给尚未即位的名人也预置「汉惠帝」
      这类谥号；而 `tier_for` 一直在拿它当爵位兜底 ⇒ 把**本档尚未发生的
      头衔**当成了现职（实测《秦末起义》刘盈：生 -210 属秦，尊号「汉惠帝」
      → 被染成**帝**色，红框）。

      判据：尊号里若点了**朝代名**，它必须与本人所处的朝代**一致** ——
      不一致（人在秦、尊号却是「汉惠帝」）说明那是后世追谥，本档不上色。
      ⚠️ **本档有君主实据的人不受此限**（君序 `fief_gen` / 继位记录
      `Ren_Ji_Wei_Time` / 天子世系）：他确实在本档当过君 —— 如《全史存档》
      刘秀（汉·「汉光武帝」，朝代相符）、姬昌（「周文王」在本档就是王）。
      ⚠️ 只挡「帝 / 王」两级：公侯伯子男是常见诸侯号（「淮南王」「楚王」
      这类带国名的更不该误伤），且本档实爵优先，动不到它们。
    """
    r = info or {}
    zh = zunhao_tier(r.get("note"), r.get("zunhao"))
    if zh not in ("帝", "王"):
        return zh
    ex = r.get("extra") if isinstance(r.get("extra"), dict) else {}
    if (ex or {}).get("Ren_Ji_Wei_Time") or r.get("Ren_Ji_Wei_Time") \
            or (r.get("fief_gen") or 0) > 0 or is_tianzi(r, era):
        return zh                      # 本档有君主实据 ⇒ 尊号属实，照用
    text = str(r.get("note") or "") + str(r.get("zunhao") or "")
    tok = next((d for d in _DYNASTY_WORDS if d in text), None)
    if tok and tok != coarse_era(era):
        return ""                      # 朝代号对不上 ⇒ 后世追谥，本档不用
    return zh


def tier_for(info, era: str = "") -> str:
    """**上色用的爵称**（第 1~3 条口径的唯一出口）。

    · 上古        → 尊号里的帝号（三皇五帝）；没有则原文爵位
    · 夏 / 商     → 天子「王」；其余**按尊号**（尊号即爵位）
    · 周（含春秋战国）→ 天子「王」；诸侯**按实际爵位**，缺失时回退尊号
    · 秦及以后    → 原文爵位（「帝」保留 —— 始皇帝起帝是帝号）
    """
    r = info or {}
    t = str(r.get("fief_title") or "")
    e = era or era_of_info(r)
    c = coarse_era(e)
    # ★ 尊号先过「朝代是否对得上」这道闸（见 `_zunhao_live`）—— 本档尚未
    #   发生的头衔（如刘盈的「汉惠帝」）不能当爵位上色。
    zh = _zunhao_live(r, e)
    # ⓿ 卿族（某国的卿大夫家族）→ 专门的「卿」色。放在最前：卿族本来就不该
    #    拿国君的爵位色（实测「子姓皇氏」的人会被国爵表带成「王」，是错的）。
    if is_qing_clan(r):
        return "卿"
    # ① 天子一律「王」—— 先判，不受朝代边界影响（纣王那条见 is_tianzi 注释）
    if is_tianzi(r, e):
        return "王"
    # ② 上古：尊号（三皇五帝）就是爵位
    if c == "上古":
        return zh or t
    # ③ 夏 / 商 / 周：尊号里的「帝」只是**死后神号** ⇒ 一律降为「王」
    #    （使用者第 3 条：「夏商周统一为王，除非在上古否则帝是死后神号」）
    # ★ 周及以后的爵位：**史料层（按年份区间）→ 游戏国爵（按朝代）→ 人物爵位
    #   → 尊号**。史料层是人工知识（`tools/jue_history.json`），专门对付
    #   「周朝爵位是活的」：杞公贬为杞子、卫伯升侯再升公、楚子自称王、
    #   徐王降徐子、小邾春秋初才封子、秦 附庸→伯→王→帝。
    hist = _hist_jue_of(r, _year_of(r)) if c not in ("上古", "夏", "商") else ""
    # ★ 2026-09-26 二次收紧（使用者报「南越王从宗庙祖先就开始算王，赵佗才是
    #   第一代王」）：**王/帝是君主专属**。游戏把王族成员的原文爵位直接写「王」
    #   （南越整条父链皆然），国爵表又把「世系国君爵」发给族里每个人 —— 两层
    #   叠加，祖先全成王。现引入「君主证据」：继位记录（Ren_Ji_Wei_Time，实测
    #   赵佗有 −141、祖先们没有）/ 尊号谥号带王帝 / 天子世系；三者全无的族人，
    #   任何来源落到「王/帝」都拦下（视为「王族」而非称王）。公侯伯子男不设这道
    #   闸 —— 毕氏→侯 是决选 1A 的拍板口径，不受影响。
    _ex = r.get("extra") if isinstance(r.get("extra"), dict) else {}
    _ji = (_ex or {}).get("Ren_Ji_Wei_Time", r.get("Ren_Ji_Wei_Time"))
    zh_raw = str(r.get("note") or "") + str(r.get("zunhao") or "")
    king_ev = bool(is_tianzi(r, e) or "王" in zh_raw or "帝" in zh_raw
                   or _ji not in (None, ""))

    def _sovereign(v):
        """族人拿到的王/帝不算数（君主专属），拦下后让链路落到下一来源。"""
        if v in ("王", "帝") and not king_ev:
            return ""
        return v or ""

    if c in _DYNASTY:
        if t in ("帝", "王") and king_ev:
            # 原文帝/王先保住 —— 仅限有君主证据的人（含世系被宗庙共祭污染、
            # 只能靠尊号认的姬发「周武王」）
            v = t
        elif hist:
            # ★ 史料层（按**年份区间**的爵位）优先于原文爵位 ——
            #   齐君原文写「公」（死后尊称「齐桓公」），史料/金文是**侯**；
            #   杞 公→子、卫 伯→侯→公、楚 子→王 全靠这一层。
            v = _sovereign(hist) or _sovereign(t) or zh
        elif c == "周":
            v = (_sovereign(_guo_jue_of(r, e)) or _sovereign(t) or zh)
        else:
            # 夏 / 商：**尊号就是爵位**（使用者第 2 条）
            v = zh or _sovereign(t)
        return "王" if v == "帝" else v
    # ④ 秦及以后：**按实际爵位** —— 史料层（秦 伯→王→帝）→ 国爵 → 人物爵位 → 尊号
    return _sovereign(hist) or _sovereign(_guo_jue_of(r, e)) or _sovereign(t) or zh


def tier_colors_for(people: Dict[str, dict], cutoff_year=None) -> Dict[str, str]:
    """{人名: 上色爵称} —— 给批量渲染用（一次算好，别在循环里反复算朝代）。"""
    out = {}
    for n, r in (people or {}).items():
        out[n] = tier_for(r, era_of_info(r, cutoff_year))
    return out
