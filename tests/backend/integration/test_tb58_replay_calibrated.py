"""T-T28：历史断言照实记录2败；逐树对比既有T-B59更正基线，不豁免整个非⑨区。

原始输入与旧分析不改；只在 pytest 专用副本调用 tb58，基线仅存摘要而不提交行情响应。
新基线来自已验收更正产物（不是本轮自动接受输出），完整 canonical SHA 约束所有字段。
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
import subprocess
from pathlib import Path

import pytest

BACKEND = Path(os.environ.get('AIA_BACKEND_DIR', Path(__file__).resolve().parents[3] / 'src/backend'))
sys.path.insert(0, str(BACKEND))
from selfchecks import tb58
import p13_analyze

MANIFEST = json.loads(Path(__file__).with_name('tb28_replay_baselines.json').read_text())
BASELINES = MANIFEST['runs']
EVIDENCE = Path(os.environ.get('AIA_TB28_EVIDENCE_ROOT', '/tmp/tb63-replay-h2r0wxj5'))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope='module')
def replayed(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp('tt28-replay')
    # 8e8525e 的版本化输入，不读取共享树未提交配置；只在专用副本落盘。
    config = root / 'share_class_list.yaml'
    config.write_bytes(subprocess.check_output([
        'git', '-C', str(Path(__file__).resolve().parents[3]), 'show',
        '8e8525e:config/share_class_list.yaml']))
    assert digest(config) == MANIFEST['share_class_config_sha256']
    sources = []
    for name, spec in BASELINES.items():
        source = EVIDENCE / name
        # 只使用既有专用取证副本；禁止让本测试写入原始取证/共享工作树。
        assert EVIDENCE.resolve().is_relative_to(Path('/tmp')), '必须提供 /tmp 下专用取证副本'
        for rel, sha in spec['inputs'].items():
            src, dst = source / rel, root / name / rel
            assert not src.is_symlink() and digest(src) == sha, '取证输入SHA不匹配'
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            sources.append((src, sha))
        assert digest(source / 'p13_analysis.corrected-T-B59.json') == spec['reviewed_correction_sha256']
    output = io.StringIO()
    args = ['tb58.py', '--replay', *(str(root / name) for name in BASELINES)]
    # 只替换命令参数；业务分析不mock，历史脚本也不改。
    with pytest.MonkeyPatch.context() as patch, contextlib.redirect_stdout(output):
        patch.setattr(sys, 'argv', args)
        # 显式指定真实配置输入路径（快照不含根config）；不替换分析器/信号函数或PG。
        patch.setattr(p13_analyze, 'SHARE_CLASS_PATH', config)
        result = tb58.main()
    (root / 'legacy-tb58.log').write_text(output.getvalue())
    for src, sha in sources:
        assert digest(src) == sha, '原取证副本被改变'
    return root, result, output.getvalue()


@pytest.mark.skip(reason="T-T22明确裁定F0610旧取证基准已失效；保留用例，未验收，不重建正式/共享源")
def test_legacy_two_failures_are_exactly_stale_non9_expectations(replayed) -> None:
    _, result, output = replayed
    assert result == 1
    assert [s for s in output.splitlines() if s.startswith('FAIL ')] == [
        f'FAIL {name} 非⑨分析完全不变' for name in BASELINES
    ]
    assert '58 passed, 2 failed' in output


@pytest.mark.skip(reason="T-T22明确裁定F0611–F0612旧取证基准已失效；保留用例，未验收")
@pytest.mark.parametrize('name', sorted(BASELINES))
def test_full_analysis_equals_reviewed_b59_baseline(replayed, name: str) -> None:
    root, _, _ = replayed
    spec = BASELINES[name]
    old = json.loads((root / name / 'p13_analysis.json').read_text())
    new = json.loads((root / name / 'p13_analysis.corrected-T-B58.json').read_text())
    changed = sorted(k for k in old.keys() | new.keys() if old.get(k) != new.get(k))
    assert changed == spec['changed_sections'], '出现未经校准的字段区变动'
    encoded = json.dumps(new, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
    assert hashlib.sha256(encoded).hexdigest() == spec['canonical_analysis_sha256'], '完整更正树偏离已审查基线'
    # 校准依据：T-B59/7c0548a 缺日历不猜日期、名单草稿不入正式、CDR按逐证券签收。
    assert not new['trading_calendar']['confirmed']
    assert not new['7_share_class_lists']['v5g_close']['closed']
    assert new['10_cdr']['689009']['cdr_unit_cleared']
    assert new['4_capital']['v5i_backfill']['by_code']['000550']['verdict'] == 'inconclusive'
    assert new['9_currency_unit']['status'] == 'unconfirmed'
