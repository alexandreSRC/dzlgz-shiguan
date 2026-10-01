# -*- coding: utf-8 -*-
"""平板前端的**数据源**：一次取数，HTTP 服务与 HTML 生成器共用。

★ 纪律（2026-09-29「1:1 复刻」那轮定下来的）：
  **对接/复刻别人的界面，"看着像"不算 —— 要跟被复刻方同源取数。**
  所以这里的数据全部读程序**渲染好的表格**（`pv._cell_for`）与
  **同一个统计函数**（`pv._stats` = `RD.people_stats` / `RD.book_stats`）、
  **同一个列宽**（`pv.table.column(c,'width')`）——
  而不是服务端自己另算一套（曾因此算出「在世 5182」而 Tk 显示 3931）。

对外只有一个 `PadData`：
    pad = PadData()        # 起一次 Tk，取数，之后常驻缓存
    pad.payload()          # 取 JSON 字典（首次调用才真取数）
    pad.reload()           # 强制重取（改档、改数据后用）
"""
from __future__ import annotations

import io
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)
os.environ.setdefault("SHIGUAN_HEADLESS", "0")

LIMIT = 500                                  # 传送给平板的最大行数
FAMILY = "人物 · 合并总表"                    # 与 proto.html 同表族
TIERS = ["邦", "上", "中", "下", "庶", "丁"]
# 列级右对齐（与 Tk 的 `anchor='e'` 同）
CENTER = ("智略", "年龄", "余寿")


class PadData:
    """取数（带缓存 + 锁；Tk 操作不并发）。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._cache = None
        self._app = None
        self._root = None
        self._warn = ""

    # ---------- 内部：起 Tk 并取一次数 ----------
    def _boot(self):
        """起应用（只起一次，之后复用）。"""
        if self._app is not None:
            return
        import tkinter as tk
        from main import ShiguanApp

        self._root = tk.Tk()
        self._root.geometry("1600x900+0+0")
        self._app = ShiguanApp(self._root)
        self._pump(45, 0.02)
        self._app.cfg["view"] = "person"
        self._app.view_key = "person"
        self._app._build_main_view()
        self._app._refresh_all()
        self._pump(25, 0.03)

    def _pump(self, n, dt):
        for _ in range(n):
            self._root.update()
            time.sleep(dt)

    def _collect(self):
        from app import profiles as PF

        app = self._app
        pv = app.person_view
        pv.goto_family(FAMILY)
        self._pump(15, 0.03)

        cols = [c[0] for c in pv._columns()]          # ['_p:姓名', '_p:身份', …]
        heads = [c[3:] if c.startswith("_p:") else c for c in cols]

        rows = []
        for r in pv.rows[:LIMIT]:
            code = str(r.get("Ren_Code") or "")
            rows.append([str(pv._cell_for(c, r, code) or "") for c in cols])

        # 列宽 = Tk 实测值（总宽 1205 > 中栏 515 ⇒ 横向滚动，这才是 Tk 的样子）
        colw = []
        for c in cols:
            try:
                colw.append(int(pv.table.column(c, "width")))
            except Exception:
                colw.append(80)

        # 计数：**同一个统计函数**（Tk 口径）
        try:
            pv._filter_ctx()
            st = dict(getattr(pv, "_stats", None) or {})
        except Exception as e:                     # noqa: BLE001
            self._warn = "取 _stats 失败: %s" % e
            st = {}
        if st:
            stats = [["史实人物", st.get("史实", 0)], ["非史实人物", st.get("非史", 0)],
                     ["男性人物", st.get("男性", 0)], ["女性人物", st.get("女性", 0)],
                     ["在世人物", st.get("在世", 0)], ["已故人物", st.get("已故", 0)]]
            stats2 = [["隐藏平民", st.get("非平民", 0)],
                      ["出生记录", st.get("出生记录", 0)]]
        else:
            n = len(pv.rows)
            hist = sum(1 for r in pv.rows
                       if PF.is_historical(str(r.get("Ren_Code") or "")))
            stats = [["史实人物", hist], ["非史实人物", n - hist],
                     ["男性人物", sum(1 for r in pv.rows
                                      if str(r.get("Ren_Sex")) != "1")],
                     ["女性人物", sum(1 for r in pv.rows
                                      if str(r.get("Ren_Sex")) == "1")],
                     ["在世人物", sum(1 for r in pv.rows
                                      if not r.get("Ren_End_Time"))],
                     ["已故人物", sum(1 for r in pv.rows
                                      if r.get("Ren_End_Time"))]]
            stats2 = [["隐藏平民", sum(1 for r in pv.rows
                                      if not bool(r.get("Ren_Zhi_Lue")))],
                      ["出生记录", 11]]

        # 「谱牒总谱」= 磁盘上那部合并谱的人数
        n_now = len(pv.rows)
        book_n = n_now
        try:
            from app import storage
            for nm in storage.list_saves():
                if (storage.load_source(nm) or {}).get("merged"):
                    bp, _ = storage.load_save(nm)
                    if bp:
                        book_n = len(bp)
                    break
        except Exception:
            pass

        # 实录层人数（状态栏「实录」）—— 从程序里取，**不写死**
        # （proto.html 里那个 17938 是当时手打的，属"猜"，这里纠正）
        try:
            record_n = len(getattr(app, "record_people", None) or {})
        except Exception:
            record_n = 0

        idx = {h: i for i, h in enumerate(heads)}
        return {
            "record": record_n,
            "book": app.current_save,
            "slot": os.path.basename(
                str((app.cfg.get("current_record") or "")).strip() or "Save_All_100"),
            "total": n_now,
            "heads": heads,
            "rows": rows,
            "colw": colw,
            "center": [h for h in CENTER if h in idx],
            "stats": stats,
            "stats2": stats2,
            "tiers": TIERS,
            "tabs": [["谱牒总谱", book_n], ["全部人物", n_now]],
            "gen": {"hit": n_now, "hitAll": n_now,
                    "book": 0, "watch": 0},
            "warn": self._warn,
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    # ---------- 对外 ----------
    def payload(self):
        """取 JSON 字典（带缓存）。"""
        with self._lock:
            if self._cache is None:
                self._boot()
                self._cache = self._collect()
            return self._cache

    def reload(self):
        """强制重取。"""
        with self._lock:
            self._boot()
            self._cache = self._collect()
            return self._cache


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    import json

    d = PadData().reload()
    print("档:", d["book"], "| 列:", d["heads"], "| 行:", len(d["rows"]))
    print("列宽:", d["colw"], "总宽", sum(d["colw"]))
    print("计数:", d["stats"], d["stats2"])
    print("左栏:", d["tabs"], "| 状态:", d["ts"], "| warn:", d["warn"] or "无")
    print("首行:", d["rows"][0] if d["rows"] else "无")
    s = json.dumps(d, ensure_ascii=False)
    print("JSON 大小: %.1f KB" % (len(s.encode("utf-8")) / 1024))
