#!/usr/bin/env python3
"""Compare authenticated history HTTP latency on disposable public backends."""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import random
import shutil
import socket
import statistics
import struct
import subprocess
import tempfile
import time
import uuid
import zlib

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--build-report',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--trials',type=int,default=5)
parser.add_argument('--requests',type=int,default=1000)
parser.add_argument('--warmup',type=int,default=100)
a=parser.parse_args();assert a.requests>=5 and a.requests%5==0 and a.warmup>=5 and a.warmup%5==0
a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=True)
repo=Path(__file__).resolve().parents[3];build=json.loads(a.build_report.read_text());assert build['status']=='passed'
def digest(b):return hashlib.sha256(b).hexdigest()
for v in build['variants'].values():assert digest(Path(v['binary']).read_bytes())==v['binary_sha256']and not v['forbidden_tags']and not v['enterprise_symbols']
report=dict(status='running',build_report_sha256=digest(a.build_report.read_bytes()),source_sha=build['source_sha'],baseline_source_sha=build['baseline_source_sha'],binaries={k:{key:v[key]for key in ['binary_sha256','build_hash','build_number']}for k,v in build['variants'].items()},runner_sha256=digest(Path(__file__).read_bytes()),trials=a.trials,requests_per_process=a.requests,warmup_per_process=a.warmup,measurement_kind='fixture/output pilot'if a.requests<100 else'synthetic local HTTP comparison',runs=[],scope='Regular team/channel member, one persistent HTTP/1.1 client, uncompressed GET /api/v4/channels/{id}/posts?page=0&per_page=60&collapsedThreads=false. Five equally weighted plain/rich/fallback attachment page types in fixed shuffled order. Fresh database/server and all-API fixtures for each process. Timing spans request send through complete response read, excluding JSON decode/assertions; wall loop includes them. Localhost without TLS, no concurrent clients or production throughput/tail claim.')
kinds=['plain','fields=0','fields=8','fields=64','actions']
references={}
class Client:
 def __init__(self,port):self.port=port;self.conn=http.client.HTTPConnection('127.0.0.1',port,timeout=10);self.token=None
 def close(self):self.conn.close()
 def reset_connection(self):self.close();self.conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=10)
 def call(self,method,path,body=None,expected=200,content_type='application/json'):
  headers={'Accept':'application/json','Accept-Encoding':'identity'}
  if self.token:headers['Authorization']='Bearer '+self.token
  if body is not None:
   headers['Content-Type']=content_type
   if not isinstance(body,bytes):body=json.dumps(body).encode()
  start=time.perf_counter_ns();self.conn.request(method,'/api/v4'+path,body=body,headers=headers);response=self.conn.getresponse();raw=response.read();elapsed=time.perf_counter_ns()-start
  value=json.loads(raw)if raw else None
  if response.status!=expected:raise RuntimeError(method+' '+path+' HTTP '+str(response.status)+' '+str(value))
  assert not response.getheader('Content-Encoding')
  return value,dict((k.lower(),v)for k,v in response.getheaders()),elapsed,len(raw)
