import copy
from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest

from app.analysis import analyze, category
from app.data import Store, timestamp, utcnow, validate
from app.demo import dataset
from app.providers import boxscore, import_roster, minutes, schedule, sync


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.data = validate(dataset())

    def test_injected_opponent_weakness_is_detected(self):
        result = analyze(self.data)
        centers = [r for r in result["defenses"] if r["category"] == "C"]
        self.assertEqual(centers[0]["team_id"], "T0")
        self.assertGreater(centers[0]["matchup_delta_per_30"], 0)
        rec = next(r for r in result["recommendations"] if r["player_id"] == "P10")
        self.assertGreater(rec["matchup_delta"], 0)
        self.assertAlmostEqual(rec["projected_pir"], rec["recent_pir"] + rec["matchup_delta"], places=1)

    def test_zero_minutes_are_excluded(self):
        row = self.data["appearances"][0]
        row.update(minutes=0, pir=0)
        result = analyze(self.data)
        self.assertEqual(result["coverage"]["appearances"], 299)

    def test_small_sample_shrinkage_uses_games_not_appearances(self):
        result = analyze(self.data, window=5)
        for cell in result["defenses"]:
            self.assertLessEqual(cell["comparable_games"], 5)
            self.assertLessEqual(cell["games"], 5)
        wings = next(c for c in result["defenses"] if c["category"] == "W")
        self.assertEqual(wings["games"], 5)
        self.assertEqual(wings["appearances"], 15)

    def test_future_and_same_round_outcomes_do_not_leak(self):
        before = analyze(self.data, target_round=10)
        for row in self.data["appearances"]:
            game = next(g for g in self.data["games"] if g["id"] == row["game_id"])
            if game["round"] >= 10:
                row["pir"] = 99
        after = analyze(self.data, target_round=10)
        self.assertEqual(before["defenses"], after["defenses"])
        self.assertEqual(before["coverage"], after["coverage"])

    def test_future_finished_game_is_ignored(self):
        original = analyze(self.data)
        game = next(g for g in self.data["games"] if g["round"] == 1)
        game["date"] = (utcnow() + timedelta(days=20)).isoformat()
        result = analyze(self.data)
        self.assertEqual(result["coverage"]["games"], original["coverage"]["games"] - 1)

    def test_out_is_excluded_only_when_fresh(self):
        result = analyze(self.data)
        self.assertIn("P14", [r["player_id"] for r in result["excluded"]])
        p = next(p for p in self.data["players"] if p["id"] == "P14")
        p["availability_as_of"] = (utcnow() - timedelta(days=2)).isoformat()
        result = analyze(self.data)
        rec = next(r for r in result["recommendations"] if r["player_id"] == "P14")
        self.assertEqual(rec["availability"], "unknown")
        self.assertFalse(rec["eligible"])

    def test_stale_price_has_no_value_metric(self):
        p = self.data["players"][0]
        p["price_as_of"] = (utcnow() - timedelta(days=3)).isoformat()
        result = analyze(self.data)
        r = next(r for r in result["recommendations"] if r["player_id"] == p["id"])
        self.assertIsNone(r["credits"])
        self.assertIsNone(r["pir_per_credit"])
        self.assertFalse(r["eligible"])

    def test_unknown_guard_is_not_point_guard(self):
        self.assertEqual(category("G"), "G")
        self.data["players"][0]["position"] = "G"
        r = next(r for r in analyze(self.data)["recommendations"] if r["player_id"] == "P0")
        self.assertIsNone(r["projected_pir"])
        self.assertFalse(r["eligible"])

    def test_generic_guard_forecast_is_labeled_broad_and_csv_refines_role(self):
        pp={p['id']:p for p in self.data['players']}
        for p in pp.values():
            if p['position']=='PG':p['position']='G'
        for row in self.data['appearances']:
            row['position']=pp[row['player_id']]['position']
        broad=analyze(self.data)
        guards=[r for r in broad['recommendations'] if r['category']=='G']
        self.assertTrue(any(r['projected_pir'] is not None for r in guards))
        self.assertTrue(all(r['position']=='G' for r in guards))
        for p in pp.values():
            if p['position']=='G':p.update(position='PG',position_source='user supplied CSV')
        detailed=analyze(self.data)
        self.assertTrue(any(r['category']=='PG' and r['projected_pir'] is not None for r in detailed['recommendations']))

    def test_insufficient_comparison_returns_no_prediction(self):
        self.data["appearances"] = self.data["appearances"][:30]
        for r in analyze(self.data)["recommendations"]:
            self.assertIsNone(r["projected_pir"])

    def test_home_away_filter_is_defenders_venue(self):
        home = analyze(self.data, venue="home")
        for cell in home["defenses"]:
            expected = sum(g["status"] == "finished" and g["home_team_id"] == cell["team_id"] for g in self.data["games"])
            self.assertEqual(cell["games"], expected)
        for rec in home["recommendations"]:
            if rec["venue"] == "home":
                self.assertIsNone(rec["projected_pir"])


