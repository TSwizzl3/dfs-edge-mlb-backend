import json
import unittest
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
