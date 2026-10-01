# -*- coding: utf-8 -*-
"""无界面冒烟测试：把「加载 → 中文化 → 关系图 → 建表 → 渲染单元格」整条链走一遍，
不弹窗口。用来在没有显示器的环境下抓语法/逻辑错误。"""
import io
import json
import os
import shutil
import subprocess
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 实录槽的根目录（17/18 段要直接读存档验证世系）
RECORD_BASE_CANDIDATE = r"D:\DevCache\dzlgz"
sys.path.insert(0, ROOT)

OUT = os.path.join(ROOT, "_stats", "smoke.txt")
buf = io.StringIO()
def w(s=""):
    buf.write(str(s) + "\n")

fails = []
def step(name, fn):
    try:
        r = fn()
        w(f"  [OK]   {name}" + (f" → {r}" if r else ""))
        return r
    except Exception as e:
        w(f"  [FAIL] {name} → {type(e).__name__}: {e}")
        w("        " + traceback.format_exc().replace("\n", "\n        ")[:1400])
        fails.append(name)
        return None

w("=" * 74)
w("冒烟测试：大周列国志 · 存档阅览器")
w("=" * 74)

w("\n1) 模块导入")
L = step("import labels", lambda: __import__("app.labels", fromlist=["x"]) and "ok")
C = step("import catalog", lambda: __import__("app.catalog", fromlist=["x"]) and "ok")
S = step("import saveload", lambda: __import__("app.saveload", fromlist=["x"]) and "ok")
R = step("import relations", lambda: __import__("app.relations", fromlist=["x"]) and "ok")
TH = step("import theme", lambda: __import__("app.theme", fromlist=["x"]) and "ok")
PF = step("import profiles", lambda: __import__("app.profiles", fromlist=["x"]) and "ok")

from app import labels as L       # noqa: E402
from app import catalog as C      # noqa: E402
from app import profiles as PF    # noqa: E402
from app import relations as R    # noqa: E402
from app import saveload as S     # noqa: E402

w("\n2) 写回代码是否已彻底移除（应该全部不存在）")
for fn in ("backup_slot", "_detect_format", "_FORMAT_CANDIDATES", "detect_format",
           "rewrite_unchanged", "plan_changes", "apply_plan", "apply_changes"):
    has = hasattr(S, fn)
    mark = "OK 已移除" if not has else "!! 仍然存在"
    w(f"  [{mark}] saveload.{fn}")
    if has:
        fails.append("写回残留 " + fn)
w(f"  源码里还有 shutil / time 的 import 吗："
  f"{'有（需清理）' if 'import shutil' in open(os.path.join(ROOT,'app','saveload.py'),encoding='utf-8').read() else '无'}")

w("\n3) labels 关键映射抽查")
checks = [
    ("Ren_Sex", 0, "男"), ("Ren_Sex", 1, "女"),
    ("King_Jue_Wei_Code", 3, "王"), ("King_Jue_Wei_Code", 5, "侯"),
    ("King_Jue_Wei_Code", 7, "子"), ("King_Jue_Wei_Code", 46, "西域城主"),
    ("Ren_Zu_Yu", 0, "中夏"),
    # ★ 2026-09-22 存档考古新增的映射
    ("Neng_Li_Or_Zheng_Ce", 40, "技术"),
    ("Neng_Li_Or_Zheng_Ce", 16, "奇观"),
    ("Neng_Li_Or_Zheng_Ce", 41, "先父余威"),
    ("Cur_Era", 10003, "黑铁时代"),
    ("Cur_Era", 10004, "作物优化"),
]
# ⚠ 曾经这里有一条 `("Wai_Jiao_Guan_Xi", 30, "同盟")` —— **已删除**。
#   实测该字段是 0~200 的**好感度数值**（16576 条、无负数），
#   不是「中立/同盟/敌对」枚举；关系状态请读 `Wai_Jiao_Zhuang_Tai`。
for field, val, want in checks:
    got = L.code_of(field, val)
    ok = got == want
    w(f"  [{'OK' if ok else 'FAIL'}] {field}={val} → {got}（期望 {want}）")
    if not ok:
        fails.append(f"map {field}={val}")

w("\n4) 时间人性化（紧凑格式 -1106.01）")
for raw, want in (("-244,1,0", "-244.01"),
                  ("-209,7,0", "-209.07"),
                  ("1066,3,12", "1066.03"),
                  ("-1106,0,0", "-1106")):
    got = L.humanize_time(raw)
    ok = got == want
    w(f"  [{'OK' if ok else 'FAIL'}] {raw} → {got}（期望 {want}）")
    if not ok:
        fails.append(f"time {raw}")
# 长格式仍可用于详情小字
for raw, want in (("-1106,1,0", "公元前 1106 年 1 月"),):
    got = L.humanize_time_long(raw)
    ok = got == want
    w(f"  [{'OK' if ok else 'FAIL'}] 长格式 {raw} → {got}")
    if not ok:
        fails.append(f"longtime {raw}")

w("\n5) 富文本剥离")
rich = '<color=#FF6A00>子文皇</color>'
got = L.strip_rich(rich)
w(f"  {'OK' if got == '子文皇' else 'FAIL'} {rich} → {got}")

w("\n6) 字段名覆盖率复核")
names = []
import re  # noqa: E402
pat = re.compile(r"^([A-Za-z_][\w\[\].]*)\t")
_leaf = os.path.join(ROOT, "_stats", "leafnames.txt")
if not os.path.isfile(_leaf):
    # fixture 不在就跳过，不让整轮冒烟崩掉（它只是覆盖率抽样，不是硬依赖）
    w(f"  [SKIP] 缺 {os.path.relpath(_leaf, ROOT)}（字段覆盖率抽样跳过）")
    w("        想跑就把原项目 _stats/leafnames.txt 拷过来")
else:
    with open(_leaf, encoding="utf-8") as f:
        for line in f:
            m = pat.match(line)
            if m:
                base = re.sub(r"\[\d*\]", "", m.group(1)).split(".")[-1]
                names.append(base)
    uniq = list(dict.fromkeys(names))
    miss = [n for n in uniq if L.field_label(n) == n]
    w(f"  唯一字段 {len(uniq)} 个，未翻译 {len(miss)} 个")
    if miss:
        w("  " + "、".join(miss[:20]))
        fails.append("字段未翻译 " + str(len(miss)))

w("\n7) 真实存档：加载 + 关系图 + 中文化渲染")
slot = step("加载 Save_All_1", lambda: S.SaveSlot(r"D:\DevCache\dzlgz\Save_All_1").load())
if slot:
    w(f"       {slot.summary()}")
    g = step("构建关系图", lambda: R.RelationGraph.build(slot))
    if g:
        for k, v in g.stats().items():
            w(f"       {k} = {v}")
    # 中文化一个人
    if g:
        hits = g.search("嬴政", limit=1)
        if hits:
            code, p = hits[0]
            prof = g.profile(code)
            w(f"       嬴政（{code}）关系：")
            for k, v in prof.items():
                if v:
                    w(f"         {k}: " + "、".join(
                        (r.note + "(占位)") if r.placeholder
                        else (r.person.name if r.person else "?") for r in v[:8]))
    # 单元格渲染（`_cell` 随 gui.py 拆件搬到了 views/person_view.py）
    t = slot.tables.get("Save_KingData")
    if t and t.rows:
        r = t.rows[0]
        from app.views.person_view import PersonView
        cells = []
        for k in ("King_Code", "King_Name", "King_Jue_Wei_Code",
                  "King_Stage", "Jian_Guo_Year", "King_Last_Ren_Total"):
            if k in r:
                cells.append(f"{C.label_of(k)}={PersonView._cell(r.get(k), k)}")
        w("       国家总表首行渲染：" + " | ".join(cells))

    # 交叉引用解析
    from app.xref import XRef
    try:
        x = XRef.build(slot)
        w("       交叉引用索引：" + str(x.stats()))
        # 找一个人试
        tr = slot.tables.get("Save_Ren_Data")
        if tr and tr.rows:
            a = tr.rows[0]
            code = a.get("Ren_Cheng_Shi_Code")
            hit = x.resolve("Ren_Cheng_Shi_Code", code)
            w(f"       Ren_Cheng_Shi_Code={code} → {hit}")
            sp = None
            for rr in tr.rows:
                if rr.get("Ren_Pei_Ou_Code_Array"):
                    sp = rr
                    break
            if sp:
                nm = x.resolve_many("Ren_Pei_Ou_Code_Array",
                                    sp["Ren_Pei_Ou_Code_Array"])
                w(f"       {sp.get('Ren_Name')} 配偶 {sp['Ren_Pei_Ou_Code_Array']} → {nm}")
    except Exception as e:
        w(f"       [FAIL] 交叉引用 {type(e).__name__}: {e}")
        fails.append("交叉引用")

