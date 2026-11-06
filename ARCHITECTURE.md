# Architecture

## 1. Final architecture

```
Browser (Next.js, :3000)
   │  multipart upload (XHR, progress)        │ poll GET /api/jobs/{id} every 1.5 s
   ▼                                          ▼
FastAPI (:8000) ── validates file ── SQLite (jobs table) ◄── Worker thread (same process)
   │ saves storage/uploads/{job}.mp4                          │ claims 'queued' jobs, one at a time
   ▼                                                          ▼
                         Pipeline (app/pipeline/*)  — each stage = one function
   prepare ─► transcribe ─► visual ─► plan ─► edit ─► render
   ffprobe     faster-whisper  ffmpeg     Gemini    validate    ffmpeg
   + audio     (local, CPU)    frames +   JSON       plan →      (libx264 + libass
   extract                     Gemini     plan       FFmpeg      captions + music)
                               vision                commands
```

Rules that never change:
- **The AI only produces JSON.** Python validates it (`plan.py`, Day 4) and builds FFmpeg arguments itself. No AI output is ever executed or interpolated into a shell string.
- FFmpeg is always called with an argument **list** (no shell), on paths the server generated.
- Clients never send paths. Files are named `{job_id}.ext` where `job_id` is a server-made UUID.
- The AI provider sits behind one interface (`app/ai/base.py`, Day 3) so Gemini can be swapped.

