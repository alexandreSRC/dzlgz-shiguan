@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo == 合并全史册 + 重建推定层（一条龙）==
python tools\merge_books.py --apply --with-guess
pause
