from collections import Counter
import unittest
from app.demo import dataset
from app.data import utcnow
from app.scout import role
from app.squad_planner import plan_squad, lineup, coach_points


def planner_fixture():
    data=dataset()
    for p in data['players']:
        p['fantasy_player_id']=p['id'][1:]
        p['fantasy_position']=role(p['position'])
        p['price_matchday']=11
    for i,c in enumerate(data['coaches']):
        c.update(fantasy_player_id=str(900+i),credits=5,price_as_of=utcnow().isoformat(),price_matchday=11,price_source='Synthetic fixture')
    selected=[p for p in data['players'] if p['team_id'] in {'T0','T1'}]+[data['coaches'][0]]
    rows=[{'fantasy_player_id':p['fantasy_player_id'],'player_id':p['id'],'name':p['name'],
           'role':p.get('fantasy_position','H'),'team_id':p['team_id'],'team':p['team_id'],'credits':p['credits']} for p in selected]
    cost=sum(p['credits'] for p in rows)
    squad={'name':'Synthetic squad','players':rows,'budget':cost+10,'free_credits':10,'roster_value':cost,
           'complete':True,'matchday':11,'observed_at':utcnow().isoformat(),'transfers_remaining':3,
           'club_limit':6,'quotas':{'G':4,'F':4,'C':2,'H':1}}
    return data,squad


