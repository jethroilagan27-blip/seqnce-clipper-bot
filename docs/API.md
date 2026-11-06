# API

Base URL (dev): `http://127.0.0.1:8000`. Interactive docs: `/docs` (Swagger) while the backend runs.
Job ids are 32-char lowercase hex; anything else returns `422`. Responses never contain server file paths.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | `{status, ffmpeg}` – is the server up and FFmpeg found |
| POST | `/api/videos/upload` | Upload MP4 + settings → creates a job |
| GET | `/api/jobs/{id}` | Job status/progress/metadata |
| GET | `/api/jobs/{id}/result` | Final output info (409 until a render exists) |
| GET | `/api/videos/{id}/preview` | Inline MP4 stream (Range supported) |
| GET | `/api/videos/{id}/download` | MP4 as attachment |
| GET | `/api/videos/{id}/original` | The uploaded source video |
| GET | `/api/music` | `{tracks: [...]}` files available in `storage/music` |
| GET | `/api/jobs/{id}/versions` | Every render of the job (plan, diff, chat reply, preview/download URLs) |
| POST | `/api/jobs/{id}/revisions` | Change the edit: chat message, hand edit, or go back to a version → `202` |

`/api/videos/{id}/preview` and `/download` accept `?version=N` (default: the current version).

## POST /api/videos/upload
`multipart/form-data`:
- `file` (required) – `.mp4`, ≤ `MAX_UPLOAD_MB`, ≤ `MAX_VIDEO_DURATION_S`, must start with an MP4 `ftyp` box and pass ffprobe.
- `target_duration` int 15–90 (default 45), `captions` bool (true), `remove_silence` bool (true), `background_music` bool (false), `music_track` string (optional), `hook` bool (true – big title at the top for the first ~4 s), `instructions` string (optional, free text for the AI editor; whitespace-normalised and capped at 500 chars).

`201` → `{ "job_id": "…" }`
Errors: `413` too large/long · `415` not an mp4 · `422` unreadable video / bad settings.

## GET /api/jobs/{id}
```json
{
  "id": "…", "status": "queued|running|completed|failed",
  "stage": "uploaded|preparing|transcribing|analyzing_visuals|planning|editing|rendering|completed",
  "progress": 0-100, "original_filename": "clip.mp4",
  "settings": { "target_duration": 45, "captions": true, "remove_silence": true, "background_music": false, "music_track": null },
  "original": { "duration": 20.0, "width": 1280, "height": 720, "fps": 30.0, "video_codec": "h264", "has_audio": true, "audio_codec": "aac", "size_bytes": 8035723 },
  "has_output": false, "error": null, "created_at": "…", "updated_at": "…"
}
```
`404` unknown job. A finished job has `status: completed`, `progress: 100`, `has_output: true`.

## GET /api/jobs/{id}/analysis
Available once transcription finished (`409` before). Returns
`{ transcript: { language, duration, segments: [{start, end, text, words:[{start,end,word}]}] }, visual: {...} | null, plan: {...} | null }`.
`plan` is the validated editing plan: `source` (`ai`|`fallback`, with `fallback_reason`), `summary`, `clips[{id,start,end,purpose,reason}]`, `reframe`, `captions`, `silence`, `music`, `hook` (`{enabled, text, color, duration_s}`; color is one of a fixed palette, text is cleaned in Python: ≤ 8 words, no emoji), `instructions`, `warnings`. Fallback plans have no hook.
`visual.analysis_source` is `"ai"` or `"fallback"` (with `fallback_reason`) when the AI was unavailable.

## GET /api/jobs/{id}/result
`200` `{ job_id, original, rendered, plan, preview_url, download_url }` · `409` not ready / failed · `404`.
`rendered` is the ffprobe result of the final file: always 1080×1920, H.264/AAC, 30 fps.

## Versions and revisions
Every finished render is a numbered **version** (v1 = the first edit). A revision creates the next version; the previous ones stay playable until the job is purged (`RETENTION_DAYS`).

