# -*- coding: utf-8 -*-
"""Windows 显示缩放感知（DPI awareness）—— 2026-09-26 新增。

★ 背景：使用者的 Windows 显示缩放是 **150%**，而本程序一直没声明 DPI 感知
  （旧备份 tools/shot.py 还引用着 make_dpi_aware，重构时丢了）——于是
  Windows 把整窗**位图拉伸** 1.5 倍：文字发虚、截图模糊。
  使用者裁定：「你没法自动检测吗？先修 DPI 再说字体是否需要更换。」

用法（顺序**不可倒**）：
    import tkinter as tk
    from app import dpi
    dpi.init()          # ← 必须在 tk.Tk() **和所有 app.* 导入**之前
    root = tk.Tk()
    ...
    theme.py / timeline.py / popcard.py 等模块级像素常量都走 dpi.px()，
    它们被导入时 SCALE 必须已就位 —— 所以 main.py 的导入区第一件事就是
    dpi.init()。探针/工具脚本直接 import app.xxx 不经 main.py 时 SCALE=1.0，
    全部常量原样 —— 与旧行为逐字节一致。

三件事：
    init()      进程级声明感知（shcore 失败退化 user32；都失败就维持现状）
    SCALE       实测缩放系数（96dpi=1.0、125%=1.25、150%=1.5）
    px(n)       逻辑像素 → 物理像素。100% 时原样返回，**一行不差等于旧行为**

感知之后 Tk 的**点阵字**（font size 为正数 = pt）会按 `tk scaling` 自动放大
（Tk 自行读系统 DPI），文字即锐利；所有**写死的像素尺寸**（栏高/侧栏宽/
节点框/卡片宽…）若不跟着放大就会「字大框小」—— 各模块用 px() 换算。
"""
import ctypes
import sys

SCALE = 1.0            # 实测缩放系数；init() 后才有意义
_done = False


def init():
    """声明 DPI 感知并测量缩放系数。幂等；非 Windows / 失败一律静默退化为 1.0。"""
    global SCALE, _done
    if _done:
        return SCALE
    _done = True
    if sys.platform != "win32":
        return SCALE
    # PER_MONITOR_AWARE_V2 → PER_MONITOR_AWARE → SYSTEM_AWARE → 旧默认。
    # Tk 8.6 处理不了 WM_DPICHANGED（跨屏改缩放不会重排），单窗口桌面程序
    # 用 SYSTEM 级最稳：主屏锐利、拖到异缩放屏由 Windows 位图缩放（旧行为）。
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass                      # 拿不到感知 = 维持旧行为，不炸
    SCALE = _measure()
    return SCALE


def _measure():
    """主屏垂直 DPI / 96。感知声明成功后 LOGPIXELSY 才会报真实值。"""
    try:
        user32 = ctypes.windll.user32
        hdc = user32.GetDC(0)
        try:
            dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)   # LOGPIXELSY
        finally:
            user32.ReleaseDC(0, hdc)
        if dpi and dpi > 0:
            return max(1.0, dpi / 96.0)
    except Exception:
        pass
    return 1.0


def px(n):
    """逻辑像素 → 物理像素（100% 时原样返回；保证 ≥1）。"""
    if SCALE == 1.0:
        return n
    return max(1, int(round(n * SCALE)))


def workarea():
    """主屏工作区（去掉任务栏）的物理像素 (宽, 高)；取不到返回 (0, 0)。"""
    if sys.platform != "win32":
        return 0, 0
    try:
        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
        rect = RECT()
        SPI_GETWORKAREA = 0x0030
        if ctypes.windll.user32.SystemParametersInfoW(
                SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
            return rect.right - rect.left, rect.bottom - rect.top
    except Exception:
        pass
    return 0, 0
