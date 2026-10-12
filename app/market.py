"""Read-only authorized fantasy-price connector. No credential values are logged."""
import argparse
import copy
import json
import os
from pathlib import Path
import urllib.request
import urllib.error
from urllib.parse import urlparse

from .data import Store, utcnow, validate, number, timestamp
from .providers import get_json

BASE = 'https://fantaking-api.dunkest.com/api/v1'
TOKEN_NAME = 'FANTASY_ACCESS_TOKEN'


def allowed_destination(url):
    parsed=urlparse(url)
    return parsed.scheme=='https' and parsed.hostname=='fantaking-api.dunkest.com' and parsed.port in {None,443} and not parsed.username and not parsed.password


class FantasyRedirectGuard(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_destination(newurl):
            raise ValueError('Fantasy authentication redirect outside the approved host was refused')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def connection_status():
    return {'credential_present':bool(os.environ.get(TOKEN_NAME)), 'variable_name':TOKEN_NAME,
            'live_schema_verified':False, 'supports':'prices', 'availability_feed_verified':False}


def authorized_json(url):
    if not allowed_destination(url):raise ValueError('Fantasy authentication is restricted to its approved HTTPS host')
    token = os.environ.get(TOKEN_NAME)
    if not token:
        raise ValueError('Fantasy access is not configured; add FANTASY_ACCESS_TOKEN securely in environment settings, or import CSV')
    req = urllib.request.Request(url, headers={'User-Agent':'FantasyMatchupLab/0.1', 'Accept':'application/json',
                                              'Authorization':'Bearer '+token})
    try:
        opener=urllib.request.build_opener(FantasyRedirectGuard())
        with opener.open(req,timeout=20) as response:
            body = response.read(8_000_001)
    except urllib.error.HTTPError as exc:
        # Response bodies can contain account details; do not include them in errors.
        raise ValueError(f'Fantasy server returned HTTP {exc.code}; existing data retained') from None
    if len(body)>8_000_000:raise ValueError('Fantasy response too large')
    return json.loads(body)


def exact_name(last, first):
    # Exact spelling, case-insensitive and whitespace-normalized. No transliteration,
    # accent removal, substring matching, edit-distance matching or name guesses.
    if not isinstance(last,str) or not isinstance(first,str):return None
    return ' '.join((last+' '+first).casefold().split())


def apply_prices(existing, payload, matchday, observed_at, source):
    if not isinstance(payload,dict) or not isinstance(payload.get('data'),list):
        raise ValueError('Fantasy market schema requires verification: expected data array')
    meta = payload.get('meta',{})
    if isinstance(meta,dict) and meta.get('last_page',1)>1:
        raise ValueError('Incomplete paginated market response; do not import partial prices')
    result = copy.deepcopy(existing)
    teams = {t['id']:t for t in result['teams']}
    names = {}
    for p in result['players']:
        if ',' not in p['name']:continue
        last, first = p['name'].split(',',1)
        key = (teams[p['team_id']].get('tv_code'),exact_name(last,first))
        names.setdefault(key,[]).append(p)
    mapped, unmatched, coaches, seen = 0, [], 0, set()
    for row in payload['data']:
        if not isinstance(row,dict):raise ValueError('Invalid fantasy player record')
        if isinstance(row.get('id'),bool) or not str(row.get('id','')).isdigit():
            raise ValueError('Fantasy market record has no valid player id')
        position = row.get('position',{})
        if not isinstance(position,dict):raise ValueError('Fantasy position schema requires verification')
        if position.get('name') == 'Head Coach':
            coaches += 1
            continue
        if position.get('name') not in {'Guard','Forward','Center'}:
            raise ValueError('Unknown fantasy position')
        team = row.get('team',{})
        if not isinstance(team,dict) or not isinstance(team.get('abbreviation'),str):
            raise ValueError('Fantasy team schema requires verification')
        candidates = names.get((team['abbreviation'],exact_name(row.get('last_name'),row.get('first_name'))),[])
        if len(candidates)!=1:
            unmatched.append({'fantasy_id':row.get('id'),'reason':'no exact unique team/name match'})
            continue
        p = candidates[0]
        if p['id'] in seen:raise ValueError('Multiple fantasy records resolve to the same official player')
        seen.add(p['id'])
        expected = {'G':'Guard','PG':'Guard','SG':'Guard','F':'Forward','SF':'Forward','PF':'Forward','C':'Center'}.get(p['position'])
        if expected and expected != position['name']:
            raise ValueError('Fantasy position differs from official roster; mapping must be checked')
        quote = number(row.get('quotation'),'quotation',0.01,1000)
        p.update(credits=quote,price_as_of=observed_at,price_source=source,
                 fantasy_player_id=str(row.get('id')),price_matchday=matchday)
        # is_injured=false is NOT proof that a player will play. No status inference.
        mapped += 1
    if not mapped:raise ValueError('No exact player matches; roster TV codes and source identifiers must be verified')
    if source not in result['sources']:result['sources'].append(source)
    validate(result)
    return result, {'matched':mapped,'unmatched':len(unmatched),'unmatched_records':unmatched,'coaches_skipped':coaches,
                    'matchday':matchday,'observed_at':observed_at,'source':source,'authentication_used':True,
                    'note':'Exact unique name + official TV team code matches; injury status is not inferred'}


def sync_prices(existing, public=get_json, authorized=authorized_json):
    if existing['mode']!='live':raise ValueError('Fantasy prices can only update live data')
    cfg = public(BASE+'/leagues/10/config').get('data',{})
    list_id = cfg.get('current_players_list_id')
    day = cfg.get('current_matchday',{})
    if type(list_id) is not int or type(day.get('id')) is not int or type(day.get('number')) is not int:
        raise ValueError('Current fantasy league configuration schema requires verification')
    # Explicitly verify the round agrees with the live schedule before merging.
    upcoming = [g for g in existing['games'] if g['status']=='scheduled' and timestamp(g['date'])>utcnow()]
    if not upcoming:raise ValueError('No upcoming official fixtures for this snapshot')
    next_game = min(upcoming,key=lambda g:timestamp(g['date']))
    if next_game['round'] != day['number']:
        raise ValueError('Fantasy matchday differs from the active statistics season; do not merge prices')
    url = BASE+f'/players-lists/{list_id}/matchdays/{day["id"]}/players?per_page=1000&page=1'
    payload = authorized(url)
    updated, report = apply_prices(existing,payload,day['number'],utcnow().isoformat(),url)
    return updated,report


def main():
    argparse.ArgumentParser(description='Read-only fantasy price sync using an existing authorized session token').parse_args()
    store = Store(Path(__file__).resolve().parent.parent/'.data'/'live.json')
    updated, report = sync_prices(store.read())
    store.save(updated)
    print(json.dumps({k:v for k,v in report.items() if k!='unmatched_records'},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
