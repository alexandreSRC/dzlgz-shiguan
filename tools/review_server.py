# -*- coding: utf-8 -*-
"""虚接复核页 —— 使用者像做题一样逐条选择「保持 / 断开 / 查史料」。

用法：
    python tools/review_server.py            # 默认 8802 端口
    python tools/review_server.py 8899       # 指定端口

打开：http://127.0.0.1:8802/   （平板：http://<本机 IP>:8802/）

提交后写到 `_scratch/review_result.json`，AI 照单执行：
    {"保持": [...], "断开": [...], "查史料": [...], "meta": {...}}

★ 只读 family.json，绝不写谱牒 —— 复核结果单独落盘，由人确认后再动手。
"""
import argparse
import io
import json
import os
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from tools.shi_origin import origin_of        # noqa: E402

BOOK = "全史存档"
RESULT = os.path.join(ROOT, "_scratch", "review_result.json")

_XING_SHI = re.compile(r"([\u4e00-\u9fff])姓([\u4e00-\u9fff]{1,2})氏")
_XING_ONLY = re.compile(r"([\u4e00-\u9fff])姓")
_SHI_ONLY = re.compile(r"^[^，]{1,14}，([\u4e00-\u9fff]{1,2})氏")


def clan(bio):
    bio = str(bio or "")
    out = set()
    m = _XING_SHI.search(bio)
    if m:
        out |= {m.group(1), m.group(2)}
    else:
        m = _XING_ONLY.search(bio)
        if m:
            out.add(m.group(1))
        m = _SHI_ONLY.match(bio)
        if m:
            out.add(m.group(1))
    return {t for t in out if t}


def yr(rec):
    try:
        return int(str(rec.get("birth") or "").split(",")[0])
    except (ValueError, IndexError):
        return None


_XS = re.compile(r"([\u4e00-\u9fff])姓([\u4e00-\u9fff]{1,2})氏")


def xing_shi(bio):
    """→ (姓, 氏)。

    游戏 bio 有三种写法（都要吃住）：
      · `英布，嬴姓英氏。`        → (嬴, 英)
      · `风厉鸟，风氏。`          → ("" , 风)   ← ★ 只有氏，没写姓
      · `狐突，姬姓狐氏。`        → (姬, 狐)

    ⚠️ 2026-09-30：原来漏了第二种，于是 `风厉鸟` 解析成 ("","") ⇒
       同氏候选全军覆没（风丘萤、风封胥… 全被判成"无关"）。
    """
    b = str(bio or "")
    m = _XS.search(b)
    if m:
        return m.group(1), m.group(2)
    m = _XING_ONLY.search(b)
    if m:
        return m.group(1), ""
    m = _SHI_ONLY.match(b)          # 只有"氏"的写法
    return "", (m.group(1) if m else "")