w("\n8) 主题 tier 色是否齐全")
from app import theme as TH  # noqa: E402
need = {"帝", "王", "公", "侯", "伯", "子", "卿", "无"}
for key, t in TH.THEMES.items():
    missing = need - set(t.tier.keys())
    w(f"  [{'OK' if not missing else 'FAIL'}] {key} 缺 {missing or '无'}")

w("\n9) v0.4 人物等级：男性五级「邦上中下庶」/ 女性五级「美佳淑丽良」（无女字前缀）")
for code, want in ((0, "庶"), (1, "下"), (2, "中"), (3, "上"), (4, "邦"),
                   (10, "圣"), (11, "神"), (5, "将"), (6, "臣"),
                   (7, "君"), (8, "豪"),
                   (100, "美"), (101, "佳"), (102, "淑"),
                   (103, "丽"), (104, "良"), (105, "哲")):
    got = L.leve_label(code)
    ok = got == want
    w(f"  [{'OK' if ok else 'FAIL'}] Ren_Leve={code} → {got}（期望 {want}）")
    if not ok:
        fails.append(f"leve {code}")
# 「圣」必须是**单独的等级**，不能混进五级，也不能和「神」混淆
if L.leve_label(10) != "圣" or L.leve_label(11) != "神" or L.leve_label(9) is not None:
    w("  [FAIL] 圣=10 / 神=11 定义不对（9 不应有名字）")
    fails.append("圣/神 码值")
else:
    w("  [OK] 圣=10、神=11 独立成级；9 无名字（存档里不出现）")

w("\n10) v0.3 史实人物判定（编号 ≤5 位数，**或非纯数字编号**）")
# ★ 2026-09-25：字母编号（QIN001 章蟜 / WEI001 公叔痤…）也是游戏**写死的具名
#   人物**（使用者裁定归史实），不能落进「非史」。
for code, want in (("162", True), ("2306", True), ("60004", True), ("99999", True),
                   ("100000013", False), ("1000001", False), ("", False),
                   ("100000", False), ("QIN001", True), ("WEI003", True)):
    got = PF.is_historical(code)
    ok = got == want
    w(f"  [{'OK' if ok else 'FAIL'}] {code!r} → {'史实' if got else '生成'}"
      f"（期望 {'史实' if want else '生成'}）")
    if not ok:
        fails.append(f"hist {code}")

w("\n11) v0.3 卒年 = 生年 + 享年（公元前负数相加，紧凑格式）")
for birth, old, want in (("-2517,1,0", 96, "-2421.01"),
                         ("-244,3,0", 59, "-185.03"),
                         ("-2590,1,0", 67, "-2523.01")):
    txt, note = PF.calc_death(birth, old)
    ok = txt == want
    w(f"  [{'OK' if ok else 'FAIL'}] 生年 {birth} + 享年 {old} → {txt}"
      f"（期望 {want}；{note}）")
    if not ok:
        fails.append(f"death {birth}+{old}")

w("\n11b) v0.3 卒年走 Profile 渲染链路（防止二次格式化）")
_p = PF.Profile("1", {"Ren_Code": "1", "Ren_Name": "测试",
                      "Ren_Chu_Sheng_Time": "-2517,1,0", "Ren_End_Old": 96}, None, "上古")
_v = _p.value_of("death")
ok = _v == "-2421.01"
w(f"  [{'OK' if ok else 'FAIL'}] Profile.value_of('death') → {_v}（期望 -2421.01）")
if not ok:
    fails.append("Profile 卒年渲染")
# 存档直接给卒年的情况
_p2 = PF.Profile("2", {"Ren_Code": "2", "Ren_Name": "测试2",
                       "Ren_Chu_Sheng_Time": "-500,1,0", "Ren_End_Time": "-450,3,0"},
                 None, "上古")
_v2 = _p2.value_of("death")
ok2 = _v2 == "-450.03"
w(f"  [{'OK' if ok2 else 'FAIL'}] 存档直接记录卒年 → {_v2}（期望 -450.03）")
if not ok2:
    fails.append("存档卒年渲染")

w("\n11c) v0.4 世代 -1 显示为「始祖」")
_p3 = PF.Profile("3", {"Ren_Code": "3", "Ren_Name": "始祖测试", "Ren_Dai_Shu": -1},
                 None, "上古")
_g = _p3.value_of("daishu")
ok3 = _g == "始祖"
w(f"  [{'OK' if ok3 else 'FAIL'}] Ren_Dai_Shu=-1 → {_g}（期望 始祖）")
if not ok3:
    fails.append("世代始祖显示")

w("\n12) v0.3 容貌字段被隐藏")
hidden_ok = ("Ren_Face" in PF.HIDDEN_FIELDS)
w(f"  [{'OK' if hidden_ok else 'FAIL'}] Ren_Face 在 HIDDEN_FIELDS 中")
if not hidden_ok:
    fails.append("Ren_Face 没被隐藏")

w("\n12b) v0.4 人物表格不列「所在」「史实」")
tbl_ok = ("所在" not in PF.TABLE_COLS) and ("史实" not in PF.TABLE_COLS)
# ★ 2026-09-24 使用者要求：删掉末尾的「世代」「编号」（要横滚才看得到），
#   并在智略之后插入新的「年龄」列。
tbl_ok = (tbl_ok and "世代" not in PF.TABLE_COLS and "编号" not in PF.TABLE_COLS
          and "年龄" in PF.TABLE_COLS
          and list(PF.TABLE_COLS).index("年龄") == list(PF.TABLE_COLS).index("智略") + 1)
# ★ 2026-09-25 使用者要求：「人物界面做出 1 个标签，身份」（主 / 谥 / 官，其余留空），
#   插在姓名之后；谥号进详情卡。
tbl_ok = (tbl_ok and "身份" in PF.TABLE_COLS
          and list(PF.TABLE_COLS).index("身份") == list(PF.TABLE_COLS).index("姓名") + 1
          and "谥号" in [zh for zh, _k in PF.PROFILE_ORDER])
w(f"  [{'OK' if tbl_ok else 'FAIL'}] TABLE_COLS = {list(PF.TABLE_COLS)}")
if not tbl_ok:
    fails.append("TABLE_COLS 口径不符（不该有 所在/史实/世代/编号；「年龄」紧跟智略、"
                 "「身份」紧跟姓名，详情卡要有「谥号」）")
# 字段悬停解释表要覆盖所有显示字段
help_missing = [c for c in PF.TABLE_COLS if c not in PF.FIELD_HELP]
help_missing += [zh for zh, _k in PF.PROFILE_ORDER if zh not in PF.FIELD_HELP]
w(f"  [{'OK' if not help_missing else 'FAIL'}] 缺悬停解释的字段：{help_missing or '无'}")
if help_missing:
    fails.append("FIELD_HELP 缺 " + ",".join(help_missing))

w("\n12c) v0.4「找不到人」时也要有返回键")
# _show_missing_person 分支必须在 return 前调用 _paint_act_bar，
# 否则用户点进一个查不到的编号后会被困在关系视图里（v0.4 实测踩过）。
# 史馆把 gui.py 拆成了 views/person_view.py —— 断言跟着走。
_VIEW_SRC = os.path.join(ROOT, "app", "views", "person_view.py")
_blk = open(_VIEW_SRC, encoding="utf-8").read()
_i = _blk.find("self._show_missing_person(code)")
_seg = _blk[_i:_i + 260] if _i >= 0 else ""
miss_ok = (_i >= 0) and ("_paint_act_bar()" in _seg)
w(f"  [{'OK' if miss_ok else 'FAIL'}] missing-person 分支后紧跟 _paint_act_bar()")
if not miss_ok:
    fails.append("缺人分支没刷新固定操作条")

w("\n13) v0.3 人物详情字段顺序")
want_order = ["姓名", "身份", "性别", "智略", "年龄", "等级", "谥号", "生年", "卒年",
              "余寿", "文化", "性格", "势力", "世代", "所在", "编号"]
got_order = [zh for zh, _k in PF.PROFILE_ORDER]
ok = got_order == want_order
w(f"  [{'OK' if ok else 'FAIL'}] {got_order}")
if not ok:
    fails.append("PROFILE_ORDER 顺序不对")

w("\n14) v0.3 不再出现「（原值 x）」调试后缀")
gui_src = open(_VIEW_SRC, encoding="utf-8").read()
ok = "（原值" not in gui_src
w(f"  [{'OK' if ok else 'FAIL'}] person_view.py 里没有「（原值」字样")
if not ok:
    fails.append("person_view.py 仍有「（原值」")

