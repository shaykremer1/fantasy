"""Deterministic fictional data, explicitly separate from real snapshots."""
from datetime import timedelta
from random import Random
from .data import utcnow


def dataset():
    now = utcnow()
    rng = Random(42)
    teams = [{"id": f"T{i}", "name": name} for i, name in enumerate([
        "אתונה לדוגמה", "מדריד לדוגמה", "תל אביב לדוגמה", "מונקו לדוגמה", "ברצלונה לדוגמה", "בלגרד לדוגמה"])]
    names = ["אלכס", "ניקו", "דניאל", "מרקו", "לוקה", "אדם", "תום", "יואן", "מילאן", "מקס", "אורי", "ליאו"]
    players = []
    for i, t in enumerate(teams):
        for j, pos in enumerate(["PG", "SG", "SF", "PF", "C"]):
            k = i * 5 + j
            players.append({"id": f"P{k}", "name": f"{names[k % len(names)]} {k + 1}", "team_id": t["id"], "position": pos,
                "credits": round(7 + rng.random() * 11, 1), "price_as_of": now.isoformat(), "price_source": "נתונים סינתטיים להדגמה בלבד",
                "availability": "out" if k == 14 else "doubtful" if k == 6 else "unknown" if k == 21 else "available",
                "availability_as_of": now.isoformat(), "availability_source": "נתונים סינתטיים להדגמה בלבד"})
    games, appearances = [], []
    rotation = list(range(6))
    for rnd in range(1, 12):
        for j in range(3):
            a, b = rotation[j], rotation[-1-j]
            if rnd % 2 == 0:
                a, b = b, a
            gid = f"R{rnd}-{j}"
            game = {"id": gid, "round": rnd, "home_team_id": f"T{a}", "away_team_id": f"T{b}",
                "date": (now + timedelta(days=2) if rnd == 11 else now - timedelta(days=(11-rnd)*5)).isoformat(),
                "status": "scheduled" if rnd == 11 else "finished"}
            games.append(game)
            if rnd < 11:
                for p in players:
                    if p["team_id"] not in {f"T{a}", f"T{b}"}:
                        continue
                    opp = f"T{b}" if p["team_id"] == f"T{a}" else f"T{a}"
                    minutes = round(18 + rng.random()*14, 1)
                    rate = 0.32 + int(p["id"][1:]) % 7 * 0.055
                    boost = 0.18 if (opp == "T0" and p["position"] == "C") or (opp == "T3" and p["position"] == "PG") else -0.09 if opp == "T1" else 0
                    appearances.append({"game_id": gid, "player_id": p["id"], "team_id": p["team_id"], "opponent_id": opp,
                        "minutes": minutes, "pir": round((rate + boost)*minutes + rng.uniform(-5,5))})
        rotation = [rotation[0], rotation[-1], *rotation[1:-1]]
    return {"schema_version": 1, "season": "DEMO", "mode": "demo", "sources": ["נתונים סינתטיים — אינם נתוני יורוליג"],
            "teams": teams, "players": players, "games": games, "appearances": appearances}
