# Running Seqnce on a rented server (always on)

Goal: `https://seqnce.orbitrixhq.com` keeps working when your laptop is off. The same two programs (backend + website) run on a small Linux server, and the **same Cloudflare Tunnel** carries traffic to it, so the addresses, the domain and the accounts setup do not change.

```
tester's browser --> Cloudflare --tunnel--> your server
                      seqnce.orbitrixhq.com      -> website (127.0.0.1:3000)
                      seqnce-api.orbitrixhq.com  -> backend (127.0.0.1:8000)
```

The server never opens a web port to the internet. `cloudflared` on the server dials OUT to Cloudflare, so the only open port is SSH (for you).

> These steps were written and checked against the project, but not run on a real server yet. If a command fails, copy the error to Claude.

## 0. Before anything: put the latest code on GitHub
The server downloads Seqnce from GitHub (`git clone`). Anything not committed and pushed (photo mode, draggable text, deploy files) will not exist on the server. Commit and push first.

## 1. Choose and buy the server

**What Seqnce needs**
- x86 (Intel/AMD) machine, **4 vCPU and 8 GB RAM** (speech-to-text and video rendering run on the CPU; 2 vCPU works but is slow).
- **80 GB or more** disk (uploads and renders are kept for `RETENTION_DAYS`, default 7).
- Ubuntu **24.04 LTS**.
- Prefer a location near your testers. For the Philippines that means **Singapore**; Europe works but uploads are slower.

**Where**
- **Hetzner Cloud** (hetzner.com/cloud) is the usual best value. Look at the shared "Cost-Optimized" (CX) or "Regular Performance" (CPX) plans with 4 vCPU / 8 GB. Do not pick the ARM (CAX) plans for now.
- Hetzner raised prices in 2026 and Singapore costs more than its European locations, so check the live price list before choosing a location. Contabo, DigitalOcean and Vultr are alternatives with the same specs.
- You will probably need a card (or PayPal) and Hetzner may ask for an ID check on a new account.

**Make an SSH key first (on your Windows laptop, PowerShell)**
```powershell
ssh-keygen -t ed25519 -C "seqnce-server"
Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub
```
Press Enter for all questions (or set a passphrase). The second command prints your PUBLIC key (one line, starts with `ssh-ed25519`). Paste that into the provider's "SSH keys" box when creating the server. Never share the file without `.pub`; that is your private key.

**Create the server**: image Ubuntu 24.04, your SSH key selected, IPv4 enabled, name it `seqnce`. If there is a "Backups" option, enabling it is cheap insurance. Note the server's IP address.

## 2. First login and basic safety
From your laptop PowerShell:
```powershell
ssh root@YOUR.SERVER.IP
```
Say `yes` to the fingerprint question. Then, on the server:
```bash
apt update && apt -y upgrade
adduser --gecos "" seqnce          # you will choose a password; it is only used for sudo
usermod -aG sudo seqnce
rsync --archive --chown=seqnce:seqnce ~/.ssh /home/seqnce
ufw allow OpenSSH && ufw --force enable
apt -y install unattended-upgrades ffmpeg git curl ca-certificates
exit
```
Log back in as the new user (from now on never use root):
```powershell
ssh seqnce@YOUR.SERVER.IP
```

## 3. Install the tools
```bash
# Node.js 22 (the website)
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt -y install nodejs
# uv (Python manager; installs Python 3.12 itself if needed)
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.local/bin/env 2>/dev/null || export PATH="$HOME/.local/bin:$PATH"
ffmpeg -version | head -1 && node -v && uv --version
```

## 4. Download Seqnce
```bash
sudo mkdir /opt/seqnce && sudo chown seqnce:seqnce /opt/seqnce
git clone https://github.com/jethroilagan27-blip/seqnce-clipper-bot.git /opt/seqnce
cd /opt/seqnce/backend && uv sync --no-dev
```

