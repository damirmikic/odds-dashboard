import contextlib
import hashlib
import io
import json
import logging
import os
import re
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

import applog
import basketball as bb
import clv
import common
import handball
import hockey
import merkur_client as mx
import mma
import pinnwire_client as pw
import pinnwire_dashboard as dash
import price_history
import tennis


def kit_event(event_id=1628594960, **overrides):
    event = {
        "event_id": event_id,
        "sport_id": 1,
        "league_id": 2196,
        "league_name": "Spain - La Liga",
        "home": "Alaves",
        "away": "Villarreal",
        "starts": "2030-08-28T19:30:00Z",
        "units": "Regular",
        "parent_id": None,
        "periods": {
            "num_0": {
                "number": 0,
                "money_line": {"home": 2.45, "draw": 3.30, "away": 2.90},
                "spreads": {
                    "-0.5": {"hdp": -0.5, "home": 2.45, "away": 1.58, "max": 500},
                    "0.0": {"hdp": 0.0, "home": 1.82, "away": 2.06, "max": 500},
                },
                "totals": {
                    "2.5": {"points": 2.5, "over": 1.90, "under": 1.98, "max": 500},
                    "3.0": {"points": 3.0, "over": 2.40, "under": 1.60, "max": 500},
                },
            },
        },
    }
    event.update(overrides)
    return event


def event(event_id, league_id=1980, starts="2030-08-28T19:30:00Z", **overrides):
    return kit_event(event_id, league_id=league_id, starts=starts, **overrides)


class FakeAPI:
    def __init__(self, full, delta=None):
        self.full = full
        self.delta = delta or []
        self.calls = 0
        self.requests = []

    def prematch_snapshot(self, sport_id, since=None, alt_units=False):
        self.calls += 1
        self.requests.append(since)
        return {"events": self.delta if since else self.full, "last": 100 + self.calls}

    def prematch_event(self, event_id):
        self.calls += 1
        return event(int(event_id))


KICKOFF_MS = 1914175800000  # 2030-08-28T19:30:00Z


def merkur_row(match_id=900, home="Alaves", away="Villarreal", league="ENG PL", ts=KICKOFF_MS, **odds):
    base = {"1": 2.50, "2": 3.20, "3": 2.80, "24": 1.85, "22": 1.90, "53877": 1.70, "53878": 2.05}
    base.update(odds)
    return {"id": match_id, "matchCode": 1234, "home": home, "away": away, "kickOffTime": ts,
            "leagueShort": league, "live": False, "odds": base, "params": {"hd2w": "-0.5"}}


class FakeMerkurAPI:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.offer_calls = 0

    def offer(self):
        self.offer_calls += 1
        return self.rows

    def match(self, match_id):
        return next(r for r in self.rows if r["id"] == match_id)


def make_state(api, merkur_rows=None):
    merkur = mx.OfferCache(api=FakeMerkurAPI(merkur_rows))
    state = dash.DashboardState(dash.History(path=None), merkur=merkur)
    state.get_api = lambda: api
    return state


class BoardTests(unittest.TestCase):
    def test_only_tracked_upcoming_competitions(self):
        api = FakeAPI([
            event(1),
            event(2, league_id=2627),
            event(3, league_id=9999),  # not a tracked league
            event(4, starts="2001-01-01T00:00:00Z"),  # already started
            event(5, parent_id=1),  # special
        ])
        board = make_state(api).board()

        self.assertEqual(sorted(m["id"] for m in board["matches"]), [1, 2])
        counts = {c["key"]: c["count"] for c in board["competitions"]}
        self.assertEqual(counts["epl"], 1)
        self.assertEqual(counts["ucl"], 1)
        self.assertEqual(board["mode"], "full")
        self.assertEqual(board["callsToday"], 1)

    def test_summary_has_fair_odds_and_main_lines(self):
        match = make_state(FakeAPI([event(1)])).board()["matches"][0]

        self.assertAlmostEqual(sum(side["prob"] for side in match["ml"].values()), 1.0, places=3)
        self.assertEqual(match["ah"]["line"], 0.0)
        self.assertEqual(match["ou"]["line"], 2.5)
        self.assertEqual(match["open"], {"home": 2.45, "draw": 3.30, "away": 2.90})
        self.assertIsNone(match["prev"])

    def test_refresh_uses_delta_and_tracks_movement(self):
        moved = {"periods": {"num_0": {"money_line": {"home": 2.30, "draw": 3.40, "away": 3.10}}}}
        api = FakeAPI([event(1), event(2)], delta=[event(1, **moved)])
        state = make_state(api)
        state.board()

        board = state.board(refresh=True)

        self.assertEqual(api.requests, [None, 101])
        self.assertEqual(board["mode"], "delta")
        self.assertEqual(board["changed"], 1)
        match = next(m for m in board["matches"] if m["id"] == 1)
        self.assertEqual(match["ml"]["home"]["odds"], 2.30)
        self.assertEqual(match["prev"]["home"], 2.45)
        self.assertEqual(match["open"]["home"], 2.45)
        self.assertEqual(match["changedAt"], board["fetchedAt"])
        # partial delta keeps the markets it did not resend
        self.assertIsNotNone(match["ou"])
        self.assertEqual(len(board["matches"]), 2)

    def test_full_reload_ignores_cursor(self):
        api = FakeAPI([event(1)])
        state = make_state(api)
        state.board()
        state.board(full=True)
        self.assertEqual(api.requests, [None, None])

    def test_match_detail_periods(self):
        state = make_state(FakeAPI([event(1)]))
        detail = state.match("1")

        self.assertEqual([p["key"] for p in detail["periods"]], ["ft", "ht"])
        self.assertIsNotNone(detail["periods"][0]["ml"])
        self.assertIsNone(detail["periods"][1]["ml"])  # fixture has no first-half prices
        with self.assertRaises(LookupError):
            state.match("999")


class ReversedPairTests(unittest.TestCase):
    """MerkurXtip lists some games (US college) with the teams the other way round than Pinnacle."""

    def test_swap_sides_turns_prices_to_pinnacle_order(self):
        out = bb.swap_sides({"ml": {"home": 4.4, "away": 1.17}, "spreads": {-10.5: {"home": 1.82, "away": 1.9}},
                             "totals": {164.5: {"over": 1.85, "under": 1.9}},
                             "home": {80.5: {"over": 1.8}}, "away": {}, "main": {"spreads": -10.5, "totals": 164.5}})
        self.assertEqual(out["ml"], {"home": 1.17, "away": 4.4})
        self.assertEqual(out["spreads"], {10.5: {"home": 1.9, "away": 1.82}})
        self.assertEqual(out["totals"], {164.5: {"over": 1.85, "under": 1.9}})
        self.assertEqual((out["home"], out["away"]), ({}, {80.5: {"over": 1.8}}))
        self.assertEqual(out["main"], {"spreads": 10.5, "totals": 164.5})

    def test_game_listed_in_the_other_order_pairs_swapped(self):
        event = {"event_id": 5, "league_id": 1, "home": "Murray State", "away": "Tennessee State",
                 "starts": "2026-11-02T17:30:00Z"}
        ts = int(common.parse_time(event["starts"]).timestamp() * 1000)
        row = {"id": 9, "leagueId": 77, "home": "Tennessee State", "away": "Murray State", "kickOffTime": ts}
        pairs = bb.pair_events([event], [row], {77: 1})
        hit, score = pairs["5"]
        self.assertTrue(hit.get(bb.SWAPPED))
        self.assertEqual(score, 1.0)

    def test_same_order_is_not_swapped(self):
        event = {"event_id": 5, "league_id": 1, "home": "Murray State", "away": "Tennessee State",
                 "starts": "2026-11-02T17:30:00Z"}
        ts = int(common.parse_time(event["starts"]).timestamp() * 1000)
        row = {"id": 9, "leagueId": 77, "home": "Murray State", "away": "Tennessee State", "kickOffTime": ts}
        self.assertFalse(bb.pair_events([event], [row], {77: 1})["5"][0].get(bb.SWAPPED))


class SuspendedTests(unittest.TestCase):
    def state(self):
        return common.SnapshotState(mock.Mock(), lambda: "k")

    def priced(self, **kw):
        return {"event_id": 1, "home": "A", "away": "B", "starts": "2999-01-01T00:00:00Z", "league_id": 7,
                "periods": {"num_0": {"money_line": {"home": 2.0, "draw": 3.0, "away": 4.0}}}, **kw}

    def test_has_prices_ignores_nulled_markets(self):
        self.assertTrue(common.has_prices(self.priced()))
        self.assertFalse(common.has_prices(self.priced(periods={"num_0": {"money_line": {"home": None}}})))
        self.assertFalse(common.has_prices(self.priced(is_have_odds=False)))

    def test_event_dropped_from_full_snapshot_is_suspended_until_priced_again(self):
        st = self.state()
        st.track_suspended({"1": self.priced()}, {}, True, "t1")
        items = st.suspended_items()
        self.assertEqual([i["id"] for i in items], ["1"])
        self.assertEqual(items[0]["ml"], {"home": 2.0, "draw": 3.0, "away": 4.0})
        st.track_suspended({}, {"1": self.priced()}, False, "t2")
        self.assertEqual(st.suspended_items(), [])

    def test_delta_without_prices_suspends_but_missing_in_delta_does_not(self):
        st = self.state()
        st.track_suspended({"1": self.priced()}, {}, False, "t")
        self.assertEqual(st.suspended_items(), [])
        bare = self.priced(periods={"num_0": {"money_line": {"home": None, "draw": None, "away": None}}})
        st.track_suspended({"1": self.priced()}, {"1": bare}, False, "t")
        self.assertEqual(len(st.suspended_items()), 1)


class ClientTests(unittest.TestCase):
    def test_devig_power_sums_to_one_and_removes_margin(self):
        odds = {"home": 2.45, "draw": 3.30, "away": 2.90}
        probs = pw.devig(odds)
        self.assertAlmostEqual(sum(probs.values()), 1.0, places=6)
        for side, p in probs.items():
            self.assertGreater(1 / p, odds[side])
        _, margin = pw.fair_odds(odds)
        self.assertAlmostEqual(margin, (1 / 2.45 + 1 / 3.30 + 1 / 2.90 - 1) * 100, places=2)

    def test_lines_are_sorted_and_main_line_marked(self):
        totals = pw.build_lines(kit_event(), "totals", ("over", "under"), "points")
        self.assertEqual([row["line"] for row in totals], [2.5])  # 3.0 is a whole line: dropped
        self.assertEqual([bool(row.get("main")) for row in totals], [True])
        spreads = pw.build_lines(kit_event(), "spreads", ("home", "away"), "hdp")
        self.assertEqual([row["line"] for row in spreads], [-0.5, 0.0])
        self.assertTrue(spreads[1]["main"])

    def test_only_half_lines_and_level_handicap_are_allowed(self):
        for line in (0.5, 1.5, 2.5, -1.5, 3.5):
            self.assertTrue(pw.allowed_line(line, "totals"))
            self.assertTrue(pw.allowed_line(line, "spreads"))
        for line in (2.0, 2.25, 2.75, 3.0, -0.25, -1.0, -0.75):
            self.assertFalse(pw.allowed_line(line, "totals"))
            self.assertFalse(pw.allowed_line(line, "spreads"))
        self.assertTrue(pw.allowed_line(0.0, "spreads"))
        self.assertFalse(pw.allowed_line(0.0, "totals"))

    def test_quarter_and_whole_lines_are_dropped_everywhere(self):
        spreads = {
            "0": {"hdp": 0.0, "home": 1.80, "away": 2.10},
            "-0.25": {"hdp": -0.25, "home": 2.00, "away": 1.90},
            "-0.5": {"hdp": -0.5, "home": 2.30, "away": 1.65},
            "-1": {"hdp": -1.0, "home": 3.30, "away": 1.35},
        }
        totals = {
            "2.25": {"points": 2.25, "over": 1.80, "under": 2.05},
            "2.5": {"points": 2.5, "over": 2.00, "under": 1.88},
            "2.75": {"points": 2.75, "over": 2.20, "under": 1.72},
        }
        pin = event(1, periods={"num_0": {"money_line": {"home": 2.45, "draw": 3.30, "away": 2.90},
                                          "spreads": spreads, "totals": totals}})
        state = make_state(FakeAPI([pin]))
        match = state.board()["matches"][0]
        self.assertEqual(match["ou"]["line"], 2.5)
        detail = state.match("1")["periods"][0]
        self.assertEqual([r["line"] for r in detail["spreads"]], [-0.5, 0.0])
        self.assertEqual([r["line"] for r in detail["totals"]], [2.5])

    def test_specials_and_alt_units_are_not_fixtures(self):
        self.assertTrue(pw.is_main_fixture(kit_event()))
        self.assertFalse(pw.is_main_fixture(kit_event(parent_id=1)))
        self.assertFalse(pw.is_main_fixture(kit_event(units="Corners")))

    def test_api_key_is_masked_in_errors(self):
        api = pw.PinnWireAPI("secret-key")
        self.assertEqual(api._mask("bad secret-key here"), "bad *** here")


