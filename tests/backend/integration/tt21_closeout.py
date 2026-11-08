"""T-T21 resource adapter, not product logic: owned DBs / Redis prefix only.
Run under recorded, read-only, network=none offline runner. Never grants roles.
"""
from __future__ import annotations
import os,sys,json,re,uuid,hashlib,socket,stat,subprocess,ast
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
OUT=Path('/workspace/team/reports/T-T21-closeout-logs')
PG='/tmp/tb70-tb91-owned-socket'
RURL='unix:///tmp/tb91-owned-redis/redis.sock?db=15'
MODE=sys.argv[1] if __name__=='__main__' else 'import'
PREFIX='tt21_'+MODE+'_'+uuid.uuid4().hex[:10]+':'
created=set();mapped={};denials=[]
sys.path.insert(0,str(ROOT/'src/backend'));sys.path.insert(0,str(Path(__file__).parent))
if __name__=='__main__':sys.modules['tt21_closeout']=sys.modules[__name__]
def verify_services():
    rows=json.loads((OUT/'resources.json').read_text())
    assert [(x['Name'],x['network'],x['running']) for x in rows]==[('/o33-review-pg','none',True),('/o33-review-redis','none',True)]
    assert rows[0]['Id']=='5dec46709f06366bf33512765158376bfd93e304103a465b1ab8b5350493a5ff'
    assert rows[1]['Id']=='9ba56c8cfc1e3fa9ff975e8d8b8e22463ef1fa4f0fa70463aaf0d1e8089e16c5'
    for x in rows:assert not x['ports'] and x['labels']['aia.task']=='T-O33-review'
    for p in [PG+'/.s.PGSQL.5432','/tmp/tb91-owned-redis/redis.sock']:assert stat.S_ISSOCK(os.stat(p).st_mode)
    return OUT/'p2n10/runtime'
def audit(event,args):
    if event=='open':
        p=str(args[0]);forbidden=any(x in p for x in ['/private-samples/','/H-01','/W-01','/docs/strategies/cards/','/team/runtime/'])
        if forbidden:denials.append('formal-private-file');raise PermissionError('T-T21 forbidden source')
    if event=='socket.connect' and args[0].family==socket.AF_UNIX:
        p=str(args[1])
        if p not in [PG+'/.s.PGSQL.5432','/tmp/tb91-owned-redis/redis.sock'] and not p.startswith('/tmp/'):
            denials.append('foreign-unix');raise PermissionError('T-T21 foreign Unix socket')
    # Internet is blocked by the runner network namespace, including descendants.
sys.addaudithook(audit)
import psycopg,redis
from psycopg.conninfo import conninfo_to_dict
real_connect=psycopg.connect
real_execute=psycopg.Cursor.execute
class ResourceBlocked(psycopg.OperationalError):pass
def own_name(name):
    if name not in mapped:mapped[name]='tb70_tt21_'+MODE+'_'+hashlib.sha256(name.encode()).hexdigest()[:20]
    return mapped[name]
def guarded_execute(self,query,params=None,**kwargs):
    q=query.as_string(self.connection) if hasattr(query,'as_string') else str(query)
    scrub=re.sub(r'--[^\n]*','',q)
    if re.search(r'\b(?:CREATE|ALTER|DROP)\s+(?:ROLE|USER)\b|\bALTER\s+SYSTEM\b',scrub,re.I):
        denials.append('cluster-role-change');raise ResourceBlocked('T-T21 cluster role changes prohibited')
    match=re.match(r'\s*(CREATE|DROP|ALTER)\s+DATABASE\s+"?([a-zA-Z0-9_]+)"?',scrub,re.I)
    if match:
        action,name=match.groups()
        if name in ('postgres','template0','template1','t_o33_acl','t_o33_review') or not re.match(r'(?:tb|p2n|tt21|aia_test)',name):raise ResourceBlocked('foreign database DDL denied')
        target=own_name(name)
        if action.upper()!='CREATE' and target not in created:raise ResourceBlocked('database not created by this run')
        q=re.sub(r'(\bDATABASE\s+)"?'+re.escape(name)+r'"?',lambda m:m[1]+'"'+target+'"',q,count=1,flags=re.I)
        result=real_execute(self,q,params,**kwargs)
        if action.upper()=='CREATE':
            created.add(target)
            (OUT/(MODE+'-created.json')).write_text(json.dumps(sorted(created)))
        if action.upper()=='DROP':created.discard(target)
        return result
    if self.connection.info.dbname=='postgres' and not re.match(r'\s*(SELECT|SHOW|SET|RESET)\b',scrub,re.I):raise ResourceBlocked('admin metadata connection is read only')
    return real_execute(self,query,params,**kwargs)
