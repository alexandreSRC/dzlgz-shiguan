# -*- coding: utf-8 -*-
"""中文字典 —— 让存档里的每一个字都是中国人一眼能读懂的。

三层结构
------------------------------------------------------------
1. `FIELD`      字段名（拼音）→ 中文名。覆盖存档里实测出现过的全部 1034 个字段。
2. `VALUE`      数字码 → 中文值。**只收有实证依据的**：
                · 要么游戏自己在别处就写着中文（如 `King_Wen_Hua` 的值域）
                · 要么能跟别的中文字段交叉验证（如 `Ren_Sex` 与「母亲」性别）
                 证据不足的一律**不猜** —— `code_of()` 会返回 `None`，
                 `decode()` 就把原值原样显示，并标注它是未解的数字码。
3. 值域枚举 `ENUM`  某些字段的取值是**固定小集合**且已在统计中实测到，
                直接把整张对照表写死（如 `King_Stage`、`Jia_Zu_Type`）。

设计原则：**宁缺勿猜，但绝不漏译字段名。**
字段名是从拼音直读的（`Ren_Zhi_Lue` = 智略），可控；值映射必须靠证据。
"""
import re

# ★ 2026-09-29：神系（`Faith_Gods_Sys_Code`）码表的**单一来源**在 `app/gods.py`
#   —— 那边连同神名、神明效果、庙宇容量公式、造神条件一起存着。
#   `gods` 不 import 本模块，故不会循环导入。
from .gods import GOD_SYS_BY_CODE

