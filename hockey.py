"""Ice hockey board: Pinnacle (PinnWire sport 4) against the MerkurXtip hockey offer (feed letter "H").

PinnWire numbers hockey periods 0 = the whole game with overtime and shootout (two-way winner), 6 = regulation
time (60 minutes: three-way winner, handicap, totals, team totals) and 1, 2, 3 = the thirds (two-way winner that
refunds a drawn third, handicap, totals). MerkurXtip sells the winner with overtime ("P1" / "P2"), the 60-minute
1X2, handicap and totals, and the same markets per third. Lines are matched exactly; only half-point lines are
used. The level handicap (AH 0) is left out on purpose, unlike football: Pinnacle's two-way hockey price is the
moneyline with overtime, compared with MerkurXtip's winner with overtime and shootout, so MerkurXtip's "X vraća
ulog" has no Pinnacle counterpart. No model, like tennis. Everything else (state, delta merging, board shape) is
shared with basketball.
"""
from __future__ import annotations

import basketball as bb
import common
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
    {"id": 1293, "key": "ohl", "name": "OHL", "country": "Kanada", "code": "OHL", "mx_id": 2325713},
    {"id": 280513, "key": "cze2l", "name": "2. liga", "country": "Češka", "code": "CZE2", "mx_id": 2388950},
    {"id": 206705, "key": "cze1l", "name": "1. liga", "country": "Češka", "code": "CZE1", "mx_id": 2313807},
    {"id": 280900, "key": "ecn", "name": "European Cup of Nations", "country": "Evropa", "code": "ECN",
     "mx_id": 2391444},
    {"id": 4605, "key": "eht", "name": "Euro Hockey Tour", "country": "Evropa", "code": "EHT", "mx_id": 2328104},
    {"id": 4828, "key": "wcw", "name": "Svetsko prvenstvo (Ž)", "country": "Svet", "code": "WCW", "mx_id": 2323564},
    {"id": 1325, "key": "chl", "name": "Champions Hockey League", "country": "Evropa", "code": "CHL", "mx_id": 2323761},
    {"id": 1517, "key": "shl", "name": "SHL", "country": "Švedska", "code": "SHL", "mx_id": 2313733},
    {"id": 206707, "key": "swissl", "name": "Swiss League", "country": "Švajcarska", "code": "SUI2", "mx_id": 2314025},
    {"id": 1446, "key": "latl", "name": "Latvian Hockey League", "country": "Letonija", "code": "LAT", "mx_id": 2314027},
    {"id": 222893, "key": "norehl", "name": "Eliteserien", "country": "Norveška", "code": "NOR", "mx_id": 2387459},
    {"id": 217164, "key": "nor1dh", "name": "1. divisjon", "country": "Norveška", "code": "NOR2", "mx_id": 2314176},
    {"id": 1604, "key": "intfrw", "name": "Prijateljske utakmice (Ž)", "country": "Svet", "code": "FRW", "mx_id": 2326954},
]
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

def numbers(period):
    """(period holding the winner, period holding the other markets) of a compare period."""
    return (0, REGULATION) if period == "ft" else (NUMBERS[period], NUMBERS[period])


def full_limit(lines, key):
    """The ladder without lines limited below its main line (prices closest to even): Pinnacle shows only the
    main line ±0.5 in hockey, and PinnWire's extra lines (60 min Over 4.5 at max 100 and 6.5 at max 50 next to
    5.5 at 200) carry lower limits and prices out of line with the rest."""
    if not isinstance(lines, dict):
        return lines
    sides = ("over", "under") if key == "points" else ("home", "away")
    rows = [(name, line, pw.priced(line, sides)) for name, line in lines.items() if isinstance(line, dict)]
    rows = [row for row in rows if len(row[2]) == 2]
    if len(rows) < 2:
        return lines
    top = min(rows, key=lambda row: abs(row[2][sides[0]] - row[2][sides[1]]))[1].get("max")
    if not top:
        return lines
    return {name: line for name, line in lines.items()
            if not (isinstance(line, dict) and line.get("max") and line["max"] < top)}


