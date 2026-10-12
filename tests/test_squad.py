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
