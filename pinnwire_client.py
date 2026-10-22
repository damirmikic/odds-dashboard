"""PinnWire (Pinnacle odds) REST client and football parsing helpers.

Docs: https://pinnwire.com/docs.html · https://pinnwire.com/llms-full.txt
"""
from __future__ import annotations

import math
import time

import requests

BASE = "https://pinnwire.com"
SOCCER = 1  # PinnWire sport_id for soccer (5 is American football)
MAX_RETRY_WAIT = 10.0  # seconds; longer Retry-After (e.g. daily quota) is reported, not slept


class PinnWireAPI:
    def __init__(self, key: str, min_interval: float = 0.2):
        self.key = key
        self.s = requests.Session()
        self.s.headers["x-api-key"] = key
        self.min_interval = min_interval
        self._last = 0.0
        self.calls = 0

    def get(self, path, **params):
        params = {k: v for k, v in params.items() if v is not None}
        last_err = None
        for attempt in range(4):
            wait = self.min_interval - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            try:
                r = self.s.get(f"{BASE}{path}", params=params, timeout=30)
            except requests.RequestException as e:
                last_err = e
                if attempt >= 1:
                    break
                time.sleep(1)
                continue
            self.calls += 1
            if r.status_code == 200:
                return r.json()
            body = self._body(r)
            if r.status_code == 401:
                raise PermissionError("PinnWire je odbio API ključ (invalid_key).")
            if r.status_code == 404:
                raise LookupError("PinnWire nema ovaj događaj (možda je počeo ili uklonjen).")
            if r.status_code == 429:
                retry = self._retry_after(r, body)
                if retry <= MAX_RETRY_WAIT and attempt < 3:
                    time.sleep(retry)
                    last_err = "HTTP 429"
                    continue
                window = body.get("window", "")
                raise RuntimeError(self._mask(
                    f"PinnWire limit zahteva je potrošen ({window}); pokušaj ponovo za {int(retry)} s."))
            if r.status_code >= 500 and attempt < 3:
                time.sleep(2 ** attempt)
                last_err = f"HTTP {r.status_code}"
                continue
            message = body.get("message") or body.get("error") or r.text[:300]
            raise RuntimeError(self._mask(f"{path} -> HTTP {r.status_code}: {message}"))
        raise RuntimeError(self._mask(f"{path} failed after retries: {last_err}"))

    @staticmethod
    def _body(r):
        try:
            data = r.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _retry_after(r, body):
        try:
            return float(r.headers.get("Retry-After"))
        except (TypeError, ValueError):
            return float(body.get("retry_after_ms") or 60000) / 1000

    def _mask(self, msg):
        """Never leak the API key into logs or the UI."""
        return msg.replace(self.key, "***") if self.key else msg

    def prematch_snapshot(self, sport_id=SOCCER, since=None, alt_units=False):
        """Raw fixtures response {events, last, ...}; with `since` only events changed after it.

        `alt_units` also lists each fixture's side markets as events with a parent_id (tennis games)."""
        data = self.get("/kit/v1/prematch/fixtures", sport_id=sport_id, since=since,
                        include_alt_units=1 if alt_units else None)
        return data if isinstance(data, dict) else {}

    def drops(self, sport_id, min_drop_pct=3, max_age_sec=300):
        """Recent prematch dropping-odds events (PinnWire keeps ~3 h): [{event_id, market, side, from, to, nvp, ...}]."""
        data = self.get("/api/drops", mode="prematch", sport_id=sport_id, min_drop_pct=min_drop_pct,
                        max_age_sec=max_age_sec, markets="moneyline,spread,total", periods="0", limit=500)
        return data.get("drops") or [] if isinstance(data, dict) else []

    def prematch_event(self, event_id):
        data = self.get("/kit/v1/prematch/markets", event_id=event_id)
        events = data.get("events") or [] if isinstance(data, dict) else []
        if not events:
            raise LookupError("PinnWire nije vratio podatke za ovaj događaj.")
        return events[0]


# ------------------------------------------------------------------------- parsing

def to_odds(value):
    """Decimal odds > 1.0, or None."""
    try:
        odds = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return odds if odds > 1.0 else None


