@echo off
chcp 65001 >nul
title 史馆 · 平板数据服务
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
echo.
echo   启动平板数据服务...（首次取数约 15 秒，请稍等）
echo   平板上的 App 填服务里打印的那个地址。
echo.
python tools\pad_server.py %1
echo.
echo   服务已退出。
pause
