# Studio: heavy, scripted edits

Studio makes longer videos from a script: many scenes, each with your own clips, pictures, voice-over, music and text. **Everything the video shows or plays is uploaded by the user**; Seqnce does not supply any footage, music or pictures.

It lives at `/studio` (a third tab next to "Edit with video" and "Edit with photos") and is switched on **per account**.

## What a scene can contain

| Tool | What it does |
|---|---|
| Clips and pictures in order | Trim each clip (start, how long), slow zoom, fill the frame with a blurred copy / cut to fill / black bars, mute or turn down the clip's own sound |
| Voice-over | Plays from the start of the scene (or after a wait). A voice-over longer than the clips holds the last clip |
| Spread under the voice-over | Gives every clip / picture an equal share of the voice-over's length (montage) |
| Music in the scene | Starts anywhere in the track, volume, fade in / out, **lowers by itself while the voice-over speaks** |
| Music under the whole video | Loops, fades out at the end, lowers by itself while anything speaks |
| Text | Drag it where you want; colour, size, outline / box / plain, when it shows, **your own font**, slow zoom in / out (title reveals) |
| Text card | A scene on black with a big text (a question, a title) |
| Pictures over a scene | Posters, flags, maps, screenshots or small clips that appear for a while: size, place, from / to, fade, pop-in or slow zoom. Transparent PNGs keep their see-through parts |
| Highlights | Box / highlighter, circle, **map pin** that drops in. Place by dragging |
| Narrow-frame opening | The scene starts as a narrow band that opens to the full frame |
| Grid | Several clips on screen at once (for example 3 x 2). All cells start together; they can appear after some dark seconds while a voice-over already plays |
| Rolling credits | One line per row; `# ` starts a heading; scrolls up the screen |
| Transitions | Fade in from black, fade out to black, cross-fade between scenes, straight cut |
| Loudness | The finished video's volume is evened out (can be turned off) |

Previews: "Preview this scene" and "Quick preview of everything" make small, rough versions quickly and cost nothing. "Make the finished video" renders at the account's quality (720p or 1080p) and counts against the daily limit.

## Per-account features and plans

Every account has a **plan** (`standard`, `pro`, `max`) plus **overrides** for single features. What each plan contains is in one place: `backend/app/features.py`. **The numbers there are starting values; the pricing and what each plan includes are still to be decided.**

Features (all switched on / limited per account): `studio`, `studio_max_projects`, `studio_max_scenes`, `studio_max_minutes`, `studio_max_height`, `studio_max_assets`, `studio_max_storage_mb`, `studio_max_file_mb`, `studio_renders_per_day`, `studio_crossfade`, `studio_text_effects`, `studio_overlays`, `studio_grid`, `studio_credits`, `studio_ducking`, `studio_auto_montage`, `studio_custom_fonts`.

New accounts (including open sign-ups) are on **standard**, which has Studio **off**. Admins and local use (accounts off) get everything.

From `backend/` (`uv run python -m app.admin ...`):

```
set-plan EMAIL pro                       put the account on a plan
set-feature EMAIL studio on              change ONE feature for ONE account
set-feature EMAIL studio_max_height 720  ...numbers work too
set-feature EMAIL studio_grid default    undo that change (back to what the plan says)
features EMAIL                           show what the account can use; * marks values changed by hand
users                                    the plan column shows `pro*` when something was changed by hand
```

The server checks these on every request (the website only hides or locks things), and refuses a video that is too long or a project that uses a tool the account doesn't have *before* it uses up a daily render.

## Limits worth knowing

- **Upload size:** one file per request, up to the account's `studio_max_file_mb`. Through Cloudflare's free plan a single request can't exceed 100 MB, so the public build allows 95 MB. Bigger files need chunked uploads (not built).
- **Fonts:** Studio ships no fonts. Upload a `.ttf` / `.otf` (needs `studio_custom_fonts`) and choose it by name. On Linux servers the default "Arial" falls back to a similar font; install `fonts-liberation` for a close match.
- **Rendering is on the server's CPU**, one project at a time. A 5-6 minute 1080p video takes a few minutes. Projects are kept at least 30 days after the last change.
- **Map highlights:** you upload the map picture; Seqnce adds boxes, circles and pins on it. It does not draw countries by itself. For exact country shapes, upload a see-through PNG per country and lay it over the map.
- Needs FFmpeg 6.1 or newer (the Ubuntu 24.04 package is fine).

## API

All under `/api/studio` and needing the `studio` feature: `GET /info`, `GET|POST /projects`, `GET|DELETE /projects/{id}`, `PUT /projects/{id}/doc` (the whole scene document), `POST /projects/{id}/assets` (one or a few files), `DELETE /projects/{id}/assets/{asset}`, `POST /projects/{id}/render` (`{"kind": "final" | "preview", "scene_id": null | "..."}`), and the files the page loads itself: `.../assets/{asset}/thumb|file`, `.../preview?scene=`, `.../video`, `.../download`. The document's shape is `backend/app/studio/schemas.py`.

## Removing Studio

Studio is self-contained: delete `backend/app/studio/`, `backend/tests/test_studio*.py`, the lines marked `# studio` in `backend/app/main.py`, the `studio_*` features in `backend/app/features.py` (and the `studio` quota kind in `auth.py`), `frontend/app/studio/`, `frontend/components/studio/`, `frontend/lib/studio*.ts` and the Studio tab in `Shell.tsx`.
