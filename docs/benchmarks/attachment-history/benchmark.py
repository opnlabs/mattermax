#!/usr/bin/env python3
"""Compare ordered attachment history against the parent preparation code."""
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
relatives = ['server/channels/app/post_metadata.go', 'server/channels/app/post.go']
cases = [(posts, files, mode) for posts, files in [(1, 2), (10, 2), (60, 2), (60, 0)] for mode in ['cold', 'warm']]


def git(*command):
    return subprocess.check_output(['git', '-C', str(workspace), *command])


baseline_sha = git('rev-parse', args.baseline).decode().strip()
baselines = {relative: git('show', baseline_sha + ':' + relative) for relative in relatives}
report = {
    'status': 'running',
    'method': 'Real ordered App.PreparePostListForClient with default priority/acknowledgement reads, stored text attachments, and attachment order/output validation. Cases cover one/ten/sixty posts with two files each, plus sixty posts without files. Cold purges only file caches outside the timer; warm uses populated caches. PostgreSQL buffers are not reset. Baseline restores parent post.go and post_metadata.go through Go overlay; the new helper file and all tests are compiled identically but the baseline preparation path does not use that helper. Excludes HTTP, file bytes, image processing and remote links. Alternating paired processes.',
    'baseline_workspace_sha': baseline_sha,
    'current_workspace_sha': git('rev-parse', 'HEAD').decode().strip(),
    'source_sha256': {relative: {'before': hashlib.sha256(baselines[relative]).hexdigest(), 'after': hashlib.sha256((workspace / relative).read_bytes()).hexdigest()} for relative in relatives},
    'helper_sha256': hashlib.sha256((server / 'channels/app/post_file_metadata.go').read_bytes()).hexdigest(),
    'benchmark_test_sha256': hashlib.sha256((server / 'channels/app/attachment_history_test.go').read_bytes()).hexdigest(),
    'environment': {'platform': platform.platform(), 'go': subprocess.check_output(['go', 'version']).decode().strip(), 'cpu': next((line.split(':', 1)[1].strip() for line in pathlib.Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')), 'unknown')},
    'settings': {'trials': args.trials, 'duration': args.duration, 'ordered_history': True},
    'samples': [],
}
try:
    with tempfile.TemporaryDirectory(prefix='attachment-history-benchmark-') as temporary:
        temporary = pathlib.Path(temporary)
        replacements = {}
        for index, relative in enumerate(relatives):
            old = temporary / (str(index) + '.go')
            old.write_bytes(baselines[relative])
            replacements[str(workspace / relative)] = str(old)
        overlay = temporary / 'overlay.json'
        overlay.write_text(json.dumps({'Replace': replacements}))
        for trial in range(args.trials):
            for variant in (['before', 'after'] if trial % 2 == 0 else ['after', 'before']):
                command = ['go', 'test']
                if variant == 'before':
                    command += ['-overlay', str(overlay)]
                command += ['./channels/app', '-run', '^$', '-bench', '^BenchmarkAttachmentHistory$', '-benchtime', args.duration, '-count=1', '-timeout=10m', '-json']
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
                    match = re.match(r'BenchmarkAttachmentHistory/posts=(\d+)/files=(\d+)/(cold|warm)-\d+\s+(\d+)\s+([\d.]+) ns/op\s+([\d.]+) B/op\s+([\d.]+) allocs/op$', output)
                    if match:
                        posts, files, mode, iterations, ns, allocated, allocations = match.groups()
                        records.append({'posts': int(posts), 'files_per_post': int(files), 'mode': mode, 'iterations': int(iterations), 'ns_per_op': float(ns), 'bytes_per_op': float(allocated), 'allocations_per_op': float(allocations), 'raw': output})
                if process.returncode or not passed or sorted((r['posts'], r['files_per_post'], r['mode']) for r in records) != sorted(cases):
                    raise RuntimeError(f'{variant} trial {trial} failed: ' + process.stdout[-14000:])
                report['samples'].append({'trial': trial, 'variant': variant, 'benchmarks': records})
                print(variant, trial, [(r['posts'], r['files_per_post'], r['mode'], r['ns_per_op']) for r in records], flush=True)
    report['summary'] = []
    for posts, files, mode in cases:
        row = {'posts': posts, 'files_per_post': files, 'mode': mode}
        for variant in ['before', 'after']:
            selected = [r for sample in report['samples'] if sample['variant'] == variant for r in sample['benchmarks'] if (r['posts'], r['files_per_post'], r['mode']) == (posts, files, mode)]
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
