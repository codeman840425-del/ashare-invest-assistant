#!/usr/bin/env bash
# 验收分库角色（T-O10）：aia_api 读密文列必须 permission denied，读其余列/状态视图正常；aia_ingest 可读密文列。
# 只读（SELECT … LIMIT 0），不改数据。连接参数同 apply-roles.sh（PGHOST/PGPORT/PGDATABASE；口令目录 AIA_DB_ROLE_PASSWORD_DIR）。
# 用法：deploy/db/roles/verify-roles.sh            退出码 0 = 全部符合
set -euo pipefail
pwdir="${AIA_DB_ROLE_PASSWORD_DIR:-/run/secrets}"
fail=0
as() { local role="$1"; shift; PGUSER="$role" PGPASSWORD="$(tr -d '\n' < "$pwdir/db_password_$role")" psql -X -q -tA -v ON_ERROR_STOP=1 "$@" 2>&1; }
expect_ok()     { if out="$(as "$1" -c "$2")"; then echo "OK   $1: $2"; else echo "FAIL $1 应可执行: $2 → $out"; fail=1; fi; }
expect_denied() {
  if out="$(as "$1" -c "$2")"; then echo "FAIL $1 不应可执行: $2"; fail=1
  elif grep -q 'permission denied' <<<"$out"; then echo "OK   $1 permission denied: $2"
  else echo "FAIL $1 预期 permission denied，实际: $out"; fail=1; fi
}
expect_denied aia_api    "SELECT ciphertext FROM app.user_data_licences LIMIT 0"
expect_denied aia_api    "SELECT * FROM app.user_data_licences LIMIT 0"
expect_ok     aia_api    "SELECT id, user_id, licence_hmac, deleted_at FROM app.user_data_licences LIMIT 0"
expect_ok     aia_api    "SELECT * FROM app.user_data_licence_status LIMIT 0"
expect_ok     aia_api    "SELECT id FROM app.user_data_licences WHERE false FOR UPDATE"
expect_ok     aia_ingest "SELECT ciphertext FROM app.user_data_licences LIMIT 0"
expect_denied aia_api    "CREATE TABLE app.t_o10_probe (x int)"
exit "$fail"
