"""Register, queue and inspect bounded AutoSaddler jobs through the Harness owner."""
import argparse
import json
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('prepare').add_argument('specification')
    commands.add_parser('start').add_argument('case_id')
    commands.add_parser('status').add_argument('case_id')
    args = parser.parse_args()
    with httpx.Client(base_url='http://127.0.0.1:8765', timeout=30, trust_env=False) as client:
        if args.command == 'prepare':
            path = Path(args.specification)
            if path.stat().st_size > 128_000:
                parser.error('Specification exceeds 128 KB')
            response = client.post('/api/harness/optimizations', json=json.loads(path.read_text()))
        else:
            uri = '/api/harness/optimizations/' + args.case_id
            response = client.post(uri + '/run') if args.command == 'start' else client.get(uri)
        if response.is_error:
            parser.error(response.text)
        print(json.dumps(response.json(), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
