# -*- coding: utf-8 -*-
"""把谱牒导出成**单文件 HTML**（零外部依赖，手机浏览器直接打开）。

为什么做这个
------------
「安卓化」研究（见 `项目日志.md` 第十节）的结论是：
- 数据层 100% 与 Tkinter 解耦，可整包搬到安卓；
- UI 层 11000 行必须重写。

本导出器是这条路的**第一步**，而且不是弯路：
  · 它把「树形布局 → 坐标」这条链路完整跑通一遍，证明数据层够用；
  · 产物本身就是移动端 UI 的骨架 —— 将来塞进 WebView（Chaquopy）
    或改写成 Flet 组件，版式与交互都照这份走；
  · 它立刻有用：手机 / 微信打开就能看家谱，**不需要 root、不需要打包**。

坐标从哪来
----------
不重算。直接调 `app.layout.compute_layout()` —— 与桌面端「家谱」页**同一套布局算法**，
所以手机上看到的世系结构与 PC 上完全一致（含世系框、夫妻/朋友符号）。
主题色同样取自 `app.theme`，直译成 CSS 变量。

用法
----
    python tools/export_html.py 满天星斗·沙盒全局
    python tools/export_html.py 文王治岐 --theme ink --out _stats/export/wenwang.html
"""
import argparse
import json
import os
import re
import sys
import time
from html import escape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import layout as LAY      # noqa: E402
from app import theme as TH        # noqa: E402
from app import labels as LB       # noqa: E402
from app import model as MD        # noqa: E402

# 节点行高与字号（与桌面端口径一致：15px 基准 × scale）
BASE_FONT = 15


def load_book(name_or_path):
    """载入谱牒 family.json。返回 (谱牒名, people, source)。"""
    p = name_or_path
    if not os.path.isfile(p):
        cand = os.path.join(ROOT, "saves", name_or_path, "family.json")
        if os.path.isfile(cand):
            p = cand
        else:
            raise SystemExit("找不到谱牒：%s" % name_or_path)
    d = json.load(open(p, encoding="utf-8"))
    people = d.get("people") or {}
    if not people:
        raise SystemExit("谱牒里没有人：%s" % p)
    title = os.path.basename(os.path.dirname(p))
    return title, people, (d.get("source") or {})


def _txt(v):
    return escape(str(v)) if v not in (None, "") else ""


_PLAIN_YEAR = re.compile(r"^-?\d+$")
_TRIPLE = re.compile(r"^-?\d+,\d+,\d+$")


def _norm_time(v):
    """谱牒里时间存的是**裸字符串**（`'-2448'` / `'-2448,3,12'`），
    而 `labels._time_parts` 只认「整数」或「y,m,d 三元组」——
    纯年份字符串它会判为不合格式返回 None。这里先归一化再交出去。"""
    if isinstance(v, str):
        s = v.strip()
        if _PLAIN_YEAR.match(s):
            return int(s)
        if _TRIPLE.match(s):
            return tuple(int(x) for x in s.split(","))
    return v


def human_time(v):
    """时间字段 → 紧凑中文（借 labels 的口径，失败就原样）。节点第二行用。"""
    if v in (None, "", 0):
        return ""
    v = _norm_time(v)
    try:
        return LB.humanize_time(v) or str(v)
    except Exception:
        return str(v)


def human_time_long(v):
    """时间字段 → 长文本（「公元前 2448 年 3 月」）。详情卡用，手机上更好读。"""
    if v in (None, "", 0):
        return ""
    v = _norm_time(v)
    try:
        return LB.humanize_time_long(v) or human_time(v)
    except Exception:
        return human_time(v)


def node_sub(info):
    """节点第二行：生卒 / 世代。"""
    born = human_time(info.get("birth"))
    died = human_time(info.get("death"))
    gen = info.get("generation") or ""
    span = born
    if born and died:
        span = "%s—%s" % (born, died)
    elif died:
        span = "卒 " + died
    parts = [p for p in (span, ("第%s代" % gen) if gen else "") if p]
    return " · ".join(parts)


def accent_of(theme, info):
    """节点描边色：神祖 / 女性 / 史实 / 普通。"""
    if info.get("divine"):
        return theme.divine
    if str(info.get("gender") or "").strip() in ("女", "女性", "female"):
        return theme.female
    if info.get("historical") is False:
        return theme.text_3
    return theme.accent


