"""Basketball board: Pinnacle (PinnWire sport 3) against the MerkurXtip basketball offer.

Full-game markets (overtime included, MerkurXtip calls them "EKS INING"), the 1st half and the 1st quarter are
compared: winner, handicap, total points and team totals. Lines are matched exactly and only half-point lines
(x.5) are used: whole-number lines refund on a push, which a two-way fair price does not account for.
"""
from __future__ import annotations

import functools
from statistics import NormalDist

import common
import merkur_client as mx
import pinnwire_client as pw
from common import event_ts, merge_event  # noqa: F401 (tennis and hockey use them through this module)

SPORT_ID = 3
OFFER_PATH = "/restapi/custom/offer/sr/sport/B/mob"

# PinnWire league_id -> display info; `mx_id` is the MerkurXtip leagueId of the same competition.
COMPETITIONS = [
    {"id": 487, "key": "nba", "name": "NBA", "country": "SAD", "code": "NBA", "mx_id": 2314399},
    {"id": 382, "key": "euroleague", "name": "Evroliga", "country": "Evropa", "code": "EL", "mx_id": 2313816},
    {"id": 377, "key": "eurocup", "name": "Evrokup", "country": "Evropa", "code": "EC", "mx_id": 2313955},
    {"id": 197844, "key": "bcl", "name": "Liga šampiona (FIBA)", "country": "Evropa", "code": "BCL",
     "mx_id": 2403750},
    {"id": 367, "key": "fibaec", "name": "FIBA Europe Cup", "country": "Evropa", "code": "FIBA EC", "mx_id": 2403767,
     "mx_extra": (2325961, 2404806)},  # some rounds are listed under the generic "International" league
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
    {"id": 493, "key": "ncaa", "name": "NCAA", "country": "SAD", "code": "NCAA", "mx_id": 2313823},
    {"id": 268, "key": "aba", "name": "ABA liga", "country": "Evropa", "code": "ABA", "mx_id": 2314107},
    {"id": 472, "key": "itaa", "name": "Lega A", "country": "Italija", "code": "ITA", "mx_id": 2314021},
    {"id": 197913, "key": "tursl", "name": "Super liga", "country": "Turska", "code": "TUR", "mx_id": 2313839},
    {"id": 462, "key": "isrpl", "name": "Premier liga", "country": "Izrael", "code": "ISR", "mx_id": 2314182},
    {"id": 415, "key": "fraprob", "name": "Pro B", "country": "Francuska", "code": "FRA2", "mx_id": 2387819},
    {"id": 417, "key": "fracup", "name": "Kup Francuske", "country": "Francuska", "code": "FRAC", "mx_id": 2326061},
    {"id": 565, "key": "swebl", "name": "Basketligan", "country": "Švedska", "code": "SWE", "mx_id": 2313843},
    {"id": 297, "key": "bulnbl", "name": "NBL", "country": "Bugarska", "code": "BUL", "mx_id": 2314214},
    {"id": 213144, "key": "icelandw", "name": "Úrvalsdeild (Ž)", "country": "Island", "code": "ISLW",
     "mx_id": 2394983},
    {"id": 303, "key": "cba", "name": "CBA", "country": "Kina", "code": "CBA", "mx_id": 2313954},
    {"id": 482, "key": "kbl", "name": "KBL", "country": "Južna Koreja", "code": "KBL", "mx_id": 2380450},
    {"id": 481, "key": "wkbl", "name": "WKBL (Ž)", "country": "Južna Koreja", "code": "WKBL", "mx_id": 2313974},
    {"id": 211487, "key": "qbl", "name": "QBL", "country": "Katar", "code": "QAT", "mx_id": 2377351},
    {"id": 207009, "key": "slv", "name": "Liga Mayor", "country": "El Salvador", "code": "SLV", "mx_id": 2330227},
]
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


# ------------------------------------------------------------------------- decoding

def pinnacle_limits(event, number=0):
    """Pinnacle limits of one period keyed like pinnacle_markets(); the moneyline carries none."""
    markets = pw.period(event, number)
    team = markets.get("team_totals") or {}
    return {
        "spreads": pw.ladder_limits(markets.get("spreads"), "hdp"),
        "totals": pw.ladder_limits(markets.get("totals"), "points"),
        "home": pw.ladder_limits(team.get("home"), "points"),
        "away": pw.ladder_limits(team.get("away"), "points"),
    }


def pinnacle_markets(event, number=0):
    """Pinnacle prices of one period keyed like merkur_markets(): ml {side: odds}, lines {line: {side: odds}}."""
    markets = pw.period(event, number)
    ml = pw.priced(markets.get("money_line") or {}, ("home", "away"))
    return {
        "ml": ml if len(ml) == 2 else None,
        "spreads": pw.ladder(markets.get("spreads"), "hdp", ("home", "away")),
        "totals": pw.ladder(markets.get("totals"), "points", ("over", "under")),
        **common.team_ladders(markets),
    }