w("\n14b) v0.4 双击启动器（Start.bat + Start.vbs）")
# 启动器负责自动挑一个「带 tkinter 的 Python」。托管 Python 没编译 tkinter，
# 用它会直接报 ModuleNotFoundError，所以 .bat 里必须逐个试。
#
# ★ 三条硬约束（都是实测踩出来的，改一处就会「双击没反应」）：
#   1) 文件名必须纯 ASCII —— 曾用「启动 大周列国志·存档阅览器.bat」，
#      文件名里的 U+00B7（·）不是 GBK 可表示字符，explorer 双击时静默失败。
#   2) 编码必须 GBK、且不能带 BOM —— cmd 按系统 ANSI(936) 读 .bat，
#      带 UTF-8 BOM 会把 BOM 当成 @echo off 的一部分，第一行就报错。
#      WSH 读 .vbs 同理，UTF-8 必乱码。
#   3) 不能出现 «call :label» / «else if» —— 标签跳转才稳。
_launchers = {
    "Start.bat": {
        "enc": "gbk",
        "needles": ["import tkinter", "main.py", "py -3", ":nopython"],
        "forbid": ["call :", "else if", "chcp 65001"],
    },
    "Start.vbs": {
        "enc": "gbk",
        "needles": ["shell.Run", "WScript.ScriptFullName", "Start.bat"],
        "forbid": [],
    },
}
for _fn, _spec in _launchers.items():
    _p = os.path.join(ROOT, _fn)
    if not os.path.isfile(_p):
        w(f"  [FAIL] 缺启动器：{_fn}")
        fails.append(f"缺启动器 {_fn}")
        continue
    # 文件名纯 ASCII 自检
    _ascii_ok = _fn.isascii()
    _b = open(_p, "rb").read()
    _has_bom = _b[:3] == b"\xef\xbb\xbf"
    # 按 GBK 解码（编码不对会在这里抛异常）
    try:
        _txt = _b.decode(_spec["enc"])
        _dec_ok = True
    except UnicodeDecodeError:
        _txt = _b.decode("latin-1")
        _dec_ok = False
    _missing = [n for n in _spec["needles"] if n not in _txt]
    # 找禁用写法时必须先剔除注释行 —— 否则 REM 里「不用 else if」这种说明
    # 会被误判成真用了 else if
    if _fn.lower().endswith(".bat"):
        _code = "\n".join(
            ln for ln in _txt.splitlines()
            if not ln.strip().upper().startswith(("REM", "::"))
        )
    else:
        _code = "\n".join(
            ln for ln in _txt.splitlines()
            if not ln.strip().startswith("'")
        )
    _banned = [n for n in _spec["forbid"] if n in _code]
    _zh = sum(1 for c in _txt if "\u4e00" <= c <= "\u9fff")
    _ok = (_ascii_ok and not _has_bom and _dec_ok
           and not _missing and not _banned)
    w(f"  [{'OK' if _ok else 'FAIL'}] {_fn}"
      f"  ASCII={'是' if _ascii_ok else '否'}"
      f"  BOM={'有' if _has_bom else '无'}"
      f"  GBK可读={'是' if _dec_ok else '否'}"
      f"  中文={_zh}字"
      f"  缺={_missing or '无'}"
      f"  忌={_banned or '无'}")
    if not _ok:
        fails.append(f"{_fn} 不合规")

# ★ 14b-2) .vbs 的 shell.Run 行必须有正确的引号。
# 真实事故：生成器用 Python 三引号字面量内联四组双引号，被定界符截断，
# 生成出 `shell.Run  & batPath & , 0, False`（裸 & 运算符）——
# WSH 直接语法错误 → 双击完全没反应，且不弹任何提示。极难排查。
# 正确写法（VBScript 里一个引号要写两个）：
#     shell.Run """" & batPath & """", 0, True
# 最后那个 True = 等 .bat 跑完再返回，这样才能拿到返回码提示失败原因。
_vbs_p = os.path.join(ROOT, "Start.vbs")
if os.path.isfile(_vbs_p):
    _vt = open(_vbs_p, encoding="gbk").read()
    # 本项目的 .vbs 把返回码接进变量（`rc = shell.Run(...)`），
    # 所以不能只找以 "shell.run" 开头的行 —— 找**包含**它的那一行。
    _run = [ln.strip() for ln in _vt.splitlines() if "shell.run" in ln.lower()]
    _Q = chr(34)
    _want = _Q * 4 + " & batPath & " + _Q * 4
    _ok = bool(_run) and _want in _run[0] and ", 0, True" in _run[0]
    w(f"  [{'OK' if _ok else 'FAIL'}] Start.vbs 的 shell.Run 引号写法")
    w(f"        {_run[0] if _run else '（找不到 shell.Run 行）'}")
    if not _ok:
        fails.append("Start.vbs 的 shell.Run 行引号不对")

# ★ 14b-3) MsgBox 必须一行写完 —— VBScript 换行续接要行尾 `_`，
# 把参数拆到下一行（哪怕缩进对齐）会报「缺少语句」，双击依然静默失败。
# 校验法：cscript //Nologo Start.vbs，语法错 rc=1 且 stderr 带行列号。
if os.path.isfile(_vbs_p):
    _bad_msg = [ln.strip() for ln in _vt.splitlines()
                if ln.strip().startswith((",", "&"))]
    w(f"  [{'OK' if not _bad_msg else 'FAIL'}] Start.vbs 无跨行断开的语句"
      f"{'（有：' + str(_bad_msg[:2]) + '）' if _bad_msg else ''}")
    if _bad_msg:
        fails.append("Start.vbs 有跨行断开的语句")

w("\n14c) v0.4 模拟器同步脚本存在性")
_sync = os.path.join(ROOT, "tools", "sync_from_mumu.py")
if not os.path.isfile(_sync):
    w("  [FAIL] 缺 tools/sync_from_mumu.py")
    fails.append("缺 sync_from_mumu.py")
else:
    _stxt = open(_sync, encoding="utf-8").read()
    # 关键点：必须带 -s（否则 more than one device）、必须用 ? 通配反斜杠目录名、
    # 必须 cd 到英文目录再 pull（中文路径 adb 会失败）、必须 adb root
    _need = {
        '"-s", SERIAL': "-s 指定设备",
        "}?Save_All_*": "? 通配反斜杠目录名",
        "os.chdir(tmp)": "pull 前切英文目录",
        '["root"]': "adb root",
    }
    _miss = [v for k, v in _need.items() if k not in _stxt]
    w(f"  [{'OK' if not _miss else 'FAIL'}] sync_from_mumu.py 关键逻辑"
      f"  缺：{_miss or '无'}")

w("\n16) M1 两层契约（app/contract.py）")
try:
    from app import contract as CT
    _views = list(CT.VIEWS)
    _keys = list(CT.VIEW_KEYS)
    # ★ 2026-09-23 独立「时间轴」页签并入家谱：四页签 + FAMILY_MODES 契约
    _ok_n = len(_views) == 4
    _ok_key = _keys == ["person", "tree", "world", "table"]
    _rec = {k for k, _l, _i, ly in _views if ly == "record"}
    _edit = {k for k, _l, _i, ly in _views if ly == "edit"}
    _ok_layer = (_rec == {"person", "world"} and _edit == {"tree", "table"})
    _ok_fam = (CT.FAMILY_MODES == ("gen", "time")
               and CT.FAMILY_MODE_LABEL == {"gen": "代际", "time": "时间"})
    w(f"  [{'OK' if _ok_n else 'FAIL'}] 四页签：{_keys}")
    w(f"  [{'OK' if _ok_layer else 'FAIL'}] 两层归属"
      f"  实录={sorted(_rec)}  谱牒={sorted(_edit)}")
    w(f"  [{'OK' if _ok_fam else 'FAIL'}] 家谱双模式={CT.FAMILY_MODES}")
    w(f"  [{'OK' if CT.DEFAULT_VIEW in _keys else 'FAIL'}] "
      f"默认页签 = {CT.DEFAULT_VIEW}")
    w(f"  [{'OK' if CT.LAYER_NAME.get('record') == '实录' else 'FAIL'}] "
      f"层名 = {CT.LAYER_NAME}")
    if not (_ok_n and _ok_key and _ok_layer and _ok_fam):
        fails.append("contract 契约不合规")
except Exception as _e:
    w(f"  [FAIL] contract 导入失败：{_e}")
    fails.append("contract 不可用")

w("\n16b) M1 派生视图独立于视图存在（app/record_derive.py）")
# 关键：默认页签可能是「表格」，那时不会建 PersonView。
# 派生表必须在**载入实录槽时**就推好，否则状态栏「实录 N 人」是 0、查档桥失效。
_rd = os.path.join(ROOT, "app", "record_derive.py")
if not os.path.isfile(_rd):
    w("  [FAIL] 缺 app/record_derive.py")
    fails.append("缺 record_derive.py")
