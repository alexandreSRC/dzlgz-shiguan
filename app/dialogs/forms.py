"""对话框集合 —— 统一按主题令牌渲染。

每个对话框都走同一套外观：主题底色 + 卡片 + 扁平按钮，
保证 v1 的全部编辑入口都在，且视觉与效果图一致。
"""
import logging
import os
import tkinter as tk
from tkinter import filedialog, ttk

from .. import model, storage
from ..config import load_config, update_config
from ..theme import NODE_STYLES, THEMES, get_theme, get_node_style
from ..widgets import msgbox as messagebox
from ..widgets.kit import (Card, FlatButton, RadioRow, combo_box, hsep, input_box,
                           text_label, tip, vsep)

logger = logging.getLogger(__name__)


def headless():
    """无头模式（验收脚本 / 冒烟测试用）：对话框一律不 `wait_window`。

    模态框在没有 mainloop 的进程里会**永久挂住** —— 整个测试静默假死，
    排查起来极痛苦（踩过）。验收脚本设 `SHIGUAN_HEADLESS=1` 即可绕开。

    ★ 取值规则：**每次调用都读环境变量**（不缓存）。
      截图脚本 `tools/shot2.py` 需要真窗口，但它的招式是
      "先以模态形态弹出首启动主题框 → 再置 SHIGUAN_HEADLESS=1 令
      `finish()` 走 destroy 分支"，所以这里必须动态读，不能 import 时定死。
    """
    return os.environ.get("SHIGUAN_HEADLESS") == "1"


# ==================================================================== 基类

class ThemedDialog(tk.Toplevel):
    def __init__(self, app, title, width=460, height=520, resizable=False):
        super().__init__(app.root)
        self.app = app
        self.theme = app.theme
        self.title(title)
        self.configure(bg=self.theme.bg_panel)
        # ★ 2026-09-26 DPI：对话框尺寸按逻辑像素传入，这里统一升物理像素
        from .. import dpi as _dpi
        self.geometry(f"{_dpi.px(width)}x{_dpi.px(height)}")
        self.resizable(resizable, resizable)
        self.transient(app.root)
        self.grab_set()

        head = tk.Frame(self, bg=self.theme.bg_panel)
        head.pack(fill=tk.X, padx=16, pady=(14, 8))
        tk.Frame(head, width=3, height=14, bg=self.theme.accent).pack(side=tk.LEFT, padx=(0, 8))
        text_label(head, self.theme, title, size=13, bold=True,
                   bg=self.theme.bg_panel).pack(side=tk.LEFT)
        hsep(self, self.theme).pack(fill=tk.X)

        self.body = tk.Frame(self, bg=self.theme.bg_panel)

        self.footer = tk.Frame(self, bg=self.theme.bg_panel)

        # ★ footer **先** pack 到 BOTTOM，body 后 pack。
        #   为什么：pack 按调用顺序分配空间，body 带 expand=True 会先吃掉全部高度，
        #   内容一高（说明 + 卡片 + 单选 + 提示 + 日志）footer 就被挤出窗口 ——
        #   续谱对话框踩过这个坑：确定键根本看不见。
        #   先 pack footer 就把它的空间锁住了，视觉位置不变。
        self.footer.pack(side=tk.BOTTOM, fill=tk.X, padx=16, pady=(0, 14))
        self.body.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)

        self._rows = 0

    # ---- 字段构造 ----
    def row(self, label, widget_builder, extra=None):
        # ★ 2026-09-28 全项目整理（第 3 批，铁律①「尽量汉字左对齐」）：
        #   字段标签原为**右对齐**（`anchor="e"`），而本对话框的**段落标题**
        #   （`text_label(...).pack(anchor="w")`，见 `settings_dialog`）是左对齐
        #   ⇒ 同一对话框里两条对齐线：段标题贴左、字段标签却在 right 边。
        #   改左对齐后，**段标题 / 字段标签共用 body 的左沿**（x 相同），
        #   值列仍由 `width=8` 定宽对齐（定宽保留 —— 值列起点不变，只改字对齐）。
        r = tk.Frame(self.body, bg=self.theme.bg_panel)
        r.pack(fill=tk.X, pady=(0, 7))
        tk.Label(r, text=label, bg=self.theme.bg_panel, fg=self.theme.text_2, width=8,
                 anchor="w", font=(self.theme.font_ui_fallback, self.theme.fs_body)).pack(side=tk.LEFT)
        holder = tk.Frame(r, bg=self.theme.bg_panel)
        holder.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0))
        widget = widget_builder(holder)
        widget.pack(side=tk.LEFT, fill=tk.X, expand=True)
        if extra:
            extra(holder)
        return widget

    def entry_row(self, label, var=None, width=None):
        var = var or tk.StringVar()
        self.row(label, lambda h: input_box(h, self.theme, var, width=width))
        return var

    def combo_row(self, label, values, var=None, width=None):
        var = var or tk.StringVar()
        self.row(label, lambda h: combo_box(h, self.theme, values=values, textvariable=var,
                                           width=width or 12))
        return var

    def radio_row(self, label, var, options, command=None):
        def build(h):
            return RadioRow(h, self.theme, var, options, command=command)
        self.row(label, build)
        return var

    def hint(self, text):
        tk.Label(self.body, text=text, bg=self.theme.bg_panel, fg=self.theme.text_3,
                 font=(self.theme.font_ui_fallback, self.fs_small()), anchor="w",
                 justify=tk.LEFT, wraplength=380).pack(fill=tk.X, pady=(0, 8))

    def fs_small(self):
        return self.theme.fs_body_sm

    # ---- 按钮 ----
    def buttons(self, ok_text="确定", on_ok=None, cancel_text="取消", extra=None):
        """画底部按钮。返回**主按钮**（`ok_text` 那个）供调用方后续 set_enabled。

        ★ 为什么返回：续谱对话框要在「目标谱牒」判定出来之前把「① 先演习」置灰，
          而按钮是最后才画的 —— 不返回就得靠 `footer.winfo_children()[-1]` 猜，
          换个顺序就静默拿错控件。
        """
        if extra:
            extra(self.footer)
        FlatButton(self.footer, self.theme, text=cancel_text, command=self.destroy,
                   kind="default", padx=16).pack(side=tk.RIGHT, pady=2, ipady=4)
        btn = None
        if on_ok:
            btn = FlatButton(self.footer, self.theme, text=ok_text, command=on_ok,
                             kind="primary", padx=20)
            btn.pack(side=tk.RIGHT, padx=(0, 8), pady=2, ipady=4)
        return btn

    def finish(self):
        if headless():
            # 无头模式不阻塞 —— 建完就撤，让调用方继续跑
            self.destroy()
            return
        self.wait_window()


# ==================================================================== 主题选择

def theme_picker_dialog(app):
    dlg = ThemedDialog(app, "选择你喜欢的界面风格", width=760, height=430)
    dlg.resizable(False, False)

    text_label(dlg.body, dlg.theme,
               "两套主题功能完全一致，只是配色不同。点一下卡片就立刻切换，不用再点按钮。",
               size=dlg.fs_small(), fg=dlg.theme.text_2).pack(anchor="w", pady=(0, 12))

    holder = tk.Frame(dlg.body, bg=dlg.theme.bg_panel)
    holder.pack(fill=tk.BOTH, expand=True)
    selected = tk.StringVar(value=app.theme.key)
    cards = {}

    for key, theme in THEMES.items():
        card = tk.Frame(holder, bg=theme.bg_card, highlightthickness=2,
                        highlightbackground=theme.border, bd=0)
        card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 12))

        head = tk.Frame(card, bg=theme.bg_card)
        head.pack(fill=tk.X, padx=12, pady=(12, 4))
        dot = tk.Canvas(head, width=13, height=13, bg=theme.bg_card, highlightthickness=0)
        dot.pack(side=tk.LEFT, padx=(0, 7))
        dot.create_oval(1, 1, 12, 12, outline=theme.accent if key == selected.get() else theme.border_2,
                        width=1.5)
        text_label(head, theme, theme.name, size=13, bold=True, bg=theme.bg_card).pack(side=tk.LEFT)

        text_label(card, theme, theme.desc, size=dlg.fs_small(), fg=theme.text_2,
                   bg=theme.bg_card, justify=tk.LEFT, wraplength=320).pack(anchor="w", padx=12)

        # 迷你预览：顶部条 + 侧栏 + 画布节点
        pv = tk.Frame(card, bg=theme.bg_canvas, height=170, highlightthickness=1,
                      highlightbackground=theme.border)
        pv.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        pv.pack_propagate(False)
        top = tk.Frame(pv, bg=theme.bg_bar, height=18)
        top.pack(fill=tk.X)
        top.pack_propagate(False)
        tk.Frame(top, width=22, height=5, bg=theme.accent).pack(side=tk.LEFT, padx=6, pady=6)
        mid = tk.Frame(pv, bg=theme.bg_canvas)
        mid.pack(fill=tk.BOTH, expand=True)
        side = tk.Frame(mid, bg=theme.bg_panel, width=54)
        side.pack(side=tk.LEFT, fill=tk.Y)
        side.pack_propagate(False)
        for _ in range(4):
            tk.Frame(side, height=7, bg=theme.border).pack(fill=tk.X, padx=6, pady=3)
        cv = tk.Canvas(mid, bg=theme.bg_canvas, highlightthickness=0)
        cv.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        _mini_tree(cv, theme)

        cards[key] = (card, dot)
        for w in (card, head, pv, mid):
            w.bind("<Button-1>", lambda e, k=key: _pick_theme(k))

    def _pick_theme(key):
        """点卡片 = 立即切换。

        以前这里只改选中圈、要再按「就用这套」才生效，而设置对话框里的主题是即点即换 ——
        两处手感不一致，使用者会以为「选了没反应」。
        """
        selected.set(key)
        for k, (card, dot) in cards.items():
            theme = THEMES[k]
            on = (k == key)
            card.configure(highlightbackground=theme.accent if on else theme.border)
            dot.delete("all")
            dot.create_oval(1, 1, 12, 12, outline=theme.accent if on else theme.border_2, width=1.5)
            if on:
                dot.create_oval(4, 4, 9, 9, outline="", fill=theme.accent)
        if key != app.theme.key:
            app.apply_theme(key)

    def apply():
        app.apply_theme(selected.get())
        dlg.destroy()

    dlg.bind("<Return>", lambda e: apply())
    dlg.buttons(ok_text="完成", on_ok=apply)
    dlg.finish()


def _mini_tree(cv, theme):
    """主题预览里的迷你树。"""
    cv.create_line(70, 20, 40, 55, fill=theme.tree_line)
    cv.create_line(70, 20, 100, 55, fill=theme.tree_line)
    cv.create_line(40, 55, 25, 90, fill=theme.tree_line)
    cv.create_line(40, 55, 60, 90, fill=theme.tree_line)
    for x, y, tier in ((70, 20, "帝"), (40, 55, "侯"), (100, 55, "王"), (25, 90, "伯"), (60, 90, "子")):
        cv.create_rectangle(x - 8, y - 12, x + 8, y + 12, outline=theme.tier[tier], width=2)


# ==================================================================== 添加始祖

