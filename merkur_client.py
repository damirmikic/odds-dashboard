"""MerkurXtip prematch offer: fetching, decoding odds codes and pairing with PinnWire events.

The offer list keys odds by tip-type code (definitions: /restapi/offer/sr/ttg_lang, `betPickMap`
entries "<code>_S"). Goal totals are sold as ranges: "0-2" is under 2.5 and "3+" is over 2.5.
"""
from __future__ import annotations

import difflib
import re
import time
import unicodedata

import requests

BASE = "https://www.merkurxtip.rs"
OFFER_PATH = "/restapi/custom/offer/sr/sport/S/mob"
MATCH_PATH = "/restapi/offer/sr/match/{id}"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

ML = {"home": "1", "draw": "2", "away": "3"}
HT_ML = {"home": "4", "draw": "5", "away": "6"}
# line: (over code, under code)
TOTALS = {1.5: ("242", "21"), 2.5: ("24", "22"), 3.5: ("25", "219"), 4.5: ("27", "453"), 5.5: ("223", "266")}
HT_TOTALS = {0.5: ("207", "267"), 1.5: ("208", "211")}
TEAM_TOTALS = {
    "home": {0.5: ("238", "239"), 1.5: ("248", "247")},
    "away": {0.5: ("240", "241"), 1.5: ("250", "249")},
}
# params key -> (over code, under code) for markets whose line is given in `params`
PARAM_TOTALS = {"overUnder": ("227", "228")}
PARAM_HT_TOTALS = {"overUnderP": ("229", "230")}
PARAM_TEAM_TOTALS = {"home": {"homeOverUnder": ("356", "355")}, "away": {"awayOverUnder": ("358", "357")}}
# two-way handicap, line from the home side: params key -> (home code, away code)
SPREADS = {"hd2w": ("53877", "53878")}
HT_SPREADS = {"hd2wp1": ("53903", "53904")}


