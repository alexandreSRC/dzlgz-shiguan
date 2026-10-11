# -*- coding: utf-8 -*-
"""整块家谱 PNG 离线渲染器 v3 —— **分块流式 + 自动拼 PDF**（★ 2026-10-02）。

不依赖窗口/屏幕：直接用 PIL 按 `app.layout` 的布局数据把**整块画布**
渲染成 PNG。画布 ≤9000×9000 时出**单张**图；超过时按 9000px 网格
分块（如《全史存档》105,000×15,500 → 12×2 = 24 张 8912×6404），
并自动把所有块拼成**一份 PDF**（每页一块、全分辨率、页尺寸合规）。

渲染按条带（横带 400px）逐带绘制、边画边压缩进 zlib 流 ——
内存只占一个条带，图再大也不爆。

用法：python tools/export_png.py 全史存档 [--scale 2.0] [--tile 9000]
"""
import argparse
import io
import math
import os
import re
import struct
import sys
import time
import zlib

try:
    _out = getattr(sys, "stdout", None)
    if _out is not None and getattr(_out, "buffer", None) is not None:
        sys.stdout = io.TextIOWrapper(_out.buffer, encoding="utf-8",
                                      errors="replace")
except Exception:
    pass                    # ★ GUI（pythonw）无控制台时 sys.stdout 为 None —— 别再崩
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

PAPER = "#f7f2e7"
_BAND_H = 400            # 渲染条带高（像素）
_OVERLAP = 90            # 条带间重叠：跨带的铭牌/文字两带各画一次，接缝无缺

# ★ 2026-10-03 补回（重写 export_png 时被踩掉的一百批倍率常量）：
#   一百批（2026-10-02）「导出倍率提高 —— 使用者要 dpi 非常高清」定的两个基准。
#   代际 2.0 → 3.0（汉字 30 → 45px）；时间 基准 6px/年 × 1.5 = 9px/年。
#   证据：磁盘上《全史存档》代际成品 = 197808×29232（= 3.0 那档），
#   重写后默认被重置成 2.0 → 下次导出会缩水，属回归。
DEFAULT_GEN_SCALE = 3.0     # 代际基准倍率（`render_book` 默认）
TIME_SCALE_MUL = 1.5        # 时间倍率（`render_timeline` 默认，× 基准 6px/年）


class StreamingPNG:
    """流式写 PNG：多 IDAT 段共用一个 zlib 流，内存只占当前条带。"""

    def __init__(self, width, height, path):
        self.w, self.h, self.path = width, height, path
        self.f = open(path, "wb")
        self.f.write(b"\x89PNG\r\n\x1a\n")
        ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
        self.f.write(struct.pack(">I", 13))
        self.f.write(b"IHDR")
        self.f.write(ihdr)
        self.f.write(struct.pack(
            ">I", zlib.crc32(b"IHDR" + ihdr) & 0xffffffff))
        self.z = zlib.compressobj(6)

    def feed(self, rows_raw):
        """喂入若干行（每行 = NUL 前缀 + RGB 像素），自动切 IDAT 段。"""
        data = self.z.compress(bytes(rows_raw))
        if data:
            self._idat(data)

    def _idat(self, data):
        CHUNK = 1 << 22
        while data:
            piece, data = data[:CHUNK], data[CHUNK:]
            self.f.write(struct.pack(">I", len(piece)))
            self.f.write(b"IDAT")
            self.f.write(piece)
            self.f.write(struct.pack(
                ">I", zlib.crc32(b"IDAT" + piece) & 0xffffffff))

    def close(self):
        self._idat(self.z.flush())
        self.f.write(struct.pack(">I", 0))
        self.f.write(b"IEND")
        self.f.write(struct.pack(">I", zlib.crc32(b"IEND") & 0xffffffff))
        self.f.close()


def _font(size):
    for f in ("C:/Windows/Fonts/simkai.ttf", "C:/Windows/Fonts/simsun.ttc",
              "C:/Windows/Fonts/msyh.ttc"):
        if os.path.exists(f):
            try:
                return ImageFont.truetype(f, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _split_dup(name):
    m = re.match(r"^(.*?)(\d+)$", name)
    if m and m.group(1):
        return m.group(1), m.group(2)
    return name, ""


ERA_COLORS = {
    "上古": "#8d7f6a", "夏": "#a08a63", "商": "#b58a4a", "西周": "#c08b3e",
    "春秋": "#b3612f", "战国": "#9c4a2a", "秦": "#5a4a6a", "汉": "#1f6b4f",
    "三国": "#3a6b8a", "晋": "#4a7a9a", "南北朝": "#5a7a8a", "隋": "#6a8a7a",
    "唐": "#8a7a3a", "五代": "#7a6a4a", "宋": "#6a7a5a",
}


def _nice_step(min_px, scale):
    for s in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000):
        if s * scale >= min_px:
            return s
    return 5000


def _fmt_short(y):
    return f"前{-y}" if y < 0 else f"{y}"


def _era_label(name):
    return name + "朝" if len(name) == 1 else name


def _stamp():
    import time
    return time.strftime("%Y%m%d_%H%M%S")


