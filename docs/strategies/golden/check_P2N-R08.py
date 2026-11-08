"""R08-only offline oracle check. Does not import application/model/generator code."""
from pathlib import Path
from decimal import Decimal as D, localcontext
from fractions import Fraction
from datetime import datetime
from collections import Counter
import json
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
FILE = HERE / 'P2N-R08_golden.json'

def tail(seq, predicate):
    count = 0
    for value in reversed(seq):
        if not predicate(value):
            break
        count += 1
    return count

def tanh_series(x):
    """Independent of finalizer's Decimal.exp: sinh/cosh Taylor series."""
    with localcontext() as ctx:
        ctx.prec = 90
        sinh = st = x
        cosh = ct = D(1)
        for k in range(1, 250):
            st *= x*x / D((2*k)*(2*k+1))
            ct *= x*x / D((2*k-1)*(2*k))
            sinh += st
            cosh += ct
            if abs(st) < D('1e-85') and abs(ct) < D('1e-85'):
                break
        else:
            raise AssertionError('Taylor series failed to converge')
        return sinh / cosh

def evaluate(c):
    if c["kind"].startswith("t33_"):
        return {"results":[evaluate_t33(c["kind"],v) for v in c["input"]["scenarios"]]}
    i = c['input']; kind = c['kind']
    if kind == 'rc5_closed':
        assert i['all_closed'] and i['complete']
        n = tail(i['pnl'], lambda x: D(x) < 0)
        return {'trailing_losses':n, 'triggered':n >= 3}
    if kind == 'rc5_nav':
        path = i['path']
        if path[-1] is None:
            return {'drawdown_pct':None, 'state':'unknown'}
        peak = max(D(v) for v in path); current = D(path[-1])
        assert peak > 0
        dd = (peak-current)*100/peak
        # Cross-multiplied threshold test avoids any rounding around 10%.
        hit = current*10 <= peak*9
        return {'drawdown_pct':dd, 'state':'triggered' if hit else 'ok'}
    if kind == 'rc5_sim':
        assert i['failure_labels_preclassified']
        n = tail(i['failures'], lambda x: x is True)
        return {'trailing_failures':n, 'triggered':n >= 5}
    if kind == 'rc6_plan':
        assert i['plan_resolved_at_trade']
        check = i['check']
        if check == 'opposite_side':
            hit = (i['plan_side'],i['trade_side']) in [('buy','sell'),('sell','buy')]
        elif check == 'qty_over_plan':
            hit = D(i['trade_qty'])-D(i['planned_qty']) > 0
        elif check == 'held_after_invalidation':
            hit = i['invalidated'] and D(i['held_qty']) > 0
            if i['invalidated']:
                assert datetime.fromisoformat(i['invalidated_at']) < datetime.fromisoformat(i['trade_at'])
        elif check == 'buy_without_stop':
            hit = i['trade_side'] == 'buy' and i['stop_loss'] is None
        elif check == 'buy_during_wait':
            hit = i['plan_side'] == 'wait' and i['trade_side'] == 'buy'
        else:
            raise AssertionError(check)
        return {'check':check,'violated':hit}
    if kind == 'weight':
        n,w = i['n'],i['wins']
        assert isinstance(n,int) and 0 <= w <= n
        if n < 20:
            return {'computed_weight':D(1),'applied_weight':D(1)}
        with localcontext() as ctx:
            ctx.prec=80
            fraction = Fraction(2*w+10,2*n+20)
            smooth = D(fraction.numerator)/D(fraction.denominator)
            e = tanh_series(D(i['avg_excess_pct'])/5)
            # Algebraically reduced expression, separate from finalizer formula.
            raw = D('0.4') + D('1.2')*smooth + D('0.4')*e
            value = D('.3') if raw < D('.3') else D('1.2') if raw > D('1.2') else raw
            return dict(smoothed_win_rate=smooth,excess_term=e,raw=raw,computed_weight=value,applied_weight=value if i['auto_downweight'] else D(1))
    if kind == 'clamp':
        v = D(i['raw'])
        return {'weight':D('.3') if v < D('.3') else D('1.2') if v > D('1.2') else v}
    if kind == 'health':
        state = i['state']; review=False
        assert i['consecutive_trading_days'] and not i['internal_evaluation_enabled']
        assert set(i['prior_streaks'].values()) == {0}
        weights = [D(w) for w in i['site_daily_weights']]
        # Batch ending at evaluation: prior streaks zero; transitions at threshold day.
        low=high=bad=0
        if i['n'] >= 20 and state in ('published','observing'):
            for value in weights:
                low = low+1 if value < D('.8') else 0
                high = high+1 if value >= D('.9') else 0
                bad = bad+1 if value < D('.6') else 0
                if state == 'published' and low >= 5:
                    state = 'observing'
                elif state == 'observing' and high >= 10:
                    state = 'published'
                if state == 'observing' and bad >= 20:
                    review=True
        return {'state':state,'notify_admin_review':review,'auto_retired':False}
    if kind == 'health_internal_entry':
        state=i['state']
        assert i['internal_evaluation_enabled'] and D(i['baseline_robustness']) > 0
        if i['n']>=20 and D(i['robustness'])*100 < D(i['baseline_robustness'])*70:
            state='observing'
        return {'state':state}
    if kind == 'evaluation_state':
        state = 'disabled' if not i['enabled'] else 'triggered' if i['known_trigger'] else 'ok' if i['all_required_inputs_complete'] else 'unknown'
        return {'state':state}
    if kind == 'rc5_correction':
        before=tail(i['before_pnl'], lambda x:D(x)<0)
        after=tail(i['after_void_effective_pnl'], lambda x:D(x)<0)
        return {'before_losses':before,'after_losses':after,'after_triggered':after>=3,'auto_resume_instance':False}
    if kind == 'rc6_asof':
        visible=[v for v in i['versions'] if datetime.fromisoformat(v['created_at']) < datetime.fromisoformat(i['trade_at'])]
        assert len(visible)==1 and visible[0]['id']==i['resolved_version_at_trade']
        return {'selected_plan_version':visible[0]['id'],'opposite_side':visible[0]['side']!=i['trade_side']}
    if kind == 'rc6_replay':
        assert i['violation_precomputed']
        return {'logical_risk_events':len({(i['logical_event_key'],v) for v in i['deliveries']})}
    if kind == 'rc6_missing_plan':
        assert i['effective_plan_at_trade'] is None
        return {'state':'unknown','gap':True,'violation':None}
    if kind == 'pause_release':
        if i['operation']=='user_resume' and i['lifecycle'] in ('simulating','retired'):
            return dict(status='paused',pause_fields_cleared=False,error='STRATEGY_VERSION_NOT_RUNNABLE',http=409,**{k:i[k] for k in ('paused_by','pause_reason_code','paused_until')})
        release = i['operation']=='user_resume'
        if i['operation']=='schedule' and i['paused_by']=='system':
            now,until = map(datetime.fromisoformat,(i['now'],i['paused_until']))
            assert now!=until  # Exact equality deliberately not adjudicated here.
            release=now>until
        result={'status':'active' if release else 'paused','pause_fields_cleared':release}
        if release and i['operation']=='user_resume' and i['paused_by']=='system':
            result['released_reason_code']='LOSS_STREAK_PAUSE'
        result.update({k:None if release else i[k] for k in ('paused_by','pause_reason_code','paused_until')})
        return result
    if kind == 'pause_trigger':
        assert i['enabled'] and i['known_trigger']
        return {'risk_state':'triggered','instance_status':'paused' if i['pause_on_trigger'] else 'active','pause_reason_code':'LOSS_STREAK_PAUSE' if i['pause_on_trigger'] else None}
    if kind == 'ranking_only':
        return {'lifecycle':i['lifecycle'],'rule_payload':i['rule_payload'],'ranking_weight':i['weight'] if i['auto_downweight'] else '1'}
    raise AssertionError(kind)

