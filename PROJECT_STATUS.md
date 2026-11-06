# Project Status

**Current day:** 7 of 7 · **Last updated:** 2026-11-06
**State:** the full MVP workflow works end to end. Final judgement on *real* footage is still pending (see "Not verified").

## Completed (all acceptance-criteria steps implemented and exercised)
1. Upload an MP4 (validated: extension, MP4 signature, ffprobe, size/duration caps) – progress bar in UI.
2. Local storage + SQLite job tracking + background worker (crash re-queue, one job at a time).
3. **Transcript** with word-level timestamps – local faster-whisper (`small`, CPU int8). ~2× real time.
4. **Frames** every 3 s + scene detection (FFmpeg), ≤ 12 frames to the AI.
5. **Gemini** visual analysis (framing, speaker position) and **editing plan** (clips, purposes, reasons). Model: `gemini-3.5-flash` (`gemini-2.5-flash` is closed to new users). 2 AI calls per job (3 worst case).
6. **Plan validation**: clamp, snap to sentence boundaries, sort, merge duplicates/overlaps, trim to length; reject → regenerate once with feedback → labelled deterministic fallback.
7. **FFmpeg render**: word-accurate cuts, long pauses shortened (not removed), 9:16 crop following the speaker, burned-in captions (≤ 4 words, safe margins), optional music ~18 dB under speech, loudness-normalised, H.264/AAC MP4. The output file is re-probed and rejected if wrong.
8. UI: upload → live stage list → result (player, original vs edited info, what-was-kept list, download). Resumes after refresh.
9. Housekeeping: old jobs auto-deleted after `RETENTION_DAYS` (7).

## Verification evidence
- **68 automated tests pass** (`cd backend && ..\tools\uv\uv.exe run pytest`), including real FFmpeg renders for portrait, square, 480p, 720p, 1080p sources; failure paths (ffmpeg crash, junk output, unexpected exception hides internals); interrupted-job requeue; path-traversal attempts; music audibility measured by band energy.
- **Live run** (real Whisper + real Gemini) on a 60 s narrated sample → 23–41 s vertical video. Frames inspected: captions bold, readable, inside safe area.
- **Caption sync measured**: transcribing the rendered audio, 24/24 caption pages matched speech, mean offset −0.01 s (worst 0.37 s).
- **Browser**: full flow through the real UI incl. page refresh mid-job; player loads the 1080×1920, 41 s file.
- **Performance**: 10-minute 1080p source, 10 cuts → pipeline (excluding Whisper) 30 s. Whisper ≈ 2× real time, so ~5 min for 10 min of video.
- Frontend: typecheck, lint and production build pass.

## Not verified (be aware)
- **Real talking-head footage.** All media so far is synthetic (test patterns + Windows text-to-speech), so nothing has yet judged: crop quality on a real face, Gemini's `speaker_focus_x` accuracy, accents/Taglish transcription, background noise.
- **Gemini free-tier limits** are only visible in your AI Studio dashboard; we use few calls, but heavy use could hit 429 (the app then falls back to a basic cut and says so).
- **Music** was verified with a generated tone, not a real track.
- **GPU** (RTX 2050) isn't used; CPU is fine for the MVP.

## Known limitations
- Clips keep chronological order (no re-ordering the hook to the front).
- 9:16 is a centre/focus **crop**; 720p sources are upscaled ~2.7× (soft). 1080p+ sources look better.
- Captions are plain pages (no word-by-word animation); no face tracking, B-roll, transitions, or accounts.
- Frame sampling is even, not content-aware beyond scene-cut hints.
- Repo is in OneDrive; `tools/`, `.venv/`, `node_modules/`, `storage/` get synced – consider moving the project.
- Nothing is committed to git yet.
- Preview launcher sometimes races when restarting the backend (wait a few seconds after stopping).

## Next recommended action
1. Run the app with one or two **real** talking-head MP4s and review the result; tune `WHISPER_MODEL` / `WHISPER_LANGUAGE` (e.g. `tl`) and crop if needed.
2. Add a real music file you may use to `storage/music/`.
3. Commit to git (`git add -A` is safe: secrets, media and tools are ignored).
