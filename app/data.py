"""Validated, versioned input. Missing market information stays missing."""
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import tempfile
from .photos import safe_image

POSITIONS = {"PG", "SG", "SF", "PF", "C", "G", "F", "UNK"}
AVAILABILITY = {"available", "doubtful", "out", "unknown"}


def utcnow():
    return datetime.now(timezone.utc)


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("Expected an ISO-8601 timestamp with timezone")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid ISO-8601 timestamp") from exc
    if result.tzinfo is None:
        raise ValueError("Timestamps must include a timezone")
    return result.astimezone(timezone.utc)


def text(value, field):
    if not isinstance(value, str) or not value.strip() or len(value) > 300:
        raise ValueError(f"{field}: expected nonempty text (max 300 characters)")
    return value


def number(value, field, low=None, high=None):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError(f"{field}: expected a finite number")
    if (low is not None and value < low) or (high is not None and value > high):
        raise ValueError(f"{field}: value out of range")
    return value


def empty_dataset():
    return {"schema_version": 1, "season": "E2026", "mode": "live", "sources": [],
            "teams": [], "players": [], "games": [], "appearances": []}


def validate(data):
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data.get("schema_version") != 1:
        raise ValueError("schema_version must be 1")
    text(data.get("season"), "season")
    if data.get("mode") not in {"live", "demo"}:
        raise ValueError("mode must be live or demo")
    for key in ("teams", "players", "games", "appearances", "sources"):
        if not isinstance(data.get(key), list):
            raise ValueError(f"{key} must be an array")
        if len(data[key]) > 100000:
            raise ValueError(f"{key}: too many records")
    for source in data["sources"]:
        text(source, "source")

    def index(key):
        result = {}
        for item in data[key]:
            if not isinstance(item, dict):
                raise ValueError(f"{key}: each record must be an object")
            ident = text(item.get("id"), f"{key}.id")
            if ident in result:
                raise ValueError(f"Duplicate {key} id: {ident}")
            result[ident] = item
        return result

    teams, players, games = index("teams"), index("players"), index("games")
    for item in [*teams.values(), *players.values()]:
        if item.get('image_url') is not None and not safe_image(item['image_url']):
            raise ValueError('Images must use an approved HTTPS image host')
    for t in teams.values():
        text(t.get("name"), "team.name")
    if 'coaches' in data:
        if not isinstance(data['coaches'], list) or len(data['coaches']) > 100000:
            raise ValueError('coaches must be a bounded array')
        for c in index('coaches').values():
            text(c.get('name'), 'coach.name')
            if c.get('team_id') not in teams or not isinstance(c.get('active'), bool):
                raise ValueError('Invalid coach team or active status')
            if c.get('credits') is not None:
                number(c['credits'], 'coach.credits', 0.01, 1000)
                if timestamp(c.get('price_as_of')) > utcnow():
                    raise ValueError('Coach price observation cannot be in the future')
                text(c.get('price_source'), 'coach.price_source')
            if c.get('price_matchday') is not None and (type(c['price_matchday']) is not int or c['price_matchday'] < 1):
                raise ValueError('Coach price matchday must be a positive integer')
    for p in players.values():
        text(p.get("name"), "player.name")
        if p.get("team_id") not in teams:
            raise ValueError("Player references an unknown team")
        if p.get("position") not in POSITIONS:
            raise ValueError("Position must be PG, SG, SF, PF, C, G, F or UNK")
        if p.get("availability", "unknown") not in AVAILABILITY:
            raise ValueError("Invalid availability")
        if 'roster_active' in p and not isinstance(p['roster_active'],bool):
            raise ValueError('roster_active must be a boolean')
        if p.get('price_matchday') is not None and (type(p['price_matchday']) is not int or p['price_matchday']<1):
            raise ValueError('price_matchday must be a positive integer')
        if p.get('fantasy_player_id') is not None:text(p['fantasy_player_id'],'fantasy_player_id')
        if p.get("credits") is not None:
            number(p["credits"], "credits", 0.01, 1000)
            timestamp(p.get("price_as_of"))
            text(p.get("price_source"), "price_source")
        if p.get("availability", "unknown") != "unknown":
            timestamp(p.get("availability_as_of"))
            text(p.get("availability_source"), "availability_source")
        for k in ("price_as_of", "availability_as_of"):
            if p.get(k) is not None:
                if timestamp(p[k]) > utcnow():
                    raise ValueError(f"{k}: future observation timestamps are not allowed")
    for g in games.values():
        if g.get("home_team_id") not in teams or g.get("away_team_id") not in teams:
            raise ValueError("Game references an unknown team")
        if g["home_team_id"] == g["away_team_id"]:
            raise ValueError("A team cannot play itself")
        if g.get("status") not in {"scheduled", "finished", "cancelled"}:
            raise ValueError("Invalid game status")
        if not isinstance(g.get("round"), int) or isinstance(g["round"], bool) or g["round"] < 1:
            raise ValueError("round must be a positive integer")
        timestamp(g.get("date"))
        for field in ('home_score', 'away_score'):
            if g.get(field) is not None:
                number(g[field], field, 0, 300)
                if type(g[field]) is not int:
                    raise ValueError('Game scores must be integers')
    seen = set()
    for row in data["appearances"]:
        if not isinstance(row, dict):
            raise ValueError("Each appearance must be an object")
        game, player = games.get(row.get("game_id")), players.get(row.get("player_id"))
        if not game or not player:
            raise ValueError("Appearance references an unknown game or player")
        if game["status"] != "finished":
            raise ValueError("Appearances can only reference finished games")
        pair = (row["game_id"], row["player_id"])
        if pair in seen:
            raise ValueError("Duplicate player/game appearance")
        seen.add(pair)
        if {row.get("team_id"), row.get("opponent_id")} != {game["home_team_id"], game["away_team_id"]}:
            raise ValueError("Appearance teams do not match the fixture")
        if row.get("team_id") == row.get("opponent_id"):
            raise ValueError("Appearance has identical team and opponent")
        if row.get("position", player["position"]) not in POSITIONS:
            raise ValueError("Invalid historical position")
        number(row.get("minutes"), "minutes", 0, 70)
        number(row.get("pir"), "pir", -100, 200)
        if row["minutes"] == 0 and row["pir"] != 0:
            raise ValueError("A DNP cannot have nonzero PIR")
    return data


class Store:
    def __init__(self, path):
        self.path = Path(path)

    def read(self):
        if not self.path.exists():
            return empty_dataset()
        return validate(json.loads(self.path.read_text()))

    def save(self, data):
        validate(data)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic replace: an invalid/failed import never corrupts the prior snapshot.
        handle, name = tempfile.mkstemp(dir=self.path.parent, suffix=".json")
        try:
            with os.fdopen(handle, "w") as f:
                json.dump(data, f, ensure_ascii=False, allow_nan=False)
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