def build_items():
    """把推定边整理成前端要的条目（附分组与建议）。

    ★ 2026-09-30 使用者给的**分层规则**：
      1. 游戏里**无父也无子** ⇒ 就是个**单节点**，不虚接（实测 378/479 条）；
      2. **是某支始祖（有子）** ⇒ 才需要接：有史料则**实接**，无则**虚接**；
      3. 没有资料实证时，**同姓同氏 > 只同姓**（族名交集 ≥2 优先）；
      4. 知道祖先是谁、只不知中间隔几代的 ⇒ **特别需要虚接**。
    """
    fp = os.path.join(ROOT, "saves", BOOK, "family.json")
    data = json.load(open(fp, encoding="utf-8"))
    P = data["people"]

    # ---- 事实子女索引（判断是不是某支始祖）----
    kids = {}
    for n, v in P.items():
        for k in ("father", "mother"):
            p = v.get(k)
            if p and p in P:
                kids.setdefault(p, []).append(n)

    def _gap_ok(n):
        g = str(n.get("gender") or "")
        return ("男" in g) or (g == "")

    # ---- 按生年排序的全谱索引（找「同代人挂靠」候选用，避免每条扫全谱）----
    by_year = []
    for _n, _v in P.items():
        _y = yr(_v)
        if _y is not None:
            by_year.append((_y, _n))
    by_year.sort()
    _years = [t[0] for t in by_year]

    # ---- 后代集合：挂靠/虚接都不能挑到自己的子孙 ----
    def _descendants(nm):
        out, q = set(), [nm]
        while q:
            cur = q.pop()
            for ch in kids.get(cur, ()):
                if ch not in out:
                    out.add(ch)
                    q.append(ch)
        return out

    def nearest_same_state(nm, rec, k=3):
        """同代人挂靠候选 —— ★ 使用者 2026-09-30 明确：

            「彭越、任敖**挂靠到同势力的人身上，以同代人身份**」

        所以挂靠的**首要依据是"同势力"**（不是同姓）——
        彭越(势力彭) 挂 彭绶英；任敖(势力任) 挂 任嚣。
        同姓只做**次级**参考（同势力没有时才用）。
        生年窗口两侧各 ±60 年。
        """
        my = yr(rec)
        if my is None:
            return []
        import bisect
        rk, rshi = clan(rec.get("bio")), xing_shi(rec.get("bio"))[1]
        my_st = rec.get("state_name") or ""
        # ⚠️ 窗口按**年份**取（±60），不是按索引 ——
        #   上一版写成 `by_year[i-80:i+80]`，在生年稀疏的年代会跨出上千年
        #   （实测「狐突 前736」挂到了「风厉鸟 前2271」）。
        lo = bisect.bisect_left(_years, my - 60)
        hi = bisect.bisect_right(_years, my + 60)
        _down = _descendants(nm)          # 不能挂到自己的子孙身上
        out = []
        for j in range(lo, hi):
            y, n2 = by_year[j]
            if n2 == nm or n2 in _down:
                continue
            v2 = P[n2]
            c_x, c_s = xing_shi(v2.get("bio"))
            same_st = 0 if (my_st and (v2.get("state_name") or "") == my_st) else 1
            # 档位：0 = 同势力；1 = 同氏；2 = 同姓；3 = 其他
            if same_st == 0:
                rank = 0
            elif rshi and c_s and rshi == c_s:
                rank = 1
            elif rk and (clan(v2.get("bio")) & rk):
                rank = 2
            else:
                rank = 3
            out.append((rank, same_st, abs(y - my), n2, y, v2))
        out.sort(key=lambda t: (t[0], t[1], t[2]))
        return [(t[0], t[3], t[4], t[5], t[2]) for t in out[:k]]

    items = []
    for nm, v in P.items():
        dad = str(v.get("father_guess") or "").strip()
        if not dad or dad not in P:
            continue
        d = P[dad]
        sy, dy = yr(v), yr(d)
        shared = sorted(clan(v.get("bio")) & clan(d.get("bio")))
        gap = (sy - dy) if (sy is not None and dy is not None) else None
        note = v.get("note") or ""
        st, dst = v.get("state_name") or "", d.get("state_name") or ""
        nk = len(kids.get(nm, []))
        xing, shi = xing_shi(v.get("bio"))
        _ox, _od = origin_of(shi)          # 氏源流（tools/shi_origin.py）

        # ---- 候选接点 ----
        #   ★ 2026-09-30 使用者纠正：判据要按**氏**，不是"族名交集≥2"。
        #     实例：`风厉鸟，风氏` 的 bio 只有氏没有姓 ⇒ 交集恒为 1，
        #     于是所有同氏（风丘萤、风封胥…）都被降级成"只同姓" —— 错。
        #   规则：**氏相同 > 姓相同**；"同姓同氏"只是"氏相同"的更强情形。
        rk, rshi = clan(v.get("bio")), shi
        _down = _descendants(nm)          # 不能接自己的子孙
        same_clan, same_xing = [], []
        if sy is not None:
            for cn, cv in P.items():
                if cn == nm or cn in _down:
                    continue
                c_x, c_s = xing_shi(cv.get("bio"))
                cy = yr(cv)
                if cy is None or cy >= sy or (sy - cy) < 15:
                    continue
                if not _gap_ok(cv):
                    continue
                # 同氏：氏都非空且相同（如 风厉鸟/风丘萤 都是"风氏"）
                if rshi and c_s and rshi == c_s:
                    same_clan.append((cn, cy, cv))
                elif xing and c_x and xing == c_x:
                    same_xing.append((cn, cy, cv))
        cand = sorted(same_clan, key=lambda t: -t[1])[:3]
        cand2 = sorted(same_xing, key=lambda t: -t[1])[:3]
        # 现有推定父属于哪一档
        _d_x, _d_s = xing_shi(d.get("bio"))
        got = ("同氏" if (rshi and _d_s and rshi == _d_s) else
               ("同姓" if (xing and _d_x and xing == _d_x) else "跨族"))

        # ---- 挂靠候选（同代人）：靠不上祖先时用 ----
        hook = nearest_same_state(nm, v) if (nk == 0 or not cand) else []

        # ---- 建议动作（按使用者 2026-09-30 规则）----
        #   ① 无父无子 ⇒ 挂靠（同代同势力的人），不虚接
        #   ② 先祖靠得上（有同氏候选）⇒ 虚接，同姓同氏优先、其次只同姓
        #   ③ 先祖可能查得到（先秦 + 有谥号）⇒ 查史料，查到就实接
        #   ④ 其余 ⇒ 挂靠
        if nk == 0:
            sug = "hook"
            why = "无父无子 ⇒ 不虚接，挂靠到同代同势力的人身上（与风巢皇树同在）"
        elif cand:
            sug = "guess"
            why = "有子，且谱里有**同姓同氏**的更早者可接 ⇒ 虚接（依据较硬）"
        elif note and (sy is None or sy <= -700):
            sug = "web"
            why = ("有子、有谥号 —— 史书可能查得到真正的祖先（如：英布之『英』"
                   "出自偃姓皋陶、夏侯之『夏侯』出自姒姓夏禹）")
        elif cand2:
            sug = "guess"
            why = "有子，仅有**同姓**（如嬴姓含秦赵英徐，依据较软）⇒ 虚接"
        else:
            sug = "hook"
            why = "有子但先祖完全靠不上 ⇒ 挂靠到同代同势力的人身上"
        grp = sug
        items.append({
            "id": "%s>%s" % (nm, dad),
            "son": nm, "dad": dad,
            "son_g": v.get("generation"), "dad_g": d.get("generation"),
            "son_y": sy, "dad_y": dy, "gap": gap,
            "son_st": st, "dad_st": dst,
            "note": note, "dad_note": d.get("note") or "",
            "shared": shared, "grp": grp,
            "sug": sug, "why": why,
            # 判断依据（使用者要求：不能只凭印象）
            "nk": nk,                                   # 事实子女数
            "xs": ("%s姓%s氏" % (xing, shi)) if (xing or shi) else "—",
            "origin": _od,                              # 氏源流一句话
            "origin_x": _ox,
            "got": got,                                 # 现有推定父属同姓同氏 / 只同姓
            "cand": ["%s(%s·%s)" % (c[0], c[1], (c[2].get("state_name") or "—"))
                     for c in cand],                    # 同姓同氏候选（最多3）
            "cand2": ["%s(%s·%s)" % (c[0], c[1], (c[2].get("state_name") or "—"))
                      for c in cand2],                  # 只同姓候选
            "hook": ["%s(%s·%s%s)" % (
                        t[1], t[2], (t[3].get("state_name") or "—"),
                        {0: "·同势力", 1: "·同氏", 2: "·同姓"}.get(t[0], ""))
                     for t in (hook or [])],            # 同代人挂靠候选
            "brief": "%s｜子%s｜现有接法:%s" % (
                ("跨势力 %s→%s" % (st or "—", dst or "—")) if st != dst else "同势力",
                nk, got),
            "son_bio": str(v.get("bio") or "")[:200],
            "dad_bio": str(d.get("bio") or "")[:200],
        })
    _order = {"hook": 0, "guess": 1, "web": 2}
    items.sort(key=lambda r: (_order.get(r["grp"], 9),
                              -(r["nk"] or 0),
                              r["son_y"] if r["son_y"] is not None else 0))
    return items


