"""Code shared by every sport: time helpers, delta merging, MerkurXtip line decoding, compare rows, value items and
the PinnWire snapshot state (fetching, delta merging, the MerkurXtip offer cache).

This module must not import `pinnwire_dashboard` (run as a script that module is `__main__`).
"""
from __future__ import annotations

import re
import threading
import time
import unicodedata
from datetime import datetime, timezone

import merkur_client as mx
import pinnwire_client as pw

FULL_RELOAD_SECONDS = 3600  # take a fresh full snapshot at least hourly; deltas in between


# ------------------------------------------------------------------------- time and events

def utc_now():
    return datetime.now(timezone.utc)


def utc_stamp():
    return utc_now().isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_time(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def starts(event):
    return event.get("starts") or event.get("start_ts") or ""


def event_ts(event):
    when = parse_time(starts(event))
    return int(when.timestamp() * 1000) if when else 0


def is_upcoming(event, now=None):
    when = parse_time(starts(event))
    return when is None or when > (now or utc_now())


def merge_event(old, new):
    """Apply a delta event on top of the stored one, market by market per period."""
    merged = {**old, **{k: v for k, v in new.items() if k != "periods"}}
    periods = dict(old.get("periods") or {})
    for key, markets in (new.get("periods") or {}).items():
        if isinstance(markets, dict):
            periods[key] = {**(periods.get(key) or {}), **markets}
    merged["periods"] = periods
    return merged


PRICED_MARKETS = ("money_line", "spreads", "totals", "team_total", "team_totals")


def _quoted(value):
    if isinstance(value, dict):
        return any(_quoted(v) for v in value.values())
    return value not in (None, "", 0)


def has_prices(event):
    """True while any period of the event still carries a Pinnacle price (a market merged in as null does not count)."""
    return event.get("is_have_odds") is not False and any(
        isinstance(markets, dict) and any(_quoted(markets.get(k)) for k in PRICED_MARKETS)
        for markets in (event.get("periods") or {}).values())


# ------------------------------------------------------------------------- decoding

def team_ladders(markets):
    """{"home": ladder, "away": ladder} of a period's team totals; the main team total PinnWire sometimes quotes
    on its own, outside the ladder, fills a line the ladder lacks."""
    team, main = markets.get("team_totals") or {}, markets.get("team_total") or {}
    out = {}
    for side in ("home", "away"):
        lines = pw.ladder(team.get(side), "points", ("over", "under"))
        single = pw.ladder({side: main.get(side)}, "points", ("over", "under"))
        out[side] = {**single, **lines}
    return out


def param_lines(row, sets, sides, market="totals"):
    """MerkurXtip lines whose value is a `params` entry: sets of (line param, first side code, second side code)
    -> {line: {side: odds}}, the first set with a line wins."""
    raw, params = row.get("odds") or {}, row.get("params") or {}
    out = {}
    for key, first, second in sets:
        line = mx._param_line(params, key)
        prices = mx._pick(raw, dict(zip(sides, (first, second))))
        if pw.allowed_line(line, market) and prices and line not in out:
            out[line] = prices
    return out


# ------------------------------------------------------------------------- comparison

def compare_row(group, line, labels, merkur, pinnacle, max_bet=None, derived=False):
    """One market: MerkurXtip odds against Pinnacle fair odds. ev = MerkurXtip / fair - 1.

    `merkur` may hold only some of the sides (a football handicap derived from a European handicap has one);
    only the sides MerkurXtip prices become outcomes. The MerkurXtip margin needs both sides of a direct price,
    so it is None for partial and derived rows.
    """
    fair, pin_margin = pw.fair_odds(pinnacle)
    outcomes = [{"key": key, "label": label, "merkur": merkur[key], "pinnacle": pinnacle[key],
                 "fair": round(fair[key], 3), "ev": round(merkur[key] / fair[key] - 1, 4)}
                for key, label in labels if key in merkur]
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


def market_label(group, line):
    if group == "Hendikep" and line == 0:
        return "X vraća ulog"  # AH 0 = MerkurXtip draw no bet
    return group + ("" if line is None else f" {line:g}")


def best_edge(period_rows, prefixes):
    """The outcome with the largest edge over [(period key, compare row)]; `prefixes` label the periods."""
    best = None
    for period, r in period_rows:
        for o in r["outcomes"]:
            if best is None or o["ev"] > best["ev"]:
                best = {"ev": o["ev"], "label": f"{prefixes[period]}{market_label(r['group'], r['line'])} {o['label']}"}
    return best


def value_items(match_id, period_rows, period_labels, label=None, stale=None):
    """Every outcome where the MerkurXtip price beats the Pinnacle price, over [(period key, compare row)], with
    pw.best_per_line_market() applied. `label(row, outcome)` renames an outcome, `stale(period, row, outcome)` is
    the MerkurXtip main line gap that favours it (basketball)."""
    items = []
    for period, r in period_rows:
        for o in r["outcomes"]:
            if o["merkur"] <= o["pinnacle"]:
                continue
            items.append({
                "matchId": match_id, "period": period, "periodLabel": period_labels[period], "group": r["group"],
                "line": r["line"], "key": o["key"], "label": label(r, o) if label else o["label"],
                "merkur": o["merkur"], "pinnacle": o["pinnacle"], "fair": o["fair"], "ev": o["ev"],
                "overPinnacle": round(o["merkur"] / o["pinnacle"] - 1, 4),
                "merkurMargin": r["merkurMargin"], "pinnacleMargin": r["pinnacleMargin"],
                "derived": bool(r.get("derived")), "modeled": bool(r.get("modeled")),
                "stale": stale(period, r, o) if stale else None,
            })
    return pw.best_per_line_market(items)


# ------------------------------------------------------------------------- leagues outside the tracked ones

# Matches of leagues a sport does not track: they are paired against the whole MerkurXtip offer, so the "missing"
# view can show what MerkurXtip does not sell. Without a competition check only names and kickoff pair a match,
# hence the stricter rules.
OTHER_WINDOW = 3 * 60
OTHER_MIN_SCORE = 0.75
# a women's, youth or reserve side never pairs with the senior side of the same club
SIDE_MARKERS = {"w", "women", "u17", "u18", "u19", "u20", "u21", "u23", "ii", "b", "res", "reserves"}


def side_markers(name):
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return SIDE_MARKERS.intersection(re.findall(r"[a-z0-9]+", text))


def other_score(pinnacle, merkur):
    return 0.0 if side_markers(pinnacle) != side_markers(merkur) else mx.name_score(pinnacle, merkur)


def split_league(name):
    """"England - EFL Cup" -> ("England", "EFL Cup"); names without a country stay whole."""
    country, sep, league = (name or "").partition(" - ")
    return (country.strip(), league.strip()) if sep else ("Ostalo", (name or "").strip())


def other_competitions(matches):
    counts = {}
    for m in matches:
        counts[m["leagueId"]] = (m["leagueName"], counts.get(m["leagueId"], (None, 0))[1] + 1)
    out = []
    for league_id, (name, count) in counts.items():
        country, league = split_league(name)
        out.append({"id": league_id, "key": f"x{league_id}", "name": league or name, "country": country,
                    "code": "•", "badge": "other", "count": count})
    return sorted(out, key=lambda c: (c["country"], c["name"]))


def offered_other(events, rows):
    """Untracked leagues whose matches MerkurXtip offers, for adding them: PinnWire league, the MerkurXtip league
    its matches pair with and how many matches."""
    league = {str(e["event_id"]): e for e in events}
    out = {}
    for pid, row in rows.items():
        e = league[pid]
        entry = out.setdefault(e["league_id"], {"leagueId": e["league_id"], "leagueName": e.get("league_name") or "",
                                                "mxLeagueId": row.get("leagueId"), "mxLeague": row.get("leagueShort") or "",
                                                "count": 0})
        entry["count"] += 1
    return sorted(out.values(), key=lambda x: (-x["count"], x["leagueName"]))


def unpaired_other(events, offer, used, merkur_ts=lambda r: r.get("kickOffTime") or 0):
    """({pinnacle id} unpaired, {pinnacle id: hint}, {pinnacle id: MerkurXtip row} paired) of untracked events;
    `used` are MerkurXtip ids already paired within the tracked competitions."""
    pin = [{"id": str(e["event_id"]), "comp": "*", "home": e.get("home", ""), "away": e.get("away", ""),
            "ts": event_ts(e)} for e in events]
    mer = [{"id": r["id"], "comp": "*", "home": r.get("home", ""), "away": r.get("away", ""),
            "ts": merkur_ts(r), "row": r} for r in offer if r["id"] not in used and mx.is_prematch(r)]
    paired = mx.pair(pin, mer, OTHER_WINDOW, OTHER_MIN_SCORE, other_score)
    hints = mx.hints(pin, mer, paired, OTHER_WINDOW, other_score)
    return {p["id"] for p in pin} - paired.keys(), hints, {pid: m["row"] for pid, (m, _) in paired.items()}


# ------------------------------------------------------------------------- state

class SnapshotState:
    """One sport's PinnWire snapshot (full load, then `since=` deltas merged in) and its MerkurXtip offer cache.

    Subclasses set `sport_id` / `offer_path` and may override the hooks `incoming` (events of a response worth
    keeping), `merge` (delta merge) and `merged` (runs under the lock after a fetch, returns the changed count).
    """

    sport_id = pw.SOCCER
    offer_path = mx.OFFER_PATH
    alt_units = False  # ask PinnWire for the side-market events too

    def __init__(self, history, key_fn, merkur=None):
        self.history = history  # shared by every sport: opening prices (football) and the request counter
        self.key_fn = key_fn
        self.lock = threading.Lock()
        self.fetch_lock = threading.Lock()
        self.merkur = merkur or mx.OfferCache(mx.MerkurAPI(offer_path=self.offer_path))
        self.merkur_lock = threading.Lock()
        self.pairs = {}  # pinnacle event id -> (merkur offer row, name score)
        self.quotes = {}  # PinnWire event id -> (board match id, MerkurXtip prices by drop_key), from the last board
        self.clv = None  # ClvStore that records value signals and closing lines at every board
        self.prices = None  # PriceStore that records every compared price change at every board
        self.api = None
        self.api_key = None
        self.events = None  # {event_id str: raw event}
        self.last = None  # PinnWire cursor for the next delta request
        self.full_at = 0.0
        self.fetched_at = ""
        self.mode = ""
        self.changed = 0
        self.suspended = {}  # event id str -> {"event": last priced event, "since": stamp}; matches Pinnacle stopped quoting

    # ----- hooks
    def incoming(self, data):
        return [e for e in data.get("events") or [] if e.get("event_id") and pw.is_main_fixture(e)]

    def merge(self, old, new):
        return merge_event(old, new)

    def merged(self, incoming, stamp):
        return len(incoming)

    # ----- fetching
    def get_api(self):
        key = self.key_fn()
        if not key:
            raise PermissionError("Unesi PinnWire API ključ da učitaš ponudu.")
        with self.lock:
            if self.api is None or self.api_key != key:
                self.api = pw.PinnWireAPI(key)
                self.api_key = key
                self.events = None
                self.last = None
                self.suspended = {}
            return self.api

    def reset(self):
        with self.lock:
            self.api = None
            self.api_key = None
            self.events = None
            self.last = None
            self.suspended = {}

    def _fetch(self, full):
        api = self.get_api()
        since = None if full else self.last
        before = api.calls
        try:
            data = api.prematch_snapshot(self.sport_id, since=since, alt_units=self.alt_units)
        finally:
            self.history.count_calls(api.calls - before)
        stamp = utc_stamp()
        incoming = self.incoming(data)
        with self.lock:
            events = {} if since is None else dict(self.events or {})
            for raw in incoming:
                key = str(raw["event_id"])
                events[key] = self.merge(events[key], raw) if key in events and since else raw
            now = utc_now()
            previous = self.events
            self.events = {k: e for k, e in events.items() if is_upcoming(e, now)}
            self.track_suspended(previous, self.events, since is None, stamp)
            if since is None:
                self.full_at = time.monotonic()
            self.last = data.get("last") or self.last
            self.fetched_at = stamp
            self.mode = "delta" if since else "full"
            self.changed = self.merged(incoming, stamp)
        try:
            self.history.save()
        except OSError:
            pass

    def track_suspended(self, previous, current, full, stamp):
        """Remember upcoming matches that had a Pinnacle price and lost it: dropped from a full snapshot, or kept
        in a delta without any price. A match that is priced again leaves the list (caller holds `lock`)."""
        for key, event in current.items():
            if has_prices(event):
                self.suspended.pop(key, None)
        for key, old in (previous or {}).items():
            if key in self.suspended or not has_prices(old):
                continue
            now = current.get(key)
            if (now is None and full) or (now is not None and not has_prices(now)):
                self.suspended[key] = {"event": old, "since": stamp}
        now = utc_now()
        self.suspended = {k: v for k, v in self.suspended.items() if is_upcoming(v["event"], now)}

    def suspended_items(self):
        with self.lock:
            entries = list(self.suspended.items())
        out = []
        for key, entry in entries:
            event = entry["event"]
            prices = pw.full_match(event).get("money_line") or {}
            out.append({"id": key, "leagueId": event.get("league_id"), "leagueName": event.get("league_name"),
                        "home": event.get("home"), "away": event.get("away"), "starts": starts(event),
                        "since": entry["since"],
                        "ml": {k: v for k, v in prices.items() if k in ("home", "draw", "away") and v}})
        return sorted(out, key=lambda m: (m["starts"] or "", m["home"] or ""))

    def refresh(self, full=False, if_empty=False):
        with self.fetch_lock:
            if if_empty and self.events is not None:
                return  # a concurrent request loaded the snapshot while we waited
            need_full = (full or self.events is None or self.last is None
                         or time.monotonic() - self.full_at > FULL_RELOAD_SECONDS)
            self._fetch(need_full)

    def merkur_offer(self, refresh=False):
        with self.merkur_lock:
            return self.merkur.get(refresh=refresh, stamp_fn=utc_stamp)

    def record(self, sport, observed, values):
        """Hand one board's compare rows to the CLV and price history stores; annotate its value items."""
        if self.clv:
            self.clv.observe(sport, observed)
        if self.prices:
            self.prices.observe(sport, observed)
            self.prices.annotate(sport, values)