def build_svg(people, lay, theme, scale=1.0):
    """产出一段自包含 SVG（世系框 → 连线 → 节点）。"""
    pos = lay.positions
    nh = lay.node_h or 34 * scale
    nw = lay.name_width or 84 * scale
    fs_name = BASE_FONT * scale
    fs_sub = BASE_FONT * scale * 0.72

    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    pad = 60
    x0, x1 = min(xs) - nw / 2 - pad, max(xs) + nw / 2 + pad
    y0, y1 = min(ys) - nh - pad, max(ys) + nh + pad

    out = []
    out.append('<svg id="tree" xmlns="http://www.w3.org/2000/svg" viewBox="%.0f %.0f %.0f %.0f" '
               'width="%.0f" height="%.0f" font-family="inherit">'
               % (x0, y0, x1 - x0, y1 - y0, x1 - x0, y1 - y0))

    # ---- 1) 世系框（虚线）----
    try:
        sboxes, qboxes = LAY.state_group_boxes(people, lay, {})
    except Exception as e:      # 参数不匹配就让这一步优雅降级
        print("  (世系框跳过：%s)" % e)
        sboxes, qboxes = [], []
    for boxes, dash in ((sboxes, "7 5"), (qboxes, "3 4")):
        for (bx0, by0, bx1, by1, color, label) in boxes:
            out.append('<rect x="%.0f" y="%.0f" width="%.0f" height="%.0f" fill="none" '
                       'stroke="%s" stroke-dasharray="%s" stroke-width="1.2" rx="8" opacity="0.55"/>'
                       % (bx0, by0, max(bx1 - bx0, 1), max(by1 - by0, 1), color or "#b9a", dash))
            if label:
                out.append('<text x="%.0f" y="%.0f" font-size="%.1f" fill="%s" opacity="0.9">%s</text>'
                           % (bx0 + 8, by0 + fs_sub + 4, fs_sub, color or "#b9a",
                              escape(str(label))))

    # ---- 2) 父子 / 母子连线 ----
    for name, info in people.items():
        if name not in pos:
            continue
        cx, cy = pos[name]
        for key, color, dash in (("father", theme.tree_line, ""),
                                 ("mother", theme.spouse, ' stroke-dasharray="5 3"')):
            par = info.get(key) or ""
            if par in pos:
                px, py = pos[par]
                out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" '
                           'stroke-width="1.6"%s/>' % (px, py + nh / 2, cx, cy - nh / 2, color, dash))

    # ---- 3) 同代符号（♥ / 友）----
    for name, info in people.items():
        ref = info.get("associate_of") or ""
        atype = info.get("associate_type") or "clan"
        if atype == "clan" or not ref or ref == name:
            continue
        if ref not in pos or name not in pos:
            continue
        (ax, ay), (bx, by) = pos[ref], pos[name]
        out.append('<text x="%.1f" y="%.1f" font-size="%.1f" text-anchor="middle" fill="%s">%s</text>'
                   % ((ax + bx) / 2, max(ay, by) + nh / 2 + fs_sub, fs_sub * 0.95,
                      theme.spouse if atype == "spouse" else theme.accent,
                      "♥" if atype == "spouse" else "友"))

    # ---- 4) 节点 ----
    out.append('<g id="nodes">')
    for name, info in people.items():
        if name not in pos:
            continue
        cx, cy = pos[name]
        stroke = accent_of(theme, info)
        sub = node_sub(info)
        died = bool(info.get("death"))
        fill = theme.bg_card if not died else theme.bg_canvas
        out.append('<g class="node" data-name="%s" transform="translate(%.1f %.1f)">'
                   % (escape(name), cx, cy))
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="6" fill="%s" '
                   'stroke="%s" stroke-width="1.6"/>'
                   % (-nw / 2, -nh / 2, nw, nh, fill, stroke))
        out.append('<text class="nm" text-anchor="middle" y="%.1f" font-size="%.1f" fill="%s">%s</text>'
                   % (2 if not sub else -1, fs_name, theme.text, escape(name)))
        if sub:
            out.append('<text class="sb" text-anchor="middle" y="%.1f" font-size="%.1f" fill="%s">%s</text>'
                       % (fs_sub + 3, fs_sub, theme.text_3, escape(sub)))
        out.append('</g>')
    out.append('</g></svg>')
    return "\n".join(out), (x1 - x0, y1 - y0)


