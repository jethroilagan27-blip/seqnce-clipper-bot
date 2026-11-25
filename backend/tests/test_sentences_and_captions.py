"""Cuts fall on whole sentences, and misheard captions can be corrected."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.editing import sentences
from app.editing.captions import apply_fixes, build_pages
from app.editing.fixes import CaptionFix
from app.pipeline.prepare import job_temp_dir
from app.plan.validate import repair_and_validate


def _words(text: str, start: float = 0.0, per: float = 0.3, pauses: dict[int, float] | None = None) -> list[dict]:
    """One word every `per` seconds; pauses[i] = extra silence before word i."""
    out, at = [], start
    for i, word in enumerate(text.split()):
        at += (pauses or {}).get(i, 0.0)
        out.append({"start": round(at, 2), "end": round(at + per, 2), "word": word})
        at += per
    return out


def _segments(words: list[dict], size: int = 7) -> list[dict]:
    """Like Whisper: chunks that pay no attention to sentences."""
    return [
        {"start": g[0]["start"], "end": g[-1]["end"], "text": " ".join(w["word"] for w in g), "words": g}
        for g in (words[i:i + size] for i in range(0, len(words), size))
    ]


# ---------- sentences ----------

def test_sentences_end_at_punctuation_not_where_the_chunks_end():
    words = _words("I want to start vlogging this year. Do not be afraid of embarrassment. It will be fine in the end.")
    got = sentences.build(_segments(words))
    assert [s["text"] for s in got] == [
        "I want to start vlogging this year.", "Do not be afraid of embarrassment.", "It will be fine in the end."]
    assert got[0]["start"] == 0.0 and got[1]["start"] == words[7]["start"] and got[-1]["end"] == words[-1]["end"]


def test_a_real_pause_ends_a_sentence_and_a_dangling_so_moves_to_the_next():
    words = _words("I hope you can hear me by the way so that is why I have not been vlogging", pauses={10: 1.2})
    first, second = [s["text"] for s in sentences.build(_segments(words))]
    assert first == "I hope you can hear me by the way"  # "so" came right before the breath
    assert second.startswith("so that is why")
    tagalog = _words("Gusto ko sanang mag vlog ngayong taon kasi nahihiya ako sa harap ng tao", pauses={8: 1.0})
    a, b = [s["text"] for s in sentences.build(_segments(tagalog))]
    assert a.endswith("ngayong taon") and b.startswith("kasi nahihiya")


def test_long_rambling_is_split_at_its_longest_breath():
    words = _words(" ".join(f"word{i}" for i in range(80)), per=0.35, pauses={31: 0.45, 55: 0.3})
    got = sentences.build(_segments(words))
    assert len(got) >= 2 and got[1]["text"].startswith("word31")
    assert all(s["end"] - s["start"] <= sentences.MAX_S + 3 for s in got)
    no_breath = _words(" ".join(f"w{i}" for i in range(60)), per=0.35)
    assert len(sentences.build(_segments(no_breath))) == 1  # better one long stretch than a cut mid-phrase


def test_short_scraps_join_their_neighbour_and_nothing_is_lost():
    words = _words("and then we went to the market yeah and bought some fruit.", pauses={8: 0.7, 9: 0.7})
    got = sentences.build(_segments(words))
    assert " ".join(s["text"] for s in got) == " ".join(w["word"] for w in words)
    assert all(a["end"] <= b["start"] for a, b in zip(got, got[1:]))


def test_building_again_changes_nothing_and_missing_word_times_are_left_alone():
    words = _words("One two three. Four five six seven. Eight nine ten.", pauses={3: 0.8})
    once = sentences.build(_segments(words, 4))
    assert sentences.build(once) == once
    bare = [{"start": 0, "end": 2, "text": "no word timings"}]
    assert sentences.build(bare) == bare and sentences.build([]) == []


def test_word_tails_whisper_splits_off_are_put_back():
    from app.pipeline.transcribe import _words

    raw = [SimpleNamespace(start=s, end=s + 0.2, word=w) for s, w in
           [(0.0, " love"), (0.2, " y"), (0.4, "'all"), (0.6, " vlog"), (0.8, "-style"), (1.0, " 'quoted'"), (1.2, " -")]]
    got = _words(raw)
    assert [w["word"] for w in got] == ["love", "y'all", "vlog-style", "'quoted'", "-"]
    assert got[1]["start"] == 0.2 and got[1]["end"] == 0.6


# ---------- cuts fall on sentences ----------

SENTENCES = [{"start": float(a), "end": float(b), "text": "x y z w"} for a, b in ((0, 6), (6.2, 12), (12.4, 19), (19.5, 26), (26.2, 31))]


def _clip(a: float, b: float):
    return SimpleNamespace(start=a, end=b, purpose="main_content", reason="r")


@pytest.mark.parametrize("asked,got", [
    ((8.0, 16.0), (6.2, 19.0)),     # inside sentences: out to their edges
    ((11.5, 19.6), (12.4, 19.0)),   # only the tail of one / barely into the next: not taken
    ((6.2, 19.0), (6.2, 19.0)),     # already on edges
    ((12.2, 19.2), (12.4, 19.0)),   # in the silences: snapped
])
def test_a_clip_never_starts_or_ends_inside_a_sentence(asked, got):
    clips, _ = repair_and_validate([_clip(*asked)], 31.0, SENTENCES, 10.5)
    assert (clips[0].start, clips[0].end) == got


# ---------- correcting captions ----------

def test_a_correction_replaces_only_its_own_words():
    words = _words("my name is Huan Dela Crus and welcome")
    fixed = apply_fixes(words, [CaptionFix(start=0.0, end=words[5]["end"], text="my name is Juan Dela Cruz")])
    assert [w["word"] for w in fixed] == "my name is Juan Dela Cruz and welcome".split()
    assert [w["start"] for w in fixed] == [w["start"] for w in words]  # same number of words: timing untouched


def test_adding_or_removing_words_shares_the_same_stretch_of_time():
    words = _words("gonna start soon then more")
    fixed = apply_fixes(words, [CaptionFix(start=0.0, end=words[2]["end"], text="I am going to start soon")])
    new = fixed[:6]
    assert [w["word"] for w in new] == "I am going to start soon".split()
    assert new[0]["start"] == 0.0 and new[-1]["end"] == pytest.approx(words[2]["end"], abs=0.01)
    assert all(a["end"] <= b["start"] + 0.001 for a, b in zip(fixed, fixed[1:]))
    assert fixed[6]["word"] == "then"
    hidden = apply_fixes(words, [CaptionFix(start=0.0, end=words[2]["end"], text="")])
    assert [w["word"] for w in hidden] == ["then", "more"] and build_pages(hidden, 4)
    assert apply_fixes(words, [CaptionFix(start=500, end=501, text="nowhere")]) == words


def test_a_correction_is_plain_one_line_text_with_sensible_times():
    assert CaptionFix(start=0, end=1, text="  two\nlines\t\x00 here ").text == "two lines here"
    for bad in ({"start": 2, "end": 1, "text": "x"}, {"start": -1, "end": 1, "text": "x"}, {"start": 0, "end": 1, "text": "x" * 700}):
        with pytest.raises(ValueError):
            CaptionFix(**bad)


def _finished(c: TestClient, path: Path) -> str:
    with path.open("rb") as f:
        job_id = c.post("/api/videos/upload", files={"file": ("a.mp4", f, "video/mp4")}).json()["job_id"]
    _wait(c, job_id)
    return job_id


def _wait(c: TestClient, job_id: str, version: int | None = None) -> dict:
    for _ in range(300):
        job = c.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("completed", "failed") and not job["revising"] and (version is None or job["current_version"] == version or job["error"]):
            return job
        time.sleep(0.2)
    raise AssertionError("job did not finish")


def test_correcting_captions_shows_in_the_preview_and_the_rendered_video(client: TestClient, sample_video: Path):
    job_id = _finished(client, sample_video)  # the stand-in transcriber hears "Hello world"
    fix = {"start": 0.0, "end": 3.0, "text": "Kumusta {mundo}"}
    spec = client.post(f"/api/jobs/{job_id}/timeline", json={"edit": {"caption_fixes": [fix]}}).json()
    assert " ".join(p["text"] for p in spec["pages"]) == "Kumusta {mundo}"
    assert client.post(f"/api/jobs/{job_id}/revisions", json={"edit": {"caption_fixes": [fix]}}).status_code == 202
    job = _wait(client, job_id, version=2)
    assert job["status"] == "completed" and job["current_version"] == 2, job["error"]
    ass = (job_temp_dir(job_id) / "captions.ass").read_text(encoding="utf-8")
    assert "Kumusta (mundo)" in ass and "Hello" not in ass  # braces can't smuggle in subtitle commands
    v2 = client.get(f"/api/jobs/{job_id}/versions").json()["versions"][1]
    assert "corrected the captions" in v2["message"] and v2["plan"]["captions"]["fixes"] == [fix]
    assert {"field": "Caption text", "before": "0 corrected", "after": "1 corrected"} in v2["changes"]["settings"]
    # what Whisper heard is kept, and taking the correction back restores it
    assert client.get(f"/api/jobs/{job_id}/analysis").json()["transcript"]["segments"][0]["text"] == "Hello world"
    assert client.post(f"/api/jobs/{job_id}/revisions", json={"edit": {"caption_fixes": []}}).status_code == 202
    _wait(client, job_id, version=3)
    v3 = client.get(f"/api/jobs/{job_id}/versions").json()["versions"][2]
    assert "fixes" not in v3["plan"]["captions"]
    assert "Hello" in (job_temp_dir(job_id) / "captions.ass").read_text(encoding="utf-8")


def test_bad_corrections_are_refused(client: TestClient, sample_video: Path):
    job_id = _finished(client, sample_video)
    for bad in ([{"start": 2, "end": 1, "text": "x"}], [{"start": 0, "end": 1, "text": "x" * 900}], [{"start": 0, "end": 1}] * 201):
        r = client.post(f"/api/jobs/{job_id}/revisions", json={"edit": {"caption_fixes": bad}})
        assert r.status_code == 422, str(bad)[:80]
    assert client.post(f"/api/jobs/{job_id}/revisions", json={"edit": {"caption_fixes": []}}).status_code == 422  # changes nothing
