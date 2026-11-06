# Seqnce – automated short-form video editor (MVP)

Upload a talking-head MP4 → local transcription + AI analysis → auto-edited vertical 9:16 short with captions.
Free/open-source stack: Next.js, FastAPI, SQLite, FFmpeg, faster-whisper, Gemini free tier.

What it does today: upload an MP4 → local Whisper transcript → Gemini picks the best clips → FFmpeg cuts them, crops to 9:16, burns in captions, mixes optional music → preview + download.

Status: see [PROJECT_STATUS.md](PROJECT_STATUS.md). Design: [ARCHITECTURE.md](ARCHITECTURE.md). API: [docs/API.md](docs/API.md).

## Run it (Windows)
Two terminals from the repo root:

```bash
scripts\dev-backend.cmd
```
```bash
scripts\dev-frontend.cmd
```
Open http://localhost:3000. Backend docs: http://127.0.0.1:8000/docs.

## First-time setup
Already done on this machine. On a fresh one:
1. Install Python 3.12 (or `tools/uv/uv.exe python install 3.12`) and FFmpeg (put `ffmpeg.exe`/`ffprobe.exe` in `tools/ffmpeg/` or on PATH).
2. `cd backend && ..\tools\uv\uv.exe sync`
3. `cd frontend && npm install`
4. Copy `.env.example` → `.env`.

## Tests
```bash
cd backend && ..\tools\uv\uv.exe run pytest -q
```

## Environment variables (root `.env`)
| Variable | Default | Meaning |
|---|---|---|
| `STORAGE_DIR` | `./storage` | uploads / temp / subtitles / outputs / music + SQLite db |
| `FFMPEG_PATH`, `FFPROBE_PATH` | auto | override tool locations |
| `MAX_UPLOAD_MB` | 500 | upload size cap |
| `MAX_VIDEO_DURATION_S` | 1800 | longest accepted video |
| `RETENTION_DAYS` | 7 | finished jobs older than this are deleted at startup (0 = keep) |
| `CORS_ORIGINS` | localhost:3000 | allowed browser origins |
| `GEMINI_API_KEY` | – | keep only in `.env`. Without it, visual analysis falls back to a neutral centre crop |
| `GEMINI_MODEL` | gemini-3.5-flash | run `check_gemini.py` to list the models your key can use |
| `WHISPER_MODEL` | small | tiny / base / small / medium (bigger = slower, more accurate) |
| `WHISPER_DEVICE`, `WHISPER_COMPUTE_TYPE` | cpu, int8 | GPU (`cuda`, `float16`) needs extra CUDA libraries |
| `WHISPER_LANGUAGE` | auto | force e.g. `en` or `tl` if auto-detect struggles |
| `FRAME_INTERVAL_S`, `FRAME_WIDTH` | 3, 512 | frame sampling for visual analysis |
| `MAX_AI_FRAMES` | 12 | max images per AI call |
| `SCENE_THRESHOLD`, `AI_MAX_RETRIES` | 0.35, 3 | scene-cut sensitivity; retries on rate limits |

### Useful commands
```bash
cd backend && ..\tools\uv\uv.exe run python check_gemini.py
```
```bash
cd backend && ..\tools\uv\uv.exe run pytest -m real_whisper -s
```
`check_gemini.py` verifies your key and model. The second runs real transcription on `samples/speech_sample.mp4` (create it with `powershell scripts\make_sample_video.ps1`).

Frontend (`frontend/.env.local`): `NEXT_PUBLIC_API_URL` (default `http://127.0.0.1:8000`), `NEXT_PUBLIC_MAX_UPLOAD_MB`.

## Background music
Put `.mp3` / `.wav` / `.m4a` files **you have the rights to use** into `storage/music/`, then tick "Background music" in the app and pick a track. It is mixed ~18 dB under the voice. No music is bundled.

## Security notes
No shell execution, no client-supplied paths, server-generated filenames, validated uploads, secrets only in untracked `.env`.
Background music: only supply music you have rights to use; none is bundled.
