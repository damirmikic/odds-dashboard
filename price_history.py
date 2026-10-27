"""Price history of every compared outcome, for the line-movement charts and the value list's "last change".

Each board hands its compare rows to `PriceStore.observe()` (the same rows the CLV store gets). A row is written only
when the Pinnacle price, the MerkurXtip price or the Pinnacle fair price of an outcome differs from the last one stored,
so a quiet match costs nothing. `ClvWorker` refreshes every board in the background, so the history fills without a
browser. Matches are deleted `KEEP_HOURS` after kickoff. Stored in SQLite next to the CLV store (own file, own lock).

This module must not import `pinnwire_dashboard` (run as a script that module is `__main__`).
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

KEEP_HOURS = 24  # history of a match is kept this long after its kickoff
PRUNE_EVERY = 600  # seconds between prunes

SCHEMA = """
CREATE TABLE IF NOT EXISTS outcomes (
    id INTEGER PRIMARY KEY,
    sport TEXT NOT NULL, match_id TEXT NOT NULL,
    period TEXT NOT NULL, grp TEXT NOT NULL, line REAL, outcome TEXT NOT NULL,
    starts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS outcomes_match ON outcomes (sport, match_id);
CREATE INDEX IF NOT EXISTS outcomes_starts ON outcomes (starts);
CREATE TABLE IF NOT EXISTS prices (
    outcome_id INTEGER NOT NULL,
    at INTEGER NOT NULL,
    pinnacle REAL, merkur REAL, fair REAL,
    PRIMARY KEY (outcome_id, at)
) WITHOUT ROWID;
"""


EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def stamp(epoch):
    # not datetime.fromtimestamp(): on Windows it rejects negative values
    return (EPOCH + timedelta(seconds=epoch)).strftime("%Y-%m-%dT%H:%M:%SZ")


def key(match_id, period, group, line, outcome):
    return str(match_id), period, group, None if line is None else float(line), outcome


class PriceStore:
    def __init__(self, path=":memory:"):
        if path != ":memory:":
            os.makedirs(os.path.dirname(path), exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        # sport -> {key: [outcome id, starts, pinnacle, merkur, fair, seen at, pinnacle changed at, merkur changed at]}
        self.last = {}
        self.pruned_at = 0.0
        with self.lock, self.db:
            self.db.executescript(SCHEMA)

    def _load(self, sport):
        """Last stored state of every outcome of a sport (once per process: the history outlives a restart)."""
        if sport in self.last:
            return self.last[sport]
        out = {}
        rows = self.db.execute(
            "SELECT o.id, o.match_id, o.period, o.grp, o.line, o.outcome, o.starts, p.at, p.pinnacle, p.merkur, p.fair "
            "FROM outcomes o JOIN prices p ON p.outcome_id = o.id WHERE o.sport = ? ORDER BY o.id, p.at", (sport,))
        for oid, match_id, period, group, line, outcome, starts, at, pin, mer, fair in rows:
            k = key(match_id, period, group, line, outcome)
            entry = out.get(k)
            if entry is None:
                out[k] = [oid, starts, pin, mer, fair, at, None, None]
                continue
            if pin != entry[2]:
                entry[6] = at
            if mer != entry[3]:
                entry[7] = at
            entry[2:5] = pin, mer, fair
        self.last[sport] = out
        return out

    def observe(self, sport, matches, now=None):
        """Store the outcomes whose prices changed since the last board.

        `matches`: [{id, starts, rows: [(period, compare row)]}] as ClvStore.observe() takes them."""
        now = int(now or time.time())
        written = 0
        with self.lock, self.db:
            last = self._load(sport)
            for m in matches:
                if not m["starts"]:
                    continue
                for period, row in m["rows"]:
                    for o in row["outcomes"]:
                        k = key(m["id"], period, row["group"], row["line"], o["key"])
                        prices = (o["pinnacle"], o["merkur"], o["fair"])
                        entry = last.get(k)
                        if entry is None:
                            oid = self.db.execute(
                                "INSERT INTO outcomes (sport, match_id, period, grp, line, outcome, starts) "
                                "VALUES (?,?,?,?,?,?,?)", (sport, *k, m["starts"])).lastrowid
                            entry = last[k] = [oid, m["starts"], None, None, None, now, None, None]
                        elif tuple(entry[2:5]) == prices:
                            continue
                        else:
                            if entry[1] != m["starts"]:  # kickoff moved: pruning goes by the new time
                                entry[1] = m["starts"]
                                self.db.execute("UPDATE outcomes SET starts = ? WHERE id = ?", (m["starts"], entry[0]))
                            if prices[0] != entry[2]:
                                entry[6] = now
                            if prices[1] != entry[3]:
                                entry[7] = now
                        entry[2:5] = prices
                        self.db.execute("INSERT OR REPLACE INTO prices (outcome_id, at, pinnacle, merkur, fair) "
                                        "VALUES (?,?,?,?,?)", (entry[0], now, *prices))
                        written += 1
            if now - self.pruned_at >= PRUNE_EVERY:
                self._prune(now)
        return written

    def _prune(self, now):
        cutoff = stamp(now - KEEP_HOURS * 3600)
        self.db.execute("DELETE FROM prices WHERE outcome_id IN (SELECT id FROM outcomes WHERE starts < ?)", (cutoff,))
        self.db.execute("DELETE FROM outcomes WHERE starts < ?", (cutoff,))
        for last in self.last.values():
            for k in [k for k, entry in last.items() if entry[1] < cutoff]:
                del last[k]
        self.pruned_at = now

    def annotate(self, sport, values):
        """Add `pinChangedAt` / `mxChangedAt` (last price change, None when it has not moved since `seenAt`) to value items."""
        with self.lock:
            last = self.last.get(sport) or {}
            for v in values:
                entry = last.get(key(v["matchId"], v.get("period", "ft"), v["group"], v["line"], v["key"]))
                v["seenAt"] = stamp(entry[5]) if entry else None
                v["pinChangedAt"] = stamp(entry[6]) if entry and entry[6] else None
                v["mxChangedAt"] = stamp(entry[7]) if entry and entry[7] else None
        return values

    def series(self, sport, match_id):
        """Every stored outcome of one match: [{period, group, line, key, points: [[epoch s, pinnacle, merkur, fair]]}]."""
        with self.lock:
            rows = self.db.execute(
                "SELECT o.id, o.period, o.grp, o.line, o.outcome, p.at, p.pinnacle, p.merkur, p.fair "
                "FROM outcomes o JOIN prices p ON p.outcome_id = o.id WHERE o.sport = ? AND o.match_id = ? "
                "ORDER BY o.id, p.at", (sport, str(match_id))).fetchall()
        out = {}
        for oid, period, group, line, outcome, at, pin, mer, fair in rows:
            entry = out.setdefault(oid, {"period": period, "group": group, "line": line, "key": outcome, "points": []})
            entry["points"].append([at, pin, mer, fair])
        return list(out.values())