SWAPPED = "pinSwapped"  # MerkurXtip row whose teams are in the reverse of Pinnacle's order
_FLIP = {"home": "away", "away": "home"}


def _flip_sides(prices):
    return {_FLIP.get(side, side): odds for side, odds in prices.items()}


def swap_sides(markets):
    """merkur_markets() of a SWAPPED row turned to Pinnacle's order: home and away prices exchange, a handicap line
    changes sign, the team totals trade places; totals and the draw stay."""
    out = dict(markets)
    for key, value in markets.items():
        if key == "ml" and value:
            out[key] = _flip_sides(value)
        elif key in ("spreads", "setspreads"):
            out[key] = {-line: _flip_sides(prices) for line, prices in value.items()}
    if "home" in markets or "away" in markets:
        out["home"], out["away"] = markets.get("away"), markets.get("home")
    if markets.get("main"):
        line = markets["main"].get("spreads")
        out["main"] = {**markets["main"], "spreads": None if line is None else -line}
    return out


def reversible(fn):
    """Decorate a merkur_markets(row, ...): a row flagged SWAPPED is returned in Pinnacle's team order."""
    @functools.wraps(fn)
    def wrapper(row, *args, **kwargs):
        out = fn(row, *args, **kwargs)
        return swap_sides(out) if row.get(SWAPPED) else out
    return wrapper


@reversible
def merkur_markets(row, period="ft"):
    """One MerkurXtip basketball offer row -> the same shape as pinnacle_markets(), for one period."""
    params = row.get("params") or {}
    codes = MX_PERIOD[period]
    return {
        "ml": mx._pick(row.get("odds") or {}, dict(zip(("home", "away"), codes["ml"]))),
        "spreads": common.param_lines(row, codes["spreads"], ("home", "away")),
        "totals": common.param_lines(row, codes["totals"], ("over", "under")),
        "home": common.param_lines(row, codes["home"], ("over", "under")),
        "away": common.param_lines(row, codes["away"], ("over", "under")),
        # MerkurXtip's own main lines: the first set of each market (params without a number suffix)
        "main": {"spreads": mx._param_line(params, codes["spreads"][0][0]),
                 "totals": mx._param_line(params, codes["totals"][0][0])},
    }


