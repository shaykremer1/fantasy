"""Public EuroLeague boxscores; fantasy prices/status require an explicit source.

Only fixed official HTTPS endpoints are contacted. No arbitrary URL fetching,
login automation, fabricated prices, or claimed official fantasy integration.
"""
import copy
import csv
import io
import json
import re
import urllib.request
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib
import threading
import time
import os
import tempfile
import urllib.error
from email.utils import parsedate_to_datetime
from http.client import RemoteDisconnected
from .data import validate, timestamp

API = "https://api-live.euroleague.net/v2/competitions/E/seasons/{season}/games?limit={limit}"
BOX = "https://live.euroleague.net/api/Boxscore?gamecode={code}&seasoncode={season}"
PEOPLE = "https://api-live.euroleague.net/v2/competitions/E/seasons/{season}/people?limit={limit}"
_BOX_LOCK = threading.Lock()
_BOX_LAST_REQUEST = 0.0
_REQUEST_LOCK = threading.Lock()
_LAST_REQUEST = 0.0
_RAW_BOX_ROOT = Path(__file__).resolve().parent.parent / '.data' / 'raw'


def public_boxscore(game, season, fetch):
    url = BOX.format(code=game['id'], season=season)
    if fetch is not get_json:
        return boxscore(fetch(url), game)
    path = _RAW_BOX_ROOT / (hashlib.sha256(url.encode()).hexdigest()+'.json')
    if path.exists():
        return boxscore(json.loads(path.read_text()), game)
    global _BOX_LAST_REQUEST
    # Respect the legacy service's rate limit. Workers share one paced request slot.
    with _BOX_LOCK:
        delay = max(0, 0.8 - (time.monotonic()-_BOX_LAST_REQUEST))
        if delay:
            time.sleep(delay)
        _BOX_LAST_REQUEST = time.monotonic()
        payload = fetch(url)
    result = boxscore(payload, game)
    path.parent.mkdir(parents=True,exist_ok=True)
    handle, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(handle,'w') as stream:
            json.dump(payload,stream,allow_nan=False)
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)
    return result


def get_json(url):
    global _LAST_REQUEST
    request = urllib.request.Request(url, headers={"User-Agent": "FantasyMatchupLab/0.1", "Accept": "application/json"})
    for attempt in range(3):
        with _REQUEST_LOCK:
            delay = max(0, 1.2-(time.monotonic()-_LAST_REQUEST))
            if delay:time.sleep(delay)
            _LAST_REQUEST = time.monotonic()
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    raw = response.read(8_000_001)
                break
            except urllib.error.HTTPError as exc:
                if exc.code != 429 or attempt == 2:
                    raise
                header = exc.headers.get('Retry-After')
                wait = 60.0
                if header:
                    try:wait = float(header)
                    except ValueError:
                        try:wait = max(0,(parsedate_to_datetime(header)-datetime.now(timezone.utc)).total_seconds())
                        except (ValueError,TypeError):pass
                if wait > 120:
                    raise ValueError('Official source is rate limited; retry after the server cooldown') from exc
                # Obey Retry-After; the shell execution yields while this waits.
                remaining = max(1,wait)
                while remaining:
                    pause = min(30,remaining)
                    time.sleep(pause)
                    remaining -= pause
            except (RemoteDisconnected, ConnectionResetError, TimeoutError):
                if attempt == 2:raise
                time.sleep(5*(attempt+1))
    if len(raw) > 8_000_000:
        raise ValueError("Official response too large")
    return json.loads(raw)


def schedule(payload, season):
    """Fail on unknown schemas instead of guessing fixtures or team identities."""
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("Unexpected official schedule schema; expected data array")
    teams, games = {}, []
    for item in payload["data"]:
        try:
            away_key = "road" if "road" in item else "visiting"
            home, away = item["local"]["club"], item[away_key]["club"]
            for club in (home, away):
                teams[str(club["code"])] = {"id": str(club["code"]), "name": club["name"], "tv_code": club.get('tvCode')}
            date = item.get("utcDate")
            if not date:
                raise ValueError("Schedule lacks utcDate; timezone must not be guessed")
            if not date.endswith("Z") and not re.search(r"[+-]\d\d:\d\d$", date):
                date += "Z"  # utcDate is explicitly a UTC field.
            timestamp(date)
            played = item.get("played")
            if not isinstance(played, bool):
                raise ValueError("Schedule lacks explicit boolean played status")
            games.append({"id": str(item["gameCode"]), "round": int(item["round"]), "date": date,
                "home_team_id": str(home["code"]), "away_team_id": str(away["code"]),
                "status": "finished" if played else "scheduled"})
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError("Official schedule schema changed; adapter requires verification") from exc
    return list(teams.values()), games


