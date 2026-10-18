import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from app.demo import dataset
from app.analysis import analyze
from app.scout import scout,role,surprise_picks
from app.server import Application


class ScoutTests(unittest.TestCase):
    def test_three_each_role_and_opponent_explanation(self):
        data=dataset();result=scout(data,analyze(data))
        for key in ('C','F','G'):
            self.assertEqual(len(result['top_three'][key]),3)
            self.assertTrue(all(p['role']==key and p['opponent_games']>=3 for p in result['top_three'][key]))
            scores=[p['scout_score'] for p in result['top_three'][key]]
            self.assertEqual(scores,sorted(scores,reverse=True))
        self.assertEqual(role('SG'),'G')
        self.assertEqual(role('PF'),'F')

    def test_surprises_rank_upside_for_price_not_raw_points(self):
        base=dict(role='C',recent_games=5,projected_minutes=22,availability='unknown',matchup_index=1.2)
        expensive=dict(base,player_id='expensive',credits=20,recent_pir=20,recent_pir_high=30,scout_score=24)
        value=dict(base,player_id='value',credits=8,recent_pir=12,recent_pir_high=24,scout_score=14.4)
        picks=surprise_picks([expensive,value],set())
        self.assertEqual(picks[0]['player_id'],'value')
        self.assertAlmostEqual(picks[0]['upside_score'],21.6)
        self.assertAlmostEqual(picks[0]['value_score'],2.7)
        self.assertEqual(surprise_picks([value],{'value'}),[])
        for change in [dict(credits=None),dict(credits=0),dict(availability='doubtful'),
                       dict(availability='out'),dict(projected_minutes=8),dict(matchup_index=.9),
                       dict(recent_games=2),dict(scout_score=4)]:
            self.assertEqual(surprise_picks([{**value,**change}],set()),[])

    def test_three_surprises_are_selected_independently_per_position(self):
        candidates=[dict(player_id=f'{role}{i}',role=role,credits=8+i,recent_games=5,
                         recent_pir=12,recent_pir_high=24,scout_score=14.4,
                         projected_minutes=22,availability='unknown',matchup_index=1.2)
                    for role in ('C','F','G') for i in range(5)]
        picks=surprise_picks(candidates,set())
        self.assertEqual(len(picks),9)
        for role in ('C','F','G'):
            self.assertEqual([p['player_id'] for p in picks if p['role']==role],
                             [f'{role}{i}' for i in range(3)])
        self.assertEqual(len(surprise_picks(candidates[:2],set())),2)

    def test_surprise_high_uses_only_history_before_target_round(self):
        data=dataset()
        first=analyze(data)
        future=data['games'][-1]
        data['appearances'].append(dict(game_id=future['id'],player_id='P10',opponent_id='T0',minutes=30,pir=999))
        second=analyze(data)
        self.assertEqual([(p['player_id'],p['recent_pir_high']) for p in first['recommendations']],
                         [(p['player_id'],p['recent_pir_high']) for p in second['recommendations']])

    def test_new_game_is_saved_before_recommendations_refresh(self):
        with tempfile.TemporaryDirectory() as folder:
            app=Application(Path(folder)/'live.json')
            data=dataset();data['mode']='live';data['season']='E2026';app.store.save(data)
            refreshed=dataset();refreshed['mode']='live';refreshed['season']='E2026'
            refreshed['appearances'][0]['pir']=55
            with patch('app.server.sync',return_value=refreshed) as source:
                self.assertTrue(app.refresh_once())
            self.assertEqual(app.store.read()['appearances'][0]['pir'],55)
            self.assertEqual(source.call_args.args[1],'E2026')
            self.assertIsNotNone(app.auto['last_success'])
            with patch('app.server.sync',side_effect=ValueError('source unavailable')):
                self.assertFalse(app.refresh_once())
            self.assertEqual(app.store.read()['appearances'][0]['pir'],55)

    def test_automatic_price_failure_keeps_successful_statistics(self):
        with tempfile.TemporaryDirectory() as folder:
            app=Application(Path(folder)/'live.json')
            data=dataset();data['mode']='live';data['season']='E2026';app.store.save(data)
            with patch('app.server.sync',return_value=data), patch('app.server.connection_status',return_value={'credential_present':True}), patch('app.server.sync_squad',return_value={'name':'Test squad'}), patch('app.server.sync_prices',side_effect=ValueError('unauthorized')):
                self.assertTrue(app.refresh_once())
            self.assertEqual(app.store.read()['season'],'E2026')
            self.assertEqual(app.market_error,'unauthorized')

    def test_automatic_prices_saved_after_statistics(self):
        with tempfile.TemporaryDirectory() as folder:
            app=Application(Path(folder)/'live.json')
            data=dataset();data['mode']='live';data['season']='E2026';app.store.save(data)
            import copy
            priced=copy.deepcopy(data);priced['players'][0]['credits']=15
            with patch('app.server.sync',return_value=data), patch('app.server.connection_status',return_value={'credential_present':True}), patch('app.server.sync_squad',return_value={'name':'Test squad'}), patch('app.server.sync_prices',return_value=(priced,{'matched':1})):
                self.assertTrue(app.refresh_once())
            self.assertEqual(app.store.read()['players'][0]['credits'],15)
            self.assertEqual(app.market_report['matched'],1)
