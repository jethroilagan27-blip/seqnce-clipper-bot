@echo off
rem Starts Seqnce for OTHER PEOPLE: accounts ON, the production website, and the Cloudflare Tunnel.
rem Every setting below applies to these windows only, so scripts\dev-backend.cmd and dev-frontend.cmd keep
rem working exactly as before (no login, no limits). Close the three windows to stop sharing.
rem First-time setup: docs\DEPLOY.md
setlocal
cd /d "%~dp0.."

set "PUBLIC_APP=https://seqnce.orbitrixhq.com"
set "PUBLIC_API=https://seqnce-api.orbitrixhq.com"
set "TOKEN_FILE=tools\cloudflared\token.txt"
set "CLOUDFLARED=tools\cloudflared\cloudflared.exe"

if not exist "%CLOUDFLARED%" echo cloudflared is missing: see docs\DEPLOY.md step 3. & pause & exit /b 1
if not exist "%TOKEN_FILE%" echo The tunnel token file is missing: see docs\DEPLOY.md step 2. & pause & exit /b 1

echo Make sure the normal dev servers (scripts\dev-*.cmd, ports 3000 and 8000) are stopped first.
echo.

rem 1) backend: accounts on, only the public site may call it, uploads kept under Cloudflare's 100 MB limit
start "Seqnce backend (public)" cmd /k "set AUTH_ENABLED=true&& set CORS_ORIGINS=%PUBLIC_APP%&& set MAX_UPLOAD_MB=95&& cd backend&& ..\tools\uv\uv.exe run uvicorn app.main:app --host 127.0.0.1 --port 8000"

rem 2) website: built for the public address, then served
start "Seqnce website (public)" cmd /k "cd frontend&& set NEXT_PUBLIC_API_URL=%PUBLIC_API%&& set NEXT_PUBLIC_MAX_UPLOAD_MB=95&& npm run build&& npm run start -- -p 3000"

rem 3) the tunnel that makes both reachable from the internet (the token is read from a git-ignored file)
set /p TUNNEL_TOKEN=<"%TOKEN_FILE%"
start "Seqnce tunnel" cmd /k "set TUNNEL_TOKEN=%TUNNEL_TOKEN%&& %CLOUDFLARED% tunnel --no-autoupdate run"

echo.
echo Started. In about a minute: %PUBLIC_APP%
echo (Keep this laptop on and awake while people use it.)
endlocal
