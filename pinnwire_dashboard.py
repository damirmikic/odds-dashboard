#!/usr/bin/env python3
"""Xtip Monitor server: Pinnacle (PinnWire) against MerkurXtip for football, basketball, tennis, hockey and MMA.

This module holds the football board, the shared History, the background workers (drop stream, CLV refresh),
the HTTP handler and main(). Every sport keeps a PinnWire snapshot (full load, then `since=` deltas, see
common.SnapshotState) and pairs it with the MerkurXtip offer; the other sports live in basketball.py, tennis.py,
hockey.py and mma.py.
"""
from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import os
import re
import threading
import time
import webbrowser
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import applog
import basketball as bb
import clv
import common
import handball
import hockey
import merkur_client as mx
import mma
import pinnwire_client as pw
import price_history
import tennis
from common import (  # noqa: F401 (tests use them here)
    event_ts,
    is_upcoming,
    offered_other,
    other_competitions,
    other_score,
    split_league,
    utc_now,
    utc_stamp,
)
from football_competitions import COMPETITIONS, HIDDEN_MISSING_LEAGUES

log = logging.getLogger("xtip.server")

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
LOGS = os.path.join(DATA, "logs")
STATIC = os.path.join(ROOT, "static", "dashboard_build")
CONFIG_PATH = os.path.join(DATA, "pinnwire_config.json")
HISTORY_PATH = os.path.join(DATA, "dashboard_history.json")
CLV_PATH = os.path.join(DATA, "clv.sqlite3")
PRICES_PATH = os.path.join(DATA, "prices.sqlite3")

LEAGUE_IDS = {c["id"] for c in COMPETITIONS}
# `merkur_also`: further MerkurXtip leagues that PinnWire quotes under the same league_id
MERKUR_COMP = {m: c["id"] for c in COMPETITIONS
               for m in [*([c["merkur"]] if "merkur" in c else []), *c.get("merkur_also", [])]}
# `merkur_of`: a competition sharing another one's MerkurXtip league pairs under that competition's id
PAIR_COMP = {c["id"]: c.get("merkur_of", c["id"]) for c in COMPETITIONS}


def merkur_comp(row):
    """PinnWire league_id of a MerkurXtip offer row's competition, None when it is not tracked."""
    return MERKUR_COMP.get(row.get("leagueShort")) or MERKUR_COMP.get(row.get("leagueId"))
# Explicit types: on Windows `mimetypes` reads the registry, where .js is sometimes text/plain,
# which breaks module scripts and service worker registration.
STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".webmanifest": "application/manifest+json",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}
ML_SIDES = ("home", "draw", "away")


def load_config():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as config_file:
            data = json.load(config_file)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Ne mogu da pročitam data/pinnwire_config.json: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("data/pinnwire_config.json mora sadržati JSON objekat.")  # noqa: TRY004 (shown in the UI)
    return data


def current_api_key():
    return os.environ.get("PINNWIRE_API_KEY") or load_config().get("api_key", "")


def save_api_key(api_key):
    if not api_key or not api_key.strip():
        raise ValueError("API ključ ne može biti prazan.")
    os.makedirs(DATA, exist_ok=True)
    config = load_config()
    config["api_key"] = api_key.strip()
    temp_path = CONFIG_PATH + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as config_file:
        json.dump(config, config_file, ensure_ascii=False, indent=2)
    os.replace(temp_path, CONFIG_PATH)


def is_tracked(event):
    return event.get("league_id") in LEAGUE_IDS and pw.is_main_fixture(event)


# ------------------------------------------------------------------------- shaping

# Largest gap between the draw-no-bet probability of Pinnacle's AH 0 and the one implied by its 1X2 before
# the AH 0 is treated as stale. Live feed: 1000+ matches sit within 0.02, a handful of low-league fixtures
# (AH 0 not actually offered on pinnacle.com) are 0.03-0.12 off.
AH0_MAX_GAP = 0.03


def main_team_totals(event):
    """The event with only the team-total line Pinnacle itself offers (`team_total`) in every period.

    PinnWire's `team_totals` also carries extra lines (e.g. home 1.5 next to the offered 2.5) that Pinnacle does
    not sell and whose prices do not follow the match total, so they only produce false Value."""
    periods = {}
    for key, markets in event.get("periods", {}).items():
        main, ladder = markets.get("team_total"), markets.get("team_totals")
        if isinstance(main, dict) and isinstance(ladder, dict):
            kept = {}
            for side, lines in ladder.items():
                point = pw._num((main.get(side) or {}).get("points")) if isinstance(main.get(side), dict) else None
                kept[side] = ({k: v for k, v in lines.items() if isinstance(v, dict) and pw._num(v.get("points")) == point}
                              if isinstance(lines, dict) and point is not None else lines)
            markets = {**markets, "team_totals": kept}
        periods[key] = markets
    return {**event, "periods": periods} if periods else event


