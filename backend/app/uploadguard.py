"""Turn bad uploads away before their body is read.

FastAPI parses a multipart body before it runs any dependency, so without this a stranger could make
the server spool hundreds of MB to disk just to be told "please sign in". Every upload endpoint
registers its path and a size cap here; main.py applies them in one middleware.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Guard:
    pattern: re.Pattern[str]
    max_bytes: Callable[[], int]  # a function, so settings can change between requests (and in tests)


GUARDS: list[Guard] = []


def register(pattern: str, max_bytes: Callable[[], int]) -> None:
    GUARDS.append(Guard(re.compile(pattern), max_bytes))


def match(path: str) -> Guard | None:
    return next((g for g in GUARDS if g.pattern.match(path)), None)
