# -*- coding: utf-8 -*-
"""人物小传浮卡 —— 主树与时间轴共用。

原来这段只长在 `tree_view` 里，时间轴视图点卡片什么都不显示，和效果图对不上。
抽出来的东西有四样：

  · `wrap_cjk` / `wrap_runs` —— 中文避头尾的手工折行（Tk 的 Text 不管这套规则）
  · `_rule` / `_sect` —— 效果图 `.popcard` 的虚线分隔条与「身份 / 在世 / 关系」分节
  · `build_popcard` —— 按主题令牌拼一张小传卡（标题 + 楷体富文本 + 分节键值行），
    返回 Frame 与宽度，**放在哪由调用方决定**（两个视图的锚点不一样）

版式对齐效果图第 ④ 节 `.popcard`：标题行（名字 + 爵位 chip）→ 小传正文 →
虚线 → `身份` / `在世` / `关系` 三节，「键右对齐 44px + 值左对齐」。
"""
import tkinter as tk
import tkinter.font as tkfont

from .. import bio as bio_mod
from .. import dpi as _dpi
from .. import labels as L
from .. import model as model_mod
from ..labels import plain_name

# 中文避头尾标点（Tk 的 Text 完全不管这套规则，句号会跑到下一行开头）
#   收尾类：不能出现在行首
#   开始类：不能出现在行尾
NO_LINE_START = set("。，、；：？！）〕】》」』〉·…—～%,.;:?!)]}>”’")
NO_LINE_END = set("（〔【《「『〈([{<“‘")

POP_W = _dpi.px(256)         # 卡片目标宽度（像素）—— 2026-09-23 加宽，配合右下角固定
POP_W2 = _dpi.px(320)        # UI 改进 C14：长小传自动升档的宽度
POP_TALL = _dpi.px(360)      # 224 档卡片高度超过这个值（≈9 行正文）就升 300 档
POP_PAD = _dpi.px(9)
POP_TEXT_SIZE = 13  # 2026-09-23 12→13：右下角固定后字大一点更好读
KEY_W = _dpi.px(48)          # 「键」列宽（2026-09-23 44→48）


def wrap_cjk(items, cols):
    """按列宽折行，并遵守中文避头尾。items = [(字, 标签), …]，返回 [[(字, 标签), …], …]。

    做法是「追入」而不是挤压 —— Tk 没办法把全角标点压成半角，所以只能把上一行末尾的字
    下移到下一行，让标点不至于孤零零落在行首。代价是上一行少一个字，好处是每行都不会
    超过列宽（浮卡按行数定高，超宽就没有软换行的余地了）。
    """
    lines, cur, pending = [], [], []
    for ch, tag in items:
        if ch == "\n":
            lines.append(cur + pending)
            cur, pending = [], []
            continue
        cur.append((ch, tag))
        if len(cur) >= cols:
            while cur and cur[-1][0] in NO_LINE_END:     # 行尾不能是开引号
                pending.insert(0, cur.pop())
            lines.append(cur)
            cur, pending = pending, []
    if cur:
        lines.append(cur)

    i = 1
    while i < len(lines):                                # 行首不能是收尾标点
        prev, line = lines[i - 1], lines[i]
        while line and line[0][0] in NO_LINE_START and prev:
            line.insert(0, prev.pop())
        while prev and prev[-1][0] in NO_LINE_END and line:
            line.insert(0, prev.pop())
        if not prev:
            lines.pop(i - 1)
            i = max(1, i - 1)
            continue
        i += 1
    return [ln for ln in lines if ln]


def wrap_runs(lines):
    """把折好的行转成「同标签连续段」插入序列，减少 Text 的 insert 次数。"""
    runs = []
    for i, line in enumerate(lines):
        if i:
            runs.append(("\n", ""))
        j = 0
        while j < len(line):
            tag = line[j][1]
            k = j
            while k < len(line) and line[k][1] == tag:
                k += 1
            runs.append(("".join(c for c, _ in line[j:k]), tag or ""))
            j = k
    return runs


