"""原创纯虚构测试卡；不读取/复制任何正式H-01/W-01。"""
import yaml


def registry(gate=False):
    level = 'f.tt21_level' if gate else 'f.close_qfq'
    regime = 'f.tt21_regime' if gate else 'f.market_regime'
    return {
        level: {'feature_key': level, 'unit': 'CNY_per_share', 'adjust': 'qfq', 'status': 'declared'},
        regime: {'feature_key': regime, 'unit': 'enum', 'adjust': 'none', 'status': 'declared'},
    }


def document(key, gate=False):
    level, regime = tuple(registry(gate))
    rules = [
        ('entry', f'{level} > ma({level}, 2)'),
        ('veto', f'{regime} == "downtrend"'),
        ('counter', f'{level} < ma({level}, 2)'),
        ('invalidation', f'{level} < 1'),
        ('exit', f'{level} < 0'),
    ]
    spec = {'key': key, 'version_no': 1, 'params_schema': {},
            'rules': [{'id': f'tt21-{role}', 'role': role, 'dimension': 'technical', 'expr': expr,
                       'eval_time': 'daily_close', 'required_features': [regime] if role == 'veto' else [level]}
                      for role, expr in rules],
            'action_map': {'entry_all_core_pass': 'buy', 'held_hold': 'hold', 'exit': 'sell', 'else': 'wait'},
            'stops': {'time_stop_days': 3}}
    card = {'key': key, 'version_no': 1, 'name': '纯虚构T-T21验收卡', 'category': 'trend',
            'horizons': ['swing'], 'hypothesis': {'falsified_by': '纯合成阈值反例'},
            'dimensions': ['technical'], 'epistemic': {'hypothesis': 'hypothesis'},
            'entry': [{'ref': 'tt21-entry'}], 'counter_evidence': [{'ref': 'tt21-counter'}],
            'invalidation': [{'ref': 'tt21-invalidation'}], 'exit': [{'ref': 'tt21-exit'}],
            'data_needs': [{'feature_key': x} for x in (level, regime)]}
    fixtures = []
    for i in range(13):
        fixtures.append({'id': f'{key}-{i}', 'desc': '虚构独立数值', 'as_of': '2026-10-30',
                         'features': {level: 4 + i, regime: 'uptrend'}, 'series': {level: [1, 2]},
                         'security': {'board': 'sh_main'}, 'holding': {}, 'expect': {'state': 'entry_ok'}})
    blocks = {'strategy-card': card, 'strategy-spec': spec,
              'validation': {'methods': ['fixture', 'trigger_stats'], 'fixtures': fixtures}}
    return '\n'.join('```yaml '+k+'\n'+yaml.safe_dump(v, allow_unicode=True)+'```' for k,v in blocks.items())