class MerkurDecodeTests(unittest.TestCase):
    def test_ranges_become_totals_and_params_give_lines(self):
        row = merkur_row(**{"21": 3.6, "242": 1.25, "4": 3.1, "5": 2.1, "6": 3.5, "238": 1.3, "239": 3.4})
        row["params"].update(overUnder="2.75")
        row["odds"].update({"227": 2.0, "228": 1.8})
        decoded = mx.markets(row)

        self.assertEqual(decoded[0]["ml"], {"home": 2.5, "draw": 3.2, "away": 2.8})
        self.assertEqual(decoded[0]["totals"][2.5], {"over": 1.85, "under": 1.90})
        self.assertEqual(decoded[0]["totals"][1.5], {"over": 1.25, "under": 3.6})
        self.assertEqual(decoded[0]["totals"][2.75], {"over": 2.0, "under": 1.8})
        self.assertEqual(decoded[0]["spreads"], {-0.5: {"home": 1.70, "away": 2.05}})
        self.assertEqual(decoded[0]["teamTotals"]["home"][0.5], {"over": 1.3, "under": 3.4})
        self.assertEqual(decoded[1]["ml"], {"home": 3.1, "draw": 2.1, "away": 3.5})

    def test_half_goal_handicaps_from_1x2_and_double_chance(self):
        row = merkur_row(**{"7": 1.57, "9": 1.55, "4": 2.72, "399": 1.40, "397": 1.50, "6": 2.68})
        decoded = mx.markets(row)
        ft, ht = decoded[0], decoded[1]

        # AH -0.5: "1" against "X2";  AH +0.5: "1X" against "2"
        self.assertEqual(ft["spreads"][-0.5], {"home": 1.70, "away": 2.05})  # direct hd2w wins on its own line
        self.assertEqual(ft["spreads"][0.5], {"home": 1.57, "away": 2.80})
        self.assertIn(0.5, ft["derived"])
        self.assertNotIn(-0.5, ft["derived"])
        self.assertEqual(ht["spreads"][-0.5], {"home": 2.72, "away": 1.40})
        self.assertEqual(ht["spreads"][0.5], {"home": 1.50, "away": 2.68})
        self.assertEqual(ht["derived"], {-0.5, 0.5})

    def test_derived_handicap_needs_both_prices(self):
        # AH +0.5 is "1X" (7) against "2" (3): with both priced it is a pair ...
        decoded = mx.markets(merkur_row(**{"7": 1.57}))
        self.assertEqual(decoded[0]["spreads"][0.5], {"home": 1.57, "away": 2.80})
        # ... and without the "2" price the line is dropped instead of being half-filled
        decoded = mx.markets(merkur_row(**{"7": 1.57, "3": None}))
        self.assertNotIn(0.5, decoded[0]["spreads"])

    def test_european_handicap_gives_one_side_of_two_asian_lines(self):
        # h = -1: H1 = home by 2+ = AH -1.5 home; H2 = X2 = AH -0.5 away (away +0.5)
        row = merkur_row(**{"201": 2.27, "203": 2.43})
        row["params"].update(hd2="-1")
        spreads = mx.markets(row)[0]["spreads"]
        self.assertEqual(spreads[-1.5], {"home": 2.27})
        self.assertEqual(spreads[-0.5]["away"], 2.05)   # direct hd2w price is kept, not the derived 2.43

    def test_european_handicap_lines_for_each_sign(self):
        row = merkur_row(**{"421": 4.0, "423": 1.5, "424": 1.25, "426": 6.7})
        row["params"].update(hd2w="-5.5", handicap2="-2", handicap3="1")
        spreads = mx.markets(row)[0]["spreads"]
        self.assertEqual(spreads[-2.5], {"home": 4.0})   # h=-2: home by 3+
        self.assertEqual(spreads[-1.5], {"away": 1.5})   # h=-2: away +1.5
        self.assertEqual(spreads[0.5]["home"], 1.25)     # h=+1: home +0.5 (1X)
        self.assertEqual(spreads[1.5], {"away": 6.7})    # h=+1: away -1.5

    def test_both_sides_from_different_european_handicaps_make_a_derived_line(self):
        row = merkur_row(**{"201": 2.27, "203": 2.43, "421": 4.0, "423": 1.5})
        row["params"] = {"hd2": "-1", "handicap2": "-2"}  # no direct hd2w
        decoded = mx.markets(row)[0]
        self.assertEqual(decoded["spreads"][-1.5], {"home": 2.27, "away": 1.5})
        self.assertIn(-1.5, decoded["derived"])

    def test_team_goal_and_half_time_total_lines(self):
        row = merkur_row(**{"276": 2.6, "551": 1.45, "555": 5.0, "553": 1.17, "277": 2.5, "552": 1.5,
                            "274": 3.6, "817": 1.3, "275": 3.65, "821": 1.28, "209": 6.0, "472": 1.12,
                            "207": 1.1, "267": 6.0})
        decoded = mx.markets(row)
        self.assertEqual(decoded[0]["teamTotals"]["home"][2.5], {"over": 2.6, "under": 1.45})
        self.assertEqual(decoded[0]["teamTotals"]["home"][3.5], {"over": 5.0, "under": 1.17})
        self.assertEqual(decoded[0]["teamTotals"]["away"][2.5], {"over": 2.5, "under": 1.5})
        self.assertEqual(decoded[1]["teamTotals"]["home"][1.5], {"over": 3.6, "under": 1.3})
        self.assertEqual(decoded[1]["teamTotals"]["away"][1.5], {"over": 3.65, "under": 1.28})
        self.assertEqual(decoded[1]["totals"][2.5], {"over": 6.0, "under": 1.12})

    def test_first_half_team_goals(self):
        row = merkur_row(**{"307": 1.49, "337": 2.50, "308": 2.30, "338": 1.52})
        decoded = mx.markets(row)[1]["teamTotals"]
        self.assertEqual(decoded["home"], {0.5: {"over": 1.49, "under": 2.50}})
        self.assertEqual(decoded["away"], {0.5: {"over": 2.30, "under": 1.52}})

    def test_market_needs_every_side(self):
        decoded = mx.markets(merkur_row(**{"3": None}))
        self.assertIsNone(decoded[0]["ml"])


class MerkurPairingTests(unittest.TestCase):
    def test_name_scores(self):
        self.assertEqual(mx.name_score("Paris Saint-Germain", "PSG"), 1.0)
        self.assertEqual(mx.name_score("Atletico Madrid", "Atl. Madrid"), 1.0)
        self.assertEqual(mx.name_score("Borussia Dortmund", "Dortmund"), 1.0)
        self.assertEqual(mx.name_score("AGF", "Aarhus"), 1.0)
        self.assertEqual(mx.name_score("Olympiakos", "Olympiacos"), 1.0)
        self.assertEqual(mx.name_score("The New Saints", "TNS"), 1.0)
        self.assertEqual(mx.name_score("Chelsea", "Arsenal"), 0.0)
        self.assertEqual(mx.name_score("Colchester United", "Colchester U21"), 1.0)
        self.assertEqual(mx.name_score("Queens Park Rangers", "QPR U21"), 1.0)
        self.assertEqual(mx.name_score("Ethiopian Medhin", "Ethiopian Insurance"), 1.0)
        self.assertEqual(mx.name_score("BC Khimki", "Khimki M."), 1.0)
        self.assertEqual(mx.name_score("Chelyabinsk", "Chelbasket"), 1.0)
        self.assertEqual(mx.name_score("Mekelakeya", "Defence Force"), 1.0)
        self.assertEqual(mx.name_score("Union Saint-Gilloise II", "Union SG 2"), 1.0)
        self.assertEqual(mx.name_score("RAEC Mons", "Renaissance Mons"), 1.0)
        self.assertEqual(mx.name_score("Diosgyori VTK", "DVTK"), 1.0)
        self.assertEqual(dash.other_score("Colchester United", "Colchester U21"), 0.0)

    def test_pair_is_one_to_one_within_competition_and_window(self):
        pin = [
            {"id": "a", "comp": 1, "home": "Manchester United", "away": "Chelsea", "ts": 0},
            {"id": "b", "comp": 1, "home": "Manchester City", "away": "Arsenal", "ts": 0},
            {"id": "c", "comp": 2, "home": "Inter", "away": "Milan", "ts": 0},
        ]
        mer = [
            {"id": 1, "comp": 1, "home": "Manchester Utd", "away": "Chelsea", "ts": 60 * 60000},
            {"id": 2, "comp": 1, "home": "Manchester City", "away": "Arsenal", "ts": 0},
            {"id": 3, "comp": 1, "home": "Inter", "away": "Milan", "ts": 0},  # wrong competition
            {"id": 4, "comp": 2, "home": "Inter", "away": "Milan", "ts": 5 * 3600000},  # too late
        ]
        pairs = mx.pair(pin, mer)
        self.assertEqual({k: v[0]["id"] for k, v in pairs.items()}, {"a": 1, "b": 2})


