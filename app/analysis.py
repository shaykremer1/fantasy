"""Opponent analysis, independent of fantasy scoring or unverified rules."""
from collections import defaultdict
from datetime import timedelta
from statistics import mean

from .data import timestamp, utcnow

CATEGORIES = {"PG": "רכזים", "W": "כנפיים / פורוורדים", "C": "סנטרים", "G": "גארדים ללא תפקיד מפורט", "U": "עמדה לא ידועה"}


def category(position):
    return {"PG": "PG", "SG": "W", "SF": "W", "PF": "W", "F": "W", "C": "C", "G": "G", "UNK": "U"}[position]


def historical_position(row, player):
    position = row.get('position',player['position'])
    # A deliberate role mapping can refine a broad registration role for the
    # live analysis. Backtests reconstruct roles exclusively from prior rows.
    if position=='G' and player['position'] in {'PG','SG'} and player.get('position_source','').startswith('user'):
        return player['position']
    if position=='F' and player['position'] in {'SF','PF'} and player.get('position_source','').startswith('user'):
        return player['position']
    return position


def fresh(observed, hours, now):
    if not observed:
        return False
    age = now - timestamp(observed)
    return timedelta(0) <= age <= timedelta(hours=hours)


def analyze(data, target_round=None, window=10, venue="all", now=None):
    now = now or utcnow()
    teams = {t["id"]: t for t in data["teams"]}
    players = {p["id"]: p for p in data["players"]}
    games = {g["id"]: g for g in data["games"]}
    upcoming = [g for g in games.values() if g["status"] == "scheduled" and timestamp(g["date"]) > now]
    rounds = sorted({g["round"] for g in upcoming})
    if target_round is None:
        target_round = min(upcoming, key=lambda g: timestamp(g["date"]))["round"] if upcoming else None
    targets = [g for g in upcoming if g["round"] == target_round]
    # A partially played round never leaks into predictions for that same round.
    round_games = [g for g in games.values() if g["round"] == target_round]
    cutoff = min([now] + [timestamp(g["date"]) for g in round_games])
    historical = {g["id"]: g for g in games.values()
                  if g["status"] == "finished" and timestamp(g["date"]) < cutoff
                  and (target_round is None or g["round"] < target_round)}
    rows = [r for r in data["appearances"] if r["game_id"] in historical and r["minutes"] > 0]
    history = defaultdict(list)
    for row in rows:
        history[row["player_id"]].append(row)
    for values in history.values():
        values.sort(key=lambda r: timestamp(games[r["game_id"]]["date"]))

    # Window is distinct team games, not last N player appearances.
    allowed = {}
    for tid in teams:
        tg = [g for g in historical.values() if tid in (g["home_team_id"], g["away_team_id"])
              and (venue == "all" or (venue == "home") == (g["home_team_id"] == tid))]
        tg.sort(key=lambda g: timestamp(g["date"]), reverse=True)
        allowed[tid] = {g["id"] for g in (tg[:window] if window else tg)}

    buckets = defaultdict(list)
    for row in rows:
        if row["game_id"] in allowed[row["opponent_id"]]:
            buckets[(row["opponent_id"], category(historical_position(row,players[row['player_id']])))].append(row)
    defenses = []
    defense_index = {}
    for (tid, cat), values in buckets.items():
        adjusted = defaultdict(list)
        # Leave this opponent out when estimating each player's normal PIR/min.
        # These are retrospective descriptive effects; all inputs precede cutoff.
        for row in values:
            other = [r for r in history[row["player_id"]] if r["opponent_id"] != tid and r["minutes"] >= 5]
            if row["minutes"] < 5:
                continue
            if len(other) >= 3:
                baseline_rate = sum(r["pir"] for r in other) / sum(r["minutes"] for r in other)
                adjusted[row["game_id"]].append(30 * (row["pir"] / row["minutes"] - baseline_rate))
        # Equal weight per game, then shrink small samples toward neutral.
        n = len(adjusted)
        effect = mean(mean(a) for a in adjusted.values()) * n / (n + 8) if n else None
        total_per_game = defaultdict(float)
        for row in values:
            total_per_game[row["game_id"]] += row["pir"]
        item = {"team_id": tid, "team": teams[tid]["name"], "category": cat,
                "average_pir": round(mean(r["pir"] for r in values), 2),
                "pir_per_30": round(30 * sum(r["pir"] for r in values) / sum(r["minutes"] for r in values), 2),
                "total_pir_per_game": round(mean(total_per_game.values()), 2),
                "games": len(total_per_game), "appearances": len(values), "comparable_games": n,
                "matchup_delta_per_30": round(effect, 2) if effect is not None else None,
                "confidence": "higher" if n >= 12 else "medium" if n >= 5 else "low"}
        defenses.append(item)
        defense_index[(tid, cat)] = item
    defenses.sort(key=lambda x: (x["matchup_delta_per_30"] is not None, x["matchup_delta_per_30"] or 0), reverse=True)

    recommendations = []
    excluded = []
    for game in targets:
        for p in players.values():
            if p["team_id"] not in (game["home_team_id"], game["away_team_id"]):
                continue
            if p.get("roster_active") is False:
                excluded.append({"player_id": p["id"], "name": p["name"], "reason": "inactive_roster", "source": "Official season registration"})
                continue
            opponent = game["away_team_id"] if p["team_id"] == game["home_team_id"] else game["home_team_id"]
            available_fresh = fresh(p.get("availability_as_of"), 24, now)
            status = p.get("availability", "unknown") if available_fresh else "unknown"
            if status == "out":
                excluded.append({"player_id": p["id"], "name": p["name"], "reason": "out", "source": p.get("availability_source")})
                continue
            cat = category(p["position"])
            cell = defense_index.get((opponent, cat))
            recent = history[p["id"]][-5:]
            minutes = mean(r["minutes"] for r in recent) if recent else None
            baseline = mean(r["pir"] for r in recent) if recent else None
            opponent_venue = "home" if game["home_team_id"] == opponent else "away"
            venue_matches = venue == "all" or venue == opponent_venue
            usable = venue_matches and cat != "U" and len(recent) >= 3 and cell and cell["comparable_games"] >= 3
            delta = cell["matchup_delta_per_30"] * minutes / 30 if usable else None
            predicted = baseline + delta if usable else None
            price_fresh = fresh(p.get("price_as_of"), 48, now) and (p.get('price_matchday') is None or p['price_matchday']==target_round)
            credits = p.get("credits") if price_fresh else None
            warnings = []
            if not venue_matches:
                warnings.append("מסנן המגרש אינו תואם למגרש היריבה במשחק הקרוב")
            if cat == "G":
                warnings.append("ניתוח גארדים משותף — אין הפרדה בין רכז לקלע")
            if cat == "U":
                warnings.append("נדרשת עמדה")
            if status != "available":
                warnings.append("זמינות בספק" if status == "doubtful" else "זמינות לא מאומתת")
            if not price_fresh or credits is None:
                warnings.append("מחיר חסר או לא עדכני")
            if not usable:
                warnings.append("אין מספיק נתונים לתחזית מול היריבה")
            elif cell["confidence"] == "low":
                warnings.append("מדגם קטן")
            recommendations.append({"player_id": p["id"], "game_id": game["id"], "name": p["name"],
                "team": teams[p["team_id"]]["name"], "opponent": teams[opponent]["name"],
                "image_url": p.get("image_url"), "image_source": p.get("image_source"),
                "team_image_url": teams[p["team_id"]].get("image_url"),
                "opponent_image_url": teams[opponent].get("image_url"),
                "position": p["position"], "fantasy_position":p.get("fantasy_position"), "category": cat, "venue": "home" if p["team_id"] == game["home_team_id"] else "away",
                "date": game["date"], "recent_games": len(recent), "recent_pir": round(baseline, 2) if baseline is not None else None,
                "recent_pir_high": round(mean(sorted((r["pir"] for r in recent), reverse=True)[:2]), 2) if recent else None,
                "projected_minutes": round(minutes, 1) if minutes is not None else None,
                "matchup_delta": round(delta, 2) if delta is not None else None,
                "projected_pir": round(predicted, 2) if predicted is not None else None,
                "credits": credits, "reported_credits": p.get("credits"), "price_as_of": p.get("price_as_of"),
                "price_source": p.get("price_source"), "price_matchday": p.get("price_matchday"), "availability": status,
                "availability_as_of": p.get("availability_as_of"), "availability_source": p.get("availability_source"),
                "pir_per_credit": round(predicted / credits, 2) if predicted is not None and credits else None,
                "confidence": cell["confidence"] if cell else "low", "warnings": warnings,
                "eligible": bool(usable and status == "available" and credits is not None),
                "opponent_games": cell["games"] if cell else 0,
                "comparable_games": cell["comparable_games"] if cell else 0})
    recommendations.sort(key=lambda r: (r["matchup_delta"] is not None, r["matchup_delta"] or 0), reverse=True)
    coverage = {"games": len(historical), "games_with_stats": len({r["game_id"] for r in rows}),
                "appearances": len(rows), "players": len(players),
                "known_positions": sum(p["position"] != "UNK" for p in players.values()),
                "detailed_guard_roles":sum(p['position'] in {'PG','SG'} for p in players.values()),
                "fresh_prices": sum(p.get("credits") is not None and fresh(p.get("price_as_of"), 48, now) and (p.get("price_matchday") is None or p["price_matchday"] == target_round) for p in players.values()),
                "fresh_availability": sum(p.get("availability", "unknown") != "unknown" and fresh(p.get("availability_as_of"), 24, now) for p in players.values())}
    return {"season": data["season"], "mode": data["mode"], "sources": data["sources"], "generated_at": now.isoformat(),
            "cutoff": cutoff.isoformat(), "target_round": target_round, "rounds": rounds, "window": window,
            "venue": venue, "categories": CATEGORIES, "coverage": coverage,
            "defenses": defenses, "recommendations": recommendations, "excluded": excluded,
            "rules_verified": True, "rules_mode": "classic", "rules_checked_at": "2026-10-12",
            "rules_source": "https://fantaking.gitbook.io/euroleague-fantasy-challenge-rules/classic-mode",
            "fantasy_scoring_implemented": False, "model_version":"matchup-v1"}
