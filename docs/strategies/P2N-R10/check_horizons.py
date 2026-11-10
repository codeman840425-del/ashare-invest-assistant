"""P2N-R10 documentary census only. No model, app import, DB or old test execution."""
from pathlib import Path
from collections import Counter
import json,re,copy

def fail(msg: object = "") -> None:
    """Explicit failure that survives python -O (unlike assert)."""
    raise AssertionError(msg)


def require(cond: object, msg: object = "") -> None:
    if not cond:
        fail(msg)

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
BASE=ROOT/'docs/strategies'
LEGAL=('intraday_t','short','swing','long')

def norm(text):return re.sub(r'[\s`*]','',text)
def parse_block(text,label):
    hits=re.findall(r'^```yaml '+label+r'\s*\n(.*?)^```',text,re.M|re.S)
    require(len(hits)==1, label)
    block=hits[0]
    def get(k):return re.search(r'^'+k+r':\s*(.*)$',block,re.M).group(1).strip()
    return get('key'),int(get('version_no')),[h.strip() for h in get('horizons').strip('[]').split(',')]

def _git_tracked(path: Path) -> bool | None:
    """T-A80 L-1 three-state tracking probe.

    Returns True if tracked (git ls-files --error-unmatch rc==0),
    False if confirmed untracked (rc==1),
    None if tracking cannot be determined (rc==128 / other rc / missing git /
    timeout / any exception) — fail-safe: caller must NOT ignore.
    """
    try:
        import subprocess
        r = subprocess.run(
            ['git', '-C', str(ROOT), 'ls-files', '--error-unmatch', str(path.relative_to(ROOT))],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=10,
        )
        if r.returncode == 0:
            return True
        if r.returncode == 1:
            return False
        return None
    except Exception:
        return None

