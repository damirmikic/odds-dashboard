"""Handball and volleyball board: Pinnacle (PinnWire sport 10) against the MerkurXtip handball (feed letter "HB")
and volleyball (feed letter "V") offers, one sport on the dashboard.

PinnWire files both under sport 10 and tells them apart only by the lines: a handball total is 20-99 goals, a
volleyball one 3.5-4.5 sets or well over 100 points (`kind`). A MerkurXtip row says its sport (`sport`), and a match
pairs only within its sport. Volleyball compares the match winner only: MerkurXtip sells point handicaps and totals,
Pinnacle quotes set lines, which share numbers (a 2.5 set handicap, a 2.5 point handicap) but not meaning.

Handball: PinnWire quotes period 0, the game in regulation time: a two-way winner that refunds a draw (MerkurXtip "W1" / "W2"),
sometimes the three-way 1X2, handicap and totals; the first half (period 1) when it is quoted. Lines are matched
exactly and only half-point lines are used. No model, like tennis.
The competitions are the PinnWire leagues ("Serbia - Superliga"), handball leagues are not mapped to MerkurXtip ones:
a match pairs by team names and kickoff within 3 h, a women's side only with a women's side (`common.other_score`).
Everything else (state, delta merging, board shape) is shared with basketball.
"""
from __future__ import annotations

import re

import basketball as bb
import common
import merkur_client as mx
import pinnwire_client as pw

SPORT_ID = 10
OFFER_PATHS = ["/restapi/custom/offer/sr/sport/HB/mob", "/restapi/custom/offer/sr/sport/V/mob"]
HANDBALL, VOLLEYBALL = "HB", "V"  # the MerkurXtip sport of each, also the pairing key
HANDBALL_TOTALS = (20, 100)  # goals; a volleyball total is 3.5-4.5 sets or 130+ points
MIN_PAIR_SCORE = common.OTHER_MIN_SCORE
PAIR_WINDOW = common.OTHER_WINDOW

# (key, label, PinnWire period number)
PERIODS = [("ft", "Ceo meč", 0), ("h1", "1. poluvreme", 1)]
NUMBERS = {key: number for key, _, number in PERIODS}

# Each set is (line param, home/over code, away/under code); the param holds the home-side line.
MX_PERIOD = {
    "ft": {
        "ml": ("264", "265"),  # draw no bet
        "x12": ("1", "2", "3"),
        "spreads": [("hd2w", "53877", "53878")],
        "totals": [("overUnder", "227", "228")],
    },
    "h1": {
        "spreads": [("hd2wp1", "53903", "53904")],
        "totals": [("overUnderP", "229", "230")],
    },
}

VOLLEYBALL_ML = ("1", "3")  # the match winner; the set and point markets are not compared

GROUPS = [
    # key in pinnacle_markets()/merkur_markets(), group label, outcome sides
    ("ml", "Pobednik", (("home", "1"), ("away", "2"))),
    ("x12", "1X2", (("home", "1"), ("draw", "X"), ("away", "2"))),
    ("spreads", "Hendikep", (("home", "1"), ("away", "2"))),
    ("totals", "Ukupno golova", (("over", "Više"), ("under", "Manje"))),
]
EMPTY = {"ml": None, "x12": None, "spreads": {}, "totals": {}}

BADGES = {HANDBALL: "handball", VOLLEYBALL: "volleyball"}  # badge class of a league
# PinnWire country -> the name the side menu groups by (the others keep PinnWire's)
COUNTRIES = {
    "Serbia": "Srbija", "France": "Francuska", "Germany": "Nemačka", "Spain": "Španija", "Croatia": "Hrvatska",
    "Slovenia": "Slovenija", "Hungary": "Mađarska", "Romania": "Rumunija", "Poland": "Poljska", "Denmark": "Danska",
    "Sweden": "Švedska", "Norway": "Norveška", "Macedonia": "Severna Makedonija", "North Macedonia": "Severna Makedonija",
    "Bosnia and Herzegovina": "Bosna i Hercegovina", "Montenegro": "Crna Gora", "Greece": "Grčka",
    "Czech Republic": "Češka", "Slovakia": "Slovačka", "Switzerland": "Švajcarska", "Austria": "Austrija",
    "Portugal": "Portugal", "Italy": "Italija", "Russia": "Rusija", "Turkey": "Turska", "Europe": "Evropa",
    "International": "Međunarodno", "Brazil": "Brazil", "Argentina": "Argentina", "Iceland": "Island",
    "Netherlands": "Holandija", "Belgium": "Belgija", "Finland": "Finska", "Lithuania": "Litvanija",
    "Ukraine": "Ukrajina", "Belarus": "Belorusija", "Bulgaria": "Bugarska", "Egypt": "Egipat", "Qatar": "Katar",
}


