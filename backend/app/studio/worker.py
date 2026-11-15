"""Background thread that renders queued Studio projects, one at a time."""

from __future__ import annotations

import logging
import threading

from ..services import media
from . import engine, store

log = logging.getLogger(__name__)
POLL_INTERVAL_S = 1.0


def _run(project: dict) -> None:
    pid = project["id"]
    kind = project.get("render_kind") or "final"
    scene = project.get("render_scene")
    log.info("studio %s: rendering (%s%s)", pid, kind, f", scene {scene}" if scene else "")

    last = -1

    def on_progress(pct: int) -> None:
        nonlocal last
        if pct > last:
            last = pct
            store.update(pid, progress=pct)

    def on_stage(text: str) -> None:
        store.update(pid, stage_text=text)

    try:
        info = engine.render(pid, kind, scene, on_progress, on_stage)
        path = info.pop("path")
        if kind == "final":
            store.update(pid, status="completed", progress=100, stage_text=None, error=None, output_path=path, output_meta_json=info)
        else:
            store.update(pid, status="completed", progress=100, stage_text=None, error=None, preview_path=path, preview_scene=scene or "")
        log.info("studio %s: done (%.1fs)", pid, info["duration"])
    except (engine.StudioError, media.MediaError) as exc:
        log.error("studio %s failed: %s", pid, exc)
        store.update(pid, status="failed", stage_text=None, error=str(exc))
    except Exception:
        log.exception("studio %s crashed", pid)
        store.update(pid, status="failed", stage_text=None, error="Something went wrong while making the video. Check the server log.")


class StudioWorker:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="studio-worker", daemon=True)

    def start(self) -> None:
        n = store.requeue_interrupted()
        if n:
            log.warning("re-queued %d Studio project(s) interrupted by a previous shutdown", n)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                project = store.claim_next()
            except Exception:
                log.exception("studio worker could not read its queue")
                self._stop.wait(POLL_INTERVAL_S * 5)
                continue
            if project is None:
                self._stop.wait(POLL_INTERVAL_S)
                continue
            _run(project)
