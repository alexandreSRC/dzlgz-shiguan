"""窗口/控件抓图与 PNG 导出（纯标准库，不引入 Pillow）。

用 Windows 的 PrintWindow 把控件内容渲染到内存位图，
再用 zlib 手写 PNG，避免为"导出图片"这一个功能增加打包体积。
"""
import ctypes
import logging
import struct
import zlib
from ctypes import wintypes

logger = logging.getLogger(__name__)

_user32 = ctypes.windll.user32
_gdi32 = ctypes.windll.gdi32

PW_CLIENTONLY = 1
SRCCOPY = 0x00CC0020


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


GA_ROOT = 2
PW_RENDERFULLCONTENT = 0x00000002


def _looks_black(bgra, step=997):
    """整张图是否**全是黑的**（采样判断，够快也够稳）。

    ★ 2026-09-28 使用者报「导出图片一直不能用，导出来的都是黑图」——
      真因就是 `PrintWindow` 对 Tk 窗口**返回 1（成功）却画了全黑**：
      原来的 fallback 只在"返回 0"时触发，所以永远走不到，导出即黑图。
      现在抓完**先验一次**，全黑就换另一条路重抓。
    """
    n = len(bgra)
    if n < 8:
        return True
    for i in range(0, n - 4, step * 4):
        # BGRA：只要有一个通道 > 8 就算"有内容"
        if bgra[i] > 8 or bgra[i + 1] > 8 or bgra[i + 2] > 8:
            return False
    return True


def _grab_screen(target, memdc, w, h):
    """从**屏幕**把 target 客户区那一块位块传送过来（Tk 用 GDI 绘制，这条路最稳）。"""
    pt = wintypes.POINT(0, 0)
    if not _user32.ClientToScreen(target, ctypes.byref(pt)):
        return False
    screen = _user32.GetDC(0)
    try:
        return bool(_gdi32.BitBlt(memdc, 0, 0, w, h, screen, pt.x, pt.y, SRCCOPY))
    finally:
        _user32.ReleaseDC(0, screen)


def _grab_printwindow(target, memdc, w, h):
    """PrintWindow 三条路：
    ① **PW_CLIENTONLY|PW_RENDERFULLCONTENT**（Win8.1+）：只画客户区且
       内容完整 —— 坐标系与 GetClientRect 一致，整块导出的裁剪靠它；
    ② PW_RENDERFULLCONTENT：连标题栏/边框一起画（坐标系是窗外框）；
    ③ 老 PW_CLIENTONLY。
    """
    try:
        if _user32.PrintWindow(target, memdc,
                               PW_CLIENTONLY | PW_RENDERFULLCONTENT):
            return True
    except Exception:
        pass
    try:
        if _user32.PrintWindow(target, memdc, PW_RENDERFULLCONTENT):
            return True
    except Exception:
        pass
    try:
        return bool(_user32.PrintWindow(target, memdc, PW_CLIENTONLY))
    except Exception:
        return False


def capture_widget(widget, prefer_printwindow=False, size=None):
    """抓取控件客户区，返回 (宽, 高, BGRA 字节)。

    `size=(w, h)`：显式指定位图尺寸 —— 最小化窗口的 GetClientRect 是 0×0，
    但 PrintWindow(PW_RENDERFULLCONTENT) 仍能按还原尺寸渲染（后台导出用）。

    ★ 2026-09-28 重写取图顺序（修「导出黑图」）：
      ① 目标窗口取 **顶层**（`GA_ROOT`）—— Tk 的子控件大多没有真 HWND，
         `GetParent` 拿到的中间层可能根本没有客户区；
      ② **先屏幕 BitBlt**（最可靠），失败或**全黑**再试 `PrintWindow`；
      ③ 两条都黑就抛错，让调用方给出明确提示，而不是默默导出一张黑图。
    ★ 2026-09-27 加 `prefer_printwindow`（整块画布导出专用）：屏幕 BitBlt
      抓的是**屏幕上最上层**的画面 —— 史馆被别的窗口（比如开着的游戏）
      盖住时会把别人截进来（实测截到了游戏地图）。PrintWindow
      (PW_RENDERFULLCONTENT) 让窗口**自己渲染进缓冲**，被遮挡也正确，
      导出拼接一律优先走它。
    """
    widget.update_idletasks()
    widget.update()
    hwnd = widget.winfo_id()
    target = _user32.GetAncestor(hwnd, GA_ROOT) or hwnd

    if size is not None:
        w, h = int(size[0]), int(size[1])
    else:
        rect = wintypes.RECT()
        _user32.GetClientRect(target, ctypes.byref(rect))
        w, h = rect.right, rect.bottom
    if w <= 0 or h <= 0:
        raise RuntimeError(f"控件尺寸异常: {w}x{h}")

    hdc = _user32.GetDC(target)
    memdc = _gdi32.CreateCompatibleDC(hdc)
    bitmap = _gdi32.CreateCompatibleBitmap(hdc, w, h)
    _gdi32.SelectObject(memdc, bitmap)
    try:
        bi = _BITMAPINFOHEADER()
        bi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bi.biWidth = w
        bi.biHeight = -h          # 负高度 = 自上而下
        bi.biPlanes = 1
        bi.biBitCount = 32
        bi.biCompression = 0

        def _read():
            buf = ctypes.create_string_buffer(w * h * 4)
            _gdi32.GetDIBits(memdc, bitmap, 0, h, buf, ctypes.byref(bi), 0)
            return buf.raw

        data = b""
        grabs = ((_grab_printwindow, _grab_screen) if prefer_printwindow
                 else (_grab_screen, _grab_printwindow))
        for grab in grabs:
            try:
                if not grab(target, memdc, w, h):
                    continue
            except Exception as e:                     # noqa: BLE001
                logger.debug(f"抓图方式失败（继续试下一种）: {e}")
                continue
            data = _read()
            if not _looks_black(data):
                return w, h, data
        if not data:
            raise RuntimeError("两种抓图方式都失败了")
        raise RuntimeError("抓到的画面是整张黑图 —— 请把窗口露出来"
                           "（别被其他窗口完全盖住）再导出")
    finally:
        _gdi32.DeleteObject(bitmap)
        _gdi32.DeleteDC(memdc)
        _user32.ReleaseDC(target, hdc)


