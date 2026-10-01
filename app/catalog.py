# -*- coding: utf-8 -*-
"""表族目录 —— 90 个表族的中文名、分类、默认列。

**字段名翻译已经全部搬到 `labels.py`**（那边覆盖实测出现过的全部 1004 个字段名，
并有覆盖率自检脚本 `tools/check_labels.py` 守着）。本模块只管「表族」这一层：
表族叫什么、归到哪个分类、表格默认显示哪几列。

`label_of()` 保留为薄封装，方便老代码继续用。
"""
from collections import OrderedDict

from . import labels as L

# 左导航的分类顺序
CATEGORIES = ["人物", "国家", "城池", "家族", "外交", "军事", "文化", "其它"]


def label_of(key: str) -> str:
    """字段中文名 —— 转交给 `labels.field_label()`（100% 覆盖率）。"""
    return L.field_label(key)


# ★ 2026-09-28 全项目整理（第 1 批）：删除 `value_of` —— 全仓（app / main /
#   tools）无任何调用（各处的取值翻译都直接走 `labels.value_label`），
#   它只是 `L.value_label` 的转发壳。


# ---------------------------------------------------------------- 表族目录
# name → (中文名, 分类)
# 覆盖 Save_All_1/2 两档共 90 个表族（见 _stats/probe_more.txt 的清单自检）
FAMILIES = OrderedDict([
    # ---- 人物 ----
    ("Save_Ren_Data",            ("人物 · 在世", "人物")),
    ("Save_Dead_Ren_Data",       ("人物 · 已故", "人物")),
    ("Save_Woman_Data",          ("人物 · 女性", "人物")),
    ("Save_Chu_Sheng_Data",      ("人物 · 出生队列", "人物")),
    ("Save_King_Death_Data",     ("人物 · 国君死亡", "人物")),
    # 人物子表
    ("Save_Ren_Data/Ren_Zheng_Ce_Array",   ("人物 · 政策", "人物")),
    ("Save_Ren_Data/Ren_Neng_Li_Array",    ("人物 · 能力", "人物")),
    ("Save_Ren_Data/Buff_Array",           ("人物 · 增益", "人物")),
    ("Save_Ren_Data/Ren_Face",             ("人物 · 容貌", "人物")),
    ("Save_Ren_Data/Ren_Pei_Ou_Code_Array", ("人物 · 配偶", "人物")),
    ("Save_Ren_Data/Ren_Zi_Nv_Code_Array", ("人物 · 子女", "人物")),
    # ---- 国家 ----
    ("Save_KingData",            ("国家 · 总表", "国家")),
    ("Save_Empty_KingData",      ("国家 · 空国模板", "国家")),
    ("Save_Look_King_Map",       ("国家 · 地图视角", "国家")),
    ("Zong_Miao_Controller",     ("国家 · 宗庙", "国家")),
    ("Save_Wang_Chao_Data",      ("王朝制度", "国家")),
    ("Save_King_Death_Data",     ("国家 · 国君死亡", "国家")),
    ("Gong_Qing_Controller",     ("公卿 · 功劳簿", "国家")),
    ("Shi_Men_Controller",       ("世门 · 门第", "国家")),
    ("Shi_Zu_Controller",        ("世族", "国家")),
    ("Ke_Guan_Table_Manager",    ("客馆", "国家")),
    ("Men_She_Table_Manager",    ("门舍", "国家")),
    # ★ 2026-09-22 纠错：原译「戏座」是错的。
    #   拼音 Xi_Zuo = **细作**；字段 `From_King`(派遣国) → `Obj_King`(目标国)
    #   + `Is_Si_Shi`(是否私事) 正是「派遣间谍」的行为特征；
    #   官方 WIKI《谍战系统》：禁府 → 谍者名册 → 派遣细作。★ 归入「外交」更准（原归国家）。
    ("Xi_Zuo_Table_Manager",     ("细作 · 谍报名册", "外交")),
    ("Jian_Yu_Table_Manager",    ("监狱 · 建狱", "国家")),
    ("Shan_Zhai_Tu_Lao_Manager", ("山寨 · 徒劳", "国家")),
    # 国家子表
    ("Save_KingData/Play_Card_Array",        ("国家 · 玩法卡牌", "国家")),
    ("Save_KingData/King_Wen_Hua_Array",     ("国家 · 文化", "国家")),
    ("Save_KingData/King_Zheng_Ing_Array",   ("国家 · 政令进行中", "国家")),
    ("Save_KingData/King_Stage_Record",      ("国家 · 阶段记录", "国家")),
    ("Save_KingData/King_Buff_Array",        ("国家 · 增益", "国家")),
    ("Save_KingData/King_Wen_Hua_Buff_Array", ("国家 · 文化增益", "国家")),
    ("Save_KingData/Zheng_Ce_Shu_Array",     ("国家 · 政策书", "国家")),
    ("Save_KingData/Map_Diu_Shi_Array",      ("国家 · 失地表", "国家")),
    ("Save_KingData/Zai_Hai_Array",          ("国家 · 灾害", "国家")),
    ("Save_KingData/Recent_Zai_Hai_Array",   ("国家 · 近期灾害", "国家")),
    ("Save_KingData/Dian_Ce_Array",          ("国家 · 典册", "国家")),
    ("Save_KingData/Guo_Jun_Zun_Hao_List",   ("国家 · 国君尊号", "国家")),
    ("Save_KingData/Zhan_Zheng_Array",       ("国家 · 战争", "国家")),
    ("Zong_Miao_Controller/All_King_Zong_Miao_Array",
     ("宗庙 · 各国宗庙", "国家")),
    ("Zong_Miao_Controller/All_Memorial_Array",
     ("宗庙 · 祭祀牌位", "国家")),
    ("Zong_Miao_Controller/All_Miao_Array",  ("宗庙 · 庙主", "国家")),
    # ---- 城池 ----
    ("New_Save_Map_Data",        ("城池 · 总表", "城池")),
    ("New_Save_Jin_Liu_Array",   ("进度流", "城池")),
    ("Save_Shan_Qu_Data",        ("山区", "城池")),
    ("Save_Shan_Zhai_Data",      ("山寨", "城池")),
    ("Save_Zai_Data",            ("灾害", "城池")),
    ("Save_Chong_Tu_Data",       ("冲突", "城池")),
    ("Save_Hui_Fang_Data",       ("回放纪事", "城池")),
    # 城池子表
    ("New_Save_Map_Data/Map_Build_Data",     ("城池 · 建筑", "城池")),
    ("New_Save_Map_Data/Land_Allocation",    ("城池 · 土地分配", "城池")),
    ("New_Save_Map_Data/Map_Cheng_Fang_Array", ("城池 · 城防", "城池")),
    ("New_Save_Map_Data/Map_Jie_Ceng_Obj",   ("城池 · 阶层", "城池")),
    ("New_Save_Map_Data/Map_Wen_Hua_Array",  ("城池 · 文化", "城池")),
    ("New_Save_Map_Data/Map_Buff_Array",     ("城池 · 增益", "城池")),
    ("New_Save_Map_Data/Map_Jun_Dui_Array",  ("城池 · 驻军", "城池")),
    ("New_Save_Map_Data/Zhan_Ling_Data",     ("城池 · 占领", "城池")),
    ("New_Save_Map_Data/Map_Tag",            ("城池 · 标记", "城池")),
    # ---- 家族 ----
    ("Jia_Zu_Controller",        ("家族 · 总表", "家族")),
    ("Jia_Zu_Genealogy",         ("家族 · 族谱", "家族")),
    ("Jia_Zu_Zhai_Yuan_Manager", ("家族 · 宅院", "家族")),
    ("Jia_Zu_Jian_Yu_Manager",   ("家族 · 监狱", "家族")),
    ("Save_Jia_Zu_And_Shan_Zhai_Guan_Xi", ("家族 · 山寨关系", "家族")),
    ("Save_Jia_Zu_Shi_Guan",     ("家族 · 世官", "家族")),
    ("Save_Jia_Zu_Shi_Guan/Jia_Zu_Data_Array", ("家族 · 世官数据", "家族")),
    ("Save_Jia_Zu_Shi_Guan/Qu_Yu_Code_Text_Map", ("家族 · 区域映射", "家族")),
    ("Save_Shi_Guan",            ("世官", "家族")),
    ("Save_Shi_Guan/King_Code_Text_Map", ("世官 · 国编号映射", "家族")),
    ("Save_Shi_Guan_Total",      ("世官 · 总计", "家族")),
    ("Gong_Qing_Controller/Gong_Lao_Bu_Map", ("公卿 · 功劳簿映射", "家族")),
    ("Jia_Zu_Zhai_Yuan_Manager/Jia_Zhai_Data", ("家族 · 家宅", "家族")),
    # 家族子表
    ("Jia_Zu_Controller/Jia_Zu_Map",         ("家族 · 明细", "家族")),
    ("Jia_Zu_Controller/Jia_Zu_Guan_Xi_Map", ("家族 · 关系", "家族")),
    ("Jia_Zu_Genealogy/Genealogy_Ren_Record_Array",
     ("族谱 · 人物记录", "家族")),
    # ---- 外交 ----
    ("Save_Wai_Jiao_Data",       ("外交 · 总表", "外交")),
    ("Save_Hui_Meng_Data",       ("会盟", "外交")),
    ("Save_Ming_Fen_Data",       ("名分", "外交")),
    ("Save_Rong_Di_Data",        ("戎狄", "外交")),
    ("Save_Rong_Di_Guan_Xi",     ("戎狄关系", "外交")),
    ("Save_Xiong_Nu_Data",       ("匈奴", "外交")),
    # ---- 军事 ----
    ("Army_Controller",          ("军队 · 总表", "军事")),
    ("Army_Controller/Army_Data_Array", ("军队 · 明细", "军事")),
    ("Bie_Bu_Manager",           ("别部", "军事")),
    ("Save_Zhan_Zheng_Data",     ("战争", "军事")),
    ("Save_Xin_Shou_Zhan_Lue",   ("新手战略", "军事")),
    ("Zhan_Lue_Controller",      ("战略", "军事")),
    # ---- 文化 ----
    ("Save_Ji_Shu_Data",         ("技术", "文化")),
    ("Save_Ji_Shu_Data/King_To_Era_Technology_Data_Array",
     ("技术 · 国至纪元", "文化")),
    ("Wen_Wu_Controller",        ("文物", "文化")),
    ("Wen_Wu_Controller/King_Wen_Wu_Data_Array", ("文物 · 各国文物", "文化")),
    ("Tai_Xue_Controller",       ("太学", "文化")),
    ("Si_Xue_Controller",        ("私学", "文化")),
    ("Qiu_Xue_Table_Manager",    ("求学", "文化")),
    ("Ru_Yu_Table_Manager",      ("入狱", "文化")),
    ("Shi_Yu_Controller",        ("谥语", "文化")),
    ("Shi_Yu_Controller/Zu_Yu_Shi_Yu",  ("谥语 · 族域", "文化")),
    ("Shi_Yu_Controller/King_Shi_Yu",   ("谥语 · 国", "文化")),
    ("Zu_Xun_Controller",        ("祖训", "文化")),
    ("Chen_Yan_Controller",      ("谶言", "文化")),
    # ★ 2026-09-22 纠错：原译「垂林」是错的。
    #   拼音 Chui_Lin = **垂临**；记录内容就是 `{Ren_Code, God_Code}` 配对 ——
    #   「某人物被尊奉为某神明」，即游戏的神明/神祖系统（人物垂临为神）。
    ("Chui_Lin_Controller",      ("神明 · 垂临", "文化")),
    ("Chui_Lin_Controller/Chui_Lin_Record_Manager", ("垂临记录", "文化")),
    ("Save_Shu_Ju_Chi_Data",     ("书籍", "文化")),
    ("Save_Sj_Ju_Qing_Data",     ("事件剧情", "文化")),
    ("Save_Sj_Ju_Qing_Wan_Cheng_Data", ("事件剧情 · 完成", "文化")),
    # ★ 2026-09-22 纠错：`Qi_Guan` = **奇观**（不是「旗关」）。
    #   证据：`King_Buff_Array` 里 kind=16（奇观）的记录同时带
    #   `Qi_Guan_Code` 与 `Map_Code` —— 「某奇观建在某城」；
    #   官方 WIKI《奇观系统介绍》共 19 个奇观（长城/稷下学宫/娲皇宫…）。
    ("Qi_Guan_Gong_Tai",         ("奇观 · 公台", "文化")),
    ("Gong_Guan_Table_Manager",  ("公馆", "文化")),
    ("Gong_Guan_Table_Manager/Gong_Guan_Data", ("公馆 · 数据", "文化")),
    # 书籍子表
    ("Save_Shu_Ju_Chi_Data/Sheng_Ren_Lin_Chao_Data_Array",
     ("书籍 · 圣人临朝", "文化")),
    ("Save_Shu_Ju_Chi_Data/Ren_Shai_Xuan",  ("书籍 · 人物筛选", "文化")),
    ("Save_Shu_Ju_Chi_Data/Year_Death_Ren", ("书籍 · 当年亡者", "文化")),
    ("Save_Shu_Ju_Chi_Data/World_Book",     ("书籍 · 天下书", "文化")),
    ("Save_Shu_Ju_Chi_Data/Yi_Xu_Data_Array", ("书籍 · 遗墟", "文化")),
    ("Save_Shu_Ju_Chi_Data/Card_Buff_Data_Array", ("书籍 · 卡牌增益", "文化")),
    ("Save_Shu_Ju_Chi_Data/Dang_Ju_Jing_Yan_Map", ("书籍 · 当局经验", "文化")),
    # ---- 其它 ----
    ("Game_Loop",                ("游戏主循环", "其它")),
    ("Game_Loop/Month_Content_List", ("主循环 · 每月内容", "其它")),
    ("Save_Task_Data",           ("任务", "其它")),
    ("Save_Task_Data/Task_Manager", ("任务 · 管理器", "其它")),
    ("Save_King_Did_Data",       ("国君行为", "其它")),
    ("Save_Res_Bank_Data",       ("资源库", "其它")),
    ("Save_Res_Bank_Data/All_Res_Bank_Array", ("资源库 · 明细", "其它")),
    ("Save_Res_Bank_Data/Empty_Res_Bank_Array", ("资源库 · 空缺", "其它")),
    ("Res_Allocation_Controller", ("资源分配", "其它")),
    ("Res_Allocation_Controller/Table_Array", ("资源分配 · 明细", "其它")),
    ("Business_Controller",      ("商业", "其它")),
    ("Business_Controller/Shang_Lu_Data_Arr", ("商业 · 商路", "其它")),
    ("Business_Controller/Market_Arr", ("商业 · 市场", "其它")),
    ("Business_Controller/Res_Avg_Value_Array", ("商业 · 资源均值", "其它")),
    ("Save_Controller_Data",     ("存档控制器", "其它")),
    ("Ever_King_Data",           ("永存国数据", "其它")),
    ("Save_Look_Jia_Zu",         ("家族视角", "其它")),
    ("Save_Sui_Ji_Wait",         ("随机等待", "其它")),
    ("Save_Sj_Ju_Qing_Data",     ("事件剧情", "其它")),
    ("Save_Wai_Jiao_Data/Zhi_Di_Data", ("外交 · 质子", "其它")),
    ("Shi_Zhuan_Controller",     ("世传", "其它")),
    ("Gong_Qing_Controller/Gong_Qing_King_Data", ("公卿 · 各国公卿", "其它")),
    ("Save_Look_King_Map",       ("国家 · 地图视角", "其它")),
    ("Save_Hui_Fang_Data/City_Change_Data_Array", ("回放 · 城池变更", "其它")),
    ("Save_Hui_Fang_Data/King_Name_Change_Data_Array",
     ("回放 · 国名变更", "其它")),
    ("Save_Hui_Fang_Data/Qi_Guan_Change_Data_Array", ("回放 · 奇观变更", "其它")),
])