def guarded_connect(conninfo='',**kwargs):
    info=conninfo_to_dict(conninfo,**{k:v for k,v in kwargs.items() if k in ['host','port','dbname','user','password','options']})
    db=info.get('dbname','postgres');host=info.get('host','')
    if host not in [PG,'localhost','127.0.0.1','::1']:raise ResourceBlocked('T-T21 unapproved PG socket/host')
    if host==PG:
        if db!='postgres':
            actual=db if db in created else mapped.get(db)
            if actual not in created:raise ResourceBlocked('T-T21 only newly created databases permitted')
            info['dbname']=actual
        for k in ['host','port','dbname','user','password','options']:kwargs.pop(k,None)
        conninfo=psycopg.conninfo.make_conninfo(**info)
    return real_connect(conninfo,**kwargs)
psycopg.connect=guarded_connect;psycopg.Cursor.execute=guarded_execute
# Prefix physical keys without replacing any API/worker behavior. Never FLUSH the shared DB.
raw_redis=redis.Redis.execute_command
# The only Lua allowed is the frozen public rate-limit script, reviewed to
# access keys exclusively through KEYS. EVAL avoids global SCRIPT LOAD/cache changes.
_abuse=ast.parse((ROOT/'src/backend/app/auth/abuse.py').read_text())
_lua=next(n.value.value for n in _abuse.body if isinstance(n,ast.AnnAssign) and isinstance(n.target,ast.Name) and n.target.id=='_SLIDING_WINDOW_LUA')
_safe_lua={hashlib.sha1(_lua.encode()).hexdigest():_lua}
single={'GET','SET','SETNX','GETSET','GETDEL','INCR','DECR','INCRBY','DECRBY','LPUSH','RPUSH','LPOP','RPOP','LLEN','LRANGE','LTRIM','EXPIRE','PEXPIRE','TTL','PTTL','HSET','HGET','HGETALL','HDEL','HLEN','SADD','SREM','SMEMBERS','SCARD','ZADD','ZRANGE','ZREM','ZCARD','TYPE'}
def key(x):
    return PREFIX.encode()+x if isinstance(x,bytes) else PREFIX+str(x)
def transform(args):
    a=list(args);cmd=str(a[0]).upper()
    if cmd in {'EVALSHA','EVAL'}:
        script=a[1].decode() if isinstance(a[1],bytes) else a[1]
        body=_safe_lua.get(script) if cmd=='EVALSHA' else script if script==_lua else None
        if body is None:raise ResourceBlocked('T-T21 unreviewed Lua denied')
        count=int(a[2]);assert 0<=count<=len(a)-3
        a[0]='EVAL';a[1]=body;a[3:3+count]=[key(x) for x in a[3:3+count]]
    elif cmd in single:a[1]=key(a[1])
    elif cmd in {'DEL','UNLINK','MGET','EXISTS'}:a[1:]=[key(x) for x in a[1:]]
    elif cmd in {'PING','INFO','TIME','DBSIZE','CLIENT SETINFO','CLIENT SETNAME'}:pass
    else:raise ResourceBlocked('T-T21 Redis unsupported command denied: '+cmd)
    return a

def namespaced(self,*args,**kwargs):
    cmd=str(args[0]).upper()
    if cmd in {'FLUSHDB','FLUSHALL'}:
        cursor=0
        while True:
            cursor,keys=raw_redis(self,'SCAN',cursor,'MATCH',PREFIX+'*','COUNT',1000)
            if keys:raw_redis(self,'DEL',*keys)
            if not cursor:break
        return True
    return raw_redis(self,*transform(args),**kwargs)
redis.Redis.execute_command=namespaced
raw_pipe=redis.client.Pipeline.execute_command
def pipe(self,*args,**kwargs):return raw_pipe(self,*transform(args),**kwargs)
redis.client.Pipeline.execute_command=pipe
import redis.asyncio as aioredis
raw_async=aioredis.Redis.execute_command
async def async_namespaced(self,*args,**kwargs):return await raw_async(self,*transform(args),**kwargs)
aioredis.Redis.execute_command=async_namespaced
raw_async_pipe=aioredis.client.Pipeline.execute_command
def async_pipe(self,*args,**kwargs):return raw_async_pipe(self,*transform(args),**kwargs)
aioredis.client.Pipeline.execute_command=async_pipe

def deploy_grants(conn):
    # Roles already exist and are checked; omit cluster-wide bootstrap/password/member changes.
    text=(ROOT/'deploy/db/roles/grants.sql').read_text();local=text[text.index('DO $grants$'):]
    assert not re.search(r'\b(?:CREATE|ALTER|DROP)\s+(?:ROLE|USER)\b',re.sub(r'--[^\n]*','',local),re.I)
    conn.connection.driver_connection.execute(local)

def pytest_collection_modifyitems(session,config,items):
    for mod in {i.module for i in items}:
        if mod.__name__.startswith('selfchecks.'):
            for k,v in list(vars(mod).items()):
                if k=='SOCKET' and isinstance(v,(str,Path)):setattr(mod,k,type(v)(PG))
                elif k=='REDIS' and isinstance(v,str):setattr(mod,k,RURL)
                elif isinstance(v,str) and re.search(r'(^DB$|DSN|PGROOT|PG_ROOT|BASE_URL|ROOT_URL)',k) and ('postgresql' in v or 'host=/tmp/' in v):
                    new=re.sub(r'host=/tmp/[^&\s]+','host='+PG,v)
                    if k=='DB' and 'postgresql' in new:
                        native=json.loads((OUT/'native-base.json').read_text())['new_database']
                        new=re.sub(r'(?<=@/)[^?]+',native,new)
                    setattr(mod,k,new)
        if hasattr(mod,'deploy_grants'):mod.deploy_grants=deploy_grants

