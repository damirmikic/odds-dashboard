"""Tennis board: Pinnacle (PinnWire sport 2) against the MerkurXtip tennis offer (feed letter "T").

PinnWire quotes a tennis match as two events: the main one in sets (winner, set handicap, total sets, 1st set winner)
and a side event with `parent_id` pointing at it in games (game handicap, total games, games per player, 1st set
total games); the side events come with `include_alt_units`. They are merged here into one event, the games under
`games`. Tournaments change their league_id every round, so the competitions are the tournaments, derived from
the league names ("ATP Lyon - R16" -> "ATP Lyon"). Lines are matched exactly and only half-point lines are used.
Everything else (state, delta merging, board shape) is shared with basketball.
"""
from __future__ import annotations

import re

import basketball as bb
import common
import merkur_client as mx
import pinnwire_client as pw

SPORT_ID = 2
OFFER_PATH = "/restapi/custom/offer/sr/sport/T/mob"
MIN_PAIR_SCORE = 0.75
# MerkurXtip's tennis kickoff is often a rough "not before" time, hours away from Pinnacle's; the player names pair
PAIR_WINDOW = 12 * 60

# (key, label, PinnWire period number); PinnWire numbers tennis periods 0 = match, 1 = 1st set.
PERIODS = [("ft", "Ceo meč", 0), ("s1", "1. set", 1)]
NUMBERS = {key: number for key, _, number in PERIODS}

ML = ("1", "3")
# Each set is (line param, home/over code, away/under code); the param holds the home-side line.
MX_PERIOD = {
    "ft": {
        "ml": ML,
        "setspreads": [("hd2", "50538", "50539")],
        "spreads": [("handicapGames", "251", "253")],
        "totals": [("overUnderGames", "256", "254"), ("overUnderGames2", "463", "461")],
        "home": [("homeOverUnderGames", "50941", "50940")],
        "away": [("awayOverUnderGames", "50943", "50942")],
    },
    "s1": {
        "ml": ("50510", "50511"),
        "totals": [
            ("overUnderGamesFirstSet", "259", "257"), ("overUnderGamesFirstSet2", "51372", "51370"),
            ("overUnderGamesFirstSet3", "51375", "51373"), ("overUnderGamesFirstSet4", "51378", "51376"),
            ("overUnderGamesFirstSet5", "51381", "51379"),
        ],
    },
}
# "Ukupan broj setova 2" / "3": best of three only, so exactly 2 sets is the under of 2.5
SET_TOTAL = (2.5, "261", "260")

GROUPS = [
    # key in pinnacle_markets()/merkur_markets(), group label, outcome sides
    ("ml", "Pobednik", (("home", "1"), ("away", "2"))),
    ("setspreads", "Hendikep setova", (("home", "1"), ("away", "2"))),
    ("settotals", "Ukupno setova", (("over", "Više"), ("under", "Manje"))),
    ("spreads", "Hendikep gemova", (("home", "1"), ("away", "2"))),
    ("totals", "Ukupno gemova", (("over", "Više"), ("under", "Manje"))),
    ("home", "Gemovi igrač 1", (("over", "Više"), ("under", "Manje"))),
    ("away", "Gemovi igrač 2", (("over", "Više"), ("under", "Manje"))),
]
EMPTY = {key: {} for key in ("setspreads", "settotals", "spreads", "totals", "home", "away")}

# (name prefix, category label, badge code, badge class); the first prefix that matches wins
CATEGORIES = [
    ("ATP Challenger", "Challenger", "CH", "challenger"),
    ("ATP", "ATP", "ATP", "atp"),
    ("WTA", "WTA", "WTA", "wta"),
    ("ITF Men", "ITF muškarci", "ITF", "itfm"),
    ("ITF Women", "ITF žene", "ITF", "itfw"),
]
OTHER_CATEGORY = ("", "Ostalo", "TEN", "tennis")


# ------------------------------------------------------------------------- events

def tournament(league_name):
    """"ATP Lyon - R16" and "ATP Lyon - Doubles" are the same tournament."""
    return (league_name or "").rsplit(" - ", 1)[0].strip()


def category(name):
    return next((c for c in CATEGORIES if name.startswith(c[0])), OTHER_CATEGORY)


def competition(name):
    prefix, label, code, badge = category(name)
    short = name[len(prefix):].strip() if prefix and name.startswith(prefix) else name
    return {"id": name, "key": re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"), "name": short or name,
            "country": label, "code": code, "badge": badge}