def add_ancestor_dialog(app):
    dlg = ThemedDialog(app, "添加始祖", width=460, height=640)
    t = dlg.theme

    var_name = dlg.entry_row("姓名", width=20)
    _char_bar(dlg, dlg.body, var_name)
    var_gender = tk.StringVar(value="男")
    dlg.radio_row("性别", var_gender, [("男", "男"), ("女", "女")])
    var_hist = tk.StringVar(value="否")
    dlg.radio_row("史实", var_hist, [("是", "是"), ("否", "否")])
    var_divine = tk.StringVar(value="否")
    dlg.radio_row("神祖", var_divine, [("是", "是"), ("否", "否")])
    var_gen = dlg.combo_row("代数", [str(i) for i in range(1, 101)], width=6)
    var_gen.set("1")
    var_father = dlg.combo_row("父亲", [""] + [n for n, i in app.people.items()
                                              if i.get("gender") == "男"], width=16)
    var_mother = dlg.combo_row("母亲", [""] + [n for n, i in app.people.items()
                                              if i.get("gender") == "女"], width=16)
    var_tier = dlg.combo_row("爵位", ["", "无", "卿", "子", "伯", "侯", "公", "王", "帝"], width=6)
    var_state = dlg.entry_row("封国", width=10)
    var_fief_gen = dlg.entry_row("君序", width=6)
    var_root_sort = dlg.combo_row("始祖排序", [""] + [str(i) for i in range(1, 101)], width=6)
    var_note = dlg.entry_row("尊号", width=20)
    var_birth = dlg.entry_row("生年", width=10)
    var_death = dlg.entry_row("卒年", width=10)

    def do_add():
        name = var_name.get().strip()
        if not name:
            messagebox.showwarning("提示", "姓名不能为空", parent=dlg)
            return
        if name in app.people:
            messagebox.showwarning("提示", "该名字已存在", parent=dlg)
            return
        tier = var_tier.get()
        state = var_state.get().strip()
        try:
            fief_gen = int(var_fief_gen.get()) if var_fief_gen.get().strip() else 0
        except ValueError:
            fief_gen = 0
        try:
            root_sort = int(var_root_sort.get()) if var_root_sort.get() else 0
        except ValueError:
            root_sort = 0
        if root_sort > 0:
            model.shift_root_sorts(app.people, root_sort, old_sort=0)
        app.people[name] = model.new_person(
            father=var_father.get(), mother=var_mother.get(),
            note=var_note.get().strip(), gender=var_gender.get(),
            generation=int(var_gen.get() or 1), historical=var_hist.get(),
            divine=var_divine.get(), birth=var_birth.get().strip(),
            death=var_death.get().strip(), rank=0,
            state_group=(state + tier) if state and tier else "",
            state_name=state, fief_title=tier, fief_gen=fief_gen, root_sort=root_sort,
        )
        app._record(f"添加始祖: {name}")
        app.save_data()
        app._refresh_all()
        dlg.destroy()
        app.select_person(name)

    dlg.buttons(ok_text="确定添加", on_ok=do_add)
    dlg.finish()


# ==================================================================== 添加子嗣

def add_child_dialog(app, parent_name):
    if parent_name not in app.people:
        return
    p_info = app.people[parent_name]
    is_mother = p_info.get("gender") == "女"
    role = "母亲" if is_mother else "父亲"
    p_gen = p_info.get("generation", 0)
    child_gen = p_gen + 1 if p_gen > 0 else 1

    dlg = ThemedDialog(app, f"给 {parent_name} 添加子嗣", width=470, height=650)
    t = dlg.theme

    var_name = dlg.entry_row("孩子姓名", width=20)
    _char_bar(dlg, dlg.body, var_name)
    other_label = "父亲" if is_mother else "母亲"
    want = "男" if is_mother else "女"
    var_other = dlg.combo_row(other_label, [""] + [n for n, i in app.people.items()
                                                  if i.get("gender") == want], width=16)
    var_gender = tk.StringVar(value="男")
    dlg.radio_row("性别", var_gender, [("男", "男"), ("女", "女")])
    var_hist = tk.StringVar(value="否")
    dlg.radio_row("史实", var_hist, [("是", "是"), ("否", "否")])
    var_divine = tk.StringVar(value="否")
    dlg.radio_row("神祖", var_divine, [("是", "是"), ("否", "否")])

    default_rank = len(model.get_children(app.people, parent_name)) + 1
    var_rank = dlg.combo_row("排行", [str(i) for i in range(1, 21)], width=6)
    var_rank.set(str(default_rank))
    var_tier = dlg.combo_row("爵位", [""] + ["无", "卿", "子", "伯", "侯", "公", "王", "帝"], width=6)
    var_state = dlg.entry_row("封国", width=10)
    var_state.set(p_info.get("state_name", ""))
    var_fief_gen = dlg.entry_row("君序", width=6)
    var_note = dlg.entry_row("尊号", width=20)
    var_birth = dlg.entry_row("生年", width=10)
    var_death = dlg.entry_row("卒年", width=10)

    inherit = tk.BooleanVar(value=False)
    p_tier = p_info.get("fief_title", "")
    p_fief_gen = p_info.get("fief_gen", 0)
    inherit_text = (f"继承{role}爵位封国（{p_tier or '无'}·{p_info.get('state_name') or '无'}·"
                    f"{p_fief_gen + 1 if p_fief_gen > 0 else 0}代）")
    chk = tk.Checkbutton(dlg.body, text=inherit_text, variable=inherit, bg=t.bg_panel,
                         fg=t.text, selectcolor=t.bg_input, activebackground=t.bg_panel,
                         activeforeground=t.text, bd=0, highlightthickness=0,
                         font=(t.font_ui_fallback, t.fs_body), anchor="w")
    chk.pack(fill=tk.X, pady=(4, 8))

    def on_inherit(*_):
        if inherit.get():
            var_tier.set(p_tier)
            var_state.set(p_info.get("state_name", ""))
            child_fief = p_fief_gen + 1 if p_fief_gen > 0 else 0
            var_fief_gen.set(str(child_fief) if child_fief > 0 else "")
        else:
            var_tier.set("")
            var_fief_gen.set("")
    inherit.trace_add("write", on_inherit)

    def do_add():
        name = var_name.get().strip()
        if not name:
            messagebox.showwarning("提示", "名字不能为空", parent=dlg)
            return
        if name in app.people:
            messagebox.showwarning("提示", "该名字已存在", parent=dlg)
            return
        tier = var_tier.get()
        state = var_state.get().strip()
        try:
            fief_gen = int(var_fief_gen.get()) if var_fief_gen.get().strip() else 0
        except ValueError:
            fief_gen = 0
        try:
            rank = int(var_rank.get()) if var_rank.get() else 0
        except ValueError:
            rank = 0
        other = var_other.get()
        record = model.new_person(
            father=other if is_mother else parent_name,
            mother=parent_name if is_mother else other,
            color=p_info.get("color", ""), bg_color=p_info.get("bg_color", ""),
            note=var_note.get().strip(), gender=var_gender.get(),
            generation=child_gen, historical=var_hist.get(), divine=var_divine.get(),
            birth=var_birth.get().strip(), death=var_death.get().strip(), rank=rank,
            state_group=(state + tier) if state and tier else "",
            state_name=state, fief_title=tier, fief_gen=fief_gen, root_sort=0,
        )
        app.people[name] = record
        app._record(f"添加子嗣: {name} ({role}: {parent_name})")
        app.save_data()
        app._refresh_all()
        dlg.destroy()
        app.select_person(parent_name)

    dlg.buttons(ok_text="确定添加", on_ok=do_add)
    dlg.finish()


# ==================================================================== 同代人

def add_associate_dialog(app, ref_name):
    if ref_name not in app.people:
        return
    dlg = ThemedDialog(app, f"在 {ref_name} 右侧添加同代人", width=460, height=520)
    t = dlg.theme

    var_name = dlg.entry_row("姓名", width=20)
    _char_bar(dlg, dlg.body, var_name)
    var_type = tk.StringVar(value="friend")
    dlg.radio_row("关联类型", var_type, [("friend", "朋友"), ("spouse", "夫妻"), ("clan", "同家族")])
    var_rank = dlg.combo_row("排序位置", [str(i) for i in range(1, 21)], width=6)
    var_rank.set("1")
    var_gender = tk.StringVar(value="男")
    dlg.radio_row("性别", var_gender, [("男", "男"), ("女", "女")])
    var_hist = tk.StringVar(value="否")
    dlg.radio_row("史实", var_hist, [("是", "是"), ("否", "否")])
    var_divine = tk.StringVar(value="否")
    dlg.radio_row("神祖", var_divine, [("是", "是"), ("否", "否")])
    var_note = dlg.entry_row("尊号", width=20)
    var_birth = dlg.entry_row("生年", width=10)
    var_death = dlg.entry_row("卒年", width=10)

    def do_add():
        name = var_name.get().strip()
        if not name:
            messagebox.showwarning("提示", "请输入姓名", parent=dlg)
            return
        if name in app.people:
            messagebox.showwarning("提示", "该名字已存在", parent=dlg)
            return
        atype = var_type.get()
        rank = int(var_rank.get() or 1)
        ref = app.people[ref_name]
        ref_gen = ref.get("generation", 1)
        common = dict(note=var_note.get().strip(), gender=var_gender.get(),
                      generation=ref_gen, historical=var_hist.get(), divine=var_divine.get(),
                      birth=var_birth.get().strip(), death=var_death.get().strip(),
                      rank=0, associate_rank=rank)
        if atype == "spouse":
            app.people[name] = model.new_person(
                father="", mother="", spouses=[ref_name], associate_of=ref_name,
                associate_type=atype, **common)
            ref.setdefault("spouses", [])
            if name not in ref["spouses"]:
                ref["spouses"].append(name)
        else:
            app.people[name] = model.new_person(
                father=ref.get("father", ""), mother=ref.get("mother", ""),
                associate_of="", associate_type=atype, hide_parent_line=True, **common)
        app._record(f"添加同代人: {name} (在 {ref_name} 右侧)")
        app.save_data()
        app._refresh_all()
        dlg.destroy()
        app.select_person(name)

    dlg.buttons(ok_text="确定", on_ok=do_add)
    dlg.finish()


def convert_to_associate_dialog(app, person):
    if person not in app.people:
        return
    candidates = sorted(n for n in app.people
                        if n != person and app.people[n].get("father"))
    if not candidates:
        messagebox.showinfo("提示", "没有可选的参考人物（参考人物必须有父亲）")
        return
    dlg = ThemedDialog(app, f"将 {person} 转为同代人", width=420, height=260)
    var_ref = dlg.combo_row("参考人物", candidates, width=18)
    var_ref.set(candidates[0])
    dlg.hint(f"{person} 及其所有子孙的代数会自动偏移对齐；参考人物必须已有父/母。")

    def do_convert():
        ref_name = var_ref.get()
        if not ref_name:
            messagebox.showwarning("提示", "请选择参考人物", parent=dlg)
            return
        ref = app.people[ref_name]
        ref_father = ref.get("father", "")
        ref_mother = ref.get("mother", "")
        if not ref_father and not ref_mother:
            messagebox.showwarning("提示", "参考人物没有父亲/母亲，无法设定兄弟关系", parent=dlg)
            return
        if ref_father == person or ref_mother == person:
            messagebox.showwarning("提示", "参考人物的父/母就是本人，会造成循环", parent=dlg)
            return
        if ref_name in model.get_descendants(app.people, person):
            messagebox.showwarning("提示", "参考人物是该始祖的后代，会造成循环引用", parent=dlg)
            return
        app._record(f"转为同代人: {person}, 参照: {ref_name}")
        old_gen = app.people[person].get("generation", 0)
        ref_gen = app.people[ref_name].get("generation", 0)
        app.people[person]["father"] = ref_father
        app.people[person]["mother"] = ref_mother
        app.people[person]["hide_parent_line"] = True
        app.people[person]["root_sort"] = 0
        if old_gen and ref_gen and old_gen != ref_gen:
            delta = ref_gen - old_gen
            for n in model.get_descendants(app.people, person):
                app.people[n]["generation"] = app.people[n].get("generation", 1) + delta
        app.save_data()
        app._refresh_all()
        dlg.destroy()

    dlg.buttons(ok_text="确定", on_ok=do_convert)
    dlg.finish()


# ==================================================================== 人物介绍

def bio_dialog(app, person):
    from .. import bio as bio_mod
    if person not in app.people:
        return
    dlg = ThemedDialog(app, f"编辑介绍 · {person}", width=560, height=420, resizable=True)
    t = dlg.theme
    info = app.people[person]

    text_w = tk.Text(dlg.body, wrap=tk.WORD, font=(t.font_name, 13), relief=tk.FLAT,
                     bg=t.bg_input, fg=t.text, insertbackground=t.text,
                     highlightthickness=1, highlightbackground=t.border, bd=0)
    text_w.pack(fill=tk.BOTH, expand=True)
    text_w.insert("1.0", info.get("bio") or bio_mod.generate_bio(app.people, person))

    def save():
        info["bio"] = text_w.get("1.0", tk.END).strip()
        app._record(f"保存人物介绍: {person}")
        app.save_data()
        app._refresh_all()
        dlg.destroy()

    def reset():
        info["bio"] = ""
        text_w.delete("1.0", tk.END)
        text_w.insert("1.0", bio_mod.generate_bio(app.people, person))

    dlg.buttons(ok_text="保存", on_ok=save,
                extra=lambda f: FlatButton(f, t, text="恢复默认", command=reset,
                                           kind="default", padx=14).pack(side=tk.RIGHT, padx=(0, 8), pady=2, ipady=4))
    dlg.finish()


# ==================================================================== 存档管理

