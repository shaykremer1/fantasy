import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from app.data import empty_dataset, validate
from app.photos import safe_image, apply_photos, collect, PortraitParser


class PhotoTests(unittest.TestCase):
    def setUp(self):
        self.data = empty_dataset()
        self.data['teams'] = [{'id': 'A', 'name': 'Alpha'}]
        self.data['players'] = [{'id': 'P1', 'name': 'DOE, JANE', 'team_id': 'A', 'position': 'G'}]
        self.url = 'https://media-cdn.cortextech.io/test.png'

    def test_rejects_untrusted_urls_and_bad_ports(self):
        for url in ['javascript:alert(1)', 'http://media-cdn.cortextech.io/a.png',
                    'https://media-cdn.cortextech.io.evil.example/a.png',
                    'https://user@media-cdn.cortextech.io/a.png',
                    'https://media-cdn.cortextech.io:999/a.png',
                    'https://media-cdn.cortextech.io:bad/a.png']:
            self.assertIsNone(safe_image(url))
        self.data['players'][0]['image_url'] = 'https://evil.example/a.png'
        with self.assertRaises(ValueError): validate(self.data)

    def test_registry_checks_both_identity_and_name(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'photos.json'
            path.write_text(json.dumps({'P1': {'name': 'DOE, JANE', 'image_url': self.url, 'source': 'Public profile'}}))
            with patch('app.photos.REGISTRY', path):
                apply_photos(self.data)
                self.assertEqual(self.data['players'][0]['image_url'], self.url)
                self.data['players'][0].pop('image_url')
                self.data['players'][0]['name'] = 'SMITH, JANE'
                apply_photos(self.data)
                self.assertNotIn('image_url', self.data['players'][0])

    def test_collect_uses_only_unique_exact_name_links_and_portrait_class(self):
        profile = '<div class="player-info__propic" style="background-image: url('+self.url+');"></div>'
        catalog = '<a class="players-group__player" href="https://www.dunkest.com/en/player/7/jane-doe">Doe Jane</a>'
        with tempfile.TemporaryDirectory() as folder, patch('app.photos.REGISTRY', Path(folder)/'photos.json'):
            result = collect(self.data, fetch=lambda url: catalog if url.endswith('/players') else profile)
            self.assertEqual(result['P1']['image_url'], self.url)
            duplicate = catalog + catalog.replace('/7/', '/8/')
            self.assertEqual(collect(self.data, fetch=lambda url: duplicate), {})
        parser = PortraitParser(); parser.feed('<img src="'+self.url+'">')
        self.assertIsNone(parser.image)