# ============================================================ 一、字段中文名
# 覆盖 _stats/leafnames.txt 里实测出现过的全部字段名。
FIELD = {
    # ---------------------------------------------------------- 通用
    "Code": "编号", "code": "编号", "ID": "编号", "id": "编号", "Id": "编号",
    "Unique_ID": "唯一编号", "Only_Code": "唯一编号", "Index": "序号",
    "Index_List": "序号表", "Key": "键", "key": "键", "Value": "值", "value": "值",
    "Name": "名称", "name": "名称", "Type": "类型", "type": "类型",
    "Level": "等级", "level": "等级", "state": "状态", "State": "状态",
    "Str": "文本", "Text": "文本", "Text_Array": "文本表", "Title": "标题",
    "Surname": "姓", "Num_Array": "数值表", "yx": "效果", "YX": "效果",
    "Yx_Set": "效果集合", "Res": "资源", "Res_Record": "资源流水",
    "Progress": "进度", "progress": "进度", "Month": "月份", "Index_List": "序号表",
    "Valid": "有效", "Used": "已用", "Is_Open": "是否开放", "Is_Empty": "是否为空",
    "Is_Pass": "是否通过", "Is_Finish": "是否完成", "Is_Sell": "是否出售",
    "Is_Visual": "是否可见", "Is_Pei_Du": "是否陪都", "Is_Abandon": "是否废弃",
    "Is_Gong_Zuo": "是否为工作", "Is_Wai_Jiao": "是否属外交",
    "Is_Zhan_Ling": "是否被占领", "Is_Si_Shi": "是否私事",
    "Show_Or_Hide": "显示或隐藏", "Color_Str": "颜色", "Text_Array": "文本表",
    "Time": "时间", "Time_Record": "时间记录", "Start_Time": "起始时间",
    "End_Time": "结束时间", "Last_Time": "上次时间", "Last_Use_Time": "上次使用时间",
    "Use_Time": "使用时间", "Use_Ci_Shu": "使用次数", "Used_Num": "已用数量",
    "Used_Time": "已用时间", "Total_Time": "总时长", "U_Time": "时间",
    "Data": "数据", "Work_Data": "工作数据", "Year_Death_Ren": "当年亡者",
    "Record_Text": "记录文字", "Record_Time": "记录时间", "Record_List": "记录表",
    "Number_Map": "数值映射", "String_Map": "文本映射", "String_Array": "文本表",
    "Obj_Array": "对象表", "Obj_Map": "对象映射", "Obj_King": "对象 · 国",
    "Obj_King_Data": "对象 · 国数据", "Obj_King_Name": "对象 · 国名",
    "Team_Type": "阵营", "Select_Type": "选取类型", "Pop_Type": "人口类型",
    "Zeng_Bi": "增减比", "Value_Base": "基准值", "Base_Code": "基准编号",
    "Add_Or_Remove": "增或删", "Allegiance_Data": "归附数据",
    "Allegiance_Code": "归附编号", "Allegiance_Type": "归附类型",

    # ---------------------------------------------------------- 人物
    "Ren_Code": "人物编号", "Ren_Name": "姓名", "Ren_Ming": "名",
    "Ren_Xing": "姓", "Ren_Shi": "氏", "Ren_Biao_Zi": "表字",
    "Ren_Zun_Hao": "尊号", "Zun_Hao": "尊号", "Zun_Hao_Obj": "尊号",
    "Ren_Sex": "性别", "Ren_Old": "年龄", "Ren_Temp_Age": "临时年龄",
    "Ren_End_Old": "享年", "Ren_Chu_Sheng_Time": "生年", "Ren_End_Time": "卒年",
    "Born_Time": "生年", "Dead_Time": "卒年", "Ren_Start_Time": "起始年",
    # ⚠️ 三个「世代」字段**语义完全不同**，2026-09-25 才彻底分清（此前混用过，
    #   小传因此把熊心写成「熊国第 80 代国君」）：
    #     `Generations`（宗庙牌位）    = **封国世代** —— 游戏算的「本封国第几代」，
    #                                    开国/受封者 = 1，−1 = 不属于本封国世代。
    #                                    项目把它抽成 family.json 的 `fief_gen`。
    #     `Ren_Generations`（宗庙牌位） = **宗庙连续编号** —— 游戏列表里的序号，
    #                                    占位祖先也占号（熊心 = 80），**没有谱系含义**。
    #     `Ren_Dai_Shu`（人物记录）     = **族谱世代** —— 自族谱始祖起算的第几代
    #                                    （嬴政 = 71），−1 = 始祖。详情卡显示的就是它。
    #   ⚠️ `Generations` 在**族谱表**（Jia_Zu_Genealogy）里又是「族谱世代」的意思 ——
    #      同名不同意，见 `record_derive.GENEALOGY_RENAME`。
    "Ren_Ji_Wei_Time": "继位时间", "Ren_Dai_Shu": "世代", "Generations": "世代",
    "Ren_Generations": "世代", "Ren_Leve": "人物等级", "Ren_Level": "人物等级",
    "Ren_Zhi_Lue": "智略", "Ren_Wen_Hua": "文化", "Ren_Xing_Ge": "性格",
    "Ren_Zu_Yu": "族域", "Ren_Sys_Is": "系属", "Class_Type": "类别",
    "Ren_Shi_Li_1": "势力", "Ren_Shi_Li": "势力", "Ren_Cheng_Shi_Code": "所在城邑",
    "Ren_Map_Name": "所在地", "Ren_Map": "所在城池", "Ren_Guo_Code": "所属国",
    "Ren_Guo_Cuo": "所属国（误）", "Ren_In_King": "所属君主", "Ren_King": "所属君主",
    "Ren_In_Map_Position": "城中身份", "Ren_Face": "容貌", "Ren_Sheng_Hai_Zi": "生育子女",
    "Ren_Pei_Ou_Code_Array": "配偶", "Ren_Zi_Nv_Code_Array": "子女",
    "Ren_Code_Array": "人物编号表", "Ren_Cong_Zheng_Jing_Yan": "从政经验",
    "Ren_Zheng_Ce_Array": "政策", "Ren_Neng_Li_Array": "能力", "Neng_Li_Array": "能力表",
    "Neng_Li_Data": "能力数据", "Ren_Gong_Xun": "功勋", "Gong_Xun": "功勋",
    "Ren_Task_Ing": "进行中任务", "Ren_Ci_Hun": "赐婚", "Ren_Shai_Xuan": "人物筛选",
    "Ren_Kou_Zeng_Zhang_Lv": "人口增长率", "Guan_Chen": "官臣", "Bu_Man": "不满",
    "Ji_Wei_Shen_Fen": "继位身份", "Jing_Li": "精力", "Jing_Li_Data": "经历数据",
    "Zhi_Liao_Ing": "治疗中", "You_Yi_Data": "就医数据", "You_Yi_Type": "就医类型",
    "Cong_Zheng_Data": "从政数据", "Last_Ren_Official_Position_Data": "最后官职",
    "Zhi_Wei_Code": "职位编号", "Shi_Hao": "谥号", "Former_Jia_Zhu": "前家主",
    "Used_Card_Map": "已用卡牌", "Play_Card_Array": "玩法卡牌", "Card_Buff_Array": "卡牌增益",
    "Card_Buff_Data_Array": "卡牌增益数据", "Debuff_Set": "减益集合",
    "Buff_Array": "增益列表", "Buff_Code": "增益编号", "Buff_Name": "增益名称",
    "Buff_Data": "增益数据", "Buff_Start_Time": "增益开始时间",
    "Buff_End_Time": "增益结束时间", "Buff_Ren_Code": "增益人物编号",
    "Buff_Need_Save_Effect_YX": "增益需存档效果", "Zi_Jian_Buff_Array": "自建增益",
    "Zi_Jian_Guan_Lian_Data": "自建关联数据", "He_Ren_Zu_Yu": "融合族域",

    # ---------------------------------------------------------- 国家
    "King_Code": "国编号", "King_Name": "国名", "King_Str": "国世系",
    "King_Colore": "国色", "King_Guo_Du_Code": "国都编号", "King_Jue_Wei_Code": "爵位",
    "King_Stage": "发展阶段", "King_Stage_Record": "阶段记录",
    "Is_King_Stage_Jin_Jie": "阶段是否晋升", "Guo_Xing": "国姓", "Guo_Shi": "国氏",
    "Zhou_Name": "州名", "Zu_Yu": "族域", "Nian_Hao": "年号", "Jian_Guo_Year": "建国年",
    "King_Tian_Ming": "天命", "Tian_Ming_Value": "天命值", "King_Zheng_Tong": "正统",
    "King_Wei_Wang": "威望", "King_Jun_Wei": "军威", "King_Wen_Ding": "问鼎",
    "King_Kuan_Xiang": "库项", "King_Xian_Neng_Total": "贤能总数",
    "King_Last_Ren_Total": "人口总数", "King_Last_Ren_Code": "末代国君",
    "King_Last_Liang": "存粮", "King_Bing_Li_Total": "兵力总数",
    "King_Lao_Yi_Total": "劳役总数", "King_Shui_Lu": "税率",
    "King_Money_Shui_Lu": "钱税", "King_Lao_Yi_Lu": "劳役率",
    "King_Zheng_Bing_Lu": "征兵率", "King_Yi_Yong_Lao_Yi": "已用劳役",
    "King_Me_Ke_Max": "门客上限", "King_Liang_Shi_Add": "粮食加成",
    "King_Kill_Old": "弑君数", "King_Du_Li": "都鄙", "King_Quan_Bing": "权柄",
    "King_Chu_Jun": "出军", "King_Ren": "国人", "King_Ren_Wang_Base": "国人王基",
    "King_Is_Na_Gong": "是否纳贡", "King_Last_Fa_Zhan_Total": "发展总值",
    "King_Last_Jun_Wei_Total": "军威总值", "King_Last_Tian_Ming_Total": "天命总值",
    "King_Last_Wen_Ding_Total": "问鼎总值", "King_Last_Zheng_Tong_Total": "正统总值",
    "Dou_Zheng_Xing": "斗政星", "Xiang_Rui_Chu_Fa": "祥瑞触发", "Good_Xiang_Rui": "吉兆",
    "Guan_Xing_Time": "观星时间", "Guo_Ren_Xian_Yu_Time": "国人现役时间",
    "Li_Fa_Accuracy": "历法精度", "Shi_Ling_Ren_Kou_Bi_Li": "适龄人口比例",
    "Shi_Ling_Ren_Kou_Bi_Li_Zong_Jie_Value": "适龄人口比例总结值",
    "Gong_Lue_Fang_Xiang": "攻略方向", "Qing_Shi_Liao_Name": "卿士寮名",
    "Is_Ji_Si_Tong_Zhi": "是否祭祀统治", "Ji_Si_Gods": "祭祀神祇",
    "Is_Ever_Jian_Hao": "是否曾经称号", "Chi_You_King": "蚩尤之国",
    "King_Level": "国等级", "King_Leve": "国等级", "King_Index": "国序号",
    "King_Wen_Hua_Array": "国文化表", "King_Wen_Hua_Buff_Array": "国文化增益",
    "King_Buff_Array": "国增益", "King_Zheng_Ing_Array": "国政进行中",
    "King_Zhan_Ling_Map_Array": "国占领地图", "King_Map_Array": "国地图表",
    "King_Array": "国列表", "King_Data": "国数据", "King_data": "国数据",
    "King_Parent_Array": "国父辈表", "King_Child_Array": "国子辈表",
    "King_Code_Array": "国编号表", "King_Code_Text_Map": "国编号文字映射",
    "Kingdom_Code": "国编号", "King_Shai_Xuan": "国家筛选", "King_Center_Pos": "国中心位置",
    "King_Suo_Gong_Time": "国索贡时间", "King_Evaluate_Data_Array": "国评价数据",
    "Now_King_Evaluate": "当今国评价", "King_Is_Huan_Di": "是否称帝",
    "King_Ai_Data": "国爱数据", "Ai_Zhu_Fang_Zhen": "爱主方针",
    "King_Xian_Neng": "贤能", "King_Cun_Xu": "国存续", "King_Quan_Bing_Max": "权柄上限",
    "Wen_Hua": "文化", "Shu_Wen_Hua": "所属文化", "Wen_Hua_Code": "文化编号",
    "Main_Wen_Hua": "主流文化", "Guo_Zu_Wen_Hua_Data": "国族文化数据",
    "Di_Kuai_Array": "地块表", "Di_Ku_Service": "地库", "Di_Yao_Service": "地祇",
    "Gui_Zu_Dai_Yu_Map": "贵族待遇映射", "Shi_Zheng_Ji_Lei_Array": "施政积累表",
    "Sheng_Zheng_Zhong_Xin": "省政中心", "Shou_Ming": "寿命", "Juan_Gu": "捐谷",
    "Liang_Shi_Chan_Liang": "粮食产量", "Guo_Jun_Sheng_Zi_Lv": "国君生子率",
    "Zhu_Liu_Wen_Hua_Chuan_Bo_Su_Du": "主流文化传播速度",
    "Zheng_Ba_Sheng_Ren_Code_Array": "争霸圣人编号表",
    "Jia_Zu_Quan_Ju_Tong_Zhi_Ji_Lu": "家族全局统治记录",
    "Quan_Ju_Tong_Zhi_Ji_Lu": "全局统治记录", "Jiu_Zhou_Tong_Zhi_Ji_Lu": "九州统治记录",
    "Ge_Ju_Record_Parent_King_Name": "割据记录 · 母国名",
    "Last_Guo_Du_Bei_Zhan_Time": "上次国都被占时间",
    "Last_Di_Fang_Pan_Luan": "上次地方叛乱", "Last_King_Ren_Kill_Time": "上次弑君时间",
    "Last_Zhan_Ling_King_Array": "上次占领国表", "Last_Ji_Xian_Array": "上次祭天表",
    "Xiong_Di_Zhu_She_Time": "兄弟煮社时间", "Zheng_Zhao_Fan_Wei": "征召范围",
    "Pei_Du_Jin_Jun_Max_Num": "陪都禁军上限", "Tan_Suo_Huang_Fei_City_Set": "探索荒废城集合",
    "Tian_Xiang_Ji_Lu": "天象记录", "Bei_Shi_Yong_Tian_Xiang_Ji_Lu": "被使用天象记录",
    "Finish_Zhan_Lue_Array": "已完成战略表", "Zhan_Zheng_Array": "战争表",
    "Zheng_Ce_Shu_Array": "政策书表", "Order_Obj": "命令", "Sell_Order_Arr": "出售命令表",
    "Play_Ge_Ju_Name": "割据名称", "Play_Ge_Ju_Di_Li": "割据地理",
    "Play_King_Start_Di_Li": "君主起始地理", "Play_Fu_Yong_Num_Change_Map": "赋用数变化",
    "Play_Have_Gong_Qing": "拥有公卿", "Play_Jun_Ren_Total_Change_Map": "军民总数变化",
    "Play_King_First_Sheng_Ren": "君主首位圣人", "Play_King_Ren_Level": "君主人物等级",
    "Play_Change_King_Map": "变更君主映射", "Play_Map_Num_Change_Map": "城数变化",
    "Play_Ren_Cai_Num_Change_Map": "人才数变化", "Play_Ren_Total_Change_Map": "人口总数变化",
    "All_King_Guo_Li_Change_Map": "全国国力变化",
    "Play_Zong_Shi_Ren_Num_Change_Map": "宗室人数变化",

    # ---------------------------------------------------------- 王朝
    "Wang_Chao_Code": "王朝编号", "Wang_Chao_Jie_Duan": "王朝阶段",
    "Wang_Chao_Zhi_Du": "王朝制度", "Wang_Chao_De_Yun": "王朝德运",
    "Wang_Chao_Guan_Xue": "王朝官学", "Wang_Chao_Xing_Dian": "王朝刑典",
    "Wang_Chao_Cheng_Yuan": "王朝成员", "Wang_Chao_Zhu_Dao_King": "王朝主导国",
    "Cur_Officical_System": "当前官制", "Official_System_Mgr_Obj": "官制管理",
    "Official_System_State_Map": "官制状态映射", "Officical_System_Array": "官制表",
    "Official_Position_Array": "官职表", "Guan_Zhi_Map": "官职映射",
    "Yun_Xu_Can_Zheng": "允许参政", "Yun_Xu_Geng_Gai_Zhu_Liu_Wen_Hua": "允许更改主流文化",
    "Yun_Xu_Jian_She_Cheng_Fang": "允许建设城防", "Yun_Xu_Xuan_Zhan": "允许宣战",
    "Yun_Xu_Xuan_Zhan_Gong_Qing": "允许宣战公卿", "Yun_Xu_Xuan_Zhan_Mu_Guo": "允许宣战母国",
    "Fen_Feng_Ing_King_Name_Array": "分封中国名表",
    "Is_Open_Bian_Hu_Qi_Min": "开放编户齐民", "Is_Open_Fei_Guo_She_Jun": "开放费国设军",
    "Is_Open_Gai_Hao_Cheng_Di": "开放改号称帝", "Is_Open_He_Tong_Yi_Xia": "开放合同一夏",
    "Is_Open_Ming_Fa_Shen_Ling": "开放明法申令", "Is_Open_San_Shi_Shou_Jue": "开放三世授爵",
    "Is_Open_Xuan_Xian_Yong_Neng": "开放选贤用能", "Is_Open_Zhong_Jian_Zhu_Hou": "开放重建议侯",
    "Jian_Zheng_Time": "建政时间", "Zhi_Zheng_Jia_Zu": "执政家族",

    # ---------------------------------------------------------- 城池
    "Map_Code": "城编号", "Map_Name": "城名", "Map_King_Code": "所属国",
    "Map_State": "城池状态", "Map_Level": "城池等级", "Map_Zhi_Li": "施政方向",
    "Map_Zhi_Du_Map": "城池制度", "Map_Kai_Fa_Nong_Ye": "农业开发度",
    "Map_Kai_Fa_Jun_Shi": "军事开发度", "Map_Literacy_Rate": "识字率",
    "Map_Crime_Rate": "犯罪率", "Map_Nong_Ye_Shui_Lu": "农业税率",
    "Map_Money_Shui_Lu": "钱税税率", "Map_Jun_Shi_Shui_Lu": "军事税率",
    "Map_Lao_Yi_Lu": "劳役率", "Map_Wen_Hua_Total": "文化总值",
    "Map_Wen_Hua_Main": "主流文化", "Map_Wen_Hua_Array": "文化表",
    "Map_Kang_Zai": "抗灾", "Kang_Zai": "抗灾", "Kang_Zai_Qian_Bi": "抗灾前比",
    "Kai_Fa_Nong_Ye": "农业开发", "Kai_Fa_Nong_Ye_Qian_Bi": "农业开发前比",
    "Kai_Fa_Jun_Shi": "军事开发", "Kai_Fa_Jun_Shi_Qian_Bi": "军事开发前比",
    "Cheng_Fang_Jun_Zhan_Li": "城防军战力", "Cheng_Fang_Jun_Shi_Qi": "城防军士气",
    "Cheng_Fang_Auto": "城防自动", "Cheng_Fang_Lost_Level": "城防损失等级",
    "War_Kill_Ren_Total": "战争击杀总数", "Map_Ren_Liu_Ru": "人口流入",
    "Map_Ren_Liu_Chu": "人口流出", "Old_Map_Ren_Liu_Ru": "原人口流入",
    "Old_Map_Ren_Liu_Chu": "原人口流出", "Map_Last_Liang_Shou": "上次粮食收成",
    "Map_Array": "城池表", "Map_Data": "城池数据", "Map_Start": "起点城池",
    "Map_End": "终点城池", "Map_Tag": "城池标记", "Tag_Type": "标记类型",
    "Tag_Zeng_Bi": "标记增减比", "Map_Buff_Array": "城池增益",
    "Map_Diu_Shi_Array": "城池丢失表", "Map_Zhan_Ling_Data": "城池占领数据",
    "Zhan_Ling_Data": "占领数据", "Zhan_Ling_King": "占领国",
    "Zhan_Ling_Time": "占领时间", "Zhan_Ling_Data_Array": "占领数据表",
    "Map_Ding_Wei": "城池定位", "Map_Bing_Yi_Off": "兵役关闭",
    "Map_Shu_Lu_Off": "署理关闭", "Map_Pan_Luan": "城池叛乱",
    "Map_Du_Li_Xing": "都鄙形制", "Map_Du_Li_Xing_Zeng_Fu": "都鄙形制增幅",
    "Map_Yan_Zhan": "城池延展", "Map_Fu_Guo_Data": "附国数据",
    "Map_Fu_Guo_Time": "附国时间", "Fu_Guo_Sheng_Yu": "附国生育",
    "Yuan_Shi_Fu_Guo_Sheng_Yu": "原始附国生育", "Map_Jie_Ceng_Obj": "城池阶层",
    "Jie_Ceng_Map": "阶层映射", "Map_Jun_Dui_Array": "城池军队表",
    "Map_Cheng_Fang_Array": "城池城防表", "Map_Build_Data": "城池建筑数据",
    "Map_Zhou": "所属州", "Map_Jun": "所属郡",
    "Huang_Ye_Type": "荒地类型", "Feng_Suo_Off": "封锁关闭",
    "Liang_Cang_Level": "粮仓等级", "Qi_Guan_Build": "旗关建筑",
    "War_Type": "战争类型", "War_Time": "战争时间", "War_End_Time": "战争结束时间",
    "War_Creat_Time": "战争发起时间", "War_Win_1": "战胜方甲",
    "War_Win_2": "战胜方乙", "Zhan_Zheng_Code": "战争编号",
    "Zhan_Zheng_Type": "战争类型", "Zhan_Zheng_End": "战争结局",
    "Zhan_Zheng_Time": "战争时间", "Zhan_Zheng_Gong_Team": "战争攻方",
    "Zhan_Zheng_Shou_Team": "战争守方", "Zhan_Zheng_Ji_Lu": "战争记录",
    "Zhan_Zheng_Ji_Lu_Dead": "战争阵亡记录", "Zhan_Zheng_Min_Fen": "战争名分",
    "Zhan_Zheng_Data": "战争数据", "Zhan_Zhan_Ji_Lu": "战争记录",
    "Guo_Wei_Change_Num": "国威变化数", "Jian_Di_Num": "歼敌数",
    "Li_Gong_Change_Num": "立功变化数", "Liang_Change_Num": "粮草变化数",
    "Loss_Map_Num": "失城数", "Ren_Change_Num": "人口变化数",
    "Sheng_Li_Num": "胜利数", "Shi_Bai_Num": "失败数", "Si_Shang_Num": "死伤数",
    "Sheng_Fu": "胜/负", "Start_King": "起始国", "Start_King_Code": "起始国编号",
    "Start_King_Name": "起始国名", "Gong_King_Name": "攻方国名",
    "Shou_King_Name": "守方国名", "Gong_Obj_All_Dead": "攻方全灭",
    "Shou_Obj_All_Dead": "守方全灭", "Gong_Obj_Cheng_Fa": "攻方惩罚",
    "Shou_Obj_Cheng_Fa": "守方惩罚", "Gong_Jun_Dui_Array": "攻方军队表",
    "Shou_Jun_Dui_Array": "守方军队表", "Gong_Jiang_Ling_Death_Num": "攻方将领阵亡数",
    "Shou_Jiang_Ling_Death_Num": "守方将领阵亡数", "Wang_End": "亡国结局",
    "Ling_Di_Array": "领地表", "Xuan_Zhan_Time": "宣战时间",
    "Zuo_Zhan_Type": "作战类型", "Chong_Xing_Time": "重新兴起时间",
    "Chao_Hui_Time": "朝会时间", "From_Hui_Meng_Code": "来自会盟编号",

    # ---------------------------------------------------------- 建筑
    "Build_Map": "建筑映射", "Upgrading_Build_Array": "升级中建筑表",
    "Bing_She_Build_Map": "兵舍建筑", "Farmland_Build_Map": "农田建筑",
    "Fortress_Build_Map": "要塞建筑", "Nature_Res_Build_Map": "自然资源建筑",
    "Nest_City_Build_Map": "巢城建筑", "Pasture_Build_Map": "牧场建筑",
    "Prison_Build_Map": "监狱建筑", "School_Build_Map": "学校建筑",
    "Nature_Res_Point_Map": "自然资源点", "Auto_Build_List": "自动建筑表",
    "King_Build_Plan": "国君建筑计划", "King_Build_Plan_Table": "建筑计划表",
    "Plan_Code": "计划编号", "Plan_Map": "计划地图",
    "Create_Build_Index": "创造建筑序号", "Demeonstration_Static_Code": "示范静态编号",
    "Put_Demonstration_Code": "建筑示范编号", "Bing_She_Lost_Percent": "兵舍损失比例",
    "Nong_Tian_Lost_Percent": "农田损失比例", "Shui_Li_Lost_Percent": "水利损失比例",
    "Gong_Liang_Lost_Percent": "公粮损失比例", "Si_Liang_Lost_Percent": "私粮损失比例",
    "Liang_Lost_Percent": "粮食损失比例", "Ren_Lost_Percent": "人口损失比例",
    "Jian_Zu_Lost_Level": "建筑损失等级", "Zai_Hai_De_Li": "灾害力度",
    "Zai_Hai_Type": "灾害类型", "Zai_Hai_Data": "灾害数据",
    "Zai_Hai_Array": "灾害表", "Recent_Zai_Hai_Array": "近期灾害表",
    "Zai_Hai_Time": "灾害时间", "Zai_Hai_End": "灾害结束",
    "Zai_Hai_Time_Len": "灾害持续时长", "Zai_Hai_Leve": "灾害等级",
    "Zai_Hai_Map": "灾害城池", "Zai_Hai_Ren": "灾害人数",
    "Zai_Hai_Ren_Min": "灾害人数下限", "Zai_Hai_Ren_Max": "灾害人数上限",
    "Zai_Hai_Laing": "灾害粮损", "Zai_Hai_Laing_Min": "灾害粮损下限",
    "Zai_Hai_Laing_Max": "灾害粮损上限", "Zai_Hai_To_Zai_Hai": "灾害引发灾害",
    "Zai_Hai_To_Zai_Hai_Li": "灾害引发灾害率", "Zai_Hai_Value": "灾害值",
    "Zai_Hai_Pin_Lv": "灾害频率", "Jiu_Zai_Ren": "救灾人",
    "Jiu_Zai_Type_Array": "救灾类型表", "Is_Happen": "是否发生",
    "Map_Build_Data": "城池建筑数据", "Last_Year_Output_Value": "去年产出值",
    "Ji_Jiu": "积贮", "Xue_Gong": "学宫", "Wei_Cheng_Open": "围城开放",
    "Tai_Du": "台度", "Yu_Bei_Yi": "预备役",

    # ---------------------------------------------------------- 家族
    "Jia_Zu_Code": "家族编号", "Jia_Zu_Code_1": "家族编号甲",
    "Jia_Zu_Code_2": "家族编号乙", "Jia_Shi": "家氏", "Zu_Xing": "族姓",
    "Ju_Suo_Code": "居所编号", "Jia_Zhu_Code": "家主编号", "Ben_Jia_Code": "本家编号",
    "Jia_Zu_Type": "家族类型", "Jia_Zu_Kuan_Xiang": "家族库项",
    "Jia_Zu_Jue_Wei_Data": "家族爵位数据", "Jia_Zu_Jue_Wei": "家族爵位",
    "Ren_Shu_Shi_Jue_Wei_Data": "人属氏爵位数据",
    "Ren_Normal_Jue_Wei_Map": "常人爵位映射", "Ren_Foreign_Jue_Wei_Map": "外族爵位映射",
    "Ren_Abnormal_Jue_Wei_Map": "异常爵位映射", "Ren_Jue_Wei_Map": "人物爵位映射",
    "Ren_Ke_Data": "客卿数据", "Shu_Yuan_Data": "属员数据",
    "Liu_Fang_Jia_Zhu_Array": "流放家主表", "Liu_Fang_Ke_Xiang_Ren_Array": "流放客卿人表",
    "Liu_Fang_Zi_Si_Array": "流放子嗣表", "Qu_Zhu_Array": "驱逐表",
    "Wei_Xiang_Ren_Array": "位象人表", "Wai_Jia_Data": "外家数据",
    "Cheng_Yuan_Array": "成员表", "Jia_Zu_Array": "家族表",
    "Jia_Zu_Data_Array": "家族数据表", "Jia_Zu_Map": "家族映射",
    "Jia_Zu_Standing_Order_Array": "家族排序表", "Standing_Order_Array": "排序表",
    "Jia_Zu_Guan_Xi_Map": "家族关系映射", "Jia_Zu_Hun_Yue_Data": "家族婚约数据",
    "Jia_Zu_Dui_Wu_Data": "家族队伍数据", "Dui_Wu_Code": "队伍编号",
    "Tong_Xing": "同姓", "Yin_Qin": "姻亲", "Ben_Zhi": "本支",
    "Zhong_Cheng_Du": "忠诚度", "Zhi_Jia_Array": "支家表", "Si_Zi": "嗣子",
    "Gong_Qing_King_Data": "公卿国数据", "Gong_Qing_Values": "公卿值",
    "Gong_Qing_Gong_Lao_Bu_Manager": "公卿功劳簿", "Gong_Lao_Bu_Map": "功劳簿映射",
    "Jia_Zu_Shi_Yu": "家族世语", "Jia_Zu_Zhai_Yuan_Manager": "家族宅院",
    "Jia_Zhai_Data": "家宅数据", "Jia_Zu_Tu_Di_Map": "家族土地映射",
    "Land_Allocation": "土地分配", "Nobles_Land": "贵族土地",
    "People_Land_Map": "平民土地映射", "land": "土地",
    "Jia_Zhu": "家主", "Jia_Zu_Zong_Miao_Index": "家族宗庙序号",
    "Jia_Zu_Standing_Order": "家族排序", "Jia_Zu": "家族",
    "Last_Shui_Lv_Change_Time": "上次税率变更时间",
    "Jia_Zu_Quan_Ju_Tong_Zhi_Ji_Lu": "家族全局统治记录",
    "Is_Ti_Shi_Yu_Li_Wei_Zhi": "是否提示语立位次",

    # ---------------------------------------------------------- 族谱
    "Genealogy_Code": "族谱编号", "Genealogy_Name": "族谱名称",
    "Ancestor_Code": "始祖编号", "Genealogy_First_Generations": "首世代",
    "Genealogy_Last_Generations": "末世代", "Current_Genealogy_Formers": "当世族谱先人",
    "Genealogy_Ren_Record_Array": "族谱人物记录表", "Set_Ancestor_Miao_Year": "设始祖庙年",
    "Miao_Level": "庙等级", "Miao_Name": "庙名", "Miao_Theme": "庙主题",
    "Father": "父", "Mother": "母", "Father_Code": "父编号", "Father_Name": "父名",
    "Mother_Code": "母编号", "Mother_Name": "母名", "Mu_Guo": "母国",
    "Parent": "父母", "Memorial_Ren_Sex": "祭祀性别",

    # ---------------------------------------------------------- 宗庙 / 祭祀
    "Zong_Miao_Code": "宗庙编号", "Zong_Miao_Name": "宗庙名",
    "All_King_Zong_Miao_Array": "全国宗庙表", "All_Miao_Array": "全庙表",
    "All_King_Memorial_Array": "全国祭祀表", "All_Memorial_Array": "全祭祀表",
    "Memorial_Code": "祭祀编号", "Memorial_Name": "祭祀名",
    "Memorial_Name_Cache": "祭祀名缓存", "Memorial_Type": "祭祀类型",
    "Memorial_Ren_Type": "祭祀人物类型", "Memorial_Ren_Ming": "祭祀人名",
    "Memorial_Ren_Zun_Hao": "祭祀人尊号", "Memorial_Ren_Born_Time": "祭祀人生年",
    "Memorial_Ren_Dead_Time": "祭祀人卒年", "Memorial_Ren_Become_Time": "祭祀人受封时间",
    "Memorial_Ren_Now_King_Code": "祭祀人当今国编号",
    "Memorial_Ren_Now_King_Name": "祭祀人当今国名",
    "Memorial_Ren_Now_King_Du_Cheng_Name": "祭祀人当今国都名",
    "Memorial_Ren_Now_King_Level": "祭祀人当今国等级",
    "Memorial_Ren_Jue_Wei_New": "祭祀人新爵位", "Zu_Ling_Data": "祖灵数据",
    "Ji_Si_Type": "祭祀类型", "Zu_Yu_Shi_Yu": "族域世语",
    "King_Shi_Yu": "国世语", "Used_Zu_Yu_Zun_Hao_Map": "已用族域尊号映射",
    "Ji_Si_Neng_Li_Num": "祭祀能力数", "Gods_Arr": "神祇表",
    "Gods_Base_Data": "神祇基础数据", "Gods_Code": "神祇编号",
    "Gods_Sys_Arr": "神祇系统表", "Gods_Sys_Code": "神祇系统编号",
    "Gods_Pos_Arr": "神祇位置表", "Gods_Pos_Limit": "神祇位置上限",
    "Faith_Gods_Sys_Code": "信仰神祇系统编号", "God_Code": "神祇编号",
    "E_Huang_Zhi_Li_Service": "娥皇之力",
    "Nv_Ying_Zhi_Pin_Service": "女英之聘", "Nv_Wa_Zao_Ren_Service": "女娲造人",
    "Shao_Hao_Service": "少昊", "Yan_Di_Service": "炎帝",
    "Chong_Hua_Service": "重华", "Qiong_Yi_Service": "穷羿", "Jie_Yi_Service": "解衣",
    "Jie_Yi_Map": "解衣映射",

    # ---------------------------------------------------------- 外交
    "Wai_Jiao_Code_1": "甲方国编号", "Wai_Jiao_Code_2": "乙方国编号",
    "Wai_Jiao_Guan_Xi": "外交关系", "Wai_Jiao_Zhuang_Tai": "外交状态",
    "Wai_Jiao_Lian_Yan": "联姻", "Wai_Jiao_Shi_Chou": "世仇",
    "Wai_Jiao_Xiu_Zhan": "休战", "Wai_Jiao_Gong_Pin": "贡品",
    "Wai_Jiao_Jiao_Wu": "交恶", "Wai_Jiao_Zong_Fu": "宗祔",
    "Wai_Jiao_Chong_Tu": "外交冲突", "Wai_Jiao_Chu_Shi_1": "外交出事甲",
    "Wai_Jiao_Chu_Shi_2": "外交出事乙", "Wai_Jiao_Die_Bao_Jin_Du_1": "外交谍报进度甲",
    "Wai_Jiao_Die_Bao_Jin_Du_2": "外交谍报进度乙", "Wai_Jiao_Fu_Yuan_Time": "外交复原时间",
    "Wai_Jiao_Qiu_Xue_Time": "外交求学时间", "Wai_Jiao_Qui_Xue_1": "外交求学甲",
    "Wai_Jiao_Record_List": "外交记录表", "Wai_Jiao_Ing": "外交进行中",
    "Zhi_Di_Data": "质子数据", "Sui_Gong_Data": "岁贡数据",
    "Wai_Suo_Gong_Type": "索贡类型", "Suo_Gong_Nei_Rong": "索贡内容",
    "Shou_La_Long": "收拉拢", "Shou_Tiao_Bo": "收挑拨",
    "Hui_Meng_Map": "会盟映射", "Hui_Meng_Qi_Xian": "会盟期限",
    "Hui_Meng_Start_Time": "会盟开始时间", "Hui_Meng_Zhu_King": "会盟主国",
    "Hui_Meng_Zhuang_Tai": "会盟状态", "Hui_Meng_Data": "会盟数据",
    "Hui_Meng_Feedback_Array": "会盟反馈表", "Tiao_Jian_Array": "条件表",
    "Tong_Yi_Or_Not": "同意或否", "Jian_Tu_Hui_Meng_Save": "建土会盟存档",
    "Xu_Zhou_Hui_Meng_Save": "徐州会盟存档", "Last_Pan_Duan_Quan_Jin": "上次判断权柄",
    "Ming_Fen_Data": "名分数据", "Ming_Fen_Name": "名分名称",
    "Ming_Fen_Origin_King": "名分起源国", "Dang_Shi_King_Array": "当时国表",
    "Dang_Ju_Cheng_Jiu_Array": "当局成就表", "Dang_Ju_Jing_Yan_Map": "当局经验映射",
    "Dang_Ju_Shi_Zhuan": "当局世传", "Qi_Yue_Array": "契约表",
    "Ji_Fen": "积分", "Allegiance_Data": "归附数据",
    "Chi_Xu_Time": "持续时长", "Is_Sheng_Xiao": "是否生效",
    "Shou_Zi_Data": "收子数据", "Wei_Zi_Data": "为子数据",
    "Jun_Wei_Zeng_Fu": "军威增幅", "Shi_Qi_Zeng_Fu": "士气增幅",
    "Zheng_Ce_Cheng_Gong_Lu": "政策成功率", "Zheng_Ce_Data": "政策数据",
    "Zheng_Ce_Data_Array": "政策数据表", "Zheng_Ce_Ing": "政策进行中",
    "Zheng_Ce_Sheng_Xiao": "政策生效", "Zheng_Ce_Start_Time": "政策开始时间",
    "Zheng_Ce_Unlock_Next": "政策解锁下一项", "Zheng_Ce_Unlock_YN": "政策是否解锁",
    "Zheng_Ce": "政策", "Zheng_Ce_Code": "政策编号", "Zheng_Ce_Index": "政策序号",
    "Zheng_Ce_Ing_Ting": "政策进行中停止", "Zheng_Data_Array": "政策数据表甲",
    "Zheng_Data_Array_Obj": "政策数据表乙", "A_Di_Zhi_Data": "地志数据",
    "Neng_Li_Or_Zheng_Ce": "能力或政策", "Fu_Jia_Shui_Type": "附加税类型",
    "Gai_Ge_Jin_Du": "改革进度", "Is_E_Wai_Jia_Shui": "是否额外加税",
    "Is_E_Wai_Zheng_Bing": "是否额外征兵", "Is_Jie_Ti": "是否借题",
    "Is_Ming_Li_Chu_Jun": "是否明令出军", "Is_Open_He_Tong_Yi_Xia": "开放合同一夏",
    "Zui_Xing_Array": "罪行表", "From_Zui_Xing": "来自罪行",
    "Zui_Level": "罪刑等级", "Xing_Fa_Type": "刑罚类型",
    "You_Jian_King": "右谏国", "Zuo_Jian_King": "左谏国",
    "King_Statute_Book_Array": "国律令书表", "Statute_Book_Owner_King_Code": "律令书属国",
    "Zui_Ming_Xing_Fa_Array": "罪名刑罚表", "Zui_Ming": "罪名",
    "Zui_Ming_Cao_Zuo": "罪名操作", "Qiu_Qi": "囚期",
    "Dang_An": "档案", "Gong_Xiang_Guan_King_Map": "共享官国映射",
    "Shou_Xiang_Guan_King_Map": "收享官国映射",

    # ---------------------------------------------------------- 军事
    "Army_Code": "军队编号", "Army_Type": "军队类型", "Army_Status": "军队状态",
    "Army_Data_Array": "军队数据表", "Army_Data_Static_Code": "军队静态编号",
    "Jun_Dui_Code": "军队编号", "Jun_Dui_Name": "军队名", "Jun_Dui_Level": "军队等级",
    "Jun_Dui_Leve": "军队等级", "Jun_Dui_Data": "军队数据",
    "Jun_Dui_Array": "军队表", "Jun_Dui_Ren_Min": "军队人数",
    "Jun_Dui_Shi_Qi": "军队士气", "Jun_Dui_Zhan_Li": "军队战力",
    "Jun_Dui_Ji_Lv": "军队纪律", "Jun_Dui_Jian_Zhi_Max": "军队建制上限",
    "Jun_Dui_Jian_Zhi_Limit": "军队建制限制", "Jun_Dui_Num_Max": "军队数量上限",
    "Jun_Dui_Shu_Liang_Limit": "军队数量限制", "Liu_Cheng_Data": "留存数据",
    "Liu_Cheng_Ren": "留存人", "Liu_Cheng_Type": "留存类型",
    "Liu_Chen_Name": "留臣名", "Liu_Chen_Str": "留臣世系",
    "Bing_Zhong_Pei_E": "兵种配额", "Bing_Yuan_Zhi_Liang_Map": "兵源支粮映射",
    "Bing_Li": "兵力", "Chang_Bing_Lian_Du": "长兵练度", "Gong_Nu_Lian_Du": "弓弩练度",
    "Qi_Cheng_Lian_Du": "骑乘练度", "Huo_Qi_Lian_Du": "火器练度",
    "Jin_Shen_Lian_Du": "近身练度", "Shou_Cheng_Lian_Du": "守城练度",
    "Gong_Cheng_Lian_Du": "攻城练度", "San_Jun_Type": "三军类型",
    "Hu_Ben_Type": "虎贲类型", "Liang_Yi_Type": "两翼类型",
    "Jiang_Ling": "将领", "Zhan_Chang_Jing_Yan": "战场经验",
    "Is_Fu_Mie": "是否覆灭", "Is_Shou_Dong": "是否手动",
    "Cur_Ma_Che_Num": "当前马车数", "Weapon_Arr": "武器表",
    "Bie_Bu_Map": "别部映射", "Zhan_Lue_Controller": "战略控制",
    "Die_Zhan_Neng_Li_Num": "谍战能力数", "Gong_Cheng_Neng_Li_Num": "攻城能力数",
    "Jiao_Yu_Neng_Li_Num": "教育能力数", "Nong_Ye_Neng_Li_Num": "农业能力数",
    "Shi_Zheng_Neng_Li_Num": "施政能力数", "Yang_Sheng_Neng_Li_Num": "养生能力数",
    "Yu_Min_Neng_Li_Num": "御民能力数", "Nong_Bing_Kai_Fa": "农兵开发",
    "Qiang_Duo_Neng_Li": "抢夺能力",

    # ---------------------------------------------------------- 文化 / 技术
    "Ji_Shu": "技术", "Cur_Ji_Shu": "当前技术", "Cur_Era": "当前纪元",
    "Cur_Innovation": "当前革新", "Era_Map": "纪元映射", "Jie_Duan": "阶段",
    "Shu_Xing": "属性", "Zi": "字", "Wen_Gu_Xing": "文古形",
    "Is_Si_Shi": "是否私事", "Ming_Fen_Data": "名分数据",
    "Technology_Data_Array": "技术数据表",
    "King_To_Era_Technology_Data_Array": "国至纪元技术数据表",
    "Last_Innovation_End_Time": "上次革新结束时间",
    "Dian_Ce_Array": "典册表", "Dian_Ce_Data": "典册数据",
    "Dian_Ce_Type": "典册类型", "Bian_Zhe": "编者", "Cheng_Shu_Time": "成书时间",
    "Fen_Hui_Count": "焚毁数", "Liu_Pai": "流派", "Wen_Wu_Code": "文物编号",
    "Wen_Wu_Code_Array": "文物编号表", "King_Wen_Wu_Data_Array": "国文物数据表",
    "Wen_Wu_Controller": "文物管理", "Card_Buff_Data_Array": "卡牌增益数据表",
    "Yi_Xu_Code": "遗墟编号", "Yi_Xu_Data_Array": "遗墟数据表",
    "World_Book": "天下书", "Sheng_Ren_Book": "圣人之书",
    "Sheng_Ren_Lin_Chao_Data_Array": "圣人临朝数据表",
    "Sheng_Ren_Sheng_Xiao_Code_Array": "圣人生效编号表",
    "Will_Yi_Xiang": "遗嘱意向", "Dai_Ru_Code_Array": "带入编号表",
    "Dang_Ju_Cheng_Jiu_Array": "当局成就表", "Dang_Ju_Jing_Yan_Map": "当局经验映射",
    "Dang_Ju_Shi_Zhuan": "当局世传", "Xue_Gong": "学宫", "Ji_Jiu": "积贮",
    "Shi_Fan_Map": "示范映射", "Xue_Zi_Data": "学子数据",
    "Gong_Guan_Data": "公馆数据", "In_Tai_Xue": "在太学",
    "Jin_Du": "进度", "Jin_Du_Type": "进度类型", "Jin_Du_Total": "进度总量",
    "Jin_Du_Cheng_Gong_Lu": "进度成功率", "Jin_Du_Liu_Cheng_Content": "进度流程内容",
    "Jin_Du_Liu_Cheng_Running": "进度流程运行中", "Jin_Du_Only_Code": "进度唯一编号",
    "Jin_Liu_Code": "进度流编号", "Jin_Liu_Type": "进度流类型",
    "Jin_Start_King": "进度起始国", "Jin_Xing_Num": "进行数",
    "Student": "学生", "Teacher": "教师", "All_Prop_Arr": "全部道具表",
    "Prop_Code": "道具编号", "Store_Code": "库房编号",

    # ---------------------------------------------------------- 家族关系 / 势力
    "Guan_Xi": "关系", "Tong_Xing": "同姓", "Yin_Qin": "姻亲",
    "Jia_Zu_Guan_Xi_Map": "家族关系映射", "Shi_Men_Arr": "世门表",
    "Shi_Men_Guan_Xi_Arr": "世门关系表", "Shi_Zu_Arr": "世族表",
    "Shi_Zhuan_Data": "世传数据", "Shi_Zhuan": "世传",
    "Political_Factions_Array": "政治派系表",
    "Political_Factions_Static_Code": "政治派系静态编号",
    "Qian_Xi_Data": "迁徙数据", "Qing_Shi_Map_Array": "卿士映射表",
    "Gong_Ting_Data_Obj": "宫廷数据", "Active_Power_Max_Base": "活动力上限基",
    "Cur_Acion_Power": "当前活动力", "Danger_Value": "危险值",
    "Fail_Active_Code_Arr": "失败活动编号表", "Leader_Code": "首领编号",
    "Success_Active_Code_Arr": "成功活动编号表",
    "YunDong_Code": "运动编号", "YunDong_Type": "运动类型", "Yun_Dong_Name": "运动名称",
    "All_Yun_Dong_Data_Map_Array": "全部运动数据映射表",
    "Book_Array": "书册表", "Master_Code": "主导编号", "Member_Code_Array": "成员编号表",
    "Sustain_Time": "维持时间", "Adventure_City_Map_Array": "历险城池映射表",
    "Administrative_Unit_Data": "行政区划数据", "Administrative_Unit": "行政区划",
    "Administrative_Unit_Code_Index": "行政区划编号序号", "Unit_Arr": "单位表",
    "Unit_Code": "单位编号", "Shui_Lv_Zhi_Du": "税率制度",
    "Gong_Ku": "公库", "Gong_Qing_Values": "公卿值",
    "Ci_Zhi": "赐职", "Ji_Di": "基地",
    "Zhan_Lue_Controller": "战略控制", "Save_Task_Data": "任务数据",
    "Task_Manager": "任务管理", "Task_List": "任务表", "Task_Num": "任务数",
    "Task_Finish_Num": "任务完成数", "Max_Task_ID": "最大任务编号",
    "End_Task_List": "结束任务表", "Show_End_Task_Obj": "显示结束任务",
    "Start_Jing_Yan": "起始经验", "Gong_Ji_Array": "功绩表",
    "Play_Card_Array": "玩法卡牌表",

    # ---------------------------------------------------------- 资源
    "Res_Bank_Code": "资源库编号", "Res_Bank_Map": "资源库映射",
    "Res_Code": "资源编号", "Res_Num": "资源数量", "Res_Static_Code": "资源静态编号",
    "Res_Avg_Value_Array": "资源均值表", "Res_Trade_Order_ID": "资源交易命令编号",
    "All_Res_Bank_Array": "全部资源库表", "Empty_Res_Bank_Array": "空资源库表",
    "All_Res_Bank_Array": "全部资源库表", "Fund": "资金", "Jun_Shi": "军事",
    "Lao_Yi": "劳役", "Liang_Shi": "粮食", "Liang": "粮",
    "Population": "人口", "Hero_Type": "英雄类型", "Civilization_Array": "文明表",
    "Cong_Shu": "从属", "Expose": "曝光", "Shou_Zai": "受灾",
    "Fa_Zhan_Value_Base": "发展价值基", "Kai_Fang_Value_Base": "开放价值基",
    "Ling_Huo_Value_Base": "灵活价值基", "Qin_Lue_Value_Base": "侵略价值基",
    "Shan_Zhan_Value_Base": "善战价值基", "Growth_Value": "成长值",
    "Rest_Time": "休息时间", "Huo_Dong_Fan_Wei": "活动范围",
    "Huo_Dong_Fan_Wei_Data_Array": "活动范围数据表",
    "Wei_Fu_1": "未符甲", "Wei_Fu_2": "未符乙", "Shou_Sun": "受损",

    # ---------------------------------------------------------- 史册 / 纪事
    "Strat_Time": "起始时间", "Chui_Lin_Record_Manager": "垂林记录管理",
    "Record_List": "记录表", "Play_Ge_Ju_Name": "割据名称",
    "Say_Array_Ji_Lu": "言论记录表", "Mie_Guo_Cao_Zuo_Map": "灭国操作映射",
    "Last_Year_Bo_Kuan_Type_Array": "去年拨款类型表", "Qiu_Xue_Jie_Shu_Map": "求学结束映射",
    "Map_Shai_Xuan": "城池筛选", "Jia_Zhai_Data": "家宅数据",
    "Jian_Yu_Data": "监狱数据", "Ke_Guan_Data": "客馆数据",
    "Liu_Fang_Data": "流放数据", "You_Shi_Data": "游戏数据",
    "Men_She_Data": "门舍数据", "Shan_Zhai_Array": "山寨表",
    "Liu_Min_Num": "流民数", "City_Code_Array": "城池编号表",
    "City_Change_Data_Array": "城池变更数据表",
    "King_Change_Data_Array": "国变更数据表",
    "King_Name_Change_Data_Array": "国名变更数据表",
    "Qi_Guan_Change_Data_Array": "旗关变更数据表",
    "Map_Code_Array": "城池编号表", "Pos": "位置", "x": "横坐标", "y": "纵坐标",
    "Gong_Lue_Fang_Xiang": "攻略方向", "Qu_Yu_Code": "区域编号",
    "Qu_Yu_Code_Text_Map": "区域编号文字映射",
    "Action_Obj": "行动对象", "Action_King": "行动国",
    "Buff_Data": "增益数据", "Cheng_Data": "城池数据",
    "Hui_Meng_Data": "会盟数据", "Jun_Dui_Array": "军队表",
    "Li_Gong": "立功", "Walk_Data": "行走数据", "Road_Data": "道路数据",
    "Xiao_Xi_Code": "消息编号", "Next_Array": "下一项表",
    "Next_Name": "下一项名称", "Next_Start_Time": "下一项开始时间",
    "Next_Total": "下一项总数", "Mu_Biao": "目标",
    "Ren": "人", "Ren_Num": "人数", "Rel_King_Array": "相关国表",
    "Rel_Map_Array": "相关城池表", "Rong_Di_Data": "戎狄数据",
    "Zhan_Zheng_Data": "战争数据", "Tai_Du": "台度",
    "Gong_Guan_Data": "公馆数据", "Table_Array": "表数组",
    "File_Name": "文件名", "Obj_King_Name": "对象国名",
    "Create_Build_Index": "创建建筑序号",

    # ---------------------------------------------------------- 主循环 / 剧本
    "Game_Day": "游戏日", "Ai_Content": "AI 内容",
    "Ai_Content_List": "AI 内容表", "Ai_Every_Month_Content": "AI 每月内容",
    "Ai_Must_Content": "AI 必做内容", "Player_Ai_Content": "玩家 AI 内容",
    "Every_Month_Content": "每月内容", "Month_Content_List": "每月内容表",
    "Must_Check_Things": "必查事项", "Yue_Chu_Content": "月初内容",
    "Add_Xiao_Xi_Time": "添加消息时间", "Jin_Du_Liu_Cheng_Content": "进度流程内容",
    "Task_Manager": "任务管理",
    "Save_Shu_Ju_Chi_Data/Ren_Shai_Xuan": "人物筛选",
    "Guo_Xue_Da_Zong": "国学大宗", "Last_Year_Bo_Kuan_Type_Array": "去年拨款类型表",
    "Map_Shai_Xuan": "城池筛选", "Mie_Guo_Cao_Zuo_Map": "灭国操作映射",
    "Qi_Yue_Array": "契约表", "Qiu_Xue_Jie_Shu_Map": "求学结束映射",
    "Quan_Ju_Tong_Zhi_Ji_Lu": "全局统治记录", "Ren_Shai_Xuan": "人物筛选",
    "Say_Array_Ji_Lu": "言论记录表", "Sheng_Ren_Book": "圣人之书",
    "Sheng_Ren_Lin_Chao_Data_Array": "圣人临朝数据表",
    "Will_Yi_Xiang": "遗嘱意向", "World_Book": "天下书",
    "Xue_Gong": "学宫", "Ji_Jiu": "积贮", "Shi_Fan_Map": "示范映射",
    "Yi_Xu_Data_Array": "遗墟数据表", "Dang_Ju_Cheng_Jiu_Array": "当局成就表",
    "Zheng_Ba_Sheng_Ren_Code_Array": "争霸圣人编号表",
    "Jia_Zu_Quan_Ju_Tong_Zhi_Ji_Lu": "家族全局统治记录",
    "Jiu_Zhou_Tong_Zhi_Ji_Lu": "九州统治记录",
    "Jun_Ren_Total_Change_Map": "军民总数变化", "Ren_Cai_Num_Change_Map": "人才数变化",

    # ---------------------------------------------------------- 杂项（游戏内部）
    "Sui_Ji": "随机", "Wait": "等待", "Ing": "进行中",
    "Yu_Ban": "预办", "Kai_Fa": "开发", "Que": "缺",
    "Meta_Data": "元数据", "Version": "版本", "Buff": "增益",
    "Buff_Code": "增益编号", "Effect": "效果", "Num": "数量",
    "Max": "上限", "Min": "下限", "Percent": "比例", "Rate": "比率",
    "Speed": "速度", "Value": "值", "Total": "总计", "List": "列表",
    "Map": "映射", "Array": "数组", "Obj": "对象", "Set": "集合",
    "Is": "是否", "Has": "拥有", "Cur": "当前", "Last": "上次",
    "Next": "下一项", "Start": "起始", "Or": "或", "Not": "否",
    "All": "全部", "Empty": "空", "New": "新", "Old": "旧",
    "First": "第一", "End": "结束", "Only": "唯一", "Static": "静态",
    # 少量漏网的
    "Activation": "激活状态", "Switch": "开关", "Evaluate": "评价",
    "Execution_Arr": "处决表", "Execution": "处决", "Arr": "表",
    # 容貌子表（Ren_Face[].X）
    "Face_Name": "部位", "Face_Str": "外观编号",
    "Ren_Ming_Name": "姓名", "Zun_Hao_Name": "尊号",

    # ---------------------------------------------------------- 世界页补遗
    # ★ 2026-09-22 存档考古：以下 54 个字段原先没有中文名（走词根兜底会拼错），
    #   逐个按「存档实际取值 + 游戏内机制 + 官方 WIKI」定名。
    #   证据类型标注在行尾：①=字段值本身即中文 ②=与另一中文字段交叉验证
    #   ③=官方 WIKI/攻略文字 ④=拼音直读（无歧义）。
    # ---- 奇观 / 文物 / 匾额（延展系统）
    "Qi_Guan_Code": "奇观编号",              # ④ 存档 kind=16 里 8=五畤原/10=稷下学宫
    "Put_Qi_Guan_Map_Code": "安放奇观城邑编号",
    "Put_Jia_Zu_Zong_Miao_Index": "安放家族宗庙序号",
    "Put_King_Code": "安放国编号",
    "Put_Map_Code": "安放城邑编号",
    "Put_Ren_Code": "安放人物编号",
    "In_Game": "是否在局中",                  # ① 值 False
    # ---- 王朝 / 官制
    "Guo_Jun_Zun_Hao_List": "国君尊号表",
    "Wang_Chao_Xing_Dian": "王朝刑典",
    "Guan_Zhi_Map": "官职映射",
    "Zuo_Jian_King": "左谏国", "You_Jian_King": "右谏国",
    # ---- 谶言 / 祖训 / 誓文
    "Chen_Yan_Code": "谶言编号",
    "Sheng_Xiao_Chen_Yan_Arr": "生效谶言表",
    "Shi_Xiao_Chen_Yan_Arr": "失效谶言表",
    "All_Zu_Xun_Stone_Array": "祖训石子表",
    "Zu_Xun_Bei_Data": "祖训备数据",
    "Zu_Xun_Unlock_Zheng_Ce_Array": "祖训解锁政策表",
    "Shi_Wen_Array": "誓文表",
    # ---- 家族 / 世官
    "Jia_Shi_Array": "家氏表",
    "Jia_Zu_Xian_Neng_Total": "家族贤能总数",
    "Has_Tu_Di_City_Array": "有封地城邑表",
    "Si_Bing_Num": "私兵数",
    # ---- 城池 / 都邑
    "Map_Zhuang_Tai": "城池围城状态",          # ① 值就是「围城」
    "Map_En_Shang_Off": "城池恩赏开关",
    "Map_Li_Yu_Off": "城池礼遇开关",
    "Map_Ping_Pan_Off": "城池评判开关",
    "Sheng_Yu_Shi_Ling_Ren_Kou": "生育适龄人口",
    "Chou_Diao_Time": "抽调时间",
    "Xun_Fang_Xian_Shi_Time": "巡访显示时间",
    "Diu_Shi_Time": "失地时间",
    "Business_Sys": "商业系统",
    "Cao_Zuo_Map": "操作映射",
    "Market_Arr": "市场表", "Shang_Lu_Code": "商路编号",
    "Shang_Lu_Data_Arr": "商路数据表", "Jie_Ju": "结局",
    # ---- 外交 / 戎狄
    "Jie_Dao_Open_1": "借道开放 · 甲", "Jie_Dao_Open_2": "借道开放 · 乙",
    "Rong_Di_data": "戎狄数据", "War_Obj": "战争对象",
    # ---- 资源 / 私有
    "Onwer_Code": "所有者编号",               # ① 原文拼写 Onwer（游戏笔误，应为 Owner）
    "Onwer_Type": "所有者类型",
    # ---- 其余
    "Chan_Sheng_Ci_Shu": "产生次数",
    "Che_Di_Die_Time": "彻底死亡时间",
    "Chu_Si_Ren_Num": "处死人数",
    "From_King": "来自国",                    # ② 与 Obj_King（对象国）成对
    "Li_Wu_Type": "礼物类型",
    "Ren_Data": "人物数据",
    "Ren_Ru_Zhui": "人物入赘",
    "Ren_Quan_Jiang": "人物劝降",             # 推断（样本仅 1 条）
    "Shu_Zi": "庶子表",
    "Tong_Zhi_Shi_Jian": "统治时间",
    "Zheng_Ce_Array": "政策表",
    "Si_Xue_Map": "私学映射", "Tai_Xue_Map": "太学映射",
    "_Code": "编号", "_State": "状态",
}