else:
    _rtxt = open(_rd, encoding="utf-8").read()
    # 派生模块不许 import tkinter（否则不能在无界面环境跑）
    _no_tk = "tkinter" not in _rtxt
    w(f"  [{'OK' if _no_tk else 'FAIL'}] record_derive 不依赖 tkinter")
    if not _no_tk:
        fails.append("record_derive 依赖 tkinter")
    # main.py 必须在 open_record 里就推派生表（不是等视图建）
    _mtxt = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    _in_open = "self.record_people, self.record_hist = self._derive(slot)" in _mtxt
    w(f"  [{'OK' if _in_open else 'FAIL'}] open_record 里已推派生表")
    if not _in_open:
        fails.append("open_record 未推派生表")
    # 视图构造不得重读存档（30MB，重建视图会卡死）
    _pv = open(os.path.join(ROOT, "app", "views", "person_view.py"),
               encoding="utf-8").read()
    _guard = "if app.record_slot is not None:" in _pv
    w(f"  [{'OK' if _guard else 'FAIL'}] PersonView 构造不盲读存档")
    if not _guard:
        fails.append("PersonView 构造会重读存档")

w("\n16c) M1 无头模式（防止模态框挂死验收进程）")
from app.dialogs import forms as _forms      # noqa: E402
_has_h = hasattr(_forms, "headless")
w(f"  [{'OK' if _has_h else 'FAIL'}] forms.headless() 存在")
if not _has_h:
    fails.append("缺 headless() 开关")
else:
    _ftxt = open(os.path.join(ROOT, "app", "dialogs", "forms.py"),
                 encoding="utf-8").read()
    _finish_guard = "if headless():" in _ftxt
    w(f"  [{'OK' if _finish_guard else 'FAIL'}] ThemedDialog.finish 受无头开关保护")
    _mtxt2 = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    # ★ 2026-09-21 起**首启动不再弹主题框**（默认宣纸，想换去「设置」或 Ctrl+T），
    #   所以这条断言从「弹窗受无头开关保护」改成「弹窗已移除」——
    #   弹窗都没了，自然也不会挂死验收进程。
    _first_run = "after(200, self.open_theme_picker)" not in _mtxt2
    w(f"  [{'OK' if _first_run else 'FAIL'}] 首启动不弹主题框（已移除）")
    if not (_finish_guard and _first_run):
        fails.append("无头开关未覆盖全部模态框")
    if _miss:
        fails.append("sync_from_mumu.py 缺 " + ",".join(_miss))

w("\n15) v0.3 人物档案 + 世系（真实存档）")
if slot:
    from app.xref import XRef
    x = XRef.build(slot)
    tr = slot.tables.get("Save_Ren_Data")
    if tr and tr.rows:
        r0 = tr.rows[0]
        p = PF.Profile(str(r0.get("Ren_Code")), r0, x, "上古")
        w(f"       样例档案 {p.code} {p.name}：")
        for zh, val in p.rows():
            w(f"         {zh} = {val}")
        w(f"       史实判定 = {p.kind}")
    # 世系
    if g:
        hits = g.search("嬴政", limit=1)
        if hits:
            code = hits[0][0]
            lin = PF.Lineage(g).of(code)
            w(f"       嬴政世系：始祖 {lin['始祖'].name if lin['始祖'] else '?'}"
              f"，后裔 {len(lin['成员'])} 人")
            for d, pp in lin["成员"][:6]:
                w(f"         第{d}代 {pp.name}（{'史实' if PF.is_historical(pp.code) else '生成'}）")

w("\n17) 君主世系只认宗庙（「不是出仕或居住地就有世系，必须是该国君主的家族」）")
# 判据全部对着**真实存档**跑：需要一份「秦末」档（秦宗庙里必须有嬴异人 2275）。
# ★ 2026-09-24：原来写死 `Save_All_1 = 秦末` —— 而那是**使用者正在玩的槽**，
#   游戏一存档就把它覆盖掉（实测当天被两盘上古档覆盖两次），于是本节
#   `_lin["2275"]` 直接 KeyError，整份冒烟跑不完。
#   改成在 `Save_All_*`（含 .bak 备份）里**找**一份宗庙带嬴异人的当夹具；
#   一份都没有就按原样 SKIP（不再假死）。
#   ⚠️ 判据必须用**真解析器**（`load_king_lineage`），不能拿「文件里有没有
#      『2275』这几个字」当判据 —— 实测 `Save_All_4` 的宗庙文件里恰好含
#      2275 这几个字符（别的字段里的数字），粗筛会选中它，随后
#      `_lin["2275"]` 照样 KeyError。
sys.path.insert(0, os.path.join(ROOT, "tools"))
import import_from_game as IM  # noqa: E402


def _find_qin_fixture():
    for _n in sorted(os.listdir(RECORD_BASE_CANDIDATE)):
        _p = os.path.join(RECORD_BASE_CANDIDATE, _n)
        if not _n.startswith("Save_All_") or not os.path.isdir(_p):
            continue
        if not os.path.exists(os.path.join(_p, "Zong_Miao_Controller.json")):
            continue
        try:
            if "2275" in IM.load_king_lineage(_p):
                return _p
        except Exception:
            continue
    return ""


