#!/usr/bin/env python3
"""Measure an autolink precheck with identical fixtures and an unguarded overlay."""
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
parser.add_argument('--duration', default='1s')
parser.add_argument('--trials', type=int, default=3)
parser.add_argument('--output', type=pathlib.Path, required=True)
args = parser.parse_args()
if args.trials < 1:
    parser.error('trials must be positive')
workspace = args.workspace.resolve()
server = workspace / 'server'
relative = 'server/channels/app/post_metadata.go'
source = workspace / relative

def git(*command):
    return subprocess.check_output(['git', '-C', str(workspace), *command])

baseline_sha = git('rev-parse', args.baseline).decode().strip()
before = git('show', baseline_sha + ':' + relative)
types = ['plain', 'prose', 'formatting', 'colon_control', 'http_control', 'www_control']
expected = ['BenchmarkFirstAutolinkPrecheck/' + name for name in types]
expected += [f'BenchmarkAutolinkPrecheckHistory/{name}/posts={n}' for name in types for n in [1, 60]]
report = {
    'status': 'running',
    'method': 'Alternating-order paired processes. A Go overlay restores only post_metadata.go for baseline; all other production code and test/benchmark fixtures stay identical. Microbenchmarks validate first-link results against the unguarded parser. History benchmarks use real stored ordered pages, default priority/acknowledgement reads and output validation. No files or reactions. Link previews are disabled; link-positive controls use external URLs without fetching them. Single- and 60-post pages, six message types.',
    'baseline_workspace_sha': baseline_sha,
    'current_workspace_sha': git('rev-parse', 'HEAD').decode().strip(),
    'source_sha256': {'before': hashlib.sha256(before).hexdigest(), 'after': hashlib.sha256(source.read_bytes()).hexdigest(), 'fixtures': hashlib.sha256((server / 'channels/app/post_autolink_precheck_test.go').read_bytes()).hexdigest()},
    'environment': {'platform': platform.platform(), 'go': subprocess.check_output(['go', 'version']).decode().strip(), 'GOMAXPROCS': os.getenv('GOMAXPROCS'), 'GOFLAGS': os.getenv('GOFLAGS'), 'cpu': next((x.split(':', 1)[1].strip() for x in pathlib.Path('/proc/cpuinfo').read_text().splitlines() if x.startswith('model name')), 'unknown')},
    'settings': {'trials': args.trials, 'duration': args.duration},
    'samples': [],
}
try:
    with tempfile.TemporaryDirectory(prefix='autolink-precheck-bench-') as tmp:
        tmp = pathlib.Path(tmp)
        (tmp / 'before.go').write_bytes(before)
        overlay = tmp / 'overlay.json'
        overlay.write_text(json.dumps({'Replace': {str(source): str(tmp / 'before.go')}}))
        for trial in range(args.trials):
            for variant in (['before', 'after'] if trial % 2 == 0 else ['after', 'before']):
                command = ['go', 'test'] + (['-overlay', str(overlay)] if variant == 'before' else [])
                command += ['./channels/app', '-run', '^$', '-bench', '^(BenchmarkFirstAutolinkPrecheck|BenchmarkAutolinkPrecheckHistory)$', '-benchtime', args.duration, '-count=1', '-timeout=10m', '-json']
                proc = subprocess.run(command, cwd=server, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=900)
                passed = False
                records = []
                for line in proc.stdout.splitlines():
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    passed |= event.get('Action') == 'pass' and not event.get('Test')
                    output = event.get('Output', '').strip()
                    match = re.match(r'(Benchmark(?:FirstAutolinkPrecheck|AutolinkPrecheckHistory)/.+)-\d+\s+(\d+)\s+([\d.]+) ns/op\s+([\d.]+) B/op\s+([\d.]+) allocs/op$', output)
                    if match:
                        name, iterations, ns, allocated, allocations = match.groups()
                        records.append({'name': name, 'iterations': int(iterations), 'ns_per_op': float(ns), 'bytes_per_op': float(allocated), 'allocations_per_op': float(allocations), 'raw': output})
                if proc.returncode or not passed or sorted(r['name'] for r in records) != sorted(expected):
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
