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
    # ⚠️ 2026-10-03 **删掉** `"Zheng_Ce_Code": "city"` —— 这条登记错了。
    #   实测本档 `Zheng_Ce_Code` 出现 **44994 次**，其中 **44994/44994 都能在
    #   `names_map.ZHENG_CE_CODES`（政策名）里查到**；当城名只查到 13672 次（30.5%）。
    #   它已在 `labels.VALUE["Zheng_Ce_Code"]` 里按政策名解析。
    #   ★ 不变式：**有专属码表（`labels.VALUE` / `names_map`）的字段，不许再登记成引用**
    #     —— 否则 `_fmt_val` 会用「城名」覆盖掉正确的「政策名」。
    #     这条不变式已由 `tools/check_labels.py` 守着。
    "Res_Bank_Code": "city",           # 89%
    # ---- 宗庙（`Zong_Miao_Controller`）★ 2026-10-03 ----
    #   使用者截图指出「庙主题」显示成裸码 `68656/7104/4003` —— 那是**人物编号**：
    #   实测 `父庙.Miao_Theme = 4003`，而同一份数据里 `Father_Code=4003` 正是
    #   `Father_Name=宋义`。⇒ 逆向出人名才算译完。
    "Miao_Theme": "person",
    "Memorial_Code": "person",
    "Memorial_Ren_Code": "person",
    "Memorial_Ren_Now_King_Code": "king",
    # ---- → 国名（Save_KingData.King_Code → King_Name）----
    "Map_King_Code": "king",           # 100%  城池所属国
    "Wai_Jiao_Code_1": "king",         # 100%  外交甲方
    "Zong_Miao_Code": "king",          # 100%  宗庙所属国
    # ⚠️ 2026-10-03 **删掉** `"Faith_Gods_Sys_Code": "king"` —— 同属上面那类错误。
    #   它是**神系码 1~5**，`labels.VALUE` 已给出「皇天 / 东皇太一 / 帝俊 / 烛龙 / 女娲肠」；
    #   当国名解会把神系码 4 解成「**匈奴**」（第 4 个国）而不是「**烛龙**」。
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
    # ---- ★ 2026-10-04 世界页去编码（使用者：「编码全部本地化成汉字」）----
    #   登记前逐一实测解析率（本模块铁律：达标才登记）：
    "Teacher": "person",               # 求学结束表·教师（1/1，语义确定）
    "Student": "person",               # 求学结束表·学生（1/1，语义确定）
    "From_King": "king",               # 坐席表·来自国（20/20）
    "Obj_King": "king",                # 坐席表·对象国（20/20）
    "King_data": "king",               # 蛮狄关系·对方国（字符串编号，语义确定）
    "Wai_Jiao_Code_2": "king",         # 外交乙方（实测 2000/2000；甲方早已登记）
    "Jia_Zu_Code_1": "family",         # 家族关系图·甲方（实测 808/821）
    "Jia_Zu_Code_2": "family",         # 家族关系图·乙方（实测 582/821，
                                       #   解不出的画「—」，不出裸码）
    "Teacher_Code": "person",          # 世门·师承的师父（语义确定）
    "Obj_King_Data": "king",           # 失地表·对象国（实测 264/264）
    "Chi_You_King": "king",            # 典册·蚩尤之国（4/4）
    "Wang_Chao_Zhu_Dao_King": "king",  # 王朝主导国（2/2）
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
    # ★ 2026-10-03：客馆「游士」名单
    #   （`Ke_Guan_Table_Manager.Ke_Guan_Data.You_Shi_Data.Ren_Map`）
    #   使用者：「各个客馆的数据，要人名，要映射到人物上」。
    #   实测本档可解析率 **100%（4453/4453）** —— 达标才登记（本模块的铁律）。
    "Ren_Map": "person",
    # ★ 2026-10-04：世门「师承」名单（`Shi_Men_Guan_Xi_Arr.Student_Code_Array`）
    "Student_Code_Array": "person",
    # ★ 2026-10-04：史书里「圣人生效」名单 —— 该书惠及的圣人（人名码）
    "Sheng_Ren_Sheng_Xiao_Code_Array": "person",
    # ★ 2026-10-04：国家地图视角的国土城列表 —— 注意它**不是数组**，是
    #   逗号拼接的字符串（"113,115,128,…"），`_cell` 里按逗号拆开逐个解
    #   （实测展开后 590/590 全部可解）。
    "King_Map_Array": "city",
}

# 这些是「自身编号」，补名字没意义（详情面板里已经能看到自己的名字）
# ★ 2026-10-03 移出 `Map_Code`：它只是**在城池表里**才等于自己；在别的表
#   （如客馆表）它是**城池引用**。实测 `Map_Code=33 → 咸阳`、`349 → 沛邑`、
#   `458 → 邯郸` 全部可解 —— 挡在这里等于让「城」列永远显示编号。
SELF_FIELDS = {"Ren_Code", "King_Code", "Code", "id", "ID",
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

    def resolve(self, field, value, allow_self=False):
        """字段 + 值 → (类型中文, 名字)。解析不了返回 None。

        **只对登记在 RULES / ARRAY_RULES 里的字段动手** —— 宁可少注一个，
        也不要把一个含义不明的数字硬翻成城名。

        ★ 2026-10-04 `allow_self`：`SELF_FIELDS`（King_Code / Code / Ren_Code
          这些「自身编号」字段名）在**别的表里出现时是引用**（如资源分配表的
          King_Code=0 → 秦），表格单元格里要解出名来（使用者：「编码全部本地化
          成汉字」）。详情卡里「自己指自己」的那一行仍然不解（默认 False），
          免得多出一条跟标题重复的「国 秦」。
        """
        kind = RULES.get(field)
        if kind and (allow_self or field not in SELF_FIELDS):
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
    "Ren_Map": "游士",
}