# 上面没登记但名字里带这些词的，做词根级兜底拼装
_ROOTS = [
    ("Ren", "人物"), ("King", "国"), ("Map", "城池"), ("Jia_Zu", "家族"),
    ("Army", "军队"), ("Jun_Dui", "军队"), ("Buff", "增益"), ("Code", "编号"),
    ("Name", "名称"), ("Time", "时间"), ("Level", "等级"), ("Data", "数据"),
    ("Array", "表"), ("List", "表"), ("Num", "数量"), ("Max", "上限"),
    ("Min", "下限"), ("Type", "类型"), ("Value", "值"), ("Rate", "比"),
    ("Wen_Hua", "文化"), ("Jue_Wei", "爵位"), ("Zhi_Lue", "智略"),
    ("Cheng", "城池"), ("Zhan", "战"), ("Zheng", "政"), ("Jun", "军"),
    ("Guan", "官"), ("Shi", "氏"), ("Xing", "姓"), ("Ming", "名"),
    ("Sheng", "生"), ("Si", "死"), ("Old", "年"), ("Time", "时间"),
    ("Xian", "先"), ("Hou", "后"), ("Zhu", "主"), ("Ke", "客"),
    ("Arr", "表"), ("Activation", "激活状态"), ("Switch", "开关"),
    ("Evaluate", "评价"), ("Execution", "处决"),
]

