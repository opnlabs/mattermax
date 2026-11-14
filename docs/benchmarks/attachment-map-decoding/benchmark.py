#!/usr/bin/env python3
"""Compare the original attachment decoder with the direct-map decoder."""
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
parser.add_argument('--history-iterations',type=int,default=200)
a=parser.parse_args();a.output.mkdir(parents=True,exist_ok=True)
repo=Path(__file__).resolve().parents[3];src=repo/'work/src/server'
def git(*args):return subprocess.check_output(['git',*args],cwd=src)
def digest(value):return hashlib.sha256(value).hexdigest()
sha=git('rev-parse','HEAD').decode().strip();base=git('rev-parse','HEAD^').decode().strip()
assert git('rev-parse','HEAD^^{tree}').decode().strip()=='a2da7f25de10aadbb8974f5f6191aa082ec6e6e6'
files=git('diff','--name-only','HEAD^','HEAD').decode().splitlines();assert files==['server/channels/app/attachment_map_history_test.go','server/public/model/attachment_map_decode_test.go','server/public/model/message_attachment_decode.go','server/public/model/post.go']
for file in files:assert(src.parent/file).read_bytes()==git('show','HEAD:'+file)
production=src/'public/model/post.go';original=git('show','HEAD^:server/public/model/post.go')
env=os.environ.copy();env.update(TZ='UTC',GOMAXPROCS='4',GOGC='100')
report=dict(status='running',source_sha=sha,baseline_source_sha=base,source_tree_sha=git('rev-parse','HEAD^{tree}').decode().strip(),file_sha256={f:digest((src.parent/f).read_bytes())for f in files},baseline_post_sha256=digest(original),runner_sha256=digest(Path(__file__).read_bytes()),trials=a.trials,history_iterations=a.history_iterations,go_version=subprocess.check_output(['go','version'],cwd=src,text=True).strip(),environment={k:env.get(k)for k in ['GOMAXPROCS','GOGC','GOMEMLIMIT','TZ']},samples=[],scope='Standalone original 38-patch parent. Model accessor plus 60-post stored history preparation. History validates raw props and prepared metadata without invoking the decoder again in the timed check. Fixtures are read back through SQL as []any. Warm caches, priority/custom emoji reads enabled; no files, remote previews or image proxy. Before overlays only the original Post.Attachments production file; helper/test files are identical. These are local synthetic component/preparation measurements, not HTTP throughput.')
expected={'model':{'BenchmarkAttachmentMapDecode/'+k for k in ['plain','typed','fields=0','fields=8','fields=64','actions','unknown','structured','malformed']},'history':{'BenchmarkAttachmentMapHistory/'+k for k in ['plain','fields=0','fields=8','fields=64','actions']}}
pattern=re.compile(r'^(Benchmark\S+)-\d+\s+\d+\s+([\d.]+) ns/op\s+(\d+) B/op\s+(\d+) allocs/op',re.M)
with tempfile.TemporaryDirectory(prefix='mattermax-attachment-map-')as temporary:
 t=Path(temporary);(t/'post.go').write_bytes(original);(t/'overlay.json').write_text(json.dumps({'Replace':{str(production):str(t/'post.go')}}))
 for trial in range(a.trials):
  for variant in (('before','after')if trial%2==0 else('after','before')):
   for group,package,bench,duration in [('model','./public/model','^BenchmarkAttachmentMapDecode$','300ms'),('history','./channels/app','^BenchmarkAttachmentMapHistory$',str(a.history_iterations)+'x')]:
    cmd=['go','test','-p','1',package,'-run','^$','-bench',bench,'-benchtime='+duration,'-count=1','-timeout=10m','-json']
    if variant=='before':cmd+=['-overlay',str(t/'overlay.json')]
    log=a.output/(str(trial)+'-'+variant+'-'+group+'.jsonl')
    with log.open('w')as stream:subprocess.run(cmd,cwd=src,env=env,stdout=stream,stderr=subprocess.STDOUT,check=True)
    events=[json.loads(l)for l in log.read_text().splitlines()if l.startswith('{')];assert not any(e['Action']in('fail','skip')for e in events);assert any(e['Action']=='pass'and not e.get('Test')for e in events)
    output={}
    for e in events:output[e.get('Test','')]=output.get(e.get('Test',''),'')+e.get('Output','')
    cases=[dict(name=m[0],ns_per_op=float(m[1]),bytes_per_op=int(m[2]),allocs_per_op=int(m[3]))for text in output.values()for m in pattern.findall(text)];assert len(cases)==len(expected[group])and{c['name']for c in cases}==expected[group]
    report['samples'].append(dict(trial=trial,variant=variant,group=group,command=cmd,benchmarks=cases,raw_log_sha256=digest(log.read_bytes())));(a.output/'results.json').write_text(json.dumps(report,indent=2)+'\n');print(trial,variant,group,'passed',flush=True)
report['status']='passed';assert production.read_bytes()==git('show','HEAD:server/public/model/post.go');(a.output/'results.json').write_text(json.dumps(report,indent=2)+'\n')
