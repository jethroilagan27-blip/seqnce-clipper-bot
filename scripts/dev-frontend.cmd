@echo off
rem Starts the Next.js frontend on http://localhost:3000
cd /d "%~dp0..\frontend"
call npm run dev -- --port 3000 %*
