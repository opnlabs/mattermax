#!/usr/bin/env python3
"""Compare committed preference updates with a baseline source overlay."""
import argparse
import hashlib
import json
import os
import pathlib
import platform
import re
import statistics
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--workspace', type=pathlib.Path, required=True, help='Mattermax work/src')
parser.add_argument('--baseline', default='HEAD^', help='Workspace revision before the batching patch')
parser.add_argument('--iterations', type=int, default=500)
parser.add_argument('--trials', type=int, default=3)
parser.add_argument('--output', type=pathlib.Path, required=True)
args = parser.parse_args()
if min(args.iterations, args.trials) < 1:
    parser.error('iterations and trials must be positive')
workspace = args.workspace.resolve()
server = workspace / 'server'
relative = 'server/channels/store/sqlstore/preference_store.go'
source = workspace / relative

def git(*command):
    return subprocess.check_output(['git', '-C', str(workspace), *command])

baseline_sha = git('rev-parse', args.baseline).decode().strip()
baseline = git('show', baseline_sha + ':' + relative)
report = {
    'status': 'running',
    'method': 'Real Go SQL store, committed updates to existing keys, 32-byte values. Each process initializes the PostgreSQL test store. Single-threaded benchmark; HTTP, app side effects and race instrumentation excluded. Alternating-order paired processes; median ns/op across trials.',
    'baseline_workspace_sha': baseline_sha,
    'current_workspace_sha': git('rev-parse', 'HEAD').decode().strip(),
    'source_sha256': {'before': hashlib.sha256(baseline).hexdigest(), 'after': hashlib.sha256(source.read_bytes()).hexdigest(), 'benchmark_test': hashlib.sha256(source.with_name('preference_store_test.go').read_bytes()).hexdigest()},
    'environment': {'platform': platform.platform(), 'go': subprocess.check_output(['go', 'version']).decode().strip(), 'cpu': next((line.split(':', 1)[1].strip() for line in pathlib.Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')), 'unknown')},
    'settings': {'trials': args.trials, 'iterations': args.iterations},
    'samples': [],
}
try:
    with tempfile.TemporaryDirectory(prefix='preference-bench-') as temporary:
        temporary = pathlib.Path(temporary)
        old = temporary / 'before.go'
        old.write_bytes(baseline)
        overlay = temporary / 'overlay.json'
        overlay.write_text(json.dumps({'Replace': {str(source): str(old)}}))
        for trial in range(args.trials):
            for variant in (['before', 'after'] if trial % 2 == 0 else ['after', 'before']):
                command = ['go', 'test']
                if variant == 'before':
                    command += ['-overlay', str(overlay)]
                command += ['./channels/store/sqlstore', '-run', '^$', '-bench', '^BenchmarkPreferenceSave$', '-benchtime', str(args.iterations)+'x', '-count=1', '-timeout=10m', '-json']
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
                    match = re.match(r'BenchmarkPreferenceSave/PostgreSQL/records=(\d+)-\d+\s+(\d+)\s+([\d.]+) ns/op\s+([\d.]+) B/op\s+([\d.]+) allocs/op$', output)
                    if match:
                        size, iterations, ns, allocated, allocations = match.groups()
                        records.append({'records': int(size), 'iterations': int(iterations), 'ns_per_op': float(ns), 'bytes_per_op': float(allocated), 'allocations_per_op': float(allocations), 'raw': output})
                if process.returncode or not terminal_pass or sorted(r['records'] for r in records) != [1, 10, 100]:
                    raise RuntimeError(f'{variant} trial {trial} failed or has missing benchmarks: ' + process.stdout[-8000:])
                report['samples'].append({'trial': trial, 'variant': variant, 'benchmarks': records})
                print(variant, trial, [(r['records'], r['ns_per_op']) for r in records], flush=True)
    report['summary'] = []
    for size in [1, 10, 100]:
        row = {'records': size}
        for variant in ['before', 'after']:
            selected = [r for s in report['samples'] if s['variant'] == variant for r in s['benchmarks'] if r['records'] == size]
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