# 明确「游戏内部 id，不该翻译」的字段 —— 这些是引擎用的哈希/id，翻译了反而误导
INTERNAL_IDS = {
    "id", "key", "state", "EntityID", "Xiao_Xi_Code", "Store_Code",
    "Unit_Code", "Unique_ID", "Only_Code", "Static_Code",
}


def field_label(key: str) -> str:
    """字段 → 中文名。已登记的走字典；没登记的做词根兜底，绝不返回空。"""
    if key is None:
        return ""
    s = str(key)
    if s in FIELD:
        return FIELD[s]
    if s in INTERNAL_IDS:
        return s + "（内部编号）"
    # 派生列（GUI 自己拼的）
    if s.startswith("_"):
        return s[1:]
    # 词根兜底
    parts = [p for p in s.split("_") if p]
    if not parts:
        return s
    out = []
    for p in parts:
        hit = None
        for root, zh in _ROOTS:
            if p == root:
                hit = zh
                break
        out.append(hit if hit else p)
    return "".join(out)


# ============================================================ 二、值域：中文枚举
# 这些字段的值本身**就是中文**，不需要映射 —— 但列出来便于 GUI 做「这里是枚举」的提示
CHINESE_ENUM_FIELDS = {
    "Ren_Wen_Hua", "Ren_Xing_Ge", "King_Stage", "Wang_Chao_Jie_Duan",
    "Wang_Chao_Zhi_Du", "Wang_Chao_De_Yun", "Wang_Chao_Guan_Xue",
    "Map_Zhi_Li", "Map_Wen_Hua_Main", "Jia_Zu_Type", "Ben_Zhi",
    "Ji_Wei_Shen_Fen", "Army_Status", "You_Yi_Type", "Wai_Jiao_Zhuang_Tai",
    "Zui_Ming", "Zui_Ming_Cao_Zuo", "Dian_Ce_Type", "State", "Ming_Fen_Name",
    "Kai_Fang_Nong_Ye", "Ren_In_Map_Position", "Face_Name", "Shu_Xing",
    # ★ 2026-09-22 补：实测「值本身即中文」的字段（原误建了数字映射）
    "Hui_Meng_Zhuang_Tai",      # 见「正常」
    "Map_Zhuang_Tai",           # 见「围城」
    "Fu_Jia_Shui_Type",         # 见「免征」
    "Xing_Fa_Type",             # 见「赦免」
    "Tian_Ming_Wu_De",          # 见「水德 / 火德」
    "Zuo_Zhan_Type",            # 见「0」（暂未出现中文，但字段语义是中文枚举）
}

