#!/usr/bin/env python3
"""Compare fixed array reads with legacy queries using identical SQL/app fixtures."""
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
parser.add_argument('--workspace', type=pathlib.Path, required=True)
parser.add_argument('--baseline', default='HEAD^')
parser.add_argument('--iterations', type=int, default=1000)
parser.add_argument('--trials', type=int, default=3)
parser.add_argument('--output', type=pathlib.Path, required=True)
args = parser.parse_args()
if min(args.iterations, args.trials) < 1:
    parser.error('iterations and trials must be positive')
workspace = args.workspace.resolve()
server = workspace / 'server'
paths = ['server/channels/store/sqlstore/post_priority_store.go', 'server/channels/store/sqlstore/post_acknowledgements_store.go']

def git(*command):
    return subprocess.check_output(['git', '-C', str(workspace), *command])

baseline_sha = git('rev-parse', args.baseline).decode().strip()
before = {path: git('show', baseline_sha + ':' + path) for path in paths}
densities = ['empty', 'sparse', 'dense']
expected = [f'BenchmarkPriorityAcknowledgementReads/PostgreSQL/{density}/ids={n}' for density in densities for n in [1, 60, 200, 201]]
expected += [f'BenchmarkPriorityAcknowledgementHistory/{density}/posts={n}' for density in densities for n in [1, 60]]
report = {
    'status': 'running',
    'method': 'Alternating-order paired processes. A Go overlay restores only the two store production files for baseline; all other code and fixtures are identical. Fixed iterations keep the leaf benchmark calibration/fixture creation count equal. Store benchmarks execute both priority and acknowledgement reads; complete App history benchmarks use stored, ordered pages with priority reads enabled. Empty/sparse/dense distributions contain zero, one per 20, or all IDs with metadata. Positive results and order are validated. No files, reactions or remote links.',
    'baseline_workspace_sha': baseline_sha,
    'current_workspace_sha': git('rev-parse', 'HEAD').decode().strip(),
    'source_sha256': {path: {'before': hashlib.sha256(before[path]).hexdigest(), 'after': hashlib.sha256((workspace / path).read_bytes()).hexdigest()} for path in paths},
    'environment': {'platform': platform.platform(), 'go': subprocess.check_output(['go', 'version']).decode().strip(), 'GOMAXPROCS': os.getenv('GOMAXPROCS'), 'GOFLAGS': os.getenv('GOFLAGS'), 'cpu': next((x.split(':', 1)[1].strip() for x in pathlib.Path('/proc/cpuinfo').read_text().splitlines() if x.startswith('model name')), 'unknown')},
    'settings': {'trials': args.trials, 'iterations': args.iterations},
    'samples': [],
}
for fixture in ['server/channels/store/sqlstore/priority_ack_array_test.go', 'server/channels/app/post_priority_array_test.go']:
    report['source_sha256'][fixture] = hashlib.sha256((workspace / fixture).read_bytes()).hexdigest()
try:
    with tempfile.TemporaryDirectory(prefix='priority-ack-bench-') as tmp:
        tmp = pathlib.Path(tmp)
        replace = {}
        for index, path in enumerate(paths):
            file = tmp / f'before-{index}.go'
            file.write_bytes(before[path])
            replace[str(workspace / path)] = str(file)
        overlay = tmp / 'overlay.json'
        overlay.write_text(json.dumps({'Replace': replace}))
        for trial in range(args.trials):
            for variant in (['before', 'after'] if trial % 2 == 0 else ['after', 'before']):
                command = ['go', 'test'] + (['-overlay', str(overlay)] if variant == 'before' else [])
                command += ['-p', '1', './channels/store/sqlstore', './channels/app', '-run', '^$', '-bench', '^(BenchmarkPriorityAcknowledgementReads|BenchmarkPriorityAcknowledgementHistory)$', '-benchtime', str(args.iterations) + 'x', '-count=1', '-timeout=10m', '-json']
                proc = subprocess.run(command, cwd=server, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=900)
                terminal = []
                records = []
                for line in proc.stdout.splitlines():
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if event.get('Action') in ['pass', 'fail'] and not event.get('Test'):
                        terminal.append(event['Action'])
                    output = event.get('Output', '').strip()
                    match = re.match(r'(BenchmarkPriorityAcknowledgement(?:Reads|History)/.+)-\d+\s+(\d+)\s+([\d.]+) ns/op\s+([\d.]+) B/op\s+([\d.]+) allocs/op$', output)
                    if match:
                        name, iterations, ns, allocated, allocations = match.groups()
                        records.append({'name': name, 'iterations': int(iterations), 'ns_per_op': float(ns), 'bytes_per_op': float(allocated), 'allocations_per_op': float(allocations), 'raw': output})
                if proc.returncode or terminal != ['pass', 'pass'] or sorted(r['name'] for r in records) != sorted(expected):
                    raise RuntimeError(f'{variant} trial {trial} failed or omitted cases: ' + proc.stdout[-10000:])
                report['samples'].append({'trial': trial, 'variant': variant, 'benchmarks': records})
                print(variant, trial, [(r['name'], r['ns_per_op']) for r in records if '/posts=60' in r['name']], flush=True)
    report['summary'] = []
    for name in expected:
        row = {'name': name}
        for variant in ['before', 'after']:
            selected = [r for s in report['samples'] if s['variant'] == variant for r in s['benchmarks'] if r['name'] == name]
            row[variant] = {key: statistics.median(r[key] for r in selected) for key in ['ns_per_op', 'bytes_per_op', 'allocations_per_op']}
            row[variant]['ns_per_op_range'] = [min(r['ns_per_op'] for r in selected), max(r['ns_per_op'] for r in selected)]
        report['summary'].append(row)
    report['status'] = 'passed'
except Exception as error:
    report.update(status='failed', error=str(error))
    raise
finally:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