class DataTests(unittest.TestCase):
    def setUp(self):
        self.data = dataset()

    def test_duplicate_appearance_rejected(self):
        self.data["appearances"].append(copy.deepcopy(self.data["appearances"][0]))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            validate(self.data)

    def test_wrong_opponent_rejected(self):
        self.data["appearances"][0]["opponent_id"] = "T0"
        with self.assertRaises(ValueError):
            validate(self.data)

    def test_market_requires_source_timestamp_and_finite_price(self):
        for key, value in [("price_source", ""), ("price_as_of", "2026-10-12"), ("credits", float("nan"))]:
            data = copy.deepcopy(self.data)
            data["players"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate(data)

    def test_invalid_save_retains_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / "live.json")
            store.save(self.data)
            original = store.path.read_bytes()
            self.data["players"][0]["position"] = "made-up"
            with self.assertRaises(ValueError):
                store.save(self.data)
            self.assertEqual(store.path.read_bytes(), original)

    def test_csv_uses_ids_and_updates_market_without_overwriting_stats(self):
        now = utcnow().isoformat()
        csv = 'season,player_id,name,team_id,position,credits,price_as_of,price_source,availability,availability_as_of,availability_source\n'
        csv += f'DEMO,P0,Updated,T0,PG,12.5,{now},User checked market,available,{now},Official club report\n'
        updated = import_roster(self.data, csv)
        self.assertEqual(updated["players"][0]["credits"], 12.5)
        self.assertEqual(updated["appearances"], self.data["appearances"])
        self.assertNotEqual(updated["players"][0]["name"], self.data["players"][0]["name"])
        with self.assertRaisesRegex(ValueError, "season"):
            import_roster(self.data, csv.replace('DEMO,P0', 'E2025,P0'))


