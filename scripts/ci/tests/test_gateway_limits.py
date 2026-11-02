"""check_gateway_limits.py 正反例（T-O03）：nginx client_max_body_size ↔ config/imports.yaml ↔ 413 信封 max_bytes。"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import check_gateway_limits as cgl
from conftest import CI_DIR, REPO, write

PLAN_YAML = ("schema_version: 1\nmax_file_bytes: 5242880\nmax_files_per_upload: 5\nmax_request_bytes: 27262976\n"
             "max_rows_per_file: 50000\nallowed_extensions: [\".txt\", \".csv\"]\nraw_file_retention_days: 365\n")


@pytest.fixture
def gw_repo(tmp_path: Path) -> Path:
    """用仓库里真实的 nginx.conf + plan 6.1 的 imports.yaml 取值。"""
    (tmp_path / "deploy/nginx").mkdir(parents=True)
    shutil.copy(REPO / cgl.NGINX_CONF, tmp_path / cgl.NGINX_CONF)
    (tmp_path / "deploy/compose").mkdir(parents=True)
    for rel in (cgl.LIMITS_PROD, cgl.LIMITS_DEV, cgl.COMPOSE_BASE, cgl.COMPOSE_DEV):
        shutil.copy(REPO / rel, tmp_path / rel)
    write(tmp_path, cgl.IMPORTS_YAML, PLAN_YAML)
    return tmp_path


def _sub(repo: Path, rel: str, old: str, new: str) -> None:
    p = repo / rel
    text = p.read_text(encoding="utf-8")
    assert old in text, old
    p.write_text(text.replace(old, new), encoding="utf-8")


def test_repo_nginx_matches_plan_values(gw_repo: Path) -> None:
    assert cgl.check(gw_repo) == []


def test_cli_exit_codes(gw_repo: Path) -> None:
    run = lambda: subprocess.run([sys.executable, str(CI_DIR / "check_gateway_limits.py"), "--repo", str(gw_repo)],  # noqa: E731
                                 capture_output=True, text=True)
    assert run().returncode == 0
    (gw_repo / cgl.IMPORTS_YAML).unlink()
    r = run()
    assert r.returncode == 1 and "config/imports.yaml 不存在" in r.stdout, r.stdout


def test_missing_imports_yaml_is_explicit_error(gw_repo: Path) -> None:
    (gw_repo / cgl.IMPORTS_YAML).unlink()
    errs = cgl.check(gw_repo)
    assert len(errs) == 1 and "不存在" in errs[0]


@pytest.mark.parametrize("old,new,needle", [
    ("client_max_body_size 26m;", "client_max_body_size 25m;", "不大于"),        # = 应用上限，不是“略大于”
    ("client_max_body_size 26m;", "client_max_body_size 27m;", "≠ imports.max_request_bytes"),
    ('"max_bytes":27262976', '"max_bytes":26214400', "413 信封"),
])
def test_nginx_mismatch(gw_repo: Path, old: str, new: str, needle: str) -> None:
    _sub(gw_repo, cgl.NGINX_CONF, old, new)
    errs = cgl.check(gw_repo)
    assert any(needle in e for e in errs), errs


@pytest.mark.parametrize("old,new,needle", [
    ("max_request_bytes: 27262976", "max_request_bytes: 26214400", "≠ imports.max_request_bytes"),
    ("max_file_bytes: 5242880", "max_file_bytes: 6291456", "不大于"),                    # 6 MiB × 5 > 26m
    ("max_files_per_upload: 5", "max_files_per_upload: \"5\"", "不是正整数"),
    ("max_file_bytes: 5242880\n", "", "max_file_bytes 缺失"),
])
def test_imports_yaml_mismatch(gw_repo: Path, old: str, new: str, needle: str) -> None:
    _sub(gw_repo, cgl.IMPORTS_YAML, old, new)
    errs = cgl.check(gw_repo)
    assert any(needle in e for e in errs), errs


def test_units_and_nested_imports_key(gw_repo: Path) -> None:
    _sub(gw_repo, cgl.NGINX_CONF, "client_max_body_size 26m;", "client_max_body_size 26624k;")
    write(gw_repo, cgl.IMPORTS_YAML, "imports:\n" + "".join("  " + ln + "\n" for ln in PLAN_YAML.splitlines()))
    assert cgl.check(gw_repo) == []


def test_commented_directive_ignored_and_conflicting_values(gw_repo: Path) -> None:
    _sub(gw_repo, cgl.NGINX_CONF, "client_max_body_size 26m;", "# client_max_body_size 1m;\n  client_max_body_size 26m;")
    assert cgl.check(gw_repo) == []
    _sub(gw_repo, cgl.NGINX_CONF, "listen 80;", "listen 80;\n    client_max_body_size 1m;")
    assert any("多个不同取值" in e for e in cgl.check(gw_repo))


# ---------------------------------------------------------------- 限流（T-O10）

def test_repo_rate_limits_ok(gw_repo: Path) -> None:
    assert cgl.check_rate_limits(gw_repo) == []


@pytest.mark.parametrize("rel,old,new,needle", [
    (cgl.LIMITS_PROD, "limit_req_zone $binary_remote_addr zone=aia_api", "limit_req_zone $http_x_forwarded_for zone=aia_api",
     "键是 $http_x_forwarded_for"),
    (cgl.LIMITS_PROD, "zone=aia_auth:10m rate=20r/m;", "zone=aia_auth:10m rate=30r/m;", "ceil(1/速率) = 2"),
    (cgl.LIMITS_PROD, "limit_req_zone $aia_import_key zone=aia_import:10m rate=6r/m;\n", "", "缺少 limit_req_zone aia_import"),
    (cgl.LIMITS_DEV, "zone=aia_api:10m rate=1000r/s;", "zone=aia_api:10m rate=5r/s;", "速率低于生产"),
    (cgl.NGINX_CONF, "  limit_req_status 429;\n", "", "limit_req_status 429"),
    (cgl.NGINX_CONF, "include /etc/nginx/aia-limits.conf;", "include /etc/nginx/other.conf;", "没有 include"),
    (cgl.NGINX_CONF, "    default $binary_remote_addr;\n", "    default $http_x_real_ip;\n", "$aia_import_key"),
    (cgl.NGINX_CONF, "limit_req zone=aia_auth burst=10 nodelay;", "", "zone=aia_auth"),
    (cgl.NGINX_CONF, "limit_req zone=aia_import burst=5 nodelay;", "", "zone=aia_import"),
    (cgl.NGINX_CONF, "error_page 429 @rate_limited;", "", "error_page 429"),
    (cgl.NGINX_CONF, '"code":"RATE_LIMITED"', '"code":"TOO_MANY"', "RATE_LIMITED"),
    (cgl.NGINX_CONF, "add_header Retry-After $aia_retry_after_s always;", "", "Retry-After"),
    (cgl.LIMITS_DEV, "limit_req_dry_run on;", "# limit_req_dry_run on;", "缺少 limit_req_dry_run on"),
    (cgl.LIMITS_PROD, "limit_req_zone $binary_remote_addr zone=aia_api", "limit_req_dry_run on;\nlimit_req_zone $binary_remote_addr zone=aia_api",
     "不得 limit_req_dry_run"),
    (cgl.COMPOSE_DEV, "../nginx/limits.dev.conf:/etc/nginx/aia-limits.conf:ro", "../nginx/limits.conf:/etc/nginx/aia-limits.conf:ro",
     "limits.dev.conf"),
])
def test_rate_limit_negative(gw_repo: Path, rel: str, old: str, new: str, needle: str) -> None:
    _sub(gw_repo, rel, old, new)
    errs = cgl.check_rate_limits(gw_repo)
    assert any(needle in e for e in errs), errs


def test_global_api_limit_required(gw_repo: Path) -> None:
    conf = (gw_repo / cgl.NGINX_CONF).read_text(encoding="utf-8")
    head = "    location /api/ {\n      limit_req zone=aia_api burst=100 nodelay;\n"
    assert head in conf
    (gw_repo / cgl.NGINX_CONF).write_text(conf.replace(head, "    location /api/ {\n"), encoding="utf-8")
    assert any("location /api/ 没有 limit_req zone=aia_api" in e for e in cgl.check_rate_limits(gw_repo))


# ---- 上游动态解析（T-O13）----

def test_repo_dynamic_upstream_ok(gw_repo: Path) -> None:
    assert cgl.check_dynamic_upstream(gw_repo) == []


@pytest.mark.parametrize("rel,old,new,needle", [
    (cgl.NGINX_CONF, "  resolver 127.0.0.11 valid=10s ipv6=off;\n", "", "需要且只能有一条 resolver"),
    (cgl.NGINX_CONF, "resolver 127.0.0.11 valid=10s", "resolver 8.8.8.8 valid=10s", "127.0.0.11"),
    (cgl.NGINX_CONF, "resolver 127.0.0.11 valid=10s", "resolver 127.0.0.11 valid=300s", "valid=≤30s"),
    (cgl.NGINX_CONF, "resolver 127.0.0.11 valid=10s ipv6=off;", "resolver 127.0.0.11 ipv6=off;", "valid=≤30s"),
    (cgl.NGINX_CONF, "  resolver_timeout 3s;\n", "  resolver_timeout 3s;\n  upstream api_upstream { server api:8000; }\n", "静态 upstream"),
    (cgl.NGINX_CONF, '    default "api:8000";\n', '    default "api:9000";\n', "map $host $aia_api_upstream"),
    # 回退成静态主机名（location /api/ 那一处）
    (cgl.NGINX_CONF, "location /api/ {\n      limit_req zone=aia_api burst=100 nodelay;\n      proxy_pass http://$aia_api_upstream;",
     "location /api/ {\n      limit_req zone=aia_api burst=100 nodelay;\n      proxy_pass http://api:8000;", "静态主机名不会重新解析"),
    (cgl.NGINX_CONF, "/api/v1/health/live$is_args$args;", "/api/v1/health/live;", "$is_args$args"),
    (cgl.COMPOSE_BASE, "http://127.0.0.1/health/live || exit 1", "http://127.0.0.1/healthz || exit 1", "探上游"),
    (cgl.COMPOSE_DEV, "      - ../nginx/limits.dev.conf:/etc/nginx/aia-limits.conf:ro\n",
     "      - ../nginx/limits.dev.conf:/etc/nginx/aia-limits.conf:ro\n    healthcheck:\n      test: [\"CMD\", \"true\"]\n",
     "不得覆盖 nginx healthcheck"),
    # 外部 DNS 断开（T-O13 补）
    (cgl.COMPOSE_BASE, "    dns:\n      - 127.0.0.1\n", "", "dns: [127.0.0.1]"),
    (cgl.COMPOSE_BASE, "    dns:\n      - 127.0.0.1\n", "    dns:\n      - 8.8.8.8\n", "dns: [127.0.0.1]"),
    (cgl.COMPOSE_BASE, "    dns:\n      - 127.0.0.1\n", "    dns:\n      - 127.0.0.1\n      - 1.1.1.1\n", "dns: [127.0.0.1]"),
    (cgl.COMPOSE_DEV, "      - ../nginx/limits.dev.conf:/etc/nginx/aia-limits.conf:ro\n",
     "      - ../nginx/limits.dev.conf:/etc/nginx/aia-limits.conf:ro\n    dns: 1.1.1.1\n", "不得覆盖 nginx dns"),
])
def test_dynamic_upstream_negative(gw_repo: Path, rel: str, old: str, new: str, needle: str) -> None:
    _sub(gw_repo, rel, old, new)
    errs = cgl.check_dynamic_upstream(gw_repo)
    assert any(needle in e for e in errs), errs


def test_dynamic_upstream_in_cli(gw_repo: Path) -> None:
    _sub(gw_repo, cgl.NGINX_CONF, "  resolver 127.0.0.11 valid=10s ipv6=off;\n", "")
    r = subprocess.run([sys.executable, str(CI_DIR / "check_gateway_limits.py"), "--repo", str(gw_repo)],
                       capture_output=True, text=True)
    assert r.returncode == 1 and "resolver" in r.stdout, r.stdout


# ---- 规则 10：414 / 494 JSON 信封（T-D） ----

def test_repo_header_limits_ok(gw_repo: Path) -> None:
    assert cgl.check_header_limits(gw_repo) == []


@pytest.mark.parametrize("rel,old,new,needle", [
    (cgl.NGINX_CONF, "    large_client_header_buffers 4 8k;\n", "", "large_client_header_buffers"),
    (cgl.NGINX_CONF, "large_client_header_buffers 4 8k;", "large_client_header_buffers 4 16k;", "不一致"),
    (cgl.NGINX_CONF, "error_page 414 /__aia_errors/414;", "error_page 414 @uri_too_long;", "命名 location"),
    (cgl.NGINX_CONF, "    error_page 414 /__aia_errors/414;\n", "", "error_page 414"),
    (cgl.NGINX_CONF, "location = /__aia_errors/414 {\n      internal;\n", "location = /__aia_errors/414 {\n", "internal"),
    (cgl.NGINX_CONF, '"code":"URI_TOO_LONG"', '"code":"BAD_REQUEST"', "URI_TOO_LONG"),
    (cgl.NGINX_CONF, 'return 414 \'{"error":{"code":"URI_TOO_LONG","message":"请求地址过长","details":{"max_bytes":8192}',
     'return 414 \'{"error":{"code":"URI_TOO_LONG","message":"请求地址过长","details":{"max_bytes":4096}', "不一致"),
    (cgl.NGINX_CONF, "    error_page 494 =400 @header_too_large;\n", "", "error_page 494"),
    (cgl.NGINX_CONF, '"code":"REQUEST_HEADER_TOO_LARGE"', '"code":"X"', "REQUEST_HEADER_TOO_LARGE"),
    (cgl.LIMITS_DEV, "limit_req_dry_run on;", "limit_req_dry_run on;\nlarge_client_header_buffers 4 32k;", "不得设置"),
])
def test_header_limits_negative(gw_repo: Path, rel: str, old: str, new: str, needle: str) -> None:
    _sub(gw_repo, rel, old, new)
    errs = cgl.check_header_limits(gw_repo)
    assert any(needle in e for e in errs), errs


def test_header_limits_x_request_id_required(gw_repo: Path) -> None:
    p = gw_repo / cgl.NGINX_CONF
    t = p.read_text(encoding="utf-8")
    i = t.index("location = /__aia_errors/414 {")
    j = t.index("\n    }\n", i)
    p.write_text(t[:i] + t[i:j].replace("add_header X-Request-Id $aia_request_id always;", "") + t[j:], encoding="utf-8")
    assert any("X-Request-Id" in e for e in cgl.check_header_limits(gw_repo))


def test_header_limits_in_cli(gw_repo: Path) -> None:
    _sub(gw_repo, cgl.NGINX_CONF, "error_page 414 /__aia_errors/414;", "error_page 414 @uri_too_long;")
    r = subprocess.run([sys.executable, str(CI_DIR / "check_gateway_limits.py"), "--repo", str(gw_repo)],
                       capture_output=True, text=True)
    assert r.returncode == 1 and "命名 location" in r.stdout, r.stdout


def test_dynamic_upstream_dns_string_form_ok(gw_repo: Path) -> None:
    _sub(gw_repo, cgl.COMPOSE_BASE, "    dns:\n      - 127.0.0.1\n", "    dns: 127.0.0.1\n")
    assert cgl.check_dynamic_upstream(gw_repo) == []


# ---- 评审 d1a148f：m1 resolver 只能一个地址 / map 分支只能内部短名；m2 network_mode；n !reset、叠加文件 ----

NGINX_SVC = "  nginx:\n"


@pytest.mark.parametrize("rel,old,new,needle", [
    # m1：多个 resolver 地址（nginx 轮询，会直接查外部 DNS）
    (cgl.NGINX_CONF, "resolver 127.0.0.11 valid=10s", "resolver 127.0.0.11 1.1.1.1 valid=10s", "只能写 Docker DNS 127.0.0.11 一个地址"),
    (cgl.NGINX_CONF, "resolver 127.0.0.11 valid=10s", "resolver 1.1.1.1 127.0.0.11 valid=10s", "只能写 Docker DNS 127.0.0.11 一个地址"),
    (cgl.NGINX_CONF, "resolver 127.0.0.11 valid=10s", "resolver 127.0.0.11 127.0.0.11:5353 valid=10s", "一个地址"),
    (cgl.NGINX_CONF, "resolver 127.0.0.11 valid=10s", "resolver [2606:4700::1111] 127.0.0.11 valid=10s", "一个地址"),
    # m1：map 新增分支指向外部主机 / IP
    (cgl.NGINX_CONF, '    default "api:8000";\n', '    default "api:8000";\n    ~^x evil.example.com:443;\n', "内部短名"),
    (cgl.NGINX_CONF, '    default "api:8000";\n', '    default "api:8000";\n    "~^y" "203.0.113.5:80";\n', "内部短名"),
    (cgl.NGINX_CONF, '    default "api:8000";\n', '    default "api:8000";\n    ~^z api.svc.cluster.local:8000;\n', "内部短名"),
    # m2：network_mode（任何文件、任何取值）
    (cgl.COMPOSE_DEV, "      - ../nginx/limits.dev.conf:/etc/nginx/aia-limits.conf:ro\n",
     "      - ../nginx/limits.dev.conf:/etc/nginx/aia-limits.conf:ro\n    network_mode: host\n", "不得设 network_mode"),
    (cgl.COMPOSE_BASE, "    dns:\n      - 127.0.0.1\n", "    dns:\n      - 127.0.0.1\n    network_mode: host\n", "不得设 network_mode"),
    (cgl.COMPOSE_BASE, "    dns:\n      - 127.0.0.1\n", "    dns:\n      - 127.0.0.1\n    network_mode: \"service:api\"\n", "不得设 network_mode"),
    # n：!reset / !override 给明确报错
    (cgl.COMPOSE_DEV, "      - ../nginx/limits.dev.conf:/etc/nginx/aia-limits.conf:ro\n",
     "      - ../nginx/limits.dev.conf:/etc/nginx/aia-limits.conf:ro\n    dns: !reset []\n", "!reset"),
    (cgl.COMPOSE_DEV, "      - ../nginx/limits.dev.conf:/etc/nginx/aia-limits.conf:ro\n",
     "      - ../nginx/limits.dev.conf:/etc/nginx/aia-limits.conf:ro\n    dns: !override [1.1.1.1]\n", "!override"),
    (cgl.COMPOSE_BASE, "    dns:\n      - 127.0.0.1\n", "    dns: !reset null\n", "!reset"),
    # extends
    (cgl.COMPOSE_DEV, "      - ../nginx/limits.dev.conf:/etc/nginx/aia-limits.conf:ro\n",
     "      - ../nginx/limits.dev.conf:/etc/nginx/aia-limits.conf:ro\n    extends:\n      file: other.yml\n      service: gw\n", "extends"),
])
def test_d1a148f_followups_negative(gw_repo: Path, rel: str, old: str, new: str, needle: str) -> None:
    _sub(gw_repo, rel, old, new)
    errs = cgl.check_dynamic_upstream(gw_repo)
    assert any(needle in e for e in errs), errs


def test_reset_tag_does_not_crash_cli(gw_repo: Path) -> None:
    _sub(gw_repo, cgl.COMPOSE_DEV, "      - ../nginx/limits.dev.conf:/etc/nginx/aia-limits.conf:ro\n",
         "      - ../nginx/limits.dev.conf:/etc/nginx/aia-limits.conf:ro\n    dns: !reset []\n")
    r = subprocess.run([sys.executable, str(CI_DIR / "check_gateway_limits.py"), "--repo", str(gw_repo)],
                       capture_output=True, text=True)
    assert r.returncode == 1 and "Traceback" not in r.stderr, r.stderr
    assert "::error" in r.stdout and "!reset" in r.stdout and "不允许" in r.stdout, r.stdout


def test_map_internal_short_name_branch_ok(gw_repo: Path) -> None:
    _sub(gw_repo, cgl.NGINX_CONF, '    default "api:8000";\n', '    default "api:8000";\n    ~^canary api-canary:8000;\n')
    assert cgl.check_dynamic_upstream(gw_repo) == []


@pytest.mark.parametrize("name,body,needles", [
    # docker compose 在 deploy/compose 里会自动加载这个文件
    ("docker-compose.override.yml", "services:\n  nginx:\n    dns: [1.1.1.1]\n", ("只允许", "不得覆盖 nginx dns")),
    ("docker-compose.override.yml", "services:\n  nginx:\n    network_mode: host\n", ("只允许", "network_mode")),
    ("compose.override.yaml", "services:\n  nginx:\n    healthcheck:\n      test: [\"CMD\", \"true\"]\n", ("只允许", "healthcheck")),
    ("docker-compose.override.yml", "services:\n  nginx:\n    dns: !reset []\n", ("只允许", "!reset")),
    ("docker-compose.extra.yml", "services: {}\n", ("只允许",)),
])
def test_override_files_checked(gw_repo: Path, name: str, body: str, needles: tuple[str, ...]) -> None:
    write(gw_repo, f"{cgl.COMPOSE_DIR}/{name}", body)
    errs = cgl.check_dynamic_upstream(gw_repo)
    for n in needles:
        assert any(n in e and name in e for e in errs), (n, errs)


def test_non_compose_files_in_compose_dir_ignored(gw_repo: Path) -> None:
    write(gw_repo, f"{cgl.COMPOSE_DIR}/README.md", "x\n")
    assert cgl.check_dynamic_upstream(gw_repo) == []


def test_repo_compose_dir_has_no_extra_files() -> None:
    assert cgl.extra_compose_files(REPO) == []


# ---------- T-A04 ⑤：证券搜索限流 + Cache-Control（规则 11）----------

def test_search_rule_ok_on_repo(gw_repo: Path) -> None:
    assert cgl.check_search(gw_repo) == []
    assert cgl.check_rate_limits(gw_repo) == []


@pytest.mark.parametrize("rel,old,new,needle", [
    (cgl.NGINX_CONF, "limit_req zone=aia_search burst=20 nodelay;", "limit_req zone=aia_search burst=50 nodelay;", "burst=20"),
    (cgl.NGINX_CONF, "limit_req zone=aia_search burst=20 nodelay;", "", "没有 limit_req zone=aia_search"),
    (cgl.NGINX_CONF, "      proxy_hide_header Cache-Control;\n", "", "proxy_hide_header"),
    (cgl.NGINX_CONF, '      add_header Cache-Control "private, no-store" always;\n    }\n\n    # 方法透传', "    }\n\n    # 方法透传",
     "证券 location 需要 add_header"),
    (cgl.NGINX_CONF, '"~^/api/v1/securities\\?(.*&)?q="         $binary_remote_addr;\n', "", "$aia_search_key 应只把"),
    (cgl.NGINX_CONF, 'default                                  "";\n  }\n  include', 'default $binary_remote_addr;\n  }\n  include',
     "$aia_search_key 应只把"),
    (cgl.LIMITS_PROD, "zone=aia_search:10m rate=5r/s;", "zone=aia_search:10m rate=10r/s;", "aia_search 生产速率应为 5r/s"),
    (cgl.LIMITS_PROD, "limit_req_zone $aia_search_key zone=aia_search", "limit_req_zone $binary_remote_addr zone=aia_search",
     "zone aia_search 的键"),
    (cgl.LIMITS_DEV, "zone=aia_search:10m rate=1000r/s;", "zone=aia_search:10m rate=1r/s;", "aia_search 速率低于生产"),
])
def test_search_rule_negative(gw_repo: Path, rel: str, old: str, new: str, needle: str) -> None:
    _sub(gw_repo, rel, old, new)
    errs = cgl.check_search(gw_repo) + cgl.check_rate_limits(gw_repo)
    assert any(needle in e for e in errs), errs


@pytest.mark.parametrize("loc", ["@rate_limited", "@payload_too_large", "@header_too_large", "/__aia_errors/414"])
def test_gateway_envelopes_private_no_store(gw_repo: Path, loc: str) -> None:
    conf = (gw_repo / cgl.NGINX_CONF).read_text(encoding="utf-8")
    body = cgl._location_body(cgl.strip_comments(conf), loc)
    assert body and cgl.NO_STORE in body
    p = gw_repo / cgl.NGINX_CONF
    head = f"location = {loc} {{" if loc.startswith("/") else f"location {loc} {{"
    i = conf.index(head)
    j = conf.index(cgl.NO_STORE, i)
    p.write_text(conf[:j] + 'add_header Cache-Control "no-store" always;' + conf[j + len(cgl.NO_STORE):], encoding="utf-8")
    assert any(f"location {loc} 缺少" in e for e in cgl.check_search(gw_repo))


@pytest.mark.parametrize("rel,line", [(cgl.NGINX_CONF, "  proxy_cache_path /tmp/c keys_zone=c:1m;\n"),
                                      (cgl.LIMITS_PROD, "proxy_cache_path /tmp/c keys_zone=c:1m;\n")])
def test_proxy_cache_forbidden(gw_repo: Path, rel: str, line: str) -> None:
    anchor = "  include /etc/nginx/aia-limits.conf;\n" if rel == cgl.NGINX_CONF else "limit_req_zone $aia_search_key"
    _sub(gw_repo, rel, anchor, line + anchor if rel == cgl.NGINX_CONF else line + anchor)
    assert any("不得启用 proxy_cache" in e for e in cgl.check_search(gw_repo))