def pinnacle_markets(event, period="ft"):
    """Pinnacle prices of one period keyed like merkur_markets(): ml {side: odds}, lines {line: {side: odds}}.

    Spreads use the default ladder rule (half-point lines only), which drops the AH 0 PinnWire still quotes.
    """
    winner, rest = (pw.period(event, n) for n in numbers(period))
    ml = pw.priced(winner.get("money_line") or {}, ("home", "away"))
    three = pw.priced(rest.get("money_line") or {}, ("home", "draw", "away"))
    return {
        "ml": ml if len(ml) == 2 else None,
        "x12": three if period == "ft" and len(three) == 3 else None,
        "spreads": pw.ladder(full_limit(rest.get("spreads"), "hdp"), "hdp", ("home", "away"), ordered=True),
        "totals": pw.ladder(full_limit(rest.get("totals"), "points"), "points", ("over", "under"), ordered=True),
        **common.team_ladders(rest),
    }


def pinnacle_limits(event, period="ft"):
    """Pinnacle limits of one period keyed like pinnacle_markets(); the moneyline carries none."""
    rest = pw.period(event, numbers(period)[1])
    team = rest.get("team_totals") or {}
    return {
        "spreads": pw.ladder_limits(full_limit(rest.get("spreads"), "hdp"), "hdp", ordered=True),
        "totals": pw.ladder_limits(full_limit(rest.get("totals"), "points"), "points", ordered=True),
        "home": pw.ladder_limits(team.get("home"), "points"),
        "away": pw.ladder_limits(team.get("away"), "points"),
    }


@bb.reversible
def merkur_markets(row, period="ft"):
    """One MerkurXtip hockey offer row -> the same shape as pinnacle_markets(), for one period."""
    raw = row.get("odds") or {}
    codes = MX_PERIOD[period]
    out = {"ml": mx._pick(raw, dict(zip(("home", "away"), codes["ml"]))), **EMPTY}
    if "x12" in codes:
        out["x12"] = mx._pick(raw, dict(zip(("home", "draw", "away"), codes["x12"])))
    out["spreads"] = common.param_lines(row, codes["spreads"], ("home", "away"))
    out["totals"] = common.param_lines(row, codes["totals"], ("over", "under"))
    for side in ("home", "away"):
        out[side] = common.param_lines(row, codes.get(side, []), ("over", "under"))
    return out


# ------------------------------------------------------------------------- comparison

def compare(pin, merkur, period="ft", limits=None):
    """Every market both books price at the same line, as compare rows."""
    rows = []
    for key, group, labels in GROUPS:
        if key in ("ml", "x12"):
            if pin[key] and merkur[key]:
                rows.append(common.compare_row(group, None, labels, merkur[key], pin[key]))
            continue
        for line in sorted(merkur[key]):
            if line in pin[key]:
                rows.append(common.compare_row(group, line, labels, merkur[key][line], pin[key][line],
                                           (limits or {}).get(key, {}).get(line)))
    for r in rows:
        r["period"] = period
    return rows


PERIOD_LABELS = {key: label for key, label, _ in PERIODS}
PREFIXES = {"ft": "", "p1": "1.per ", "p2": "2.per ", "p3": "3.per "}


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


def pair_events(events, offer):
    return bb.pair_events(events, offer, MX_COMP, name_score)


def shape_match(event, hit):
    """Board entry of one Pinnacle event, plus its value items from the paired MerkurXtip row."""
    pin = pinnacle_markets(event)
    rows, periods = [], {}
    if hit:
        row, _ = hit
        rows = compare(pin, merkur_markets(row), limits=pinnacle_limits(event))
        for key, _, number in PERIODS[1:]:
            if pw.period(event, number):
                found = compare(pinnacle_markets(event, key), merkur_markets(row, key), key,
                                pinnacle_limits(event, key))
                if found:
                    periods[key] = found
    match, every_row = bb.board_match(event, pin, hit, rows, periods, ("Hendikep", "Ukupno golova"), PREFIXES)
    items = common.value_items(event.get("event_id"), [(r["period"], r) for r in every_row], PERIOD_LABELS)
    return match, items


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
    competition_list = COMPETITIONS
    mx_comp = MX_COMP
    league_ids = frozenset(c["id"] for c in COMPETITIONS)
    score_fn = staticmethod(name_score)

    def shape(self, event, hit):
        return shape_match(event, hit)

    def drop_quotes(self, event, match):
        return drop_quotes(event, match)
