"""check_secret_boundary.py 正反例 + .gitignore 拦截证书封装私钥（T-O09）。"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import check_secret_boundary as ccs
from conftest import CI_DIR, REPO

NAME = "MAIRUI_" + "LICENCE"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    shutil.copytree(REPO / "deploy/compose", tmp_path / "deploy/compose")
    shutil.copytree(REPO / "deploy/scripts", tmp_path / "deploy/scripts")
    (tmp_path / "deploy/env").mkdir(parents=True)
    shutil.copy(REPO / ccs.ENV_EXAMPLE, tmp_path / ccs.ENV_EXAMPLE)
    shutil.copytree(REPO / ".github", tmp_path / ".github")
    return tmp_path


def _sub(repo: Path, rel: str, old: str, new: str) -> None:
    p = repo / rel
    text = p.read_text(encoding="utf-8")
    assert old in text, old
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


def test_repo_is_clean(repo: Path) -> None:
    assert ccs.check(repo) == []


def test_real_repo_is_clean() -> None:
    assert ccs.check(REPO) == []


def test_cli_exit_codes(repo: Path) -> None:
    run = lambda: subprocess.run([sys.executable, str(CI_DIR / "check_secret_boundary.py"), "--repo", str(repo)],  # noqa: E731
                                 capture_output=True, text=True)
    assert run().returncode == 0
    (repo / "deploy/scripts/x.sh").write_text(f'echo "${NAME}"\n', encoding="utf-8")
    assert run().returncode == 1


@pytest.mark.parametrize("rel", ["deploy/compose/docker-compose.dev.yml", "deploy/env/.env.example",
                                 "deploy/scripts/up.sh", ".github/workflows/ci.yml"])
def test_forbidden_name_anywhere(repo: Path, rel: str) -> None:
    with (repo / rel).open("a", encoding="utf-8") as f:
        f.write(f"# {NAME}\n")
    assert any(rel in e for e in ccs.check(repo))


def test_private_secret_on_api(repo: Path) -> None:
    _sub(repo, ccs.BASE_COMPOSE, "    secrets:\n      - data_licence_seal_public_keys\n",
         "    secrets:\n      - data_licence_seal_public_keys\n      - data_licence_seal_private_keys\n")
    assert any("服务 api" in e and "data_licence_seal_private_keys" in e for e in ccs.check(repo))


def test_private_env_on_overlay_worker(repo: Path) -> None:
    (repo / "deploy/compose/docker-compose.x.yml").write_text(
        "services:\n  worker:\n    environment:\n      DATA_LICENCE_SEAL_PRIVATE_KEYS: x\n", encoding="utf-8")
    assert any("worker" in e for e in ccs.check(repo))


def test_private_env_list_form_and_volume(repo: Path) -> None:
    (repo / "deploy/compose/docker-compose.x.yml").write_text(
        "services:\n  beat:\n    environment: [\"SEAL_PRIVATE_KEY=x\"]\n    volumes: [\"/s/data_licence_seal_private_keys:/k:ro\"]\n",
        encoding="utf-8")
    errs = ccs.check(repo)
    assert sum("beat" in e for e in errs) == 2


def test_env_file_forbidden(repo: Path) -> None:
    (repo / "deploy/compose/docker-compose.x.yml").write_text(
        "services:\n  api:\n    env_file: ../env/.env\n", encoding="utf-8")
    assert any("env_file" in e for e in ccs.check(repo))


def test_secret_from_environment_forbidden(repo: Path) -> None:
    (repo / "deploy/compose/docker-compose.x.yml").write_text(
        "secrets:\n  data_licence_seal_private_keys:\n    environment: SEAL\n", encoding="utf-8")
    assert any("environment:" in e for e in ccs.check(repo))


def test_ingest_must_have_private(repo: Path) -> None:
    _sub(repo, ccs.BASE_COMPOSE, "      - data_licence_seal_private_keys\n", "")
    assert any("服务 ingest" in e for e in ccs.check(repo))


def test_env_example_private_key(repo: Path) -> None:
    with (repo / ccs.ENV_EXAMPLE).open("a", encoding="utf-8") as f:
        f.write("DATA_LICENCE_SEAL_PRIVATE_KEYS=\n")
    assert any(".env.example" in e for e in ccs.check(repo))


@pytest.mark.parametrize("path", [
    "deploy/secrets/data_licence_seal_private_keys",
    "data_licence_seal_private_keys",
    "deploy/x/data_licence_seal_public_keys",
    "backup/data_licence_seal_private_keys.20261102",
])
def test_gitignore_blocks_seal_key_files(path: str) -> None:
    r = subprocess.run(["git", "-C", str(REPO), "check-ignore", "-q", "--no-index", path])
    assert r.returncode == 0, f".gitignore 应排除 {path}"


# ---------------------------------------------------------------- 数据库角色分离（T-O10）

def test_api_on_owner_role_rejected(repo: Path) -> None:
    _sub(repo, ccs.BASE_COMPOSE, "DATABASE_URL: *db-api-url", "DATABASE_URL: postgresql+psycopg://${POSTGRES_USER:-aia}:${POSTGRES_PASSWORD:?x}@postgres:5432/aia")
    errs = ccs.check(repo)
    assert any("服务 api 的 DATABASE_URL 应为 aia_api" in e for e in errs), errs


def test_worker_registered_as_aia_api() -> None:
    assert ccs.DB_ROLE_OF["worker"] == ("aia_api", "AIA_DB_API_PASSWORD")


def test_worker_on_owner_role_rejected(repo: Path) -> None:
    _sub(repo, ccs.BASE_COMPOSE, "      DATABASE_URL: *db-api-url\n      # 到期原始文件清理",
         "      DATABASE_URL: postgresql+psycopg://${POSTGRES_USER:-aia}:${POSTGRES_PASSWORD:?x}@postgres:5432/aia\n      # 到期原始文件清理")
    errs = ccs.check(repo)
    assert any("服务 worker 的 DATABASE_URL 应为 aia_api" in e for e in errs), errs


def test_worker_without_explicit_url_rejected(repo: Path) -> None:
    _sub(repo, ccs.BASE_COMPOSE, "      DATABASE_URL: *db-api-url\n      # 到期原始文件清理", "      # 到期原始文件清理")
    errs = ccs.check(repo)
    # 不显式覆盖时 <<: *app-env 带进属主 DATABASE_URL，必须被拒
    assert any("服务 worker 的 DATABASE_URL 应为 aia_api" in e or "服务 worker 没有显式 DATABASE_URL" in e for e in errs), errs


def test_overlay_cannot_switch_worker_back_to_owner(repo: Path) -> None:
    errs = _overlay(repo, "services:\n  worker:\n    environment:\n      DATABASE_URL: postgresql://aia:${POSTGRES_PASSWORD}@postgres/aia\n")
    assert any("服务 worker 的 DATABASE_URL" in e for e in errs), errs


def test_ingest_literal_password_rejected(repo: Path) -> None:
    _sub(repo, ccs.BASE_COMPOSE, "DATABASE_URL: *db-ingest-url",
         "DATABASE_URL: postgresql+psycopg://aia_ingest:" + "x" * 8 + "@postgres:5432/aia")
    assert any("服务 ingest 的 DATABASE_URL" in e for e in ccs.check(repo))


def test_overlay_cannot_switch_api_back_to_owner(repo: Path) -> None:
    (repo / "deploy/compose/docker-compose.x.yml").write_text(
        "services:\n  api:\n    environment:\n      - DATABASE_URL=postgresql://aia:${POSTGRES_PASSWORD}@postgres/aia\n",
        encoding="utf-8")
    assert any("docker-compose.x.yml: 服务 api 的 DATABASE_URL" in e for e in ccs.check(repo))


def test_db_password_secret_only_for_db_roles(repo: Path) -> None:
    (repo / "deploy/compose/docker-compose.x.yml").write_text(
        "services:\n  worker:\n    secrets: [db_password_aia_api]\n", encoding="utf-8")
    assert any("服务 worker 挂了 db_password_aia_api" in e for e in ccs.check(repo))


def test_db_password_secret_must_be_file(repo: Path) -> None:
    text = (repo / ccs.BASE_COMPOSE).read_text(encoding="utf-8")
    assert "  db_password_aia_ingest:\n    file:" in text
    _sub(repo, ccs.BASE_COMPOSE, "  db_password_aia_ingest:\n    file:", "  db_password_aia_ingest:\n    x-file:")
    assert any("顶层 secrets 缺少 db_password_aia_ingest" in e for e in ccs.check(repo))


# ---------------------------------------------------------------- aia_maint / APP_MASTER_KEY（T-O11）

def _overlay(repo: Path, text: str) -> list[str]:
    (repo / "deploy/compose/docker-compose.x.yml").write_text(text, encoding="utf-8")
    return ccs.check(repo)


def test_maint_password_only_for_db_roles_and_maint_cli(repo: Path) -> None:
    errs = _overlay(repo, "services:\n  api:\n    secrets: [db_password_aia_maint]\n")
    assert any("服务 api 挂了 db_password_aia_maint" in e for e in errs), errs
    assert _overlay(repo, "services:\n  maint-cli:\n    secrets: [db_password_aia_maint]\n") == []


def test_maint_cli_cannot_take_other_role_passwords(repo: Path) -> None:
    errs = _overlay(repo, "services:\n  maint-cli:\n    secrets: [db_password_aia_api]\n")
    assert any("服务 maint-cli 挂了 db_password_aia_api" in e for e in errs), errs


def test_maint_cli_without_owner_database_url(repo: Path) -> None:
    errs = _overlay(repo, "services:\n  maint-cli:\n    environment:\n      DATABASE_URL: postgresql://aia:x@postgres/aia\n")
    assert any("maint-cli 不得有 DATABASE_URL" in e for e in errs), errs


@pytest.mark.parametrize("key", ["AIA_MAINT_DATABASE_URL", "AIA_MAINT_DATABASE_URL_FILE"])
def test_maint_url_never_in_environment(repo: Path, key: str) -> None:
    errs = _overlay(repo, f"services:\n  api:\n    environment: [\"{key}=x\"]\n")
    assert any(key in e for e in errs), errs


def test_maint_password_secret_must_be_file(repo: Path) -> None:
    _sub(repo, ccs.BASE_COMPOSE, "  db_password_aia_maint:\n    file:", "  db_password_aia_maint:\n    x-file:")
    assert any("顶层 secrets 缺少 db_password_aia_maint" in e for e in ccs.check(repo))


@pytest.mark.parametrize("svc", ["api", "worker", "ingest"])
def test_master_key_never_in_environment(repo: Path, svc: str) -> None:
    errs = _overlay(repo, f"services:\n  {svc}:\n    environment:\n      APP_MASTER_KEY: x\n")
    assert any(f"服务 {svc} 的 environment 有 APP_MASTER_KEY" in e for e in errs), errs


def test_master_key_secret_only_api_worker(repo: Path) -> None:
    errs = _overlay(repo, "services:\n  ingest:\n    secrets: [app_master_key]\n")
    assert any("服务 ingest 挂了 app_master_key" in e for e in errs), errs


def test_master_key_secret_must_be_file_and_mounted(repo: Path) -> None:
    _sub(repo, ccs.BASE_COMPOSE, "  app_master_key:\n    file:", "  app_master_key:\n    x-file:")
    assert any("顶层 secrets 缺少 app_master_key" in e for e in ccs.check(repo))


def test_worker_must_mount_master_key(repo: Path) -> None:
    _sub(repo, ccs.BASE_COMPOSE, "    secrets:\n      - app_master_key\n    volumes:\n      # 读写（删除到期文件）",
         "    volumes:\n      # 读写（删除到期文件）")
    assert any("服务 worker 缺少 secrets ['app_master_key']" in e for e in ccs.check(repo))


def test_env_example_master_key_value(repo: Path) -> None:
    with (repo / ccs.ENV_EXAMPLE).open("a", encoding="utf-8") as f:
        f.write("APP_MASTER_KEY=placeholder\n")
    assert any("APP_MASTER_KEY 不得出现在 .env" in e for e in ccs.check(repo))


@pytest.mark.parametrize("path", [
    "app_master_key", "deploy/x/app_master_key", "deploy/x/db_password_aia_maint", "x/.db_password_aia_api.AbC123",
    "x/aia-maint.dsn",
])
def test_gitignore_blocks_master_key_and_role_passwords(path: str) -> None:
    r = subprocess.run(["git", "-C", str(REPO), "check-ignore", "-q", "--no-index", path])
    assert r.returncode == 0, f".gitignore 应排除 {path}"


# --- M1：不悄悄换主密钥 ---
def test_compose_sh_must_not_call_keygen(repo: Path) -> None:
    with (repo / ccs.COMPOSE_SH).open("a", encoding="utf-8") as f:
        f.write('[ -e "$d/app_master_key" ] || "$ROOT/deploy/scripts/app-master-keygen.sh" "$d"\n')
    assert any("不得直接调用 app-master-keygen.sh" in e for e in ccs.check(repo))


def test_compose_sh_keygen_in_comment_ok(repo: Path) -> None:
    with (repo / ccs.COMPOSE_SH).open("a", encoding="utf-8") as f:
        f.write("# 人工：deploy/scripts/app-master-keygen.sh\n")
    assert ccs.check(repo) == []


def test_compose_sh_must_call_ensure(repo: Path) -> None:
    p = repo / ccs.COMPOSE_SH
    p.write_text(p.read_text(encoding="utf-8").replace("app-master-key-ensure.sh", "true"), encoding="utf-8")
    assert any("没有调用 app-master-key-ensure.sh" in e for e in ccs.check(repo))


def test_ensure_script_must_exist(repo: Path) -> None:
    (repo / "deploy/scripts/app-master-key-ensure.sh").unlink()
    assert any("app-master-key-ensure.sh 不存在" in e for e in ccs.check(repo))


@pytest.mark.parametrize("svc", ["api", "worker"])
def test_require_master_key_flag_in_base(repo: Path, svc: str) -> None:
    p = repo / ccs.BASE_COMPOSE
    text = p.read_text(encoding="utf-8")
    lines = text.split("\n")
    # 删掉该服务块里的 AIA_REQUIRE_APP_MASTER_KEY 行
    start = lines.index(f"  {svc}:")
    for i in range(start + 1, len(lines)):
        if lines[i].strip().startswith("AIA_REQUIRE_APP_MASTER_KEY"):
            del lines[i]
            break
    else:
        raise AssertionError("基础 compose 里没找到该行")
    p.write_text("\n".join(lines), encoding="utf-8")
    assert any(f"服务 {svc} 缺少 AIA_REQUIRE_APP_MASTER_KEY" in e for e in ccs.check(repo))


@pytest.mark.parametrize("value", ['"0"', '""'])
def test_overlay_cannot_disable_require_flag(repo: Path, value: str) -> None:
    errs = _overlay(repo, f"services:\n  worker:\n    environment:\n      AIA_REQUIRE_APP_MASTER_KEY: {value}\n")
    assert any("服务 worker 的 AIA_REQUIRE_APP_MASTER_KEY 必须是" in e for e in errs), errs


# ---------- 冷却记录定时清理：deploy 的 cooldown-purge 服务已删除（review-6670b10 m5）----------


def test_cooldown_purge_service_removed() -> None:
    import yaml

    for name in ("docker-compose.yml", "docker-compose.dev.yml"):
        data = yaml.safe_load((REPO / "deploy/compose" / name).read_text(encoding="utf-8")) or {}
        assert "cooldown-purge" not in (data.get("services") or {}), name
    assert not (REPO / "deploy/docker/cooldown-purge.py").exists()
    assert "cooldown-purge" not in ccs.MASTER_KEY_ALLOC and "cooldown-purge" not in ccs.DB_ROLE_OF


def test_cooldown_purge_reintroduced_is_unregistered(repo: Path) -> None:
    errs = _overlay(repo, "services:\n  cooldown-purge:\n    image: busybox\n")
    assert any("服务 cooldown-purge 未在 MASTER_KEY_ALLOC 白名单登记" in e for e in errs), errs


# ---------- M2：APP_MASTER_KEY 按服务分配白名单（plan e56462c，CI 规则 7）----------


def test_unregistered_service_fails(repo: Path) -> None:
    errs = _overlay(repo, "services:\n  newsvc:\n    image: busybox\n")
    assert any("服务 newsvc 未在 MASTER_KEY_ALLOC 白名单登记" in e for e in errs), errs


@pytest.mark.parametrize("svc", ["ingest", "beat", "signal-rt", "migrate", "maint-cli"])
def test_non_owner_cannot_mount_master_key(repo: Path, svc: str) -> None:
    errs = _overlay(repo, f"services:\n  {svc}:\n    secrets:\n      - app_master_key\n")
    assert any(f"服务 {svc} 挂了 app_master_key" in e for e in errs), errs


def test_whitelist_covers_every_base_service() -> None:
    import yaml
    doc = yaml.safe_load((REPO / ccs.BASE_COMPOSE).read_text(encoding="utf-8"))
    assert set(doc["services"]) <= set(ccs.MASTER_KEY_ALLOC)
    assert {k for k, v in ccs.MASTER_KEY_ALLOC.items() if v} == {"api", "worker", "master-bootstrap"}



# ---------- T-A04 ②：规则 7 按服务的 secret 白名单 SERVICE_SECRETS ----------


def test_service_secrets_match_base_exactly() -> None:
    import yaml
    doc = yaml.safe_load((REPO / ccs.BASE_COMPOSE).read_text(encoding="utf-8"))
    for name, svc in doc["services"].items():
        assert set(ccs._secret_names((svc or {}).get("secrets"))) == set(ccs.SERVICE_SECRETS[name]), name
    assert set(doc.get("secrets") or {}) == set(ccs.PROTECTED_SECRETS)
    assert ccs.MASTER_KEY_ALLOC == {k: ccs.MASTER_SECRET in v for k, v in ccs.SERVICE_SECRETS.items()}


@pytest.mark.parametrize(("svc", "secret"), [
    ("worker", "data_licence_seal_public_keys"),
    ("worker", "db_password_aia_api"),
    ("api", "db_password_aia_api"),
    ("ingest", "db_password_aia_ingest"),
    ("maint-cli", "data_licence_seal_public_keys"),
    ("db-roles", "app_master_key"),
    ("beat", "data_licence_seal_public_keys"),
    ("signal-rt", "db_password_aia_maint"),
    ("migrate", "data_licence_seal_public_keys"),
    ("timescale-apply", "db_password_aia_api"),
    ("nginx", "data_licence_seal_public_keys"),
    ("postgres", "db_password_aia_api"),
    ("redis", "app_master_key"),
])
def test_secret_outside_service_whitelist_rejected(repo: Path, svc: str, secret: str) -> None:
    errs = _overlay(repo, f"services:\n  {svc}:\n    secrets:\n      - {secret}\n")
    assert any(f"服务 {svc} 挂了 {secret}，不在该服务的 secret 白名单" in e for e in errs), errs


def test_secret_long_form_outside_whitelist_rejected(repo: Path) -> None:
    errs = _overlay(repo, "services:\n  beat:\n    secrets:\n      - source: app_master_key\n        target: k\n")
    assert any("服务 beat 挂了 app_master_key，不在该服务的 secret 白名单" in e for e in errs), errs


def test_unregistered_top_level_secret_rejected(repo: Path) -> None:
    errs = _overlay(repo, "secrets:\n  extra_key:\n    file: ./extra\nservices:\n  api:\n    secrets:\n      - extra_key\n")
    assert any("顶层 secret extra_key 未登记" in e for e in errs), errs
    assert any("服务 api 挂了 extra_key，不在该服务的 secret 白名单" in e for e in errs), errs


def test_unregistered_service_with_secret_rejected(repo: Path) -> None:
    errs = _overlay(repo, "services:\n  newsvc:\n    secrets:\n      - data_licence_seal_public_keys\n")
    assert any("服务 newsvc 未在 MASTER_KEY_ALLOC 白名单登记" in e for e in errs), errs


@pytest.mark.parametrize("svc", ["api", "worker", "ingest", "db-roles", "maint-cli"])
def test_whitelisted_secret_allowed(repo: Path, svc: str) -> None:
    lines = "".join(f"      - {s}\n" for s in sorted(ccs.SERVICE_SECRETS[svc]))
    errs = _overlay(repo, f"services:\n  {svc}:\n    secrets:\n{lines}")
    assert not any("不在该服务的 secret 白名单" in e for e in errs), errs


def test_base_missing_whitelisted_secret_rejected(repo: Path) -> None:
    import yaml
    p = repo / ccs.BASE_COMPOSE
    doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    doc["services"]["maint-cli"]["secrets"] = []
    p.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    errs = ccs.check(repo)
    assert any("服务 maint-cli 缺少 secrets ['db_password_aia_maint']" in e for e in errs), errs


def test_ingest_forbid_flag_required_in_base(repo: Path) -> None:
    _sub(repo, ccs.BASE_COMPOSE, '      AIA_FORBID_APP_MASTER_KEY: "1"\n', "")
    assert any("服务 ingest 缺少 AIA_FORBID_APP_MASTER_KEY" in e for e in ccs.check(repo))


def test_overlay_cannot_disable_ingest_forbid(repo: Path) -> None:
    errs = _overlay(repo, 'services:\n  ingest:\n    environment:\n      AIA_FORBID_APP_MASTER_KEY: "0"\n')
    assert any("服务 ingest 的 AIA_FORBID_APP_MASTER_KEY 必须是" in e for e in errs), errs


def test_overlay_cannot_bypass_ingest_wrapper(repo: Path) -> None:
    errs = _overlay(repo, 'services:\n  ingest:\n    entrypoint: ["python"]\n')
    assert any("服务 ingest 的 entrypoint 必须是入口包装" in e for e in errs), errs


# ---- 评审 75c233b m1：入口包装防绕过、合并标签明确报错 ----
@pytest.mark.parametrize("env", ["environment:\n      AIA_SECRET_ENV_DIR: /nope\n",
                                 "environment:\n      - AIA_SECRET_ENV_DIR=/nope\n",
                                 "environment:\n      - AIA_SECRET_ENV_DIR\n"])
@pytest.mark.parametrize("svc", ["ingest", "api"])
def test_secret_env_dir_forbidden(repo: Path, svc: str, env: str) -> None:
    errs = _overlay(repo, f"services:\n  {svc}:\n    {env}")
    assert any(f"服务 {svc} 的 environment 设了 AIA_SECRET_ENV_DIR" in e for e in errs), errs


@pytest.mark.parametrize("vol", [
    "- ${AIA_SECRETS_DIR}:/s:ro",
    "- ${AIA_SECRETS_DIR:?x}/app_master_key:/k:ro",
    "- ~/.config/aia/secrets:/s:ro",
    "- /home/box/.config/aia/secrets/aia:/s",
    "- type: bind\n        source: ${AIA_SECRETS_DIR}\n        target: /s",
])
@pytest.mark.parametrize("svc", ["ingest", "beat"])
def test_secret_dir_volume_forbidden(repo: Path, svc: str, vol: str) -> None:
    errs = _overlay(repo, f"services:\n  {svc}:\n    volumes:\n      {vol}\n")
    assert any(f"服务 {svc} 把密钥目录当普通卷挂载" in e for e in errs), errs


@pytest.mark.parametrize("snippet,tag", [
    ("services:\n  ingest:\n    entrypoint: !reset null\n", "!reset"),
    ("services:\n  ingest:\n    environment: !reset {}\n", "!reset"),
    ("services:\n  ingest:\n    secrets: !override\n      - data_licence_seal_public_keys\n", "!override"),
])
def test_merge_tags_reported_not_crash(repo: Path, snippet: str, tag: str) -> None:
    errs = _overlay(repo, snippet)
    assert any("合并标签" in e and tag in e for e in errs), errs
    r = subprocess.run([sys.executable, str(CI_DIR / "check_secret_boundary.py"), "--repo", str(repo)],
                       capture_output=True, text=True)
    assert r.returncode == 1 and "Traceback" not in r.stderr and "::error title=secret-boundary::" in r.stdout


def test_invalid_yaml_reported_not_crash(repo: Path) -> None:
    errs = _overlay(repo, "services:\n  ingest:\n    environment: [\n")
    assert any("YAML 无法解析" in e for e in errs), errs


# ---- 评审 8cf9771 m2：密钥文件的定义不可改道（规则 10）----
S = "${AIA_SECRETS_DIR:?x}"


@pytest.mark.parametrize("snippet,needle", [
    # 自定义 secret 指向主密钥 / 证书私钥（起别名再挂给别的服务）
    (f"secrets:\n  mk2:\n    file: {S}/app_master_key\n", "secret mk2 的 file: 指向受保护的 app_master_key"),
    (f"secrets:\n  pk:\n    file: {S}/data_licence_seal_private_keys\n", "secret pk 的 file: 指向受保护的 data_licence_seal_private_keys"),
    ("secrets:\n  mk3:\n    file: /tmp/elsewhere/app_master_key\n", "secret mk3 的 file: 指向受保护的 app_master_key"),
    (f"secrets:\n  other:\n    file: {S}/something_new\n", "secret other 指向密钥目录里未登记的文件"),
    # 覆盖文件改路径 / 重定义受保护 secret
    ("secrets:\n  app_master_key:\n    file: /tmp/fake_master\n", "覆盖文件重定义了受保护的 secret app_master_key"),
    (f"secrets:\n  app_master_key:\n    file: {S}/app_master_key\n", "覆盖文件重定义了受保护的 secret app_master_key"),
    ("secrets:\n  data_licence_seal_private_keys:\n    file: ./pk\n", "覆盖文件重定义了受保护的 secret data_licence_seal_private_keys"),
    ("secrets:\n  db_password_aia_maint:\n    file: ./pw\n", "覆盖文件重定义了受保护的 secret db_password_aia_maint"),
    # configs 指向密钥
    (f"configs:\n  c1:\n    file: {S}/app_master_key\n", "config c1 引用了"),
    ("configs:\n  c2:\n    file: ~/.config/aia/secrets/aia/data_licence_seal_private_keys\n", "config c2 引用了"),
    ("configs:\n  c3:\n    environment: AIA_SECRETS_DIR\n", "config c3 引用了"),
    # 卷 driver_opts.device 指向密钥目录
    (f"volumes:\n  kv:\n    driver: local\n    driver_opts:\n      type: none\n      o: bind\n      device: {S}\n", "卷 kv 的 driver_opts 引用了"),
    ("volumes:\n  kv2:\n    driver_opts:\n      device: /home/box/.config/aia/secrets/aia\n", "卷 kv2 的 driver_opts 引用了"),
    # include / extends.file
    ("include:\n  - other.yml\n", "使用了 include:"),
    ("include:\n  - path: ../x/compose.yml\n", "使用了 include:"),
    ("services:\n  api:\n    extends:\n      file: ../x.yml\n      service: api\n", "服务 api 用 extends.file"),
    # 服务卷直接挂受保护文件（不经密钥目录变量）
    ("services:\n  beat:\n    volumes:\n      - /srv/keys/app_master_key:/k:ro\n", "服务 beat 把受保护的密钥文件当普通卷挂载"),
])
def test_rule10_overlay_rejected(repo: Path, snippet: str, needle: str) -> None:
    errs = _overlay(repo, snippet)
    assert any(needle in e for e in errs), errs


@pytest.mark.parametrize("old,new,needle", [
    ("file: ${AIA_SECRETS_DIR:?请用 deploy/scripts/compose.sh 调用}/app_master_key",
     "file: /tmp/app_master_key", "secret app_master_key 的 file: 必须是"),
    ("file: ${AIA_SECRETS_DIR:?请用 deploy/scripts/compose.sh 调用}/data_licence_seal_private_keys",
     "file: ${HOME}/data_licence_seal_private_keys", "secret data_licence_seal_private_keys 的 file: 必须是"),
    ("file: ${AIA_SECRETS_DIR:?请用 deploy/scripts/compose.sh 调用}/app_master_key",
     "file: ${AIA_SECRETS_DIR:?x}/db_password_aia_api", "secret app_master_key 的 file: 指向受保护的 db_password_aia_api"),
])
def test_rule10_base_path_pinned(repo: Path, old: str, new: str, needle: str) -> None:
    _sub(repo, ccs.BASE_COMPOSE, old, new)
    errs = ccs.check(repo)
    assert any(needle in e for e in errs), errs


@pytest.mark.parametrize("snippet", [
    "configs:\n  nginx_conf:\n    file: ./nginx.conf\n",
    "volumes:\n  data:\n    driver_opts:\n      type: tmpfs\n      device: tmpfs\n",
    "services:\n  api:\n    extends:\n      service: worker\n",
])
def test_rule10_benign_overlay_ok(repo: Path, snippet: str) -> None:
    assert _overlay(repo, snippet) == []


def test_rule10_ingest_cannot_bind_mount_private_keys(repo: Path) -> None:
    # 规则 3 放行 ingest 挂私钥路径；规则 10 要求私钥也只经 secrets:
    errs = _overlay(repo, "services:\n  ingest:\n    volumes:\n      - /srv/data_licence_seal_private_keys:/k:ro\n")
    assert any("服务 ingest 把受保护的密钥文件当普通卷挂载" in e for e in errs), errs


# ---------- T-A04 ⑪：imports 卷（review-028c077 M2）----------

IMPORTS_MOUNT = "      - imports:${IMPORT_STORAGE_PATH:-/var/lib/aia-dev/imports}\n"


def test_worker_mounts_imports_rw_in_base() -> None:
    import yaml
    doc = yaml.safe_load((REPO / ccs.BASE_COMPOSE).read_text(encoding="utf-8"))
    w = doc["services"]["worker"]
    mounts = ccs._volume_mounts(w["volumes"])
    assert ("imports", "${IMPORT_STORAGE_PATH:-/var/lib/aia-dev/imports}", False) in mounts
    assert w["environment"]["IMPORT_STORAGE_PATH"] == "${IMPORT_STORAGE_PATH:-/var/lib/aia-dev/imports}"


def test_worker_without_imports_rejected(repo: Path) -> None:
    _sub(repo, ccs.BASE_COMPOSE, "      # 读写（删除到期文件）；卷根目录属主 10001、700，与 api 共用同一卷\n" + IMPORTS_MOUNT, "")
    errs = ccs.check(repo)
    assert any("服务 worker 没有挂数据卷 imports" in e for e in errs), errs


@pytest.mark.parametrize("svc", ["ingest", "beat", "signal-rt", "migrate", "nginx"])
def test_imports_on_other_service_rejected(repo: Path, svc: str) -> None:
    errs = _overlay(repo, f"services:\n  {svc}:\n    volumes:\n      - imports:/data\n")
    assert any(f"服务 {svc} 挂了数据卷 imports" in e for e in errs), errs


@pytest.mark.parametrize("vol", ["      - imports:/var/lib/aia-dev/imports:ro\n",
                                 "      - type: volume\n        source: imports\n        target: /x\n        read_only: true\n"])
def test_imports_read_only_rejected(repo: Path, vol: str) -> None:
    errs = _overlay(repo, "services:\n  worker:\n    volumes:\n" + vol)
    assert any("服务 worker 只读挂载了数据卷 imports" in e for e in errs), errs


def test_imports_target_must_match_env(repo: Path) -> None:
    _sub(repo, ccs.BASE_COMPOSE, "      # 读写（删除到期文件）；卷根目录属主 10001、700，与 api 共用同一卷\n" + IMPORTS_MOUNT,
         "      - imports:/srv/elsewhere\n")
    errs = ccs.check(repo)
    assert any("服务 worker 的数据卷 imports 挂载点 /srv/elsewhere ≠ 其 IMPORT_STORAGE_PATH" in e for e in errs), errs


def test_volume_mounts_parses_colon_in_target() -> None:
    assert ccs._volume_mounts(["imports:${P:-/a/b}:ro", "x:/y", {"source": "s", "target": "/t"}]) == [
        ("imports", "${P:-/a/b}", True), ("x", "/y", False), ("s", "/t", False)]


# ---------- review-baa4539 M1：master 快照卷只给 worker ----------

MASTER_MOUNT = "      - master:${MASTER_SNAPSHOT_PATH:-/var/lib/aia-dev/master}\n"


def test_worker_mounts_master_rw_in_base() -> None:
    import yaml
    doc = yaml.safe_load((REPO / ccs.BASE_COMPOSE).read_text(encoding="utf-8"))
    w = doc["services"]["worker"]
    mounts = ccs._volume_mounts(w["volumes"])
    assert ("master", "${MASTER_SNAPSHOT_PATH:-/var/lib/aia-dev/master}", False) in mounts
    assert w["environment"]["MASTER_SNAPSHOT_PATH"] == "${MASTER_SNAPSHOT_PATH:-/var/lib/aia-dev/master}"
    assert "app_master_key" in ccs._secret_names(w.get("secrets"))
    assert "data_licence_seal_private_keys" not in ccs._secret_names(w.get("secrets"))


def test_worker_without_master_rejected(repo: Path) -> None:
    _sub(repo, ccs.BASE_COMPOSE, MASTER_MOUNT, "")
    errs = ccs.check(repo)
    assert any("服务 worker 没有挂数据卷 master" in e for e in errs), errs


def test_worker_without_master_env_rejected(repo: Path) -> None:
    _sub(repo, ccs.BASE_COMPOSE, "      MASTER_SNAPSHOT_PATH: ${MASTER_SNAPSHOT_PATH:-/var/lib/aia-dev/master}\n", "")
    errs = ccs.check(repo)
    assert any("服务 worker 缺少 MASTER_SNAPSHOT_PATH" in e for e in errs), errs


@pytest.mark.parametrize("svc", ["api", "ingest", "beat", "signal-rt", "nginx"])
def test_master_on_other_service_rejected(repo: Path, svc: str) -> None:
    errs = _overlay(repo, f"services:\n  {svc}:\n    volumes:\n      - master:/data\n")
    assert any(f"服务 {svc} 挂了数据卷 master" in e for e in errs), errs


def test_master_read_only_rejected(repo: Path) -> None:
    errs = _overlay(repo, "services:\n  worker:\n    volumes:\n      - master:/var/lib/aia-dev/master:ro\n")
    assert any("服务 worker 只读挂载了数据卷 master" in e for e in errs), errs


def test_master_target_must_match_env(repo: Path) -> None:
    _sub(repo, ccs.BASE_COMPOSE, MASTER_MOUNT, "      - master:/srv/elsewhere\n")
    errs = ccs.check(repo)
    assert any("服务 worker 的数据卷 master 挂载点 /srv/elsewhere ≠ 其 MASTER_SNAPSHOT_PATH" in e for e in errs), errs
