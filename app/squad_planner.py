"""Budget/transfer constrained alternatives; bounded search, never account trades."""
from collections import Counter, defaultdict
from functools import lru_cache
from statistics import mean
from .analysis import analyze, fresh
from .scout import scout, role
from .data import timestamp, utcnow

FORMATIONS = [(2,2,1), (1,2,2), (2,1,2), (1,3,1), (3,1,1)]


def coach_points(margin):
    """Conservative bound at the guide's overlapping 20-point boundary."""
    if margin == 0:return -5
    if margin > 0:return 10 if margin <= 10 else 20 if margin <= 20 else 25
    return -5 if margin >= -10 else -10 if margin > -20 else -20


def candidates(data, analysis):
    scouting = scout(data, analysis)
    cells = {(d['team'], d['role']): d for d in scouting['defenses']}
    players = {p['id']:p for p in data['players']}
    available = {}
    for p in analysis['recommendations']:
        original = players[p['player_id']]
        pos = p.get('fantasy_position') or role(p['position'])
        cell = cells.get((p['opponent'], pos))
        score = (p['recent_pir']*cell['matchup_index'] if p['recent_games'] >= 3 and cell
                 and cell['games'] >= 3 and cell['matchup_index'] is not None else None)
        if original.get('fantasy_player_id') is None:continue
        available[str(original['fantasy_player_id'])] = {**p, 'role':pos, 'team_id':original['team_id'],
            'fantasy_player_id':str(original['fantasy_player_id']), 'score':score}
    cutoff = timestamp(analysis['cutoff'])
    games = sorted([g for g in data['games'] if g['status'] == 'finished' and timestamp(g['date']) < cutoff
                    and (analysis['target_round'] is None or g['round'] < analysis['target_round'])
                    and g.get('home_score') is not None and g.get('away_score') is not None],
                   key=lambda g:timestamp(g['date']), reverse=True)
    margins = defaultdict(list)
    for g in games:
        m = g['home_score']-g['away_score']
        margins[g['home_team_id']].append(m);margins[g['away_team_id']].append(-m)
    teams = {t['id']:t for t in data['teams']}
    for g in data['games']:
        if g['status'] != 'scheduled' or g['round'] != analysis['target_round'] or timestamp(g['date']) <= utcnow():continue
        for tid, opponent in [(g['home_team_id'],g['away_team_id']), (g['away_team_id'],g['home_team_id'])]:
            for coach in data.get('coaches', []):
                if coach['team_id'] != tid or coach.get('active') is not True or not coach.get('fantasy_player_id'):continue
                a, b = margins[tid], margins[opponent]
                if analysis['window']:a,b=a[:analysis['window']],b[:analysis['window']]
                score = mean(coach_points((x-y)/2) for x in a for y in b) if min(len(a),len(b)) >= 3 else None
                price = coach.get('credits') if fresh(coach.get('price_as_of'),48,utcnow()) and coach.get('price_matchday') == analysis['target_round'] else None
                available[str(coach['fantasy_player_id'])] = {'player_id':coach['id'], 'fantasy_player_id':str(coach['fantasy_player_id']),
                    'name':coach['name'], 'role':'H', 'team_id':tid, 'team':teams[tid]['name'],
                    'opponent':teams[opponent]['name'], 'credits':price, 'score':score,
                    'availability':'unknown', 'image_url':None}
    return available


def lineup(roster):
    if any(p['score'] is None for p in roster):return None
    groups = {r:sorted([p for p in roster if p['role'] == r], key=lambda p:-p['score']) for r in ('G','F','C')}
    coach = next(p for p in roster if p['role'] == 'H')
    best = None
    for counts in FORMATIONS:
        starters = [p for r,n in zip(('G','F','C'), counts) for p in groups[r][:n]]
        ids = {p['fantasy_player_id'] for p in starters}
        reserves = sorted([p for p in roster if p['role'] != 'H' and p['fantasy_player_id'] not in ids],key=lambda p:-p['score'])
        captain = max(starters,key=lambda p:p['score'])
        sixth, bench = reserves[0], reserves[1:]
        score = sum(p['score'] for p in starters)+captain['score']+sixth['score']+.5*sum(p['score'] for p in bench)+coach['score']
        if best is None or score > best['score']:
            best = {'score':score, 'formation':list(counts), 'starters':[p['fantasy_player_id'] for p in starters],
                    'captain':captain['fantasy_player_id'], 'sixth':sixth['fantasy_player_id'],
                    'bench':[p['fantasy_player_id'] for p in bench], 'coach':coach['fantasy_player_id']}
    return best