# ============================================================ 三、值域：数字码
# ⚠️ 每一个都标了「证据来源」。没有证据的一律不进这张表。
#
# 证据 A：游戏在**别处**用中文写下了同样的值
# 证据 B：与另一个中文字段交叉验证
# 证据 C：国名的字面语义（仅用于族姓，标注为「推断」）

VALUE = {}

# ---- 性别（证据 B：Save_Woman_Data 是纯女性表，Ren_Sex 全是 1；
#      已故表中女性也几乎是 1；族谱里母亲节点查回来全是 1）—— 铁证
VALUE["Ren_Sex"] = {0: "男", 1: "女"}

# ---- 爵位（证据 A：上古档 King_Str 末段就是同一个码，且与国名姓氏字一一对应）
#      例：风巢皇|风||公|-24 → 码 3 = 「公」；子厌潏|子||王|-24 → 码 3 = 「王」…
#      ⚠️ 但上古档与秦末档的码表**不同**（不同剧本用了不同段位表），
#      所以这里只登记在**两档都能对上**的那几个，其余交给 GUI 按档提示。
VALUE["King_Jue_Wei_Code"] = {
    1: "帝", 3: "王", 4: "公", 5: "侯", 6: "伯", 7: "子", 53: "卿",
    25: "匈奴单于", 26: "乌桓大人", 27: "东部大人", 28: "丁零大人",
    29: "鞑靼可汗", 34: "羯胡首领", 35: "室韦都督", 46: "西域城主",
}

