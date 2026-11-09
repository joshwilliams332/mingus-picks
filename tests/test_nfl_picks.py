"""Tests for scripts/nfl_picks.py: python3 -m unittest discover -s tests"""

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import nfl_picks as N  # noqa: E402

ET = N.ET


def log(weeks, opp, **stats):
    return [{"week": w, "team": None, "opp": opp, **{k: (v[i] if isinstance(v, list) else v) for k, v in stats.items()}}
            for i, w in enumerate(weeks)]


def make_data(folder, sleeper=None, injury=None):
    """Week 9 SNF: PHI @ WAS, Sun Nov 8 2026 20:20 ET (plus a 1 PM game that must be ignored)."""
    teams = {"PHI": {"city": "Philadelphia", "nickname": "Eagles"}, "WAS": {"city": "Washington", "nickname": "Commanders"},
             "DAL": {"city": "Dallas", "nickname": "Cowboys"}, "NYG": {"city": "New York", "nickname": "Giants"}}
    games = [
        {"id": "2026_09_PHI_WAS", "week": 9, "date": "2026-11-08", "time": "20:20", "away": "PHI", "home": "WAS",
         "home_spread": -3, "home_implied": 24.0, "away_implied": 21.0},
        {"id": "2026_09_DAL_NYG", "week": 9, "date": "2026-11-08", "time": "13:00", "away": "DAL", "home": "NYG",
         "home_spread": 1, "home_implied": 22.0, "away_implied": 23.0},
    ]
    weeks = list(range(1, 9))
    te = {"id": "TE1", "name": "Dallas Goedert", "pos": "TE", "team": "PHI", "injury": injury,
          "log": log(weeks, "NYG", rec_yds=[40, 55, 30, 62, 48, 51, 44, 58], rec=[4, 5, 3, 6, 4, 5, 4, 5], tgt=[5, 6, 4, 7, 5, 6, 5, 6])}
    if sleeper is not None:
        te["proj"] = {"sleeper": {"9": {"line": {"rec_yds": sleeper}}}}
    qb = {"id": "QB1", "name": "Jayden Daniels", "pos": "QB", "team": "WAS", "injury": None,
          "log": log(weeks, "DAL", pass_yds=[230, 250, 210, 270, 240, 220, 260, 245], rush_yds=[30, 40, 20, 35, 25, 45, 30, 38], att=32, car=6)}
    # Defenses: WAS gives up a lot to TEs (the DvP sample).
    opp_te = [{"id": f"X{i}", "name": f"Other TE {i}", "pos": "TE", "team": "NYG", "injury": None,
               "log": log([i], "WAS", rec_yds=90, rec=8, tgt=10)} for i in range(1, 9)]
    other = [{"id": "Y1", "name": "Some TE", "pos": "TE", "team": "DAL", "injury": None, "log": log(weeks, "PHI", rec_yds=30, rec=3, tgt=4)}]
    players = [te, qb, *opp_te, *other]
    meta = {"season": 2026}
    for name, v in (("teams", teams), ("games", games), ("players", players), ("meta", meta)):
        (Path(folder) / f"{name}.json").write_text(json.dumps(v))
    return N.Data(folder)


def event_odds(over=-110, under=-110, line=45.5):
    books = []
    for title, o, u in (("DraftKings", over, under), ("FanDuel", over + 5, under - 5), ("BetMGM", over, under)):
        books.append({"key": title.lower(), "title": title, "markets": [
            {"key": "player_reception_yds", "outcomes": [
                {"name": "Over", "description": "Dallas Goedert", "price": o, "point": line},
                {"name": "Under", "description": "Dallas Goedert", "price": u, "point": line}]},
            {"key": "player_pass_yds", "outcomes": [
                {"name": "Over", "description": "Jayden Daniels", "price": -112, "point": 238.5},
                {"name": "Under", "description": "Jayden Daniels", "price": -108, "point": 238.5}]},
        ]})
    return {"bookmakers": books}


class FakeAPI:
    def __init__(self, odds, remaining=300):
        self.odds, self.usage, self.calls = odds, {"remaining": remaining}, []

    def events(self):
        self.calls.append("events")
        return [{"id": "ev1", "home_team": "Washington Commanders", "away_team": "Philadelphia Eagles",
                 "commence_time": "2026-11-09T01:20:00Z"},
                {"id": "ev2", "home_team": "New York Giants", "away_team": "Dallas Cowboys",
                 "commence_time": "2026-11-08T18:00:00Z"}]

    def props(self, event_id, markets=None):
        self.calls.append(event_id)
        self.markets = list(markets or N.MARKETS)
        self.usage["remaining"] -= len(self.markets)
        return self.odds


def stats_rows(week, rows):
    return [{"week": str(week), "team": t, "player_id": pid, **{k: str(v) for k, v in st.items()}} for pid, t, st in rows]


