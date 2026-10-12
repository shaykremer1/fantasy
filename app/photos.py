"""Public player portraits, matched by a unique exact name and saved by official ID."""
from collections import defaultdict
from html.parser import HTMLParser
import json
import os
import tempfile
from pathlib import Path
import re
import time
from urllib.parse import urlparse
import urllib.request

CATALOG = 'https://www.dunkest.com/en/euroleague/players'
REGISTRY = Path(__file__).with_name('player_photos.json')
IMAGE_HOSTS = {'media-cdn.incrowdsports.com', 'media-cdn.cortextech.io', 'fantaking-assets.dunkest.com', 'www.dunkest.com'}


def safe_image(url):
    if not isinstance(url, str) or len(url) > 1500:
        return None
    try:
        parsed = urlparse(url)
        if (parsed.scheme == 'https' and parsed.hostname in IMAGE_HOSTS
                and parsed.port in (None, 443) and not parsed.username and not parsed.password):
            return url
    except ValueError:
        pass
    return None


class CatalogParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows = []; self.current = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a' and 'players-group__player' in attrs.get('class', '').split():
            url = attrs.get('href', '')
            if re.fullmatch(r'https://www\.dunkest\.com/en/player/\d+/[a-z0-9-]+', url):
                self.current = [url, '']

    def handle_data(self, text):
        if self.current is not None:
            self.current[1] += text

    def handle_endtag(self, tag):
        if tag == 'a' and self.current is not None:
            self.rows.append(self.current); self.current = None


class PortraitParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.image = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'player-info__propic' in attrs.get('class', '').split():
            match = re.search(r'background-image:\s*url\(([^)]+)\)', attrs.get('style', ''))
            if match:
                self.image = safe_image(match[1].strip('\"\x27'))


def name_key(name):
    return ' '.join(name.replace(',', ' ').casefold().split())


def apply_photos(data):
    registry = json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {}
    for player in data['players']:
        record = registry.get(player['id'], {})
        # IDs stay stable across club transfers. Check the exact name as well.
        if (name_key(record.get('name', '')) == name_key(player['name'])
                and safe_image(record.get('image_url')) and not safe_image(player.get('image_url'))):
            player.update(image_url=record['image_url'], image_source=record['source'])
            if CATALOG not in data['sources']:
                data['sources'].append(CATALOG)
    return data


def fetch_public_text(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'FantasyMatchupLab/0.1', 'Accept': 'text/html'})
    with urllib.request.urlopen(request, timeout=20) as response:
        body = response.read(6_000_001)
    if len(body) > 6_000_000:
        raise ValueError('Public portrait page too large')
    return body.decode('utf-8')


def collect(data, fetch=fetch_public_text, progress=None):
    parser = CatalogParser(); parser.feed(fetch(CATALOG))
    # A player newly transferred into EuroLeague may still have a public NBA portrait.
    # This directory supplies identity/photo links only; no NBA statistics are imported.
    try:
        parser.feed(fetch('https://www.dunkest.com/en/nba/players'))
    except (OSError, ValueError):
        pass
    names = defaultdict(set)
    for url, name in parser.rows:
        names[name_key(name)].add(url)
    official_names = defaultdict(list)
    for player in data['players']:
        official_names[name_key(player['name'])].append(player)
    registry = json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {}
    count = 0
    for key, players in official_names.items():
        if len(players) != 1 or len(names[key]) != 1:
            continue
        player = players[0]
        if registry.get(player['id'], {}).get('name') == player['name']:
            continue
        url = next(iter(names[key]))
        if fetch is fetch_public_text:
            time.sleep(1.2)  # Bounded, read-only requests to the public player directory.
        try:
            portrait = PortraitParser(); portrait.feed(fetch(url))
        except (OSError, ValueError):
            continue
        if portrait.image:
            registry[player['id']] = {'name': player['name'], 'image_url': portrait.image, 'source': url}
            count += 1
            if fetch is fetch_public_text:
                handle, temporary = tempfile.mkstemp(dir=REGISTRY.parent, suffix='.json')
                try:
                    with os.fdopen(handle, 'w') as stream:
                        json.dump(registry, stream, ensure_ascii=False, indent=2)
                        stream.write('\n')
                    os.replace(temporary, REGISTRY)
                finally:
                    if os.path.exists(temporary): os.unlink(temporary)
            if progress:
                progress(count, len(registry))
    return registry


if __name__ == '__main__':
    from .data import Store
    collect(Store(Path(__file__).resolve().parent.parent / '.data/live.json').read(),
            progress=lambda count, total: print(f'Public portraits saved: {total}', flush=True) if count % 20 == 0 else None)
