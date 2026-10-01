#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""行为指纹快照 —— v1 ↔ v2 逻辑等价性回归工具（规划 P0）。

思路
----
把「数据迁移 / 人物介绍 / 树形布局 / 世系框 / 工具函数」这些**纯逻辑**的输出
导成一份 JSON 指纹；对 v1 和 v2 各跑一次，再逐路径比对。
只要指纹逐字节一致，就说明重构没有改动业务逻辑（UI 外观是刻意重做的，不参与比对）。

v1 的布局逻辑藏在 `FamilyTreeApp.draw_tree` 内部、没有对外暴露，
这里用 monkeypatch 把 `_draw_person_node` 包一层，把每个人的 (x, y) 劫出来；
世系框则从画布上带 dash 的矩形里反解。

用法
----
    python tools/snapshot.py v2 --out snapshots/v2.json
    python tools/snapshot.py v1 --v1-root "D:\\Desktop\\Ongoing apps\\Family tree" --out snapshots/v1.json
    python tools/snapshot.py compare snapshots/v1.json snapshots/v2.json

判定"差异是移植引入的，还是原版自身就不确定"（重要）
------------------------------------------------------
如果差异集中在 layout.positions，先把**同一个版本**用不同 PYTHONHASHSEED 跑两次自比：

    set PYTHONHASHSEED=0     && python tools/snapshot.py v2 --out snapshots/a.json
    set PYTHONHASHSEED=12345 && python tools/snapshot.py v2 --out snapshots/b.json
    python tools/snapshot.py compare snapshots/a.json snapshots/b.json

自比不一致 → 该版本自身不确定，不能拿它当基准。
v1 的 `visible_people` 是 set，同 root_sort / 同 rank 的节点顺序随 hash 变化，
所以同一存档每次打开树形排布都可能不同；v2 已改为按存档顺序确定迭代。