def _book_manager_body(app, dlg, height=110):
    """谱牒档列表 + 新建 / 重命名 / 复制 / 删除 / 导出 / 导入。

    `save_manager_dialog` 与 `archive_dialog` **共用这一块** —— 免得两处各写一份
    增删改查，改一处漏一处。返回 `(listbox, reload_list, selected_name)`，
    「切换到选中」由调用方自己接（存档对话框是底部的「切换」按钮）。
    """
    t = dlg.theme
    holder = tk.Frame(dlg.body, bg=t.bg_input, height=height)
    holder.pack(fill=tk.X, pady=(2, 4))
    holder.pack_propagate(False)
    listbox = tk.Listbox(holder, font=(t.font_ui_fallback, t.fs_body), bg=t.bg_input,
                         fg=t.text, selectbackground=t.accent, selectforeground=t.accent_on,
                         bd=0, highlightthickness=1, highlightbackground=t.border,
                         activestyle="none")
    sb = tk.Scrollbar(holder, orient=tk.VERTICAL, command=listbox.yview,
                      bg=t.border_2, troughcolor=t.bg_panel, highlightthickness=0, bd=0,
                      width=t.scrollbar_w, relief=tk.FLAT)
    listbox.configure(yscrollcommand=sb.set)
    listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    sb.pack(side=tk.RIGHT, fill=tk.Y)

    def reload_list():
        listbox.delete(0, tk.END)
        names = storage.list_saves()
        for i, s in enumerate(names):
            try:
                people, _ = storage.load_save(s)
                count = len(people)
            except Exception:
                count = -1
            tag = "（空存档）" if count == 0 else (f"{count} 人" if count > 0 else "读取失败")
            # ★ 保护档：自动续谱会跳过它（使用者 2026-09-21 拍板）。
            #   列表里用一个「保」字标出来，一眼能看出哪几部不会被自动动。
            mark = "保 " if storage.is_protected(s) else "　 "
            listbox.insert(tk.END, f"{mark}{s}    {tag}")
            if s == app.current_save:
                listbox.selection_set(i)
                listbox.see(i)
        return names

    def selected_name():
        sel = listbox.curselection()
        if not sel:
            return None
        names = storage.list_saves()
        return names[sel[0]] if sel[0] < len(names) else None

    def do_new():
        from tkinter import simpledialog
        name = simpledialog.askstring("新建谱牒", "请输入谱牒名称：", parent=dlg)
        if not name:
            return
        name = storage.sanitize_name(name)
        if not name:
            messagebox.showwarning("警告", "谱牒名称不能为空", parent=dlg)
            return
        if not storage.create_save(name):
            messagebox.showwarning("警告", f"谱牒 '{name}' 已存在", parent=dlg)
            return
        app.switch_save(name)
        reload_list()

    def do_rename():
        from tkinter import simpledialog
        name = selected_name()
        if not name:
            return
        new = simpledialog.askstring("重命名", f"将 '{name}' 重命名为：",
                                     initialvalue=name, parent=dlg)
        if not new or new == name:
            return
        new = storage.sanitize_name(new)
        if not storage.rename_save(name, new):
            messagebox.showwarning("警告", f"谱牒 '{new}' 已存在", parent=dlg)
            return
        if app.current_save == name:
            app.current_save = new
            update_config(current_save=new)
            app._refresh_all()
        reload_list()

    def do_duplicate():
        from tkinter import simpledialog
        name = selected_name()
        if not name:
            return
        new = simpledialog.askstring("复制谱牒", f"将 '{name}' 复制为：",
                                     initialvalue=name + "_副本", parent=dlg)
        if not new:
            return
        if not storage.duplicate_save(name, storage.sanitize_name(new)):
            messagebox.showwarning("警告", "目标谱牒已存在", parent=dlg)
            return
        reload_list()

    def do_delete():
        name = selected_name()
        if not name:
            return
        if name == app.current_save:
            messagebox.showwarning("警告", "不能删除当前正在使用的谱牒", parent=dlg)
            return
        # ★ 2026-09-26 修：此处曾写成 `if not ask_danger(...)` —— 判据反了：
        #   点「删除」不生效，点「取消」反而删档（危险动作反着走）。
        if not messagebox.ask_danger("删除谱牒",
                                     f"确定要永久删除谱牒《{name}》吗？\n此操作不可恢复！",
                                     ok_text="删除", parent=dlg):
            return
        storage.delete_save(name)
        reload_list()

    def do_export():
        if not app.current_save:
            messagebox.showinfo("提示", "当前没有谱牒可导出", parent=dlg)
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=[("JSON文件", "*.json")],
            initialfile=f"{app.current_save}_家族树.json", title="导出谱牒", parent=dlg)
        if not path:
            return
        try:
            storage.export_save(app.current_save, path)
            messagebox.showinfo("成功", f"谱牒已导出到：\n{path}", parent=dlg)
        except Exception as e:
            messagebox.showerror("错误", f"导出失败：{e}", parent=dlg)

    def do_import():
        from tkinter import simpledialog
        path = filedialog.askopenfilename(
            filetypes=[("JSON文件", "*.json"), ("所有文件", "*.*")],
            title="选择要导入的谱牒文件", parent=dlg)
        if not path:
            return
        base = storage.sanitize_name(os.path.splitext(os.path.basename(path))[0])
        name = simpledialog.askstring("导入谱牒", "请为导入的谱牒命名：",
                                      initialvalue=base, parent=dlg)
        if not name:
            return
        try:
            count = storage.import_save(path, storage.sanitize_name(name))
            app.switch_save(storage.sanitize_name(name))
            messagebox.showinfo("成功",
                                f"成功导入谱牒：{name}\n\n共 {count} 个人物数据", parent=dlg)
            reload_list()
        except Exception as e:
            messagebox.showerror("错误", f"导入失败：{e}", parent=dlg)

    def do_protect():
        """打 / 摘「保护档」标记 —— 自动续谱遇到它就跳过，不覆盖手写记录。"""
        name = selected_name()
        if not name:
            messagebox.showinfo("提示", "先在上面选一部谱牒。", parent=dlg)
            return
        now = storage.is_protected(name)
        storage.set_protected(name, not now)
        reload_list()
        messagebox.showinfo(
            "保护档",
            f"《{name}》已{'取消保护' if now else '设为保护档'}。\n\n"
            + ("自动续谱不会再自动续写它（想手动续写请先取消保护）。"
               if not now else "自动续谱遇到它会正常新建 / 续写。"),
            parent=dlg)

    btns = tk.Frame(dlg.body, bg=t.bg_panel)
    btns.pack(fill=tk.X, pady=(4, 0))
    for text, cmd, kind in (("新建", do_new, "default"), ("重命名", do_rename, "default"),
                            ("复制", do_duplicate, "default"), ("删除", do_delete, "danger"),
                            ("导出", do_export, "default"), ("导入", do_import, "default"),
                            ("保护档", do_protect, "edit")):
        FlatButton(btns, t, text=text, command=cmd, kind=kind, padx=10).pack(
            side=tk.LEFT, padx=2, pady=2, ipady=3)
    tip(btns, "「保」= 保护档：自动续谱遇到它会跳过，不覆盖你手写的原始记录。\n"
              "选中一部谱牒，点「保护档」按钮即可打上 / 摘下。")

    reload_list()
    return listbox, reload_list, selected_name


def save_manager_dialog(app):
    dlg = ThemedDialog(app, "存档管理", width=520, height=440)
    t = dlg.theme
    text_label(dlg.body, t, "谱牒档列表：", size=t.fs_title, bold=True,
               bg=t.bg_panel).pack(anchor="w", pady=(0, 6))

    listbox, reload_list, selected_name = _book_manager_body(app, dlg, height=180)

    def do_switch():
        name = selected_name()
        if name:
            app.switch_save(name)
            dlg.destroy()

    btns = tk.Frame(dlg.body, bg=t.bg_panel)
    btns.pack(fill=tk.X, pady=(6, 0))
    FlatButton(btns, t, text="切换到选中", command=do_switch, kind="primary",
               padx=14).pack(side=tk.LEFT, pady=2, ipady=3)

    dlg.buttons(ok_text=None, cancel_text="关闭")
    dlg.finish()


# ==================================================================== 设置

def settings_dialog(app):
    dlg = ThemedDialog(app, "设置", width=520, height=580)
    t = dlg.theme
    cfg = load_config()

    text_label(dlg.body, t, "界面主题", size=t.fs_title, bold=True, bg=t.bg_panel).pack(anchor="w")
    var_theme = tk.StringVar(value=app.theme.key)
    dlg.radio_row("主题", var_theme,
                  [(k, v.name) for k, v in THEMES.items()],
                  command=lambda: app.apply_theme(var_theme.get()))
    dlg.hint("切换后立即生效，并写入 config.json。")

    text_label(dlg.body, t, "画布节点版式", size=t.fs_title, bold=True,
               bg=t.bg_panel).pack(anchor="w", pady=(8, 0))
    var_style = tk.StringVar(value=get_node_style(app.cfg.get("node_style", "")))
    dlg.radio_row("版式", var_style, NODE_STYLES,
                  command=lambda: app.apply_node_style(var_style.get()))
    dlg.hint("经典版：透明框 + 顶部爵位装饰线（v1 原版画法）。"
             "竖向卡片式：淡底卡片 + 左侧爵位色条 + 右上角爵位小字，"
             "节点密集时更清楚。只改画法，不改变布局与间距。")

    text_label(dlg.body, t, "生僻字快捷条", size=t.fs_title, bold=True,
               bg=t.bg_panel).pack(anchor="w", pady=(8, 0))
    var_chars = dlg.entry_row("快捷汉字", width=30)
    var_chars.set(app.quick_chars)
    dlg.hint("出现在添加/新增对话框的姓名框下方，点击即可输入（最多 20 个）。")

    text_label(dlg.body, t, "云同步备份", size=t.fs_title, bold=True,
               bg=t.bg_panel).pack(anchor="w", pady=(8, 0))
    var_cloud = dlg.entry_row("备份目录", width=30)
    var_cloud.set(cfg.get("cloud_backup_dir", ""))

    def pick_dir():
        path = filedialog.askdirectory(title="选择云同步文件夹", parent=dlg,
                                       initialdir=var_cloud.get() or None)
        if path:
            var_cloud.set(path)
    dlg.row("", lambda h: FlatButton(h, t, text="选择目录", command=pick_dir,
                                     kind="default", padx=12))

    text_label(dlg.body, t, "AI 截图识别", size=t.fs_title, bold=True,
               bg=t.bg_panel).pack(anchor="w", pady=(8, 0))
    var_key = dlg.entry_row("豆包 Key", width=30)
    var_key.set(cfg.get("doubao_api_key", ""))
    dlg.hint("火山引擎 ARK API Key，用于识别游戏「贤士出生」截图。")

    def save():
        app.quick_chars = var_chars.get().strip()[:20]
        update_config(quick_chars=app.quick_chars,
                      cloud_backup_dir=var_cloud.get().strip(),
                      doubao_api_key=var_key.get().strip())
        app.cfg = load_config()
        app._init_detector()
        messagebox.showinfo("成功", "设置已保存", parent=dlg)
        dlg.destroy()

    dlg.buttons(ok_text="保存", on_ok=save)
    dlg.finish()


# ==================================================================== 粘贴导入