def equal(actual, expected, tolerance):
    if isinstance(actual, D):
        assert abs(actual-D(expected)) <= tolerance, (actual,expected)
    elif isinstance(actual, dict):
        assert actual.keys()==expected.keys(),(actual.keys(),expected.keys())
        for key in actual:
            equal(actual[key],expected[key],tolerance)
    else:
        assert type(actual) is type(expected) and actual==expected,(actual,expected)

def norm(s):
    return re.sub(r'[\s`*]','',s)

def run():
    data=json.loads(FILE.read_text(),parse_float=lambda s:(_ for _ in ()).throw(AssertionError('binary float JSON forbidden')))
    assert data['fictitious'] is True and data['task']=='P2N-R08'
    for source in data['source_registry'].values():
        assert norm(source['quote']) in norm((ROOT/source['file']).read_text()),source
    # Explicit algebraic/analytic anchors independent of stored model notes.
    assert tanh_series(D(0))==0
    assert abs(tanh_series(D(1))+tanh_series(D(-1))) < D('1e-75')
    assert D('.3') < D('.4')+D('1.2')*D(5)/30 == D('.6')
    ids=set();ready=blocked=0
    for c in data['cases']:
        assert c['id'] not in ids;ids.add(c['id'])
        assert c['steps'] and c['source_refs'] and c['units'] and c['precision']
        assert set(c['source_refs']) <= data['source_registry'].keys()
        if c['case_status']=='blocked':
            assert c['expected'] is None and c['kind']=='spec_ambiguity' and c['block_reason']=='spec_ambiguity' and c['question']
            blocked+=1
            continue
        assert c['case_status']=='ready'
        tol=D(c['precision']['oracle_abs_tolerance'])
        assert D(0)<=tol<=D('1e-12')
        try:
            equal(evaluate(c),c['expected'],tol)
        except AssertionError as exc:
            raise AssertionError(c['id']) from exc
        ready+=1
    assert ready==92 and blocked==0
    matrix=Counter(c['kind'] for c in data['cases'] if c['case_status']=='ready')
    assert matrix['rc6_plan']==10 and matrix['clamp']==6
    checks={c['input']['check'] for c in data['cases'] if c['kind']=='rc6_plan'}
    assert checks=={'opposite_side','qty_over_plan','held_after_invalidation','buy_without_stop','buy_during_wait'}
    # Negative-oracle checks: reject corruption at high-risk threshold boundaries.
    rejected=0
    for case in [next(c for c in data['cases'] if c['kind']==k) for k in ('rc5_nav','rc6_plan','weight','health')]:
        wrong=dict(case['expected']); key=next(iter(wrong));wrong[key]='CORRUPTED'
        try:equal(evaluate(case),wrong,D(case['precision']['oracle_abs_tolerance']))
        except (AssertionError, ArithmeticError):rejected+=1
    assert rejected==4
    print(json.dumps({'ready_pass':ready,'blocked_not_run':blocked,'negative_oracles_rejected':rejected,'coverage':matrix},ensure_ascii=False))


