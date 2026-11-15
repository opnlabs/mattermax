#!/usr/bin/env python3
"""Summarize all HTTP pairs without dropping slower samples."""
import argparse
import json
from pathlib import Path
import statistics

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('report', type=Path)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
report = json.loads(args.report.read_text())
assert report['status'] == 'passed'
runs = report['runs']
assert len(runs) == 2 * report['trials']
assert all(r['status'] == 'passed' and r['regular_member'] and
           r['persistent_connection_verified'] and r['database_removed'] and
           r['server_stopped'] and r['runtime_directory_removed'] for r in runs)
assert len({json.dumps(r['normalized_response_sha256'], sort_keys=True)
            for r in runs}) == 1
cases = []
for name in ['all', 'empty', 'priority', 'acknowledgements', 'mixed', 'dense']:
    samples = {}
    for variant in ['before', 'after']:
        variant_runs = sorted((r for r in runs if r['variant'] == variant),
                              key=lambda r: r['trial'])
        assert [r['trial'] for r in variant_runs] == list(range(report['trials']))
        samples[variant] = [r['mean_latency_ns'] if name == 'all' else
                            statistics.mean(r['latencies_ns'][name])
                            for r in variant_runs]
    before, after = samples['before'], samples['after']
    cases.append(dict(name=name, before_mean_ns=before, after_mean_ns=after,
                      before_median_ns=statistics.median(before),
                      after_median_ns=statistics.median(after),
                      median_change_percent=100 * (statistics.median(after) /
                                                   statistics.median(before) - 1),
                      paired_change_percent=[100 * (a / b - 1)
                                             for a, b in zip(after, before)]))
summary = dict(status='passed', priority_enabled=report['priority_enabled'],
               source_sha=report['source_sha'], trials=report['trials'],
               requests=sum(len(v) for r in runs for v in r['latencies_ns'].values()),
               scope=report['scope'], cases=cases)
args.output.write_text(json.dumps(summary, indent=2) + '\n')