def plan_squad(data, squad, target_round=None, window=10, venue='all'):
    analysis = analyze(data,target_round=target_round,window=window,venue=venue)
    if not squad['complete']:
        return {'available':False,'reason':'הסגל אינו מלא: נדרשים 4 גארדים, 4 פורוורדים, 2 סנטרים ומאמן.'}
    if squad['matchday'] != analysis['target_round'] or not fresh(squad['observed_at'],48,utcnow()):
        return {'available':False,'reason':'הסגל אינו מעודכן למחזור שנבחר; ממתין לסנכרון.'}
    round_dates = [timestamp(g['date']) for g in data['games'] if g['round'] == analysis['target_round']]
    if round_dates and min(round_dates) <= utcnow():
        return {'available':False,'reason':'המחזור כבר החל. הצעות העברות יוכנו לפני המחזור הבא.'}
    if squad['free_credits'] is None or any(p['credits'] is None for p in squad['players']):
        return {'available':False,'reason':'חסר מחיר מאומת בסגל; אי אפשר לבדוק את התקציב.'}
    pool = candidates(data,analysis)
    excluded = {p['player_id']:p['reason'] for p in analysis['excluded']}
    original = []
    for own in squad['players']:
        item = {**own, 'score':None, 'opponent':None, 'availability':'unknown', **pool.get(own['fantasy_player_id'],{}),
                'credits':own['credits'], 'role':own['role']}
        # The owner's quotation is the sale value reported with these finances.
        if own.get('player_id') in excluded and excluded[own['player_id']] in {'out','inactive_roster'}:
            item.update(score=0, availability='out')
        original.append(item)
        pool[own['fantasy_player_id']] = item
    missing = [p['name'] for p in original if p['score'] is None]
    quotas = squad['quotas'];budget = squad['budget']; club_limit = squad['club_limit']
    buy = defaultdict(list)
    for p in pool.values():
        if p['score'] is not None and p['credits'] is not None and p['role'] in quotas and p.get('team_id') is not None:
            buy[p['role']].append(p)
    for r, values in buy.items():
        ordered = sorted(values,key=lambda p:(-p['score'],p['credits'],p['fantasy_player_id']))[:12]
        cheap = sorted(values,key=lambda p:(p['credits'],-p['score']))[:6]
        buy[r] = list({p['fantasy_player_id']:p for p in ordered+cheap}.values())
    start = tuple(p['fantasy_player_id'] for p in original)
    original_ids = set(start)
    snapshot_ids = set(squad.get('baseline_ids') or [])
    inactive_ids = set(squad.get('baseline_inactive_ids') or [])
    maximum = squad.get('transfers_limit')
    def net_transfers(ids):
        if snapshot_ids:
            return max(0,len(set(ids)-snapshot_ids)-len(inactive_ids-set(ids)))
        return squad.get('transfers_used',0)+sum(a!=b for a,b in zip(start,ids))
    if snapshot_ids:
        limit = len(start) if maximum is None else min(len(start),max(1,2*maximum+len(inactive_ids)))
    else:
        limit = min(squad['transfers_remaining'],len(start))
    # Unknown forecasts remain locked; their value is never invented as a recommendation.
    unlocked = [i for i,p in enumerate(original) if p['score'] is not None]
    limit = min(limit,len(unlocked))
    cheapest = {r:min((p['credits'] for p in values),default=10000) for r,values in buy.items()}

    @lru_cache(maxsize=60000)
    def evaluate(ids):
        rows = [pool[i] for i in ids]
        money = sum(p['credits'] for p in rows)
        if missing:
            score = sum(p['score'] for p in rows if p['score'] is not None)
        else:
            score = lineup(rows)['score']
        return score, money

    baseline, original_cost = evaluate(start)
    beam = [start];seen = {frozenset(start)};final = []
    for depth in range(1,limit+1):
        states = []
        for ids in beam:
            for i in unlocked:
                if ids[i] != start[i]:continue
                for incoming in buy[original[i]['role']]:
                    ident = incoming['fantasy_player_id']
                    if ident in ids or ident in original_ids:continue
                    next_ids = ids[:i]+(ident,)+ids[i+1:]
                    identity = frozenset(next_ids)
                    if identity in seen:continue
                    seen.add(identity)
                    if max(Counter(pool[j].get('team_id') for j in next_ids).values()) > club_limit:continue
                    score,cost = evaluate(next_ids)
                    savings = sorted((max(0,original[j]['credits']-cheapest.get(original[j]['role'],10000))
                                      for j in unlocked if next_ids[j] == start[j]),reverse=True)
                    if cost > budget+sum(savings[:limit-depth])+1e-6:continue
                    net = net_transfers(next_ids)
                    if maximum is not None and net > maximum+limit-depth:continue
                    states.append(next_ids)
                    if (maximum is None or net <= maximum) and cost <= budget+1e-6 and score > baseline+1e-6:final.append(next_ids)
        if not states:break
        # Preserve both high-score and low-cost paths, including funding swaps.
        best = sorted(states,key=lambda ids:(-evaluate(ids)[0],evaluate(ids)[1]))[:48]
        affordable = sorted(states,key=lambda ids:(evaluate(ids)[1],-evaluate(ids)[0]))[:16]
        beam = list(dict.fromkeys(best+affordable))
    choices = []
    selectors = [
        ('הציון הגבוה ביותר שנמצא', final, lambda ids:(-evaluate(ids)[0],evaluate(ids)[1])),
        ('שיפור ממוקד', [ids for ids in final if sum(a!=b for a,b in zip(start,ids)) <= 2], lambda ids:(-evaluate(ids)[0],evaluate(ids)[1])),
        ('שיפור בלי להגדיל הוצאות', [ids for ids in final if evaluate(ids)[1] <= original_cost+1e-6], lambda ids:(-evaluate(ids)[0],evaluate(ids)[1]))]
    chosen = set()
    for title, eligible, ordering in selectors:
        ids = next((ids for ids in sorted(eligible,key=ordering) if frozenset(ids) not in chosen),None)
        if ids is None:continue
        chosen.add(frozenset(ids));rows = [pool[i] for i in ids];score,cost = evaluate(ids)
        swaps = [{'out':original[i], 'in':pool[new], 'credit_change':round(original[i]['credits']-pool[new]['credits'],2)}
                 for i,new in enumerate(ids) if new != start[i]]
        allocation = lineup(rows) if not missing else None
        choices.append({'title':title,'players':rows,'transfers':swaps,'transfer_count':len(swaps),'net_transfer_count':net_transfers(ids),
                        'roster_value':round(cost,2),'free_credits':round(budget-cost,2),
                        'model_score':round(score,2),'improvement':round(score-baseline,2),'lineup':allocation})
    return {'available':True,'alternatives':choices,'current_players':original,'current_model_score':round(baseline,2),
            'current_lineup':lineup(original) if not missing else None,'missing_forecasts':missing,
            'method':'Bounded search within current budget, fantasy position quotas, club cap and remaining transfers. Player opponent-adjusted PIR; captain ×2, sixth player ×1 and bench ×0.5 when every forecast is known. Coach score uses historical matchup-margin samples with conservative scoring at 20 points. Player win bonus is not modeled; scores are exploratory, not calibrated fantasy forecasts or guaranteed global optima.',
            'score_kind':'partial-known-components' if missing else 'weighted-roster', 'searched_transfer_limit':limit,'can_replan':bool(snapshot_ids)}