def css_vars(theme):
    m = {
        "--bg-app": theme.bg_app, "--bg-bar": theme.bg_bar, "--bg-panel": theme.bg_panel,
        "--bg-card": theme.bg_card, "--bg-input": theme.bg_input, "--bg-canvas": theme.bg_canvas,
        "--bg-sel": theme.bg_sel, "--border": theme.border, "--border2": theme.border_2,
        "--grid": theme.grid, "--text": theme.text, "--text2": theme.text_2,
        "--text3": theme.text_3, "--accent": theme.accent, "--danger": theme.danger,
        "--spouse": theme.spouse, "--divine": theme.divine, "--female": theme.female,
    }
    return "\n".join("  %s:%s;" % kv for kv in m.items())


PAGE = """<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=5">
<title>%(title)s · 史馆</title>
<style>
:root{
%(vars)s
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;height:100%%;background:var(--bg-app);color:var(--text);
  font-family:"PingFang SC","Microsoft YaHei","Noto Sans CJK SC",system-ui,sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--bg-bar);border-bottom:1px solid var(--border);
  padding:10px 14px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
h1{font-size:15px;font-weight:500;margin:0}
.meta{font-size:12px;color:var(--text3)}
input[type=search]{flex:1;min-width:120px;padding:7px 10px;font-size:14px;border:1px solid var(--border2);
  border-radius:8px;background:var(--bg-input);color:var(--text)}
button{padding:7px 11px;font-size:13px;border:1px solid var(--border2);border-radius:8px;
  background:var(--bg-panel);color:var(--text)}
#stage{position:relative;overflow:auto;height:calc(100%% - 54px);padding:8px;
  background:var(--bg-canvas);background-image:
    linear-gradient(var(--grid) 1px,transparent 1px),
    linear-gradient(90deg,var(--grid) 1px,transparent 1px);background-size:28px 28px}
#tree{display:block;touch-action:pan-x pan-y}
.node{cursor:pointer}
.node rect{transition:stroke-width .12s}
.node.on rect{stroke-width:3}
.node.dim{opacity:.18}
#sheet{position:fixed;left:0;right:0;bottom:0;max-height:62%%;overflow:auto;
  background:var(--bg-panel);border-top:1px solid var(--border2);border-radius:14px 14px 0 0;
  padding:14px 16px 22px;transform:translateY(105%%);transition:transform .18s ease-out;
  box-shadow:0 -6px 24px rgba(0,0,0,.10)}
#sheet.up{transform:translateY(0)}
#sheet h2{margin:0 0 2px;font-size:17px;font-weight:500}
#sheet .tag{display:inline-block;font-size:11px;padding:2px 7px;border-radius:99px;margin-right:6px;
  border:1px solid var(--border2);color:var(--text2)}
#sheet dl{margin:10px 0 0;display:grid;grid-template-columns:76px 1fr;gap:6px 10px;font-size:13px}
#sheet dt{color:var(--text3)}
#sheet dd{margin:0;line-height:1.55;word-break:break-word}
#close{position:absolute;right:10px;top:10px}
footer{font-size:11px;color:var(--text3);padding:6px 14px 12px}
</style></head><body>
<header>
  <h1>%(title)s</h1>
  <span class="meta">%(npeople)s 人 · %(ngen)s 代 · 史实 %(nhist)s</span>
  <input id="q" type="search" placeholder="搜名字…">
  <button id="zin">放大</button><button id="zout">缩小</button>
</header>
<div id="stage">%(svg)s</div>
<div id="sheet"><button id="close">关闭</button><div id="body"></div></div>
<footer>由「大周列国志 · 史馆」导出 · 单文件离线可看 · %(stamp)s</footer>
<script>
var DATA = %(data)s;
var stage = document.getElementById('stage'), sheet = document.getElementById('sheet');
var body = document.getElementById('body'), zoom = 1, sel = null;
function fit(){ var t = document.getElementById('tree');
  t.style.width = (t.viewBox.baseVal.width * zoom) + 'px';
  t.style.height = (t.viewBox.baseVal.height * zoom) + 'px'; }
function pick(name){
  var d = DATA[name]; if(!d) return;
  document.querySelectorAll('.node').forEach(function(g){
    g.classList.toggle('on', g.dataset.name === name); });
  var h = '<h2>' + name + '</h2>';
  (d.tags||[]).forEach(function(t){ h += '<span class="tag">' + t + '</span>'; });
  h += '<dl>';
  (d.rows||[]).forEach(function(r){ h += '<dt>' + r[0] + '</dt><dd>' + (r[1]||'—') + '</dd>'; });
  h += '</dl>';
  body.innerHTML = h; sheet.classList.add('up'); sel = name;
}
document.querySelectorAll('.node').forEach(function(g){
  g.addEventListener('click', function(){ pick(g.dataset.name); }); });
document.getElementById('close').addEventListener('click', function(){
  sheet.classList.remove('up'); sel = null;
  document.querySelectorAll('.node').forEach(function(g){ g.classList.remove('on'); }); });
document.getElementById('zin').addEventListener('click', function(){ zoom = Math.min(zoom*1.25, 4); fit(); });
document.getElementById('zout').addEventListener('click', function(){ zoom = Math.max(zoom/1.25, .3); fit(); });
document.getElementById('q').addEventListener('input', function(e){
  var v = e.target.value.trim();
  document.querySelectorAll('.node').forEach(function(g){
    g.classList.toggle('dim', !!v && g.dataset.name.indexOf(v) < 0); }); });
fit();
</script></body></html>
"""