# ---- 族域（证据 B：与 Ren_Wen_Hua 交叉 —— 秦末档 12 码里
#      0 是兵家/儒家/道家/法家（华夏诸子）；6 是匈奴/西域/扶余；7 是西域/匈奴/象雄；
#      12 是百越/辰韩/百濮；13 是象雄/百濮/百越；9/10/14 全是「先民」（未开化部族）。
#      ⚠️ 上古档只有 0-5，且那 6 个码全是「先民/河洛/岐山/江淮/河汾/渤海」这类
#      **文化地理区**，不是族域 —— 所以码表按档分开给，`region_of()` 负责分派。
VALUE["Ren_Zu_Yu"] = {
    # 秦末档 · 华夏与四方
    0: "中夏", 6: "北狄", 7: "西戎", 12: "南蛮", 13: "西戎",
    9: "先民", 10: "先民", 14: "先民",
    1: "东夷", 2: "东夷", 3: "东夷", 4: "南蛮", 5: "东夷",
}
# 上古档 0-5 = 文化地理区（那时还没有「戎狄」的区分）
VALUE["Ren_Zu_Yu_上古"] = {
    0: "河洛", 1: "岐山", 2: "江淮", 3: "河汾", 4: "中原", 5: "渤海",
}

# ---- 神系（`Faith_Gods_Sys_Code`，信仰神祇系统编号）★ 2026-09-29 新增
#   ★ **单一来源**：码表本体在 `app/gods.py`（连同神名、效果、庙宇公式一起），
#     这里只引用 —— 避免两处各抄一份、日后不同步（本项目已有先例：
#     表族分类只认 `catalog.CATEGORIES` 一处）。
#   证据链（三条独立证据互相印证）与免责声明见 `app/gods.py` 模块头。
VALUE["Faith_Gods_Sys_Code"] = dict(GOD_SYS_BY_CODE)

# ---- 外交关系数值：⚠ 2026-09-22 修正 —— 原映射 {0:中立 30:同盟 60:敌对} **是错的**。
#      全档实测 16576 条，取值范围 **0 ~ 200、无负数**，是**好感度/信任度**这一连续量，
#      与「中立/同盟/敌对」不是一回事 —— 证据：关系值 = 0 的记录里，
#      状态同时存在 中立(2631) / 同盟(8) / 敌对(6) 三种。
#      关系状态请读 `Wai_Jiao_Zhuang_Tai`（值本身就是中文）。
# Wai_Jiao_Guan_Xi  ← 好感度 0~200（无数值枚举）

# ---- 荒地类型（证据 A：城池名与地形 —— 1 合黎/柳湾/燕山 = 山林荒；2 临羌/龙首 = 高原荒；
#      3 卑禾/天峻/弓月 = 荒漠；⚠️ 仅 3 值，游戏内未见中文对照，标注为「推断」）
VALUE["Huang_Ye_Type"] = {1: "山林荒地", 2: "高原荒地", 3: "荒漠戈壁"}

# ---- 城池状态（证据 A：值 4 占绝大多数 = 正常，值 1 只 1 例）—— 证据最弱，只登记「正常」
VALUE["Map_State"] = {4: "正常"}

# ---- 人物等级 Ren_Leve（证据 A：该等级的**智略均值单调递增**，且样例人名可查证）
#      ───────────────────────────────────────────────────────────────────────
#      【男性段】0-11，码越大等级越高。五级制「庶 → 下 → 中 → 上 → 邦」由使用者确认。
#        秦末档实测智略均值：0 →30 熊心/韩藤    1 →61 徐福/嬴胡亥    2 →75 叔孙通/刘肥
#                            3 →83 李左车/吕泽  4 →94 挛鞮冒顿
#        上古档实测（Save_All_100_new，3759 人）：
#                            0 →33.3（n=1564）  1 →59.2（n=804）   2 →74.2（n=592）
#                            3 →81.3（n=26）    4 →94.0（n=6）     7 →88（n=1 风少典）
#        5/6/7/8 = 将/臣/君/豪，是**特殊身份标签**，不属于五级（5/6 原译「名将/名臣」，
#        2026-09-21 使用者裁改为单字「将/臣」；7/8 原译「雄主/枭雄」，
#        2026-09-21 使用者二次裁改为「君/豪」—— 同样为与其他单字标签对齐）。
#        ⚠️ 注意：这里 7=「君」是**人物等级标签**，与爵位「公/侯/伯」无关，
#           也不代表「一国君主」（是否为君主看宗庙表，别混）。
#        10 = 圣（**单独的等级**，与五级分开计）。
#             ⚠️ 使用者订正：智略靠前的那批人等级显示为「圣」。
#             实测（Save_All_3 / Save_All_100，34 人，智略均值 93.8）——
#             姬旦（周公旦）、姬昌（周文王）、姬发（周武王）、姜尚（姜子牙）、
#             子比干、鬻熊、太颠、子胥余。**这些就是「圣人」层**。
#             ⚠️ 曾误以为是 9，实际码值是 **10**（9 在存档里从未出现）。
#        11 = 神（原「神祖」，使用者要求简化为单字「神」）。
#             风伏羲/姜石年（伏羲/神农）/风太典等，上古档 n=5 智略均值 91.6；
#             存档实测跨档 31 人（含姜尚、子受＝商纣王、妘灵皇等）。
#
#      【女性段】100+，与男性段**并行**（不是更高）。
#        ⚠️ 方向与男性段**相反**：码越大等级越高，但名字按「美 → 佳 → 淑 → 丽 → 良」自低向高。
#        使用者确认：100=美 101=佳 102=淑 103=丽 104=良
#        ⚠️ 使用者要求：显示时**不加「女」字前缀**（男女段的分野由「性别」列自己说明）。
#        上古档实测（智略均值单调递增，印证方向）：
#            100 →46.1（n=297）  101 →67.9（n=394）  102 →81.6（n=65）
#            103 →92.3（n=3 曹章/嬴芸/幽泉）        105 →73（n=2 赤水听訞/姜女娃）
#        秦末档：105 →96 吕雉/窦漪房（后妃级）
VALUE["Ren_Leve"] = {
    # 男性五级（庶最低 → 邦最高）
    0: "庶", 1: "下", 2: "中", 3: "上", 4: "邦",
    # 特殊身份标签（不属五级；5/6 原译「名将/名臣」，2026-09-21 使用者定为单字「将/臣」；
    # 7/8 原译「雄主/枭雄」，同日二次裁改为「君/豪」）
    5: "将", 6: "臣", 7: "君", 8: "豪",
    10: "圣",
    11: "神",
    # 女性五级（码越大越高：美最低 → 良最高）
    # ⚠️ 2026-09-21 使用者二次裁改：105 原译「后妃」→ 单字「哲」（与男段的「君/豪」同样单字）。
    # ⚠️ 2026-09-22 使用者三次裁改：106 原译「宠姬」→ 单字「国」
    #   （对照戚姬=106 游戏内徽标显示「国」，即宠妃级）。
    100: "美", 101: "佳", 102: "淑", 103: "丽", 104: "良",
    105: "哲", 106: "国",
}