### Changes vs. the original brief (based on this machine)
| Brief said | Reality / decision |
|---|---|
| Python, FFmpeg installed | Neither was installed. Both now live in `tools/` (uv-managed Python 3.12, gyan.dev FFmpeg 9 essentials). No system PATH changes. |
| "Two parallel processes" (speech ‖ visual) | Run **sequentially** in the MVP. Whisper already saturates the CPU; parallelism buys little and adds bugs. Revisit only if too slow. |
| faster-whisper | Yes, CPU `int8`, model `small` by default. GPU (RTX 2050 4 GB) is possible later via CUDA libs; not needed for MVP. |
| Project in OneDrive | Works, but OneDrive will try to sync `tools/`, `.venv/`, `node_modules/`, `storage/` (GBs). Recommend moving the repo to e.g. `C:\dev\` or excluding those folders. |

## 2. Folder structure

```
.
├─ backend/                FastAPI app (uv project)
│  ├─ app/
│  │  ├─ main.py           app factory, CORS, lifespan (starts worker)
│  │  ├─ config.py         env-driven settings, storage paths, ffmpeg lookup
│  │  ├─ db.py             SQLite schema + job queries
│  │  ├─ schemas.py        Pydantic API models
│  │  ├─ stages.py         stage names + progress %
│  │  ├─ worker.py         background thread draining the queue
│  │  ├─ api/              videos.py (upload/preview/download), jobs.py (status/result)
│  │  ├─ services/media.py ffprobe / audio extraction wrappers
│  │  └─ pipeline/         runner.py (stage list) + one module per stage
│  └─ tests/               pytest (generates real videos with ffmpeg)
├─ frontend/               Next.js 16 + Tailwind 4
│  ├─ app/page.tsx         state machine: upload → processing → result
│  ├─ components/          UploadCard, ProcessingView, ResultView
│  └─ lib/api.ts           backend client + formatters
├─ storage/                (gitignored) uploads/ temp/ subtitles/ outputs/ music/ + svb.sqlite3
├─ tools/                  (gitignored) uv, python, ffmpeg
├─ scripts/                dev-backend.cmd, dev-frontend.cmd
└─ README.md  ARCHITECTURE.md  PROJECT_STATUS.md  docs/API.md  .env.example
```

## 3. Dependencies
- **Backend now:** fastapi, uvicorn, python-multipart, pydantic-settings; dev: pytest, httpx.
- **Backend later:** `faster-whisper` (Day 3), `google-genai` (Day 3), `Pillow` only if frame handling needs it.
- **Frontend:** next, react, tailwindcss (no UI library, no state library).
- **System tools:** ffmpeg + ffprobe (local, in `tools/`).

## 4. Environment variables
See `.env.example` (documented there and in README). Secrets (`GEMINI_API_KEY`) only in the untracked `.env`.

## 5. API
See [docs/API.md](docs/API.md).

## 6. Database schema
Single table `jobs` (see `backend/app/db.py`): `id, status, stage, progress, original_filename, upload_path, audio_path, transcript_path, output_path, settings_json, metadata_json, output_metadata_json, plan_json, error, created_at, updated_at`.
`status` ∈ queued | running | completed | failed. `stage` ∈ uploaded | preparing | transcribing | analyzing_visuals | planning | editing | rendering | completed.

## 7. Background processing
One daemon thread started in FastAPI's lifespan. Loop: `claim_next_job()` (atomic `BEGIN IMMEDIATE` select+update) → `run_job()` → repeat; sleeps 1 s when idle. Each stage updates `stage`/`progress` in SQLite; the frontend polls. On startup, jobs stuck in `running` (crash/restart) are put back to `queued`. Errors: `MediaError`-type exceptions carry a user-safe message; anything else is logged with a traceback and the user sees a generic message. One job at a time (rendering is CPU-bound).

## 8. AI editing-plan schema (target; built Day 4)
```json
{
  "version": 1,
  "summary": { "main_subject": "string", "main_message": "string" },
  "format": { "aspect_ratio": "9:16", "width": 1080, "height": 1920 },
  "target_duration": 45,
  "clips": [
    { "id": "c1", "start": 12.5, "end": 24.0,
      "purpose": "hook | main_content | example | conclusion",
      "reason": "Strong opening statement" }
  ],
  "reframe": { "strategy": "center | face_center", "focus_x": 0.5 },
  "captions": { "enabled": true, "max_words_per_line": 4, "max_lines": 2 },
  "silence": { "remove": true, "max_pause_s": 0.6 },
  "music": { "enabled": false, "track": null, "volume": 0.12 }
}
```
Validation (all in Python, before any FFmpeg call): JSON parses and matches the Pydantic model; `0 ≤ start < end ≤ video duration`; each clip ≥ 1 s; no overlaps/duplicates (IoU/containment check); clips sorted chronologically unless an explicit `order` field says otherwise; total duration within ±25 % of target (else trim/pad the last clip or re-ask); clip edges snapped to transcript segment boundaries so sentences aren't cut mid-word; music track must exist in `storage/music/`. On failure: one auto-repair attempt (clamp/sort/dedupe), then one regeneration with the validation errors appended to the prompt, then fall back to a deterministic plan (first N seconds of best-scoring segments).

## 9. Seven-day checklist
- [x] **Day 1** Environment, repo, FastAPI + Next.js scaffold, upload UI, CORS link.
- [x] **Day 2 (mostly pulled forward)** Upload endpoint + validation, SQLite, ffprobe metadata, audio extraction, worker, tests.
- [x] **Day 3** faster-whisper transcript (`storage/temp/{job}/transcript.json`), frame extraction + scene detection, provider-neutral AI layer with Gemini client and one vision call. Live Gemini call still unverified (no key yet); free-tier limits are only visible per project in AI Studio.
- [x] **Day 4** Gemini planner (`pipeline/planner.py`), plan schema + validator + repair/regenerate/fallback (`plan/`). Verified live: 5 sensible clips, filler skipped, sentence-aligned.
- [x] **Day 5** Editor (`editing/`, `pipeline/editor.py`, `pipeline/render.py`): word-accurate cuts, pause shortening, 9:16 speaker-focused crop, ASS captions, music mix, loudness normalisation, output verification.
- [x] **Day 6** Full UI flow, music picker, plan summary, refresh-resume, retention cleanup.
- [~] **Day 7** Automated edge-case/failure tests done (68 tests). Still needs a real talking-head video for crop/accent judgement.

## 10. Likely bottlenecks / risks
1. **Whisper speed on CPU.** `small` int8 on 6 cores should be a few× real-time; `medium` is slower. Mitigation: model env var; GPU path later.
2. **Gemini free tier** has per-minute/day request & token limits that change. Mitigation: ≤ ~12 frames/call, 1–2 calls per job, cache results per job in SQLite, retry with backoff.
3. **Speaker-aware 9:16 crop.** Center-crop is the MVP; face tracking is nice-to-have. Landscape → portrait loses sides; plan carries `focus_x`.
4. **Caption sync after cuts.** Caption times must be remapped from source time to output time per clip. Do this in one function with unit tests.
5. **Cut quality.** Stream-copy cuts are fast but snap to keyframes; we re-encode (libx264) for frame-accurate cuts.
6. **OneDrive** syncing large generated files (see above).
7. **Large uploads** are spooled to disk twice by multipart parsing (acceptable at ≤ 500 MB).
