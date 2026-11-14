#!/usr/bin/env python3
"""Compare read, write and storage costs on a disposable migrated schema."""
import argparse,collections,hashlib,json,os,pathlib,shutil,socket,statistics,subprocess,tempfile,time,urllib.request,urllib.parse,uuid
parser=argparse.ArgumentParser();parser.add_argument('--workspace',type=pathlib.Path,required=True);parser.add_argument('--binary',type=pathlib.Path,required=True);parser.add_argument('--container',required=True);parser.add_argument('--reply-rows',type=int,default=100000);parser.add_argument('--write-rows',type=int,default=5000);parser.add_argument('--trials',type=int,default=3);parser.add_argument('--samples',type=int,default=15);parser.add_argument('--roots',type=int,default=100000);parser.add_argument('--output',type=pathlib.Path,required=True);args=parser.parse_args()
repo=pathlib.Path(__file__).resolve().parents[3];workspace=args.workspace.resolve();storage=args.output.parent.resolve();storage.mkdir(parents=True,exist_ok=True)
service=os.environ.get('TEST_DATABASE_POSTGRESQL_DSN','');address=urllib.parse.urlsplit(service)
if address.scheme not in ('postgres','postgresql') or not address.username:parser.error('Set TEST_DATABASE_POSTGRESQL_DSN to a disposable PostgreSQL URL')
if min(args.trials,args.samples,args.roots,args.reply_rows,args.write_rows)<1:parser.error('trial, sample and fixture sizes must be positive')
user=urllib.parse.unquote(address.username);runtime=pathlib.Path(tempfile.mkdtemp(prefix='unread-index-full-schema-'));database='unread_index_'+uuid.uuid4().hex[:12];container=args.container;binary=args.binary.resolve();created=False;server=None;indexed=False