# ---- 人物等级的**顺序标签**（给 GUI 排序/着色用，不参与显示文本）
#      男性段 0-4 由低到高 = 庶 下 中 上 邦；女性段 100-104 由低到高 = 美 佳 淑 丽 良
LEVE_ORDER = {
    0: 0, 1: 1, 2: 2, 3: 3, 4: 4,
    5: 5, 6: 6, 7: 7, 8: 8,
    10: 9, 11: 10,
    100: 0, 101: 1, 102: 2, 103: 3, 104: 4,
    105: 5, 106: 6,
}


def is_female_tier(value) -> bool:
    """这个等级码是不是女性段（100+）。"""
    try:
        return int(value) >= 100
    except (TypeError, ValueError):
        return False


def leve_label(value):
    """等级码 → 中文。

    例：3 → 「上」；103 → 「丽」；11 → 「神」。
    ⚠️ 女性段**不加前缀** —— 使用者要求去掉「女 ·」，
       男女的区分看「性别」列即可。
    """
    zh = VALUE["Ren_Leve"].get(value) if not isinstance(value, bool) else None
    if zh is None:
        try:
            zh = VALUE["Ren_Leve"].get(int(value))
        except (TypeError, ValueError):
            zh = None
    return zh


# ---- 国等级 King_Leve（证据 A：上古档 100 = 叛军、102 = 猃狁黑氏/合黎风氏这类异族政权）
#      值域太小（只有 100/102 两种），不足以定名，故**不登记**，GUI 会原样显示数字。

# ---- 类别 Class_Type（证据 A：在世/女性/出生/ED 表里出现 1；已故表里为 None）
#      ⚠️ 使用者明确要求：显示为「在世」，不要「活跃人物」这种措辞。
VALUE["Class_Type"] = {1: "在世"}

# ---- 系属 Ren_Sys_Is（证据 A：在世表 780 个 1 = 历史人物，2788 个空 = 随机生成的路人）
#      ⚠️ 使用者要求：1 → 「在世」；0/空 → 不显示措辞（GUI 里为空时输出「—」）。
VALUE["Ren_Sys_Is"] = {0: "在世", 1: "在世"}

# ---- 兵种 / 军队
# ⚠ 2026-09-22 修正：`Army_Type` 原映射 {1:步兵 2:车兵 3:骑兵 4:水军} **是猜的**，
#   全档实测只出现三个值 **7(343) / 22(6) / 21(1)**，与 1-4 完全不相交。
#   7 是本国主力军的默认值；21/22 样本各 1~6 条，且都带 `Allegiance_Data`
#   （归附数据），疑似「附庸军 / 盟军 / 义军」。**证据不足，宁缺勿猜 —— 不给映射。**
# Army_Type        ← 待考（实测 7 / 21 / 22）
# 下面这三个在本机 5 个存档里**从未出现**，保留仅为兼容旧档，标「未证实」。
VALUE["Hu_Ben_Type"] = {1: "虎贲", 2: "虎贲锐士"}          # 未证实
VALUE["San_Jun_Type"] = {1: "左军", 2: "中军", 3: "右军"}   # 未证实
VALUE["Liang_Yi_Type"] = {1: "左翼", 2: "右翼"}             # 未证实

# ---- 会盟状态：⚠ 2026-09-22 修正 —— 实测值**本身就是中文**（「正常」），
#      原 {1:筹备 2:进行 3:结束} 无依据，已删；改由 CHINESE_ENUM_FIELDS 声明。
# ---- 罪刑等级、祭祀类型：全档未出现，保留原映射但标「未证实」。
VALUE["Memorial_Type"] = {1: "先祖", 2: "先王", 3: "功臣", 4: "天地"}   # 未证实
VALUE["Zui_Level"] = {1: "轻罪", 2: "中罪", 3: "重罪", 4: "死罪"}        # 未证实

# ---- 继位身份：⚠ 2026-09-22 修正 —— 实测值**本身就是中文**
#      （布衣×347 / 宗亲×42 / 卿族×3 / 公族×2），原 0/1/2/3 映射无依据，已删。
# ---- 城池施政方向：⚠ 2026-09-22 修正 —— 实测值**本身就是中文**
#      （暂无×6988 / 军备×825 / 农业×207 / 文化×32 / 治安×7），原映射已删。

# ---- 骑兵等练度等级（证据 A：字符与数字混排 —— 甲乙丙 + 1/2/3）
VALUE["Level"] = {"甲": "甲等", "乙": "乙等", "丙": "丙等",
                  1: "一等", 2: "二等", 3: "三等"}

# ---- 城池施政方向、继位身份、会盟状态、围城状态：**值本身就是中文**，
#      取消数字兜底（原兜底映射经实测无依据，反而可能在别的档里显示错）。
#      见 CHINESE_ENUM_FIELDS。

# ---- 所有者类型（证据 C：值 0/1 占绝大多数 = 国/家族）
VALUE["Onwer_Type"] = {0: "国", 1: "家族", 3: "山寨", 4: "戎狄", 6: "外族"}

# ---- 增益类别（Neng_Li_Or_Zheng_Ce）—— 「这一条记录属于哪一类效果」
# ★ 2026-09-22 大扩展：此前只登记了 0/1 两种，实测存档里其实有 15 种。
#   证据：`Save_KingData.King_Buff_Array` 每条记录都带 `Buff_Name`（中文），
#   按本字段分组后语义一目了然（详见 `_stats/_buff_kinds.txt`）。
VALUE["Neng_Li_Or_Zheng_Ce"] = {
    0: "政策",        # 名字与 names_map.ZHENG_CE_CODES 完全一致
    1: "能力",        # 名字与 names_map.NENG_LI_CODES 完全一致
    2: "祭祀",        # 值形如「祭祀水神若皇」「祭祖」
    3: "外交盟约",    # 万流同源 / 睦邻友好 / 华夷之辩（WIKI：会盟盟约）
    6: "状态增益",    # 兵民一体 / 明君盛世 / 幼龄化…（含阶段 5151-5154）
    7: "政体",        # 中央集权
    8: "政治格局",    # 政在方伯
    9: "文物",        # 宗庙宝器 + 长信宫灯 / 错金博山炉…（WIKI：文物系统）
    16: "奇观",       # 五畤原 / 稷下学宫…（带 Qi_Guan_Code + Map_Code）
    30: "天时",       # 农业历法 / 小冰期 / 温暖期
    31: "技术积累",   # 农耕积累 / 农艺积累 / 水工积累…（WIKI：技术系统经验加成）
    32: "兵种传统",   # 盾兵 / 矛兵 / 戈兵 / 弓兵 / 弩兵 / 车兵传统
    40: "技术",       # Buff_Code 形如 `Technology_1103`
    41: "先父余威",   # 「先父余威：厉/庄/懿/文/昭…」= 继承某谥号先君的加成
    102: "年号",      # 洪化年号
    103: "辅政",      # 南岳辅政
}

# ---- 「参数化编号」——**一个编号对多个名字**，不能进任何映射表
# ★ 2026-09-22 定案。实测 `10082` 一次就对应 11 个名字
#   （凤之军建制位军 / 鸾之军建制位军 / 鸿之军建制位军 …）。
#   它们表达的是「**某军的某级建制**」：军名由上下文（哪支军）决定，建制由编号决定。
#   对应游戏机制（TapTap《割据势力介绍》）：
#     · 渠帅军制（割据叛军）：天/地/人/雷/山/波/龙/虎 八军
#     · 部曲军制（割据军阀）：中/前/后/左/右 五军
#     · 六军体系：青云六军(凤鸾鸿鹄雕鸠) / 黄云六军(貅貙) / 白云六军(肩臂骨)
#     · 建制：位 / 向 / 列 / 阵 / 方 / 大方（渠帅）；曲 / 营 / 部 / 校 / 五校 / 八校（部曲）
#   ⇒ **渲染时必须用记录自身的 `Buff_Name`**，绝不能查表 —— 查了只能得到其中一个名字。
PARAMETRIC_POLICY_CODES = {
    10082: "【某】之军建制位军", 10083: "【某】之军建制向军",
    10084: "【某】之军建制列军", 10085: "【某】之军建制阵军",
    10086: "【某】之军建制方军",
    10309: "【某】军建制曲", 10310: "【某】军建制营",
}

# ============================================================ 三·乙、效果名档案
# 「类别码 → (编号 → 中文名)」。存档里每条记录自带 `Buff_Name`，所以这里是**冗余兜底**：
# 当某条记录的编号出现在别处（政策树 / 技术树 / 别国引用）而记录本身已被清理时，
# 仍能查到它的名字。数据来自 2026-09-22 全档普查，工具：
#     python tools/scan_number_map.py --kinds
EFFECT_NAME = {
    # ---- 40 技术（Buff_Code = `Technology_<编号>`）—— **70 个，实测全量**
    #      分组规律（与官方 WIKI《技术系统详解》三个特殊时代一一对应）：
    #        11xx 木石时代 · 12xx 青铜时代 · 13xx 黑铁时代
    #        27xx 作物优化 · 28xx 历法优化 · 39xx 族群认同 · 14xx（未出现）
    40: {
        # —— 木石时代 11xx
        "1101": "裁叶作衣", "1102": "构木为巢", "1103": "钻木取火",
        "1104": "抟土造陶", "1105": "发明陶轮", "1106": "播植百谷",
        "1107": "刀耕火种", "1108": "选育良种", "1109": "驯化野兽",
        "1110": "兽栏围墙", "1111": "畜力协作", "1112": "畜力磨坊",
        "1113": "畜力战车",
        # —— 青铜时代 12xx
        "1201": "带釉陶器", "1202": "陶范", "1203": "青铜锻造",
        "1204": "青铜铸造", "1205": "青铜构件", "1206": "原始铜镰",
        "1207": "原始铜锄", "1208": "原始铜犁", "1209": "原始铜剑",
        "1210": "原始铜矛", "1211": "原始铜盾", "1212": "守城器械",
        "1213": "攻城器械",
        # —— 黑铁时代 13xx（本机存档只出现过 9 项，其余待补）
        "1301": "火窑", "1302": "地炉", "1304": "退火技术",
        "1305": "固体渗碳", "1308": "铁制农具", "1309": "畜力橐龠",
        "1311": "铁制铸范", "1312": "生铁柔化", "1313": "韧性铸铁",
        # —— 作物优化 27xx（对应时代 10004）
        "2701": "驯化栽培", "2702": "种田优选", "2703": "单株选择",
        "2704": "纯种优化", "2705": "良种引入", "2706": "粟种改良",
        "2707": "黍种改良", "2708": "稻种改良", "2709": "引入小麦",
        "2710": "驯化大豆", "2713": "救荒作物",
        # —— 历法优化 28xx（对应时代 10005）
        "2801": "观象授时", "2802": "观星定历", "2803": "观月定历",
        "2804": "观日定历", "2805": "日月合历", "2806": "编订夏小正",
        "2807": "编订北斗历", "2808": "编订太岁历", "2809": "编订羲和历",
        "2810": "编订朔望历", "2811": "编订颛顼历", "2812": "编订干支历",
        "2813": "编订太初历",
        # —— 族群认同 39xx（对应时代 10006）
        "3901": "物资分配", "3902": "首次分工", "3903": "农耕生活",
        "3904": "国野分化", "3905": "宗族共治", "3906": "游牧生活",
        "3907": "冬夏牧场", "3908": "部盟联合", "3909": "渔猎生活",
        "3910": "猎区规划", "3911": "寨落互助",
    },
    # ---- 32 兵种传统
    32: {"5209": "盾兵传统", "5210": "矛兵传统", "5211": "戈兵传统",
         "5212": "弓兵传统", "5213": "弩兵传统", "5214": "车兵传统"},
    # ---- 31 技术积累
    31: {"5300": "先民匠作", "5301": "精工六齐",
         "5318": "农耕积累", "5319": "农艺积累",
         "5324": "水工积累", "5325": "水利积累", "5327": "观星积累",
         "5330": "作物革命", "5331": "历法革命"},
    # ---- 30 天时
    30: {"304": "农业历法", "5422": "小冰期", "5423": "温暖期"},
    # ---- 16 奇观（编号 = Qi_Guan_Code，与 WIKI 展示顺序不同）
    16: {"8": "五畤原", "9": "汤王庙", "10": "稷下学宫", "11": "灵台",
         "13": "娲皇宫", "15": "龙游石窟", "16": "伏羲台", "19": "钧台"},
    # ---- 3 外交盟约
    3: {"34": "万流同源", "36": "睦邻友好", "38": "华夷之辩"},
    # ---- 8 政治格局 / 王朝官职（编号 88-90 是格局，102-107 是王朝官职）
    8: {"88": "礼乐严明", "89": "政在天子", "90": "政在方伯",
        "102": "王朝军正", "103": "王朝虞候", "104": "王朝太卜",
        "105": "王朝太祝", "106": "王朝典乐", "107": "王朝士师"},
}

