#!/usr/bin/env python3
"""Measure the reply-count projection through the helper and real saves."""
import argparse
import collections
import hashlib
import json
import os
import pathlib
import re
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--workspace', type=pathlib.Path, required=True)
parser.add_argument('--baseline', default='HEAD^')
parser.add_argument('--iterations', type=int, default=200)
parser.add_argument('--trials', type=int, default=3)
parser.add_argument('--bench', default='^BenchmarkReplyCountProjection$')
parser.add_argument('--expected-cases', type=int, default=36)
parser.add_argument('--output', type=pathlib.Path, required=True)
args = parser.parse_args()
if min(args.iterations, args.trials, args.expected_cases) < 1:
    parser.error('iterations, trials and expected cases must be positive')
env = dict(os.environ, GOFLAGS='-p=2', GOMAXPROCS='4')
if not env.get('TEST_DATABASE_POSTGRESQL_DSN'):
    parser.error('Set TEST_DATABASE_POSTGRESQL_DSN to a disposable PostgreSQL test service')
workspace = args.workspace.resolve()
args.output.parent.mkdir(parents=True, exist_ok=True)
run = args.output.parent.resolve()
target = workspace / 'channels/store/sqlstore/post_store.go'
baseline = run / 'baseline-post-store.go'
baseline.write_bytes(subprocess.check_output(['git', 'show', args.baseline + ':server/channels/store/sqlstore/post_store.go'], cwd=workspace))
overlay = run / 'baseline-overlay.json'
overlay.write_text(json.dumps({'Replace': {str(target): str(baseline)}}))
report = {
    'status': 'running', 'iterations': args.iterations, 'trials': args.trials,
    'benchmark_filter': args.bench, 'expected_cases': args.expected_cases,
    'source_sha': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=workspace, text=True).strip(),
    'source_tree_sha': subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=workspace, text=True).strip(),
    'production_file_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
    'baseline_file_sha256': hashlib.sha256(baseline.read_bytes()).hexdigest(),
    'benchmark_file_sha256': hashlib.sha256((workspace / 'channels/store/sqlstore/reply_count_projection_benchmark_test.go').read_bytes()).hexdigest(),
    'runner_sha256': hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
    'go_version': subprocess.check_output(['go', 'version'], cwd=workspace, env=env, text=True).strip(),
    'gomaxprocs': 4, 'samples': [],
    'scope': 'Serial SQL-store operations on fresh databases. The baseline overlay restores only the original production file; fixtures, indexes and validation are shared. Populate is read-only. Save writes one reply per root per operation and its history grows equally in both variants. Roots=1 uses Save; roots=10 uses SaveMultiple. Root controls save a root without executing the changed query. Seeding, visibility setup, plans and cleanup are untimed. Not HTTP latency or production capacity.'
}
try:
    for trial in range(args.trials):
        for variant in (('before', 'after') if trial % 2 == 0 else ('after', 'before')):
            command = ['go', 'test', '-p', '1', './channels/store/sqlstore', '-run', '^$', '-bench', args.bench, '-benchtime', str(args.iterations) + 'x', '-count=1', '-timeout=20m', '-json']
            if variant == 'before':
                command += ['-overlay', str(overlay)]
            log = run / (str(trial) + '-' + variant + '.jsonl')
            with log.open('w') as output:
                subprocess.run(command, cwd=workspace, env=dict(env, MATTERMAX_REPLY_COUNT_VARIANT=variant), stdout=output, stderr=subprocess.STDOUT, check=True)
            events = [json.loads(line) for line in log.read_text().splitlines() if line.startswith('{')]
            ends = [e for e in events if not e.get('Test') and e['Action'] in ('pass', 'fail')]
            assert len(ends) == 1 and ends[0]['Action'] == 'pass'
            assert not any(e['Action'] in ('fail', 'skip') for e in events)
            output = collections.defaultdict(str)
            for event in events:
                output[event.get('Package'), event.get('Test')] += event.get('Output', '')
            rows, plans, indexes = [], [], []
            for (_, test), value in output.items():
                for match in re.finditer(r'^(Benchmark\S+)-\d+\s+(\d+)\s+([\d.]+) ns/op\s+([\d.]+) B/op\s+([\d.]+) allocs/op', value, re.M):
                    rows.append({'name': match[1], 'iterations': int(match[2]), 'ns_op': float(match[3]), 'bytes_op': float(match[4]), 'allocs_op': float(match[5])})
                for match in re.finditer(r'reply_count_plan (before|after) (populate|save|root_control):\s*', value):
                    plan, _ = json.JSONDecoder().raw_decode(value[match.end():])
                    plans.append({'test': test, 'stage': match[1], 'method': match[2], 'plan': plan})
                for match in re.finditer(r'reply_count_indexes:\s*', value):
                    definitions, _ = json.JSONDecoder().raw_decode(value[match.end():])
                    indexes.append(definitions)
            assert len(rows) == args.expected_cases, (len(rows), args.expected_cases)
            assert len({r['name'] for r in rows}) == args.expected_cases
            assert plans and indexes
            report['samples'].append({'trial': trial, 'variant': variant, 'command': command, 'benchmarks': rows, 'plans': plans, 'indexes': indexes, 'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()})
            print(trial, variant, 'passed', len(rows), flush=True)
    assert len({json.dumps(i, sort_keys=True) for s in report['samples'] for i in s['indexes']}) == 1, 'Index definitions differ across variants'
    report['status'] = 'passed'
except Exception as error:
    report['status'] = 'failed'
    report['error'] = str(error)
    raise
finally:
    args.output.write_text(json.dumps(report, indent=2) + '\n')
