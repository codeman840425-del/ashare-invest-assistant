#!/bin/sh
# 容器入口包装（T-O11）：把 docker secret 文件转成进程内环境变量后 exec 原命令。
# compose 以只读方式挂到 /aia/secret-env.sh，作为 api / worker / ingest / maint-cli 的 entrypoint（原 command 不变）。
#   /run/secrets/app_master_key        → APP_MASTER_KEY（后端 Settings.app_master_key 只认环境变量，
#                                         这里在进程内注入，compose 的 environment / docker inspect 里都没有它）
#   /run/secrets/db_password_aia_maint → 在容器内 600 临时文件里拼出 aia_maint 的 DSN，
#                                         导出 AIA_MAINT_DATABASE_URL_FILE（删除用户数据 CLI 读它，只有 maint-cli 挂这份 secret）
# 不打印任何值；secret 存在但为空 / 读不到时直接失败（不回落到无密钥运行）。
# 评审 8cf9771 m3：先关掉继承来的 xtrace（bash -x / SHELLOPTS=xtrace），免得密钥或口令值被打到 stderr。
{ set +x; } 2>/dev/null
set -eu
sd="${AIA_SECRET_ENV_DIR:-/run/secrets}"

# AIA_FORBID_APP_MASTER_KEY=1（compose 给 ingest 设；plan e56462c“按服务分配”）：ingest 持有证书私钥，
# 同一容器不得同时持有主密钥——环境变量里有 APP_MASTER_KEY、或挂了 app_master_key secret，都拒绝启动。
# （后端启动检查同样要做，见 plan；这里是部署侧兜底。）
if [ "${AIA_FORBID_APP_MASTER_KEY:-0}" = 1 ]; then
  if [ -n "${APP_MASTER_KEY+x}" ] || [ -e "$sd/app_master_key" ]; then
    echo "secret-env: 本服务不得持有 APP_MASTER_KEY（环境变量或 $sd/app_master_key），拒绝启动（plan：ingest 不与证书私钥同处一个容器）" >&2; exit 2
  fi
  exec "$@"
fi

# AIA_REQUIRE_APP_MASTER_KEY=1（compose 给 api / worker 设）：没挂 secret 就拒绝启动，
# 不让后端在 local/test 下回落到临时随机主密钥（等于悄悄换了主密钥，T-O11 评审 M1）。
if [ "${AIA_REQUIRE_APP_MASTER_KEY:-0}" = 1 ] && [ ! -e "$sd/app_master_key" ]; then
  echo "secret-env: 缺少 $sd/app_master_key（compose secret app_master_key 没挂上），拒绝启动；不会生成或回落到临时主密钥" >&2; exit 2
fi
if [ -e "$sd/app_master_key" ]; then
  if [ -n "${APP_MASTER_KEY:-}" ]; then
    echo "secret-env: APP_MASTER_KEY 只能来自 secret 文件，环境里不应再设置" >&2; exit 2
  fi
  [ -r "$sd/app_master_key" ] || { echo "secret-env: 读不到 $sd/app_master_key（属主应为容器用户 $(id -u)，权限 600）" >&2; exit 2; }
  APP_MASTER_KEY="$(tr -d '\r\n' < "$sd/app_master_key")"
  [ -n "$APP_MASTER_KEY" ] || { echo "secret-env: $sd/app_master_key 为空" >&2; exit 2; }
  export APP_MASTER_KEY
fi

if [ -e "$sd/db_password_aia_maint" ]; then
  [ -r "$sd/db_password_aia_maint" ] || { echo "secret-env: 读不到 $sd/db_password_aia_maint（属主应为容器用户 $(id -u)，权限 600）" >&2; exit 2; }
  pw="$(tr -d '\r\n' < "$sd/db_password_aia_maint")"
  case "$pw" in ''|*[!0-9a-f]*) echo "secret-env: db_password_aia_maint 格式不对（应为十六进制）" >&2; exit 2 ;; esac
  umask 077
  dsn_file="$(mktemp "${TMPDIR:-/tmp}/aia-maint-dsn.XXXXXX")"
  printf 'postgresql+psycopg://aia_maint:%s@%s:%s/%s\n' "$pw" "${AIA_MAINT_DB_HOST:-postgres}" \
    "${AIA_MAINT_DB_PORT:-5432}" "${AIA_MAINT_DB_NAME:-aia}" > "$dsn_file"
  unset pw
  export AIA_MAINT_DATABASE_URL_FILE="$dsn_file"
fi

exec "$@"
