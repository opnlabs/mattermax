#!/usr/bin/env python3
"""Compare attachment image URL reads over the standalone attachment decoder."""
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
a=parser.parse_args();a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=True)
repo=Path(__file__).resolve().parents[3];src=repo/'work/src/server'
def git(*args):return subprocess.check_output(['git',*args],cwd=src)
def digest(b):return hashlib.sha256(b).hexdigest()
sha=git('rev-parse','HEAD').decode().strip();base=git('rev-parse','HEAD^').decode().strip()
baseline_tree=git('rev-parse','HEAD^^{tree}').decode().strip()
contexts={'baa143e158e0663eca40552dfe1db2c1b24ed20a':'standalone PR58','bc29e763dac98119e836a7a3a95e10156a0d7c0a':'combined20 PR39-58'}
assert baseline_tree in contexts
context=contexts[baseline_tree]
files=git('diff','--name-only','HEAD^','HEAD').decode().splitlines()
assert files==['server/public/model/attachment_image_map.go','server/public/model/attachment_image_map_test.go','server/public/model/message_attachment_decode.go','server/public/model/post.go']
for f in files:assert(src.parent/f).read_bytes()==git('show','HEAD:'+f)
fixture='server/channels/app/attachment_map_history_test.go';assert(src.parent/fixture).read_bytes()==git('show','HEAD^:'+fixture)
helper=src/'public/model/message_attachment_decode.go';image=src/'public/model/attachment_image_map.go';post=src/'public/model/post.go';text=helper.read_text()
validate=text[text.index('func validateAttachmentMap('):text.index('\nfunc attachmentMapString(')]
json_fallback=text[text.index('func decodeAttachmentJSON('):]
# The original post/helper are restored for baseline production calls. These
# extra declarations keep new tests/helpers compilable; the baseline accessors
# do not call them and they have no initialization effects.
baseline_image=image.read_text().replace('package model\n','package model\n\nimport "encoding/json"\n',1)+'\n'+validate+'\n'+json_fallback
originals={post:git('show','HEAD^:server/public/model/post.go'),helper:git('show','HEAD^:server/public/model/message_attachment_decode.go'),image:baseline_image.encode()}
env=os.environ.copy();env.update(TZ='UTC',GOMAXPROCS='4',GOGC='100')
report=dict(status='running',comparison_context=context,baseline_tree_sha=baseline_tree,source_sha=sha,baseline_source_sha=base,source_tree_sha=git('rev-parse','HEAD^{tree}').decode().strip(),file_sha256={f:digest((src.parent/f).read_bytes())for f in files+[fixture]},baseline_overlay_sha256={str(f.relative_to(src.parent)):digest(b)for f,b in originals.items()},runner_sha256=digest(Path(__file__).read_bytes()),trials=a.trials,history_iterations=a.history_iterations,go_version=subprocess.check_output(['go','version'],cwd=src,text=True).strip(),environment={k:env.get(k)for k in ['GOMAXPROCS','GOGC','GOMEMLIMIT','TZ']},samples=[],scope='Incremental image URL change over '+context+'. Before restores both original production files and adds unused validator/JSON fallback declarations to keep new test/helper files compilable. No initializer effects. Model image accessor and attachment-decoder controls plus identical SQL-stored 60-post history fixtures. Synthetic component/preparation measurements, not HTTP throughput.')
expected={'model':{'BenchmarkAttachmentMapDecode/'+k for k in ['plain','typed','fields=0','fields=8','fields=64','actions','unknown','structured','malformed']}|{'BenchmarkAttachmentImageMapURLs/'+k for k in ['plain','typed','fields=0','fields=8','fields=64','urls','actions','unknown','structured','malformed','mixed-late']},'history':{'BenchmarkAttachmentMapHistory/'+k for k in ['plain','fields=0','fields=8','fields=64','actions']}}
pattern=re.compile(r'^(Benchmark\S+)-\d+\s+\d+\s+([\d.]+) ns/op\s+(\d+) B/op\s+(\d+) allocs/op',re.M)
with tempfile.TemporaryDirectory(prefix='mattermax-attachment-image-map-')as temporary:
 t=Path(temporary);replace={}
 for n,(file,content)in enumerate(originals.items()):
  original=t/(str(n)+'.go');original.write_bytes(content);replace[str(file)]=str(original)
 (t/'overlay.json').write_text(json.dumps({'Replace':replace}))
 for trial in range(a.trials):
  for variant in (('before','after')if trial%2==0 else('after','before')):
   for group,package,bench,duration in [('model','./public/model','^(BenchmarkAttachmentMapDecode|BenchmarkAttachmentImageMapURLs)$','300ms'),('history','./channels/app','^BenchmarkAttachmentMapHistory$',str(a.history_iterations)+'x')]:
    cmd=['go','test','-p','1',package,'-run','^$','-bench',bench,'-benchtime='+duration,'-count=1','-timeout=10m','-json']
    if variant=='before':cmd+=['-overlay',str(t/'overlay.json')]
    log=a.output/(str(trial)+'-'+variant+'-'+group+'.jsonl')
    with log.open('w')as stream:subprocess.run(cmd,cwd=src,env=env,stdout=stream,stderr=subprocess.STDOUT,check=True)
    events=[json.loads(l)for l in log.read_text().splitlines()if l.startswith('{')];assert not any(e['Action']in('fail','skip')for e in events);assert any(e['Action']=='pass'and not e.get('Test')for e in events)
    output={}
    for e in events:output[e.get('Test','')]=output.get(e.get('Test',''),'')+e.get('Output','')
    cases=[dict(name=m[0],ns_per_op=float(m[1]),bytes_per_op=int(m[2]),allocs_per_op=int(m[3]))for s in output.values()for m in pattern.findall(s)];assert len(cases)==len(expected[group])and{c['name']for c in cases}==expected[group]
    report['samples'].append(dict(trial=trial,variant=variant,group=group,command=cmd,benchmarks=cases,raw_log_sha256=digest(log.read_bytes())));(a.output/'results.json').write_text(json.dumps(report,indent=2)+'\n');print(trial,variant,group,'passed',flush=True)
report['status']='passed';(a.output/'results.json').write_text(json.dumps(report,indent=2)+'\n')
