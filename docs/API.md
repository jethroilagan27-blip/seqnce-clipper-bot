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
