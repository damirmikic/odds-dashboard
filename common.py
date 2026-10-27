"""Code shared by every sport: time helpers, delta merging, MerkurXtip line decoding, compare rows, value items and
the PinnWire snapshot state (fetching, delta merging, the MerkurXtip offer cache).

This module must not import `pinnwire_dashboard` (run as a script that module is `__main__`).
"""
from __future__ import annotations

import threading
import time
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
            self.events = {k: e for k, e in events.items() if is_upcoming(e, now)}
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
