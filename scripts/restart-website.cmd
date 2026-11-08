@echo off
rem Rebuilds and restarts ONLY the public website window (after a frontend change). The backend and the tunnel keep running.
rem Close the old "Seqnce website (public)" window first (or it will fight for port 3000). Same settings as start-public.cmd.
setlocal
cd /d "%~dp0.."
set "PUBLIC_API=https://seqnce-api.orbitrixhq.com"
start "Seqnce website (public)" cmd /k "cd frontend&& set NEXT_PUBLIC_API_URL=%PUBLIC_API%&& set NEXT_PUBLIC_MAX_UPLOAD_MB=95&& npm run build&& npm run start -- -p 3000"
echo Rebuilding the website. It is back in about a minute.
endlocal
