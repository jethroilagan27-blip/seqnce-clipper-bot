"""Keeps HTTPS working next to antivirus software.

Programs that scan HTTPS (Avast, AVG) can give a process the setting SSLKEYLOGFILE, pointing at a device of their own.
That device can stop accepting it, for example in a server that outlives the program that started it. Python opens the
file for every new secure connection, so from then on every AI call fails with "permission denied" or "not found".
"""

from __future__ import annotations

import logging
import os
import ssl

log = logging.getLogger(__name__)


def drop_unusable_key_log() -> None:
    """Forget SSLKEYLOGFILE only when it cannot be opened. While it works it is left alone."""
    path = os.environ.get("SSLKEYLOGFILE")
    if not path:
        return
    try:
        ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).keylog_filename = path  # exactly what a new connection would do
    except OSError as exc:
        os.environ.pop("SSLKEYLOGFILE", None)
        log.warning("SSLKEYLOGFILE can't be opened (%s): ignoring it so secure connections keep working", type(exc).__name__)
