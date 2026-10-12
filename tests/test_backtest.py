import copy
import unittest

from app.backtest import before_round, evaluate, metrics
from app.demo import dataset
from app.analysis import analyze


def history_fixture():
    data = dataset()
    players = {p['id']:p for p in data['players']}
    for row in data['appearances']:
        row['position'] = players[row['player_id']]['position']
    return data


class BacktestTests(unittest.TestCase):
    def test_future_performance_current_roster_and_market_do_not_leak(self):
        data = history_fixture()
        snap,now = before_round(data,6)
        expected = analyze(snap,target_round=6,now=now)
        altered = copy.deepcopy(data)
        games = {g['id']:g for g in altered['games']}
        for row in altered['appearances']:
            if games[row['game_id']]['round']>=6:
                row['pir']=150
                row['position']='C'
        for p in altered['players']:
            p.update(team_id='T1',position='C',availability='out',credits=999)
        snap2,now2=before_round(altered,6)
        actual=analyze(snap2,target_round=6,now=now2)
        self.assertEqual(expected['defenses'],actual['defenses'])
        self.assertEqual(expected['recommendations'],actual['recommendations'])

    def test_warmup_skips_holdout_and_paired_counts_are_explicit(self):
        report=evaluate(history_fixture(),through_round=10,holdout_rounds=2)
        self.assertEqual(report['holdout_rounds'],[9,10])
        self.assertGreater(report['summary']['n'],0)
        self.assertEqual(report['summary']['n'],sum(v['n'] for v in report['segments'].values()))
        self.assertTrue(all(r['round']>=5 for r in report['records']))

    def test_dnp_is_scored_as_zero_not_dropped(self):
        data=history_fixture()
        game=next(g for g in data['games'] if g['round']==10)
        row=next(r for r in data['appearances'] if r['game_id']==game['id'])
        row.update(minutes=0,pir=0)
        report=evaluate(data,through_round=10,holdout_rounds=2)
        rec=next(r for r in report['records'] if r['game_id']==row['game_id'] and r['player_id']==row['player_id'])
        self.assertEqual(rec['actual'],0)
        self.assertGreater(report['summary']['dnp'],0)

    def test_missing_historical_role_is_not_filled_from_current_role(self):
        data=dataset()
        report=evaluate(data,through_round=10,holdout_rounds=2)
        self.assertEqual(report['summary']['n'],0)
        self.assertIsNone(report['summary']['model_mae'])

    def test_metrics_use_same_observations_and_signed_improvement(self):
        rows=[{'baseline':10,'predicted':12,'actual':9,'minutes':20},
              {'baseline':10,'predicted':8,'actual':6,'minutes':0}]
        m=metrics(rows)
        self.assertEqual(m['baseline_mae'],2.5)
        self.assertEqual(m['model_mae'],2.5)
        self.assertEqual(m['dnp'],1)
        self.assertEqual(m['mae_improvement'],0)
        self.assertEqual(metrics([])['n'],0)

    def test_error_interval_resamples_games_and_preserves_sign(self):
        rows=[{'baseline':8,'predicted':9,'actual':10,'minutes':20,'game_id':str(i//2)} for i in range(10)]
        m=metrics(rows,bootstrap=True)
        self.assertEqual(m['games'],5)
        self.assertEqual(m['mae_improvement_ci95'],[1,1])


if __name__=='__main__':unittest.main()
