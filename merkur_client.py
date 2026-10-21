"""MerkurXtip prematch offer: fetching, decoding odds codes and pairing with PinnWire events.

The offer list keys odds by tip-type code (definitions: /restapi/offer/sr/ttg_lang, `betPickMap`
entries "<code>_S"). Goal totals are sold as ranges: "0-2" is under 2.5 and "3+" is over 2.5.

Handicaps (home side line L, away side priced at -L) come from three kinds of source:
- direct two-way handicaps: AH 0 as "X vraća ulog" (264/265) and `hd2w` / `hd2wp1` (line in `params`);
- 1X2 and double chance, which are half-goal handicaps: AH -0.5 is "1" against "X2", AH +0.5 is "1X"
  against "2" (same codes with the 1st half 1X2 and double chance for the 1st half);
- European handicap with integer h (`hd2`, `handicap2`, `handicap3`, 1st half `hdp`): H1 (home + h beats away)
  is the home side of AH h - 0.5 and H2 (away beats home + h) is the away side of AH h + 0.5.
  For example h = -1: H1 is home by 2+ (AH -1.5 home) and H2 is "X2" (AH -0.5 away, i.e. AH +0.5 for away).
Direct prices win over derived ones. A line whose prices are not both direct is flagged derived: its two
sides come from different markets, so no margin is computed for it.
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
HT_TOTALS = {0.5: ("207", "267"), 1.5: ("208", "211"), 2.5: ("209", "472")}
# team goals: over 0.5 = "D 1+", under 0.5 = "D 0"; over 1.5 = "D 2+", under 1.5 = "D 0-1" ...
TEAM_TOTALS = {
    "home": {0.5: ("238", "239"), 1.5: ("248", "247"), 2.5: ("276", "551"), 3.5: ("555", "553")},
    "away": {0.5: ("240", "241"), 1.5: ("250", "249"), 2.5: ("277", "552"), 3.5: ("556", "554")},
}
# 1st half team goals: "D I 1+" / "D I 0", "D I 2+" / "D I 0-1" and the same for the guest
HT_TEAM_TOTALS = {
    "home": {0.5: ("307", "337"), 1.5: ("274", "817")},
    "away": {0.5: ("308", "338"), 1.5: ("275", "821")},
}
# params key -> (over code, under code) for markets whose line is given in `params`
PARAM_TOTALS = {"overUnder": ("227", "228")}
PARAM_HT_TOTALS = {"overUnderP": ("229", "230")}
PARAM_TEAM_TOTALS = {"home": {"homeOverUnder": ("356", "355")}, "away": {"awayOverUnder": ("358", "357")}}
# two-way handicap, line from the home side: params key -> (home code, away code)
SPREADS = {"hd2w": ("53877", "53878")}
# fixed-line handicaps: "X vraća ulog" (W1/W2, draw no bet) is the level handicap AH 0
FIXED_SPREADS = {0.0: ("264", "265")}
HT_SPREADS = {"hd2wp1": ("53903", "53904")}
# half-goal handicaps from 1X2 / double chance: line -> {side: code}; both prices must exist
DERIVED_SPREADS = {
    -0.5: {"home": "1", "away": "9"},     # "1"  against "X2"
    0.5: {"home": "7", "away": "3"},      # "1X" against "2"
}
HT_DERIVED_SPREADS = {
    -0.5: {"home": "4", "away": "399"},   # 1st half "1"  against "X2"
    0.5: {"home": "397", "away": "6"},    # 1st half "1X" against "2"
}
# European handicap: params key -> (H1 code, H2 code); the param holds the integer handicap h
EURO_HANDICAPS = {"hd2": ("201", "203"), "handicap2": ("421", "423"), "handicap3": ("424", "426")}
HT_EURO_HANDICAPS = {"hdp": ("224", "226")}


class MerkurAPI:
    def __init__(self, timeout=30, offer_path=OFFER_PATH):
        self.offer_path = offer_path
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
        data = self._get(self.offer_path, annex=0)
        return data.get("esMatches") or [] if isinstance(data, dict) else []

    def match(self, match_id):
        data = self._get(MATCH_PATH.format(id=match_id), annex=0, locale="sr")
        if not isinstance(data, dict) or not data.get("odds"):
            raise LookupError("MerkurXtip nema kvote za ovaj meč.")
        return data


# ------------------------------------------------------------------------- decoding

def is_prematch(row, now_ms=None):
    """Offer rows still before kickoff. MerkurXtip flags some matches `live` hours early (live betting opens
    before the start) while their prices are still prematch ones, so only started matches are excluded."""
    now_ms = time.time() * 1000 if now_ms is None else now_ms
    return not row.get("live") or (row.get("kickOffTime") or 0) > now_ms


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


def _spreads(raw, params, by_param, fixed=None, derived=None, euro=None):
    """Handicap prices by home-side line -> ({line: {side: odds}}, {derived lines}); see the module docstring."""
    prices = {}  # line -> {side: (odds, direct)}

    def put(line, side, odds, direct):
        if odds and side not in prices.setdefault(line, {}):
            prices[line][side] = (odds, direct)

    def put_pair(line, pair, direct):
        for side, odds in (pair or {}).items():
            put(line, side, odds, direct)

    for line, (home, away) in (fixed or {}).items():
        put_pair(line, _pick(raw, {"home": home, "away": away}), True)
    for key, (home, away) in by_param.items():
        line = _param_line(params, key)
        if line is not None:
            put_pair(line, _pick(raw, {"home": home, "away": away}), True)
    for line, codes in (derived or {}).items():
        put_pair(line, _pick(raw, codes), False)
    for key, (h1, h2) in (euro or {}).items():
        h = _param_line(params, key)
        if h is None or h == 0 or h != round(h):
            continue
        put(h - 0.5, "home", _odds(raw, h1), False)
        put(h + 0.5, "away", _odds(raw, h2), False)

    lines = {line: {side: odds for side, (odds, _) in sides.items()} for line, sides in prices.items() if sides}
    derived_lines = {line for line, sides in prices.items() if sides and not all(d for _, d in sides.values())}
    return lines, derived_lines


def markets(match):
    """Decode one offer row into {period: {ml, totals, spreads, derived, teamTotals}}.

    0 = match, 1 = 1st half. `spreads` is {line: {side: odds}} and may hold one side only;
    `derived` is the set of spread lines that are not a direct two-way price.
    """
    raw = match.get("odds") or {}
    params = match.get("params") or {}
    spreads, derived = _spreads(raw, params, SPREADS, FIXED_SPREADS, DERIVED_SPREADS, EURO_HANDICAPS)
    ht_spreads, ht_derived = _spreads(raw, params, HT_SPREADS, None, HT_DERIVED_SPREADS, HT_EURO_HANDICAPS)
    return {
        0: {
            "ml": _pick(raw, ML),
            "totals": _ou(raw, params, TOTALS, PARAM_TOTALS),
            "spreads": spreads,
            "derived": derived,
            "teamTotals": {
                side: _ou(raw, params, TEAM_TOTALS[side], PARAM_TEAM_TOTALS[side]) for side in ("home", "away")
            },
        },
        1: {
            "ml": _pick(raw, HT_ML),
            "totals": _ou(raw, params, HT_TOTALS, PARAM_HT_TOTALS),
            "spreads": ht_spreads,
            "derived": ht_derived,
            "teamTotals": {side: _ou(raw, params, HT_TEAM_TOTALS[side], {}) for side in ("home", "away")},
        },
    }


# ------------------------------------------------------------------------- pairing

_STOP = {"w", "fc", "ac", "cf", "sc", "cp", "sv", "fk", "afc", "sk", "nk", "bk", "club", "the", "cd", "ud", "sd", "as"}
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


def closest_unpaired(pinnacle, merkur, pairs, window_minutes=180):
    """For each unpaired Pinnacle event the best still-unused MerkurXtip row of the same competition and kickoff window.

    Rows paired below `min_score` still show up here, which points at team names that need an alias.
    pairs: the result of pair(). Returns {pinnacle id: (merkur row, score)}.
    """
    used = {m["id"] for m, _ in pairs.values()}
    out = {}
    for p in pinnacle:
        if p["id"] in pairs:
            continue
        best = None
        for m in merkur:
            diff = abs(m["ts"] - p["ts"]) / 60000
            if m["comp"] != p["comp"] or m["id"] in used or diff > window_minutes:
                continue
            score = (name_score(p["home"], m["home"]) + name_score(p["away"], m["away"])) / 2
            if score > 0 and (best is None or (score, -diff) > best[0]):
                best = ((score, -diff), m)
        if best:
            out[p["id"]] = (best[1], round(best[0][0], 2))
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
