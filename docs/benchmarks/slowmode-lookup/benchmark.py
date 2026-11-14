#!/usr/bin/env python3
"""Compare the unchanged slowmode query with/without its proposed index."""
import argparse
import hashlib
import json
import pathlib
import statistics
import subprocess
import time
import uuid

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--workspace',type=pathlib.Path,required=True,help='Mattermax work/src/server')
parser.add_argument('--container',required=True,help='Disposable PostgreSQL Docker container')
parser.add_argument('--user',default='mmuser')
parser.add_argument('--database',default='mattermost_test')
parser.add_argument('--rows',type=int,default=1000000,help='Recent unrelated channel posts; additional fixtures are added')
parser.add_argument('--samples',type=int,default=20)
parser.add_argument('--trials',type=int,default=3)
parser.add_argument('--output',type=pathlib.Path,required=True)
args=parser.parse_args()
if min(args.rows,args.samples,args.trials)<1:parser.error('rows, samples and trials must be positive')
workspace=args.workspace.resolve();schema='slowmode_bench_'+uuid.uuid4().hex
migrations=workspace/'channels/db/migrations/postgres';index='idx_posts_channel_user_create_at'
up=(migrations/'000243_posts_channel_user_create_at.up.sql').read_text();down=(migrations/'000243_posts_channel_user_create_at.down.sql').read_text()
source=workspace/'channels/store/sqlstore/post_store.go'
channel='c'*26;quiet='q'*26;active='a'*26;system='s'*26;deleted='d'*26;now=int(time.time()*1000)
cases={'quiet_user':(quiet,0),'active_user':(active,now),'system_only':(system,0),'deleted_post':(deleted,now-120000)}

def sql(text):
    result=subprocess.run(['docker','exec','-i',args.container,'psql','-XqAt','-U',args.user,'-d',args.database,'-v','ON_ERROR_STOP=1'],input=text,text=True,capture_output=True,timeout=600)
    if result.returncode:raise RuntimeError(result.stderr.strip())
    return result.stdout.strip()

def scoped(text):return sql('SET search_path='+schema+';'+text)
def query(uid):return f"SELECT COALESCE(MAX(CreateAt),0) FROM Posts WHERE ChannelId='{channel}' AND UserId='{uid}' AND CreateAt>{now-3600000} AND Type NOT LIKE 'system_%'"
def json_stream(text):
    decoder=json.JSONDecoder();values=[]
    while text.strip():
        text=text.lstrip();value,at=decoder.raw_decode(text);values.append(value);text=text[at:]
    return values

def scan_metrics(node):
    result={'filtered_rows':node.get('Rows Removed by Filter',0)*node.get('Actual Loops',1)}
    for child in node.get('Plans',[]):result['filtered_rows']+=scan_metrics(child)['filtered_rows']
    return result

