"""Each account's own Gemini API key.

With accounts on, the AI runs on the key of the person who asked, never on the server's key (apart from admins), so
nobody's usage is paid by someone else. The key is private:
- it is stored encrypted (Fernet: AES + a signature) with a secret that lives only in the server's storage folder (or
  AI_KEY_SECRET), tied to the account so a copied database row is useless for another account;
- after it is saved the server only ever reveals the last 4 characters;
- it is never written to the log (see GeminiProvider's scrubbing) and never sent anywhere but Google.
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
import threading
import time
from collections import defaultdict, deque

from cryptography.fernet import Fernet, InvalidToken

from . import db
from .config import get_settings

KEY_SHAPE = re.compile(r"^[A-Za-z0-9_.\-]{20,200}$")  # Google keys start "AIza" (older) or "AQ." (newer); be lenient about the rest
TRIES_PER_WINDOW = 10
WINDOW_S = 15 * 60
_tries: dict[int, deque[float]] = defaultdict(deque)
_lock = threading.Lock()


def _fernet() -> Fernet:
    cfg = get_settings()
    if cfg.ai_key_secret:
        raw = cfg.ai_key_secret.encode("utf-8")
    else:
        path = cfg.storage_dir / ".ai_key_secret"
        if path.is_file():
            raw = path.read_bytes()
        else:
            cfg.ensure_dirs()
            raw = secrets.token_bytes(32)
            path.write_bytes(raw)
            try:
                path.chmod(0o600)
            except OSError:
                pass  # Windows: best effort
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"seqnce-ai-key|" + raw).digest()))


def looks_valid(key: str) -> bool:
    return bool(KEY_SHAPE.match(key))


def too_many_tries(user_id: int) -> bool:
    """Saving a key checks it with Google: don't let one account hammer that."""
    now = time.time()
    with _lock:
        q = _tries[user_id]
        while q and now - q[0] > WINDOW_S:
            q.popleft()
        if len(q) >= TRIES_PER_WINDOW:
            return True
        q.append(now)
        return False


def reset_throttle() -> None:  # for tests
    with _lock:
        _tries.clear()


def save(user_id: int, key: str) -> str:
    """Store the key (encrypted) and return the hint that may be shown ("…x4Fz")."""
    token = _fernet().encrypt(f"{user_id}:{key}".encode("utf-8")).decode("ascii")
    hint = f"…{key[-4:]}"
    db.set_ai_key(user_id, token, hint)
    return hint


def load(user_id: int) -> str | None:
    row = db.get_ai_key(user_id)
    if row is None:
        return None
    try:
        plain = _fernet().decrypt(row["ciphertext"].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None  # a lost secret or a tampered row: act as if there is no key (the person can paste it again)
    owner, _, key = plain.partition(":")
    return key if owner == str(user_id) and key else None


def hint(user_id: int) -> str | None:
    row = db.get_ai_key(user_id)
    return row["hint"] if row else None


def remove(user_id: int) -> None:
    db.delete_ai_key(user_id)
