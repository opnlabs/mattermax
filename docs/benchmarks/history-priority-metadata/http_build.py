#!/usr/bin/env python3
"""Build public baseline/candidate history metadata backends."""
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
matching=Path('/tmp/mattermax-release-goroot')
parser.add_argument('--nm-goroot',type=Path,default=matching if matching.is_dir()else None)
a=parser.parse_args();a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=True)
repo=Path(__file__).resolve().parents[3];src=repo/'work/src/server'
def git(*args):return subprocess.check_output(['git',*args],cwd=src)
def digest(b):return hashlib.sha256(b).hexdigest()
sha=git('rev-parse','HEAD').decode().strip();base=git('rev-parse','HEAD^').decode().strip();assert git('rev-parse','HEAD^^{tree}').decode().strip()=='a2da7f25de10aadbb8974f5f6191aa082ec6e6e6'
file=src/'channels/app/post_metadata.go';assert file.read_bytes()==git('show','HEAD:server/channels/app/post_metadata.go');original=git('show','HEAD^:server/channels/app/post_metadata.go')
changed=git('diff','--name-only','HEAD^','HEAD').decode().splitlines()
for f in changed:assert(src.parent/f).read_bytes()==git('show','HEAD:'+f)
env=os.environ.copy();env.update(GOMAXPROCS='4',GOFLAGS='-p=2 -buildvcs=false')
report=dict(status='running',comparison_context='original38',source_sha=sha,baseline_source_sha=base,source_tree_sha=git('rev-parse','HEAD^{tree}').decode().strip(),file_sha256={f:digest((src.parent/f).read_bytes())for f in changed},baseline_post_metadata_sha256=digest(original),runner_sha256=digest(Path(__file__).read_bytes()),go_version=subprocess.check_output(['go','version'],cwd=src,text=True).strip(),variants={})
with tempfile.TemporaryDirectory(prefix='mattermax-priority-meta-build-')as temporary:
 t=Path(temporary);(t/'post_metadata.go').write_bytes(original);(t/'overlay.json').write_text(json.dumps({'Replace':{str(file):str(t/'post_metadata.go')}}))
 for variant in ('before','after'):
  binary=a.output/('server-'+variant);build_hash=base if variant=='before'else sha;number='12.0.2-1.priority-metadata-http-'+variant
  flags='-X github.com/mattermost/mattermost/server/public/model.BuildNumber='+number+' -X github.com/mattermost/mattermost/server/public/model.BuildHash='+build_hash+' -X github.com/mattermost/mattermost/server/public/model.BuildEnterpriseReady=false'
  cmd=['go','build','-tags','production','-ldflags',flags,'-o',str(binary)]
  if variant=='before':cmd+=['-overlay',str(t/'overlay.json')]
  cmd+=['./cmd/mattermost'];log=a.output/(variant+'-build.log')
  with log.open('w')as f:subprocess.run(cmd,cwd=src,env=env,stdout=f,stderr=subprocess.STDOUT,check=True)
  info=subprocess.check_output(['go','version','-m',str(binary)],env=env,text=True);(a.output/(variant+'-buildinfo.txt')).write_text(info);assert not re.search(r'-tags=.*\b(enterprise|sourceavailable)\b',info)
  nm_env=env.copy()
  if a.nm_goroot:nm_env['GOROOT']=str(a.nm_goroot)
  symbols=subprocess.check_output(['go','tool','nm',str(binary)],env=nm_env,text=True);assert 'server/v8/enterprise'not in symbols
  linked='channels/app.readPostListPriorityMetadata'in symbols;assert linked==(variant=='after')
  report['variants'][variant]=dict(binary=str(binary),binary_sha256=digest(binary.read_bytes()),build_hash=build_hash,build_number=number,build_enterprise_ready=False,command=cmd,combined_read_entrypoint_linked=linked,forbidden_tags=False,enterprise_symbols=False,buildinfo_sha256=digest(info.encode()),build_log_sha256=digest(log.read_bytes()))
  (a.output/'build.json').write_text(json.dumps(report,indent=2)+'\n');print(variant,'build and exclusion checks passed',flush=True)
report['status']='passed';(a.output/'build.json').write_text(json.dumps(report,indent=2)+'\n')