def paste_dialog(app, rows):
    """把剪贴板表格解析后批量新增/更新。"""
    dlg = ThemedDialog(app, "从 Excel 粘贴", width=760, height=520, resizable=True)
    t = dlg.theme

    known = {c[1]: c[0] for c in model.TABLE_COLUMNS}
    header = [h.strip() for h in rows[0]]
    has_header = any(h in known for h in header)
    if not has_header:
        header = [c[1] for c in model.TABLE_COLUMNS if c[0] not in ("__seq__",)]
    fields = [known.get(h) for h in header]
    data_rows = rows[1:] if has_header else rows

    text_label(dlg.body, t,
               f"识别到 {len(data_rows)} 行 · {len([f for f in fields if f])} 列可映射。"
               f"首列需为姓名，同名人物将被更新，不存在则新增。",
               size=t.fs_small(), fg=t.text_2).pack(anchor="w", pady=(0, 8))

    holder = tk.Frame(dlg.body, bg=t.bg_panel)
    holder.pack(fill=tk.BOTH, expand=True)
    preview = tk.Text(holder, font=(t.font_ui_fallback, t.fs_body_sm), bg=t.bg_input, fg=t.text,
                      bd=0, highlightthickness=1, highlightbackground=t.border, wrap=tk.NONE)
    preview.pack(fill=tk.BOTH, expand=True)
    preview.insert("1.0", "\t".join(header) + "\n" + "\n".join("\t".join(r) for r in data_rows[:60]))
    preview.configure(state="disabled")

    var_update = tk.BooleanVar(value=True)
    _cb = tk.Checkbutton(dlg.body, text="同名人物覆盖更新", variable=var_update,
                         bg=t.bg_panel, fg=t.text, selectcolor=t.bg_input,
                         activebackground=t.bg_panel,
                         bd=0, highlightthickness=0, anchor="w",
                         font=(t.font_ui_fallback, t.fs_body))
    _cb.pack(fill=tk.X, pady=(6, 0))
    tip(_cb, "勾上：谱里已有同名人物时，用文件里的值覆盖他。\n"
             "不勾：同名的一律跳过（保留你谱里现有的）。")

    def do_import():
        added = updated = skipped = 0
        for row in data_rows:
            record = {}
            name = None
            for i, field in enumerate(fields):
                if not field or i >= len(row):
                    continue
                raw = row[i].strip()
                if field == "__name__":
                    name = raw
                    continue
                if field in ("__seq__", "__bio__", "__life__"):
                    continue
                if field in ("generation", "rank", "fief_gen", "root_sort"):
                    try:
                        record[field] = int(raw) if raw else 0
                    except ValueError:
                        record[field] = 0
                elif field == "spouses":
                    record[field] = [s for s in raw.replace(",", "、").split("、")
                                     if s in app.people]
                else:
                    record[field] = raw
            if not name:
                skipped += 1
                continue
            if name in app.people:
                if not var_update.get():
                    skipped += 1
                    continue
                app.people[name].update(record)
                updated += 1
            else:
                app.people[name] = model.new_person(**record)
                added += 1
        app._record(f"粘贴导入: 新增{added} 更新{updated}")
        app.save_data()
        app._refresh_all()
        dlg.destroy()
        messagebox.showinfo("完成", f"新增 {added} 人，更新 {updated} 人，跳过 {skipped} 行。")

    dlg.buttons(ok_text="确认导入", on_ok=do_import)
    dlg.finish()


# ==================================================================== AI 识别

def ai_dialog(app):
    from ai_recognizer import AIDetector, DOUBAO_VISION_MODEL
    cfg = load_config()
    key = cfg.get("doubao_api_key", "")
    if not key:
        if messagebox.askyesno("提示", "尚未配置豆包 API Key，是否现在配置？"):
            settings_dialog(app)
        return
    if not app.detector or getattr(app.detector, "provider", "") != "doubao":
        app.detector = AIDetector(api_key=key, model=DOUBAO_VISION_MODEL, provider="doubao")

    paths = filedialog.askopenfilenames(
        title="选择游戏截图（可多选）",
        filetypes=[("图片文件", "*.png *.jpg *.jpeg *.bmp *.webp"), ("所有文件", "*.*")],
        parent=app.root)
    if not paths:
        return

    dlg = ThemedDialog(app, "豆包 AI 识别中", width=420, height=170)
    t = dlg.theme
    label = text_label(dlg.body, t, "正在调用豆包 AI 识别…", size=t.fs_body, bg=t.bg_panel)
    label.pack(anchor="w", pady=(0, 8))
    bar = ttk.Progressbar(dlg.body, length=360, mode="determinate", maximum=len(paths))
    bar.pack(fill=tk.X)

    def progress(cur, total, filename):
        label.configure(text=f"正在分析 ({cur}/{total}): {filename}")
        bar["value"] = cur
        dlg.update()

    result = {}

    def work():
        try:
            raw = app.detector.analyze_batch(list(paths), progress_callback=progress)
            result["raw"] = raw
        except Exception as e:
            result["error"] = str(e)
        dlg.destroy()

    dlg.after(100, work)
    dlg.finish()

    if result.get("error"):
        messagebox.showerror("识别失败", f"豆包 AI 识别出错：\n{result['error']}")
        return
    raw = result.get("raw") or []
    if not raw:
        messagebox.showinfo("识别结果", "未能从截图中识别到任何生子记录。")
        return
    matched = app.detector.match_against_tree(raw, set(app.people.keys()))
    _ai_results_dialog(app, matched)


def _ai_results_dialog(app, results):
    dlg = ThemedDialog(app, "AI 识别结果确认", width=820, height=540, resizable=True)
    t = dlg.theme

    seen, deduped = set(), []
    for r in results:
        key = (r.get("child", ""), r.get("father", ""))
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    results = deduped
    matched = sum(1 for r in results if r["father_exists"])

    text_label(dlg.body, t,
               f"共识别 {len(results)} 条生子记录 | 已在家族树中 {matched} 条 | "
               f"未匹配 {len(results) - matched} 条",
               size=t.fs_title, bold=True, bg=t.bg_panel).pack(anchor="w")
    text_label(dlg.body, t, "勾选要添加的记录；未精确匹配的会尝试相似姓名（橙色标注）。",
               size=t.fs_small(), fg=t.text_3, bg=t.bg_panel).pack(anchor="w", pady=(0, 8))

    holder = tk.Frame(dlg.body, bg=t.bg_panel)
    holder.pack(fill=tk.BOTH, expand=True)
    vars_ = []
    for r in results:
        row = tk.Frame(holder, bg=t.bg_card, highlightthickness=1,
                       highlightbackground=t.border)
        row.pack(fill=tk.X, pady=1)
        var = tk.BooleanVar(value=bool(r["can_add"]))
        vars_.append((var, r))
        tk.Checkbutton(row, variable=var, bg=t.bg_card, activebackground=t.bg_card,
                       selectcolor=t.bg_input, bd=0, highlightthickness=0).pack(side=tk.LEFT, padx=4)
        suggested = r.get("suggested_father")
        father = suggested if suggested and suggested != r.get("father") else r.get("father", "")
        cells = [r.get("year", ""), father, r.get("child", ""), r.get("gender", "")]
        for text in cells:
            tk.Label(row, text=text, bg=t.bg_card, fg=t.text, width=14, anchor="w",
                     font=(t.font_ui_fallback, t.fs_body)).pack(side=tk.LEFT, padx=3)
        if suggested and suggested != r.get("father"):
            status, color = f"✓ {suggested}", t.tier["王"]
        elif r["father_exists"]:
            status, color = "已匹配", t.accent
        else:
            status, color = "未匹配", t.danger
        tk.Label(row, text=status, bg=t.bg_card, fg=color, anchor="w", width=14,
                 font=(t.font_ui_fallback, t.fs_small, "bold")).pack(side=tk.LEFT, padx=3)

    def select_all():
        for var, r in vars_:
            var.set(bool(r["father_exists"]))

    def confirm():
        picked = [r for var, r in vars_ if var.get()]
        if not picked:
            messagebox.showinfo("提示", "请勾选需要添加的记录", parent=dlg)
            return
        added = skipped = 0
        errors = []
        for r in picked:
            father = (r.get("suggested_father") or r.get("father") or "").strip()
            child = (r.get("child") or "").strip()
            mother = (r.get("mother") or "").strip()
            if not father or not child:
                errors.append(f"数据不完整: 父亲={father} 孩子={child}")
                continue
            if father not in app.people:
                errors.append(f"父亲 '{father}' 不在家族树中")
                skipped += 1
                continue
            if child in app.people:
                errors.append(f"孩子 '{child}' 已存在")
                skipped += 1
                continue
            p = app.people[father]
            p_gen = p.get("generation", 0)
            app.people[child] = model.new_person(
                father=father if p.get("gender") != "女" else mother,
                mother=mother if p.get("gender") != "女" else father,
                gender=r.get("gender", "男"),
                generation=p_gen + 1 if p_gen > 0 else 1,
                historical="否", divine="否",
                rank=len(model.get_children(app.people, father)) + 1,
                color=p.get("color", ""), bg_color=p.get("bg_color", ""),
                state_name=p.get("state_name", ""), state_group=p.get("state_group", ""),
            )
            added += 1
        if added:
            app._record(f"AI批量添加 {added} 个子嗣")
            app.newly_added = {r.get("child") for r in picked if r.get("child")}
            app.save_data()
            app._refresh_all()
        dlg.destroy()
        msg = f"添加完成！\n\n成功添加: {added} 人"
        if skipped:
            msg += f"\n跳过: {skipped} 人"
        if errors:
            msg += "\n\n详细信息：\n" + "\n".join(errors[:10])
        messagebox.showinfo("批量添加结果", msg)

    dlg.buttons(ok_text="确认添加", on_ok=confirm,
                extra=lambda f: FlatButton(f, t, text="全选已匹配", command=select_all,
                                           kind="default", padx=12).pack(side=tk.RIGHT, padx=(0, 8), pady=2, ipady=4))
    dlg.finish()


# ==================================================================== 生僻字条

def _char_bar(dlg, parent, target_entry):
    """在姓名框下方插入生僻字快捷条。"""
    chars = dlg.app.quick_chars
    if not chars:
        return
    bar = tk.Frame(parent, bg=dlg.theme.bg_panel)
    bar.pack(fill=tk.X, pady=(0, 8))
    tk.Label(bar, text="快捷：", bg=dlg.theme.bg_panel, fg=dlg.theme.text_3,
             font=(dlg.theme.font_ui_fallback, dlg.theme.fs_body)).pack(side=tk.LEFT)
    for ch in chars:
        lab = tk.Label(bar, text=ch, bg=dlg.theme.bg_card, fg=dlg.theme.accent,
                       font=(dlg.theme.font_name, dlg.theme.fs_body + 2), padx=5, pady=1,
                       relief=tk.FLAT, highlightthickness=1,
                       highlightbackground=dlg.theme.border, cursor="hand2")
        lab.pack(side=tk.LEFT, padx=1)
        lab.bind("<Button-1>", lambda e, c=ch: _insert_char(target_entry, c))


def _insert_char(entry, char):
    try:
        entry.focus_set()
        pos = entry.index(tk.INSERT)
        current = entry.get()
        entry.delete(0, tk.END)
        entry.insert(0, current[:pos] + char + current[pos:])
        entry.icursor(pos + len(char))
    except Exception:
        pass


# ==================================================================== 保存侧栏修改
# 从家族树 main.py 的 save_modification 平移过来 —— 判定顺序一字未改，
# 只是把「从侧栏取值」这段留在本函数内，主控制器不再背这段业务。

