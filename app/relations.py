# -*- coding: utf-8 -*-
"""关系引擎 —— 从存档里把「人—人」的血缘与婚姻关系抽成一张图。

## 为什么需要它
存档里同一个人的亲属信息**散在三个地方**，而且各自不完整：

| 方向 | 数据源 | 实测覆盖率（秦末档 6822 人） |
|---|---|---|
| 子 → 父 | 人物表 `Parent.Father.Ren_Code` | 3949 人有值（**父系权威来源**） |
| 子 → 母 | 人物表 `Parent.Mother.Ren_Code` | 只 12 条有值（**几乎全空**） |
| 父 → 子 | 人物表 `Ren_Zi_Nv_Code_Array` | 2369 人的字段非空 |
| 父 → 子 | 族谱 `Genealogy_Ren_Record_Array[].Father_Code` | 3603 条（**族谱是唯一全量表**） |
| 夫 ↔ 妻 | 人物表 `Ren_Pei_Ou_Code_Array` | 只 6 条（**几乎全空**） |

结论：
· **父系链**靠 `Parent.Father` 与族谱 `Father_Code` **双向**都能走通 —— 互为补充，取并集。
· **母系链**存档里基本没记，只能靠 `Parent.Mother.Ren_Name`（往往是个占位词「媵妾」）
  或族谱 `Mother_Name`。**照实呈现，没有就说没有**，绝不为了好看编一个。
· **配偶**同理 —— `Ren_Pei_Ou_Code_Array` 只有 6 条，所以关系视图里配偶一栏
  大多数人是空的，这不是 bug，是存档本身就没写。

## 「媵妾」是什么
`Parent.Mother.Ren_Name` 大量出现 `"媵妾"` 且 `Ren_Code` 为空 —— 这是游戏对
「生母身份低微、不入谱」的统一占位。本模块把它识别为 `placeholder=True`，
GUI 会以灰色斜体显示，不当作真人。
"""
from collections import defaultdict

# 游戏用来占位的「非真人」生母名
PLACEHOLDER_NAMES = {"媵妾", "无名", "不详", "", None}

# 关系类型
FATHER = "父"
MOTHER = "母"
SPOUSE = "配偶"
SON = "子"
DAUGHTER = "女"
CHILD = "子女"


class Person:
    """人物在关系图里的节点。"""
    __slots__ = ("code", "name", "sex", "alive", "dynasty", "level",
                 "culture", "birth", "death", "sources")

    def __init__(self, code, name, sex=None, alive=True, level=None,
                 culture="", birth=None, death=None, sources=()):
        self.code = str(code)
        self.name = name or f"（无名·{code}）"
        self.sex = sex
        self.alive = alive
        self.level = level
        self.culture = culture
        self.birth = birth
        self.death = death
        self.sources = list(sources)

    @property
    def sex_label(self):
        return {0: "男", 1: "女"}.get(self.sex, "?")

    def __repr__(self):
        return f"<Person {self.code} {self.name}>"


class Relation:
    """有方向的亲属边。`kind` 用 FATHER/MOTHER/SPOUSE/SON/DAUGHTER 之一。"""
    __slots__ = ("kind", "person", "placeholder", "note")

    def __init__(self, kind, person, placeholder=False, note=""):
        self.kind = kind
        self.person = person          # Person 或 None（没查到人但有名字）
        self.placeholder = placeholder
        self.note = note

    def __repr__(self):
        return f"<{self.kind} {self.person}>"