def minutes(value):
    if isinstance(value, str) and ":" in value:
        mm, ss = value.split(":")
        seconds = int(ss)
        if not 0 <= seconds < 60:
            raise ValueError("Invalid seconds in playing time")
        return int(mm) + seconds / 60
    if value in (None, "", "DNP", "Did not play"):
        return 0.0
    return float(value)


def boxscore(payload, game):
    stats = payload.get("Stats") if isinstance(payload, dict) else None
    if not isinstance(stats, list) or len(stats) != 2:
        raise ValueError("Unexpected official boxscore schema; expected two Stats teams")
    players, rows = [], []
    # The legacy endpoint documents Stats in home, away order.
    for side, opponent, block in [(game["home_team_id"], game["away_team_id"], stats[0]),
                                   (game["away_team_id"], game["home_team_id"], stats[1])]:
        for p in block.get("PlayersStats", []):
            if p.get("Team") and p["Team"].strip() != side:
                raise ValueError("Boxscore team code does not match the official fixture")
            pid = p.get("Player_ID")
            name = p.get("Player")
            if not pid or not name:
                raise ValueError("Missing official player identity")
            pid = str(pid).strip()
            # Statistical guards must not be misrepresented as point guards.
            players.append({"id": pid, "name": name.strip(), "team_id": side,
                            "position": "UNK", "availability": "unknown"})
            if "Minutes" not in p:
                raise ValueError("Official boxscore has no Minutes field")
            playing = minutes(p.get("Minutes"))
            if "Valuation" not in p:
                raise ValueError("Official boxscore has no Valuation field")
            pir = float(p["Valuation"] or 0)
            rows.append({"game_id": game["id"], "player_id": pid, "team_id": side,
                         "opponent_id": opponent, "minutes": playing, "pir": pir})
    return players, rows