### POST /api/jobs/{id}/revisions
JSON body, exactly one of:
- `{"message": "cut the intro and make the hook a question"}` – **chat**. The AI re-plans using the saved transcript (1 Gemini call, 2 in the worst case), Python validates the result like a first plan, then the video is re-rendered. If the AI decides nothing needs to change, the new version reuses the same video.
- `{"edit": {"hook_enabled"?, "hook_text"?, "hook_color"?, "captions_enabled"?, "remove_clips"?: ["c2"]}}` – **hand edit**, no AI. Hook text is cleaned (≤ 8 words, no emoji); at least one clip must remain.
- `{"restore_version": 1}` – **go back**. Instant: the new version points at the old version's video (no render).

`202 {"version": N}` (the number the new version will get) · `409` job not finished / another change running · `422` invalid or no-op request · `404` unknown job or version.
Then poll `GET /api/jobs/{id}`: while it runs `status` is `queued|running`, `revising: true`, `stage` is `revising|editing|rendering`. When done `revising` is `false` and `current_version` has increased.
**A failed revision never loses the current version**: the job returns to `completed`, `current_version` is unchanged, and `error` explains what went wrong (it is cleared by the next request).

### GET /api/jobs/{id}/versions
```json
{ "current": 2, "versions": [
  { "version": 1, "source": "initial", "message": "your first instructions or null", "reply": null,
    "plan": { }, "changes": null, "has_output": true,
    "preview_url": "/api/videos/…/preview?version=1", "download_url": "…" },
  { "version": 2, "source": "chat|manual|restore", "message": "…", "reply": "the AI editor's answer (chat only)",
    "plan": { },
    "changes": { "clips": [{"id":"c1","start":0,"end":9.5,"purpose":"hook","reason":"…","status":"kept|trimmed|added|removed","before":{"start":0,"end":12}}],
                 "settings": [{"field":"Hook colour","before":"yellow","after":"red"}],
                 "counts": {"kept":1,"trimmed":0,"added":0,"removed":2}, "unchanged": false,
                 "old_total": 34.0, "new_total": 17.9 },
    "has_output": true, "preview_url": "…", "download_url": "…" } ] }
```
`changes` is computed against the version that was current when the change was made. `removed` clips carry the ids/times of the *old* plan.

## Timeline editing (clips by hand, live preview data)

### Hand edits can now replace the whole clip list
`POST /api/jobs/{id}/revisions` with `{"edit": {"clips": [{"start": 12.3, "end": 20.0, "purpose": "main_content", "reason": ""}], "hook_duration_s": 3}}`.
- `clips` is the **complete** new list in source-video seconds (not combinable with `remove_clips`). Positions are kept exactly as sent (no snapping to sentences); the server clamps to the video, sorts, merges overlapping/touching clips, and rejects clips shorter than 1 s, more than 30 clips, or more than 180 s in total (`422` with a readable message).
- At render time each clip's edges still land on the first/last spoken word inside it (plus a tiny pad), so a trim that falls in silence moves to the nearest word.
- `hook_duration_s` (1–10): how long the hook title stays on screen.

### POST /api/jobs/{id}/timeline
Body (optional): `{"version": 2, "edit": { …same shape as a hand edit… }}`. Saves nothing. Returns what the edit looks like, computed with **the same code the renderer uses**:
```json
{ "total": 14.02,
  "cuts":  [{"start": 0.0, "end": 1.7, "out_start": 0.0}],        // source ranges that are played, in order
  "pages": [{"start": 0.0, "end": 1.6, "text": "Welcome to"}],   // caption pages, output time
  "captions_enabled": true,
  "hook":  {"enabled": true, "text": "…", "color": "cyan", "duration_s": 4.0},
  "reframe": {"strategy": "focus", "focus_x": 0.5},
  "source": {"width": 1280, "height": 720, "duration": 59.9},
  "clips": [ … plan clips … ] }
```
Available as soon as the plan exists (`409` before), also while the video is still rendering. `404` unknown version, `422` invalid draft. The browser uses it to play the **original** video as the edit (`GET /api/videos/{id}/original`, Range supported) with the crop, captions and title drawn on top.

## Live view while processing, and filmstrip frames