class ComparisonTests(unittest.TestCase):
    def test_board_compares_against_fair_odds(self):
        state = make_state(FakeAPI([event(1)]), [merkur_row()])
        match = state.board()["matches"][0]
        merkur = match["merkur"]

        self.assertEqual(merkur["id"], 900)
        self.assertEqual(merkur["kickoffDiff"], 0)
        fair_home = match["ml"]["home"]["fair"]
        self.assertAlmostEqual(merkur["ml"]["home"]["ev"], 2.50 / fair_home - 1, places=3)
        self.assertNotIn("totals", merkur)
        goals = match["goals"]
        self.assertEqual(goals["line"], 2.5)
        self.assertEqual(goals["merkur"], {"over": 1.85, "under": 1.90})
        self.assertEqual(goals["pinnacle"], {"over": 1.90, "under": 1.98})
        self.assertAlmostEqual(goals["ev"]["over"], 1.85 / goals["fair"]["over"] - 1, places=3)
        self.assertIsNotNone(merkur["best"])

    def test_value_list_has_every_outcome_above_pinnacle(self):
        # Pinnacle: 1X2 2.45/3.30/2.90, totals 2.5 1.90/1.98, AH -0.5 2.45/1.58
        row = merkur_row(**{"1": 2.55, "2": 3.10, "3": 2.95, "24": 1.95, "22": 1.85, "53877": 2.30, "53878": 1.60})
        board = make_state(FakeAPI([event(1)]), [row]).board()
        values = board["values"]

        found = {(v["group"], v["line"], v["key"]) for v in values}
        self.assertEqual(found, {("1X2", None, "home"), ("1X2", None, "away"),
                                 ("Ukupno golova", 2.5, "over"), ("Hendikep", -0.5, "away")})
        self.assertEqual([v["ev"] for v in values], sorted((v["ev"] for v in values), reverse=True))
        handicap = next(v for v in values if v["group"] == "Hendikep")
        self.assertEqual(handicap["label"], "Villarreal")
        home = next(v for v in values if v["key"] == "home" and v["group"] == "1X2")
        self.assertAlmostEqual(home["overPinnacle"], 2.55 / 2.45 - 1, places=4)
        self.assertNotIn("rows", board["matches"][0]["merkur"])

    def test_goal_line_closest_to_pinnacle_main_line(self):
        totals = {
            "2.5": {"points": 2.5, "over": 1.70, "under": 2.20},
            "2.75": {"points": 2.75, "over": 1.95, "under": 1.95},  # quarter line: never used
            "3.5": {"points": 3.5, "over": 2.60, "under": 1.50},
        }
        pin = event(1, periods={"num_0": {"money_line": {"home": 2.45, "draw": 3.30, "away": 2.90},
                                          "totals": totals}})
        row = merkur_row(**{"25": 2.50, "219": 1.48})  # MX has 2.5 and 3.5
        match = make_state(FakeAPI([pin]), [row]).board()["matches"][0]
        self.assertEqual(match["ou"]["line"], 2.5)  # main among half lines: closest to even
        self.assertEqual(match["goals"]["line"], 2.5)

    def test_unpaired_match_shows_pinnacle_main_goal_line(self):
        match = make_state(FakeAPI([event(1)])).board()["matches"][0]
        self.assertEqual(match["goals"]["line"], 2.5)
        self.assertIsNone(match["goals"]["merkur"])
        self.assertEqual(match["goals"]["pinnacle"], {"over": 1.90, "under": 1.98})

    def test_goal_line_movement_is_tracked(self):
        rows = [merkur_row()]
        state = make_state(FakeAPI([event(1)]), rows)
        state.board()
        rows[0]["odds"]["24"] = 1.80
        state.merkur.at = 0
        board = state.board(refresh=True)
        goals = board["matches"][0]["goals"]
        self.assertEqual(goals["mxPrev"], {"over": 1.85, "under": 1.90})
        self.assertEqual(goals["mxChangedAt"], board["merkur"]["fetchedAt"])
        self.assertIsNone(goals["pinPrev"])

    def test_derived_and_partial_handicaps_are_compared_without_margin(self):
        # Pinnacle AH -0.5 2.45/1.58, AH +0.5 and AH -1.5; Merkur: -0.5 from "1"/"X2", -1.5 home from euro h=-1
        spreads = {
            "-0.5": {"hdp": -0.5, "home": 2.45, "away": 1.58},
            "0.5": {"hdp": 0.5, "home": 1.40, "away": 3.10},
            "-1.5": {"hdp": -1.5, "home": 4.00, "away": 1.27},
        }
        pin = event(1, periods={"num_0": {"money_line": {"home": 2.45, "draw": 3.30, "away": 2.90},
                                          "spreads": spreads}})
        row = merkur_row(**{"1": 2.55, "9": 1.60, "7": 1.45, "3": 3.00, "201": 4.20})
        row["params"] = {"hd2": "-1"}  # no direct hd2w
        state = make_state(FakeAPI([pin]), [row])
        state.board()
        rows = {r["line"]: r for r in state.match("1")["merkur"]["periods"]["ft"] if r["group"] == "Hendikep"}

        self.assertEqual(sorted(rows), [-1.5, -0.5, 0.5])
        for line in rows:
            self.assertTrue(rows[line]["derived"])
            self.assertIsNone(rows[line]["merkurMargin"])
            self.assertIsNotNone(rows[line]["pinnacleMargin"])
        # AH -0.5: both sides ("1" 2.55 vs home 2.45, "X2" 1.60 vs away 1.58)
        self.assertEqual([(o["key"], o["merkur"], o["pinnacle"]) for o in rows[-0.5]["outcomes"]],
                         [("home", 2.55, 2.45), ("away", 1.60, 1.58)])
        # AH -1.5: only the home side, from the European handicap
        self.assertEqual([(o["key"], o["merkur"]) for o in rows[-1.5]["outcomes"]], [("home", 4.20)])
        fair_home = rows[-1.5]["outcomes"][0]["fair"]
        self.assertAlmostEqual(rows[-1.5]["outcomes"][0]["ev"], 4.20 / fair_home - 1, places=3)

    def test_direct_handicap_keeps_its_margin(self):
        state = make_state(FakeAPI([event(1)]), [merkur_row()])
        state.board()
        row = next(r for r in state.match("1")["merkur"]["periods"]["ft"] if r["group"] == "Hendikep")
        self.assertFalse(row["derived"])
        self.assertAlmostEqual(row["merkurMargin"], (1 / 1.70 + 1 / 2.05 - 1) * 100, places=2)

    def test_value_list_flags_derived_rows_and_keeps_one_sided_outcomes(self):
        spreads = {"-1.5": {"hdp": -1.5, "home": 4.00, "away": 1.27}}
        pin = event(1, periods={"num_0": {"money_line": {"home": 2.45, "draw": 3.30, "away": 2.90},
                                          "spreads": spreads}})
        row = merkur_row(**{"201": 4.30})
        row["params"] = {"hd2": "-1"}
        values = make_state(FakeAPI([pin]), [row]).board()["values"]
        handicap = [v for v in values if v["group"] == "Hendikep"]
        self.assertEqual(len(handicap), 1)
        self.assertTrue(handicap[0]["derived"])
        self.assertIsNone(handicap[0]["merkurMargin"])
        self.assertEqual((handicap[0]["line"], handicap[0]["key"], handicap[0]["merkur"]), (-1.5, "home", 4.30))

    def test_draw_no_bet_is_compared_with_level_handicap(self):
        # Pinnacle AH 0.0: 1.82 / 2.06; MerkurXtip "X vraća ulog" W1/W2 (264/265)
        row = merkur_row(**{"264": 1.85, "265": 2.00})
        state = make_state(FakeAPI([event(1)]), [row])
        state.board()
        rows = state.match("1")["merkur"]["periods"]["ft"]
        dnb = next(r for r in rows if r["group"] == "Hendikep" and r["line"] == 0.0)
        self.assertEqual([(o["key"], o["merkur"], o["pinnacle"]) for o in dnb["outcomes"]],
                         [("home", 1.85, 1.82), ("away", 2.00, 2.06)])
        self.assertEqual(mx.markets(row)[0]["spreads"][0.0], {"home": 1.85, "away": 2.00})

    def test_detail_lists_compared_markets_and_skips_lines_pinnacle_lacks(self):
        state = make_state(FakeAPI([event(1)]), [merkur_row()])
        state.board()
        detail = state.match("1")["merkur"]

        groups = [(r["group"], r["line"]) for r in detail["periods"]["ft"]]
        self.assertEqual(groups, [("1X2", None), ("Ukupno golova", 2.5), ("Hendikep", -0.5)])
        self.assertEqual(detail["periods"]["ht"], [])

    def test_unpaired_match_and_merkur_failure(self):
        class Down(FakeMerkurAPI):
            def offer(self):
                raise RuntimeError("MerkurXtip nije dostupan")

        state = make_state(FakeAPI([event(1)]))
        state.merkur.api = Down()
        board = state.board()
        self.assertIsNone(board["matches"][0]["merkur"])
        self.assertIn("nije dostupan", board["merkur"]["error"])
        self.assertIsNone(state.match("1")["merkur"])

    def test_merkur_price_change_is_tracked(self):
        rows = [merkur_row()]
        state = make_state(FakeAPI([event(1)]), rows)
        first = state.board()["matches"][0]["merkur"]
        self.assertIsNone(first["prev"])

        rows[0]["odds"]["1"] = 2.40
        state.merkur.at = 0  # expire the offer cache
        board = state.board(refresh=True)
        merkur = board["matches"][0]["merkur"]
        self.assertEqual(merkur["prev"]["home"], 2.50)
        self.assertEqual(merkur["ml"]["home"]["odds"], 2.40)
        self.assertEqual(merkur["changedAt"], board["merkur"]["fetchedAt"])

    def test_board_has_league_name_and_main_line_limit(self):
        match = make_state(FakeAPI([event(1)])).board()["matches"][0]
        self.assertEqual(match["leagueName"], "Spain - La Liga")
        self.assertEqual(match["ah"]["max"], 500)

    def test_kickoff_difference_is_reported(self):
        state = make_state(FakeAPI([event(1)]), [merkur_row(ts=KICKOFF_MS + 3600000)])
        self.assertEqual(state.board()["matches"][0]["merkur"]["kickoffDiff"], 60)


class MergeTests(unittest.TestCase):
    def test_merge_replaces_markets_per_period(self):
        old = event(1)
        new = {"event_id": 1, "periods": {"num_0": {"totals": {}}}}
        merged = common.merge_event(old, new)
        self.assertEqual(merged["periods"]["num_0"]["totals"], {})
        self.assertIn("money_line", merged["periods"]["num_0"])
        self.assertEqual(merged["home"], "Alaves")


class BasketballTests(unittest.TestCase):
    ROW = {
        "id": 1, "home": "Orlando", "away": "Atlanta", "leagueId": 2314399, "kickOffTime": 1_900_000_000_000,
        "odds": {"50291": 1.67, "50293": 2.2, "50430": 2.08, "50431": 1.77, "50445": 1.9, "50444": 1.9,
                 "50432": 2.48, "50433": 1.52},
        "params": {"handicapOvertime": "-4.5", "handicapOvertime2": "-7.5", "overUnderOvertime": "235.5"},
    }

    @staticmethod
    def event():
        return {"event_id": 7, "league_id": 487, "league_name": "NBA", "home": "Orlando Magic",
                "away": "Atlanta Hawks", "starts": "2030-03-17T17:46:40Z", "units": "Regular", "parent_id": None,
                "periods": {"num_0": {
                    "money_line": {"home": 1.7, "away": 2.2},
                    "spreads": {"-4.5": {"hdp": -4.5, "home": 2.0, "away": 1.85},
                                "-7.5": {"hdp": -7.5, "home": 2.4, "away": 1.58}},
                    "totals": {"235.5": {"points": 235.5, "over": 1.85, "under": 1.95}},
                }}}

    def test_merkur_markets_use_line_params(self):
        decoded = bb.merkur_markets(self.ROW)
        self.assertEqual(decoded["ml"], {"home": 1.67, "away": 2.2})
        self.assertEqual(decoded["spreads"], {-4.5: {"home": 2.08, "away": 1.77}, -7.5: {"home": 2.48, "away": 1.52}})
        self.assertEqual(decoded["totals"], {235.5: {"over": 1.9, "under": 1.9}})

    def test_match_compares_shared_lines_only(self):
        match, values = bb.shape_match(self.event(), (self.ROW, 1.0))
        groups = {(r["group"], r["line"]) for r in match["rows"]}
        self.assertEqual(groups, {("Pobednik", None), ("Hendikep", -4.5), ("Hendikep", -7.5),
                                  ("Ukupno poena", 235.5)})
        self.assertEqual(match["total"]["line"], 235.5)
        self.assertEqual(match["spread"]["line"], -4.5)  # closest to even Pinnacle prices
        self.assertTrue(all(v["merkur"] > v["pinnacle"] for v in values))

    def test_match_without_merkur_keeps_pinnacle_main_lines(self):
        match, values = bb.shape_match(self.event(), None)
        self.assertIsNone(match["merkur"])
        self.assertIsNone(match["total"]["merkur"])
        self.assertEqual(values, [])

    def test_pairs_by_merkur_league_id(self):
        pairs = bb.pair_events([self.event()], [self.ROW])
        self.assertEqual(pairs["7"][0]["id"], 1)


