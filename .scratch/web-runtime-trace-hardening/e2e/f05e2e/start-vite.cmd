@echo off
cd /d "%~dp0..\..\..\..\web"
set VITE_API_PROXY=http://127.0.0.1:8471
call npm run dev -- --port 5273 --strictPort > "%~dp0vite.log" 2> "%~dp0vite.err"