class MerkurAPI:
    def __init__(self, timeout=30):
        self.s = requests.Session()
        self.s.headers.update(HEADERS)
        self.timeout = timeout

    def _get(self, path, **params):
        try:
            r = self.s.get(f"{BASE}{path}", params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise RuntimeError(f"MerkurXtip nije dostupan: {exc}") from exc
        if r.status_code == 404:
            raise LookupError("MerkurXtip nema ovaj meč.")
        if r.status_code != 200:
            raise RuntimeError(f"MerkurXtip {path} -> HTTP {r.status_code}")
        try:
            return r.json()
        except ValueError as exc:
            raise RuntimeError("MerkurXtip je vratio neispravan JSON.") from exc

    def offer(self):
        data = self._get(OFFER_PATH, annex=0)
        return data.get("esMatches") or [] if isinstance(data, dict) else []

    def match(self, match_id):
        data = self._get(MATCH_PATH.format(id=match_id), annex=0, locale="sr")
        if not isinstance(data, dict) or not data.get("odds"):
            raise LookupError("MerkurXtip nema kvote za ovaj meč.")
        return data


# ------------------------------------------------------------------------- decoding

def _odds(raw, code):
    try:
        value = float(raw.get(code))
    except (TypeError, ValueError):
        return None
    return value if value > 1.0 else None


def _pick(raw, codes):
    """{side: code} -> {side: odds}, only when every side is priced."""
    out = {side: _odds(raw, code) for side, code in codes.items()}
    return out if all(out.values()) else None


def _param_line(params, key):
    try:
        return float(params.get(key))
    except (TypeError, ValueError):
        return None


def _ou(raw, params, ranges, by_param):
    lines = {}
    for line, (over, under) in ranges.items():
        prices = _pick(raw, {"over": over, "under": under})
        if prices:
            lines[line] = prices
    for key, (over, under) in by_param.items():
        line = _param_line(params, key)
        prices = _pick(raw, {"over": over, "under": under})
        if line is not None and prices and line not in lines:
            lines[line] = prices
    return lines


def _spreads(raw, params, by_param):
    lines = {}
    for key, (home, away) in by_param.items():
        line = _param_line(params, key)
        prices = _pick(raw, {"home": home, "away": away})
        if line is not None and prices:
            lines[line] = prices
    return lines


def markets(match):
    """Decode one offer row into {period: {ml, totals, spreads, teamTotals}}; 0 = match, 1 = 1st half."""
    raw = match.get("odds") or {}
    params = match.get("params") or {}
    return {
        0: {
            "ml": _pick(raw, ML),
            "totals": _ou(raw, params, TOTALS, PARAM_TOTALS),
            "spreads": _spreads(raw, params, SPREADS),
            "teamTotals": {
                side: _ou(raw, params, TEAM_TOTALS[side], PARAM_TEAM_TOTALS[side]) for side in ("home", "away")
            },
        },
        1: {
            "ml": _pick(raw, HT_ML),
            "totals": _ou(raw, params, HT_TOTALS, PARAM_HT_TOTALS),
            "spreads": _spreads(raw, params, HT_SPREADS),
            "teamTotals": {},
        },
    }


# ------------------------------------------------------------------------- pairing

_STOP = {"fc", "ac", "cf", "sc", "cp", "sv", "fk", "afc", "sk", "nk", "bk", "club", "the", "cd", "ud", "sd", "as"}
# normalised name -> canonical form, for names the token rules cannot pair
ALIASES = {
    "agf": "aarhus",
    "olympiakos": "olympiacos",
}


def norm_tokens(name):
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    text = ALIASES.get(text, text)
    return [t for t in text.split() if t not in _STOP] or text.split()


def _token_match(a, b):
    if a == b or a.startswith(b) or b.startswith(a):
        return True
    if min(len(a), len(b)) >= 4 and (a in b or b in a):
        return True
    return min(len(a), len(b)) >= 5 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.8


def name_score(a, b):
    """0..1: share of the shorter name's tokens found in the other (prefixes, initials, typos)."""
    ta, tb = norm_tokens(a), norm_tokens(b)
    if not ta or not tb:
        return 0.0
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if len(short) == 1 and len(long_) > 1 and short[0] == "".join(t[0] for t in long_):
        return 1.0  # PSG <-> Paris Saint Germain
    return sum(1 for t in short if any(_token_match(t, u) for u in long_)) / len(short)


def pair(pinnacle, merkur, window_minutes=180, min_score=0.5):
    """Pair events one-to-one.

    pinnacle: [{id, comp, home, away, ts}], merkur: [{id, comp, home, away, ts}] (ts in ms).
    Only the same competition with kickoff within the window is considered; the best name score wins.
    Returns {pinnacle id: (merkur row, score)}.
    """
    by_comp = {}
    for m in merkur:
        by_comp.setdefault(m["comp"], []).append(m)
    scored = []
    for p in pinnacle:
        for m in by_comp.get(p["comp"], ()):
            diff = abs(m["ts"] - p["ts"]) / 60000
            if diff > window_minutes:
                continue
            score = (name_score(p["home"], m["home"]) + name_score(p["away"], m["away"])) / 2
            if score >= min_score:
                scored.append((score, -diff, p["id"], m["id"], m))
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    out, used = {}, set()
    for score, _, pid, mid, m in scored:
        if pid in out or mid in used:
            continue
        out[pid] = (m, round(score, 2))
        used.add(mid)
    return out


class OfferCache:
    """Offer list kept for `ttl` seconds; one fetch at a time."""

    def __init__(self, api=None, ttl=60):
        self.api = api or MerkurAPI()
        self.ttl = ttl
        self.rows = None
        self.at = 0.0
        self.stamp = ""
        self.error = ""

    def get(self, refresh=False, stamp_fn=None):
        fresh = self.rows is not None and time.monotonic() - self.at < (30 if refresh else self.ttl)
        if fresh:
            return self.rows
        try:
            rows = self.api.offer()
        except (RuntimeError, LookupError) as exc:
            self.error = str(exc)
            return self.rows or []
        self.rows = rows
        self.at = time.monotonic()
        self.stamp = stamp_fn() if stamp_fn else ""
        self.error = ""
        return rows