def capture_widget_region(widget, allow_screen=True):
    """抓取 widget **自身**客户区（T2 拖动快照专用），返回 (宽, 高, BGRA)。

    ★ 2026-10-05 修「拖动时画布左半出现幽灵菜单栏」：T2 快照此前误用
      capture_widget —— 它按 GA_ROOT 抓的是**整个程序窗口**客户区，整窗
      截图被原样贴进画布，左侧菜单栏/顶栏整块复制了进来。

    取图顺序（与 capture_widget 相反，**PrintWindow 优先**）：
    ① PrintWindow(widget 自身 HWND, PW_CLIENTONLY|PW_RENDERFULLCONTENT)
       —— 实测 Tk 子控件**有**真 HWND 且 PrintWindow 渲染正确；
    ② `allow_screen=True` 时屏幕 BitBlt 兜底（史馆在最上层时才准）；
       **False 时禁用** —— 影子渲染台等场景，屏幕兜底会抓到盖在别处的
       别家内容（主窗口/游戏），宁可报错重试。

    ①若出全黑（★ 刚映射的窗口 DWM 表面未就绪，PrintWindow 会"成功"却
    给黑图），稍候重试一次再判。
    """
    import time as _time
    widget.update_idletasks()
    # ★ update() 必须保留：实测 PrintWindow 抓的是**已落屏**内容，画布若还有
    #   未画完的一帧（刚 create 完 / 刚滚动完），抓到的就是黑图。它清空事件
    #   队列的副作用（拖动 Motion 重入 _on_drag）由调用方 _grab_busy 旗标挡住
    #   —— 重入的 _grab_start 直接短路，嵌套的 xview_moveto 也无害（抓图像
    #   素与锚点都取自 update 之后的同一视口状态）。
    widget.update()
    hwnd = widget.winfo_id()
    rect = wintypes.RECT()
    _user32.GetClientRect(hwnd, ctypes.byref(rect))
    w, h = rect.right, rect.bottom
    if w <= 0 or h <= 0:
        raise RuntimeError(f"控件尺寸异常: {w}x{h}")

    hdc = _user32.GetDC(hwnd)
    memdc = _gdi32.CreateCompatibleDC(hdc)
    bitmap = _gdi32.CreateCompatibleBitmap(hdc, w, h)
    _gdi32.SelectObject(memdc, bitmap)
    try:
        bi = _BITMAPINFOHEADER()
        bi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bi.biWidth = w
        bi.biHeight = -h          # 负高度 = 自上而下
        bi.biPlanes = 1
        bi.biBitCount = 32
        bi.biCompression = 0

        def _read():
            buf = ctypes.create_string_buffer(w * h * 4)
            _gdi32.GetDIBits(memdc, bitmap, 0, h, buf, ctypes.byref(bi), 0)
            return buf.raw

        def _try_pw():
            try:
                return bool(_user32.PrintWindow(
                    hwnd, memdc, PW_CLIENTONLY | PW_RENDERFULLCONTENT))
            except Exception:
                return False

        data = b""
        # ① PrintWindow 抓子控件自身（不受遮挡影响）；黑图稍候重试一次
        if _try_pw():
            data = _read()
            if not _looks_black(data):
                return w, h, data
            _time.sleep(0.05)
            widget.update_idletasks()
            if _try_pw():
                data = _read()
                if not _looks_black(data):
                    return w, h, data
        if not allow_screen:
            raise RuntimeError("PrintWindow 出图失败/全黑（已禁用屏幕兜底）")
        # ② 屏幕 BitBlt 兜底
        pt = wintypes.POINT(0, 0)
        if _user32.ClientToScreen(hwnd, ctypes.byref(pt)):
            screen = _user32.GetDC(0)
            try:
                ok = bool(_gdi32.BitBlt(memdc, 0, 0, w, h, screen,
                                        pt.x, pt.y, SRCCOPY))
            finally:
                _user32.ReleaseDC(0, screen)
            if ok:
                data = _read()
                if not _looks_black(data):
                    return w, h, data
        raise RuntimeError("画布区域抓图失败/全黑 —— 走降级路径")
    finally:
        _gdi32.DeleteObject(bitmap)
        _gdi32.DeleteDC(memdc)
        _user32.ReleaseDC(hwnd, hdc)


