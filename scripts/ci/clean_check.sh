#!/usr/bin/env bash
# 干净检出自检（T-O09a）：在临时目录里检出“已提交的内容”（默认 HEAD），跑和 CI 相同的步骤，跑完自动清理。
#
#   bash scripts/ci/clean_check.sh <job...|quick|all> [--rev <提交>] [--base <提交>] [--keep]
#
# job：ignored-sources secret-scan selftest fixtures gateway-limits secret-boundary licenses pip-audit
#      backend frontend contract migrations image
#   quick = ignored-sources secret-boundary gateway-limits secret-scan（几秒到十几秒，适合 pre-push）
#   all   = 全部（contract / migrations / image 需要 docker）
# --rev   要检查的提交，默认 HEAD（只看提交，不看工作树和暂存区）
# --base  secret-scan 的范围起点，默认 origin/main（找不到就只扫 tree）
# --keep  不删临时目录（排查用）
#
# 安全：
# - 只用 `git clone --shared --no-checkout` 到 mktemp 目录，再 detach 检出 --rev。不在你的工作树里执行
#   git clean / reset / stash / checkout，不碰未提交的文件；不在你的仓库里新建 worktree 或分支。
# - 子进程不带 MAIRUI_LICENCE / DEEPSEEK_API_KEY（env -u，只影响本脚本的子进程，不改你的 shell）。
#   麦蕊基址指向 127.0.0.1:9，与 CI 相同，不会访问麦蕊。
# - 需要数据库的 job 起临时容器 clean-check-<pid>-*（随机本机端口），退出时删除；不碰其他容器和卷。
# - 依赖缓存：uv 缓存、pnpm store 在本机复用（和 CI 的缓存一样只缓存下载，不带工作区文件）。
set -euo pipefail

if [ -z "${_CLEAN_CHECK_SANITIZED:-}" ]; then
  exec env -u MAIRUI_LICENCE -u DEEPSEEK_API_KEY _CLEAN_CHECK_SANITIZED=1 bash "$0" "$@"
fi

ALL_JOBS=(ignored-sources secret-scan selftest fixtures gateway-limits secret-boundary licenses pip-audit
          backend frontend contract migrations image)
QUICK_JOBS=(ignored-sources secret-boundary gateway-limits secret-scan)

usage() { sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-2}"; }

rev=HEAD base=origin/main keep=0 jobs=()
while [ $# -gt 0 ]; do
  case "$1" in
    --rev) rev="$2"; shift 2 ;;
    --base) base="$2"; shift 2 ;;
    --keep) keep=1; shift ;;
    -h|--help) usage 0 ;;
    all) jobs+=("${ALL_JOBS[@]}"); shift ;;
    quick) jobs+=("${QUICK_JOBS[@]}"); shift ;;
    *) if [[ " ${ALL_JOBS[*]} " == *" $1 "* ]]; then jobs+=("$1"); shift; else echo "未知 job：$1" >&2; usage; fi ;;
  esac