注意：跑 v1 会把 v1 的 `save_data` 打成空操作、并屏蔽所有对话框，避免污染它的存档。
"""
import argparse
import importlib.util
import json
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
V2_ROOT = os.path.dirname(HERE)
V1_ROOT_DEFAULT = r"D:\Desktop\Ongoing apps\Family tree"
SCALE = 1.0 * (1.1 ** 3)          # 与两版的初始缩放一致
ROUND = 4                          # 坐标保留小数位


# ==================================================================== 迁移脏数据

def migration_fixture():
    """构造一份刻意"脏"的数据，专门覆盖迁移分支。两版必须用完全相同的字面量。

    覆盖点：缺 spouses/bio/root_sort、旧 spouse 单数字段、birth_death 拆分、
    多配偶被拼成一条字符串、悬空配偶引用、自指 associate_of、祖序重复、
    注释里的"X公N代"与"X国Y 余"正则、state_group 反推 state_name、
    state_name 为 None、封国名向下继承。
    """
    return {
        "正常甲": {"father": "", "mother": "", "gender": "男", "generation": 1,
                   "historical": "是", "divine": "否", "note": "", "rank": 0,
                   "spouses": [], "state_name": "", "state_group": "",
                   "fief_title": "", "fief_gen": 0, "root_sort": 0,
                   "bio": "", "birth": "", "death": ""},
        "正常乙": {"father": "正常甲", "gender": "女", "generation": 2, "rank": 1},
        "缺字段丙": {"father": "正常甲", "gender": "男"},
        "旧字段丁": {"father": "正常甲", "gender": "男", "spouse": "正常乙",
                     "birth_death": "-100--50"},
        "空生日戊": {"father": "正常甲", "gender": "男", "birth_death": ""},
        "拼接配偶己": {"gender": "男", "spouses": ["正常乙、正常甲"]},
        "悬空配偶庚": {"gender": "男", "spouses": ["查无此人"]},
        "自指辛": {"gender": "男", "associate_of": "自指辛"},
        "祖序壬": {"gender": "男", "root_sort": 2},
        "祖序癸": {"gender": "男", "root_sort": 2},
        "祖序子": {"gender": "男", "root_sort": 1},
        "祖序丑": {"gender": "男", "root_sort": 2},
        "注释寅": {"gender": "男", "note": "宋公三代"},
        "注释卯": {"gender": "男", "note": "宋国伯 余"},
        "反推辰": {"gender": "男", "state_group": "雷王", "fief_title": "王"},
        "空名巳": {"gender": "男", "state_name": None, "state_group": "风公",
                   "fief_title": "公"},
        "继承父": {"gender": "男", "state_name": "雷", "fief_title": "王",
                   "fief_gen": 1},
        "继承子": {"father": "继承父", "gender": "男"},
        "继承孙": {"father": "继承子", "gender": "男"},
    }


# ==================================================================== v2 指纹

def fingerprint_v2(saves_dir):
    os.chdir(V2_ROOT)
    if V2_ROOT not in sys.path:
        sys.path.insert(0, V2_ROOT)
    from app import bio as bio_mod
    from app import layout as layout_mod
    from app import model, storage
    from app.theme import PAPER

    fp = {"version": "v2", "saves": {}}

    # --- 迁移脏数据 ---
    dirty = migration_fixture()
    changed = model.normalize(dirty)
    fp["migration"] = {"changed": bool(changed), "people": dirty}

    # --- 真实存档 ---
    names = storage.list_saves()
    for name in names:
        people, cutoff = storage.load_save(name)
        normalized = model.normalize(people)
        lay = layout_mod.compute_layout(people, scale=SCALE,
                                        hidden_non_historical={}, cutoff_person=cutoff)
        state_boxes, qing_boxes = layout_mod.state_group_boxes(people, lay, PAPER.tier)
        fp["saves"][name] = {
            "normalized": bool(normalized),
            "cutoff_person": cutoff,
            "people": people,
            "bio": {p: [[t, g] for t, g in bio_mod.generate_bio_segments(people, p)]
                    for p in people},
            "layout": {
                "positions": {p: [round(x, ROUND), round(y, ROUND)]
                              for p, (x, y) in lay.positions.items()},
                "scrollregion": [0, round(lay.scroll_y_start, ROUND),
                                 round(lay.scroll_x, ROUND),
                                 round(lay.scroll_y_end, ROUND)],
                "min_depth": lay.min_depth,
                "max_depth": lay.max_depth,
                "roots_count": len(lay.roots),
                "roots_order": list(lay.roots),
                "children": {p: list(c) for p, c in lay.children.items() if c},
                "associate_groups": {k: list(v) for k, v in lay.associate_groups.items()},
                "shift_count": lay.shift_count,
                # 世系框是彼此独立的图形，绘制/返回顺序不属于行为语义
                # （v1 从画布反解得到堆叠序，v2 是字典迭代序），按坐标归一化后比对
                "state_boxes": sorted([round(v, ROUND) for v in box[:4]]
                                      for box in state_boxes),
                "qing_boxes": sorted([round(v, ROUND) for v in box[:4]]
                                     for box in qing_boxes),
            },
            "helpers": _helpers(model, people),
        }
    return fp


def _helpers(model, people):
    return {
        "num_to_chinese": {str(n): model.num_to_chinese(n) for n in range(0, 121)},
        "tier": {p: model.tier_of(people, p) for p in people},
        "children_count": {p: len(model.get_children(people, p)) for p in people},
        "root_ancestor": {p: model.root_ancestor(people, p) for p in people},
        "descendants_count": {p: len(model.get_descendants(people, p)) for p in people},
    }


# ==================================================================== 时间轴指纹

TIMELINE_SCALES = (2.43, 4.4, 5.0, 12.0)


def fingerprint_timeline(saves_dir):
    """时间轴视图的指纹（**单独一个文件**）。

    刻意不混进 v2.json —— 那份要和 v1 做逐字节等价比对，多加字段会让比对失真。
    """
    os.chdir(V2_ROOT)
    if V2_ROOT not in sys.path:
        sys.path.insert(0, V2_ROOT)
    from app import storage, timeline as tl

    fp = {"version": "v2-timeline", "saves": {}}
    for name in storage.list_saves():
        people, _ = storage.load_save(name)
        entry = {"people": len(people), "scales": {}}
        for sc in TIMELINE_SCALES:
            lay = tl.compute(people, scale=sc)
            entry["scales"][str(sc)] = {
                "year0": lay.year0,
                "positions": {p: [round(x, ROUND), round(y, ROUND)]
                              for p, (x, y) in lay.positions.items()},
                "unplaced": sorted(lay.unplaced),
                "links": {f"{f}->{n}": [[round(a, ROUND), round(b, ROUND)] for a, b in pts]
                          for f, n, pts in lay.links},
                "size": [round(lay.width, ROUND), round(lay.height, ROUND)],
                "link_kinds": [lay.links_same_x, lay.links_folded,
                               lay.links_channel, lay.links_diagonal],
                "shift_count": lay.shift_count,
                # 硬性验收：两个都必须为 0
                "check": tl.self_check(lay),
            }
        fp["saves"][name] = entry
    return fp


# ==================================================================== v1 指纹

def fingerprint_v1(v1_root, saves_dir):
    """跑 v1：monkeypatch 出坐标，并禁用写盘。"""
    import tkinter as tk

    main_py = os.path.join(v1_root, "main.py")
    if not os.path.exists(main_py):
        raise RuntimeError(f"找不到 v1 的 main.py: {main_py}")

    # v1 的 main.py 在导入时会 os.chdir(自己的目录)，所以要在导入前记录
    old_cwd = os.getcwd()
    spec = importlib.util.spec_from_file_location("v1_main", main_py)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["v1_main"] = mod
    if v1_root not in sys.path:
        sys.path.insert(0, v1_root)
    spec.loader.exec_module(mod)

    captured = {}

    # 1) 禁止写盘 + 屏蔽一切会阻塞的对话框
    mod.FamilyTreeApp.save_data = lambda self: True
    mod.messagebox.askyesno = lambda *a, **k: True
    mod.messagebox.showinfo = lambda *a, **k: None
    mod.messagebox.showerror = lambda *a, **k: None
    mod.messagebox.showwarning = lambda *a, **k: None

    # 2) 劫持 _draw_person_node 拿坐标
    orig_draw = mod.FamilyTreeApp._draw_person_node

    def spy_draw(self, name, x, y, node_w, node_h):
        captured[name] = (x, y)
        return orig_draw(self, name, x, y, node_w, node_h)

    mod.FamilyTreeApp._draw_person_node = spy_draw

    # v1 的存档目录
    saves_dir = os.path.join(v1_root, "saves")
    save_names = sorted(
        d for d in os.listdir(saves_dir)
        if os.path.isdir(os.path.join(saves_dir, d))
        and os.path.exists(os.path.join(saves_dir, d, "family.json"))
    ) if os.path.isdir(saves_dir) else []

    root = tk.Tk()
    try:
        app = mod.FamilyTreeApp(root)
        root.update_idletasks()

        fp = {"version": "v1", "migration": None, "saves": {}}

        for save_name in save_names:
            if app.current_save != save_name:
                app.switch_save(save_name)
            if app.current_save != save_name:
                app.current_save = save_name
                app.load_data()
            captured.clear()
            app.draw_tree()                      # 重画一次，确保 captured 属于本次
            root.update_idletasks()

            # 从画布反解世系框：v1 里只有世系框用虚线矩形
            # 国世系 dash=(4,3)  卿世系 dash=(2,2)
            boxes, qboxes = [], []
            for item in app.canvas.find_all():
                if app.canvas.type(item) != "rectangle":
                    continue
                try:
                    dash = app.canvas.itemcget(item, "dash")
                except tk.TclError:
                    continue
                if not dash or dash in ("", "0"):
                    continue
                pattern = [int(float(v)) for v in dash.replace(",", " ").split()]
                coords = [round(float(v), ROUND) for v in app.canvas.coords(item)]
                if pattern[:2] == [4, 3]:
                    boxes.append(coords)
                elif pattern[:2] == [2, 2]:
                    qboxes.append(coords)

            raw_region = str(app.canvas.cget("scrollregion")).split()
            scrollregion = ([round(float(v), ROUND) for v in raw_region]
                            if len(raw_region) == 4 else [0, 0, 0, 0])
            boxes.sort()
            qboxes.sort()

            fp["saves"][save_name] = {
                "normalized": None,
                "cutoff_person": app.cutoff_person,
                "people": app.people,
                "bio": {p: [[t, g] for t, g in app.generate_bio_segments(p)]
                        for p in app.people},
                "layout": {
                    "positions": {p: [round(x, ROUND), round(y, ROUND)]
                                  for p, (x, y) in captured.items()},
                    "scrollregion": scrollregion,
                    "min_depth": None,
                    "max_depth": None,
                    "roots_count": None,
                    "roots_order": None,
                    "children": None,
                    "associate_groups": None,
                    "shift_count": None,
                    "state_boxes": boxes,
                    "qing_boxes": qboxes,
                },
                "helpers": {
                    "num_to_chinese": {str(n): app.num_to_chinese(n)
                                       for n in range(0, 121)},
                    "tier": {p: app.get_person_tier(p)[0] for p in app.people},
                    "children_count": {p: len(app.get_children(p))
                                       for p in app.people},
                    "root_ancestor": None,
                    "descendants_count": None,
                },
            }
            print(f"   已采集 v1 存档 {save_name}: {len(app.people)} 人, "
                  f"{len(captured)} 个坐标, {len(boxes)} 个世系框")

        # v1 的迁移是实例方法，用同一份脏数据跑（必须在取完真实数据之后）
        dirty = migration_fixture()
        app.people = dirty
        app._migrate_old_data()
        fp["migration"] = {"changed": None, "people": dirty}

        return fp
    finally:
        try:
            root.destroy()
        except Exception:
            pass
        os.chdir(old_cwd)


# ==================================================================== 比对

NUMERIC = (int, float)


def diff(a, b, path="", out=None, limit=400):
    if out is None:
        out = []
    if len(out) >= limit:
        return out
    if isinstance(a, NUMERIC) and isinstance(b, NUMERIC) and \
            not isinstance(a, bool) and not isinstance(b, bool):
        if abs(float(a) - float(b)) > 1e-6:
            out.append((path, a, b))
        return out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            if k not in a:
                out.append((f"{path}.{k}", "<v1缺失>", b[k]))
            elif k not in b:
                out.append((f"{path}.{k}", a[k], "<v2缺失>"))
            else:
                diff(a[k], b[k], f"{path}.{k}", out, limit)
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append((f"{path}[长度]", len(a), len(b)))
            return out
        for i, (x, y) in enumerate(zip(a, b)):
            diff(x, y, f"{path}[{i}]", out, limit)
        return out
    if a != b:
        out.append((path, a, b))
    return out


# 刻意与 v1 不同的部分：不是移植失误，不参与"是否等价"的判定，单独汇报。
INTENTIONAL = {
    "bio": "v2 主动优化人物小传行文（补句号 / 去尊号重复 / 尊号加括号分隔），信息不变",
}


def _intentional_of(path):
    """返回该差异路径命中的「有意为之」条目名，没有则返回 None。"""
    parts = path.split(".")
    for key in INTENTIONAL:
        if key in parts:
            return key
    return None


def _short(v, n=90):
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    return s if len(s) <= n else s[:n] + "…"


def do_compare(path_a, path_b, show=40):
    a = json.load(open(path_a, encoding="utf-8"))
    b = json.load(open(path_b, encoding="utf-8"))
    print(f"v1 指纹: {path_a}  ({a.get('version')})")
    print(f"v2 指纹: {path_b}  ({b.get('version')})")
    print()

    # 只比对两边都有的存档
    saves_a = set(a.get("saves", {}))
    saves_b = set(b.get("saves", {}))
    common = sorted(saves_a & saves_b)
    print(f"共同存档: {common}")
    if saves_a - saves_b:
        print(f"仅 v1 有: {sorted(saves_a - saves_b)}")
    if saves_b - saves_a:
        print(f"仅 v2 有: {sorted(saves_b - saves_a)}")
    print()

    all_diffs = []
    intentional = {}
    # 迁移脏数据
    ma, mb = a.get("migration"), b.get("migration")
    if ma and mb:
        d = diff(ma.get("people"), mb.get("people"), "migration.people")
        all_diffs += [("migration",) + x for x in d]
        print(f"[迁移脏数据] 差异 {len(d)} 处")
    # 各存档
    for name in common:
        d = diff(a["saves"][name], b["saves"][name], f"saves.{name}")
        # 过滤掉 v1 本来就不提供的字段
        d = [x for x in d if not _is_v1_unavailable(x)]
        kept = []
        for row in d:
            key = _intentional_of(row[0])
            if key:
                intentional.setdefault(key, []).append((name,) + row)
            else:
                kept.append((name,) + row)
        all_diffs += kept
        n_int = len(d) - len(kept)
        suffix = f"（另有 {n_int} 处属有意为之，见下）" if n_int else ""
        print(f"[{name}] 差异 {len(kept)} 处{suffix}")

    if intentional:
        print()
        print("-" * 60)
        print("以下差异是 v2 有意为之，不计入等价性判定：")
        for key, rows in intentional.items():
            print(f"  · {key}：{len(rows)} 处 —— {INTENTIONAL[key]}")
        for row in intentional.get("bio", [])[:3]:
            scope, path, va, vb = row
            print(f"    [{scope}] {path.rsplit('.', 2)[-2]}")
            print(f"        v1 = {_short(va)}")
            print(f"        v2 = {_short(vb)}")
        print("-" * 60)

    print()
    if not all_diffs:
        print("=" * 60)
        print("✅ 指纹完全一致 —— v1 与 v2 的业务逻辑等价")
        print("=" * 60)
        return 0

    print("=" * 60)
    print(f"❌ 共 {len(all_diffs)} 处差异（最多显示 {show} 条）")
    print("=" * 60)
    print("提示：若差异集中在 layout.positions，先确认是【移植引入】还是【v1 自身不确定】——")
    print("      用不同 PYTHONHASHSEED 把同一版本跑两次再自比即可判定。")
    print("      v1 的 visible_people 是 set，同 root_sort / 同 rank 的节点顺序随 hash 变化，")
    print("      表现为同一存档每次打开树形排布都不同；v2 已改为按存档顺序确定迭代。")
    print()
    for row in all_diffs[:show]:
        scope, path, va, vb = row
        print(f"[{scope}] {path}")
        print(f"    v1 = {_short(va)}")
        print(f"    v2 = {_short(vb)}")
    if len(all_diffs) > show:
        print(f"... 其余 {len(all_diffs) - show} 处省略")
    return 1


V1_NULL_FIELDS = ("min_depth", "max_depth", "roots_count", "roots_order",
                  "children", "associate_groups", "shift_count",
                  "root_ancestor", "descendants_count", "normalized")


def _is_v1_unavailable(row):
    """v1 没暴露的字段（值为 null）不算差异。"""
    path, va, vb = row
    if va == "<v1缺失>" or vb == "<v2缺失>":
        return False
    tail = path.rsplit(".", 1)[-1].split("[")[0]
    if tail in V1_NULL_FIELDS and (va is None or vb is None):
        return True
    if va is None and vb is not None:
        return True
    return False


# ==================================================================== 入口

def main():
    ap = argparse.ArgumentParser(description="v1/v2 行为指纹快照与比对")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p2 = sub.add_parser("v2", help="采集 v2 指纹")
    p2.add_argument("--out", default=os.path.join(V2_ROOT, "snapshots", "v2.json"))
    p2.add_argument("--timeline", action="store_true",
                    help="顺带再写一份时间轴指纹 snapshots/timeline.json"
                         "（单独文件，不动 v2.json —— 那份要和 v1 逐字节比对）")

    p1 = sub.add_parser("v1", help="采集 v1 指纹")
    p1.add_argument("--v1-root", default=V1_ROOT_DEFAULT)
    p1.add_argument("--out", default=os.path.join(V2_ROOT, "snapshots", "v1.json"))

    pc = sub.add_parser("compare", help="比对两份指纹")
    pc.add_argument("file_a")
    pc.add_argument("file_b")
    pc.add_argument("--show", type=int, default=40)

    args = ap.parse_args()

    if args.cmd == "compare":
        sys.exit(do_compare(args.file_a, args.file_b, args.show))

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    try:
        if args.cmd == "v2":
            fp = fingerprint_v2(None)
        else:
            fp = fingerprint_v1(args.v1_root, None)
    except Exception:
        traceback.print_exc()
        sys.exit(2)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(fp, f, ensure_ascii=False, indent=1, sort_keys=True)
    size = os.path.getsize(args.out)
    print(f"✅ {fp['version']} 指纹已写入 {args.out}  ({size:,} 字节)")
    for name, data in fp.get("saves", {}).items():
        lay = data["layout"]
        print(f"   {name}: {len(data['people'])} 人, "
              f"布局 {len(lay['positions'])} 点, "
              f"世系框 {len(lay['state_boxes'])}, 卿框 {len(lay['qing_boxes'])}")

    if getattr(args, "timeline", False):
        tpath = os.path.join(os.path.dirname(args.out), "timeline.json")
        tfp = fingerprint_timeline(None)
        with open(tpath, "w", encoding="utf-8") as f:
            json.dump(tfp, f, ensure_ascii=False, indent=1, sort_keys=True)
        print(f"\n✅ 时间轴指纹已写入 {tpath}  ({os.path.getsize(tpath):,} 字节)")
        bad = 0
        for name, data in tfp["saves"].items():
            rows = []
            for sc, d in data["scales"].items():
                c = d["check"]
                rows.append(f"{sc}px/年 相交{c['card_hits']} 穿卡{c['link_hits']}")
                if c["card_hits"] or c["link_hits"]:
                    bad += 1
            print(f"   {name}: {data['people']} 人 | " + " | ".join(rows))
        print("   " + ("❌ 有存档未达标" if bad else "✅ 全部达标（卡片相交 0、折线穿卡 0）"))


if __name__ == "__main__":
    main()
