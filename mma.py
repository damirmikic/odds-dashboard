"""MMA board: Pinnacle (PinnWire sport 8) against the MerkurXtip MMA offer (feed letter "MM").

PinnWire quotes a fight in period 0 only: the winner (two-way) and total rounds, usually one line (1.5 or 2.5).
MerkurXtip sells the winner as "W1" / "W2" (264 / 265), rounds over/under with the line in `params.our`, and
method of victory and "goes the distance" markets that Pinnacle does not price, so only the winner and total
rounds are compared. Lines are matched exactly, no model.

Both books order the fighters as they like (often the other way round), so a fight pairs in either order and a
reversed MerkurXtip row is flagged `pinSwapped`: its winner prices are read the other way round. Every PinnWire
MMA league is shown (the promotion is the competition) and fights pair by fighter names and kickoff within 12 h,
with no competition check: Pinnacle gives the card's start time, MerkurXtip each fight's own.
Everything else (state, delta merging, board shape) is shared with basketball.
"""
from __future__ import annotations

import re

import basketball as bb
import common
import merkur_client as mx
import pinnwire_client as pw
import tennis

SPORT_ID = 8
OFFER_PATH = "/restapi/custom/offer/sr/sport/MM/mob"
MIN_PAIR_SCORE = 0.75
PAIR_WINDOW = 12 * 60
SWAPPED = "pinSwapped"  # MerkurXtip row whose fighters are in the reverse of Pinnacle's order

ML = ("264", "265")  # "$h pobeđuje na meču" / "$a pobeđuje na meču"
# (line param, over code, under code)
ROUNDS = [("our", "54291", "54290")]

GROUPS = [
    # key in pinnacle_markets()/merkur_markets(), group label, outcome sides
    ("ml", "Pobednik", (("home", "1"), ("away", "2"))),
    ("totals", "Ukupno rundi", (("over", "Više"), ("under", "Manje"))),
]

# (league name prefix, badge code, badge class); the first prefix that matches wins
PROMOTIONS = [
    ("UFC", "UFC", "ufc"),
    ("PFL", "PFL", "pfl"),
    ("Bellator", "BEL", "bellator"),
    ("ONE", "ONE", "onefc"),
    ("Oktagon", "OKT", "oktagon"),
    ("KSW", "KSW", "ksw"),
]
OTHER_PROMOTION = ("", "MMA", "mma")
COUNTRY = "Organizacije"  # the side menu groups competitions by this label

# MerkurXtip fighter name (normalised) -> the PinnWire name of the same fighter, for names the token rules
# cannot pair (a fighter listed under a maiden or married name).
ALIASES = {
    "kunitskaya yana": "yana santos",
}


# ------------------------------------------------------------------------- decoding

def pinnacle_markets(event):
    """Pinnacle prices keyed like merkur_markets(): ml {side: odds}, totals {line: {side: odds}}."""
    markets = pw.period(event, 0)
    ml = pw.priced(markets.get("money_line") or {}, ("home", "away"))
    return {
        "ml": ml if len(ml) == 2 else None,
        "spreads": {},  # no handicap in MMA; board_match() reads it for the board cell
        "totals": pw.ladder(markets.get("totals"), "points", ("over", "under")),
    }


def pinnacle_limits(event):
    """Pinnacle limits keyed like pinnacle_markets(); the moneyline carries none."""
    return {"totals": pw.ladder_limits(pw.period(event, 0).get("totals"), "points")}


def merkur_markets(row):
    """One MerkurXtip MMA offer row -> the same shape as pinnacle_markets(), in Pinnacle's fighter order."""
    home, away = ML[::-1] if row.get(SWAPPED) else ML
    return {
        "ml": mx._pick(row.get("odds") or {}, {"home": home, "away": away}),
        "totals": common.param_lines(row, ROUNDS, ("over", "under")),
    }


# ------------------------------------------------------------------------- comparison

def compare(pin, merkur, limits=None):
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
        r["period"] = "ft"
    return rows


PERIOD_LABELS = {"ft": "Borba"}
PREFIXES = {"ft": ""}