def _rule(parent, theme, width, pady):
    """虚线分隔条（效果图 `.sect` 的 `border-top: 1px dashed`）。"""
    cv = tk.Canvas(parent, height=1, width=width, bg=theme.bg_card,
                   highlightthickness=0, bd=0)
    cv.create_line(0, 0, width, 0, fill=theme.border, dash=(2, 2))
    cv.pack(fill=tk.X, padx=POP_PAD, pady=pady)
    return cv


def _rich_value(parent, theme, runs, body_px, val_font):
    """「值」列的多色渲染：一段文字里每个人名各自上色（女性标红）。

    `runs = [(字, 标签), …]`，标签空串 = 默认色、`"f"` = 女性色。
    Tk 的 Label 只能整条一个颜色，所以这里退回 Text —— 与正文小传同一套路：
    列数按字宽自己算、折行用 `wrap_cjk`，行数就是控件高度（不靠 count(displaylines)，
    那个在控件没布局完时不准）。
    """
    probe = tkfont.Font(family=val_font[0], size=val_font[1])
    char_w = max(1.0, probe.measure("中"))
    room = max(body_px - KEY_W - 10, 40)
    cols = max(4, int(room / char_w))
    lines = wrap_cjk(runs, cols)
    t = tk.Text(parent, wrap="none", bd=0, highlightthickness=0,
                bg=theme.bg_card, fg=theme.text, font=val_font,
                width=cols, height=max(1, len(lines)), cursor="arrow",
                spacing1=1, spacing3=1, takefocus=0)
    t.tag_configure("f", foreground=theme.spouse,
                    font=(val_font[0], val_font[1], "bold"))
    for seg, tag in wrap_runs(lines):
        t.insert("end", seg, tag)
    t.configure(state="disabled")
    t.grid(row=0, column=1, sticky="w", padx=(6, 0))
    return t


def _sect(parent, theme, title, rows, body_px, val_font):
    """一节 = 标题（主色小色块 + 主色字）+ 若干「键 值」行。

    键列固定 44px 右对齐、值列左对齐并按剩余宽度折行 —— 与效果图 `.li` 一致。
    值可以是**字符串**（整条同色）或 **runs 列表**（逐人名上色，见 `_rich_value`）。
    """
    wrap = tk.Frame(parent, bg=theme.bg_card)
    wrap.pack(fill=tk.X, padx=POP_PAD, pady=(7, 0))

    head = tk.Frame(wrap, bg=theme.bg_card)
    head.pack(fill=tk.X)
    tk.Frame(head, bg=theme.accent, width=3, height=12).pack(side=tk.LEFT, pady=1)
    tk.Label(head, text=title, bg=theme.bg_card, fg=theme.accent,
             font=(theme.font_ui_fallback, 10, "bold")).pack(side=tk.LEFT, padx=(5, 0))

    for key, val in rows:
        line = tk.Frame(wrap, bg=theme.bg_card)
        line.pack(fill=tk.X, pady=(2, 0))
        # 键列用 grid 的 minsize 钉宽度（用 Frame+pack_propagate 试过：帧高度会塌成 1px，
        # 字被裁成一条细线）。第 0 列固定 44px 右对齐、第 1 列吃掉余宽。
        line.columnconfigure(0, minsize=KEY_W)
        line.columnconfigure(1, weight=1)
        tk.Label(line, text=key, bg=theme.bg_card, fg=theme.text_3, anchor="e",
                 font=(theme.font_ui_fallback, 10)).grid(row=0, column=0, sticky="e")
        if isinstance(val, list):
            _rich_value(line, theme, val, body_px, val_font)
        else:
            tk.Label(line, text=val or "—", bg=theme.bg_card, fg=theme.text, anchor="w",
                     justify=tk.LEFT, wraplength=max(body_px - KEY_W - 10, 40),
                     font=val_font).grid(row=0, column=1, sticky="w", padx=(6, 0))


