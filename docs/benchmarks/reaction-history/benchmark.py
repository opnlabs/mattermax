#!/usr/bin/env python3
"""Compare reaction history preparation with per-post reads restored by Go overlay."""
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
parser.add_argument('--workspace', type=pathlib.Path, required=True, help='Mattermax work/src')
parser.add_argument('--baseline', default='HEAD^', help='Workspace revision before reaction batching')
parser.add_argument('--iterations', type=int, default=300)
parser.add_argument('--bench', default='^BenchmarkReactionHistory$', help='Go benchmark selector')
parser.add_argument('--duration', help='Go benchmark duration, for example 1s; overrides iterations')
parser.add_argument('--trials', type=int, default=3)
parser.add_argument('--output', type=pathlib.Path, required=True)
args = parser.parse_args()
if min(args.iterations, args.trials) < 1:
    parser.error('iterations and trials must be positive')
workspace = args.workspace.resolve()
server = workspace / 'server'
relative = 'server/channels/app/post_metadata.go'
source = workspace / relative

def git(*command):
    return subprocess.check_output(['git', '-C', str(workspace), *command])

baseline_sha = git('rev-parse', args.baseline).decode().strip()
baseline = git('show', baseline_sha+':'+relative)
report = {
    'status': 'running',
    'method': 'Real App.PreparePostListForClient with SQL/cache setup, three standard emoji reactions per post, one/ten/sixty posts. Baseline restores only post_metadata.go through Go overlay; both variants retain the same store code and benchmark. Cold purges local store caches outside the timer; warm uses populated caches. Timed loops include preparation, SQL/cache fills or reads, and output validation. Excludes HTTP, files, custom emoji and remote links. Alternating-order paired processes. Ordered PostLists include default priority and acknowledgement queries; returned order length is validated.',
    'baseline_workspace_sha': baseline_sha,
    'current_workspace_sha': git('rev-parse', 'HEAD').decode().strip(),
    'source_sha256': {'before': hashlib.sha256(baseline).hexdigest(), 'after': hashlib.sha256(source.read_bytes()).hexdigest(), 'store': hashlib.sha256((server/'channels/store/sqlstore/reaction_store.go').read_bytes()).hexdigest(), 'cache': hashlib.sha256((server/'channels/store/localcachelayer/reaction_layer.go').read_bytes()).hexdigest(), 'benchmark_test': hashlib.sha256(source.with_name('post_reaction_batch_test.go').read_bytes()).hexdigest()},
    'environment': {'platform': platform.platform(), 'go': subprocess.check_output(['go', 'version']).decode().strip(), 'cpu': next((line.split(':', 1)[1].strip() for line in pathlib.Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')), 'unknown')},
    'settings': {'trials': args.trials, 'iterations': args.iterations, 'duration': args.duration, 'bench': args.bench},
    'samples': [],
}
try:
    with tempfile.TemporaryDirectory(prefix='reaction-history-bench-') as temporary:
        temporary = pathlib.Path(temporary)
        old = temporary/'before.go'
        old.write_bytes(baseline)
        overlay = temporary/'overlay.json'
        overlay.write_text(json.dumps({'Replace': {str(source): str(old)}}))
        for trial in range(args.trials):
            for variant in (['before', 'after'] if trial % 2 == 0 else ['after', 'before']):
                command = ['go', 'test']
                if variant == 'before':
                    command += ['-overlay', str(overlay)]
                command += ['./channels/app', '-run', '^$', '-bench', args.bench, '-benchtime', args.duration or (str(args.iterations)+'x'), '-count=1', '-timeout=10m', '-json']
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
                    match = re.match(r'BenchmarkReactionHistory/posts=(\d+)/(cold|warm)-\d+\s+(\d+)\s+([\d.]+) ns/op\s+([\d.]+) B/op\s+([\d.]+) allocs/op$', output)
                    if match:
                        posts, mode, iterations, ns, allocated, allocations = match.groups()
                        records.append({'posts': int(posts), 'mode': mode, 'iterations': int(iterations), 'ns_per_op': float(ns), 'bytes_per_op': float(allocated), 'allocations_per_op': float(allocations), 'raw': output})
                if process.returncode or not terminal_pass or sorted((r['posts'], r['mode']) for r in records) != ([(1, 'cold')] if args.bench == '^BenchmarkReactionHistory$/^posts=1$/^cold$' else [(n, mode) for n in [1, 10, 60] for mode in ['cold', 'warm']]):
                    raise RuntimeError(f'{variant} trial {trial} failed or has missing benchmarks: '+process.stdout[-10000:])
                report['samples'].append({'trial': trial, 'variant': variant, 'benchmarks': records})
                print(variant, trial, [(r['posts'], r['mode'], r['ns_per_op']) for r in records], flush=True)
    report['summary'] = []
    for posts in ([1] if args.bench == '^BenchmarkReactionHistory$/^posts=1$/^cold$' else [1, 10, 60]):
        for mode in (['cold'] if args.bench == '^BenchmarkReactionHistory$/^posts=1$/^cold$' else ['cold', 'warm']):
            row = {'posts': posts, 'mode': mode}
            for variant in ['before', 'after']:
                selected = [r for s in report['samples'] if s['variant'] == variant for r in s['benchmarks'] if r['posts'] == posts and r['mode'] == mode]
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