def clean_ah0(event):
    """The event without full-match AH 0 / AH ±0.5 lines that contradict the 1X2 (PinnWire keeps quoting an AH 0
    for some small fixtures where Pinnacle does not offer it, and its AH ±0.5 is sometimes a stale copy of ±1)."""
    event = main_team_totals(event)
    markets = pw.period(event, 0)
    spreads = markets.get("spreads") or {}
    ml = pw.priced(markets.get("money_line") or {}, ML_SIDES)
    if len(ml) < 3:
        return event
    p = pw.devig(ml)
    expected = {0: p["home"] / (p["home"] + p["away"]), -0.5: p["home"], 0.5: p["home"] + p["draw"]}
    drop = []
    for line in spreads.values():
        hdp = pw._num(line.get("hdp")) if isinstance(line, dict) else None
        ah = pw.priced(line, ("home", "away")) if hdp in expected else {}
        if len(ah) == 2 and abs(pw.devig(ah)["home"] - expected[hdp]) > AH0_MAX_GAP:
            drop.append(line)
    if not drop:
        return event
    kept = {k: v for k, v in spreads.items() if not any(v is d for d in drop)}
    return {**event, "periods": {**event["periods"], "num_0": {**markets, "spreads": kept}}}


def money_line(event, number=0):
    prices = pw.priced(pw.period(event, number).get("money_line") or {}, ML_SIDES)
    if len(prices) < 3:
        return None, None
    fair, margin = pw.fair_odds(prices)
    return {side: {"odds": prices[side], "fair": round(fair[side], 3),
                   "prob": round(1 / fair[side], 4)} for side in ML_SIDES}, margin


def main_line(rows, sides):
    row = next((r for r in rows if r.get("main")), None)
    if not row:
        return None
    return {"line": row["line"], "odds": row["odds"], "fair": row["fair"], "margin": row["margin"],
            "max": row.get("max"), "sides": list(sides)}


def team_totals(event, number):
    out = {}
    for side, lines in (pw.period(event, number).get("team_totals") or {}).items():
        if isinstance(lines, dict):
            out[side] = pw.lines_from(lines.values(), ("over", "under"), "points")
    return out


def period_detail(event, number):
    event = clean_ah0(event)
    ml, margin = money_line(event, number)
    return {
        "ml": ml,
        "margin": margin,
        "spreads": pw.build_lines(event, "spreads", ("home", "away"), "hdp", number),
        "totals": pw.build_lines(event, "totals", ("over", "under"), "points", number),
        "teamTotals": team_totals(event, number),
    }


def summary(event, track, cleaned=False):
    if not cleaned:
        event = clean_ah0(event)
    ml, margin = money_line(event)
    spreads = pw.build_lines(event, "spreads", ("home", "away"), "hdp")
    totals = pw.build_lines(event, "totals", ("over", "under"), "points")
    return {
        "id": event.get("event_id"),
        "leagueId": event.get("league_id"),
        "leagueName": event.get("league_name") or "",
        "home": event.get("home", ""),
        "away": event.get("away", ""),
        "starts": event.get("starts") or event.get("start_ts") or "",
        "ml": ml,
        "margin": margin,
        "ah": main_line(spreads, ("home", "away")),
        "ou": main_line(totals, ("over", "under")),
        "open": track.get("open"),
        "prev": track.get("prev"),
        "changedAt": track.get("changedAt"),
    }


# ------------------------------------------------------------------------- MerkurXtip comparison

COMPARE_GROUPS = [
    # (key in decoded markets, group label, outcome labels)
    ("ml", "1X2", (("home", "1"), ("draw", "X"), ("away", "2"))),
    ("totals", "Ukupno golova", (("over", "Više"), ("under", "Manje"))),
    ("spreads", "Hendikep", (("home", "1"), ("away", "2"))),
]
OU_SIDES = (("over", "Više"), ("under", "Manje"))
# compare row group -> PinnWire drop market, for the MerkurXtip price on a drop alert
DROP_GROUPS = {"1X2": "moneyline", "Hendikep": "spread", "Ukupno golova": "total"}


def pinnacle_lines(event, number, cleaned=False):
    """Pinnacle prices of one period keyed like merkur_client.markets()."""
    if number == 0 and not cleaned:
        event = clean_ah0(event)
    markets = pw.period(event, number)
    ml = pw.priced(markets.get("money_line") or {}, ML_SIDES)
    return {
        "ml": ml if len(ml) == 3 else None,
        "totals": pw.ladder(markets.get("totals"), "points", ("over", "under")),
        "spreads": pw.ladder(markets.get("spreads"), "hdp", ("home", "away"), "spreads"),
        "teamTotals": {side: pw.ladder(lines, "points", ("over", "under"))
                       for side, lines in (markets.get("team_totals") or {}).items() if isinstance(lines, dict)},
    }


def pinnacle_max(event, number, cleaned=False):
    """Pinnacle limit (max bet) per line, shaped like pinnacle_lines(); the 1X2 price carries no limit."""
    if number == 0 and not cleaned:
        event = clean_ah0(event)
    markets = pw.period(event, number)
    return {
        "totals": pw.ladder_limits(markets.get("totals"), "points"),
        "spreads": pw.ladder_limits(markets.get("spreads"), "hdp", "spreads"),
        "teamTotals": {side: pw.ladder_limits(lines, "points")
                       for side, lines in (markets.get("team_totals") or {}).items() if isinstance(lines, dict)},
    }