class TennisTests(unittest.TestCase):
    ROW = {
        "id": 5, "home": "S. Wawrinka", "away": "M. Landaluce", "kickOffTime": 1_900_000_000_000,
        "odds": {"1": 2.4, "3": 1.5, "50510": 2.25, "50511": 1.55, "261": 2.35, "260": 1.48,
                 "50538": 1.57, "50539": 2.2, "251": 1.72, "253": 1.97, "256": 2.0, "254": 1.7,
                 "259": 1.8, "257": 2.0, "50941": 1.75, "50940": 1.92,
                 "50271": 1.2, "50272": 1.4},
        "params": {"hd2": "1.5", "handicapGames": "3.5", "overUnderGames": "22.5",
                   "overUnderGamesFirstSet": "9.5", "homeOverUnderGames": "11.5"},
    }

    @staticmethod
    def main_event():
        return {"event_id": 7, "league_id": 199241, "league_name": "ATP Lyon - R16", "home": "Stan Wawrinka",
                "away": "Martin Landaluce", "starts": "2030-03-17T17:46:40Z", "units": "Sets", "parent_id": None,
                "periods": {
                    "num_0": {"money_line": {"home": 2.6, "away": 1.45},
                              "spreads": {"1.5": {"hdp": 1.5, "home": 1.6, "away": 2.3},
                                          "-1.5": {"hdp": -1.5, "home": 4.4, "away": 1.2}},
                              "totals": {"2.5": {"points": 2.5, "over": 2.2, "under": 1.65}}},
                    "num_1": {"money_line": {"home": 2.4, "away": 1.55}}}}

    @staticmethod
    def games_event():
        return {"event_id": 8, "league_id": 199241, "league_name": "ATP Lyon - R16",
                "home": "Stan Wawrinka (Games)", "away": "Martin Landaluce (Games)",
                "starts": "2030-03-17T17:46:41Z", "units": "Games", "parent_id": 7,
                "periods": {
                    "num_0": {"spreads": {"3.5": {"hdp": 3.5, "home": 1.8, "away": 2.05},
                                          "4.5": {"hdp": 4.5, "home": 1.6, "away": 2.4}},
                              "totals": {"22.5": {"points": 22.5, "over": 1.95, "under": 1.85},
                                         "22": {"points": 22, "over": 1.9, "under": 1.9}},
                              "team_totals": {"home": {"11.5": {"points": 11.5, "over": 1.9, "under": 1.9}},
                                              "away": {}}},
                    "num_1": {"totals": {"9.5": {"points": 9.5, "over": 1.85, "under": 1.95}}}}}

    def merged(self):
        return tennis.TennisState.incoming(None, {"events": [self.games_event(), self.main_event()]})[0]

    def test_games_event_is_folded_into_its_main_event(self):
        events = tennis.TennisState.incoming(None, {"events": [self.games_event(), self.main_event()]})
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_id"], 7)
        self.assertEqual(events[0]["home"], "Stan Wawrinka")
        self.assertIn("num_0", events[0]["games"])

    def test_games_event_alone_is_not_a_complete_match(self):
        events = tennis.TennisState.incoming(None, {"events": [self.games_event()]})
        self.assertFalse(tennis.TennisState.complete(None, events[0]))

    def test_delta_merges_games_markets_per_period(self):
        delta = {"event_id": 7, "games": {"num_0": {"totals": {"23.5": {"points": 23.5, "over": 2.1, "under": 1.75}}}}}
        out = tennis.merge_event(self.merged(), delta)
        self.assertEqual(set(out["games"]["num_0"]["totals"]), {"23.5"})
        self.assertIn("num_1", out["games"])
        self.assertEqual(out["home"], "Stan Wawrinka")

    def test_merkur_markets_use_line_params_and_fixed_set_totals(self):
        decoded = tennis.merkur_markets(self.ROW)
        self.assertEqual(decoded["ml"], {"home": 2.4, "away": 1.5})
        self.assertEqual(decoded["setspreads"], {1.5: {"home": 1.57, "away": 2.2}})
        self.assertEqual(decoded["settotals"], {2.5: {"over": 2.35, "under": 1.48}})
        self.assertEqual(decoded["spreads"], {3.5: {"home": 1.72, "away": 1.97}})
        self.assertEqual(decoded["totals"], {22.5: {"over": 2.0, "under": 1.7}})
        self.assertEqual(decoded["home"], {11.5: {"over": 1.75, "under": 1.92}})
        self.assertEqual(decoded["away"], {})
        first_set = tennis.merkur_markets(self.ROW, "s1")
        self.assertEqual(first_set["ml"], {"home": 2.25, "away": 1.55})
        self.assertEqual(first_set["totals"], {9.5: {"over": 1.8, "under": 2.0}})

    def test_player_wins_a_set_is_the_set_handicap_plus_one_and_a_half(self):
        pin = tennis.pinnacle_markets(self.merged())
        spreads = pin["setspreads"]
        self.assertEqual(pin["setwin"]["home"], {"yes": spreads[1.5]["home"], "no": spreads[1.5]["away"]})
        self.assertEqual(pin["setwin"]["away"], {"yes": spreads[-1.5]["away"], "no": spreads[-1.5]["home"]})
        self.assertEqual(tennis.merkur_markets(self.ROW)["setwin"], {"home": {"yes": 1.2}, "away": {"yes": 1.4}})
        swapped = tennis.merkur_markets({**self.ROW, "pinSwapped": True})["setwin"]
        self.assertEqual(swapped, {"home": {"yes": 1.4}, "away": {"yes": 1.2}})
        self.assertEqual(tennis.set_win({1.5: {"home": 1.2, "away": 4.0}, 2.5: {"home": 1.1, "away": 7.0}},
                                        {3.5: {}}), {"home": {"yes": 1.1, "no": 7.0}})

    def test_pinnacle_markets_read_sets_and_games(self):
        pin = tennis.pinnacle_markets(self.merged())
        self.assertEqual(set(pin["setspreads"]), {1.5, -1.5})
        self.assertEqual(set(pin["settotals"]), {2.5})
        self.assertEqual(set(pin["spreads"]), {3.5, 4.5})
        self.assertEqual(set(pin["totals"]), {22.5})  # the whole-game line 22 is dropped
        self.assertEqual(set(pin["home"]), {11.5})
        self.assertEqual(set(tennis.pinnacle_markets(self.merged(), "s1")["totals"]), {9.5})

    def test_match_compares_shared_lines_in_every_period(self):
        match, values = tennis.shape_match(self.merged(), (self.ROW, 1.0))
        groups = {(r["group"], r["line"]) for r in match["rows"]}
        self.assertEqual(groups, {("Pobednik", None), ("Hendikep setova", 1.5), ("Ukupno setova", 2.5),
                                  ("Hendikep gemova", 3.5), ("Ukupno gemova", 22.5), ("Gemovi igrač 1", 11.5),
                                  ("Igrač 1 osvaja set", None), ("Igrač 2 osvaja set", None)})
        self.assertEqual({(r["group"], r["line"]) for r in match["periods"]["s1"]},
                         {("Pobednik", None), ("Ukupno gemova", 9.5)})
        self.assertEqual(match["leagueId"], "ATP Lyon")
        self.assertEqual(match["spread"]["line"], 3.5)
        self.assertEqual(match["total"]["line"], 22.5)
        self.assertTrue(all(v["merkur"] > v["pinnacle"] for v in values))
        self.assertIn("1. set", {v["periodLabel"] for v in values})

    def test_match_without_merkur_keeps_pinnacle_main_lines(self):
        match, values = tennis.shape_match(self.merged(), None)
        self.assertIsNone(match["merkur"])
        self.assertEqual(match["total"]["line"], 22.5)
        self.assertIsNone(match["total"]["merkur"])
        self.assertEqual(values, [])

    def test_player_names_pair_by_surname_and_initial(self):
        self.assertEqual(tennis.player_score("Katarzyna Kawa", "K. Kawa"), 1.0)
        self.assertEqual(tennis.player_score("Stan Wawrinka", "Wawrinka S."), 1.0)
        self.assertEqual(tennis.player_score("Katarzyna Kawa", "K. Jacquet"), 0.0)  # an initial matches only once
        self.assertEqual(tennis.player_score("Katarzyna Kawa", "J. Kawa"), 0.0)
        self.assertEqual(tennis.player_score("Guido Andreozzi / Manuel Guinard", "Andreozzi G./Guinard M."), 1.0)

    def test_pairs_by_players_even_when_kickoff_is_hours_off(self):
        row = {**self.ROW, "kickOffTime": 1_900_000_000_000 + 5 * 3600_000}
        pairs = tennis.pair_events([self.merged()], [row])
        self.assertEqual(pairs["7"][0]["id"], 5)
        other = {**row, "home": "K. Jacquet", "away": "B. Nakashima"}
        self.assertEqual(tennis.pair_events([self.merged()], [other]), {})

    def test_competitions_are_tournaments_grouped_by_category(self):
        state = tennis.TennisState.__new__(tennis.TennisState)
        comps = state.competitions([{"leagueId": "ITF Women Austin"}, {"leagueId": "ATP Lyon"},
                                    {"leagueId": "ATP Lyon"}, {"leagueId": "WTA Osaka"}])
        self.assertEqual([(c["country"], c["name"], c["count"]) for c in comps],
                         [("ATP", "Lyon", 2), ("WTA", "Osaka", 1), ("ITF žene", "Austin", 1)])
        self.assertEqual(tennis.tournament("ATP Lyon - Doubles"), "ATP Lyon")


class HandballTests(unittest.TestCase):
    def test_women_marker_covers_both_sides_and_country_aliases_pair(self):
        # MerkurXtip marks only one team ("Kaunas W") and does not call the league a women's one
        self.assertEqual(handball.women("Kaunas W", "Avarca de Menorca", "CEV"), ("Kaunas W", "Avarca de Menorca W"))
        self.assertEqual(handball.women("TK Kaunas VDU", "Avarca", "CEV Challenge Cup Women"),
                         ("TK Kaunas VDU W", "Avarca W"))
        self.assertEqual(handball.women("Austria", "Turkey", "European Championships"), ("Austria", "Turkey"))
        self.assertEqual(common.other_score("Turkiye", "Turkey"), 1.0)
        self.assertEqual(common.other_score("Bosnia & Herzegovina", "BiH"), 1.0)

    KICK = "2030-03-17T17:00:00Z"
    HB_ROW = {
        "id": 21, "sport": "HB", "home": "Vojvodina", "away": "Metaloplastika", "leagueName": "Super Liga",
        "kickOffTime": 1_900_000_000_000,
        "odds": {"264": 1.13, "265": 4.5, "1": 1.2, "2": 12.0, "3": 5.25, "53877": 1.83, "53878": 1.85,
                 "227": 1.75, "228": 1.9, "229": 1.9, "230": 1.75, "53903": 1.83, "53904": 1.8},
        "params": {"overUnder": "62.5", "hd2w": "-4.5", "overUnderP": "31.5", "hd2wp1": "-2.5"},
    }
    V_ROW = {"id": 22, "sport": "V", "home": "Jaworzno", "away": "Bydgoszcz", "leagueName": "1. Liga",
             "kickOffTime": 1_900_000_000_000, "odds": {"1": 1.6, "3": 2.15, "50882": 1.85, "50884": 1.9},
             "params": {"handicapPoints": "-3.5", "overUnderPoints": "181.5"}}

    @classmethod
    def handball(cls, **extra):
        return {"event_id": 7, "league_id": 222897, "league_name": "Serbia - Superliga", "units": "Regular",
                "home": "RK Vojvodina", "away": "RK Metaloplastika", "starts": cls.KICK,
                "periods": {
                    "num_0": {"money_line": {"home": 1.163, "away": 4.01},
                              "spreads": {"-4.5": {"hdp": -4.5, "home": 1.9, "away": 1.8, "max": 100},
                                          "-4": {"hdp": -4, "home": 1.8, "away": 1.9}},
                              "totals": {"62.5": {"points": 62.5, "over": 1.704, "under": 2.01, "max": 200}}},
                    "num_1": {"money_line": {"home": 1.3, "away": 3.4},
                              "totals": {"31.5": {"points": 31.5, "over": 1.8, "under": 1.95}}}},
                **extra}

    @classmethod
    def volleyball(cls):
        return {"event_id": 8, "league_id": 215953, "league_name": "Poland - Liga 1", "units": "Regular",
                "home": "McKis Energetyk Jaworzno", "away": "BKS Visla Bydgoszcz", "starts": cls.KICK,
                "periods": {"num_0": {"money_line": {"home": 1.7, "away": 2.2},
                                      "spreads": {"-1.5": {"hdp": -1.5, "home": 2.4, "away": 1.55}},
                                      "totals": {"3.5": {"points": 3.5, "over": 2.1, "under": 1.7}}}}}

    def test_kind_tells_handball_from_volleyball_by_the_totals(self):
        self.assertEqual(handball.kind(self.handball()), "HB")
        self.assertEqual(handball.kind(self.volleyball()), "V")
        points = {"periods": {"num_0": {"totals": {"181.5": {"points": 181.5}}}}}
        self.assertEqual(handball.kind(points), "V")
        self.assertIsNone(handball.kind({"periods": {"num_0": {"money_line": {"home": 1.5, "away": 2.5}}}}))

    def test_handball_compares_winner_exact_lines_and_first_half(self):
        match, values = handball.shape_match(self.handball(), (self.HB_ROW, 1.0))
        self.assertEqual({(r["group"], r["line"]) for r in match["rows"]},
                         {("Pobednik", None), ("Hendikep", -4.5), ("Ukupno golova", 62.5)})  # AH -4 is a whole line
        self.assertEqual({r["group"] for r in match["periods"]["h1"]}, {"Ukupno golova"})  # 31.5 in both books
        self.assertEqual(match["sport"], "HB")
        self.assertEqual(match["merkur"]["ml"]["home"]["odds"], 1.13)
        self.assertTrue(values)

    def test_three_way_winner_compares_with_the_1x2(self):
        event = self.handball()
        event["periods"]["num_0"]["money_line"] = {"home": 1.2, "draw": 11.0, "away": 5.0}
        pin = handball.pinnacle_markets(event)
        self.assertIsNone(pin["ml"])
        self.assertEqual(pin["x12"], {"home": 1.2, "draw": 11.0, "away": 5.0})
        rows = handball.shape_match(event, (self.HB_ROW, 1.0))[0]["rows"]
        self.assertIn("1X2", {r["group"] for r in rows})

    def test_volleyball_compares_the_winner_only(self):
        match, _ = handball.shape_match(self.volleyball(), (self.V_ROW, 1.0))
        self.assertEqual([r["group"] for r in match["rows"]], ["Pobednik"])
        self.assertEqual(match["sport"], "V")
        self.assertIsNone(match["spread"])  # set handicaps are not handball goals
        self.assertEqual(handball.merkur_markets(self.V_ROW)["spreads"], {})

    def test_a_match_pairs_only_within_its_sport_and_sex(self):
        ts = bb.event_ts(self.handball())
        hb, vb = ({**row, "kickOffTime": ts, "live": False} for row in (self.HB_ROW, self.V_ROW))
        clash = {**self.V_ROW, "id": 23, "home": "Vojvodina", "away": "Metaloplastika", "kickOffTime": ts, "live": False}
        pairs = handball.pair_events([self.handball(), self.volleyball()], [hb, vb, clash])
        self.assertEqual({pid: row["id"] for pid, (row, _) in pairs.items()}, {"7": 21, "8": 22})
        women = {**self.handball(), "event_id": 9, "league_name": "Serbia - Superliga Women"}
        self.assertEqual(handball.pair_events([women], [hb]), {})  # a men side is not the women side
        women_row = {**hb, "id": 24, "home": "Vojvodina W", "away": "Metaloplastika W"}
        self.assertIn("9", handball.pair_events([women], [women_row]))

    def test_board_keeps_both_sports_and_ignores_unknown_events(self):
        ts = bb.event_ts(self.handball())
        rows = [{**self.HB_ROW, "kickOffTime": ts, "live": False}, {**self.V_ROW, "kickOffTime": ts, "live": False}]
        bare = {**self.handball(), "event_id": 10, "periods": {"num_0": {"money_line": {"home": 1.5, "away": 2.5}}}}
        state = handball.HandballState(dash.History(path=None), str, mx.OfferCache(api=FakeMerkurAPI(rows)))
        state.get_api = lambda: FakeAPI([self.handball(), self.volleyball(), bare])
        board = state.board()
        self.assertEqual(sorted(m["id"] for m in board["matches"]), [7, 8])  # the event without a total is neither yet
        self.assertEqual({c["badge"] for c in board["competitions"]}, {"handball", "volleyball"})
        self.assertEqual(board["merkur"]["paired"], 2)
        self.assertTrue(state.owns(7) and state.owns("8") and not state.owns(10))

    def test_competition_uses_the_pinnwire_league(self):
        entry = handball.competition(222897, "Serbia - Superliga")
        self.assertEqual((entry["country"], entry["name"], entry["code"], entry["badge"]),
                         ("Srbija", "Superliga", "SRB", "handball"))
        self.assertEqual(handball.competition(1, "Austria - AVL Women", "V")["badge"], "volleyball")