def _text_w(txt, font):
    """字体量宽（PIL 真字体有 getlength；退化字体的兜底按字号估）。"""
    try:
        return float(font.getlength(txt))
    except Exception:
        try:
            return len(txt) * float(font.size) * 0.62
        except Exception:
            return len(txt) * 8.0


def _dashed_poly(dr, pts, fill, width=1, dash=(4, 3)):
    """PIL 没有虚线图元 —— 沿折线自绘。

    ★ 2026-10-11：从「只认两段 `(实, 空)`」**推广成任意偶数段**（与 Tk 的 `dash`
      同义：依次是 实/空/实/空… 的像素长度）。为什么必须改：屏幕上「推定世系」
      用的是**点划线 `(7,3,1,3)`**，导出要与它同款，两段版会 `ValueError`。
    """
    if len(pts) < 2:
        return
    pat = [float(x) for x in dash]
    if len(pat) % 2:                      # 奇数段：补一个 0（Tk 同样容错）
        pat.append(0.0)
    if not pat or sum(pat) <= 0:
        return
    period = sum(pat)
    phase = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        dx, dy = x2 - x1, y2 - y1
        seg = math.hypot(dx, dy)
        if seg <= 1e-9:
            continue
        ux, uy = dx / seg, dy / seg
        t = 0.0
        while t < seg:
            p = (phase + t) % period
            acc, idx = 0.0, 0
            while idx < len(pat) and acc + pat[idx] <= p:
                acc += pat[idx]
                idx += 1
            if idx < len(pat) and idx % 2 == 0:      # 偶数段 = 实
                run = min(pat[idx] - (p - acc), seg - t)
                dr.line([x1 + ux * t, y1 + uy * t,
                         x1 + ux * (t + run), y1 + uy * (t + run)],
                        fill=fill, width=width)
            t += min(period - p, seg - t)
        phase = (phase + seg) % period


def _dashed_rect(dr, x0, y0, x1, y1, color, dash=(4, 3)):
    """虚线矩形（PIL 没有，用 `_dashed_poly` 描一圈）。"""
    _dashed_poly(dr, [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)],
                 color, width=1, dash=dash)


