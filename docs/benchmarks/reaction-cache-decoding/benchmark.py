#!/usr/bin/env python3
"""Compare cache decoding while keeping stored bytes and benchmark fixtures identical."""
import argparse
import hashlib
import json
import pathlib
import platform
import re
import statistics
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--workspace', required=True, type=pathlib.Path)
parser.add_argument('--baseline', default='HEAD^')
parser.add_argument('--suite', choices=['cache', 'history'], required=True)
parser.add_argument('--duration', default='1s')
parser.add_argument('--case', help='Run one exact case, for example posts=1/cold')
parser.add_argument('--trials', type=int, default=3)
parser.add_argument('--output', required=True, type=pathlib.Path)
args = parser.parse_args()
if args.trials < 1:
    parser.error('trials must be positive')
workspace = args.workspace.resolve()
server = workspace / 'server'
relative = 'server/channels/store/localcachelayer/reaction_layer.go'
source = workspace / relative

def git(*command):
    return subprocess.check_output(['git', '-C', str(workspace), *command])

baseline_sha = git('rev-parse', args.baseline).decode().strip()
before = git('show', baseline_sha + ':' + relative)
bench = 'BenchmarkReactionCacheRead' if args.suite == 'cache' else 'BenchmarkReactionHistory'
expected = [f'posts={n}' for n in [1, 60]] if args.suite == 'cache' else [f'posts={n}/{mode}' for n in [1, 10, 60] for mode in ['cold', 'warm']]
if args.case:
    if args.case not in expected:
        parser.error('unknown case for suite')
    expected = [args.case]
selector = '^' + bench + '$' + (''.join('/^' + re.escape(part) + '$' for part in args.case.split('/')) if args.case else '')
package = './channels/store/localcachelayer' if args.suite == 'cache' else './channels/app'
report = {
    'status': 'running', 'suite': args.suite,
    'method': 'Alternating-order paired processes. Go overlay restores only reaction_layer.go for baseline; identical cache writes, SQL, fixtures and output validation in both variants. Cache suite reads populated LRU entries with three reactions per post. History suite uses real stored ordered pages, three standard reactions per post, default priority and acknowledgement reads, and output validation. Cold purges outside the timer. Excludes HTTP and frontend execution.',
    'baseline_workspace_sha': baseline_sha,
    'current_workspace_sha': git('rev-parse', 'HEAD').decode().strip(),
    'source_sha256': {relative: {'before': hashlib.sha256(before).hexdigest(), 'after': hashlib.sha256(source.read_bytes()).hexdigest()}},
    'environment': {'platform': platform.platform(), 'go': subprocess.check_output(['go', 'version']).decode().strip(), 'cpu': next((x.split(':', 1)[1].strip() for x in pathlib.Path('/proc/cpuinfo').read_text().splitlines() if x.startswith('model name')), 'unknown')},
    'settings': {'trials': args.trials, 'duration': args.duration, 'package': package, 'benchmark': bench, 'case': args.case},
    'samples': [],
}
for name in ['server/channels/store/localcachelayer/reaction_cache.go', 'server/channels/store/localcachelayer/reaction_cache_test.go', 'server/channels/app/post_reaction_batch_test.go']:
    report['source_sha256'][name] = hashlib.sha256((workspace / name).read_bytes()).hexdigest()
try:
    with tempfile.TemporaryDirectory(prefix='reaction-codec-bench-') as tmp:
        tmp = pathlib.Path(tmp)
        (tmp / 'before.go').write_bytes(before)
        overlay = tmp / 'overlay.json'
        overlay.write_text(json.dumps({'Replace': {str(source): str(tmp / 'before.go')}}))
        for trial in range(args.trials):
            for variant in (['before', 'after'] if trial % 2 == 0 else ['after', 'before']):
                command = ['go', 'test'] + (['-overlay', str(overlay)] if variant == 'before' else [])
                command += [package, '-run', '^$', '-bench', selector, '-benchtime', args.duration, '-count=1', '-timeout=10m', '-json']
                proc = subprocess.run(command, cwd=server, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=900)
                records = []
                passed = False
                for line in proc.stdout.splitlines():
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    passed |= event.get('Action') == 'pass' and not event.get('Test')
                    output = event.get('Output', '').strip()
                    match = re.match(bench + r'/(.+)-\d+\s+(\d+)\s+([\d.]+) ns/op\s+([\d.]+) B/op\s+([\d.]+) allocs/op$', output)
                    if match:
                        name, iterations, ns, allocated, allocations = match.groups()
                        records.append({'name': name, 'iterations': int(iterations), 'ns_per_op': float(ns), 'bytes_per_op': float(allocated), 'allocations_per_op': float(allocations), 'raw': output})
                if proc.returncode or not passed or sorted(r['name'] for r in records) != sorted(expected):
                    raise RuntimeError(f'{variant} trial {trial} failed or omitted cases: ' + proc.stdout[-10000:])
                report['samples'].append({'trial': trial, 'variant': variant, 'benchmarks': records})
                print(variant, trial, [(r['name'], r['ns_per_op']) for r in records], flush=True)
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
