@echo off
rem Restarts the backend and the public website (after a code change) but NOT the tunnel, which keeps running.
rem Close the old "Seqnce backend (public)" and "Seqnce website (public)" windows first, then run this.
rem The settings are the same as in start-public.cmd: keep the two in sync.
setlocal
cd /d "%~dp0.."
set "PUBLIC_APP=https://seqnce.orbitrixhq.com"
set "PUBLIC_API=https://seqnce-api.orbitrixhq.com"

start "Seqnce backend (public)" cmd /k "set AUTH_ENABLED=true&& set OPEN_SIGNUP=true&& set CORS_ORIGINS=%PUBLIC_APP%&& set MAX_UPLOAD_MB=95&& cd backend&& ..\tools\uv\uv.exe run uvicorn app.main:app --host 127.0.0.1 --port 8000"
start "Seqnce website (public)" cmd /k "cd frontend&& set NEXT_PUBLIC_API_URL=%PUBLIC_API%&& set NEXT_PUBLIC_MAX_UPLOAD_MB=95&& npm run build&& npm run start -- -p 3000"
echo Restarting the backend and rebuilding the website. Back in about a minute.
endlocal