def compare_period(event, merkur_period, number, cleaned=False):
    if number == 0 and not cleaned:
        event = clean_ah0(event)
    pin = pinnacle_lines(event, number, cleaned=True)
    limits = pinnacle_max(event, number, cleaned=True)
    rows = []
    for key, group, labels in COMPARE_GROUPS:
        if key == "ml":
            if merkur_period.get("ml") and pin["ml"]:
                rows.append(common.compare_row(group, None, labels, merkur_period["ml"], pin["ml"]))
            continue
        for line in sorted(merkur_period.get(key) or {}):
            if line in pin[key]:
                derived = key == "spreads" and line in merkur_period.get("derived", ())
                rows.append(common.compare_row(group, line, labels, merkur_period[key][line], pin[key][line],
                                               limits[key].get(line), derived))
    for side, group in (("home", "Golovi domaćin"), ("away", "Golovi gost")):
        pin_side = pin["teamTotals"].get(side) or {}
        for line, prices in sorted(((merkur_period.get("teamTotals") or {}).get(side) or {}).items()):
            if line in pin_side:
                rows.append(common.compare_row(group, line, OU_SIDES, prices, pin_side[line],
                                               limits["teamTotals"].get(side, {}).get(line)))
    return rows


def merkur_ts(row):
    return row.get("kickOffTime") or 0


def merkur_info(row, event, score=None):
    return {
        "id": row.get("id"),
        "code": row.get("matchCode"),
        "home": row.get("home", ""),
        "away": row.get("away", ""),
        "kickoff": datetime.fromtimestamp(merkur_ts(row) / 1000, timezone.utc).isoformat().replace("+00:00", "Z"),
        "kickoffDiff": round((merkur_ts(row) - event_ts(event)) / 60000),
        "score": score,
    }


PERIOD_LABELS = {"ft": "Ceo meč", "ht": "1. poluvreme"}
PREFIXES = {"ft": "", "ht": "1.pol "}


def period_rows(rows):
    """{"ft": rows, "ht": rows} -> [(period key, row)]"""
    return [(period, r) for period in ("ft", "ht") for r in rows[period]]


def value_items(match, rows):
    """Every outcome where the MerkurXtip price beats the Pinnacle price (with margin), one row each."""
    def label(r, o):
        if r["group"] == "Hendikep":
            return match["home"] if o["key"] == "home" else match["away"]
        return o["label"]

    return common.value_items(match["id"], period_rows(rows), PERIOD_LABELS, label=label)


def merkur_summary(row, event, score, cleaned=False):
    """Board cell data: 1X2 against fair odds, comparable goal lines and the largest edge anywhere."""
    decoded = mx.markets(row)
    rows = {"ft": compare_period(event, decoded[0], 0, cleaned=cleaned),
            "ht": compare_period(event, decoded[1], 1, cleaned=True)}
    ml = next((r for r in rows["ft"] if r["group"] == "1X2"), None)
    return {
        **merkur_info(row, event, score),
        "ml": {o["key"]: {"odds": o["merkur"], "ev": o["ev"]} for o in ml["outcomes"]} if ml else None,
        "margin": ml["merkurMargin"] if ml else None,
        "totals": [r for r in rows["ft"] if r["group"] == "Ukupno golova"],
        "rows": rows,
        "best": common.best_edge(period_rows(rows), PREFIXES),
        "compared": len(rows["ft"]) + len(rows["ht"]),
    }


def goals_line(match, totals_rows):
    """Goal line for the board: the line both books price that is closest to Pinnacle's main line.

    MerkurXtip only sells half-goal lines, Pinnacle's main line is often a quarter (2.25, 2.75);
    ties go to the line whose Pinnacle prices are closest to even. Without MerkurXtip the
    Pinnacle main line is shown.
    """
    main = match.get("ou")
    if totals_rows:
        target = main["line"] if main else 2.5

        def rank(row):
            pin = {o["key"]: o["pinnacle"] for o in row["outcomes"]}
            return abs(row["line"] - target), abs(pin["over"] - pin["under"])

        row = min(totals_rows, key=rank)
        out = {o["key"]: o for o in row["outcomes"]}
        return {
            "line": row["line"],
            "fair": {k: o["fair"] for k, o in out.items()},
            "pinnacle": {k: o["pinnacle"] for k, o in out.items()},
            "merkur": {k: o["merkur"] for k, o in out.items()},
            "ev": {k: o["ev"] for k, o in out.items()},
            "pinnacleMargin": row["pinnacleMargin"],
            "merkurMargin": row["merkurMargin"],
        }
    if main:
        return {"line": main["line"], "fair": main["fair"], "pinnacle": main["odds"], "merkur": None, "ev": None,
                "pinnacleMargin": main["margin"], "merkurMargin": None}
    return None


# Pinnacle and MerkurXtip sometimes differ by hours on kickoff (e.g. Colombian evening games); names and league still have to match
PAIR_WINDOW = 6 * 60


def pair_inputs(events, offer):
    pin = [{"id": str(e["event_id"]), "comp": PAIR_COMP[e["league_id"]], "home": e.get("home", ""),
            "away": e.get("away", ""), "ts": event_ts(e)} for e in events]
    mer = [{"id": r["id"], "comp": merkur_comp(r), "home": r.get("home", ""),
            "away": r.get("away", ""), "ts": merkur_ts(r), "row": r}
           for r in offer if merkur_comp(r) and mx.is_prematch(r)]
    return pin, mer


def pair_events(events, offer):
    pin, mer = pair_inputs(events, offer)
    return {pid: (m["row"], score) for pid, (m, score) in mx.pair(pin, mer, PAIR_WINDOW).items()}


def unpaired_hints(events, offer, pairs):
    """{pinnacle id: closest unused MerkurXtip offer row} for events without a pair, for the "missing" view."""
    pin, mer = pair_inputs(events, offer)
    return mx.hints(pin, mer, pairs, PAIR_WINDOW)