def build_popcard(canvas, theme, people, name, width=POP_W):
    """拼一张小传卡，返回 (Frame, 宽, 高)。

    要点：
      1. 用 Canvas 内嵌 Frame + Text 做富文本 —— Text 原生支持按段着色，
         比逐字在画布上摆位置可靠得多；配色沿用 v1 介绍栏原版
         （人物名 #8B0000 / 封国 #2E7D32 / 尊号 #CC0000，楷体加粗）
      2. 尺寸自己算 —— Text 的 width/height 单位是「字符数」而不是像素，
         中文一个字远宽于一个字符。正文全是全角字、等宽，所以按字宽换算列数、
         折行位置自己算，行数就是控件高度。
         （别指望 count(displaylines)：控件还没完成布局时它不生效，会退化成字符数，
         height 被写成几十行，卡片就变成竖长条。）

    UI 改进 C14：默认 224px；正文折出来超过 POP_TALL 像素高（长小传折成
    细长条）时，自动升 300px 档重拼一次。调用方只消费返回的宽高，零改动。
    """
    built = _build(canvas, theme, people, name, width)
    if built is None:
        return None
    if width == POP_W and built[2] > POP_TALL:
        return _build(canvas, theme, people, name, POP_W2)
    return built


def _build(canvas, theme, people, name, width):
    """按给定宽度拼卡（build_popcard 的实体，供双档宽度复用）。"""
    info = people.get(name)
    if not info:
        return None
    pad = POP_PAD
    body_px = width - 2 * pad - 2

    card = tk.Frame(canvas, bg=theme.bg_card, bd=0,
                    highlightthickness=1, highlightbackground=theme.border_2)
    # 卡片宽度基准：正文按「每行 N 个全角字」估算行数，卡片就必须有确定宽度，
    # 否则宽度被标题行决定，正文每行塞不下预估字数、换行全乱。放一条与底色同色的
    # 1px 撑条把宽度钉死，视觉上看不见。
    tk.Frame(card, bg=theme.bg_card, width=body_px, height=1).pack(fill=tk.X, padx=pad)

    head = tk.Frame(card, bg=theme.bg_card)
    head.pack(fill=tk.X, padx=pad, pady=(7, 0))
    # 名字按性别上色：女性用 spouse 色（使用者要求「女性角色名字在任何地方都标红」）
    # 重名序数归一成数字（老档的「王贲①」→「王贲1」）—— 浮卡是纯文本 Label，
    # 做不了右上角灰角标（那一套只在主树/时间轴的画布上），至少数字要一致
    title_fg = theme.spouse if info.get("gender", "") == "女" else theme.text
    tk.Label(head, text=plain_name(name), bg=theme.bg_card, fg=title_fg,
             font=(theme.font_name, 16, "bold")).pack(side=tk.LEFT)
    tier = info.get("fief_title", "")
    if tier and tier != "无":
        tk.Label(head, text=tier, bg=theme.tier.get(tier, theme.text_2),
                 fg=theme.accent_on, font=(theme.font_ui_fallback, 10, "bold"),
                 padx=5).pack(side=tk.RIGHT)
    # ★ 2026-09-23 标题下一道主题色细线，把「标题 → 正文」分成两块（原只有虚线分隔）
    tk.Frame(card, bg=theme.accent, height=2).pack(fill=tk.X, padx=pad, pady=(4, 0))

    probe = tkfont.Font(family=theme.font_name, size=POP_TEXT_SIZE)
    char_w = max(1.0, probe.measure("中"))
    cols = max(6, int(body_px / char_w))
    segments = bio_mod.bio_segments_for(people, name)
    lines = wrap_cjk([(ch, tag) for seg, tag in segments for ch in seg], cols)
    rows = max(1, len(lines))

    txt = tk.Text(card, wrap="none", bd=0, highlightthickness=0,
                  bg=theme.bg_card, fg=theme.text_2,
                  font=(theme.font_name, POP_TEXT_SIZE), width=cols, height=rows,
                  cursor="arrow", spacing1=1, spacing3=1, takefocus=0)
    txt.tag_configure("tag_person", foreground=theme.bio_person,
                      font=(theme.font_name, POP_TEXT_SIZE, "bold"))
    txt.tag_configure("tag_state", foreground=theme.bio_state,
                      font=(theme.font_name, POP_TEXT_SIZE, "bold"))
    txt.tag_configure("tag_note", foreground=theme.bio_note,
                      font=(theme.font_name, POP_TEXT_SIZE, "bold"))
    for t_name, t_color in theme.tier.items():
        txt.tag_configure(f"tag_{t_name}", foreground=t_color,
                          font=(theme.font_name, POP_TEXT_SIZE, "bold"))
    for seg, tag in wrap_runs(lines):
        txt.insert("end", seg, tag)
    txt.configure(state="disabled")
    txt.pack(fill=tk.X, padx=pad, pady=(3, 0))

    # ---- 身份 / 在世 / 关系（效果图第 ④ 节的三节）----
    ident = [("代数", str(info.get("generation") or ""))]
    if info.get("rank"):
        ident.append(("排行", str(info["rank"])))
    state = info.get("state_name") or ""
    if state:
        if info.get("fief_gen"):
            state = f"{state} · 第{info['fief_gen']}代"
        ident.append(("封国", state))
    ident.append(("爵位", info.get("fief_title") or "—"))
    if info.get("note"):
        ident.append(("尊号", info["note"]))
    ident.append(("史实", "是" if info.get("historical") == "是" else "否"))

    life = []
    if info.get("birth"):
        # 谱牒 birth 是完整年月日串（如 `-1380,6,10`），浮卡显示长格式；
        # 格式非法时原样显示（humanize_time_long 返回 None）
        life.append(("生于", L.humanize_time_long(info["birth"]) or info["birth"]))
    # ★ 2026-09-26：真实卒年缺失时用「生年 + 享年」推定（与表格页 / Profile 同一口径）。
    #   ⚠️ 不加「（推定）」括注 —— 九十三批续十二裁定「括注一律不要」，
    #   依据由「天寿」属性承载（`Profile.tianshou`）。
    _death = str(info.get("death") or "")
    if not _death.strip():
        _eo = (info.get("extra") or {}).get("Ren_End_Old")
        if _eo not in (None, "", 0):
            try:
                from .. import profiles as _PF
                _d, _why = _PF.calc_death(str(info.get("birth") or ""), _eo)
                if _d:
                    _death = _d
            except Exception:
                _death = ""
    if _death.strip():
        life.append(("卒于", L.humanize_time_long(_death) or _death))

    rel = []
    # ★ 2026-09-21 使用者要求「女性角色名字在任何地方都标红」——
    #   亲属行的人名要**逐个**上色，所以这里给的是 runs 而不是拼接好的字符串。
    def name_runs(names):
        items = []
        for i, nm in enumerate(names):
            if not nm:
                continue
            if items:
                items += [(" · ", "")]
            female = (people.get(nm) or {}).get("gender", "") == "女"
            items += [(ch, "f" if female else "") for ch in plain_name(nm)]
        return items

    if info.get("father"):
        rel.append(("父", name_runs([info["father"]])))
    if info.get("mother"):
        rel.append(("母", name_runs([info["mother"]])))
    spouses = [s for s in (info.get("spouses") or []) if s]
    if spouses:
        rel.append(("配偶", name_runs(spouses)))
    kids = model_mod.get_children(people, name)
    if kids:
        rel.append(("子女", name_runs(kids)))

    val_ui = (theme.font_ui_fallback, 10)
    val_kai = (theme.font_name, 11)
    _rule(card, theme, body_px, (8, 0))
    _sect(card, theme, "身份", ident, body_px, val_ui)
    if life:
        _sect(card, theme, "在世", life, body_px, val_ui)
    if rel:
        _sect(card, theme, "关系", rel, body_px, val_kai)
    tk.Frame(card, bg=theme.bg_card, height=7).pack(fill=tk.X)

    card.update_idletasks()
    return card, width, max(card.winfo_reqheight(), 40)
