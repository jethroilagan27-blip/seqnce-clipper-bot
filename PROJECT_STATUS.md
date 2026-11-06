# Project Status

**Product name:** Seqnce (renamed from "ClipForge" on 2026-11-06; the repo folder / GitHub repo name `bot-clip` is unchanged).
**MVP (Days 1–7):** done · **Post-MVP roadmap** (user-requested 2026-11-06):
1. ✅ **Hook title + instructions box** – big coloured headline in the upper part for the first ~4 s (text and colour chosen by the AI, cleaned/validated in Python); optional free-text instructions fed to the planner.
2. ✅ **Editable plans, versions, re-render, chat revisions, clip diff.** Every render is a version (v1, v2…); chat messages re-plan with Gemini from the saved transcript (1 call + re-render); hand edits (hook text/colour/on-off, captions, remove clips) need no AI; "go back to vX" is instant; the UI shows a chat panel next to the player, version tabs, and added/removed/trimmed badges. A failed change never loses the current version.
3. ✅ **Timeline editor + live preview.** The browser plays the ORIGINAL video as the edit (cuts, 9:16 crop, captions and hook drawn on top; the cut list and caption pages come from the renderer's own code via `POST /api/jobs/{id}/timeline`, so preview = render). Drag clip edges (snap to words, zoom, keyboard/±0.1 s nudges), click transcript sentences to cut/restore them, edit hook text/colour/duration and captions, then Apply (one render = one new version). While a video is still processing the transcript appears live, and the plan becomes a playable preview + timeline before the render finishes.

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
- **Frontend:** `npm test` (9 unit tests for the timeline helpers), typecheck, lint, production build.
- **111 backend tests pass** (78 at the MVP + 17 for versions/chat/manual/restore/failure/retention + 16 for manual clips, the timeline spec and a preview==render check). Live (real Whisper + Gemini `gemini-3.5-flash-lite`): chat "make it ~20 s and turn the hook red" cut 34 s → 18 s, hook red, diff correct. In the browser (step 2): hand edit (hook on + cyan + remove clip) produced v2 with the cyan hook burned in; a chat request while the AI was rate-limited showed a clear error and left v2 untouched.
- Earlier milestone: 78 tests (`cd backend && ..\tools\uv\uv.exe run pytest`), including real FFmpeg renders for portrait, square, 480p, 720p, 1080p sources; failure paths (ffmpeg crash, junk output, unexpected exception hides internals); interrupted-job requeue; path-traversal attempts; music audibility measured by band energy.
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
- Chat edits cannot re-order clips (chronological only), and cannot add things the editor doesn't support (B-roll, transitions, new captions styles) – the AI is told to say so. Trimming a clip to exact seconds by hand waits for the timeline editor (step 3).
- `gemini-3.5-flash` was rate-limited during testing (free tier); the AI-dependent checks ran on `gemini-3.5-flash-lite`. If chat edits report "rate-limited", wait a minute or set `GEMINI_MODEL=gemini-3.5-flash-lite` in `.env`.
- Hook title is shown only for the first ~4 s (duration not yet adjustable in the UI). Fallback (no-AI) plans have no hook, but you can add one by hand. Font is Arial Black/Arial via libass; non-Latin scripts / emoji are not supported in the hook.
- Preview launcher sometimes races when restarting the backend (wait a few seconds after stopping).

## Next recommended action
1. Run the app with one or two **real** talking-head MP4s and review the result; tune `WHISPER_MODEL` / `WHISPER_LANGUAGE` (e.g. `tl`) and crop if needed.
2. Add a real music file you may use to `storage/music/`.
3. Commit to git (`git add -A` is safe: secrets, media and tools are ignored).

- Step 3 checked in the browser: playback hops over cut-out gaps exactly where the spec says; dragging a clip edge snapped to a word and shortened the preview 24.6 s → 17.1 s; clicking a transcript sentence split a clip; Apply rendered v3 whose length (14.03 s) matched the preview (14.02 s) and the renderer cut list (14.02 s); the processing screen showed the transcript while the AI was working and a playable preview + timeline while the render was still running.
- Step 3 not verified: real talking-head footage; very long videos (the whole transcript with word timings is loaded into the browser); touch devices; browsers other than the one built into the app.
- Preview vs render differences: the preview draws captions/title with browser fonts (Arial-like) and plays the original, so tiny font/pixel differences are expected; cuts and caption timing are identical. Clip order stays chronological.
