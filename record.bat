@echo off
REM 进入当前 .bat 所在目录
cd /d "%~dp0"

REM 执行 Python 脚本
python main.py

pause