HTML = r"""<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>虚接复核 · 大周列国志</title>
<style>
:root{
  --bg:#f2ecdc; --panel:#f8f4e8; --card:#fdfaee; --bar:#f8f4e8;
  --line:#ddd0b8; --line2:#e8e0cc;
  --ink:#2a1a0a; --ink2:#5a4a38; --ink3:#8a7a64;
  --acc:#1f6b4f; --acc-soft:#dcebe2;
  --gold:#a8781f; --gold-soft:#f2e3c2;
  --red:#b33a2b; --red-soft:#f6dcd6;
  --blue:#2b5f8a; --blue-soft:#dde8f2;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:13px/1.55 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
a{color:var(--acc)}
b,strong{font-weight:700}

/* ── 顶栏 ── */
header{position:sticky;top:0;z-index:10;background:var(--panel);
  border-bottom:1px solid var(--line);padding:9px 14px;
  display:flex;align-items:center;gap:14px;flex-wrap:wrap}
.brand{font-size:15px;font-weight:800;letter-spacing:.5px}
.sub{color:var(--ink3);font-size:12px}
.spacer{flex:1}
.pill{background:var(--card);border:1px solid var(--line2);border-radius:999px;
  padding:3px 11px;font-size:12px;color:var(--ink2)}
.pill b{color:var(--ink);font-family:Arial,sans-serif}
button{font:inherit;cursor:pointer;border-radius:6px;border:1px solid var(--line);
  background:var(--card);color:var(--ink);padding:5px 12px}
button:hover{border-color:var(--acc);color:var(--acc)}
button.primary{background:var(--acc);border-color:var(--acc);color:#fff;font-weight:700}
button.primary:hover{filter:brightness(1.08)}
button.ghost{background:transparent}
button.sm{padding:2px 9px;font-size:12px}

/* ── 进度 ── */
.prog{height:4px;background:var(--line2);border-radius:2px;overflow:hidden;flex:0 0 180px}
.prog i{display:block;height:100%;background:var(--acc);width:0;transition:width .2s}

/* ── 分组 ── */
main{padding:12px 14px 90px;max-width:1180px;margin:0 auto}
.grp{background:var(--panel);border:1px solid var(--line);border-radius:9px;
  margin-bottom:12px;overflow:hidden}
.grp>h2{margin:0;padding:8px 12px;background:var(--bar);border-bottom:1px solid var(--line2);
  font-size:13.5px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.grp>h2 .n{color:var(--ink3);font-weight:400;font-size:12px}
.grp>h2 .desc{color:var(--ink2);font-weight:400;font-size:12px}
.grp .body{padding:2px 0}

/* ── 条目 ── */
.row{display:flex;align-items:center;gap:10px;padding:5px 12px;
  border-bottom:1px solid var(--line2)}
.row:last-child{border-bottom:0}
.row.done{background:var(--acc-soft)}
.row .who{flex:0 0 268px;min-width:0}
.row .who .nm{font-weight:700}
.row .who .meta{color:var(--ink3);font-size:11.5px;font-family:Arial,sans-serif}
.row .arrow{flex:0 0 210px;min-width:0;color:var(--ink2);font-size:12px}
.row .arrow .d{font-weight:700}
.row .why{flex:1;min-width:0;color:var(--ink3);font-size:11.5px;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.seg{display:flex;gap:4px;flex:0 0 auto}
.seg button{padding:3px 10px;font-size:12px;border-radius:6px;min-width:62px;text-align:center}
.seg button.on[data-v=hook]{background:var(--gold);border-color:var(--gold);color:#fff;font-weight:700}
.seg button.on[data-v=guess]{background:var(--acc);border-color:var(--acc);color:#fff;font-weight:700}
.seg button.on[data-v=web]{background:var(--blue);border-color:var(--blue);color:#fff;font-weight:700}
.seg button[data-v=hook]:hover{background:var(--gold-soft)}
.seg button[data-v=guess]:hover{background:var(--acc-soft)}
.seg button[data-v=web]:hover{background:var(--blue-soft)}
.kid{font-size:10.5px;font-weight:400;color:var(--ink3);background:var(--card);
  border:1px solid var(--line2);border-radius:3px;padding:0 4px;margin-left:2px}
.pl{color:var(--ink3);font-size:11.5px}
.orgn{font-size:11px;color:var(--gold);margin-top:1px;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.thead{display:flex;align-items:center;gap:10px;padding:4px 12px;
  background:var(--bg-app);border-bottom:1px solid var(--line);
  font-size:11.5px;color:var(--ink3);font-weight:700}
.thead .who{flex:0 0 268px}
.thead .arrow{flex:0 0 210px}
.thead .why{flex:1}
.thead .seg{flex:0 0 auto;min-width:200px;text-align:right;padding-right:4px}
.cand{display:block;color:var(--acc);font-size:11px;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.cand2{display:block;color:var(--ink3);font-size:11px;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.grpbar{padding:6px 12px;background:var(--card);border-top:1px solid var(--line2);
  display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.grpbar .lab{color:var(--ink3);font-size:12px}

/* ── 底栏 ── */
footer{position:fixed;bottom:0;left:0;right:0;background:var(--panel);
  border-top:1px solid var(--line);padding:9px 14px;
  display:flex;gap:12px;align-items:center;flex-wrap:wrap;z-index:10}
footer .st{color:var(--ink2);font-size:12.5px}
footer .st b{font-family:Arial,sans-serif}
.toast{position:fixed;bottom:64px;left:50%;transform:translateX(-50%);
  background:var(--acc);color:#fff;padding:8px 18px;border-radius:8px;
  font-size:13px;opacity:0;pointer-events:none;transition:opacity .25s;z-index:20}
.toast.show{opacity:1}
.toast.err{background:var(--red)}
@media(max-width:900px){
  .row{flex-wrap:wrap}
  .row .who,.row .arrow{flex:1 1 46%}
  .row .why{display:none}
}
</style></head>
<body>

<header>
  <span class="brand">虚接复核</span>
  <span class="sub">《全史存档》推定世系 · 逐条定夺</span>
  <span class="pill">已选 <b id="nSel">0</b> / <b id="nAll">0</b></span>
  <span class="prog"><i id="prog"></i></span>
  <span class="spacer"></span>
  <button class="ghost sm" id="bm">全部按建议</button>
  <button class="ghost sm" id="br">全部重置</button>
</header>

<main id="app"></main>

<footer>
  <span class="st">挂靠 <b id="cHook">0</b> ｜ 虚接 <b id="cGuess">0</b> ｜ 查史料 <b id="cWeb">0</b></span>
  <span class="spacer"></span>
  <span class="st" id="saveTip"></span>
  <button class="primary" id="submit">提交复核结果</button>
</footer>
<div class="toast" id="toast"></div>

<script>
const GRP_DESC = {
  'hook':{t:'① 建议「挂靠」',d:'无父无子、或先祖完全靠不上 —— 不做虚接，挂靠到同代同势力的人身上（与风巢皇始祖树同在一处）'},
  'guess':{t:'② 建议「虚接」',d:'有子，且谱里有更早的同族可接 —— 虚接（灰虚线）。同姓同氏优先，其次只同姓'},
  'web':{t:'③ 建议「查史料」',d:'有子且有谥号 —— 史书可能查得到真祖先（如英布之「英」出自偃姓皋陶）—— 查到就实接'}
};
let ITEMS=[], SEL={};

function fmtY(y){ return y==null?'—':(y<0?('前'+(-y)):(''+y)); }

function render(){
  const byGrp={};
  ITEMS.forEach(it=>{ (byGrp[it.grp]=byGrp[it.grp]||[]).push(it); });
  const app=document.getElementById('app');
  app.innerHTML = Object.keys(byGrp).sort().map(g=>{
    const list=byGrp[g], info=GRP_DESC[g]||{t:g,d:''};
    const rows = list.map(it=>{
      const v=SEL[it.id];
      const cls=v?'done':'';
      const meta=[ '世代'+it.son_g, fmtY(it.son_y), it.xs, it.son_st, it.note ].filter(Boolean).join(' · ');
      const dmeta=[ '世代'+it.dad_g, fmtY(it.dad_y), it.dad_st, it.dad_note ].filter(Boolean).join(' · ');
      return `<div class="row ${cls}" data-id="${it.id}">
        <div class="who" title="${it.son_bio}">
          <div class="nm">${it.son} <span class="kid">${it.nk?('子'+it.nk):'无子'}</span></div>
          <div class="meta">${meta}</div>
          ${it.origin?('<div class="orgn">氏源流：'+it.origin+'</div>'):''}
        </div>
        <div class="arrow" title="${it.dad_bio}">
          <span class="pl">父 =</span> <span class="d">${it.dad}</span>
          <div class="meta">${dmeta}</div>
        </div>
        <div class="why">
          ${it.brief}
          ${(it.cand&&it.cand.length)?('<span class="cand">祖先候选(同氏) '+it.cand.join('、')+'</span>')
            :((it.cand2&&it.cand2.length)?('<span class="cand2">祖先候选(仅同姓) '+it.cand2.join('、')+'</span>')
            :((it.hook&&it.hook.length)?('<span class="cand2">挂靠候选(同代) '+it.hook.join('、')+'</span>'):''))}
        </div>
        <div class="seg">
          <button data-v="hook"  class="${v==='hook'?'on':''}">挂靠</button>
          <button data-v="guess" class="${v==='guess'?'on':''}">虚接</button>
          <button data-v="web"   class="${v==='web'?'on':''}">查史料</button>
        </div>
      </div>`;
    }).join('');
    return `<section class="grp" data-g="${g}">
      <h2>${info.t} <span class="n">${list.length} 条</span>
        <span class="desc">${info.d}</span></h2>
      <div class="thead">
        <div class="who">本人（儿子）</div>
        <div class="arrow">拟接的父亲</div>
        <div class="why">判断依据 / 候选</div>
        <div class="seg">你的定夺</div>
      </div>
      <div class="body">${rows}</div>
      <div class="grpbar">
        <span class="lab">整批：</span>
        <button class="sm" data-bulk="hook">全设挂靠</button>
        <button class="sm" data-bulk="guess">全设虚接</button>
        <button class="sm" data-bulk="web">全设查史料</button>
        <button class="sm" data-bulk="sug">按建议</button>
        <button class="sm" data-bulk="clear">清空本批</button>
      </div>
    </section>`;
  }).join('');
  updateCounts();
}

function updateCounts(){
  const c={hook:0,guess:0,web:0};
  Object.values(SEL).forEach(v=>{ if(c[v]!=null) c[v]++; });
  const sel=Object.keys(SEL).length;
  document.getElementById('nSel').textContent=sel;
  document.getElementById('nAll').textContent=ITEMS.length;
  document.getElementById('cHook').textContent=c.hook;
  document.getElementById('cGuess').textContent=c.guess;
  document.getElementById('cWeb').textContent=c.web;
  document.getElementById('prog').style.width=(ITEMS.length?100*sel/ITEMS.length:0)+'%';
  localStorage.setItem('review_sel', JSON.stringify(SEL));
  // 逐行高亮
  document.querySelectorAll('.row').forEach(r=>{
    const v=SEL[r.dataset.id];
    r.classList.toggle('done', !!v);
    r.querySelectorAll('.seg button').forEach(b=>{
      b.classList.toggle('on', b.dataset.v===v);
    });
  });
}

document.addEventListener('click', e=>{
  const b=e.target.closest('.seg button');
  if(b){
    const id=b.closest('.row').dataset.id, v=b.dataset.v;
    SEL[id] = (SEL[id]===v) ? undefined : v;   // 再点一次取消
    if(!SEL[id]) delete SEL[id];
    updateCounts();
    return;
  }
  const bulk=e.target.closest('[data-bulk]');
  if(bulk){
    const g=bulk.closest('.grp').dataset.g, mode=bulk.dataset.bulk;
    ITEMS.filter(it=>it.grp===g).forEach(it=>{
      if(mode==='clear') delete SEL[it.id];
      else if(mode==='sug') SEL[it.id]=it.sug;
      else SEL[it.id]=mode;
    });
    updateCounts();
  }
});

document.getElementById('bm').onclick=()=>{
  ITEMS.forEach(it=>SEL[it.id]=it.sug); updateCounts();
};
document.getElementById('br').onclick=()=>{
  SEL={}; updateCounts();
};

document.getElementById('submit').onclick=async ()=>{
  const out={};
  ITEMS.forEach(it=>{ if(SEL[it.id]) (out[SEL[it.id]]=out[SEL[it.id]]||[]).push(it.id); });
  const n=Object.values(out).reduce((a,b)=>a+b.length,0);
  if(!n){ toast('还没选任何一条 —— 至少点一条，或直接按建议全部设置', true); return; }
  try{
    const r=await fetch('/api/submit',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({sel:SEL, summary:out, ts:new Date().toISOString()})});
    const j=await r.json();
    if(j.ok){ toast('已提交：'+j.n+' 条 → '+j.path);
      document.getElementById('saveTip').textContent='已提交 '+j.time; }
    else { toast('提交失败：'+(j.err||'未知'), true); }
  }catch(err){ toast('提交出错：'+err, true); }
};

function toast(msg, err){
  const t=document.getElementById('toast');
  t.textContent=msg; t.className='toast show'+(err?' err':'');
  setTimeout(()=>t.className='toast', 2600);
}

(async function init(){
  const r=await fetch('/api/items'); ITEMS=await r.json();
  try{ SEL=JSON.parse(localStorage.getItem('review_sel')||'{}'); }catch(e){ SEL={}; }
  render();
})();
</script></body></html>
"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        raw = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.startswith("/api/items"):
            try:
                self._send(200, build_items())
            except Exception as e:
                self._send(500, {"err": str(e)})
        elif self.path in ("/", "/index.html"):
            self._send(200, HTML, "text/html; charset=utf-8")
        else:
            self._send(404, {"err": "not found"})

    def do_POST(self):
        if not self.path.startswith("/api/submit"):
            self._send(404, {"err": "not found"})
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception as e:
            self._send(400, {"err": "bad json: %s" % e})
            return
        try:
            sel = payload.get("sel") or {}
            items = {it["id"]: it for it in build_items()}
            # 落盘：明细 + 三个动作清单（供 AI 照单执行）
            detail = []
            for k, v in sel.items():
                it = items.get(k)
                detail.append({"id": k, "action": v,
                               "son": it["son"] if it else k.split(">")[0],
                               "dad": it["dad"] if it else "",
                               "grp": it["grp"] if it else "",
                               "sug": it["sug"] if it else ""})
            out = {
                "ts": payload.get("ts") or time.strftime("%Y-%m-%d %H:%M:%S"),
                "book": BOOK,
                "明细": detail,
                "挂靠": payload.get("summary", {}).get("hook", []),
                "虚接": payload.get("summary", {}).get("guess", []),
                "查史料": payload.get("summary", {}).get("web", []),
            }
            os.makedirs(os.path.dirname(RESULT), exist_ok=True)
            with open(RESULT, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=1)
            print("[复核提交] %d 条 → %s" % (len(detail), RESULT), flush=True)
            self._send(200, {"ok": True, "n": len(detail), "path": RESULT,
                             "time": time.strftime("%H:%M:%S")})
        except Exception as e:
            self._send(500, {"ok": False, "err": str(e)})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port", nargs="?", type=int, default=8802)
    args = ap.parse_args()
    n = len(build_items())
    print("=" * 62)
    print("虚接复核页  ·  《%s》推定边 %d 条" % (BOOK, n))
    print("  本机   http://127.0.0.1:%d/" % args.port)
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        print("  平板   http://%s:%d/" % (s.getsockname()[0], args.port))
        s.close()
    except Exception:
        pass
    print("  提交写到：%s" % RESULT)
    print("  （Ctrl+C 停止）")
    print("=" * 62)
    ThreadingHTTPServer(("0.0.0.0", args.port), H).serve_forever()


if __name__ == "__main__":
    main()
