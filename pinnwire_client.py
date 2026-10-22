"""PinnWire (Pinnacle odds) REST client and football parsing helpers.

Docs: https://pinnwire.com/docs.html · https://pinnwire.com/llms-full.txt
"""
from __future__ import annotations

import json
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

    def drop_stream(self, min_drop=1, recheck=None, stop=None):
        """Prematch drops pushed by PinnWire's SSE stream (plans with drops; not counted as REST requests).

        Yields one list of raw drop frames per `data:` line until the connection ends or `stop()` is true;
        `recheck` makes PinnWire hold each drop that many seconds and send it only if it still holds."""
        params = {"min_drop": min_drop, "recheck": recheck}
        try:
            r = self.s.get(f"{BASE}/odds-drop-prematch", params={k: v for k, v in params.items() if v is not None},
                           headers={"Accept": "text/event-stream"}, stream=True, timeout=(10, 90))
        except requests.RequestException as e:
            raise RuntimeError(self._mask(f"/odds-drop-prematch: {e}"))
        with r:
            if r.status_code in (401, 403):
                error = self._body(r).get("error") or r.status_code
                raise PermissionError(f"PinnWire ne dozvoljava drop stream ovom ključu ({error}).")
            if r.status_code != 200:
                raise RuntimeError(self._mask(f"/odds-drop-prematch -> HTTP {r.status_code}"))
            try:
                for line in r.iter_lines(decode_unicode=True):
                    if stop and stop():
                        return
                    if not line or not line.startswith("data:"):
                        continue  # ":ka" keep-alives and blank separators
                    try:
                        frame = json.loads(line[5:])
                    except ValueError:
                        continue
                    if isinstance(frame, list):
                        yield [d for d in frame if isinstance(d, dict)]
            except requests.RequestException as e:
                raise RuntimeError(self._mask(f"/odds-drop-prematch: {e}"))

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


DROP_MARKETS = ("moneyline", "spread", "total")  # team_total drops do not say which team


def normalize_drop(raw):
    """An SSE drop frame in the /api/drops field names; None for drops the dashboard does not use."""
    market = raw.get("market_type") or raw.get("market")
    if market not in DROP_MARKETS or raw.get("is_live"):
        return None
    try:
        return {
            "event_id": int(raw.get("id") or raw.get("event_id")),
            "sport_id": int(raw.get("sport_id")),
            "league": raw.get("league") or "",
            "home": raw.get("home") or "",
            "away": raw.get("away") or "",
            "market": market,
            "period": int(raw.get("period") or 0),
            "side": raw.get("outcome") or raw.get("side"),
            "points": _num(raw.get("points")),
            "from": float(raw.get("from_price") or raw.get("from")),
            "to": float(raw.get("to_price") or raw.get("to")),
            "drop_pct": float(raw.get("drop_pct") or 0),
            "nvp": _num(raw.get("nvp")),
            "starts": raw.get("starts") or "",
            "alerted": int(raw.get("alerted") or time.time()),
        }
    except (TypeError, ValueError):
        return None


def drop_key(market, period, side, points):
    """Key of a drop's outcome in quote_index(). Rows keep spreads as the home handicap, while a drop
    on the away side carries the away line (away +4 is hdp -4)."""
    line = None if market == "moneyline" else _num(points)
    if market == "spread" and side == "away" and line is not None:
        line = -line
    return market, int(period), line, side


def quote_index(rows_by_period, markets):
    """{drop_key: MerkurXtip outcome} of compare rows; `rows_by_period` is {PinnWire period number: rows},
    `markets` maps a row group to its drop market (groups not listed are skipped)."""
    out = {}
    for number, rows in rows_by_period.items():
        for r in rows:
            market = markets.get(r["group"])
            if market is None or r.get("modeled"):
                continue
            line = None if market == "moneyline" else _num(r["line"])
            for o in r["outcomes"]:
                out[(market, int(number), line, o["key"])] = {"merkur": o["merkur"], "fair": o["fair"]}
    return out


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