class HockeyTests(unittest.TestCase):
    ROW = {
        "id": 9, "home": "Zurich", "away": "Langnau", "kickOffTime": 1_900_000_000_000, "leagueId": 2313897,
        "odds": {"50816": 1.6, "50817": 2.4, "1": 2.1, "2": 4.2, "3": 3.6, "264": 1.55, "265": 2.35,
                 "53877": 2.9, "53878": 1.38, "227": 1.7, "228": 2.05, "356": 1.95, "355": 1.8,
                 "50761": 1.8, "50762": 2.0, "50505": 1.75, "50504": 2.0},
        "params": {"hd2w": "-1.5", "overUnder": "5.5", "homeOverUnder": "3.5", "overUnderFirstPeriod": "1.5"},
    }

    @staticmethod
    def event():
        return {"event_id": 4, "league_id": 1532, "league_name": "Switzerland - Nationalliga A", "units": "Regular",
                "home": "ZSC Lions", "away": "SCL Tigers", "starts": "2030-03-17T17:46:40Z",
                "periods": {
                    "num_0": {"money_line": {"home": 1.62, "away": 2.38}, "spreads": {}, "totals": {}},
                    "num_6": {"money_line": {"home": 2.05, "draw": 4.3, "away": 3.7},
                              "spreads": {"0": {"hdp": 0, "home": 1.5, "away": 2.5, "max": 200},
                                          "-1.5": {"hdp": -1.5, "home": 2.75, "away": 1.43, "max": 200},
                                          "-1": {"hdp": -1, "home": 2.2, "away": 1.7, "max": 200}},
                              "totals": {"5.5": {"points": 5.5, "over": 1.75, "under": 2.0, "max": 200},
                                         "6": {"points": 6, "over": 2.0, "under": 1.8, "max": 200}},
                              "team_totals": {"home": {"3.5": {"points": 3.5, "over": 1.9, "under": 1.85}}, "away": {}}},
                    "num_1": {"money_line": {"home": 1.85, "away": 2.1},
                              "totals": {"1.5": {"points": 1.5, "over": 1.7, "under": 2.1, "max": 100}}}}}

    def test_pinnacle_markets_split_game_and_regulation(self):
        pin = hockey.pinnacle_markets(self.event())
        self.assertEqual(pin["ml"], {"home": 1.62, "away": 2.38})
        self.assertEqual(pin["x12"], {"home": 2.05, "draw": 4.3, "away": 3.7})
        self.assertEqual(set(pin["spreads"]), {-1.5})  # whole-goal lines are dropped, AH 0 included
        self.assertEqual(set(hockey.pinnacle_limits(self.event())["spreads"]), {-1.5})
        self.assertEqual(set(pin["totals"]), {5.5})
        self.assertEqual(set(pin["home"]), {3.5})
        first = hockey.pinnacle_markets(self.event(), "p1")
        self.assertEqual(first["ml"], {"home": 1.85, "away": 2.1})
        self.assertIsNone(first["x12"])

    def test_merkur_markets_decode_regulation_and_period(self):
        decoded = hockey.merkur_markets(self.ROW)
        self.assertEqual(decoded["ml"], {"home": 1.6, "away": 2.4})
        self.assertEqual(decoded["x12"], {"home": 2.1, "draw": 4.2, "away": 3.6})
        self.assertEqual(decoded["spreads"], {-1.5: {"home": 2.9, "away": 1.38}})  # "X vraća ulog" (264/265) ignored
        self.assertEqual(decoded["totals"], {5.5: {"over": 1.7, "under": 2.05}})
        self.assertEqual(decoded["home"], {3.5: {"over": 1.95, "under": 1.8}})
        first = hockey.merkur_markets(self.ROW, "p1")
        self.assertEqual(first["ml"], {"home": 1.8, "away": 2.0})
        self.assertEqual(first["totals"], {1.5: {"over": 1.75, "under": 2.0}})
        self.assertIsNone(first["x12"])

    def test_match_compares_winner_x12_handicap_and_periods_without_level_handicap(self):
        match, values = hockey.shape_match(self.event(), (self.ROW, 1.0))
        groups = {(r["group"], r["line"]) for r in match["rows"]}
        self.assertEqual(groups, {("Pobednik", None), ("1X2", None), ("Hendikep", -1.5),
                                  ("Ukupno golova", 5.5), ("Golovi domaćin", 3.5)})
        x12 = next(r for r in match["rows"] if r["group"] == "1X2")
        self.assertEqual([o["key"] for o in x12["outcomes"]], ["home", "draw", "away"])
        self.assertEqual({r["group"] for r in match["periods"]["p1"]}, {"Pobednik", "Ukupno golova"})
        self.assertEqual(match["ml"]["home"]["odds"], 1.62)
        self.assertEqual(match["merkur"]["ml"]["home"]["odds"], 1.6)
        self.assertEqual(match["total"]["line"], 5.5)
        self.assertTrue(all(v["merkur"] > v["pinnacle"] for v in values))

    def test_alias_pairs_a_short_merkur_name(self):
        self.assertEqual(hockey.name_score("ZSC Lions", "Zurich"), 1.0)
        self.assertEqual(hockey.name_score("SCL Tigers", "Langnau"), 1.0)
        late = {**self.ROW, "kickOffTime": bb.event_ts(self.event()) + 4 * 3600 * 1000, "live": False}
        self.assertEqual(hockey.pair_events([self.event()], [late]), {})  # outside the 3 h window
        row = {**self.ROW, "kickOffTime": bb.event_ts(self.event()), "live": False}
        self.assertIn("4", hockey.pair_events([self.event()], [row]))

    def test_untracked_leagues_only_feed_the_missing_view(self):
        other = {**self.event(), "event_id": 5, "league_id": 1, "league_name": "Norway - Eliteserien",
                 "home": "Stavanger Oilers", "away": "Storhamar"}
        third = {**other, "event_id": 6, "home": "Valerenga", "away": "Frisk Asker"}
        offered = {**self.ROW, "id": 10, "home": "Valerenga", "away": "Frisk Asker", "leagueId": 77,
                   "leagueShort": "NOR EL", "kickOffTime": bb.event_ts(self.event()), "live": False}
        state = hockey.HockeyState(dash.History(path=None), str, mx.OfferCache(api=FakeMerkurAPI([offered])))
        state.get_api = lambda: FakeAPI([self.event(), other, third])
        board = state.board()
        self.assertEqual([m["id"] for m in board["matches"]], [4])
        self.assertEqual([m["id"] for m in board["otherMissing"]], [5])  # 6 is offered under an untracked league
        self.assertEqual([(c["key"], c["country"]) for c in board["otherCompetitions"]], [("x1", "Norway")])
        self.assertEqual([(o["leagueId"], o["mxLeagueId"], o["count"]) for o in board["otherOffered"]], [(1, 77, 1)])
        with self.assertRaises(LookupError):
            state.match("5")

    def test_drop_quotes_use_game_period_for_winner_and_regulation_for_the_rest(self):
        match, _ = hockey.shape_match(self.event(), (self.ROW, 1.0))
        quotes = hockey.drop_quotes(self.event(), match)["4"][1]
        self.assertIn(("moneyline", 0, None, "home"), quotes)
        self.assertIn(("moneyline", 6, None, "draw"), quotes)
        self.assertIn(("total", 6, 5.5, "over"), quotes)
        self.assertIn(("total", 1, 1.5, "over"), quotes)


class MmaTests(unittest.TestCase):
    # MerkurXtip lists the fight the other way round: Moicano first
    ROW = {
        "id": 7, "home": "Moicano, Renato", "away": "Nolan, Tom", "kickOffTime": 1_900_000_000_000 + 4 * 3600 * 1000,
        "leagueId": 2404691, "odds": {"264": 1.79, "265": 2.0, "54291": 1.52, "54290": 2.49, "54292": 1.28},
        "params": {"our": "1.5"},
    }

    @staticmethod
    def event():
        return {"event_id": 8, "league_id": 1624, "league_name": "UFC", "units": "Regular", "parent_id": None,
                "home": "Tom Nolan", "away": "Renato Moicano", "starts": "2030-03-17T17:46:40Z",
                "periods": {"num_0": {"money_line": {"home": 2.0, "away": 1.855}, "spreads": {},
                                      "totals": {"1.5": {"points": 1.5, "over": 1.546, "under": 2.49, "max": 1025}}}}}

    def pair(self):
        return mma.pair_events([self.event()], [self.ROW])["8"]

    def test_reversed_merkur_fight_pairs_and_reads_the_winner_the_other_way_round(self):
        row, score = self.pair()
        self.assertEqual(score, 1.0)
        self.assertTrue(row[mma.SWAPPED])
        self.assertEqual(mma.merkur_markets(row)["ml"], {"home": 2.0, "away": 1.79})
        self.assertFalse(self.ROW.get(mma.SWAPPED))  # the cached offer row is left as it is

    def test_straight_fight_keeps_its_order(self):
        straight = {**self.ROW, "home": "Nolan, Tom", "away": "Moicano, Renato"}
        row, _ = mma.pair_events([self.event()], [straight])["8"]
        self.assertFalse(row.get(mma.SWAPPED))
        self.assertEqual(mma.merkur_markets(row)["ml"], {"home": 1.79, "away": 2.0})

    def test_fight_compares_winner_and_total_rounds(self):
        match, values = mma.shape_match(self.event(), self.pair())
        self.assertEqual({(r["group"], r["line"]) for r in match["rows"]}, {("Pobednik", None), ("Ukupno rundi", 1.5)})
        self.assertEqual((match["merkur"]["home"], match["merkur"]["away"]), ("Nolan, Tom", "Moicano, Renato"))
        self.assertEqual(match["merkur"]["ml"]["away"]["odds"], 1.79)
        self.assertIsNone(match["spread"])
        self.assertEqual(match["total"]["line"], 1.5)
        self.assertEqual(next(r for r in match["rows"] if r["line"] == 1.5)["maxBet"], 1025)
        self.assertTrue(all(v["merkur"] > v["pinnacle"] for v in values))

    def test_names_pair_across_name_order_and_aliases(self):
        self.assertEqual(mma.fighter_score("Zachary Reese", "Reese, Zach"), 1.0)
        self.assertEqual(mma.fighter_score("Talita Alencar", "de Oliviera Alencar, Ana Talita"), 1.0)
        self.assertEqual(mma.fighter_score("Yana Santos", "Kunitskaya, Yana W"), 1.0)
        far = {**self.ROW, "kickOffTime": bb.event_ts(self.event()) + 13 * 3600 * 1000}
        self.assertEqual(mma.pair_events([self.event()], [far]), {})  # outside the 12 h window

    def test_every_league_is_kept_and_named_by_its_promotion(self):
        other = {**self.event(), "event_id": 9, "league_id": 5, "league_name": "Oktagon MMA"}
        out = mma.MmaState(dash.History(path=None), str).incoming({"events": [self.event(), other]})
        self.assertEqual([e["event_id"] for e in out], [8, 9])
        comps = mma.MmaState.competitions(None, [mma.shape_match(e, None)[0] for e in out])
        self.assertEqual([(c["code"], c["badge"], c["count"]) for c in comps], [("UFC", "ufc", 1), ("OKT", "oktagon", 1)])

    def test_drop_quotes_are_in_period_zero(self):
        match, _ = mma.shape_match(self.event(), self.pair())
        quotes = mma.drop_quotes(self.event(), match)["8"][1]
        self.assertEqual(quotes[("moneyline", 0, None, "away")], {"merkur": 1.79, "fair": 1.925})
        self.assertIn(("total", 0, 1.5, "under"), quotes)