def render_timeline(book, outdir="导出画布", plate="v", scale_mul=TIME_SCALE_MUL,
                    band_h=_BAND_H, on_progress=None):
    """时间家谱整块离线渲染（★ 2026-10-03 重写 —— 真流式，九十九批规格）。

    为什么重写：上一版是「**假**流式」—— 它用 `Image.new` 一次开**整张**画布，
    《全史存档》那种 50000×10000 ≈ 5 亿像素直接 OOM；连线也只画两端点的
    **直斜线**（不走路由，会从卡片上压过去），且**漏了世系虚线框与「全览」标签**。
    本版与 `render_book` 同一套流式骨架（逐条带画、边画边压进 zlib），
    并与屏上 `timeline_view.redraw` **同源**绘制。

    绘制顺序（同屏上）：朝代带（色块/朝代名/年份刻度/「全览」标签）→ 年格线
    → 世系虚线框 → 连线（父子**走 `lay.path_for` 路由**、挂母线·母系额外线画
    婚姻色虚线）→ 铭牌（爵色描边/填底 · 已故灰字 · 女性红名淡底 · 竖横排 ·
    弹性字号 · 尊号小字 · 重名角标 · 封代数字）→ 夫妻红线（U 型 + ♥）→ 接入点圆点。
    ⚠️ 所有文字用**带内相对坐标**（`Y(v) = v - by0`）—— 吸取九十七批
    「用画布绝对坐标 ⇒ 只有第 0 带有字」的教训。

    返回 [(文件, 宽, 高)]（**单图**一份；`main.py` 的时间分支按此消费）。
    """
    from app import storage
    from app import timeline as T
    from app import layout as LAY
    from app import jue
    from app.theme import get_theme

    theme = get_theme("宣纸")
    people = storage.load_save(book)[0]
    jue.install_from_save(book)
    tiers = jue.tier_colors_for(people)
    try:
        hide_dead = storage.hide_dead_shade(book)
    except Exception:
        hide_dead = False

    scale = 6.0 * scale_mul                     # 基准 6px/年 × 倍率
    card_h = float(T.PLATES[plate][0])
    width_of = (lambda n: T.PLATES["v"][1]) if plate == "v" else T.card_width
    lay = T.compute(people, scale=scale, width_of=width_of, card_h=card_h)
    lay.route_all()                             # 导出不看视口 ⇒ 连线路径一次算全

    f_name = _font(max(9, int(15 * scale_mul)))
    f_note = _font(max(7, int(9 * scale_mul)))
    f_tick = _font(max(7, int(7 * scale_mul)))
    f_rail = _font(max(9, int(9 * scale_mul)))
    f_badge = _font(max(7, int(7 * scale_mul)))

    # 左沿朝代带宽：量「前2350」（与屏上同口径，最小 56）
    rail_w = max(56, int(_text_w("前2350", f_rail)) + 12)
    plate_w = float(T.PLATES[plate][1])

    W = int(lay.width) + rail_w + 60
    H = int(lay.height) + 40

    # 世系虚线框（只认 lineage_name；老档回退 state_name）
    try:
        boxes = LAY.state_group_boxes_timeline(
            people, lay.positions, lay.widths, lay.card_h, theme.tier,
            char_w=_text_w("世", f_rail), tier_of=tiers)
    except Exception:
        boxes = []

    outdir = os.path.join(ROOT, outdir, book)
    os.makedirs(outdir, exist_ok=True)
    fp = os.path.join(outdir, f"{book}_时间_{_stamp()}.png")

    year_lo, year_hi = lay.year_at(0.0), lay.year_at(float(H))
    rail_step = _nice_step(200, scale)
    grid_step = _nice_step(58, scale)

    # 预备：连线折线（含 rail 偏移在绘制时加）、接入点
    attach_m = set(getattr(lay, "attach_mother", ()) or ())
    links = []                                  # (折线, 是否虚线)
    for (_f, n, _ax, _ay, _bx, _by) in lay.link_pairs:
        pts = lay.path_for(n)[0]
        if pts:
            links.append((pts, n in attach_m))
    for (_m, n) in (getattr(lay, "mother_extra", ()) or ()):
        pts = lay.path_for_mother(n)[0]
        if pts:
            links.append((pts, True))
    ends = [(pts[0], pts[-1]) for (pts, _d) in links]

    sp = StreamingPNG(W, H, fp)
    n_bands = max(1, math.ceil(H / band_h))
    try:
        for bi in range(n_bands):
            by0 = bi * band_h
            by1 = min(by0 + band_h + _OVERLAP, H)
            bh = by1 - by0
            band = Image.new("RGB", (W, bh), PAPER)
            dr = ImageDraw.Draw(band)

            def Y(v):
                return v - by0

            # ---- 1) 朝代带（色块 + 朝代名 + 年份刻度）----
            taken = []
            for name, s2, e in T.era_segments(year_lo, year_hi):
                top, bot = lay.y_of(s2), lay.y_of(e + 1)
                if bot <= max(by0, 0) or top >= by1:
                    continue
                t2, b2 = max(top, by0), min(bot, by1)
                if b2 > t2:
                    dr.rectangle([0, Y(t2), rail_w, Y(b2)],
                                 fill=ERA_COLORS.get(name, "#8d7f6a"))
                if bot - top >= 46:
                    cyy = (top + bot) / 2
                    if by0 - 20 <= cyy <= by1 + 20:
                        taken.append(cyy)
                        dr.text((rail_w / 2, Y(cyy)), _era_label(name),
                                fill="#ffffff", font=f_rail, anchor="mm")
            yr = int(year_lo // rail_step) * rail_step
            while yr <= year_hi:
                yy = lay.y_of(yr)
                if by0 - 20 <= yy <= by1 + 20 and 8 <= yy <= H - 8 \
                        and all(abs(yy - c) > 13 for c in taken):
                    dr.text((rail_w / 2, Y(yy)), _fmt_short(yr),
                            fill="#ffffff", font=f_tick, anchor="mm")
                yr += rail_step
            dr.line([rail_w - 1, Y(max(0, by0)), rail_w - 1, Y(by1)],
                    fill=theme.border, width=2)

            # ---- 2) 年格线 + 年份 ----
            yr = int(year_lo // grid_step) * grid_step
            while yr <= year_hi:
                yy = lay.y_of(yr)
                if by0 - 20 <= yy <= by1 + 20 and 0 <= yy <= H:
                    dr.line([rail_w, Y(yy), W, Y(yy)], fill=theme.grid)
                    dr.text((rail_w + 6, Y(yy) + 2), _fmt_short(yr),
                            fill=theme.text_3, font=f_tick)
                yr += grid_step

            # ---- 3) 世系虚线框（画在连线/卡片之下）----
            for min_x, min_y, max_x, max_y, bcolor, title in boxes:
                if max_y < by0 - 20 or min_y > by1 + 20:
                    continue
                x0, x1 = min_x + rail_w, max_x + rail_w
                t2, b2 = max(min_y, by0), min(max_y, by1)
                if b2 > t2:
                    _dashed_rect(dr, x0, Y(t2), x1, Y(b2), bcolor)
                if title and by0 - 20 <= min_y <= by1 + 20:
                    tw = min(_text_w(title, f_rail) + 10, max_x - min_x - 4)
                    cx = (x0 + x1) / 2
                    dr.rectangle([cx - tw / 2, Y(min_y), cx + tw / 2,
                                  Y(min_y + 13)], fill=bcolor)
                    dr.text((cx, Y(min_y + 6.5)), title, fill="#ffffff",
                            font=f_rail, anchor="mm")

            # ---- 4) 连线（画在卡片之下）----
            for pts, is_dash in links:
                ys = [p[1] for p in pts]
                if max(ys) < by0 - 40 or min(ys) > by1 + 40:
                    continue
                lp = [(px + rail_w, Y(py)) for (px, py) in pts]
                if is_dash:
                    _dashed_poly(dr, lp, theme.spouse, width=1, dash=(3, 2))
                else:
                    dr.line([v for p in lp for v in p],
                            fill=theme.tree_line, width=1)

            # ---- 5) 铭牌 ----
            for name, (x, y) in lay.positions.items():
                if y + card_h < by0 - 40 or y > by1 + 40:
                    continue
                r = people.get(name) or {}
                base, dup = _split_dup(name)
                tier = tiers.get(name, "")
                female = r.get("gender") == "女"
                dead = bool(r.get("death")) and not hide_dead
                color = theme.tier.get(tier) or theme.tier.get("无", "#8a8a8a")
                tier_fill = (bool(color) and tier in theme.tier
                             and tier not in ("", "无"))
                if dead and tier_fill:
                    fill, tcolor = color, "#d8d3c6"
                elif dead:
                    fill, tcolor = (theme.bg_dead or "#d9d4c8"), theme.text_3
                elif tier_fill and female:
                    fill, tcolor = _tint(color), theme.spouse
                elif tier_fill:
                    fill, tcolor = color, "#ffffff"
                elif female:
                    fill, tcolor = theme.female, theme.spouse
                else:
                    fill, tcolor = theme.bg_card, theme.text
                px_, py_ = x + rail_w, Y(y)
                left, right = px_ - plate_w / 2, px_ + plate_w / 2
                top, bot = py_, py_ + card_h
                dr.rectangle([left, top, right, bot], fill=fill or None,
                             outline=theme.border_2, width=1)
                if color and not tier_fill:
                    dr.rectangle([left, top, right, bot], fill=None,
                                 outline=color, width=2)
                if plate == "v":
                    dr.text((px_, top + card_h / 2), chr(10).join(base),
                            fill=tcolor, font=f_name, anchor="mm")
                else:
                    dr.text((left + 2, top + card_h / 2), base,
                            fill=tcolor, font=f_name, anchor="lm")
                if dup:
                    dr.text((right - 3, top + 1), dup, fill=theme.text_3,
                            font=f_badge, anchor="ra")
                note = str(r.get("note") or "")
                if note:
                    nfg = theme.spouse if female else theme.text_2
                    ny = top + card_h / 2 - f_note.size * min(3, len(note)) / 2
                    for ch2 in note[:4]:
                        dr.text((right + 2, ny), ch2, fill=nfg, font=f_note)
                        ny += f_note.size
                fgen = r.get("fief_gen") or 0
                if fgen:
                    dr.text((px_, bot + 5), str(fgen), fill=theme.text_2,
                            font=f_badge, anchor="ma")

            # ---- 6) 夫妻红线（U 型 + ♥）----
            sp_line = theme.spouse_line or theme.spouse
            for name, (x1, y1) in lay.positions.items():
                if y1 + card_h < by0 - 60 or y1 > by1 + 60:
                    continue
                for s in ((people.get(name) or {}).get("spouses") or []):
                    if not s or s <= name or s not in lay.positions:
                        continue
                    x2, y2 = lay.positions[s]
                    w1, w2 = lay.widths[name], lay.widths[s]
                    if x1 <= x2:
                        lx, rx = x1 + w1 / 2, x2 - w2 / 2
                        b1, b2 = y1 + card_h, y2 + card_h
                    else:
                        lx, rx = x2 + w2 / 2, x1 - w1 / 2
                        b1, b2 = y2 + card_h, y1 + card_h
                    if rx - lx < 2:
                        continue
                    drop = max(b1, b2) + 5.0
                    if drop < by0 - 40 or max(b1, b2) > by1 + 40:
                        continue
                    _dashed_poly(dr,
                                 [(lx + rail_w, Y(b1)), (lx + rail_w, Y(drop)),
                                  (rx + rail_w, Y(drop)), (rx + rail_w, Y(b2))],
                                 sp_line, width=1, dash=(4, 2))
                    dr.text(((lx + rx) / 2 + rail_w, Y(drop + 8)), "♥",
                            fill=sp_line, font=f_badge, anchor="ma")

            # ---- 7) 连线接入点（画在卡片之上；卡太密就不补点，免得成麻点）----
            if len(lay.positions) and len(lay.positions) <= 2400:
                for (p, q) in ends:
                    for (ex, ey) in (p, q):
                        if by0 - 8 <= ey <= by1 + 8:
                            exx, eyy = ex + rail_w, Y(ey)
                            dr.ellipse([exx - 1.5, eyy - 1.5,
                                        exx + 1.5, eyy + 1.5],
                                       fill=theme.tree_line)

            # ---- 8) 「全览」标签（钉在图顶端，与屏上钉视口顶同理）----
            if bi == 0:
                dr.rectangle([0, 0, rail_w, 22], fill=theme.bg_panel)
                dr.text((rail_w / 2, 11), "全览", fill=theme.text_2,
                        font=f_badge, anchor="mm")
                dr.line([0, 22, rail_w, 22], fill=theme.border)

            # ---- 喂进流式 PNG ----
            rows = band.tobytes()
            stride = W * 3
            raw = bytearray()
            for ry in range(bh):
                raw += b"\x00"
                raw += rows[ry * stride:(ry + 1) * stride]
            sp.feed(raw)
            if on_progress:
                on_progress(bi + 1, n_bands)
    finally:
        sp.close()

    return [(fp, W, H)]


def _tint(bg_hex, f=0.62):
    """爵色 → 淡底（向白色调 f 比例），给女性红名当底。"""
    try:
        r = int(bg_hex[1:3], 16)
        g = int(bg_hex[3:5], 16)
        b = int(bg_hex[5:7], 16)
    except Exception:
        return bg_hex
    return "#%02x%02x%02x" % (int(r + (255 - r) * f),
                              int(g + (255 - g) * f),
                              int(b + (255 - b) * f))


def tiles_to_pdf(files, pdf_path, resolution=100):
    """把分块 PNG 拼成一份 PDF（每页一块、全分辨率、页尺寸合规）。"""
    if not files:
        return None
    pages = []
    for f in files:
        path = f[0] if isinstance(f, tuple) else f
        pages.append(Image.open(path))   # 懒加载：save 时逐页编码，不占双份内存
    first, rest = pages[0], pages[1:]
    first.save(pdf_path, "PDF", save_all=True, append_images=rest,
               resolution=resolution)
    return pdf_path


def render_book(book, outdir="导出画布", scale=DEFAULT_GEN_SCALE, tile=9000,
                band_h=_BAND_H, on_progress=None, pdf=True, pdf_only=False):
    """把谱牒 `book` 的整块代际画布渲染成 PNG（大谱自动分块 + PDF）。

    返回 (files, pdf_path)；files = [(文件, 宽, 高), ...]。
    """
    from app import jue
    from app import storage
    from app.layout import compute_layout
    from app.theme import get_theme

    theme = get_theme("宣纸")
    jue.install_from_save(book)
    people = storage.load_save(book)[0]
    lay = compute_layout(people, scale=scale)
    tiers = jue.tier_colors_for(people)
    # ★ 2026-10-11 使用者：「导出的图片上还标有**灰色填充铭牌**（显示死亡），
    #   但**全谱是不需要显示死亡的**（没有标准时间；以后出新剧本还要续全谱）」
    #   ⇒ 与界面**同一口径**：谱牒自己声明了 `hide_dead_shade` 就不涂灰
    #   （判据唯一实现在 `storage.hide_dead_shade`，《全史存档》= True）。
    hide_dead = storage.hide_dead_shade(book)

    W = int(lay.scroll_x) + 260
    H = int(lay.scroll_y_end) + 60
    nw, nh = float(lay.node_w), float(lay.node_h)
    name_w = float(lay.name_width)
    font_name = _font(max(9, int(15 * scale)))
    font_gen = _font(max(9, int(13 * scale)))
    font_note = _font(max(7, int(9 * scale)))
    font_badge = _font(max(7, int(8 * scale)))
    font_guess = _font(max(9, int(10 * scale)))   # 「推定世系」小字
    font_sym = _font(max(9, int(15 * scale * 0.7)))   # 同代人符号 ♥ / 友

    outdir = os.path.join(ROOT, outdir, book)   # ★ 按谱分子目录
    os.makedirs(outdir, exist_ok=True)
    # ★ 2026-10-11：`--pdf-only` 时把中间分块写进**临时子目录**，拼完整目录删掉
    #   —— 不留在用户眼皮底下（拼装前不能删：PIL 是逐块读文件的）。
    png_dir = os.path.join(outdir, "_tiles_tmp") if pdf_only else outdir
    if pdf_only:
        os.makedirs(png_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")

    n_cols = max(1, math.ceil(W / tile))
    n_rows = max(1, math.ceil(H / tile))
    cw, chh = math.ceil(W / n_cols), math.ceil(H / n_rows)
    # ★ 2026-10-11：跨树夫妻 U 型线的「一对只画一颗♥」判重集（与屏幕 `tree_view` 同规）——
    #   夫妻已由 U 线正式相连时，挂靠那一侧就**不再画心**（否则一对夫妻两颗心）。
    _sp_line = theme.spouse_line or theme.spouse
    u_pairs = set()
    for _n2, _r2 in people.items():
        for _s2 in ((_r2.get("spouses") or [])):
            if _s2 in lay.positions:
                u_pairs.add(frozenset((_n2, _s2)))
    _assoc = getattr(lay, "associate_groups", {}) or {}
    _sym = max(6, int(15 * scale * 0.7))     # 同代人符号（♥/友）字号

    files = []
    total = n_cols * n_rows
    done = 0
    pdf_path = None
    for ri in range(n_rows):
        for ci in range(n_cols):
            x0, x1 = ci * cw, min((ci + 1) * cw, W)
            y0, y1 = ri * chh, min((ri + 1) * chh, H)
            tw, th = x1 - x0, y1 - y0
            fp = os.path.join(png_dir, f"{book}_代际_{stamp}"
                                      f"_r{ri + 1}c{ci + 1}.png") \
                if total > 1 else \
                os.path.join(png_dir, f"{book}_代际_{stamp}.png")
            sp = StreamingPNG(tw, th, fp)

            n_bands = max(1, math.ceil(th / band_h))
            try:
                for bi in range(n_bands):
                    by0 = y0 + bi * band_h
                    by1 = min(by0 + band_h + _OVERLAP, y1)
                    band = Image.new("RGB", (tw, by1 - by0), PAPER)
                    dr = ImageDraw.Draw(band)
                    # 本带内的「一对只画一次」判重（挂靠心 / 夫妻 U 线）——**每带重置**：
                    # 各带是独立画布，跨带的线必须在每条带上都画一遍才不断。
                    _paired = set()

                    def Y(v):
                        return v - by0

                    def X(v):
                        return v - x0

                    for d in range(lay.min_depth, lay.max_depth + 1):
                        y = lay.scroll_y_start + lay.top_margin + \
                            (d - lay.min_depth) * lay.level_height
                        if by0 - 40 <= y <= by1:
                            dr.text((20, Y(y)), f"第{d}代",
                                    fill=theme.text_3, font=font_gen)

                    for n, r in people.items():
                        if n not in lay.positions:
                            continue
                        x, y = lay.positions[n]
                        if not (x0 - nw - 20 <= x <= x1 + nw + 20):
                            continue
                        # ★★ 2026-10-11 使用者：「图里有些线没画，比如**姜尚的儿子跟姜尚**」。
                        #   真因：连线原来只在**子节点所在的那条带**里画（判据只看 `y`），
                        #   可姜丁(3199,4716) 与姜尚(4716,4622) 横向差 **1517px**、是条
                        #   **斜长线**，纵跨两三条带 ⇒ 其余带上**根本没画** ⇒ 看着断开。
                        #   ⇒ 判据改成看**连线自身的 y 跨度**（本人 + 父/母/推定父/配偶），
                        #   只要跨度与本带相交就画 —— 长线在它经过的每条带上都补齐。
                        _ys = [y]
                        for _k in ("father", "mother", "father_guess"):
                            _p = str(r.get(_k) or "")
                            if _p and _p in lay.positions:
                                _ys.append(lay.positions[_p][1])
                        for _p in (r.get("spouses") or []):
                            if _p in lay.positions:
                                _ys.append(lay.positions[_p][1])
                        if min(_ys) - nh > by1 + 40 or max(_ys) + nh < by0 - 40:
                            continue
                        f = str(r.get("father") or "")
                        m = str(r.get("mother") or "")
                        g = str(r.get("father_guess") or "")
                        if f in lay.positions and x0 <= lay.positions[f][0] <= x1:
                            fx, fy = lay.positions[f]
                            dr.line([X(fx), Y(fy + nh / 2),
                                     X(x), Y(y - nh / 2)],
                                    fill=theme.tree_line, width=2)
                        if m in lay.positions and m != f and \
                                x0 <= lay.positions[m][0] <= x1:
                            mx, my = lay.positions[m]
                            dr.line([X(mx), Y(my + nh / 2),
                                     X(x), Y(y - nh / 2)],
                                    fill=theme.spouse, width=1)
                        if g in lay.positions and g != f and \
                                x0 <= lay.positions[g][0] <= x1:
                            gx, gy = lay.positions[g]
                            # ★★ 2026-10-11 使用者：「导出画布上**为什么没看到虚接线和
                            #   注明的虚接小字**？」—— 原来这里只画一条 **1px 灰色实线**：
                            #   在 1.3 亿像素的大图上等于看不见；小字干脆没画。
                            #   ⇒ 改成与**屏幕同一画法**（`tree_view` 3b 层）：
                            #   **点划线 `(7,3,1,3)` + 两端圆点 + 中间「推定世系」小字**，
                            #   粗细 `max(2, 1.8×scale)`（随倍率放大，3.0 倍下 5px）。
                            #   ⚠️ 导出没有"选中态"，所以**每条都带字**（屏上只给选中那条）。
                            gp = [(X(gx), Y(gy + nh / 2)),
                                  (X(x), Y(y - nh / 2))]
                            gw = max(2, int(1.8 * scale))
                            _dashed_poly(dr, gp, theme.text_3, width=gw,
                                         dash=(7, 3, 1, 3))
                            rd = max(2, int(2.6 * scale))
                            for _px2, _py2 in gp:
                                dr.ellipse([_px2 - rd, _py2 - rd,
                                            _px2 + rd, _py2 + rd],
                                           fill=theme.text_3)
                            dr.text(((gp[0][0] + gp[1][0]) / 2,
                                     (gp[0][1] + gp[1][1]) / 2), "推定世系",
                                    fill=theme.text_3, font=font_guess,
                                    anchor="mm")
                        # ---- ★★ 2026-10-11 补：同代人符号（挂靠：♥ / 友）------
                        #   使用者：「补上挂靠符号」。原来 `render_book` **一个都没画**
                        #   （《全史存档》369 人挂靠）。画法与屏幕 `tree_view` 同款：
                        #   · 位置：两卡中点、**两卡下沿之下**（`bottom_y`），
                        #     同一锚下多个配偶按 `associate_groups` 的次序横向散开；
                        #   · `associate_type == "spouse"` → 红 **♥**，否则 → **友**（accent 色）；
                        #   · **夫妻已由 U 线相连的不再画心**（`u_pairs` 判重）——
                        #     否则一对夫妻两颗心（屏幕踩过这个坑，2026-10-03）。
                        _ref = str(r.get("associate_of") or "")
                        # ⚠️ 判据与屏幕**逐字同款**（两边一起修）：`associate_type`
                        #   **字段不存在**时不能当 clan —— 只有主程序/自动关注写的
                        #   宗主族人挂靠才显式标 "clan"（`main.py` 2620「算族人（不画♥）」），
                        #   而 `tools/guess_lineage.py` 的同代人挂靠**不写这个字段**，
                        #   五十五批口径明写「挂靠（同代人）→ 同排 + **「友」标**」。
                        #   实测《全史存档》351 条挂靠**全部缺这个字段** ⇒ 缺/空一律当「友」。
                        _atype = str(r.get("associate_type") or "friend")
                        if _ref and _ref != n and _ref in lay.positions \
                                and _atype != "clan" \
                                and frozenset((n, _ref)) not in u_pairs:
                            _rx, _ry = lay.positions[_ref]
                            _ws = _assoc.get(_ref) or [n]
                            _k = len(_ws)
                            _i = _ws.index(n) if n in _ws else 0
                            _mx = ((_rx + x) / 2
                                   + (_i - (_k - 1) / 2.0) * _sym * 1.6)
                            _by = max(_ry, y) + nh / 2 + 1 + _sym / 2
                            dr.text((_mx, _by),
                                    "♥" if _atype == "spouse" else "友",
                                    fill=(theme.spouse if _atype == "spouse"
                                          else theme.accent),
                                    font=font_sym, anchor="mm")
                        # ---- ★★ 2026-10-11 补：跨树夫妻 U 型线 + ♥ --------------
                        #   使用者：「补上跨树夫妻线」。屏幕是 U 型（下探 `8×scale`
                        #   再上来）+ 中点一颗♥；一对只画一次（`_paired` 判重）。
                        for _s in (r.get("spouses") or []):
                            _key = frozenset((n, _s))
                            if _s not in lay.positions or _key in _paired:
                                continue
                            _paired.add(_key)
                            _sx, _sy = lay.positions[_s]
                            _b1, _b2 = y + nh / 2, _sy + nh / 2
                            _dy = max(_b1, _b2) + 8 * scale
                            _uw = max(1, int(1.5 * scale))
                            _dashed_poly(dr,
                                         [(X(x), Y(_b1)), (X(x), Y(_dy)),
                                          (X(_sx), Y(_dy)), (X(_sx), Y(_b2))],
                                         _sp_line, width=_uw, dash=(4, 2))
                            dr.text(((X(x) + X(_sx)) / 2, Y(_dy) + 2 * scale),
                                    "♥", fill=_sp_line, font=font_sym,
                                    anchor="ma")

                    for n, (x, y) in lay.positions.items():
                        if not (x0 <= x <= x1
                                and by0 - nh - 20 <= y <= by1 + nh + 20):
                            continue
                        r = people.get(n) or {}
                        base, dup = _split_dup(n)
                        tier = tiers.get(n, "")
                        dead = bool(r.get("death")) and not hide_dead
                        female = r.get("gender") == "女"
                        color = theme.tier.get(tier, theme.text)
                        if female:
                            color = theme.spouse
                        elif dead:
                            color = theme.text_3
                        left, top = X(x - name_w / 2), Y(y - nh / 2)
                        right, bottom = X(x + name_w / 2), Y(y + nh / 2)
                        fill = (theme.bg_dead or "#d9d4c8") if dead else \
                               (theme.female if female else "")
                        dr.rectangle([left, top, right, bottom],
                                     fill=fill or None,
                                     outline=theme.tier.get(
                                         tier, theme.border_2), width=2)
                        size = max(9, min(font_name.size,
                                          int((nh - 8) /
                                              max(1, len(base)))))
                        vfont = ImageFont.truetype(font_name.path, size)
                        # ★★ 2026-10-11 使用者报「**导出的画布（全史存档 PDF）上面没有字**」：
                        #   真因就在这里 —— 姓名与尊号是**唯二**用**未偏移坐标**画的文字，
                        #   而整图是**按 400px 条带**分段渲染的（每条带一张小图，`Y(v)=v-by0`）。
                        #   从第 2 条带起 `by0 > 0` ⇒ 文字被画到条带画布之外、**直接被裁掉**
                        #   ⇒ 只有第 1 条带那条能看见名字，整张导出图看着"没有字"。
                        #   （框、「史」徽标、封代数字都用了 `X()/Y()`，所以它们都在。）
                        cy = Y(y) - size * len(base) / 2
                        for ch in base:
                            wch = dr.textlength(ch, font=vfont)
                            dr.text((X(x) - wch / 2, cy), ch,
                                    fill=color, font=vfont)
                            cy += size
                        if dup:
                            dr.text((right - 2, top + 2), dup,
                                    fill=theme.text_3, font=font_badge)
                        note = str(r.get("note") or "")
                        if note:
                            nf = ImageFont.truetype(
                                font_note.path, max(8, int(size * 0.45)))
                            ny = Y(y) - nf.size * min(4, len(note)) / 2
                            for ch in note[:4]:
                                wch = dr.textlength(ch, font=nf)
                                dr.text((right + 8, ny), ch,
                                        fill=theme.text_2, font=nf)
                                ny += nf.size
                        if r.get("historical", "是") == "是":
                            hs = int(nh / 5)
                            dr.rectangle([left - hs - 4, top,
                                          left - 4, top + hs],
                                         fill=theme.bg_canvas,
                                         outline=theme.hist or theme.divine,
                                         width=1)
                            dr.text((left - hs - 4 + 2, top + 1), "史",
                                    fill=theme.hist or theme.divine,
                                    font=font_badge)
                        fgen = r.get("fief_gen") or 0
                        if fgen:
                            dr.text((right - 10, bottom + 4), str(fgen),
                                    fill=theme.text_2, font=font_badge)

                    raw = bytearray()
                    rows = band.tobytes()
                    stride = tw * 3
                    # ★★ 2026-10-11（本条是"位置全错"的真凶）：条带带 **90px 重叠**
                    #   （`_OVERLAP`，为的是跨带的铭牌/文字两带各画一次、接缝不缺），
                    #   但喂进 PNG 流时**把重叠那 90 行也重复写了一遍** ⇒ 每过一条带，
                    #   画面就往下多走 90 行 ⇒ **整图被纵向拉长 1.225 倍、且随条带累积
                    #   错位**（实测：布局 y=2123 的卡片跑到流里的 y≈2573；底部还超出
                    #   IHDR 声明的高度被丢掉）。按 `Y()` 画的图元全被这一条带偏，
                    #   这也是"按坐标去图上找东西找不到"的原因。
                    #   ⇒ 第 2 条带起**跳过开头 `_OVERLAP` 行**（那段上一带已经写过，
                    #     且写在同一位置），拼起来才与布局坐标 1:1 对齐。
                    _skip = 0 if bi == 0 else min(_OVERLAP, band.height)
                    for ry in range(_skip, band.height):
                        raw += b"\x00"
                        raw += rows[ry * stride:(ry + 1) * stride]
                    sp.feed(raw)
                    done += 1
                    if on_progress:
                        on_progress(done, total)
            finally:
                sp.close()
            files.append((fp, tw, th))

    if pdf:
        try:
            pdf_path = os.path.join(outdir, f"{book}_代际_{stamp}.pdf")
            tiles_to_pdf(files, pdf_path)
        except Exception as e:
            print(f"PDF 拼装失败（PNG 已生成）: {e}")
            pdf_path = None
    if pdf_only and pdf_path:
        # ★ 2026-10-11 使用者：「**只需要 1 个文件即可，分片的 png 自己删除**」
        import shutil as _sh
        try:
            _sh.rmtree(png_dir)
            print("  （中间分块已随临时目录删掉，只留 PDF）")
        except OSError as e:
            print(f"  （临时分块目录删除失败，可手动删 {png_dir}：{e}）")
        files = []
    return files, pdf_path


def main():
    ap = argparse.ArgumentParser(description="整块家谱 PNG 离线渲染（分块+PDF）")
    ap.add_argument("book", help="谱牒名，如 全史存档")
    ap.add_argument("--scale", type=float, default=DEFAULT_GEN_SCALE)
    ap.add_argument("--tile", type=int, default=9000)
    ap.add_argument("--outdir", default="导出画布")
    # ★ 2026-10-11 使用者：「只需要 1 个文件即可，分片的 png 自己删除」
    ap.add_argument("--pdf-only", action="store_true",
                    help="只留 PDF，拼完自动删掉中间分块 PNG")
    # ★ 2026-10-11 使用者：「感情拼接你全给我**竖着拼接 pdf** 了……那张 png 是**一整张画布**」
    #   ⇒ 加 `--single`：**不切块**，出**一整张画布**的 PNG（= `--tile` 设成大于画布）。
    #   同时**不生成 PDF** —— 整张画布 197808×29232 px，做单页 PDF 要把它整幅读进内存
    #   （≈17 GB）必 OOM；而分块多页 PDF 在阅读器里就是**竖着堆**，正是他不想要的。
    ap.add_argument("--single", action="store_true",
                    help="整张画布一张 PNG（不切块、不出 PDF）")
    # ★ 2026-10-11 使用者：「最后**时间家谱也出个 png**」—— `render_timeline` 早就写好，
    #   只是 CLI 一直没有入口（以前多半是走界面导出）。
    ap.add_argument("--mode", choices=("gen", "timeline"), default="gen",
                    help="gen=代际家谱（默认）· timeline=时间家谱")
    a = ap.parse_args()
    if a.mode == "timeline":
        t0 = time.time()
        files = render_timeline(a.book, a.outdir,
                                on_progress=lambda d, t:
                                print(f"\r{d}/{t}", end=""))
        print("\n时间家谱：%s（%d×%d）· 耗时 %.0fs"
              % (os.path.basename(files[0][0]), files[0][1], files[0][2],
                 time.time() - t0))
        return
    if a.single:
        a.tile = 10 ** 9
    t0 = time.time()
    files, pdf = render_book(a.book, a.outdir, a.scale, a.tile,
                             pdf=not a.single,
                             pdf_only=a.pdf_only,
                             on_progress=lambda d, t:
                             print(f"\r{d}/{t}", end=""))
    dt = time.time() - t0
    print(f"\n{len(files)} 个分块 + PDF · 耗时 {dt:.0f}s")
    for f, w, h in files[:5]:
        print(f"  {os.path.basename(f)}（{w}×{h}）")
    if pdf:
        print(f"  PDF: {pdf}")


if __name__ == "__main__":
    main()