def unpaired_other(events, offer, used):
    """({pinnacle id} unpaired, {pinnacle id: hint}, {pinnacle id: MerkurXtip row} paired) of events outside
    COMPETITIONS; `used` are MerkurXtip ids already paired within COMPETITIONS."""
    return common.unpaired_other(events, offer, used, merkur_ts)


# ------------------------------------------------------------------------- state

class History:
    """Opening and previous 1X2 prices per event plus a daily request counter, kept on disk.

    Shared by every sport state, so each method takes the lock: a board of one sport may save while another
    sport's fetch is counting calls or football's is observing prices."""

    def __init__(self, path=HISTORY_PATH):
        self.path = path
        self.lock = threading.Lock()
        self.data = {"events": {}, "usage": {}}
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                self.data.update(loaded)
        except (OSError, json.JSONDecodeError):
            pass

    def track(self, event_id):
        with self.lock:
            return dict(self.data["events"].get(str(event_id)) or {})

    def observe(self, event, stamp):
        ml = pw.priced(pw.full_match(event).get("money_line") or {}, ML_SIDES)
        if len(ml) < 3:
            return
        key = str(event.get("event_id"))
        with self.lock:
            track = self.data["events"].setdefault(key, {})
            if "open" not in track:
                track.update(open=ml, openAt=stamp, last=ml)
            elif track.get("last") != ml:
                track.update(prev=track.get("last"), last=ml, changedAt=stamp)

    def count_calls(self, calls):
        today = utc_now().date().isoformat()
        with self.lock:
            usage = self.data.get("usage") or {}
            if usage.get("date") != today:
                usage = {"date": today, "calls": 0}
            usage["calls"] += calls
            self.data["usage"] = usage

    def calls_today(self):
        with self.lock:
            usage = self.data.get("usage") or {}
            return usage.get("calls", 0) if usage.get("date") == utc_now().date().isoformat() else 0

    def prune(self, keep_ids):
        keep = {str(i) for i in keep_ids}
        with self.lock:
            self.data["events"] = {k: v for k, v in self.data["events"].items() if k in keep}

    def save(self):
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with self.lock:  # also keeps two threads from writing the same .tmp file
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, ensure_ascii=False)
            for attempt in range(5):
                try:
                    os.replace(tmp, self.path)
                    return
                except PermissionError:  # Windows: a virus scanner or indexer briefly holds the new file
                    if attempt == 4:
                        raise
                    time.sleep(0.05)


