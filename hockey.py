"""Ice hockey board: Pinnacle (PinnWire sport 4) against the MerkurXtip hockey offer (feed letter "H").

PinnWire numbers hockey periods 0 = the whole game with overtime and shootout (two-way winner), 6 = regulation
time (60 minutes: three-way winner, handicap, totals, team totals) and 1, 2, 3 = the thirds (two-way winner that
refunds a drawn third, handicap, totals). MerkurXtip sells the winner with overtime ("P1" / "P2"), the 60-minute
1X2, handicap and totals, and the same markets per third. Lines are matched exactly; only half-point lines are
used, plus the level handicap (AH 0), which MerkurXtip sells as "X vraća ulog". No model, like tennis.
Everything else (state, delta merging, board shape) is shared with basketball.
"""
from __future__ import annotations

import basketball as bb
import merkur_client as mx
import pinnwire_client as pw

SPORT_ID = 4
OFFER_PATH = "/restapi/custom/offer/sr/sport/H/mob"
REGULATION = 6  # PinnWire period number of the 60 minutes

# PinnWire league_id -> display info; `mx_id` is the MerkurXtip leagueId of the same competition.
COMPETITIONS = [
    {"id": 1456, "key": "nhl", "name": "NHL", "country": "SAD", "code": "NHL", "mx_id": 2314881},
    {"id": 1264, "key": "ahl", "name": "AHL", "country": "SAD", "code": "AHL", "mx_id": 2315898},
    {"id": 1295, "key": "qmjhl", "name": "QMJHL", "country": "Kanada", "code": "QMJ", "mx_id": 2342477},
    {"id": 206704, "key": "whl", "name": "WHL", "country": "Kanada", "code": "WHL", "mx_id": 2341400},
    {"id": 1484, "key": "khl", "name": "KHL", "country": "Rusija", "code": "KHL", "mx_id": 2313732},
    {"id": 5154, "key": "vhl", "name": "VHL", "country": "Rusija", "code": "VHL", "mx_id": 2313832},
    {"id": 149037, "key": "mhl", "name": "MHL", "country": "Rusija", "code": "MHL", "mx_id": 2313805},
    {"id": 1512, "key": "allsv", "name": "Allsvenskan", "country": "Švedska", "code": "ALL", "mx_id": 2313893},
    {"id": 217161, "key": "ettan", "name": "HockeyEttan", "country": "Švedska", "code": "ETT", "mx_id": 2313834},
    {"id": 223040, "key": "sdhl", "name": "SDHL (Ž)", "country": "Švedska", "code": "SDHL", "mx_id": 2341149},
    {"id": 1401, "key": "liiga", "name": "Liiga", "country": "Finska", "code": "LII", "mx_id": 2375725},
    {"id": 4529, "key": "mestis", "name": "Mestis", "country": "Finska", "code": "MES", "mx_id": 2316051},
    {"id": 1379, "key": "u20fin", "name": "Suomi-sarja U20", "country": "Finska", "code": "U20", "mx_id": 2390554},
    {"id": 1419, "key": "del", "name": "DEL", "country": "Nemačka", "code": "DEL", "mx_id": 2314454},
    {"id": 149036, "key": "del2", "name": "DEL 2", "country": "Nemačka", "code": "DL2", "mx_id": 2313836},
    {"id": 1532, "key": "nla", "name": "National League", "country": "Švajcarska", "code": "NL", "mx_id": 2313897},
    {"id": 1297, "key": "czeext", "name": "Extraliga", "country": "Češka", "code": "CZE", "mx_id": 2313810},
    {"id": 1498, "key": "sloext", "name": "Extraliga", "country": "Slovačka", "code": "SVK", "mx_id": 2313797},
    {"id": 1497, "key": "slo1", "name": "1. liga", "country": "Slovačka", "code": "SV1", "mx_id": 2314032},
    {"id": 1282, "key": "bely", "name": "Extraliga", "country": "Belorusija", "code": "BLR", "mx_id": 2313833},
    {"id": 1275, "key": "ihl", "name": "Ice Hockey League", "country": "Austrija", "code": "AUT", "mx_id": 2329773},
    {"id": 1413, "key": "magnus", "name": "Ligue Magnus", "country": "Francuska", "code": "FRA", "mx_id": 2314123},
    {"id": 1477, "key": "phl", "name": "PHL", "country": "Poljska", "code": "POL", "mx_id": 2390652},
    {"id": 1316, "key": "metal", "name": "Metal Ligaen", "country": "Danska", "code": "DEN", "mx_id": 2313738},
    {"id": 216131, "key": "alps", "name": "Alps Hockey League", "country": "Evropa", "code": "AHL2", "mx_id": 2394103},
    {"id": 211710, "key": "erste", "name": "Erste Liga", "country": "Evropa", "code": "ERS", "mx_id": 2313835},
    {"id": 206706, "key": "elite", "name": "Elite League", "country": "Velika Britanija", "code": "UK", "mx_id": 2317614},
    {"id": 1597, "key": "asia", "name": "Asia League", "country": "Azija", "code": "ASIA", "mx_id": 2387174},
]
LEAGUE_IDS = {c["id"] for c in COMPETITIONS}
MX_COMP = {c["mx_id"]: c["id"] for c in COMPETITIONS}

