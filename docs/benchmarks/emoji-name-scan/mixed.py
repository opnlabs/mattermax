#!/usr/bin/env python3
"""Measure a balanced shuffled history mix and its process-wide GC counters."""
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
parser.add_argument('--trials', type=int, default=5)
parser.add_argument('--iterations', type=int, default=1000)
args = parser.parse_args()
assert args.iterations >= 5 and args.iterations % 5 == 0
repo = Path(__file__).resolve().parents[3]
src = repo / 'work/src/server'
args.output.mkdir(parents=True, exist_ok=True)
def git(*args): return subprocess.check_output(['git', *args], cwd=src)
def digest(data): return hashlib.sha256(data).hexdigest()
sha = git('rev-parse', 'HEAD').decode().strip()
assert git('rev-parse', 'HEAD^^{tree}').decode().strip() == 'a2da7f25de10aadbb8974f5f6191aa082ec6e6e6'
changed = git('diff', '--name-only', 'HEAD^', 'HEAD').decode().splitlines()
assert changed == ['server/channels/app/emoji_name_scan_mixed_test.go', 'server/channels/app/emoji_name_scan_test.go', 'server/channels/app/post_metadata.go']
for file in changed: assert (src.parent / file).read_bytes() == git('show', 'HEAD:' + file)
production = src / 'channels/app/post_metadata.go'
original = git('show', 'HEAD^:server/channels/app/post_metadata.go')
env = os.environ.copy()
env.update(TZ='UTC', GOMAXPROCS='4', GOGC='100')
report = dict(status='running', source_sha=sha, source_tree_sha=git('rev-parse', 'HEAD^{tree}').decode().strip(),
    production_sha256=digest(production.read_bytes()), baseline_sha256=digest(original),
    fixture_sha256=digest((src/'channels/app/emoji_name_scan_mixed_test.go').read_bytes()),
    runner_sha256=digest(Path(__file__).read_bytes()), iterations=args.iterations, trials=args.trials,
    environment={key:env.get(key) for key in ['GOMAXPROCS', 'GOGC', 'GOMEMLIMIT', 'GODEBUG', 'TZ']},
    go_version=subprocess.check_output(['go', 'version'], text=True).strip(), samples=[],
    scope='Five equally weighted 60-post page types in a deterministic shuffled request sequence. Warm caches, priority reads enabled. GC collected after fixture warming, before timing. Overall ns/op includes output checks; per-page percentiles cover preparation calls only. GC CPU/pause counters include all process work during the loop. Synthetic local workload, not a production or HTTP throughput/tail-latency measurement.')
with tempfile.TemporaryDirectory(prefix='mattermax-emoji-mixed-') as temporary:
    temp = Path(temporary)
    (temp/'post_metadata.go').write_bytes(original)
    (temp/'overlay.json').write_text(json.dumps({'Replace': {str(production):str(temp/'post_metadata.go')}}))
    for trial in range(args.trials):
        for variant in (('before','after') if trial % 2 == 0 else ('after','before')):
            cmd=['go','test','-p','1','./channels/app','-run','^$','-bench','^BenchmarkEmojiNameScanMixedHistory$', '-benchtime='+str(args.iterations)+'x','-count=1','-timeout=10m','-json']
            if variant=='before': cmd += ['-overlay',str(temp/'overlay.json')]
            log=args.output/(str(trial)+'-'+variant+'.jsonl')
            with log.open('w') as stream:
                subprocess.run(cmd,cwd=src,env=env,stdout=stream,stderr=subprocess.STDOUT,check=True)
            events=[json.loads(l)for l in log.read_text().splitlines()if l.startswith('{')]
            assert not any(e['Action']in('fail','skip')for e in events)
            assert any(e['Action']=='pass' and not e.get('Test')for e in events)
            output=''.join(e.get('Output','')for e in events)
            lines=re.findall(r'^BenchmarkEmojiNameScanMixedHistory-\d+\s+\d+\s+.*$',output,re.M)
            assert len(lines)==1,lines
            values={unit:float(value)for value,unit in re.findall(r'([\d.eE+-]+)\s+(\S+)',lines[0].split(None,2)[2])}
            assert all(values[kind+'-pages']==args.iterations/5 for kind in ['plain','system','custom','dense','invalid'])
            assert all(key in values for key in ['ns/op','B/op','allocs/op','gc/op','gc-cpu-ns/op','gc-pause-ns/op','initial-heap-B','final-heap-B'])
            report['samples'].append(dict(trial=trial,variant=variant,metrics=values,command=cmd,raw_log_sha256=digest(log.read_bytes())))
            (args.output/'mixed.json').write_text(json.dumps(report,indent=2)+'\n')
            print(trial,variant,values['ns/op'],'ns/op',values['gc/op'],'gc/op',flush=True)
report['status']='passed'
assert production.read_bytes()==git('show','HEAD:server/channels/app/post_metadata.go')
(args.output/'mixed.json').write_text(json.dumps(report,indent=2)+'\n')
