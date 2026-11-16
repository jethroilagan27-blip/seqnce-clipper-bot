# Sharing Seqnce from your own computer (private beta)

Goal: friends/testers open **https://seqnce.orbitrixhq.com**, sign in with an invite, and use Seqnce while **your laptop is on**.
Seqnce keeps running on your machine; a free **Cloudflare Tunnel** gives it a public address with HTTPS. No ports are opened on your router.

```
tester's browser ──► Cloudflare ──tunnel──► your laptop
                       seqnce.orbitrixhq.com      → website   (localhost:3000)
                       seqnce-api.orbitrixhq.com  → backend   (localhost:8000)
```

When your laptop is off, the site is down. To make it always-on later, run the same two programs on a rented server and point the same two names at it (see the end).

## One-time setup

### 1. The domain
Already done: `orbitrixhq.com` is registered at Cloudflare, so its DNS is on Cloudflare.

### 2. Create the tunnel (Cloudflare dashboard, about 5 minutes)
1. Cloudflare dashboard → **Zero Trust** (free plan; it may ask for a payment method but does not charge for this) → **Networks → Tunnels → Create a tunnel**.
2. Type **Cloudflared**, name it `seqnce-laptop`, and copy the **token** (a long text starting with `ey…`). Treat it like a password.
3. Save it, alone on one line, in `tools\cloudflared\token.txt` (the `tools` folder is git-ignored; never commit or paste the token anywhere).
4. In the tunnel's **Public Hostnames** tab add two entries (Cloudflare creates the DNS records for you):
   | Subdomain | Domain | Service |
   |---|---|---|
   | `seqnce` | `orbitrixhq.com` | `HTTP` → `localhost:3000` |
   | `seqnce-api` | `orbitrixhq.com` | `HTTP` → `localhost:8000` |

   Use a single-level name like `seqnce-api`, not `api.seqnce`: Cloudflare's free certificate covers one level of subdomain.

### 3. Get `cloudflared.exe`
Download the Windows 64-bit `cloudflared-windows-amd64.exe` from the official releases page (github.com/cloudflare/cloudflared/releases) and save it as `tools\cloudflared\cloudflared.exe`.

### 4. Create your admin account and invites
From `backend\` (no need to start the server first):

```bash
..\tools\uv\uv.exe run python -m app.admin create-user you@example.com --admin
..\tools\uv\uv.exe run python -m app.admin invite --email friend@example.com
```
The invite code is shown once; send it to your tester.

## Every time you want to share it
1. Stop the normal dev servers if they are running (they use ports 3000 and 8000).
2. Run `scripts\start-public.cmd`. It opens three windows: backend (accounts on), website, tunnel. Wait about a minute (the site is built first).
3. Open `https://seqnce.orbitrixhq.com` from your phone **on mobile data** to prove it works from outside.
4. Close the three windows to stop sharing. `scripts\dev-backend.cmd` / `dev-frontend.cmd` still give you the normal no-login local version.

Keep the laptop **plugged in and set to never sleep** while testers are using it (Windows → Settings → System → Power).

## Things to know
- **Upload size:** Cloudflare's free plan rejects any single request over **100 MB**, so the public setup (`PROXY_REQUEST_LIMIT_MB=100`, set by `start-public.cmd`) sends bigger videos and Studio files in **50 MB pieces** that the server puts back together (resumable per piece, unfinished uploads deleted after 12 hours). Files up to `MAX_UPLOAD_MB` (1500 in the public script) work. Photos still go in groups under 60 MB. On your own computer (`dev-backend.cmd`) the setting is absent, so every file goes up in a single request, with no pieces and no 100 MB limit.
- **Accounts and limits:** the public run turns accounts on: invite-only, everyone sees only their own work, 3 videos and 20 AI chat messages per person per 24 hours (see `.env.example`). Photo videos count as videos.
- **Everyone brings their own Gemini key.** With accounts on, each person adds their free Gemini key at **Settings** (`/settings`); the AI for their videos, chat and Studio runs on that key, so your key pays for nothing (only admin accounts fall back to the key in `.env`). Without a key a person still gets a basic cut, and a banner tells them where to add one. Keys are checked with Google, stored **encrypted** (secret in `storage/.ai_key_secret`, or `AI_KEY_SECRET`: back it up with the database, or people must paste their keys again), never shown again (only the last 4 characters) and never logged.
- **Phones:** the website is installable as an app (Settings → "Use Seqnce as a phone app", or the browser's "Add to Home Screen"). It needs the public HTTPS address; the editing still runs on the server.
- **Privacy:** testers' videos are stored on your laptop (deleted automatically after `RETENTION_DAYS`, default 7). The transcript, a few small frames and chat messages are sent to Google's Gemini API. Tell testers.
- **Speed:** the laptop does all the work, one video at a time per task type. Several people at once will queue.
- **If something looks wrong:** the backend window shows the log. `uv run python -m app.admin users` shows who has used what.

## Offline page (what visitors see when Seqnce is off)
When your laptop is off, a small Cloudflare Worker named `seqnce-offline` shows a Seqnce page ("Seqnce is resting, usually online 9:00 AM to 9:00 PM Philippine time, back in 8 h 8 min") instead of Cloudflare's "Error 1033". It runs on Cloudflare, so it works with the laptop off.

- Code: `cloudflare/seqnce-offline/worker.js` (tests: `node --test cloudflare/seqnce-offline/worker.test.mjs`).
- Attached to **`seqnce.orbitrixhq.com/*` only**, as a Worker Route with "Fail open" (if the Worker itself fails, visitors go straight to Seqnce). The API address is not touched.
- To change the hours, edit `OPEN_HOUR` / `CLOSE_HOUR` at the top of `worker.js`, then in the Cloudflare dashboard open Workers & Pages -> `seqnce-offline` -> Edit code, paste the file, and Deploy.
- Look at the page any time: `https://seqnce.orbitrixhq.com/__offline-preview` (add `?state=open` or `?state=closed` to see each version).
- The page has two versions, chosen by the hours in the file (it cannot see whether you are actually around):
  - **Outside the usual hours:** "Seqnce is resting" with the usual hours and a "back in" countdown.
  - **During the usual hours:** "Seqnce is switched off right now. Please notify Levin to turn the server on so you can use it." It reloads itself every minute, so it opens Seqnce as soon as the server is on. This way you only switch the laptop on when someone asks.
- Change the name with `NAME` at the top of `worker.js`. `CONTACT` is an optional extra line under the message (for example your Messenger link); leave it empty to show nothing.
- On an always-on server, remove the route (Workers & Pages -> `seqnce-offline` -> Domains -> remove the route) or keep it only for maintenance.

Lesson from setting it up: a Worker "custom domain" set to **Production and Preview** also claims `*.yourdomain.com`, which hides every tunnel address. Keep `orbitrixhq.com` as Production only.

## Later: an always-on server
Rent a small Linux server (4 CPU cores / 8 GB RAM is a comfortable start), install the same things (Python + uv, Node, FFmpeg), run the backend and website there as services, and move the same tunnel (or plain DNS records) to it. The two public names, the accounts and the data layout do not change.