class PlannerTests(unittest.TestCase):
    def test_all_returned_alternatives_obey_budget_roles_club_and_transfer_limits(self):
        data,squad=planner_fixture();report=plan_squad(data,squad)
        self.assertTrue(report['available'])
        self.assertGreater(len(report['alternatives']),0)
        self.assertEqual(len({frozenset(p['fantasy_player_id'] for p in a['players']) for a in report['alternatives']}),len(report['alternatives']))
        for choice in report['alternatives']:
            rows=choice['players']
            self.assertEqual(Counter(p['role'] for p in rows),Counter(squad['quotas']))
            self.assertEqual(len({p['fantasy_player_id'] for p in rows}),11)
            self.assertLessEqual(sum(p['credits'] for p in rows),squad['budget']+1e-6)
            self.assertLessEqual(choice['transfer_count'],3)
            self.assertLessEqual(max(Counter(p['team_id'] for p in rows).values()),6)
            self.assertGreater(choice['improvement'],0)
            self.assertGreaterEqual(choice['free_credits'],0)

    def test_no_trades_and_missing_prices_do_not_produce_impossible_plans(self):
        data,squad=planner_fixture();squad['transfers_remaining']=0
        self.assertEqual(plan_squad(data,squad)['alternatives'],[])
        squad['free_credits']=None
        self.assertFalse(plan_squad(data,squad)['available'])

    def test_unknown_forecast_stays_locked_and_not_falsely_reported_as_full_score(self):
        data,squad=planner_fixture()
        locked=squad['players'][0]['player_id']
        data['appearances']=[a for a in data['appearances'] if a['player_id']!=locked]
        report=plan_squad(data,squad)
        self.assertEqual(report['score_kind'],'partial-known-components')
        self.assertIsNone(report['current_lineup'])
        for choice in report['alternatives']:
            self.assertIn(locked,[p['player_id'] for p in choice['players']])

    def test_already_planned_trades_can_be_revised_against_original_snapshot(self):
        data,squad=planner_fixture()
        start=[p['fantasy_player_id'] for p in squad['players']]
        baseline=list(start)
        for slot,replaced in zip([0,1,2,3],['10','11','12','13']):baseline[slot]=replaced
        squad.update(baseline_ids=baseline,baseline_inactive_ids=[],transfers_used=4,transfers_limit=4,transfers_remaining=0)
        report=plan_squad(data,squad)
        self.assertTrue(report['can_replan'])
        self.assertGreater(len(report['alternatives']),0)
        for choice in report['alternatives']:
            self.assertLessEqual(choice['net_transfer_count'],4)
            self.assertEqual(choice['net_transfer_count'],len({p['fantasy_player_id'] for p in choice['players']}-set(baseline)))

    def test_funding_swap_makes_expensive_upgrade_affordable(self):
        from unittest.mock import patch
        data,squad=planner_fixture()
        for p in squad['players']:p['credits']=10
        squad.update(budget=110,roster_value=110,free_credits=0,transfers_remaining=2)
        pool={p['fantasy_player_id']:{**p,'score':20,'availability':'unknown'} for p in squad['players']}
        pool['upgrade']={'fantasy_player_id':'upgrade','player_id':'upgrade','name':'Upgrade','role':'G','credits':15,'score':50,'team_id':'T2'}
        pool['funding']={'fantasy_player_id':'funding','player_id':'funding','name':'Funding','role':'F','credits':5,'score':19,'team_id':'T2'}
        with patch('app.squad_planner.candidates',return_value=pool):report=plan_squad(data,squad)
        self.assertGreater(len(report['alternatives']),0)
        for choice in report['alternatives']:
            self.assertLessEqual(choice['roster_value'],110)
            ids={p['fantasy_player_id'] for p in choice['players']}
            self.assertIn('upgrade',ids)
            self.assertIn('funding',ids)

    def test_closed_previous_round_is_the_baseline_even_after_current_draft_changes(self):
        import copy
        data,squad=planner_fixture()
        original=copy.deepcopy(squad['players'])
        expected=plan_squad(data,squad)['current_model_score']
        byid={p['fantasy_player_id']:p for p in data['players']}
        for slot,incoming in zip([0,1,2,3],['10','11','12','13']):
            p=byid[incoming]
            squad['players'][slot]={**squad['players'][slot],'fantasy_player_id':incoming,'player_id':p['id'],'name':p['name'],'credits':p['credits']}
        squad.update(previous_round={'matchday':10,'players':original,'roster_value':sum(p['credits'] for p in original),'complete':True},
                     baseline_ids=[p['fantasy_player_id'] for p in original],requires_closed_round=True,
                     transfers_used=4,transfers_limit=4,transfers_remaining=0)
        report=plan_squad(data,squad)
        self.assertEqual(report['baseline_matchday'],10)
        self.assertEqual(report['current_model_score'],expected)
        self.assertEqual({p['fantasy_player_id'] for p in report['current_players']},{p['fantasy_player_id'] for p in original})
        self.assertGreater(len(report['alternatives']),0)
        for choice in report['alternatives']:self.assertLessEqual(choice['net_transfer_count'],4)
        squad.pop('previous_round')
        self.assertFalse(plan_squad(data,squad)['available'])

    def test_explicit_keep_choice_is_enforced_without_inventing_a_forecast(self):
        from unittest.mock import patch
        from app.squad_planner import candidates
        from app.analysis import analyze
        data,squad=planner_fixture();pool=candidates(data,analyze(data))
        pool['10']['score']=None
        with patch('app.squad_planner.candidates',return_value=pool):report=plan_squad(data,squad,required_ids=['10'])
        self.assertGreater(len(report['alternatives']),0)
        self.assertIn(pool['10']['name'],report['missing_forecasts'])
        for choice in report['alternatives']:
            selected=next(p for p in choice['players'] if p['fantasy_player_id']=='10')
            self.assertIsNone(selected['score'])
            self.assertIsNone(choice['lineup'])

    def test_lineup_has_legal_five_captain_sixth_bench_and_coach(self):
        _,squad=planner_fixture();rows=squad['players']
        for i,p in enumerate(rows):p['score']=10+i
        result=lineup(rows)
        self.assertEqual(len(result['starters']),5)
        self.assertIn(result['captain'],result['starters'])
        ids=result['starters']+[result['sixth']]+result['bench']+[result['coach']]
        self.assertEqual(len(set(ids)),11)
        byid={p['fantasy_player_id']:p['score'] for p in rows}
        expected=sum(byid[i] for i in result['starters'])+byid[result['captain']]+byid[result['sixth']]+.5*sum(byid[i] for i in result['bench'])+byid[result['coach']]
        self.assertEqual(result['score'],expected)
        self.assertEqual(coach_points(20),20)
        self.assertEqual(coach_points(-20),-20)
