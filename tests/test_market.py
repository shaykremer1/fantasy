import copy
import os
import unittest
from unittest.mock import patch

from app.data import empty_dataset,utcnow
from app.market import apply_prices, authorized_json, FantasyRedirectGuard
import urllib.request


class MarketTests(unittest.TestCase):
    def setUp(self):
        self.data=empty_dataset()
        self.data['teams']=[{'id':'A','name':'Alpha','tv_code':'AAA'}]
        self.data['players']=[{'id':'P000001','name':'DOE, JANE','team_id':'A','position':'G','availability':'unknown'}]
        self.payload={'data':[{'id':7,'first_name':'Jane','last_name':'Doe','quotation':12.5,
                              'position':{'name':'Guard'},'team':{'abbreviation':'AAA'},'is_injured':False}]}

    def test_price_mapping_preserves_unknown_availability_and_input(self):
        updated,report=apply_prices(self.data,self.payload,5,utcnow().isoformat(),'Official fantasy test fixture')
        self.assertEqual(updated['players'][0]['credits'],12.5)
        self.assertEqual(updated['players'][0]['availability'],'unknown')
        self.assertNotIn('credits',self.data['players'][0])
        self.assertEqual(report['matched'],1)

    def test_ambiguous_names_wrong_team_and_incomplete_pages_are_rejected(self):
        for modification in ['duplicate','team','page']:
            data,payload=copy.deepcopy(self.data),copy.deepcopy(self.payload)
            if modification=='duplicate':
                other=copy.deepcopy(data['players'][0]);other['id']='P000002';data['players'].append(other)
            elif modification=='team':payload['data'][0]['team']['abbreviation']='OTHER'
            else:payload['meta']={'last_page':2}
            with self.subTest(modification=modification),self.assertRaises(ValueError):
                apply_prices(data,payload,5,utcnow().isoformat(),'Test')

    def test_coach_prices_are_mapped_separately(self):
        self.data['coaches'] = [{'id':'COACH-1','name':'COACH, JIM','team_id':'A','active':True}]
        self.payload['data'].append({'id':8,'first_name':'Jim','last_name':'Coach','quotation':6.5,
                                     'position':{'name':'Head Coach'},'team':{'abbreviation':'AAA'}})
        result,report=apply_prices(self.data,self.payload,5,utcnow().isoformat(),'Test source')
        self.assertEqual(result['coaches'][0]['credits'],6.5)
        self.assertEqual(report['coaches_matched'],1)
        self.assertEqual(result['players'][0]['credits'],12.5)

    def test_stale_or_wrong_round_quote_is_not_presented_as_current(self):
        from app.demo import dataset
        from app.analysis import analyze
        from datetime import timedelta
        data=dataset();analysis=analyze(data)
        player=data['players'][0]
        player['price_matchday']=analysis['target_round']+1
        result=analyze(data)
        candidate=next(p for p in result['recommendations'] if p['player_id']==player['id'])
        self.assertIsNone(candidate['credits'])
        self.assertIsNotNone(candidate['reported_credits'])
        self.assertEqual(result['coverage']['fresh_prices'],29)
        player['price_matchday']=analysis['target_round']
        player['price_as_of']=(utcnow()-timedelta(hours=49)).isoformat()
        self.assertIsNone(next(p for p in analyze(data)['recommendations'] if p['player_id']==player['id'])['credits'])

    def test_fantasy_role_can_differ_from_basketball_role(self):
        self.payload['data'][0]['position']['name']='Forward'
        updated,report=apply_prices(self.data,self.payload,5,utcnow().isoformat(),'Fantasy source')
        self.assertEqual(updated['players'][0]['position'],'G')
        self.assertEqual(updated['players'][0]['fantasy_position'],'F')
        self.assertEqual(updated['players'][0]['credits'],12.5)
        self.assertEqual(report['position_differences'],['P000001'])

    def test_missing_credential_fails_before_any_request(self):
        with patch.dict(os.environ,{},clear=True),patch('urllib.request.urlopen') as request:
            with self.assertRaisesRegex(ValueError,'securely'):
                authorized_json('https://fantaking-api.dunkest.com/api/v1/example')
            request.assert_not_called()

    def test_authentication_cannot_be_sent_or_redirected_to_other_hosts(self):
        with self.assertRaises(ValueError):
            authorized_json('https://other.example/api')
        request=urllib.request.Request('https://fantaking-api.dunkest.com/api/v1/example')
        for target in ['https://other.example/path','http://fantaking-api.dunkest.com/path']:
            with self.subTest(target=target),self.assertRaises(ValueError):
                FantasyRedirectGuard().redirect_request(request,None,302,'redirect',{},target)


if __name__=='__main__':unittest.main()