# badge codes where the first three letters of the PinnWire country mislead
CODES = {"Austria": "AUT", "Greece": "GRC", "Germany": "GER", "Spain": "ESP", "Serbia": "SRB", "Switzerland": "SUI",
         "Netherlands": "NED", "Denmark": "DEN", "Slovakia": "SVK", "Slovenia": "SVN", "Croatia": "CRO",
         "Czech Republic": "CZE", "Bulgaria": "BUL", "Portugal": "POR", "Sweden": "SWE", "Hungary": "HUN"}


# ------------------------------------------------------------------------- handball or volleyball

def top_total(event):
    """Largest total line any period of the event quotes, None while it has none."""
    lines = []
    for markets in (event.get("periods") or {}).values():
        for total in ((markets or {}).get("totals") or {}).values():
            if isinstance(total, dict) and total.get("points") is not None:
                lines.append(float(total["points"]))
    return max(lines) if lines else None


def kind(event):
    """HANDBALL or VOLLEYBALL by the event's totals; None while it has none (or an unknown size of them)."""
    total = top_total(event)
    if total is None:
        return None
    if HANDBALL_TOTALS[0] <= total < HANDBALL_TOTALS[1]:
        return HANDBALL
    return VOLLEYBALL if total < 6 or total >= HANDBALL_TOTALS[1] else None


# ------------------------------------------------------------------------- decoding

def pinnacle_markets(event, period="ft"):
    """Pinnacle prices of one period keyed like merkur_markets(): ml / x12 {side: odds}, lines {line: {side: odds}}."""
    markets = pw.period(event, NUMBERS[period])
    prices = markets.get("money_line") or {}
    three = pw.priced(prices, ("home", "draw", "away"))
    two = pw.priced(prices, ("home", "away"))
    if kind(event) == VOLLEYBALL:
        return {**EMPTY, "ml": two if len(two) == 2 else None}
    return {
        "ml": two if len(two) == 2 and len(three) < 3 else None,
        "x12": three if len(three) == 3 else None,
        "spreads": pw.ladder(markets.get("spreads"), "hdp", ("home", "away"), "spreads"),
        "totals": pw.ladder(markets.get("totals"), "points", ("over", "under")),
    }


def pinnacle_limits(event, period="ft"):
    """Pinnacle limits of one period keyed like pinnacle_markets(); the moneyline carries none."""
    markets = pw.period(event, NUMBERS[period])
    if kind(event) == VOLLEYBALL:
        return {"spreads": {}, "totals": {}}
    return {
        "spreads": pw.ladder_limits(markets.get("spreads"), "hdp", "spreads"),
        "totals": pw.ladder_limits(markets.get("totals"), "points"),
    }


def merkur_markets(row, period="ft"):
    """One MerkurXtip handball offer row -> the same shape as pinnacle_markets(), for one period."""
    raw = row.get("odds") or {}
    out = dict(EMPTY)
    if row.get("sport") == VOLLEYBALL:
        out["ml"] = mx._pick(raw, dict(zip(("home", "away"), VOLLEYBALL_ML)))
        return out
    codes = MX_PERIOD[period]
    if "ml" in codes:
        out["ml"] = mx._pick(raw, dict(zip(("home", "away"), codes["ml"])))
        out["x12"] = mx._pick(raw, dict(zip(("home", "draw", "away"), codes["x12"])))
    out["spreads"] = common.param_lines(row, codes["spreads"], ("home", "away"), "spreads")
    out["totals"] = common.param_lines(row, codes["totals"], ("over", "under"))
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
PREFIXES = {"ft": "", "h1": "1.pol "}


# ------------------------------------------------------------------------- pairing

def women(name, league):
    """The side name with a "W" marker when its league is a women's one, so common.other_score keeps the sexes apart."""
    if "women" in (league or "").lower() and "w" not in common.side_markers(name):
        return f"{name} W"
    return name