def save_person_modification(app):
    """保存右侧栏的改动（判定顺序与 v1 一致）。"""
    if not app.selected_node:
        messagebox.showinfo("提示", "请先选中人物", parent=app.root)
        return
    old_name = app.selected_node
    s = app.sidebar
    new_name = s.var_name.get().strip()
    if not new_name:
        messagebox.showinfo("提示", "姓名不能为空", parent=app.root)
        return
    if new_name != old_name and new_name in app.people:
        messagebox.showinfo("提示", "%s 已存在" % new_name, parent=app.root)
        return

    old_info = app.people[old_name]
    father, mother = s.var_father.get(), s.var_mother.get()
    spouse_sel = s.var_spouse.get()
    if spouse_sel and spouse_sel not in app.people:
        spouse_sel = ""
    gender = s.var_gender.get()

    def _int(raw):
        try:
            return int(raw) if raw else 0
        except ValueError:
            return 0

    gen = _int(s.var_gen.get())
    rank = _int(s.var_rank.get())
    fief_gen = _int(s.var_fief_gen.get())
    tier = s.var_tier_person.get()
    if tier == "无":
        fief_gen = 0
        s.var_fief_gen.set("")
    state_name = s.var_state_person.get().strip()
    note = s.var_note.get().strip()
    birth, death = s.var_birth.get().strip(), s.var_death.get().strip()
    historical, divine = s.var_hist_person.get(), s.var_divine.get()
    state_group = (state_name + tier) if state_name and tier else ""

    old_gen = old_info.get("generation", 0)
    old_state_name = old_info.get("state_name", "")
    old_state_group = old_info.get("state_group", "")

    # ★ 2026-09-23「封国 ↔ 世系 联动」：世系框（「X世系」虚线框）认的是
    #   `lineage_name`（宗庙世系 = 该国**君主的家族**），不是 `state_name`
    #   （后者是「势力/效忠对象」，拿它分组会把效忠者混进君族框里 —— 使用者
    #   报的「秽貊世系混进非黑齿家的人」就是这个）。但使用者手填的封国要能
    #   立刻出框，所以**填了就同步写世系**。
    #   清空封国**不清**世系（使用者原话：「世系中的谥号是很好的材料」）。
    new_lineage = state_name or old_info.get("lineage_name", "")

    # 代数变化 → 全部子孙整体偏移
    if gen != old_gen and gen > 0 and old_gen > 0:
        delta = gen - old_gen
        for name in model.get_descendants(app.people, old_name):
            app.people[name]["generation"] = app.people[name].get("generation", 1) + delta

    if new_name != old_name:
        old_spouses = list(old_info.get("spouses", []))
        new_spouses = list(old_spouses)
        if spouse_sel:
            if gender == "男":
                if spouse_sel not in new_spouses:
                    new_spouses.append(spouse_sel)
            else:
                new_spouses = [spouse_sel]
        model.rename_person(app.people, old_name, new_name)
        record = {
            "father": father, "mother": mother,
            "color": old_info.get("color", ""), "bg_color": old_info.get("bg_color", ""),
            "note": note, "gender": gender, "generation": gen,
            "historical": historical, "divine": divine,
            "rank": rank, "spouses": new_spouses,
            "birth": birth, "death": death,
            "state_group": state_group, "state_name": state_name,
            "lineage_name": new_lineage,
            "fief_title": tier, "fief_gen": fief_gen,
            "root_sort": old_info.get("root_sort", 0),
        }
        # code 必须跟着走 —— 这是两层之间的锚点，改名不能丢
        for key in ("code", "bio", "associate_of", "associate_type", "associate_rank",
                    "hide_parent_line"):
            if key in old_info:
                record[key] = old_info[key]
        del app.people[old_name]
        app.people[new_name] = record
        for sp in new_spouses:
            if sp in app.people:
                lst = app.people[sp].setdefault("spouses", [])
                if new_name not in lst:
                    lst.append(new_name)
        for sp in old_spouses:
            if sp in app.people:
                lst = app.people[sp].get("spouses", [])
                if old_name in lst:
                    lst[lst.index(old_name)] = new_name
        app.selected_node = new_name
        action = "修改: %s → %s" % (old_name, new_name)
    else:
        rec = app.people[old_name]
        rec.update({"father": father, "mother": mother, "note": note, "gender": gender,
                    "generation": gen, "historical": historical, "divine": divine,
                    "rank": rank, "birth": birth, "death": death,
                    "state_group": state_group, "state_name": state_name,
                    "lineage_name": new_lineage,
                    "fief_title": tier, "fief_gen": fief_gen})
        cur = rec.setdefault("spouses", [])
        if spouse_sel and spouse_sel not in cur:
            cur.append(spouse_sel)
        elif not spouse_sel and gender == "女" and cur:
            cur.clear()
        for sp in cur:
            if sp in app.people:
                lst = app.people[sp].setdefault("spouses", [])
                if old_name not in lst:
                    lst.append(old_name)
        action = "修改: %s" % old_name

    target = app.selected_node
    if old_state_name != state_name or old_state_group != state_group:
        children = model.get_children(app.people, target)
        if children and messagebox.ask_confirm(
                "封国信息变更",
                "%s 的封国信息已变更。\n\n"
                "旧封国: %s   →   新封国: %s\n\n"
                "是否将其所有后裔的封国信息同步更新？"
                % (target, old_state_name or "(无)", state_name or "(无)"),
                ok_text="同步后裔", cancel_text="只改本人", parent=app.root):
            model.cascade_state_change(app.people, target, state_name, state_group)

    app._record(action)
    app.save_data()
    app._refresh_all()
    app.select_person(target)


# ==================================================================== 续谱 / 存档

_PRUNE_LABEL = {"hist": "只收史实", "anon": "史实 + 有爵位",
                "male-son": "再加有男嗣", "none": "全要"}


def _prune_label(p):
    return _PRUNE_LABEL.get(p, p or "（未知）")


# ---- 争霸类型（与 tools/sync_from_mumu.py 同一张号段表，别在两处各写一份）----
def slot_mode(slot):
    try:
        from tools import sync_from_mumu as SM
        return SM.slot_mode(slot)
    except Exception:
        return "未识别模式"


def slot_number(slot):
    try:
        from tools import sync_from_mumu as SM
        return SM.slot_number(slot)
    except Exception:
        return 0


def slot_groups(rows):
    """把 [(slot, desc, enabled, payload)] 按争霸类型分组并排序。

    返回 `[(模式名, [行…]), …]`；模式顺序固定（沙盒全局 → 沙盒局部 →
    家族模式 → 争霸模式 → 未识别），号段表里没有的类型排在最后。
    """
    order = ["沙盒全局", "沙盒局部", "家族模式", "争霸模式", "未识别模式"]
    buckets = {}
    for r in rows:
        buckets.setdefault(slot_mode(r[0]), []).append(r)
    names = [m for m in order if buckets.get(m)]
    names += [m for m in buckets if m not in order]
    return [(m, sorted(buckets[m], key=lambda x: slot_number(x[0]))) for m in names]


def slot_radio_list(parent, theme, var, rows, height=None):
    """按争霸类型分组渲染一组槽（单选）—— **带纵向滚动条**。

    `rows = [(slot, desc, enabled, payload)]`：
      slot    槽名（Save_All_1）
      desc    一行说明（`秦末 · 408 个表文件 · 09-19 13:09`）
      enabled 加密档给 False —— 会置灰不可选
      payload 选中后取值用的东西（一般是槽目录绝对路径）

    返回 `{槽名: payload}`，供调用方把 var.get() 映射回路径。

    ★ 2026-09-21 修「最多可能有 20 个存档，但是没有上下滑动的窗口」：
      原来直接把单选钮 pack 进一个固定高的 Frame，`slot_host` 又开了
      `pack_propagate(False)`，超出的部分被硬裁掉、连滚动条都没有 ——
      第 5 个槽之后就点不到了。现在套一层 Canvas + Scrollbar，
      并且把滚轮事件同时挂在画布、内容框和每个单选钮上（鼠标停在哪个上都能滚）。
    """
    holder = tk.Frame(parent, bg=theme.bg_panel)
    holder.pack(fill=tk.BOTH, expand=True)
    cv = tk.Canvas(holder, bg=theme.bg_panel, highlightthickness=0, bd=0,
                   height=height or 170)
    sb = tk.Scrollbar(holder, orient=tk.VERTICAL, command=cv.yview,
                      bg=theme.border_2, troughcolor=theme.bg_panel,
                      activebackground=theme.accent, highlightthickness=0,
                      bd=0, width=theme.scrollbar_w, relief=tk.FLAT)
    cv.configure(yscrollcommand=sb.set)
    cv.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    sb.pack(side=tk.RIGHT, fill=tk.Y)

    box = tk.Frame(cv, bg=theme.bg_panel)
    win = cv.create_window((0, 0), window=box, anchor="nw")
    box.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
    cv.bind("<Configure>", lambda e: cv.itemconfigure(win, width=e.width))

    def _wheel(e):
        cv.yview_scroll(int(-e.delta / 120) * 2, "units")
        return "break"

    cv.bind("<MouseWheel>", _wheel)
    box.bind("<MouseWheel>", _wheel)

    payloads = {}
    n_any = 0
    for mode, arr in slot_groups(rows):
        tk.Label(box, text="【" + mode + "】", anchor="w", bg=theme.bg_panel,
                 fg=theme.text_3, font=(theme.font_ui_fallback, theme.fs_body_sm, "bold")
                 ).pack(fill=tk.X, pady=(6, 1))
        for slot, desc, enabled, payload in arr:
            txt = f"{slot}    {desc}" if desc else slot
            rb = tk.Radiobutton(box, text=txt, variable=var, value=slot,
                                bg=theme.bg_panel, fg=theme.text if enabled else theme.text_3,
                                selectcolor=theme.bg_input, activebackground=theme.bg_panel,
                                activeforeground=theme.text, bd=0, highlightthickness=0,
                                anchor="w", font=(theme.font_ui_fallback, theme.fs_body_sm))
            if not enabled:
                rb.configure(state="disabled")
            rb.pack(fill=tk.X, padx=(10, 0))
            rb.bind("<MouseWheel>", _wheel)
            payloads[slot] = payload
            n_any += 1
    if not n_any:
        tk.Label(box, text="（一个槽也没有）", anchor="w", bg=theme.bg_panel,
                 fg=theme.text_3, font=(theme.font_ui_fallback, theme.fs_body_sm)
                 ).pack(fill=tk.X, pady=6)
    return payloads


