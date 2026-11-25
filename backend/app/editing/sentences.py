"""Real sentences out of Whisper's output. Pure functions on the transcript.

Whisper's "segments" are chunks of audio, not sentences: in casual speech most of them stop in the middle of one, so a
cut made on a segment edge starts or ends mid-thought. Sentences are rebuilt from the words: one ends at . ? ! or at a
real pause; very long ones are split at their longest breath; a connecting word left dangling before a pause ("...so")
belongs to what follows. The result has the same shape as Whisper's segments, and building it again changes nothing.
"""

from __future__ import annotations

import re
from typing import Any, Sequence

PAUSE_S = 0.55  # silence this long ends a sentence even without punctuation
SOFT_PAUSE_S = 0.2  # the shortest breath a long sentence may be split at
MAX_S = 14.0  # longer than this is split, so there is always somewhere to cut
MIN_S = 1.2  # shorter than this joins its neighbour (unless it is a real sentence of its own)

END = re.compile(r"[.?!…][\"')\]]*$")
COMMA = re.compile(r"[,;:]$")
# words that lead into what comes next: a sentence must not end on one just because the speaker drew breath
CONNECTORS = {"and", "so", "but", "because", "cause", "or", "um", "uh", "the", "a", "to", "if", "when", "like", "that", "of",
              "kasi", "tapos", "pero", "at", "kaya", "yung", "ang", "na", "sa", "ng"}

Word = dict[str, Any]


def _bare(word: str) -> str:
    return re.sub(r"[^\w']", "", word).lower()


def _split_long(words: list[Word]) -> list[list[Word]]:
    if len(words) < 4 or words[-1]["end"] - words[0]["start"] <= MAX_S:
        return [words]
    best, best_score = None, 0.0
    for i in range(2, len(words) - 1):  # split before word i, never leaving a single word alone
        gap = words[i]["start"] - words[i - 1]["end"]
        comma = bool(COMMA.search(words[i - 1]["word"]))
        if gap < SOFT_PAUSE_S and not comma:
            continue
        if _bare(words[i - 1]["word"]) in CONNECTORS:
            continue
        # prefer a long breath, and prefer the middle
        middle = 1 - abs(i / len(words) - 0.5)
        score = (gap + (0.25 if comma else 0.0) + 0.05) * middle
        if score > best_score:
            best, best_score = i, score
    if best is None:
        return [words]  # no breath to split at: better one long sentence than a cut mid-phrase
    return _split_long(words[:best]) + _split_long(words[best:])


def group_words(words: Sequence[Word]) -> list[list[Word]]:
    groups: list[list[Word]] = []
    current: list[Word] = []
    for i, w in enumerate(words):
        current.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if nxt is None:
            break
        ended = bool(END.search(w["word"]))
        paused = nxt["start"] - w["end"] >= PAUSE_S
        if ended or (paused and _bare(w["word"]) not in CONNECTORS):
            groups.append(current)
            current = []
        elif paused and len(current) > 1:  # "... by the way, so <breath>": "so" starts the next sentence
            groups.append(current[:-1])
            current = [w]
    if current:
        groups.append(current)

    groups = [part for g in groups for part in _split_long(g)]

    # tiny scraps ("yeah", "um okay") join the neighbour they are closest to, unless they are sentences of their own
    merged: list[list[Word]] = []
    for g in groups:
        if merged:
            prev = merged[-1]
            gap = g[0]["start"] - prev[-1]["end"]
            tiny_prev = prev[-1]["end"] - prev[0]["start"] < MIN_S and not END.search(prev[-1]["word"])
            tiny_this = g[-1]["end"] - g[0]["start"] < MIN_S and not END.search(prev[-1]["word"])
            if (tiny_prev or tiny_this) and gap < 1.0 and g[-1]["end"] - prev[0]["start"] <= MAX_S:
                merged[-1] = prev + g
                continue
        merged.append(g)
    return merged


def build(segments: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Transcript segments -> sentences. Segments without word timings (nothing to go on) are returned unchanged."""
    if not segments or not all(s.get("words") for s in segments):
        return list(segments)
    words = sorted((w for s in segments for w in s["words"]), key=lambda w: w["start"])
    return [
        {"start": g[0]["start"], "end": max(w["end"] for w in g), "text": " ".join(w["word"] for w in g), "words": g}
        for g in group_words(words)
    ]