# ------------------------------------------------------------------------- comparison

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
                rows.append(common.compare_row(group, None, labels, merkur["ml"], pin["ml"]))
            continue
        for line in sorted(merkur[key]):
            if line in pin[key]:
                rows.append(common.compare_row(group, line, labels, merkur[key][line], pin[key][line],
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


PERIOD_LABELS = {key: label for key, label, _, _ in PERIODS}
PREFIXES = {"ft": "", "ht": "1.pol ", "q1": "1.čet "}


def value_items(match_id, rows, stale=None):
    """Every outcome where the MerkurXtip price beats the Pinnacle price, one item each; `stale` is stale_gaps()."""
    def gap(period, r, o):
        # MerkurXtip main line vs Pinnacle's, when this outcome is the side that gap favours
        found = (stale or {}).get(r["group"])
        return found if period == "ft" and found and favours(r["group"], found, o["key"]) else None

    return common.value_items(match_id, [(r.get("period", "ft"), r) for r in rows], PERIOD_LABELS, stale=gap)


def swapped_entries(base, row):
    """A MerkurXtip row offered in both team orders: the second entry has home and away exchanged and its row
    flagged SWAPPED, so a game MerkurXtip lists the other way round than Pinnacle still pairs (and is priced
    the right way round). mx.pair keeps one entry per offer id."""
    return [{**base, "home": row.get("home", ""), "away": row.get("away", ""), "row": row},
            {**base, "home": row.get("away", ""), "away": row.get("home", ""), "row": {**row, SWAPPED: True}}]


def pair_inputs(events, offer, mx_comp=MX_COMP):
    pin = [{"id": str(e["event_id"]), "comp": e["league_id"], "home": e.get("home", ""),
            "away": e.get("away", ""), "ts": event_ts(e)} for e in events]
    mer = [m for r in offer if r.get("leagueId") in mx_comp and mx.is_prematch(r)
           for m in swapped_entries({"id": r["id"], "comp": mx_comp[r["leagueId"]],
                                     "ts": r.get("kickOffTime") or 0}, r)]
    return pin, mer


def pair_events(events, offer, mx_comp=MX_COMP, score_fn=None):
    pin, mer = pair_inputs(events, offer, mx_comp)
    return {pid: (m["row"], score) for pid, (m, score) in mx.pair(pin, mer, score_fn=score_fn).items()}


def unpaired_hints(events, offer, pairs, mx_comp=MX_COMP, score_fn=None):
    """{pinnacle id: closest unused MerkurXtip offer row} for events without a pair, for the "missing" view."""
    pin, mer = pair_inputs(events, offer, mx_comp)
    return mx.hints(pin, mer, pairs, score_fn=score_fn)


def board_match(event, pin, hit, rows, periods, groups, prefixes, stale=None, league_id=None):
    """Board entry of one Pinnacle event, plus every compare row of it.

    `groups` are the (handicap, total) group labels of the board cells, `prefixes` the period labels of the best
    edge, `stale` the "Merkur kasni" gaps (basketball), `league_id` the competition when not the PinnWire league.
    """
    every_row = rows + [r for found in periods.values() for r in found]
    merkur = None
    if hit:
        row, score = hit
        swapped = bool(row.get(SWAPPED))  # names in Pinnacle's order, like the prices
        ml_row = next((r for r in rows if r["group"] == "Pobednik"), None)
        merkur = {
            "id": row.get("id"), "home": row.get("away" if swapped else "home", ""),
            "away": row.get("home" if swapped else "away", ""), "score": score,
            "kickoffDiff": round(((row.get("kickOffTime") or 0) - event_ts(event)) / 60000),
            "ml": {o["key"]: {"odds": o["merkur"], "ev": o["ev"]} for o in ml_row["outcomes"]} if ml_row else None,
            "best": common.best_edge([(r.get("period", "ft"), r) for r in every_row], prefixes),
            "compared": len(every_row),
            "stale": [{"group": g, "gap": gap} for g, gap in (stale or {}).items()],
        }
    ml_fair, margin = pw.fair_odds(pin["ml"]) if pin["ml"] else ({}, None)
    exact = [r for r in rows if not r.get("modeled")]
    match = {
        "id": event.get("event_id"),
        "leagueId": event.get("league_id") if league_id is None else league_id,
        "leagueName": event.get("league_name") or "",
        "home": event.get("home", ""),
        "away": event.get("away", ""),
        "starts": common.starts(event),
        "ml": ({s: {"odds": pin["ml"][s], "fair": round(ml_fair[s], 3)} for s in ("home", "away")}
               if pin["ml"] else None),
        "margin": margin,
        "spread": board_cell([r for r in exact if r["group"] == groups[0]], pin["spreads"], ("home", "away")),
        "total": board_cell([r for r in exact if r["group"] == groups[1]], pin["totals"], ("over", "under")),
        "merkur": merkur,
        "rows": rows,
        "periods": periods,
    }
    return match, every_row


def shape_match(event, hit):
    """Board entry of one Pinnacle event, plus its value items from the paired MerkurXtip row."""
    pin = pinnacle_markets(event)
    rows, stale, periods = [], {}, {}
    if hit:
        row, _ = hit
        decoded = merkur_markets(row)
        rows = compare(pin, decoded, limits=pinnacle_limits(event))
        stale = stale_gaps(pin, decoded)
        for key, _, number, scale in PERIODS[1:]:
            if pw.period(event, number):
                found = compare(pinnacle_markets(event, number), merkur_markets(row, key), key, scale,
                                pinnacle_limits(event, number))
                if found:
                    periods[key] = found
    match, every_row = board_match(event, pin, hit, rows, periods, ("Hendikep", "Ukupno poena"), PREFIXES, stale)
    return match, value_items(event.get("event_id"), every_row, stale)


# compare row group -> PinnWire drop market, for the MerkurXtip price on a drop alert
DROP_GROUPS = {"Pobednik": "moneyline", "Hendikep": "spread", "Ukupno poena": "total"}


def rows_by_period(match, periods):
    """Every compare row of a board match grouped by PinnWire period number; `periods` maps key -> number."""
    out = {}
    for r in match["rows"] + [r for found in match["periods"].values() for r in found]:
        out.setdefault(periods[r.get("period", "ft")], []).append(r)
    return out


def drop_quotes(event, match):
    """{PinnWire event id: (board match id, quote index)} of one board match."""
    rows = rows_by_period(match, {key: number for key, _, number, _ in PERIODS})
    return {str(event["event_id"]): (match["id"], pw.quote_index(rows, DROP_GROUPS))}


def clv_matches(matches):
    """Board matches with a MerkurXtip pair in the shape ClvStore.observe() / PriceStore.observe() take."""
    return [{"id": m["id"], "home": m["home"], "away": m["away"], "league": m["leagueName"], "starts": m["starts"],
             "rows": [(r.get("period", "ft"), r) for r in m["rows"] + [r for found in m["periods"].values() for r in found]]}
            for m in matches if m["merkur"]]


class BasketballState(common.SnapshotState):
    """Basketball board. TennisState and HockeyState reuse it, overriding the class settings and hook methods."""

    sport_id = SPORT_ID
    offer_path = OFFER_PATH
    clv_name = "basketball"
    competition_list = COMPETITIONS
    mx_comp = MX_COMP  # MerkurXtip leagueId -> PinnWire league_id
    league_ids = frozenset(c["id"] for c in COMPETITIONS)
    score_fn = None  # team name score for pairing, None for merkur_client.name_score
    other_cache = None  # (offer, signature, unpaired ids, hints, offered) of the untracked leagues

    # ----- hooks
    def incoming(self, data):
        # every league: the untracked ones feed the "missing" view
        return [e for e in data.get("events") or [] if e.get("event_id") and pw.is_main_fixture(e)]

    def tracked(self, event):
        return event.get("league_id") in self.league_ids

    def complete(self, event):
        return True

    def shape(self, event, hit):
        return shape_match(event, hit)

    def pair(self, events, offer):
        return pair_events(events, offer, self.mx_comp, self.score_fn)

    def hints(self, events, offer, pairs):
        return unpaired_hints(events, offer, pairs, self.mx_comp, self.score_fn)

    def offered(self, offer):
        return sum(1 for r in offer if r.get("leagueId") in self.mx_comp and mx.is_prematch(r))

    def drop_quotes(self, event, match):
        return drop_quotes(event, match)

    def competitions(self, matches):
        counts = {}
        for m in matches:
            counts[m["leagueId"]] = counts.get(m["leagueId"], 0) + 1
        return [{**c, "count": counts.get(c["id"], 0)} for c in self.competition_list]

    def match(self, event_id):
        """One match compared against fresh single-match MerkurXtip odds (no PinnWire request)."""
        if self.events is None:
            self.refresh(if_empty=True)
        with self.lock:
            event = (self.events or {}).get(event_id)
        if event is None or not self.complete(event) or not self.tracked(event):
            raise LookupError("Meč nije u ponudi (možda je počeo ili uklonjen).")
        hit = self.pairs.get(event_id)
        error, fetched = "", self.merkur.stamp
        if hit is not None:
            row, score = hit
            try:
                row, fetched = {**hit[0], **self.merkur.api.match(row["id"])}, common.utc_stamp()
            except (RuntimeError, LookupError) as exc:
                error = str(exc)
            hit = (row, score)
        match, _ = self.shape(event, hit)
        return {"match": match, "fetchedAt": fetched, "error": error, "callsToday": self.history.calls_today()}

    def board(self, refresh=False, full=False):
        if refresh or full or self.events is None:
            self.refresh(full=full, if_empty=not (refresh or full))
        offer = self.merkur_offer(refresh=refresh or full)
        with self.lock:
            now = common.utc_now()
            upcoming = [e for e in (self.events or {}).values() if common.is_upcoming(e, now) and self.complete(e)]
        events = [e for e in upcoming if self.tracked(e)]
        others = [e for e in upcoming if not self.tracked(e)]
        pairs = self.pair(events, offer)
        self.pairs = pairs
        hints = self.hints(events, offer, pairs)
        matches, values, quotes = [], [], {}
        for event in events:
            match, items = self.shape(event, pairs.get(str(event["event_id"])))
            match["hint"] = hints.get(str(event["event_id"]))
            if match["merkur"]:
                quotes.update(self.drop_quotes(event, match))
            # a match without any Pinnacle price is not worth a row
            if match["ml"] or match["spread"] or match["total"]:
                matches.append(match)
                values.extend(items)
        matches.sort(key=lambda m: (m["starts"], m["home"]))
        self.quotes = quotes
        self.record(self.clv_name, clv_matches(matches), values)
        missing_other = self.missing_other(others, offer, {row["id"] for row, _ in pairs.values()})
        return {
            "competitions": self.competitions(matches),
            "matches": matches,
            "otherCompetitions": common.other_competitions(missing_other),
            "otherMissing": missing_other,
            "suspended": self.suspended_items(),
            "otherOffered": self.other_cache[4] if self.other_cache else [],
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

    def missing_other(self, events, offer, used):
        """Board entries of untracked events MerkurXtip does not offer (cached until the offer or the set of events
        changes: the pairing without a competition check is slow)."""
        signature = (frozenset(str(e["event_id"]) for e in events), frozenset(used))
        cache = self.other_cache
        if cache is None or cache[0] is not offer or cache[1] != signature:
            missing, hints, paired = common.unpaired_other(events, offer, used)
            cache = self.other_cache = (offer, signature, missing, hints, common.offered_other(events, paired))
        _, _, missing, hints, _ = cache
        out = []
        for e in events:
            key = str(e["event_id"])
            if key not in missing:
                continue
            match, _ = self.shape(e, None)
            if match["ml"] or match["spread"] or match["total"]:
                out.append({**{k: v for k, v in match.items() if k not in ("rows", "periods")},
                            "hint": hints.get(key)})
        return sorted(out, key=lambda m: (m["starts"], m["home"]))
