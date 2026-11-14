#!/usr/bin/env python3
"""Compare per-member and batched read-receipt preference inputs."""
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
files = ['channels/store/sqlstore/preference_store.go', 'channels/store/sqlstore/preference_store_test.go', 'channels/app/read_receipts.go']
report = {
    'status': 'running',
    'method': 'Same real SQL store and full migrated schema. Legacy individual preference reads versus one batched read, including parsing/default-map construction. Synthetic 2-, 4- and 8-member ID sets with off, absent and enabled-since-zero preferences. Timed loops exclude channel/member reads, HTTP and event delivery. Alternating-order paired processes; median ns/op across trials.',
    'workspace_sha': subprocess.check_output(['git', '-C', str(workspace), 'rev-parse', 'HEAD']).decode().strip(),
    'source_sha256': {p: hashlib.sha256((server/p).read_bytes()).hexdigest() for p in files},
    'environment': {'platform': platform.platform(), 'go': subprocess.check_output(['go', 'version']).decode().strip(), 'cpu': next((line.split(':', 1)[1].strip() for line in pathlib.Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')), 'unknown')},
    'settings': {'iterations': args.iterations, 'trials': args.trials},
    'samples': [],
}
try:
    for trial in range(args.trials):
        for variant in (['legacy', 'batch'] if trial % 2 == 0 else ['batch', 'legacy']):
            command = ['go', 'test', './channels/store/sqlstore', '-run', '^$', '-bench', '^BenchmarkReadReceiptPreferenceInputs$/^PostgreSQL$/^members=(2|4|8)$/^'+variant+'$', '-benchtime', str(args.iterations)+'x', '-count=1', '-timeout=10m', '-json']
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
                match = re.match(r'BenchmarkReadReceiptPreferenceInputs/PostgreSQL/members=(\d+)/'+variant+r'-\d+\s+(\d+)\s+([\d.]+) ns/op\s+([\d.]+) B/op\s+([\d.]+) allocs/op$', output)
                if match:
                    members, iterations, ns, allocated, allocations = match.groups()
                    records.append({'members': int(members), 'iterations': int(iterations), 'ns_per_op': float(ns), 'bytes_per_op': float(allocated), 'allocations_per_op': float(allocations), 'raw': output})
            if process.returncode or not terminal_pass or sorted(r['members'] for r in records) != [2, 4, 8]:
                raise RuntimeError(f'{variant} trial {trial} failed or has missing benchmarks: ' + process.stdout[-10000:])
            report['samples'].append({'trial': trial, 'variant': variant, 'benchmarks': records})
            print(variant, trial, [(r['members'], r['ns_per_op']) for r in records], flush=True)
    report['summary'] = []
    for members in [2, 4, 8]:
        row = {'members': members}
        for variant in ['legacy', 'batch']:
            selected = [r for s in report['samples'] if s['variant'] == variant for r in s['benchmarks'] if r['members'] == members]
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