def main():
    verify_services();os.environ.update(APP_ENV='test',MAIRUI_MODE='replay',MAIRUI_LICENCE='',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',AIA_TEST_REDIS_URL=RURL)
    sentinel=OUT/(MODE+'.started');sentinel.open('x').write('one authorized invocation\n')
    if MODE=='frontend':
        cmd=['node',str(ROOT/'src/frontend/node_modules/vitest/vitest.mjs'),'run','--config',str(ROOT/'tests/e2e/tt21-vitest-full.config.ts'),'--reporter=json','--reporter=default','--outputFile='+str(OUT/'frontend.json')]
        return subprocess.call(cmd,cwd=ROOT/'src/frontend')
    name='tt21_'+MODE+'_'+uuid.uuid4().hex
    with psycopg.connect(dbname='postgres',user='postgres',host=PG,autocommit=True) as admin:
        admin.execute(psycopg.sql.SQL('CREATE DATABASE {}').format(psycopg.sql.Identifier(name)))
    actual=mapped[name];url='postgresql+psycopg://postgres@/'+actual+'?host='+PG
    os.environ['AIA_TEST_DATABASE_URL']=url.replace('+psycopg','');os.environ['DATABASE_URL']=url;os.environ['REDIS_URL']=RURL
    try:
        if MODE=='migrate':
            from alembic.config import Config
            from alembic import command
            from argparse import Namespace
            cfg=Config();cfg.set_main_option('script_location',str(ROOT/'src/backend/migrations'));cfg.cmd_opts=Namespace(x=['url='+url]);command.upgrade(cfg,'0027')
            with psycopg.connect(dbname=actual,user='postgres',host=PG) as c:
                version=c.execute('select version_num from alembic_version').fetchone()[0]
                (OUT/'migration-result.json').write_text(json.dumps({'new_database':actual,'from':'empty','actual_version':version}));assert version=='0027'
            return 0
        if MODE=='full':
            from alembic.config import Config
            from alembic import command
            from argparse import Namespace
            from sqlalchemy import create_engine
            native_name='tt21_native_'+uuid.uuid4().hex
            with psycopg.connect(dbname='postgres',user='postgres',host=PG,autocommit=True) as c:
                c.execute(psycopg.sql.SQL('CREATE DATABASE {}').format(psycopg.sql.Identifier(native_name)))
            native=mapped[native_name];native_url='postgresql+psycopg://postgres@/'+native+'?host='+PG
            cfg=Config();cfg.set_main_option('script_location',str(ROOT/'src/backend/migrations'));cfg.cmd_opts=Namespace(x=['url='+native_url]);command.upgrade(cfg,'0027')
            engine=create_engine(native_url)
            try:
                with engine.begin() as c:deploy_grants(c)
            finally:engine.dispose()
            (OUT/'native-base.json').write_text(json.dumps({'new_database':native,'fixture_setup_only':True}))
        import pytest
        if MODE=='full':args=['src/backend/selfchecks','tests/backend','tests/replay','--ignore=tests/backend/integration/test_p2n10_loop.py','--continue-on-collection-errors']
        elif MODE=='p2n':os.environ['P2N10_ARTIFACTS']=str(OUT/'p2n10');args=['tests/backend/integration/test_p2n10_loop.py','-k','daily_risk_tracking']
        else:raise ValueError(MODE)
        args+=['-c','tests/pytest.ini','-q','--tb=short','-o','cache_dir='+str(OUT/('pytest-cache-'+MODE)),'--junitxml='+str(OUT/(MODE+'.xml'))]
        (OUT/(MODE+'.pytest-started')).open('x').write('single actual pytest invocation\n')
        return pytest.main(args,plugins=[sys.modules[__name__]])
    finally:
        cleanup=[];cleanup_errors=[]
        for db in list(created):
            try:
                with real_connect(dbname='postgres',user='postgres',host=PG,autocommit=True) as c:
                    real_execute(c.cursor(),psycopg.sql.SQL('DROP DATABASE {} WITH (FORCE)').format(psycopg.sql.Identifier(db)))
                created.discard(db);cleanup.append(db)
            except Exception as exc: cleanup_errors.append({'owned_database':db,'error_type':type(exc).__name__})
        cache=redis.Redis.from_url(RURL);namespaced(cache,'FLUSHDB');cache.close()
        (OUT/(MODE+'-cleanup.json')).write_text(json.dumps({'only_task_databases_removed':cleanup,'redis_prefix_removed':PREFIX,'containers_preserved':True,'cleanup_errors':cleanup_errors,'denials':denials},indent=2))
if __name__=='__main__':raise SystemExit(main())