class ProviderTests(unittest.TestCase):
    def test_public_boxscore_cache_survives_repeat_reads(self):
        from unittest.mock import patch
        from app import providers
        game={'id':'1','home_team_id':'A','away_team_id':'B'}
        payload={'Stats':[{'PlayersStats':[{'Player_ID':'P000001','Player':'Example','Team':'A','Minutes':'20:00','Valuation':12}]},{'PlayersStats':[]}]}
        with tempfile.TemporaryDirectory() as folder,patch.object(providers,'_RAW_BOX_ROOT',Path(folder)),patch.object(providers,'get_json',return_value=payload) as fetch,patch('app.providers.time.sleep'):
            first=providers.public_boxscore(game,'E2025',fetch)
            second=providers.public_boxscore(game,'E2025',fetch)
            self.assertEqual(first,second)
            self.assertEqual(fetch.call_count,1)
            self.assertEqual(len(list(Path(folder).glob('*.json'))),1)

    def test_invalid_boxscore_never_poisoned_cache(self):
        from unittest.mock import patch
        from app import providers
        game={'id':'1','home_team_id':'A','away_team_id':'B'}
        with tempfile.TemporaryDirectory() as folder,patch.object(providers,'_RAW_BOX_ROOT',Path(folder)),patch.object(providers,'get_json',return_value={}) as fetch,patch('app.providers.time.sleep'):
            with self.assertRaises(ValueError):providers.public_boxscore(game,'E2025',fetch)
            self.assertEqual(list(Path(folder).iterdir()),[])

    def test_rate_limit_waits_for_retry_after_and_preserves_verification(self):
        from unittest.mock import patch,MagicMock
        import urllib.error
        from app.providers import get_json
        limited=urllib.error.HTTPError('https://api-live.euroleague.net/example',429,'limited',{'Retry-After':'2'},None)
        response=MagicMock();response.__enter__.return_value.read.return_value=b'{"ok":true}'
        with patch('app.providers.urllib.request.urlopen',side_effect=[limited,response]) as fetch,patch('app.providers.time.sleep') as wait:
            self.assertEqual(get_json('https://api-live.euroleague.net/example'),{'ok':True})
            self.assertEqual(fetch.call_count,2)
            self.assertTrue(any(call.args[0]==2 for call in wait.call_args_list))
            self.assertTrue(all(call.args[0].full_url.startswith('https://') for call in fetch.call_args_list))

    def test_time_parser_preserves_seconds(self):
        self.assertAlmostEqual(minutes("21:30"), 21.5)
        with self.assertRaises(ValueError):
            minutes("21:99")

    def test_schedule_rejects_ambiguous_time_and_status(self):
        with self.assertRaises(ValueError):
            schedule({"data": [{"local": {"club": {"code": "A", "name": "Alpha"}},
                                "visiting": {"club": {"code": "B", "name": "Beta"}}}]}, "E2026")

    def test_boxscore_identity_and_unknown_position(self):
        game = {"id": "1", "home_team_id": "A", "away_team_id": "B"}
        payload = {"Stats": [{"PlayersStats": [{"Player_ID": "001", "Player": "Example", "Minutes": "20:30", "Valuation": 12}]}, {"PlayersStats": []}]}
        pp, rr = boxscore(payload, game)
        self.assertEqual(pp[0]["position"], "UNK")
        self.assertEqual(rr[0]["opponent_id"], "B")
        self.assertEqual(rr[0]["minutes"], 20.5)
        payload["Stats"][0]["PlayersStats"][0].pop("Player_ID")
        with self.assertRaises(ValueError):
            boxscore(payload, game)

    def test_sync_is_repeatable_and_keeps_market_fields(self):
        from app.data import empty_dataset
        schedule_data = {"data": [{"gameCode": 1, "round": 1, "utcDate": "2026-01-01T12:00:00Z", "played": True,
                                  "local": {"club": {"code": "A", "name": "Alpha"}}, "visiting": {"club": {"code": "B", "name": "Beta"}}}]}
        box = {"Stats": [{"PlayersStats": [{"Player_ID": "001", "Player": "Example", "Minutes": "20:00", "Valuation": 12}]}, {"PlayersStats": []}]}
        calls = []
        def fetch(url):
            calls.append(url)
            if '/people?' in url:
                return {"data": [], "total": 0}
            return schedule_data if 'api-live' in url else box
        initial = sync(empty_dataset(), "E2026", fetch=fetch)
        initial["players"][0]["position"] = "PG"
        second = sync(initial, "E2026", fetch=fetch)
        self.assertEqual(initial, second)
        self.assertEqual(len(calls), 5)

    def test_official_road_schema_and_registration_join(self):
        from app.data import empty_dataset
        fixture = {"data": [{"gameCode": 1, "round": 1, "utcDate": "2026-01-01T12:00:00Z", "played": True,
                             "local": {"club": {"code": "A", "name": "Alpha"}}, "road": {"club": {"code": "B", "name": "Beta"}}}]}
        box = {"Stats": [{"PlayersStats": [{"Player_ID": "P000001 ", "Player": "Example", "Team": "A", "Minutes": "20:00", "Valuation": 12}]}, {"PlayersStats": []}]}
        people = {"data": [{"person": {"code": "000001", "name": "Example"}, "club": {"code": "A"},
                            "type": "J", "active": True, "positionName": "Center", "startDate": "2026-01-01"},
                           {"person": {"code": "COACH", "name": "Coach"}, "type": "E"}], "total": 2}
        def fetch(url):
            return people if '/people?' in url else fixture if 'api-live' in url else box
        result = sync(empty_dataset(), 'E2026', fetch=fetch)
        self.assertEqual(len(result['players']), 1)
        self.assertEqual(result['players'][0]['position'], 'C')
        self.assertEqual(result['players'][0]['id'], result['appearances'][0]['player_id'])
        self.assertEqual(result['players'][0]['availability'], 'unknown')


if __name__ == "__main__":
    unittest.main()
