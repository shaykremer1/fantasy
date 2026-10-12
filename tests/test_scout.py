import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from app.demo import dataset
from app.analysis import analyze
from app.scout import scout,role
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
