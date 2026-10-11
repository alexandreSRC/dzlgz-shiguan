"""树形布局引擎。

从 v1 的 draw_tree 前半段抽出，逻辑逐行保留：
可见性计算 → 截断 → children/roots → 深度 → 子树宽度 → 摆放 → 碰撞避让 → 滚动区域。

输出纯数据（positions/roots/children/...），与画布完全解耦，
表格视图、导出图片、快照比对都可以复用。
"""
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .theme import TIER_PRIORITY

logger = logging.getLogger(__name__)

# 与 v1 一致的基准尺寸
BASE_NODE_W = 120
BASE_NODE_H = 60
# ★ 2026-09-26 使用者实测「世系框标题压住『史』徽标/上一代节点底」——
#   25px 的层间隙要同时装下「框边距 18 + 标题条 16 + 史徽标 14」，物理放不下。
#   加到 34（层高 94，画布高 +11%）：标题条与上一代节点只余 4px 轻贴，
#   与徽标带完全错开；配合标题条居左（见 tree_view），遮挡基本清零。
BASE_H_GAP = 34
BASE_V_GAP = 55
BASE_X_CURRENT = 100
BASE_Y_START = 110
BASE_ROOT_GAP = 70
NAME_BOX_W = 20          # 节点框宽（缩放前）
NOTE_FONT_RATIO = 0.7

ROOT_SURNAME_ORDER = {"风": 1, "子": 2, "妘": 3, "姮": 4, "姑": 5, "嫫": 6}


@dataclass
class Layout:
    positions: Dict[str, Tuple[float, float]] = field(default_factory=dict)
    roots: List[str] = field(default_factory=list)
    children: Dict[str, List[str]] = field(default_factory=dict)
    associate_groups: Dict[str, List[str]] = field(default_factory=dict)
    depth: Dict[str, int] = field(default_factory=dict)
    visible: Set[str] = field(default_factory=set)
    person_id_map: Dict[str, str] = field(default_factory=dict)

    # 画布尺寸与绘制参数
    scale: float = 1.0
    node_w: float = 0.0
    node_h: float = 0.0
    h_gap: float = 0.0
    v_gap: float = 0.0
    level_height: float = 0.0
    name_width: float = 0.0
    min_depth: int = 1
    max_depth: int = 1
    top_margin: float = 0.0
    scroll_x: float = 0.0
    scroll_y_start: float = 0.0
    scroll_y_end: float = 0.0
    shift_count: int = 0
    # ★ 2026-10-06 孤儿挂靠（与时间轴同规）：{孤儿: 锚}。连线绘制必须按它
    #   跳过这些对 —— 挂靠只定位，不是血缘。
    attach_side: Dict[str, str] = field(default_factory=dict)
    attach_count: int = 0
    # ★ 2026-10-06 入赘孩子（姓随母、布局挂母边）集合 —— 连线绘制用它决定
    #   画母线（mlink）而不是父线；数据层 father 字段不动。
    uz_kids: Set[str] = field(default_factory=set)


def line_clan(children, root, memo=None):
    """根这一支**实际用的姓/氏** ＝ 根 + 全部后裔的**姓名首字**里最常见的那个。

    ★ 2026-10-11 使用者：「**同姓同氏的排一起 —— 徐氏隔得远**」。
      徐国是**嬴姓徐氏**：根 `嬴章禹` 自己的名字用了「**姓**」（嬴），可它整条链
      都叫「**徐**」（子＝徐融→徐简→徐侨→徐满…）—— 只看根自身首字会把它归到
      「嬴」，与真正的徐氏根（`徐迈2` / `徐毅2`）分家，于是画布上一东一西。
      故按**整支的主姓**归组（`children` = 父→子列表；后裔部分每支互不相交，
      memo 兜住重复调用，整体 O(人)）。谱内没有别的「氏」字段可用时才走这里。
    """
    if memo is None:
        memo = {}
    v = memo.get(root)
    if v is not None:
        return v
    cnt = {}
    stack, seen = [root], set()
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        c = str(n)[:1]
        cnt[c] = cnt.get(c, 0) + 1
        stack.extend(children.get(n, ()))
    v = max(cnt.items(), key=lambda kv: (kv[1], kv[0]))[0] if cnt else str(root)[:1]
    memo[root] = v
    return v


def _ancestor_chains(people, names):
    """names 里每个人的**祖先链**（沿「事实父 → 事实母 → 推定父」向上走到根）。

    ★ 2026-10-04 使用者拍板（时间家谱孤立非史实节点）：「父链向上连通」——
      选定/钉住者的祖先一并豁免滤镜，否则「仅显所选」只留选定者+男性后裔，
      祖先被挡，选定的人在画布上悬空成孤点。链在『已收集过的人』处提前停
      （多条链向上会汇合，不重复收集）；无上位者记录的散人无链可连。
    """
    out = set()
    for start in names:
        cur = start
        seen = set()
        while cur in people and cur not in seen:
            seen.add(cur)
            nxt = _parent(people[cur], people)
            if not nxt or nxt in out:
                break
            out.add(nxt)
            cur = nxt
    return out


def _parent(info, people):
    """结构上的「上位者」：事实父 → 事实母 → **推定父**（`father_guess`），
    取第一个**在谱里**的；都没有返回空串。

    ★ 2026-09-25 使用者：「虚接的你还留着原来的坐标不动呢？你至少参与排序逻辑啊」
      —— 上一版把推定边做成"纯渲染"，被接的那支**还站在自己原来的位置**，
      475 条长虚线横跨画布，比接之前更乱。现在**推定边参与布局**
      （定位 / 排序 / 子树宽度 / 世系框 / 只显所选 / 截断…），
      被接的那支会**排到推定父底下**，整张图才有秩序。

    ⚠️ 口径：**事实永远优先**。只有这个人既没有事实父、也没有事实母时，
      才退到推定父；所以正常父子一律不受影响。
    ⚠️ 数据层仍分两套字段（`father` 事实 / `father_guess` 推定），导出时分得开。
    """
    for k in ("father", "mother", "father_guess"):
        p = (info or {}).get(k) or ""
        if p and p in people:
            return p
    return ""


def _uzheng_family(people):
    """识别「**入赘家庭**」（★ 2026-10-06 奇观场景：女君主 + 入赘）。

    使用者立了允许女性当君主、允许入赘的奇观：一代女君主（如韩淑）娶了
    十三个史实丈夫，孩子**姓随母**。若布局按父边走，孩子会被拆散到十几个
    父系树里（实测：11 个韩姓孩子散在 9 棵树上，画面大乱）。

    判据全用**硬数据**（不猜）：
      · **母系家主** = 女性 + 无父无母（自立门户）+ 有孩子「姓随她、且 ≠
        孩子的父姓」—— 姓取名字首字（本项目人名 = 姓 + 名，成立）；
      · **入赘孩子** = 家主的这些孩子 ⇒ 布局**挂母边**；
      · **入赘男**   = 男性 + 配偶里有母系家主 ⇒ 布局**挂妻**、离开自己的
        父系（入赘 = 出宗，视觉上他是妻家的一员；血缘数据不动）。

    返回 `(挂母的孩子集合, 家主集合, {入赘男: 家主妻})`。
    """
    kids_by_mother = {}
    for n, r in people.items():
        m = str(r.get("mother") or "")
        if m:
            kids_by_mother.setdefault(m, []).append(n)
    matri = set()
    for m, ks in kids_by_mother.items():
        info = people.get(m) or {}
        if str(info.get("gender") or "") != "女":
            continue
        if _parent(info, people):
            continue                      # 有上位者 ⇒ 不是自立门户的家主
        fam = str(m)[:1]
        for k in ks:
            kinfo = people.get(k) or {}
            f = str(kinfo.get("father") or "")
            if str(k)[:1] == fam and (not f or str(f)[:1] != fam):
                matri.add(m)
                break
    if not matri:
        return set(), set(), {}
    uz_kids = set()
    for m in matri:
        fam = str(m)[:1]
        for k in kids_by_mother.get(m, ()):
            kinfo = people.get(k) or {}
            f = str(kinfo.get("father") or "")
            if str(k)[:1] == fam and (not f or str(f)[:1] != fam):
                uz_kids.add(k)
    chost = {}
    # 入赘男判据：**从家主的 spouses 反推**（韩淑的 spouses 列了 13 夫，而男方
    # 的 spouses 未必回指她 —— 实测 13 人只有 3 人的 spouses 里写了韩淑）。
    for m in matri:
        for h in (people.get(m) or {}).get("spouses") or []:
            if h and h in people and h != m \
                    and str((people.get(h) or {}).get("gender") or "") == "男":
                chost[h] = m
    return uz_kids, matri, chost


def _dad_or_guess(info):
    """**父系**上位者（事实父 → 推定父，**不含母**）—— 给"只跟 father 边"那几处用。"""
    return (info or {}).get("father") or (info or {}).get("father_guess") or ""