class RelationGraph:
    """整个存档的人物关系图。

    用法：
        g = RelationGraph.build(slot)
        g.profile("162")          # → 徐福的亲属档案
        g.search("嬴")            # → 按名字找人
    """

    def __init__(self):
        self.people = {}                    # code → Person
        self.father_of = defaultdict(set)   # code → {子code}
        self.mother_of = defaultdict(set)   # code → {子code}
        self.spouse_of = defaultdict(set)   # code → {配偶code}
        self.father = {}                    # code → (父code, 父名)
        self.mother = {}                    # code → (母code, 母名, 是否占位)
        self.notes = []

    # ---------------------------------------------------------------- 构建
    @classmethod
    def build(cls, slot):
        g = cls()
        g._collect_people(slot)
        g._collect_parents(slot)
        g._collect_spouses(slot)
        g._collect_genealogy(slot)
        return g

    def _collect_people(self, slot):
        for tname in ("Save_Ren_Data", "Save_Dead_Ren_Data", "Save_Woman_Data",
                      "Save_Chu_Sheng_Data"):
            t = slot.tables.get(tname)
            if not t:
                continue
            alive = tname != "Save_Dead_Ren_Data"
            for r in t.rows:
                code = r.get("Ren_Code")
                if code in (None, ""):
                    continue
                code = str(code)
                p = self.people.get(code)
                if p is None:
                    p = Person(code, r.get("Ren_Name"), r.get("Ren_Sex"),
                               alive=alive, level=r.get("Ren_Leve"),
                               culture=r.get("Ren_Wen_Hua") or "",
                               birth=r.get("Ren_Chu_Sheng_Time"),
                               death=r.get("Ren_End_Time"))
                    self.people[code] = p
                else:
                    # 先来优先，后来的只补空缺
                    if not p.name or p.name.startswith("（无名"):
                        p.name = r.get("Ren_Name") or p.name
                    if p.sex is None:
                        p.sex = r.get("Ren_Sex")
                    if p.alive is None:
                        p.alive = alive
                    if p.level is None:
                        p.level = r.get("Ren_Leve")
                    if not p.culture:
                        p.culture = r.get("Ren_Wen_Hua") or ""
                if tname not in p.sources:
                    p.sources.append(tname)

    def _collect_parents(self, slot):
        """子 → 父/母。这是**父系最权威**的来源。"""
        for tname in ("Save_Ren_Data", "Save_Dead_Ren_Data", "Save_Woman_Data",
                      "Save_Chu_Sheng_Data"):
            t = slot.tables.get(tname)
            if not t:
                continue
            for r in t.rows:
                code = r.get("Ren_Code")
                if code in (None, ""):
                    continue
                code = str(code)
                par = r.get("Parent")
                if not isinstance(par, dict):
                    continue
                f = par.get("Father")
                if isinstance(f, dict):
                    fc = f.get("Ren_Code")
                    fn = f.get("Ren_Name")
                    if fc not in (None, ""):
                        self.father[code] = (str(fc), fn)
                        self.father_of[str(fc)].add(code)
                m = par.get("Mother")
                if isinstance(m, dict):
                    mc = m.get("Ren_Code")
                    mn = m.get("Ren_Name")
                    if mc not in (None, ""):
                        self.mother[code] = (str(mc), mn, False)
                        self.mother_of[str(mc)].add(code)
                    elif mn:
                        # 有名字没编号 → 占位（「媵妾」就是这种）
                        self.mother.setdefault(
                            code, ("", mn, mn in PLACEHOLDER_NAMES))
                # 子女（反向表，供父系链加速）
                kids = r.get("Ren_Zi_Nv_Code_Array")
                if isinstance(kids, list):
                    for k in kids:
                        if k in (None, ""):
                            continue
                        self.father_of[code].add(str(k))

    def _collect_spouses(self, slot):
        for tname in ("Save_Ren_Data", "Save_Dead_Ren_Data", "Save_Woman_Data",
                      "Save_Chu_Sheng_Data"):
            t = slot.tables.get(tname)
            if not t:
                continue
            for r in t.rows:
                code = r.get("Ren_Code")
                if code in (None, ""):
                    continue
                code = str(code)
                ps = r.get("Ren_Pei_Ou_Code_Array")
                if not isinstance(ps, list):
                    continue
                for s in ps:
                    if s in (None, ""):
                        continue
                    s = str(s)
                    self.spouse_of[code].add(s)
                    self.spouse_of[s].add(code)      # 配偶是对称的

    def _collect_genealogy(self, slot):
        """族谱是**父系链的全量表** —— 人物表只收了 2369 人，族谱有 3603 条父编号。

        族谱记录里 `Ren_Name` 常常是空的（只有姓/氏/名三段），要拼。
        """
        t = slot.tables.get("Jia_Zu_Genealogy")
        if not t:
            return
        recs = 0
        for gi, g in enumerate(t.rows):
            for r in (g.get("Genealogy_Ren_Record_Array") or []):
                if not isinstance(r, dict):
                    continue
                code = r.get("Ren_Code")
                if code in (None, ""):
                    continue
                code = str(code)
                recs += 1
                name = r.get("Ren_Name")
                if not name:
                    name = (f"{r.get('Ren_Shi') or r.get('Ren_Xing') or ''}"
                            f"{r.get('Ren_Ming') or ''}") or None
                p = self.people.get(code)
                if p is None:
                    sex = 1 if r.get("Memorial_Ren_Sex") == "女" else None
                    p = Person(code, name, sex, alive=False, sources=["族谱"])
                    self.people[code] = p
                else:
                    if (not p.name or p.name.startswith("（无名")) and name:
                        p.name = name
                    if "族谱" not in p.sources:
                        p.sources.append("族谱")
                # 族谱的父/母
                fc, fn = r.get("Father_Code"), r.get("Father_Name")
                if fc not in (None, "") and code not in self.father:
                    self.father[code] = (str(fc), fn)
                    self.father_of[str(fc)].add(code)
                mc, mn = r.get("Mother_Code"), r.get("Mother_Name")
                if mc not in (None, "") and code not in self.mother:
                    self.mother[code] = (str(mc), mn, False)
                    self.mother_of[str(mc)].add(code)
                elif mn and code not in self.mother:
                    self.mother[code] = ("", mn, mn in PLACEHOLDER_NAMES)
        self.notes.append(f"族谱提供 {recs} 条人物记录")

    # ---------------------------------------------------------------- 查询
    def get(self, code):
        return self.people.get(str(code))

    def name_of(self, code):
        p = self.people.get(str(code))
        return p.name if p else None

    def children_of(self, code):
        """某人的子女编号集合（父系 ∪ 母系）。"""
        code = str(code)
        return set(self.father_of.get(code, ())) | set(self.mother_of.get(code, ()))

    def parents_of(self, code):
        """某人的 (父code, 母code)；没有的为 None。"""
        code = str(code)
        f = self.father.get(code)
        m = self.mother.get(code)
        return (f[0] if f else None,
                (m[0] if m and m[0] else None))

    def siblings_of(self, code):
        """兄弟姐妹 = 同父 ∪ 同母 − 自己。"""
        code = str(code)
        out = set()
        f = self.father.get(code)
        if f and f[0]:
            out |= set(self.father_of.get(str(f[0]), ()))
        m = self.mother.get(code)
        if m and m[0]:
            out |= set(self.mother_of.get(str(m[0]), ()))
        out.discard(code)
        return out

    def profile(self, code):
        """一个人的完整亲属档案。返回 dict，每个值是 Relation 列表。

        键：父 / 母 / 配偶 / 子女 / 兄弟姐妹
        """
        code = str(code)
        out = {"父": [], "母": [], "配偶": [], "子女": [], "兄弟姐妹": []}

        # 父
        f = self.father.get(code)
        if f:
            fc, fn = f
            p = self.people.get(fc)
            out["父"].append(Relation(FATHER, p, note=f"编号 {fc}"))
        # 母
        m = self.mother.get(code)
        if m:
            mc, mn, ph = m
            if ph:
                out["母"].append(Relation(MOTHER, None, placeholder=True, note=mn))
            else:
                p = self.people.get(mc)
                if p is None and mc not in (None, ""):
                    p = Person(mc, mn, sex=1)
                out["母"].append(Relation(MOTHER, p, note=f"编号 {mc}"))

        # 配偶
        for sc in sorted(self.spouse_of.get(code, ())):
            out["配偶"].append(Relation(SPOUSE, self.people.get(sc) or Person(sc, None)))

        # 子女（两个来源取并集）
        kids = set(self.father_of.get(code, ())) | set(self.mother_of.get(code, ()))
        kids.discard(code)
        for kc in sorted(kids, key=lambda x: (len(x), x)):
            p = self.people.get(kc)
            kind = CHILD
            if p is not None and p.sex == 1:
                kind = DAUGHTER
            elif p is not None and p.sex == 0:
                kind = SON
            out["子女"].append(Relation(kind, p or Person(kc, None)))

        # 兄弟姐妹（同父或同母）
        sibs = set()
        if f:
            sibs |= self.father_of.get(str(f[0]), set())
        # 母系只在有编号时才用
        m2 = self.mother.get(code)
        if m2 and m2[0]:
            sibs |= self.mother_of.get(str(m2[0]), set())
        sibs.discard(code)
        for sc in sorted(sibs, key=lambda x: (len(x), x)):
            out["兄弟姐妹"].append(Relation("兄弟姐妹", self.people.get(sc) or Person(sc, None)))
        return out

    def ancestors(self, code, depth=3):
        """向上追溯父系，返回 [(世代偏移, Person)]，只走父系（母系存档里基本没编号）。"""
        out = []
        cur = str(code)
        seen = {cur}
        for d in range(1, depth + 1):
            f = self.father.get(cur)
            if not f:
                break
            fc = str(f[0])
            if fc in seen:
                break
            seen.add(fc)
            p = self.people.get(fc)
            if p is None:
                p = Person(fc, f[1])
            out.append((-d, p))
            cur = fc
        return out

    def descendants(self, code, depth=3):
        """向下推子女（父系+母系取并集），BFS。返回 [(世代偏移, Person)]。"""
        out = []
        frontier = [(str(code), 0)]
        seen = {str(code)}
        while frontier:
            cur, d = frontier.pop(0)
            if d >= depth:
                continue
            kids = (set(self.father_of.get(cur, ()))
                    | set(self.mother_of.get(cur, ())))
            for kc in sorted(kids, key=lambda x: (len(x), x)):
                if kc in seen:
                    continue
                seen.add(kc)
                p = self.people.get(kc)
                if p is None:
                    p = Person(kc, None)
                out.append((d + 1, p))
                frontier.append((kc, d + 1))
        return out

    def search(self, query, limit=80):
        """按姓名 / 编号找人。返回 [(code, Person)]。"""
        q = str(query).strip()
        if not q:
            return []
        ql = q.lower()
        out = []
        for code, p in self.people.items():
            if ql in str(p.name).lower() or ql == code:
                out.append((code, p))
                if len(out) >= limit:
                    break
        return out

    def stats(self):
        return {
            "人物总数": len(self.people),
            "有父记载": len(self.father),
            "有母记载": len(self.mother),
            "有父→子边": sum(len(v) for v in self.father_of.values()),
            "有母→子边": sum(len(v) for v in self.mother_of.values()),
            "有配偶边": sum(len(v) for v in self.spouse_of.values()) // 2,
        }