_SRC1 = _find_qin_fixture() or os.path.join(RECORD_BASE_CANDIDATE, "（本机无秦末档）")
if _SRC1 and os.path.isdir(_SRC1):
    w(f"  （秦末夹具：{os.path.basename(_SRC1)}）")
    _lin = IM.load_king_lineage(_SRC1)
    _real = {c: v for c, v in _lin.items() if not v["is_placeholder"]}
    w(f"       宗庙牌位 {len(_lin)} 张（真人 {len(_real)} · 占位 {len(_lin) - len(_real)}）")
    # a) 皇帝 / 王的区分 —— 由尊号推出，不是查历史
    _zun = {c: v["zun"] for c, v in _lin.items() if v["zun"]}
    _checks = [("2276", "始皇", "帝"), ("2275", "秦庄襄王", "王"),
               ("2274", "秦孝文王", "王"), ("2268", "秦惠文王", "王"),
               ("2266", "秦孝公", "公"),
               # 只有职位名、没有爵位的：推不出爵位就留空（宁缺勿猜）
               ("2237", "西陲大夫秦", ""),
               # 尊号是纯名号（少昊/太昊/雷祖）不含爵位字 → 空
               ("60051", "少昊", "")]
    for code, want_zun, want_rank in _checks:
        v = _lin.get(code)
        got_z = v["zun"] if v else None
        got_r = IM.zun_hao_rank(got_z) if got_z is not None else None
        ok = (got_z == want_zun) and (got_r == want_rank)
        _label = want_zun or "（空）"
        w(f"  [{'OK' if ok else 'FAIL'}] {code} 尊号={got_z!r} → 爵={got_r!r}"
          f"（期望 {_label!r} → {want_rank!r}）")
        if not ok:
            fails.append(f"{code} 尊号→爵 判定不符")
    # b) 二世承父为帝：胡亥本身尊号为空，但父亲是始皇 → 帝
    _hu = IM.inherit_rank("2279", _lin, {})
    w(f"  [{'OK' if _hu == '帝' else 'FAIL'}] 胡亥（尊号空·父=始皇）→ {_hu!r}"
      f"（期望 '帝'）")
    if _hu != "帝":
        fails.append("二世未承父为帝")
    # c) 父辈**不**因为儿子称帝而被追认为皇帝
    _yz = _lin["2275"]["rank"]
    w(f"  [{'OK' if _yz == '王' else 'FAIL'}] 嬴异人（始皇之父）→ {_yz!r}"
      f"（期望 '王'，不能是 '帝'）")
    if _yz != "王":
        fails.append("始皇之父被误判为帝")
    # d) 共同远祖被多庙共祭 → 不占任何一国封国
    _sh = [v for v in _real.values() if v.get("shared")]
    w(f"  [OK] 多庙共祭的共同远祖 {len(_sh)} 位（黄帝/燧人/伏羲/巢皇…），"
      f"不给封国")
    # e) 占位祖先被识别（名字+编号都带 父/祖/曾/高）
    _ph = sum(1 for v in _lin.values() if v["is_placeholder"])
    w(f"  [{'OK' if _ph > 0 else 'FAIL'}] 识别出游戏硬造的占位祖先 {_ph} 张")
    if _ph <= 0:
        fails.append("占位祖先未被识别")
    # f) 封代 = 牌位自带的 `Generations`（**游戏算的「本封国第几代」**）
    #    —— 使用者 2026-09-25 定的口径：「就像周初分封一样，**从分封第一代
    #    开始算起**」。旧口径 `_real_depth`（沿父链数真人）已废：它数的是
    #    **家族深度**，把本局才受封的熊心写成「熊国第 80 代国君」。
    _zo = None
    _zp = os.path.join(_SRC1, "Zong_Miao_Controller.json")
    if os.path.exists(_zp):
        try:
            _zo = json.load(open(_zp, encoding="utf-8-sig"))
        except Exception:
            _zo = None
    # f) 封代 ≡ 牌位 `Generations` − 「建国年重定基准」的偏移
    #    （见 `load_king_lineage` 里 rebase 那段）。偏移 > 0 只在**重新受封**的国上
    #    出现：某位国君的**即位年 == 本国建国年** ⇒ 他是始封之君、算第 1 代，
    #    而宗庙里他前面可能还排着游戏造的占位祖先（如宋义排第 5）。
    # ⚠️ 只比**真人**：占位祖先游戏也编号，但项目一直不给占位写封代（既定口径）。
    # ⚠️ 同一真人可能被**多庙共祭**（古公亶父出现在 19 座庙，各庙编号还不同），
    #    所以按「各庙算出的取值集合」判 —— 落在集合里即算对。这样既容忍共祭，
    #    又能抓出口径错（若退回旧 `_real_depth`，嬴政会是 71，不在 {30, 0} 里 → FAIL）。
    _gjy = {}
    for _f in sorted(os.listdir(_SRC1)):
        if not (_f.startswith("Save_KingData_") and _f.endswith(".json")):
            continue
        _k = IM._read(os.path.join(_SRC1, _f))
        if isinstance(_k, dict) and _k.get("King_Name") is not None \
                and isinstance(_k.get("Jian_Guo_Year"), (int, float)):
            _gjy[_k["King_Name"]] = int(_k["Jian_Guo_Year"])
    _per_code = {}
    for _z in ((_zo or {}).get("All_King_Zong_Miao_Array") or []):
        _arr = _z.get("All_Memorial_Array") or []
        _guo = ""
        for _m in _arr:
            _g3 = str(_m.get("Memorial_Ren_Now_King_Name") or "").strip()
            if _g3:
                _guo = _g3
                break
        _off = 0
        _jy = _gjy.get(_guo)
        if _jy is not None:
            _fo = None
            for _m in _arr:
                _bt = IM.parse_time(_m.get("Memorial_Ren_Become_Time"))
                _g4 = _m.get("Generations")
                if _bt and _bt[0] == _jy and isinstance(_g4, int) and _g4 > 0:
                    if _fo is None or _g4 < _fo:
                        _fo = _g4
            if _fo is not None and _fo > 1:
                _off = _fo - 1
        for _m in _arr:
            _c = str(_m.get("Memorial_Code") or "").strip()
            if not _c or IM.is_placeholder_memorial(_m):
                continue
            _g4 = _m.get("Generations")
            _v = _g4 if isinstance(_g4, int) and _g4 > 0 else 0
            _per_code.setdefault(_c, set()).add(_v - _off if _v > _off else 0)
    _gbad = [(c, _lin[c]["fief_gen"], sorted(_per_code[c]))
             for c in _lin
             if c in _per_code and _lin[c]["fief_gen"] not in _per_code[c]]
    w(f"  [{'OK' if not _gbad else 'FAIL'}] 封代 ≡ 牌位 Generations − 建国年偏移"
      f"（逐张比对真人牌位 {len(_per_code)} 张，应 0 违例）")
    if _gbad:
        w(f"        违例示例：{_gbad[:6]}")
        fails.append("封代与牌位 Generations/建国年 不符")
    # f2) 沿父链递增：父子都在庙内且都有封代时，父 < 子（0 违例）
    _mbad, _mpair = [], 0
    for _z in ((_zo or {}).get("All_King_Zong_Miao_Array") or []):
        _tb = _z.get("All_Memorial_Array") or []
        _by = {str(m.get("Memorial_Code")): m for m in _tb}
        for _m in _tb:
            _c = str(_m.get("Memorial_Code") or "").strip()
            _f = _by.get(str(_m.get("Father_Code") or "").strip())
            if not _f or _c not in _lin or str(_f.get("Memorial_Code")) not in _lin:
                continue
            _a = _lin[_c]["fief_gen"]
            _b = _lin[str(_f.get("Memorial_Code"))]["fief_gen"]
            if _a > 0 and _b > 0:
                _mpair += 1
                if _b >= _a:
                    _mbad.append((_f.get("Memorial_Name"), _b,
                                  _m.get("Memorial_Name"), _a))
    w(f"  [{'OK' if not _mbad else 'FAIL'}] 封代沿父链递增"
      f"（{_mpair} 组父子对，0 违例）")
    if _mbad:
        w(f"        违例示例：{_mbad[:6]}")
        fails.append("封代沿父链未递增")
    # f3) 「从分封第一代开始算起」：游戏把每座宗庙的第一代标为 Generations==1，
    #     项目原样沿用（不重排、不偏移），所以必然存在一批「封代 == 1」的君主。
    #     ⚠️ 不写死具体人名 —— 夹具是「秦末」档，但具体是哪一份备份会变。
    _ones = [c for c, v in _lin.items() if v["fief_gen"] == 1]
    _sample = "、".join(f"{_lin[c]['guo']}·{_lin[c]['zun'] or _lin[c]['name']}"
                       for c in _ones[:4])
    w(f"  [{'OK' if _ones else 'FAIL'}] 各封国第一代共 {len(_ones)} 位"
      f"（封代 == 1，从分封第一代算起；如 {_sample}）")
    if not _ones:
        fails.append("没有任何封代 == 1 的君主（分封第一代未从 1 起算）")
    # g) 导入产物：非君主不得带爵位（父系继承已删除）
    _verify = os.path.join(ROOT, "_scratch", "_smoke36")
    _rc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "tools", "import_from_game.py"),
         "--src", _SRC1, "--save", "_smoke36", "--real-state-only"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=ROOT)
    _vp = os.path.join(ROOT, "saves", "_smoke36", "family.json")
    if os.path.exists(_vp):
        _vo = json.load(open(_vp, encoding="utf-8"))
        _ppl = _vo["people"]
        _titled = sum(1 for v in _ppl.values() if v.get("fief_title"))
        # ★ 2026-09-25 口径变了：爵位从「只认尊号」扩到「尊号推不出时用**国爵**兜底」
        #   （使用者：「每一代国君的爵位大差不差都是一样的」）→ 有爵位的人变多是**对的**。
        #   真正要守的不变式换成：**有爵位的人必须有世系**（= 宗庙里的人）。
        #   宗庙先世虽封代 0，但尊号（周文王 / 楚怀王 / 夏后帝…）本身就是真爵位，
        #   他们合法；该挡住的是**平民 / 功臣**（修前 1149 那批父系继承的错判）。
        _bad = [n for n, v in _ppl.items()
                if v.get("fief_title") and not v.get("lineage_name")]
        _ok = (not _bad) and _titled < 800
        w(f"  [{'OK' if _ok else 'FAIL'}] 有爵位 {_titled} 人，其中**无世系**（平民/功臣）"
          f"的 {len(_bad)} 人（应为 0；修前 1149 全是父系继承的错判）")
        if _bad:
            w(f"        示例：{_bad[:6]}")
        if not _ok:
            fails.append(f"爵位越界：{len(_bad)} 人无世系却有爵位")
        # 抽查：非君族不得有封国爵位
        for nm in ("任敖", "灌婴"):
            v = _ppl.get(nm)
            if v is not None:
                good = not v.get("fief_title")
                w(f"  [{'OK' if good else 'FAIL'}] {nm}（汉功臣）爵位={v.get('fief_title')!r}"
                  f"（期望空）")
                if not good:
                    fails.append(f"{nm} 被误封爵")
        # 世系字段独立于势力
        _cy = _ppl.get("陈胜")
        if _cy is not None:
            w(f"       陈胜：势力={_cy.get('state_name')!r} "
              f"世系={_cy.get('lineage_name')!r}")
        # source 元数据已写入（谱牒↔实录一一对应的接缝）
        w(f"  [{'OK' if _vo.get('source', {}).get('slot') else 'FAIL'}] "
          f"导入产物带 source.slot = {_vo.get('source', {}).get('slot')!r}")
        if not _vo.get("source", {}).get("slot"):
            fails.append("import 未写 source")
    shutil.rmtree(os.path.join(ROOT, "saves", "_smoke36"), ignore_errors=True)
else:
    w(f"  （找不到 {_SRC1}，跳过）")

w("\n18) 谱牒 ↔ 实录 一一对应（family.json 的 source 元数据）")
from app import storage as _ST
_ss = _ST.load_source("文王治岐")
w(f"  [{'OK' if _ss.get('slot') else 'FAIL'}] 文王治岐 的来源槽 = {_ss.get('slot')!r}"
  f" · 剧本 {_ss.get('era')!r}")
if not _ss.get("slot"):
    fails.append("文王治岐 没有 source")
_ss2 = None
# ★ 2026-09-21：不再写死《秦末起义·史实》—— 使用者会删档（实测把这部删了），
#   写死会让冒烟跟着红。改成「挑一部**带 source 且不是文王治岐**的谱牒来验」。
_cands = [n for n in _ST.list_saves()
          if n != "文王治岐" and (_ST.load_source(n) or {}).get("slot")]
if _cands:
    _nm2 = _cands[0]
    _ss2 = _ST.load_source(_nm2)
    _own = _ss2.get("slot")
    w(f"  [{'OK' if _own else 'FAIL'}] {_nm2} 的来源槽 = {_own!r}")
    if not _own:
        fails.append(f"{_nm2} 来源槽不对")
