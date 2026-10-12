"""Coach shortlist from team results against the next opponent, not player PIR."""
from statistics import mean
from .data import timestamp, utcnow


def recommend_coaches(data, analysis):
    cutoff = timestamp(analysis['cutoff'])
    upcoming_after = max(cutoff, utcnow())
    teams = {t['id']: t['name'] for t in data['teams']}
    history = sorted([g for g in data['games']
                      if g['status'] == 'finished' and timestamp(g['date']) < cutoff
                      and (analysis['target_round'] is None or g['round'] < analysis['target_round'])
                      and g.get('home_score') is not None and g.get('away_score') is not None],
                     key=lambda g: timestamp(g['date']), reverse=True)

    def form(tid):
        selected = [g for g in history if tid in (g['home_team_id'], g['away_team_id'])
                    and (analysis['venue'] == 'all' or
                         (analysis['venue'] == 'home') == (g['home_team_id'] == tid))]
        if analysis['window']:
            selected = selected[:analysis['window']]
        margins = [(g['home_score'] - g['away_score']) * (1 if g['home_team_id'] == tid else -1)
                   for g in selected]
        return {'games': len(margins), 'wins': sum(m > 0 for m in margins),
                'average_margin': round(mean(margins), 2) if margins else None}

    forms = {tid: form(tid) for tid in teams}
    coaches = {c['team_id']: c for c in data.get('coaches', []) if c.get('active') is True}
    picks = []
    for g in data['games']:
        if g['status'] != 'scheduled' or g['round'] != analysis['target_round'] or timestamp(g['date']) <= upcoming_after:
            continue
        for tid, opponent in [(g['home_team_id'], g['away_team_id']), (g['away_team_id'], g['home_team_id'])]:
            coach = coaches.get(tid)
            own, rival = forms[tid], forms[opponent]
            if not coach or min(own['games'], rival['games']) < 3:
                continue
            # Difference of team net margins divided by two is an exploratory
            # matchup indicator; it is not a calibrated win probability or score.
            picks.append({'coach_id': coach['id'], 'name': coach['name'], 'team': teams[tid],
                          'opponent': teams[opponent], 'game_id': g['id'], 'date': g['date'],
                          'venue': 'home' if tid == g['home_team_id'] else 'away',
                          'team_form': own, 'opponent_form': rival,
                          'matchup_margin': round((own['average_margin'] - rival['average_margin']) / 2, 2)})
    picks.sort(key=lambda p: (-p['matchup_margin'], p['coach_id'], p['game_id']))
    return picks[:3]
