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
    assert ready>=20 and blocked==9
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

if __name__=='__main__':
    run()