else:
    w("  [SKIP] 没有第二部带 source 的谱牒（使用者删档了）")
# 向后兼容：没有 source 的老档也能读
_p3, _c3, _s3 = _ST.load_save_full("文王治岐")
w(f"  [{'OK' if len(_p3) > 0 else 'FAIL'}] load_save_full 兼容读出 {len(_p3)} 人")
if not _p3:
    fails.append("load_save_full 读不出人")
# main.py 里得有绑定链路
_mt = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
for _need, _desc in (("_slot_for_save", "按 source 找槽"),
                     ("bind_save_to_record", "切谱牒时同步实录"),
                     ("switch_save", "切换入口接上同步")):
    w(f"  [{'OK' if _need in _mt else 'FAIL'}] main.py 有 {_desc}（{_need}）")
    if _need not in _mt:
        fails.append(f"main.py 缺 {_need}")

w("\n19) 「已故（旧表）」等冗余 label 已清除")
_cat = open(os.path.join(ROOT, "app", "catalog.py"), encoding="utf-8").read()
w(f"  [{'OK' if 'Save_ED_Ren_Data' not in _cat else 'FAIL'}] "
  f"catalog.py 不再有「已故（旧表）」表族")
if "Save_ED_Ren_Data" in _cat:
    fails.append("catalog 仍有旧表")
_rdsrc = open(os.path.join(ROOT, "app", "record_derive.py"),
              encoding="utf-8").read()
# 只在**代码**里查（PERSON_TABLES 那一段），不含注释 —— 注释里提到旧表名是正常的
_rdcode = "\n".join(ln for ln in _rdsrc.splitlines()
                    if not ln.lstrip().startswith("#"))
w(f"  [{'OK' if 'Save_ED_Ren_Data' not in _rdcode else 'FAIL'}] "
  f"record_derive 合并总表不再收旧表")
if "Save_ED_Ren_Data" in _rdcode:
    fails.append("record_derive 仍收旧表")
_pvsrc = open(os.path.join(ROOT, "app", "views", "person_view.py"),
              encoding="utf-8").read()
w(f"  [{'OK' if '已故（旧表）' not in _pvsrc else 'FAIL'}] "
  f"侧栏不再出现「已故（旧表）」")
if "已故（旧表）" in _pvsrc:
    fails.append("侧栏仍有旧表节点")

w("\n20) 时间轴：镜头落在人堆上 + 后期朝代不铺白点（使用者问题 4 / 5）")
from app import timeline as _TL2
_tlbg = open(os.path.join(ROOT, "app", "views", "timeline_view.py"),
             encoding="utf-8").read()
# (a) 「白点」根因：端点补的小圆点必须有密度闸门
w(f"  [{'OK' if 'END_DOT_MAX' in _tlbg else 'FAIL'}] "
  f"端点圆点有密度闸门（END_DOT_MAX）—— 缩小时不铺白点")
if "END_DOT_MAX" not in _tlbg:
    fails.append("时间轴端点圆点没有密度闸门（会铺白点）")
_tlbg_code = "\n".join(ln for ln in _tlbg.splitlines()
                       if not ln.lstrip().startswith("#"))
w(f"  [{'OK' if 'stipple' not in _tlbg_code else 'FAIL'}] "
  f"时间轴代码无 stipple 点阵（白点的另一个来源，注释里提到是正常的）")
if "stipple" in _tlbg_code:
    fails.append("时间轴代码仍有 stipple 点阵")
# (b) 缩略轴：2026-09-26 九十批把全览条从顶部横向改到**左沿纵向**——
#     旧断言查的 `clipped_left`（横向贴左锚点）随该重设计一并删除；
#     新口径查「纵向全览条」的三件套（MINI_W 竖向容器 / 纵向视口框 / 朝代带按高度比例）。
w(f"  [{'OK' if ('MINI_W' in _tlbg and '_year_to_mini_y' in _tlbg) else 'FAIL'}] "
  f"缩略轴已改左沿纵向（MINI_W + 纵向年份定位，九十批重设计）")
if not ("MINI_W" in _tlbg and "_year_to_mini_y" in _tlbg):
    fails.append("缩略轴纵向化缺失")