class OtherLeagueTests(unittest.TestCase):
    @staticmethod
    def event(event_id, home, away, league_id=999, league="Wales - Cymru Premier"):
        return {"event_id": event_id, "league_id": league_id, "league_name": league, "home": home, "away": away,
                "starts": "2030-03-17T17:46:40Z", "units": "Regular",
                "periods": {"num_0": {"money_line": {"home": 2.0, "draw": 3.4, "away": 3.8}}}}

    def test_pairing_without_competition_and_side_markers(self):
        events = [self.event(1, "Bala Town", "Penybont"), self.event(2, "Arsenal", "Chelsea"),
                  self.event(3, "Arsenal W", "Chelsea W")]
        ts = dash.event_ts(events[0])
        offer = [{"id": 11, "home": "Bala Town", "away": "Penybont FC", "kickOffTime": ts, "live": False},
                 {"id": 12, "home": "Arsenal", "away": "Chelsea", "kickOffTime": ts, "live": False}]
        missing, _, paired = dash.unpaired_other(events, offer, set())
        self.assertEqual(missing, {"3"})
        offered = dash.offered_other(events, paired)
        self.assertEqual([(o["leagueId"], o["count"]) for o in offered], [(999, 2)])  # the women's match is not the senior one MerkurXtip offers
        missing, _, _ = dash.unpaired_other(events, offer, {12})
        self.assertEqual(missing, {"2", "3"})  # an offer row already used inside the tracked leagues is not reused

    def test_missing_other_lists_unpaired_events_with_their_league(self):
        state = dash.DashboardState(history=object(), merkur=FakeMerkurAPI)
        events = [self.event(1, "Bala Town", "Penybont")]
        out = state.missing_other(events, [], set())
        self.assertEqual([m["id"] for m in out], [1])
        self.assertIsNone(out[0]["merkur"])
        comps = dash.other_competitions(out)
        self.assertEqual((comps[0]["country"], comps[0]["name"], comps[0]["key"]), ("Wales", "Cymru Premier", "x999"))
        self.assertEqual(dash.split_league("NHL"), ("Ostalo", "NHL"))

    def test_untracked_events_stay_out_of_the_tracked_board(self):
        self.assertFalse(dash.is_tracked(self.event(1, "Bala Town", "Penybont")))


class DevigTests(unittest.TestCase):
    def test_two_way_uses_shin_and_sums_to_one(self):
        probs = pw.devig({"home": 1.15, "away": 5.78})
        self.assertAlmostEqual(sum(probs.values()), 1.0, places=9)
        self.assertAlmostEqual(1 / probs["away"], 6.59, places=2)

    def test_lopsided_two_way_does_not_explode(self):
        probs = pw.devig({"home": 1.01, "away": 8.12})
        self.assertLess(1 / probs["away"], 20)

    def test_three_way_keeps_power_method(self):
        probs = pw.devig({"home": 2.0, "draw": 3.4, "away": 4.0})
        self.assertAlmostEqual(sum(probs.values()), 1.0, places=9)
        expected = pw._power([1 / 2.0, 1 / 3.4, 1 / 4.0])
        for side, p in zip(("home", "draw", "away"), expected):
            self.assertAlmostEqual(probs[side], p, places=9)

    def test_even_market_is_symmetric(self):
        probs = pw.devig({"over": 1.9, "under": 1.9})
        self.assertAlmostEqual(probs["over"], 0.5, places=9)


class ValueDedupeTests(unittest.TestCase):
    @staticmethod
    def item(group, line, key, ev, period="ft", match=1):
        return {"matchId": match, "period": period, "group": group, "line": line, "key": key, "ev": ev}

    def test_alternative_lines_collapse_to_best(self):
        items = [self.item("Ukupno golova", 2.5, "over", 0.01), self.item("Ukupno golova", 3.5, "over", 0.03),
                 self.item("Hendikep", -0.5, "home", 0.02), self.item("Hendikep", 0.5, "home", 0.01),
                 self.item("1X2", None, "home", 0.01), self.item("1X2", None, "away", 0.02)]
        out = pw.best_per_line_market(items)
        self.assertEqual({(i["group"], i["line"]) for i in out},
                         {("Ukupno golova", 3.5), ("Hendikep", -0.5), ("1X2", None)})
        self.assertEqual(len([i for i in out if i["group"] == "1X2"]), 2)

    def test_periods_and_matches_stay_separate(self):
        items = [self.item("Hendikep", -0.5, "home", 0.02), self.item("Hendikep", -0.5, "home", 0.01, period="ht"),
                 self.item("Hendikep", -0.5, "home", 0.03, match=2)]
        self.assertEqual(len(pw.best_per_line_market(items)), 3)


class BasketballModelTests(unittest.TestCase):
    # Pinnacle totals ladder built from a normal with mean 166.5 and sigma 14, quoted without margin.
    @staticmethod
    def ladder(mean=166.5, sigma=14.0, lines=(164.5, 165.5, 166.5, 167.5, 168.5)):
        from statistics import NormalDist
        out = {}
        for line in lines:
            over = 1 - NormalDist(mean, sigma).cdf(line)
            out[line] = {"over": round(1 / (over * 1.025), 3), "under": round(1 / ((1 - over) * 1.025), 3)}
        return out

    def test_model_extends_the_ladder(self):
        ladder = self.ladder()
        p, margin = bb.model_probability(ladder, "totals", 161.5)
        from statistics import NormalDist
        self.assertAlmostEqual(p, 1 - NormalDist(166.5, 14).cdf(161.5), delta=0.01)
        self.assertGreater(margin, 0)

    def test_model_refuses_far_lines(self):
        self.assertIsNone(bb.model_probability(self.ladder(), "totals", 150.5))

    def test_modeled_row_flags_value_on_a_lagging_total(self):
        ladder = self.ladder()
        pin = {"ml": None, "spreads": {}, "totals": ladder, "home": {}, "away": {}}
        merkur = {"ml": None, "spreads": {}, "totals": {161.5: {"over": 1.9, "under": 1.9}}, "home": {}, "away": {},
                  "main": {"spreads": None, "totals": 161.5}}
        rows = bb.compare(pin, merkur)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["modeled"])
        over = next(o for o in rows[0]["outcomes"] if o["key"] == "over")
        self.assertGreater(over["ev"], 0.1)
        gaps = bb.stale_gaps(pin, merkur)
        self.assertEqual(gaps, {"Ukupno poena": -5.0})
        items = bb.value_items(1, rows, gaps)
        self.assertEqual([(i["key"], i["stale"], i["modeled"]) for i in items], [("over", -5.0, True)])

    def test_spread_direction(self):
        self.assertTrue(bb.favours("Hendikep", 2.5, "home"))
        self.assertTrue(bb.favours("Ukupno poena", 3.0, "under"))
        self.assertFalse(bb.favours("Ukupno poena", -3.0, "under"))


class MissingHintTests(unittest.TestCase):
    def test_closest_unpaired_points_at_unused_row_of_same_competition(self):
        pin = [{"id": "1", "comp": 5, "home": "Alpha Beta Gamma Delta", "away": "Qqq Rrr", "ts": 0},
               {"id": "2", "comp": 5, "home": "Nobody", "away": "Else", "ts": 0}]
        mer = [{"id": 10, "comp": 5, "home": "Alpha Zeta", "away": "Mmm Nnn", "ts": 60000},
               {"id": 11, "comp": 6, "home": "Nobody", "away": "Else", "ts": 0}]
        hints = mx.closest_unpaired(pin, mer, mx.pair(pin, mer))
        self.assertEqual(hints["1"][0]["id"], 10)
        self.assertNotIn("2", hints)  # the only same-name row belongs to another competition

    def test_women_marker_is_ignored_in_names(self):
        self.assertGreaterEqual(mx.name_score("AZS UMCS Lublin", "Lublin W"), 1.0)


class PrematchRowTests(unittest.TestCase):
    def test_live_flag_before_kickoff_still_counts_as_prematch(self):
        self.assertTrue(mx.is_prematch({"live": True, "kickOffTime": 2000}, now_ms=1000))
        self.assertFalse(mx.is_prematch({"live": True, "kickOffTime": 500}, now_ms=1000))
        self.assertTrue(mx.is_prematch({"live": False, "kickOffTime": 500}, now_ms=1000))


class BasketballPeriodTests(unittest.TestCase):
    ROW = {"odds": {"611": 1.6, "612": 2.2, "53903": 1.85, "53904": 1.85, "50979": 1.9, "50980": 1.8,
                    "598": 1.88, "599": 1.82, "602": 1.9, "603": 1.8, "50025": 1.7, "50026": 2.1},
           "params": {"hd2wp1": "-1.5", "overUnderP": "86.5", "handicapFirstPeriod": "0.5",
                      "overUnderFirstPeriod": "42.5"}}

    def test_first_half_codes(self):
        half = bb.merkur_markets(self.ROW, "ht")
        self.assertEqual(half["ml"], {"home": 1.6, "away": 2.2})
        self.assertEqual(half["spreads"], {-1.5: {"home": 1.85, "away": 1.85}})
        self.assertEqual(half["totals"], {86.5: {"over": 1.9, "under": 1.8}})

    def test_first_quarter_codes(self):
        quarter = bb.merkur_markets(self.ROW, "q1")
        self.assertEqual(quarter["ml"], {"home": 1.7, "away": 2.1})
        self.assertEqual(quarter["spreads"], {0.5: {"home": 1.9, "away": 1.8}})
        self.assertEqual(quarter["totals"], {42.5: {"over": 1.88, "under": 1.82}})

    def test_period_rows_carry_their_period_into_value_items(self):
        pin = {"ml": None, "spreads": {}, "totals": {86.5: {"over": 1.95, "under": 1.85}}, "home": {}, "away": {}}
        rows = bb.compare(pin, bb.merkur_markets(self.ROW, "ht"), "ht", 0.71)
        self.assertEqual({r["period"] for r in rows}, {"ht"})
        items = bb.value_items(1, rows)
        self.assertTrue(all(i["period"] == "ht" and i["periodLabel"] == "1. poluvreme" for i in items))


