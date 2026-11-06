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

## POST /api/videos/upload
`multipart/form-data`:
- `file` (required) – `.mp4`, ≤ `MAX_UPLOAD_MB`, ≤ `MAX_VIDEO_DURATION_S`, must start with an MP4 `ftyp` box and pass ffprobe.
- `target_duration` int 15–90 (default 45), `captions` bool (true), `remove_silence` bool (true), `background_music` bool (false), `music_track` string (optional).

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
`plan` is the validated editing plan: `source` (`ai`|`fallback`, with `fallback_reason`), `summary`, `clips[{id,start,end,purpose,reason}]`, `reframe`, `captions`, `silence`, `music`, `warnings`.
`visual.analysis_source` is `"ai"` or `"fallback"` (with `fallback_reason`) when the AI was unavailable.

## GET /api/jobs/{id}/result
`200` `{ job_id, original, rendered, plan, preview_url, download_url }` · `409` not ready / failed · `404`.
`rendered` is the ffprobe result of the final file: always 1080×1920, H.264/AAC, 30 fps.
