from functools import partial
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
import urllib.error

from app.demo import dataset
from app.server import Application, Handler


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.app = Application(Path(cls.folder.name) / 'live.json')
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, app=cls.app))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.folder.cleanup()

    def request(self, path, data=None, origin=None):
        headers = {'Content-Type': 'application/json'}
        if origin:
            headers['Origin'] = origin
        req = urllib.request.Request(self.base + path, headers=headers,
                                     data=json.dumps(data).encode() if data is not None else None)
        return urllib.request.urlopen(req)

    def test_live_starts_empty_and_demo_is_separate(self):
        with self.request('/api/dashboard') as r:
            data = json.load(r)
        self.assertEqual(data['mode'], 'live')
        self.assertEqual(data['coverage']['players'], 0)
        with self.request('/api/dashboard?mode=demo') as r:
            demo = json.load(r)
        self.assertEqual(demo['coverage']['players'], 30)
        self.assertFalse(self.app.store.path.exists())

    def test_import_rejects_demo_into_live(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.request('/api/import', dataset())
        self.assertEqual(ctx.exception.code, 400)

    def test_cross_origin_cannot_write(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.request('/api/import', {}, origin='https://other.example')
        self.assertEqual(ctx.exception.code, 403)

    def test_invalid_filters_and_unknown_paths(self):
        for path, code in [('/api/dashboard?window=99', 400), ('/api/dashboard?venue=sideways', 400), ('/app/data.py', 404)]:
            with self.subTest(path=path), self.assertRaises(urllib.error.HTTPError) as ctx:
                self.request(path)
            self.assertEqual(ctx.exception.code, code)

    def test_html_and_csv_are_served(self):
        with self.request('/') as r:
            self.assertIn('lang="he"', r.read().decode())
        with self.request('/api/roster-template?mode=demo') as r:
            text = r.read().decode('utf-8-sig')
        self.assertIn('price_source', text)
        self.assertIn('DEMO,P0', text)

    def test_portrait_csp_and_local_fallback(self):
        with self.request('/') as response:
            csp=response.headers['Content-Security-Policy']
            self.assertIn('img-src',csp)
            self.assertIn('https://media-cdn.cortextech.io',csp)
            self.assertIn("script-src 'self'",csp)
        with self.request('/player-placeholder.svg') as response:
            self.assertIn('<svg',response.read().decode())

    def test_successful_import_is_persisted_and_bad_import_preserves_it(self):
        data = dataset()
        data['mode'] = 'live'
        data['season'] = 'E2026'
        try:
            with self.request('/api/import', data) as r:
                self.assertEqual(json.load(r)['status'], 'saved')
            with self.request('/api/dashboard') as r:
                self.assertEqual(json.load(r)['coverage']['players'], 30)
            original = self.app.store.path.read_bytes()
            data['appearances'][0]['opponent_id'] = 'does-not-exist'
            with self.assertRaises(urllib.error.HTTPError):
                self.request('/api/import', data)
            self.assertEqual(self.app.store.path.read_bytes(), original)
        finally:
            self.app.store.path.unlink(missing_ok=True)

    def test_failed_sync_preserves_snapshot_and_reports_error(self):
        from unittest.mock import patch
        data = dataset()
        try:
            self.app.store.save(data)
            original = self.app.store.path.read_bytes()
            with patch('app.server.sync', side_effect=ValueError('schema changed')):
                self.app.run_sync(data, 'E2026')
            self.assertEqual(self.app.job['state'], 'failed')
            self.assertIn('schema changed', self.app.job['error'])
            self.assertEqual(self.app.store.path.read_bytes(), original)
        finally:
            self.app.store.path.unlink(missing_ok=True)

    def test_synthetic_evaluation_is_separate_and_has_real_test_counts(self):
        with self.request('/api/backtest?mode=demo') as r:
            result=json.load(r)
        self.assertTrue(result['available'])
        self.assertEqual(result['mode'],'demo')
        self.assertGreater(result['summary']['n'],0)
        self.assertNotIn('records',result)

    def test_market_status_has_no_credential_values_and_missing_access_blocks_write(self):
        from unittest.mock import patch
        import os
        with patch.dict(os.environ,{'FANTASY_ACCESS_TOKEN':''}):
            with self.request('/api/market-status') as r:
                status=json.load(r)
            self.assertFalse(status['credential_present'])
            self.assertNotIn('token',status)
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.request('/api/market-sync',{})
            self.assertEqual(ctx.exception.code,409)


if __name__ == '__main__':
    unittest.main()
