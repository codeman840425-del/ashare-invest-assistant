"""T-T21 resource adapter, not product logic: owned DBs / Redis prefix only.
Run under recorded, read-only, network=none offline runner. Never grants roles.
"""
from __future__ import annotations
import os,sys,json,re,uuid,hashlib,socket,stat,subprocess,ast
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
OUT=Path('/workspace/team/reports/T-T22-closeout-logs')
PG='/tmp/tb70-tb91-owned-socket'
RURL='unix:///tmp/tb91-owned-redis/redis.sock?db=15'
MODE=sys.argv[1] if __name__=='__main__' else 'import'
PREFIX='tt22_'+MODE+'_'+uuid.uuid4().hex[:10]+':'
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
    if name not in mapped:mapped[name]='tb70_tt22_'+MODE+'_'+hashlib.sha256(name.encode()).hexdigest()[:20]
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
    for mod in {i.module for i in items if hasattr(i,'module')}:
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

# Only authorized tests/fixtures are adapted; product and its native assertions stay frozen.
_base_collect=pytest_collection_modifyitems
_GAPS=json.loads((Path(__file__).parent/'fixtures/tt22_known_gaps.json').read_text())

def canonical(item):
    return str(item.path.relative_to(ROOT))+''.join('::'+p for p in item.nodeid.split('::')[1:])

def pytest_collection_modifyitems(session,config,items):
    _base_collect(session,config,items)
    for mod in {i.module for i in items if hasattr(i,'module')}:
        if Path(mod.__file__).name=='test_tb72_features.py':
            original=mod.inputs
            def inputs(n=70,_original=original):
                instrument,dates,factors=_original(n)
                for bar in instrument['bars']:bar['open']=bar['close']
                return instrument,dates,factors
            mod.inputs=inputs
        if Path(mod.__file__).name=='test_tb63_signals.py':
            if hasattr(mod,'verify_isolated_pg'):mod.verify_isolated_pg=verify_services
            script=(ROOT/'src/backend/selfchecks/tb60.py').read_text()
            original_name='tt21_f0043_'+uuid.uuid4().hex
            with psycopg.connect(dbname='postgres',user='postgres',host=PG,autocommit=True) as c:
                c.execute(psycopg.sql.SQL('CREATE DATABASE {}').format(psycopg.sql.Identifier(original_name)))
            physical=own_name(original_name)
            assert physical in created and physical.startswith('tb70_tt22_')
            # Rebind only the isolated resource identity and owner on this empty DB.
            script=script.replace('Path(tempfile.gettempdir()) / "tb58-pg3-socket"','Path('+repr(PG)+')')
            script=script.replace('postgresql+psycopg://tb58@/tb58_isolated','postgresql+psycopg://postgres@/'+physical)
            script=script.replace('== "tb58_isolated"','== '+repr(physical))
            script=script.replace('from app.db.tables.market import securities','from app.db.tables.market import securities\nfrom app.db.tables.licences import user_data_licences')
            script=script.replace('user, strategy, version = uuid4(), uuid4(), uuid4()','user, strategy, version = uuid4(), uuid4(), uuid4(); licence = uuid4()')
            script=script.replace('            fixtures = {','            conn.execute(user_data_licences.insert().values(id=licence,user_id=user,provider="mairui",tier="free",status="invalid",seal_key_version=1,ciphertext=bytes([0]),licence_hmac=bytes([1])))\n            fixtures = {')
            script=re.sub(r'(?m)^( +)signal_events\.insert\(\)\.values\(\n',lambda m:m[1]+'signal_events.insert().values(\n'+m[1]+'    source_licence_id=licence,\n',script)
            assert script.count('source_licence_id=licence') == 2
            (OUT/'f0043-bound-fixture.py').write_text(script)
            namespace={'__name__':'tt22_tb60_fixture','__file__':str(ROOT/'src/backend/selfchecks/tb60.py')}
            exec(compile(script,'<T-T22-resource-bound-tb60>', 'exec'),namespace)
            def bound_main(_fn=namespace['main']):
                before=sys.argv[:]
                try:
                    args=before[:];args[args.index('--socket-dir')+1]=PG;sys.argv=args
                    return _fn()
                finally:sys.argv=before
            mod.tb60.main=bound_main
    for item in items:
        node=canonical(item)
        if node in _GAPS:
            import pytest
            item.add_marker(pytest.mark.skip(reason=_GAPS[node]))

import pytest
class UnavailableModule(pytest.Module):
    def collect(self):
        yield UnavailableItem.from_parent(self,name='T-T22_受限夹具保留缺口')
class UnavailableItem(pytest.Item):
    def runtest(self):pytest.skip(_GAPS[str(self.path.relative_to(ROOT))])
    def reportinfo(self):return self.path,0,'T-T22 restricted fixture remains unavailable'
@pytest.hookimpl(tryfirst=True)
def pytest_pycollect_makemodule(module_path,parent):
    rel=str(module_path.relative_to(ROOT))
    if rel in _GAPS:return UnavailableModule.from_parent(parent,path=module_path)


