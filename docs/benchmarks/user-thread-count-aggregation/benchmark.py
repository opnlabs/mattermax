#!/usr/bin/env python3
"""Compare user-thread response count aggregation with the original production file."""
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
    parser.add_argument('--iterations', type=int, default=1000)
    parser.add_argument('--trials', type=int, default=3)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--isolated', action='store_true', help='Run each 1000-thread, priority-enabled serial response mode in a separate process.')
    args = parser.parse_args()
    if min(args.iterations, args.trials) < 1:
        parser.error('iterations and trials must be positive')
    workspace = args.workspace.resolve()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    def git(*parts):
        return subprocess.check_output(['git', *parts], cwd=workspace)

    source = git('rev-parse', 'HEAD').decode().strip()
    baseline = git('rev-parse', args.baseline).decode().strip()
    relative = 'server/channels/app/user.go'
    before = git('show', baseline + ':' + relative)
    after = (workspace / relative).read_bytes()

    def outside_method(data):
        start = data.index(b'func (a *App) GetThreadsForUser(')
        end = data.index(b'\nfunc ', start + 10)
        return data[:start] + data[end:]

    assert outside_method(before) == outside_method(after), 'unrelated production changes'
    env = os.environ.copy()
    env.setdefault('GOMAXPROCS', '4')
    samples, commands = [], []
    pattern = re.compile(r'^(Benchmark\S+)-\d+\s+(\d+)\s+([\d.]+) ns/op\s+(\d+) B/op\s+(\d+) allocs/op$', re.M)
    with tempfile.TemporaryDirectory(prefix='user-thread-counts-baseline-') as directory:
        directory = Path(directory)
        old_file = directory / 'user.go'
        old_file.write_bytes(before)
        overlay = directory / 'overlay.json'
        overlay.write_text(json.dumps({'Replace': {str(workspace / relative): str(old_file)}}))
        cases = [('matrix', '^BenchmarkUserThreadCountsHistory$', 24)]
        if args.isolated:
            cases = [(mode, '^BenchmarkUserThreadCountsHistory$/^priority=true$/^threads=1000$/^' + mode + '$/^serial$', 1) for mode in ['threads_only', 'totals', 'page']]
        for case, selector, expected_cases in cases:
            for trial in range(args.trials):
                for variant in (['before', 'after'] if trial % 2 == 0 else ['after', 'before']):
                    cmd = ['go', 'test', './channels/app', '-run', '^$', '-bench', selector, '-benchtime=' + str(args.iterations) + 'x', '-count=1', '-timeout=10m']
                    if variant == 'before':
                        cmd.extend(['-overlay', str(overlay)])
                    log = output.parent / ('user-thread-counts-' + case + '-' + str(trial) + '-' + variant + '.log')
                    with log.open('w') as stream:
                        subprocess.run(cmd, cwd=workspace / 'server', env=env, stdout=stream, stderr=subprocess.STDOUT, check=True)
                    matches = pattern.findall(log.read_text())
                    assert len(matches) == expected_cases, (log, len(matches))
                    for name, iterations, ns, size, allocations in matches:
                        assert int(iterations) == args.iterations
                        samples.append({'trial': trial, 'variant': variant, 'name': name, 'iterations': int(iterations), 'ns/op': float(ns), 'B/op': int(size), 'allocs/op': int(allocations)})
                    commands.append({'trial': trial, 'variant': variant, 'command': cmd, 'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()})
                    print(trial, variant, 'passed', flush=True)
    rows = []
    for name in sorted({sample['name'] for sample in samples}):
        row = {'name': name}
        for variant in ['before', 'after']:
            selected = [sample for sample in samples if sample['name'] == name and sample['variant'] == variant]
            assert len(selected) == args.trials
            row[variant] = {key: {'median': statistics.median(sample[key] for sample in selected), 'min': min(sample[key] for sample in selected), 'max': max(sample[key] for sample in selected)} for key in ['ns/op', 'B/op', 'allocs/op']}
        rows.append(row)
    result = {'scope': 'Independent contribution over the original 38-patch baseline. Baseline restores only the old App dispatch path; the added internal store method remains compiled but unused by that path. Identical fixtures and other production code; alternating-order process pairs and fixed iteration counts.', 'source_workspace_sha': source, 'source_tree_sha': git('rev-parse', 'HEAD^{tree}').decode().strip(), 'baseline_source_sha': baseline, 'production_file': relative, 'before_sha256': hashlib.sha256(before).hexdigest(), 'after_sha256': hashlib.sha256(after).hexdigest(), 'go_version': subprocess.check_output(['go', 'version'], text=True).strip(), 'platform': platform.platform(), 'GOMAXPROCS': env['GOMAXPROCS'], 'database_pool': {'max_open': 8, 'max_idle': 8, 'one_pool_for_reads_and_writes': True}, 'parallel_workers': 'GOMAXPROCS, testing.B.RunParallel default parallelism', 'isolated_modes': args.isolated, 'trials': args.trials, 'iterations': args.iterations, 'rows': rows, 'samples': samples, 'commands': commands, 'limits': ['App method on loopback PostgreSQL, not complete HTTP endpoint latency or production capacity.', 'Parallel ns/op is amortized wall time per completed operation, not per-request latency.', 'Real users, memberships, root posts and replies are created outside timing. Every operation checks all count fields and returned page data; threads-only controls exercise the unchanged no-count path.', 'These are standalone measurements, not combined-stack throughput.']}
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(output, flush=True)


if __name__ == '__main__':
    main()
