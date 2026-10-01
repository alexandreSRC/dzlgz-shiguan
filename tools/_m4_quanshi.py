# -*- coding: utf-8 -*-
"""《全史存档》开卷验收（无头）：
① 谱牒能载入、人数与报告一致；
② `source.hide_cols` 生效 —— 人物页表头**不含**年龄/余寿，普通谱牒仍含（对照组）；
③ 家谱/时间轴/表格三页能画出来（不抛异常）；
④ 抽样核对风女娲的世代与生卒。
"""
import io
import os
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
os.chdir(PROJ)
os.environ["SHIGUAN_HEADLESS"] = "1"
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace")

log, fails = [], []


def step(name, ok, detail=""):
    print(f"[{'OK' if ok else 'FAIL'}] {name}" + (f"　{detail}" if detail else ""))
    if not ok:
        fails.append(name)


def main():
    import tkinter as tk
    import tkinter.messagebox as mb
    for fn in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel"):
        setattr(mb, fn, lambda *a, **k: "ok")
    import main as M
    from app import storage, profiles as PF

    # ★ 工具纪律（项目日志第 8 条）：脚本开头存、收尾还原 ——
    #   `switch_save / switch_view` 内部都会写 config.json（当前谱牒 / 页签），
    #   本脚本只是验收，不该动使用者的现场。
    cfg_p = os.path.join(PROJ, "config.json")
    cfg_before = open(cfg_p, encoding="utf-8").read() if os.path.exists(cfg_p) else None

    root = tk.Tk()
    root.withdraw()
    app = M.ShiguanApp(root)

    step("《全史存档》出现在谱牒列表",
         "全史存档" in storage.list_saves())
    people, cutoff, src = storage.load_save_full("全史存档")
    step("载入人数 = 13526（剔除占位假人后）", len(people) == 13526, f"{len(people)} 人")
    step("谱牒声明 hide_cols = 年龄/余寿",
         sorted(src.get("hide_cols") or []) == ["余寿", "年龄"], str(src.get("hide_cols")))
    step("来源档数 = 32", len(src.get("parts") or []) == 32,
         f"{len(src.get('parts') or [])} 档")

    # ---- 切到《全史存档》，看人物页表头 ----
    app.switch_save("全史存档")
    app.switch_view("person")
    pv = app.person_view
    pv._render_table()                      # 切档后强制重画一次
    heads = [c.split(":",1)[1] for c in pv.table["columns"]]
    step("人物页表头不含 年龄/余寿", "年龄" not in heads and "余寿" not in heads,
         " / ".join(heads))
    step("其余列仍在（姓名/性别/生年/卒年…）",
         {"姓名", "性别", "生年", "卒年"} <= set(heads))
    step("列宽表也少了这两列",
         "年龄" not in pv._fit_person_cols() and "余寿" not in pv._fit_person_cols())

    # ---- 对照组：普通谱牒仍有这两列 ----
    app.switch_save("穆王巡游")
    app.switch_view("person")
    app.person_view._render_table()
    heads2 = [c.split(":",1)[1] for c in app.person_view.table["columns"]]
    step("对照组《穆王巡游》仍有 年龄/余寿",
         "年龄" in heads2 and "余寿" in heads2, " / ".join(heads2))

    # ---- 回到《全史存档》，三页都能画 ----
    app.switch_save("全史存档")
    for v in ("tree", "timeline", "table"):
        try:
            app.switch_view(v)
            step(f"{v} 页可渲染", True)
        except Exception as e:
            step(f"{v} 页可渲染", False, repr(e))

    # ---- 抽样 ----
    step("风女娲在谱且世代 = 3",
         bool(people.get("风女娲")) and people["风女娲"]["generation"] == 3,
         f"世代 {people.get('风女娲', {}).get('generation')}")
    step("风女娲生卒取到完整档（前2523/前2431）",
         str(people["风女娲"]["birth"]).startswith("-2523")
         and str(people["风女娲"]["death"]).startswith("-2431"))
    # ★ 架构评审 v3（多源 DP 锚定）新增断言：
    #   断链根按生年落位（霍仲孺 生前161 → 约 75 代，绝不该是第 1 代）；
    #   爵位分字段众数采纳（姬昌=王 · 嬴政=帝）。
    step("断链根霍仲孺按生年落位（世代 ≥ 60）",
         bool(people.get("霍仲孺")) and people["霍仲孺"]["generation"] >= 60,
         f"世代 {people.get('霍仲孺', {}).get('generation')}")
    step("第 1 代只有风巢皇（生前2580）",
         sum(1 for v in people.values() if v.get("generation") == 1) == 1
         and people["风巢皇"]["generation"] == 1)
    step("姬昌爵位 = 王（分字段众数采纳）",
         people.get("姬昌", {}).get("fief_title") == "王",
         str(people.get("姬昌", {}).get("fief_title")))
    step("嬴政爵位 = 帝",
         people.get("嬴政", {}).get("fief_title") == "帝",
         str(people.get("嬴政", {}).get("fief_title")))
    # 世代不变量全量复核（子 > 父，逐人）
    name2gen = {nm: v.get("generation", 0) for nm, v in people.items()}
    bad = 0
    for v in people.values():
        for k in ("father", "mother"):
            f = v.get(k)
            if f and f in name2gen and v.get("generation", 0) <= name2gen[f]:
                bad += 1
    step("世代不变量（子 > 父/母）0 违例", bad == 0, f"违例 {bad}")

    # ---- 人物页读总谱（★ 七十批收尾新增：谱牒总谱派生表）----
    from app import record_derive as RDB
    try:
        # ⚠️ 切谱牒会重建视图，必须取**当前**的 person_view（旧引用的控件已销毁）；
        #     上一步停在表格页，先切回人物页让实例建出来。
        app.switch_view("person")
        pv2 = app.person_view
        # ★ 2026-09-25 修：这条断言**原来写死 True**（假断言）—— 表挂上了、
        #   导航却没有这一行，使用者根本点不到，而验收全绿。现在真查导航。
        nav_names = [pv2._nav_index[k] for k in pv2.nav.get_children()]
        step("人物页导航含「人物 · 谱牒总谱」（点得到）",
             RDB.BOOK_NAME in nav_names, " / ".join(nav_names))
        pv2.goto_family(RDB.BOOK_NAME)
        n_rows = len(pv2.table.get_children())
        step("谱牒总谱 13526 行全显", n_rows == 13526, f"{n_rows} 行")
        heads3 = [c.split(":", 1)[1] for c in pv2.table["columns"]]
        step("谱牒总谱表头同样无 年龄/余寿",
             "年龄" not in heads3 and "余寿" not in heads3)
        pv2.search_var.set("嬴政")
        pv2._apply_filter()
        rows = pv2.table.get_children()
        step("谱牒总谱搜索「嬴政」有结果", bool(rows), f"{len(rows)} 行")
        step("嬴政生年在总谱 = 前259",
             str(people.get("嬴政", {}).get("birth", "")).startswith("-259"))
        # ---- 扩展字段（★ 十八点半批：enrich_staging 回捞的存档原文字段）----
        bt = pv2.slot.table(RDB.BOOK_NAME)
        n_z = sum(1 for r in bt.rows
                  if r.get("Ren_Zhi_Lue") not in (None, "", 0))
        step("谱牒总谱智略齐全（≥10000 人）", n_z >= 10000, f"{n_z} 人")
        row = next((r for r in bt.rows if r.get("Ren_Name") == "嬴政"), None)
        step("嬴政 智略/等级/政策/能力 已填",
             bool(row) and row.get("Ren_Zhi_Lue") not in (None, "", 0)
             and row.get("Ren_Leve") not in (None, "", 0)
             and len(row.get("Ren_Zheng_Ce_Array") or []) > 0
             and len(row.get("Ren_Neng_Li_Array") or []) > 0,
             f"智略={row.get('Ren_Zhi_Lue')} 等级={row.get('Ren_Leve')} "
             f"政策={len(row.get('Ren_Zheng_Ce_Array') or [])} "
             f"能力={len(row.get('Ren_Neng_Li_Array') or [])}" if row else "无此人")
        # ---- ★ 2026-09-25（使用者裁定）：世代用**合并重算**的那个 ----
        #   原文档位世代（Ren_Dai_Shu）不采纳：嬴政原文 71 / 合并 82。
        gen_bad = sum(1 for r in bt.rows
                      if r.get("Ren_Dai_Shu")
                      != people.get(r.get("Ren_Name"), {}).get("generation"))
        step("总谱世代 ≡ 合并重算 generation（0 违例）", gen_bad == 0, f"违例 {gen_bad}")
        step("嬴政 世代 = 82（非原文档位世代 71）",
             bool(row) and row.get("Ren_Dai_Shu") == 82,
             f"{row.get('Ren_Dai_Shu') if row else '—'}")

        # ---- ★ 2026-09-25（使用者要求）：人物页每列都要有数据 ----
        #   与单剧本存档同一套列（`profiles.TABLE_COLS` 去掉本谱 hide_cols），
        #   值取自谱牒自带 + extra（各档存档原文众数/并集）。
        def n_filled(key):
            if key in ("Ren_Leve", "Ren_Zhi_Lue"):   # 数值型：0 也算有值
                return sum(1 for r in bt.rows if r.get(key) is not None)
            return sum(1 for r in bt.rows
                       if r.get(key) not in (None, "", 0, [], {}))

        n_sex = sum(1 for r in bt.rows if r.get("Ren_Sex") in (0, 1))
        cover = {"姓名": n_filled("Ren_Name"), "性别": n_sex,
                 "智略": n_filled("Ren_Zhi_Lue"), "等级": n_filled("Ren_Leve"),
                 "生年": n_filled("Ren_Chu_Sheng_Time"),
                 "卒年": n_filled("Ren_End_Time"),
                 "文化": n_filled("Ren_Wen_Hua"), "性格": n_filled("Ren_Xing_Ge"),
                 "势力": n_filled("Ren_Shi_Li_1")}
        ok_cover = (cover["姓名"] == cover["性别"] == cover["文化"] == cover["性格"]
                    == cover["生年"] == 13526
                    and cover["智略"] >= 10000 and cover["等级"] >= 10000
                    and cover["卒年"] >= 10000 and cover["势力"] >= 12000)
        step("总谱人物页各列数据齐备", ok_cover,
             " · ".join(f"{k}{v}" for k, v in cover.items()))

        # ---- ★ 与单剧本存档同一套表头（列名/顺序/宽度口径全同）----
        heads_book = [c.split(":", 1)[1] for c in pv2.table["columns"]]
        pv2.goto_family("人物 · 合并总表")
        heads_slot = [c.split(":", 1)[1] for c in pv2.table["columns"]]
        step("总谱表头 == 单剧本档「全部人物」表头",
             heads_book == heads_slot, " / ".join(heads_book))
        # ★ 缺值一律「—」：存档的**已故表**没有 `Ren_Zhi_Lue`，原来会显示字面
        #   「None」（详情卡与表格里都很扎眼）。
        step("无智略的人显示「—」（不显示 None）",
             PF.Profile("1", {"Ren_Code": "1"}).value_of("zhilue") == "—")

        # ⚠️ 上面的表头对照把视图切到「合并总表」了 —— 先回总谱再验筛选口径。
        pv2.goto_family(RDB.BOOK_NAME)
        # ---- ★ 2026-09-25（使用者报「选中总谱后筛选无效」）----
        st_b = getattr(pv2, "_stats", None) or {}
        step("总谱筛选计数按**本表**口径（共 13526 人，不是实录槽的 11874）",
             st_b.get("全部") == 13526, str(st_b.get("全部")))
        n_civ = sum(1 for r in bt.rows if PF.identity_of(r))
        step("「隐藏平民」计数与筛选集合同源",
             st_b.get("非平民") == n_civ, f"{st_b.get('非平民')} / {n_civ}")
        n_lv0 = sum(1 for r in bt.rows if r.get("Ren_Leve") == 0)
        step("总谱里有等级 0（庶）的人 —— 0 没被当空丢掉", n_lv0 > 0, f"{n_lv0} 人")
        pv2.chips["lv5"].set_state("lv5", True)
        pv2._on_filter()
        n_shu = len(pv2.table.get_children())
        pv2.chips["lv5"].set_state("lv5", False)
        pv2._on_filter()
        step("总谱勾「庶」能筛出人", n_shu == n_lv0, f"筛出 {n_shu} / 应有 {n_lv0}")
    except Exception as e:
        step("人物页读总谱", False, repr(e))
    # 对照：正常谱牒不挂这张表
    app.switch_save("穆王巡游")
    app.switch_view("person")
    fams2 = set(getattr(app.person_view, "_nav_index", {}).values())
    step("对照《穆王巡游》无「谱牒总谱」表族", RDB.BOOK_NAME not in fams2)

    print()
    if cfg_before is not None:            # 还原使用者现场
        open(cfg_p, "w", encoding="utf-8").write(cfg_before)
        print("（config.json 已还原）")
    print("=" * 60)
    print("全部通过。" if not fails else f"FAILS {len(fails)}: {fails}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