r={'status':'running','settings':{'trials':args.trials,'samples':args.samples,'roots':args.roots,'reply_rows':args.reply_rows,'write_rows':args.write_rows},'candidate':'Replace existing RootId/DeleteAt index, preserving its prefix and adding CreateAt; no extra index.','reads':[],'writes':[],'indexes':[],'cleanup':{},'scope':'Full-schema SQL measurements of replacement RootId/DeleteAt/CreateAt index and count projections, not App or HTTP throughput. Actual migrated schema from the supplied public backend, with the target index normalized to the original RootId/DeleteAt definition before seeding. Fresh write copies bulk-build the identical baseline index definitions before measurement.','binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'runner_sha256':hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()}
def sql(s):
 result=subprocess.run(['docker','exec','-i',container,'psql','-XqAt','-U',user,'-d',database,'-v','ON_ERROR_STOP=1'],input=s,text=True,capture_output=True,timeout=600)
 if result.returncode:raise RuntimeError(result.stderr)
 return result.stdout.strip()
def scoped(s):return sql('SET search_path=probe,public;'+s)
def stream(s):
 d=json.JSONDecoder();out=[]
 while s.strip():
  s=s.lstrip();v,i=d.raw_decode(s);out.append(v);s=s[i:]
 return out
try:
 subprocess.run(['docker','exec',container,'createdb','-U',user,database],check=True,capture_output=True);created=True
 for name in ('i18n','templates','fonts'):shutil.copytree(workspace/name,runtime/name)
 config=json.loads((repo/'config/overlay.json').read_text())
 def update(section,values):config.setdefault(section,{}).update(values)
 for port in range(18065,18085):
  try:
   with socket.socket()as s:s.bind(('127.0.0.1',port))
   break
  except OSError:continue
 else:raise RuntimeError('No free loopback port')
 url='http://127.0.0.1:'+str(port)
 update('ServiceSettings',{'ListenAddress':'127.0.0.1:'+str(port),'SiteURL':url,'WebserverMode':'disabled','EnableLocalMode':False})
 update('SqlSettings',{'DriverName':'postgres','DataSource':urllib.parse.urlunsplit(address._replace(path='/'+database)),'MaxOpenConns':4,'MaxIdleConns':2})
 update('PluginSettings',{'Enable':False,'Directory':str(runtime/'plugins'),'ClientDirectory':str(runtime/'client-plugins')})
 update('JobSettings',{'RunJobs':False,'RunScheduler':False});update('FileSettings',{'DriverName':'local','Directory':str(runtime/'data')});update('LogSettings',{'EnableFile':False,'EnableConsole':True})
 cp=runtime/'config.json';cp.write_text(json.dumps(config));cp.chmod(0o600)
 env={k:v for k,v in os.environ.items()if k in ('PATH','LANG','TZ','TMPDIR')}
 with (storage/'full-schema-unread-index-server.log').open('w')as log:
  server=subprocess.Popen([str(binary),'server','--config',str(cp)],cwd=runtime,env=env,stdout=log,stderr=subprocess.STDOUT)
  deadline=time.monotonic()+60
  while time.monotonic()<deadline:
   if server.poll()is not None:raise RuntimeError('Migration backend exited')
   try:
    with urllib.request.urlopen(url+'/api/v4/system/ping',timeout=1)as response:assert json.load(response)['status']=='OK'
    break
   except Exception:time.sleep(.5)
  else:raise RuntimeError('Backend did not become ready')
  server.terminate();server.wait(timeout=15);r['cleanup']['server_stopped']=True
 r['postgres']=json.loads(sql("SELECT json_build_object('version',version(),'shared_buffers',current_setting('shared_buffers'),'random_page_cost',current_setting('random_page_cost'),'fsync',current_setting('fsync'),'synchronous_commit',current_setting('synchronous_commit'))"))
 r['schema_version']=sql('SELECT max(version) FROM db_migrations');sql('DROP INDEX IF EXISTS public.idx_posts_root_id_delete_at_create_at;CREATE INDEX IF NOT EXISTS idx_posts_root_id_delete_at ON public.posts(rootid,deleteat);');r['baseline_indexes']=json.loads(sql("SELECT json_agg(indexdef ORDER BY indexname) FROM pg_indexes WHERE schemaname='public' AND tablename='posts'"))
 assert not any('channel_user_create_at' in x for x in r['baseline_indexes'])
 sql('CREATE SCHEMA probe;CREATE TABLE probe.posts(LIKE public.posts INCLUDING ALL);')
 old_name=sql("SELECT c.relname FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid WHERE i.indrelid='probe.posts'::regclass AND pg_get_indexdef(i.indexrelid) LIKE '%(rootid, deleteat)'")
 assert old_name and '\n'not in old_name
 sql('ALTER INDEX probe.'+old_name+' RENAME TO probe_base_root_delete;')
 def fixtures(table,root_rows,reply_rows,prefix):
  # Synthetic roots and interleaved replies; full indexes, ordinary default-free rows.
  return f"""INSERT INTO {table}(id,rootid,createat,updateat,deleteat,userid,channelid,message,type,props,hashtags,fileids)
   SELECT substr(md5('{prefix}root'||n),1,26),'',1000000+n,1000000+n,0,substr(md5('user'||(n%1000)),1,26),substr(md5('channel'||(n%100)),1,26),repeat('synthetic benchmark message ',40),'','{{}}'::jsonb,'','' FROM generate_series(1,{root_rows})n;
   INSERT INTO {table}(id,rootid,createat,updateat,deleteat,userid,channelid,message,type,props,hashtags,fileids)
   SELECT substr(md5('{prefix}reply'||n),1,26),substr(md5('thread'||(n%100)),1,26),n/100,n/100,CASE WHEN n%7=0 THEN n ELSE 0 END,substr(md5('user'||(n%1000)),1,26),substr(md5('channel'||(n%100)),1,26),repeat('synthetic benchmark message ',40),'','{{}}'::jsonb,'','' FROM generate_series(1,{reply_rows})n;"""
 scoped(fixtures('Posts',args.roots,args.reply_rows,'fixture'))
 root=scoped("SELECT substr(md5('thread0'),1,26)")
 def query(star,viewed,deleted):return f"SELECT COUNT({'*'if star else 'Id'}) FROM Posts WHERE RootId='{root}' AND CreateAt>{viewed}"+(''if deleted else ' AND DeleteAt=0')
 def variant(wanted):
  global indexed
  if wanted==indexed:return
  if wanted:
   start=time.monotonic();scoped('CREATE INDEX CONCURRENTLY idx_posts_unread_root_create ON Posts(RootId,DeleteAt,CreateAt);DROP INDEX CONCURRENTLY probe_base_root_delete;')
   r['indexes'].append({'seconds':time.monotonic()-start,'bytes':int(scoped("SELECT pg_relation_size('idx_posts_unread_root_create')"))})
  else:scoped('CREATE INDEX CONCURRENTLY probe_base_root_delete ON Posts(RootId,DeleteAt);DROP INDEX CONCURRENTLY idx_posts_unread_root_create;')
  indexed=wanted
 # Separate visible and freshly updated rows. Recreate the same non-HOT update
 # state after each index transition; cleanup VACUUM happens outside timing.
 for state in ('vacuumed','changed'):
  for trial in range(args.trials):
   for new in ((False,True)if trial%2==0 else(True,False)):
    variant(new)
    scoped("UPDATE Posts SET DeleteAt=CASE WHEN CreateAt%7=0 THEN 10000 ELSE 0 END WHERE RootId<>'' AND CreateAt>900;VACUUM ANALYZE Posts;")
    if state=='changed':scoped("UPDATE Posts SET DeleteAt=CASE WHEN CreateAt%7=0 THEN 0 ELSE 10000 END WHERE RootId<>'' AND CreateAt>900;")
    for star in (False,True):
     for deleted in (False,True):
      for viewed in (0,900,1000):
       q=query(star,viewed,deleted);expected=int(scoped(query(False,viewed,deleted)));assert int(scoped(q))==expected
       scoped((q+';')*3)
       plans=stream(scoped(('EXPLAIN(ANALYZE,BUFFERS,FORMAT JSON) '+q+';')*args.samples))
       r['reads'].append({'state':state,'trial':trial,'indexed':new,'count_star':star,'deleted':deleted,'last_viewed':viewed,'expected':expected,'execution_ms':[p[0]['Execution Time']for p in plans],'first_plan':plans[0]})
    control=f"SELECT COUNT(*) FROM Posts WHERE RootId='{root}' AND DeleteAt=0"
    plans=stream(scoped(('EXPLAIN(ANALYZE,BUFFERS,FORMAT JSON) '+control+';')*args.samples))
    r['reads'].append({'state':state,'trial':trial,'indexed':new,'control':'existing_total_reply_count','execution_ms':[p[0]['Execution Time']for p in plans],'first_plan':plans[0]})
    print('read',state,trial,new,flush=True)
 # Read probes intentionally end before write samples. A fresh table for each
 # variant prevents earlier writes/rollbacks from changing the next sample.
 variant(False)
 r['baseline_sizes']=json.loads(scoped("SELECT json_build_object('heap_bytes',pg_relation_size('Posts'),'indexes_bytes',pg_indexes_size('Posts'),'total_bytes',pg_total_relation_size('Posts'))"))
 for trial in range(args.trials):
  for new in ((False,True)if trial%2==0 else(True,False)):
   for op in ('insert_roots','insert_replies','edit','delete'):
    scoped('DROP TABLE IF EXISTS WritePosts;CREATE TABLE WritePosts(LIKE Posts INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING STORAGE);INSERT INTO WritePosts SELECT * FROM Posts;')
    for number,definition in enumerate(r['baseline_indexes']):
     prefix='CREATE UNIQUE INDEX' if definition.startswith('CREATE UNIQUE INDEX') else 'CREATE INDEX'
     body=definition.split(' ON public.posts ',1)[1]
     scoped(prefix+' write_posts_index_'+str(number)+' ON WritePosts '+body+';')
    scoped('VACUUM ANALYZE WritePosts;')
    if new:
     number=next(i for i,definition in enumerate(r['baseline_indexes']) if definition.endswith('(rootid, deleteat)'))
     scoped('CREATE INDEX write_posts_unread_root_create ON WritePosts(RootId,DeleteAt,CreateAt);DROP INDEX write_posts_index_'+str(number)+';')
    if op=='insert_roots':q=fixtures('WritePosts',args.write_rows,0,f'write-{trial}-{op}')
    elif op=='insert_replies':q=fixtures('WritePosts',0,args.write_rows,f'write-{trial}-{op}').split(';')[1]+';'
    elif op=='edit':q="UPDATE WritePosts SET Message='edited message',EditAt=10001 WHERE RootId='"+root+"'"
    else:q="UPDATE WritePosts SET DeleteAt=10001 WHERE RootId='"+root+"'"
    # The generated fixture can contain an empty second insert. Select the one
    # nonempty insert for measuring and keep setup outside EXPLAIN.
    if op=='insert_roots':q=q.split(';')[0]+';'
    plan=json.loads(scoped('EXPLAIN(ANALYZE,BUFFERS,WAL,FORMAT JSON) '+q))
    r['writes'].append({'trial':trial,'indexed':new,'operation':op,'execution_ms':plan[0]['Execution Time'],'plan':plan})
    print('write',trial,new,op,flush=True)
 variant(True)
 r['after_sizes']=json.loads(scoped("SELECT json_build_object('heap_bytes',pg_relation_size('Posts'),'indexes_bytes',pg_indexes_size('Posts'),'total_bytes',pg_total_relation_size('Posts'))"))
 r['status']='passed'
except Exception as e:r['status']='failed';r['error']=str(e);raise
finally:
 if server is not None and server.poll()is None:server.terminate();server.wait(timeout=15)
 r['cleanup']['server_stopped']=server is None or server.poll()is not None
 if created:subprocess.run(['docker','exec',container,'dropdb','-U',user,'--force',database],check=True,capture_output=True);r['cleanup']['database_removed']=True
 shutil.rmtree(runtime);r['cleanup']['runtime_removed']=not runtime.exists()
 args.output.write_text(json.dumps(r,indent=2)+'\n')
print(json.dumps({'status':r['status'],'reads':len(r['reads']),'writes':len(r['writes']),'sizes':r.get('after_sizes')}))
