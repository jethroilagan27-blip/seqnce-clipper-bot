@echo off
rem Starts the FastAPI backend on http://127.0.0.1:8000
cd /d "%~dp0..\backend"
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 %*