class DropTests(unittest.TestCase):
    FRAME = {"id": 1637470980, "sport_id": 3, "home": "San Antonio Spurs", "away": "Houston Rockets", "league": "NBA",
             "sport": "Basketball", "sect": "Spread", "market_type": "spread", "period": 0, "outcome": "away",
             "points": 4, "from_price": 1.625, "to_price": 1.599, "drop_pct": 1.6, "nvp": 1.655,
             "starts": "2030-10-24T01:40:00Z", "is_live": False, "alerted": 1792706473}

    def test_sse_frame_gets_rest_field_names(self):
        d = pw.normalize_drop(self.FRAME)
        self.assertEqual((d["event_id"], d["market"], d["side"], d["points"], d["from"], d["to"]),
                         (1637470980, "spread", "away", 4.0, 1.625, 1.599))

    def test_team_total_and_live_drops_are_skipped(self):
        self.assertIsNone(pw.normalize_drop({**self.FRAME, "market_type": "team_total"}))
        self.assertIsNone(pw.normalize_drop({**self.FRAME, "is_live": True}))

    def test_away_spread_drop_uses_the_home_handicap(self):
        self.assertEqual(pw.drop_key("spread", 0, "away", 4), ("spread", 0, -4.0, "away"))
        self.assertEqual(pw.drop_key("spread", 0, "home", -4), ("spread", 0, -4.0, "home"))
        self.assertEqual(pw.drop_key("moneyline", 1, "home", None), ("moneyline", 1, None, "home"))

    def test_quote_index_matches_compare_rows(self):
        rows = dash.compare_period(kit_event(), {"ml": {"home": 2.5, "draw": 3.2, "away": 2.8},
                                                 "spreads": {-0.5: {"home": 2.5, "away": 1.5}}}, 0)
        index = pw.quote_index({0: rows}, dash.DROP_GROUPS)
        self.assertEqual(index[pw.drop_key("moneyline", 0, "draw", None)]["merkur"], 3.2)
        self.assertEqual(index[pw.drop_key("spread", 0, "away", 0.5)]["merkur"], 1.5)

    def test_tennis_games_drop_finds_the_parent_match(self):
        event = tennis.TennisState.incoming(None, {"events": [
            TennisTests.main_event(), TennisTests.games_event()]})[0]
        match, _ = tennis.shape_match(event, (TennisTests.ROW, 1.0))
        quotes = tennis.drop_quotes(event, match)
        self.assertEqual(quotes["8"][0], 7)
        self.assertEqual(quotes["8"][1][pw.drop_key("spread", 0, "home", 3.5)]["merkur"], 1.72)
        self.assertEqual(quotes["7"][1][pw.drop_key("moneyline", 0, "home", None)]["merkur"], 2.4)

    def test_drops_response_adds_match_and_merkur_edge(self):
        feed = dash.DropFeed(lambda: "")
        now = int(dash.time.time())
        feed.add([{**self.FRAME, "alerted": now}, {**self.FRAME, "sport_id": 99, "alerted": now}])
        key = pw.drop_key("spread", 0, "away", 4)
        old_feed, old_quotes = dash.DROPS, dash.BB_STATE.quotes
        dash.DROPS, dash.BB_STATE.quotes = feed, {"1637470980": (1637470980, {key: {"merkur": 1.72, "fair": 1.7}})}
        try:
            body = dash.drops_response({"sport": ["basketball"], "min": ["1"]})
            above = dash.drops_response({"sport": ["basketball"], "min": ["5"]})
        finally:
            dash.DROPS, dash.BB_STATE.quotes = old_feed, old_quotes
        [drop] = body["drops"]
        self.assertEqual(drop["match_id"], 1637470980)
        self.assertEqual(drop["merkur"], {"odds": 1.72, "ev": round(1.72 / 1.655 - 1, 4)})
        self.assertEqual(above["drops"], [])


class ClvTests(unittest.TestCase):
    @staticmethod
    def match(merkur, fair=2.0, starts="2030-08-28T19:30:00Z", line=2.5, **row):
        outcome = {"key": "over", "label": "Više", "merkur": merkur, "pinnacle": 1.9, "fair": fair,
                   "ev": merkur / fair - 1}
        return [{"id": 7, "home": "A", "away": "B", "league": "Liga", "starts": starts,
                 "rows": [("ft", {"group": "Ukupno golova", "line": line, "outcomes": [outcome], **row})]}]

    def setUp(self):
        self.store = clv.ClvStore()

    def test_only_edges_above_the_threshold_become_signals(self):
        self.assertEqual(self.store.observe("football", self.match(2.02), "2030-08-28T10:00:00Z"), 0)
        self.assertEqual(self.store.observe("football", self.match(2.10), "2030-08-28T10:00:30Z"), 1)

    def test_signal_keeps_first_price_and_closing_follows_the_latest_board(self):
        self.store.observe("football", self.match(2.10), "2030-08-28T10:00:00Z")
        self.store.observe("football", self.match(2.30, fair=2.2), "2030-08-28T19:20:00Z")
        stats = self.store.stats(now="2030-08-28T20:00:00Z")
        [row] = stats["recent"]
        self.assertEqual((row["merkur"], row["close_fair"], row["clv"]), (2.10, 2.2, round(2.10 / 2.2 - 1, 4)))
        self.assertEqual(stats["total"]["n"], 1)
        self.assertEqual(stats["total"]["positive"], 0)

    def test_stale_closing_line_is_not_counted(self):
        self.store.observe("football", self.match(2.10), "2030-08-28T10:00:00Z")
        stats = self.store.stats(now="2030-08-28T20:00:00Z")
        self.assertEqual((stats["total"]["n"], stats["unclosed"], stats["recent"][0]["clv"]), (0, 1, None))

    def test_modelled_rows_and_started_matches_are_skipped(self):
        self.assertEqual(self.store.observe("basketball", self.match(2.5, modeled=True), "2030-08-28T10:00:00Z"), 0)
        self.assertEqual(self.store.observe("football", self.match(2.5), "2030-08-28T20:00:00Z"), 0)

    def test_groups_and_pending_counts(self):
        self.store.observe("football", self.match(2.10), "2030-08-28T10:00:00Z")
        self.store.observe("football", self.match(2.4, line=3.5, starts="2030-09-01T19:30:00Z"), "2030-08-28T10:00:00Z")
        self.store.observe("football", self.match(2.10, fair=2.0), "2030-08-28T19:25:00Z")
        stats = self.store.stats(now="2030-08-28T20:00:00Z")
        self.assertEqual((stats["pending"], stats["total"]["n"]), (1, 1))
        self.assertEqual(stats["byLeague"][0]["name"], "Liga")
        self.assertEqual(stats["byGroup"][0]["name"], "Ukupno golova")

    def test_soon_flags_a_signal_close_to_kickoff(self):
        self.store.observe("football", self.match(2.10), "2030-08-28T10:00:00Z")
        early = clv.datetime(2030, 8, 28, 19, 20, tzinfo=clv.timezone.utc)
        self.assertTrue(self.store.soon(15, now=early))
        self.assertFalse(self.store.soon(15, now=early - clv.timedelta(hours=2)))

    def test_state_board_reports_to_the_store(self):
        state = make_state(FakeAPI([event(1)]))
        state.clv = self.store
        state.board()
        self.assertIn("football", self.store.last_seen)


class DropFeedCycleTests(unittest.TestCase):
    """DropFeed.cycle(): one stream connection and the wait before the next one."""

    def feed(self, *outcomes):
        """A feed whose successive connections yield the frame lists of each outcome, or raise it."""
        feed = dash.DropFeed(lambda: "key")
        feed.slept = []
        feed.sleep = feed.slept.append
        outcomes = list(outcomes)

        class API:
            def __init__(self, key):
                pass

            def drop_stream(self, **params):
                outcome = outcomes.pop(0)
                if isinstance(outcome, Exception):
                    raise outcome
                yield from outcome

        feed.api_factory = API
        return feed

    def test_failures_back_off_up_to_30_seconds(self):
        feed = self.feed(*[RuntimeError("down")] * 6)
        wait = 1
        for _ in range(6):
            wait = feed.cycle(wait)
        self.assertEqual(feed.slept, [1, 2, 4, 8, 16, 30])
        self.assertEqual((feed.error, feed.connected), ("down", False))

    def test_a_frame_resets_the_back_off(self):
        frame = {"id": 1, "sport_id": 1, "market_type": "moneyline", "outcome": "home", "from_price": 2.0,
                 "to_price": 1.9, "drop_pct": 5, "alerted": int(time.time())}
        feed = self.feed([[frame]])
        self.assertEqual(feed.cycle(16), 2)  # stream ended after a frame: wait 1 s, then 2 s
        self.assertEqual((feed.slept, feed.error, len(feed.drops)), ([1], "", 1))

    def test_refused_key_waits_a_minute(self):
        feed = self.feed(PermissionError("plan"))
        self.assertEqual(feed.cycle(1), 30)
        self.assertEqual(feed.slept, [60])

    def test_unexpected_error_keeps_the_feed_alive(self):
        feed = self.feed(ValueError("bad frame"))
        feed.cycle(1)
        self.assertIn("ValueError", feed.error)

    def test_reconnect_connects_again_at_once(self):
        feed = self.feed(RuntimeError("closed"))
        original = feed.api_factory.drop_stream

        def drop_stream(api, **params):
            feed.reconnect()  # a new key was saved while the stream was open
            yield from original(api, **params)

        feed.api_factory.drop_stream = drop_stream
        self.assertEqual(feed.cycle(8), 1)
        self.assertEqual(feed.slept, [])


class AppLogTests(unittest.TestCase):
    """The log gets one line per state change, not one per refresh."""

    def messages(self, logs):
        return [record.getMessage() for record in logs.records]

    def test_setup_writes_the_file_and_records_crashed_threads(self):
        logger = applog.logger
        handlers, level, hook = list(logger.handlers), logger.level, threading.excepthook

        def restore():
            for handler in logger.handlers[:]:
                if handler not in handlers:
                    logger.removeHandler(handler)
                    handler.close()
            logger.setLevel(level)
            threading.excepthook = hook

        self.addCleanup(restore)
        directory = os.path.join(tempfile.mkdtemp(), "logs")
        with contextlib.redirect_stderr(io.StringIO()):
            path = applog.setup(directory)
            logging.getLogger("xtip.test").info("šđčćž")

            def crash():
                raise ValueError("boom")

            thread = threading.Thread(target=crash, name="radnik")
            thread.start()
            thread.join()
        with open(path, encoding="utf-8") as log_file:
            text = log_file.read()
        self.assertIn("šđčćž", text)
        self.assertIn("Nit radnik je pala", text)
        self.assertIn("ValueError: boom", text)

    def test_unusable_directory_does_not_stop_the_server(self):
        logger = applog.logger
        handlers, level, hook = list(logger.handlers), logger.level, threading.excepthook

        def restore():
            logger.handlers[:] = handlers
            logger.setLevel(level)
            threading.excepthook = hook

        self.addCleanup(restore)
        blocker = os.path.join(tempfile.mkdtemp(), "file")
        with open(blocker, "w", encoding="utf-8"):
            pass
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertIsNone(applog.setup(os.path.join(blocker, "logs")))

    def test_pinnwire_outage_logs_once_and_recovery_once(self):
        class Flaky(FakeAPI):
            down = True

            def prematch_snapshot(self, sport_id, since=None, alt_units=False):
                if self.down:
                    raise RuntimeError("PinnWire pao")
                return super().prematch_snapshot(sport_id, since, alt_units)

        api = Flaky([event(1)])
        state = make_state(api)
        state.label = "football"
        with self.assertLogs("xtip.snapshot", "INFO") as logs:
            for _ in range(3):
                with self.assertRaises(RuntimeError):
                    state.refresh()
            api.down = False
            state.refresh()
            state.refresh()
        self.assertEqual(self.messages(logs), ["football: PinnWire: PinnWire pao", "football: PinnWire ponovo radi",
                                               "football: pun snapshot, 1 mečeva (pre: 0)"])

    def test_halved_snapshot_is_a_warning(self):
        state = make_state(FakeAPI([event(i) for i in range(1, 21)]))
        state.refresh(full=True)
        state.get_api().full = [event(1)]
        with self.assertLogs("xtip.snapshot", "WARNING") as logs:
            state.refresh(full=True)
        self.assertIn("broj mečeva je pao sa 20 na 1", logs.output[0])

    def test_merkur_outage_logs_once_and_recovery_once(self):
        class Flaky(FakeMerkurAPI):
            down = True

            def offer(self):
                if self.down:
                    raise RuntimeError("Merkur pao")
                return []

        api = Flaky()
        state = dash.DashboardState(dash.History(path=None), merkur=mx.OfferCache(api=api))
        state.label = "football"
        with self.assertLogs("xtip.snapshot", "INFO") as logs:
            state.merkur_offer()
            state.merkur_offer()
            api.down = False
            state.merkur_offer()
        self.assertEqual(self.messages(logs), ["football: MerkurXtip: Merkur pao", "football: MerkurXtip ponovo radi"])

    def drop_feed(self, *outcomes):
        feed = dash.DropFeed(lambda: "key")
        feed.sleep = lambda seconds: None
        outcomes = list(outcomes)

        class API:
            def __init__(self, key):
                pass

            def drop_stream(self, **params):
                outcome = outcomes.pop(0)
                if isinstance(outcome, Exception):
                    raise outcome
                yield from outcome

        feed.api_factory = API
        return feed

    def test_drop_stream_logs_a_repeated_failure_once(self):
        feed = self.drop_feed(*[RuntimeError("down")] * 3)
        with self.assertLogs("xtip.server", "INFO") as logs:
            for _ in range(3):
                feed.cycle(1)
        self.assertEqual(self.messages(logs), ["Drop stream: down"])

    def test_drop_stream_logs_connecting_and_dropping(self):
        feed = self.drop_feed([[]], RuntimeError("down"))
        with self.assertLogs("xtip.server", "INFO") as logs:
            feed.cycle(1)
            feed.cycle(1)
        self.assertEqual(self.messages(logs)[0], "Drop stream povezan")
        self.assertTrue(self.messages(logs)[1].startswith("Drop stream prekinut"))
        self.assertEqual(self.messages(logs)[2], "Drop stream: down")

    def test_unexpected_drop_error_logs_its_traceback_once(self):
        feed = self.drop_feed(ValueError("bad"), ValueError("bad"))
        with self.assertLogs("xtip.server", "ERROR") as logs:
            feed.cycle(1)
            feed.cycle(1)
        self.assertEqual(len(logs.records), 1)
        self.assertIn("ValueError: bad", logs.output[0])

    def test_status_line_counts_matches_and_pairs(self):
        state = make_state(FakeAPI([event(1)]))
        state.board()
        with self.assertLogs("xtip.server", "INFO") as logs:
            dash.log_status({"football": state})
        self.assertIn("football 1/0", logs.output[0])

    def test_pinnwire_retry_is_logged_without_the_key(self):
        api = pw.PinnWireAPI("TAJNIKLJUC", min_interval=0)
        error = pw.requests.ConnectionError("veza pala, kljuc TAJNIKLJUC")
        with (mock.patch.object(api.s, "get", side_effect=error), mock.patch.object(pw.time, "sleep"),
              self.assertLogs("xtip.pinnwire", "WARNING") as logs, self.assertRaises(RuntimeError)):
            api.get("/x")
        self.assertIn("/x: ponovni pokušaj", logs.output[0])
        self.assertNotIn("TAJNIKLJUC", logs.output[0])