def _chunk(tag, data):
    return (struct.pack(">I", len(data)) + tag + data +
            struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def save_png(path, width, height, bgra):
    """把 BGRA 像素写成 PNG（真彩色、无 alpha）。"""
    stride = width * 4
    raw = bytearray()
    for y in range(height):
        raw.append(0)                      # 每行的 filter type
        row = bgra[y * stride:(y + 1) * stride]
        # BGRA → RGB
        for x in range(0, len(row), 4):
            raw += bytes((row[x + 2], row[x + 1], row[x]))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(_chunk(b"IHDR", ihdr))
        f.write(_chunk(b"IDAT", zlib.compress(bytes(raw), 6)))
        f.write(_chunk(b"IEND", b""))


def client_offset_in_window(widget):
    """PrintWindow(PW_RENDERFULLCONTENT) 会把**非客户区**（标题栏/边框）也画
    进缓冲 —— 返回客户区原点在窗面缓冲里的偏移 (off_x, off_y)，裁剪时用。"""
    hwnd = widget.winfo_id()
    target = _user32.GetAncestor(hwnd, GA_ROOT) or hwnd
    pt = wintypes.POINT()
    _user32.ClientToScreen(target, ctypes.byref(pt))
    wr = wintypes.RECT()
    _user32.GetWindowRect(target, ctypes.byref(wr))
    return (pt.x - wr.left, pt.y - wr.top)


def real_visible_size(img, rel_x, rel_y, vw, vh):
    """从整窗截图里**实测**画布真实可见宽高。

    ★ 2026-09-27：Tk 的 `winfo_width` 与实际映射宽度有 ~20px 漂移，
      超出的部分在窗面上是**黑底**（整块导出的接缝黑边实证）。
      从右/下往左扫多行多列，连续黑（RGB 和 < 30）即到边界。
    """
    px = img.load()
    y_lo, y_hi = rel_y + 10, min(rel_y + vh, img.height) - 10
    x_lo, x_hi = rel_x + 10, min(rel_x + vw, img.width) - 10
    if y_hi <= y_lo or x_hi <= x_lo:
        return vw, vh
    # ★ 2026-10-02：深色画布防御 —— 画布中心若本身是深色（墨夜类主题/
    #   黑屏），「从右往左找黑边」会把内容误判成边。只有中心是浅色时
    #   才做黑边收缩。
    cx, cy = rel_x + vw // 2, rel_y + vh // 2
    if sum(px[cx, cy][:3]) < 360:
        return vw, vh

    def col_black(x):
        return all(sum(px[x, y][:3]) < 30
                   for y in range(y_lo, y_hi, max(1, (y_hi - y_lo) // 40)))

    def row_black(y):
        return all(sum(px[x, y][:3]) < 30
                   for x in range(x_lo, x_hi, max(1, (x_hi - x_lo) // 60)))

    vis_w = min(vw, img.width - rel_x)
    while vis_w > 50 and col_black(rel_x + vis_w - 1):
        vis_w -= 1
    vis_h = min(vh, img.height - rel_y)
    while vis_h > 50 and row_black(rel_y + vis_h - 1):
        vis_h -= 1
    return vis_w, vis_h


def capture_widget_to_png(widget, path):
    """抓图并直接落盘为 PNG，返回 (宽, 高)。"""
    w, h, bgra = capture_widget(widget)
    save_png(path, w, h, bgra)
    logger.info(f"导出图片: {path} ({w}x{h})")
    return w, h