report={'status':'running','method':'Same unchanged slowmode SQL, actual Posts/index DDL from migrations20/80/102, synthetic sparse rows. Three alternating-order before/after trials by default. Query measurements use PostgreSQL EXPLAIN ANALYZE execution time after three warmups. Insert probes are bulk INSERT statements with EXPLAIN ANALYZE BUFFERS WAL after all read trials. Not HTTP throughput, request latency or production capacity.','settings':vars(args).copy(),'schema_cleaned':False,'read_trials':[],'write_trials':[],'index_builds':[],'source_sha256':{str(p.relative_to(workspace)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [source,migrations/'000243_posts_channel_user_create_at.up.sql',migrations/'000243_posts_channel_user_create_at.down.sql']}}
report['settings']['workspace']=str(workspace);report['settings']['output']=str(args.output)
created=False;indexed=False
try:
    sql('CREATE SCHEMA '+schema);created=True
    ddl='\n'.join((migrations/name).read_text() for name in ['000020_create_posts.up.sql','000080_posts_createat_id.up.sql','000102_posts_originalid_index.up.sql'])
    scoped(ddl)
    scoped(f"""INSERT INTO Posts(id,createat,userid,channelid,type,deleteat,message)
      SELECT substr(md5('busy'||n),1,26),{now}-n*2,substr(md5('other-user'||(n%1000)),1,26),'{channel}','',0,repeat('synthetic benchmark message ',2) FROM generate_series(1,{args.rows})n;
    INSERT INTO Posts(id,createat,userid,channelid,type,deleteat,message)
      SELECT substr(md5('history'||u||n),1,26),{now}-n*60000,u,substr(md5('other-channel'||(n%100)),1,26),'',0,repeat('synthetic benchmark message ',2) FROM unnest(ARRAY['{quiet}','{active}','{system}'])u CROSS JOIN generate_series(1,30000)n;
    INSERT INTO Posts(id,createat,userid,channelid,type,deleteat,message)
      SELECT substr(md5('system'||n),1,26),{now}-n,'{system}','{channel}','system_join_channel',0,repeat('synthetic benchmark message ',2) FROM generate_series(1,{args.rows//3})n;
    INSERT INTO Posts(id,createat,userid,channelid,type,deleteat,message) VALUES
      (substr(md5('active-target'),1,26),{now},'{active}','{channel}','',0,'active fixture'),
      (substr(md5('deleted-target'),1,26),{now}-120000,'{deleted}','{channel}','',{now},'deleted fixture');
    VACUUM ANALYZE Posts;""")
    report['fixture_rows']=int(scoped('SELECT count(*) FROM Posts'))
    report['postgres']=json.loads(sql("SELECT json_build_object('version',version(),'shared_buffers',current_setting('shared_buffers'),'random_page_cost',current_setting('random_page_cost'),'fsync',current_setting('fsync'),'synchronous_commit',current_setting('synchronous_commit'))"))
    def variant(name):
        global indexed
        wanted=name=='after'
        if wanted!=indexed:
            start=time.monotonic();scoped(up if wanted else down)
            if wanted:
                valid=scoped(f"SELECT i.indisvalid AND i.indisready FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid WHERE c.relname='{index}' AND c.relnamespace='{schema}'::regnamespace")
                assert valid=='t',valid
                report['index_builds'].append({'seconds':time.monotonic()-start,'bytes':int(scoped(f"SELECT pg_relation_size('{schema}.{index}')"))})
            indexed=wanted
            scoped('ANALYZE Posts;')
    for trial in range(args.trials):
        for name in (['before','after'] if trial%2==0 else ['after','before']):
            variant(name)
            for case,(uid,expected) in cases.items():
                assert int(scoped(query(uid)))==expected,(name,case)
                scoped((query(uid)+';')*3)
                plans=json_stream(scoped(('EXPLAIN(ANALYZE,BUFFERS,FORMAT JSON) '+query(uid)+';')*args.samples))
                assert len(plans)==args.samples
                row={'trial':trial,'variant':name,'case':case,'execution_ms':[p[0]['Execution Time'] for p in plans],'first_plan':plans[0],'first_filtered_rows':scan_metrics(plans[0][0]['Plan'])['filtered_rows']}
                report['read_trials'].append(row)
                print(name,trial,case,round(statistics.mean(row['execution_ms']),4),flush=True)
    for trial in range(args.trials):
        for name in (['before','after'] if trial%2==0 else ['after','before']):
            variant(name)
            prefix=f'write-{trial}-{name}-'
            plan=json.loads(scoped(f"EXPLAIN(ANALYZE,BUFFERS,WAL,FORMAT JSON) INSERT INTO Posts(id,createat,userid,channelid,type,deleteat,message) SELECT substr(md5('{prefix}'||n),1,26),{now}+n,substr(md5('other-user'||(n%1000)),1,26),'{channel}','',0,repeat('synthetic benchmark message ',2) FROM generate_series(1,5000)n;"))
            report['write_trials'].append({'trial':trial,'variant':name,'rows':5000,'execution_ms':plan[0]['Execution Time'],'plan':plan})
    report['summary']={}
    for case in cases:
        report['summary'][case]={}
        for name in ['before','after']:
            selected=[r for r in report['read_trials'] if r['case']==case and r['variant']==name];means=[statistics.mean(r['execution_ms']) for r in selected]
            report['summary'][case][name]={'median_trial_mean_ms':statistics.median(means),'trial_mean_range_ms':[min(means),max(means)],'filtered_rows':[r['first_filtered_rows'] for r in selected]}
    report['write_summary']={name:{'median_batch_ms':statistics.median(r['execution_ms'] for r in report['write_trials'] if r['variant']==name),'batch_range_ms':[min(r['execution_ms'] for r in report['write_trials'] if r['variant']==name),max(r['execution_ms'] for r in report['write_trials'] if r['variant']==name)]} for name in ['before','after']}
    variant('after');report['final_index_bytes']=int(scoped(f"SELECT pg_relation_size('{schema}.{index}')"))
    variant('before');assert scoped(f"SELECT to_regclass('{schema}.{index}') IS NULL")=='t'
    variant('after');assert int(scoped(query(deleted)))==cases['deleted_post'][1];report['up_down_up_verified']=True
    report['status']='passed'
except Exception as error:
    report['status']='failed';report['error']=str(error);raise
finally:
    if created:sql('DROP SCHEMA '+schema+' CASCADE');report['schema_cleaned']=True
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2)+'\n')
