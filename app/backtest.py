"""Chronological paired evaluation, without present-day market/roster leakage."""
import argparse
import copy
from collections import defaultdict
from datetime import timedelta
import json
from pathlib import Path
from statistics import mean
import math
import re
from random import Random

from .analysis import analyze, category
from .data import Store, timestamp, utcnow
from .providers import sync

ROOT = Path(__file__).resolve().parent.parent


def before_round(data, rnd):
    games = {g['id']: g for g in data['games']}
    targets = [g for g in games.values() if g['round'] == rnd and g['status'] == 'finished']
    if not targets:
        raise ValueError('No completed target fixtures')
    cutoff = min(timestamp(g['date']) for g in targets)
    snapshot = copy.deepcopy(data)
    latest = {}
    for row in sorted(data['appearances'], key=lambda r: timestamp(games[r['game_id']]['date'])):
        game = games[row['game_id']]
        if game['round'] < rnd and timestamp(game['date']) < cutoff:
            latest[row['player_id']] = row
    for p in snapshot['players']:
        previous = latest.get(p['id'])
        # Only historical registration roles stored on appearances are usable.
        p['position'] = previous.get('position', 'UNK') if previous else 'UNK'
        if previous:
            p['team_id'] = previous['team_id']
        p['roster_active'] = previous is not None
        p['availability'] = 'unknown'
        for key in ('credits','price_as_of','price_source','availability_as_of','availability_source'):
            p.pop(key, None)
    for game in snapshot['games']:
        if game['id'] in {g['id'] for g in targets}:
            game['status'] = 'scheduled'
    return snapshot, cutoff - timedelta(microseconds=1)


def metrics(records, bootstrap=False):
    if not records:
        return {'n':0, 'baseline_mae':None, 'model_mae':None, 'mae_improvement':None,
                'baseline_rmse':None, 'model_rmse':None, 'model_bias':None, 'dnp':0, 'better_fraction':None}
    baseline_mae = mean(abs(r['baseline'] - r['actual']) for r in records)
    model_mae = mean(abs(r['predicted'] - r['actual']) for r in records)
    result = {'n':len(records), 'baseline_mae':round(baseline_mae,3), 'model_mae':round(model_mae,3),
            'mae_improvement':round(baseline_mae-model_mae,3),
            'baseline_rmse':round(math.sqrt(mean((r['baseline']-r['actual'])**2 for r in records)),3),
            'model_rmse':round(math.sqrt(mean((r['predicted']-r['actual'])**2 for r in records)),3),
            'model_bias':round(mean(r['predicted']-r['actual'] for r in records),3),
            'dnp':sum(r['minutes']==0 for r in records),
            'better_fraction':round(mean(abs(r['predicted']-r['actual']) < abs(r['baseline']-r['actual']) for r in records),3)}
    if bootstrap:
        groups=defaultdict(list)
        for i,row in enumerate(records):
            groups[row.get('game_id',str(i))].append(abs(row['baseline']-row['actual'])-abs(row['predicted']-row['actual']))
        clusters=[(sum(values),len(values)) for values in groups.values()]
        rng=Random(42)
        draws=[]
        for _ in range(1000):
            sample=rng.choices(clusters,k=len(clusters))
            draws.append(sum(item[0] for item in sample)/sum(item[1] for item in sample))
        draws.sort()
        result.update(games=len(clusters),mae_improvement_ci95=[round(draws[24],3),round(draws[974],3)])
    return result


