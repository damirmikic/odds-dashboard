"""Basketball board: Pinnacle (PinnWire sport 3) against the MerkurXtip basketball offer.

Full-game markets (overtime included, MerkurXtip calls them "EKS INING"), the 1st half and the 1st quarter are
compared: winner, handicap, total points and team totals. Lines are matched exactly and only half-point lines
(x.5) are used: whole-number lines refund on a push, which a two-way fair price does not account for.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from statistics import NormalDist

import merkur_client as mx
import pinnwire_client as pw

SPORT_ID = 3
OFFER_PATH = "/restapi/custom/offer/sr/sport/B/mob"
FULL_RELOAD_SECONDS = 3600

# PinnWire league_id -> display info; `mx_id` is the MerkurXtip leagueId of the same competition.
COMPETITIONS = [
    {"id": 487, "key": "nba", "name": "NBA", "country": "SAD", "code": "NBA", "mx_id": 2314399},
    {"id": 382, "key": "euroleague", "name": "Evroliga", "country": "Evropa", "code": "EL", "mx_id": 2313816},
    {"id": 377, "key": "eurocup", "name": "Evrokup", "country": "Evropa", "code": "EC", "mx_id": 2313955},
    {"id": 197844, "key": "bcl", "name": "Liga šampiona (FIBA)", "country": "Evropa", "code": "BCL",
     "mx_id": 2403750},
    {"id": 367, "key": "fibaec", "name": "FIBA Europe Cup", "country": "Evropa", "code": "FEC", "mx_id": 2403767,
     "mx_extra": (2325961,)},  # some rounds are listed under the generic "International" league
    {"id": 223698, "key": "enbl", "name": "ENBL", "country": "Evropa", "code": "ENBL", "mx_id": 2360673},
    {"id": 374, "key": "vtb", "name": "VTB liga", "country": "Evropa", "code": "VTB", "mx_id": 2314880},
    {"id": 210890, "key": "aba2", "name": "ABA liga 2", "country": "Evropa", "code": "ABA2", "mx_id": 2315349},
    {"id": 383, "key": "elw", "name": "Evroliga (Ž)", "country": "Evropa", "code": "ELW", "mx_id": 2313973},
    {"id": 379, "key": "ecw", "name": "Evrokup (Ž)", "country": "Evropa", "code": "ECW", "mx_id": 2315446},
    {"id": 202722, "key": "elbl", "name": "Estonsko-letonska liga", "country": "Evropa", "code": "ELBL",
     "mx_id": 2403632},
    {"id": 474, "key": "itaa2", "name": "Serie A2", "country": "Italija", "code": "ITA2", "mx_id": 2315606},
    {"id": 237687, "key": "copaesp", "name": "Copa del Rey", "country": "Španija", "code": "ESP", "mx_id": 2389797},
    {"id": 439, "key": "grelite", "name": "Elite liga", "country": "Grčka", "code": "GRE", "mx_id": 2337796},
    {"id": 408, "key": "korisliiga", "name": "Korisliiga", "country": "Finska", "code": "FIN", "mx_id": 2313964},
    {"id": 485, "key": "lkl", "name": "LKL", "country": "Litvanija", "code": "LKL", "mx_id": 2313841},
    {"id": 208618, "key": "nkl", "name": "NKL", "country": "Litvanija", "code": "NKL", "mx_id": 2325726},
    {"id": 293, "key": "nbb", "name": "NBB", "country": "Brazil", "code": "BRA", "mx_id": 2314041},
    {"id": 486, "key": "lnbp", "name": "LNBP", "country": "Meksiko", "code": "MEX", "mx_id": 2326413},
    {"id": 501, "key": "blno", "name": "BLNO", "country": "Norveška", "code": "NOR", "mx_id": 2314043},
    {"id": 204110, "key": "iceland", "name": "Úrvalsdeild", "country": "Island", "code": "ISL", "mx_id": 2315462},
    {"id": 282, "key": "wnbl", "name": "WNBL", "country": "Australija", "code": "WNBL", "mx_id": 2328102},
    {"id": 274, "key": "lnbarg", "name": "Liga Nacional", "country": "Argentina", "code": "ARG", "mx_id": 2315603},
    {"id": 238365, "key": "rus", "name": "Superliga", "country": "Rusija", "code": "RUS", "mx_id": 2339821},
]
LEAGUE_IDS = {c["id"] for c in COMPETITIONS}
MX_COMP = {mid: c["id"] for c in COMPETITIONS for mid in (c["mx_id"], *c.get("mx_extra", ()))}

ML = ("50291", "50293")  # winner incl. overtime: home, away
# Each set is (line param, home/over code, away/under code); the param holds the home-side line.
SPREADS = [
    ("handicapOvertime", "50430", "50431"), ("handicapOvertime2", "50432", "50433"),
    ("handicapOvertime3", "50434", "50435"), ("handicapOvertime4", "50436", "50437"),
    ("handicapOvertime5", "50438", "50439"), ("handicapOvertime6", "50440", "50441"),
    ("handicapOvertime7", "50442", "50443"),
]
TOTALS = [
    ("overUnderOvertime", "50445", "50444"), ("overUnderOvertime2", "50447", "50446"),
    ("overUnderOvertime3", "50449", "50448"), ("overUnderOvertime4", "50451", "50450"),
    ("overUnderOvertime5", "50453", "50452"), ("overUnderOvertime6", "50455", "50454"),
    ("overUnderOvertime7", "50457", "50456"),
]
TEAM_TOTALS = {
    "home": [("homeOverUnderOvertime", "50467", "50466"), ("homeOverUnderOvertime2", "51541", "51540")],
    "away": [("awayOverUnderOvertime", "50479", "50478"), ("awayOverUnderOvertime2", "51543", "51542")],
}

# Lines MerkurXtip prices that Pinnacle does not are priced from a normal model fitted to Pinnacle's ladder.
# The sigmas are what Pinnacle's own ladders fit to (spread ~10, total ~14 points); they are only a fallback
# when the ladder is too short to fit one.
SIGMA = {"spreads": 10.0, "totals": 14.0, "home": 10.0, "away": 10.0}
MAX_MODEL_GAP = {"spreads": 4.0, "totals": 5.0, "home": 4.0, "away": 4.0}  # points from the nearest Pinnacle line
STALE_GAP = 2.0  # MerkurXtip main line this far from Pinnacle's: the offer lags
NORMAL = NormalDist()

# (key, label, PinnWire period number, spread of the margin/total relative to the full game).
# PinnWire numbers basketball periods 0 = game, 1 = 1st half, 3 = 1st quarter; it quotes the quarter only close to
# the start, so a quarter is compared once it appears.
PERIODS = [("ft", "Ceo meč", 0, 1.0), ("ht", "1. poluvreme", 1, 0.71), ("q1", "1. četvrtina", 3, 0.5)]
# MerkurXtip codes per period: winner (draw no bet for the half and the quarter) and sets of
# (line param, home/over code, away/under code).
MX_PERIOD = {
    "ft": {"ml": ML, "spreads": SPREADS, "totals": TOTALS, "home": TEAM_TOTALS["home"], "away": TEAM_TOTALS["away"]},
    "ht": {
        "ml": ("611", "612"),
        "spreads": [("hd2wp1", "53903", "53904")],
        "totals": [("overUnderP", "50979", "50980")],
        "home": [("homeOverUnderFirstHalf", "50983", "50982")],
        "away": [("awayOverUnderFirstHalf", "50985", "50984")],
    },
    "q1": {
        "ml": ("50025", "50026"),
        "spreads": [("handicapFirstPeriod", "602", "603")],
        "totals": [("overUnderFirstPeriod", "598", "599")],
        "home": [("homeOverUnderFirstPeriod", "50028", "50027")],
        "away": [("awayOverUnderFirstPeriod", "50030", "50029")],
    },
}

GROUPS = [
    # key in pinnacle_markets()/merkur_markets(), group label, outcome sides
    ("ml", "Pobednik", (("home", "1"), ("away", "2"))),
    ("spreads", "Hendikep", (("home", "1"), ("away", "2"))),
    ("totals", "Ukupno poena", (("over", "Više"), ("under", "Manje"))),
    ("home", "Poeni domaćin", (("over", "Više"), ("under", "Manje"))),
    ("away", "Poeni gost", (("over", "Više"), ("under", "Manje"))),
]


def utc_now():
    return datetime.now(timezone.utc)


def utc_stamp():
    return utc_now().isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_time(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def event_ts(event):
    starts = parse_time(event.get("starts") or event.get("start_ts") or "")
    return int(starts.timestamp() * 1000) if starts else 0


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


# ------------------------------------------------------------------------- decoding

def line_limits(lines, key):
    """{line: Pinnacle limit (max bet)} of a spread/total ladder, over the same lines as pinnacle_markets()."""
    out = {}
    for line in (lines or {}).values() if isinstance(lines, dict) else ():
        if isinstance(line, dict) and pw.allowed_line(pw._num(line.get(key)), "totals"):
            out[pw._num(line[key])] = line.get("max")
    return out


def pinnacle_limits(event, number=0):
    """Pinnacle limits of one period keyed like pinnacle_markets(); the moneyline carries none."""
    markets = pw.period(event, number)
    team = markets.get("team_totals") or {}
    return {
        "spreads": line_limits(markets.get("spreads"), "hdp"),
        "totals": line_limits(markets.get("totals"), "points"),
        "home": line_limits(team.get("home"), "points"),
        "away": line_limits(team.get("away"), "points"),
    }


def pinnacle_markets(event, number=0):
    """Pinnacle prices of one period keyed like merkur_markets(): ml {side: odds}, lines {line: {side: odds}}."""
    markets = pw.period(event, number)

    def by_line(lines, key, sides):
        out = {}
        for line in (lines or {}).values() if isinstance(lines, dict) else ():
            if isinstance(line, dict) and pw.allowed_line(pw._num(line.get(key)), "totals"):
                prices = pw.priced(line, sides)
                if len(prices) == len(sides):
                    out[pw._num(line[key])] = prices
        return out

    ml = pw.priced(markets.get("money_line") or {}, ("home", "away"))
    team = markets.get("team_totals") or {}
    main_team = markets.get("team_total") or {}
    out = {
        "ml": ml if len(ml) == 2 else None,
        "spreads": by_line(markets.get("spreads"), "hdp", ("home", "away")),
        "totals": by_line(markets.get("totals"), "points", ("over", "under")),
    }
    for side in ("home", "away"):
        lines = by_line(team.get(side), "points", ("over", "under"))
        # the main team total is sometimes quoted on its own, outside the ladder
        single = by_line({side: main_team.get(side)}, "points", ("over", "under"))
        lines.update({k: v for k, v in single.items() if k not in lines})
        out[side] = lines
    return out


def merkur_markets(row, period="ft"):
    """One MerkurXtip basketball offer row -> the same shape as pinnacle_markets(), for one period."""
    raw, params = row.get("odds") or {}, row.get("params") or {}
    codes = MX_PERIOD[period]

    def lines(sets, sides):
        out = {}
        for key, first, second in sets:
            line = mx._param_line(params, key)
            prices = mx._pick(raw, dict(zip(sides, (first, second))))
            if pw.allowed_line(line, "totals") and prices and line not in out:
                out[line] = prices
        return out

    return {
        "ml": mx._pick(raw, dict(zip(("home", "away"), codes["ml"]))),
        "spreads": lines(codes["spreads"], ("home", "away")),
        "totals": lines(codes["totals"], ("over", "under")),
        "home": lines(codes["home"], ("over", "under")),
        "away": lines(codes["away"], ("over", "under")),
        # MerkurXtip's own main lines: the first set of each market (params without a number suffix)
        "main": {"spreads": mx._param_line(params, codes["spreads"][0][0]),
                 "totals": mx._param_line(params, codes["totals"][0][0])},
    }


# ------------------------------------------------------------------------- comparison

def compare_row(group, line, labels, merkur, pinnacle, max_bet=None):
    """Merkur odds against Pinnacle fair odds; ev = Merkur / fair - 1."""
    fair, pin_margin = pw.fair_odds(pinnacle)
    outcomes = [{"key": key, "label": label, "merkur": merkur[key], "pinnacle": pinnacle[key],
                 "fair": round(fair[key], 3), "ev": round(merkur[key] / fair[key] - 1, 4)}
                for key, label in labels if key in merkur]
    return {
        "group": group,
        "line": line,
        "outcomes": outcomes,
        "merkurMargin": round((sum(1 / o for o in merkur.values()) - 1) * 100, 2),
        "pinnacleMargin": pin_margin,
        "maxBet": max_bet,
        "maxEv": max(o["ev"] for o in outcomes),
    }


def ladder_points(lines, key):
    """Pinnacle's ladder as (threshold t, probit of P(first side wins), P, overround) with P = P(X > t).

    Totals and team totals: X is the points, t the line, first side "over". Handicap: X is the home margin,
    t = -line, first side "home". A normal X gives probit(P) = (mu - t) / sigma, linear in t.
    """
    first = "home" if key == "spreads" else "over"
    points = []
    for line, prices in lines.items():
        p = pw.devig(prices)[first]
        if 0.03 < p < 0.97:
            points.append((-line if key == "spreads" else line, NORMAL.inv_cdf(p), p,
                           sum(1 / o for o in prices.values()) - 1))
    return points


def model_probability(lines, key, line, scale=1.0):
    """(P(first side), overround) at a line Pinnacle does not quote, or None when it is too far from the ladder."""
    points = ladder_points(lines, key)
    t = -line if key == "spreads" else line
    if not points:
        return None
    near = sorted(points, key=lambda pt: abs(pt[0] - t))
    t0, z0, _, margin = near[0]
    if abs(t0 - t) > MAX_MODEL_GAP[key] * scale:
        return None
    sigma = SIGMA[key] * scale
    fit = near[:4]
    if len(fit) >= 3:  # least squares of probit against t over the lines nearest to the target
        mean_t = sum(pt[0] for pt in fit) / len(fit)
        mean_z = sum(pt[1] for pt in fit) / len(fit)
        spread = sum((pt[0] - mean_t) ** 2 for pt in fit)
        slope = sum((pt[0] - mean_t) * (pt[1] - mean_z) for pt in fit) / spread if spread else 0
        if slope < 0 and 0.7 * sigma <= -1 / slope <= 1.5 * sigma:
            sigma = -1 / slope
    return NORMAL.cdf(z0 + (t0 - t) / sigma), margin


def model_row(group, line, labels, merkur, p_first, overround):
    """Compare row for a line priced from the model: the Pinnacle price is the fair price plus the ladder margin."""
    probs = {labels[0][0]: p_first, labels[1][0]: 1 - p_first}
    outcomes = []
    for key, label in labels:
        fair = 1 / probs[key]
        outcomes.append({"key": key, "label": label, "merkur": merkur[key],
                         "pinnacle": round(1 / (probs[key] * (1 + overround)), 3), "fair": round(fair, 3),
                         "ev": round(merkur[key] / fair - 1, 4)})
    return {
        "group": group, "line": line, "outcomes": outcomes, "modeled": True,
        "merkurMargin": round((sum(1 / o for o in merkur.values()) - 1) * 100, 2),
        "pinnacleMargin": round(overround * 100, 2),
        "maxEv": max(o["ev"] for o in outcomes),
    }


def compare(pin, merkur, period="ft", scale=1.0, limits=None):
    """Every market both books price, as compare rows; Merkur lines outside Pinnacle's ladder are modelled."""
    rows = []
    for key, group, labels in GROUPS:
        if key == "ml":
            if pin["ml"] and merkur["ml"]:
                rows.append(compare_row(group, None, labels, merkur["ml"], pin["ml"]))
            continue
        for line in sorted(merkur[key]):
            if line in pin[key]:
                rows.append(compare_row(group, line, labels, merkur[key][line], pin[key][line],
                                        (limits or {}).get(key, {}).get(line)))
                continue
            model = model_probability(pin[key], key, line, scale)
            if model:
                rows.append(model_row(group, line, labels, merkur[key][line], *model))
    for r in rows:
        r["period"] = period
    return rows


