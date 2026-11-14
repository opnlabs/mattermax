#!/usr/bin/env python3
"""Compare legacy and scalar auto-archive activity reads through the SQL store."""
import argparse
import hashlib
import json
import pathlib
import platform
import re
import statistics
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--workspace', type=pathlib.Path, required=True, help='Mattermax work/src')
parser.add_argument('--iterations', type=int, default=500)
parser.add_argument('--trials', type=int, default=3)
parser.add_argument('--output', type=pathlib.Path, required=True)
args = parser.parse_args()
if min(args.iterations, args.trials) < 1:
    parser.error('iterations and trials must be positive')
workspace = args.workspace.resolve()
server = workspace / 'server'
files = ['channels/store/sqlstore/post_store.go', 'channels/store/sqlstore/thread_store.go', 'channels/store/sqlstore/post_store_test.go', 'channels/app/channel_posting_rules.go']
report = {
    'status': 'running',
    'method': 'Same real SQL store and full migrated schema, legacy GetSingle plus Thread.Get versus scalar GetThreadLastActivityAt. Synthetic thread fixtures with 0, 1000 and 10000 replies. Timed loops include PostgreSQL/driver costs but exclude HTTP, post insertion and policy authorization. Alternating-order paired processes; median ns/op across trials.',
    'workspace_sha': subprocess.check_output(['git', '-C', str(workspace), 'rev-parse', 'HEAD']).decode().strip(),
    'source_sha256': {p: hashlib.sha256((server/p).read_bytes()).hexdigest() for p in files},
    'environment': {'platform': platform.platform(), 'go': subprocess.check_output(['go', 'version']).decode().strip(), 'cpu': next((line.split(':', 1)[1].strip() for line in pathlib.Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')), 'unknown')},
    'settings': {'iterations': args.iterations, 'trials': args.trials},
    'samples': [],
}
try:
    for trial in range(args.trials):
        for variant in (['legacy', 'scalar'] if trial % 2 == 0 else ['scalar', 'legacy']):
            command = ['go', 'test', './channels/store/sqlstore', '-run', '^$', '-bench', '^BenchmarkThreadActivityLookup$/^PostgreSQL$/^replies=(0|1000|10000)$/^'+variant+'$', '-benchtime', str(args.iterations)+'x', '-count=1', '-timeout=10m', '-json']
            process = subprocess.run(command, cwd=server, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=900)
            records = []
            terminal_pass = False
            for line in process.stdout.splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                terminal_pass |= event.get('Action') == 'pass' and not event.get('Test')
                output = event.get('Output', '').strip()
                match = re.match(r'BenchmarkThreadActivityLookup/PostgreSQL/replies=(\d+)/'+variant+r'-\d+\s+(\d+)\s+([\d.]+) ns/op\s+([\d.]+) B/op\s+([\d.]+) allocs/op$', output)
                if match:
                    replies, iterations, ns, allocated, allocations = match.groups()
                    records.append({'replies': int(replies), 'iterations': int(iterations), 'ns_per_op': float(ns), 'bytes_per_op': float(allocated), 'allocations_per_op': float(allocations), 'raw': output})
            if process.returncode or not terminal_pass or sorted(r['replies'] for r in records) != [0, 1000, 10000]:
                raise RuntimeError(f'{variant} trial {trial} failed or has missing benchmarks: ' + process.stdout[-10000:])
            report['samples'].append({'trial': trial, 'variant': variant, 'benchmarks': records})
            print(variant, trial, [(r['replies'], r['ns_per_op']) for r in records], flush=True)
    report['summary'] = []
    for replies in [0, 1000, 10000]:
        row = {'replies': replies}
        for variant in ['legacy', 'scalar']:
            selected = [r for s in report['samples'] if s['variant'] == variant for r in s['benchmarks'] if r['replies'] == replies]
            row[variant] = {key: statistics.median(r[key] for r in selected) for key in ['ns_per_op', 'bytes_per_op', 'allocations_per_op']}
            row[variant]['ns_per_op_range'] = [min(r['ns_per_op'] for r in selected), max(r['ns_per_op'] for r in selected)]
        report['summary'].append(row)
    report['status'] = 'passed'
except Exception as error:
    report['status'] = 'failed'
    report['error'] = str(error)
    raise
finally:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2)+'\n')