class Helpers(unittest.TestCase):
    def test_implied_and_payout(self):
        self.assertAlmostEqual(N.implied(-110), 0.5238, places=3)
        self.assertAlmostEqual(N.implied(150), 0.4)
        self.assertAlmostEqual(N.payout(-200), 0.5)
        self.assertAlmostEqual(N.payout(150), 1.5)

    def test_names_match_across_sources(self):
        self.assertEqual(N.norm_name("Amon-Ra St. Brown"), N.norm_name("Amon Ra St Brown"))
        self.assertEqual(N.norm_name("Kenneth Walker III"), "kenneth walker")

    def test_night_games_only(self):
        self.assertTrue(N.is_night({"time": "20:15"}))
        self.assertFalse(N.is_night({"time": "16:25"}))

    def test_slot_label(self):
        self.assertEqual(N.slot_label({"date": "2026-11-08", "time": "20:20"}), "SNF")
        self.assertEqual(N.slot_label({"date": "2026-11-05", "time": "20:15"}), "TNF")
        self.assertEqual(N.slot_label({"date": "2026-11-09", "time": "20:15"}), "MNF")


class Props(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = make_data(self.tmp.name)
        self.game = self.data.game["2026_09_PHI_WAS"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_parse_consensus_and_no_vig(self):
        rows = {r["stat"]: r for r in N.parse_props(event_odds(), self.data, self.game)}
        r = rows["rec_yds"]
        self.assertEqual((r["line"], r["books"]), (45.5, 3))
        self.assertEqual((r["over"], r["book_o"]), (-105, "FanDuel"))   # best over price
        self.assertAlmostEqual(r["fair_o"] + r["fair_u"], 1)
        self.assertAlmostEqual(rows["pass_yds"]["fair_o"], 0.5047, places=3)

    def test_ignores_players_not_in_the_game(self):
        odds = {"bookmakers": [{"title": "DK", "markets": [{"key": "player_receptions", "outcomes": [
            {"name": "Over", "description": "Some TE", "price": -110, "point": 3.5},
            {"name": "Under", "description": "Some TE", "price": -110, "point": 3.5}]}]}]}
        self.assertEqual(N.parse_props(odds, self.data, self.game), [])

    def test_event_match(self):
        ev = N.match_event(self.data, self.game, FakeAPI(None).events())
        self.assertEqual(ev["id"], "ev1")


class Projection(unittest.TestCase):
    def test_model_is_volume_times_efficiency_with_matchup(self):
        with tempfile.TemporaryDirectory() as d:
            data = make_data(d)
            p = N.projection(data, data.by_id["TE1"], "rec_yds", data.game["2026_09_PHI_WAS"], 9)
            x = p["parts"]
            self.assertEqual(p["source"], "Mingus model")
            self.assertAlmostEqual(p["mean"], x["vol"] * x["eff"] * N.MEAN_ADJ["rec_yds"], delta=0.2)
            self.assertGreater(x["f_def_vol"], 1)                 # WAS gives TEs lots of targets...
            self.assertLessEqual(x["f_def_vol"], N.DEF_CAP[1])    # ...capped
            self.assertLess(x["f_imp"], 1)                        # PHI's 21 implied is below the week's average
            self.assertEqual(x["f_script"], 1)                    # game script tested as no help on 2021-2025
            self.assertEqual(p["opp_rank"]["rank"], 1)

    def test_injury_opening_boosts_volume(self):
        with tempfile.TemporaryDirectory() as d:
            data = make_data(d)
            mate = {"id": "WR9", "name": "Out Receiver", "pos": "WR", "team": "PHI", "injury": {"status": "Out"},
                    "log": log(range(1, 9), "NYG", tgt=8, rec=5, rec_yds=60)}
            data.players.append(mate)
            data.by_id["WR9"] = mate
            boost, names = N.openings(data, data.by_id["TE1"], data.game["2026_09_PHI_WAS"], "tgt")
            self.assertGreater(boost, 1)
            self.assertLessEqual(boost, 1.25)
            self.assertEqual(names, ["Out Receiver"])

    def test_sleeper_blended_when_present(self):
        with tempfile.TemporaryDirectory() as d:
            data = make_data(d, sleeper=61.0)
            p = N.projection(data, data.by_id["TE1"], "rec_yds", data.game["2026_09_PHI_WAS"], 9)
            self.assertEqual(p["source"], "Sleeper + Mingus model")
            self.assertAlmostEqual(p["mean"], (61.0 + p["parts"]["mingus"]) / 2, delta=0.1)

    def test_recent_games_count_more(self):
        w = N.decay_weights(5, 4)
        self.assertEqual(w[-1], 1.0)
        self.assertAlmostEqual(w[0], 0.5)                     # four games back counts half
        with tempfile.TemporaryDirectory() as d:
            data = make_data(d)
            te = data.by_id["TE1"]
            for e, t in zip(te["log"], [2, 2, 2, 2, 2, 9, 9, 9]):  # role grew lately
                e["tgt"] = t
            p = N.projection(data, te, "rec_yds", data.game["2026_09_PHI_WAS"], 9)
            self.assertGreater(p["parts"]["vol_base"], (2 * 5 + 9 * 3) / 8)   # above his plain average

    def test_yardage_is_skewed_passing_is_not(self):
        # A line right at the projection: the skewed curve gives the over less than 50% (most games land below the
        # average), passing yards' bell curve gives exactly 50%.
        self.assertLess(N.chance_over({"mean": 50, "sd": 30, "stat": "rec_yds"}, 50), 0.45)
        self.assertAlmostEqual(N.chance_over({"mean": 240, "sd": 70, "stat": "pass_yds"}, 240), 0.5)
        self.assertEqual(N.chance_over({"mean": 3, "sd": 2, "stat": "rec"}, 0), 1.0)

    def test_not_enough_games(self):
        with tempfile.TemporaryDirectory() as d:
            data = make_data(d)
            self.assertIsNone(N.projection(data, data.by_id["TE1"], "rec_yds", data.game["2026_09_PHI_WAS"], 3))


def espn_fake(completed=True, goedert=(6, 52)):
    sb = {"events": [{"id": "e1", "competitions": [{"status": {"type": {"completed": completed}}, "competitors": [
        {"team": {"abbreviation": "WSH"}}, {"team": {"abbreviation": "PHI"}}]}]}]}
    athletes = [{"athlete": {"displayName": "Dallas Goedert"}, "stats": [str(goedert[0]), str(goedert[1]), "8.7", "0", "21", "8"]}] if goedert else []
    summ = {"boxscore": {"players": [{"team": {"abbreviation": "PHI"}, "statistics": [
        {"name": "receiving", "labels": ["REC", "YDS", "AVG", "TD", "LONG", "TGTS"], "athletes": athletes},
        {"name": "rushing", "labels": ["CAR", "YDS", "AVG", "TD", "LONG"], "athletes": [
            {"athlete": {"displayName": "Saquon Barkley"}, "stats": ["15", "1,04", "6.9", "1", "30"]}]}]}]}}
    return lambda url: sb if "scoreboard" in url else summ


class QuickResults(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = make_data(Path(self.tmp.name))
        self.store = Path(self.tmp.name) / "store"
        self.pick = {"id": "a", "gid": "2026_09_PHI_WAS", "pid": "TE1", "name": "Dallas Goedert", "team": "PHI", "opp": "WAS",
                     "week": 9, "stat": "rec_yds", "side": "o", "line": 45.5, "price": -110}
        N.write(self.store / "picks" / "2026-11-08.json", {"season": 2026, "week": 9, "test": False,
                                                           "games": ["2026_09_PHI_WAS"], "picks": [self.pick]})
        self.late = datetime.fromisoformat("2026-11-08T23:45").replace(tzinfo=ET)

    def tearDown(self):
        self.tmp.cleanup()

    def test_waits_for_final_then_grades_once(self):
        self.assertEqual(N.quick_results(self.data, self.store, self.late, "night", espn_fake(completed=False))["state"], "waiting")
        r = N.quick_results(self.data, self.store, self.late, "night", espn_fake())
        self.assertEqual((r["state"], r["record"]), ("done", "1-0"))
        doc = json.loads((self.store / "picks" / "2026-11-08-quick.json").read_text())
        self.assertTrue(doc["unofficial"])
        self.assertIn("✅ Dallas Goedert O 45.5 rec yds (52)", doc["post"]["main"])
        self.assertIn("1-800-GAMBLER", doc["post"]["main"])
        self.assertIn("unofficial", doc["email"]["subject"])
        self.assertEqual(N.locked_days(self.store / "picks"), ["2026-11-08"])     # never mistaken for a locked day
        self.assertEqual(N.quick_results(self.data, self.store, self.late, "night", espn_fake(goedert=(1, 3)))["state"], "done")

    def test_missing_player_is_check_not_void(self):
        N.quick_results(self.data, self.store, self.late, "night", espn_fake(goedert=None))
        doc = json.loads((self.store / "picks" / "2026-11-08-quick.json").read_text())
        self.assertEqual(doc["results"][0]["status"], "check")
        self.assertEqual(doc["record"]["w"] + doc["record"]["l"], 0)

    def test_espn_parsing(self):
        box = N.espn_box(espn_fake()("summary"))
        self.assertEqual(box[("PHI", "dallas goedert")]["receiving_yards"], 52.0)
        self.assertEqual(box[("PHI", "saquon barkley")]["rushing_yards"], 104.0)   # "1,04"-style thousands commas stripped


class Touchdowns(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = make_data(Path(self.tmp.name))
        self.game = self.data.game["2026_09_PHI_WAS"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_more_red_zone_work_and_points_mean_more_tds(self):
        te = self.data.by_id["TE1"]
        base = N.td_chance(self.data, te, self.game)["p"]
        for e in te["log"]:
            e["rz_tgt"] = 2
        self.data._rz = None
        more = N.td_chance(self.data, te, self.game)["p"]
        self.assertGreater(more, base)
        self.game["away_implied"] = 30.0
        self.assertGreater(N.td_chance(self.data, te, self.game)["p"], more)

    def test_needs_three_games_and_counts_only_rush_rec(self):
        te = self.data.by_id["TE1"]
        self.assertIsNone(N.td_chance(self.data, te, {**self.game, "week": 3}))
        self.assertIsNone(N.td_chance(self.data, {**te, "pos": "K"}, self.game))
        p = N.td_chance(self.data, te, self.game)["p"]
        for e in te["log"]:
            e["pass_td"] = 3                                # passing TDs aren't anytime TDs
        self.assertEqual(N.td_chance(self.data, te, self.game)["p"], p)

    def test_fair_price(self):
        self.assertEqual(N.fair_price(0.5), -100)
        self.assertEqual(N.fair_price(0.25), 300)
        self.assertEqual(N.fair_price(0.6), -150)


class LockAndGrade(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = make_data(Path(self.tmp.name))
        self.store = Path(self.tmp.name) / "store"

    def tearDown(self):
        self.tmp.cleanup()

    def at(self, hhmm, day="2026-11-08"):
        return datetime.fromisoformat(f"{day}T{hhmm}").replace(tzinfo=ET)

    def test_sunday_games_lock_saturday_night(self):
        api = FakeAPI(event_odds())
        sat = lambda t: self.at(t, "2026-11-07")
        r = N.lock(self.data, self.store, sat("18:30"), api, day="2026-11-08")
        self.assertEqual(r["state"], "waiting")
        self.assertIn("7 PM", r["why"])
        self.assertEqual(api.calls, [])                         # no credits spent while waiting
        self.assertEqual(N.lock(self.data, self.store, sat("19:05"), api, day="2026-11-08")["state"], "locked")
        doc = json.loads((self.store / "picks" / "2026-11-08.json").read_text())
        self.assertEqual(doc["date"], "2026-11-08")              # filed under the game's date, not Saturday's
        self.assertIn("before inactives", doc["email"]["html"])

    def test_lock_times(self):
        g = lambda d, t: {"date": d, "time": t}
        opens = lambda d, t: N.lock_opens([g(d, t)]).strftime("%a %H:%M")
        self.assertEqual(opens("2026-11-05", "20:15"), "Thu 09:00")     # TNF: Thursday morning
        self.assertEqual(opens("2026-11-08", "13:00"), "Sat 19:00")     # every Sunday game: Saturday night
        self.assertEqual(opens("2026-11-08", "16:25"), "Sat 19:00")
        self.assertEqual(opens("2026-11-08", "20:20"), "Sat 19:00")
        self.assertEqual(opens("2026-11-09", "20:15"), "Mon 09:00")     # MNF: Monday morning
        self.assertEqual(opens("2026-12-19", "20:00"), "Sat 09:00")     # late-season Saturday night: that morning

    def test_no_night_games(self):
        self.assertEqual(N.lock(self.data, self.store, self.at("17:00", "2026-11-10"), FakeAPI(None))["state"], "no-games")

    def test_locks_once_and_pulls_once(self):
        api = FakeAPI(event_odds(over=110, under=-140, line=45.5))   # over is a plus price; we project well above 45.5
        r = N.lock(self.data, self.store, self.at("17:00"), api)
        self.assertEqual(r["state"], "locked")
        doc = json.loads((self.store / "picks" / "2026-11-08.json").read_text())
        self.assertFalse(doc["test"])
        self.assertTrue(all(p["gid"] == "2026_09_PHI_WAS" for p in doc["picks"]))
        self.assertLessEqual(len(doc["picks"]), N.PICK["per_game"])
        self.assertIn("1-800-GAMBLER", doc["post"]["main"])
        self.assertLessEqual(N.post_length(doc["post"]["main"]), 280)
        self.assertTrue(doc["email"]["subject"].startswith("🏈 SNF picks"))
        if doc["picks"]:
            self.assertIn("Deep dive", doc["email"]["html"])
            self.assertTrue(all(len(f"{N.short(p)}: {p['why']}") <= 280 for p in doc["picks"]))
        before = list(api.calls)
        again = N.lock(self.data, self.store, self.at("17:30"), api)
        self.assertEqual(again["why"], "already locked")
        self.assertEqual(api.calls, before)                       # never re-pulled or rewritten

    def test_sunday_1pm_slate_locks_separately_with_two_markets(self):
        odds = event_odds(over=110, under=-140)
        for b in odds["bookmakers"]:                      # the DAL @ NYG game: Some TE (DAL) receiving yards
            b["markets"].append({"key": "player_reception_yds", "outcomes": [
                {"name": "Over", "description": "Some TE", "price": -110, "point": 20.5},
                {"name": "Under", "description": "Some TE", "price": -110, "point": 20.5}]})
        api = FakeAPI(odds)
        sat = self.at("19:10", "2026-11-07")
        self.assertEqual(N.lock(self.data, self.store, sat, api, slate="late", day="2026-11-08")["state"], "no-games")
        r = N.lock(self.data, self.store, sat, api, slate="early", day="2026-11-08")
        self.assertEqual(r["state"], "locked")
        self.assertEqual(api.calls, ["events", "ev2"])            # only the 1 PM game, never the night game
        self.assertEqual(api.markets, list(N.DAY_MARKETS))        # 2 credits, not 4
        doc = json.loads((self.store / "picks" / "sun-early" / "2026-11-08.json").read_text())
        self.assertEqual((doc["slate"], doc["games"], doc["test"]), ("early", ["2026_09_DAL_NYG"], False))
        self.assertLessEqual(len(doc["picks"]), N.DAY_MAX_PICKS)
        self.assertIn("Sunday 1 PM games", doc["post"]["main"])
        self.assertIn("1-800-GAMBLER", doc["post"]["main"])
        self.assertFalse((self.store / "picks" / "2026-11-08.json").exists())   # the night slate is untouched
        self.assertEqual(N.lock(self.data, self.store, self.at("10:00"), api, slate="early")["why"], "already locked")
        self.assertEqual(N.lock(self.data, self.store, sat, api, day="2026-11-08")["state"], "locked")   # night locks too
        self.assertEqual(api.markets, list(N.MARKETS))

    def test_sunday_email_waits_for_every_slate_then_writes_once(self):
        odds = event_odds(over=110, under=-140)
        for b in odds["bookmakers"]:
            b["markets"].append({"key": "player_reception_yds", "outcomes": [
                {"name": "Over", "description": "Some TE", "price": -110, "point": 20.5},
                {"name": "Under", "description": "Some TE", "price": -110, "point": 20.5}]})
        api = FakeAPI(odds)
        sat = lambda t: self.at(t, "2026-11-07")
        self.assertEqual(N.sunday_preview(self.data, self.store, sat("19:10"))["state"], "waiting")
        N.lock(self.data, self.store, sat("19:10"), api, day="2026-11-08")              # night locked, 1 PM not yet
        self.assertEqual(N.sunday_preview(self.data, self.store, sat("19:10"))["state"], "waiting")
        N.lock(self.data, self.store, sat("19:40"), api, slate="early", day="2026-11-08")
        r = N.sunday_preview(self.data, self.store, sat("19:40"))
        self.assertEqual(r["state"], "done")
        doc = json.loads((self.store / "picks" / "sunday" / "2026-11-08.json").read_text())
        self.assertEqual(doc["slates"], ["early", "night"])
        html = doc["email"]["html"]
        self.assertLess(html.index("Sunday 1 PM"), html.index("Sunday night · PHI @ WAS"))   # split by time slot
        self.assertIn("1-800-GAMBLER", doc["email"]["text"])
        self.assertTrue(doc["email"]["subject"].startswith("🏈 Sunday picks · Sun 11/8"))
        self.assertEqual(N.sunday_preview(self.data, self.store, sat("20:10"))["state"], "done")
        self.assertEqual(N.sunday_preview(self.data, self.store, self.at("12:00", "2026-11-05"))["state"], "none")

    def test_sunday_email_goes_out_late_saturday_with_what_locked(self):
        N.lock(self.data, self.store, self.at("19:10", "2026-11-07"), FakeAPI(event_odds()), day="2026-11-08")
        self.assertEqual(N.sunday_preview(self.data, self.store, self.at("23:10", "2026-11-07"))["state"], "waiting")
        self.assertEqual(N.sunday_preview(self.data, self.store, self.at("23:40", "2026-11-07"))["state"], "done")
        doc = json.loads((self.store / "picks" / "sunday" / "2026-11-08.json").read_text())
        self.assertEqual(doc["pending"], ["early"])
        self.assertIn("Not locked yet: Sunday 1 PM", doc["email"]["text"])

    def test_day_results_and_record_kept_apart(self):
        day_dir = self.store / "picks" / "sun-early"
        pick = {"id": "d", "gid": "2026_09_DAL_NYG", "pid": "Y1", "name": "Some TE", "team": "DAL", "opp": "NYG", "week": 9,
                "stat": "rec_yds", "side": "u", "line": 20.5, "price": -110}
        N.write(day_dir / "2026-11-08.json", {"season": 2026, "week": 9, "test": False, "slate": "early",
                                              "games": ["2026_09_DAL_NYG"], "picks": [pick]})
        rows = stats_rows(9, [("Y1", "DAL", {"receiving_yards": 12})])
        r = N.night_results(self.data, self.store, rows, self.at("09:30", "2026-11-09"), slate="early")
        self.assertEqual((r["state"], r["record"]), ("done", "1-0 (+0.9u)"))
        doc = json.loads((day_dir / "2026-11-08-results.json").read_text())
        self.assertIn("Sunday 1 PM results (1 game)", doc["post"]["main"])
        self.assertIn("Sundays: 1-0", doc["post"]["main"])
        self.assertEqual(json.loads((self.store / "picks" / "sunday-record.json").read_text())["season"]["w"], 1)
        N.recap(self.data, self.store, rows, self.at("12:00", "2026-11-10"))   # the night record never sees day picks
        self.assertEqual(json.loads((self.store / "picks" / "record.json").read_text())["season"]["w"], 0)

    def test_sunday_slates(self):
        slate = lambda t, d="2026-11-08": N.day_slate({"date": d, "time": t})
        self.assertEqual([slate("13:00"), slate("15:00"), slate("16:05"), slate("16:25")], ["early", "early", "late", "late"])
        self.assertIsNone(slate("09:30"))                 # London
        self.assertIsNone(slate("20:20"))                 # SNF is the night slate
        self.assertIsNone(slate("13:00", "2026-11-26"))   # Thanksgiving Thursday

    def test_injured_player_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            data = make_data(d, injury={"status": "Questionable"})
            rows = N.parse_props(event_odds(over=110, under=-140), data, data.game["2026_09_PHI_WAS"])
            self.assertFalse(any(c["player"]["id"] == "TE1" for c in N.candidates(data, data.game["2026_09_PHI_WAS"], rows)))

    def test_far_from_market_is_skipped(self):
        game = self.data.game["2026_09_PHI_WAS"]
        rows = N.parse_props(event_odds(line=150.5), self.data, game)   # a line we'd call a near-certain under
        self.assertFalse([c for c in N.candidates(self.data, game, rows) if c["row"]["stat"] == "rec_yds"])

    def test_keeps_credit_reserve(self):
        r = N.lock(self.data, self.store, self.at("17:00"), FakeAPI(event_odds(), remaining=12))
        self.assertEqual(r["state"], "no-credits")

    def test_grade(self):
        pick = {"pid": "TE1", "team": "PHI", "opp": "WAS", "week": 9, "stat": "rec_yds", "side": "o", "line": 45.5, "price": -110}
        rows = stats_rows(9, [("TE1", "PHI", {"receiving_yards": 52}), ("QB1", "WAS", {"passing_yards": 240})])
        self.assertEqual(N.grade(pick, rows)["status"], "win")
        self.assertAlmostEqual(N.grade(pick, rows)["profit"], 0.909, places=3)
        self.assertEqual(N.grade({**pick, "side": "u"}, rows)["profit"], -1)
        self.assertEqual(N.grade(pick, stats_rows(9, [("QB1", "WAS", {"passing_yards": 240})]))["status"], "void")
        self.assertEqual(N.grade(pick, [])["status"], "open")

    def test_recap_written_once_and_test_week_not_counted(self):
        dir_ = self.store / "picks"
        pick = {"id": "a", "gid": "2026_09_PHI_WAS", "pid": "TE1", "name": "Dallas Goedert", "team": "PHI", "opp": "WAS", "week": 9,
                "stat": "rec_yds", "side": "o", "line": 45.5, "price": -110}
        N.write(dir_ / "2026-11-08.json", {"season": 2026, "week": 9, "test": False, "picks": [pick]})
        N.write(dir_ / "2026-11-01.json", {"season": 2026, "week": 8, "test": True, "picks": [{**pick, "week": 8, "id": "t"}]})
        rows = stats_rows(9, [("TE1", "PHI", {"receiving_yards": 60})]) + stats_rows(8, [("TE1", "PHI", {"receiving_yards": 10})])
        # Before the week's night games are over, nothing is written.
        self.assertEqual(N.recap(self.data, self.store, rows, self.at("19:00"))["state"], "waiting")
        r = N.recap(self.data, self.store, rows, self.at("12:00", "2026-11-10"))
        self.assertEqual(r["state"], "done")
        doc = json.loads((dir_ / "week-09-recap.json").read_text())
        self.assertEqual(doc["season_record"]["w"], 1)
        self.assertEqual(doc["season_record"]["l"], 0)       # the week-8 test loss isn't counted
        self.assertIn("Season: 1-0", doc["post"]["main"])
        test_doc = json.loads((dir_ / "week-08-recap.json").read_text())
        self.assertTrue(test_doc["test"])
        self.assertNotIn("Season:", test_doc["post"]["main"])
        mtime = (dir_ / "week-09-recap.json").stat().st_mtime_ns
        N.recap(self.data, self.store, rows, self.at("13:00", "2026-11-10"))
        self.assertEqual((dir_ / "week-09-recap.json").stat().st_mtime_ns, mtime)

    def test_night_results_written_once_after_grading(self):
        dir_ = self.store / "picks"
        pick = {"id": "a", "gid": "2026_09_PHI_WAS", "pid": "TE1", "name": "Dallas Goedert", "team": "PHI", "opp": "WAS", "week": 9,
                "stat": "rec_yds", "side": "o", "line": 45.5, "price": -110}
        N.write(dir_ / "2026-11-08.json", {"season": 2026, "week": 9, "test": False, "games": ["2026_09_PHI_WAS"], "picks": [pick]})
        self.assertEqual(N.night_results(self.data, self.store, [], self.at("19:00"))["state"], "waiting")
        self.assertEqual(N.night_results(self.data, self.store, [], self.at("09:00", "2026-11-09"))["state"], "pending")
        rows = stats_rows(9, [("TE1", "PHI", {"receiving_yards": 60})])
        r = N.night_results(self.data, self.store, rows, self.at("09:30", "2026-11-09"))
        self.assertEqual((r["state"], r["record"]), ("done", "1-0 (+0.9u)"))
        doc = json.loads((dir_ / "2026-11-08-results.json").read_text())
        self.assertIn("SNF results", doc["post"]["main"])
        self.assertIn("✅ Dallas Goedert O 45.5 rec yds (60)", doc["post"]["main"])
        self.assertIn("Season: 1-0", doc["post"]["main"])
        self.assertIn("1-800-GAMBLER", doc["post"]["main"])
        self.assertEqual(N.locked_days(dir_), ["2026-11-08"])      # results files aren't mistaken for locked nights
        self.assertEqual(N.night_results(self.data, self.store, rows, self.at("10:00", "2026-11-09"))["state"], "done")


if __name__ == "__main__":
    unittest.main()



class SundayResults(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = make_data(Path(self.tmp.name))
        self.store = Path(self.tmp.name) / "store"
        night = {"id": "a", "gid": "2026_09_PHI_WAS", "pid": "TE1", "name": "Dallas Goedert", "team": "PHI", "opp": "WAS",
                 "week": 9, "stat": "rec_yds", "side": "o", "line": 45.5, "price": -110}
        early = {"id": "d", "gid": "2026_09_DAL_NYG", "pid": "Y1", "name": "Some TE", "team": "DAL", "opp": "NYG",
                 "week": 9, "stat": "rec_yds", "side": "u", "line": 20.5, "price": -110}
        N.write(self.store / "picks" / "2026-11-08.json", {"season": 2026, "week": 9, "test": False, "slate": "night",
                                                           "games": ["2026_09_PHI_WAS"], "picks": [night]})
        N.write(self.store / "picks" / "sun-early" / "2026-11-08.json", {"season": 2026, "week": 9, "test": False,
                "slate": "early", "games": ["2026_09_DAL_NYG"], "picks": [early]})

    def tearDown(self):
        self.tmp.cleanup()

    def quick(self, folder, rec):
        N.write(self.store / "picks" / folder / "2026-11-08-quick.json",
                {"record": rec, "post": {"main": f"results {folder or 'night'}\nFor entertainment. 21+ · Gamble responsibly · 1-800-GAMBLER"}})

    def test_sunday_day(self):
        at = lambda s: datetime.fromisoformat(s).replace(tzinfo=ET)
        self.assertEqual(N.sunday_day(at("2026-11-08T23:50")), "2026-11-08")
        self.assertEqual(N.sunday_day(at("2026-11-09T00:40")), "2026-11-08")    # the night game ran past midnight
        self.assertIsNone(N.sunday_day(at("2026-11-09T09:00")))

    def test_one_email_after_the_night_game(self):
        now = datetime.fromisoformat("2026-11-08T17:30").replace(tzinfo=ET)
        self.quick("sun-early", {"w": 1, "l": 0, "p": 0, "profit": 0.909})
        self.assertEqual(N.sunday_results(self.data, self.store, now, "2026-11-08")["state"], "waiting")   # night not graded
        self.quick("", {"w": 0, "l": 1, "p": 0, "profit": -1.0})
        r = N.sunday_results(self.data, self.store, now, "2026-11-08")
        self.assertEqual((r["state"], r["record"]), ("done", "1-1"))
        doc = json.loads((self.store / "picks" / "sunday" / "2026-11-08-results.json").read_text())
        self.assertIn("Sunday results (unofficial) · Sun 11/8 · 1-1", doc["email"]["subject"])
        text = doc["email"]["text"]
        self.assertLess(text.index("Sunday 1 PM"), text.index("Sunday night · PHI @ WAS"))
        self.assertIn("1-800-GAMBLER", text)
        self.assertEqual(N.sunday_results(self.data, self.store, now, "2026-11-08")["state"], "done")
        self.assertEqual(N.sunday_results(self.data, self.store, now, None)["state"], "none")


def espn_injury_fake(phi=(), was=()):
    sb = {"events": [{"id": "e1", "competitions": [{"competitors": [
        {"team": {"abbreviation": "WSH"}}, {"team": {"abbreviation": "PHI"}}]}]}]}
    side = lambda abbr, rows: {"team": {"abbreviation": abbr}, "injuries": [
        {"status": st, "athlete": {"displayName": name, "position": {"abbreviation": pos}}} for name, pos, st in rows]}
    summ = {"injuries": [side("PHI", phi), side("WSH", was)]}
    return lambda url: sb if "scoreboard" in url else summ


class HeadsUp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = make_data(Path(self.tmp.name))
        wr = {"id": "WR1", "name": "A.J. Brown", "pos": "WR", "team": "PHI", "injury": {"status": "Questionable"}, "log": []}
        self.data.by_id["WR1"] = wr
        self.store = Path(self.tmp.name) / "store"
        self.pick = {"id": "a", "gid": "2026_09_PHI_WAS", "pid": "TE1", "name": "Dallas Goedert", "team": "PHI", "opp": "WAS",
                     "week": 9, "stat": "rec_yds", "side": "o", "line": 45.5, "price": -110}
        N.write(self.store / "picks" / "2026-11-08.json", {"season": 2026, "week": 9, "test": False, "slate": "night",
                                                           "games": ["2026_09_PHI_WAS"], "picks": [self.pick]})
        N.write(self.store / "odds" / "props" / "2026_09_PHI_WAS.json", {"rows": [
            {"pid": "TE1", "stat": "rec_yds"}, {"pid": "WR1", "stat": "rec_yds"}, {"pid": "QB1", "stat": "pass_yds"}]})

    def tearDown(self):
        self.tmp.cleanup()

    def at(self, hhmm):
        return datetime.fromisoformat(f"2026-11-08T{hhmm}").replace(tzinfo=ET)

    def doc(self):
        return json.loads((self.store / "picks" / "headsup" / "2026-11-08-night.json").read_text())

    def test_waits_for_inactives_then_writes_once(self):
        fake = espn_injury_fake()
        self.assertEqual(N.headsup(self.data, self.store, self.at("18:30"), "night", fake)["state"], "waiting")
        r = N.headsup(self.data, self.store, self.at("19:05"), "night", fake)
        self.assertEqual((r["state"], r["affected"], r["changed"]), ("done", 0, False))
        self.assertNotIn("email", self.doc())                   # nothing to say: no email
        self.assertEqual(N.headsup(self.data, self.store, self.at("19:30"), "night", fake)["state"], "done")

    def test_teammate_out_and_cleared_players(self):
        fake = espn_injury_fake(phi=[("A.J. Brown", "WR", "Out")], was=[("Jayden Daniels", "QB", "Active")])
        r = N.headsup(self.data, self.store, self.at("19:05"), "night", fake)
        self.assertEqual((r["affected"], r["changed"]), (1, True))
        self.assertIn("SNF update", self.doc()["email"]["subject"])
        self.assertIn("1-800-GAMBLER", self.doc()["email"]["text"])
        text = self.doc()["email"]["text"]
        self.assertIn("teammate A.J. Brown (WR) out. More targets could go his way (helps the over)", text)
        self.assertIn("PHI: A.J. Brown (WR)", text)

    def test_pick_player_out_is_a_void(self):
        fake = espn_injury_fake(phi=[("Dallas Goedert", "TE", "Out")])
        N.headsup(self.data, self.store, self.at("19:05"), "night", fake)
        self.assertIn("Graded as a void", self.doc()["email"]["text"])

    def test_too_late_or_nothing_locked(self):
        self.assertEqual(N.headsup(self.data, self.store, self.at("20:30"), "night", espn_injury_fake())["state"], "missed")
        self.assertEqual(N.headsup(self.data, self.store, self.at("12:00"), "early", espn_injury_fake())["state"], "none")


class WhyLine(unittest.TestCase):
    def test_under_with_average_above_the_line_explains_itself(self):
        c = {"row": {"stat": "rec_yds", "line": 19.5}, "side": "u", "model": 0.64, "player": {"pos": "RB", "team": "IND"},
             "proj": {"mean": 20.2, "parts": {}, "vals": [12, 9, 50, 14, 11]}}
        w = N.why_line(c)
        self.assertIn("gives the under a 64% chance", w)
        self.assertNotIn("projects 20.2 vs the 19.5 line", w)