# ---- 时代编号（Save_Ji_Shu_Data/King_To_Era_Technology_Data_Array）
#      证据 A：`Era_Map` 里每个时代固定 13 项技术，State=3 表示已研完；
#              Cur_Era=10003 的国，10001/10002 全 3 → 说明 10003 是「黑铁」。
#      证据 B：WIKI《技术系统详解》——木石/青铜/黑铁三主时代 + 族群认同/作物优化/历法优化。
VALUE["Cur_Era"] = {
    10001: "木石时代", 10002: "青铜时代", 10003: "黑铁时代",
    10004: "作物优化", 10005: "历法优化", 10006: "族群认同",
    10007: "未知时代 · 待考",   # 技术段 14xx，本机 5 档从未出现名字
}
# ---- 技术树节点状态（同表 Technology_Data_Array[].State）
VALUE["_Tech_State"] = {0: "未研究", 1: "研究中", 2: "可研究", 3: "已完成"}


# ============================================================ 四、值域：时间
def _time_parts(v):
    """`"-244,1,0"` → `(年, 月, 日)`；兼容不带逗号的纯年份 `"-2500"` → `(-2500, 0, 0)`。

    ★ 代码改进 A13（2026-09-22）：吸收 profiles.py 的容错版 —— 唯一实现。
      此前纯年份串会返回 None 导致上层原样显示；现在正常格式化（显示文本不变）。
      数字 / 纯数字串以外的输入不合法返回 None。
    """
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v), 0, 0
    if not isinstance(v, str):
        return None
    s = v.strip()
    if not s:
        return None
    if "," in s:
        parts = s.split(",")
    elif re.fullmatch(r"-?\d+", s):
        parts = [s, "0", ""]
    else:
        return None
    if len(parts) < 2:
        return None
    try:
        y = int(parts[0].strip())
        m = int(parts[1].strip())
        d = int(parts[2].strip()) if len(parts) > 2 and parts[1].strip() else 0
    except ValueError:
        return None
    return y, m, d


def fmt_year_month(y, m):
    """(年, 月) → 紧凑文本（`"-1106.01"`；0 年 →「元年」，月份缺省只给年份）。

    ★ 代码改进 A13：从 profiles.py 抽出公用（生卒推算与时间列同一套格式）。
    """
    if y == 0:
        s = "元年"
    else:
        s = str(y)
    if m:
        s += f".{int(m):02d}"
    return s


def humanize_time(v):
    """时间 → **紧凑格式**（使用者要求：只写 `-1106.01` 这样，省地方）。

    例：`-244,1,0` → `-244.01`；`1066,3,12` → `1066.03`；月份缺省只给年份。
    不合格式的返回 None（交给调用方按原值显示）。
    """
    p = _time_parts(v)
    if p is None:
        return None
    y, m, _d = p
    return fmt_year_month(y, m)


def humanize_time_long(v):
    """时间 → **长文本**（「公元前 1106 年 1 月」）。详情小字、关系视图里用。"""
    p = _time_parts(v)
    if p is None:
        return None
    y, m, d = p
    if y < 0:
        s = f"公元前 {-y} 年"
    elif y == 0:
        s = "公元 0 年"
    else:
        s = f"公元 {y} 年"
    if m:
        s += f" {m} 月"
    if d:
        s += f" {d} 日"
    return s


# 这些字段的值是时间三元组（从 _stats/enums.txt 的实测值域确定）
TIME_FIELDS = {
    "Ren_Chu_Sheng_Time", "Ren_End_Time", "Ren_Start_Time", "Ren_Ji_Wei_Time",
    "Born_Time", "Dead_Time", "Start_Time", "End_Time", "Last_Time",
    "Last_Use_Time", "Use_Time", "Used_Time", "Total_Time", "Time",
    "Buff_Start_Time", "Buff_End_Time", "Memorial_Ren_Born_Time",
    "Memorial_Ren_Dead_Time", "Memorial_Ren_Become_Time", "Zai_Hai_Time",
    "Zai_Hai_End", "Hui_Meng_Start_Time", "Zhan_Zheng_Time", "Zhan_Zheng_End",
    "War_Time", "War_End_Time", "War_Creat_Time", "Xuan_Zhan_Time",
    "Chao_Hui_Time", "Chong_Xing_Time", "Ji_Si_Time", "Chu_Sheng_Time",
    "Record_Time", "Cheng_Shu_Time", "Jian_Zheng_Time", "Guan_Xing_Time",
    "Xiong_Di_Zhu_She_Time", "Xun_Fang_Xian_Shi_Time", "Last_King_Ren_Kill_Time",
    "Last_Guo_Du_Bei_Zhan_Time", "Guo_Ren_Xian_Yu_Time", "Zheng_Ce_Start_Time",
    "Last_Innovation_End_Time", "Last_Shui_Lv_Change_Time", "Diu_Shi_Time",
    "Add_Xiao_Xi_Time", "Wai_Jiao_Fu_Yuan_Time", "Wai_Jiao_Qiu_Xue_Time",
    "King_Suo_Gong_Time", "Presence_Time", "Next_Start_Time", "Sustain_Time",
    "Rest_Time", "Strat_Time", "Che_Di_Die_Time", "Ren_End_Old",
}

# ============================================================ 五、富文本剥离
_COLOR_TAG = re.compile(r"</?color(?:=[^>]*)?>|<[^>]{1,20}>")


def strip_rich(text: str) -> str:
    """剥掉 `<color=#FF6A00>…</color>` 这类游戏富文本标记。"""
    if not isinstance(text, str) or "<" not in text:
        return text
    return _COLOR_TAG.sub("", text)


# ============================================================ 五之二、重名序数
# 重名序数 **现行是纯数字**（`风会胜1`）—— 与 `tools/import_from_game.dup_num` 同规。
# 渲染层（主树 / 时间轴）靠 `split_dup` 把「风会胜1」拆成「风会胜」+「1」，
# 再把序数缩成小号**灰**字贴到名字最后一字的**右上角**（像幂）。
# （使用者 2026-09-22：「改成数字右上角角标灰色123吧，像幂一样那种」）
#
# 老档里还留着上一版的**带圈数字**（①②③）和更老的中文数字 —— 认出来之后
# 一律**归一成数字**再画/再显示，保证「表格里是 3、画布上也是 3」。
DUP_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def split_dup(name):
    """`「风会胜3」→ ("风会胜", "3")`；没有序数返回 `(原名, "")`。

    序数**一律归一成数字**再返回（老档的带圈数字换算成数字）：
      · 现行「风会胜3」   → `("风会胜", "3")`
      · 上一版「风会胜③」 → `("风会胜", "3")`
      · 更老的退路「风会胜(21)」→ `("风会胜", "(21)")`（原样留着，纯文本回退）
    """
    s = str(name or "")
    if not s:
        return s, ""
    if s[-1] in DUP_CIRCLED:
        return s[:-1], str(DUP_CIRCLED.index(s[-1]) + 1)
    if s[-1].isdigit():                 # ⚠️ 必须在带圈数字那支**之后**：'①'.isdigit() 也是真
        i = len(s)
        while i > 0 and s[i - 1].isdigit():
            i -= 1
        if i > 0:                       # 全是数字的名字不当序数（基名不能为空）
            return s[:i], s[i:]
        return s, ""
    if s.endswith(")"):
        head, sep, tail = s.rpartition("(")
        if sep and head and tail[:-1].isdigit():
            return head, sep + tail
    return s, ""


def plain_name(name):
    """纯文本场景用的名字：重名序数**归一成数字**（`王贲①` → `王贲1`）。

    `ttk.Treeview` / `tk.Label` 这类纯文本控件做不了角标、也没法只给序数上灰 ——
    角标那一套只存在于画布（主树 / 时间轴）。这里统一成数字，
    免得老档在表格里是「王贲①」、画布上却是「王贲1」。
    """
    base, dup = split_dup(name)
    return (base + dup) if dup else str(name or "")


# ============================================================ 六、统一解码入口
class Decoded:
    """解码结果：`text` 是给人看的，`note` 说明这是推出来的还是原样。"""
    __slots__ = ("text", "note")

    def __init__(self, text, note=""):
        self.text = text
        self.note = note

    def __str__(self):
        return self.text


def code_of(field: str, value):
    """字段 + 值 → 中文。查不到就返回 None（**不猜**）。"""
    table = VALUE.get(field)
    if table is None:
        return None
    try:
        return table.get(value)
    except TypeError:
        return None


def region_of(value, era="秦末"):
    """族域码 → 中文。**码表按剧本分档**：上古档的 0-5 是文化地理区，不是族域。

    `era` 传 "上古" 走地理区表，其余走族域表。
    """
    table = VALUE["Ren_Zu_Yu_上古"] if "上古" in str(era) else VALUE["Ren_Zu_Yu"]
    try:
        return table.get(value)
    except TypeError:
        return None


def decode(field: str, value):
    """把「一个字段的取值」翻成中文可读文本。

    返回 `Decoded`。没把握的一律原样返回，绝不用猜测糊弄。
    """
    if value is None:
        return Decoded("—", "空值")
    if value == "":
        return Decoded("", "空字符串")

    # 时间三元组
    if field in TIME_FIELDS or (isinstance(value, str) and "," in value
                                and re.fullmatch(r"-?\d+,\d+,\d*", value.strip())):
        h = humanize_time(value)
        if h:
            return Decoded(h, "时间")

    # 富文本
    if isinstance(value, str) and "<" in value and ">" in value:
        cleaned = strip_rich(value)
        if cleaned != value:
            return Decoded(cleaned, "已剥离富文本")

    # 数字码
    if field in ("Ren_Leve", "Ren_Level"):
        zh = leve_label(value)          # 等级有男女两段，走专用函数
        if zh:
            return Decoded(zh, "已译码")
    zh = code_of(field, value)
    if zh:
        return Decoded(zh, "已译码")

    # ★ 2026-09-22：技术编号（`Buff_Code` 形如 `Technology_1103`）
    if isinstance(value, str) and value.startswith("Technology_"):
        num = value.split("_", 1)[1]
        nm = EFFECT_NAME[40].get(num)
        if nm:
            return Decoded("%s（%s）" % (nm, num), "已译码")

    return Decoded(str(value))


def value_label(field: str, value):
    """便捷：只要文本。"""
    return decode(field, value).text


# ============================================================ 七、家族 / 表族
# 表族 → 分类（给 GUI 左导航用）
#
# ★ 2026-09-21 去掉 `Save_ED_Ren_Data`：它的字段 schema 与 `Save_Ren_Data`
#   完全一致（26 个字段一一对应），只是分表存放（118 条 vs 3568 条），
#   属于同一批数据的分片；挂个「已故（旧表）」的独立节点会误导。
CATEGORY_OF = {
    "人物": ["Save_Ren_Data", "Save_Dead_Ren_Data", "Save_Woman_Data",
             "Save_Chu_Sheng_Data", "Save_King_Death_Data"],
}