# (c) 剧本口径：秦末档时间轴不该框在「上古」
if os.path.isdir(_SRC1):
    from app import storage as _ST2
    try:
        _pp, _cc, _ss3 = _ST2.load_save_full("秦末起义·史实")
    except Exception:
        _pp = {}
    if _pp:
        _yrs = [y for y in (_TL2.birth_year(v) for v in _pp.values()) if y is not None]
        _rs, _re_ = _TL2.year_bounds(_yrs)
        # 秦末档最晚生年应落在战国末~秦，不该被钉在上古
        w(f"  [{'OK' if max(_yrs) > -400 else 'FAIL'}] "
          f"秦末档生年最晚 {max(_yrs)}（> -400，落在战国末/秦，不是上古）")
        if max(_yrs) <= -400:
            fails.append("秦末档生年范围异常")
        # 该档前半段应当是空的（人都在中后段），镜头必须自动跳过空段
        _med = sorted(_yrs)[len(_yrs) // 2]
        w(f"  [OK] 秦末档生年中位 {_med}（最早 {min(_yrs)} 那一段是空的 → "
          f"必须靠 _scroll_to_content 自动跳）")
        w(f"  [{'OK' if '_scroll_to_content' in _tlbg else 'FAIL'}] "
          f"时间轴有「跳到人最密一屏」逻辑（_scroll_to_content）")
        if "_scroll_to_content" not in _tlbg:
            fails.append("时间轴没有镜头自动定位")
    else:
        w("  （秦末起义·史实 读不出人，跳过镜头检查）")
else:
    w(f"  （找不到 {_SRC1}，跳过）")

w("\n21) 表格页合并档案抽屉（使用者第 8 问：以表格为基础，合并人物的信息）")
_tv = open(os.path.join(ROOT, "app", "views", "table_view.py"),
           encoding="utf-8").read()
for _need, _desc in (("archive_rows", "档案派生（实录层同名优先）"),
                     ("_build_drawer", "右侧档案抽屉"),
                     ("toggle_drawer", "抽屉可折叠"),
                     ("_drawer_locate", "查档桥入口"),
                     ("_drawer_push", "入谱桥入口"),
                     ("_drawer_relations", "关系入口")):
    w(f"  [{'OK' if _need in _tv else 'FAIL'}] 表格页有 {_desc}（{_need}）")
    if _need not in _tv:
        fails.append(f"表格页缺 {_need}")
w(f"  [{'OK' if 'grid' in _tv and 'minsize=DRAWER_W' in _tv else 'FAIL'}] "
  f"抽屉用 grid+minsize 锁宽（pack 会被 Treeview 的请求宽度挤成 25px）")
if "minsize=DRAWER_W" not in _tv:
    fails.append("抽屉宽度会被挤扁")
# 档案口径：抽屉里应能看到「智略/文化/性格」这些人物页字段（证明合并到位）
for _zh in ("智略", "文化", "性格"):
    w(f"  [{'OK' if _zh in _tv else 'FAIL'}] 表格页档案含人物页字段「{_zh}」")
    if _zh not in _tv:
        fails.append(f"表格页档案缺 {_zh}")
# 工具条有「档案」按钮
_mn = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
w(f"  [{'OK' if 'toggle_drawer' in _mn else 'FAIL'}] 表格页工具条挂上「档案」按钮")
if "toggle_drawer" not in _mn:
    fails.append("工具条缺档案按钮")

w("\n22) source / 画布状态不被日常写档冲掉（实测踩过：文王治岐 被抹）")
# (a) 直接验证 write_save(source=None) 保留
import tempfile as _tmpd
_with = _tmpd.TemporaryDirectory()
_tdir = _with.name
_tpath = os.path.join(_tdir, "family.json")
json.dump({"people": {"甲": {"gender": "男", "historical": "是"}},
           "cutoff_person": None,
           "source": {"slot": "Save_All_3", "era": "上古"},
           "focused_people": ["甲"],
           "hidden_non_historical": ["乙"]},
          open(_tpath, "w", encoding="utf-8"), ensure_ascii=False)
_orig_sp = _ST.save_path
_ST.save_path = lambda name: _tpath
try:
    _pp2, _cc2 = _ST.load_save("x")
    _ST.write_save("x", _pp2, _cc2)
    _after = json.load(open(_tpath, encoding="utf-8"))
    w(f"  [{'OK' if (_after.get('source') or {}).get('slot') == 'Save_All_3' else 'FAIL'}] "
      f"write_save(source=None) 保留已有 source")
    if (_after.get("source") or {}).get("slot") != "Save_All_3":
        fails.append("write_save 冲掉 source")
    # ★ 2026-09-24：画布状态（选定名单 / 按支系隐藏名单）同款 —— 它们原来住在
    #   全局 config.json（换本书会串档），现在按谱牒存，也必须不被无关保存冲掉。
    _cv = _ST.load_canvas_state("x")
    _ok_cv = (_cv.get("focused_people") == ["甲"]
              and _cv.get("hidden_non_historical") == ["乙"])
    w(f"  [{'OK' if _ok_cv else 'FAIL'}] load_canvas_state 读出两个名单")
    if not _ok_cv:
        fails.append("load_canvas_state 读不出名单")
    _ok_keep = (_after.get("focused_people") == ["甲"]
                and _after.get("hidden_non_historical") == ["乙"])
    w(f"  [{'OK' if _ok_keep else 'FAIL'}] write_save(canvas=None) 保留已有画布状态")
    if not _ok_keep:
        fails.append("write_save 冲掉画布状态")
    # 显式传空表 → 键被移除（「清空名单」要能真清掉）
    _ST.write_save("x", _pp2, _cc2, canvas={"focused_people": [],
                                            "hidden_non_historical": []})
    _after2 = json.load(open(_tpath, encoding="utf-8"))
    _ok_clr = ("focused_people" not in _after2
               and "hidden_non_historical" not in _after2)
    w(f"  [{'OK' if _ok_clr else 'FAIL'}] write_save(canvas=空) 真的清掉这两个键")
    if not _ok_clr:
        fails.append("画布状态清不掉")
finally:
    _ST.save_path = _orig_sp
    _with.cleanup()
# (a2) 画布状态必须是**谱牒级**（不能回到全局 config —— 使用者第 9 问）
_mn_scope = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
_ok_scope = ("_load_canvas_state" in _mn_scope
             and "focused_people=list(self.focused)" not in _mn_scope)
w(f"  [{'OK' if _ok_scope else 'FAIL'}] 选定名单按谱牒存（不再写回全局 config）")
if not _ok_scope:
    fails.append("选定名单又写回全局 config 了（会串档）")
_cfgsrc = open(os.path.join(ROOT, "app", "config.py"), encoding="utf-8").read()
_ok_cfg = '"focused_people": []' not in _cfgsrc
w(f"  [{'OK' if _ok_cfg else 'FAIL'}] config.py 的 DEFAULTS 不再有 focused_people")
if not _ok_cfg:
    fails.append("config DEFAULTS 还留着 focused_people")
# (b) 真实档抽查
# ★ 2026-09-21：不再写死谱牒名（使用者会删档）。改成「哪部在就验哪部」。
for _sn, _want_slot in (("文王治岐", "Save_All_3"),):
    if not os.path.isdir(os.path.join(ROOT, "saves", _sn)):
        w(f"  [SKIP] {_sn} 不在（使用者删档了）")
        continue
    _ss4 = _ST.load_source(_sn)
    w(f"  [{'OK' if _ss4.get('slot') == _want_slot else 'FAIL'}] "
      f"{_sn} 的来源槽 = {_ss4.get('slot')!r}（期望 {_want_slot}）")
    if _ss4.get("slot") != _want_slot:
        fails.append(f"{_sn} 缺 source（被冲掉了？）")
# 另外：**所有**现存谱牒只要带了 source.slot，那个槽目录就该真的存在
for _sn2 in _ST.list_saves():
    _s4 = (_ST.load_source(_sn2) or {}).get("slot_path") or ""
    if _s4 and not os.path.isdir(_s4):
        w(f"  [FAIL] {_sn2} 的 source.slot_path 指向不存在的目录：{_s4}")
        fails.append(f"{_sn2} 来源槽路径失效")

w("\n23) 键盘快捷键（使用者第 1 问：「双击启动的快捷键都不能用」）")
# (a) 旧的单层绑定必须已拆除 —— 只 root.bind 会被输入框的 class binding 吃掉
_old = 'self.root.bind("<Control-z>"'
w(f"  [{'OK' if _old not in _mn else 'FAIL'}] 旧的单层 root.bind 已拆除")
if _old in _mn:
    fails.append("仍在用单层 root.bind")
for _need in ("HOTKEYS", "_install_hotkeys", "_bind_widget_hotkeys",
              "_focus_in_editor", "_make_view_hotkey"):
    w(f"  [{'OK' if _need in _mn else 'FAIL'}] main.py 有 {_need}")
    if _need not in _mn:
        fails.append("快捷键缺 " + _need)
# (b) 键位覆盖
# ★ 2026-09-21 顶栏改版：Ctrl+B（切换谱牒档）并进「存档」对话框，已删；
#   Ctrl+O 从「切换实录槽」改成「打开存档」（同一个对话框管两层）。
for _seq in ("<Control-f>", "<Control-s>", "<Control-o>",
             "<Control-p>", "<Control-t>", "<Control-e>", "<Control-g>",
             "<Control-d>", "<Control-q>", "<F5>", "<F1>", "<Control-z>"):
    w(f"  [{'OK' if _seq in _mn else 'FAIL'}] 键位 {_seq}")
    if _seq not in _mn:
        fails.append("缺键位 " + _seq)
# (c) 每次重建视图都要重绑（换主题 / 切页签会重建控件，旧绑定随控件一起没了）
_i = _mn.find("self._install_hotkeys()")
_b = _mn.find("def _build_main_view")
w(f"  [{'OK' if 0 < _b < _i else 'FAIL'}] _install_hotkeys 挂在 _build_main_view 内")
if not (0 < _b < _i):
    fails.append("重绑时机不对")
# (d) 真窗口注入实证 —— 静态断言证明不了「按下去真有用」，必须起窗口按一遍
try:
    _r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "hotkey_check.py")],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", timeout=240, cwd=ROOT)
    _n = -1
    for _ln in (_r.stdout or "").splitlines():
        if _ln.strip().startswith("FAILS "):
            try:
                _n = int(_ln.strip().split()[1])
            except Exception:
                pass
    if _n < 0:
        w("  [FAIL] 快捷键实证没跑出结果（多半挂死了）")
        fails.append("快捷键实证挂死")
    else:
        w(f"  [{'OK' if _n == 0 else 'FAIL'}] 真窗口注入实证 FAILS={_n}")
        if _n:
            fails.append(f"快捷键实证 {_n} 项失败")
except Exception as _e:
    w(f"  [FAIL] 快捷键实证异常 {type(_e).__name__}: {_e}")
    fails.append("快捷键实证异常")

w("\n24) 截图工具真能切页（回归：三页图不该长得一样）")
_s2 = open(os.path.join(ROOT, "tools", "shot2.py"), encoding="utf-8").read()
# (a) 静态：顺序化截图 + 闸门 + 长时限兜底 三件套齐全
for _need, _why in (("_ARM[0] = True", "截图闸门（防 update 重入提前触发）"),
                    ("_stage2_body", "after 回调异常可见（Tk 静默吞异常）"),
                    ("root.after(25000", "兜底时限够长（open_record 就要 2 秒）"),
                    # ★ 2026-09-26 九十批：时间轴并入家谱后，切页兜底改成
                    #   「timeline → tree + family_mode=time」的转写（旧断言查的
                    #   `update_config(view=view)` 随之失效）
                    ("app.cfg = update_config(view=target)",
                     "切页兜底（timeline 转写为 tree+time 模式）"),
                    ("_restore_cfg", "截图不污染用户配置（view/current_record/current_save）")):
    w(f"  [{'OK' if _need in _s2 else 'FAIL'}] shot2.py 有 {_why}")
    if _need not in _s2:
        fails.append("shot2 缺 " + _need)