class DashboardState(common.SnapshotState):
    """Football board. The snapshot keeps every main fixture of the feed (the "Nedostaju" view pairs the leagues
    outside COMPETITIONS too); only COMPETITIONS are compared and tracked in History."""

    def __init__(self, history=None, merkur=None):
        super().__init__(history or History(), current_api_key, merkur)
        self.mx_track = {}  # merkur match id -> {last, prev, changedAt}: 1X2 movement this session
        self.goal_track = {}  # "pin|mx:<id>:<line>" -> {last, prev, changedAt}: board goal line movement
        self.other_cache = None  # (offer, signature, unpaired ids, hints, offered) of leagues outside COMPETITIONS

    def merged(self, incoming, stamp):
        """Opening and previous 1X2 prices of the tracked events this fetch changed."""
        tracked = {k for k, e in self.events.items() if is_tracked(e)}
        for key in {str(e["event_id"]) for e in incoming if is_tracked(e)} & tracked:
            self.history.observe(self.events[key], stamp)
        self.history.prune(tracked)
        return sum(1 for e in incoming if is_tracked(e))

    def board(self, refresh=False, full=False):
        if refresh or full or self.events is None:
            self.refresh(full=full, if_empty=not (refresh or full))
        offer = self.merkur_offer(refresh=refresh or full)
        with self.lock:
            now = utc_now()
            upcoming = [e for e in (self.events or {}).values() if is_upcoming(e, now)]
            events = [clean_ah0(e) for e in upcoming if is_tracked(e)]
            others = [e for e in upcoming if not is_tracked(e)]
            matches = [summary(e, self.history.track(e["event_id"]), cleaned=True) for e in events]
        pairs = pair_events(events, offer)
        hints = unpaired_hints(events, offer, pairs)
        self.pairs = pairs
        by_id = {str(e["event_id"]): e for e in events}
        values, quotes, clv_rows = [], {}, {}
        for m in matches:
            hit = pairs.get(str(m["id"]))
            m["merkur"] = merkur_summary(hit[0], by_id[str(m["id"])], hit[1], cleaned=True) if hit else None
            m["hint"] = hints.get(str(m["id"]))
            if m["merkur"]:
                m["merkur"].update(self.track_merkur(m["merkur"]))
            m["goals"] = goals_line(m, m["merkur"].pop("totals") if m["merkur"] else None)
            if m["merkur"]:
                rows = m["merkur"].pop("rows")
                values.extend(value_items(m, rows))
                quotes[str(m["id"])] = (m["id"], pw.quote_index({0: rows["ft"], 1: rows["ht"]}, DROP_GROUPS))
                clv_rows[m["id"]] = [("ft", r) for r in rows["ft"]] + [("ht", r) for r in rows["ht"]]
            if m["goals"]:
                m["goals"].update(self.track_goals(m))
        self.mx_track = {k: v for k, v in self.mx_track.items()
                         if k in {row["id"] for row, _ in pairs.values()}}
        live_keys = {f"{src}:{i}:" for m in matches for src, i in
                     (("pin", m["id"]), ("mx", (m["merkur"] or {}).get("id")))}
        self.goal_track = {k: v for k, v in self.goal_track.items() if k[:k.rindex(":") + 1] in live_keys}
        matches = [m for m in matches if m["ml"] or m["ah"] or m["ou"]]
        kept = {m["id"] for m in matches}
        values = [v for v in values if v["matchId"] in kept]
        matches.sort(key=lambda m: (m["starts"], m["home"]))
        self.quotes = quotes
        observed = [{"id": m["id"], "home": m["home"], "away": m["away"], "league": m["leagueName"],
                     "starts": m["starts"], "rows": clv_rows[m["id"]]} for m in matches if m["id"] in clv_rows]
        self.record("football", observed, values)
        counts = {}
        for m in matches:
            counts[m["leagueId"]] = counts.get(m["leagueId"], 0) + 1
        missing_other = self.missing_other(others, offer, {row["id"] for row, _ in pairs.values()})
        return {
            "competitions": [{**c, "count": counts.get(c["id"], 0)} for c in COMPETITIONS],
            "matches": matches,
            "otherCompetitions": other_competitions(missing_other),
            "otherMissing": missing_other,
            "suspended": self.suspended_items(),
            "otherOffered": self.offered_other(),
            "fetchedAt": self.fetched_at,
            "mode": self.mode,
            "changed": self.changed,
            "callsToday": self.history.calls_today(),
            "values": sorted(values, key=lambda v: v["ev"], reverse=True),
            "merkur": {
                "fetchedAt": self.merkur.stamp,
                "error": self.merkur.error,
                "paired": sum(1 for m in matches if m["merkur"]),
                "offered": sum(1 for r in offer if merkur_comp(r) and mx.is_prematch(r)),
            },
        }

    def missing_other(self, events, offer, used):
        """Board entries of events outside COMPETITIONS that MerkurXtip does not offer (cached until the offer
        or the set of events changes: the pairing without a competition check is slow)."""
        # the offer list itself, not its id(): holding it keeps a newer list from reusing the id of an old one
        signature = (frozenset(str(e["event_id"]) for e in events), frozenset(used))
        cache = self.other_cache
        if cache is None or cache[0] is not offer or cache[1] != signature:
            missing, hints, paired = unpaired_other(events, offer, used)
            cache = self.other_cache = (offer, signature, missing, hints, offered_other(events, paired))
        _, _, missing, hints, _ = cache
        out = []
        for e in events:
            key = str(e["event_id"])
            if key not in missing or e.get("league_name") in HIDDEN_MISSING_LEAGUES:
                continue
            m = summary(e, {})
            if m["ml"] or m["ah"] or m["ou"]:
                out.append({**m, "merkur": None, "hint": hints.get(key)})
        return sorted(out, key=lambda m: (m["starts"], m["home"]))

    def offered_other(self):
        return self.other_cache[4] if self.other_cache else []

    def track_merkur(self, summary_row):
        """Remember MerkurXtip 1X2 between offer fetches; returns {prev, changedAt} for the board."""
        if not summary_row.get("ml"):
            return {"prev": None, "changedAt": None}
        ml = {side: v["odds"] for side, v in summary_row["ml"].items()}
        track = self.mx_track.setdefault(summary_row["id"], {"last": ml})
        if track["last"] != ml:
            track.update(prev=track["last"], last=ml, changedAt=self.merkur.stamp)
        return {"prev": track.get("prev"), "changedAt": track.get("changedAt")}

    @staticmethod
    def _track(store, key, prices, stamp):
        track = store.setdefault(key, {"last": prices})
        if track["last"] != prices:
            track.update(prev=track["last"], last=prices, changedAt=stamp)
        return track.get("prev"), track.get("changedAt")

    def track_goals(self, match):
        """Movement of the board goal line for both books, per line, between fetches."""
        goals = match["goals"]
        line = goals["line"]
        pin_prev, pin_at = self._track(self.goal_track, f"pin:{match['id']}:{line}", goals["pinnacle"],
                                       self.fetched_at)
        out = {"pinPrev": pin_prev, "pinChangedAt": pin_at, "mxPrev": None, "mxChangedAt": None}
        if goals["merkur"]:
            out["mxPrev"], out["mxChangedAt"] = self._track(
                self.goal_track, f"mx:{match['merkur']['id']}:{line}", goals["merkur"], self.merkur.stamp)
        return out

    def merkur_detail(self, event):
        """Fresh single-match odds from MerkurXtip, compared per period; falls back to the offer list."""
        hit = self.pairs.get(str(event["event_id"]))
        if hit is None:
            return None
        row, score = hit
        error = ""
        try:
            row, fetched = self.merkur.api.match(row["id"]), utc_stamp()
        except (RuntimeError, LookupError) as exc:
            error, fetched = str(exc), self.merkur.stamp
        decoded = mx.markets(row)
        return {
            **merkur_info(row, event, score),
            "fetchedAt": fetched,
            "error": error,
            "periods": {"ft": compare_period(event, decoded[0], 0), "ht": compare_period(event, decoded[1], 1)},
        }

    def match(self, event_id, refresh=False):
        if refresh:
            api = self.get_api()
            before = api.calls
            try:
                event = api.prematch_event(event_id)
            finally:
                self.history.count_calls(api.calls - before)
            stamp = utc_stamp()
            with self.lock:
                if self.events is not None and is_tracked(event):
                    self.events[event_id] = event
                    self.history.observe(event, stamp)
            fetched = stamp
        else:
            if self.events is None:
                self.refresh(if_empty=True)
            with self.lock:
                event = (self.events or {}).get(event_id)
                fetched = self.fetched_at
            if event is None:
                raise LookupError("Meč nije u ponudi (možda je počeo ili uklonjen).")
        return {
            "match": summary(event, self.history.track(event_id)),
            "periods": [
                {"key": "ft", "label": "Ceo meč", **period_detail(event, 0)},
                {"key": "ht", "label": "1. poluvreme", **period_detail(event, 1)},
            ],
            "fetchedAt": fetched,
            "callsToday": self.history.calls_today(),
            "merkur": self.merkur_detail(event),
        }