# R08b unit projections, not complete HTTP/event payloads. Independent input-only
# oracles: do not read expected, model draft, or application implementation.
def expiry(v):
    from datetime import datetime, time
    t=datetime.fromisoformat(v['trigger_at']); days=v['calendar']
    start=next((j for j,day in enumerate(days) if day>t.date().isoformat() or (day==t.date().isoformat() and t.time()<=time(15))),None)
    if start is None or start+v['pause_days']>=len(days):
        return {'day0':None,'paused_until':None,'gap':True}
    return {'day0':days[start],'paused_until':days[start+v['pause_days']]+'T15:00:00+08:00','gap':False}

def evaluate_t33(kind,v):
    if kind=='t33_sim':
        mapping={'intraday_t':1,'short':5,'swing':20,'long':20}
        picked={};gap=set()
        for o in v['observations']:
            if o['owner']!='self' or o['strategy_version']!=v['strategy_version']:continue
            horizon=o['horizon'] or v['version_horizon']
            if horizon not in mapping:
                gap.add('sim_fail_horizon_unknown');continue
            if o['horizon_days']!=mapping[horizon]:continue
            key=(o['suggestion_id'],o['strategy_version'],o['horizon_days'])
            old=picked.get(key)
            if old is None or (o['instance_created_at'],o['instance_id'])<(old['instance_created_at'],old['instance_id']):picked[key]=o
        n=0
        for o in sorted(picked.values(),key=lambda x:(x['exit_at'],x['suggestion_id'])):
            if o['state']=='complete':
                assert type(o['direction_correct']) is bool
                n=0 if o['direction_correct'] else n+1
        return {'trailing_failures':n,'triggered':n>=5,'gap_codes':sorted(gap)}
    if kind=='t33_closed':
        accounts={};closed=[];gap=False
        for f in sorted(v['fills'],key=lambda x:(x['executed_at'],x['id'])):
            key=(f['account'],f['security']);q,cost=accounts.get(key,(D(0),D(0)))
            qty,price,fee=map(D,(f['qty'],f['price'],f['fee']))
            if q==0 and f['side']=='sell':gap=True;continue
            if f['side']=='buy':q+=qty;cost-=qty*price+fee
            else:q-=qty;cost+=qty*price-fee
            assert q>=0
            accounts[key]=(q,cost)
            if q==0:
                closed.append((f['executed_at'],f['id'],cost));accounts[key]=(D(0),D(0))
        closed.sort();n=0
        for _,_,profit in closed:
            if profit<0:n+=1
            elif profit>0:n=0
        return {'closed_pnl':[format(x[2].normalize(),'f') for x in closed],'trailing_losses':n,'triggered':n>=3,'gap':gap}
    if kind=='t33_expiry':return expiry(v)
    if kind=='t33_recovery':
        n=0;state=v['state']
        for w,r in zip(v['weights'],v['robustness']):
            ok=v['n']>=20 and D(w)>=D('.9') and (not v['enabled'] or D(r)>=D(v['baseline'])*D(v['recover_ratio']))
            n=n+1 if ok else 0
            if n>=10 and state=='observing':state='published'
        return {'state':state,'joint_streak':n}
    if kind=='t33_qty':
        p=v['plan'];q=D(0)
        for f in v['trades']:
            if not f['voided'] and all(f[k]==p[k] for k in ['account','security','side']) and f['plan_version']==p['id'] and p['from']<=f['executed_at']<p['until']:q+=D(f['qty'])
        return {'cumulative_qty':format(q,'f'),'triggered':q>D(p['qty']),'logical_events':int(q>D(p['qty']))}
    if kind=='t33_version':
        unknown={'selected':None,'state':'unknown','opposite_side':None,'gap':True}
        if 'trade_date' in v:
            day=v['trade_date']
            if any(any(t and t[:10]==day for t in (p['from'],p['until'])) for p in v['versions']):return unknown
            at=day+'T15:00:00+08:00'
        else:at=v['trade_at']
        eligible=[p for p in v['versions'] if p['from']<=at and (p['until'] is None or at<p['until'])]
        if not eligible:return unknown
        same=[p for p in eligible if p['side']==v['trade_side']]
        choices=same or eligible;latest=max(p['from'] for p in choices)
        chosen=min((p for p in choices if p['from']==latest),key=lambda x:x['id'])
        return {'selected':chosen['id'],'state':'ok','opposite_side':not bool(same),'gap':False}
    if kind=='t33_gap':
        low=high=0;state=v['state'];gap=False
        for w in v['weights']:
            if w is None:low=high=0;gap=True;continue
            if v['n']<20:continue
            low=low+1 if D(w)<D('.8') else 0
            high=high+1 if D(w)>=D('.9') else 0
            if state=='published' and low>=5:state='observing'
            elif state=='observing' and high>=10:state='published'
        return {'state':state,'low_streak':low,'high_streak':high,'gap':gap}
    if kind=='t33_edge':
        edge=D(v['before'])<D(v['threshold'])<=D(v['after']);until=v['existing_until'];status='paused'
        if edge:
            new=expiry(v);assert not new['gap'];until=max(until,new['paused_until'])
        elif v['at_expiry'] and v['trigger_at']>=until:until=None;status='active'
        return {'edge':edge,'paused_until':until,'status':status,'risk_triggered':D(v['after'])>=D(v['threshold'])}
    if kind=='t33_resume':
        out={'status':'paused','paused_until':v['paused_until'],'reason':v['reason'],'expiry_blocked':False,'system_event_detail':None,'blocked_notification_required':False,'gap':not v['calendar_available'],'expiry_blocked_actor':None}
        if not v['calendar_available'] or v['now']<v['paused_until']:return out
        out['paused_until']=None
        if v['lifecycle'] in ['published','observing']:
            out.update(status='active',reason=None)
        else:
            out.update(expiry_blocked_actor='system',expiry_blocked=True,system_event_detail={'expiry_blocked':'STRATEGY_VERSION_NOT_RUNNABLE','lifecycle':v['lifecycle']},blocked_notification_required=True)
        return out
    raise AssertionError(kind)

