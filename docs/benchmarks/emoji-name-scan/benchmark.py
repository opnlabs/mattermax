#!/usr/bin/env python3
"""Measure identical helper/history fixtures with the old regex and new scanner."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--trials', type=int, default=3)
parser.add_argument('--history-iterations', type=int, default=300)
args = parser.parse_args()
repo = Path(__file__).resolve().parents[3]
src = repo / 'work/src/server'
args.output.mkdir(parents=True, exist_ok=True)
production = src / 'channels/app/post_metadata.go'
test = src / 'channels/app/emoji_name_scan_test.go'
def git(*argv):
    return subprocess.check_output(['git', *argv], cwd=src)
def digest(data):
    return hashlib.sha256(data).hexdigest()
sha = git('rev-parse', 'HEAD').decode().strip()
baseline_sha = git('rev-parse', 'HEAD^').decode().strip()
assert git('rev-parse', 'HEAD^^{tree}').decode().strip() == 'a2da7f25de10aadbb8974f5f6191aa082ec6e6e6'
baseline = git('show', baseline_sha + ':server/channels/app/post_metadata.go')
assert git('diff', '--name-only', baseline_sha, 'HEAD').decode().splitlines() == [
    'server/channels/app/emoji_name_scan_mixed_test.go',
    'server/channels/app/emoji_name_scan_test.go', 'server/channels/app/post_metadata.go']
assert production.read_bytes() == git('show', 'HEAD:server/channels/app/post_metadata.go')
assert test.read_bytes() == git('show', 'HEAD:server/channels/app/emoji_name_scan_test.go')
assert (src / 'channels/app/emoji_name_scan_mixed_test.go').read_bytes() == git('show', 'HEAD:server/channels/app/emoji_name_scan_mixed_test.go')
env = os.environ.copy()
env.update(TZ='UTC', GOMAXPROCS='4')
result = {'status': 'running', 'source_sha': sha,
          'source_tree_sha': git('rev-parse', 'HEAD^{tree}').decode().strip(),
          'baseline_source_sha': baseline_sha,
          'production_file_sha256': digest(production.read_bytes()),
          'baseline_file_sha256': digest(baseline), 'benchmark_file_sha256': digest(test.read_bytes()),
          'runner_sha256': digest(Path(__file__).read_bytes()),
          'go_version': subprocess.check_output(['go', 'version'], env=env, text=True).strip(),
          'trials': args.trials, 'history_iterations': args.history_iterations,
          'gomaxprocs': 4, 'samples': [],
          'scope': 'Standalone change over the original 38-patch source. Ordered stored history pages with warm emoji caches and priority reads enabled. No reactions, files, image proxy or network previews. Helper timings are not whole-server throughput. Before uses a Go overlay for the original production file; test file is identical.'}
expected = {
    'helper': {'BenchmarkEmojiNameScan/' + n for n in ('plain', 'link', 'emoji', 'long_plain', 'dense', 'invalid')},
    'history': {'BenchmarkEmojiNameScanHistory/' + n + '/posts=' + str(size)
                for n in ('plain', 'system', 'custom', 'dense', 'invalid') for size in (1, 60)}}
pattern = re.compile(r'^(Benchmark\S+)-\d+\s+\d+\s+([\d.]+) ns/op\s+(\d+) B/op\s+(\d+) allocs/op', re.M)
with tempfile.TemporaryDirectory(prefix='mattermax-emoji-scan-') as temporary:
    temp = Path(temporary)
    original = temp / 'post_metadata.go'
    original.write_bytes(baseline)
    overlay = temp / 'overlay.json'
    overlay.write_text(json.dumps({'Replace': {str(production): str(original)}}))
    for trial in range(args.trials):
        for variant in (('before', 'after') if trial % 2 == 0 else ('after', 'before')):
            for group, bench, duration in (
                ('helper', '^BenchmarkEmojiNameScan$', '300ms'),
                ('history', '^BenchmarkEmojiNameScanHistory$', str(args.history_iterations) + 'x')):
                command = ['go', 'test', '-p', '1', './channels/app', '-run', '^$', '-bench', bench,
                           '-benchtime=' + duration, '-count=1', '-timeout=10m', '-json']
                if variant == 'before': command += ['-overlay', str(overlay)]
                log = args.output / (str(trial) + '-' + variant + '-' + group + '.jsonl')
                with log.open('w') as stream:
                    subprocess.run(command, cwd=src, env=env, stdout=stream, stderr=subprocess.STDOUT, check=True)
                events = [json.loads(line) for line in log.read_text().splitlines() if line.startswith('{')]
                assert not any(e['Action'] in ('fail', 'skip') for e in events)
                assert any(e['Action'] == 'pass' and not e.get('Test') for e in events)
                outputs = {}
                for e in events:
                    key = e.get('Test', '')
                    outputs[key] = outputs.get(key, '') + e.get('Output', '')
                cases = [dict(name=m[0], ns_per_op=float(m[1]), bytes_per_op=int(m[2]), allocs_per_op=int(m[3]))
                         for output in outputs.values() for m in pattern.findall(output)]
                assert {c['name'] for c in cases} == expected[group], cases
                assert len(cases) == len(expected[group])
                result['samples'].append(dict(trial=trial, variant=variant, group=group,
                    command=shlex.join(command), benchmarks=cases, raw_log_sha256=digest(log.read_bytes())))
                (args.output / 'results.json').write_text(json.dumps(result, indent=2) + '\n')
                print(trial, variant, group, 'passed', flush=True)
result['status'] = 'passed'
assert production.read_bytes() == git('show', 'HEAD:server/channels/app/post_metadata.go')
(args.output / 'results.json').write_text(json.dumps(result, indent=2) + '\n')