def is_main(event):
    return not event.get("parent_id") and event.get("units") in (None, "", "Sets")


def is_games(event):
    return bool(event.get("parent_id")) and event.get("units") == "Games"


def merge_periods(old, new):
    periods = dict(old or {})
    for key, markets in (new or {}).items():
        if isinstance(markets, dict):
            periods[key] = {**(periods.get(key) or {}), **markets}
    return periods


def merge_event(old, new):
    """Delta merge of a main event, its periods and its games periods market by market."""
    merged = bb.merge_event(old, {k: v for k, v in new.items() if k != "games"})
    games = merge_periods(old.get("games"), new.get("games"))
    if games:
        merged["games"] = games
    return merged


# ------------------------------------------------------------------------- decoding

def pinnacle_markets(event, period="ft"):
    """Pinnacle prices of one period keyed like merkur_markets(): ml {side: odds}, lines {line: {side: odds}}."""
    number = NUMBERS[period]
    sets = pw.period(event, number)
    games = pw.period({"periods": event.get("games")}, number)
    ml = pw.priced(sets.get("money_line") or {}, ("home", "away"))
    return {
        "ml": ml if len(ml) == 2 else None,
        "setspreads": pw.ladder(sets.get("spreads"), "hdp", ("home", "away")),
        "settotals": pw.ladder(sets.get("totals"), "points", ("over", "under")),
        "spreads": pw.ladder(games.get("spreads"), "hdp", ("home", "away")),
        "totals": pw.ladder(games.get("totals"), "points", ("over", "under")),
        **common.team_ladders(games),
    }


def pinnacle_limits(event, period="ft"):
    """Pinnacle limits of one period keyed like pinnacle_markets(); the moneyline carries none."""
    number = NUMBERS[period]
    sets = pw.period(event, number)
    games = pw.period({"periods": event.get("games")}, number)
    team = games.get("team_totals") or {}
    return {
        "setspreads": pw.ladder_limits(sets.get("spreads"), "hdp"),
        "settotals": pw.ladder_limits(sets.get("totals"), "points"),
        "spreads": pw.ladder_limits(games.get("spreads"), "hdp"),
        "totals": pw.ladder_limits(games.get("totals"), "points"),
        "home": pw.ladder_limits(team.get("home"), "points"),
        "away": pw.ladder_limits(team.get("away"), "points"),
    }


@bb.reversible
def merkur_markets(row, period="ft"):
    """One MerkurXtip tennis offer row -> the same shape as pinnacle_markets(), for one period."""
    raw = row.get("odds") or {}
    codes = MX_PERIOD[period]
    out = {"ml": mx._pick(raw, dict(zip(("home", "away"), codes["ml"]))), **EMPTY}
    out["totals"] = common.param_lines(row, codes["totals"], ("over", "under"))
    if period == "ft":
        out["setspreads"] = common.param_lines(row, codes["setspreads"], ("home", "away"))
        out["spreads"] = common.param_lines(row, codes["spreads"], ("home", "away"))
        out["home"] = common.param_lines(row, codes["home"], ("over", "under"))
        out["away"] = common.param_lines(row, codes["away"], ("over", "under"))
        line, over, under = SET_TOTAL
        prices = mx._pick(raw, {"over": over, "under": under})
        if prices:
            out["settotals"] = {line: prices}
    return out


# ------------------------------------------------------------------------- comparison

def compare(pin, merkur, period="ft", limits=None):
    """Every market both books price at the same line, as compare rows."""
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
    for r in rows:
        r["period"] = period
    return rows


PERIOD_LABELS = {key: label for key, label, _ in PERIODS}
PREFIXES = {"ft": "", "s1": "1.set "}


def player_score(pinnacle, merkur):
    """0..1 for a player or a doubles pair: "Katarzyna Kawa" against "K. Kawa" (MerkurXtip writes initials).

    Every full name token of the side with fewer of them must be found in the other name, and every initial
    must start a token of the other name; a lone initial never pairs two players.
    """
    ta, tb = mx.norm_tokens(pinnacle), mx.norm_tokens(merkur)
    full_a, full_b = [t for t in ta if len(t) > 1], [t for t in tb if len(t) > 1]
    if not full_a or not full_b:
        return 0.0
    initials = [(t, full_b) for t in ta if len(t) == 1] + [(t, full_a) for t in tb if len(t) == 1]
    if not all(any(u.startswith(t) for u in names) for t, names in initials):
        return 0.0
    short, long_ = (full_a, full_b) if len(full_a) <= len(full_b) else (full_b, full_a)
    return sum(1 for t in short if any(mx._token_match(t, u) for u in long_)) / len(short)


