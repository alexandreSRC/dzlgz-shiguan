"""离屏渲染台 + 拖动底图瓦片（2026-10-05「拖动=拖图」改造）。

背景
----
T2 快照贴图只覆盖抓取瞬间的一屏，拖出一大步就露纸底。本模块提供两条腿：

1. `ShadowStage`：**影子画布** —— 一个 overrideredirect 的隐藏 Toplevel，
   常驻映射、贴在主窗口客户区原点、`lower` 到主窗口**正后方**（被完全
   盖住，使用者看不见），画完 `PrintWindow` 抓成位图。PrintWindow 对被
   遮挡窗口照样出图（wincap 实证）。
   ★ 常驻映射是铁律：withdraw → deiconify 的头一帧 DWM 表面未就绪，
     PrintWindow 会"成功"却给黑图（wincap 已加黑图重试 + 影子抓图禁用
     屏幕兜底，双保险）。

2. `TileRingMixin`：**瓦片环** —— 停手后把「当前视口 ± 1 视口」预渲染成
   半视口大小的位图瓦片缓存；下次拖动进快照模式时把缓存瓦片钉在快照图
   周围一起平移 —— ±1 屏范围内拖动就是纯拖图：不空白、不重画、无闪现。

缩放 / 换谱 / 筛选 / 编辑都会 `_tiles_bump()` 作废重铺。
"""
import time

import tkinter as tk

from . import wincap


class ShadowStage:
    """影子渲染台。整个进程一块（按主窗口缓存），常驻映射、用完不撤。"""

    def __init__(self, root):
        self._root = root
        self._top = tk.Toplevel(root)
        self._top.overrideredirect(True)
        self._top.withdraw()
        self._canvas = tk.Canvas(self._top, highlightthickness=0, bd=0,
                                 bg="#ffffff")
        self._canvas.pack(fill=tk.BOTH, expand=True)
        self._busy = False
        self._geom = None
        # ★ 2026-10-06 白块修复（使用者报「屏幕左上角一大块白，点一下就没了，
        #   动别的又出来」）：影子是**常驻映射**的纯白无边框窗，全靠"躲在主窗口
        #   正后方"隐形。主窗口一旦最小化/隐藏，`begin()` 里的 max(...,0) 会把影子
        #   钳到屏幕左上角 (0,0)，而最小化的主窗口盖不住它 —— 整块 #ffffff 露出来，
        #   正是那块白（实测白块高 571 ≈ 瓦片高 574、位置即主窗口客户区原点）。
        #   故：主窗口 Unmap（最小化/隐藏）时影子一并 withdraw；Map 时再恢复映射，
        #   并手动补一次首帧等待（否则 PrintWindow 给黑图）。
        #   实测（2026-10-06，mainloop 下）：iconify → <Unmap> 触发 → shadow_mapped=0；
        #   deiconify → shadow_mapped=1。注意用 update() 轮询**测不出**这个事件。
        try:
            root.bind("<Unmap>", self._on_root_unmap, add="+")
            root.bind("<Map>", self._on_root_map, add="+")
        except tk.TclError:
            pass

    def _on_root_unmap(self, ev=None):
        """主窗口最小化/隐藏 —— 影子必须一起收，否则纯白整块露在屏幕上。

        ⚠️ 必须确认事件来自**主窗口自身**：Tk 的 bindtags 里带着所属 toplevel 的
        名字标签，**子控件的 Map/Unmap 会一路冒泡到这里**。不判来源，切页签/建控件
        就会把影子反复收起→再映射，每次都要重走首帧等待（update+sleep 0.12s），
        家谱页就会「一个字一个字地加载」（使用者 2026-10-06 实测）。
        """
        if ev is not None and ev.widget is not self._root:
            return
        try:
            self._top.withdraw()
        except tk.TclError:
            pass

    def _on_root_map(self, ev=None):
        """主窗口恢复 —— 影子跟着回到主窗口正后方（首帧补一次等待）。"""
        if ev is not None and ev.widget is not self._root:
            return
        try:
            if self._geom is not None:
                self._top.deiconify()
                self._top.lower(self._root)
                self._top.update()
                time.sleep(0.06)
                self._top.update()
        except tk.TclError:
            pass

    @property
    def canvas(self):
        return self._canvas

    def begin(self, w, h, behind):
        """开渲染会话：影子画布调成 w×h，贴在 behind（主 Toplevel）客户区
        原点、压到它正后方。返回影子画布；会话必须以 snap() 收台。
        ★ 窗口常驻映射 —— 只在首次（或尺寸变了）才做 DWM 首帧等待。
        """
        if self._busy:
            raise RuntimeError("影子渲染台正在使用中")
        self._busy = True
        cv = self._canvas
        cv.config(width=w, height=h)
        try:
            # ★ 2026-10-06 白块修复：**不再 max(...,0)**。原来的钳制本意是"别让影子
            #   跑到屏幕外"，但主窗口最小化时 winfo_rootx ≈ -32000，钳制会把它丢到
            #   屏幕左上角 (0,0) 变成一块白（见 __init__ 注释）。跟随主窗口真实位置
            #   即可 —— 主窗口在哪影子就在哪，屏幕外也无所谓（反正被盖住）。
            x = behind.winfo_rootx()
            y = behind.winfo_rooty()
            geom = f"{w}x{h}+{x}+{y}"
            fresh = not self._top.winfo_ismapped()
            if geom != self._geom:
                self._top.geometry(geom)
                self._geom = geom
                fresh = True
            if fresh:
                self._top.deiconify()
                self._top.lower(behind)
                # ★ DWM 首帧等待：刚映射的窗口 PrintWindow 会给黑图
                self._top.update()
                time.sleep(0.06)
                self._top.update()
            else:
                self._top.lower(behind)
        except tk.TclError:
            pass
        cv.delete("all")
        return cv

    def snap(self):
        """PrintWindow 抓图 → (w, h, BGRA)，清空影子画布（**窗口不撤**）。

        ★ 禁用屏幕 BitBlt 兜底（allow_screen=False）：影子藏在主窗口后面，
          屏幕兜底只会抓到主窗口/别家内容 —— 黑图就重试，重试失败宁可
          抛错让这块瓦片下轮再铺。
        """
        cv = self._canvas
        try:
            return wincap.capture_widget_region(cv, allow_screen=False)
        finally:
            try:
                cv.delete("all")
            except tk.TclError:
                pass
            self._busy = False

    def abandon(self):
        try:
            self._canvas.delete("all")
        except tk.TclError:
            pass
        self._busy = False


