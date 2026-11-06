"""Delete old jobs (uploads, temp files, renders, DB rows) so the disk doesn't fill up."""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import db
from .config import get_settings

log = logging.getLogger(__name__)


def purge_old_jobs(retention_days: int) -> int:
    """Remove finished/failed jobs older than `retention_days`. Returns how many."""
    if retention_days <= 0:
        return 0
    cfg = get_settings()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat(timespec="seconds")
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, upload_path, output_path FROM jobs "
            "WHERE status IN ('completed','failed') AND updated_at < ?", (cutoff,)
        ).fetchall()
        for r in rows:
            for p in (r["upload_path"], r["output_path"]):
                if p:
                    Path(p).unlink(missing_ok=True)
            shutil.rmtree(cfg.temp_dir / r["id"], ignore_errors=True)
            (cfg.subtitles_dir / f"{r['id']}.ass").unlink(missing_ok=True)
            conn.execute("DELETE FROM jobs WHERE id = ?", (r["id"],))
    if rows:
        log.info("retention: removed %d job(s) older than %d days", len(rows), retention_days)
    return len(rows)
