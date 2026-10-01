# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 —— 大周列国志 · 史馆。

用法（在项目根目录）：
    pyinstaller Shiguan.spec --noconfirm

产物：`dist/Shiguan.exe`（单文件）—— 再拷到项目根目录即可。

★ 为什么 exe 用**英文名**（2026-09-30 使用者点名改）：
  · 原名 `史馆.exe` 让命令行排查到处受限 —— `tasklist`/`taskkill` 按中文名
    过滤会因 GBK/UTF-8 编码错乱拿不到 PID（实测 `进程 PID: []`），
    `start`、脚本里的匹配也都不稳。
  · 改成 ASCII 后，`tasklist /FI "IMAGENAME eq Shiguan.exe"` 一路畅通。

★ 三条硬约定（都是踩过的坑）：
  1. **EXE 必须放在项目根目录**（`saves/`、`config.json` 的旁边）。
     打包后 `app/contract.py` 的 `_base_dir()` 走 `sys.frozen` 分支，
     基准目录 = **exe 所在目录** ⇒ exe 放哪，`saves/` 就在哪。
     放到别处 = 读不到你现有的谱牒档（会看到空列表）。
  2. **`console=False`**：GUI 程序，别弹黑框。
  3. **排除大库**：numpy / matplotlib / pandas / scipy 等本项目用不到，
     不排会把体积从 ~40MB 抬到 200MB+。

⚠️ 显示名（窗口标题、任务栏）仍是中文「大周列国志 · 史馆」——
   改的只是**磁盘文件名**，界面上一个字都没变。
"""
import os

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[os.path.abspath('.')],
    binaries=[],
    # 窗口图标要在运行时读 —— 单文件模式下必须随包带上
    datas=[('app_icon.ico', '.')],
    hiddenimports=[
        # PIL + tkinter 的老坑：不显式声明，打包后 ImageTk 会 ImportError
        'PIL._tkinter_finder',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 本项目没用到，排掉能省一半体积
    excludes=[
        'numpy', 'matplotlib', 'pandas', 'scipy', 'sympy',
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
        'IPython', 'jupyter', 'notebook', 'pytest',
        'setuptools', 'pip', 'wheel',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Shiguan',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,             # 不压：UPX 常被杀软误报，且对 tkinter 收益小
    upx_exclude=[],
    runtime_tmpdir=None,   # 默认解到 %TEMP%\_MEIxxxx，退出即清
    console=False,         # GUI —— 不要黑框
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='app_icon.ico',
)
