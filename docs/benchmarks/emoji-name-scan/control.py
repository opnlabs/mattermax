#!/usr/bin/env python3
"""Repeat the single-post plain-text control in alternating isolated processes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
repo = Path(__file__).resolve().parents[3]
src = repo / 'work/src/server'
p = src / 'channels/app/post_metadata.go'
args.output.mkdir(parents=True, exist_ok=True)
env = os.environ.copy()
env.update(TZ='UTC', GOMAXPROCS='4')
sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=src, text=True).strip()
assert subprocess.check_output(['git', 'rev-parse', 'HEAD^^{tree}'], cwd=src, text=True).strip() == 'a2da7f25de10aadbb8974f5f6191aa082ec6e6e6'
original = subprocess.check_output(['git', 'show', 'HEAD^:server/channels/app/post_metadata.go'], cwd=src)
report = dict(status='running', source_sha=sha, iterations=3000, trials=5,
              production_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
              baseline_sha256=hashlib.sha256(original).hexdigest(),
              runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), samples=[])
pattern = re.compile(r'^BenchmarkEmojiNameScanHistory/plain/posts=1-\d+\s+\d+\s+([\d.]+) ns/op\s+(\d+) B/op\s+(\d+) allocs/op', re.M)
with tempfile.TemporaryDirectory(prefix='mattermax-emoji-control-') as temporary:
    t = Path(temporary)
    (t / 'post_metadata.go').write_bytes(original)
    (t / 'overlay.json').write_text(json.dumps({'Replace': {str(p): str(t / 'post_metadata.go')}}))
    for trial in range(5):
        for variant in (('before', 'after') if trial % 2 == 0 else ('after', 'before')):
            cmd = ['go', 'test', '-p', '1', './channels/app', '-run', '^$', '-bench', '^BenchmarkEmojiNameScanHistory/plain/posts=1$', '-benchtime=3000x', '-count=1', '-timeout=5m', '-json']
            if variant == 'before': cmd += ['-overlay', str(t / 'overlay.json')]
            log = args.output / (str(trial) + '-' + variant + '.jsonl')
            with log.open('w') as stream:
                subprocess.run(cmd, cwd=src, env=env, stdout=stream, stderr=subprocess.STDOUT, check=True)
            events = [json.loads(line) for line in log.read_text().splitlines() if line.startswith('{')]
            assert not any(e['Action'] in ('fail', 'skip') for e in events)
            assert any(e['Action'] == 'pass' and not e.get('Test') for e in events)
            output = ''.join(e.get('Output', '') for e in events)
            matches = pattern.findall(output)
            assert len(matches) == 1, matches
            ns, size, allocs = matches[0]
            report['samples'].append(dict(trial=trial, variant=variant, ns_per_op=float(ns), bytes_per_op=int(size), allocs_per_op=int(allocs), command=cmd, raw_log_sha256=hashlib.sha256(log.read_bytes()).hexdigest()))
            (args.output / 'control.json').write_text(json.dumps(report, indent=2) + '\n')
            print(trial, variant, 'passed', flush=True)
report['status'] = 'passed'
(args.output / 'control.json').write_text(json.dumps(report, indent=2) + '\n')
