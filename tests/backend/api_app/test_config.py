"""T-B01 报告 §6 建议 8（配置）与 10（API 前缀）。"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

#: 虚构标记值：用来检查 MAIRUI_* 环境变量不会进入 Settings / 日志 / 响应（不是任何真实 licence）
FAKE_LICENCE_MARKER = "FAKE-LICENCE-MARKER-0000"


def test_production_requires_master_key(backend, clean_env):
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="APP_MASTER_KEY"):
        backend.config.Settings(app_env="production")
    with pytest.raises(ValidationError, match="APP_MASTER_KEY"):
        backend.config.Settings(app_env="staging")


def test_master_key_min_length(backend, clean_env):
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="32"):
        backend.config.Settings(app_env="production", app_master_key="short-test-key")
    s = backend.config.Settings(app_env="production", app_master_key="p" * 32)
    assert "p" * 32 not in repr(s) and "p" * 32 not in str(s.model_dump())


def test_dev_envs_allow_missing_key(backend, clean_env):
    for env in ("local", "test"):
        assert backend.config.Settings(app_env=env).app_master_key is None


def test_defaults(backend, clean_env):
    s = backend.config.Settings()
    assert s.app_env == "local"
    assert s.api_prefix == "/api/v1"
    assert (s.page_limit_default, s.page_limit_max) == (50, 200)
    assert s.health_check_timeout_s == 1.0
    assert (s.ingest_heartbeat_key, s.ingest_paused_key, s.ingest_stale_after_s) == ("ingest:heartbeat", "ingest:paused", 120)
    assert s.cursor_ttl_s == 86_400


def test_env_overrides(backend, clean_env, monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("INGEST_STALE_AFTER_S", "45")
    monkeypatch.setenv("INGEST_HEARTBEAT_KEY", "hb:x")
    monkeypatch.setenv("PAGE_LIMIT_MAX", "100")
    s = backend.config.Settings()
    assert (s.app_env, s.ingest_stale_after_s, s.ingest_heartbeat_key, s.page_limit_max) == ("test", 45, "hb:x", 100)


def test_page_limit_default_gt_max_rejected(backend, clean_env):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        backend.config.Settings(page_limit_default=300, page_limit_max=200)


def _write_realtime(cfgtools, cfg: Path) -> dict:
    """写入完整的 realtime.yaml（plan §6.1 默认值），返回其内容。"""
    import yaml

    text = cfgtools.source("realtime").read_text(encoding="utf-8")
    (cfg / "realtime.yaml").write_text(text, encoding="utf-8")
    return yaml.safe_load(text)


def test_env_overrides_yaml_business(backend, cfgtools, clean_env, monkeypatch):
    """plan v0.2.2 §6.1：三层深合并（逐键递归），只覆盖给出的键，兄弟键保留。"""
    base = _write_realtime(cfgtools, clean_env)
    bd = cfgtools.business_dict
    assert bd(backend.config.Settings())["realtime"]["intervals"]["quote_interval_s"] == 15
    monkeypatch.setenv("BUSINESS", '{"realtime": {"intervals": {"quote_interval_s": 30}}}')
    got = bd(backend.config.Settings())["realtime"]
    want = {**base, "intervals": {**base["intervals"], "quote_interval_s": 30}}
    assert got == want


def test_business_list_replaced_wholesale(backend, cfgtools, clean_env, monkeypatch):
    """架构师已定（T-T01b）：列表整体替换，不按元素合并。"""
    base = _write_realtime(cfgtools, clean_env)
    assert base["universe"]["tier1_priority"] != ["focus"] and len(base["universe"]["tier1_priority"]) > 1
    monkeypatch.setenv("BUSINESS", '{"realtime": {"universe": {"tier1_priority": ["focus"]}}}')
    got = cfgtools.business_dict(backend.config.Settings())["realtime"]["universe"]
    assert got["tier1_priority"] == ["focus"]
    assert {k: v for k, v in got.items() if k != "tier1_priority"} == {
        k: v for k, v in base["universe"].items() if k != "tier1_priority"}


def test_business_null_means_not_overridden(backend, cfgtools, clean_env, monkeypatch):
    """plan v0.2.2 §6.1：上层值显式为 null 视为“未覆盖”，保留下层值。"""
    from pydantic import ValidationError

    _write_realtime(cfgtools, clean_env)
    monkeypatch.setenv("BUSINESS", '{"realtime": {"intervals": {"quote_interval_s": null}}}')
    try:
        got = cfgtools.business_dict(backend.config.Settings())["realtime"]["intervals"]["quote_interval_s"]
    except (ValidationError, ValueError):
        pytest.xfail("后端 T-B02（plan §6.1 合并规则）未实现：上层 null 覆盖了 yaml 值并导致校验失败")
    if got is None:
        pytest.xfail("后端 T-B02（plan §6.1 合并规则）未实现：上层 null 覆盖了 yaml 值")
    assert got == 15


def test_business_merged_result_validated(backend, cfgtools, clean_env, monkeypatch):
    """合并后的结果整体走 pydantic 校验：环境变量带入未知键 → 启动失败。"""
    _write_realtime(cfgtools, clean_env)
    if not cfgtools.business_files():
        pytest.xfail("T-B02（config/*.yaml 的 pydantic 模型）未实现：合并结果未校验（plan §6.1）")
    monkeypatch.setenv("BUSINESS", '{"realtime": {"intervalz": {}}}')
    with pytest.raises(ValueError):
        backend.config.Settings()


def test_mairui_env_ignored(backend, clean_env, monkeypatch, caplog):
    monkeypatch.setenv("MAIRUI_LICENCE", FAKE_LICENCE_MARKER)
    monkeypatch.setenv("MAIRUI_EGRESS_IP_EXPECTED", "192.0.2.1")
    s = backend.config.Settings(app_env="test")
    assert not [f for f in type(s).model_fields if "mairui" in f.lower()]
    assert FAKE_LICENCE_MARKER not in repr(s) and FAKE_LICENCE_MARKER not in str(s.model_dump())
    caplog.set_level(logging.DEBUG)
    from fastapi.testclient import TestClient

    with TestClient(backend.main.create_app(s), raise_server_exceptions=False) as c:
        bodies = [c.get(p).text for p in ("/api/v1/health", "/api/v1/meta/enums", "/api/v1/nope", "/api/v1/openapi.json")]
    assert all(FAKE_LICENCE_MARKER not in b for b in bodies)
    assert FAKE_LICENCE_MARKER not in caplog.text


def test_secrets_not_in_repr(backend, clean_env):
    s = backend.config.Settings(app_env="test", database_url="postgresql://127.0.0.1:1/x_marker_db", app_master_key="m" * 40)
    text = repr(s) + str(s)
    assert "x_marker_db" not in text and "m" * 40 not in text


# ---------------- config/*.yaml 加载 ----------------
def test_yaml_dir_loading(backend, cfgtools, clean_env):
    """只读一层 *.yaml / *.yml；子目录（strategies/）与其他扩展名忽略。"""
    (clean_env / "note.txt").write_text("ignored", encoding="utf-8")
    sub = clean_env / "strategies"
    sub.mkdir()
    (sub / "s.yaml").write_text("x: 1\n", encoding="utf-8")
    names = cfgtools.business_files()
    if not names:  # 旧后端：任意文件名都读入
        (clean_env / "a.yaml").write_text("schema_version: 1\nk: 1\n", encoding="utf-8")
        (clean_env / "b.yml").write_text("", encoding="utf-8")
        assert backend.config.Settings().business == {"a": {"schema_version": 1, "k": 1}, "b": {}}
        return
    first = clean_env / f"{names[0]}.yaml"
    first.rename(first.with_suffix(".yml"))  # .yml 同样识别
    assert set(cfgtools.business_dict(backend.config.Settings())) == set(names)


def test_extra_yaml_file_rejected_plan_6_1(backend, cfgtools, clean_env):
    """plan §6.1：config/ 顶层只允许约定文件，多余文件 → 启动失败。"""
    (clean_env / "a.yaml").write_text("schema_version: 1\nk: 1\n", encoding="utf-8")
    if not cfgtools.business_files():
        pytest.xfail("T-B02（config/*.yaml 的 pydantic 模型）未实现：多余文件未被拒绝（plan §6.1）")
    with pytest.raises(backend.config.ConfigError, match="多余"):
        backend.config.Settings()


def test_missing_yaml_file_rejected_plan_6_1(backend, cfgtools, clean_env):
    names = cfgtools.business_files()
    if not names:
        pytest.xfail("T-B02（config/*.yaml 的 pydantic 模型）未实现：缺文件未被拒绝（plan §6.1）")
    (clean_env / f"{names[-1]}.yaml").unlink()
    with pytest.raises(backend.config.ConfigError, match="缺少"):
        backend.config.Settings()


def test_missing_config_dir(backend, cfgtools, clean_env, monkeypatch, tmp_path):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "nope"))
    if not cfgtools.business_files():
        assert backend.config.Settings().business == {}
        return
    with pytest.raises(backend.config.ConfigError, match="缺少"):
        backend.config.Settings()


@pytest.mark.parametrize(
    ("files", "match"),
    [
        ({"bad.yaml": "a: [1, 2\n"}, "解析失败"),
        ({"list.yaml": "- 1\n- 2\n"}, "顶层必须是映射"),
        ({"scalar.yaml": "42\n"}, "顶层必须是映射"),
        ({"dup.yaml": "a: 1\n", "dup.yml": "a: 2\n"}, "重名"),
    ],
)
def test_bad_yaml_fails_startup(backend, clean_env, files, match):
    for name, text in files.items():
        (clean_env / name).write_text(text, encoding="utf-8")
    with pytest.raises(backend.config.ConfigError, match=match):
        backend.config.Settings()


def test_bad_yaml_error_has_no_content(backend, clean_env):
    (clean_env / "bad.yaml").write_text("secret_marker_value: [unclosed\n", encoding="utf-8")
    with pytest.raises(backend.config.ConfigError) as ei:
        backend.config.Settings()
    assert "secret_marker_value" not in str(ei.value)


def test_unknown_yaml_key_rejected_plan_6_1(backend, cfgtools, clean_env):
    """plan §6.1：未知键 → 启动失败（extra=forbid），每个文件必须 schema_version: 1。"""
    _write_realtime(cfgtools, clean_env)
    with (clean_env / "realtime.yaml").open("a", encoding="utf-8") as fh:
        fh.write("intervalz: {}\n")
    try:
        backend.config.Settings()
    except (backend.config.ConfigError, ValueError):
        return
    pytest.xfail("T-B02（config/*.yaml 的 pydantic 模型）未实现：未知键未被拒绝（plan §6.1）")


def test_sensitive_yaml_key_rejected(backend, cfgtools, clean_env):
    """plan §6.1：yaml 只放非敏感参数；疑似敏感键名 → 启动失败，错误信息不回显取值。"""
    _write_realtime(cfgtools, clean_env)
    with (clean_env / "realtime.yaml").open("a", encoding="utf-8") as fh:
        fh.write("licence: FAKE_NOT_A_REAL_VALUE\n")
    try:
        backend.config.Settings()
    except (backend.config.ConfigError, ValueError) as exc:
        assert "FAKE_NOT_A_REAL_VALUE" not in str(exc)
        return
    pytest.xfail("T-B02（config/*.yaml 的 pydantic 模型）未实现：敏感键未被拒绝（plan §6.1）")


def test_llm_api_key_env_name_is_not_sensitive(backend, cfgtools, clean_env):
    """plan v0.2.2 §6.1 llm.yaml 用 ``api_key_env`` 写**变量名**（不是值），不能被敏感键检查误杀。"""
    if not cfgtools.business_files():
        pytest.skip("旧后端无 plan §6.1 文件集校验（T-B02）")
    src = (cfgtools.snapshot_dir / "llm.yaml").read_text(encoding="utf-8")
    (clean_env / "llm.yaml").write_text(src, encoding="utf-8")
    try:
        cfgtools.business_dict(backend.config.Settings())
    except (backend.config.ConfigError, ValueError) as exc:
        msg = str(exc)
        why = "敏感键检查把 api_key_env（变量名）当成密钥" if "敏感键" in msg else "不认识 llm.yaml（多余文件/无模型）"
        pytest.xfail(f"后端 T-B25/T-B02：plan v0.2.2 的 llm.yaml 无法加载——{why}")


# ---------------- 10. API 前缀 ----------------
@pytest.mark.parametrize(
    ("raw", "norm"),
    [("/api/v1", "/api/v1"), ("/v1", "/v1"), ("v1", "/v1"), ("/v1/", "/v1"), (" /v1 ", "/v1"), ("/", ""), ("", "")],
)
def test_prefix_normalization(backend, clean_env, raw, norm):
    assert backend.config.Settings(api_prefix=raw).api_prefix == norm


def test_prefix_v1_moves_routes_and_openapi(make_client):
    c = make_client(api_prefix="/v1")
    assert c.get("/v1/health").status_code in {200, 503}
    assert c.get("/v1/meta/enums").status_code == 200
    assert c.get("/api/v1/meta/enums").status_code == 404
    spec = c.get("/v1/openapi.json").json()
    paths = set(spec["paths"])
    assert "/v1/meta/enums" in paths and all(p.startswith("/v1/") for p in paths)
    assert c.get("/api/v1/openapi.json").status_code == 404


def test_docs_only_in_dev(make_client):
    assert make_client(app_env="test").get("/api/v1/docs").status_code == 200
    assert make_client(app_env="production").get("/api/v1/docs").status_code == 404


def test_openapi_error_schema(make_client):
    spec = make_client().get("/api/v1/openapi.json").json()
    assert "ErrorResponse" in spec["components"]["schemas"]
    assert set(spec["components"]["schemas"]["ErrorBody"]["properties"]) == {"code", "message", "details", "request_id"}


def test_settings_module_has_no_mairui_reference(backend):
    src = Path(backend.config.__file__).read_text(encoding="utf-8")
    # 文档字符串里可以提到“不读取 MAIRUI_LICENCE”，但不得声明字段或 os.environ 读取
    assert "os.environ.get(\"MAIRUI" not in src and "mairui_licence:" not in src.lower()