### GET /api/jobs/{id}/analysis while transcribing
Once Whisper has produced its first sentence (and until the transcript is final) this returns `200` with `"partial": true`: `transcript` holds the sentences recognised **so far** (text and times only, no per-word timings; `complete: false`, `duration` = length of the whole video), `visual` and `plan` are `null`. The server saves this about every 1.5 s. When the transcript is final the response is the full one with `"partial": false`. Before the first sentence it is still `409`.

### GET /api/videos/{id}/thumb?t=12.5&h=64
One small JPEG frame of the **original** video, for filmstrips. `t` = seconds (0–1,000,000, clamped to just before the end), `h` ∈ {48, 64, 96, 144} (anything else → `422`). Frames are cut on a half-second grid with FFmpeg on first request (at most 3 at a time), cached on disk under the job's temp folder (removed with the job) and sent with `Cache-Control: max-age=86400`. `404` unknown job, missing file, or no frame at that time.

## Accounts, ownership and quotas (`AUTH_ENABLED=true`)

Off by default: with it off every request is served as a built-in local admin with no limits, `/api/auth/login|signup` return `404`, and nothing below applies. With it on:

- **Everything under `/api/` except `/api/health`, `/api/auth/signup` and `/api/auth/login` needs `Authorization: Bearer <token>`** (`401` otherwise). The interactive docs (`/docs`, `/openapi.json`) are switched off.
- **Sign-up is invite-only.** An admin creates a one-time code with `uv run python -m app.admin invite [--email x] [--days 7]`; only its hash is stored.
- **Ownership:** a job belongs to the user who uploaded it. Someone else's job answers `404`, exactly like a job that doesn't exist. Admins can open any job; jobs from before accounts existed are admin-only.
- **Passwords** are scrypt hashes (min. 10 characters). Sessions and invite codes are stored only as SHA-256 hashes. Sign-in is throttled (5 failures per email and 30 per address per 15 minutes → `429`, in memory), and failures never reveal whether an email exists.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/auth/signup` | `{invite_code, email, password}` → `201 {token, media_token, user}` |
| POST | `/api/auth/login` | `{email, password}` → `{token, media_token, user}` |
| POST | `/api/auth/logout` | ends this session (`204`) |
| GET | `/api/auth/me` | `{auth_required, user, media_token}`; call it hourly to renew the media token |

`user` = `{email, is_admin, quota: {videos: {used, limit, resets_at}, chats: {…}}}`; `limit: null` = unlimited.
`/api/health` also returns `auth_required` so a client knows whether to show a sign-in screen.

### Media tokens
`<video>`, `<img>` and download links can't send an `Authorization` header, so `GET /api/videos/{id}/original|preview|download|thumb` also accept `?st=<media_token>`: an HMAC-signed token (valid 6 hours, tied to the user, checked against the job owner and the user's enabled state). It works **only** on those four endpoints; it is not a login.

### Quotas (rolling 24 hours, per user)
- **Videos** (`DAILY_VIDEO_LIMIT`, default 3): spent when an upload is accepted. **Chat messages** (`DAILY_CHAT_LIMIT`, default 20): spent by `POST /revisions` with `{message}` (the AI call). Hand edits, restoring a version, the live preview and thumbnails cost nothing.
- Over the limit → `429` with a readable message ("…More free up in about 3 hours."). The check-and-spend is one database transaction, so parallel requests can't slip past it.
- A user may have `MAX_ACTIVE_JOBS_PER_USER` (default 1) videos queued/processing at once → `409`.
- Admins have no limits; per-user overrides: `python -m app.admin set-limits EMAIL --videos 10 --chats default`.

### Upload gate
`POST /api/videos/upload` is checked **before its body is read**: without a valid session it answers `401`, and a declared size over `MAX_UPLOAD_MB` answers `413`, so a stranger can't make the server spool a huge file just to be refused.

### Admin tool
`uv run python -m app.admin` (from `backend/`): `invite`, `create-user EMAIL [--admin]`, `users`, `disable|enable EMAIL`, `make-admin EMAIL`, `set-limits`, `reset-password`. Passwords come from a hidden prompt or `SEQNCE_ADMIN_PASSWORD`, never from the command line.
