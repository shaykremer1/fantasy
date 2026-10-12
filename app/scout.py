"""The requested three-position opponent scouting and top-three shortlist."""
from collections import defaultdict
from statistics import mean
from .data import timestamp


def role(position):
    return {'PG':'G','SG':'G','G':'G','SF':'F','PF':'F','F':'F','C':'C','UNK':'U'}[position]


def scout(data, analysis):
    players={p['id']:p for p in data['players']}
    teams={t['id']:t for t in data['teams']}
    cutoff=timestamp(analysis['cutoff'])
    games={g['id']:g for g in data['games'] if g['status']=='finished' and timestamp(g['date'])<cutoff
           and (analysis['target_round'] is None or g['round']<analysis['target_round'])}
    rows=[r for r in data['appearances'] if r['game_id'] in games and r['minutes']>0]
    buckets=defaultdict(list)
    league=defaultdict(list)
    for r in rows:
        pos=role(r.get('position',players[r['player_id']]['position']))
        if pos=='U':continue
        league[pos].append(r)
    defense=[]
    for tid in teams:
        fixture_ids=[g['id'] for g in sorted(games.values(),key=lambda g:timestamp(g['date']),reverse=True)
                     if tid in (g['home_team_id'],g['away_team_id'])
                     and (analysis['venue']=='all' or (analysis['venue']=='home')==(g['home_team_id']==tid))]
        if analysis['window']:fixture_ids=fixture_ids[:analysis['window']]
        selected=set(fixture_ids)
        for r in rows:
            if r['opponent_id']==tid and r['game_id'] in selected:
                buckets[(tid,role(r.get('position',players[r['player_id']]['position'])))].append(r)
        for pos in ('C','F','G'):
            values=buckets[(tid,pos)]
            if not values:continue
            pir30=30*sum(r['pir'] for r in values)/sum(r['minutes'] for r in values)
            all_rows=league[pos]
            reference=30*sum(r['pir'] for r in all_rows)/sum(r['minutes'] for r in all_rows)
            defense.append({'team_id':tid,'team':teams[tid]['name'],'role':pos,
                'average_pir':round(mean(r['pir'] for r in values),2),
                'total_pir_per_game':round(sum(r['pir'] for r in values)/len(selected),2),
                'pir_per_30':round(pir30,2),'matchup_index':round(pir30/reference,4) if reference>0 else None,
                'games':len(selected),'appearances':len(values)})
    index={(d['team_id'],d['role']):d for d in defense}
    team_ids_by_name={t['name']:t['id'] for t in teams.values()}
    shortlists={'C':[],'F':[],'G':[]}
    for candidate in analysis['recommendations']:
        pos=role(candidate['position'])
        if pos not in shortlists or candidate['recent_games']<3:continue
        opponent=team_ids_by_name[candidate['opponent']]
        cell=index.get((opponent,pos))
        if not cell or cell['games']<3 or cell['matchup_index'] is None:continue
        game=next(g for g in data['games'] if g['id']==candidate['game_id'])
        opponent_venue='home' if game['home_team_id']==opponent else 'away'
        if analysis['venue']!='all' and analysis['venue']!=opponent_venue:continue
        item={**candidate,'role':pos,'opponent_average_pir':cell['average_pir'],
              'opponent_pir_per_30':cell['pir_per_30'],'opponent_games':cell['games'],
              'matchup_index':cell['matchup_index'],
              'scout_score':round(candidate['recent_pir']*cell['matchup_index'],2)}
        shortlists[pos].append(item)
    for pos,values in shortlists.items():
        values.sort(key=lambda p:(-p['scout_score'],-p['recent_pir'],p['player_id']))
        shortlists[pos]=values[:3]
    defense.sort(key=lambda d:(d['role'],-d['average_pir'],d['team_id']))
    return {'defenses':defense,'top_three':shortlists,
            'point_guards':sorted([p for p in analysis['recommendations'] if p['position']=='PG' and p['projected_pir'] is not None],key=lambda p:-p['projected_pir'])[:3],
            'method':'Recent player PIR × opponent PIR/30min relative to the league at that position. Exploratory ranking, not a calibrated forecast.',
            'guard_note':'G includes point guards and shooting guards. Unknown guard roles are never labeled PG.'}
