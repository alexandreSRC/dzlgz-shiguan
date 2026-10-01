@echo off
rem ============================================================
rem  大周列国志 · 史馆  ——  启动器
rem  本文件必须存为 GBK 无 BOM，否则 cmd 读到中文会乱码。
rem  找 Python 的逻辑只在本文件里维护一份，Start.vbs 只负责隐藏黑框。
rem ============================================================
setlocal
cd /d "%~dp0"

set "PY="

rem ---- 候选 1：托管 Python（若已装 tkinter）----
if exist "%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe" (
    "%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe" -c "import tkinter" >nul 2>&1
    if not errorlevel 1 set "PY=%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe"
)

rem ---- 候选 2：系统 Python 3.13 ----
if not defined PY if exist "C:\Program Files\Python313\python.exe" (
    "C:\Program Files\Python313\python.exe" -c "import tkinter" >nul 2>&1
    if not errorlevel 1 set "PY=C:\Program Files\Python313\python.exe"
)

rem ---- 候选 3：PATH 里的 py 启动器 ----
if not defined PY (
    py -3 -c "import tkinter" >nul 2>&1
    if not errorlevel 1 set "PY=py -3"
)

rem ---- 候选 4：PATH 里的 python ----
if not defined PY (
    python -c "import tkinter" >nul 2>&1
    if not errorlevel 1 set "PY=python"
)

if not defined PY goto nopython

%PY% "main.py" %*
if errorlevel 1 goto crashed
goto end

:nopython
echo.
echo   ============================================================
echo     找不到能用的 Python（需要带 tkinter 的 Python 3.10+）
echo   ============================================================
echo.
echo   已经找过这几个地方：
echo     * %%USERPROFILE%%\.workbuddy\binaries\python\versions\3.13.12\python.exe
echo     * C:\Program Files\Python313\python.exe
echo     * PATH 里的 py -3  /  python
echo.
echo   怎么修：
echo     1. 装一个 Python 3.12 或 3.13（安装时勾选 tcl/tk）
echo        下载：https://www.python.org/downloads/
echo     2. 记住安装路径，然后手动跑：
echo        "你的python.exe" main.py
echo.
echo   注意：本程序是 Tkinter 桌面程序，装完 Python 直接跑 main.py 也行。
echo.
pause
goto end

:crashed
echo.
echo   ============================================================
echo     程序启动后异常退出（上面有报错信息）
echo   ============================================================
echo.
echo   详细日志写在：shiguan.log
echo.
pause

:end
endlocal