def run(trial,variant):
 run=Path(tempfile.mkdtemp(prefix='mattermax-attachment-http-'));database='mm_attachment_http_'+uuid.uuid4().hex[:12];created=False;server=None;client=None
 result=dict(trial=trial,variant=variant,status='running',database=database,database_removed=False,server_stopped=False,runtime_directory_removed=False)
 try:
  subprocess.run(['docker','exec','mattermax-upstream-tests','createdb','-U','mmuser',database],check=True,capture_output=True);created=True
  for name in ['i18n','templates','fonts']:
   source=repo/'work/src/server'/name;assert source.is_dir()and not any(f.is_symlink()for f in source.rglob('*'));shutil.copytree(source,run/name)
  for port in range(18065,18085):
   try:
    with socket.socket()as probe:probe.bind(('127.0.0.1',port))
    break
   except OSError:continue
  else:raise RuntimeError('No local test port')
  config=json.loads((repo/'config/overlay.json').read_text())
  def update(section,values):config.setdefault(section,{}).update(values)
  update('ServiceSettings',{'ListenAddress':'127.0.0.1:'+str(port),'SiteURL':'http://127.0.0.1:'+str(port),'WebserverMode':'disabled','EnableLocalMode':False,'EnableLinkPreviews':False,'EnableCustomEmoji':True,'PostPriority':True})
  update('TeamSettings',{'EnableOpenServer':True})
  update('EmailSettings',{'SendEmailNotifications':False,'RequireEmailVerification':False})
  update('RateLimitSettings',{'Enable':False})
  update('MetricsSettings',{'Enable':False})
  update('SqlSettings',{'DriverName':'postgres','DataSource':'postgres://mmuser:mostest_password@127.0.0.1:55439/'+database+'?sslmode=disable','MaxOpenConns':4,'MaxIdleConns':2})
  update('PluginSettings',{'Enable':False,'Directory':str(run/'plugins'),'ClientDirectory':str(run/'client-plugins')})
  update('JobSettings',{'RunJobs':False,'RunScheduler':False})
  update('FileSettings',{'DriverName':'local','Directory':str(run/'data')})
  update('LogSettings',{'EnableFile':False,'EnableConsole':True,'ConsoleLevel':'ERROR'})
  file=run/'config.json';file.write_text(json.dumps(config));file.chmod(0o600)
  env={k:v for k,v in os.environ.items()if k in ['PATH','LANG','TMPDIR']};env.update(TZ='UTC',GOMAXPROCS='4',GOGC='100')
  with (a.output/(str(trial)+'-'+variant+'-server.log')).open('w')as log:
   server=subprocess.Popen([build['variants'][variant]['binary'],'server','--config',str(file)],cwd=run,env=env,stdout=log,stderr=subprocess.STDOUT)
   deadline=time.monotonic()+60
   while time.monotonic()<deadline:
    if server.poll()is not None:raise RuntimeError('Server exited before readiness')
    probe=Client(port)
    try:
     value,_,_,_=probe.call('GET','/system/ping')
     if value.get('status')=='OK':break
    except (OSError,http.client.HTTPException):pass
    finally:probe.close()
    time.sleep(0.25)
   else:raise RuntimeError('Readiness timeout')
   client=Client(port);value,_,_,_=client.call('GET','/config/client?format=old');assert value['BuildNumber']==build['variants'][variant]['build_number']and value['SiteName']=='Mattermax'and value['Version']=='12.0.2';result['verified_build_number']=value['BuildNumber']
   password='PerfHttpFixtureOnly!7'
   admin,_,_,_=client.call('POST','/users',{'username':'perf_admin','email':'admin@perf.example.test','password':password},201);assert 'system_admin'in admin['roles']
   _,headers,_,_=client.call('POST','/users/login',{'login_id':admin['email'],'password':password});client.token=headers['token']
   reader,_,_,_=client.call('POST','/users',{'username':'perf_reader','email':'reader@perf.example.test','password':password},201);assert 'system_admin'not in reader['roles']
   team,_,_,_=client.call('POST','/teams',{'name':'perf-http','display_name':'Performance fixture','type':'O'},201)
   client.call('POST','/teams/'+team['id']+'/members',{'team_id':team['id'],'user_id':reader['id']},201)
   messages=['attachment history']*5
   channels=[];posts=[];ids={admin['id']:'owner',reader['id']:'reader',team['id']:'team'}
   for i,kind in enumerate(kinds):
    channel,_,_,_=client.call('POST','/channels',{'team_id':team['id'],'name':'perf-'+kind.replace('=','-'),'display_name':kind,'type':'O'},201);channels.append(channel['id']);ids[channel['id']]='channel-'+kind
    client.call('POST','/channels/'+channel['id']+'/members',{'user_id':reader['id']},201)
    fields=64 if kind=='fields=64'else(8 if kind in('fields=8','actions')else 0)
    attachment={'fallback':'monitoring report','color':'good','author_name':'Monitor','title':'Report','text':'observations','footer':'local fixture','fields':[{'title':'Metric '+str(n),'value':'observed value','short':True}for n in range(fields)]}
    if kind=='actions':attachment['actions']=[{'id':'view','type':'button','name':'View','integration':{'url':'https://action.example.test/callback'}}]
    group=[];previous=0
    for n in range(60):
     post,_,_,_=client.call('POST','/posts',dict(channel_id=channel['id'],message=messages[i],**({'props':{'attachments':[attachment]}}if kind!='plain'else{})),201);assert post['message']==messages[i]and post['create_at']>previous;previous=post['create_at'];group.append(post['id']);ids[post['id']]='post-'+kind+'-'+str(n);time.sleep(0.002)
    posts.append(group)
   _,headers,_,_=client.call('POST','/users/login',{'login_id':reader['email'],'password':password});client.token=headers['token'];client.reset_connection()
   def normalize(obj,key=''):
    if isinstance(obj,dict):return {ids.get(k,k):normalize(v,k)for k,v in obj.items()}
    if isinstance(obj,list):return [normalize(x,key)for x in obj]
    if key.endswith('_at')and isinstance(obj,int):return 0
    if isinstance(obj,str):return ids.get(obj,'other-id'if obj and(key=='id'or key.endswith('_id'))else obj)
    return obj
   def history(i):
    value,headers,elapsed,size=client.call('GET','/channels/'+channels[i]+'/posts?page=0&per_page=60&collapsedThreads=false')
    assert headers.get('content-type','').startswith('application/json')and len(value['posts'])==60 and value['order']==list(reversed(posts[i]))and set(value['posts'])==set(posts[i])
    for post in value['posts'].values():
     assert post['message']==messages[i]and post['channel_id']==channels[i]and post['user_id']==admin['id']and not post.get('root_id')and post['delete_at']==0
     emojis=(post.get('metadata')or{}).get('emojis')or[]
     assert len(emojis)==0
     if kinds[i]!='plain':
      attachments=post.get('props',{}).get('attachments')
      assert len(attachments)==1 and attachments[0]['text']=='observations'
      expected_fields=64 if kinds[i]=='fields=64'else(8 if kinds[i]in('fields=8','actions')else 0)
      assert len(attachments[0]['fields'])==expected_fields
      for n,field in enumerate(attachments[0]['fields']):assert field['title']=='Metric '+str(n)and field['value']=='observed value'and field['short']is True
      if kinds[i]=='actions':assert len(attachments[0]['actions'])==1 and attachments[0]['actions'][0]['id']=='view'
      embeds=(post.get('metadata')or{}).get('embeds')or[];assert len(embeds)==1 and embeds[0]['type']=='message_attachment'

    fingerprint=digest(json.dumps(normalize(value),sort_keys=True,separators=(',',':')).encode());key=kinds[i]
    if key in references:assert references[key]==fingerprint,(key,'normalized response mismatch')
    else:references[key]=fingerprint
    return elapsed,size
   for n in range(a.warmup):history(n%5)
   sock=client.conn.sock;assert sock is not None
   order=[n%5 for n in range(a.requests)];random.Random(42).shuffle(order);samples={k:[]for k in kinds};sizes={k:set()for k in kinds};started=time.perf_counter_ns()
   for i in order:
    elapsed,size=history(i);assert client.conn.sock is sock;samples[kinds[i]].append(elapsed);sizes[kinds[i]].add(size)
   wall=time.perf_counter_ns()-started;assert all(len(v)==a.requests//5 for v in samples.values())
   result.update(status='passed',latencies_ns=samples,response_bytes={k:sorted(v)for k,v in sizes.items()},mean_latency_ns=sum(sum(v)for v in samples.values())/a.requests,wall_loop_ns=wall,regular_member=True,persistent_connection_verified=True,normalized_response_sha256=dict(references),environment={'GOMAXPROCS':4,'GOGC':100,'TZ':'UTC'},fixture_posts=300)
 except Exception as error:
  result.update(status='failed',error=str(error));raise
 finally:
  if client:client.close()
  if server:
   if server.poll()is None:
    server.terminate()
    try:server.wait(timeout=15)
    except subprocess.TimeoutExpired:server.kill();server.wait(timeout=5)
   result['server_stopped']=server.poll()is not None
  if created:
   subprocess.run(['docker','exec','mattermax-upstream-tests','dropdb','-U','mmuser','--force',database],check=True,capture_output=True);result['database_removed']=True
  shutil.rmtree(run);result['runtime_directory_removed']=not run.exists();report['runs'].append(result);(a.output/'http.json').write_text(json.dumps(report,indent=2)+'\n')
for trial in range(a.trials):
 for variant in (('before','after')if trial%2==0 else('after','before')):
  run(trial,variant);print(trial,variant,report['runs'][-1]['mean_latency_ns'],'ns/request',flush=True)
report['status']='passed';(a.output/'http.json').write_text(json.dumps(report,indent=2)+'\n')