def _anchored_to_historical(info, people):
    """这个人是否**挂在史实人物名下**（父 / 母 / 推定父 任一是史实）。

    ★ 2026-09-30 使用者报：「**箕否其实有三个儿子，为什么这里只有 1 个**」
      → 又补：「那多出来的两个孩子是**游戏里机制认的义子**，
      但**家族树应该也画出来**啊」。

      真因：这些义子的 `historical="否"`，被「隐藏非史」整片排除
      ⇒ 家谱上只剩亲儿子箕准。

      ⚠️ **诚实说明（我查过，但没查到"义子"标记）**：
        · 搜遍游戏存档全部 59 个分片（`Save_All_100` 31 + `Save_All_1` 28），
          **`箕求`/`箕权`/`箕破` 一个都不在**；族谱表 `Genealogy_Ren_Record_Array`
          里 `Father_Code=11329` 也只有 1 条（亲儿子 `11330 准`）。
        · 族谱字段全集（见 `labels.py` 族谱段）里**没有**任何"义子/养子"字段。
        · 这三个人**只存在于 `family.json`（项目谱牒层）**，`bio` 是项目体例
          ⇒ 是**谱牒侧**的节点，不是游戏原始数据。
        · 所以本函数**不是**在识别游戏标记的义子，而是按
          **"挂在史实人物名下"** 这个**推断判据**放行。

      为什么这个判据可用：实测《全史存档》13564 人里 `historical="否"`
      仅 **38 人（0.3%）**，且**全部挂在史实人物名下**
      ⇒ 他们有**明确的谱系位置**，与"来处不明的随机人物"不是一类东西。
      判据与 `hide_dead` 的「唯一桥梁」同构：**挂得上人，才留。**

      ⚠️ 待办：向使用者确认这批节点是**怎么进 `family.json`** 的
      （手工加的？某个 merge / 补全工具的产物？）—— 若谱牒侧将来能给出
      **明确的"义子"字段**，应改用那个字段，替换掉这里的推断。
    """
    for k in ("father", "mother", "father_guess"):
        p = (info or {}).get(k) or ""
        if p and p in people and \
                (people[p] or {}).get("historical", "否") == "是":
            return True
    return False


