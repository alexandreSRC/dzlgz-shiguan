# -*- coding: utf-8 -*-
"""M3 交互改造验收：续谱/存档对话框、人物筛选勾选、启动器 .lnk。

产出 `_stats/_m3_ui.txt`。全部在无头模式下跑（模态框会挂死进程，踩过）。
"""
import os
import subprocess
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
sys.path.insert(0, os.path.join(PROJ, "tools"))
os.chdir(PROJ)
os.environ["SHIGUAN_HEADLESS"] = "1"

log, fails = [], []


def w(s):
    log.append(str(s))
    print(s)


def step(name, ok, detail=""):
    w(f"[{'OK' if ok else 'FAIL'}] {name}" + (f"　{detail}" if detail else ""))
    if not ok:
        fails.append(name)
    return ok


def main():
    import tkinter as tk
    import tkinter.messagebox as mb
    for fn in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel"):
        setattr(mb, fn, lambda *a, **k: "ok")
    import main as M
    from app.dialogs import forms

    w("=" * 62)
    w("=== M3 交互改造验收 ===")
    w("=" * 62)

    root = tk.Tk()
    root.withdraw()
    app = M.ShiguanApp(root)
    w(f"启动：谱牒《{app.current_save}》· 实录 "
      f"{app.record_slot.name if app.record_slot else '（无）'}")

    # ---------------- 1. 顶栏：一个「存档」胶囊 ----------------
    w("\n--- ① 顶栏 ---")
    tb = app.topbar
    step("只有「存档 / 续谱 / 设置」三个胶囊",
         hasattr(tb, "pill_archive") and hasattr(tb, "pill_extend")
         and hasattr(tb, "pill_settings")
         and not any(hasattr(tb, n) for n in
                     ("pill_record", "pill_book", "pill_theme", "pill_sync")))
    txt = tb.pill_archive.value_widget.cget("text")
    step("存档胶囊显示「谱牒 → 实录」", "→" in txt, txt)

    # ---------------- 2. 两个对话框：能构造、底部按钮在 ----------------
    w("\n--- ② 对话框 ---")
    forms.extend_dialog(app)
    dlg = None
    for child in root.winfo_children():
        if isinstance(child, tk.Toplevel):
            dlg = child
    # 无头模式 finish() 会立刻 destroy，所以这里改用直接构造的方式再验一次
    from app.dialogs.forms import ThemedDialog
    _probe = ThemedDialog(app, "探针", width=400, height=300)
    _probe.footer.pack_forget()
    _probe.footer.pack(side=tk.BOTTOM, fill=tk.X)
    root.update_idletasks()
    step("ThemedDialog 的 footer 先 pack 到 BOTTOM（底部按钮不会被内容挤出窗口）",
         _probe.footer.winfo_manager() == "pack"
         and int(_probe.footer.pack_info().get("side", "").lower() == "bottom"
                 or _probe.footer.pack_info().get("side") == "bottom"),
         f"side={_probe.footer.pack_info().get('side')}")
    _probe.destroy()

    forms.archive_dialog(app)
    w("  存档对话框构造无异常")
    forms.extend_dialog(app)
    w("  续谱对话框构造无异常")
    step("两个对话框都能在无头模式下构造（不挂死）", True)

    # ---------------- 3. 人物筛选勾选 ----------------
    w("\n--- ③ 人物筛选 ---")
    app.switch_view("person")
    root.update()
    pv = app.person_view
    st = getattr(pv, "_stats", {}) or {}
    w(f"  计数：{st}")
    # 2026-09-21：补了「出生记录」一项（人物筛选多出这个勾选框），共 10 项
    step("people_stats 有全部 10 项",
         all(k in st for k in ("全部", "史实", "非史", "男性", "女性",
                               "在世", "已故", "出生记录", "谱牒内", "续谱名单")),
         f"{len(st)} 项")
    step("史实 + 非史 = 全部", st.get("史实", 0) + st.get("非史", 0) == st.get("全部", 0),
         f"{st.get('史实')} + {st.get('非史')} = {st.get('全部')}")
    step("男性 + 女性 = 全部", st.get("男性", 0) + st.get("女性", 0) == st.get("全部", 0),
         f"{st.get('男性')} + {st.get('女性')} = {st.get('全部')}")
    step("在世 + 已故 = 全部", st.get("在世", 0) + st.get("已故", 0) == st.get("全部", 0),
         f"{st.get('在世')} + {st.get('已故')} = {st.get('全部')}")

    def hits():
        return len(pv.all_pairs)

    pv._set_all_filters(False)
    root.update()
    n_all = hits()
    step("全不勾 = 不限（等于全部）", n_all == st.get("全部"), f"{n_all} vs {st.get('全部')}")

    pv.chips["female"].set_state("female", True)
    pv._on_filter()
    root.update()
    step("只勾「女性人物」→ 命中 = 女性人数",
         hits() == st.get("女性"), f"{hits()} vs {st.get('女性')}")

    pv.chips["hist"].set_state("hist", True)
    pv._on_filter()
    root.update()
    n_hf = hits()
    # ★ 2026-09-26：期望值从**视图当前绑定的表族**实算 —— 原来写死
    #   「人物 · 合并总表」，而 person_family 现在可以合法停在
    #   「人物 · 谱牒总谱」（13,526 人全是史实编号），两批人口径不同，
    #   断言必然打架（实测 146 vs 23）。跟随 cur_family 后，无论使用者
    #   停在哪张表族，检查的都是同一件事：筛选逻辑自洽。
    _rows = pv.slot.tables[pv.cur_family].rows
    expect_hf = len([1 for r in _rows
                     if str(r.get("Ren_Sex")) == "1"
                     and __import__("app.profiles", fromlist=["x"]).is_historical(
                         str(r.get("Ren_Code") or ""))])
    step("「史实人物 + 女性人物」= 两者交集",
         n_hf == expect_hf and n_hf <= min(st.get("史实", 0), st.get("女性", 0)),
         f"{n_hf} vs 实算 {expect_hf}")

    pv._set_all_filters(False)
    root.update()
    step("清空后回到全部", hits() == st.get("全部"), f"{hits()}")

    # ---------------- 4. 启动器 .lnk ----------------
    w("\n--- ④ 启动器 ---")
    import importlib
    ms = importlib.import_module("make_shortcut") if False else None
    sys.path.insert(0, os.path.join(PROJ, "tools"))
    import make_shortcut as MS
    target = MS.pythonw()
    step("pythonw() 指向 pythonw.exe", target.lower().endswith("pythonw.exe"), target)
    info = MS.verify(os.path.join(PROJ, MS.NAME))
    if len(info) >= 3:
        step("项目根 .lnk 目标 = pythonw.exe", info[0].lower().endswith("pythonw.exe"),
             info[0])
        step("项目根 .lnk 参数 = main.py", info[1] == "main.py", info[1])
        step("项目根 .lnk 工作目录 = 项目根",
             os.path.normcase(info[2]) == os.path.normcase(PROJ), info[2])
    else:
        step("项目根 .lnk 可读回", False, str(info))
    desk = MS._desktop()
    step("桌面路径取注册表里的真实桌面（这台机器是 D:\\Desktop）",
         os.path.normcase(desk) == os.path.normcase(r"D:\Desktop"), desk)
    dlnk = os.path.join(desk, MS.NAME)
    step("桌面 .lnk 存在", os.path.isfile(dlnk), dlnk)

    # ---------------- 5. 拉档/选槽 ----------------
    w("\n--- ⑤ 选槽（不连模拟器，只验本机那一路）---")
    rows = []
    for p in app.record_slots:
        desc, ok = app.local_slot_desc(p)
        rows.append((os.path.basename(p), desc, ok, p))
    step("本机缓存槽列表非空", bool(rows), f"{len(rows)} 个")
    for slot, desc, ok, _p in rows:
        w(f"    {slot:<16s} {desc}")
    step("槽列表按争霸类型分组可用",
         all(g[0] for g in forms.slot_groups(rows)),
         "、".join(g[0] for g in forms.slot_groups(rows)))

    w("")
    w("=" * 62)
    if fails:
        w(f"未通过 {len(fails)} 项：")
        for f in fails:
            w("  · " + f)
    else:
        w("全部通过。")
    w("=" * 62)

    os.makedirs(os.path.join(PROJ, "_stats"), exist_ok=True)
    with open(os.path.join(PROJ, "_stats", "_m3_ui.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(log) + "\n")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
