"""Photo mode: turn a pile of photos (in order) + your music + your text into a video.

Self-contained on purpose. To remove the whole feature:
  1. delete this folder (backend/app/slideshow/) and backend/tests/test_slideshow.py,
  2. delete the "slideshow" lines in backend/app/main.py (marked),
  3. delete frontend/app/photos/ and frontend/components/photos/ and the mode switch in Shell.tsx.
The shared text overlay code (app/editing/overlays.py) is also used by video mode and stays.
"""

from __future__ import annotations

from . import store
from .api import router
from .worker import SlideshowWorker

_worker: SlideshowWorker | None = None


def start() -> None:
    """Create the tables and start the render thread (call after db.init_db())."""
    global _worker
    store.init_tables()
    _worker = SlideshowWorker()
    _worker.start()


def stop() -> None:
    if _worker is not None:
        _worker.stop()


def purge(retention_days: int) -> int:
    return store.purge_old(retention_days)


__all__ = ["router", "start", "stop", "purge"]
