@echo off
REM ─────────────────────────────────────────────────────────────
REM 一键跑批（Windows 双击运行）
REM
REM 作用：把 data\corpus\ 里的新研报入库，并留下台账。
REM 原理：调用 WSL 默认发行版里的 scripts/ingest-corpus.sh。
REM
REM ⚠️ 前提：
REM   1. 已安装 WSL，且**默认发行版**就是这个项目所在的发行版
REM      （若不是，把下面的 wsl 改成：wsl -d <发行版名>）
REM   2. 项目位于该发行版的 ~/FrontierAgent（若路径不同，改下面的 cd 路径）
REM ─────────────────────────────────────────────────────────────

echo.
echo [1/1] 正在跑批，请稍候...
echo.

wsl -e bash -lc "cd ~/FrontierAgent && bash scripts/ingest-corpus.sh"
set CODE=%ERRORLEVEL%

echo.
echo ============================================================
if "%CODE%"=="0" echo   完成：全部成功
if "%CODE%"=="1" echo   完成，但有失败/空文档 —— 上面已列出，或运行：
if "%CODE%"=="1" echo     wsl -e bash -lc "cd ~/FrontierAgent ^&^& uv run python -m plugins.corpus.service failures"
if "%CODE%"=="2" echo   失败：跑批没跑起来（数据库不可达？已有跑批在跑？）
echo   退出码 = %CODE%
echo ============================================================
echo.
pause