# (b) 动态：真截三页，哈希必须两两不同；且配置不得被改
# ★ 2026-09-23 独立「时间轴」页签已并入家谱（timeline → 家谱 key=tree + mode=time），
#   截图页签清单换成四个页签键中的三个（person / tree / table）。
import hashlib as _hl
from app.config import load_config as _load_cfg
_cfg_before = dict(_load_cfg())
_shots = {}
for _v in ("tree", "table", "person"):
    # ★ 截图产物落到 `_stats\shots\`（正式输出目录），不落 `_scratch\`
    #   —— _scratch 只放工具脚本，避免临时文件堆积（使用者 2026-09-22 要求）
    _p = os.path.join(ROOT, "_stats", "shots", "_smoke_%s.png" % _v)
    _r = subprocess.run(
        [sys.executable, os.path.join(ROOT, "tools", "shot2.py"),
         _v, _p, r"D:\DevCache\dzlgz\Save_All_1"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=180, cwd=ROOT)
    if os.path.isfile(_p):
        _shots[_v] = _hl.md5(open(_p, "rb").read()).hexdigest()[:12]
    else:
        _shots[_v] = ""
for _v, _h in _shots.items():
    w(f"  [{'OK' if _h else 'FAIL'}] 截图 {_v} 落地 {_h or '（没生成）'}")
    if not _h:
        fails.append("截图没落地 " + _v)
_uniq = len({h for h in _shots.values() if h})
w(f"  [{'OK' if _uniq == 3 else 'FAIL'}] 三页截图互不相同（实际 {_uniq} 种）")
if _uniq != 3:
    fails.append("截图分不出页签（尺寸/哈希相同）")
# ★ 截图不该改用户配置（实测踩过：跑完 config.view 被刷成 table）
_cfg_after = dict(_load_cfg())
if _cfg_before:
    _dirty = [k for k in ("view", "current_record", "current_save")
              if _cfg_before.get(k) != _cfg_after.get(k)]
    w(f"  [{'OK' if not _dirty else 'FAIL'}] 截图未污染用户配置"
      + ("" if not _dirty else f"（被改：{_dirty}）"))
    if _dirty:
        fails.append("截图改了用户配置 " + ",".join(_dirty))

w("")
w("25) HTML 家谱导出（安卓化第一步：单文件 · 自包含 · 手机可看）")
_EXP = os.path.join(ROOT, "tools", "export_html.py")
_BOOK = os.path.join(ROOT, "saves", "满天星斗·沙盒全局", "family.json")
if not os.path.isfile(_EXP):
    w("  [FAIL] 缺 tools/export_html.py")
    fails.append("缺 export_html.py")
elif not os.path.isfile(_BOOK):
    w("  [SKIP] 谱牒《满天星斗·沙盒全局》不存在")
else:
    _out = os.path.join(ROOT, "_stats", "_smoke_export.html")
    subprocess.run([sys.executable, _EXP, "满天星斗·沙盒全局", "--out", _out],
                   capture_output=True, text=True, encoding="utf-8",
                   errors="replace", timeout=180, cwd=ROOT)
    _html = open(_out, encoding="utf-8").read() if os.path.isfile(_out) else ""
    for _need, _why in (("<!DOCTYPE html>", "完整 HTML"),
                        ("var DATA =", "带详情卡数据"),
                        ("viewBox", "带矢量世系图"),
                        ("公元前", "时间已汉字化")):
        _ok = _need in _html
        w(f"  [{'OK' if _ok else 'FAIL'}] 含{_why}")
        if not _ok:
            fails.append("HTML 导出缺 " + _why)
    _n = _html.count('class="node"')
    w(f"  [{'OK' if _n >= 200 else 'FAIL'}] 节点数 {_n}（谱牒 285 人）")
    if _n < 200:
        fails.append("HTML 节点数异常 %d" % _n)
    _ext = ('src="http' in _html) or ('href="http' in _html)
    w(f"  [{'OK' if not _ext else 'FAIL'}] 零外部依赖（真自包含，可离线打开）")
    if _ext:
        fails.append("HTML 引用了外部资源")
    if os.path.isfile(_out):
        os.remove(_out)

w("")
w("26) B 批修复：假设不牢四件套（detect_start_year / scenario_of / 保护档 / 缓存来源）")
from tools import import_from_game as _IM3
# ★ 2026-09-24 同 17) 段：夹具**不能写死 Save_All_1** —— 那是使用者正在玩的槽，
#   被游戏覆盖后这里会拿一盘上古档去比「-209」，假 FAIL。
_S1 = _SRC1 if os.path.isdir(_SRC1) else ""
if not _S1:
    w("  [SKIP] 本机找不到秦末档，B1 跳过")
else:
    import time as _t3
    _ya = _IM3.detect_start_year(_S1)
    _t3a = _t3.time()
    _yb = _IM3.detect_start_year(_S1)
    _t3b = _t3.time()
    w(f"  [{'OK' if _ya == -209 else 'FAIL'}] B1 开局年 = {_ya}（秦末档应为 -209）")
    if _ya != -209:
        fails.append("B1 开局年异常 %s" % _ya)
    w(f"  [{'OK' if _yb == _ya else 'FAIL'}] B1 缓存命中后结果一致（{_yb}）")
    if _yb != _ya:
        fails.append("B1 缓存前后不一致")
    _ms = (_t3b - _t3a) * 1000
    w(f"  [{'OK' if _ms < 10 else 'FAIL'}] B1 缓存命中耗时 {_ms:.1f}ms（应 <10ms）")
    if _ms >= 10:
        fails.append("B1 缓存没生效")

from app import scenarios as _SC3
_name, _st, _dft, _mg = _SC3.scenario_match(-209, "沙盒全局")
_ok2 = (_name == "秦末起义" and _dft == 0 and _mg == 2)
w(f"  [{'OK' if _ok2 else 'FAIL'}] B2 诊断 {_name} 漂移={_dft} 余量={_mg}（秦末起义余量应为 2）")
if not _ok2:
    fails.append("B2 诊断异常 %r" % ((_name, _st, _dft, _mg),))
_up = _SC3.scenario_match(-2502, "沙盒全局")
w(f"  [{'OK' if _up[0] == '满天星斗' else 'FAIL'}] B2 向上容差生效（-2502 → {_up[0]}）")
if _up[0] != "满天星斗":
    fails.append("B2 向上容差失效")
w(f"  [{'OK' if _SC3.scenario_of(-209, '沙盒全局') == '秦末起义' else 'FAIL'}]"
  f" B2 兼容：scenario_of 仍返回字符串")
if _SC3.scenario_of(-209, "沙盒全局") != "秦末起义":
    fails.append("B2 scenario_of 兼容性被破坏")

_sf = open(os.path.join(ROOT, "app", "dialogs", "forms.py"), encoding="utf-8").read()
_sm = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
for _src, _need, _why in (
        (_sf, 'dry_ok = ok or act == "skip"', "B3 保护档也允许「先演习」"),
        # ★ 2026-09-29 放宽：写回按钮**只对保护档（skip）禁用** ——
        #   使用者原话「只把标记保护的存档保护好就行了，我要写就写，
        #   不要给我不能点」。原来的 `act_now in ("new","extend")` 会把
        #   conflict / none 也一起挡死（且 `refresh_target` 只禁不启，
        #   按钮永远点不动）。安全性改由「必须先演习通过」这一道闸门保证。
        (_sf, 'act_now != "skip"', "B3 写回只挡保护档（2026-09-29 放宽）"),
        (_sf, 'state["dry_ok"]', "B3 写回仍需先演习通过（二次闸门）"),
        (_sm, "_cache_stale(", "B4 缓存过期判据"),
        (_sm, "按本机旧缓存", "B4 列表标注旧缓存")):
    _ok = _need in _src
    w(f"  [{'OK' if _ok else 'FAIL'}] {_why}")
    if not _ok:
        fails.append("B 批缺 " + _why)

w("\n27) 人物页双击跳家谱 + 现场保持 + 返回按钮（2026-09-24）")
_pv = open(os.path.join(ROOT, "app", "views", "person_view.py"), encoding="utf-8").read()
_cf = open(os.path.join(ROOT, "app", "config.py"), encoding="utf-8").read()
for _src, _need, _why in (
        (_pv, '"<Double-1>", self._on_row_double', "人物页表格绑了双击"),
        (_pv, "def _on_row_double", "双击回调存在"),
        (_pv, "app.book_name_of_code(code)", "跳转按 code 反查谱牒人名"),
        (_pv, "goto_main_tree(book_name, from_person=True)", "跳转带 from_person 标记"),
        (_pv, "messagebox.showwarning(", "不在谱牒时明确提示（不静默）"),
        (_pv, "self.app.restore_person_view(self)", "attach 接上现场恢复"),
        (_sm, "def restore_person_view", "现场恢复入口"),
        (_sm, "def _remember_view_state", "切页销毁前记住现场"),
        (_sm, "def _apply_person_scroll", "两处滚动位置恢复"),
        (_sm, "def book_name_of_code", "code → 谱牒人名 反查"),
        (_sm, "self._return_to_person = False", "返回标记默认关"),
        (_sm, "← 返回人物页", "家谱页返回按钮文案"),
        (_sm, "def back_to_person", "返回动作"),
        (_sm, "def _hint_not_on_canvas", "被过滤挡住时说明原因"),
        (_cf, '"person_family"', "config 落盘表族"),
        (_cf, '"person_sort"', "config 落盘排序")):
    _ok = _need in _src
    w(f"  [{'OK' if _ok else 'FAIL'}] {_why}")
    if not _ok:
        fails.append("双击跳转缺 " + _why)

# 反向断言：`_build_main_view` 必须在销毁控件**之前**记住现场
_i_rem = _sm.find("self._remember_view_state()")
_i_des = _sm.find("def _build_main_view")
_i_kill = _sm.find("w.destroy()", _i_des)
_ok = _i_des < _i_rem < _i_kill
w(f"  [{'OK' if _ok else 'FAIL'}] 记住现场早于销毁主区控件（静态）")
if not _ok:
    fails.append("_remember_view_state 的调用时机不对（要在 w.destroy() 之前）")

w("")
w("=" * 74)
if fails:
    w(f"结果：{len(fails)} 项失败")
    for f in fails:
        w("  · " + f)
else:
    w("结果：全部通过")
w("=" * 74)

with open(OUT, "w", encoding="utf-8") as f:
    f.write(buf.getvalue())
print("FAILS", len(fails))