# (key, label, PinnWire period number or None for the whole game)
PERIODS = [("ft", "Ceo meč", None), ("p1", "1. period", 1), ("p2", "2. period", 2), ("p3", "3. period", 3)]
NUMBERS = {"ft": 0, "p1": 1, "p2": 2, "p3": 3}

# Each set is (line param, home/over code, away/under code); the param holds the home-side line.
MX_PERIOD = {
    "ft": {
        "ml": ("50816", "50817"),  # winner with overtime and shootout
        "x12": ("1", "2", "3"),
        "spreads": [("hd2w", "53877", "53878")],
        "totals": [("overUnder", "227", "228"), ("overUnder2", "429", "427"), ("overUnder3", "432", "430"),
                   ("overUnder4", "50078", "50076")],
        "home": [("homeOverUnder", "356", "355")],
        "away": [("awayOverUnder", "358", "357")],
    },
    "p1": {
        "ml": ("50761", "50762"),  # draw no bet
        "spreads": [("handicapFirstPeriod", "50751", "50752")],
        "totals": [("overUnderFirstPeriod", "50505", "50504")],
    },
    "p2": {
        "ml": ("50763", "50764"),
        "spreads": [("handicapSecondPeriod", "50753", "50754")],
        "totals": [("overUnderSecondPeriod", "50507", "50506")],
    },
    "p3": {
        "ml": ("50765", "50766"),
        "spreads": [("handicapThirdPeriod", "50755", "50756")],
        "totals": [("overUnderThirdPeriod", "50509", "50508")],
    },
}
LEVEL_SPREAD = ("264", "265")  # "X vraća ulog" (W1 / W2) is the level handicap of the 60 minutes

GROUPS = [
    # key in pinnacle_markets()/merkur_markets(), group label, outcome sides
    ("ml", "Pobednik", (("home", "1"), ("away", "2"))),
    ("x12", "1X2", (("home", "1"), ("draw", "X"), ("away", "2"))),
    ("spreads", "Hendikep", (("home", "1"), ("away", "2"))),
    ("totals", "Ukupno golova", (("over", "Više"), ("under", "Manje"))),
    ("home", "Golovi domaćin", (("over", "Više"), ("under", "Manje"))),
    ("away", "Golovi gost", (("over", "Više"), ("under", "Manje"))),
]
EMPTY = {"x12": None, "spreads": {}, "totals": {}, "home": {}, "away": {}}


# ------------------------------------------------------------------------- decoding

def by_line(lines, key, sides, market):
    out = {}
    for line in (lines or {}).values() if isinstance(lines, dict) else ():
        if isinstance(line, dict) and pw.allowed_line(pw._num(line.get(key)), market):
            prices = pw.priced(line, sides)
            if len(prices) == len(sides):
                out[pw._num(line[key])] = prices
    return out


def limits_by_line(lines, key, market):
    out = {}
    for line in (lines or {}).values() if isinstance(lines, dict) else ():
        if isinstance(line, dict) and pw.allowed_line(pw._num(line.get(key)), market):
            out[pw._num(line[key])] = line.get("max")
    return out


def numbers(period):
    """(period holding the winner, period holding the other markets) of a compare period."""
    return (0, REGULATION) if period == "ft" else (NUMBERS[period], NUMBERS[period])


def pinnacle_markets(event, period="ft"):
    """Pinnacle prices of one period keyed like merkur_markets(): ml {side: odds}, lines {line: {side: odds}}."""
    winner, rest = (pw.period(event, n) for n in numbers(period))
    ml = pw.priced(winner.get("money_line") or {}, ("home", "away"))
    three = pw.priced(rest.get("money_line") or {}, ("home", "draw", "away"))
    out = {
        "ml": ml if len(ml) == 2 else None,
        "x12": three if period == "ft" and len(three) == 3 else None,
        "spreads": by_line(rest.get("spreads"), "hdp", ("home", "away"), "spreads"),
        "totals": by_line(rest.get("totals"), "points", ("over", "under"), "totals"),
    }
    team, main_team = rest.get("team_totals") or {}, rest.get("team_total") or {}
    for side in ("home", "away"):
        lines = by_line(team.get(side), "points", ("over", "under"), "totals")
        single = by_line({side: main_team.get(side)}, "points", ("over", "under"), "totals")
        lines.update({k: v for k, v in single.items() if k not in lines})
        out[side] = lines
    return out


