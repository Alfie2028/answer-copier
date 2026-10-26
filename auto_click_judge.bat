@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul && (
  py -3 "%~dp0auto_click_judge_gui.py"
  pause
  exit /b
)
where python >nul 2>nul && (
  python "%~dp0auto_click_judge_gui.py"
  pause
  exit /b
)
echo [错误] 未找到 Python，请先安装 Python 3.9+ 并加入 PATH（或勾选 py launcher）。
pause
