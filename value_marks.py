"""Value marks: what a trader did about a value outcome ("Urađeno", "Ostavljeno zbog uplate", ...).

Marks live on the server (SQLite, `data/marks.sqlite3`), so everyone using the same server sees the same marks; the UI
polls `/api/marks`. A mark is keyed by an opaque string the UI builds from sport, match, period, market, line and
outcome, keeps the MerkurXtip price it was set at (the UI flags a mark whose price has moved since) and the basic-auth
user the proxy passes in `X-Remote-User`. Marks are deleted `KEEP_HOURS` after kickoff.

This module must not import `pinnwire_dashboard` (run as a script that module is `__main__`).
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from datetime import datetime, timezone

KEEP_HOURS = 24  # a mark is kept this long after its match's kickoff
PRUNE_EVERY = 600  # seconds between prunes
STATUSES = ("done", "deposit", "blocked", "nochange", "custom")
MAX_KEY = 300
MAX_NOTE = 200

SCHEMA = """
CREATE TABLE IF NOT EXISTS marks (
    mkey TEXT PRIMARY KEY,
    sport TEXT NOT NULL,
    status TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    merkur REAL,
    user TEXT NOT NULL DEFAULT '',
    at INTEGER NOT NULL,
    starts INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS marks_starts ON marks (starts);
"""


def parse_starts(value, now):
    """Kickoff as epoch seconds; a missing or unreadable kickoff counts as now (pruned a day later)."""
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc).timestamp())
    except (TypeError, ValueError):
        return int(now)


def stamp(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class MarkStore:
    def __init__(self, path=":memory:"):
        if path != ":memory:":
            os.makedirs(os.path.dirname(path), exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        self.pruned_at = 0.0
        with self.lock, self.db:
            self.db.executescript(SCHEMA)

    def set(self, body, sports, user="", now=None):
        """Set or clear one mark from a request body {key, sport, starts, status, note, merkur}.

        An empty status clears the mark. Bad input raises ValueError (the handler answers 400)."""
        now = int(now or time.time())
        mkey, sport = body.get("key"), body.get("sport")
        if not isinstance(mkey, str) or not mkey or len(mkey) > MAX_KEY:
            raise ValueError("Neispravan ključ oznake.")
        if sport not in sports:
            raise ValueError("Nepoznat sport.")
        status = body.get("status") or ""
        note = str(body.get("note") or "").strip()[:MAX_NOTE]
        merkur = body.get("merkur")
        if merkur is not None:
            try:
                merkur = float(merkur)
            except (TypeError, ValueError):
                raise ValueError("Neispravna kvota.") from None
        with self.lock, self.db:
            if not status:
                self.db.execute("DELETE FROM marks WHERE mkey = ?", (mkey,))
                return None
            if status not in STATUSES:
                raise ValueError("Nepoznat status oznake.")
            if status == "custom" and not note:
                raise ValueError("Upiši napomenu.")
            self.db.execute(
                "INSERT OR REPLACE INTO marks (mkey, sport, status, note, merkur, user, at, starts) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (mkey, sport, status, note, merkur, (user or "")[:60], now, parse_starts(body.get("starts"), now)))
            if now - self.pruned_at >= PRUNE_EVERY:
                self.db.execute("DELETE FROM marks WHERE starts < ?", (now - KEEP_HOURS * 3600,))
                self.pruned_at = now
        return self.get(mkey)

    def get(self, mkey):
        with self.lock:
            row = self.db.execute("SELECT mkey, status, note, merkur, user, at FROM marks WHERE mkey = ?",
                                  (mkey,)).fetchone()
        return self._out(row)[1] if row else None

    def all(self, now=None):
        """Every mark of a match that has not been over for `KEEP_HOURS`: {key: {status, note, merkur, user, at}}."""
        cutoff = int(now or time.time()) - KEEP_HOURS * 3600
        with self.lock:
            rows = self.db.execute("SELECT mkey, status, note, merkur, user, at FROM marks WHERE starts >= ?",
                                   (cutoff,)).fetchall()
        return dict(self._out(row) for row in rows)

    @staticmethod
    def _out(row):
        mkey, status, note, merkur, user, at = row
        return mkey, {"status": status, "note": note, "merkur": merkur, "user": user, "at": stamp(at)}