def devig(odds):
    """{side: decimal odds} -> {side: fair probability}.

    Two-way markets use Shin's method, three-way (1X2) the power method. Both put more of the margin
    on long shots than proportional scaling; the power method overshoots on lopsided two-way prices
    (a 1.01 favourite makes the 8.12 underdog "fair" at 53), Shin stays close to it.
    """
    sides = list(odds)
    q = [1.0 / odds[s] for s in sides]
    if sum(q) <= 1.0:
        return {s: x / sum(q) for s, x in zip(sides, q)}
    if len(sides) == 2:
        return dict(zip(sides, _shin(q)))
    return dict(zip(sides, _power(q)))


def _shin(q):
    """Shin probabilities for implied probabilities q (sum > 1); z is the share of insider money."""
    total = sum(q)

    def probs(z):
        return [(math.sqrt(z * z + 4 * (1 - z) * x * x / total) - z) / (2 * (1 - z)) for x in q]

    lo, hi = 0.0, 0.4
    for _ in range(200):  # bisection: sum(probs) falls from > 1 at z = 0 towards 1 as z grows
        mid = 0.5 * (lo + hi)
        if sum(probs(mid)) > 1.0:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-12:
            break
    p = probs(0.5 * (lo + hi))
    return [x / sum(p) for x in p]


def _power(q):
    """Power method: p_i = q_i ** k with sum(p) = 1 (k > 1 when there is a margin)."""
    lo, hi = 1.0, 6.0
    for _ in range(200):  # bisection on k
        mid = 0.5 * (lo + hi)
        if sum(x ** mid for x in q) > 1.0:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-10:
            break
    k = 0.5 * (lo + hi)
    return [x ** k for x in q]


def best_per_line_market(items):
    """Value items with one entry per line market of a match: alternative lines of the same handicap
    or total (per period) collapse into the outcome with the largest edge. Markets without a line
    (1X2, winner) keep every outcome."""
    best = {}
    out = []
    for item in items:
        if item["line"] is None:
            out.append(item)
            continue
        key = (item["matchId"], item.get("period"), item["group"], item.get("modeled"))
        if key not in best or item["ev"] > best[key]["ev"]:
            best[key] = item
    return out + list(best.values())


def is_main_fixture(event):
    """Main match rows only: specials and alt units (corners, bookings) carry a parent_id."""
    return not event.get("parent_id") and (event.get("units") in (None, "", "Regular"))


def period(event, number=0):
    """Period markets: 0 = full match, 1 = first half."""
    return (event.get("periods") or {}).get(f"num_{number}") or {}


def full_match(event):
    return period(event, 0)


def priced(prices, sides):
    out = {side: to_odds(prices.get(side)) for side in sides}
    return {side: odds for side, odds in out.items() if odds}


def fair_odds(prices):
    """{side: odds} -> ({side: fair odds}, margin %) using the power devig method."""
    if len(prices) < 2:
        return {}, None
    probs = devig(prices)
    margin = (sum(1 / odds for odds in prices.values()) - 1) * 100
    return {side: 1 / p for side, p in probs.items()}, round(margin, 2)


def allowed_line(line, market):
    """Only half-goal lines (x.5) are kept: quarter and whole lines have push/half-win settlement that
    MerkurXtip does not sell. The one exception is the level handicap (AH 0), which MerkurXtip sells
    as "X vraća ulog" (draw no bet)."""
    if line is None:
        return False
    if market == "spreads" and line == 0:
        return True
    return abs(line * 2 - round(line * 2)) < 1e-9 and round(line * 2) % 2 == 1


def build_lines(event, market, sides, line_key, number=0):
    """Spreads or totals of one period as sorted rows with fair odds per side."""
    return lines_from((period(event, number).get(market) or {}).values(), sides, line_key, market)


def lines_from(lines, sides, line_key, market="totals"):
    rows = []
    for line in lines:
        if not isinstance(line, dict):
            continue
        prices = priced(line, sides)
        if len(prices) < 2:
            continue
        fair, margin = fair_odds(prices)
        rows.append({
            "line": _num(line.get(line_key)),
            "odds": prices,
            "fair": {side: round(odds, 3) for side, odds in fair.items()},
            "margin": margin,
            "max": line.get("max"),
        })
    rows = [row for row in rows if allowed_line(row["line"], market)]
    # main line first: the one whose prices are closest to even
    rows.sort(key=lambda row: abs(row["odds"][sides[0]] - row["odds"][sides[1]]))
    if rows:
        rows[0]["main"] = True
    return sorted(rows, key=lambda row: row["line"])


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
