# -*- coding: utf-8 -*-
"""交叉引用解析 —— 把 `Ren_Cheng_Shi_Code = 352` 这样的编号补上「→ 徐州」。

存档里到处都是「编号」而不是名字：人物在哪个城（`Ren_Cheng_Shi_Code`）、
哪个国（`Map_King_Code`）、配偶是谁（`Ren_Pei_Ou_Code_Array`）……
光看数字没法读，所以这里建三张索引，把编号翻成名字。

**只建有实证依据的映射**（见 `tools/probe_xref.py` 的可解析率普查）：
实测可解析率 100% 的字段才登记进 `RULES`，其余一律不管 —— 免得把一个
「其实是别的含义」的数字硬套成城名，反而误导。
"""
import re

# 字段名 → (实体类型, 是否可能是数组)
# 依据：tools/probe_xref.py 跑出来的可解析率 ≥89% 的那些字段
RULES = {
    # ---- → 城池名（New_Save_Map_Data.Map_Code → Map_Name）----
    "Ren_Cheng_Shi_Code": "city",      # 100%  人物所在城邑
    "Ju_Suo_Code": "city",             # 100%  家族居所
    "King_Guo_Du_Code": "city",        # 100%  国都
    "Onwer_Code": "city",              # 100%  所有者
    "Army_Code": "city",               # 100%  军队驻地
    "Map_Code": "city",                # 自身编号（详情里也补一下，便于对照）
    "Put_Map_Code": "city",
    "Qi_Guan_Map_Code": "city",
    "Zheng_Ce_Code": "city",
    "Res_Bank_Code": "city",           # 89%
    # ---- → 国名（Save_KingData.King_Code → King_Name）----
    "Map_King_Code": "king",           # 100%  城池所属国
    "Wai_Jiao_Code_1": "king",         # 100%  外交甲方
    "Zong_Miao_Code": "king",          # 100%  宗庙所属国
    "Faith_Gods_Sys_Code": "king",     # 100%
    "Army_Data_Static_Code": "king",
    "Put_King_Code": "king",
    "Start_King_Code": "king",
    "King_Code": "king",
    # ---- → 人名（人物表.Ren_Code → Ren_Name）----
    "Ren_Code": "person",
    "Jia_Zhu_Code": "person",          # 100%  家主
    "Buff_Ren_Code": "person",         # 100%
    "Put_Ren_Code": "person",
    "Father_Code": "person",
    "Mother_Code": "person",
    "Ancestor_Code": "person",
    "Current_Genealogy_Formers": "person",
    "Leader_Code": "person",
    "Master_Code": "person",
    "Only_Code": "person",
}

# 数组型引用 → 元素类型
ARRAY_RULES = {
    "Ren_Pei_Ou_Code_Array": "person",     # 配偶 100%
    "Ren_Zi_Nv_Code_Array": "person",      # 子女 95%
    "King_Code_Array": "king",
    "Ren_Code_Array": "person",
    "Member_Code_Array": "person",
    "City_Code_Array": "city",
    "Map_Code_Array": "city",
    "Jia_Zu_Array": "family",
    "King_Array": "king",
}

# 这些是「自身编号」，补名字没意义（详情面板里已经能看到自己的名字）
SELF_FIELDS = {"Ren_Code", "King_Code", "Map_Code", "Code", "id", "ID",
               "Only_Code", "Unique_ID"}


class XRef:
    """编号 → 名字的索引集。"""

    def __init__(self):
        self.city = {}      # Map_Code → 城名
        self.king = {}      # King_Code → 国名
        self.person = {}    # Ren_Code → 人名
        self.family = {}    # 家族 Code → 氏

    # ---------------------------------------------------------------- 构建
    @classmethod
    def build(cls, slot):
        x = cls()
        t = slot.tables.get("New_Save_Map_Data")
        if t:
            for r in t.rows:
                c = r.get("Map_Code")
                if c is not None and r.get("Map_Name"):
                    x.city[str(c)] = r["Map_Name"]
        for tn in ("Save_KingData", "Save_Empty_KingData"):
            t = slot.tables.get(tn)
            if t:
                for r in t.rows:
                    c = r.get("King_Code")
                    if c is not None and r.get("King_Name"):
                        x.king[str(c)] = r["King_Name"]
        for tn in ("Save_Ren_Data", "Save_Dead_Ren_Data", "Save_Woman_Data",
                   "Save_Chu_Sheng_Data"):
            t = slot.tables.get(tn)
            if t:
                for r in t.rows:
                    c = r.get("Ren_Code")
                    if c is not None and r.get("Ren_Name"):
                        x.person.setdefault(str(c), r["Ren_Name"])
        t = slot.tables.get("Jia_Zu_Controller/Jia_Zu_Map")
        if t:
            for r in t.rows:
                c = r.get("Code")
                nm = r.get("Jia_Shi") or r.get("Zu_Xing")
                if c is not None and nm:
                    x.family[str(c)] = nm
        # 族谱里还有一批人物表没收的人
        g = slot.tables.get("Jia_Zu_Genealogy")
        if g:
            for r in g.rows:
                for rec in (r.get("Genealogy_Ren_Record_Array") or []):
                    if not isinstance(rec, dict):
                        continue
                    c = rec.get("Ren_Code")
                    if c is None or str(c) in x.person:
                        continue
                    nm = rec.get("Ren_Name") or (
                        f"{rec.get('Ren_Shi') or rec.get('Ren_Xing') or ''}"
                        f"{rec.get('Ren_Ming') or ''}")
                    if nm:
                        x.person[str(c)] = nm
        return x

    # ---------------------------------------------------------------- 查询
    def lookup(self, kind, value):
        table = getattr(self, kind, None)
        if not table:
            return None
        return table.get(str(value))

    def resolve(self, field, value):
        """字段 + 值 → (类型中文, 名字)。解析不了返回 None。

        **只对登记在 RULES / ARRAY_RULES 里的字段动手** —— 宁可少注一个，
        也不要把一个含义不明的数字硬翻成城名。
        """
        kind = RULES.get(field)
        if kind and field not in SELF_FIELDS:
            nm = self.lookup(kind, value)
            if nm:
                return (KIND_ZH[kind], nm)
            return None
        return None

    def resolve_many(self, field, values):
        """数组型引用 → [(原编号, 名字)]，查不到的跳过。"""
        kind = ARRAY_RULES.get(field)
        if not kind or not isinstance(values, list):
            return []
        out = []
        for v in values[:30]:
            if isinstance(v, (dict, list)):
                continue
            nm = self.lookup(kind, v)
            if nm:
                out.append((v, nm))
        return out

    def stats(self):
        return {"城": len(self.city), "国": len(self.king),
                "人物": len(self.person), "家族": len(self.family)}


KIND_ZH = {"city": "城", "king": "国", "person": "人", "family": "家族"}


# 详情面板里要「补名字」的数组字段
ARRAY_LABEL = {
    "Ren_Pei_Ou_Code_Array": "配偶",
    "Ren_Zi_Nv_Code_Array": "子女",
    "King_Code_Array": "相关国",
    "Ren_Code_Array": "相关人物",
    "Member_Code_Array": "成员",
    "City_Code_Array": "相关城池",
    "Map_Code_Array": "相关城池",
}
