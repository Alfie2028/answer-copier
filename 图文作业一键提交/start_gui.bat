@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 未找到 python 命令，请先安装 Python 3 并加入 PATH。
  pause
  exit /b
)
echo 正在启动 头歌图文作业 一键提交/拉取 工具...
start "" python "common_homework_gui.py"