class CompetitionTableTests(unittest.TestCase):
    """Run after adding a league: duplicates or a missing badge colour fail here instead of in the UI."""

    TABLES = {"football": dash.COMPETITIONS, "basketball": bb.COMPETITIONS, "hockey": hockey.COMPETITIONS}

    @staticmethod
    def duplicates(values):
        seen, out = set(), set()
        for v in values:
            (out if v in seen else seen).add(v)
        return out

    def test_ids_keys_and_badge_codes_are_unique(self):
        for sport, table in self.TABLES.items():
            for field in ("id", "key", "code"):
                with self.subTest(sport=sport, field=field):
                    self.assertEqual(self.duplicates(c[field] for c in table), set())

    def test_each_merkur_league_maps_to_one_competition(self):
        football = [m for c in dash.COMPETITIONS
                    for m in [*([c["merkur"]] if "merkur" in c else []), *c.get("merkur_also", [])]]
        basketball = [m for c in bb.COMPETITIONS for m in (c["mx_id"], *c.get("mx_extra", ()))]
        for sport, ids in (("football", football), ("basketball", basketball),
                           ("hockey", [c["mx_id"] for c in hockey.COMPETITIONS])):
            with self.subTest(sport=sport):
                self.assertEqual(self.duplicates(ids), set())

    def test_shared_merkur_league_points_at_a_competition_with_its_own(self):
        own = {c["id"] for c in dash.COMPETITIONS if "merkur" in c}
        for c in dash.COMPETITIONS:
            with self.subTest(key=c["key"]):
                self.assertTrue(("merkur" in c) != ("merkur_of" in c))
                self.assertIn(c.get("merkur_of", c["id"]), own)

    def test_every_competition_has_a_badge_colour(self):
        with open(os.path.join(os.path.dirname(dash.__file__), "frontend", "dashboard", "dashboard.css"),
                  encoding="utf-8") as fh:
            css = fh.read()
        coloured = set(re.findall(r"\.comp-badge\.([\w-]+)", css))
        for sport, table in self.TABLES.items():
            with self.subTest(sport=sport):
                self.assertEqual([c["key"] for c in table if c["key"] not in coloured], [])
        badges = [badge for _, _, badge in mma.PROMOTIONS] + [mma.OTHER_PROMOTION[2], *handball.BADGES.values()]
        self.assertEqual([b for b in badges if b not in coloured], [])


class BuildSyncTests(unittest.TestCase):
    """The committed static/dashboard_build must be built from the current frontend source."""

    @staticmethod
    def source_hash(frontend):
        # same files and algorithm as sourceHash() in frontend/vite.config.js
        files = [os.path.join(dirpath, name) for dirpath, _, names in os.walk(os.path.join(frontend, "dashboard"))
                 for name in names]
        files += [os.path.join(frontend, name) for name in ("package.json", "package-lock.json", "vite.config.js")]
        digest = hashlib.sha256()
        for path in sorted(os.path.relpath(f, frontend).replace(os.sep, "/") for f in files):
            with open(os.path.join(frontend, path), "rb") as fh:
                digest.update(path.encode() + b"\0" + fh.read().replace(b"\r\n", b"\n") + b"\0")
        return digest.hexdigest()

    def test_bundle_matches_the_frontend_source(self):
        root = os.path.dirname(os.path.abspath(dash.__file__))
        with open(os.path.join(root, "static", "dashboard_build", "source-hash.txt"), encoding="utf-8") as fh:
            built = fh.read().strip()
        self.assertEqual(self.source_hash(os.path.join(root, "frontend")), built,
                         "frontend/ changed since the last build: run `npm run build` in frontend/ and commit the bundle")


class HistoryThreadTests(unittest.TestCase):
    def test_save_while_another_sport_observes(self):
        history = dash.History(path=os.path.join(tempfile.mkdtemp(), "history.json"))
        errors = []

        def observe():
            for i in range(1000):
                history.observe(kit_event(event_id=i), "2030-08-28T10:00:00Z")
                history.count_calls(1)

        def save():
            try:
                for _ in range(30):
                    history.save()
            except Exception as exc:  # noqa: BLE001 (before the lock: "dictionary changed size during iteration")
                errors.append(exc)

        threads = [threading.Thread(target=observe), threading.Thread(target=save), threading.Thread(target=save)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(history.calls_today(), 1000)


class HandlerTests(unittest.TestCase):
    def setUp(self):
        self.server = dash.ThreadingHTTPServer(("127.0.0.1", 0), dash.Handler)
        threading.Thread(target=self.server.serve_forever, args=(0.05,), daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def request(self, path, data=None, content_type=None):
        req = urllib.request.Request(self.base + path, data=data, method="POST" if data is not None else "GET")
        if content_type:
            req.add_header("Content-Type", content_type)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as err:
            with err:
                return err.code, json.loads(err.read())

    def test_unexpected_error_is_a_json_500(self):
        original = dash.drops_response
        dash.drops_response = lambda query: {}["boom"]
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                status, body = self.request("/api/drops")
        finally:
            dash.drops_response = original
        self.assertEqual(status, 500)
        self.assertIn("KeyError", body["error"])

    class FakeState:
        def __init__(self, error=None):
            self.error, self.calls = error, []

        def board(self, refresh=False, full=False):
            self.calls.append(("board", refresh, full))
            if self.error:
                raise self.error
            return {"ok": True}

        def match(self, event_id, **extra):
            self.calls.append(("match", event_id, extra))
            return {"id": event_id}

    def test_routes_reach_the_right_sport(self):
        states = {sport: self.FakeState() for sport in dash.SPORT_STATES}
        with mock.patch.dict(dash.SPORT_STATES, states):
            self.assertEqual(self.request("/api/board?refresh=1")[0], 200)
            self.assertEqual(self.request("/api/hockey/board?full=1")[0], 200)
            self.assertEqual(self.request("/api/tennis/match/12")[1], {"id": "12"})
            self.assertEqual(self.request("/api/mma/board")[0], 200)
            self.assertEqual(self.request("/api/handball/board")[0], 200)
            self.assertEqual(self.request("/api/match/34?refresh=1")[1], {"id": "34"})
        self.assertEqual(states["football"].calls, [("board", True, False), ("match", "34", {"refresh": True})])
        self.assertEqual(states["hockey"].calls, [("board", False, True)])
        self.assertEqual(states["tennis"].calls, [("match", "12", {})])  # only football re-reads a match
        self.assertEqual(states["mma"].calls, [("board", False, False)])
        self.assertEqual(states["handball"].calls, [("board", False, False)])
        self.assertEqual(states["basketball"].calls, [])

    def test_bad_ids_and_unknown_routes(self):
        self.assertEqual(self.request("/api/basketball/match/abc")[0], 400)
        self.assertEqual(self.request("/api/board/x")[0], 404)
        self.assertEqual(self.request("/api/volleyball/board")[0], 404)

    def test_errors_map_to_status_codes(self):
        cases = [(PermissionError("ključ"), 401), (LookupError("nema"), 404), (RuntimeError("PinnWire"), 502),
                 (KeyError("bug"), 500), (TypeError("bug"), 500)]
        for error, status in cases:
            with (self.subTest(error=error), contextlib.redirect_stderr(io.StringIO()),
                  mock.patch.dict(dash.SPORT_STATES, {"football": self.FakeState(error)})):
                self.assertEqual(self.request("/api/board")[0], status)

    def test_config_accepts_only_json(self):
        saved = []
        original = dash.save_api_key
        dash.save_api_key = saved.append
        try:
            status, _ = self.request("/api/config", b'{"apiKey": "x"}', "text/plain")
        finally:
            dash.save_api_key = original
        self.assertEqual((status, saved), (415, []))


class PriceHistoryTests(unittest.TestCase):
    match = staticmethod(ClvTests.match)

    def setUp(self):
        self.store = price_history.PriceStore()

    def test_only_changes_are_stored(self):
        self.assertEqual(self.store.observe("football", self.match(2.10), now=1000), 1)
        self.assertEqual(self.store.observe("football", self.match(2.10), now=1030), 0)
        self.assertEqual(self.store.observe("football", self.match(2.05), now=1060), 1)
        [series] = self.store.series("football", 7)
        self.assertEqual((series["period"], series["group"], series["line"], series["key"]),
                         ("ft", "Ukupno golova", 2.5, "over"))
        self.assertEqual(series["points"], [[1000, 1.9, 2.10, 2.0], [1060, 1.9, 2.05, 2.0]])

    def test_annotate_reports_last_change_per_book(self):
        self.store.observe("football", self.match(2.10), now=1000)
        value = {"matchId": 7, "period": "ft", "group": "Ukupno golova", "line": 2.5, "key": "over"}
        self.store.annotate("football", [value])
        self.assertEqual((value["seenAt"], value["pinChangedAt"], value["mxChangedAt"]),
                         (price_history.stamp(1000), None, None))
        self.store.observe("football", self.match(2.05), now=1060)
        self.store.observe("football", self.match(2.05, fair=2.1), now=1090)  # Pinnacle fair moved, price did not
        self.store.annotate("football", [value])
        self.assertEqual((value["pinChangedAt"], value["mxChangedAt"]), (None, price_history.stamp(1060)))

    def test_state_survives_a_restart(self):
        path = os.path.join(tempfile.mkdtemp(), "prices.sqlite3")
        first = price_history.PriceStore(path)
        first.observe("football", self.match(2.10), now=1000)
        first.observe("football", self.match(2.05), now=1060)
        first.db.close()
        second = price_history.PriceStore(path)
        self.assertEqual(second.observe("football", self.match(2.05), now=1090), 0)
        value = {"matchId": 7, "period": "ft", "group": "Ukupno golova", "line": 2.5, "key": "over"}
        second.annotate("football", [value])
        self.assertEqual(value["mxChangedAt"], price_history.stamp(1060))
        second.db.close()

    def test_started_matches_are_pruned(self):
        starts = price_history.stamp(100000)
        self.store.observe("football", self.match(2.10, starts=starts), now=1000)
        self.store.observe("football", self.match(2.10, starts=starts, line=3.5),
                           now=100000 + price_history.KEEP_HOURS * 3600 + price_history.PRUNE_EVERY)
        self.assertEqual(self.store.series("football", 7), [])

    def test_state_board_reports_and_annotates_values(self):
        row = merkur_row(**{"1": 2.55, "2": 3.10, "3": 2.95, "24": 1.95, "22": 1.85})
        state = make_state(FakeAPI([event(1)]), [row])
        state.prices = self.store
        values = state.board()["values"]
        self.assertTrue(values)
        self.assertTrue(all(v["seenAt"] and v["mxChangedAt"] is None for v in values))
        self.assertTrue(self.store.series("football", 1))


if __name__ == "__main__":
    unittest.main()
