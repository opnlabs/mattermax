#!/usr/bin/env python3
"""Compare preview dispatch in real post preparation with a Go source overlay."""
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
parser.add_argument('--baseline', default='HEAD^', help='Workspace revision before the preview-dispatch patch')
parser.add_argument('--iterations', type=int, default=1000)
parser.add_argument('--trials', type=int, default=3)
parser.add_argument('--benchtime', help='Duration such as 1s, overriding fixed iterations')
parser.add_argument('--mode', choices=['all', 'warm', 'master'], default='all')
parser.add_argument('--output', type=pathlib.Path, required=True)
args = parser.parse_args()
if min(args.iterations, args.trials) < 1:
    parser.error('iterations and trials must be positive')
if args.benchtime:
    duration = re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)(ns|us|ms|s|m|h)', args.benchtime)
    if not duration or float(duration.group(1)) <= 0:
        parser.error('benchtime must be a positive Go duration such as 1s')

workspace = args.workspace.resolve()
server = workspace / 'server'
relative = 'server/channels/app/file.go'
source = workspace / relative

def git(*command):
    return subprocess.check_output(['git', '-C', str(workspace), *command])

baseline_sha = git('rev-parse', args.baseline).decode().strip()
baseline = git('show', baseline_sha+':'+relative)
report = {
    'status': 'running',
    'method': 'Real App.PreparePostForClientWithEmbedsAndImages with full test SQL store/cache setup. Original file.go through Go overlay versus dispatch only for files needing a mini-preview. Text files and PNG FileInfo rows with an existing JPEG mini-preview; zero/one/ten files, warm cached reads and master reads selected by IsNewPost. Both baseline post-metadata passes remain unchanged. Timed loops include app/store/driver work but exclude HTTP, upload bytes, image decoding and remote link fetching. Three alternating-order paired processes by default.',
    'baseline_workspace_sha': baseline_sha,
    'current_workspace_sha': git('rev-parse', 'HEAD').decode().strip(),
    'source_sha256': {'before': hashlib.sha256(baseline).hexdigest(), 'after': hashlib.sha256(source.read_bytes()).hexdigest(), 'benchmark_test': hashlib.sha256(source.with_name('file_mini_preview_test.go').read_bytes()).hexdigest()},
    'environment': {'platform': platform.platform(), 'go': subprocess.check_output(['go', 'version']).decode().strip(), 'cpu': next((line.split(':', 1)[1].strip() for line in pathlib.Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')), 'unknown')},
    'settings': {'trials': args.trials, 'iterations': None if args.benchtime else args.iterations, 'benchtime': args.benchtime or str(args.iterations)+'x', 'mode': args.mode},
    'unchanged_post_metadata_sha256': hashlib.sha256((server/'channels/app/post_metadata.go').read_bytes()).hexdigest(),
    'samples': [],
}
try:
    with tempfile.TemporaryDirectory(prefix='mini-preview-bench-') as temporary:
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
                pattern = '^BenchmarkMiniPreviewPostPreparation$'
                if args.mode != 'all':
                    pattern += '/^(text|ready_image)$/^files=(0|1|10)$/^'+args.mode+'$'
                command += ['./channels/app', '-run', '^$', '-bench', pattern, '-benchtime', args.benchtime or str(args.iterations)+'x', '-count=1', '-timeout=10m', '-json']
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
                    match = re.match(r'BenchmarkMiniPreviewPostPreparation/(text|ready_image)/files=(\d+)/(warm|master)-\d+\s+(\d+)\s+([\d.]+) ns/op\s+([\d.]+) B/op\s+([\d.]+) allocs/op$', output)
                    if match:
                        kind, files, mode, iterations, ns, allocated, allocations = match.groups()
                        records.append({'kind': kind, 'files': int(files), 'mode': mode, 'iterations': int(iterations), 'ns_per_op': float(ns), 'bytes_per_op': float(allocated), 'allocations_per_op': float(allocations), 'raw': output})
                if process.returncode or not terminal_pass or sorted((r['kind'], r['files'], r['mode']) for r in records) != sorted((kind, n, mode) for kind in ['text', 'ready_image'] for n in [0, 1, 10] for mode in (['master', 'warm'] if args.mode == 'all' else [args.mode])):
                    raise RuntimeError(f'{variant} trial {trial} failed or has missing benchmarks: '+process.stdout[-10000:])
                report['samples'].append({'trial': trial, 'variant': variant, 'benchmarks': records})
                print(variant, trial, [(r['kind'], r['files'], r['mode'], r['ns_per_op']) for r in records], flush=True)
    report['summary'] = []
    for kind in ['text', 'ready_image']:
        for files in [0, 1, 10]:
            for mode in (['warm', 'master'] if args.mode == 'all' else [args.mode]):
                row = {'kind': kind, 'files': files, 'mode': mode}
                for variant in ['before', 'after']:
                    selected = [r for s in report['samples'] if s['variant'] == variant for r in s['benchmarks'] if r['kind'] == kind and r['files'] == files and r['mode'] == mode]
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
