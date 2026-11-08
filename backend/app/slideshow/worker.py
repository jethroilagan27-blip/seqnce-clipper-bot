"""Background thread that renders queued photo projects, one at a time."""

from __future__ import annotations

import logging
import threading

from ..services import media
from . import engine, store

log = logging.getLogger(__name__)
POLL_INTERVAL_S = 1.0


def _run(project: dict) -> None:
    pid = project["id"]
    log.info("slideshow %s: rendering", pid)

    last = -1

    def on_progress(pct: int) -> None:
        nonlocal last
        if pct > last:
            last = pct
            store.update(pid, progress=pct)

    try:
        info = engine.render(pid, on_progress)
        path = info.pop("path")
        store.update(pid, status="completed", progress=100, error=None, output_path=path, output_meta_json=info)
        log.info("slideshow %s: done (%.1fs)", pid, info["duration"])
    except (engine.SlideshowError, media.MediaError) as exc:
        log.error("slideshow %s failed: %s", pid, exc)
        store.update(pid, status="failed", error=str(exc))
    except Exception:
        log.exception("slideshow %s crashed", pid)
        store.update(pid, status="failed", error="Something went wrong while making the video. Check the server log.")


class SlideshowWorker:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="slideshow-worker", daemon=True)

    def start(self) -> None:
        n = store.requeue_interrupted()
        if n:
            log.warning("re-queued %d photo project(s) interrupted by a previous shutdown", n)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                project = store.claim_next()
            except Exception:
                log.exception("slideshow worker could not read its queue")
                self._stop.wait(POLL_INTERVAL_S * 5)
                continue
            if project is None:
                self._stop.wait(POLL_INTERVAL_S)
                continue
            _run(project)