def validate(data):
    files={}
    tracking_unknown=[]
    for p in BASE.rglob('*'):
        if not p.is_file() or HERE in p.parents:
            continue
        rel=str(p.relative_to(ROOT))
        is_pyc = p.suffix == '.pyc' or '__pycache__' in p.parts
        if is_pyc:
            tracked = _git_tracked(p)
            if tracked is None:
                tracking_unknown.append(rel)
                files[rel]=p  # do not ignore
                continue
            if tracked is False:
                continue  # confirmed untracked → ignore
            files[rel]=p  # tracked pyc stays
            continue
        files[rel]=p
    census=data['scope_snapshot'];require(len({f['path'] for f in census})==len(census))
    if set(files)!={f['path'] for f in census}:
        extra=sorted(set(files)-{f['path'] for f in census})
        missing=sorted({f['path'] for f in census}-set(files))
        parts=[]
        if tracking_unknown:
            parts.append('tracking_unknown:'+','.join(tracking_unknown))
        if extra:
            parts.append('extra:'+','.join(extra))
        if missing:
            parts.append('missing:'+','.join(missing))
        fail('scope files changed: refresh census; '+' ; '.join(parts))
    actual={}
    # All actual card fences, not merely catalog names; golden render inputs excluded explicitly.
    for path,p in files.items():
        if p.suffix!='.md':continue
        text=p.read_text()
        if re.search(r'^```yaml strategy-card\s*$',text,re.M):
            require(path.startswith('docs/strategies/cards/'), 'new formal-card location requires scope review')
            key,ver,hs=parse_block(text,'strategy-card')
            require(parse_block(text,'strategy-spec')==(key,ver,hs))
            scope='historical_frozen' if '/history/' in path else 'current_formal_L1_with_L2_spec'
            actual[(path,key,ver)]=(scope,hs)
            if scope=='historical_frozen':
                vm=re.search(r'\.v(\d+)\.md$',p.name);require(vm is not None, 'history file must be <key>.vN.md')  # T-R49: v2 frozen
                current=BASE/'cards'/(p.name[:vm.start()]+'.md')
                require(f'cards/history/{p.name}' in current.read_text() and f'v{vm.group(1)} 原文冻结' in current.read_text())
        elif re.match(r'# [A-Z]-\d\d .*知识卡 v\d+',text.splitlines()[0] if text else ''):
            require('当前状态：不可导入' in text)
            title=text.splitlines()[0];ver=int(re.search(r'知识卡 v(\d+)',title).group(1))
            identity=next(l for l in text.splitlines() if 'horizons `[' in l)
            key=re.search(r'key `([^`]+)`',identity).group(1)
            hs=re.search(r'horizons `\[([^]]+)\]`',identity).group(1).replace(' ','').split(',')
            actual[(path,key,ver)]=('research_blocked_not_importable',hs)
    # Research table has no strategy version_no: never pretend its document version is one.
    path='docs/strategies/catalog.md';text=(ROOT/path).read_text();require('不是正式策略卡' in text)
    translation={'日内做T':['intraday_t'],'短线':['short'],'波段':['swing'],'中长线':['long'],'全部':list(LEGAL),'波段/中长线':['swing','long']}
    for l in text.splitlines():
        if not re.match(r'^\| [GHTSWLN]-\d\d \|',l):continue
        cols=[c.strip() for c in l.split('|')[1:-1]]
        if len(cols)==7:actual[(path,cols[1],None)]=('catalog_research_not_formal_card',translation[cols[3]])
    rows=data['records'];require(len({r['record_id'] for r in rows})==len(rows))
    require(len(rows)==len(actual)==45)  # T-R49: +hold_risk_monitor v2 frozen; T-R55: +st_pullback_ma v1 frozen
    for r in rows:
        key=(r['path'],r['key'],r['version_no']);require(key in actual)
        scope,hs=actual[key];require((r['scope'],r['horizons'])==(scope,hs))
        require(hs and len(set(hs))==len(hs) and set(hs)<=set(LEGAL))
        require(r['runtime_lifecycle'] is None, 'document never proves runtime lifecycle')
        require(r['horizon']==(hs[0] if len(hs)==1 else None), 'no guessed unique fallback')
        require(r['classification']==('explicit_single' if len(hs)==1 else 'explicit_multi_no_unique_fallback'))
        if len(hs)>1:require(r['gap_reason'] and r['release_condition'])
        for ref in r['evidence']:
            lines=(ROOT/ref['path']).read_text().splitlines()
            require(ref['quote'] in lines[ref['line']-1])
        if scope=='catalog_research_not_formal_card':require(r['version_no'] is None and r['document_version']=='0.3.8')
        else:require(r['document_version']=='v'+str(r['version_no']))
        if scope=='research_blocked_not_importable':require(r['rc5_consume']=='excluded_research_no_runtime_version')
    for ref in data['authorities']:require(norm(ref['quote']) in norm((ROOT/ref['path']).read_text()), ref)
    for mirror in data['excluded_render_mirrors']:
        p=ROOT/mirror['path'];current=ROOT/mirror['current_source']
        require(parse_block(p.read_text(),'strategy-card')==parse_block(current.read_text(),'strategy-card'))
        key,ver,hs=parse_block(p.read_text(),'strategy-card');require((key,ver,hs)==(mirror['key'],mirror['version_no'],mirror['horizons']))
        require(not any(r['path']==mirror['path'] for r in rows))
    roles={f['path']:f['scope_role'] for f in census}
    require(roles['docs/strategies/_template.md']=='teaching_example_not_formal_card')
    require(roles['docs/strategies/system_components_T-R15.md']=='system_policy_component_not_strategy_version')
    require(all(roles[p]=='synthetic_golden_or_helper_not_strategy' for p in files if '/golden/' in p and not p.endswith('.card.tmpl')))
    require(data['rc5_boundary']['horizon_days_mapping']=={'intraday_t':1,'short':5,'swing':20,'long':20})
    require(data['rc5_boundary']['this_audit_changes_runtime'] is False)
    stats={'identity_records':len(rows),'source_identity_files':len({r['path'] for r in rows}),'scope_counts':dict(Counter(r['scope'] for r in rows)),'explicit_single_distribution':dict(Counter(r['horizon'] for r in rows if r['horizon'])),'multi_records':sum(r['horizon'] is None for r in rows),'source_field_repairs':0,'missing_horizons':0}
    require(stats==data['stats'])
    return stats

def run():
    data=json.loads((HERE/'horizon_inventory.json').read_text());stats=validate(data)
    # Mutation tests challenge actual source consistency, not expected labels.
    mutations=[]
    v=copy.deepcopy(data);v['records'].pop();mutations.append(v)
    v=copy.deepcopy(data);v['records'][0]['horizon']='swing';mutations.append(v) # multi H01 frozen
    v=copy.deepcopy(data);v['records'][1]['horizons']=['medium'];mutations.append(v)
    v=copy.deepcopy(data);v['records'][0]['scope']='current_formal_L1_with_L2_spec';mutations.append(v)
    v=copy.deepcopy(data);v['records'][0]['version_no']=99;mutations.append(v)
    v=copy.deepcopy(data);v['records'][0]['runtime_lifecycle']='published';mutations.append(v)
    v=copy.deepcopy(data);v['records'][0]['path']=data['excluded_render_mirrors'][0]['path'];mutations.append(v)
    v=copy.deepcopy(data);v['rc5_boundary']['horizon_days_mapping']['short']=1;mutations.append(v)
    rejected=0
    for v in mutations:
        try:validate(v)
        except (AssertionError,KeyError):rejected+=1
        else:raise AssertionError('mutated inventory accepted')
    require(rejected==8)
    print(json.dumps({'result':'PASS','stats':stats,'scope_files':len(data['scope_snapshot']),'mirrors_excluded':len(data['excluded_render_mirrors']),'negative_mutations_rejected':rejected,'runtime_verified':False,'limit':'document census/declared periods only; no business or old test execution'},ensure_ascii=False))
if __name__=='__main__':run()
