import unittest
from app.squad import parse_squad, sync_squad
from app.data import empty_dataset, utcnow


class SquadTests(unittest.TestCase):
    def fixtures(self):
        cfg={'current_matchday':{'id':5,'number':5},'game_modes_configs':[{'game_mode_id':1,
             'players_per_positions':[{'name':n,'num_players':c} for n,c in [('Guard',4),('Forward',4),('Center',2),('Head Coach',1)]]}]}
        info={'credits':112.5,'trades':1,'max_num_trades_per_matchday':4,'max_num_same_team_players':6}
        rows=[]
        for i,role in enumerate(['Guard']*4+['Forward']*4+['Center']*2+['Head Coach']):
            rows.append({'id':i+1,'first_name':'Jane','last_name':f'Doe {i}', 'quotation':10,
                         'position':{'name':role},'team':{'name':'A','abbreviation':'A'}})
        return cfg,info,{'players':rows}

    def test_total_budget_free_credit_and_trade_limits(self):
        cfg,info,roster=self.fixtures()
        squad=parse_squad(empty_dataset(),cfg,{'name':'My squad'},info,roster,utcnow().isoformat())
        self.assertEqual(squad['free_credits'],2.5)
        self.assertEqual(squad['budget'],112.5)
        self.assertEqual(squad['transfers_remaining'],3)
        self.assertTrue(squad['complete'])
        self.assertNotIn('user_id',squad)

    def test_missing_price_never_becomes_zero_and_invalid_rules_fail(self):
        cfg,info,roster=self.fixtures();roster['players'][0]['quotation']=None
        squad=parse_squad(empty_dataset(),cfg,{'name':'My squad'},info,roster,utcnow().isoformat())
        self.assertIsNone(squad['free_credits'])
        cfg['game_modes_configs'][0]['players_per_positions'][0]['num_players']=5
        with self.assertRaises(ValueError):parse_squad(empty_dataset(),cfg,{'name':'My squad'},info,roster,utcnow().isoformat())

    def test_duplicate_roster_and_negative_trade_limit_rejected(self):
        cfg,info,roster=self.fixtures();roster['players'][1]['id']=roster['players'][0]['id']
        with self.assertRaises(ValueError):parse_squad(empty_dataset(),cfg,{'name':'My squad'},info,roster,utcnow().isoformat())
        cfg,info,roster=self.fixtures();info['max_num_trades_per_matchday']=-1
        with self.assertRaises(ValueError):parse_squad(empty_dataset(),cfg,{'name':'My squad'},info,roster,utcnow().isoformat())

    def test_snapshot_and_creation_round_limits_are_preserved(self):
        cfg,info,roster=self.fixtures()
        roster['latest_snapshot']={'players':[{'id':i} for i in range(1,12)]}
        roster['snapshot_players_current_status']=[{'id':1,'active':False}]
        s=parse_squad(empty_dataset(),cfg,{'name':'My squad'},info,roster,utcnow().isoformat())
        self.assertEqual(s['baseline_ids'],[str(i) for i in range(1,12)])
        self.assertEqual(s['baseline_inactive_ids'],['1'])
        info['created_on_matchday_id']=5
        s=parse_squad(empty_dataset(),cfg,{'name':'My squad'},info,roster,utcnow().isoformat())
        self.assertIsNone(s['transfers_limit'])

    def test_each_refresh_reads_the_new_closed_round_and_current_prices(self):
        from datetime import timedelta
        from unittest.mock import patch
        cfg,info,roster=self.fixtures()
        cfg['previous_matchday']={'id':4,'number':4}
        data=empty_dataset()
        data['teams']=[{'id':'A','name':'A'}]
        data['games']=[{'id':'future','round':5,'date':(utcnow()+timedelta(days=1)).isoformat(),'status':'scheduled'}]
        data['players']=[{'id':f'P{i}','fantasy_player_id':str(i),'name':'Mapped person','team_id':'A','credits':13,
                          'price_matchday':5,'price_as_of':utcnow().isoformat()} for i in range(1,13)]
        original=[dict(p) for p in roster['players']]
        roster['players'][0]={**roster['players'][0],'id':12,'last_name':'New player'}
        requests=[]
        def authorized(url):
            requests.append(url)
            if '/user/config?' in url:return {'data':{'fantasy_teams':[{'id':99,'name':'Owner squad','league_id':10,'game_mode_id':1}]}}
            if url.endswith('/4/roster'):return {'data':{'players':original}}
            if url.endswith('/roster'):return {'data':roster}
            return {'data':info}
        result=sync_squad(data,public=lambda url:{'data':cfg},authorized=authorized)
        self.assertEqual(result['previous_round']['matchday'],4)
        self.assertEqual(result['previous_round']['players'][0]['fantasy_player_id'],'1')
        self.assertEqual(result['previous_round']['players'][0]['credits'],13)
        self.assertEqual(result['draft_transfers']['in'][0]['fantasy_player_id'],'12')
        self.assertIn('/user/config?game=7',requests[0])
        cfg['previous_matchday']={'id':5,'number':5};cfg['current_matchday']={'id':6,'number':6};data['games'][0]['round']=6
        requests.clear()
        sync_squad(data,public=lambda url:{'data':cfg},authorized=authorized)
        self.assertTrue(any(url.endswith('/5/roster') for url in requests))