def pair_inputs(events, offer):
    pin = [{"id": str(e["event_id"]), "comp": kind(e), "ts": bb.event_ts(e),
            "home": women(e.get("home", ""), e.get("league_name")),
            "away": women(e.get("away", ""), e.get("league_name"))} for e in events]
    mer = [{"id": r["id"], "comp": r.get("sport"), "ts": r.get("kickOffTime") or 0, "row": r,
            "home": women(r.get("home", ""), r.get("leagueName")),
            "away": women(r.get("away", ""), r.get("leagueName"))} for r in offer if mx.is_prematch(r)]
    return pin, mer


def pair_events(events, offer):
    pin, mer = pair_inputs(events, offer)
    return {pid: (m["row"], score)
            for pid, (m, score) in mx.pair(pin, mer, PAIR_WINDOW, MIN_PAIR_SCORE, common.other_score).items()}


def unpaired_hints(events, offer, pairs):
    """{pinnacle id: closest unused MerkurXtip offer row} for events without a pair, for the "missing" view."""
    pin, mer = pair_inputs(events, offer)
    return mx.hints(pin, mer, pairs, PAIR_WINDOW, common.other_score)


def shape_match(event, hit):
    """Board entry of one Pinnacle event, plus its value items from the paired MerkurXtip row."""
    pin = pinnacle_markets(event)
    rows, periods = [], {}
    if hit:
        row, _ = hit
        rows = compare(pin, merkur_markets(row), limits=pinnacle_limits(event))
        for key, _, number in PERIODS[1:] if kind(event) == HANDBALL else ():
            if pw.period(event, number):
                found = compare(pinnacle_markets(event, key), merkur_markets(row, key), key,
                                pinnacle_limits(event, key))
                if found:
                    periods[key] = found
    match, every_row = bb.board_match(event, pin, hit, rows, periods, ("Hendikep", "Ukupno golova"), PREFIXES)
    match["sport"] = kind(event)
    items = common.value_items(event.get("event_id"), [(r["period"], r) for r in every_row], PERIOD_LABELS)
    return match, items


# compare row group -> PinnWire drop market
DROP_GROUPS = {"Pobednik": "moneyline", "1X2": "moneyline", "Hendikep": "spread", "Ukupno golova": "total"}


def drop_quotes(event, match):
    """{PinnWire event id: (board match id, quote index)} of one board match."""
    rows = bb.rows_by_period(match, NUMBERS)
    return {str(event["event_id"]): (match["id"], pw.quote_index(rows, DROP_GROUPS))}


def competition(league_id, name, sport=HANDBALL):
    """Side menu entry of a PinnWire handball or volleyball league ("Serbia - Superliga")."""
    country, league = common.split_league(name)
    return {"id": league_id, "key": re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") or f"hb{league_id}",
            "name": league or name, "country": COUNTRIES.get(country, country), "code": CODES.get(country, country[:3].upper()) or "HB",
            "badge": BADGES[sport]}


class JoinedAPI:
    """MerkurAPI over both offers: handball and volleyball rows in one list (each row carries its `sport`)."""

    def __init__(self):
        self.apis = [mx.MerkurAPI(offer_path=path) for path in OFFER_PATHS]

    def offer(self):
        rows, errors = [], []
        for api in self.apis:
            try:
                rows += api.offer()
            except (RuntimeError, LookupError) as exc:
                errors.append(exc)
        if len(errors) == len(self.apis):
            raise errors[0]  # one feed down still shows the other
        return rows

    def match(self, match_id):
        return self.apis[0].match(match_id)


class HandballState(bb.BasketballState):
    clv_name = "handball"
    sport_id = SPORT_ID
    offer_path = OFFER_PATHS[0]

    def __init__(self, history, key_fn, merkur=None):
        super().__init__(history, key_fn, merkur or mx.OfferCache(JoinedAPI()))

    def tracked(self, event):
        return True  # every league

    def complete(self, event):
        return kind(event) is not None

    def owns(self, event_id):
        """True for a PinnWire event this board shows (the stream carries every event of sport 10)."""
        with self.lock:
            event = (self.events or {}).get(str(event_id))
        return event is not None and kind(event) is not None

    def suspended_items(self):
        return [m for m in super().suspended_items() if self.owns(m["id"])]

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
        found = {}
        for m in matches:
            entry = found.setdefault(m["leagueId"], competition(m["leagueId"], m["leagueName"], m["sport"]))
            entry["count"] = entry.get("count", 0) + 1
        return sorted(found.values(), key=lambda c: (c["country"], c["name"]))
