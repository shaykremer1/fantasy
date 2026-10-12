"""Repeatable setup/refresh command for the public statistics snapshot."""
import argparse
from pathlib import Path

from .data import Store
from .providers import sync


def main():
    parser = argparse.ArgumentParser(description="Refresh official EuroLeague statistics and season registrations")
    parser.add_argument('--season', help='Starting-year code, e.g. E2026; defaults to the current snapshot season')
    parser.add_argument('--data', default=str(Path(__file__).resolve().parent.parent / '.data' / 'live.json'))
    args = parser.parse_args()
    store = Store(args.data)
    current = store.read()
    def progress(done, total):
        if done % 10 == 0 or done == total:
            print(f'Completed boxscores: {done}/{total}', flush=True)
    result = sync(current, args.season or current['season'], progress=progress)
    store.save(result)
    print(f"Saved {result['season']}: {len(result['teams'])} teams, {len(result['players'])} roster players, "
          f"{len(result['games'])} fixtures, {len(result['appearances'])} appearance records")


if __name__ == '__main__':
    main()