def compute_layout(people, scale, hidden_non_historical=None,
                   cutoff_person=None, skip_collision=False,
                   base_font_size_name=15, hide_dead=False, focus_list=None,
                   enrolled_list=None, pinned_list=None, hide_nohist_all=False,
                   families=None, fam_ranks=None):
    """计算树形布局。people 为人物字典，其余参数与 v1 语义一致。

    `focus_list`（2026-09-23 新增）：「仅显所选」名单 —— 只保留名单上的人
    及其**全部男性后裔**（纯父系，沿 father 边向下），外加名单人的直接配偶
    （保住夫妻连线）。多人并集。

    `enrolled_list`（★ 2026-09-23 新增）：画布默认只画**点名过的人** ——
    点过「入谱」的人 + 「加入族谱」（续谱名单）点名的人。None = 不筛（全画）。
    使用者原话：「只有点了入谱或续谱的人物才会绘制家族谱，就像现在的
    『仅显所选』一样」；抽取规则不变（仍全量抽进谱牒），只是画布默认筛掉
    没点名过的，想全看就勾掉侧栏「仅显入谱」。

    `pinned_list`（★ 2026-09-23 新增）：**手动「选定」的人**，穿透所有过滤层
    （隐藏非史 / 隐藏逝者 / 仅显入谱）。使用者反馈「点选定好多次都点不上」，
    根因就是选定者被这些默认收窄挡住了 —— 选定是明确的「我要看他」意图，
    必须可见。

    `hide_nohist_all`（★ 2026-09-24 新增）：侧栏「隐藏非史」**全局开关** ——
    为真时**全部非史实人物**一律不画（不再依赖 `hidden_non_historical` 那份
    「按始祖」的名单）。使用者报「勾了隐藏非史画布不变化、非史角色还存在」：
    原来那个勾选框只在恰好选中节点时才动手，没选中就等于没勾。
    """
    hidden_non_historical = hidden_non_historical or {}
    lay = Layout(scale=scale)

    visible_people: Set[str] = set()
    excluded_people: Set[str] = set()

    all_roots = []
    for name in people:
        # ★ 推定父也算"有上位者" —— 否则被接的那支仍被当成根（见 `_parent` 说明）
        if not _parent(people[name], people):
            all_roots.append(name)

    for name in people:
        # ★ 全局「隐藏非史」摆在最前 —— 必须早于「根节点直接可见」那条捷径，
        #   否则非史实的根节点照样会进来。
        # ★ 2026-09-30 例外（使用者：「多出来的两个孩子是游戏里机制认的义子，
        #   但家族树应该也画出来啊」）：**挂在史实人物名下的非史实者不排除** ——
        #   义子/养子属于这种（游戏随机生成 ⇒ `historical=否`，但父系明确）。
        #   实测全谱这类只有 38 人（0.3%），不会把随机人物成片放进来。
        if hide_nohist_all and people[name].get("historical", "否") != "是":
            if not _anchored_to_historical(people[name], people):
                excluded_people.add(name)
                continue
        is_root = name in all_roots
        has_associate = bool(people[name].get("associate_of", ""))
        if is_root and not has_associate:
            visible_people.add(name)
            continue

        historical = people[name].get("historical", "否")
        if historical == "否":
            ancestor, _seen = name, set()
            while ancestor not in _seen:
                _seen.add(ancestor)
                _up = _parent(people[ancestor], people)
                if not _up:
                    break
                ancestor = _up
            if hidden_non_historical.get(ancestor, False):
                excluded_people.add(name)
                continue
        visible_people.add(name)

    # 非史实后裔的级联隐藏
    # ★ 2026-09-26 审查修复（M4）：内层原来对每个排除者**全表扫一遍**
    #   （O(排除数 × 全表)，大谱牒勾「隐藏非史」时是几千万次迭代，明显卡顿）。
    #   预建反向索引后 BFS，逐条边语义与原版一致，只是不再重扫。
    kid_edges = defaultdict(list)      # 上位者 → [人]（父/母/推定父三边）
    assoc_ref = defaultdict(list)      # associate_of → [人]
    spouse_edges = defaultdict(list)   # 反向配偶（s → 配偶是 s 的人）
    for _p, _info in people.items():
        for _par in (_info.get("father", ""), _info.get("mother", ""),
                     _info.get("father_guess", "")):
            if _par:
                kid_edges[_par].append(_p)
        _ref = _info.get("associate_of", "")
        if _ref:
            assoc_ref[_ref].append(_p)
        for _s in (_info.get("spouses") or []):
            spouse_edges[_s].append(_p)
    expanded_excluded = set(excluded_people)
    queue = deque(excluded_people)
    while queue:
        cur = queue.popleft()
        for p in kid_edges.get(cur, ()):
            if p not in expanded_excluded:
                expanded_excluded.add(p)
                queue.append(p)
        for p in assoc_ref.get(cur, ()):
            if p not in expanded_excluded and \
                    people[p].get("historical", "否") == "否":
                expanded_excluded.add(p)
                queue.append(p)
        for s in spouse_edges.get(cur, ()):
            if s in people and s not in expanded_excluded and \
                    people[s].get("historical", "否") == "否":
                expanded_excluded.add(s)
                queue.append(s)
    visible_people -= expanded_excluded
    # ★ 2026-09-23 使用者反馈「点选定好多次都点不上」：查出来是**选定的人被
    #   默认过滤层挡住** —— 他在实录层选了「朴敏勇」（不在谱牒，另修），
    #   又选了已故的「公孙圭」而当时勾着「隐藏逝者」（2630 → 802 人，公孙圭
    #   被藏），画布毫无变化，看着就像按钮没反应。
    #   语义上「手动选定」是**明确的『我要看他』意图**，优先级高于一切默认
    #   收窄 —— 所以选定者穿透「隐藏非史」「隐藏逝者」「仅显入谱」三层。
    _pinned = set(pinned_list or ()) | set(focus_list or ())
    # ★ 2026-10-04 使用者拍板（时间家谱孤立非史实节点）：「父链向上连通」——
    #   选定/钉住者的**祖先链**一并豁免滤镜，否则「仅显所选」只留选定者+
    #   男性后裔，祖先被挡，选定的人在画布上悬空成孤点（实测：纪黯的父亲
    #   纪信是史实人物，仍被仅显所选挡掉）。链沿「事实父 → 事实母 → 推定父」
    #   向上走到根；无父记录的散人依旧无链可连（数据没有边）。
    if _pinned:
        _pinned |= _ancestor_chains(people, _pinned)
    visible_people |= (_pinned & set(people))    # 选定者豁免「隐藏非史」

    # 隐藏已故：death 字段非空即已故（与已故涂灰同一判据）
    # ★ 2026-09-23 使用者反馈：一刀切会把链路剪断 —— 爷爷在世、儿子已故、
    #   孙子在世时，儿子一藏，爷孙的父子连线就没了（画面成了祖孙各挂一截）。
    #   改法：已故者若同时「向上能走到在世者」且「向下能走到在世者」，
    #   他就是这条链的**唯一桥梁**，必须留下（只留桥，不留整条已故支）。
    if hide_dead:
        dead_now = {n for n in visible_people
                    if (people.get(n) or {}).get("death")}
        alive_now = visible_people - dead_now
        if dead_now and alive_now:
            child_map: Dict[str, List[str]] = {}
            for n in visible_people:
                info = people.get(n) or {}
                for p in (info.get("father", ""), info.get("mother", ""),
                          info.get("father_guess", "")):
                    if p in visible_people:
                        child_map.setdefault(p, []).append(n)

            def _parents(n):
                info = people.get(n) or {}
                return [p for p in (info.get("father", ""), info.get("mother", ""),
                                    info.get("father_guess", ""))
                        if p in visible_people]

            up_memo: Dict[str, bool] = {}
            down_memo: Dict[str, bool] = {}

            def _up_alive(n):
                """n 的祖先里有没有在世者（只在可见集合内走，带记忆防环）。"""
                if n in up_memo:
                    return up_memo[n]
                up_memo[n] = False                # 先占位，防数据成环时无限递归
                r = any(p in alive_now or _up_alive(p) for p in _parents(n))
                up_memo[n] = r
                return r

            def _down_alive(n):
                """n 的后代里有没有在世者。"""
                if n in down_memo:
                    return down_memo[n]
                down_memo[n] = False
                r = any(c in alive_now or _down_alive(c)
                        for c in child_map.get(n, ()))
                down_memo[n] = r
                return r

            bridge = {n for n in dead_now if _up_alive(n) and _down_alive(n)}
            visible_people -= (dead_now - bridge)
        visible_people |= (_pinned & set(people))    # 选定者豁免「隐藏逝者」

    # ★ 2026-09-23 画布默认只画「点名过的人」（入谱 / 加入族谱）
    #   放在「仅显所选」之前：先按点名收窄，再按选定收窄，两级叠加。
    if enrolled_list is not None:
        visible_people &= (set(enrolled_list) | _pinned)

    # 仅显所选：保留名单人及其全部后裔 + 直接配偶（多人并集）
    if focus_list:
        # ★ 2026-09-23 使用者纠正：「选定（仅显所选）不是应该从被选定的人开始
        #   包含其**所有男性后裔**都被选定吗？毕竟我要看的是他的谱系啊」——
        #   所以展开只跟 **father 边**（纯父系谱系，不含女儿支），与修谱/续谱的
        #   父系口径一致。原来父/母两边都走，等于把女儿支也收了进来。
        child_map = {n: [] for n in people}
        for n in people:
            d = _dad_or_guess(people[n])          # 父系口径：不含母，但含推定父
            if d in child_map:
                child_map[d].append(n)
        keep = set()
        q = list(focus_list)
        while q:
            cur = q.pop(0)
            if cur in keep or cur not in people:
                continue
            keep.add(cur)
            for c in child_map.get(cur, []):
                if c not in keep:
                    q.append(c)
        for n in list(keep):            # 保住名单人的配偶（夫妻连线不断）
            for s in (people[n].get("spouses") or []):
                if s in people:
                    keep.add(s)
        # ★ 2026-10-04：选定/钉住者与其**祖先链**不被「仅显所选」裁掉
        #   （祖先链见 `_ancestor_chains`——只显所选原会把它上面的父辈剪掉，
        #     选定的人就成了悬空孤点）。
        visible_people &= (keep | _pinned)

    # 截断显示：只保留指定人物及其后裔
    if cutoff_person and cutoff_person in people and cutoff_person in visible_people:
        all_children = {name: [] for name in people}
        for name in people:
            info = people[name]
            for parent in [info.get("father", ""), info.get("mother", ""),
                           info.get("father_guess", "")]:
                if parent in all_children:
                    all_children[parent].append(name)
        root_of_cutoff = cutoff_person
        _hop_guard = 0                       # ★ 2026-09-26（L1）：环保护 ——
        while True:                          #   model.root_ancestor 有 guard，
            _hop_guard += 1                  #   这里原来没有；脏数据成环时死循环
            if _hop_guard > len(people):
                break
            dad = people[root_of_cutoff].get("father", "")
            mom = people[root_of_cutoff].get("mother", "")
            if dad and dad in people:
                root_of_cutoff = dad
            elif mom and mom in people:
                root_of_cutoff = mom
            else:
                break
        descendants = set()
        queue_desc = [cutoff_person]
        while queue_desc:
            cur = queue_desc.pop(0)
            if cur in descendants or cur not in visible_people:
                continue
            descendants.add(cur)
            for child in all_children.get(cur, []):
                if child not in descendants:
                    queue_desc.append(child)
        same_tree = set()
        queue_tree = [root_of_cutoff]
        while queue_tree:
            cur = queue_tree.pop(0)
            if cur in same_tree:
                continue
            same_tree.add(cur)
            for child in all_children.get(cur, []):
                if child not in same_tree:
                    queue_tree.append(child)
        visible_people -= (same_tree - descendants)
        for name in list(visible_people):
            ref = people[name].get("associate_of", "")
            if ref and ref in people and ref not in visible_people:
                visible_people.discard(name)

    lay.visible = visible_people

    # children / roots
    #
    # 重要：这里必须按 people 的字典顺序（= 存档文件里的顺序）迭代，
    # 不能用 visible_people —— 它是 set，迭代顺序随 PYTHONHASHSEED 变化。
    # v1 用了 set，导致同 root_sort / 同 rank 的节点相对顺序每次启动都可能不同，
    # 表现为"同一个存档每次打开，族谱排布都不一样"。这里改为确定顺序。
    children: Dict[str, List[str]] = {}
    roots: List[str] = []
    # ★ 2026-10-06 入赘家庭（女君主 + 入赘）：先识别，建树时把孩子挂母。
    #   数据不动，只改布局解释。
    # ★★ 2026-10-07 使用者裁定（第 2 条）：「**入赘男不要挂妻定位，按照自家
    #   家族排序，连配偶线即可**」—— 原来入赘男 `continue` 掉（不入 children
    #   也不进 roots），再走 `_consort_assoc` 挂到妻旁；现在取消这条，让他
    #   按**自己的父系/家族**正常落座（配偶线由 spouses 数据照常画）。
    _uz_kids, _matri, _chost = _uzheng_family(people)
    for name in people:
        if name in visible_people:
            children[name] = []
    for name in people:
        if name not in visible_people:
            continue
        info = people[name]
        associate_of = info.get("associate_of", "")
        if name in _uz_kids:
            # ★ 入赘孩子：姓随母 ⇒ 挂母边（不走父边）
            m = str(info.get("mother") or "")
            if m and m in visible_people:
                children[m].append(name)
                continue
        # ★ 上位者 = 事实父 → 事实母 → **推定父**（推定边参与布局，见 `_parent`）
        par = _parent(info, people)
        if par and par in visible_people:
            children[par].append(name)
        elif not associate_of or associate_of not in visible_people:
            roots.append(name)

    def _sib_key(name):
        """兄弟姐妹按生年排：年长者（生年数值小，公元前越早越老）在前，无生年排最后。"""
        b = (people.get(name) or {}).get("birth")
        if not b:
            return (True, 0)
        try:
            return (False, int(str(b).split(",")[0]))
        except (ValueError, TypeError):
            return (True, 0)

    for dad in children:
        children[dad].sort(key=_sib_key)

    # ★ 2026-09-23 使用者要求：「根节点排序，让被 X 世系框起来的排在前面，
    #   按 X 的首字母顺序排」。世系口径与世系框**完全一致**（认 lineage_name
    #   君族，老档回退 state_name），否则会出现「框住了却不参与排序」的错位。
    _use_lin = any((v or {}).get("lineage_name") for v in people.values())

    def _root_lineage(name):
        info = people.get(name) or {}
        return info.get("lineage_name" if _use_lin else "state_name", "") or ""

    def _pinyin_key(s):
        """拼音序排序键 —— 用 **GBK 字节序**，不依赖 pypinyin / locale。

        GBK（cp936）的汉字区位码本身就是按拼音排列的（实测：风 0xB7E7 <
        秦 0xC7D8 < 卫 0xCEC0，正是 f < q < w），所以字节序 = 拼音序。
        逐字编码，个别 GBK 收不进的生僻字给最大值排到最后。
        """
        out = []
        for ch in str(s):
            try:
                out.append(ch.encode("gbk"))
            except UnicodeEncodeError:
                out.append(b"\xff\xff")
        return b"".join(out)

    _root_order = {n: i for i, n in enumerate(roots)}   # 同优先级时保持存档顺序

    # ★★ 2026-10-11 使用者：「**同姓同氏的根节点依次按爵位高低、始祖生卒年排序，
    #   然后才是不同姓同氏的按爵位排序**」。同姓同氏 = 同一个**家族框键**
    #   （`families`：成员 → 家族键，判据与世系框同一份）；爵位由视图经
    #   `fam_ranks` 传入（`gongqing.family_ranks`：卿室=卿，公室/宗室=本国现行爵位）。
    #   没传家族信息时整段退化成原行为（零改动、零风险）。
    _fam_map = dict(families) if families else {}
    _fr_ranks = fam_ranks or {}

    def _root_birth(name):
        """始祖生卒年排序键：生年数值；无生年排最后。"""
        b = str((people.get(name) or {}).get("birth") or "").split(",")[0]
        try:
            return int(b)
        except (ValueError, TypeError):
            return 10 ** 9

    _clan_memo = {}      # 「整支主姓」缓存（见 line_clan）；一次绘制只算一遍

    def get_root_sort_key(name):
        """根节点排序键（元组，逐级比较）：
        手动祖序 → 少数民族孤根 → **家族（同姓同氏，按爵位↔生卒年）**
        → 世系（按拼音）→ 姓氏序 → 存档顺序。"""
        # ★ 2026-09-26 使用者要求：「**少数民族孤根放风巢皇节点的右侧去**」。
        #   声明 `root_group == "separate"` 的根（素和古尔本 + 藏族三支）
        #   一律**排到最后** ⇒ 画布上落到最右端（风巢皇那棵大树的右臂之外），
        #   不再夹在树中间碍事。标由 `tools/guess_lineage.py --apply` 写。
        rs = people[name].get("root_sort", 0)
        if rs > 0:
            return (0, rs, b"", 0, 0, "")
        if (people[name].get("root_group") or "") == "separate":
            return (9, 0, b"", 0, 0, "")
        # ★★ 2026-10-11 使用者：「不是说**风巢皇的家族谱是 1 号节点**……吗？」
        #   实测风巢皇排到了**第 10**（前 6 是 翟洛甘/妫叔/妘适/旺秋鲁赞/妘行南/缯贺，
        #   全带 `lineage_name`）。真因：风巢皇的 `lineage_name` 早在「共同远祖」
        #   那批修复里被清成**空**了 ⇒ 走到姓氏序；而姓氏序（`ROOT_SURNAME_ORDER`
        #   里 **风 = 1**，本来就是"风排最前"的设计）被排在了**世系之后** ⇒ 被压下去。
        #   ⇒ **姓氏序提到世系之前**：风巢皇那棵大树仍是第 1 号。
        for surname, order in ROOT_SURNAME_ORDER.items():
            if name.startswith(surname):
                return (1, order, b"", 0, _root_birth(name), name)
        lin = _root_lineage(name)
        if lin:
            return (2, 0, _pinyin_key(lin), 0, _root_birth(name), name)
        _fk = _fam_map.get(name, "")
        if _fk:
            # 组间：爵位降序 → 家族键（保证同族相邻、同爵时次序确定）；
            # 组内：爵位 → 始祖生卒年 → 姓名。
            return (3, -_fr_ranks.get(_fk, 0), str(_fk).encode("utf-8", "replace"),
                    0, _root_birth(name), name)
        # ★ 孤立节点（无姓氏序、无世系、无家族、又**没有子女**）**殿后**。
        if not children.get(name):
            return (8, 0, b"", _root_order.get(name, 0), _root_birth(name), name)
        # ★★ 2026-10-11 使用者：「**同姓同氏的排一起 —— 徐氏隔得远**」。
        #   兜底档原第一键是 `b""`（＝整档只按**存档顺序**）⇒ 既无 `lineage_name`
        #   又不在公卿家族里的**同姓根**被打散到几十位之外（实测《秦末起义》三条
        #   徐氏根：`嬴章禹`=第51位、`徐迈2`=第118位、`徐毅2`=第170位）。
        #   ⇒ 兜底档第一键改成**整支主姓**（`line_clan`：根＋全部后裔最常见的姓名
        #   首字，能认出「嬴姓徐氏」这种**根用姓、后用氏**的支）＋拼音序；
        #   段内仍按存档序。只用谱内自带的名字，不新增字段、不改上层档位。
        return (4, 0, _pinyin_key(line_clan(children, name, _clan_memo)),
                _root_order.get(name, 0), _root_birth(name), name)

    roots.sort(key=get_root_sort_key)

    # ---- ★ 2026-10-06 孤儿挂靠（代际版，与时间轴同规）----------------------
    #   无父无母（也没有 associate 锚）的节点是"根"，独立占列；同家族的家族框
    #   按成员包围盒画 ⇒ 孤儿排得远就把框撑出十几屏
    #   （实测：汉·刘泽距刘肥 15000px，把「秦国刘氏」框撑到 26125px 宽）。
    #   改为**定位挂靠**：同家族里找**世代最接近**的族人当锚，孤儿作为锚的
    #   孩子参与横向排布（y 仍由 generation 决定 ⇒ 纵位不动），
    #   **不画血缘线**（`_draw_people` 按 `lay.attach_side` 跳过这些对）。
    #   三条守则（照抄 `timeline.compute`）：家族里还有**世代更早**的人才挂
    #   （始祖不挂靠）；锚不能是自己的后代（防成环）；锚不能是本轮已挂靠的
    #   孤儿（防长链）。
    attached: set = set()

    def _year_of(t):
        try:
            return int(str(t or "").split(",")[0])
        except (ValueError, TypeError):
            return None

    # ★ 2026-10-06 孤立君主 → 前任君主（继任链，使用者裁定 A）——
    #   独立于 families：无父无母的君主（note 带帝/王/皇）不找同龄族人，
    #   而是挂到**同称号（note 相同）的前任君主**（卒年早于自己且最近）旁。
    #   实测：韩广（秦帝，卒-206）→ 嬴胡亥（秦帝，卒-207）；
    #         韩淑（秦帝，现任无卒年）→ 韩广。
    #   ⚠️ 允许锚是本轮已挂靠的君主（继任链本来就是一串）。
    for r in sorted(roots, key=get_root_sort_key):
        note = str((people.get(r) or {}).get("note") or "")
        if not note or not ("帝" in note or "王" in note or "皇" in note):
            continue
        dy = _year_of((people.get(r) or {}).get("death"))
        cands = []
        for n, v in people.items():
            if n == r or str(v.get("note") or "") != note or n not in visible_people:
                continue
            y2 = _year_of(v.get("death"))
            if y2 is None or (dy is not None and y2 >= dy):
                continue       # 前任 = 卒年更早；无卒年 = 在世，不是前任
            cands.append((y2, n))
        if cands:
            cands.sort(reverse=True)            # 卒年最近的
            host = cands[0][1]
            children.setdefault(host, []).append(r)
            children[host].sort(key=_sib_key)
            attached.add(r)
            lay.attach_side[r] = host
    if attached:
        roots = [n for n in roots if n not in attached]

    if families:
        fam_of = dict(families)
        # 锚**优先选「已经长在树里」的族人**（有父/有子），不选同样是孤儿的
        # 离群者 —— 实测教训：刘泽第一版被挂到「刘琳」名下（她本身也是散在
        # 远处的那一批），x 几乎没动、框照样被撑到 26125px。
        _orphans = set(roots)

        def _gen_of(n):
            g = (people.get(n) or {}).get("generation", 0) or 0
            return g if g > 0 else None

        for r in sorted(roots, key=get_root_sort_key):
            fam = fam_of.get(r)
            if not fam:
                continue
            gr = _gen_of(r)
            mates = [n for n, k in fam_of.items()
                     if k == fam and n != r and n in visible_people
                     and n not in attached]
            if not mates:
                continue
            _gs = [g for g in (_gen_of(m) for m in mates) if g is not None]
            if gr is not None and _gs and gr <= min(_gs):
                continue                     # 家族里世代最早者 = 始祖，不挂靠
            desc, stack = set(), [r]
            while stack:                     # 自己的后代不能当锚（防成环）
                cur = stack.pop()
                for k2 in children.get(cur, ()):
                    if k2 not in desc:
                        desc.add(k2)
                        stack.append(k2)
            cand = [n for n in mates if n not in desc]
            # 锚优先选**真正长在树里**的族人（有父/有母/有子）——「秦国刘氏」
            # 里有一批靠 `associate_of` 挂着太太身份的成员（刘琳那一类），
            # 她们自己就散在画布远处，拿她们当锚等于没挂（实测 x 一动没动）。
            _body = [n for n in cand
                     if (people.get(n) or {}).get("father")
                     or (people.get(n) or {}).get("mother")
                     or children.get(n)]
            if _body:
                cand = _body
            if not cand:
                continue
            if gr is not None:
                host = min(cand, key=lambda n: (abs((_gen_of(n) or gr) - gr), n))
            else:
                host = cand[0]
            children.setdefault(host, []).append(r)
            children[host].sort(key=_sib_key)
            attached.add(r)
            lay.attach_side[r] = host
        if attached:
            roots = [n for n in roots if n not in attached]
    lay.attach_count = len(lay.attach_side)

    lay.children = children
    lay.roots = roots
    lay.uz_kids = _uz_kids

    # 深度
    depth: Dict[str, int] = {}

    def calc_depth(person, d):
        gen = people[person].get("generation", 0)
        depth[person] = gen if gen > 0 else d
        for child in children[person]:
            # ★ 2026-10-06 挂靠者**纵位与锚同代**（挂靠借的是列位，不是血缘）：
            #   否则没有 generation 的孤儿会被算成「锚的下一代」，白掉一层。
            if child in lay.attach_side:
                calc_depth(child, depth[person])
            else:
                calc_depth(child, depth[person] + 1)

    for r in roots:
        calc_depth(r, 1)
    lay.depth = depth

    # 尺寸
    node_w = BASE_NODE_W * scale
    node_h = BASE_NODE_H * scale
    h_gap = BASE_H_GAP * scale
    v_gap = 1 * scale
    level_height = node_h + h_gap
    root_gap = 20 * scale
    actual_name_width = NAME_BOX_W * scale
    note_font_size = int(base_font_size_name * scale * NOTE_FONT_RATIO)

    lay.node_w = node_w
    lay.node_h = node_h
    lay.h_gap = h_gap
    lay.v_gap = v_gap
    lay.level_height = level_height
    lay.name_width = actual_name_width

    def cell_width(person):
        note = people[person].get("note", "")
        if not note:
            return actual_name_width
        note_width = len(note) * note_font_size * 0.6 + 2
        return actual_name_width + note_width

    # 同代人分组（先算，subtree_width 依赖它）
    # 同样按 people 顺序迭代，避免 set 顺序带来的不确定性
    associate_groups: Dict[str, List[str]] = {}
    for name in people:
        if name not in visible_people:
            continue
        # ★ 2026-10-07 使用者裁定（第 2 条）：入赘男不再「跟妻子旁边」——
        #   他按自家家族排序（`_consort_assoc` 已取消，见建树处说明）。
        ref = people[name].get("associate_of", "")
        if ref and ref != name and ref in visible_people:
            associate_groups.setdefault(ref, []).append(name)
    for ref in associate_groups:
        associate_groups[ref].sort(key=lambda n: people[n].get("associate_rank", 999))
    lay.associate_groups = associate_groups

    # ★ 2026-09-26 启动优化：子树宽缓存。实测 13,526 人时 `subtree_width`
    #   被递归调用 **78 万次**（同一棵子树被反复从不同祖先重算，profiler 里
    #   独占 2.2s / 累计 5.0s，是启动最大的一块）。`visited` 只用于**防环**，
    #   节点不在祖先链上时结果与 visited 无关 ⇒ 可以按人缓存。
    _sw_cache: Dict[str, float] = {}

    def subtree_width_cached(person):
        hit = _sw_cache.get(person)
        if hit is None:
            hit = subtree_width(person)
            _sw_cache[person] = hit
        return hit

    def subtree_width(person, visited=None):
        if visited is None:
            visited = set()
        if person in visited:
            return cell_width(person) + v_gap
        visited.add(person)
        person_w = cell_width(person)
        if person in associate_groups:
            assoc_total = cell_width(person)
            for assoc in associate_groups[person]:
                assoc_total += v_gap + subtree_width(assoc, visited.copy())
            person_w = max(person_w, assoc_total)
        kids = children[person]
        if not kids:
            visited.remove(person)
            return person_w + v_gap
        slot_set = set()
        slot_widths = []

        def _expand_slots(node, visited_expand):
            if node in slot_set:
                return
            slot_set.add(node)
            # 常态（node 不在祖先链上）：子树宽与 visited 无关，走缓存；
            # 真遇到环才退回带 visited 的原路径。
            if node in visited_expand:
                slot_widths.append(subtree_width(node, visited_expand.copy()))
            else:
                slot_widths.append(subtree_width_cached(node))
            if node in associate_groups:
                for a in associate_groups[node]:
                    _expand_slots(a, visited_expand)

        for c in kids:
            _expand_slots(c, visited.copy())
        total = sum(slot_widths) + v_gap * (len(slot_widths) - 1)
        visited.remove(person)
        return max(total, person_w + v_gap)

    # 摆放
    positions: Dict[str, Tuple[float, float]] = {}

    def _place_tree_person(person, x_center, y, kids_center=None):
        positions[person] = (x_center, y)
        kids = children[person]
        if not kids:
            return
        slots = []
        slot_set = set()

        def _expand_place(node):
            if node in slot_set:
                return
            slot_set.add(node)
            slots.append(node)
            if node in associate_groups:
                for a in associate_groups[node]:
                    _expand_place(a)

        for c in kids:
            _expand_place(c)
        slot_widths = [subtree_width_cached(s) for s in slots]
        total_w = sum(slot_widths) + v_gap * (len(slot_widths) - 1)
        my_center = kids_center if kids_center is not None else x_center
        start_x = my_center - total_w / 2
        slot_lefts = []
        cur_x = start_x
        for sw in slot_widths:
            slot_lefts.append(cur_x)
            cur_x += sw + v_gap
        slot_y = y + level_height

        handled = set()
        for i, slot in enumerate(slots):
            if slot in handled:
                continue
            if children.get(slot):
                merge_L = i
                while merge_L > 0 and not children.get(slots[merge_L - 1]):
                    merge_L -= 1
                merge_R = i
                while merge_R < len(slots) - 1 and not children.get(slots[merge_R + 1]):
                    merge_R += 1
                merged_center = None
                if merge_L < i or merge_R > i:
                    ml = slot_lefts[merge_L]
                    mr = slot_lefts[merge_R] + slot_widths[merge_R]
                    merged_center = (ml + mr) / 2
                for j in range(merge_L, merge_R + 1):
                    sj_x = slot_lefts[j] + slot_widths[j] / 2
                    _place_tree_person(slots[j], sj_x, slot_y, kids_center=merged_center)
                    handled.add(slots[j])
            else:
                slot_x = slot_lefts[i] + slot_widths[i] / 2
                _place_tree_person(slot, slot_x, slot_y)
                handled.add(slot)

    x_current = BASE_X_CURRENT * scale
    y_start = BASE_Y_START * scale

    for r in roots:
        r_width = subtree_width_cached(r)
        gen = people[r].get("generation", 1)
        r_y = y_start + (gen - 1) * level_height
        r_x = x_current + r_width / 2
        _place_tree_person(r, r_x, r_y)

        placed_assocs = set()

        def _place_root_assocs(person, base_x, y):
            if person in associate_groups:
                cur_x = base_x + cell_width(person) / 2 + v_gap
                for assoc in associate_groups[person]:
                    if assoc in placed_assocs:
                        continue
                    placed_assocs.add(assoc)
                    aw = subtree_width_cached(assoc)
                    ax = cur_x + aw / 2
                    _place_tree_person(assoc, ax, y)
                    cur_x += aw + v_gap
                    _place_root_assocs(assoc, ax, y)

        _place_root_assocs(r, r_x, r_y)
        x_current += r_width + root_gap

    # 碰撞避让：按 x 从左到右扫描，遇到重叠就把该节点整棵子树右移
    if not skip_collision:
        def _collect_subtree_fast(start):
            result = set()
            q = deque([start])
            while q:
                cur = q.popleft()
                if cur in result:
                    continue
                result.add(cur)
                for child in children.get(cur, []):
                    if child not in result:
                        q.append(child)
                if cur in associate_groups:
                    for assoc in associate_groups[cur]:
                        if assoc not in result:
                            q.append(assoc)
            return result

        y_levels: Dict[float, List[str]] = {}
        for name, (x, y) in positions.items():
            y_levels.setdefault(y, []).append(name)

        min_gap = 1 * scale
        total_shifts = 0
        MAX_PASSES = 10
        for y, level_names in y_levels.items():
            for _ in range(MAX_PASSES):
                names = sorted(level_names, key=lambda n: positions[n][0])
                cursor = None
                shifted = False
                for name in names:
                    left_edge = positions[name][0] - actual_name_width / 2
                    if cursor is not None and left_edge < cursor + min_gap:
                        shift = cursor + min_gap - left_edge
                        for p in _collect_subtree_fast(name):
                            px, py = positions[p]
                            positions[p] = (px + shift, py)
                        left_edge += shift
                        total_shifts += 1
                        shifted = True
                    cursor = left_edge + cell_width(name)
                if not shifted:
                    break
            else:
                logger.warning(f"第 {y} 层碰撞避让达到最大轮次({MAX_PASSES})，停止该层避让")
        lay.shift_count = total_shifts
        if total_shifts:
            logger.info(f"碰撞检测完成，共 {total_shifts} 次移位")

    lay.positions = positions

    # 滚动区域
    if positions:
        max_x = max(px for px, py in positions.values())
        x_current = max(x_current, max_x + actual_name_width / 2 + 100 * scale)

    for name in positions:
        if name not in depth:
            depth[name] = people[name].get("generation", 1)

    max_depth = max(depth.values()) if depth else 1
    min_depth = min(depth.get(p, 1) for p in positions) if positions else 1
    top_margin = 30 * scale
    bottom_padding = 60 * scale
    lay.min_depth = min_depth
    lay.max_depth = max_depth
    lay.top_margin = top_margin
    lay.scroll_x = x_current + 200 * scale
    lay.scroll_y_start = y_start + (min_depth - 1) * level_height - top_margin
    lay.scroll_y_end = y_start + (max_depth - 1) * level_height + node_h + bottom_padding

    # 人物编号（按树遍历顺序）
    ordered = []
    visited_ids = set()

    def _traverse_id(person):
        if person in visited_ids or person not in positions:
            return
        visited_ids.add(person)
        ordered.append(person)
        for child in children.get(person, []):
            _traverse_id(child)

    for r in roots:
        _traverse_id(r)
    lay.person_id_map = {name: f"{i:05d}" for i, name in enumerate(ordered, 1)}

    logger.info(f"布局完成: 人物 {len(people)} 人, 可见 {len(positions)} 人, "
                f"根节点 {len(roots)}, 可见代数 {min_depth}-{max_depth}")
    return lay