def run_r08b():
    import hashlib,copy
    data=json.loads(FILE.read_text(),parse_float=lambda s:(_ for _ in ()).throw(AssertionError('binary float forbidden')))
    baseline=hashlib.sha256(json.dumps(data['cases'][:83],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    assert baseline==data['r08b']['baseline_first83_sha256']
    cases=data['cases'][83:];assert len(cases)==9
    refs={r for c in cases for r in c['source_refs']}
    for r in refs:
        src=data['source_registry'][r];assert norm(src['quote']) in norm((ROOT/src['file']).read_text()),r
    rejected=0;vectors=0
    for c in cases:
        assert c['case_status']=='ready' and c['steps']
        raw=json.dumps(c['input']['scenarios'],sort_keys=True,ensure_ascii=False).encode()
        assert hashlib.sha256(raw).hexdigest()==c['review']['reviewed_input_sha256']
        actual=evaluate(c);equal(actual,c['expected'],D(0));vectors+=len(c['input']['scenarios'])
        wrong=copy.deepcopy(c['expected']);wrong['results'][0]['ORACLE_MUTATION']=True
        try:equal(actual,wrong,D(0))
        except AssertionError:rejected+=1
    # Semantic input mutations: keep expected fixed; oracle must respond to facts.
    mutations=[(0,lambda v:v.update(observations=[])),(1,lambda v:v.update(fills=[])),(2,lambda v:v.update(pause_days=1)),(3,lambda v:v.update(robustness=['79']*10)),(4,lambda v:v['plan'].update(qty='120')),(5,lambda v:v.update(trade_side='buy')),(6,lambda v:v.update(weights=['.79']*5)),(7,lambda v:v.update(before='3')),(8,lambda v:v.update(lifecycle='published'))]
    input_rejected=0
    for index,mutate in mutations:
        c=copy.deepcopy(cases[index]);mutate(c['input']['scenarios'][0])
        try:equal(evaluate(c),cases[index]['expected'],D(0))
        except AssertionError:input_rejected+=1
    assert rejected==9 and input_rejected==9
    print(json.dumps({'r08b_ready':9,'vectors_pass':vectors,'original83_hash_preserved':True,'expected_mutations_rejected':rejected,'input_mutations_rejected':input_rejected,'scope':'084-092 only; unit specification, not E2E'},ensure_ascii=False))

if __name__=='__main__':
    import sys
    run_r08b() if '--r08b' in sys.argv else run()
