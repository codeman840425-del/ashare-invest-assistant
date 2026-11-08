#!/bin/sh
# T-T20 只读 runner 入口（T-O23）。不启动生产栈，不写共享 .git，不写 /cache 或 /code。
# 挂载：/code:ro  /cache:ro  /git-ro:ro（仓库 .git）  /hostpy:ro
#   deploy/testkit/tt20/run.sh --check
# 显式 TT20_RUN_PYTEST=1 才执行与 logs/backend.sh 相同的 pytest（测试角色复验用）。
set -eu
HERE=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
. "$HERE/export-pythonpath.sh"
if [ ! -d "${TT20_GIT_RO:-/git-ro}/objects" ]; then
  echo "tt20: 未挂只读 Git 对象库（TT20_GIT_RO 或 /git-ro）" >&2
  exit 2
fi
if [ -w "${TT20_GIT_RO:-/git-ro}/objects" ]; then
  echo "tt20: Git 对象库可写，拒绝启动" >&2
  exit 2
fi
if [ "${1:-}" = "--check" ]; then
  sample=$("$HERE/git-ro.sh" rev-parse --is-bare-repository >/dev/null 2>&1 || true)
  "$HERE/git-ro.sh" cat-file -t "${TT20_GIT_PROBE_REV:-3895963f5366d734e5229b210b92d6811851fc62}" >/dev/null
  "$HERE/git-ro.sh" show "${TT20_GIT_PROBE_REV:-3895963f5366d734e5229b210b92d6811851fc62}:docs/strategies/feature_spec.md" >/dev/null
  py=${TT20_PYTHON:-/hostpy/bin/python3.12}
  "$py" -c 'import subprocess,sys; subprocess.check_call([sys.executable,"-m","alembic","--help"],stdout=subprocess.DEVNULL)'
  echo "tt20: git 对象只读可读，alembic 可被子进程继承"
  exit 0
fi
if [ "${TT20_RUN_PYTEST:-}" != 1 ]; then
  echo "tt20: 默认不跑测试。--check 只做探针；全量复验需测试角色设置 TT20_RUN_PYTEST=1。" >&2
  exit 2
fi
export COVERAGE_FILE="${COVERAGE_FILE:-/logs/.coverage}"
export PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 APP_ENV=test
export CONFIG_DIR="${CONFIG_DIR:-/code/config}"
py=${TT20_PYTHON:-/hostpy/bin/python3.12}
cd /code
exec "$py" ${TT20_RUN_CACHED:-/run/tt20/run_cached.py} pytest --continue-on-collection-errors -p no:cacheprovider -p pytest_cov.plugin -c tests/pytest.ini tests/backend src/backend/selfchecks --cov=src/backend/app --cov-branch --cov-report=term --tb=short -q