STATE = DashboardState()
BB_STATE = bb.BasketballState(STATE.history, current_api_key)
TN_STATE = tennis.TennisState(STATE.history, current_api_key)
HK_STATE = hockey.HockeyState(STATE.history, current_api_key)
MM_STATE = mma.MmaState(STATE.history, current_api_key)
HB_STATE = handball.HandballState(STATE.history, current_api_key)


DROP_SPORTS = {"football": pw.SOCCER, "basketball": bb.SPORT_ID, "tennis": tennis.SPORT_ID, "hockey": hockey.SPORT_ID,
               "mma": mma.SPORT_ID, "handball": handball.SPORT_ID}
DROP_RECHECK = 15  # seconds PinnWire holds a drop and re-reads the price before pushing it (drops that bounce back are dropped)
DROP_KEEP = 3 * 3600  # seconds of drops kept for the UI, like PinnWire's own /api/drops buffer


class DropFeed:
    """Background reader of PinnWire's prematch SSE drop stream. It keeps every drop of at least 1 %
    (the UI filters by its own threshold) and does not use REST requests."""

    def __init__(self, key_fn, sports=None):
        self.key_fn = key_fn
        self.sports = set(sports or DROP_SPORTS.values())
        self.lock = threading.Lock()
        self.drops = deque(maxlen=20000)
        self.connected = False
        self.error = ""
        self.since = ""
        self.thread = None
        self.generation = 0  # bumped by reconnect() so the stream with the old key stops

    def start(self):
        with self.lock:
            if self.thread is None:
                self.thread = threading.Thread(target=self.run, name="pinnwire-drops", daemon=True)
                self.thread.start()

    def reconnect(self):
        with self.lock:
            self.generation += 1

    def add(self, frames):
        kept = [d for d in map(pw.normalize_drop, frames) if d and d["sport_id"] in self.sports]
        with self.lock:
            self.drops.extend(kept)
            cutoff = time.time() - DROP_KEEP
            while self.drops and self.drops[0]["alerted"] < cutoff:
                self.drops.popleft()
        return len(kept)

    def recent(self, sport_id, min_pct, max_age):
        cutoff = time.time() - max_age
        with self.lock:
            return [d for d in self.drops
                    if d["sport_id"] == sport_id and d["drop_pct"] >= min_pct and d["alerted"] >= cutoff]

    def status(self):
        return {"connected": self.connected, "error": self.error, "since": self.since}

    api_factory = pw.PinnWireAPI  # replaced in tests
    sleep = staticmethod(time.sleep)

    def run(self):
        wait = 1
        while True:
            wait = self.cycle(wait)

    def cycle(self, wait):
        """One connection: read the stream until it ends or fails, then wait before the next one.

        Returns the wait for the next failure: doubling up to 30 s, reset to 1 s once a frame arrives, 60 s after
        PinnWire refuses the key or the plan; no wait when reconnect() asked for a new key."""
        key = self.key_fn()
        if not key:
            self.sleep(5)
            return wait
        generation = self.generation
        previous_error, bug = self.error, None
        try:
            stream = self.api_factory(key).drop_stream(min_drop=1, recheck=DROP_RECHECK,
                                                       stop=lambda: self.generation != generation)
            for frames in stream:
                if not self.connected:
                    self.connected, self.error, self.since, wait = True, "", utc_stamp(), 1
                    log.info("Drop stream povezan")
                self.add(frames)
            self.error = ""
        except PermissionError as exc:
            self.error, wait = str(exc), 60
        except RuntimeError as exc:
            self.error = str(exc)
        except Exception as exc:  # noqa: BLE001 (the stream must outlive a bug in one frame, like ClvWorker)
            self.error, bug = f"Greška u drop streamu: {exc!r}", exc
        if self.connected:
            log.info("Drop stream prekinut (povezan od %s)", self.since)
        if self.error and self.error != previous_error:  # the same failure again is not a new log line
            log.log(logging.ERROR if bug else logging.WARNING, "Drop stream: %s", self.error, exc_info=bug)
        self.connected = False
        if self.generation != generation:
            return 1  # reconnect(): the new key connects right away
        self.sleep(wait)
        return min(wait * 2, 30)

DROPS = DropFeed(current_api_key)
SPORT_STATES = {"football": STATE, "basketball": BB_STATE, "tennis": TN_STATE, "hockey": HK_STATE, "mma": MM_STATE,
                "handball": HB_STATE}
for _sport, _state in SPORT_STATES.items():
    _state.label = _sport

