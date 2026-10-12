import argparse
import csv
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlparse
import urllib.error
import copy
import os

from .analysis import analyze
from .data import Store, validate
from .demo import dataset
from .providers import import_roster, sync
from .market import connection_status, sync_prices
from .backtest import evaluate
from .scout import scout
from .photos import apply_photos
from .squad import sync_squad
from .squad_planner import plan_squad
from .data import utcnow

ROOT = Path(__file__).resolve().parent.parent


class Application:
    def __init__(self, path, public_read_only=False):
        self.public_read_only=public_read_only
        self.store = Store(path)
        self.demo = validate(dataset())
        self.lock = threading.RLock()
        self.job = {"state": "idle", "completed": 0, "total": 0, "error": None}
        self.market_report = None
        self.market_error = None
        self.squad = None
        self.squad_error = None
        self.stop_event=threading.Event()
        self.auto={'enabled':False,'interval_seconds':300,'last_attempt':None,'last_success':None,'error':None}
        self.auto_thread=None

    def refresh_once(self):
        with self.lock:
            if self.job['state']=='running':return False
            current=self.store.read()
            if current['mode']!='live':return False
            self.job={'state':'running','kind':'automatic','completed':0,'total':0,'error':None}
            self.auto['last_attempt']=utcnow().isoformat()
        self.run_sync(current,current['season'])
        with self.lock:
            if self.job['state']=='done':
                self.auto.update(last_success=utcnow().isoformat(),error=None)
            else:self.auto['error']=self.job['error']
        return self.job['state']=='done'

    def start_auto(self, interval=300):
        self.auto.update(enabled=True,interval_seconds=interval)
        def loop():
            while not self.stop_event.is_set():
                self.refresh_once()
                if self.stop_event.wait(interval):break
        self.auto_thread=threading.Thread(target=loop,daemon=True)
        self.auto_thread.start()

    def snapshot(self, mode):
        with self.lock:
            return self.demo if mode == "demo" else apply_photos(self.store.read())

    def progress(self, completed, total):
        with self.lock:
            self.job.update(completed=completed, total=total)

    def run_sync(self, current, season, kind='statistics'):
        try:
            if kind=='market':
                updated, report = sync_prices(current)
            else:
                updated = sync(current, season, progress=self.progress)
            with self.lock:
                self.store.save(updated)
                if kind=='market':
                    self.market_report=report
                    self.market_error=None
            if kind != 'market' and connection_status()['credential_present']:
                try:
                    priced, report = sync_prices(updated)
                    with self.lock:
                        self.store.save(priced)
                        self.market_report = report
                        self.market_error = None
                except ValueError as exc:
                    # Provider validation errors contain field names/status codes, not response bodies or credentials.
                    with self.lock:
                        self.market_error = str(exc)[:300]
                except Exception:
                    # Successful statistics remain available when pricing is unavailable.
                    with self.lock:
                        self.market_error = 'Price source could not be refreshed; previous prices retained'
            if connection_status()['credential_present']:
                try:
                    owner_squad = sync_squad(self.store.read())
                    with self.lock:
                        self.squad = owner_squad
                        self.squad_error = None
                except ValueError as exc:
                    with self.lock:self.squad_error = str(exc)[:300]
                except Exception:
                    with self.lock:self.squad_error = 'Squad source could not be refreshed'
            with self.lock:
                self.job.update(state="done")

        except (ValueError, urllib.error.URLError, OSError, TimeoutError) as exc:
            with self.lock:
                self.job.update(state="failed", error=f"{type(exc).__name__}: {exc}")
        except Exception:
            with self.lock:
                self.job.update(state="failed", error="Unexpected provider failure; existing snapshot was retained")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, app, **kwargs):
        self.app = app
        super().__init__(*args, directory=str(ROOT / "web"), **kwargs)

    def send_bytes(self, status, data, content_type="application/json; charset=utf-8", download=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{download}"')
        self.end_headers()
        self.wfile.write(data)

    def end_headers(self):
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' https://media-cdn.incrowdsports.com https://media-cdn.cortextech.io https://fantaking-assets.dunkest.com https://www.dunkest.com; style-src 'self'; script-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'")
        super().end_headers()

    def reply(self, status, data):
        self.send_bytes(status, json.dumps(data, ensure_ascii=False, allow_nan=False).encode())

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            if parsed.path == '/api/squad':
                with self.app.lock:
                    owner = copy.deepcopy(self.app.squad)
                    error = self.app.squad_error
                    updating = self.app.job['state'] == 'running'
                if owner is None:
                    return self.reply(200, {'available':False, 'error':error, 'updating':updating})
                # Public access was explicitly requested by the owner for now.
                if query.get('summary',['0'])[0] == '1':
                    return self.reply(200, {'available':True, 'squad':owner, 'error':error, 'updating':updating})
                rnd = query.get('round',[None])[0]
                rnd = int(rnd) if rnd else None
                window = int(query.get('window',['10'])[0])
                venue = query.get('venue',['all'])[0]
                if window not in {0,5,10} or venue not in {'all','home','away'}:
                    raise ValueError('Invalid squad analysis filters')
                plans = plan_squad(self.app.snapshot('live'),owner,target_round=rnd,window=window,venue=venue)
                return self.reply(200, {'available':True, 'squad':owner, 'plans':plans, 'error':error, 'updating':updating})
            if parsed.path == "/api/health":
                return self.reply(200, {"status": "ok"})
            if parsed.path=='/api/auto-status':
                with self.app.lock:return self.reply(200,self.app.auto)
            if parsed.path == "/api/sync-status":
                with self.app.lock:
                    return self.reply(200, self.app.job)
            if parsed.path == '/api/market-status':
                with self.app.lock:
                    return self.reply(200,{**connection_status(),'live_schema_verified':self.app.market_report is not None,'last_import':self.app.market_report,'error':self.app.market_error})
            if parsed.path in {'/api/backtest','/api/backtest/export'}:
                mode=query.get('mode',['live'])[0]
                if mode not in {'live','demo'}:raise ValueError('Invalid mode')
                if mode=='demo':
                    data=copy.deepcopy(self.app.demo)
                    pp={p['id']:p for p in data['players']}
                    for row in data['appearances']:row['position']=pp[row['player_id']]['position']
                    report=evaluate(data,through_round=10,holdout_rounds=2)
                else:
                    path=ROOT/'.data'/'reports'/'E2025.json'
                    if not path.exists():return self.reply(200,{'available':False,'mode':mode,'reason':'No completed historical report yet'})
                    report=json.loads(path.read_text())
                    if report.get('kind')!='backtest' or report.get('mode')!='live':raise ValueError('Invalid saved evaluation report')
                if parsed.path.endswith('/export'):
                    return self.send_bytes(200,json.dumps(report,ensure_ascii=False,indent=2).encode(),download=f'backtest-{mode}.json')
                summary={k:v for k,v in report.items() if k!='records'}
                return self.reply(200,{'available':True,**summary})
            if parsed.path in {"/api/dashboard", "/api/export", "/api/roster-template"}:
                mode = query.get("mode", ["live"])[0]
                if mode not in {"live", "demo"}:
                    raise ValueError("Invalid mode")
                data = self.app.snapshot(mode)
                if parsed.path == "/api/export":
                    return self.send_bytes(200, json.dumps(data, ensure_ascii=False, indent=2).encode(), download=f"fantasy-{mode}.json")
                if parsed.path == "/api/roster-template":
                    fields = ["season", "player_id", "name", "team_id", "position", "credits", "price_as_of", "price_source",
                              "availability", "availability_as_of", "availability_source"]
                    buf = io.StringIO()
                    writer = csv.DictWriter(buf, fieldnames=fields)
                    writer.writeheader()
                    for p in data["players"]:
                        row = {k: p.get(k, "") for k in fields}
                        row.update(season=data["season"], player_id=p["id"])
                        writer.writerow(row)
                    return self.send_bytes(200, buf.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8", "roster.csv")
                rnd = query.get("round", [None])[0]
                rnd = int(rnd) if rnd else None
                window = int(query.get("window", ["10"])[0])
                venue = query.get("venue", ["all"])[0]
                if window not in {0, 5, 10} or venue not in {"all", "home", "away"}:
                    raise ValueError("Invalid analysis filter")
                if rnd is not None and rnd < 1:
                    raise ValueError("Invalid round")
                analysis=analyze(data, target_round=rnd, window=window, venue=venue)
                analysis['scouting']=scout(data,analysis)
                analysis['auto_refresh']=dict(self.app.auto)
                analysis['public_read_only']=self.app.public_read_only
                analysis['market']={'connected':connection_status()['credential_present'], 'last_import':self.app.market_report, 'error':self.app.market_error}
                return self.reply(200,analysis)
            if parsed.path.startswith("/api/"):
                return self.reply(404, {"error": "Unknown endpoint"})
            if parsed.path not in {"/", "/index.html", "/style.css", "/app.js", "/player-placeholder.svg"}:
                return self.reply(404, {"error": "Not found"})
            return super().do_GET()
        except (ValueError, TypeError, KeyError) as exc:
            return self.reply(400, {"error": str(exc)})

    def do_POST(self):
        if self.app.public_read_only:
            return self.reply(403,{'error':'Public website is read-only'})
        # Local dev API: disallow cross-origin writes and DNS rebinding.
        host = self.headers.get("Host", "")
        hostname = urlparse("http://" + host).hostname
        if hostname not in {"localhost", "127.0.0.1", "::1"}:
            return self.reply(403, {"error": "Local development access only"})
        origin = self.headers.get("Origin")
        if origin and origin != "http://" + host:
            return self.reply(403, {"error": "Cross-origin writes are not allowed"})
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            return self.reply(415, {"error": "Content-Type must be application/json"})
        path = urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 8_000_000:
                return self.reply(413, {"error": "Request must be between 1 byte and 8 MB"})
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("Expected a JSON object")
            with self.app.lock:
                if self.app.job["state"] == "running":
                    return self.reply(409, {"error": "Sync is running; wait before importing"})
                if path == "/api/import":
                    if body.get("mode") != "live":
                        raise ValueError("Only live snapshots can be imported; demo data is kept separate")
                    self.app.store.save(body)
                    return self.reply(200, {"status": "saved", "players": len(body["players"])})
                if path == "/api/roster":
                    contents = body.get("csv")
                    if not isinstance(contents, str):
                        raise ValueError("csv must be text")
                    updated = import_roster(self.app.store.read(), contents)
                    self.app.store.save(updated)
                    return self.reply(200, {"status": "saved", "players": len(updated["players"])})
                if path in {"/api/sync",'/api/market-sync'}:
                    kind='market' if path=='/api/market-sync' else 'statistics'
                    if kind=='market' and not connection_status()['credential_present']:
                        return self.reply(409,{'error':'Configure FANTASY_ACCESS_TOKEN securely in environment settings, or use CSV import'})
                    season = body.get("season",self.app.store.read()['season'])
                    if not isinstance(season, str):
                        raise ValueError("season must be text, e.g. E2026")
                    self.app.job = {"state": "running", "kind":kind,"completed": 0, "total": 0, "error": None}
                    thread = threading.Thread(target=self.app.run_sync, args=(self.app.store.read(), season,kind), daemon=True)
                    thread.start()
                    return self.reply(202, {"status": "running"})
                return self.reply(404, {"error": "Unknown endpoint"})
        except (ValueError, TypeError, KeyError, UnicodeDecodeError) as exc:
            return self.reply(400, {"error": str(exc)})


def main():
    parser = argparse.ArgumentParser(description="EuroLeague Fantasy Matchup Lab")
    parser.add_argument("--port", type=int, default=int(os.environ.get('PORT','8000')))
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--public-read-only',action='store_true')
    parser.add_argument("--data", default=str(ROOT / ".data" / "live.json"))
    parser.add_argument('--no-auto-sync',action='store_true',help='Disable public-data polling for isolated tests/offline operation')
    parser.add_argument('--sync-interval',type=int,default=300,help='Official EuroLeague polling interval in seconds (minimum 60)')
    args = parser.parse_args()
    app = Application(args.data,public_read_only=args.public_read_only)
    if args.sync_interval<60:parser.error('Minimum polling interval is 60 seconds')
    if not args.no_auto_sync:app.start_auto(args.sync_interval)
    handler = partial(Handler, app=app)
    with ThreadingHTTPServer((args.host, args.port), handler) as server:
        print(f"Matchup Lab listening on port {server.server_port}; live data is separate from demo", flush=True)
        try:server.serve_forever()
        finally:app.stop_event.set()


if __name__ == "__main__":
    main()
