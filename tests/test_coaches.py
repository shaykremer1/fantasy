import copy
import unittest
from app.demo import dataset
from app.analysis import analyze
from app.coaches import recommend_coaches
from app.data import validate
from app.providers import schedule


class CoachTests(unittest.TestCase):
    def test_shortlist_has_real_fixture_and_sorted_matchup_explanations(self):
        data = dataset()
        picks = recommend_coaches(data, analyze(data))
        self.assertEqual(len(picks), 3)
        self.assertEqual([p['matchup_margin'] for p in picks],
                         sorted((p['matchup_margin'] for p in picks), reverse=True))
        for p in picks:
            self.assertGreaterEqual(p['opponent_form']['games'], 3)
            self.assertIn(p['game_id'], {g['id'] for g in data['games'] if g['status'] == 'scheduled'})

    def test_opponent_results_change_ranking(self):
        data = dataset(); analysis = analyze(data)
        before = recommend_coaches(data, analysis)
        opponent = next(t['id'] for t in data['teams'] if t['name'] == before[0]['opponent'])
        for g in data['games']:
            if g['status'] == 'finished' and opponent in (g['home_team_id'], g['away_team_id']):
                g['home_score'] = 130 if g['home_team_id'] == opponent else 60
                g['away_score'] = 130 if g['away_team_id'] == opponent else 60
        after = recommend_coaches(data, analysis)
        self.assertNotEqual(before, after)
        self.assertNotEqual(before[0]['coach_id'], after[0]['coach_id'])

    def test_missing_scores_and_inactive_coaches_are_not_recommended(self):
        data = dataset()
        for g in data['games']:
            g.pop('home_score', None); g.pop('away_score', None)
        self.assertEqual(recommend_coaches(data, analyze(data)), [])
        data = dataset()
        for c in data['coaches']: c['active'] = False
        self.assertEqual(recommend_coaches(data, analyze(data)), [])

    def test_future_results_do_not_leak_into_selected_round(self):
        data = dataset(); analysis = analyze(data); before = recommend_coaches(data, analysis)
        future = copy.deepcopy(data['games'][-1])
        future.update(id='future', status='finished', home_score=200, away_score=30)
        data['games'].append(future)
        self.assertEqual(recommend_coaches(data, analysis), before)

    def test_official_scores_only_for_completed_games(self):
        item = {'gameCode': 1, 'round': 1, 'utcDate': '2026-10-01T18:00:00Z', 'played': True,
                'local': {'club': {'code': 'A', 'name': 'A'}, 'score': 90},
                'road': {'club': {'code': 'B', 'name': 'B'}, 'score': 80}}
        self.assertEqual(schedule({'data': [item]}, 'E2026')[1][0]['home_score'], 90)
        item['played'] = False
        self.assertNotIn('home_score', schedule({'data': [item]}, 'E2026')[1][0])

    def test_invalid_scores_rejected(self):
        data = dataset(); data['games'][0]['home_score'] = True
        with self.assertRaises(ValueError): validate(data)