CLV_REFRESH = 30  # seconds between background boards when nobody refreshes in the browser
CLV_REFRESH_SOON = 10  # ... while a signalled match starts within 15 minutes, to catch its closing line
STATUS_EVERY = 3600  # seconds between the status lines in the log


def log_status(states):
    """One line of how the app stands, so the log shows a slow decline as well as outright failures."""
    sports = ", ".join(f"{sport} {len(state.events or ())}/{len(state.pairs)}" for sport, state in states.items())
    log.info("Stanje (mečevi/upareni): %s; drop stream %s", sports, "povezan" if DROPS.connected else "nije povezan")


class ClvWorker:
    """Keeps boards fresh without a browser so the closing line of every signal is recorded before kickoff.
    A board refreshed by the UI counts too: only sports not observed for a while are fetched."""

    def __init__(self, store, states):
        self.store = store
        self.states = states
        self.started = False

    def start(self):
        if not self.started:
            self.started = True
            threading.Thread(target=self.run, name="clv-worker", daemon=True).start()

    def run(self):
        next_status = 0.0
        while True:
            interval = CLV_REFRESH_SOON if self.store.soon() else CLV_REFRESH
            self.tick(interval)
            if time.monotonic() >= next_status:
                log_status(self.states)
                next_status = time.monotonic() + STATUS_EVERY
            time.sleep(2)

    def tick(self, interval):
        if not current_api_key():
            return
        for sport, state in self.states.items():
            if time.time() - self.store.last_seen.get(sport, 0) < interval:
                continue
            try:
                state.board(refresh=True)
            except (PermissionError, LookupError, RuntimeError):
                self.store.last_seen[sport] = time.time()  # retry after one interval, not in a tight loop
            except Exception as exc:  # the worker must outlive a parsing bug in one sport
                self.store.last_seen[sport] = time.time()
                log.error("CLV worker, %s: %r", sport, exc, exc_info=exc)


CLV = None  # opened by start_clv(), so importing this module (tests) never touches data/clv.sqlite3


def start_clv(path=CLV_PATH):
    """Open the CLV store, hand it to the sport states and start the background worker."""
    global CLV
    CLV = clv.ClvStore(path)
    for state in SPORT_STATES.values():
        state.clv = CLV
    ClvWorker(CLV, SPORT_STATES).start()


PRICES = None  # opened by start_prices(), like CLV


def start_prices(path=PRICES_PATH):
    """Open the price history store and hand it to the sport states (ClvWorker keeps it filling)."""
    global PRICES
    PRICES = price_history.PriceStore(path)
    for state in SPORT_STATES.values():
        state.prices = PRICES


def history_response(query):
    """Stored price history of one board match, for the line-movement charts in the odds modals."""
    if PRICES is None:
        raise LookupError("Istorija kvota nije otvorena.")
    sport = (query.get("sport") or ["football"])[0]
    match_id = (query.get("id") or [""])[0]
    if sport not in SPORT_STATES or not match_id.isdigit():
        raise LookupError("Neispravni parametri.")
    return {"series": PRICES.series(sport, match_id), "keepHours": price_history.KEEP_HOURS}


def clv_response(query):
    if CLV is None:
        raise LookupError("CLV baza nije otvorena.")
    sport = (query.get("sport") or [""])[0] or None
    if sport is not None and sport not in SPORT_STATES:
        raise LookupError("Nepoznat sport.")
    try:
        days = min(365, max(1, int((query.get("days") or ["30"])[0])))
    except ValueError:
        raise LookupError("Neispravni parametri.")
    return CLV.stats(sport=sport, days=days)


def drops_response(query):
    """Recent prematch drops of one sport from the SSE buffer, each with the board match it belongs to and,
    for paired matches, the MerkurXtip price of the same outcome (`merkur / nvp - 1` is its edge)."""
    sport = (query.get("sport") or ["football"])[0]
    if sport not in DROP_SPORTS:
        raise LookupError("Nepoznat sport.")
    try:
        min_pct = max(1.0, float((query.get("min") or ["3"])[0]))
        max_age = min(DROP_KEEP, max(10, int((query.get("age") or ["300"])[0])))
    except ValueError:
        raise LookupError("Neispravni parametri.")
    state = SPORT_STATES[sport]
    quotes = state.quotes
    owns = getattr(state, "owns", None)  # handball shares its PinnWire sport with volleyball
    now = time.time()
    out = []
    for d in DROPS.recent(DROP_SPORTS[sport], min_pct, max_age):
        if owns and not owns(d["event_id"]):
            continue
        match_id, index = quotes.get(str(d["event_id"]), (None, {}))
        quote = index.get(pw.drop_key(d["market"], d["period"], d["side"], d["points"]))
        merkur = None
        if quote:
            fair = d["nvp"] or quote["fair"]
            merkur = {"odds": quote["merkur"], "ev": round(quote["merkur"] / fair - 1, 4)}
        out.append({**d, "match_id": match_id, "age_s": max(0, round(now - d["alerted"])), "merkur": merkur})
    return {"drops": out, "stream": DROPS.status(), "callsToday": STATE.history.calls_today()}


# /api/board, /api/match/<id>, /api/<sport>/board, /api/<sport>/match/<id>
SPORT_ROUTE = re.compile(r"/api/(?:(basketball|tennis|hockey|mma|handball)/)?(board|match/(.*))")


