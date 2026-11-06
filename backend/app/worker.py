"""Background worker: one thread that drains the SQLite job queue.

Why a thread and not Celery/Redis: one machine, one job at a time (video
rendering is CPU/GPU-bound anyway), and SQLite already is our source of truth.
"""

from __future__ import annotations

import logging
import threading

from . import db
from .pipeline.runner import run_job

log = logging.getLogger(__name__)

POLL_INTERVAL_S = 1.0


class Worker:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="job-worker", daemon=True)

    def start(self) -> None:
        n = db.requeue_interrupted_jobs()
        if n:
            log.warning("re-queued %d job(s) interrupted by a previous shutdown", n)
        self._thread.start()
        log.info("worker started")

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                job = db.claim_next_job()
            except Exception:
                log.exception("worker could not read the job queue")
                self._stop.wait(POLL_INTERVAL_S * 5)
                continue
            if job is None:
                self._stop.wait(POLL_INTERVAL_S)
                continue
            run_job(job)  # handles its own errors
