"""Closing line value of the MerkurXtip prices the dashboard flagged as value.

A signal is an outcome whose MerkurXtip price beat Pinnacle's fair price by at least `MIN_EV` the first time the
dashboard saw it. Every later board keeps the latest Pinnacle fair price (and MerkurXtip price) of that outcome until
the match starts, so the last one seen is the closing line. CLV = signal MerkurXtip price / closing fair price - 1:
above zero means MerkurXtip offered more than Pinnacle finally thought fair. Stored in SQLite (stdlib), because the
history must outlive the matches, which the JSON history drops once they start.

This module must not import `pinnwire_dashboard` (run as a script that module is `__main__`).
"""
from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

MIN_EV = 0.02  # a value outcome becomes a signal from this edge over Pinnacle's fair price
FRESH_MINUTES = 30  # a closing line counts when it was seen at most this long before kickoff

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    sig TEXT PRIMARY KEY,
    sport TEXT NOT NULL,
    event_id TEXT NOT NULL,
    home TEXT, away TEXT, league TEXT,
    starts TEXT NOT NULL,
    period TEXT NOT NULL, grp TEXT NOT NULL, line REAL, outcome TEXT NOT NULL, label TEXT,
    seen_at TEXT NOT NULL,
    merkur REAL NOT NULL, pinnacle REAL NOT NULL, fair REAL NOT NULL, ev REAL NOT NULL,
    close_at TEXT, close_fair REAL, close_pinnacle REAL, close_merkur REAL
);
CREATE INDEX IF NOT EXISTS signals_starts ON signals (starts);
"""


def stamp(moment=None):
    return (moment or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")


def signature(match_id, period, group, line, key):
    return f"{match_id}|{period}|{group}|{'' if line is None else float(line)}|{key}"


class ClvStore:
    def __init__(self, path=":memory:"):
        if path != ":memory:":
            os.makedirs(os.path.dirname(path), exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self.last_seen = {}  # sport -> epoch seconds of the last observed board, for the background worker
        self.open = {}  # sport -> signatures of signals known to the store (loaded lazily, never pruned: tiny)
        with self.lock, self.db:
            self.db.executescript(SCHEMA)

    # ----- recording
    def _known_sigs(self, sport, now):
        if sport not in self.open:
            rows = self.db.execute("SELECT sig FROM signals WHERE sport = ?", (sport,))
            self.open[sport] = {r["sig"] for r in rows}
        return self.open[sport]

    def observe(self, sport, matches, now=None):
        """Record signals and update closing lines from one board.

        `matches`: [{id, home, away, league, starts, rows: [(period, compare row)]}], upcoming matches only.
        A compare row is {group, line, outcomes: [{key, label, merkur, pinnacle, fair, ev}], modeled?}."""
        now = now or stamp()
        added = 0
        with self.lock, self.db:
            known = self._known_sigs(sport, now)
            for m in matches:
                if not m["starts"] or m["starts"] <= now:
                    continue
                for period, row in m["rows"]:
                    if row.get("modeled"):
                        continue  # a modelled Pinnacle price is not a market price
                    for o in row["outcomes"]:
                        sig = signature(m["id"], period, row["group"], row["line"], o["key"])
                        if sig in known:
                            self.db.execute(
                                "UPDATE signals SET close_at = ?, close_fair = ?, close_pinnacle = ?, close_merkur = ? "
                                "WHERE sig = ?", (now, o["fair"], o["pinnacle"], o["merkur"], sig))
                        elif o["ev"] >= MIN_EV:
                            cur = self.db.execute(
                                "INSERT OR IGNORE INTO signals (sig, sport, event_id, home, away, league, starts, period, "
                                "grp, line, outcome, label, seen_at, merkur, pinnacle, fair, ev) "
                                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                (sig, sport, str(m["id"]), m["home"], m["away"], m["league"], m["starts"], period,
                                 row["group"], row["line"], o["key"], o["label"], now, o["merkur"], o["pinnacle"],
                                 o["fair"], o["ev"]))
                            if cur.rowcount:
                                known.add(sig)
                                added += 1
        self.last_seen[sport] = datetime.now(timezone.utc).timestamp()
        return added

    def soon(self, minutes=15, now=None):
        """True when an unstarted signal's match starts within `minutes` (the worker then polls faster)."""
        now = now or datetime.now(timezone.utc)
        with self.lock:  # the worker thread asks while a board may be writing on the same connection
            row = self.db.execute("SELECT 1 FROM signals WHERE starts > ? AND starts <= ? LIMIT 1",
                                  (stamp(now), stamp(now + timedelta(minutes=minutes)))).fetchone()
        return row is not None

    # ----- reading
    def _closed_where(self):
        return ("starts <= :now AND close_fair IS NOT NULL "
                "AND close_at >= strftime('%Y-%m-%dT%H:%M:%SZ', starts, :fresh)")

    def stats(self, sport=None, days=30, now=None):
        now = now or stamp()
        since = stamp(datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) - timedelta(days=days))
        params = {"now": now, "fresh": f"-{FRESH_MINUTES} minutes", "since": since, "sport": sport}
        scope = "starts >= :since AND (:sport IS NULL OR sport = :sport)"
        closed = f"{scope} AND {self._closed_where()}"

        def grouped(column):
            rows = self.db.execute(
                f"SELECT {column} AS name, COUNT(*) AS n, AVG(merkur / close_fair - 1) AS clv, "
                f"AVG(merkur / close_fair - 1 > 0) AS positive, AVG(ev) AS ev FROM signals WHERE {closed} "
                f"GROUP BY {column} ORDER BY n DESC", params).fetchall()
            return [self._round(dict(r)) for r in rows]

        with self.lock:
            total = self.db.execute(
                f"SELECT COUNT(*) AS n, AVG(merkur / close_fair - 1) AS clv, AVG(merkur / close_fair - 1 > 0) AS positive, "
                f"AVG(ev) AS ev FROM signals WHERE {closed}", params).fetchone()
            pending = self.db.execute(
                f"SELECT COUNT(*) FROM signals WHERE {scope} AND starts > :now", params).fetchone()[0]
            unclosed = self.db.execute(
                f"SELECT COUNT(*) FROM signals WHERE {scope} AND starts <= :now AND NOT ({self._closed_where()})",
                params).fetchone()[0]
            recent = self.db.execute(
                f"SELECT *, CASE WHEN {self._closed_where()} THEN merkur / close_fair - 1 END AS clv "
                f"FROM signals WHERE {scope} ORDER BY seen_at DESC LIMIT 200", params).fetchall()
            return {
                "days": days, "minEv": MIN_EV,
                "total": self._round(dict(total)), "pending": pending, "unclosed": unclosed,
                "bySport": grouped("sport"), "byGroup": grouped("grp"), "byLeague": grouped("league"),
                "recent": [self._round(dict(r)) for r in recent],
            }

    @staticmethod
    def _round(row):
        for key in ("clv", "positive", "ev"):
            if row.get(key) is not None:
                row[key] = round(row[key], 4)
        return row