# ---------------------------------------------------------------- 表族说明
# ★ 2026-09-22 存档考古：世界页里最让人看不懂的不是字段名，而是「这张表到底是
#   干什么的」。这里给**不显然**的表写一句用途说明，由世界页在悬停表名时显示。
#   一眼能看懂的（如「城池 · 总表」）不写，避免噪音。
FAMILY_NOTE = {
    # ---- 国家
    "Save_KingData": "一国一条：国名/爵位/正统/天命/军威/人口/存粮，以及全部子表。",
    "Zong_Miao_Controller": "各国宗庙（祖庙）。★ 君主世系**只认这里** —— 进了这家祖庙才算这家的人。",
    "Zong_Miao_Controller/All_King_Zong_Miao_Array": "各国宗庙主记录。★ 爵位看尊号 `Memorial_Ren_Zun_Hao`，庙里的 `Jue_Wei` 恒为 1，不可当爵位。",
    "Zong_Miao_Controller/All_Memorial_Array": "宗庙牌位 —— 列祖列宗。每条带生卒 / 受封时间 / 当今国名与国都。",
    # ★ 2026-09-29：`All_Miao_Array` 原缺说明。庙 = 宗庙内的**分级祭祀单位**
    #   （始祖庙 level 0、高祖庙…），`Miao_Theme` 是主题码。
    #   与「神系 / 造神」相关的字段说明见世界页工具栏「字段说明」。
    "Zong_Miao_Controller/All_Miao_Array": "全庙表 —— 宗庙内的分级祭祀单位（始祖庙 / 高祖庙…），带 `Miao_Level` 庙等级。",
    "Save_Wang_Chao_Data": "王朝本体：制度（中央集权制 / 宗法分封制）、阶段、德运，以及各项改革开关。",
    "Gong_Qing_Controller": "公卿功勋 / 过错簿 —— 功勋越高，罢免代价越大。",
    "Shi_Men_Controller": "世门（门第）—— 家族的门第高低。",
    "Shi_Zu_Controller": "世族登记。",
    "Ke_Guan_Table_Manager": "客馆（按城分）：在馆**游士**名单 —— 招贤纳士的池子。",
    "Men_She_Table_Manager": "门舍（按城分）：门客住处。门客数超过容量会有人逃跑。",
    "Xi_Zuo_Table_Manager": "★ **细作**（间谍）名册：从哪国派往哪国、是否私事。",
    "Ru_Yu_Table_Manager": "入狱者：罪名（典押质子 / 获罪卿室 / 捕获俘虏）+ 刑期（徒终身 / 徒三年）。",
    "Jian_Yu_Table_Manager": "监狱 · 建狱。",
    "Shan_Zhai_Tu_Lao_Manager": "山寨 · 徒众（本机 5 档皆空，用途待考）。",
    # ---- 城池
    "New_Save_Map_Data": "一城一条：等级 / 税率 / 开发度 / 主流文化 / 城防 / 驻军 / 附国。",
    "New_Save_Jin_Liu_Array": "进度流：城池发展进程队列。",
    # ---- 家族
    "Jia_Zu_Controller": "家族总表（宗室 / 卿室 / 公室）。",
    "Jia_Zu_Genealogy": "家族族谱 —— **游戏自己带的**，与我们可编辑的「谱牒层」不是一回事。",
    "Jia_Zu_Controller/Jia_Zu_Guan_Xi_Map": "家族两两之间的关系（同姓 / 姻亲）。",
    "Save_Jia_Zu_Shi_Guan": "家族世官 —— 某家族世袭某官。",
    # ---- 外交
    "Save_Wai_Jiao_Data": "两国一条：好感度(0~200) / 状态(中立·同盟·敌对) / 联姻 / 世仇 / 谍报进度。",
    "Save_Hui_Meng_Data": "会盟（多边盟约：睦邻友好 / 灾害互助 / 情报共享 / 文化认同…）。",
    "Save_Ming_Fen_Data": "名分 —— 天子 / 霸主用来治诸侯的凭据。",
    "Save_Rong_Di_Data": "戎狄部族。",
    # ---- 军事
    "Army_Controller": "军队总表（最多 6 支，单支上限 7.5 万）。",
    "Save_Zhan_Zheng_Data": "战争记录。",
    "Bie_Bu_Manager": "别部 —— 非正规编制的部众。",
    # ---- 文化
    "Save_Ji_Shu_Data": "技术 —— ★ **存档里的技术树就在这张表**（`Era_Map`：7 个时代 × 13 项）。",
    "Wen_Wu_Controller": "文物（挖掘 / 购买 / 夺取，可供奉在庙宇或城邑）。",
    "Tai_Xue_Controller": "太学（官学）。",
    "Si_Xue_Controller": "私学。",
    "Shi_Yu_Controller": "谥语 —— 给君主定谥号的词库（按国 / 族域分派）。",
    "Zu_Xun_Controller": "祖训。",
    "Chen_Yan_Controller": "谶言（预言）。",
    "Chui_Lin_Controller": "★ **神明 · 垂临**：哪些人（Ren_Code）被尊奉为哪些神（God_Code）。",
    "Save_Shu_Ju_Chi_Data": "书籍（含圣人之书 / 天下书 / 遗墟 / 卡牌增益）。",
    "Gong_Guan_Table_Manager": "公馆。",
    "Qi_Guan_Gong_Tai": "奇观 · 公台。",
    # ---- 其它
    "Ever_King_Data": "永存国数据 —— 跨局保留的国家档案。",
    "Shi_Zhuan_Controller": "★ **世传**：玩家势力自己的编年史 —— 城数 / 人口 / 军队 / 劳役**逐年**曲线。",
    "Save_Res_Bank_Data": "资源库（按所有者分：国 / 家族 / 山寨 / 戎狄）。",
    "Business_Controller": "商业（商路 / 市场 / 资源均价）。",
    "Save_Hui_Fang_Data": "回放纪事（城池变更 / 国名变更 / 奇观变更）。",
    "Save_Task_Data": "任务。",
    "Game_Loop": "游戏主循环。",
    "Save_Controller_Data": "存档控制器。",
    "Save_King_Did_Data": "国君行为记录。",
    "Save_Xin_Shou_Zhan_Lue": "新手战略（开局引导）。",
    "Zhan_Lue_Controller": "战略部署。",
}


