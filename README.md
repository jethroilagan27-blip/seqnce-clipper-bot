# Seqnce

**Turn a talking-head video into a ready-to-post vertical short, then edit it like you would in a video editor, or just ask for changes in plain words.**

Upload an MP4. Seqnce transcribes it on your computer, asks an AI which parts are worth keeping, and renders a 9:16 short with captions and an optional title, music and chat-driven revisions. You can see the cuts, trim them on a filmstrip timeline, and re-render.

> **Early-stage, self-hosted software.** It runs on your own machine. It has **no login and no usage limits of its own**, so do not expose it to the internet as it is (see [Security](#security-and-privacy)).

## What it does

- **Auto-edit:** local speech-to-text ([faster-whisper](https://github.com/SYSTRAN/faster-whisper)) → Gemini chooses the best moments → FFmpeg cuts, shortens long pauses, crops to 9:16 around the speaker, burns in captions, and mixes optional music.
- **Hook title:** a big coloured headline at the top for the first few seconds (text and colour chosen by the AI, editable).
- **Tell it what you want:** optional instructions before editing ("focus on the pricing tips, make the hook a question").
- **Chat revisions:** "cut the intro", "make it 20 seconds". Each change becomes a numbered **version**, with a diff showing which parts were added, removed or trimmed. Go back to any version instantly.
- **Edit by hand:** a map of your whole video made of real frames, a list of numbered parts, a zoomed filmstrip to trim each one (handles snap to words), transcript click-to-cut, and title/captions controls.
- **Live preview:** the browser plays your original video as the edit (cuts, crop, captions, title) before anything is rendered. The preview uses the same cut list as the renderer.
- **Live progress:** while it works you watch the transcript appear, then the AI's chosen parts, and can play the preview before the final render finishes.

## How it works

```
upload ─► prepare ─► transcribe ─► look at frames ─► AI plan ─► validate ─► FFmpeg render ─► result
          ffprobe    Whisper        FFmpeg + Gemini   Gemini     Python     libx264 + libass
```

The AI only ever returns JSON. Python validates and repairs it (clamping, snapping to sentence boundaries, merging overlaps, length limits) and builds the FFmpeg commands itself. Nothing the AI writes is executed. See [ARCHITECTURE.md](ARCHITECTURE.md) and [docs/API.md](docs/API.md).

Stack: Next.js (React, Tailwind) · FastAPI · SQLite · FFmpeg · faster-whisper · Google Gemini.

## Requirements

- **Python 3.12+** and [uv](https://docs.astral.sh/uv/) (or any way to install the backend dependencies)
- **Node.js 20.9+**
- **FFmpeg + ffprobe**, built with libx264 and libass (most full builds have both). FFmpeg is not bundled; install it yourself and put it on your `PATH`, or drop `ffmpeg` and `ffprobe` into `tools/ffmpeg/`.
- A **Gemini API key** (free at <https://aistudio.google.com/apikey>). Without one the app still works, but falls back to a basic cut with no AI choices, hook or chat edits.
- Disk space and patience: the first run downloads the Whisper `small` model (about 0.5 GB). On a CPU, transcription takes roughly twice the video length.

## Quick start

```bash
git clone https://github.com/jethroilagan27-blip/seqnce-clipper-bot.git
cd seqnce-clipper-bot
cp .env.example .env          # then put your GEMINI_API_KEY in .env
```

Backend (terminal 1):

```bash
cd backend
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Frontend (terminal 2):

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:3000>. API docs are at <http://127.0.0.1:8000/docs>.

On Windows, `scripts\dev-backend.cmd` and `scripts\dev-frontend.cmd` do the same thing once the dependencies are installed.

Check that your key and model work:

```bash
cd backend && uv run python check_gemini.py
```

## Configuration

Everything is optional except the key. Put these in the repo-root `.env` (see [.env.example](.env.example)).

| Variable | Default | Meaning |
|---|---|---|
| `GEMINI_API_KEY` | – | Your key. Keep it only in `.env` (git-ignored). |
| `GEMINI_MODEL` | `gemini-3.5-flash` | Run `check_gemini.py` to list models your key can use. If you hit rate limits, try a `-lite` model. |
| `WHISPER_MODEL` | `small` | `tiny` / `base` / `small` / `medium` (bigger = slower, more accurate) |
| `WHISPER_LANGUAGE` | auto | Force e.g. `en` or `tl` if auto-detect struggles |
| `WHISPER_DEVICE`, `WHISPER_COMPUTE_TYPE` | `cpu`, `int8` | GPU (`cuda`, `float16`) needs extra CUDA libraries |
| `MAX_UPLOAD_MB`, `MAX_VIDEO_DURATION_S` | 500, 1800 | Upload size and length caps |
| `RETENTION_DAYS` | 7 | Finished jobs older than this are deleted at startup (0 = keep) |
| `STORAGE_DIR` | `./storage` | Uploads, renders, temp files and the SQLite database |
| `CORS_ORIGINS` | localhost:3000 | Browser origins allowed to call the API |
| `FFMPEG_PATH`, `FFPROBE_PATH` | auto | Override tool locations |

Frontend (`frontend/.env.local`): `NEXT_PUBLIC_API_URL` (default `http://127.0.0.1:8000`) and `NEXT_PUBLIC_MAX_UPLOAD_MB`.

**Background music:** put `.mp3`/`.wav`/`.m4a` files **you have the rights to use** into `storage/music/`, then tick "Background music". No music is bundled.

## Costs and limits

- Seqnce itself is free. Transcription, frame extraction, editing and rendering all run locally with no per-video fee.
- The AI step uses the **Gemini API**. On the free tier you get a limited number of requests per minute and per day (shown in Google AI Studio). Each upload uses 2 AI calls and each chat message uses 1; hand edits, restoring a version and the live preview use none. If you hit the limit the app falls back to a basic cut and tells you why.

## Sharing it with other people (accounts and limits)

By default Seqnce has no login (fine on your own computer). To let others use your server, turn on invite-only accounts in `.env`:

```
AUTH_ENABLED=true
DAILY_VIDEO_LIMIT=3      # per user, rolling 24 h (admins unlimited)
DAILY_CHAT_LIMIT=20
```

Then, from `backend/`:

```bash
uv run python -m app.admin create-user you@example.com --admin   # asks for a password
uv run python -m app.admin invite --email friend@example.com     # prints a one-time invite code
uv run python -m app.admin users                                  # who has used what today
```

With accounts on, nobody can reach any video without signing in, users only ever see their own jobs, uploads are refused before the file is read if you're not signed in, and each user is limited to a few videos and AI chat messages per day and one video at a time. Details: [docs/API.md](docs/API.md#accounts-ownership-and-quotas-auth_enabledtrue).

This does **not** make the server safe to put on the open internet by itself: serve it over HTTPS (for example through a Cloudflare Tunnel or a reverse proxy), keep `CORS_ORIGINS` set to your real site only, and remember that your Gemini key pays for everyone's AI calls.

## Security and privacy

- **What leaves your machine:** the transcript text, up to 12 small (512 px) frames sampled from the video, and any instructions or chat messages you type are sent to the Gemini API. Your video file and audio stay local. Read Google's current terms for the free tier; they differ from the paid tier.
- **Accounts are off by default.** With `AUTH_ENABLED=false` anyone who can reach the backend can upload videos and spend your Gemini quota, so keep it on localhost or a private network. To share it, switch on [accounts and limits](#sharing-it-with-other-people-accounts-and-limits) and serve it over HTTPS.
- The code takes care to avoid the usual footguns: no shell execution (FFmpeg is always called with an argument list), no client-supplied paths, server-generated filenames, MP4 signature and ffprobe validation, size and duration caps, and secrets only in the untracked `.env`.
- Only upload footage you have the right to edit and share.

## Known limitations

- Talking-head footage works best; there is no face tracking (the 9:16 crop is centred on where the AI says the speaker is).
- Clips stay in chronological order (no re-ordering). Captions are plain pages, not animated word-by-word.
- 720p sources look soft after the vertical crop; 1080p and up look better.
- Tested on synthetic samples and a few real vlogs. Accents, noisy audio and very long videos are not well tested.
- One job renders at a time.

## Tests

```bash
cd backend && uv run pytest -q     # 115 tests, no network or real models needed
cd frontend && npm test            # timeline helper unit tests
cd frontend && npm run lint && npx tsc --noEmit
```

Opt-in checks that use the real Whisper model and the real Gemini API: `uv run pytest -m real_whisper -s` and `uv run pytest -m live_ai -s` (create `samples/speech_sample.mp4` first with `scripts/make_sample_video.ps1` on Windows).

## Project layout

```
backend/    FastAPI app: pipeline stages, AI layer, plan validation, FFmpeg editing, tests
frontend/   Next.js UI: upload, live processing view, editor, chat, versions
docs/       API reference
scripts/    Windows launchers and a sample-video generator
```

## Contributing

Issues and pull requests are welcome. Please run the tests above before opening a PR, and keep the rule that AI output is only ever data (validated JSON), never code or shell.

## License

[MIT](LICENSE) © 2026 Jethro Ilagan. FFmpeg, faster-whisper and the other dependencies have their own licenses; FFmpeg is installed separately and is not distributed with this repository.
