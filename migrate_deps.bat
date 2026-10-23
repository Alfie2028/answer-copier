@echo off
chcp 65001 >nul
rem 一键迁移依赖：从原项目 D:\Python项目\fuck-educoder 拷贝 educoder_reminder 依赖模块到本目录。
set "SRC=D:\Python项目\fuck-educoder\educoder_reminder"
set "DST=%~dp0educoder_reminder"
if not exist "%SRC%" (
  echo [错误] 找不到源码目录 %SRC%
  pause
  exit /b 1
)
if not exist "%DST%" mkdir "%DST%"
for %%F in (auth.py client.py errors.py login.py export.py submit.py _oslock.py) do (
  if exist "%SRC%\%%F" copy /y "%SRC%\%%F" "%DST%\%%F" >nul
)
if not exist "%DST%\__init__.py" type nul > "%DST%\__init__.py"
echo.
echo 已把 educoder_reminder 依赖模块拷贝到本目录，可运行 answer_copier.bat 使用。
pause