# ------------------------------------------------------------------------- pairing

def fighter_score(pinnacle, merkur):
    """0..1 for one fighter: "Zachary Reese" against "Reese, Zach" (tennis rules, plus the MMA aliases)."""
    return tennis.player_score(pinnacle, ALIASES.get(" ".join(mx.norm_tokens(merkur)), merkur))


def pair_inputs(events, offer):
    # every MerkurXtip fight is offered in both fighter orders; pair() keeps one per offer id
    pin = [{"id": str(e["event_id"]), "comp": "MM", "home": e.get("home", ""), "away": e.get("away", ""),
            "ts": bb.event_ts(e)} for e in events]
    mer = []
    for r in offer:
        if not mx.is_prematch(r):
            continue
        base = {"id": r["id"], "comp": "MM", "ts": r.get("kickOffTime") or 0}
        mer.append({**base, "home": r.get("home", ""), "away": r.get("away", ""), "row": r})
        mer.append({**base, "home": r.get("away", ""), "away": r.get("home", ""), "row": {**r, SWAPPED: True}})
    return pin, mer


def pair_events(events, offer):
    pin, mer = pair_inputs(events, offer)
    return {pid: (m["row"], score)
            for pid, (m, score) in mx.pair(pin, mer, PAIR_WINDOW, MIN_PAIR_SCORE, fighter_score).items()}


def unpaired_hints(events, offer, pairs):
    """{pinnacle id: closest unused MerkurXtip offer row} for events without a pair, for the "missing" view."""
    pin, mer = pair_inputs(events, offer)
    return mx.hints(pin, mer, pairs, PAIR_WINDOW, fighter_score)


def shape_match(event, hit):
    """Board entry of one Pinnacle event, plus its value items from the paired MerkurXtip row."""
    pin = pinnacle_markets(event)
    rows = []
    if hit:
        rows = compare(pin, merkur_markets(hit[0]), pinnacle_limits(event))
    match, every_row = bb.board_match(event, pin, hit, rows, {}, ("Hendikep", "Ukupno rundi"), PREFIXES)
    if hit and hit[0].get(SWAPPED):  # MerkurXtip's names in Pinnacle's order, like its prices
        merkur = match["merkur"]
        merkur["home"], merkur["away"] = merkur["away"], merkur["home"]
    items = common.value_items(event.get("event_id"), [(r["period"], r) for r in every_row], PERIOD_LABELS)
    return match, items


# compare row group -> PinnWire drop market; everything drops in period 0
DROP_GROUPS = {"Pobednik": "moneyline", "Ukupno rundi": "total"}


def drop_quotes(event, match):
    """{PinnWire event id: (board match id, quote index)} of one board match."""
    rows = bb.rows_by_period(match, {"ft": 0})
    return {str(event["event_id"]): (match["id"], pw.quote_index(rows, DROP_GROUPS))}


def competition(league_id, name):
    """Side menu entry of a PinnWire MMA league; the badge comes from the promotion in its name."""
    code, badge = next(((c, b) for prefix, c, b in PROMOTIONS if name.startswith(prefix)), OTHER_PROMOTION[1:])
    return {"id": league_id, "key": re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "mma", "name": name,
            "country": COUNTRY, "code": code, "badge": badge}


class MmaState(bb.BasketballState):
    clv_name = "mma"
    sport_id = SPORT_ID
    offer_path = OFFER_PATH

    def incoming(self, data):
        # every MMA league: promotions come and go, and fights pair by the fighters' names
        return [e for e in data.get("events") or [] if e.get("event_id") and pw.is_main_fixture(e)]

    def tracked(self, event):
        return True  # every promotion

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
            entry = found.setdefault(m["leagueId"], competition(m["leagueId"], m["leagueName"]))
            entry["count"] = entry.get("count", 0) + 1
        order = {badge: i for i, (_, _, badge) in enumerate(PROMOTIONS)}
        return sorted(found.values(), key=lambda c: (order.get(c["badge"], len(order)), c["name"]))
