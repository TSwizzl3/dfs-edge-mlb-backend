import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class AdminIngestionTests(unittest.TestCase):
    def test_player_name_matching_ignores_accents(self):
        self.assertEqual(
            main.normalized_player_name("Cristopher Sánchez"),
            main.normalized_player_name("Cristopher Sanchez"),
        )

    def test_imported_slate_never_falls_back_to_samples(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            active_path = Path(temp_dir) / "active.json"
            sample_path = Path(temp_dir) / "sample.json"
            active_path.write_text(json.dumps([{"name": "Only Slate Player"}]), encoding="utf-8")
            sample_path.write_text(json.dumps([{"name": "Wrong Sample Player"}] * 10), encoding="utf-8")
            with patch.object(main, "ACTIVE_SLATE_PATH", active_path), patch.object(main, "SAMPLE_PLAYERS_PATH", sample_path):
                loaded = main.load_players()
                self.assertEqual(len(loaded), 1)
                self.assertEqual(loaded[0]["name"], "Only Slate Player")
                self.assertNotEqual(loaded[0]["name"], "Wrong Sample Player")

    def test_likely_starter_filter_keeps_one_pitcher_per_team(self):
        players = [
            {"name": "Likely Starter", "position": "P", "team": "PHI", "salary": 9500, "projection": 22, "active": True},
            {"name": "Reliever", "position": "P", "team": "PHI", "salary": 4500, "projection": 6, "active": True},
            {"name": "Other Starter", "position": "P", "team": "ATL", "salary": 9000, "projection": 20, "active": True},
        ]
        filtered = main.apply_slate_starter_likelihood(players)
        active_pitchers = [p for p in filtered if p["active"]]
        self.assertEqual({p["name"] for p in active_pitchers}, {"Likely Starter", "Other Starter"})
        self.assertEqual(next(p for p in filtered if p["name"] == "Reliever")["inactive_reason"], "not_probable_starting_pitcher")

    def test_optimizer_pool_never_reintroduces_inactive_bench_player(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            active_path = Path(temp_dir) / "active.json"
            active_path.write_text("[]", encoding="utf-8")
            players = [
                {
                    "name": "Confirmed Bat", "position": "OF", "team": "PHI", "salary": 5000,
                    "active": True, "starter_status": "confirmed_starter", "starter_source": "mlb_stats_confirmed_lineup",
                    "starter_probability": 1.0,
                },
                {
                    "name": "Bench Bat", "position": "OF", "team": "PHI", "salary": 4000,
                    "active": False, "starter_status": "bench_risk", "starter_source": "dk_slate_likelihood",
                    "starter_probability": 0.2,
                },
            ]
            with patch.object(main, "ACTIVE_SLATE_PATH", active_path):
                pool, report = main.build_optimizer_pool_with_fallback(players)
            self.assertEqual([p["name"] for p in pool], ["Confirmed Bat"])
            self.assertFalse(report["fallback_used"])

    def test_same_team_pitchers_are_rejected(self):
        lineup = [
            {"name": "P1", "position": "P", "team": "PHI"},
            {"name": "P2", "position": "P", "team": "PHI"},
        ]
        self.assertTrue(main.same_team_pitcher_conflict(lineup))

    def test_live_refresh_applies_probable_pitcher_and_confirmed_order(self):
        schedule = {
            "dates": [{"games": [{
                "gamePk": 123,
                "teams": {
                    "away": {"team": {"abbreviation": "PHI"}, "probablePitcher": {"fullName": "Cristopher Sánchez"}},
                    "home": {"team": {"abbreviation": "ATL"}, "probablePitcher": {"fullName": "Spencer Strider"}},
                },
            }]}]
        }
        boxscore = {
            "teams": {
                "away": {"battingOrder": [10], "players": {"ID10": {"person": {"fullName": "Trea Turner"}}}},
                "home": {"battingOrder": [], "players": {}},
            }
        }
        players = [
            {"name": "Cristopher Sanchez", "position": "P", "team": "PHI", "salary": 9500, "projection": 21, "active": True},
            {"name": "PHI Relief", "position": "P", "team": "PHI", "salary": 5000, "projection": 5, "active": True},
            {"name": "Trea Turner", "position": "SS", "team": "PHI", "salary": 6000, "projection": 11, "active": True},
            {"name": "Bench Bat", "position": "OF", "team": "PHI", "salary": 3000, "projection": 4, "active": True},
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            active_path = Path(temp_dir) / "active.json"
            state_path = Path(temp_dir) / "state.json"
            active_path.write_text("[]", encoding="utf-8")
            with patch.object(main, "ACTIVE_SLATE_PATH", active_path), patch.object(main, "MLB_STARTER_STATE_PATH", state_path), patch.object(
                main, "fetch_mlb_stats_json", side_effect=[schedule, boxscore]
            ), patch.object(main, "fetch_mlb_roster_statuses", return_value=({}, {})):
                refreshed, state = main.refresh_mlb_starters(players, "2026-08-23")

        by_name = {p["name"]: p for p in refreshed}
        self.assertTrue(by_name["Cristopher Sanchez"]["active"])
        self.assertEqual(by_name["Cristopher Sanchez"]["starter_source"], "mlb_stats_probable_pitcher")
        self.assertFalse(by_name["PHI Relief"]["active"])
        self.assertEqual(by_name["Trea Turner"]["lineup_spot"], 1)
        self.assertFalse(by_name["Bench Bat"]["active"])
        self.assertEqual(state["probable_pitcher_matches"], 1)
        self.assertEqual(state["confirmed_hitter_matches"], 1)

    def test_official_il_status_overrides_likely_starter_projection(self):
        schedule = {
            "dates": [{"games": [{
                "gamePk": 321,
                "teams": {
                    "away": {"team": {"id": 143, "abbreviation": "PHI"}},
                    "home": {"team": {"id": 144, "abbreviation": "ATL"}},
                },
            }]}]
        }
        boxscore = {"teams": {"away": {"battingOrder": [], "players": {}}, "home": {"battingOrder": [], "players": {}}}}
        players = [
            {"name": "Injured Star", "position": "OF", "team": "PHI", "salary": 6200, "projection": 13, "active": True},
            {"name": "Healthy Bat", "position": "OF", "team": "PHI", "salary": 5000, "projection": 10, "active": True},
        ]
        roster_statuses = {"PHI": {main.normalized_player_name("Injured Star"): "Injured 10-Day"}}
        with tempfile.TemporaryDirectory() as temp_dir:
            active_path = Path(temp_dir) / "active.json"
            state_path = Path(temp_dir) / "state.json"
            active_path.write_text("[]", encoding="utf-8")
            with patch.object(main, "ACTIVE_SLATE_PATH", active_path), patch.object(main, "MLB_STARTER_STATE_PATH", state_path), patch.object(
                main, "fetch_mlb_stats_json", side_effect=[schedule, boxscore]
            ), patch.object(main, "fetch_mlb_roster_statuses", return_value=(roster_statuses, {})):
                refreshed, state = main.refresh_mlb_starters(players, "2026-08-23")

        injured = next(player for player in refreshed if player["name"] == "Injured Star")
        self.assertFalse(injured["active"])
        self.assertEqual(injured["injury_status"], "il")
        self.assertEqual(injured["starter_probability"], 0.0)
        self.assertEqual(injured["roster_status"], "Injured 10-Day")
        self.assertEqual(state["official_unavailable_matches"], 1)

    def test_sixth_hitter_from_same_team_is_rejected(self):
        def hitter(name, position):
            return {
                "name": name, "position": position, "team": "PHI", "salary": 4000,
                "active": True, "starter_status": "confirmed_starter",
                "starter_source": "mlb_stats_confirmed_lineup", "starter_probability": 1.0,
            }

        lineup = [
            hitter("C", "C"), hitter("1B", "1B"), hitter("2B", "2B"),
            hitter("3B", "3B"), hitter("SS", "SS"),
        ]
        candidate = hitter("OF", "OF")
        with tempfile.TemporaryDirectory() as temp_dir:
            active_path = Path(temp_dir) / "active.json"
            active_path.write_text("[]", encoding="utf-8")
            with patch.object(main, "ACTIVE_SLATE_PATH", active_path):
                self.assertFalse(main.v4_can_add(lineup, candidate, max_players_per_team=6))

    def test_central_admin_token_is_authorized(self):
        payload = {
            "success": True,
            "user": {"email": main.ADMIN_EMAIL, "role": "admin"},
        }
        with patch.object(main.urllib.request, "urlopen", return_value=FakeResponse(payload)):
            self.assertTrue(main.is_admin_token("verified-central-token"))

    def test_projection_csv_parses_optional_accuracy_fields(self):
        rows = main.parse_projection_csv(
            "Name,Projection,Ownership,Ceiling,Floor\n"
            "Shohei Ohtani,12.4,19.5%,28.0,3.2\n"
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Shohei Ohtani")
        self.assertEqual(rows[0]["ownership"], 19.5)
        self.assertEqual(rows[0]["ceiling"], 28.0)
        self.assertEqual(rows[0]["floor"], 3.2)

    def test_payout_csv_supports_rank_ranges(self):
        tiers = main.parse_payout_csv(
            "Rank,Payout\n1,$1000\n2-5,$250\n6-10,$75\n"
        )
        self.assertEqual(tiers[1], {"start_rank": 2, "end_rank": 5, "payout": 250.0})

    def test_uploaded_payout_table_drives_contest_math(self):
        tiers = [
            {"start_rank": 1, "end_rank": 1, "payout": 1000.0},
            {"start_rank": 2, "end_rank": 10, "payout": 50.0},
        ]
        request = main.ContestSimulationRequest(
            contest_size=100,
            paid_positions=20,
            payout_rate=0.2,
        )
        with patch.object(main, "load_payout_table", return_value=tiers):
            contest = main.normalize_contest_request(request)
            self.assertEqual(contest["paid_positions"], 10)
            self.assertEqual(contest["payout_source"], "uploaded_exact_table")
            self.assertEqual(main.payout_for_rank(5, contest), 50.0)
            self.assertEqual(main.payout_for_rank(11, contest), 0.0)

    def test_contest_library_payouts_override_legacy_table(self):
        tiers = [
            {"start_rank": 1, "end_rank": 1, "payout": 50000.0},
            {"start_rank": 2, "end_rank": 100, "payout": 75.0},
        ]
        request = main.ContestSimulationRequest(
            contest_profile_id="shared-mlb-contest",
            contest_profile_name="MLB Featured GPP",
            contest_size=5000,
            paid_positions=1000,
            payout_tiers=tiers,
        )
        with patch.object(main, "load_payout_table", return_value=[]):
            contest = main.normalize_contest_request(request)
        self.assertEqual(contest["payout_source"], "contest_library_exact_table")
        self.assertEqual(contest["paid_positions"], 100)
        self.assertEqual(contest["contest_profile_name"], "MLB Featured GPP")

    def test_contest_ownership_overrides_are_applied(self):
        lineup = {"lineup": [{"name": "Shohei Ohtani", "ownership": 15.0}]}
        main.apply_contest_ownership_overrides([lineup], {"Shohei Ohtani": 31.2})
        self.assertEqual(lineup["lineup"][0]["ownership"], 31.2)
        self.assertEqual(lineup["lineup"][0]["ownership_source"], "contest_library")

    def test_real_results_produce_position_backtest(self):
        players = [
            {
                "name": "Pitcher One",
                "position": "P",
                "projection": 20,
                "floor": 8,
                "ceiling": 35,
                "projection_model_version": "test",
            },
            {
                "name": "Hitter One",
                "position": "OF",
                "projection": 10,
                "floor": 2,
                "ceiling": 24,
                "projection_model_version": "test",
            },
        ]
        actuals = main.parse_actual_results_csv(
            "Player,DK Points\nPitcher One,23\nHitter One,8\n"
        )
        result = main.projection_backtest(players, actuals)
        self.assertEqual(result["matched_players"], 2)
        self.assertEqual(result["overall"]["mae"], 2.5)
        self.assertEqual(result["by_position"]["P"]["sample_size"], 1)
        self.assertEqual(result["by_position"]["OF"]["sample_size"], 1)


if __name__ == "__main__":
    unittest.main()