def main_line(lines, sides):
    """The Pinnacle line whose two prices are closest to even."""
    if not lines:
        return None
    return min(lines, key=lambda line: abs(lines[line][sides[0]] - lines[line][sides[1]]))


def stale_gaps(pin, merkur):
    """{group: MerkurXtip main line - Pinnacle main line} where the gap is at least STALE_GAP.

    A lower MerkurXtip total favours the over, a higher one the under; a higher home handicap favours the home side.
    """
    out = {}
    for key, group, sides in (("spreads", "Hendikep", ("home", "away")), ("totals", "Ukupno poena", ("over", "under"))):
        pin_main, mx_main = main_line(pin[key], sides), merkur["main"][key]
        if pin_main is not None and mx_main is not None and abs(mx_main - pin_main) >= STALE_GAP:
            out[group] = round(mx_main - pin_main, 2)
    return out


def favours(group, gap, key):
    """Does the outcome `key` benefit from a MerkurXtip main line `gap` points away from Pinnacle's?"""
    if group == "Ukupno poena":
        return key == ("over" if gap < 0 else "under")
    return key == ("home" if gap > 0 else "away")


def board_cell(group_rows, pin_lines, sides):
    """Board cell for a two-way line market: the shared line closest to Pinnacle's main line.

    Without a shared line the Pinnacle main line is shown alone.
    """
    target = main_line(pin_lines, sides)
    if target is None:
        return None
    if group_rows:
        row = min(group_rows, key=lambda r: (abs(r["line"] - target),
                                             abs(r["outcomes"][0]["pinnacle"] - r["outcomes"][1]["pinnacle"])))
        out = {o["key"]: o for o in row["outcomes"]}
        return {"line": row["line"], "fair": {k: o["fair"] for k, o in out.items()},
                "pinnacle": {k: o["pinnacle"] for k, o in out.items()},
                "merkur": {k: o["merkur"] for k, o in out.items()},
                "ev": {k: o["ev"] for k, o in out.items()}}
    prices = pin_lines[target]
    fair, _ = pw.fair_odds(prices)
    return {"line": target, "fair": {k: round(v, 3) for k, v in fair.items()}, "pinnacle": prices,
            "merkur": None, "ev": None}


