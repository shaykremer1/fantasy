"""Read-only owner squad import using routes present in the official public client."""
from .market import BASE, authorized_json
from .providers import get_json
from .data import number, text, utcnow, timestamp
from collections import Counter
from .analysis import fresh

ROLES = {'Guard': 'G', 'Forward': 'F', 'Center': 'C', 'Head Coach': 'H'}


def object_data(payload, field):
    if not isinstance(payload, dict):
        raise ValueError(f'{field}: expected an object')
    body = payload.get('data', payload)
    if not isinstance(body, dict):
        raise ValueError(f'{field}: expected an object body')
    return body


def sync_squad(data, public=get_json, authorized=authorized_json):
    cfg = object_data(public(BASE+'/leagues/10/config'), 'league config')
    day = cfg.get('current_matchday', {})
    if type(day.get('id')) is not int or type(day.get('number')) is not int:
        raise ValueError('Squad matchday schema requires verification')
    future = [g for g in data['games'] if g['status'] == 'scheduled' and timestamp(g['date']) > utcnow()]
    if not future or min(future, key=lambda g: timestamp(g['date']))['round'] != day['number']:
        raise ValueError('Squad matchday does not match the upcoming EuroLeague round')
    user = object_data(authorized(BASE+'/user/config?game=7'), 'user config')
    teams = user.get('fantasy_teams')
    if not isinstance(teams, list):
        raise ValueError('Owner team list schema requires verification')
    teams = [t for t in teams if t.get('league_id') == 10 and t.get('game_mode_id') == 1]
    if len(teams) != 1 or type(teams[0].get('id')) is not int:
        raise ValueError('Expected exactly one owner EuroLeague Classic team')
    team = teams[0]
    root = BASE+f'/fantasy-teams/{team["id"]}/matchdays/{day["id"]}'
    info = object_data(authorized(root), 'team finances')
    roster = object_data(authorized(root+'/roster'), 'team roster')
    observed = utcnow().isoformat()
    result = parse_squad(data, cfg, team, info, roster, observed)
    previous = cfg.get('previous_matchday')
    if isinstance(previous, dict) and type(previous.get('id')) is int and type(previous.get('number')) is int:
        prior_roster = object_data(authorized(BASE+f'/fantasy-teams/{team["id"]}/matchdays/{previous["id"]}/roster'), 'previous round roster')
        prior = parse_squad(data,cfg,team,info,prior_roster,observed)
        prices = {str(p['fantasy_player_id']):p for p in [*data['players'],*data.get('coaches',[])] if p.get('fantasy_player_id') is not None}
        current_prices = {p['fantasy_player_id']:p['credits'] for p in result['players']}
        for p in prior['players']:
            quote = prices.get(p['fantasy_player_id'], {})
            p['credits'] = current_prices.get(p['fantasy_player_id'], quote.get('credits') if quote.get('price_matchday') == result['matchday'] and fresh(quote.get('price_as_of'),48,utcnow()) else None)
        value = sum(p['credits'] for p in prior['players']) if all(p['credits'] is not None for p in prior['players']) else None
        result['previous_round'] = {'matchday':previous['number'], 'players':prior['players'],
                                    'roster_value':round(value,2) if value is not None else None,
                                    'complete':prior['complete']}
        result['baseline_ids'] = [p['fantasy_player_id'] for p in prior['players']] if prior['complete'] else None
        old = set(result.get('baseline_ids') or [])
        result['draft_transfers'] = {'in':[p for p in result['players'] if p['fantasy_player_id'] not in old],
                                    'out':[p for p in prior['players'] if p['fantasy_player_id'] not in {q['fantasy_player_id'] for q in result['players']}]}
    result['preferred_incoming_ids'] = []
    result['requires_closed_round'] = True
    return result


