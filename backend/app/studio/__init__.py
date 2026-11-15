"""Studio: heavy, scripted edits. Several scenes, each with your clips, pictures, voice-over, music and text.

Self-contained on purpose (like photo mode), and switched on per account with the "studio" feature
(app/features.py). To remove the whole feature:
  1. delete this folder (backend/app/studio/) and backend/tests/test_studio.py,
  2. delete the "studio" lines in backend/app/main.py (marked) and the "studio" feature and plan values in
     backend/app/features.py, auth.py (KINDS, limit_for) and admin.py,
  3. delete frontend/app/studio/ and frontend/components/studio/ and the Studio tab in Shell.tsx.
The shared text overlay code (app/editing/overlays.py) is also used by the other modes and stays.
"""

from __future__ import annotations

from . import store
from .api import router
from .worker import StudioWorker

_worker: StudioWorker | None = None


def start() -> None:
    """Create the tables and start the render thread (call after db.init_db())."""
    global _worker
    store.init_tables()
    _worker = StudioWorker()
    _worker.start()


def stop() -> None:
    if _worker is not None:
        _worker.stop()


def purge(retention_days: int) -> int:
    """Studio projects take days to finish, so they are kept at least 30 days after the last change."""
    return store.purge_old(max(retention_days, 30) if retention_days > 0 else 0)


__all__ = ["router", "start", "stop", "purge"]