def value_items(match_id, rows, stale=None):
    """Every outcome where the MerkurXtip price beats the Pinnacle price, one item each."""
    labels = {key: label for key, label, _, _ in PERIODS}
    items = []
    for r in rows:
        for o in r["outcomes"]:
            if o["merkur"] <= o["pinnacle"]:
                continue
            period = r.get("period", "ft")
            items.append({
                "matchId": match_id, "period": period, "periodLabel": labels[period], "group": r["group"], "line": r["line"], "key": o["key"],
                "label": o["label"], "merkur": o["merkur"], "pinnacle": o["pinnacle"], "fair": o["fair"],
                "ev": o["ev"], "overPinnacle": round(o["merkur"] / o["pinnacle"] - 1, 4),
                "merkurMargin": r["merkurMargin"], "pinnacleMargin": r["pinnacleMargin"],
                "modeled": bool(r.get("modeled")),
                # MerkurXtip main line vs Pinnacle's, when this outcome is the side that gap favours
                "stale": gap if (period == "ft" and (gap := (stale or {}).get(r["group"]))
                                 and favours(r["group"], gap, o["key"])) else None,
            })
    return pw.best_per_line_market(items)


def best_edge(rows):
    best = None
    prefixes = {"ft": "", "ht": "1.pol ", "q1": "1.čet "}
    for r in rows:
        for o in r["outcomes"]:
            if best is None or o["ev"] > best["ev"]:
                market = r["group"] + ("" if r["line"] is None else f" {r['line']:g}")
                best = {"ev": o["ev"], "label": f"{prefixes[r.get('period', 'ft')]}{market} {o['label']}"}
    return best


