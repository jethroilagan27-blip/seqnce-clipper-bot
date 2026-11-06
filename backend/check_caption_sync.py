"""Dev check: are burned-in captions in sync with the speech in the rendered video?

    ../tools/uv/uv.exe run python check_caption_sync.py ../samples/live_output.mp4 ../samples/live_captions.ass

Transcribes the *rendered* audio with Whisper and compares each caption page's start
time with when its first word is actually spoken.
"""
import re, subprocess, sys, tempfile, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
from app.config import get_settings
from app.pipeline.transcribe import _get_model, _load_wav

video, ass = Path(sys.argv[1]), Path(sys.argv[2])
wav = Path(tempfile.mkdtemp()) / "a.wav"
subprocess.run([get_settings().ffmpeg, "-y", "-loglevel", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)], check=True)
segs, _ = _get_model().transcribe(_load_wav(str(wav)), word_timestamps=True, vad_filter=True, language="en")
spoken = [(w.start, w.word.strip().lower().strip(".,!?")) for s in segs for w in s.words]

def secs(t):
    h, m, s = t.split(":"); return int(h) * 3600 + int(m) * 60 + float(s)

pages = []
for line in ass.read_text(encoding="utf-8").splitlines():
    if line.startswith("Dialogue"):
        f = line.split(",", 9); pages.append((secs(f[1]), secs(f[2]), f[9]))

offsets = []
cursor = 0
for start, end, text in pages:
    first = re.sub(r"[^\w']", "", text.split()[0].lower())
    # find the next spoken occurrence of the page's first word from where we left off
    for i in range(cursor, len(spoken)):
        if re.sub(r"[^\w']", "", spoken[i][1]) == first and abs(spoken[i][0] - start) < 2.0:
            offsets.append(start - spoken[i][0]); cursor = i + 1; break
print(f"{len(offsets)}/{len(pages)} caption pages matched to speech in the rendered audio")
if offsets:
    print(f"caption lead(+)/lag(-) vs speech: mean {sum(offsets)/len(offsets):+.2f}s, worst {max(offsets, key=abs):+.2f}s")
    mean_abs = sum(abs(o) for o in offsets) / len(offsets)
    sys.exit(0 if mean_abs < 0.15 and max(abs(o) for o in offsets) < 0.6 and len(offsets) >= 0.7 * len(pages) else 1)
sys.exit(1)