def parse_squad(data, cfg, team, info, roster, observed_at):
    rows = roster.get('players')
    if not isinstance(rows, list) or len(rows) > 30:
        raise ValueError('Squad players schema requires verification')
    modes = [c for c in cfg.get('game_modes_configs', []) if c.get('game_mode_id') == 1]
    if len(modes) != 1:
        raise ValueError('Classic roster rules missing from league configuration')
    rules = modes[0]
    quotas = {ROLES[p['name']]: p['num_players'] for p in rules.get('players_per_positions', []) if p.get('name') in ROLES}
    if quotas != {'G':4, 'F':4, 'C':2, 'H':1}:
        raise ValueError('Classic position limits changed; optimizer requires review')
    records = [*data['players'], *data.get('coaches', [])]
    identities = {str(p['fantasy_player_id']): p for p in records if p.get('fantasy_player_id') is not None}
    players, seen = [], set()
    for row in rows:
        ident = row.get('id')
        if type(ident) is not int or ident in seen:
            raise ValueError('Invalid or duplicate squad player id')
        seen.add(ident)
        role = ROLES.get(row.get('position', {}).get('name'))
        if role is None:
            raise ValueError('Unknown squad fantasy position')
        club = row.get('team', {})
        own = identities.get(str(ident))
        price = row.get('quotation')
        if price is not None: number(price, 'squad quotation', 0.01, 1000)
        players.append({'fantasy_player_id': str(ident), 'player_id': own['id'] if own else None,
                        'name': text((row.get('last_name') or '')+', '+(row.get('first_name') or ''), 'squad name'),
                        'role': role, 'team': club.get('name'), 'team_code': club.get('abbreviation'),
                        'team_id': own['team_id'] if own else None, 'credits': price,
                        'image_url': own.get('image_url') if own else None,
                        'court_position': row.get('court_position'), 'captain': row.get('is_captain') is True,
                        'match_played': row.get('match_played') is True,
                        'is_injured': row.get('is_injured') is True})
    # Official client passes total credits minus sum(quotation) as remaining_credits.
    budget = number(info.get('credits'), 'team total credits', 0, 10000)
    used = info.get('trades')
    maximum = info.get('max_num_trades_per_matchday')
    club_limit = info.get('max_num_same_team_players')
    if type(used) is not int or used < 0 or (maximum is not None and (type(maximum) is not int or maximum < 0)):
        raise ValueError('Squad trade limits require verification')
    if type(club_limit) is not int or club_limit < 1:
        raise ValueError('Squad club limit requires verification')
    if info.get('created_on_matchday_id') == cfg['current_matchday']['id']:
        maximum = None  # The official client treats creation during this round as unlimited.
    snapshot = roster.get('latest_snapshot')
    baseline = None
    inactive = []
    if isinstance(snapshot, dict) and isinstance(snapshot.get('players'), list):
        identifiers = [p.get('id') for p in snapshot['players']]
        if len(identifiers) == 11 and len(set(identifiers)) == 11 and all(type(i) is int and i > 0 for i in identifiers):
            baseline = [str(i) for i in identifiers]
            statuses = roster.get('snapshot_players_current_status') or []
            inactive = [str(p['id']) for p in statuses if p.get('active') is False and str(p.get('id')) in baseline]
    total = sum(p['credits'] for p in players) if all(p['credits'] is not None for p in players) else None
    return {'name': text(team.get('name'), 'squad team name'), 'matchday': cfg['current_matchday']['number'],
            'observed_at': observed_at, 'players': players, 'budget': round(budget, 2),
            'roster_value': round(total, 2) if total is not None else None,
            'free_credits': round(budget-total, 2) if total is not None else None,
            'transfers_used': used, 'transfers_limit': maximum,
            'transfers_remaining': max(0, maximum-used) if maximum is not None else len(players),
            'club_limit': club_limit, 'quotas': quotas, 'baseline_ids':baseline, 'baseline_inactive_ids':inactive,
            'complete': Counter(p['role'] for p in players) == Counter(quotas),
            'source': 'EuroLeague Fantasy Challenge — owner roster and team finances'}
