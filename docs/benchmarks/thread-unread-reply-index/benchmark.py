#!/usr/bin/env python3
"""Run alternating real-store before/after unread-reply measurements."""
import argparse,collections,hashlib,json,os,pathlib,re,statistics,subprocess,time
parser=argparse.ArgumentParser();parser.add_argument('--workspace',type=pathlib.Path,required=True);parser.add_argument('--baseline',default='HEAD^');parser.add_argument('--iterations',type=int,default=500);parser.add_argument('--trials',type=int,default=3);parser.add_argument('--bench',default='^BenchmarkThreadUnreadReplies$');parser.add_argument('--expected-cases',type=int,default=30);parser.add_argument('--output',type=pathlib.Path,required=True);args=parser.parse_args();src=args.workspace.resolve();args.output.parent.mkdir(parents=True,exist_ok=True)
run=args.output.parent;target=src/'channels/store/sqlstore/thread_store.go';old=run/'baseline-thread-store.go';old.write_bytes(subprocess.check_output(['git','show',args.baseline+':server/channels/store/sqlstore/thread_store.go'],cwd=src));overlay=run/'baseline-overlay.json';overlay.write_text(json.dumps({'Replace':{str(target):str(old)}}))
env=os.environ.copy();env.update(GOFLAGS='-p=2',GOMAXPROCS='4')
if not env.get('TEST_DATABASE_POSTGRESQL_DSN'):parser.error('Set TEST_DATABASE_POSTGRESQL_DSN to a disposable PostgreSQL test service')
if min(args.iterations,args.trials)<1:parser.error('iterations and trials must be positive')

r={'status':'running','runner_sha256':hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),'source_sha':subprocess.check_output(['git','rev-parse','HEAD'],cwd=src,text=True).strip(),'source_tree_sha':subprocess.check_output(['git','rev-parse','HEAD^{tree}'],cwd=src,text=True).strip(),'go_version':subprocess.check_output(['go','version'],cwd=src,env=env,text=True).strip(),'gomaxprocs':4,'benchmark_filter':args.bench,'expected_cases':args.expected_cases,'iterations':args.iterations,'trials':args.trials,'baseline_sha':args.baseline,'production_file_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'baseline_file_sha256':hashlib.sha256(old.read_bytes()).hexdigest(),'samples':[],'scope':'Serial SQL-store calls on 30 roots and fresh, interleaved reply rows. Before uses the original production file and drops the candidate index before seeding. Each process has a new database from the standard store test harness. Fixture setup, index changes and cleanup are outside timing. Not App/HTTP latency or production capacity.'}
try:
 for trial in range(args.trials):
  for variant in (('before','after') if trial%2==0 else ('after','before')):
   cmd=['go','test','-p','1','./channels/store/sqlstore','-run','^$','-bench',args.bench,'-benchtime',str(args.iterations)+'x','-count=1','-timeout=15m','-json']
   if variant=='before':cmd+=['-overlay',str(overlay)]
   variant_env=dict(env,MATTERMAX_UNREAD_INDEX_VARIANT=variant);log=run/(str(trial)+'-'+variant+'.jsonl')
   with log.open('w')as f:subprocess.run(cmd,cwd=src,env=variant_env,stdout=f,stderr=subprocess.STDOUT,check=True)
   events=[json.loads(l)for l in log.read_text().splitlines()if l.startswith('{')];ends=[e for e in events if not e.get('Test')and e['Action']in('pass','fail')];assert len(ends)==1 and ends[0]['Action']=='pass';assert not any(e['Action']in('fail','skip')for e in events)
   output=collections.defaultdict(str)
   for e in events:output[e.get('Package'),e.get('Test')]+=e.get('Output','')
   rows=[]
   for value in output.values():
    for m in re.finditer(r'^(Benchmark\S+)-\d+\s+(\d+)\s+([\d.]+) ns/op\s+([\d.]+) B/op\s+([\d.]+) allocs/op',value,re.M):rows.append({'name':m[1],'iterations':int(m[2]),'ns_op':float(m[3]),'bytes_op':float(m[4]),'allocs_op':float(m[5])})
   assert len(rows)==args.expected_cases,len(rows)
   r['samples'].append({'trial':trial,'variant':variant,'command':cmd,'benchmarks':rows,'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()});print(trial,variant,'passed',flush=True)
 r['status']='passed'
except Exception as e:r['status']='failed';r['error']=str(e);raise
finally:args.output.write_text(json.dumps(r,indent=2)+'\n')