def extend_dialog(app):
    """顶栏「⟲ 续谱」（Ctrl+P）：选实录槽 → 自动定谱牒 → 抽取 → 新建 / 增量续写。

    ★ 2026-09-21 改成**以实录槽为主**（使用者核心诉求）：
      原话「我续谱（抽取存档）后，自动产生或更新相应的存档的谱牒，感觉没达到要求」。
      旧流程要先选好谱牒、还得已经绑对槽，续谱才知道往哪写；现在反过来 ——
      选哪个槽，就按槽里的剧本推出谱牒名（`剧本名·争霸类型`），
      不存在自动新建、存在就增量续写。《上古时代》《文王治岐》是保护档，自动跳过。

    仍然分两步（**先演习、再写回**）：第一次续谱要把没有编号的老记录一条条
    认到新抽的人物上（姓名 + 性别 + 生年 + 父名，唯一才连）。这一步万一认错，
    手写的小传就挂到别人身上了 —— 所以演习必须先跑、报告要能逐条看，
    确认了再动文件。
    """
    slot0 = app.extend_slot()

    dlg = ThemedDialog(app, "⟲ 续谱 · 从存档续写家谱", width=820, height=780)
    th = dlg.theme
    text_label(dlg.body, th,
               "选一个实录槽，自动推出该剧本对应的谱牒：没有就新建，有就增量续写。"
               "新人补进来；旧人只更新实证字段（生年 / 卒年），"
               "你手写的小传、注释、配色、祖序、封国爵位一律不动；"
               "谱内独有的人也不会被删。",
               size=dlg.fs_small(), fg=th.text_2, justify=tk.LEFT,
               wraplength=770).pack(anchor="w", pady=(0, 8))

    # ---- 只读上下文 ----
    info = tk.Frame(dlg.body, bg=th.bg_card, highlightthickness=1,
                    highlightbackground=th.border)
    info.pack(fill=tk.X, pady=(0, 8))
    for label, value, col in (("当前谱牒", app.current_save or "（无）", th.edit_2),
                              ("默认槽", os.path.basename(slot0) if slot0 else "（没配上）",
                               th.accent)):
        r = tk.Frame(info, bg=th.bg_card)
        r.pack(fill=tk.X, padx=12, pady=(7, 0))
        tk.Label(r, text=label, bg=th.bg_card, fg=th.text_3, width=8, anchor="e",
                 font=(th.font_ui_fallback, dlg.fs_small())).pack(side=tk.LEFT)
        tk.Label(r, text=value, bg=th.bg_card, fg=col, anchor="w",
                 font=(th.font_ui_fallback, dlg.fs_small(), "bold")).pack(
                     side=tk.LEFT, padx=(8, 0))
    tk.Frame(info, bg=th.bg_card, height=7).pack()

    # ---- 从模拟器拉档（并进原「同步」按钮；只保留续谱一个动作）----
    tk.Label(dlg.body, text="从模拟器拉取最新存档", anchor="w", bg=th.bg_panel,
             fg=th.text, font=(th.font_ui_fallback, th.fs_body, "bold")
             ).pack(fill=tk.X, pady=(2, 2))
    var_slot = tk.StringVar()
    # ★ 2026-09-21：不再 pack_propagate(False) + 固定高 —— 那样会把里面那个
    #   带滚动条的 Canvas 一起压扁、滚动条被裁掉（使用者原话「没有上下滑动的窗口」）。
    #   现在高度由 `slot_radio_list` 里 Canvas 的 height=170 决定，滚动条在它右侧。
    slot_host = tk.Frame(dlg.body, bg=th.bg_panel)
    slot_host.pack(fill=tk.X)
    note = tk.Label(dlg.body, text="", anchor="w", bg=th.bg_panel, fg=th.text_3,
                    font=(th.font_ui_fallback, dlg.fs_small()))
    note.pack(fill=tk.X, pady=(2, 6))

    # ---- 目标谱牒（★ 2026-09-21 使用者核心诉求的落地点）----
    # 原话：「我续谱（抽取存档）后，自动产生或更新相应的存档的谱牒，
    #         感觉没有达到我的要求」。
    # 现在改成**以实录槽为主**：选哪个槽 → 读出剧本 → 目标谱牒名 = 剧本名·争霸类型
    # （《秦末起义·沙盒全局》）→ 不存在就自动新建、存在就增量续写。
    # 《上古时代》《文王治岐》打了「保护档」，自动流程遇到同一个剧本就跳过。
    tgt = tk.Frame(dlg.body, bg=th.bg_panel)
    tgt.pack(fill=tk.X, pady=(2, 0))
    tk.Label(tgt, text="目标谱牒", bg=th.bg_panel, fg=th.text_2, width=8, anchor="e",
             font=(th.font_ui_fallback, th.fs_body)).pack(side=tk.LEFT)
    tgt_lbl = tk.Label(tgt, text="", bg=th.bg_panel, anchor="w",
                       font=(th.font_ui_fallback, th.fs_body, "bold"))
    tgt_lbl.pack(side=tk.LEFT, padx=(10, 0))

    opt = tk.Frame(dlg.body, bg=th.bg_panel)
    opt.pack(fill=tk.X, pady=(2, 6))
    var_manual = tk.BooleanVar(value=False)
    var_mname = tk.StringVar()
    var_new = tk.BooleanVar(value=False)
    # ★ 2026-09-24 使用者报「让游戏自动跑了一会，续不上存档了」：脚本的人
    #   数比闸门（新抽 / 谱牒 > 2 倍）在 GUI 里**无路可走** —— 只回一句
    #   「请在命令行加 --force」。这里给一个勾选，勾了就把 --force 透传下去。
    var_force = tk.BooleanVar(value=False)
    names_now = storage.list_saves()
    var_mname.set(app.current_save or (names_now[0] if names_now else ""))
    # ★ 2026-09-22 使用者：「允许我修改目标谱牒的名字，不用默认的名字抽取族谱」。
    #   原来是 `readonly=True` 的下拉框，只能从**已有**谱牒里挑一个 ——
    #   想给新抽的谱牒起个自己的名字根本没入口。现在改成**可编辑**：
    #   既能从下拉里选已有的，也能直接打一个新名字（不存在就新建这部谱牒）。
    cmb = combo_box(opt, th, values=names_now, textvariable=var_mname, width=26,
                    readonly=False)
    cmb_hint = tk.Label(opt, text="可直接输入新名字", bg=th.bg_panel, fg=th.text_3,
                        font=(th.font_ui_fallback, dlg.fs_small()))
    tip(cmb_hint, "输入的名字不能含 \\ / : * ? \" < > |（会自动换成 _）。\n"
                  "名字不存在 → 新建这部谱牒；已存在 → 增量续写它。")
    cb_manual = tk.Checkbutton(opt, text="手动指定目标谱牒", variable=var_manual,
                               bg=th.bg_panel, fg=th.text_2, selectcolor=th.bg_input,
                               activebackground=th.bg_panel, activeforeground=th.text,
                               bd=0, highlightthickness=0,
                               font=(th.font_ui_fallback, dlg.fs_small()))
    cb_manual.pack(side=tk.LEFT)
    cb_new = tk.Checkbutton(opt, text="另存为新谱牒", variable=var_new,
                            bg=th.bg_panel, fg=th.text_2, selectcolor=th.bg_input,
                            activebackground=th.bg_panel, activeforeground=th.text,
                            bd=0, highlightthickness=0,
                            font=(th.font_ui_fallback, dlg.fs_small()))
    tip(cb_manual, "默认自动：按所选实录槽推出剧本名，谱牒名 = 剧本名·争霸类型。\n"
                   "勾上则按右边输入框里的名字来 —— 可以选已有的谱牒，\n"
                   "也可以直接打一个新名字（不存在就新建这部谱牒）。")
    tip(tgt_lbl, "自动推导规则：读槽里的剧本开局年 → 谱牒名 =「剧本名·争霸类型」。\n"
                 "例：Save_All_1（秦末起义·沙盒全局）→ 谱牒《秦末起义·沙盒全局》。\n"
                 "想换个名字：勾「手动指定目标谱牒」后在输入框里改。")

    plan_state = {"plan": {}, "pending_pull": False, "auto_name": "",
                  "manual_name": "", "was_manual": False, "set_mname_guard": False}
    # 按钮与运行态先占位 —— `refresh_target` 会在按钮画出来之前就被调到，
    # 那时 btn_dry[0] 还是 None，跳过即可（按钮画完 `extra` 里再补上）。
    btn_dry = [None]
    btn_apply = [None]
    state = {"dry_ok": False, "busy": False}

    def cur_slot_path():
        """当前选中槽的**本机目录**（空串 = 这个槽还没拉到本机）。

        ★ payload 由 `main.emulator_slot_rows` 给，必须是路径不是槽名 ——
          曾经错传槽名，于是这里永远拿到 `"Save_All_4001"` 这种相对名，
          `plan_extend_target` 读不出剧本 → 目标谱牒显示「认不出」→
          「先演习 / 备份并写回」两个按钮全灰（使用者报的就是这个）。
        """
        pay = getattr(app, "_extend_payloads", None) or {}
        return pay.get(var_slot.get(), "") or ""

    def _sync_cmb():
        if var_manual.get():
            cmb.pack(side=tk.LEFT, padx=(8, 0))
            cmb_hint.pack(side=tk.LEFT, padx=(6, 0))
            # 每敲一个字都会走到这里（`var_mname` 挂了 trace），
            # 所以只在候选名单**真变了**时才重设，免得输入时下拉被反复重置。
            vals = storage.list_saves()
            if list(cmb.cget("values")) != vals:
                cmb.configure(values=vals)
        else:
            cmb.pack_forget()
            cmb_hint.pack_forget()

    def _set_mname(name):
        """改写「手动指定」输入框的内容。

        ★ 它自己会触发 `var_mname` 的 trace（＝再进一次 `refresh_target`），
          所以先立个闸门把那次重入挡掉，免得来回递归。
        """
        plan_state["set_mname_guard"] = True
        try:
            var_mname.set(name)
        finally:
            plan_state["set_mname_guard"] = False

    def refresh_target(*_):
        """按当前选的槽重算目标谱牒，并把结论写在这一行上。

        ★ 2026-09-22 起多了「改名字」这一层：勾选框一开一关时，在
          「默认名」与「你起的名字」之间切换输入框内容（见下面那段）。
        """
        if plan_state.get("set_mname_guard"):
            return

        # ---- 手动指定的开关动作：勾上填默认名 / 取消记下你改的名字 ----
        manual_on = bool(var_manual.get())
        if manual_on != plan_state["was_manual"]:
            plan_state["was_manual"] = manual_on
            if manual_on:
                # 刚勾上 —— 把按剧本推出来的默认名先填进去，你在这个基础上改就行
                seed = (plan_state["manual_name"] or plan_state["auto_name"]
                        or var_mname.get().strip())
                if seed:
                    _set_mname(seed)
            else:
                # 刚取消 —— 记住你起的名字（下次勾上还能接着改），输入框回到默认名
                typed = var_mname.get().strip()
                if typed:
                    plan_state["manual_name"] = typed
                if plan_state["auto_name"]:
                    _set_mname(plan_state["auto_name"])

        manual = var_mname.get().strip() if manual_on else ""
        if manual:
            # 边打边记 —— 取消勾选时就知道你起的名字是什么，下次勾上还能接着改
            plan_state["manual_name"] = manual
        if manual_on and not manual:
            # 勾了手动指定却是空名字 —— 不能悄悄退回自动名（那等于没勾）
            plan_state["plan"] = {}
            plan_state["pending_pull"] = False
            tgt_lbl.configure(text="勾了「手动指定」，但名字是空的 —— 请输入一个谱牒名，"
                                   "或从右边的下拉里选一部已有的。", fg=th.warn)
            cb_new.pack_forget()
            if btn_dry[0] is not None:
                btn_dry[0].set_enabled(False)
            if btn_apply[0] is not None:
                btn_apply[0].set_enabled(False)
            _sync_cmb()
            return

        sp = cur_slot_path()
        if not sp and not manual:
            # 本机还没这个槽的缓存 —— 剧本文件在模拟器里，得先拉档才知道是哪一盘。
            # 这时**不能**把按钮灰掉：点「先演习」就会先拉档、再按剧本自动定目标
            # （`run_extend(auto=True)`）。
            plan_state["plan"] = {}
            plan_state["pending_pull"] = bool(var_slot.get())
            plan_state["auto_name"] = ""   # 槽还没拉下来，默认名未知，别拿上一个槽的
            tgt_lbl.configure(
                text=("这个槽还没拉到本机 —— 点「① 先演习」会先拉档，再按剧本自动定谱牒。"
                      if var_slot.get() else "先在上面选一个实录槽。"),
                fg=th.text_3)
            cb_new.pack_forget()
            if btn_dry[0] is not None:
                btn_dry[0].set_enabled(bool(var_slot.get()))
            if btn_apply[0] is not None:
                btn_apply[0].set_enabled(False)
            _sync_cmb()
            return
        plan_state["pending_pull"] = False
        plan = app.plan_extend_target(sp, manual)
        if not manual:
            # 记下「按剧本推出来的默认名」—— 勾「手动指定」时拿它当起改点
            plan_state["auto_name"] = plan.get("name") or ""
        # 冲突：同名谱牒已经绑在别的槽上 —— 勾「另存为新谱牒」就换个不重名的
        if plan["action"] == "conflict":
            alt = app.free_book_name(plan["name"])
            cb_new.configure(text=f"另存为新谱牒《{alt}》")
            cb_new.pack(side=tk.LEFT, padx=(10, 0))
            if var_new.get():
                plan = app.plan_extend_target(sp, alt)
        else:
            var_new.set(False)
            cb_new.pack_forget()
        plan_state["plan"] = plan
        act = plan["action"]
        col = {"new": th.accent, "extend": th.edit_2, "skip": th.warn,
               "conflict": th.warn, "none": th.text_3}.get(act, th.text_2)
        tgt_lbl.configure(text=plan["note"] or "——", fg=col)
        ok = act in ("new", "extend")
        # ★ 2026-09-22 修（B 批第 3 条）：「先演习」**不该跟着目标谱牒一起灰**。
        #   原来是 `ok` 才点亮 —— 于是「命中保护档」（skip）时两个按钮全灰，
        #   使用者连「先拉档看一眼」都做不到，也就没法靠拉档把剧本认对。
        #   演习是**只读**的（不写 family.json），所以单独放开：
        #     · 命中保护档（skip）→ 允许演习：先拉档、出报告，
        #       看完再决定是去取消保护，还是改「手动指定」换一部谱牒。
        #     · 目标未定（none）但**已经选了槽** → 也允许演习
        #       （拉档之后剧本可能就定得出来了）。
        #   「写回」仍然只在 new/extend 时放开（见 do_dry 里的二次闸门）。
        dry_ok = ok or act == "skip" or (act == "none" and bool(var_slot.get()))
        if btn_dry[0] is not None:
            btn_dry[0].set_enabled(dry_ok)
        # ★ 2026-09-29 使用者：「到底什么情况下不让我备份写回？查找逻辑，
        #   **只把标记保护的存档保护好就行了，我要写就写，不要给我不能点**」。
        #   原来这里**只禁不启** —— `if ... and not ok: set_enabled(False)`，
        #   而唯一的"启用"在 `do_dry` 末尾且要求 `act_now in ("new","extend")`
        #   ⇒ 计划动作是 conflict / none 时，按钮**永远点不动**（哪怕手动指定了
        #   新名字、演习也通过了）。
        #   现在：**只有保护档（skip）禁用**；conflict / none 一概放行 ——
        #   点了会走 `do_apply` 的确认框与二次闸门，不会静默覆盖任何东西。
        if btn_apply[0] is not None:
            btn_apply[0].set_enabled(act != "skip")
        _sync_cmb()

    cb_manual.configure(command=refresh_target)
    cb_new.configure(command=refresh_target)
    var_manual.trace_add("write", lambda *_: refresh_target())
    var_mname.trace_add("write", lambda *_: refresh_target())

    # ---- 抽取口径（★ 2026-09-21 使用者定稿：不再给选项，就这一条）----
    # 原话：「抽取口径应该是史实和选定的非史实角色的所有后裔，其他选项没必要」
    #      「后裔纯父系，不含女儿支」
    # 所以四档单选（只收史实 / 史实+有爵位 / 再加有男嗣 / 全要）整排删掉，
    # 改成一行只读说明；`prune` 固定传 "hist"（= 只收史实），
    # 点名的非史实人物由 `--watch` 连同其**纯父系后裔**一起收，
    # 并且不参与剪枝（见 `import_from_game.build` 第 1b / 4c 步）。
    prune_fixed = "hist"
    rule = tk.Frame(dlg.body, bg=th.bg_panel)
    rule.pack(fill=tk.X, pady=(0, 6))
    tk.Label(rule, text="抽取口径", bg=th.bg_panel, fg=th.text_2, width=8, anchor="e",
             font=(th.font_ui_fallback, th.fs_body)).pack(side=tk.LEFT)
    tk.Label(rule, text="史实人物 ＋ 续谱名单点名的非史实人物",
             bg=th.bg_panel, fg=th.accent, anchor="w",
             font=(th.font_ui_fallback, th.fs_body)).pack(side=tk.LEFT, padx=(10, 0))
    # 「（连同其纯父系后裔）」是解释说明 → 挪到悬停（使用者 2026-09-21 要求）
    tip(rule, "非史实人物默认一个都不收；只有你在人物页点「加入族谱」\n"
              "点名的那几位，会连同他们的纯父系后裔一起抽进谱（不含女儿支）。")

    # ---- 续谱名单（= 关注世系，选择入口在人物页/表格页）----
    var_watch = tk.StringVar()
    r = tk.Frame(dlg.body, bg=th.bg_panel)
    r.pack(fill=tk.X, pady=(0, 6))
    tk.Label(r, text="续谱名单", bg=th.bg_panel, fg=th.text_2, width=8, anchor="e",
             font=(th.font_ui_fallback, th.fs_body)).pack(side=tk.LEFT)
    watch_lbl = tk.Label(r, text="", bg=th.bg_panel, fg=th.accent, anchor="w",
                         font=(th.font_ui_fallback, th.fs_body))
    watch_lbl.pack(side=tk.LEFT, padx=(10, 0))

    def refresh_watch():
        codes = app.followed_codes()
        # 括号里的解释挪到悬停（使用者 2026-09-21 要求），正文只留「N 人」
        watch_lbl.configure(text=f"{len(codes)} 人")

    tip(watch_lbl, "在人物页点「加入族谱」增删。\n"
                   "非史实人物默认一个都不收；点名的那几位会连同他们的\n"
                   "纯父系后裔一起抽进谱（不含女儿支）。")

    refresh_watch()

    # ---- 进度条（★ 使用者原话：「点了续谱按钮后有明显卡顿，此时应该有进度条」）----
    # 续谱要拉档（adb，几秒~几十秒）+ 跑子进程读四表（0.6s/槽 那种整档解析），
    # 全过程以前只有 log 区在滚 —— 点下去像卡死。现在 5 步走到哪一步都看得见。
    prog_lbl = tk.Label(dlg.body, text="", anchor="w", bg=th.bg_panel, fg=th.text_3,
                        font=(th.font_ui_fallback, dlg.fs_small()))
    prog_lbl.pack(fill=tk.X, pady=(4, 1))
    prog = ttk.Progressbar(dlg.body, mode="determinate", maximum=5, length=760)
    prog.pack(fill=tk.X)

    log = tk.Text(dlg.body, height=8, bg=th.bg_input, fg=th.text,
                  insertbackground=th.text, relief=tk.FLAT, wrap="word",
                  font=(th.font_ui_fallback, th.fs_body_sm))
    log.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

    def write(s):
        log.insert(tk.END, str(s).rstrip() + "\n")
        log.see(tk.END)
        log.update_idletasks()

    def progress(n, text):
        prog["value"] = n
        prog_lbl.configure(text=f"（{n}/5）{text}")
        dlg.update_idletasks()

    def build_slot_list():
        for w in slot_host.winfo_children():
            w.destroy()
        var_slot.set("")
        # ★ 把 `write` 传下去：`emulator_slot_rows` 会在**阻塞连 adb 之前**
        #   先喊一句「连接模拟器（要 root，约几秒）...」，配合 update_idletasks
        #   就看得见进度，不至于像卡死。
        rows, err = app.emulator_slot_rows(log=write)
        if err:
            write(err)
            note.configure(text="拉档不可用 —— 会用本机已有的存档继续续谱。", fg=th.text_3)
            app._extend_payloads = {}
            refresh_target()
            return
        payloads = slot_radio_list(slot_host, th, var_slot, rows)
        app._extend_payloads = payloads
        # 默认选当前来源槽
        cur = os.path.basename(slot0) if slot0 else ""
        for slot, desc, enabled, _p in rows:
            if slot == cur and enabled:
                var_slot.set(slot)
                break
        else:
            for slot, desc, enabled, _p in rows:
                if enabled:
                    var_slot.set(slot)
                    break
        enc = [s for s, _d, e, _p in rows if not e]
        # 括号里的解释挪到悬停（使用者 2026-09-21 要求），正文只留计数
        note.configure(
            text=(f"发现 {len(rows)} 个槽；加密的 {len(enc)} 个已置灰"
                  if enc else f"发现 {len(rows)} 个槽。"), fg=th.text_3)
        if enc:
            tip(note, "置灰的是游戏「云端下载」的加密档，解析不了。\n"
                      "在游戏里【载入】它、过一个回合，游戏会把明文写回一个新槽，\n"
                      "那时就能选了。")
        refresh_target()

    def _adopt_pulled():
        """演习/写回都拉过档了 —— 按**本机现在这一份**重算目标谱牒并刷新显示。

        ★ 2026-09-22 修（使用者：「脚本从模拟器拉取存档的时候，经常把剧本读成别的剧本」）：
          原来只在「本机原本没有这个槽」时才刷新（判据是 payload 变没变）。
          可本机**有旧缓存**时 payload 早就是那个路径了、压根不会变，
          于是刷新被跳过 —— 「目标谱牒」一直显示按旧缓存算出来的名字。
          现在无条件重算：`run_extend` 那边也已经改成「拉了档就按新档重推目标」，
          两边结论一致（写回用的是 `_extend_last`，不会拿旧结论去写）。
        """
        slot = var_slot.get()
        if not slot:
            return
        sp = app.local_slot_dir(slot)
        if sp:
            pay = dict(getattr(app, "_extend_payloads", None) or {})
            pay[slot] = sp
            app._extend_payloads = pay
        refresh_target()

    def do_dry():
        if state["busy"]:
            return
        plan = plan_state["plan"] or {}
        auto = bool(plan_state.get("pending_pull"))
        manual = var_mname.get().strip() if var_manual.get() else ""
        if not auto and plan.get("action") not in ("new", "extend"):
            messagebox.showinfo("续谱", plan.get("note") or "这部谱牒不能自动续谱。")
            return
        log.delete("1.0", tk.END)
        prog["value"] = 0
        write("$ 演习 —— 只出报告，一个字节都不写")
        if auto:
            write("$ 目标谱牒：这个槽还没拉到本机，先拉档、再按槽里的剧本自动定")
        else:
            write(f"$ 目标谱牒：《{plan['name']}》"
                  + ("（新建）" if plan["action"] == "new" else "（续写）"))
            write("$ （拉档后若本机原来那份是别的剧本，会按新档重新认定目标）")
        state["busy"] = True
        kw = dict(prune=prune_fixed, pull_slot=var_slot.get(), log=write,
                  target="" if auto else plan["name"],
                  create=False if auto else (plan["action"] == "new"),
                  manual=manual, slot_path=cur_slot_path(), auto=auto,
                  progress=progress)
        try:
            ok, out = app.run_extend(apply=False, force=var_force.get(), **kw)
            # ★ 2026-09-24 使用者报「点了强行继续，② 备份并写回还是灰的」：
            #   原来被闸门拦下后只是**把勾选框打上**，还要求他再点一次
            #   「① 先演习」才会亮「②」—— 他就卡在这一步（截图：勾已打上、
            #   ② 仍灰、日志停在「演习失败」）。
            #   现在拦下就**自动按「强行继续」重跑一次演习**（不再重复拉档，
            #   目标沿用上一趟定下的），报告照样出来，核对无误直接写回。
            if not ok and "人数比闸门" in (out or "") and not var_force.get():
                var_force.set(True)
                write("\n$ 已被人数比闸门拦下 —— 自动按「强行继续」重跑一次演习"
                      "（不重复拉档）...")
                last = getattr(app, "_extend_last", None) or {}
                ok, out = app.run_extend(
                    apply=False, prune=prune_fixed, log=write,
                    target=last.get("target") or plan.get("name", ""),
                    create=bool(last.get("create")),
                    slot_path=cur_slot_path(), progress=progress, force=True)
        finally:
            state["busy"] = False
        state["dry_ok"] = bool(ok)
        _adopt_pulled()
        # ★ 2026-09-22 修（B 批第 3 条）：写回还要再过一道闸门 —— 看**当前计划**是什么动作。
        #   命中保护档（skip）时允许跑演习（只读，拿报告用），但**绝不能**因此
        #   把「写回」放开 —— 那会覆盖使用者手写的保护档。
        # ★ 2026-09-29 放宽（同 `refresh_target` 的注释）：**只挡保护档**。
        #   演习通过后，只要目标不是保护档就点亮「② 备份并写回」；
        #   真写之前还有 `do_apply` 的确认框 + `state["dry_ok"]` 二次闸门。
        act_now = (plan_state.get("plan") or {}).get("action")
        if btn_apply[0] is not None:
            btn_apply[0].set_enabled(bool(ok) and act_now != "skip")
        write("\n演习通过。核对上面的数字无误，再点「② 备份并写回」。" if ok
              else "\n演习失败，未动任何文件。")
        prog_lbl.configure(text="演习结束。" if ok else "演习失败。")

    def do_apply():
        if state["busy"]:
            return
        if not state["dry_ok"]:
            messagebox.showinfo("续谱", "请先点「① 先演习」，看过报告再写回。")
            return
        # 目标以**演习时实际定下**的那份为准（`run_extend` 记的 `_extend_last`）；
        # 演习后 `_adopt_pulled()` 也会把 plan 刷新成真实结果，两者一致。
        last = getattr(app, "_extend_last", None) or {}
        plan = plan_state["plan"] or {}
        target = last.get("target") or plan.get("name")
        create = bool(last.get("create")) if last else (plan.get("action") == "new")
        if not target:
            messagebox.showinfo("续谱", "还没定下目标谱牒 —— 请重新点一次「① 先演习」。")
            return
        verb = "新建" if create else "续写"
        if not messagebox.ask_confirm(
                "续谱",
                f"{verb}谱牒档《{target}》？\n\n"
                + ("这是新谱牒，会整档抽一遍。\n" if create
                   else "会先自动备份一份 family.json。\n")
                + "写完后按 Ctrl+Z 可一步撤销。", ok_text=verb):
            return
        write(f"\n$ 写回 —— {'整档新建' if create else '先备份，再合并'}")
        state["busy"] = True
        try:
            ok, out = app.run_extend(apply=True, prune=prune_fixed,
                                     target=target, create=create,
                                     slot_path=cur_slot_path(),
                                     log=write, progress=progress,
                                     force=var_force.get())
        finally:
            state["busy"] = False
        if ok:
            refresh_watch()
            _adopt_pulled()
            refresh_target()
            messagebox.showinfo("续谱完成",
                                f"《{app.current_save}》已{verb}。\n"
                                "顶栏人数已刷新，Ctrl+Z 可一步撤销。")
        else:
            messagebox.showerror("续谱失败", (out or "未知错误")[-1200:])
            prog_lbl.configure(text="写回失败，未动任何文件。")

    def extra(footer):
        FlatButton(footer, th, text="重扫模拟器", command=build_slot_list,
                   kind="default", padx=12).pack(side=tk.LEFT, pady=2, ipady=4)
        cb_force = tk.Checkbutton(footer, text="强行继续", variable=var_force,
                                  bg=th.bg_panel, fg=th.text_2,
                                  selectcolor=th.bg_input,
                                  activebackground=th.bg_panel,
                                  activeforeground=th.text, bd=0,
                                  highlightthickness=0,
                                  font=(th.font_ui_fallback, dlg.fs_small()))
        cb_force.pack(side=tk.LEFT, padx=(10, 0))
        tip(cb_force, "脚本的人数比保险：新抽人数与谱牒相差 2 倍以上时会拦下，\n"
                      "防「抽取口径不一致」灌进几千个路人。\n"
                      "但世界正常长大（游戏跑了一阵、子孙繁衍）也会触发它 ——\n"
                      "核对演习报告无误后勾上这里，演习与写回都按强行继续走。")
        b = FlatButton(footer, th, text="② 备份并写回", command=do_apply,
                       kind="edit", padx=16)
        b.pack(side=tk.LEFT, padx=(8, 0), pady=2, ipady=4)
        b.set_enabled(False)
        btn_apply[0] = b

    btn_dry[0] = dlg.buttons(ok_text="① 先演习", on_ok=do_dry,
                             cancel_text="关闭", extra=extra)
    # ★ 扫槽要连 adb（几秒起），**不能**在窗口画出来之前同步做 ——
    #   那样对话框会先白着/冻住几秒，正是使用者说的「点了续谱按钮后有明显卡顿」。
    #   先让窗口画出来（refresh_target 用的是上一次的槽表，没有就显示「认不出」），
    #   再用 after 把扫槽甩到事件循环里，期间「扫描模拟器上的存档槽 ...」看得见。
    app._extend_payloads = {}
    refresh_target()
    prog_lbl.configure(text="准备中：正在扫描模拟器上的存档槽 ...")

    def _scan_later():
        try:
            if not dlg.winfo_exists():
                return
        except tk.TclError:
            return
        build_slot_list()
        prog_lbl.configure(text="")

    dlg.after(60, _scan_later)
    dlg.finish()


