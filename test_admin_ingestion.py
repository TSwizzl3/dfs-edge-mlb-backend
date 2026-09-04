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
    def test_named_contest_slates_remain_isolated(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            main, "SLATE_LIBRARY_DIR", Path(directory)
        ), patch.object(main, "supabase_service_key", return_value=""):
            main.save_slate_library([{"name": "Early Batter"}], "2026-08-23-early", "Early")
            main.save_slate_library([{"name": "Main Batter"}], "2026-08-23-main", "Main")
            self.assertEqual(main.load_slate_record("2026-08-23-early")["players"][0]["name"], "Early Batter")
            self.assertEqual(main.load_slate_record("2026-08-23-main")["players"][0]["name"], "Main Batter")

    def test_active_slate_reads_use_publishable_key_when_server_secret_is_missing(self):
        saved = [{
            "slate_key": "2026-08-24-main",
            "name": "MLB Turbo",
            "is_active": True,
            "players": [{"name": "Saved Player"}],
        }]
        with patch.object(main, "supabase_service_key", return_value=""), patch.object(
            main.urllib.request, "urlopen", return_value=FakeResponse(saved)
        ) as request_call:
            record = main.load_slate_record("2026-08-24-main")

        request = request_call.call_args.args[0]
        self.assertEqual(record["players"][0]["name"], "Saved Player")
        self.assertEqual(request.headers.get("Apikey"), main.SUPABASE_PUBLISHABLE_KEY)
        self.assertNotIn("Authorization", request.headers)

    def test_every_pro_lineup_count_from_one_through_twenty_is_supported(self):
        self.assertEqual(main.normalize_lineup_count(2), 2)
        self.assertEqual(main.normalize_lineup_count(13), 13)
        self.assertEqual(main.normalize_lineup_count(20), 20)
        self.assertEqual(main.normalize_lineup_count(21), 20)

    def test_admin_optimizer_keeps_requested_count_of_four(self):
        request = main.MultiOptimizeRequest(count=4)
        lineups = [{"lineup": [], "projected_points": 100 + index} for index in range(4)]
        with patch.object(main, "build_fast_multi_lineups_for_pro", return_value=(lineups, None, {}, 2)), patch.object(
            main, "calculate_exposures", return_value=[]
        ), patch.object(main, "record_lineup_learning_run") as learning_run:
            result = main.optimize_multiple_lineups(request, {"role": "admin"})
        self.assertEqual(result["requested_count"], 4)
        self.assertEqual(result["effective_count"], 4)
        self.assertEqual(result["returned_count"], 4)
        self.assertEqual(len(result["lineups"]), 4)
        learning_run.assert_called_once_with(request, lineups, "")

    def test_session_falls_back_to_direct_supabase_verification(self):
        with patch.object(main, "central_auth_request", return_value={"success": False}), patch.object(
            main, "supabase_session_from_token", return_value={"email": "admin@example.com", "role": "admin"}
        ) as direct_verification:
            session = main.optional_session("Bearer valid-supabase-token")
        direct_verification.assert_called_once_with("valid-supabase-token")
        self.assertEqual(session["role"], "admin")

    def test_live_builder_accepts_two_lineups_not_only_old_presets(self):
        request = main.MultiOptimizeRequest(count=2, mode="gpp")

        def fake_lineup(*args, **kwargs):
            offset = kwargs.get("offset", 0)
            return [
                {"name": f"Player {offset}-{index}", "position": "OF", "team": f"T{index}", "salary": 5000, "projection": 10.0}
                for index in range(10)
            ]

        def simple_metadata(data):
            return {**data, "takedown_strength": 0, "ceiling_score": 0}

        with patch.object(main, "ensure_mlb_live_availability", return_value=([{"name": "Pool"}], {"safe_to_optimize": True})), patch.object(
            main, "validate_locks", return_value=None
        ), patch.object(main, "build_optimizer_pool_with_fallback", return_value=([{"name": "Pool"}], {})), patch.object(
            main, "add_values", side_effect=lambda players: players
        ), patch.object(main, "valid_optimizer_player", return_value=True), patch.object(
            main, "is_manual_inactive_player", return_value=False
        ), patch.object(main, "has_required_mlb_positions", return_value=True), patch.object(
            main, "v4_team_stack_scores", return_value=[("AAA", 1.0), ("BBB", 0.9)]
        ), patch.object(main, "v4_build_one_lineup", side_effect=fake_lineup), patch.object(
            main, "add_lineup_metadata", side_effect=simple_metadata
        ), patch.object(main, "v4_lineup_objective", return_value=1.0), patch.object(
            main, "deterministic_random_bonus", return_value=0.0
        ), patch.object(main, "diversify_lineups", side_effect=lambda all_lineups, count, **kwargs: all_lineups[:count]):
            selected, error, _, _ = main.build_fast_multi_lineups_for_pro(request, 2)

        self.assertIsNone(error)
        self.assertEqual(len(selected), 2)

    def test_live_availability_refresh_persists_official_scratches(self):
        main._MLB_LIVE_STATUS_CACHE.clear()
        record = {
            "slate_key": "2026-08-30-main",
            "name": "Main Slate",
            "slate_date": "2026-08-30",
            "slate_type": "main",
            "updated_at": "2026-08-30T10:00:00+00:00",
            "players": [
                {"name": "Active Hitter", "position": "OF", "team": "AAA", "salary": 5000, "active": True},
                {"name": "Late Scratch", "position": "OF", "team": "AAA", "salary": 4500, "active": True},
            ],
        }
        refreshed = [
            dict(record["players"][0], starter_status="confirmed_starter", starter_source="mlb_stats_confirmed_lineup"),
            dict(record["players"][1], active=False, starter_status="confirmed_not_starting", starter_source="mlb_stats_confirmed_lineup", inactive_reason="not_in_announced_batting_order"),
        ]
        state = {"games_checked": 1, "confirmed_hitter_matches": 1, "error": ""}
        with patch.object(main, "load_slate_record", return_value=record), patch.object(
            main, "refresh_mlb_starters", return_value=(refreshed, state)
        ), patch.object(main, "save_slate_library", return_value={**record, "updated_at": "2026-08-30T10:01:00+00:00"}) as saved:
            players, availability = main.ensure_mlb_live_availability("2026-08-30-main", max_age_seconds=0)

        scratch = next(player for player in players if player["name"] == "Late Scratch")
        self.assertFalse(scratch["active"])
        self.assertFalse(main.optimizer_starter_eligible(scratch))
        self.assertTrue(availability["safe_to_optimize"])
        saved.assert_called_once()

    def test_optimizer_fails_closed_when_official_availability_is_stale(self):
        request = main.MultiOptimizeRequest(count=1, slate_key="2026-08-30-main")
        with patch.object(
            main,
            "ensure_mlb_live_availability",
            return_value=([], {"safe_to_optimize": False, "error": "official feed unavailable"}),
        ):
            selected, error, report, checked = main.build_fast_multi_lineups_for_pro(request, 1)

        self.assertEqual(selected, [])
        self.assertIn("blocked this build", error)
        self.assertFalse(report["availability"]["safe_to_optimize"])
        self.assertEqual(checked, 0)

    def test_manual_lock_overrides_scratch_while_unlocked_scratch_stays_out(self):
        available = {
            "name": "Available Hitter", "position": "OF", "team": "AAA",
            "salary": 5000, "projection": 10.0, "active": True,
            "starter_status": "confirmed_starter", "starter_source": "mlb_stats_confirmed_lineup",
        }
        locked_scratch = {
            "name": "Locked Scratch", "position": "OF", "team": "BBB",
            "salary": 4500, "projection": 8.0, "active": False,
            "starter_status": "confirmed_not_starting", "starter_source": "mlb_stats_confirmed_lineup",
            "inactive_reason": "not_in_announced_batting_order",
        }
        automatic_scratch = {
            "name": "Automatic Scratch", "position": "OF", "team": "CCC",
            "salary": 4400, "projection": 7.5, "active": False,
            "starter_status": "out", "starter_source": "mlb_stats_confirmed_lineup",
            "inactive_reason": "confirmed_out",
        }
        players = [available, locked_scratch, automatic_scratch]

        self.assertIsNone(main.validate_locks(players, ["Locked Scratch"], []))
        pool, _ = main.build_optimizer_pool_with_fallback(players, ["Locked Scratch"], [])
        names = {player["name"] for player in pool}

        self.assertIn("Available Hitter", names)
        self.assertIn("Locked Scratch", names)
        self.assertNotIn("Automatic Scratch", names)

    def test_exclude_still_wins_over_manual_lock(self):
        player = {
            "name": "Manual Choice", "position": "P", "team": "AAA",
            "salary": 8000, "projection": 12.0, "active": False,
            "starter_status": "out", "starter_source": "mlb_stats_probable_pitcher",
        }
        error = main.validate_locks([player], ["Manual Choice"], ["Manual Choice"])
        self.assertIn("both locked and excluded", error)

    def test_live_builder_places_a_manually_locked_out_player_in_the_lineup(self):
        def active_player(name, position, team):
            is_pitcher = position == "P"
            return {
                "name": name, "position": position, "team": team, "opponent": "",
                "salary": 4000, "projection": 10.0, "ownership": 10.0, "active": True,
                "dk_slate_eligible": True,
                "starter_status": "probable_pitcher" if is_pitcher else "confirmed_starter",
                "starter_source": "mlb_stats_probable_pitcher" if is_pitcher else "mlb_stats_confirmed_lineup",
                "starter_probability": 0.96 if is_pitcher else 1.0,
            }

        players = [
            active_player("Pitcher One", "P", "NYY"),
            active_player("Pitcher Two", "P", "BOS"),
            active_player("Catcher", "C", "CHC"),
            active_player("First Base", "1B", "LAD"),
            active_player("Second Base", "2B", "ATL"),
            active_player("Third Base", "3B", "PHI"),
            active_player("Shortstop", "SS", "SEA"),
            active_player("Outfield One", "OF", "HOU"),
            active_player("Outfield Two", "OF", "SD"),
            {
                **active_player("Locked Outfielder", "OF", "NYM"),
                "active": False,
                "starter_status": "out",
                "inactive_reason": "confirmed_out",
            },
        ]
        request = main.MultiOptimizeRequest(
            count=1,
            mode="cash",
            locked_players=["Locked Outfielder"],
            avoid_pitcher_vs_hitter=False,
        )
        valued_players = main.add_values(players)
        pool, _ = main.build_optimizer_pool_with_fallback(
            valued_players,
            ["Locked Outfielder"],
            [],
        )
        groups = {position: [] for position in main.V4_REQUIRED_COUNTS}
        for player in pool:
            groups[main.normalize_position(player["position"])].append(player)
        direct_lineup = main.v4_build_one_lineup(
            groups=groups,
            style="safe",
            stack_team="",
            secondary_team=None,
            stack_target=2,
            locked_objects=[player for player in pool if player["name"] == "Locked Outfielder"],
            excluded_names=set(),
            offset=0,
            max_players_per_team=5,
            min_salary=0,
            avoid_pitcher_vs_hitter=False,
        )
        self.assertIsNotNone(
            direct_lineup,
            f"pool counts={main.mlb_position_counts(pool)} eligibility="
            f"{[(player['name'], main.optimizer_starter_eligible(player)) for player in pool]}",
        )
        with patch.object(
            main,
            "ensure_mlb_live_availability",
            return_value=(players, {"safe_to_optimize": True}),
        ):
            lineups, error, _, _ = main.build_fast_multi_lineups_for_pro(request, 1)

        self.assertIsNone(error)
        self.assertEqual(len(lineups), 1)
        self.assertIn("Locked Outfielder", {player["name"] for player in lineups[0]["lineup"]})

    def test_custom_simulation_never_uses_legacy_global_payout_table(self):
        request = main.ContestSimulationRequest(
            contest_size=1000,
            field_size=1000,
            entry_fee=20,
            prize_pool=10000,
            payout_tiers=[],
        )
        with patch.object(main, "load_payout_table") as legacy_table:
            contest = main.normalize_contest_request(request)
        legacy_table.assert_not_called()
        self.assertEqual(contest["payout_table"], [])
        self.assertEqual(contest["payout_source"], "estimated_curve")

    def test_draftkings_gamecenter_export_imports_actual_ownership(self):
        csv_text = (
            "Rank,EntryId,EntryName,Points,Lineup\n"
            "1,123,Winner,151.25,SP Player One OF Player Two\n"
            "\n"
            "Player,Roster Position,% Drafted,FPTS\n"
            "Zack Wheeler,P,37.4%,28.65\n"
            "Bryce Harper,1B,22.1%,14.0\n"
        )
        rows = main.parse_actual_results_csv(csv_text)
        by_name = {row["name"]: row for row in rows}
        self.assertEqual(by_name["Zack Wheeler"]["actual_points"], 28.65)
        self.assertEqual(by_name["Zack Wheeler"]["actual_ownership"], 37.4)
        self.assertEqual(by_name["Bryce Harper"]["actual_ownership"], 22.1)


    def test_personal_lineup_ownership_is_tagged_partial(self):
        rows = [
            {"name": f"Player {index}", "actual_points": 10, "actual_ownership": 12}
            for index in range(10)
        ]
        scope = main.tag_actual_ownership_scope(rows)
        self.assertEqual(scope, "partial_entered_lineup")
        self.assertTrue(all(row["ownership_scope"] == scope for row in rows))

    def test_partial_lineup_ownership_does_not_train_full_slate_calibration(self):
        history = [{
            "slate_key": "2026-08-25-main",
            "observations": [{
                "position": "OF",
                "raw_projection": 10,
                "actual": 12,
                "projected_ownership": 8,
                "actual_ownership": 22,
                "ownership_scope": "partial_entered_lineup",
            }],
        }]
        _, observations = main.training_observations(history)
        self.assertNotIn("actual_ownership", observations[0])

    def test_saved_entered_lineup_is_evaluated_against_exact_slate(self):
        saved = [{
            "id": "saved-1",
            "session_data": {
                "slate_key": "2026-08-25-main",
                "status": "entered",
                "mode": "nuclear",
                "lineups": [{"players": [{"name": "Player One"}, {"name": "Player Two"}]}],
            },
        }]
        calls = []

        def data_request(table, method="GET", query="", payload=None, **kwargs):
            calls.append((table, method, payload))
            return saved if method == "GET" else []

        with patch.object(main, "supabase_data_request", side_effect=data_request):
            evidence = main.evaluate_saved_lineup_sessions(
                "2026-08-25-main",
                [
                    {"name": "Player One", "actual_points": 20},
                    {"name": "Player Two", "actual_points": 15},
                ],
                [40, 30, 20],
                "admin-token",
            )
        self.assertEqual(evidence["entered_observation_count"], 1)
        self.assertEqual(evidence["best_actual_score"], 35)
        self.assertTrue(any(method == "PATCH" for _, method, _ in calls))


    def test_draftkings_gamecenter_export_imports_contest_standings(self):
        csv_text = (
            "Rank,EntryId,EntryName,Points,Lineup\n"
            "1,123,Winner,151.25,SP Player One OF Player Two\n"
            "2,456,Runner Up,145.00,SP Player Three OF Player Four\n"
            "100,789,Last Paid,90.50,SP Player Five OF Player Six\n"
            "\n"
            "Player,Roster Position,% Drafted,FPTS\n"
            "Zack Wheeler,P,37.4%,28.65\n"
        )
        evidence = main.parse_contest_standings_csv(csv_text)
        self.assertEqual(evidence["summary"]["observation_count"], 3)
        self.assertEqual(evidence["summary"]["field_size"], 100)
        self.assertEqual(evidence["summary"]["first_place_score"], 151.25)
        self.assertEqual(evidence["summary"]["minimum_score"], 90.5)

    def test_pro_optimizer_preserves_disabled_pitcher_hitter_conflict_setting(self):
        request = main.MultiOptimizeRequest(count=1, avoid_pitcher_vs_hitter=False)
        lineup = [{"lineup": [], "projected_points": 100}]
        with patch.object(
            main, "build_fast_multi_lineups_for_pro", return_value=(lineup, None, {}, 1)
        ) as builder, patch.object(
            main, "record_lineup_learning_run"
        ), patch.object(
            main, "calculate_exposures", return_value=[]
        ):
            main.optimize_multiple_lineups(request, {"role": "admin"})
        self.assertFalse(builder.call_args.args[0].avoid_pitcher_vs_hitter)


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


    def test_uploaded_projection_pitcher_is_preferred_over_default_estimate(self):
        players = [
            {"name": "Estimated Arm", "position": "P", "team": "PHI", "salary": 10000, "projection": 30, "active": True},
            {"name": "Roto Starter", "position": "P", "team": "PHI", "salary": 8000, "projection": 18, "projection_source": "admin_projection_csv", "active": True},
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            active_path = Path(temp_dir) / "active.json"
            active_path.write_text("[]", encoding="utf-8")
            with patch.object(main, "ACTIVE_SLATE_PATH", active_path):
                filtered = main.apply_slate_starter_likelihood(players)
                active_names = {p["name"] for p in filtered if main.optimizer_starter_eligible(p)}
                self.assertEqual(active_names, {"Roto Starter"})
                self.assertEqual(next(p for p in filtered if p["name"] == "Roto Starter")["starter_source"], "admin_projection_csv")

    def test_optimizer_accepts_official_or_uploaded_projection_backed_pitcher_only(self):
        guessed = {
            "name": "Wrong Pitcher", "position": "P", "team": "PHI", "active": True,
            "starter_status": "projected_probable_pitcher", "starter_source": "dk_slate_likelihood",
            "starter_probability": 0.99,
        }
        projection_backed = {
            "name": "RotoGrinders Starter", "position": "P", "team": "NYM", "active": True,
            "starter_status": "projected_probable_pitcher", "starter_source": "admin_projection_csv",
            "starter_probability": 0.92,
        }

        official = {
            "name": "Official Pitcher", "position": "P", "team": "ATL", "active": True,
            "starter_status": "probable_pitcher", "starter_source": "mlb_stats_probable_pitcher",
            "starter_probability": 0.98,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            active_path = Path(temp_dir) / "active.json"
            active_path.write_text("[]", encoding="utf-8")
            with patch.object(main, "ACTIVE_SLATE_PATH", active_path):
                self.assertFalse(main.optimizer_starter_eligible(guessed))
                self.assertTrue(main.optimizer_starter_eligible(official))
                self.assertTrue(main.optimizer_starter_eligible(projection_backed))

    def test_web_strategy_modes_map_to_distinct_optimizer_styles(self):
        balanced = main.MultiOptimizeRequest(mode="balanced")
        ceiling = main.MultiOptimizeRequest(mode="ceiling")
        nuclear = main.MultiOptimizeRequest(mode="nuclear", randomness=18)
        self.assertEqual(main.v4_style_from_request(balanced, balanced.mode), "safe")
        self.assertEqual(main.v4_style_from_request(ceiling, ceiling.mode), "aggressive")
        self.assertEqual(main.v4_style_from_request(nuclear, nuclear.mode), "nuclear")

    def test_mlb_lineup_is_returned_in_draftkings_roster_order(self):
        positions = ["OF", "2B", "P", "SS", "C", "OF", "1B", "P", "3B", "OF"]
        lineup = [{"name": f"Player {index}", "position": position} for index, position in enumerate(positions)]
        ordered = main.order_mlb_lineup_for_draftkings(lineup)
        self.assertEqual([player["position"] for player in ordered], ["P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF"])

    def test_tournament_distribution_anchors_to_uploaded_player_ceiling(self):
        player = {
            "name": "Verified Upside", "position": "OF", "salary": 4800,
            "projection": 10.0, "ceiling": 18.0, "ownership": 12.0,
        }
        distribution = main.v4_player_dist(player)
        self.assertGreaterEqual(distribution["p95"], 18.0)
        self.assertGreater(distribution["p99"], distribution["p95"])
        self.assertLess(distribution["p99"], 30.0)

    def test_nuclear_objective_prefers_four_player_stack_without_overrewarding_five(self):
        lineup = [
            {"name": f"Player {index}", "projection": 10, "salary": 5000, "ownership": 8}
            for index in range(10)
        ]
        leverage = {"leverage_score": 60, "uniqueness_score": 60, "duplication_risk": 20}
        core = {"average_core_play_score": 50}
        with patch.object(main, "v4_player_dist", return_value={"p95": 20, "p99": 30}), patch.object(main, "v2_lineup_leverage_profile", return_value=leverage), patch.object(main, "lineup_core_profile", return_value=core):
            with patch.object(main, "v2_lineup_stack_profile", return_value={"stack_score": 90, "primary_stack_size": 5}):
                five_stack_score = main.v4_lineup_objective(lineup, "nuclear", "nuclear")
            with patch.object(main, "v2_lineup_stack_profile", return_value={"stack_score": 90, "primary_stack_size": 4}):
                four_stack_score = main.v4_lineup_objective(lineup, "nuclear", "nuclear")
                four_stack_no_correlation = main.v4_lineup_objective(lineup, "nuclear", "nuclear", correlation_enabled=False)
            with patch.object(main, "v2_lineup_stack_profile", return_value={"stack_score": 90, "primary_stack_size": 5}):
                five_stack_no_correlation = main.v4_lineup_objective(lineup, "nuclear", "nuclear", correlation_enabled=False)
        self.assertGreater(four_stack_score, five_stack_score)
        self.assertEqual(five_stack_no_correlation, four_stack_no_correlation)


    def test_nuclear_objective_prefers_stars_and_qualified_boom_values(self):
        def player(name, salary, projection, ownership, p99):
            return {
                "name": name, "position": "OF", "team": "SEA", "salary": salary,
                "projection": projection, "ownership": ownership, "test_p99": p99,
            }

        barbell = [
            player("Premium One", 5600, 10, 14, 38), player("Premium Two", 5200, 9.5, 13, 35),
            player("Boom Value One", 3400, 7, 8, 26), player("Boom Value Two", 3600, 7.5, 10, 27),
        ] + [player(f"Middle {index}", 4400, 8, 14, 28) for index in range(6)]
        middle_only = [player(f"Middle Only {index}", 4400, 8, 14, 28) for index in range(10)]
        leverage = {"leverage_score": 60, "uniqueness_score": 60, "duplication_risk": 20}
        core = {"average_core_play_score": 50}

        def distribution(p):
            return {"p75": p["projection"] * 1.3, "p95": p["test_p99"] * 0.78, "p99": p["test_p99"]}

        with patch.object(main, "v4_player_dist", side_effect=distribution), patch.object(main, "v2_lineup_leverage_profile", return_value=leverage), patch.object(main, "lineup_core_profile", return_value=core), patch.object(main, "v2_lineup_stack_profile", return_value={"stack_score": 70, "primary_stack_size": 4}):
            barbell_score = main.v4_lineup_objective(barbell, "nuclear", "nuclear")
            middle_score = main.v4_lineup_objective(middle_only, "nuclear", "nuclear")
            profile = main.v4_nuclear_lineup_profile(barbell)

        self.assertEqual(profile["premium_ceiling_count"], 2)
        self.assertEqual(profile["boom_value_count"], 2)
        self.assertGreater(barbell_score, middle_score + 80)

    def test_nuclear_rejects_cheap_player_without_real_boom_ceiling(self):
        weak_value = {"name": "Weak Punt", "position": "OF", "salary": 3000, "projection": 3.5, "ownership": 4}
        strong_value = {"name": "Boom Value", "position": "OF", "salary": 3500, "projection": 7.0, "ownership": 9}
        with patch.object(main, "v4_player_dist", side_effect=[{"p99": 17}, {"p99": 27}]):
            weak = main.v4_nuclear_player_profile(weak_value)
            strong = main.v4_nuclear_player_profile(strong_value)
        self.assertTrue(weak["fragile_punt"])
        self.assertFalse(weak["boom_value"])
        self.assertTrue(strong["boom_value"])

    def test_hard_hitter_stack_cap_cannot_be_overridden(self):
        existing = [
            {"name": "Hitter One", "team": "WSH", "position": "1B"},
            {"name": "Hitter Two", "team": "WSH", "position": "2B"},
        ]
        third_hitter = {"name": "Hitter Three", "team": "WSH", "position": "OF"}
        with patch.object(main, "optimizer_starter_eligible", return_value=True):
            self.assertFalse(main.v4_can_add(existing, third_hitter, max_players_per_team=2, avoid_pitcher_vs_hitter=False))
            self.assertTrue(main.v4_can_add(existing, third_hitter, max_players_per_team=3, avoid_pitcher_vs_hitter=False))

    def test_pitcher_does_not_consume_mlb_hitter_stack_limit(self):
        existing = [{"name": "Pitcher", "team": "WSH", "position": "P"}, {"name": "Hitter One", "team": "WSH", "position": "1B"}]
        second_hitter = {"name": "Hitter Two", "team": "WSH", "position": "2B"}
        with patch.object(main, "optimizer_starter_eligible", return_value=True):
            self.assertTrue(main.v4_can_add(existing, second_hitter, max_players_per_team=2, avoid_pitcher_vs_hitter=False))


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

    def test_exact_contest_payout_table_drives_contest_math(self):
        tiers = [
            {"start_rank": 1, "end_rank": 1, "payout": 1000.0},
            {"start_rank": 2, "end_rank": 10, "payout": 50.0},
        ]
        request = main.ContestSimulationRequest(
            contest_size=100,
            paid_positions=20,
            payout_rate=0.2,
            contest_profile_id="exact-contest",
            payout_tiers=tiers,
        )
        contest = main.normalize_contest_request(request)
        self.assertEqual(contest["paid_positions"], 10)
        self.assertEqual(contest["payout_source"], "contest_library_exact_table")
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
            "Player,DK Points,Actual Ownership %\nPitcher One,23,18.4%\nHitter One,8,7.2%\n"
        )
        result = main.projection_backtest(players, actuals)
        self.assertEqual(result["matched_players"], 2)
        self.assertEqual(result["overall"]["mae"], 2.5)
        self.assertEqual(result["by_position"]["P"]["sample_size"], 1)
        self.assertEqual(result["by_position"]["OF"]["sample_size"], 1)
        self.assertEqual(actuals[0]["actual_ownership"], 18.4)
        self.assertEqual(result["ownership"]["overall"]["sample_size"], 2)

    def calibration_history(self, slate_count):
        positions = ["P", "C", "1B", "2B", "3B", "SS", "OF"]
        history = []
        for slate_index in range(slate_count):
            observations = []
            for player_index in range(70):
                projection = 8.0 + (player_index % 8)
                observations.append({
                    "name": f"Player {slate_index}-{player_index}",
                    "position": positions[player_index % len(positions)],
                    "raw_projection": projection,
                    "projection": projection,
                    "actual": projection - 2.0,
                    "model_version": "imported_projection_blend_v1",
                })
            history.append({
                "slate_key": f"2026-slate-{slate_index}",
                "evaluated_at": f"2026-08-{slate_index + 1:02d}T23:00:00+00:00",
                "observations": observations,
            })
        return history

    def test_calibration_stays_in_collecting_mode_after_one_slate(self):
        model = main.train_calibration_model(self.calibration_history(1))
        self.assertEqual(model["status"], "collecting")
        self.assertFalse(model["is_active"])
        self.assertEqual(model["training_slate_count"], 1)
        self.assertEqual(model["adjustment_scale"], 0)

    def test_cross_validated_calibration_activates_when_it_beats_baseline(self):
        model = main.train_calibration_model(self.calibration_history(3))
        self.assertEqual(model["status"], "active")
        self.assertTrue(model["is_active"])
        self.assertGreater(model["validation"]["improvement_percent"], 0.5)
        self.assertLess(model["parameters"]["positions"]["OF"]["projection_offset"], 0)
        self.assertEqual(model["learning_stage"], "fast_start")
        self.assertLess(model["adjustment_scale"], 1)

    def test_fast_start_can_activate_after_two_independent_slates(self):
        history = self.calibration_history(2)
        for slate in history:
            slate["observations"].extend(slate["observations"][:10])
        model = main.train_calibration_model(history)
        self.assertEqual(model["status"], "active")
        self.assertEqual(model["training_slate_count"], 2)
        self.assertEqual(model["adjustment_scale"], 0.25)

    def test_calibration_reaches_full_strength_after_eight_slates(self):
        model = main.train_calibration_model(self.calibration_history(8))
        self.assertEqual(model["adjustment_scale"], 1.0)
        self.assertEqual(model["learning_stage"], "full_strength")

    def test_active_calibration_uses_raw_projection_without_double_applying(self):
        model = {
            "model_version": "mlb-cal-test",
            "is_active": True,
            "training_slate_count": 10,
            "target_model_versions": ["imported_projection_blend_v1"],
            "parameters": {"positions": {"OF": {
                "projection_offset": -1.0,
                "residual_q15": -5.0,
                "residual_q90": 7.0,
                "confidence": 0.8,
            }}},
        }
        player = {
            "name": "Calibrated Hitter", "position": "OF",
            "raw_projection": 10.0, "projection": 9.0,
            "raw_floor": 2.0, "floor": 2.0,
            "raw_ceiling": 22.0, "ceiling": 22.0,
            "projection_model_version": "imported_projection_blend_v1",
        }
        first = main.apply_calibration_to_player(player, model)
        second = main.apply_calibration_to_player(first, model)
        self.assertEqual(first["projection"], 9.0)
        self.assertEqual(second["projection"], 9.0)

    def test_actual_ownership_earns_a_separate_validated_adjustment(self):
        history = self.calibration_history(3)
        for slate in history:
            for observation in slate["observations"]:
                observation["projected_ownership"] = 10.0
                observation["actual_ownership"] = 15.0
        model = main.train_calibration_model(history)
        self.assertTrue(model["validation"]["ownership"]["passes"])
        self.assertGreater(model["parameters"]["ownership_positions"]["ALL"]["ownership_offset"], 0)
        player = {
            "name": "Ownership Test", "position": "OF",
            "projection": 10.0, "floor": 2.0, "ceiling": 22.0,
            "ownership": 10.0,
            "projection_model_version": "imported_projection_blend_v1",
        }
        calibrated = main.apply_calibration_to_player(player, model)
        self.assertTrue(calibrated["ownership_calibration_applied"])
        self.assertGreater(calibrated["ownership"], 10.0)

    def test_backtest_compares_raw_and_calibrated_accuracy(self):
        players = [{
            "name": "Learned Hitter", "position": "OF",
            "raw_projection": 10.0, "projection": 9.0,
            "floor": 2.0, "ceiling": 20.0,
            "projection_model_version": "imported_projection_blend_v1",
            "calibration_applied": True,
        }]
        result = main.projection_backtest(players, [{"name": "Learned Hitter", "actual_points": 9.0}])
        self.assertEqual(result["baseline_overall"]["mae"], 1.0)
        self.assertEqual(result["overall"]["mae"], 0.0)
        self.assertEqual(len(result["observations"]), 1)

    def test_projection_snapshots_remain_isolated_by_slate(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot_dir = Path(directory) / "snapshots"
            snapshot_dir.mkdir()
            legacy_path = Path(directory) / "latest.json"
            with patch.object(main, "PROJECTION_SNAPSHOT_DIR", snapshot_dir), patch.object(
                main, "PROJECTION_SNAPSHOT_PATH", legacy_path
            ), patch.object(main, "supabase_data_request", return_value=None), patch.object(
                main, "load_slate_record", return_value={}
            ), patch.object(main, "load_slate_metadata", return_value={"slate_date": "2026-08-24"}):
                main.save_projection_snapshot([{"name": "Early Bat"}], "2026-08-24-early")
                main.save_projection_snapshot([{"name": "Main Bat"}], "2026-08-24-main")
                early = main.load_projection_snapshot("2026-08-24-early")
                main_slate = main.load_projection_snapshot("2026-08-24-main")
        self.assertEqual(early["players"][0]["name"], "Early Bat")
        self.assertEqual(main_slate["players"][0]["name"], "Main Bat")

    def test_mlb_odds_consensus_creates_team_totals(self):
        events = [{
            "id": "game-1",
            "home_team": "Philadelphia Phillies",
            "away_team": "Atlanta Braves",
            "bookmakers": [{
                "key": "draftkings",
                "markets": [
                    {"key": "totals", "outcomes": [{"name": "Over", "point": 8.5}]},
                    {"key": "spreads", "outcomes": [{"name": "Philadelphia Phillies", "point": -1.5}]},
                    {"key": "h2h", "outcomes": [
                        {"name": "Philadelphia Phillies", "price": -145},
                        {"name": "Atlanta Braves", "price": 125},
                    ]},
                ],
            }],
        }]
        teams, games = main.parse_mlb_odds_consensus(events, {"PHI", "ATL"})
        self.assertEqual(len(games), 1)
        self.assertEqual(teams["PHI"]["team_total"], 5.0)
        self.assertEqual(teams["ATL"]["team_total"], 3.5)
        self.assertEqual(teams["PHI"]["moneyline"], -145.0)

    def test_live_odds_are_preserved_by_vegas_engine(self):
        player = {
            "name": "Live Odds Bat", "position": "OF", "team": "PHI", "opponent": "ATL",
            "team_total": 5.25, "opponent_total": 3.75, "odds_source": "The Odds API consensus",
        }
        result = main.vegas_environment_for_player(player)
        self.assertEqual(result["team_total"], 5.2)
        self.assertEqual(result["opponent_total"], 3.8)
        self.assertEqual(result["vegas_source"], "The Odds API consensus")
    def vegas_history(self, slate_count=3, odds_source="The Odds API consensus"):
        boosts = [-0.6, -0.3, 0.3, 0.6]
        history = []
        for slate_index in range(slate_count):
            observations = []
            for player_index in range(70):
                boost = boosts[player_index % len(boosts)]
                projection = 10.0
                observations.append({
                    "name": f"Vegas Player {slate_index}-{player_index}",
                    "position": "P" if player_index % 7 == 0 else "OF",
                    "raw_projection": projection,
                    "projection": projection,
                    "actual": projection + boost * 2.0,
                    "vegas_boost": boost,
                    "team_total": 4.2 + boost,
                    "odds_source": odds_source,
                    "model_version": "imported_projection_blend_v1",
                })
            history.append({
                "slate_key": f"2026-vegas-{slate_index}",
                "observations": observations,
            })
        return history

    def test_verified_vegas_effect_activates_only_after_cross_validation(self):
        model = main.train_calibration_model(self.vegas_history())
        vegas_validation = model["validation"]["vegas"]
        self.assertTrue(vegas_validation["eligible"])
        self.assertTrue(vegas_validation["passes"])
        self.assertEqual(vegas_validation["validated_slates"], 3)
        self.assertGreater(model["parameters"]["vegas"]["groups"]["ALL"]["projection_slope"], 0)

    def test_estimated_team_totals_do_not_train_vegas_calibration(self):
        model = main.train_calibration_model(self.vegas_history(3, "DFS Edge estimate"))
        self.assertEqual(model["validation"]["vegas"]["gate"], "collecting")
        self.assertEqual(model["vegas_training_player_count"], 0)

    def test_earned_vegas_adjustment_requires_verified_odds(self):
        model = {
            "model_version": "mlb-cal-vegas-test",
            "is_active": True,
            "training_slate_count": 3,
            "target_model_versions": ["imported_projection_blend_v1"],
            "parameters": {
                "positions": {},
                "ownership_positions": {},
                "vegas": {
                    "groups": {"H": {"projection_slope": 1.0, "confidence": 0.8}},
                    "adjustment_scale": 1.0,
                },
            },
            "validation": {
                "passes": False,
                "ownership": {"passes": False},
                "vegas": {"passes": True},
            },
        }
        player = {
            "name": "Vegas Test Bat",
            "position": "OF",
            "projection": 10.0,
            "raw_projection": 10.0,
            "floor": 2.0,
            "ceiling": 22.0,
            "vegas_boost": 0.5,
            "projection_model_version": "imported_projection_blend_v1",
        }
        verified = main.apply_calibration_to_player(
            {**player, "odds_source": "The Odds API consensus"},
            model,
        )
        estimated = main.apply_calibration_to_player(
            {**player, "odds_source": "DFS Edge estimate"},
            model,
        )
        self.assertTrue(verified["vegas_calibration_applied"])
        self.assertEqual(verified["projection"], 10.5)
        self.assertFalse(estimated["vegas_calibration_applied"])
        self.assertEqual(estimated["projection"], 10.0)

    def test_first_market_snapshot_does_not_invent_movement(self):
        player = {
            "name": "Real Signal", "position": "OF", "team": "PHI",
            "projection": 10.0, "ownership": 14.0, "team_total": 4.9,
            "odds_source": "The Odds API consensus",
        }
        profile = main.market_movement_profile(player, {"players": {}, "teams": {}})
        self.assertEqual(profile["ownership_delta"], 0.0)
        self.assertEqual(profile["team_total_delta"], 0.0)
        self.assertEqual(profile["market_signal_type"], "neutral")

    def test_slate_metadata_saves_name_key_and_type_to_library(self):
        request = main.SlateMetadataRequest(
            auth_token="admin-token",
            slate_name="Sunday Afternoon",
            slate_date="2026-08-24",
            slate_key="2026-08-24-afternoon",
            slate_type="afternoon",
        )
        existing = {"name": "DraftKings MLB Slate", "slate_date": "2026-08-24", "slate_type": "main", "players": [{"name": "Player"}]}
        saved_meta = {
            "slate_name": "Sunday Afternoon",
            "slate_date": "2026-08-24",
            "slate_key": "2026-08-24-afternoon",
            "slate_type": "afternoon",
        }
        with patch.object(main, "is_admin_authorized", return_value=True), patch.object(
            main, "is_admin_token", return_value=True
        ), patch.object(main, "save_slate_metadata", return_value=saved_meta) as save_meta, patch.object(
            main, "load_slate_record", return_value=existing
        ), patch.object(main, "save_slate_library", return_value={"persisted": True}) as save_library, patch.object(
            main, "load_players", return_value=[]
        ), patch.object(main, "current_slate_source", return_value="imported_or_edited_slate"):
            result = main.update_slate_metadata(request)

        self.assertTrue(result["success"])
        self.assertEqual(result["slate_name"], "Sunday Afternoon")
        self.assertEqual(result["slate_key"], "2026-08-24-afternoon")
        self.assertEqual(result["slate_type"], "afternoon")
        self.assertTrue(result["library_updated"])
        self.assertEqual(save_meta.call_args.kwargs["slate_type"], "afternoon")
        self.assertEqual(save_library.call_args.args[2], "Sunday Afternoon")
        self.assertEqual(save_library.call_args.args[4], "afternoon")

    def test_live_weather_is_blended_into_data_engine(self):
        player = {
            "name": "Weather Bat", "position": "OF", "team": "PHI", "opponent": "ATL",
            "salary": 4800, "projection": 9.0, "ownership": 10,
            "weather_source": "National Weather Service", "weather_risk": "High",
            "weather_boost": -1.1, "weather": "Thunderstorms likely",
            "starter_status": "confirmed_starter", "injury_status": "active",
        }
        result = main.data_engine_for_player(player)
        self.assertEqual(result["weather_risk"], "High")
        self.assertEqual(result["weather_boost"], -1.1)
        self.assertIn("Thunderstorms likely", result["data_engine_reasons"])

    def test_weather_state_applies_to_both_teams(self):
        players = [
            {"name": "Phillies Bat", "team": "PHI"},
            {"name": "Braves Bat", "team": "ATL"},
        ]
        state = {
            "fetched_at": "2026-08-23T12:00:00+00:00",
            "team_to_home": {"PHI": "PHI", "ATL": "PHI"},
            "forecasts": {"PHI": {
                "stadium": "Citizens Bank Park", "venue": "Outdoor", "forecast": "Rain showers",
                "weather_risk": "Watch", "weather_boost": -0.35, "source": "National Weather Service",
            }},
        }
        applied = main.apply_mlb_weather(players, state)
        self.assertTrue(all(player["weather_risk"] == "Watch" for player in applied))
        self.assertTrue(all(player["weather_source"] == "National Weather Service" for player in applied))

    def test_payout_from_tiers_reads_exact_rank_ranges(self):
        tiers = [
            {"start_rank": 1, "end_rank": 1, "payout": 20000},
            {"start_rank": 7, "end_rank": 8, "payout": 250},
            {"start_rank": 361, "end_rank": 991, "payout": 25},
        ]
        self.assertEqual(main.payout_from_tiers(1, tiers), 20000)
        self.assertEqual(main.payout_from_tiers(8, tiers), 250)
        self.assertEqual(main.payout_from_tiers(500, tiers), 25)
        self.assertEqual(main.payout_from_tiers(1000, tiers), 0)

    def test_learning_lineup_features_are_stable_and_include_stack_shape(self):
        lineup = {
            "lineup": [
                {"name": "Pitcher One", "team": "PHI", "salary": 9000, "projection": 22, "ceiling": 32, "ownership": 15},
                {"name": "Batter One", "team": "ATL", "salary": 5000, "projection": 11, "ceiling": 20, "ownership": 8},
                {"name": "Batter Two", "team": "ATL", "salary": 4800, "projection": 10, "ceiling": 19, "ownership": 9},
                {"name": "Batter Three", "team": "ATL", "salary": 4200, "projection": 9, "ceiling": 18, "ownership": 7},
            ],
            "projected_points": 52,
            "optimizer_score": 61,
        }
        features = main.learning_lineup_features(lineup)
        self.assertEqual(features["projected_points"], 52)
        self.assertEqual(features["optimizer_score"], 61)
        self.assertEqual(features["primary_stack_size"], 3)
        self.assertEqual(features["hitter_team_count"], 2)
        self.assertEqual(features["lineup_fingerprint"], main.learning_lineup_fingerprint(lineup["lineup"]))

    def test_historic_builder_labels_map_to_public_strategy_modes(self):
        self.assertEqual(main.canonical_mlb_strategy_mode("safe"), "balanced")
        self.assertEqual(main.canonical_mlb_strategy_mode("aggressive"), "ceiling")
        self.assertEqual(main.canonical_mlb_strategy_mode("nuclear"), "nuclear")

    def test_empirical_adjustments_activate_only_with_repeated_slate_evidence(self):
        rows = []
        for slate in range(8):
            for index in range(14):
                rows.append({
                    "slate_key": f"slate-{slate}",
                    "field_percentile": 70 if index < 7 else 35,
                    "primary_stack_size": 4 if index < 7 else 2,
                    "average_ownership": 10 if index < 7 else 6,
                })
        model = main.build_empirical_lineup_adjustments(rows)
        self.assertTrue(model["active"])
        self.assertGreater(model["dimensions"]["primary_stack_size"]["4"]["adjustment"], 0)
        self.assertLess(model["dimensions"]["primary_stack_size"]["2"]["adjustment"], 0)

    def test_performance_report_deduplicates_and_walks_forward(self):
        runs = []
        for slate_number in range(4):
            for mode, percentile in (("balanced", 55), ("ceiling", 70), ("nuclear", 40)):
                lineups = []
                results = []
                for lineup_number in range(5):
                    players = [
                        {"name": f"{mode}-{slate_number}-{lineup_number}-{player_number}", "team": "ATL" if player_number < 3 else "PHI", "projection": 10 + player_number, "salary": 4500, "ownership": 10}
                        for player_number in range(4)
                    ]
                    lineups.append({"lineup": players, "projection": 46, "builder_style": mode})
                    results.append({"lineup_index": lineup_number + 1, "status": "complete", "actual_score": 50 + lineup_number, "field_percentile": percentile})
                runs.append({
                    "id": f"{mode}-{slate_number}", "slate_key": f"2026-09-0{slate_number + 1}-main",
                    "generated_at": f"2026-09-0{slate_number + 1}T10:00:00Z", "strategy_mode": mode,
                    "lineups": lineups, "lineup_count": 5, "evaluation": {"results": results},
                })
        # Repeat one run to prove the report removes slate/fingerprint duplicates.
        runs.append({**runs[0], "id": "duplicate-run"})

        def fake_request(table, **kwargs):
            if table == "mlb_lineup_runs":
                return runs
            if table == "contest_entries":
                return [{"id": "entry-1", "status": "settled", "entry_fee": 20, "payout": 30, "net_profit": 10}]
            return []

        with patch.object(main, "supabase_data_request", side_effect=fake_request):
            report = main.build_strategy_performance_report("admin-token")

        self.assertEqual(report["data_quality"]["unique_lineups"], 60)
        self.assertEqual(report["data_quality"]["duplicate_lineups"], 5)
        self.assertEqual(report["walk_forward"]["test_slate_count"], 1)
        self.assertEqual(report["walk_forward"]["tests"][0]["selected_strategy"], "ceiling")
        self.assertEqual(set(report["by_strategy"]), {"balanced", "ceiling", "nuclear"})
        self.assertEqual(report["profit"]["net_profit"], 10)
        self.assertFalse(report["activation_gate"]["passes"])


if __name__ == "__main__":
    unittest.main()
