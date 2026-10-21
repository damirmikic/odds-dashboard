#!/usr/bin/env python3
"""PinnWire top-competitions dashboard: top 5 leagues + UEFA club competitions, Pinnacle only.

The first load takes the full soccer snapshot; refreshes ask only for events changed since
the previous response (`since=last`) and merge them, which keeps the trial quota usable.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import threading
import time
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import basketball as bb
import tennis
import merkur_client as mx
import pinnwire_client as pw

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
STATIC = os.path.join(ROOT, "static", "dashboard_build")
CONFIG_PATH = os.path.join(DATA, "pinnwire_config.json")
HISTORY_PATH = os.path.join(DATA, "dashboard_history.json")

# PinnWire league_id -> display info; order is the tab order in the UI.
# `merkur` is the MerkurXtip `leagueShort` of the same competition.
COMPETITIONS = [
    {"id": 1980, "key": "epl", "name": "Premier League", "country": "Engleska", "code": "ENG", "merkur": "ENG PL"},
    {"id": 2196, "key": "laliga", "name": "La Liga", "country": "Španija", "code": "ESP", "merkur": "ESP LL"},
    {"id": 2436, "key": "seriea", "name": "Serie A", "country": "Italija", "code": "ITA", "merkur": "ITA SA"},
    {"id": 1842, "key": "bundesliga", "name": "Bundesliga", "country": "Nemačka", "code": "GER", "merkur": "GER BL"},
    {"id": 2036, "key": "ligue1", "name": "Ligue 1", "country": "Francuska", "code": "FRA", "merkur": "FRA L1"},
    {"id": 2627, "key": "ucl", "name": "Liga šampiona", "country": "UEFA", "code": "UCL", "merkur": "UEFA CL"},
    {"id": 2630, "key": "uel", "name": "Liga Evrope", "country": "UEFA", "code": "UEL", "merkur": "UEFA EL"},
    {"id": 214101, "key": "uecl", "name": "Liga konferencija", "country": "UEFA", "code": "UECL",
     "merkur": "UEFA ECFL"},
    {"id": 2386, "key": "ligapt", "name": "Liga Portugal", "country": "Portugal", "code": "POR", "merkur": "POR LP"},
    {"id": 1928, "key": "eredivisie", "name": "Eredivisie", "country": "Holandija", "code": "NED", "merkur": "NLD ERE"},
    {"id": 2592, "key": "superlig", "name": "Süper Lig", "country": "Turska", "code": "TUR", "merkur": "TUR SL"},
    {"id": 1977, "key": "championship", "name": "Championship", "country": "Engleska", "code": "ENG2",
     "merkur": "ENG CH"},
    {"id": 1843, "key": "bundesliga2", "name": "2. Bundesliga", "country": "Nemačka", "code": "GER2",
     "merkur": "GER 2BL"},
    {"id": 1817, "key": "jupiler", "name": "Jupiler Pro League", "country": "Belgija", "code": "BEL",
     "merkur": "BEL PL"},
    {"id": 210697, "key": "ligaarg", "name": "Liga Profesional", "country": "Argentina", "code": "ARG",
     "merkur": "ARG LPF"},
    {"id": 1913, "key": "superligadk", "name": "Superliga", "country": "Danska", "code": "DEN", "merkur": "DNK SL"},
    {"id": 2517, "key": "superligach", "name": "Super League", "country": "Švajcarska", "code": "SUI",
     "merkur": "SWI SL"},
    {"id": 2432, "key": "laliga2", "name": "La Liga 2", "country": "Španija", "code": "ESP2", "merkur": "ESP LL2"},
    {"id": 1834, "key": "brasileirao", "name": "Serie A", "country": "Brazil", "code": "BRA", "merkur": "BRA SA"},
    {"id": 2374, "key": "ekstraklasa", "name": "Ekstraklasa", "country": "Poljska", "code": "POL",
     "merkur": "POL EK"},
    {"id": 2395, "key": "liga1ro", "name": "Liga 1", "country": "Rumunija", "code": "ROU", "merkur": "ROM SL"},
    {"id": 2333, "key": "eliteserien", "name": "Eliteserien", "country": "Norveška", "code": "NOR",
     "merkur": "NOR ES"},
    {"id": 2421, "key": "scotprem", "name": "Premiership", "country": "Škotska", "code": "SCO", "merkur": "SCO PL"},
    {"id": 2663, "key": "mls", "name": "MLS", "country": "SAD", "code": "MLS", "merkur": "USA MLS"},
    {"id": 1957, "key": "leagueone", "name": "League One", "country": "Engleska", "code": "ENG3",
     "merkur": "ENG L1"},
    {"id": 1958, "key": "leaguetwo", "name": "League Two", "country": "Engleska", "code": "ENG4",
     "merkur": "ENG L2"},
    {"id": 1728, "key": "allsvenskan", "name": "Allsvenskan", "country": "Švedska", "code": "SWE",
     "merkur": "SWE ALL"},
    {"id": 5591, "key": "primeraco", "name": "Primera A", "country": "Kolumbija", "code": "COL",
     "merkur": "COL PA"},
    {"id": 2406, "key": "rpl", "name": "Premier liga", "country": "Rusija", "code": "RUS",
     "merkur": "RUS PL"},
    {"id": 1844, "key": "liga3", "name": "3. Liga", "country": "Nemačka", "code": "GER3",
     "merkur": "GER 3L"},
    {"id": 1891, "key": "firstligacz", "name": "1. liga", "country": "Češka", "code": "CZE",
     "merkur": "CZE 1L"},
    {"id": 10419, "key": "prosa", "name": "Pro liga", "country": "Saudijska Arabija", "code": "KSA",
     "merkur": "SAU PRO"},
    {"id": 2242, "key": "ligamx", "name": "Liga MX", "country": "Meksiko", "code": "MEX",
     "merkur": "MEX MX"},
    {"id": 1792, "key": "bundesligaat", "name": "Bundesliga", "country": "Austrija", "code": "AUT",
     "merkur": "AUT BL"},
    {"id": 2157, "key": "j1", "name": "J1 liga", "country": "Japan", "code": "JPN", "merkur": "JPN J1"},
]
LEAGUE_IDS = {c["id"] for c in COMPETITIONS}
MERKUR_COMP = {c["merkur"]: c["id"] for c in COMPETITIONS}
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
FULL_RELOAD_SECONDS = 3600  # take a fresh full snapshot at least hourly; deltas in between
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
        raise RuntimeError("data/pinnwire_config.json mora sadržati JSON objekat.")
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


def utc_now():
    return datetime.now(timezone.utc)


def utc_stamp():
    return utc_now().isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_time(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def is_tracked(event):
    return event.get("league_id") in LEAGUE_IDS and pw.is_main_fixture(event)


def is_upcoming(event, now=None):
    starts = parse_time(event.get("starts") or event.get("start_ts") or "")
    return starts is None or starts > (now or utc_now())


def merge_event(old, new):
    """Apply a delta event on top of the stored one, market by market per period."""
    merged = {**old, **{k: v for k, v in new.items() if k != "periods"}}
    periods = dict(old.get("periods") or {})
    for key, markets in (new.get("periods") or {}).items():
        if isinstance(markets, dict):
            periods[key] = {**(periods.get(key) or {}), **markets}
    merged["periods"] = periods
    return merged


# ------------------------------------------------------------------------- shaping

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
    ml, margin = money_line(event, number)
    return {
        "ml": ml,
        "margin": margin,
        "spreads": pw.build_lines(event, "spreads", ("home", "away"), "hdp", number),
        "totals": pw.build_lines(event, "totals", ("over", "under"), "points", number),
        "teamTotals": team_totals(event, number),
    }


def summary(event, track):
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


def pinnacle_lines(event, number):
    """Pinnacle prices of one period keyed like merkur_client.markets()."""
    markets = pw.period(event, number)

    def by_line(lines, key, sides, market):
        out = {}
        for line in (lines or {}).values():
            if isinstance(line, dict) and line.get(key) is not None and pw.allowed_line(float(line[key]), market):
                prices = pw.priced(line, sides)
                if len(prices) == len(sides):
                    out[float(line[key])] = prices
        return out

    ml = pw.priced(markets.get("money_line") or {}, ML_SIDES)
    return {
        "ml": ml if len(ml) == 3 else None,
        "totals": by_line(markets.get("totals"), "points", ("over", "under"), "totals"),
        "spreads": by_line(markets.get("spreads"), "hdp", ("home", "away"), "spreads"),
        "teamTotals": {side: by_line(lines, "points", ("over", "under"), "totals")
                       for side, lines in (markets.get("team_totals") or {}).items() if isinstance(lines, dict)},
    }


def pinnacle_max(event, number):
    """Pinnacle limit (max bet) per line, shaped like pinnacle_lines(); the 1X2 price carries no limit."""
    markets = pw.period(event, number)

    def by_line(lines, key, market):
        out = {}
        for line in (lines or {}).values():
            if isinstance(line, dict) and line.get(key) is not None and pw.allowed_line(float(line[key]), market):
                out[float(line[key])] = line.get("max")
        return out

    return {
        "totals": by_line(markets.get("totals"), "points", "totals"),
        "spreads": by_line(markets.get("spreads"), "hdp", "spreads"),
        "teamTotals": {side: by_line(lines, "points", "totals")
                       for side, lines in (markets.get("team_totals") or {}).items() if isinstance(lines, dict)},
    }


def compare_row(group, line, labels, merkur, pinnacle, derived=False, max_bet=None):
    """One market: Merkur odds against Pinnacle fair odds. ev = Merkur / fair - 1.

    `merkur` may hold only some of the sides (a handicap derived from a European handicap has one);
    only the sides Merkur prices become outcomes. The Merkur margin needs both sides of a direct
    two-way price, so it is None for partial and derived rows.
    """
    fair, pin_margin = pw.fair_odds(pinnacle)
    outcomes = []
    for key, label in labels:
        if key not in merkur:
            continue
        ev = merkur[key] / fair[key] - 1
        outcomes.append({"key": key, "label": label, "merkur": merkur[key], "pinnacle": pinnacle[key],
                         "fair": round(fair[key], 3), "ev": round(ev, 4)})
    complete = not derived and len(outcomes) == len(labels)
    return {
        "group": group,
        "line": line,
        "outcomes": outcomes,
        "derived": derived,
        "merkurMargin": round((sum(1 / o for o in merkur.values()) - 1) * 100, 2) if complete else None,
        "pinnacleMargin": pin_margin,
        "maxBet": max_bet,
        "maxEv": max(o["ev"] for o in outcomes),
    }


def compare_period(event, merkur_period, number):
    pin = pinnacle_lines(event, number)
    limits = pinnacle_max(event, number)
    rows = []
    for key, group, labels in COMPARE_GROUPS:
        if key == "ml":
            if merkur_period.get("ml") and pin["ml"]:
                rows.append(compare_row(group, None, labels, merkur_period["ml"], pin["ml"]))
            continue
        for line in sorted(merkur_period.get(key) or {}):
            if line in pin[key]:
                derived = key == "spreads" and line in merkur_period.get("derived", ())
                rows.append(compare_row(group, line, labels, merkur_period[key][line], pin[key][line], derived,
                                        limits[key].get(line)))
    for side, group in (("home", "Golovi domaćin"), ("away", "Golovi gost")):
        pin_side = pin["teamTotals"].get(side) or {}
        for line, prices in sorted(((merkur_period.get("teamTotals") or {}).get(side) or {}).items()):
            if line in pin_side:
                rows.append(compare_row(group, line, OU_SIDES, prices, pin_side[line],
                                        max_bet=limits["teamTotals"].get(side, {}).get(line)))
    return rows


def merkur_ts(row):
    return row.get("kickOffTime") or 0


def event_ts(event):
    starts = parse_time(event.get("starts") or event.get("start_ts") or "")
    return int(starts.timestamp() * 1000) if starts else 0


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


def value_items(match, rows):
    """Every outcome where the MerkurXtip price beats the Pinnacle price (with margin), one row each."""
    items = []
    for period, period_label in (("ft", "Ceo meč"), ("ht", "1. poluvreme")):
        for r in rows[period]:
            for o in r["outcomes"]:
                if o["merkur"] <= o["pinnacle"]:
                    continue
                label = o["label"]
                if r["group"] == "Hendikep":
                    label = match["home"] if o["key"] == "home" else match["away"]
                items.append({
                    "matchId": match["id"],
                    "period": period,
                    "periodLabel": period_label,
                    "group": r["group"],
                    "line": r["line"],
                    "key": o["key"],
                    "label": label,
                    "merkur": o["merkur"],
                    "pinnacle": o["pinnacle"],
                    "fair": o["fair"],
                    "ev": o["ev"],
                    "overPinnacle": round(o["merkur"] / o["pinnacle"] - 1, 4),
                    "merkurMargin": r["merkurMargin"],
                    "derived": r["derived"],
                    "pinnacleMargin": r["pinnacleMargin"],
                })
    return pw.best_per_line_market(items)


def best_edge(rows):
    best = None
    for period, prefix in (("ft", ""), ("ht", "1.pol ")):
        for r in rows[period]:
            for o in r["outcomes"]:
                if best is None or o["ev"] > best["ev"]:
                    if r["group"] == "Hendikep" and r["line"] == 0:
                        market = "X vraća ulog"  # AH 0 = MerkurXtip draw no bet
                    else:
                        market = r["group"] + ("" if r["line"] is None else f" {r['line']:g}")
                    best = {"ev": o["ev"], "label": f"{prefix}{market} {o['label']}"}
    return best


def merkur_summary(row, event, score):
    """Board cell data: 1X2 against fair odds, comparable goal lines and the largest edge anywhere."""
    decoded = mx.markets(row)
    rows = {"ft": compare_period(event, decoded[0], 0), "ht": compare_period(event, decoded[1], 1)}
    ml = next((r for r in rows["ft"] if r["group"] == "1X2"), None)
    return {
        **merkur_info(row, event, score),
        "ml": {o["key"]: {"odds": o["merkur"], "ev": o["ev"]} for o in ml["outcomes"]} if ml else None,
        "margin": ml["merkurMargin"] if ml else None,
        "totals": [r for r in rows["ft"] if r["group"] == "Ukupno golova"],
        "rows": rows,
        "best": best_edge(rows),
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


def pair_inputs(events, offer):
    pin = [{"id": str(e["event_id"]), "comp": e["league_id"], "home": e.get("home", ""),
            "away": e.get("away", ""), "ts": event_ts(e)} for e in events]
    mer = [{"id": r["id"], "comp": MERKUR_COMP[r["leagueShort"]], "home": r.get("home", ""),
            "away": r.get("away", ""), "ts": merkur_ts(r), "row": r}
           for r in offer if r.get("leagueShort") in MERKUR_COMP and mx.is_prematch(r)]
    return pin, mer


def pair_events(events, offer):
    pin, mer = pair_inputs(events, offer)
    return {pid: (m["row"], score) for pid, (m, score) in mx.pair(pin, mer).items()}


def unpaired_hints(events, offer):
    """{pinnacle id: closest unused MerkurXtip offer row} for events without a pair, for the "missing" view."""
    pin, mer = pair_inputs(events, offer)
    paired = mx.pair(pin, mer)
    ts = {p["id"]: p["ts"] for p in pin}
    return {pid: {"home": m["home"], "away": m["away"], "score": score, "kickoffDiff": round((m["ts"] - ts[pid]) / 60000)}
            for pid, (m, score) in mx.closest_unpaired(pin, mer, paired).items()}


# ------------------------------------------------------------------------- state

class History:
    """Opening and previous 1X2 prices per event plus a daily request counter, kept on disk."""

    def __init__(self, path=HISTORY_PATH):
        self.path = path
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
        return self.data["events"].get(str(event_id)) or {}

    def observe(self, event, stamp):
        ml = pw.priced(pw.full_match(event).get("money_line") or {}, ML_SIDES)
        if len(ml) < 3:
            return
        key = str(event.get("event_id"))
        track = self.data["events"].setdefault(key, {})
        if "open" not in track:
            track.update(open=ml, openAt=stamp, last=ml)
        elif track.get("last") != ml:
            track.update(prev=track.get("last"), last=ml, changedAt=stamp)

    def count_calls(self, calls):
        today = utc_now().date().isoformat()
        usage = self.data.get("usage") or {}
        if usage.get("date") != today:
            usage = {"date": today, "calls": 0}
        usage["calls"] += calls
        self.data["usage"] = usage

    def calls_today(self):
        usage = self.data.get("usage") or {}
        return usage.get("calls", 0) if usage.get("date") == utc_now().date().isoformat() else 0

    def prune(self, keep_ids):
        keep = {str(i) for i in keep_ids}
        self.data["events"] = {k: v for k, v in self.data["events"].items() if k in keep}

    def save(self):
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, ensure_ascii=False)
        os.replace(tmp, self.path)


class DashboardState:
    def __init__(self, history=None, merkur=None):
        self.lock = threading.Lock()
        self.merkur = merkur or mx.OfferCache()
        self.merkur_lock = threading.Lock()
        self.pairs = {}  # pinnacle event id -> (merkur offer row, name score)
        self.mx_track = {}  # merkur match id -> {last, prev, changedAt}: 1X2 movement this session
        self.goal_track = {}  # "pin|mx:<id>:<line>" -> {last, prev, changedAt}: board goal line movement
        self.fetch_lock = threading.Lock()
        self.api = None
        self.api_key = None
        self.history = history or History()
        self.events = None  # {event_id str: raw /kit event}, tracked competitions only
        self.last = None  # PinnWire cursor for the next delta request
        self.full_at = 0.0
        self.fetched_at = ""
        self.mode = ""
        self.changed = 0

    def get_api(self):
        key = current_api_key()
        if not key:
            raise PermissionError("Unesi PinnWire API ključ da učitaš ponudu.")
        with self.lock:
            if self.api is None or self.api_key != key:
                self.api = pw.PinnWireAPI(key)
                self.api_key = key
                self.events = None
                self.last = None
            return self.api

    def reset(self):
        with self.lock:
            self.api = None
            self.api_key = None
            self.events = None
            self.last = None

    def _fetch(self, full):
        api = self.get_api()
        since = None if full else self.last
        before = api.calls
        try:
            data = api.prematch_snapshot(pw.SOCCER, since=since)
        finally:
            self.history.count_calls(api.calls - before)
        stamp = utc_stamp()
        incoming = [e for e in data.get("events") or [] if e.get("event_id") and is_tracked(e)]
        with self.lock:
            events = {} if since is None else dict(self.events or {})
            for raw in incoming:
                key = str(raw["event_id"])
                events[key] = merge_event(events[key], raw) if key in events and since else raw
            now = utc_now()
            events = {k: e for k, e in events.items() if is_upcoming(e, now)}
            for key in {str(e["event_id"]) for e in incoming} & events.keys():
                self.history.observe(events[key], stamp)
            if since is None:
                self.full_at = time.monotonic()
            self.history.prune(events.keys())
            self.events = events
            self.last = data.get("last") or self.last
            self.fetched_at = stamp
            self.mode = "delta" if since else "full"
            self.changed = len(incoming)
        try:
            self.history.save()
        except OSError:
            pass

    def refresh(self, full=False, if_empty=False):
        with self.fetch_lock:
            if if_empty and self.events is not None:
                return  # a concurrent request loaded the snapshot while we waited
            need_full = (full or self.events is None or self.last is None
                         or time.monotonic() - self.full_at > FULL_RELOAD_SECONDS)
            self._fetch(need_full)

    def board(self, refresh=False, full=False):
        if refresh or full or self.events is None:
            self.refresh(full=full, if_empty=not (refresh or full))
        offer = self.merkur_offer(refresh=refresh or full)
        with self.lock:
            now = utc_now()
            events = [e for e in (self.events or {}).values() if is_upcoming(e, now)]
            matches = [summary(e, self.history.track(e["event_id"])) for e in events]
        pairs = pair_events(events, offer)
        hints = unpaired_hints(events, offer)
        self.pairs = pairs
        by_id = {str(e["event_id"]): e for e in events}
        values = []
        for m in matches:
            hit = pairs.get(str(m["id"]))
            m["merkur"] = merkur_summary(hit[0], by_id[str(m["id"])], hit[1]) if hit else None
            m["hint"] = hints.get(str(m["id"]))
            if m["merkur"]:
                m["merkur"].update(self.track_merkur(m["merkur"]))
            m["goals"] = goals_line(m, m["merkur"].pop("totals") if m["merkur"] else None)
            if m["merkur"]:
                values.extend(value_items(m, m["merkur"].pop("rows")))
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
        counts = {}
        for m in matches:
            counts[m["leagueId"]] = counts.get(m["leagueId"], 0) + 1
        return {
            "competitions": [{**c, "count": counts.get(c["id"], 0)} for c in COMPETITIONS],
            "matches": matches,
            "fetchedAt": self.fetched_at,
            "mode": self.mode,
            "changed": self.changed,
            "callsToday": self.history.calls_today(),
            "values": sorted(values, key=lambda v: v["ev"], reverse=True),
            "merkur": {
                "fetchedAt": self.merkur.stamp,
                "error": self.merkur.error,
                "paired": sum(1 for m in matches if m["merkur"]),
                "offered": sum(1 for r in offer if r.get("leagueShort") in MERKUR_COMP and mx.is_prematch(r)),
            },
        }

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

    def merkur_offer(self, refresh=False):
        with self.merkur_lock:
            return self.merkur.get(refresh=refresh, stamp_fn=utc_stamp)

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
            if path.startswith("/api/basketball/match/"):
                event_id = unquote(path[len("/api/basketball/match/"):].strip("/"))
                if not event_id.isdigit():
                    return self.send_error_json(400, "Neispravan ID događaja.")
                return self.send_json(200, BB_STATE.match(event_id))
            if path == "/api/basketball/board":
                return self.send_json(200, BB_STATE.board(refresh=refresh, full=full))
            if path.startswith("/api/tennis/match/"):
                event_id = unquote(path[len("/api/tennis/match/"):].strip("/"))
                if not event_id.isdigit():
                    return self.send_error_json(400, "Neispravan ID događaja.")
                return self.send_json(200, TN_STATE.match(event_id))
            if path == "/api/tennis/board":
                return self.send_json(200, TN_STATE.board(refresh=refresh, full=full))
            if path == "/api/board":
                return self.send_json(200, STATE.board(refresh=refresh, full=full))
            if path.startswith("/api/match/"):
                event_id = unquote(path[len("/api/match/"):].strip("/"))
                if not event_id.isdigit():
                    return self.send_error_json(400, "Neispravan ID događaja.")
                return self.send_json(200, STATE.match(event_id, refresh=refresh))
            return self.serve_static(path)
        except PermissionError as exc:
            return self.send_error_json(401, str(exc))
        except LookupError as exc:
            return self.send_error_json(404, str(exc))
        except RuntimeError as exc:
            return self.send_error_json(502, str(exc))

    def do_POST(self):
        if urlparse(self.path).path != "/api/config":
            return self.send_error_json(404, "Ruta nije pronađena.")
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length > 4096:
                return self.send_error_json(413, "Zahtev je prevelik.")
            body = json.loads(self.rfile.read(content_length) or b"{}")
            if not isinstance(body, dict):
                return self.send_error_json(400, "Neispravan format podešavanja.")
            save_api_key(body.get("apiKey", ""))
            STATE.reset()
            BB_STATE.reset()
            TN_STATE.reset()
            return self.send_json(200, {"apiKeySet": True})
        except (ValueError, json.JSONDecodeError) as exc:
            return self.send_error_json(400, str(exc))
        except RuntimeError as exc:
            return self.send_error_json(500, str(exc))
        except OSError as exc:
            return self.send_error_json(500, f"Ne mogu da sačuvam podešavanje: {exc}")


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
    print(f"PinnWire Dashboard: {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