def pinnacle_limits(event, period="ft"):
    """Pinnacle limits of one period keyed like pinnacle_markets(); the moneyline carries none."""
    rest = pw.period(event, numbers(period)[1])
    team = rest.get("team_totals") or {}
    return {
        "spreads": limits_by_line(rest.get("spreads"), "hdp", "spreads"),
        "totals": limits_by_line(rest.get("totals"), "points", "totals"),
        "home": limits_by_line(team.get("home"), "points", "totals"),
        "away": limits_by_line(team.get("away"), "points", "totals"),
    }


def merkur_markets(row, period="ft"):
    """One MerkurXtip hockey offer row -> the same shape as pinnacle_markets(), for one period."""
    raw, params = row.get("odds") or {}, row.get("params") or {}
    codes = MX_PERIOD[period]

    def lines(sets, sides, market):
        out = {}
        for key, first, second in sets:
            line = mx._param_line(params, key)
            prices = mx._pick(raw, dict(zip(sides, (first, second))))
            if pw.allowed_line(line, market) and prices and line not in out:
                out[line] = prices
        return out

    out = {"ml": mx._pick(raw, dict(zip(("home", "away"), codes["ml"]))), **EMPTY}
    if "x12" in codes:
        out["x12"] = mx._pick(raw, dict(zip(("home", "draw", "away"), codes["x12"])))
    out["spreads"] = lines(codes["spreads"], ("home", "away"), "spreads")
    if period == "ft":
        level = mx._pick(raw, dict(zip(("home", "away"), LEVEL_SPREAD)))
        if level:
            out["spreads"].setdefault(0.0, level)
    out["totals"] = lines(codes["totals"], ("over", "under"), "totals")
    for side in ("home", "away"):
        out[side] = lines(codes.get(side, []), ("over", "under"), "totals")
    return out


# ------------------------------------------------------------------------- comparison

def compare(pin, merkur, period="ft", limits=None):
    """Every market both books price at the same line, as compare rows."""
    rows = []
    for key, group, labels in GROUPS:
        if key in ("ml", "x12"):
            if pin[key] and merkur[key]:
                rows.append(bb.compare_row(group, None, labels, merkur[key], pin[key]))
            continue
        for line in sorted(merkur[key]):
            if line in pin[key]:
                rows.append(bb.compare_row(group, line, labels, merkur[key][line], pin[key][line],
                                           (limits or {}).get(key, {}).get(line)))
    for r in rows:
        r["period"] = period
    return rows


def value_items(match_id, rows):
    """Every outcome where the MerkurXtip price beats the Pinnacle price, one item each."""
    labels = {key: label for key, label, _ in PERIODS}
    items = []
    for r in rows:
        period = r.get("period", "ft")
        for o in r["outcomes"]:
            if o["merkur"] <= o["pinnacle"]:
                continue
            items.append({
                "matchId": match_id, "period": period, "periodLabel": labels[period], "group": r["group"],
                "line": r["line"], "key": o["key"], "label": o["label"], "merkur": o["merkur"],
                "pinnacle": o["pinnacle"], "fair": o["fair"], "ev": o["ev"],
                "overPinnacle": round(o["merkur"] / o["pinnacle"] - 1, 4),
                "merkurMargin": r["merkurMargin"], "pinnacleMargin": r["pinnacleMargin"],
                "modeled": False, "stale": None,
            })
    return pw.best_per_line_market(items)


def best_edge(rows):
    best = None
    prefixes = {"ft": "", "p1": "1.per ", "p2": "2.per ", "p3": "3.per "}
    for r in rows:
        for o in r["outcomes"]:
            if best is None or o["ev"] > best["ev"]:
                market = r["group"] + ("" if r["line"] is None else f" {r['line']:g}")
                best = {"ev": o["ev"], "label": f"{prefixes[r.get('period', 'ft')]}{market} {o['label']}"}
    return best


# ------------------------------------------------------------------------- pairing

# MerkurXtip team name (normalised) -> the PinnWire name of the same team, for names the token rules cannot pair.
# Kept here and not in merkur_client.ALIASES: these short forms ("zurich") would also rewrite football names.
ALIASES = {
    "iisalmen": "ipk", "kiekko pojat": "jokp",
    "dinamo sp u20": "jhc dinamo st petersburg", "almaz u20": "almaz cherepovets",
    "tkh torun": "kh energa torun", "krakow": "comarch cracovia",
    "schwenninger": "serc wild wings", "bremerhaven": "fischtown pinguins",
    "zurich": "zsc lions", "langnau": "scl tigers",
}


def name_score(pinnacle, merkur):
    return mx.name_score(pinnacle, ALIASES.get(" ".join(mx.norm_tokens(merkur)), merkur))