def _lineage_groups(people, positions, use_lineage):
    """归世系组 → {标题: [人]}（标题可能是「周朝齐」这种带朝代的）。

    ★ 2026-09-23 原口径：「有世系标的人 + 其**父系后裔**」（宗庙只给君主本人
      打世系标，不把后裔并进来框就框不住整个家族）。

    ★ 2026-09-26 使用者第 1 / 第 3 项（选 A）—— **框要从始封君开始**，
      并**排查所有国家**（实测 90 个世系有「混入」，合计 12,103 人）：

      ① 按**父系连通块**（含推定边）把一个世系拆成若干块；
      ② 每块的**起点**：
         · 块内有受封者（`fief_gen > 0`）→ 优先 `fief_gen == 1` 的**建国君主**，
           没有 1 就取**最早受封**的那位；**受封之前的先世不进框**
           （实测「羲和世系」：原框从第 3 代「风雷方」开始，而该族始封君是
           第 11 代「娥娵訾」封代 1 ⇒ 现在从娥娵訾起算）；
         · 块内一个受封者都没有 → 起点 = 该块**世代最小的始祖**。
      ③ 成员 = **起点 + 其父系后裔**（∩ 该块）；
      ④ **整块丢弃**：块内没有任何受封者、而同一世系在**别的块**里有受封者
         —— 那是混进这个世系的先世/别家（实测齊世系里那条虞国线）；
      ⑤ **同名多组 → 标题加朝代号**（第 7 项）：先用粗朝代（周朝/汉朝），
         仍重名再用细朝代（西周/战国…）。
    """
    field = "lineage_name" if use_lineage else "state_name"
    owner = {}
    for n in positions:
        sn = (people.get(n) or {}).get(field, "")
        if sn:
            owner[n] = sn
    kids = {}
    for n in positions:
        d = _dad_or_guess(people.get(n))
        if d:
            kids.setdefault(d, []).append(n)

    # ---- 该世系的人 = 有世系标的人 ∪ 其父系后裔 ----
    base = dict(owner)
    stack = list(owner)
    while stack:
        cur = stack.pop()
        for c in kids.get(cur, ()):
            if c not in base:
                # ⚠️ 用 `base[cur]` 而不是 `owner[cur]`：`cur` 本身可能是
                #    沿后裔链传下来的（它没有世系标），取 owner 会 KeyError。
                base[c] = base[cur]
                stack.append(c)
    per = {}
    for n, sn in base.items():
        per.setdefault(sn, set()).add(n)

    from .jue import era_of_info, era_prefix       # 局部 import，避免环

    def _block_start(blk, kings):
        """块的起点：建国君主 → 最早受封者 → 始祖。"""
        f1 = [x for x in kings if (people[x].get("fief_gen") or 0) == 1]
        pool = f1 or kings
        if pool:
            return min(pool, key=lambda x: ((people[x].get("fief_gen") or 999),
                                           people[x].get("generation") or 0,
                                           str(people[x].get("birth") or "")))
        # ★ 2026-09-26 审查修复（探针抓到）：兜底起点必须取**连通块顶点**
        #   （块内没有父的人）。原来直接按 (generation, birth) 取最小 ——
        #   generation 缺失/平局时可能取到块中段的人，而 `_descendants`
        #   只向下收 ⇒ 起点上方的先世被丢出框（实测：父子两人 generation
        #   同缺时选中儿子、父亲丢框）。手写谱 generation 没填全的最容易中招。
        bset = set(blk)
        tops = [x for x in blk if _dad_or_guess(people.get(x)) not in bset]
        cand = tops or blk
        return min(cand, key=lambda x: (people[x].get("generation") or 0,
                                       str(people[x].get("birth") or "")))

    def _descendants(start, within):
        keep, st = {start}, [start]
        while st:
            cur = st.pop()
            for c in kids.get(cur, ()):
                if c in within and c not in keep:
                    keep.add(c)
                    st.append(c)
        return keep

    out = {}
    for sn, members in per.items():
        # ① 父系连通块
        seen, blocks = set(), []
        for n in members:
            if n in seen:
                continue
            seen.add(n)
            blk, st = [], [n]
            while st:
                cur = st.pop()
                blk.append(cur)
                d = _dad_or_guess(people.get(cur))
                if d in members and d not in seen:
                    seen.add(d)
                    st.append(d)
                for c in kids.get(cur, ()):
                    if c in members and c not in seen:
                        seen.add(c)
                        st.append(c)
            blocks.append(blk)
        kings_of = {id(b): [x for x in b if (people[x].get("fief_gen") or 0) > 0]
                    for b in blocks}
        has_king_somewhere = any(kings_of[id(b)] for b in blocks)

        groups = []
        for b in blocks:
            kings = kings_of[id(b)]
            if has_king_somewhere and not kings:
                continue                        # ④ 混进来的先世/别家 → 整块丢
            start = _block_start(b, kings)
            keep = _descendants(start, set(b))
            # ★ 2026-10-04 使用者报：「冯国世系（冯伯）**没把第二代冯伯框进去**」。
            #   实测定因：冯代 `fief_gen=2`（**第二代冯伯**），可他父亲是冯无择、
            #   也就是始封君冯解敢的**弟弟** ⇒ 他**不是**始封君的后裔 ✗。
            #   而原规则「成员 = 起点 + 其父系后裔」只认**一个**起点 ⇒ 冯代**整支**
            #   出框（他连自己的框都没有 —— `clusters_of` 还会把单人簇丢掉）。
            #   ⇒ 修正：块内**每一位受封者**（`fief_gen > 0`）连同其后裔都进框。
            #   **不变的是**「受封之前的先世不进框」：未受封的先世（`fief_gen=0`）
            #   既不是起点、也不是任何受封者的后裔 ⇒ 仍然留在框外
            #   （实测冯世系里姬/毕/魏那 40 位先世照旧不进 ✓）。
            for k in kings:
                if k != start:
                    keep |= _descendants(k, set(b))
            if keep:
                groups.append((start, keep))
        if not groups:
            continue
        if len(groups) == 1:
            out[sn] = sorted(groups[0][1])
            continue
        # ⑤ 同名多组 → 朝代号（第 7 项）
        #   ★ 2026-09-26 使用者裁定：**西周 / 春秋 / 战国 基本上算一个朝代**，
        #     所以一律只用**粗朝代**前缀（周朝 / 汉朝 / 秦 …），
        #     **不得挂「西周」「春秋」「战国」** —— 也就是统称「周某某」。
        #     同一朝代内真的重名（如姜齐 / 妫齐都算周）→ 补「（起点君主名）」区分。
        #   同名多组里**人最多的那组排前面**
        groups.sort(key=lambda gk: -len(gk[1]))
        from .jue import branch_name
        titled = [(era_prefix(era_of_info(people[s])), s, keep)
                  for s, keep in groups]
        same_era = {}
        for t, _s, _k in titled:
            same_era[t] = same_era.get(t, 0) + 1
        for t, start, keep in titled:
            if same_era[t] > 1:
                # ★ 使用者 2026-09-26：「周朝齐国**不是已经分姜齐和田齐了吗**」
                #   ⇒ 同一朝代内的多支用**支名**命名（姜齐 / 田齐），
                #     不用「周齐（妫满）」这种；支名表在 `jue_history.json._支名`。
                #   氏取「势力」，但若它等于国名（如妫满的势力也写「齐」）
                #   就没有区分力 ⇒ 退回**起点君主名字首字**（妫满→妫）。
                shi = str(people[start].get("state_name") or "")
                if not shi or shi == sn:
                    shi = str(start)[:1]
                key = branch_name(sn, shi)
            else:
                key = f"{t}{sn}"
            while key in out:
                key += "·"
            out[key] = sorted(keep)
    return out


