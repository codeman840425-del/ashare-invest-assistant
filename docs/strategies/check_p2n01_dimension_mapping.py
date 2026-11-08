"""P2N-01 documentation-only checks; no network, business code, or T-R23 execution."""
from pathlib import Path
import re

BASE = Path(__file__).resolve().parent
text = (BASE / 'phase2_daily_dimensions.md').read_text()
spec = (BASE / 'feature_spec.md').read_text()
expected = ['technical', 'capital', 'fundamental', 'sentiment', 'sector_market', 'news']
assert re.findall(r'^### (\w+)$', text, re.M) == expected
rows = []
for line in text.splitlines():
    if line.startswith('| f.'):
        row = [s.strip() for s in line.strip('|').split('|')]
        assert len(row) == 6, row
        key, ref, unit, status, pit, missing = row
        assert key.startswith('f.') and re.fullmatch(r'F\d+', ref)
        assert pit and missing and unit and status
        # Locate the exact registered key, not a near-name or frontend mock.
        matches = re.findall(r'^  - \{feature_key: ' + re.escape(key) + r',.*$', spec, re.M)
        assert len(matches) == 1, key
        entry = matches[0]
        unit_match = re.search(r'\bunit: (\w+)', entry)
        assert unit_match, key
        if key == 'f.main_net_20d':
            assert unit == 'null' and unit_match[1] == 'pending'
        elif key == 'f.rsi14':
            assert unit == 'index_0_100' and '0–100' in spec
        else:
            assert unit == unit_match[1], (key, unit, unit_match[1])
        registered_status = re.search(r'\bstatus: (declared|verified_doc|verified_live|gap|deprecated)', entry)
        if registered_status:
            assert status == registered_status[1], (key, status)
        elif key == 'f.ann_risk_count_10d':
            assert status == 'declared' and '仍 declared' in (BASE.parent / 'plan-phase2-next.md').read_text()
        else:
            assert status == 'null（等级未明）', key
        # F16-18 are grouped in one heading; other references must be headings.
        assert re.search(r'^### .*\b' + ref + r'\b.*`' + re.escape(key) + r'`', spec, re.M), (key, ref)
        rows.append(row)
assert len(rows) == len({r[0] for r in rows}) == 20
by_key = {r[0]: r for r in rows}
for key in ['f.main_net_20d', 'f.ann_risk_count_10d', 'f.market_regime', 'f.ind_rs20']:
    assert by_key[key][3] == 'declared'
assert by_key['f.market_regime_idx'][3] == 'verified_doc'
assert 'F25为账户RC3口径，不能由F50顶替' in text
assert 'F14/F15' in text and 'declared；d+1可见' in text
for phrase in ['Evidence.value=null', 'facts=[]', 'data_as_of=null', '不填range',
               'known_at 是', '不合并动作', 'next_trading_day(plrq)', '[D−9,D]',
               '不抓正文', '未登记键 status=null', 'verify_pending', 'unit_mismatch']:
    assert phrase in text, phrase
print('PASS: six ordered groups; 20 distinct registered keys; units/status/spec refs; PIT/null/gap boundaries; F25/F50 separated')
