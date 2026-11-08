"""只从受测main迁移图产生期望；绝不采用库内任意版本作期望。"""
import hashlib
import json
from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory


def expected_main_head(backend: Path) -> str:
    pinned = json.loads(Path(__file__).with_name('tt21_mainline.json').read_text())
    actual = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
              for p in (backend / 'migrations/versions').glob('*.py')}
    assert actual == pinned['migration_sha256'], '受测迁移文件不是固定main dcf734d版本图'
    cfg = Config()
    cfg.set_main_option('script_location', str(backend / 'migrations'))
    scripts = ScriptDirectory.from_config(cfg)
    heads = scripts.get_heads()
    assert len(heads) == 1, '迁移图必须唯一head'
    chain = list(scripts.walk_revisions(base='base', head=heads[0]))
    assert chain and chain[-1].revision == '0001', '迁移链根不在主线0001'
    assert any(r.revision == '0020' for r in chain), '迁移head不是主线0020的后代'
    seen = set()
    for r in chain:
        assert r.revision not in seen and not isinstance(r.down_revision, tuple), '主线存在分叉/重复'
        seen.add(r.revision)
    assert all(r.down_revision is None or r.down_revision in seen for r in chain), '迁移主线祖先缺失'
    assert set(scripts.get_bases()) == {'0001'}, '存在非主线孤立根'
    return heads[0]
