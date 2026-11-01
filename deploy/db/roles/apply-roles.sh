#!/usr/bin/env bash
# 应用分库角色与列级授权（T-O10）：psql 执行 grants.sql（幂等）。compose 的 db-roles 服务用它；也可手工执行。
# 连接：标准 PG* 环境变量（PGHOST/PGPORT/PGUSER=库属主/PGPASSWORD/PGDATABASE）。
# 口令：$AIA_DB_ROLE_PASSWORD_DIR/db_password_aia_api、db_password_aia_ingest（compose secret 挂在 /run/secrets）。
# 不打印口令；口令以 psql 变量传入（不在命令行上：用 \set 从文件读入的临时脚本，权限 600，结束即删）。
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pwdir="${AIA_DB_ROLE_PASSWORD_DIR:-/run/secrets}"
read_pw() {
  local f="$pwdir/db_password_$1" v
  [ -s "$f" ] || { echo "db-roles: 缺少口令文件 $f（deploy/scripts/db-role-passwords.sh 生成）" >&2; exit 2; }
  v="$(tr -d '\n' < "$f")"
  [[ "$v" =~ ^[0-9a-f]{16,}$ ]] || { echo "db-roles: $f 格式不对（应为十六进制）" >&2; exit 2; }
  printf '%s' "$v"
}
api_pw="$(read_pw aia_api)"; ingest_pw="$(read_pw aia_ingest)"
umask 077
tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT
{ printf '\\set api_pw %s\n\\set ingest_pw %s\n' "$api_pw" "$ingest_pw"; cat "$here/grants.sql"; } > "$tmp"
for i in $(seq 1 30); do pg_isready -q && break; sleep 1; done
psql -X -q -v ON_ERROR_STOP=1 -f "$tmp"
echo "db-roles: OK（aia_api、aia_ingest 已授权；库 ${PGDATABASE:-?}）"