def state_group_boxes(people, lay, tier_colors, tier_priority=None, tier_of=None,
                      groups=None, titles=None):
    """计算"国世系 / 卿世系"虚线框。返回 (state_boxes, qing_boxes)。

    每项：(min_x, min_y, max_x, max_y, 颜色, 标题)
    tier_colors: 由主题提供；tier_priority: 爵位优先级映射（可选）。
    """
    positions = lay.positions
    node_h = lay.node_h
    scale = lay.scale
    actual_name_width = lay.name_width
    note_font_size = int(15 * scale * NOTE_FONT_RATIO)
    if tier_priority is None:
        tier_priority = TIER_PRIORITY

    def cell_width(person):
        note = people[person].get("note", "")
        if not note:
            return actual_name_width
        return actual_name_width + len(note) * note_font_size * 0.6 + 2

    state_all: Dict[str, List[str]] = {}
    # ★ 2026-09-23 修正（使用者报告「秽貊世系框混进非黑齿家的人」）：
    #   世系框必须认 `lineage_name`（宗庙世系 = **该国君主的家族**），
    #   不能认 `state_name` —— 后者的语义是「势力/效忠对象」（抽取器注释原文：
    #   「非君主只记『势力』，不写封国」），拿它分组会把「效忠秽貊的人」
    #   全框进「秽貊世系」（实测混入 7 个「X父」占位祖先：无爵位、fief_gen=0，
    #   只有势力字段是秽貊）。这个坑项目里踩过一次：刘邦功臣 103 人 state_name=汉
    #   但 lineage_name 空 → 任敖、灌婴全被框进「汉国世系」。
    #   使用者手填的封国要出框，走**联动**：保存封国时同步写 lineage_name。
    #   老档（整个谱牒没有一个 lineage_name）仍回退 state_name 以兼容旧数据。
    use_lineage = any(v.get("lineage_name") for v in people.values())
    # ★ 2026-10-04：`groups` 有值时**直接用现成分组**（= `gongqing.frame_groups`
    #   给的**家族框**：公室「X公族」/ 宗室「X国」/ 卿室「X氏」），跳过世系推导。
    #   两个家谱（代际 / 时间轴）共用同一份判据，口径一致。
    family_mode = groups is not None
    state_all = (dict(groups) if family_mode
                 else _lineage_groups(people, positions, use_lineage))
    # ★ 2026-10-07 **撤销「同名标题合并」**（使用者纠正：两家不同家族编号的公卿
    #   家族必须**各画一框**；当初的依据「续四十六」是误引，详见
    #   `state_group_boxes_timeline` 同处说明）。
    def edges_of(m):
        left = positions[m][0] - actual_name_width / 2
        return left, left + cell_width(m)

    def clusters_of(members):
        """**同一世系永远只画一个框**（★ 2026-10-04 使用者裁定：「**一律不分簇**」）。

        沿革（三批走完，别再走回头路）：
          · **续四十四**：冯家有两位受封者（冯解敢 `fief_gen=1`、冯代 `fief_gen=2`，
            冯代是始封君的**侄子**、不是其父系后裔）⇒ 块规则「成员 = 起点 + 其父系
            后裔」只认一个起点 ⇒ 冯代整支出框。已改为「块内**每一位**受封者连同
            其后裔都进框」。
          · **续四十五 / 四十六**：分簇会画出**两个**「冯世系」框 ⇒ 使用者：
            「为什么画两个世系？你把世系框往外框住不就行了」；先改成"优先整组"，
            再留一道"20 个节点宽的离谱闸"。
          · **本批**：使用者定案「**一律不分簇**」⇒ 闸门取消，**永远返回整组**。
            框往外扩，把该世系所有人一起框住。

        代价（使用者已知并接受）：《全史存档》里「方雷」3 人彼此隔着 31303 px
        （≈256 个节点宽）、「有熊」183 人隔 16085 px（≈134 倍）⇒ 那类世系的框
        会横跨**十来个屏幕**、中间大片留白。

        ⚠️ 老逻辑（按横向邻近度分簇：阈值 `node_w * 4`；全拆成单人时再按
        `node_w * 12` 跨度决定画不画）**已整体删除**，原文保存在
        `项目日志.md` **续四十七批**，需要时原样粘回。

        注：**单人世系**（该世系只剩 1 人）仍不画框 —— 那与分簇无关，
        由调用处的 `if len(group) < 2: continue` 把关。
        """
        return [sorted(members, key=lambda m: edges_of(m)[0])]

    state_boxes = []
    qing_boxes = []
    for sn, members in state_all.items():
        # ⚠️⚠️ 2026-10-04 **真凶修复**：家族分组的成员来自**存档的家族名册**，
        #   未必都在当前布局的 `positions` 里（被隐藏的非史实、未入谱的人…）。
        #   老路径的世系分组是从 `positions` 反推的（`_lineage_groups` 里
        #   `for n in positions`）⇒ 天然安全；家族分组没有这层保护 ⇒
        #   `clusters_of` 里的 `edges_of(m) → positions[m]` 会 **KeyError** ✗ ⇒
        #   被视图的 try/except 吞掉 ⇒ **整批框一个都不画**（使用者实测：
        #   「看不到框」就是这个）。
        #   ⇒ **必须在这里先过滤**（放进循环内已经太晚 —— `clusters_of` 先跑）。
        members = [m for m in members if m in positions]
        if not members:
            continue
        for group in clusters_of(members):
            # ★ 2026-10-04：家族模式下**不再**用「2 人成框」拦 —— 那道门槛已由
            #   `gongqing.frame_groups` 把关（含**公室 1 人也成框**的例外：
            #   「现在只有 1 人，以后会有后代」）。这里再拦一次会把「嬴公族」
            #   （本档只有秦质 1 人）整框丢掉（实测 54 → 53 ✗）。
            if len(group) < 2 and not family_mode:
                continue
            left_edges = [edges_of(m)[0] for m in group]
            right_edges = [edges_of(m)[1] for m in group]
            ys = [positions[m][1] for m in group]
            min_x = min(left_edges) - 8
            max_x = max(right_edges) + 8
            # ★ 2026-09-26 使用者实测「世系框标题压住节点的『史』徽标」——
            #   标题条画在框顶（min_y 起、高 16px），而第一代节点的『史』徽标
            #   悬在节点上沿外 4px ⇒ 正好压进标题条。框顶多让出一条标题带
            #   （20px：标题 16 + 间隙 4），徽标与节点从此在标题条下方。
            min_y = min(ys) - node_h / 2 - 18 - 20 * scale
            max_y = max(ys) + node_h / 2 + 18

            top_has_historical = any(
                people[m].get("historical") == "是" and abs(positions[m][1] - min(ys)) < node_h * 0.5
                for m in group
            )
            if top_has_historical:
                min_y -= 12 * scale

            # ★ 2026-09-26 修正：框色改走**上色爵称**（`tier_of`，见 app/jue.py），
            #   与铭牌/时间轴同一口径。原先直接读原文 `fief_title`，
            #   于是「铭牌按国爵是侯、框却按原文是公」两处打架。
            def _tier_of(m):
                if tier_of:
                    t = tier_of.get(m)
                    if t:
                        return t
                return people[m].get("fief_title", "无")

            best_tier = "无"
            best_priority = 0
            for m in group:
                t = _tier_of(m)
                if t in tier_priority and tier_priority[t] > best_priority:
                    best_priority = tier_priority[t]
                    best_tier = t
            title_color = tier_colors.get(best_tier, "#333333")

            qm = [m for m in group if _tier_of(m) == "卿"]
            has_qing = len(qm) >= 2
            # ★ 2026-09-26 使用者报「齐国高氏卿 / 齐国国氏卿 两个世系框怎么回事」：
            #   根因是**同一组卿族画了两个几乎重叠的框** —— 卿族（世系名以
            #   「氏」结尾，如「姜姓高氏」「姜姓国氏」）整组没有受封者，走
            #   「起点=始祖」分支照画君族大框（「X世系」），八十二批的卿内框
            #   （「X卿」）又框同一批人 ⇒ 两个框套在各自头顶，看着像多了两个
            #   莫名其妙的国。修法：**组内成员全是「卿」时只画卿内框**，不再画
            #   君族大框（卿族不是国，本就不该按「始封君世系」的画法框）。
            all_qing = bool(group) and all(_tier_of(m) == "卿" for m in group)
            if not all_qing:
                # ★ 2026-09-23 使用者要求：框题 = **用户填的字段值 + 「世系」**，
                #   不再自动补「国」/「卿」—— 字段值本身可能就是「X国」「X氏」
                #   或「XX（人名）」，再补「国」会变成「X国国世系」。
                #   框太窄时逐级退让：全称 → 只留字段值 → 不写。
                char_w = 14 * scale
                box_w = max_x - min_x
                # 家族框标题**照搬**（「冯国」/「冯公族」/「秦刘氏」）—— 使用者：
                # 「世系这俩字也不要了」；`titles` 映射负责「**键唯一、显示可同名**」
                # （两家「秦刘氏」就是两家，靠 `sn` = 家族编号区分）。
                _disp = (titles or {}).get(sn, sn) if family_mode else sn
                full_title = _disp if family_mode else sn + "世系"
                if box_w >= len(full_title) * char_w:
                    box_title = full_title
                elif box_w >= len(_disp) * char_w:
                    box_title = _disp
                else:
                    box_title = ""
                state_boxes.append((min_x, min_y, max_x, max_y,
                                    title_color, box_title))

            # ★ 2026-09-26 使用者报「重复画框，一个意思两个框」（如智氏）——
            #   混合组（组里**既有受封君、又有卿**）原来既画「X世系」大框、
            #   又画「X卿」内框，同一批人套两个框。修：**只有整组全是卿**
            #   （纯卿族，如「姜姓高氏」）才画卿内框；只要组里有非卿（是国/君族）
            #   就只画世系大框 —— 一组最多一个框。
            # 家族模式下**不画**「X卿」内框：卿室家族本身已经是一个「X氏」框了，
            # 再套一层就是当初那个「一个意思两个框」的老 bug（见上面注释）。
            if has_qing and all_qing and not family_mode:
                qleft = [edges_of(m)[0] for m in qm]
                qright = [edges_of(m)[1] for m in qm]
                qys = [positions[m][1] for m in qm]
                qing_boxes.append((
                    min(qleft) - 4,
                    # ★ 同上：给「X卿」标题条（14px）让出顶部带
                    min(qys) - node_h / 2 - 12 - 18 * scale,
                    max(qright) + 4, max(qys) + node_h / 2 + 12,
                    # ★ 兜底色与主题 `tier["卿"]` 对齐（2026-10-02 C 批：赭石）——
                    #   主题里一定有「卿」键，这里只是防主题不全的老路径。
                    tier_colors.get("卿", "#8B5A2B"), sn + "卿",
                ))

    return state_boxes, qing_boxes


