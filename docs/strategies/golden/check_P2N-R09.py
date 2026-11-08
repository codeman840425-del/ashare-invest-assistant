"""Finite R09 golden verifier, not a general Chinese semantic classifier.
Uses deterministic guards plus researcher review bound to exact candidate hashes.
No model, network, application code, R08, or old golden checks are invoked.
"""
from pathlib import Path
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from collections import Counter
import json
import re
import hashlib
import copy

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
DIMS=['technical','capital','fundamental','sentiment','sector_market','news']
UNIT={'CNY_per_share':'元/股','CNY':'元','pct':'%','count':'次','times':'倍'}
FIELDS={'action','score','confidence','stops'}
REF=re.compile(r'\[([A-Z_]+)\]')
CODE=re.compile(r'(?<![0-9A-Za-z])\d{6}\.(?:SZ|SH|BJ)(?![0-9A-Za-z])')
NUMBER=re.compile(r'(?<![A-Za-z_])([-+]?\d+(?:\.\d+)?)(元/股|万元|元|%|次|倍)?')
TA36_NUMBER=re.compile(r'(?<![A-Za-z_])([-+]?\d+(?:\.\d+)?)(元/股|亿元|万元|元|%|次|倍)?')

def digest(candidate):
    return hashlib.sha256(json.dumps(candidate,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def findings(c, include_review=True):
    """Deterministic guards evaluated independently of expected.verdict/findings.
    Semantic review is finite manually-authored oracle, NOT inferred by keywords.
    """
    i=c['input'];candidate=c['candidate'];result=set()
    if include_review:
        assert digest(candidate)==c['semantic_review']['text_sha256'],'changed text requires new semantic review'
        if c.get('authority_revision')=='T-A36':
            assert review_binding(c)==c['semantic_review']['binding_sha256'],'changed evidence requires new semantic review'
        result.update(c['semantic_review']['findings'])
    if i.get('prohibited_input'):
        assert 'username' in i['prohibited_input']
        result.add('pii_input')
        return sorted(result)
    if candidate is None:
        result.add('generation_unavailable')
        return sorted(result)
    if set(candidate)!={'paragraphs'}:
        result.add('model_schema')
    for field in FIELDS:
        if field in candidate and candidate[field]!=i['protected_result'][field]:
            result.add('protected_result_mutation')
    if i.get('committed') and i.get('operation')=='overwrite_existing_explanation':
        result.add('immutable_snapshot')
    if 'candidate_ui_disclaimer' in i and i['candidate_ui_disclaimer']!=i['ui_disclaimer']:
        result.add('disclaimer_changed')
    evidence={v['id']:v for v in i['evidence']}
    assert len(evidence)==len(i['evidence'])
    strategies={v['strategy_key']:v for v in i['enabled_strategies']}
    paragraphs=candidate['paragraphs'];bindings=c['paragraph_bindings']
    assert len(paragraphs)==len(bindings)
    if i['scope']=='six_dimensions':
        if [v['dimension'] for v in bindings]!=DIMS or any(v.get('merged_dimensions') for v in bindings):
            result.add('dimension_merge')
    if i['scope']=='strategy_divergence':
        if [v['strategy_key'] for v in bindings]!=list(strategies) or any(v.get('merged_strategies') for v in bindings):
            result.add('strategy_merge')
    for paragraph,binding in zip(paragraphs,bindings):
        assert set(paragraph)=={'text','cites'}
        text=paragraph['text'];cites=paragraph['cites']; inline=REF.findall(text)
        sentences=[s for s in re.split('[。！？]',text) if s.strip()]
        if not cites or any(not REF.findall(s) for s in sentences):
            result.add('missing_citation')
        if set(inline)!=set(cites):
            result.add('inline_citation_mismatch')
        if any(eid not in evidence for eid in cites):
            result.add('unknown_citation')
        if cites and not set(binding['required_evidence_ids'])<=set(cites):
            result.add('citation_fact_mismatch')
        subject_codes=CODE.findall(text)
        if any(code!=i['security_code'] for code in subject_codes) or '虚构乙' in text:
            result.add('new_subject')
        # Only cited evidence may license values/units, not every value in the pack.
        known=[evidence[eid] for eid in cites if eid in evidence]
        if known:
            plain=REF.sub('',CODE.sub('',text))
            for number,unit in (TA36_NUMBER if c.get('authority_revision')=='T-A36' else NUMBER).findall(plain):
                if c.get('authority_revision')=='T-A36':
                    outcomes=[numeric_guard(number,unit,ev['value'],ev['unit']) for ev in known if ev['value'] is not None]
                    if not any(ok for ok,_ in outcomes):
                        reasons={reason for _,reason in outcomes}
                        result.add('numeric_precision' if 'precision' in reasons else 'unit_mismatch' if 'unit' in reasons and reasons=={'unit'} else 'unsupported_number')
                    continue
                matches=[]
                for ev in known:
                    try:
                        if ev['value'] is not None and Decimal(str(ev['value']))==Decimal(number):
                            matches.append(ev)
                    except InvalidOperation:
                        pass
                if not matches:
                    result.add('unsupported_number')
                elif not any(UNIT.get(ev['unit'])==unit for ev in matches):
                    result.add('unit_mismatch')
        skey=binding['strategy_key']
        if skey is not None:
            if skey not in strategies:
                result.add('inactive_strategy')
            else:
                rules={r['rule_id']:r for r in strategies[skey]['rule_refs']}
                rule=rules[binding['rule_id']]
                if rule['passed'] is not binding['asserted_passed']:
                    result.add('rule_contradiction')
                if not set(rule['evidence_ids'])<=set(cites):
                    result.add('citation_fact_mismatch')
    if c.get('authority_revision')=='T-A36':
        # Only the two attested lexemes in these finite candidates are asserted.
        # This is NOT an exhaustive action list, nor a whitelist for other text.
        for p in paragraphs:
            if '减仓' in p['text']:result.add('action_word')
            if '保证' in p['text']:result.add('prohibited_term')
    return sorted(result)

def projection(c, detected):
    out={'source':'template' if detected else 'llm','validation_status':'fallback' if detected else 'passed'}
    if c.get('authority_revision')=='T-A36':
        out['fallback_reason']='validation_failed' if detected else None
    if not detected:
        # Model cites are adapted to existing TextWithEvidence.evidence_ids.
        out['paragraphs']=[]
        lines=[]
        for paragraph in c['candidate']['paragraphs']:
            lines.append(paragraph['text'])
            out['paragraphs'].append(dict(text=paragraph['text'],expr=None,evidence_ids=list(paragraph['cites'])))
        out['text']='\n'.join(lines)
    elif not c['input'].get('model_invoked',True):
        out['llm_call_id']=None
    return out

def norm(s):return re.sub(r'[\s`*]','',s)

def run():
    data=json.loads((HERE/'P2N-R09_golden.json').read_text())
    assert data['fictitious'] is True and data['task']=='P2N-R09'
    for ref in data['source_registry'].values():
        assert norm(ref['quote']) in norm((ROOT/ref['file']).read_text()),ref
    disclaimer=(ROOT/'docs/strategies/compliance/disclaimer.md').read_text().split('> ')[1].strip()
    ids=set();counts=Counter();failure_coverage=Counter();dim_coverage=Counter()
    for c in data['cases']:
        assert c['id'] not in ids;ids.add(c['id'])
        assert c['audit_steps'] and c['source_refs'] and c['semantic_review']['note']
        assert set(c['source_refs'])<=data['source_registry'].keys()
        assert c['input']['ui_disclaimer']==disclaimer
        assert all(e['provider']=='system' and e['epistemic_type']=='hypothesis' for e in c['input']['evidence'])
        assert [s['card_version'] for s in c['input']['enabled_strategies']]==[2,2]
        if c['case_status']=='blocked':
            assert c['expected'] is None and c['question']
            counts['blocked_not_run']+=1
            continue
        assert c['case_status']=='ready'
        detected=findings(c)
        assert detected==c['expected']['findings'],(c['id'],detected,c['expected']['findings'])
        verdict='rejected' if detected else 'accepted'
        assert verdict==c['expected']['verdict'],c['id']
        assert projection(c,detected)==c['expected']['explanation_projection'],c['id']
        assert c['input']['protected_result']==c['expected']['protected_result']
        counts[verdict]+=1
        failure_coverage.update(detected)
        if not detected:
            dim_coverage.update(v['dimension'] for v in c['paragraph_bindings'])
    assert counts['accepted']>=12 and counts['rejected']>=8 and sum(counts.values())>=20
    assert set(dim_coverage)==set(DIMS)
    assert set(data['finding_source_map'])>=set(failure_coverage)
    # Mutation probes bypass review labels: deterministic checks must detect actual corruption.
    original=next(c for c in data['cases'] if c.get('expected') and c['expected']['verdict']=='accepted')
    mutations=[]
    c=copy.deepcopy(original);c['candidate']['paragraphs'][0]['text']=c['candidate']['paragraphs'][0]['text'].replace('12.40','12.41');mutations.append((c,'unsupported_number'))
    c=copy.deepcopy(original);c['candidate']['paragraphs'][0]['cites']=['E_GHOST'];mutations.append((c,'unknown_citation'))
    c=copy.deepcopy(original);c['candidate']['paragraphs'][0]['text']=c['candidate']['paragraphs'][0]['text'].replace('元/股','万元');mutations.append((c,'unit_mismatch'))
    c=copy.deepcopy(original);c['candidate']['paragraphs'][0]['text']='虚构乙999002.SZ'+c['candidate']['paragraphs'][0]['text'];mutations.append((c,'new_subject'))
    c=copy.deepcopy(original);c['candidate']['action']='buy';mutations.append((c,'protected_result_mutation'))
    for c,required in mutations:
        assert required in findings(c,include_review=False),required
        try:findings(c,include_review=True)
        except AssertionError as exc:assert 'requires new semantic review' in str(exc)
        else:raise AssertionError('mutated text reused manual review')
    # A new semantic-only promise is NOT claimed detectable by these structural guards.
    semantic_mutation=copy.deepcopy(original)
    semantic_mutation['candidate']['paragraphs'][0]['text']+='保证获利[E_T]。'
    assert not findings(semantic_mutation,include_review=False)
    try:findings(semantic_mutation,include_review=True)
    except AssertionError as exc:assert 'requires new semantic review' in str(exc)
    else:raise AssertionError('unreviewed semantic promise reused review')
    print(json.dumps({'result':'PASS','cases':dict(counts),'accepted_dimension_coverage':dict(dim_coverage),'finding_coverage':dict(failure_coverage),'deterministic_mutations_detected':len(mutations),'semantic_review_hash_mutations_blocked':len(mutations)+1,'limit':'finite reviewed candidates only; not universal Chinese semantic validation'},ensure_ascii=False))


def numeric_guard(token, display_unit, value, evidence_unit):
    """Input-only Decimal guard per T-A36 p4; fixture uses official default 2.
    No invented tolerances or display configuration. Non-numeric facts unsupported.
    """
    try:
        source=Decimal(str(value));shown=Decimal(token)
    except InvalidOperation:return False,'value'
    scale=Decimal(1)
    if evidence_unit=='CNY' and display_unit in ('万元','亿元'):
        scale=Decimal(10000 if display_unit=='万元' else 100000000)
    elif UNIT.get(evidence_unit)!=display_unit:return False,'unit'
    d=max(0,-shown.as_tuple().exponent);p=max(0,-source.as_tuple().exponent)
    if evidence_unit=='count':return (True,None) if shown==source else (False,'value')
    if evidence_unit in ('pct','CNY_per_share') and d<min(p,2):return False,'precision'
    rounded=(source/scale).quantize(Decimal(1).scaleb(-d),rounding=ROUND_HALF_UP)
    return (True,None) if shown==rounded else (False,'value')

def review_binding(c):
    return hashlib.sha256(json.dumps({'candidate':c['candidate'],'input':c['input'],'paragraph_bindings':c['paragraph_bindings']},sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def run_r09b():
    data=json.loads((HERE/'P2N-R09_golden.json').read_text())
    assert hashlib.sha256(json.dumps(data['cases'][:64],sort_keys=True,ensure_ascii=False).encode()).hexdigest()==data['r09b']['original64_sha256']
    cases=data['cases'][64:];assert len(cases)==3
    for ref in {r for c in cases for r in c['source_refs']}:
        r=data['source_registry'][ref];assert norm(r['quote']) in norm((ROOT/r['file']).read_text()),ref
    for c in cases:
        assert c['case_status']=='ready' and c['semantic_review']['sentence_reviews']
        assert review_binding(c)==c['semantic_review']['binding_sha256']
        assert digest(c['candidate'])==c['semantic_review']['text_sha256']
        # Final tags checked against fresh mechanical findings, not review labels.
        got=findings(c,include_review=False)
        assert got==c['expected']['findings'],(c['id'],got)
        assert findings(c)==got
        assert ('rejected' if got else 'accepted')==c['expected']['verdict']
        assert projection(c,got)==c['expected']['explanation_projection']
        assert c['expected']['protected_result']==c['input']['protected_result']
    count=0
    for v in cases[0]['numeric_probes']:
        ok,reason=numeric_guard(v['display_token'],v['display_unit'],v['evidence_value'],v['evidence_unit'])
        assert (ok,reason)==(v['expected_valid'],v['expected_reason']),v
        count+=1
    # Main-case arithmetic independently derived; do not consume its explanation notes.
    raw=next(e for e in cases[0]['input']['evidence'] if e['id']=='E_T')
    token=NUMBER.findall(REF.sub('',cases[0]['candidate']['paragraphs'][0]['text']))[0][0]
    assert Decimal(raw['value']).quantize(Decimal('1'),rounding=ROUND_HALF_UP)==Decimal(token)
    assert max(0,-Decimal(token).as_tuple().exponent)<min(max(0,-Decimal(raw['value']).as_tuple().exponent),2)
    ev_dec=max(0,-Decimal(raw['value']).as_tuple().exponent)
    num_dec=max(0,-Decimal(token).as_tuple().exponent)
    rounded=Decimal(raw['value']).quantize(Decimal(1).scaleb(-num_dec),rounding=ROUND_HALF_UP)
    calc={'evidence_id':raw['id'],'evidence_value':raw['value'],'evidence_unit':raw['unit'],'display_token':token,'display_unit':'元/股','display_decimals':num_dec,'evidence_decimals':ev_dec,'configured_min_decimals':2,'required_min_decimals':min(ev_dec,2),'rounding':'ROUND_HALF_UP','rounded_value':str(rounded),'equality_pass':rounded==Decimal(token),'precision_pass':num_dec>=min(ev_dec,2),'result':'accepted' if numeric_guard(token,'元/股',raw['value'],raw['unit'])[0] else 'rejected'}
    assert calc==cases[0]['numeric_calculation']
    # Changed input/text must change findings independently, and cannot reuse review.
    cleared=0;hash_blocked=0
    replacements=[('12元/股','12.40元/股'),('减仓','已记录'),('不保证收益','仅为研究记录')]
    for c,(old,new) in zip(cases,replacements):
        changed=copy.deepcopy(c);changed['candidate']['paragraphs'][0]['text']=changed['candidate']['paragraphs'][0]['text'].replace(old,new)
        assert not findings(changed,include_review=False) # mechanical pass only, NOT semantic acceptance
        cleared+=1
        assert review_binding(changed)!=c['semantic_review']['binding_sha256']
        try:findings(changed)
        except AssertionError:hash_blocked+=1
        else:raise AssertionError('stale text review accepted')
    changed=copy.deepcopy(cases[0]);changed['input']['evidence'][0]['value']='12'
    assert not findings(changed,include_review=False)
    assert review_binding(changed)!=cases[0]['semantic_review']['binding_sha256']
    try:findings(changed)
    except AssertionError as exc:assert 'requires new semantic review' in str(exc)
    else:raise AssertionError('stale evidence review accepted')
    # Review labels cannot suppress hard rejection and expected corruption is rejected.
    for c in cases:
        changed=copy.deepcopy(c);changed['semantic_review']['findings']=[]
        assert findings(changed)==c['expected']['findings']
        wrong=copy.deepcopy(c['expected']);wrong['verdict']='accepted'
        assert ('rejected' if findings(c,False) else 'accepted')!=wrong['verdict']
    counts=Counter(c['expected']['verdict'] for c in data['cases'])
    assert counts=={'accepted':19,'rejected':48}
    print(json.dumps({'new_ready':3,'new_rejected':3,'new_accepted':0,'original64_hash_preserved':True,'total_recorded_counts':dict(counts),'numeric_probes_pass':count,'text_mutations_guard_changed':cleared,'stale_text_review_rejected':hash_blocked,'input_mutations_guard_changed':1,'review_label_erasure_resisted':3,'expected_verdict_mutations_rejected':3,'scope':'065-067 only, no original64 execution; finite guards not universal Chinese semantics'},ensure_ascii=False))

if __name__=='__main__':
    import sys
    run_r09b() if '--r09b' in sys.argv else run()