done
[ ${#jobs[@]} -gt 0 ] || usage

src_repo=$(git rev-parse --show-toplevel)
sha=$(git -C "$src_repo" rev-parse --verify "${rev}^{commit}")
base_sha=$(git -C "$src_repo" rev-parse --verify -q "${base}^{commit}" || true)

wf="$src_repo/.github/workflows"
wf_env() { git -C "$src_repo" show "$sha:.github/workflows/$1" | sed -n "s/^  $2: *\"\{0,1\}\([^\"]*\)\"\{0,1\}.*/\1/p" | head -1; }
export MAIRUI_BASE_URL="http://127.0.0.1:9" MAIRUI_PRO_BASE_URL="http://127.0.0.1:9"
export UV_PYTHON="$(wf_env ci.yml UV_PYTHON)" UV_PYTHON_DOWNLOADS=automatic
PYYAML_VERSION="$(wf_env ci.yml PYYAML_VERSION)"
PYTEST_VERSION="$(wf_env secret-scan.yml PYTEST_VERSION)"
PYTEST_COV_VERSION="$(wf_env ci.yml PYTEST_COV_VERSION)"
PIP_AUDIT_VERSION="$(wf_env ci.yml PIP_AUDIT_VERSION)"
SCHEMATHESIS_VERSION="$(wf_env ci.yml SCHEMATHESIS_VERSION)"
TIMESCALE_IMAGE="$(wf_env ci.yml TIMESCALE_IMAGE)"
REDIS_IMAGE="$(wf_env ci.yml REDIS_IMAGE)"
GITLEAKS_VERSION="$(wf_env secret-scan.yml GITLEAKS_VERSION)"
GITLEAKS_SHA256="$(wf_env secret-scan.yml GITLEAKS_SHA256)"

tmp=$(mktemp -d "${TMPDIR:-/tmp}/clean-check.XXXXXX")
export RUNNER_TEMP="$tmp/runner"
mkdir -p "$RUNNER_TEMP"
tag="clean-check-$$"
cleanup() {
  docker rm -f "$tag-db" "$tag-redis" "$tag-api" >/dev/null 2>&1 || true
  docker rmi "aia-backend:$tag" >/dev/null 2>&1 || true
  if [ "$keep" = 1 ]; then echo "临时目录保留在 $tmp"; else rm -rf "$tmp"; fi
}
trap cleanup EXIT

git clone -q --shared --no-checkout "$src_repo" "$tmp/wt"
git -C "$tmp/wt" -c advice.detachedHead=false checkout -q --detach "$sha"
cd "$tmp/wt"
echo "干净检出：$sha（$tmp/wt，只含已提交内容）"

pyrun() { uv run --no-project -q --with "pyyaml==${PYYAML_VERSION}" python "$@"; }

gitleaks_bin() {
  if [ -n "${GITLEAKS_BIN:-}" ] && [ -x "$GITLEAKS_BIN" ]; then return; fi
  local d="${XDG_CACHE_HOME:-$HOME/.cache}/aia-ci/gitleaks-${GITLEAKS_VERSION}"
  if [ ! -x "$d/gitleaks" ]; then
    mkdir -p "$d"
    curl -fsSLo "$d/gitleaks.tgz" "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz"
    echo "${GITLEAKS_SHA256}  $d/gitleaks.tgz" | sha256sum -c - >/dev/null
    tar -xzf "$d/gitleaks.tgz" -C "$d" gitleaks && rm -f "$d/gitleaks.tgz"
  fi
  export GITLEAKS_BIN="$d/gitleaks"
}

start_db() {  # 临时 timescale（+ redis），导出 DATABASE_URL / REDIS_URL
  docker run -d --name "$tag-db" -e POSTGRES_USER=aia -e POSTGRES_PASSWORD=ci-only -e POSTGRES_DB=aia \
    -p 127.0.0.1::5432 "$TIMESCALE_IMAGE" >/dev/null
  for _ in $(seq 1 60); do docker exec "$tag-db" pg_isready -U aia -d aia -q 2>/dev/null && break; sleep 1; done
  sleep 2
  export DATABASE_URL="postgresql://aia:ci-only@$(docker port "$tag-db" 5432/tcp | head -1)/aia" APP_ENV=test
  if [ "${1:-}" = redis ]; then
    docker run -d --name "$tag-redis" -p 127.0.0.1::6379 "$REDIS_IMAGE" >/dev/null
    export REDIS_URL="redis://$(docker port "$tag-redis" 6379/tcp | head -1)/0"
  fi
}

job_ignored-sources() { python3 scripts/ci/check_ignored_sources.py; }
job_fixtures()        { pyrun scripts/ci/check_fixtures.py; }
job_gateway-limits()  {  # 与 CI 同步（T-O10）：静态规则 + 有 docker 时跑 nginx 限流运行时冒烟
  pyrun scripts/ci/check_gateway_limits.py || return 1
  if docker info >/dev/null 2>&1; then bash scripts/ci/nginx_limits_smoke.sh both; else echo "（没有 docker，跳过 nginx_limits_smoke.sh；CI 会跑）"; fi
}
job_secret-boundary() { pyrun scripts/ci/check_secret_boundary.py; }
job_secret-scan() {
  gitleaks_bin
  if [ -n "$base_sha" ] && git merge-base --is-ancestor "$base_sha" "$sha" && [ "$base_sha" != "$sha" ]; then
    bash scripts/ci/gitleaks_run.sh range "$base_sha..$sha" "$RUNNER_TEMP/gitleaks.json"
    pyrun scripts/ci/gitleaks_report.py "$RUNNER_TEMP/gitleaks.json"
    pyrun scripts/ci/secret_scan.py range "$base_sha..$sha"
  else
    echo "（没有 $base..$sha 的线性范围，只扫 tree）"
  fi
  pyrun scripts/ci/secret_scan.py tree
}
job_selftest() {
  gitleaks_bin
  (cd scripts/ci/tests && GIT_AUTHOR_NAME=ci GIT_AUTHOR_EMAIL=ci@example.invalid GIT_COMMITTER_NAME=ci \
     GIT_COMMITTER_EMAIL=ci@example.invalid uv run --no-project -q --with "pyyaml==${PYYAML_VERSION}" \
     --with "pytest==${PYTEST_VERSION}" python -m pytest -q -p no:cacheprovider .)
}
job_licenses() { (cd src/backend && uv sync -q --frozen) && python3 scripts/ci/check_licenses.py --python src/backend/.venv/bin/python; }
job_pip-audit() {
  uv export --project src/backend --frozen --all-groups --no-emit-project --format requirements.txt -o "$RUNNER_TEMP/req.txt" -q
  uvx -q --from "pip-audit==${PIP_AUDIT_VERSION}" pip-audit --strict --progress-spinner off -r "$RUNNER_TEMP/req.txt" --require-hashes --disable-pip
  if [ -f tests/requirements.txt ]; then uvx -q --from "pip-audit==${PIP_AUDIT_VERSION}" pip-audit --strict --progress-spinner off -r tests/requirements.txt; fi
}
job_backend() {
  (cd src/backend && uv sync -q --frozen && uv run --frozen ruff check . && uv run --frozen mypy)
  local py=src/backend/.venv/bin/python dirs=() ini=()
  if [ -f tests/requirements.txt ]; then uv pip install -q --python "$py" -r tests/requirements.txt "pytest-cov==${PYTEST_COV_VERSION}"
  else uv pip install -q --python "$py" "pytest-cov==${PYTEST_COV_VERSION}"; fi
  for d in src/backend/tests tests/backend tests/replay; do [ -d "$d" ] && dirs+=("$d"); done
  [ ${#dirs[@]} -gt 0 ] || { echo "没有后端测试目录（CI 同样失败）"; return 1; }
  [ -f tests/pytest.ini ] && ini=(-c tests/pytest.ini)
  PYTHONPATH=src/backend "$py" -m pytest "${ini[@]}" "${dirs[@]}" --cov=src/backend/app \
    --cov-report="json:$RUNNER_TEMP/coverage.json" --cov-fail-under=80 -q
  python3 scripts/ci/check_coverage.py "$RUNNER_TEMP/coverage.json"
}
job_frontend() {
  [ -f src/frontend/package.json ] || { echo "没有前端工程，跳过"; return 0; }
  local rc=0
  (cd src/frontend && pnpm install -s --frozen-lockfile) || return 1
  (cd src/frontend && pnpm exec eslint . --max-warnings=0) || rc=1
  (cd src/frontend && if node -e 'process.exit(require("./package.json").scripts?.typecheck ? 0 : 1)'; then pnpm run -s typecheck; else pnpm exec tsc --noEmit; fi) || rc=1
  (cd src/frontend && pnpm exec vitest run) || rc=1
  (cd src/frontend && pnpm audit --audit-level high) || rc=1
  python3 scripts/ci/check_licenses.py --node-modules src/frontend/node_modules || rc=1
  if [ -f tests/package.json ]; then (cd tests && pnpm install -s --frozen-lockfile && pnpm exec vitest run) || rc=1; fi
  return $rc
}
job_migrations() {
  [ -f src/backend/alembic.ini ] || { echo "没有 alembic.ini，跳过"; return 0; }
  start_db
  (cd src/backend && uv sync -q --frozen && .venv/bin/alembic upgrade head && .venv/bin/alembic downgrade base \
     && .venv/bin/alembic upgrade head && .venv/bin/alembic check) || return 1
  # 与 CI 同步（T-O10）：分库角色幂等两次 + 验收（口令目录是临时目录，随 RUNNER_TEMP 删除）
  local hp; hp="$(docker port "$tag-db" 5432/tcp | head -1)"
  PGHOST="${hp%:*}" PGPORT="${hp##*:}" PGUSER=aia PGPASSWORD=ci-only PGDATABASE=aia AIA_DB_ROLE_PASSWORD_DIR="$RUNNER_TEMP/db-roles" \
    bash -c 'bash deploy/scripts/db-role-passwords.sh "$AIA_DB_ROLE_PASSWORD_DIR" && bash deploy/db/roles/apply-roles.sh \
             && bash deploy/db/roles/apply-roles.sh && bash deploy/db/roles/verify-roles.sh'
}
job_contract() {
  local rc=0
  python3 scripts/ci/check_contract.py || rc=1
  python3 scripts/ci/check_code_namespaces.py || rc=1
  start_db redis
  (cd src/backend && uv sync -q --frozen) || return 1
  (cd src/backend && .venv/bin/python ../../scripts/ci/dump_meta_enums.py "$RUNNER_TEMP/meta.json") || return 1
  python3 scripts/ci/check_contract.py --meta-json "$RUNNER_TEMP/meta.json" || rc=1
  python3 scripts/ci/check_code_namespaces.py --meta-json "$RUNNER_TEMP/meta.json" || rc=1
  [ -f src/backend/alembic.ini ] && { (cd src/backend && .venv/bin/alembic upgrade head) || rc=1; }
  local port; port=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
  (cd src/backend && .venv/bin/uvicorn app.main:create_app --factory --host 127.0.0.1 --port "$port" >"$RUNNER_TEMP/api.log" 2>&1 & echo $! >"$RUNNER_TEMP/api.pid")
  for _ in $(seq 1 60); do curl -fsS "http://127.0.0.1:$port/api/v1/health/live" >/dev/null 2>&1 && break; sleep 1; done
  (cd src/backend && uvx -q --from "schemathesis==${SCHEMATHESIS_VERSION}" schemathesis run \
     "http://127.0.0.1:$port/api/v1/openapi.json" --checks all --max-examples 50 --seed 20261101 --no-color) \
     || { tail -n 50 "$RUNNER_TEMP/api.log"; rc=1; }
  kill "$(cat "$RUNNER_TEMP/api.pid")" 2>/dev/null || true
  return $rc
}
job_image() {
  docker build -q -f deploy/docker/backend.Dockerfile -t "aia-backend:$tag" src/backend >/dev/null
  docker run -d --name "$tag-api" -e APP_ENV=test -v "$PWD/config:/app/config:ro" -p 127.0.0.1::8000 "aia-backend:$tag" >/dev/null
  local addr; addr=$(docker port "$tag-api" 8000/tcp | head -1)
  for _ in $(seq 1 30); do curl -fsS "http://$addr/api/v1/health/live" >/dev/null 2>&1 && return 0; sleep 1; done
  docker logs "$tag-api" 2>&1 | tail -n 50; return 1
}

declare -A seen=(); results=(); fail=0
for j in "${jobs[@]}"; do
  [ -n "${seen[$j]:-}" ] && continue; seen[$j]=1
  echo "=== $j"
  start=$(date +%s)
  if ( set -euo pipefail; "job_$j" ); then results+=("ok    $j ($(( $(date +%s) - start ))s)")
  else results+=("FAIL  $j ($(( $(date +%s) - start ))s)"); fail=1; fi
  docker rm -f "$tag-db" "$tag-redis" "$tag-api" >/dev/null 2>&1 || true
done
echo "=== clean_check $sha"
printf '%s\n' "${results[@]}"
exit $fail
