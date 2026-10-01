@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
echo.
echo   ============================================================
echo    虚接复核  ·  大周列国志 · 史馆
echo   ============================================================
echo.
echo    浏览器会自动打开。选完后点「提交复核结果」。
echo    平板同一 WiFi 下用上面显示的「平板」地址。
echo.
echo    关闭这个窗口即停止服务。
echo.
echo   ============================================================
echo.
start "" http://127.0.0.1:8802/
python tools\review_server.py 8802
pause
