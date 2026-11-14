#!/usr/bin/env python3
"""Compare team-thread unread aggregation with the original production file."""
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
    relative = 'server/channels/store/sqlstore/thread_store.go'
    before = git('show', baseline + ':' + relative)
    after = (workspace / relative).read_bytes()

    def outside_method(data):
        start = data.index(b'func (s *SqlThreadStore) GetTeamsUnreadForUser(')
        end = data.index(b'\nfunc ', start + 10)
        return data[:start] + data[end:]

    assert outside_method(before).replace(b'\t"golang.org/x/sync/errgroup"\n', b'') == outside_method(after), 'unrelated production changes'
    env = os.environ.copy()
    env.setdefault('GOMAXPROCS', '4')
    samples, commands = [], []
    pattern = re.compile(r'^(Benchmark\S+)-\d+\s+(\d+)\s+([\d.]+) ns/op\s+(\d+) B/op\s+(\d+) allocs/op$', re.M)
    with tempfile.TemporaryDirectory(prefix='team-thread-unreads-baseline-') as directory:
        directory = Path(directory)
        old_file = directory / 'thread_store.go'
        old_file.write_bytes(before)
        overlay = directory / 'overlay.json'
        overlay.write_text(json.dumps({'Replace': {str(workspace / relative): str(old_file)}}))
        for trial in range(args.trials):
            for variant in (['before', 'after'] if trial % 2 == 0 else ['after', 'before']):
                cmd = ['go', 'test', './channels/store/sqlstore', '-run', '^$', '-bench', '^BenchmarkTeamThreadUnreadAggregation$', '-benchtime=' + str(args.iterations) + 'x', '-count=1', '-timeout=10m']
                if variant == 'before':
                    cmd.extend(['-overlay', str(overlay)])
                log = output.parent / ('team-thread-unreads-' + str(trial) + '-' + variant + '.log')
                with log.open('w') as stream:
                    subprocess.run(cmd, cwd=workspace / 'server', env=env, stdout=stream, stderr=subprocess.STDOUT, check=True)
                matches = pattern.findall(log.read_text())
                assert len(matches) == 12, (log, len(matches))
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
    result = {'scope': 'Standalone contribution over the original 38-patch baseline. Three alternating-order pairs by default; fixed iteration counts and identical fixtures/output checks.', 'source_workspace_sha': source, 'source_tree_sha': git('rev-parse', 'HEAD^{tree}').decode().strip(), 'baseline_source_sha': baseline, 'production_file': relative, 'before_sha256': hashlib.sha256(before).hexdigest(), 'after_sha256': hashlib.sha256(after).hexdigest(), 'go_version': subprocess.check_output(['go', 'version'], text=True).strip(), 'platform': platform.platform(), 'GOMAXPROCS': env['GOMAXPROCS'], 'database_pool': {'max_open': 8, 'max_idle': 8, 'one_pool_for_reads_and_writes': True}, 'parallel_workers': 'GOMAXPROCS, testing.B.RunParallel default parallelism', 'trials': args.trials, 'iterations': args.iterations, 'rows': rows, 'samples': samples, 'commands': commands, 'limits': ['SQL store method on loopback PostgreSQL, not complete HTTP endpoint latency or production capacity.', 'Parallel ns/op is amortized wall time per completed operation, not per-request latency.', 'Fixture creation is outside timing; every operation checks map shape and all count fields.', 'These are standalone measurements, not combined-stack throughput.']}
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(output, flush=True)


if __name__ == '__main__':
    main()
