import unittest

import merkur_client as mx
import pinnwire_client as pw
import pinnwire_dashboard as dash


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

    def prematch_snapshot(self, sport_id, since=None):
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


class ClientTests(unittest.TestCase):
    def test_devig_power_sums_to_one_and_removes_margin(self):
        odds = {"home": 2.45, "draw": 3.30, "away": 2.90}
        probs = pw.devig(odds)
        self.assertAlmostEqual(sum(probs.values()), 1.0, places=6)
        for side, p in probs.items():
            self.assertGreater(1 / p, odds[side])
        fair, margin = pw.fair_odds(odds)
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
        self.assertEqual(mx.name_score("Chelsea", "Arsenal"), 0.0)

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
        merged = dash.merge_event(old, new)
        self.assertEqual(merged["periods"]["num_0"]["totals"], {})
        self.assertIn("money_line", merged["periods"]["num_0"])
        self.assertEqual(merged["home"], "Alaves")


if __name__ == "__main__":
    unittest.main()