def pair_inputs(events, offer):
    pin = [{"id": str(e["event_id"]), "comp": e["league_id"], "home": e.get("home", ""),
            "away": e.get("away", ""), "ts": event_ts(e)} for e in events]
    mer = [{"id": r["id"], "comp": MX_COMP[r["leagueId"]], "home": r.get("home", ""), "away": r.get("away", ""),
            "ts": r.get("kickOffTime") or 0, "row": r}
           for r in offer if r.get("leagueId") in MX_COMP and mx.is_prematch(r)]
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


def shape_match(event, hit):
    """Board entry of one Pinnacle event, plus its value items from the paired MerkurXtip row."""
    pin = pinnacle_markets(event)
    ml_fair, margin = pw.fair_odds(pin["ml"]) if pin["ml"] else ({}, None)
    rows, merkur, stale, periods = [], None, {}, {}
    if hit:
        row, score = hit
        decoded = merkur_markets(row)
        rows = compare(pin, decoded, limits=pinnacle_limits(event))
        stale = stale_gaps(pin, decoded)
        for key, _, number, scale in PERIODS[1:]:
            if pw.period(event, number):
                found = compare(pinnacle_markets(event, number), merkur_markets(row, key), key, scale,
                                pinnacle_limits(event, number))
                if found:
                    periods[key] = found
        ml_row = next((r for r in rows if r["group"] == "Pobednik"), None)
        merkur = {
            "id": row.get("id"), "home": row.get("home", ""), "away": row.get("away", ""), "score": score,
            "kickoffDiff": round(((row.get("kickOffTime") or 0) - event_ts(event)) / 60000),
            "ml": {o["key"]: {"odds": o["merkur"], "ev": o["ev"]} for o in ml_row["outcomes"]} if ml_row else None,
            "best": best_edge(rows + [r for found in periods.values() for r in found]),
            "compared": len(rows) + sum(len(found) for found in periods.values()),
            "stale": [{"group": g, "gap": gap} for g, gap in stale.items()],
        }
    match = {
        "id": event.get("event_id"),
        "leagueId": event.get("league_id"),
        "leagueName": event.get("league_name") or "",
        "home": event.get("home", ""),
        "away": event.get("away", ""),
        "starts": event.get("starts") or event.get("start_ts") or "",
        "ml": ({s: {"odds": pin["ml"][s], "fair": round(ml_fair[s], 3)} for s in ("home", "away")}
               if pin["ml"] else None),
        "margin": margin,
        "spread": board_cell([r for r in rows if r["group"] == "Hendikep" and not r.get("modeled")], pin["spreads"], ("home", "away")),
        "total": board_cell([r for r in rows if r["group"] == "Ukupno poena" and not r.get("modeled")], pin["totals"], ("over", "under")),
        "merkur": merkur,
        "rows": rows,
        "periods": periods,
    }
    every_row = rows + [r for found in periods.values() for r in found]
    return match, value_items(event.get("event_id"), every_row, stale)


