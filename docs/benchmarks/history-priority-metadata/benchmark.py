#!/usr/bin/env python3
"""Compare independent versus combined priority/acknowledgement preparation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--trials',type=int,default=3)
parser.add_argument('--iterations',type=int,default=100)
a=parser.parse_args();a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=True)
repo=Path(__file__).resolve().parents[3];src=repo/'work/src/server'
def git(*args):return subprocess.check_output(['git',*args],cwd=src)
def digest(b):return hashlib.sha256(b).hexdigest()
sha=git('rev-parse','HEAD').decode().strip();base=git('rev-parse','HEAD^').decode().strip()
assert git('rev-parse','HEAD^^{tree}').decode().strip()=='a2da7f25de10aadbb8974f5f6191aa082ec6e6e6'
files=git('diff','--name-only','HEAD^','HEAD').decode().splitlines();modified=git('diff','--name-only','--diff-filter=M','HEAD^','HEAD').decode().splitlines();assert modified==['server/channels/app/post_metadata.go']
for f in files:assert(src.parent/f).read_bytes()==git('show','HEAD:'+f)
production=src/'channels/app/post_metadata.go';original=git('show','HEAD^:server/channels/app/post_metadata.go')
env=os.environ.copy();env.update(TZ='UTC',GOMAXPROCS='4',GOGC='100')
report=dict(status='running',source_sha=sha,baseline_source_sha=base,source_tree_sha=git('rev-parse','HEAD^{tree}').decode().strip(),file_sha256={f:digest((src.parent/f).read_bytes())for f in files},baseline_post_metadata_sha256=digest(original),runner_sha256=digest(Path(__file__).read_bytes()),trials=a.trials,iterations=a.iterations,go_version=subprocess.check_output(['go','version'],cwd=src,text=True).strip(),environment={k:env.get(k)for k in ['GOMAXPROCS','GOGC','GOMEMLIMIT','TZ']},samples=[],scope='Independent candidate over original38 patches. Before overlays original post_metadata.go, retaining original separate app/store reads. Both variants compile the new optional capability files and identical fixture/check code; setup is outside timing. SQL-stored ordered pages, priority/custom emoji enabled except explicit disabled control; previews/image proxy off, no attachments/files/reactions. Timer includes output checks. Synthetic preparation comparison, not HTTP or concurrent throughput.')
expected={'BenchmarkHistoryPriorityMetadata/posts='+str(n)+'/'+kind for n in [1,60,201]for kind in ['empty','priority','acknowledgements','mixed','dense','disabled']};pattern=re.compile(r'^(Benchmark\S+)-\d+\s+\d+\s+([\d.]+) ns/op\s+(\d+) B/op\s+(\d+) allocs/op',re.M)
with tempfile.TemporaryDirectory(prefix='mattermax-history-priority-')as temporary:
 t=Path(temporary);(t/'post_metadata.go').write_bytes(original);(t/'overlay.json').write_text(json.dumps({'Replace':{str(production):str(t/'post_metadata.go')}}))
 for trial in range(a.trials):
  for variant in (('before','after')if trial%2==0 else('after','before')):
   cmd=['go','test','-p','1','./channels/app','-run','^$','-bench','^BenchmarkHistoryPriorityMetadata$','-benchtime='+str(a.iterations)+'x','-count=1','-timeout=15m','-json']
   if variant=='before':cmd+=['-overlay',str(t/'overlay.json')]
   log=a.output/(str(trial)+'-'+variant+'.jsonl')
   with log.open('w')as f:subprocess.run(cmd,cwd=src,env=env,stdout=f,stderr=subprocess.STDOUT,check=True)
   events=[json.loads(l)for l in log.read_text().splitlines()if l.startswith('{')];assert not any(e['Action']in('fail','skip')for e in events);assert any(e['Action']=='pass'and not e.get('Test')for e in events)
   output={}
   for e in events:output[e.get('Test','')]=output.get(e.get('Test',''),'')+e.get('Output','')
   cases=[dict(name=m[0],ns_per_op=float(m[1]),bytes_per_op=int(m[2]),allocs_per_op=int(m[3]))for s in output.values()for m in pattern.findall(s)];assert len(cases)==18 and{c['name']for c in cases}==expected
   report['samples'].append(dict(trial=trial,variant=variant,command=cmd,benchmarks=cases,raw_log_sha256=digest(log.read_bytes())));(a.output/'results.json').write_text(json.dumps(report,indent=2)+'\n');print(trial,variant,'passed',flush=True)
report['status']='passed';(a.output/'results.json').write_text(json.dumps(report,indent=2)+'\n')