## 5. Settings
Create the backend settings file (repo root `.env`, never committed):
```bash
nano /opt/seqnce/.env
```
Paste this, put your real Gemini key after `GEMINI_API_KEY=`, then Ctrl+O, Enter, Ctrl+X to save:
```
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.5-flash
AUTH_ENABLED=true
OPEN_SIGNUP=true
CORS_ORIGINS=https://seqnce.orbitrixhq.com
MAX_UPLOAD_MB=95
RETENTION_DAYS=7
WHISPER_MODEL=small
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8
```
Your key is the one in the `.env` on your laptop (project folder). Open it there and copy the value; do not paste it into chat.

The website needs its public address at build time:
```bash
nano /opt/seqnce/frontend/.env.production.local
```
```
NEXT_PUBLIC_API_URL=https://seqnce-api.orbitrixhq.com
NEXT_PUBLIC_MAX_UPLOAD_MB=95
```
Build it (takes a few minutes):
```bash
cd /opt/seqnce/frontend && npm ci && npm run build
```

## 6. Make both programs start by themselves
```bash
sudo tee /etc/systemd/system/seqnce-backend.service >/dev/null <<'EOF'
[Unit]
Description=Seqnce backend
After=network-online.target
Wants=network-online.target

[Service]
User=seqnce
WorkingDirectory=/opt/seqnce/backend
ExecStart=/home/seqnce/.local/bin/uv run --no-dev uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/seqnce-web.service >/dev/null <<'EOF'
[Unit]
Description=Seqnce website
After=network-online.target
Wants=network-online.target

[Service]
User=seqnce
WorkingDirectory=/opt/seqnce/frontend
Environment=NODE_ENV=production
ExecStart=/usr/bin/npm run start -- -H 127.0.0.1 -p 3000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now seqnce-backend seqnce-web
sleep 15
curl -s http://127.0.0.1:8000/api/health
curl -s -o /dev/null -w "website: %{http_code}\n" http://127.0.0.1:3000
```
You should see `{"status":"ok","ffmpeg":true,"auth_required":true}` and `website: 200`. If not: `sudo journalctl -u seqnce-backend -n 50` (or `seqnce-web`) shows why.

## 7. Create your admin account on the server
The server starts with an empty database, so your laptop account does not exist there yet. On the server (you type the password, it stays hidden):
```bash
cd /opt/seqnce/backend && uv run --no-dev python -m app.admin create-user you@example.com --admin
```

## 8. Move the tunnel from the laptop to the server
Important: **close the three `start-public` windows on your laptop first.** If both machines run the tunnel, Cloudflare splits visitors between them.

1. Install the tunnel program on the server:
```bash
sudo mkdir -p --mode=0755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt update && sudo apt -y install cloudflared
```
2. Connect it with the tunnel's token. The token is in `tools\cloudflared\token.txt` on your laptop (or Cloudflare dashboard -> Networking -> Tunnels -> seqnce-laptop -> the install command). Paste it yourself, do not share it in chat:
```bash
sudo cloudflared service install PASTE_YOUR_TOKEN_HERE
```
3. Test: open `https://seqnce.orbitrixhq.com` on your phone with Wi-Fi off, then turn your laptop off and test again.

The two routes (`seqnce` -> `localhost:3000`, `seqnce-api` -> `localhost:8000`) are already saved in Cloudflare, and `localhost` now means the server.

## 9. Invites
```bash
cd /opt/seqnce/backend && uv run --no-dev python -m app.admin invite --email friend@example.com
cd /opt/seqnce/backend && uv run --no-dev python -m app.admin users
```

## Updating later
When the code changes, push it to GitHub from your laptop, then on the server:
```bash
bash /opt/seqnce/scripts/server-update.sh
```

## Backups and housekeeping
- Everything that matters is in `/opt/seqnce/storage/` (accounts in `svb.sqlite3`, plus `.auth_secret`). Enable the provider's backups, or copy `storage/svb.sqlite3` and `storage/.auth_secret` somewhere safe now and then.
- Old videos are deleted automatically after `RETENTION_DAYS`. Check disk space with `df -h /`.
- Logs: `sudo journalctl -u seqnce-backend -f`.
- Keep the Gemini key only in `/opt/seqnce/.env` (`chmod 600 /opt/seqnce/.env`).
- Photo-mode and videos share one worker per task type, so several people at once queue. Rent a bigger plan if that hurts.