_STAGE = {}


def get_stage(root):
    """取主窗口对应的渲染台（整个进程每窗口一块，懒建）。"""
    stage = _STAGE.get(root)
    if stage is None:
        stage = ShadowStage(root)
        _STAGE[root] = stage
    return stage


class TileRingMixin:
    """瓦片环（宿主=TreeView/TimelineView）。

    宿主需实现四个钩子：
      _tile_root()   -> 主 Toplevel（影子藏在它后面）
      _tile_grid()   -> (tw, th)   瓦片尺寸（半视口）
      _tile_region() -> 影子画布的 scrollregion 元组
      _tile_paint(cv, x0, y0, tw, th)   在影子画布上画一块瓦片
    """

    def _tiles_init(self):
        self._tiles = {}            # (col,row) -> PhotoImage（当前代）
        self._tile_gen = 0
        self._tile_queue = []       # 待预铺 (col,row)，近的在前
        self._tile_pump_job = None

    def _tiles_bump(self):
        """画面内容变了（缩放/换谱/筛选/编辑/改尺寸）—— 瓦片全部作废。"""
        self._tile_gen += 1
        self._tiles.clear()
        self._tile_queue = []
        if getattr(self, "_tile_pump_job", None) is not None:
            try:
                self.canvas.after_cancel(self._tile_pump_job)
            except Exception:
                pass
            self._tile_pump_job = None

    def _tiles_check_lay(self):
        """保险：布局对象被整体换掉（换谱/筛选重算）而没走 rerender 时，
        也在挂载/排环前把旧瓦片作废。"""
        lay_id = id(getattr(self, "lay", None))
        if lay_id != getattr(self, "_tile_lay_id", None):
            self._tile_lay_id = lay_id
            self._tiles_bump()

    def _tile_attach(self, c, vx0, vy0, vw, vh):
        """拖动开始：把缓存里落在「视口 ± 1 视口」的瓦片钉进画布。
        必须在创建快照图**之前**调（快照图后建、压在最上层）。"""
        self._tiles_check_lay()
        tw, th = self._tile_grid()
        ex0, ey0 = vx0 - vw, vy0 - vh
        ex1, ey1 = vx0 + 2 * vw, vy0 + 2 * vh
        for (col, row), photo in list(self._tiles.items()):
            x0, y0 = col * tw, row * th
            if x0 + tw < ex0 or x0 > ex1 or y0 + th < ey0 or y0 > ey1:
                continue
            c.create_image(x0, y0, image=photo, anchor="nw", tags=("tile",))

    def _tile_enqueue_ring(self):
        """把「当前视口 ± 1 视口」里没缓存的瓦片排进预铺队列（近的先铺）。"""
        self._tiles_check_lay()
        if getattr(self, "lay", None) is None or not getattr(self.lay, "positions", None):
            return
        tw, th = self._tile_grid()
        c = self.canvas
        vx0, vy0 = c.canvasx(0), c.canvasy(0)
        vw = max(c.winfo_width(), 50)
        vh = max(c.winfo_height(), 50)
        col0 = int((vx0 - vw) // tw)
        col1 = int((vx0 + 2 * vw) // tw)
        row0 = int((vy0 - vh) // th)
        row1 = int((vy0 + 2 * vh) // th)
        cx, cy = vx0 + vw / 2.0, vy0 + vh / 2.0
        want = []
        for col in range(col0, col1 + 1):
            for row in range(row0, row1 + 1):
                if (col, row) in self._tiles:
                    continue
                mx, my = col * tw + tw / 2.0, row * th + th / 2.0
                want.append(((mx - cx) ** 2 + (my - cy) ** 2, col, row))
        want.sort()
        self._tile_queue = [(col, row) for _d, col, row in want]

    def _tile_prefetch_soon(self, delay=250):
        if getattr(self, "_tile_pump_job", None) is None:
            self._tile_pump_job = self.canvas.after(delay, self._tile_pump)

    def _tile_pump(self):
        """预铺泵：空闲时每 25ms 铺一块瓦片（每块 ≈70ms，肉眼无感）。"""
        self._tile_pump_job = None
        if self._grab_id is not None or getattr(self, "_grab_busy", False):
            self._tile_queue = []
            return                       # 拖动优先，松手后重新排
        if not self._tile_queue:
            return
        if not self.canvas.winfo_ismapped():
            self._tile_pump_soon(500)    # 本页暂未显示 —— 留队稍后再试
            return                       #   （不抢渲染台；切回来接着铺）
        col, row = self._tile_queue.pop(0)
        self._render_tile(col, row)
        if self._tile_queue:
            self._tile_pump_soon()

    def _tile_pump_soon(self, delay=25):
        if getattr(self, "_tile_pump_job", None) is None:
            self._tile_pump_job = self.canvas.after(delay, self._tile_pump)

    def _render_tile(self, col, row):
        key = (col, row)
        if key in self._tiles:
            return
        try:
            from PIL import Image, ImageTk
            tw, th = self._tile_grid()
            x0, y0 = col * tw, row * th
            stage = get_stage(self._tile_root())
            cv = stage.begin(tw, th, self._tile_root())
            sr = self._tile_region()
            cv.config(scrollregion=sr)
            w_span = max(sr[2] - sr[0], 1)
            h_span = max(sr[3] - sr[1], 1)
            cv.xview_moveto(min(1.0, max(0.0, (x0 - sr[0]) / w_span)))
            cv.yview_moveto(min(1.0, max(0.0, (y0 - sr[1]) / h_span)))
            self._tile_paint(cv, x0, y0, tw, th)
            w, h, bgra = stage.snap()
            img = Image.frombuffer("RGBA", (w, h), bgra, "raw", "BGRA").convert("RGB")
            self._tiles[key] = ImageTk.PhotoImage(img)
            while len(self._tiles) > 40:          # 上限保护（≈半视口×40）
                self._tiles.pop(next(iter(self._tiles)))
        except tk.TclError:
            raise                                  # 解释器没了，随它去
        except Exception:
            pass                                   # 单块失败不追命，下轮再铺