class Handler(BaseHTTPRequestHandler):
    server_version = "PinnWireDashboard/1.0"
    static_root = STATIC

    def log_message(self, fmt, *args):
        pass

    def send_json(self, status, body):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_error_json(self, status, message):
        self.send_json(status, {"error": message})

    def serve_static(self, path):
        relative = "index.html" if path in ("", "/") else path.lstrip("/")
        candidate = os.path.abspath(os.path.join(self.static_root, relative))
        if os.path.commonpath((self.static_root, candidate)) != self.static_root or not os.path.isfile(candidate):
            return self.send_error_json(404, "Stranica nije pronađena. Pokreni `npm run build` u frontend folderu.")
        try:
            with open(candidate, "rb") as static_file:
                content = static_file.read()
        except OSError as exc:
            return self.send_error_json(500, f"Ne mogu da pročitam statički fajl: {exc}")
        content_type = (STATIC_TYPES.get(os.path.splitext(candidate)[1].lower())
                        or mimetypes.guess_type(candidate)[0] or "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        # the page, service worker and manifest must be revalidated so a new build is picked up
        no_cache = relative in ("index.html", "sw.js", "manifest.webmanifest")
        self.send_header("Cache-Control", "no-cache" if no_cache else "public, max-age=3600")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path
        query = parse_qs(url.query)
        refresh = query.get("refresh") == ["1"]
        full = query.get("full") == ["1"]
        try:
            if path == "/api/status":
                return self.send_json(200, {"apiKeySet": bool(current_api_key()),
                                            "callsToday": STATE.history.calls_today()})
            if path == "/api/clv":
                return self.send_json(200, clv_response(query))
            if path == "/api/history":
                return self.send_json(200, history_response(query))
            if path == "/api/drops":
                return self.send_json(200, drops_response(query))
            route = SPORT_ROUTE.fullmatch(path)
            if route:
                sport, endpoint, event_id = route.group(1) or "football", route.group(2), route.group(3)
                state = SPORT_STATES[sport]
                if endpoint == "board":  # else "match/<id>"
                    return self.send_json(200, state.board(refresh=refresh, full=full))
                event_id = unquote(event_id or "").strip("/")
                if not event_id.isdigit():
                    return self.send_error_json(400, "Neispravan ID događaja.")
                # only football re-reads a match from PinnWire; the other sports take it from the snapshot
                extra = {"refresh": refresh} if sport == "football" else {}
                return self.send_json(200, state.match(event_id, **extra))
            return self.serve_static(path)
        except PermissionError as exc:
            return self.send_error_json(401, str(exc))
        except (KeyError, IndexError) as exc:  # LookupError subclasses, but only ever raised by a bug
            return self.internal_error(exc)
        except LookupError as exc:
            return self.send_error_json(404, str(exc))
        except RuntimeError as exc:
            return self.send_error_json(502, str(exc))
        except ConnectionError:
            return  # the browser went away mid-response (aborted fetch)
        except Exception as exc:  # noqa: BLE001 (a bug answers 500 instead of dropping the connection)
            return self.internal_error(exc)

    def internal_error(self, exc):
        log.error("%s %s: %r", self.command, urlparse(self.path).path, exc, exc_info=exc)
        return self.send_error_json(500, f"Interna greška servera: {exc!r}")

    def do_POST(self):
        if urlparse(self.path).path != "/api/config":
            return self.send_error_json(404, "Ruta nije pronađena.")
        # a JSON body needs a CORS preflight, which this server never grants, so another site open in the
        # browser cannot post a form or text/plain body here and replace the API key
        if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
            return self.send_error_json(415, "Zahtev mora biti application/json.")
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length > 4096:
                return self.send_error_json(413, "Zahtev je prevelik.")
            body = json.loads(self.rfile.read(content_length) or b"{}")
            if not isinstance(body, dict):
                return self.send_error_json(400, "Neispravan format podešavanja.")
            save_api_key(body.get("apiKey", ""))
            log.info("API ključ je promenjen")
            for state in SPORT_STATES.values():
                state.reset()
            DROPS.reconnect()
            return self.send_json(200, {"apiKeySet": True})
        except (ValueError, json.JSONDecodeError) as exc:
            return self.send_error_json(400, str(exc))
        except RuntimeError as exc:
            return self.send_error_json(500, str(exc))
        except OSError as exc:
            return self.send_error_json(500, f"Ne mogu da sačuvam podešavanje: {exc}")
        except Exception as exc:  # noqa: BLE001 (a bug answers 500 instead of dropping the connection)
            return self.internal_error(exc)


def main():
    parser = argparse.ArgumentParser(description="PinnWire top competitions dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8070)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    if not os.path.isfile(os.path.join(STATIC, "index.html")):
        parser.error("React app is not built. Run `npm run build` in frontend/.")

    # On Windows SO_REUSEADDR lets a second server bind the same port silently; fail instead.
    ThreadingHTTPServer.allow_reuse_address = os.name != "nt"
    try:
        httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as exc:
        parser.error(f"Port {args.port} je zauzet (da li dashboard već radi?): {exc}")
    host = "127.0.0.1" if args.host in ("0.0.0.0", "") else args.host
    url = f"http://{host}:{args.port}"
    applog.setup(LOGS)  # after the bind: a second server that exits above must not touch the first one's log
    log.info("Server pokrenut: %s  (Ctrl+C za prekid)", url)
    DROPS.start()
    start_prices()
    start_clv()
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log.info("Server zaustavljen")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