def pair_inputs(events, offer):
    pin = [{"id": str(e["event_id"]), "comp": e["league_id"], "home": e.get("home", ""),
            "away": e.get("away", ""), "ts": bb.event_ts(e)} for e in events]
    mer = [{"id": r["id"], "comp": MX_COMP[r["leagueId"]], "home": r.get("home", ""), "away": r.get("away", ""),
            "ts": r.get("kickOffTime") or 0, "row": r}
           for r in offer if r.get("leagueId") in MX_COMP and mx.is_prematch(r)]
    return pin, mer


def pair_events(events, offer):
    pin, mer = pair_inputs(events, offer)
    return {pid: (m["row"], score) for pid, (m, score) in mx.pair(pin, mer, score_fn=name_score).items()}


def unpaired_hints(events, offer):
    """{pinnacle id: closest unused MerkurXtip offer row} for events without a pair, for the "missing" view."""
    pin, mer = pair_inputs(events, offer)
    paired = mx.pair(pin, mer, score_fn=name_score)
    ts = {p["id"]: p["ts"] for p in pin}
    return {pid: {"home": m["home"], "away": m["away"], "score": score,
                  "kickoffDiff": round((m["ts"] - ts[pid]) / 60000)}
            for pid, (m, score) in mx.closest_unpaired(pin, mer, paired, score_fn=name_score).items()}


def shape_match(event, hit):
    """Board entry of one Pinnacle event, plus its value items from the paired MerkurXtip row."""
    pin = pinnacle_markets(event)
    ml_fair, margin = pw.fair_odds(pin["ml"]) if pin["ml"] else ({}, None)
    rows, merkur, periods = [], None, {}
    if hit:
        row, score = hit
        rows = compare(pin, merkur_markets(row), limits=pinnacle_limits(event))
        for key, _, number in PERIODS[1:]:
            if pw.period(event, number):
                found = compare(pinnacle_markets(event, key), merkur_markets(row, key), key,
                                pinnacle_limits(event, key))
                if found:
                    periods[key] = found
        ml_row = next((r for r in rows if r["group"] == "Pobednik"), None)
        merkur = {
            "id": row.get("id"), "home": row.get("home", ""), "away": row.get("away", ""), "score": score,
            "kickoffDiff": round(((row.get("kickOffTime") or 0) - bb.event_ts(event)) / 60000),
            "ml": {o["key"]: {"odds": o["merkur"], "ev": o["ev"]} for o in ml_row["outcomes"]} if ml_row else None,
            "best": best_edge(rows + [r for found in periods.values() for r in found]),
            "compared": len(rows) + sum(len(found) for found in periods.values()),
            "stale": [],
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
        "spread": bb.board_cell([r for r in rows if r["group"] == "Hendikep"], pin["spreads"], ("home", "away")),
        "total": bb.board_cell([r for r in rows if r["group"] == "Ukupno golova"], pin["totals"], ("over", "under")),
        "merkur": merkur,
        "rows": rows,
        "periods": periods,
    }
    every_row = rows + [r for found in periods.values() for r in found]
    return match, value_items(event.get("event_id"), every_row)


# compare row group -> PinnWire drop market; the winner of the game drops in period 0, the rest of "ft" in period 6
DROP_GROUPS = {"Pobednik": "moneyline", "1X2": "moneyline", "Hendikep": "spread", "Ukupno golova": "total"}


def drop_quotes(event, match):
    """{PinnWire event id: (board match id, quote index)} of one board match."""
    rows = {}
    for r in match["rows"] + [r for found in match["periods"].values() for r in found]:
        period = r.get("period", "ft")
        number = 0 if period == "ft" and r["group"] == "Pobednik" else numbers(period)[1]
        rows.setdefault(number, []).append(r)
    return {str(event["event_id"]): (match["id"], pw.quote_index(rows, DROP_GROUPS))}


class HockeyState(bb.BasketballState):
    clv_name = "hockey"
    sport_id = SPORT_ID
    offer_path = OFFER_PATH

    def incoming(self, data):
        return [e for e in data.get("events") or []
                if e.get("event_id") and e.get("league_id") in LEAGUE_IDS and pw.is_main_fixture(e)]

    def shape(self, event, hit):
        return shape_match(event, hit)

    def pair(self, events, offer):
        return pair_events(events, offer)

    def hints(self, events, offer):
        return unpaired_hints(events, offer)

    def offered(self, offer):
        return sum(1 for r in offer if r.get("leagueId") in MX_COMP and mx.is_prematch(r))

    def drop_quotes(self, event, match):
        return drop_quotes(event, match)

    def competitions(self, matches):
        counts = {}
        for m in matches:
            counts[m["leagueId"]] = counts.get(m["leagueId"], 0) + 1
        return [{**c, "count": counts.get(c["id"], 0)} for c in COMPETITIONS]