def evaluate(data, through_round=14, holdout_rounds=4, window=10):
    games = {g['id']:g for g in data['games']}
    actual = {(r['game_id'],r['player_id']):r for r in data['appearances']}
    observed_games = {r['game_id'] for r in data['appearances']}
    rounds = sorted({g['round'] for g in games.values() if g['round'] <= through_round
                     and g['status']=='finished' and g['id'] in observed_games})
    holdout = set(rounds[-holdout_rounds:]) if holdout_rounds else set()
    records, missing_actual, transfers, missing_model = [], 0, 0, 0
    by_round = []
    for rnd in rounds:
        snapshot, now = before_round(data, rnd)
        result = analyze(snapshot, target_round=rnd, window=window, now=now)
        current = []
        for rec in result['recommendations']:
            row = actual.get((rec['game_id'],rec['player_id']))
            if row is None:
                missing_actual += 1
                continue
            predicted_team = next(p['team_id'] for p in snapshot['players'] if p['id']==rec['player_id'])
            if row['team_id'] != predicted_team:
                transfers += 1
                continue
            if rec['projected_pir'] is None:
                missing_model += 1
                continue
            record = {'round':rnd, 'game_id':rec['game_id'], 'player_id':rec['player_id'],
                      'category':rec['category'], 'baseline':rec['recent_pir'], 'predicted':rec['projected_pir'],
                      'actual':row['pir'], 'minutes':row['minutes'], 'segment':'holdout' if rnd in holdout else 'development'}
            current.append(record)
        records.extend(current)
        by_round.append({'round':rnd,'segment':'holdout' if rnd in holdout else 'development', **metrics(current)})
    segments = {name: metrics([r for r in records if r['segment']==name],bootstrap=True) for name in ('development','holdout')}
    by_position = [{"category":cat, **metrics([r for r in records if r['category']==cat])}
                   for cat in sorted({r['category'] for r in records})]
    return {'schema_version':1, 'kind':'backtest', 'season':data['season'], 'mode':data['mode'], 'generated_at':utcnow().isoformat(),
            'through_round':through_round, 'holdout_rounds':sorted(holdout), 'window':window,
            'model_version':'matchup-v1', 'summary':metrics(records,bootstrap=True), 'segments':segments,
            'by_round':by_round, 'by_position':by_position, 'records':records,
            'coverage':{'games_with_stats':len({g for g in observed_games if games[g]['round']<=through_round}),
                        'rounds_with_stats':rounds, 'missing_actual':missing_actual,
                        'missing_prediction':missing_model,'team_mismatch':transfers},
            'limitations':['Evaluation includes players listed in boxscores, including listed DNP; absent players are not assumed to have played or scored zero.',
                          'The 95% empirical interval resamples whole games in 1000 paired bootstrap draws; it is not a player forecast confidence interval.',
                          'Historical registration positions have calendar-day resolution and may include retrospective corrections.',
                          'No historical fantasy price or availability data was available; this tests PIR forecasts, not roster returns.',
                          'Later holdout rounds are used for assessment, not model parameter selection.']}


def main():
    parser = argparse.ArgumentParser(description='Chronological PIR evaluation on a separate historical snapshot')
    parser.add_argument('--season', default='E2025')
    parser.add_argument('--through-round', type=int, default=14)
    parser.add_argument('--holdout-rounds', type=int, default=4)
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'E20\d{2}',args.season):parser.error('Season must be a starting-year code, e.g. E2025')
    if not 1 <= args.through_round <= 50 or not 0 <= args.holdout_rounds < args.through_round:
        parser.error('Invalid evaluation range')
    # Never overwrite the current live season or its market data.
    store = Store(ROOT / '.data' / 'history' / f'{args.season}.json')
    if args.refresh:
        def progress(done,total):
            if done%10==0 or done==total:print(f'Historical boxscores {done}/{total}',flush=True)
        store.save(sync(store.read(),args.season,progress=progress,through_round=args.through_round))
    data = store.read()
    if data['season'] != args.season or not data['appearances']:
        parser.error('Historical data missing; run with --refresh')
    report = evaluate(data, args.through_round, args.holdout_rounds)
    path = ROOT / '.data' / 'reports' / f'{args.season}.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False))
    print(json.dumps({k:report[k] for k in ('season','coverage','summary','segments')},ensure_ascii=False,indent=2))
    print('Report:', path)


if __name__ == '__main__':
    main()
