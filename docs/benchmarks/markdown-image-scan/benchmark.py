#!/usr/bin/env python3
"""Compare real history preparation with and without the image-scan guard."""
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
parser.add_argument('--duration', default='1s')
parser.add_argument('--trials', type=int, default=3)
parser.add_argument('--output', required=True, type=pathlib.Path)
args = parser.parse_args()
if args.trials < 1:
    parser.error('trials must be positive')
workspace = args.workspace.resolve()
server = workspace / 'server'
source = server / 'channels/app/post_metadata.go'
test = source.with_name('post_image_scan_test.go')
cases = ['short', 'prose', 'formatting', 'bang_control', 'inline_image', 'reference_image']


def git(*command):
    return subprocess.check_output(['git', '-C', str(workspace), *command])


baseline_sha = git('rev-parse', args.baseline).decode().strip()
baseline = git('show', baseline_sha + ':server/channels/app/post_metadata.go')
report = {
    'status': 'running',
    'method': 'Real App.PreparePostListForClient over 60 stored posts with default priority/acknowledgement reads. Same benchmark in both variants; baseline restores only post_metadata.go with a Go overlay. Cases use short text, prose, formatting, punctuation and cached inline/reference images. Setup and image warming are outside the timer. Timed loops validate image counts and dimensions. Image cases reject any network fetch during timing. Three alternating-order paired processes by default. Ordered PostLists include default priority and acknowledgement queries; returned order length is validated.',
    'baseline_workspace_sha': baseline_sha,
    'current_workspace_sha': git('rev-parse', 'HEAD').decode().strip(),
    'source_sha256': {'before': hashlib.sha256(baseline).hexdigest(), 'after': hashlib.sha256(source.read_bytes()).hexdigest(), 'benchmark_test': hashlib.sha256(test.read_bytes()).hexdigest()},
    'environment': {'platform': platform.platform(), 'go': subprocess.check_output(['go', 'version']).decode().strip(), 'cpu': next((line.split(':', 1)[1].strip() for line in pathlib.Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')), 'unknown')},
    'settings': {'trials': args.trials, 'duration': args.duration},
    'samples': [],
}
try:
    with tempfile.TemporaryDirectory(prefix='markdown-image-benchmark-') as temporary:
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
                command += ['./channels/app', '-run', '^$', '-bench', '^BenchmarkMarkdownImageHistory$', '-benchtime', args.duration, '-count=1', '-timeout=10m', '-json']
                process = subprocess.run(command, cwd=server, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=900)
                records = []
                passed = False
                for line in process.stdout.splitlines():
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    passed |= event.get('Action') == 'pass' and not event.get('Test')
                    output = event.get('Output', '').strip()
                    match = re.match(r'BenchmarkMarkdownImageHistory/(\w+)-\d+\s+(\d+)\s+([\d.]+) ns/op\s+([\d.]+) B/op\s+([\d.]+) allocs/op$', output)
                    if match:
                        case, iterations, ns, allocated, allocations = match.groups()
                        records.append({'case': case, 'iterations': int(iterations), 'ns_per_op': float(ns), 'bytes_per_op': float(allocated), 'allocations_per_op': float(allocations), 'raw': output})
                if process.returncode or not passed or sorted(r['case'] for r in records) != sorted(cases):
                    raise RuntimeError(f'{variant} trial {trial} failed: ' + process.stdout[-12000:])
                report['samples'].append({'trial': trial, 'variant': variant, 'benchmarks': records})
                print(variant, trial, [(r['case'], r['ns_per_op']) for r in records], flush=True)
    report['summary'] = []
    for case in cases:
        row = {'case': case}
        for variant in ['before', 'after']:
            selected = [r for sample in report['samples'] if sample['variant'] == variant for r in sample['benchmarks'] if r['case'] == case]
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
    args.output.write_text(json.dumps(report, indent=2) + '\n')
