#!/usr/bin/env python3
"""Build public backends for the incremental attachment image URL comparison."""
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
matching_nm=Path('/tmp/mattermax-release-goroot')
parser.add_argument('--nm-goroot',type=Path,default=matching_nm if matching_nm.is_dir()else None)
a=parser.parse_args();a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=True)
repo=Path(__file__).resolve().parents[3];src=repo/'work/src/server'
def git(*args):return subprocess.check_output(['git',*args],cwd=src)
def digest(b):return hashlib.sha256(b).hexdigest()
sha=git('rev-parse','HEAD').decode().strip();base=git('rev-parse','HEAD^').decode().strip()
baseline_tree=git('rev-parse','HEAD^^{tree}').decode().strip()
contexts={'baa143e158e0663eca40552dfe1db2c1b24ed20a':'standalone PR58','bc29e763dac98119e836a7a3a95e10156a0d7c0a':'combined20 PR39-58'}
assert baseline_tree in contexts
context=contexts[baseline_tree]
post=src/'public/model/post.go';helper=src/'public/model/message_attachment_decode.go';image=src/'public/model/attachment_image_map.go';files=[post,helper,image]
for f in files:assert f.read_bytes()==git('show','HEAD:server/'+str(f.relative_to(src)))
text=helper.read_text();validate=text[text.index('func validateAttachmentMap('):text.index('\nfunc attachmentMapString(')];fallback=text[text.index('func decodeAttachmentJSON('):]
baseline_image=image.read_text().replace('package model\n','package model\n\nimport "encoding/json"\n',1)+'\n'+validate+'\n'+fallback
originals={post:git('show','HEAD^:server/public/model/post.go'),helper:git('show','HEAD^:server/public/model/message_attachment_decode.go'),image:baseline_image.encode()}
env=os.environ.copy();env.update(GOMAXPROCS='4',GOFLAGS='-p=2 -buildvcs=false')
report=dict(status='running',runner_sha256=digest(Path(__file__).read_bytes()),comparison_context=context,baseline_tree_sha=baseline_tree,source_sha=sha,baseline_source_sha=base,source_tree_sha=git('rev-parse','HEAD^{tree}').decode().strip(),production_sha256={str(f.relative_to(src)):digest(f.read_bytes())for f in files},baseline_overlay_sha256={str(f.relative_to(src)):digest(b)for f,b in originals.items()},go_version=subprocess.check_output(['go','version'],cwd=src,text=True).strip(),variants={})
with tempfile.TemporaryDirectory(prefix='mattermax-image-map-http-build-')as temporary:
 t=Path(temporary);replace={}
 for n,(file,data)in enumerate(originals.items()):
  f=t/(str(n)+'.go');f.write_bytes(data);replace[str(file)]=str(f)
 (t/'overlay.json').write_text(json.dumps({'Replace':replace}))
 for variant in ('before','after'):
  binary=a.output/('server-'+variant);build_hash=base if variant=='before'else sha;number='12.0.2-1.attachment-image-http-'+variant
  flags='-X github.com/mattermost/mattermost/server/public/model.BuildNumber='+number+' -X github.com/mattermost/mattermost/server/public/model.BuildHash='+build_hash+' -X github.com/mattermost/mattermost/server/public/model.BuildEnterpriseReady=false'
  cmd=['go','build','-tags','production','-ldflags',flags,'-o',str(binary)]
  if variant=='before':cmd+=['-overlay',str(t/'overlay.json')]
  cmd+=['./cmd/mattermost'];log=a.output/(variant+'-build.log')
  with log.open('w')as f:subprocess.run(cmd,cwd=src,env=env,stdout=f,stderr=subprocess.STDOUT,check=True)
  info=subprocess.check_output(['go','version','-m',str(binary)],env=env,text=True);(a.output/(variant+'-buildinfo.txt')).write_text(info);assert not re.search(r'-tags=.*\b(enterprise|sourceavailable)\b',info)
  nm_env=env.copy()
  if a.nm_goroot:nm_env['GOROOT']=str(a.nm_goroot)
  symbols=subprocess.check_output(['go','tool','nm',str(binary)],env=nm_env,text=True);assert 'server/v8/enterprise'not in symbols
  fast_symbols=['public/model.'+name for name in ['appendAttachmentMapImageURLs','validateAttachmentMap','decodeAttachmentJSON']]
  linked=[name for name in fast_symbols if name in symbols]
  assert len(linked)==(0 if variant=='before'else 3),(variant,linked)
  report['variants'][variant]=dict(binary=str(binary),binary_sha256=digest(binary.read_bytes()),build_hash=build_hash,build_number=number,build_enterprise_ready=False,command=cmd,image_fast_path_symbols=linked,forbidden_tags=False,enterprise_symbols=False,buildinfo_sha256=digest(info.encode()),build_log_sha256=digest(log.read_bytes()))
  (a.output/'build.json').write_text(json.dumps(report,indent=2)+'\n');print(variant,'build and exclusion checks passed',flush=True)
report['status']='passed';(a.output/'build.json').write_text(json.dumps(report,indent=2)+'\n')