class BasketballState:
    """PinnWire snapshot + MerkurXtip offer for one sport. TennisState overrides the hook methods below."""

    sport_id = SPORT_ID
    offer_path = OFFER_PATH
    alt_units = False  # ask PinnWire for the side-market events too

    def __init__(self, history, key_fn):
        self.history = history  # shared with the football state: only its request counter is used
        self.key_fn = key_fn
        self.lock = threading.Lock()
        self.fetch_lock = threading.Lock()
        self.merkur = mx.OfferCache(mx.MerkurAPI(offer_path=self.offer_path))
        self.merkur_lock = threading.Lock()
        self.pairs = {}  # pinnacle event id -> (merkur offer row, name score)
        self.api = None
        self.api_key = None
        self.events = None
        self.last = None
        self.full_at = 0.0
        self.fetched_at = ""
        self.mode = ""
        self.changed = 0

    # ----- hooks
    def incoming(self, data):
        return [e for e in data.get("events") or [] if e.get("event_id") and is_tracked(e)]

    def merge(self, old, new):
        return merge_event(old, new)

    def complete(self, event):
        return True

    def shape(self, event, hit):
        return shape_match(event, hit)

    def pair(self, events, offer):
        return pair_events(events, offer)

    def hints(self, events, offer):
        return unpaired_hints(events, offer)

    def offered(self, offer):
        return sum(1 for r in offer if r.get("leagueId") in MX_COMP and mx.is_prematch(r))

    def competitions(self, matches):
        counts = {}
        for m in matches:
            counts[m["leagueId"]] = counts.get(m["leagueId"], 0) + 1
        return [{**c, "count": counts.get(c["id"], 0)} for c in COMPETITIONS]

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
            self.fetched_at = utc_stamp()
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

    def match(self, event_id):
        """One match compared against fresh single-match MerkurXtip odds (no PinnWire request)."""
        if self.events is None:
            self.refresh(if_empty=True)
        with self.lock:
            event = (self.events or {}).get(event_id)
        if event is None or not self.complete(event):
            raise LookupError("Meč nije u ponudi (možda je počeo ili uklonjen).")
        hit = self.pairs.get(event_id)
        error, fetched = "", self.merkur.stamp
        if hit is not None:
            row, score = hit
            try:
                row, fetched = {**hit[0], **self.merkur.api.match(row["id"])}, utc_stamp()
            except (RuntimeError, LookupError) as exc:
                error = str(exc)
            hit = (row, score)
        match, _ = self.shape(event, hit)
        return {"match": match, "fetchedAt": fetched, "error": error, "callsToday": self.history.calls_today()}

    def board(self, refresh=False, full=False):
        if refresh or full or self.events is None:
            self.refresh(full=full, if_empty=not (refresh or full))
        with self.merkur_lock:
            offer = self.merkur.get(refresh=refresh or full, stamp_fn=utc_stamp)
        with self.lock:
            now = utc_now()
            events = [e for e in (self.events or {}).values() if is_upcoming(e, now) and self.complete(e)]
        pairs = self.pair(events, offer)
        self.pairs = pairs
        hints = self.hints(events, offer)
        matches, values = [], []
        for event in events:
            match, items = self.shape(event, pairs.get(str(event["event_id"])))
            match["hint"] = hints.get(str(event["event_id"]))
            # a match without any Pinnacle price is not worth a row
            if match["ml"] or match["spread"] or match["total"]:
                matches.append(match)
                values.extend(items)
        matches.sort(key=lambda m: (m["starts"], m["home"]))
        return {
            "competitions": self.competitions(matches),
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
                "offered": self.offered(offer),
            },
        }