def archive_dialog(app):
    """顶栏「存档」：一个对话框管两层 —— 上半选谱牒档（目的），下半选实录槽（来源）。

    为什么合成一个：甲方原话「谱牒是目的，实录是来源」，本来就是一件事的
    两头；两份各自独立的菜单纯属啰嗦（原来顶栏两个下拉并排占位）。
    """
    dlg = ThemedDialog(app, "存档 · 谱牒与实录", width=760, height=720)
    th = dlg.theme
    text_label(dlg.body, th,
               "谱牒（橙金）是你要修的那部谱，落盘在 saves/<谱名>/；"
               "实录（青绿）是抽人物用的游戏存档，只读。切谱牒会自动带上它"
               "绑定的实录槽；关掉「自动跟随」就能临时翻别的档而不动谱牒。",
               size=dlg.fs_small(), fg=th.text_2, justify=tk.LEFT,
               wraplength=710).pack(anchor="w", pady=(0, 8))

    # ---- 上：谱牒档（与「存档管理」共用同一块，免得两处各写一份增删改查）----
    # 括号里的角色说明挪到悬停（使用者 2026-09-21 要求）
    _bk = tk.Label(dlg.body, text="谱牒档", anchor="w", bg=th.bg_panel,
                   fg=th.edit_2, font=(th.font_ui_fallback, th.fs_body, "bold"))
    _bk.pack(fill=tk.X)
    tip(_bk, "谱牒＝目的（橙金 · 可编辑）。\n你要修的那部谱，落盘在 saves/<谱名>/。")
    lb, reload_books, selected_book = _book_manager_body(app, dlg, height=110)

    # ---- 下：实录槽 ----
    head = tk.Frame(dlg.body, bg=th.bg_panel)
    head.pack(fill=tk.X, pady=(6, 0))
    _rc = tk.Label(head, text="实录槽", anchor="w", bg=th.bg_panel,
                   fg=th.accent, font=(th.font_ui_fallback, th.fs_body, "bold"))
    _rc.pack(side=tk.LEFT)
    tip(_rc, "实录＝来源（青绿 · 只读）。\n抽人物用的游戏存档，本软件不会改动它。")
    var_follow = tk.BooleanVar(value=True)
    tk.Checkbutton(head, text="自动跟随谱牒", variable=var_follow,
                   bg=th.bg_panel, fg=th.text_2, selectcolor=th.bg_input,
                   activebackground=th.bg_panel, activeforeground=th.text,
                   bd=0, highlightthickness=0,
                   font=(th.font_ui_fallback, dlg.fs_small())).pack(side=tk.LEFT, padx=(12, 0))

    var_slot = tk.StringVar()
    # 槽列表的容器高度由 slot_radio_list 里的 Canvas 给（它自带滚动条）。
    # 这里不再 pack_propagate(False) —— 那会把 Canvas 压成固定高、滚动条也算不进去。
    slot_host = tk.Frame(dlg.body, bg=th.bg_panel)
    slot_host.pack(fill=tk.BOTH, expand=True, pady=(2, 4))

    # ★ 2026-09-21 使用者：「移除选中槽这个 bar 的位置是不是太靠右了」。
    #   原来它挂在标题行上 `side=RIGHT`，被推到对话框最右角，和「实录槽」标题
    #   隔着半个窗口，根本看不出它管的是下面那份列表。
    #   现在放到**列表正下方、左对齐**，紧挨着列表，语义一眼可见。
    slotbar = tk.Frame(dlg.body, bg=th.bg_panel)
    slotbar.pack(fill=tk.X, pady=(0, 2))

    btn_remove = FlatButton(slotbar, th, text="移除选中槽", kind="default", padx=10,
                            command=lambda: do_remove(), size=dlg.fs_small())
    btn_remove.pack(side=tk.LEFT)
    tip(btn_remove, "把选中的实录槽从列表里移除。\n"
                    "只删脚本的记录（config.json 的 hidden_slots），\n"
                    "磁盘上的存档文件一个字节都不动。\n"
                    "想恢复：把槽名从 config.json 的 hidden_slots 里去掉。")

    btn_delete = FlatButton(slotbar, th, text="彻底删除选中槽", kind="danger", padx=10,
                            command=lambda: do_delete(), size=dlg.fs_small())
    btn_delete.pack(side=tk.LEFT, padx=(6, 0))
    tip(btn_delete, "把选中的实录槽的**本机缓存**彻底删掉\n"
                    "（D:\\DevCache\\dzlgz\\Save_All_N 整目录），\n"
                    "并同时从「移除」名单里去掉。\n"
                    "模拟器里的游戏存档不受影响（要删请进游戏删）。\n"
                    "删除不可恢复，请想清楚再点。")

    btn_bind = FlatButton(slotbar, th, text="绑定到选中槽", kind="default", padx=10,
                          command=lambda: do_bind(), size=dlg.fs_small())
    btn_bind.pack(side=tk.LEFT, padx=(6, 0))
    tip(btn_bind, "把当前谱牒的来源改绑到这个实录槽。\n"
                  "只写谱牒的 source（槽名 + 路径），不重新抽取、不合并、\n"
                  "不动任何人物数据 —— 比「备份并写回」轻得多。\n"
                  "用途：槽被删掉又重拉、或游戏写到别的槽号时，手动对一次。")

    btn_unhide = FlatButton(slotbar, th, text="恢复被移除的槽", kind="default", padx=10,
                            command=lambda: do_unhide(), size=dlg.fs_small())
    btn_unhide.pack(side=tk.LEFT, padx=(6, 0))
    tip(btn_unhide, "把之前「移除选中槽」移除掉的槽全部放回列表。\n"
                    "移除只是记了个名单（config.json 的 hidden_slots），\n"
                    "磁盘上的存档一直都在 —— 这个按钮就是把名单清空。")

    status = tk.Label(slotbar, text="", anchor="w", bg=th.bg_panel, fg=th.text_3,
                      font=(th.font_ui_fallback, dlg.fs_small()))
    status.pack(side=tk.LEFT, padx=(10, 0))

    def local_rows():
        """本机缓存里的槽 —— 要读哪个。"""
        rows = []
        for p in app.record_slots:
            slot = os.path.basename(p)
            desc, ok = app.local_slot_desc(p)
            rows.append((slot, desc, ok, p))
        return rows

    def rebuild_slots(*_a):
        for w in slot_host.winfo_children():
            w.destroy()
        rows = local_rows()
        app._archive_payloads = slot_radio_list(slot_host, th, var_slot, rows, height=180)
        cur = app.record_slot.root if app.record_slot is not None else ""
        for slot, _d, ok, p in rows:
            if p and cur and os.path.normcase(p) == os.path.normcase(cur):
                var_slot.set(slot)
                break
        if var_follow.get():
            follow = app._slot_for_save(app.current_save) if app.current_save else ""
            for slot, _d, ok, p in rows:
                if follow and os.path.normcase(p) == os.path.normcase(follow):
                    var_slot.set(slot)
                    break
        # 槽一个都没有时，移除按钮也就没意义了
        btn_remove.set_enabled(bool(rows))
        btn_bind.set_enabled(bool(rows))
        btn_delete.set_enabled(bool(rows))
        # 「恢复」只在真有名被移除时才可用
        n_hidden = len(app.cfg.get("hidden_slots") or [])
        btn_unhide.set_enabled(bool(n_hidden))
        btn_unhide.set_text(f"恢复被移除的槽（{n_hidden}）" if n_hidden
                            else "恢复被移除的槽")

    def do_unhide():
        """把 hidden_slots 清空 —— 之前「移除」掉的槽全部放回列表。"""
        n = len(app.cfg.get("hidden_slots") or [])
        if not n:
            status.configure(text="没有被移除的槽")
            return
        app.cfg = update_config(hidden_slots=[])
        app.scan_record_slots()
        status.configure(text=f"已放回 {n} 个槽")
        rebuild_slots()

    def do_bind():
        """把当前谱牒绑到选中的实录槽（★ 2026-09-21 使用者问的「一一对应」）。

        只写 `source.slot_path / slot`，不重新抽取、不合并 —— 这是「对上一次」，
        不是「续一次谱」。
        """
        slot = var_slot.get()
        path = (getattr(app, "_archive_payloads", {}) or {}).get(slot, "")
        if not slot or not path:
            messagebox.showinfo("存档", "先在上面选一个实录槽。")
            return
        if not app.current_save:
            messagebox.showinfo("存档", "还没有谱牒档，先建一个。")
            return
        if app.bind_save_slot(path):
            status.configure(text=f"已把《{app.current_save}》绑到 {slot}")
            rebuild_slots()
            app._refresh_all()
        else:
            status.configure(text=f"绑定 {slot} 失败")

    def do_remove():
        """把选中的实录槽从列表里移除（★ 2026-09-21 使用者要求）。

        只删**脚本的记录**（写进 config.json 的 hidden_slots），
        磁盘上的槽目录一个字节都不动 —— 使用者自己说的「虽然可能删除不了实际游戏存档，
        但让我删除脚本的记录也可以」。
        """
        slot = var_slot.get()
        path = (getattr(app, "_archive_payloads", {}) or {}).get(slot, "")
        if not slot or not path:
            messagebox.showinfo("存档", "先在上面选一个实录槽。")
            return
        if not messagebox.ask_confirm(
                "移除实录槽",
                f"把 {slot} 从列表里移除？\n\n"
                "只是不再列出来（记进 config.json 的 hidden_slots），\n"
                "磁盘上的存档文件一个字节都不会动。\n\n"
                "想彻底删掉文件的话，请自己去文件夹里删：\n"
                f"{os.path.dirname(path)}", ok_text="移除"):
            return
        if app.hide_record_slot(path):
            status.configure(text=f"已移除 {slot}（磁盘文件未动）")
            rebuild_slots()

    def do_delete():
        """**彻底删除**选中的实录槽：删本机缓存目录 + 从 hidden_slots 移除。

        「移除」只是隐藏名单，磁盘文件还在；这个按钮是真正删掉本机缓存
        （D:\\DevCache\\dzlgz\\Save_All_N 整目录），不可恢复。
        模拟器里的游戏存档不动 —— 要删得进游戏里删。
        """
        slot = var_slot.get()
        path = (getattr(app, "_archive_payloads", {}) or {}).get(slot, "")
        if not slot or not path:
            messagebox.showinfo("存档", "先在上面选一个实录槽。")
            return
        if not messagebox.ask_danger(
                "彻底删除实录槽",
                f"确定要彻底删除 {slot} 的本机缓存吗？\n\n"
                "· 会删除 D:\\DevCache\\dzlgz\\ 下的整个槽目录\n"
                "· 同时把它从「移除」名单里去掉\n"
                "· 删除不可恢复\n\n"
                "模拟器里的游戏存档不受影响（要删请进游戏删）。",
                ok_text="彻底删除"):
            return
        ok, msg = app.delete_record_slot(path)
        if ok:
            status.configure(text=msg)
        else:
            messagebox.showwarning("彻底删除", msg)
        rebuild_slots()

    var_follow.trace_add("write", rebuild_slots)
    rebuild_slots()

    def do_switch():
        book = selected_book()
        if not book:
            messagebox.showinfo("存档", "先在上面选一部谱牒。")
            return
        # 先切谱牒（会按 source 自动带上它自己的实录槽），
        # 关掉「自动跟随」时再把用户手选的槽盖上去。
        if book != app.current_save:
            app.switch_save(book)
        if not var_follow.get():
            path = app._archive_payloads.get(var_slot.get(), "")
            if path and (app.record_slot is None
                         or os.path.normcase(path) != os.path.normcase(app.record_slot.root)):
                app.open_record(path)
        status.configure(text=f"当前：谱牒《{app.current_save}》 · 实录 "
                              f"{app.record_slot.name if app.record_slot else '（无）'}")
        app._refresh_all()

    dlg.buttons(ok_text="切换", on_ok=do_switch, cancel_text="关闭")
    dlg.finish()