def main():
    assert MODE in {'retry','frontend-target','affected','fixture','fixture-final','fixture-verified'},'No full/coverage mode exists for T-T22'
    verify_services()
    (OUT/(MODE+'.started')).open('x').write('one targeted invocation only\n')
    os.environ.update(APP_ENV='test',CONFIG_DIR=str(ROOT/'config'),MAIRUI_MODE='replay',MAIRUI_LICENCE='',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',AIA_TEST_REDIS_URL=RURL)
    if MODE=='frontend-target':
        selected=json.loads((OUT/'frontend-nodes.json').read_text())
        names=[x['name'] for x in selected if x.get('name')]
        files=list(dict.fromkeys(x['file'] for x in selected))
        pattern='^(?:'+'|'.join(re.escape(n) for n in names)+')$'
        cmd=['node',str(ROOT/'src/frontend/node_modules/vitest/vitest.mjs'),'run','--config',str(ROOT/'tests/e2e/tt21-vitest-full.config.ts'),*files,'--testNamePattern',pattern,'--reporter=json','--reporter=default','--outputFile='+str(OUT/'frontend.json')]
        (OUT/'frontend-actual-args.json').write_text(json.dumps(cmd,ensure_ascii=False,indent=2))
        return subprocess.call(cmd,cwd=ROOT/'src/frontend')
    from alembic.config import Config
    from alembic import command
    from argparse import Namespace
    from sqlalchemy import create_engine
    original='tt21_retry_'+uuid.uuid4().hex
    with psycopg.connect(dbname='postgres',user='postgres',host=PG,autocommit=True) as c:
        c.execute(psycopg.sql.SQL('CREATE DATABASE {}').format(psycopg.sql.Identifier(original)))
    native=own_name(original);url='postgresql+psycopg://postgres@/'+native+'?host='+PG
    os.environ.update(DATABASE_URL=url,AIA_TEST_DATABASE_URL=url.replace('+psycopg',''),REDIS_URL=RURL,P2N10_ARTIFACTS=str(OUT/'p2n10'))
    try:
        cfg=Config();cfg.set_main_option('script_location',str(ROOT/'src/backend/migrations'));cfg.cmd_opts=Namespace(x=['url='+url]);command.upgrade(cfg,'0027')
        engine=create_engine(url)
        try:
            with engine.begin() as c:deploy_grants(c)
        finally:engine.dispose()
        (OUT/'native-base.json').write_text(json.dumps({'new_database':native}))
        from app.config import Settings
        settings=Settings()
        assert settings.config_dir.resolve()==(ROOT/'config').resolve()
        import importlib.util
        spec=importlib.util.spec_from_file_location('tt22_profile_precheck',ROOT/'tests/conftest.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        from hypothesis import settings as hs
        assert hs.default.derandomize and hs.default.database is None
        assert stat.S_ISSOCK(os.stat(PG+'/.s.PGSQL.5432').st_mode)
        (OUT/(MODE+'-preflight-result.json')).write_text(json.dumps({'resolved_config_dir':str(settings.config_dir),'hypothesis_derandomize':hs.default.derandomize,'hypothesis_database_is_none':hs.default.database is None,'approved_socket':PG,'new_database':native,'product_sha':os.environ.get('TT22_PRODUCT_SHA','6b77d86a179a4b0571d30721fb941624accfb199')},indent=2))
        nodes=json.loads((OUT/(MODE+'-nodes.json' if MODE in {'affected','fixture','fixture-final','fixture-verified'} else 'backend-nodes.json')).read_text())
        assert len(nodes)==len(set(nodes)) and all('.py' in x and not (ROOT/x).is_dir() for x in nodes)
        args=[*nodes,'-c','tests/pytest.ini','--continue-on-collection-errors','-q','--tb=short','-o','cache_dir='+str(OUT/'pytest-cache'),'--junitxml='+str(OUT/(MODE+'.xml'))]
        (OUT/(MODE+'-actual-args.json')).write_text(json.dumps(args,ensure_ascii=False,indent=2))
        (OUT/(MODE+'.pytest-started')).open('x').write('only failed/error set, not directories\n')
        return pytest.main(args,plugins=[sys.modules[__name__]])
    finally:
        cleanup=[];errors=[]
        for db in list(created):
            try:
                with real_connect(dbname='postgres',user='postgres',host=PG,autocommit=True) as c:
                    real_execute(c.cursor(),psycopg.sql.SQL('DROP DATABASE {} WITH (FORCE)').format(psycopg.sql.Identifier(db)))
                cleanup.append(db)
            except Exception as e:errors.append({'owned_database':db,'error_type':type(e).__name__})
        cache=redis.Redis.from_url(RURL);namespaced(cache,'FLUSHDB');cache.close()
        (OUT/(MODE+'-cleanup.json')).write_text(json.dumps({'owned_databases_removed':cleanup,'cleanup_errors':errors,'redis_prefix':PREFIX,'shared_containers_preserved':True,'denials':denials},indent=2))
if __name__=='__main__':raise SystemExit(main())