def build_data(people):
    """每人的详情卡数据（谱牒字段 → 中文标签）。"""
    data = {}
    for name, info in people.items():
        rows = []
        for key in ("gender", "birth", "death", "generation", "rank", "fief_title",
                    "state_name", "state_group", "fief_gen", "root_sort",
                    "father", "mother", "bio", "note"):
            v = info.get(key)
            if v in (None, "", 0, []):
                continue
            label = LB.field_label(key) if hasattr(LB, "field_label") else key
            if key in ("birth", "death"):
                v = human_time_long(v) or v
            rows.append([label, str(v)])
        sp = info.get("spouses") or []
        if sp:
            rows.append(["配偶", "、".join(str(x) for x in sp)])
        tags = []
        if info.get("divine"):
            tags.append("神祖")
        if str(info.get("gender") or "").strip() in ("女", "女性", "female"):
            tags.append("女")
        if info.get("historical") is False:
            tags.append("推断")
        elif info.get("historical"):
            tags.append("史实")
        data[name] = {"rows": rows, "tags": tags}
    return data


def main():
    ap = argparse.ArgumentParser(description="把谱牒导出成单文件 HTML")
    ap.add_argument("book", help="谱牒名（saves/ 下的目录名）或 family.json 路径")
    ap.add_argument("--out", default="", help="输出 HTML 路径，默认 _stats/export/<名>.html")
    ap.add_argument("--theme", default=TH.DEFAULT_THEME, choices=sorted(TH.THEMES),
                    help="配色：paper / ink / tencent")
    ap.add_argument("--scale", type=float, default=1.0, help="布局缩放（1.0 = 桌面端等比）")
    args = ap.parse_args()

    t0 = time.time()
    title, people, source = load_book(args.book)
    theme = TH.get_theme(args.theme)

    lay = LAY.compute_layout(people, scale=args.scale)
    n_vis = len(lay.positions)
    svg, (vw, vh) = build_svg(people, lay, theme, scale=args.scale)

    depths = [v for v in (lay.depth or {}).values() if isinstance(v, int)]
    ngen = (max(depths) - min(depths) + 1) if depths else 0
    nhist = sum(1 for p in people.values() if p.get("historical"))

    html = PAGE % {
        "title": escape(title), "vars": css_vars(theme), "svg": svg,
        "npeople": len(people), "ngen": ngen or "?", "nhist": nhist,
        "data": json.dumps(build_data(people), ensure_ascii=False, separators=(",", ":")),
        "stamp": time.strftime("%Y-%m-%d %H:%M") + (("  ·  实录 " + str(source.get("slot")))
                                                   if source.get("slot") else ""),
    }

    out = args.out or os.path.join(ROOT, "_stats", "export", "%s.html" % title)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w", encoding="utf-8", newline="\n").write(html)

    kb = os.path.getsize(out) / 1024.0
    print("HTML_OK %s" % out)
    print("  谱牒 %s：%d 人（画布内 %d）· %s 代 · 史实 %d · 画布 %.0f×%.0f"
          % (title, len(people), n_vis, ngen or "?", nhist, vw, vh))
    print("  单文件 %.0f KB，无外部依赖，耗时 %.2fs" % (kb, time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
