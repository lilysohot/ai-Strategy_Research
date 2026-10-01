@echo off
cd /d "%~dp0..\..\..\.."
.venv\Scripts\python.exe -m deploy.huggingface.mock_llm --port 8018 --no-auth > "%~dp0mock.log" 2> "%~dp0mock.err"