def sync(existing, season, fetch=get_json, progress=None, through_round=None):
    if not re.fullmatch(r"E20\d{2}", season):
        raise ValueError("season must be E followed by the four-digit starting year")
    if existing["mode"] == "demo":
        raise ValueError("Cannot sync live data into a demo snapshot")
    payload = fetch(API.format(season=season, limit=1000))
    if isinstance(payload, dict) and payload.get("total", 0) > len(payload.get("data", [])):
        total = int(payload["total"])
        if total > 3000:
            raise ValueError("Unexpected schedule size")
        payload = fetch(API.format(season=season, limit=total))
        if payload.get("total", 0) > len(payload.get("data", [])):
            raise ValueError("Incomplete official schedule response")
    teams, games = schedule(payload, season)
    if not games:
        raise ValueError("Official schedule is empty; existing snapshot retained")
    same = existing["season"] == season
    roster = {p["id"]: copy.deepcopy(p) for p in existing["players"]} if same else {}
    # Prefer already completed cached boxscores. Explicit JSON import can refresh corrections.
    finished_ids = {g["id"] for g in games if g["status"] == "finished"}
    rows = [copy.deepcopy(r) for r in existing["appearances"] if r["game_id"] in finished_ids] if same else []
    cached = {r["game_id"] for r in rows}
    pending = sorted([g for g in games if g["status"] == "finished" and g["id"] not in cached
                      and (through_round is None or g["round"] <= through_round)], key=lambda g: timestamp(g["date"]))
    completed = 0
    if progress:
        progress(completed, len(pending))
    def fetch_game(game):
        return public_boxscore(game, season, fetch)
    # Four bounded read-only requests at a time; merge in chronological order.
    with ThreadPoolExecutor(max_workers=min(4, len(pending) or 1)) as pool:
        for pp, rr in pool.map(fetch_game, pending):
            for p in pp:
                if p["id"] not in roster:
                    roster[p["id"]] = p
                else:
                    roster[p["id"]]["name"] = p["name"]
                    roster[p["id"]]["team_id"] = p["team_id"]
            rows.extend(rr)
            completed += 1
            if progress:
                progress(completed, len(pending))
    people = fetch(PEOPLE.format(season=season, limit=2000))
    if not isinstance(people, dict) or not isinstance(people.get("data"), list):
        raise ValueError("Unexpected official roster schema")
    if people.get("total", 0) > len(people["data"]):
        raise ValueError("Incomplete official roster; existing snapshot retained")
    # Official season registrations include coaches/staff and transferred players.
    # Player type J, active registration, latest startDate wins; no fuzzy matching.
    registrations = {}
    all_registrations = {}
    for person in sorted(people["data"], key=lambda item: item.get("startDate") or ""):
        if person.get("type") != "J":
            continue
        code = person.get("person", {}).get("code")
        if not isinstance(code, str) or not re.fullmatch(r"[A-Z0-9]{2,12}", code):
            raise ValueError("Unexpected official player code")
        pid = "P" + code  # Legacy Boxscore prefixes the official person code with P.
        all_registrations.setdefault(pid, []).append(person)
        if pid not in registrations or person.get("active") is True or registrations[pid].get("active") is not True:
            registrations[pid] = person
    for pid, person in registrations.items():
        team = person.get("club", {}).get("code")
        if team not in {t["id"] for t in teams}:
            raise ValueError("Official registration references a team outside the schedule")
        p = roster.get(pid, {"id": pid, "availability": "unknown", "position": "UNK"})
        p["name"] = person["person"]["name"]
        p["team_id"] = team
        official_position = {"Guard": "G", "Forward": "F", "Center": "C"}.get(person.get("positionName"), "UNK")
        # Preserve detailed user-supplied basketball roles (e.g. PG vs SG).
        if p["position"] in {"UNK", "G", "F", "C"} and not p.get("position_source", "").startswith("user"):
            p["position"] = official_position
            p["position_source"] = "https://api-live.euroleague.net (season registration)"
        p["roster_active"] = person.get("active") is True
        roster[pid] = p
    game_index = {g['id']: g for g in games}
    for row in rows:
        if row.get('position') is not None:
            continue
        day = timestamp(game_index[row['game_id']]['date']).date()
        candidates = [p for p in all_registrations.get(row['player_id'], [])
                      if p.get('club', {}).get('code') == row['team_id']
                      and p.get('startDate') and p.get('endDate')
                      and datetime.fromisoformat(p['startDate']).date() <= day <= datetime.fromisoformat(p['endDate']).date()]
        if candidates:
            row['position'] = {'Guard':'G', 'Forward':'F', 'Center':'C'}.get(candidates[-1].get('positionName'), 'UNK')
            row['position_source'] = 'Official season registration valid on game date (calendar-day resolution)'
    valid_teams = {t["id"] for t in teams}
    roster = {k: p for k, p in roster.items() if p["team_id"] in valid_teams or any(r["player_id"] == k for r in rows)}
    result = {"schema_version": 1, "season": season, "mode": "live",
        "sources": list(dict.fromkeys((existing["sources"] if same else []) + ["https://api-live.euroleague.net", "https://live.euroleague.net"])),
        "teams": teams, "players": list(roster.values()), "games": games, "appearances": rows}
    return validate(result)


def import_roster(existing, contents):
    """CSV patches must explicitly identify the snapshot season and player ID."""
    result = copy.deepcopy(existing)
    roster = {p["id"]: p for p in result["players"]}
    team_ids = {t["id"] for t in result["teams"]}
    reader = csv.DictReader(io.StringIO(contents.lstrip("\ufeff")))
    required = {"season", "player_id", "name", "team_id", "position"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError("CSV needs season,player_id,name,team_id,position columns")
    seen = set()
    count = 0
    for row in reader:
        pid = row["player_id"].strip()
        if row["season"] != result["season"]:
            raise ValueError("CSV season differs from the active snapshot")
        if not pid or pid in seen:
            raise ValueError("Missing or duplicate CSV player_id")
        seen.add(pid)
        if row["team_id"] not in team_ids:
            raise ValueError("CSV team_id must match an existing team")
        p = roster.get(pid, {"id": pid, "availability": "unknown"})
        for k in ("name", "team_id", "position"):
            p[k] = row[k].strip()
        p["position_source"] = "user supplied CSV"
        # A blank optional field preserves previous information; 'unknown' clears status.
        if row.get("credits", "").strip():
            p["credits"] = float(row["credits"])
            p["price_as_of"] = row.get("price_as_of", "").strip()
            p["price_source"] = row.get("price_source", "").strip()
        if row.get("availability", "").strip():
            p["availability"] = row["availability"].strip()
            p["availability_as_of"] = row.get("availability_as_of", "").strip() or None
            p["availability_source"] = row.get("availability_source", "").strip() or None
        roster[pid] = p
        count += 1
    if not count:
        raise ValueError("CSV has no player rows")
    result["players"] = list(roster.values())
    if "CSV import (user supplied)" not in result["sources"]:
        result["sources"].append("CSV import (user supplied)")
    return validate(result)
