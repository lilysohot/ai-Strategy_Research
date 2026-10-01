@echo off
cd /d "%~dp0..\..\..\.."
set "SERVER_DATABASE_URL=sqlite+aiosqlite:///C:/Users/Administrator/AppData/Local/Temp/f05e2e/e2e.db"
set "SERVER_RUNS_ROOT=C:/Users/Administrator/AppData/Local/Temp/f05e2e/runs"
set SERVER_MASTER_KEY=f05e2e-master-key
set SERVER_JWT_SECRET=f05e2e-jwt-secret
set SERVER_DEBUG=1
set OPENAI_BASE_URL=http://127.0.0.1:8018/v1
set OPENAI_API_KEY=mock-key
set OPENAI_MODEL=mock-frontier-model
.venv\Scripts\python.exe -m uvicorn server.app:app --host 127.0.0.1 --port 8471 > "%~dp0api.log" 2> "%~dp0api.err"