def state_group_boxes_timeline(people, positions, widths, card_h, tier_colors,
                               tier_priority=None, char_w=8.0, tier_of=None,
                               groups=None, titles=None):
    """★ 2026-09-23 时间轴版「X国世系」虚线框。

    时间轴的坐标系与主树不同：卡片以**中心 x、顶部 y** 定位，宽度按人各异
    （`widths[name]`），高度固定 `card_h`。所以不能直接复用 `state_group_boxes`
    （那是主树版：中心定位 + 统一 node_h / name_width）。

    分组口径与主树完全一致：只认 `lineage_name`（宗庙世系 = 君主家族），
    整个谱牒没有 `lineage_name` 字段的老档才回退 `state_name` 兼容。
    返回 [(min_x, min_y, max_x, max_y, 颜色, 标题)]，框贴在卡片之上。

    ★ 2026-09-26 审查修复（M1）：新增 `tier_of` 参数 —— 框色改走**上色爵称**
      （`jue.tier_for`，主树版八十二批已改，这里漏了）。原先直接读原文
      `fief_title`，于是「铭牌按国爵是侯、时间轴框却按原文是公」两处打架
      —— 正是八十二批批评的那个问题在时间轴上的残留。
    """
    if tier_priority is None:
        tier_priority = TIER_PRIORITY

    def edges_of(n):
        w = widths.get(n, 40.0)
        x = positions[n][0]
        return x - w / 2, x + w / 2

    state_all = {}
    # ★ 2026-09-23 与主树同规：认 `lineage_name`（君族），老档回退 state_name
    #   （见 state_group_boxes 处的说明）
    use_lineage = any(v.get("lineage_name") for v in people.values())
    # ★ 2026-10-04：`groups` 有值 ⇒ 直接用它（家族框，与代际同一份判据）。
    family_mode = groups is not None
    state_all = (dict(groups) if family_mode
                 else _lineage_groups(people, positions, use_lineage))
    # ★ 2026-10-07 **撤销「同名标题合并」**（使用者纠正）：
    #   上一版把**同名不同家族编号**的两家并成一个框（如「秦国赵氏」= fam1000140
    #   ＋ fam1000153），依据是「续四十六：为什么画两个世系？你把世系框往外框住
    #   不就行了」—— **那是误引**：那条裁定说的是 `clusters_of` 把**同一个世系**
    #   拆成两个框（见该函数沿革）。使用者本轮明确：「**这是两个公卿家族**，
    #   我当时说要分开了吗？」⇒ **一家一框**（`frame_groups` 的 key 唯一，
    #   重复 key 实测 0 个 ⇒ 不会退回「双份」）。
    boxes = []
    for sn, members in state_all.items():
        # ⚠️⚠️ 同 `state_group_boxes`：家族成员未必都在 `positions` 里，
        #   不过滤就会 `positions[m]` KeyError ⇒ 整批框不画（实测踩过）。
        members = [m for m in members if m in positions]
        # ★ 2026-10-07 修「时间家谱一个家族框都画不出来」：家族模式下只判了
        #   `len < 2 and not family_mode`，**漏了 len == 0** —— 只要有**一家**
        #   的成员被筛光（默认勾着「仅显入谱」时很常见），下面的 `min(lefts)`
        #   就 `ValueError: min() iterable argument is empty`，被 rerender 的
        #   `except Exception: pass` 静默吞掉 ⇒ **整批框一起不画**（实测框数 = 0）。
        if not members:
            continue
        # ★ 2026-10-04：家族模式下门槛已由 `frame_groups` 把关（公室 1 人也成框），
        #   这里不再拦（否则「嬴公族」会被整框丢掉）。
        if len(members) < 2 and not family_mode:
            continue
        # ★ 2026-09-23 修「时间轴一个世系框都画不出来」（实测框数 = 0）：
        #   主树那套 `clusters_of` 按**横向**邻近度拆簇，因为主树里同代人横向
        #   并排、同一世系自然连成一片。但时间轴的坐标语义完全不同 ——
        #   横向是「同一年里并排的人」，纵向才是年份，同一世系的人横向上
        #   本来就散在几十年到上百年之间，一拆簇就全成单人，整批被丢弃。
        #   时间轴改为**不分簇**：直接取该世系全体成员的包围盒，
        #   纵向跨多少年都照画（这正是「X世系」在时间轴上的自然形态）。
        lefts = [edges_of(m)[0] for m in members]
        rights = [edges_of(m)[1] for m in members]
        ys = [positions[m][1] for m in members]
        min_x = min(lefts) - 8
        max_x = max(rights) + 8
        min_y = min(ys) - 14
        max_y = max(ys) + card_h + 10

        best_tier = "无"
        best_p = 0
        for m in members:
            # ★ 2026-09-26（M1）：优先走上色爵称（与铭牌同源），回退原文爵位
            if tier_of:
                t = tier_of.get(m)
                if not t:
                    t = people.get(m, {}).get("fief_title", "无")
            else:
                t = people.get(m, {}).get("fief_title", "无")
            if t in tier_priority and tier_priority[t] > best_p:
                best_p = tier_priority[t]
                best_tier = t
        color = tier_colors.get(best_tier, "#333333")

        box_w = max_x - min_x
        # ★ 2026-09-23 与主树同规：框题 = 字段值 + 「世系」，不自动补「国」
        # ★ 2026-10-04：家族模式下标题**照搬**（「冯国」/「冯公族」/「秦刘氏」）——
        #   使用者：「世系这俩字也不要了」；`titles` 负责「键唯一、显示可同名」。
        _disp = (titles or {}).get(sn, sn) if family_mode else sn
        full = _disp if family_mode else sn + "世系"
        if box_w >= len(full) * char_w + 6:
            title = full
        elif box_w >= len(_disp) * char_w + 6:
            title = _disp
        else:
            title = ""
        # ★ 2026-09-26 与主树同规：全「卿」的组（某国卿大夫家族）不是国，
        #   不按「始封君世系」画框 —— 题改「X卿」、色用卿色（与八十二批的
        #   卿内框同语义；时间轴没有内外两框机制，直接给出卿框）。
        # 家族模式下**不再**把「全卿组」改题「X卿」+ 卿色：卿室家族本身就是
        # 一个「X氏」框（颜色也已在 `frame_groups` 侧定好）。
        if not family_mode and members and all(
                ((tier_of or {}).get(m) or people.get(m, {}).get("fief_title", ""))
                == "卿" for m in members):
            color = tier_colors.get("卿", color)
            full = sn + "卿"
            title = full if box_w >= len(full) * char_w + 6 else sn
        boxes.append((min_x, min_y, max_x, max_y, color, title))
    return boxes
