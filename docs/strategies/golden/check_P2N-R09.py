"""Finite R09 golden verifier, not a general Chinese semantic classifier.
Uses deterministic guards plus researcher review bound to exact candidate hashes.
No model, network, application code, R08, or old golden checks are invoked.
"""
from pathlib import Path
from decimal import Decimal, InvalidOperation
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

def digest(candidate):
    return hashlib.sha256(json.dumps(candidate,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def findings(c, include_review=True):
    """Deterministic guards evaluated independently of expected.verdict/findings.
    Semantic review is finite manually-authored oracle, NOT inferred by keywords.
    """
    i=c['input'];candidate=c['candidate'];result=set()
    if include_review:
        assert digest(candidate)==c['semantic_review']['text_sha256'],'changed text requires new semantic review'
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
            for number,unit in NUMBER.findall(plain):
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
    return sorted(result)

def projection(c, detected):
    out={'source':'template' if detected else 'llm','validation_status':'fallback' if detected else 'passed'}
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

if __name__=='__main__':run()
