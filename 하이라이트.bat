@echo off
chcp 65001 >nul
cd /d "%~dp0"

"C:\Users\seok\AppData\Local\Programs\Python\Python312\python.exe" "make_highlights.py" %*

pause
