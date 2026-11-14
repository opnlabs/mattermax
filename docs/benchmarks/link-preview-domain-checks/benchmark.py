#!/usr/bin/env python3
"""Compare link-preview domain checks with only post_metadata.go overlaid."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import statistics
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--baseline', default='HEAD^')
    parser.add_argument('--trials', type=int, default=3)
    parser.add_argument('--check-iterations', type=int, default=100000)
    parser.add_argument('--history-iterations', type=int, default=1000)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--benchmarks', choices=['all', 'history'], default='all')
    args = parser.parse_args()
    if min(args.trials, args.check_iterations, args.history_iterations) < 1:
        parser.error('trial and iteration counts must be positive')
    workspace = args.workspace.resolve()
    server = workspace / 'server'
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    def git(*parts):
        return subprocess.check_output(['git', *parts], cwd=workspace)

    source_sha = git('rev-parse', 'HEAD').decode().strip()
    baseline_sha = git('rev-parse', args.baseline).decode().strip()
    relative = 'server/channels/app/post_metadata.go'
    before = git('show', baseline_sha + ':' + relative)
    after = (workspace / relative).read_bytes()
    def outside_check(data):
        start = data.index(b'func (a *App) isLinkAllowedForPreview')
        end = data.index(b'\nfunc normalizeDomains', start)
        return data[:start] + data[end:]
    assert outside_check(before) == outside_check(after), 'production changes outside the domain check'
    env = os.environ.copy()
    env.setdefault('GOMAXPROCS', '4')
    samples = []
    commands = []
    pattern = re.compile(r'^(Benchmark\S+)-\d+\s+(\d+)\s+([\d.]+) ns/op\s+(\d+) B/op\s+(\d+) allocs/op$', re.M)
    with tempfile.TemporaryDirectory(prefix='link-preview-baseline-') as temporary:
        temporary = Path(temporary)
        old_file = temporary / 'post_metadata.go'
        old_file.write_bytes(before)
        overlay = temporary / 'overlay.json'
        overlay.write_text(json.dumps({'Replace': {str(workspace / relative): str(old_file)}}))
        for trial in range(args.trials):
            variants = ['before', 'after'] if trial % 2 == 0 else ['after', 'before']
            for variant in variants:
                for kind, iterations, count in [('Checks', args.check_iterations, 12), ('History', args.history_iterations, 4)]:
                    if args.benchmarks == 'history' and kind != 'History':
                        continue
                    cmd = ['go', 'test', './channels/app', '-run', '^$', '-bench', '^BenchmarkLinkPreviewDomain' + kind + '$', '-benchtime=' + str(iterations) + 'x', '-count=1', '-timeout=5m']
                    if variant == 'before':
                        cmd.extend(['-overlay', str(overlay)])
                    log = output.parent / ('link-preview-' + str(trial) + '-' + variant + '-' + kind.lower() + '.log')
                    with log.open('w') as stream:
                        subprocess.run(cmd, cwd=server, env=env, stdout=stream, stderr=subprocess.STDOUT, check=True)
                    matches = pattern.findall(log.read_text())
                    assert len(matches) == count, (log, len(matches))
                    commands.append({'trial': trial, 'variant': variant, 'kind': kind, 'command': cmd, 'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()})
                    for name, n, ns, size, allocs in matches:
                        assert int(n) == iterations
                        samples.append({'trial': trial, 'variant': variant, 'name': name, 'iterations': int(n), 'ns/op': float(ns), 'B/op': int(size), 'allocs/op': int(allocs)})
                    print(trial, variant, kind, 'passed', flush=True)
    rows = []
    for name in sorted({s['name'] for s in samples}):
        row = {'name': name}
        for variant in ['before', 'after']:
            selected = [s for s in samples if s['name'] == name and s['variant'] == variant]
            assert len(selected) == args.trials
            row[variant] = {key: {'median': statistics.median(s[key] for s in selected), 'min': min(s[key] for s in selected), 'max': max(s[key] for s in selected)} for key in ['ns/op', 'B/op', 'allocs/op']}
        rows.append(row)
    report = {'scope': 'Standalone contribution over the original 38-patch baseline. Alternating-order processes with identical fixtures and fixed iterations; output validation is enabled in both variants.', 'source_workspace_sha': source_sha, 'source_tree_sha': git('rev-parse', 'HEAD^{tree}').decode().strip(), 'baseline_source_sha': baseline_sha, 'production_file': relative, 'production_file_before_sha256': hashlib.sha256(before).hexdigest(), 'production_file_after_sha256': hashlib.sha256(after).hexdigest(), 'go_version': subprocess.check_output(['go', 'version'], text=True).strip(), 'platform': platform.platform(), 'GOMAXPROCS': env['GOMAXPROCS'], 'trials': args.trials, 'benchmarks': args.benchmarks, 'commands': commands, 'rows': rows, 'samples': samples, 'limits': ['Local PostgreSQL/Redis. Preview fetching is disabled in history fixtures, which measure filtering and post preparation without external HTTP requests. No concurrent-load or production-capacity measurement.', 'Standalone allocation and timing results are not combined-stack throughput measurements.']}
    output.write_text(json.dumps(report, indent=2) + '\n')
    print(output, flush=True)


if __name__ == '__main__':
    main()