def note_of_family(name: str) -> str:
    """表族用途说明（没有就回空串）。"""
    return FAMILY_NOTE.get(name, "")


def label_of_family(name: str) -> str:
    hit = FAMILIES.get(name)
    if hit:
        return hit[0]
    # 未登记的（版本更新后会冒出来）—— 用原名，并标明它还没被登记
    return f"{name}（未登记）"


def category_of_family(name: str) -> str:
    hit = FAMILIES.get(name)
    return hit[1] if hit else "其它"


# ---------------------------------------------------------------- 默认列
# 值 = [(字段名, 列宽, 是否右对齐)]；只列「一眼要看的」，其余进详情面板
COLUMNS = {
    "人物 · 合并总表": [("Ren_Code", 70, True), ("Ren_Name", 86, False),
                        ("Ren_Shi", 52, False), ("Ren_Xing", 52, False),
                        ("Ren_Ming", 52, False), ("Ren_Sex", 44, False),
                        ("_父名", 78, False), ("_母名", 78, False),
                        ("Ren_Dai_Shu", 52, True), ("Ren_Leve", 44, True),
                        ("Ren_Zhi_Lue", 52, True), ("Ren_Chu_Sheng_Time", 92, False),
                        ("Ren_Wen_Hua", 58, False), ("Ren_Xing_Ge", 48, False),
                        ("_来源表", 104, False)],
    "Save_Ren_Data": [("Ren_Code", 70, True), ("Ren_Name", 90, False),
                      ("Ren_Sex", 44, False), ("Ren_Leve", 60, True),
                      ("Ren_Zhi_Lue", 52, True), ("Ren_Chu_Sheng_Time", 110, False),
                      ("Ren_Wen_Hua", 60, False), ("Ren_Xing_Ge", 50, False),
                      ("Ren_Dai_Shu", 52, True), ("Ren_Shi_Li_1", 70, False),
                      ("Ren_Map_Name", 76, False)],
    "Save_Dead_Ren_Data": [("Ren_Code", 70, True), ("Ren_Name", 90, False),
                           ("Ren_Sex", 44, False), ("Ren_Chu_Sheng_Time", 110, False),
                           ("Ren_End_Time", 110, False), ("Ren_Old", 50, True),
                           ("Ren_Wen_Hua", 60, False), ("Ren_Xing_Ge", 50, False),
                           ("Ren_Dai_Shu", 52, True)],
    "Save_KingData": [("King_Code", 60, True), ("King_Name", 80, False),
                      ("King_Str", 110, False), ("King_Jue_Wei_Code", 66, True),
                      ("King_Bing_Li_Total", 76, True), ("King_Lao_Yi_Total", 76, True),
                      ("King_Tian_Ming", 66, True), ("King_Zheng_Tong", 66, True),
                      ("Guo_Xing", 60, False), ("Jian_Guo_Year", 76, True),
                      ("King_Last_Ren_Total", 68, True)],
    "New_Save_Map_Data": [("Map_Code", 60, True), ("Map_Name", 90, False),
                          ("Map_State", 70, False),
                          ("Map_Kai_Fa_Nong_Ye", 78, True),
                          ("Map_Kai_Fa_Jun_Shi", 78, True),
                          ("Map_Literacy_Rate", 72, True),
                          ("Map_Crime_Rate", 72, True),
                          ("Map_Wen_Hua_Main", 70, False),
                          ("Map_Zhi_Li", 76, False)],
    "Jia_Zu_Controller/Jia_Zu_Map": [("Code", 76, True), ("Jia_Shi", 70, False),
                                     ("Zu_Xing", 70, False), ("Jia_Zhu_Code", 76, True),
                                     ("Jia_Zu_Type", 64, False), ("Ben_Zhi", 60, False),
                                     ("Ju_Suo_Code", 68, True)],
    "Jia_Zu_Genealogy": [("Genealogy_Code", 86, True), ("Genealogy_Name", 100, False),
                         ("Ancestor_Code", 86, True),
                         ("Genealogy_First_Generations", 90, True),
                         ("Genealogy_Last_Generations", 90, True)],
    "Jia_Zu_Genealogy/Genealogy_Ren_Record_Array":
        [("Ren_Code", 76, True), ("Ren_Name", 96, False), ("Ren_Xing", 56, False),
         ("Ren_Shi", 56, False), ("Ren_Ming", 60, False), ("Born_Time", 100, False),
         ("Dead_Time", 100, False), ("Father_Name", 90, False),
         ("Mother_Name", 76, False), ("Generations", 60, True)],
    "Save_Wai_Jiao_Data": [("Wai_Jiao_Code_1", 78, True), ("Wai_Jiao_Code_2", 78, True),
                           ("Wai_Jiao_Guan_Xi", 76, True),
                           ("Wai_Jiao_Zhuang_Tai", 76, False),
                           ("Wai_Jiao_Lian_Yan", 66, True), ("Wai_Jiao_Shi_Chou", 66, True)],
    "Save_Shan_Qu_Data": [("Code", 66, True), ("Name", 120, False), ("Liu_Min_Num", 76, True)],
    "New_Save_Jin_Liu_Array": [("Code", 70, True), ("Name", 110, False),
                               ("Jin_Du_Type", 72, True), ("Start_Time", 110, False)],
    "Save_King_Death_Data": [("King_Code", 70, True), ("King_Name", 80, False),
                             ("Guo_Xing", 60, False), ("Guo_Shi", 60, False),
                             ("King_Leve", 60, True), ("Che_Di_Die_Time", 110, False)],
    "Save_Ming_Fen_Data": [("Code", 56, True), ("Name", 100, False),
                           ("Ming_Fen_Data", 84, True), ("Start_Time", 110, False),
                           ("Valid", 56, False), ("Used", 56, True)],
    "Save_Zhan_Zheng_Data": [("Zhan_Zheng_Code", 92, True), ("Zhan_Zheng_Type", 84, True),
                             ("Start_Time", 110, False), ("Zhan_Zheng_End", 76, False)],
    "Save_Wang_Chao_Data": [("Wang_Chao_Jie_Duan", 90, False),
                            ("Wang_Chao_Zhi_Du", 96, False),
                            ("Wang_Chao_De_Yun", 70, False),
                            ("Wang_Chao_Guan_Xue", 70, False),
                            ("Wang_Chao_Zhu_Dao_King", 96, False)],
    "Jia_Zu_Controller/Jia_Zu_Guan_Xi_Map":
        [("Jia_Zu_Code_1", 86, True), ("Jia_Zu_Code_2", 86, True),
         ("Guan_Xi", 70, False), ("Tong_Xing", 60, False), ("Yin_Qin", 60, False)],
    "Army_Controller/Army_Data_Array":
        [("Army_Code", 76, True), ("Jun_Dui_Name", 96, False),
         ("Army_Type", 70, False), ("Army_Status", 70, False),
         ("Jun_Dui_Ren_Min", 76, True), ("Jun_Dui_Shi_Qi", 76, True),
         ("Jun_Dui_Zhan_Li", 76, True), ("Jun_Dui_Ji_Lv", 76, True)],
    "Save_Res_Bank_Data/All_Res_Bank_Array":
        [("Res_Bank_Code", 84, True), ("Res_Code", 76, True),
         ("Res_Num", 76, True)],
}

# 通用兜底：取前 N 个字段
FALLBACK_COLS = 6