def pair_inputs(events, offer):
    # tournaments are named differently by the two books, so only the players and the kickoff pair a match
    pin = [{"id": str(e["event_id"]), "comp": "T", "home": e.get("home", ""), "away": e.get("away", ""),
            "ts": bb.event_ts(e)} for e in events]
    mer = [m for r in offer if mx.is_prematch(r)
           for m in bb.swapped_entries({"id": r["id"], "comp": "T", "ts": r.get("kickOffTime") or 0}, r)]
    return pin, mer


def pair_events(events, offer):
    pin, mer = pair_inputs(events, offer)
    return {pid: (m["row"], score) for pid, (m, score) in mx.pair(pin, mer, PAIR_WINDOW, MIN_PAIR_SCORE, player_score).items()}


def unpaired_hints(events, offer, pairs):
    """{pinnacle id: closest unused MerkurXtip offer row} for events without a pair, for the "missing" view."""
    pin, mer = pair_inputs(events, offer)
    return mx.hints(pin, mer, pairs, PAIR_WINDOW, player_score)


def shape_match(event, hit):
    """Board entry of one Pinnacle event, plus its value items from the paired MerkurXtip row."""
    pin = pinnacle_markets(event)
    rows, periods = [], {}
    if hit:
        row, _ = hit
        rows = compare(pin, merkur_markets(row), limits=pinnacle_limits(event))
        for key, _, _ in PERIODS[1:]:
            found = compare(pinnacle_markets(event, key), merkur_markets(row, key), key, pinnacle_limits(event, key))
            if found:
                periods[key] = found
    match, every_row = bb.board_match(event, pin, hit, rows, periods, ("Hendikep gemova", "Ukupno gemova"), PREFIXES,
                                      league_id=tournament(event.get("league_name")))
    items = common.value_items(event.get("event_id"), [(r["period"], r) for r in every_row], PERIOD_LABELS)
    return match, items


# compare row group -> PinnWire drop market; sets markets drop on the main event, games markets on the games event
MAIN_DROPS = {"Pobednik": "moneyline", "Hendikep setova": "spread", "Ukupno setova": "total"}
GAMES_DROPS = {"Hendikep gemova": "spread", "Ukupno gemova": "total"}


def drop_quotes(event, match):
    """{PinnWire event id: (board match id, quote index)} for the main and the games event of one match."""
    rows = bb.rows_by_period(match, {key: number for key, _, number in PERIODS})
    out = {str(event["event_id"]): (match["id"], pw.quote_index(rows, MAIN_DROPS))}
    if event.get("games_id"):
        out[str(event["games_id"])] = (match["id"], pw.quote_index(rows, GAMES_DROPS))
    return out


class TennisState(bb.BasketballState):
    clv_name = "tennis"
    sport_id = SPORT_ID
    offer_path = OFFER_PATH
    alt_units = True

    def incoming(self, data):
        """Main events plus their games events, folded into one partial event per match."""
        out = {}
        for raw in data.get("events") or []:
            if is_main(raw) and raw.get("event_id"):
                part = raw
            elif is_games(raw):
                part = {"event_id": raw["parent_id"], "games": raw.get("periods") or {}, "games_id": raw["event_id"]}
            else:
                continue
            key = str(part["event_id"])
            out[key] = merge_event(out[key], part) if key in out else part
        return list(out.values())

    def merge(self, old, new):
        return merge_event(old, new)

    def tracked(self, event):
        return True  # every tournament

    def complete(self, event):
        # a games event can arrive before (or without) its main event
        return bool(event.get("home") and event.get("away"))

    def shape(self, event, hit):
        return shape_match(event, hit)

    def pair(self, events, offer):
        return pair_events(events, offer)

    def hints(self, events, offer, pairs):
        return unpaired_hints(events, offer, pairs)

    def offered(self, offer):
        return sum(1 for r in offer if mx.is_prematch(r))

    def drop_quotes(self, event, match):
        return drop_quotes(event, match)

    def competitions(self, matches):
        counts = {}
        for m in matches:
            counts[m["leagueId"]] = counts.get(m["leagueId"], 0) + 1
        comps = [{**competition(name), "count": count} for name, count in counts.items()]
        order = {c[1]: i for i, c in enumerate(CATEGORIES)}
        return sorted(comps, key=lambda c: (order.get(c["country"], len(order)), c["name"]))
