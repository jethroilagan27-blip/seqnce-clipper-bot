from __future__ import annotations

from app.editing import captions as cap
from app.editing.cuts import Cut, build_cuts, total_duration
from app.editing.ffgraph import build_filtergraph, compute_crop
from app.plan.schema import Clip, EditingPlan, Silence


def words(*spec):
    """spec: (start, end, word)"""
    return [{"start": s, "end": e, "word": w} for s, e, w in spec]


def plan(clips, remove_silence=True, max_pause=0.6):
    return EditingPlan(
        target_duration=30,
        clips=[Clip(id=f"c{i}", start=s, end=e, purpose="main_content") for i, (s, e) in enumerate(clips, 1)],
        silence=Silence(remove=remove_silence, max_pause_s=max_pause),
    )


# ---------- cuts ----------
W = words((1.0, 1.4, "Hello"), (1.5, 2.0, "there"), (4.0, 4.5, "after"), (4.6, 5.0, "pause."), (5.2, 5.6, "Next"))


def test_cut_pads_but_never_enters_neighbouring_words():
    cuts = build_cuts(plan([(1.0, 5.0)], remove_silence=False), W, 10.0)
    assert len(cuts) == 1
    assert 0.88 <= cuts[0].start <= 1.0  # lead-in before "Hello" (nothing before it)
    assert cuts[0].end <= (5.0 + 5.2) / 2 + 1e-6  # tail stops midway to the next word


def test_long_pause_is_shortened_not_removed():
    cuts = build_cuts(plan([(1.0, 5.0)]), W, 10.0)
    assert len(cuts) == 2  # split at the 2.0 s gap between "there" and "after"
    skipped = cuts[1].start - cuts[0].end  # source time left out of the output
    assert abs(skipped - (2.0 - 0.35)) < 0.01  # 2.0 s gap shortened to a 0.35 s beat
    # the output still keeps a natural beat of silence around the cut
    assert cuts[0].end - 2.0 >= 0.1 and 4.0 - cuts[1].start >= 0.1
    assert abs(total_duration(cuts) - (cuts[0].duration + cuts[1].duration)) < 1e-9


def test_short_pauses_are_left_alone():
    cuts = build_cuts(plan([(4.0, 5.6)]), W, 10.0)
    assert len(cuts) == 1


def test_out_start_accumulates():
    cuts = build_cuts(plan([(1.0, 2.0), (4.0, 5.6)]), W, 10.0)
    assert cuts[0].out_start == 0
    assert abs(cuts[1].out_start - cuts[0].duration) < 1e-2


def test_clip_without_words_is_used_as_is():
    cuts = build_cuts(plan([(6.0, 8.0)]), W, 10.0)
    assert (cuts[0].start, cuts[0].end) == (6.0, 8.0)


def test_cut_never_exceeds_video_duration():
    cuts = build_cuts(plan([(4.0, 5.6)]), W, 5.5)
    assert cuts[0].end <= 5.5


# ---------- captions ----------
def test_remap_words_to_output_time():
    cuts = [Cut(10.0, 12.0, 0.0), Cut(20.0, 22.0, 2.0)]
    src = words((10.5, 11.0, "a"), (15.0, 15.5, "skipped"), (20.5, 21.0, "b"))
    out = cap.remap_words(src, cuts)
    assert [w["word"] for w in out] == ["a", "b"]
    assert out[0]["start"] == 0.5 and out[1]["start"] == 2.5


def test_pages_have_few_words_and_break_on_sentences_and_gaps():
    ws = words(*[(i * 0.4, i * 0.4 + 0.3, w) for i, w in enumerate("one two three four five six. seven eight".split())])
    pages = cap.build_pages(ws, max_words=4)
    assert all(len(p.text.split()) <= 4 for p in pages)
    assert pages[0].text == "one two three four"
    assert any(p.text.endswith("six.") for p in pages)
    assert not any("six. seven" in p.text for p in pages)  # sentence end starts a new page


def test_pages_do_not_overlap_and_are_ordered():
    ws = words(*[(i * 0.5, i * 0.5 + 0.4, f"w{i}") for i in range(20)])
    pages = cap.build_pages(ws, 3)
    for a, b in zip(pages, pages[1:]):
        assert a.end <= b.start + 1e-6 and a.start < b.start


def test_ass_output_is_safe_and_well_formed():
    pages = [cap.Page(0.0, 1.0, "hello {\\an8} world\nline")]
    ass = cap.render_ass(pages)
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass
    line = [l for l in ass.splitlines() if l.startswith("Dialogue")][0]
    assert "{" not in line.split(",,", 1)[1] and "\\" not in line.split(",,", 1)[1]
    assert line.startswith("Dialogue: 0,0:00:00.00,0:00:01.00,")
    assert "MarginV" in ass and ",86,86,422," in ass  # safe margins: 8 % sides, ~22 % bottom


# ---------- crop + graph ----------
def test_crop_landscape_follows_speaker_and_stays_inside():
    c = compute_crop(1920, 1080, 0.5)
    assert (c.w, c.h) == (606, 1080) and c.x == 657 - 657 % 2 or abs(c.x - (960 - 303)) <= 2
    left = compute_crop(1920, 1080, 0.0)
    right = compute_crop(1920, 1080, 1.0)
    assert left.x == 0 and right.x + right.w <= 1920
    assert c.w % 2 == 0 and c.h % 2 == 0 and c.x % 2 == 0


def test_crop_tall_source_crops_height():
    c = compute_crop(1080, 2400, 0.5)
    assert c.w == 1080 and c.h == 1920 and c.y == 240


def test_crop_exact_9_16_is_full_frame():
    c = compute_crop(1080, 1920, 0.3)
    assert (c.w, c.h, c.x, c.y) == (1080, 1920, 0, 0)


def test_graph_structure():
    cuts = [Cut(1.0, 3.0, 0.0), Cut(5.0, 8.0, 2.0)]
    g = build_filtergraph(cuts, compute_crop(1280, 720, 0.5), captions=True, music=True, music_volume=0.12, total=5.0)
    assert "concat=n=2:v=1:a=1" in g
    assert "trim=start=1.000:end=3.000" in g and "atrim=start=5.000:end=8.000" in g
    assert "ass=captions.ass" in g and "[1:a]" in g and "amix" in g and "loudnorm" in g
    assert "[vout]" in g and "[aout]" in g
    plain = build_filtergraph(cuts, compute_crop(1280, 720, 0.5), captions=False, music=False, music_volume=0.12, total=5.0)
    assert "ass=" not in plain and "amix" not in plain and "[1:a]" not in plain
