#!/usr/bin/env bash
# 验收分库角色（T-O10）：aia_api 读密文列必须 permission denied，读其余列/状态视图正常；aia_ingest 可读密文列。
# T-O11（评审 45589c2 m3、plan §7.3）：aia_api / aia_ingest 对 ops.pending_file_purges 无任何权限；
#   “置 purging → 删不可变行 → 改回 → 提交”的攻击序列必须失败（只有失败才算通过）；aia_maint 只有 CLI 所需权限，
#   且它自己也不能把 purging 改回、不能不删行就提交；aia_maint 必须 LOGIN，aia_api/aia_ingest 不得是其成员。
#   aia_maint 是列级授权：清单外的列读不到、写不了，DELETE 只在清单里的表上（第 4 节）。
# T-A04 ④：worker 用 aia_api，其任务所需 DML 可用；aia_api 无 DDL、读不到证书密文列（第 6 节）。
# plan 4.6.5A 第 9 条：aia_ingest 对 master_vendor_batches 只有 SELECT 与 status、fetched_at、datasets、error_code
#   的 UPDATE，对 master_vendor_list_rows 只有 INSERT；其余读写在 aia_api。两表都未落地则跳过；只落地一张或点名列缺失则失败。
# T-O10 部分只读（SELECT … LIMIT 0）。T-O11 的事务用例会插入名为 t_o11_<随机> 的探针用户：失败的序列整体回滚；
#   需要落库的探针最后用正规删除路径（aia_maint：purging → 删 → 提交）清掉，并用属主连接确认无残留。
#   属主连接 = 调用方的 PGUSER/PGPASSWORD（compose db-roles / CI 都是库属主）。连接参数同 apply-roles.sh（PGHOST/PGPORT/PGDATABASE；口令目录 AIA_DB_ROLE_PASSWORD_DIR）。
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

# ---------- T-O11 ----------
own() { psql -X -q -tA -v ON_ERROR_STOP=1 "$@" 2>&1; }   # 属主连接（继承调用方 PG*）
# 运行一段多语句事务；返回 psql 退出码，输出放在 $out。VERBOSITY verbose 让错误带 SQLSTATE。
tx() { local role="$1" sql="$2"; out="$(printf '\\set VERBOSITY verbose\n%s\n' "$sql" | as "$role" -f -)"; }
# 期望事务失败，且 SQLSTATE 是给定之一，且已经走到标记 $3（证明前面的步骤确实执行过，不是在更早处被挡）
expect_tx_fail() {
  local role="$1" name="$2" reached="$3" codes="$4" sql="$5" code
  if tx "$role" "$sql"; then echo "FAIL $role 序列应失败却提交成功：$name"; fail=1; return; fi
  code="$(grep -oE 'ERROR: +[0-9A-Z]{5}' <<<"$out" | head -1 | grep -oE '[0-9A-Z]{5}$' || true)"
  if ! grep -q "^step:$reached\$" <<<"$out"; then
    echo "FAIL $role 序列在到达 $reached 之前就失败了（用例无效）：$name → $(grep -m1 ERROR <<<"$out")"; fail=1
  elif [[ " $codes " == *" $code "* ]]; then
    echo "OK   $role 序列被拒（SQLSTATE $code）：$name"
  else
    echo "FAIL $role 序列失败但 SQLSTATE=$code 不在预期 [$codes]：$name → $(grep -m1 ERROR <<<"$out")"; fail=1
  fi
}
expect_tx_ok() {
  local role="$1" name="$2" sql="$3"
  if tx "$role" "$sql"; then echo "OK   $role 序列成功：$name"; else echo "FAIL $role 序列应成功：$name → $(grep -m1 ERROR <<<"$out")"; fail=1; fi
}
probe_left() { own -c "SELECT count(*) FROM app.users WHERE username = '$1'"; }
# 正规删除路径（与 CLI 相同的数据库约束）：aia_maint 置 purging → 删画像 → 删用户 → 提交
purge_sql() {
  cat <<SQL
BEGIN;
UPDATE app.users SET status = 'purging' WHERE username = '$1';
DELETE FROM app.user_profiles WHERE user_id IN (SELECT id FROM app.users WHERE username = '$1');
DELETE FROM app.users WHERE username = '$1';
COMMIT;
SQL
}
rnd() { printf 't_o11_%s' "$(od -An -tx1 -N5 /dev/urandom | tr -d ' \n')"; }

if [ "$(own -c "SELECT to_regclass('ops.pending_file_purges') IS NOT NULL AND EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_users_purging_guard')")" != t ]; then
  echo "FAIL 库里没有 ops.pending_file_purges / trg_users_purging_guard（迁移未到 0013？），T-O11 用例无法执行"; exit 1
fi

# 1) api / ingest 对待清文件队列无任何权限
for r in aia_api aia_ingest; do
  expect_denied "$r" "SELECT * FROM ops.pending_file_purges LIMIT 0"
  expect_denied "$r" "BEGIN; INSERT INTO ops.pending_file_purges (path) VALUES ('/t_o11_probe'); ROLLBACK;"   # 万一有权也不落库
  expect_denied "$r" "UPDATE ops.pending_file_purges SET attempts = attempts WHERE false"
  expect_denied "$r" "DELETE FROM ops.pending_file_purges WHERE false"
done

# 2) 攻击序列：api / ingest 置 purging → 删不可变行（user_profiles）→ 改回 → 提交，必须失败
for r in aia_api aia_ingest; do
  u="$(rnd)"
  expect_tx_fail "$r" "置 purging→删画像→改回→提交" purging "42501 23001" "$(cat <<SQL
BEGIN;
INSERT INTO app.users (username, password_hash, role, status) VALUES ('$u', 'x', 'user', 'approved');
INSERT INTO app.user_profiles (user_id, version_no) SELECT id, 1 FROM app.users WHERE username = '$u';
\echo step:purging
UPDATE app.users SET status = 'purging' WHERE username = '$u';
\echo step:delete
DELETE FROM app.user_profiles WHERE user_id IN (SELECT id FROM app.users WHERE username = '$u');
\echo step:revert
UPDATE app.users SET status = 'approved' WHERE username = '$u';
COMMIT;
SQL
)"
  [ "$(probe_left "$u")" = 0 ] || { echo "FAIL $r 攻击序列留下了探针用户 $u（已用属主连接清理）"; fail=1
    own -c "BEGIN; SET LOCAL ROLE aia_maint; $(purge_sql "$u" | sed '1d;$d') COMMIT;" >/dev/null || true; }
done

# 3) aia_maint 自身：同样的“改回”也被拒；不删行就提交被拒（按行延迟检查）；正规删除路径可提交
u="$(rnd)"
own -c "BEGIN; INSERT INTO app.users (username, password_hash, role, status) VALUES ('$u', 'x', 'user', 'approved');
        INSERT INTO app.user_profiles (user_id, version_no) SELECT id, 1 FROM app.users WHERE username = '$u'; COMMIT;" >/dev/null
expect_tx_fail aia_maint "置 purging→删画像→改回→提交" revert "23001" "$(cat <<SQL
BEGIN;
\echo step:purging
UPDATE app.users SET status = 'purging' WHERE username = '$u';
\echo step:delete
DELETE FROM app.user_profiles WHERE user_id IN (SELECT id FROM app.users WHERE username = '$u');
\echo step:revert
UPDATE app.users SET status = 'approved' WHERE username = '$u';
COMMIT;
SQL
)"
expect_tx_fail aia_maint "置 purging 后不删用户直接提交（延迟检查）" commit "23001" "$(cat <<SQL
BEGIN;
UPDATE app.users SET status = 'purging' WHERE username = '$u';
\echo step:commit
COMMIT;
SQL
)"
expect_tx_ok aia_maint "正规删除：purging→删画像→删用户→提交" "$(purge_sql "$u")"
[ "$(probe_left "$u")" = 0 ] || { echo "FAIL 探针用户 $u 未被正规删除路径清掉（已用属主连接清理）"; fail=1
  own -c "BEGIN; SET LOCAL ROLE aia_maint; $(purge_sql "$u" | sed '1d;$d') COMMIT;" >/dev/null || true; }

# 4) aia_maint 最小权限（列级，清单见 reports/aia_maint-grants.md §3）：清单内的列可读写，清单外的列读不到、写不了
expect_ok     aia_maint "SELECT id, path, attempts, last_error, created_at FROM ops.pending_file_purges LIMIT 0"
expect_ok     aia_maint "SELECT id, username, role, status, reviewed_by FROM app.users LIMIT 0"
expect_ok     aia_maint "UPDATE app.users SET status = status WHERE false"
expect_ok     aia_maint "DELETE FROM app.trades WHERE user_id IS NULL AND false"
# 清单外的列：读
expect_denied aia_maint "SELECT * FROM app.users LIMIT 0"
expect_denied aia_maint "SELECT password_hash FROM app.users LIMIT 0"
expect_denied aia_maint "SELECT email FROM app.users LIMIT 0"
expect_denied aia_maint "SELECT ciphertext FROM app.user_data_licences LIMIT 0"
expect_denied aia_maint "SELECT licence_hmac FROM app.user_data_licences LIMIT 0"
expect_denied aia_maint "SELECT api_key_ciphertext FROM app.llm_providers LIMIT 0"
expect_denied aia_maint "SELECT raw_line FROM app.import_rows LIMIT 0"
expect_denied aia_maint "SELECT request_body FROM app.llm_calls LIMIT 0"
expect_denied aia_maint "SELECT security_code FROM app.trades LIMIT 0"
expect_denied aia_maint "SELECT last_attempt_at FROM ops.pending_file_purges LIMIT 0"
# maint_deny 其余三列（T-O11 aia_deny 裁定 ⑴）
expect_denied aia_maint "SELECT target_ciphertext FROM app.notification_channel_bindings LIMIT 0"
expect_denied aia_maint "SELECT response_body FROM app.llm_calls LIMIT 0"
expect_denied aia_maint "SELECT fingerprint FROM app.user_data_licence_cooldowns LIMIT 0"
# 清单外的列：写（WHERE false 不改数据；列权限在规划时检查）
expect_denied aia_maint "UPDATE app.users SET role = role WHERE false"
expect_denied aia_maint "UPDATE app.users SET password_hash = password_hash WHERE false"
expect_denied aia_maint "UPDATE app.trades SET quantity = quantity WHERE false"
expect_denied aia_maint "UPDATE ops.pending_file_purges SET path = path WHERE false"
# DELETE 只在清单里的表上
expect_denied aia_maint "DELETE FROM app.invite_codes WHERE false"
expect_denied aia_maint "DELETE FROM app.prompt_templates WHERE false"
# 汇总断言（属主连接）：任何表都没有表级 SELECT/INSERT/UPDATE；没有序列权限、没有默认权限
expect_attr_early() { local v; v="$(own -c "$2" || true)"; if [ "$v" = t ]; then echo "OK   $1"; else echo "FAIL $1（SQL 结果 $v，应为 t）"; fail=1; fi; }
expect_attr_early "aia_maint 在 app/ops/market 无任何表级 SELECT/INSERT/UPDATE/TRUNCATE/REFERENCES/TRIGGER" \
  "SELECT NOT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace CROSS JOIN unnest(ARRAY['SELECT','INSERT','UPDATE','TRUNCATE','REFERENCES','TRIGGER']) p WHERE n.nspname IN ('app','ops','market') AND c.relkind IN ('r','p','v','m','f') AND has_table_privilege('aia_maint', c.oid, p))"
expect_attr_early "aia_maint 无序列权限、无默认权限" \
  "SELECT NOT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname IN ('app','ops','market') AND CASE WHEN c.relkind = 'S' THEN has_sequence_privilege('aia_maint', c.oid, 'USAGE,SELECT,UPDATE') ELSE false END) AND NOT EXISTS (SELECT 1 FROM pg_default_acl d, aclexplode(d.defaclacl) a WHERE a.grantee = 'aia_maint'::regrole)"
expect_attr_early "aia_maint 在 market 只可读 source_licence_id" \
  "SELECT NOT EXISTS (SELECT 1 FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'market' AND c.relkind IN ('r','p') AND a.attnum > 0 AND NOT a.attisdropped AND a.attname <> 'source_licence_id' AND has_column_privilege('aia_maint', c.oid, a.attnum, 'SELECT'))"
expect_denied aia_maint "INSERT INTO app.users (username, password_hash, role, status) VALUES ('t_o11_denied', 'x', 'user', 'purging')"
expect_denied aia_maint "INSERT INTO app.trades DEFAULT VALUES"
expect_denied aia_maint "TRUNCATE ops.pending_file_purges"
expect_denied aia_maint "SELECT * FROM ops.ingest_leases LIMIT 0"
expect_denied aia_maint "CREATE TABLE app.t_o11_probe (x int)"
# 5) 角色关系（架构师 T-O11 细化裁定）：aia_maint 有 LOGIN；aia_api / aia_ingest 不是它的成员（含间接），
#    也不能 SET ROLE 过去；aia_maint 自己不属于任何角色、也没有任何成员
expect_attr() {   # $1 说明  $2 属主连接执行的布尔 SQL，必须为 t
  local v; v="$(own -c "$2")"
  if [ "$v" = t ]; then echo "OK   $1"; else echo "FAIL $1（断言不成立：SQL 结果 $v，应为 t）"; fail=1; fi
}
expect_attr "aia_maint rolcanlogin = true" \
  "SELECT coalesce((SELECT rolcanlogin FROM pg_roles WHERE rolname = 'aia_maint'), false)"
for r in aia_api aia_ingest; do
  expect_attr "pg_has_role('$r','aia_maint','MEMBER') = false" \
    "SELECT NOT pg_has_role('$r', 'aia_maint', 'MEMBER')"
  if out="$(as "$r" -c "SET ROLE aia_maint")"; then echo "FAIL $r 不应能 SET ROLE aia_maint"; fail=1
  elif grep -q 'permission denied' <<<"$out"; then echo "OK   $r permission denied: SET ROLE aia_maint"
  else echo "FAIL $r SET ROLE aia_maint 预期 permission denied，实际: $out"; fail=1; fi
done
expect_attr "aia_maint 没有成员、也不属于任何角色（pg_auth_members）" \
  "SELECT NOT EXISTS (SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.rolname = 'aia_maint' WHERE m.roleid = r.oid OR m.member = r.oid)"


# DDL 被拒：非属主 ALTER/DROP/CREATE INDEX 报 must be owner，CREATE 报 permission denied，两者都算通过
expect_ddl_denied() {
  if out="$(as "$1" -c "$2")"; then echo "FAIL $1 不应可执行: $2"; fail=1
  elif grep -Eq 'must be owner|permission denied' <<<"$out"; then echo "OK   $1 DDL 被拒: $2"
  else echo "FAIL $1 预期 DDL 被拒，实际: $out"; fail=1; fi
}
# 6) T-A04 ④：worker 以 aia_api 连接，只需这些 DML（app/workers/jobs.py）；aia_api 无 DDL、读不到证书密文列
expect_ok     aia_api "SELECT user_id FROM app.user_data_licence_cooldowns WHERE false"
expect_ok     aia_api "DELETE FROM app.user_data_licence_cooldowns WHERE false"
expect_ok     aia_api "SELECT id, batch_id FROM app.import_rows WHERE false"
expect_ok     aia_api "DELETE FROM app.import_rows WHERE false"
expect_ok     aia_api "SELECT id, status FROM app.import_batches WHERE false"
expect_ok     aia_api "SELECT id, batch_id, storage_path FROM app.import_files WHERE false FOR UPDATE SKIP LOCKED"
expect_ok     aia_api "UPDATE app.import_files SET deleted_at = deleted_at, storage_path = storage_path WHERE false"
expect_denied aia_api "SELECT ciphertext FROM app.user_data_licences WHERE false"
expect_denied aia_api "TRUNCATE app.import_rows"
expect_ddl_denied aia_api "ALTER TABLE app.import_files ADD COLUMN t_a04_probe int"
expect_ddl_denied aia_api "DROP TABLE app.user_data_licence_cooldowns"
expect_ddl_denied aia_api "CREATE INDEX t_a04_probe ON app.import_rows (batch_id)"
expect_attr "aia_api 不拥有任何表或 schema；库与业务 schema 上无 CREATE" \
  "SELECT NOT EXISTS (SELECT 1 FROM pg_class WHERE relowner = 'aia_api'::regrole) AND NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspowner = 'aia_api'::regrole) AND NOT has_database_privilege('aia_api', current_database(), 'CREATE') AND NOT EXISTS (SELECT 1 FROM pg_namespace n WHERE n.nspname NOT LIKE 'pg\\_%' AND n.nspname <> 'information_schema' AND has_schema_privilege('aia_api', n.oid, 'CREATE'))"
expect_attr "aia_api 在 app/ops/market 无表级 TRUNCATE/REFERENCES/TRIGGER" \
  "SELECT NOT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace CROSS JOIN unnest(ARRAY['TRUNCATE','REFERENCES','TRIGGER']) p WHERE n.nspname IN ('app','ops','market') AND c.relkind IN ('r','p') AND has_table_privilege('aia_api', c.oid, p))"
# 7) plan 4.6.5A 第 9 条（T-B61）。列名只使用裁定点名的四列；其余列从库里现查，不写死未落地的字段。
vendor_count() {
  own -c "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE c.relname = '$1' AND c.relkind IN ('r','p') AND NOT c.relispartition AND n.nspname NOT LIKE 'pg\\_%' AND n.nspname <> 'information_schema'"
}
vendor_rel() {
  own -c "SELECT format('%I.%I', n.nspname, c.relname) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE c.relname = '$1' AND c.relkind IN ('r','p') AND NOT c.relispartition AND n.nspname NOT LIKE 'pg\\_%' AND n.nspname <> 'information_schema'"
}
nb="$(vendor_count master_vendor_batches)"
nr="$(vendor_count master_vendor_list_rows)"
if [ "$nb" = 0 ] && [ "$nr" = 0 ]; then
  echo "SKIP 4.6.5A 第 9 条：master_vendor_batches / master_vendor_list_rows 未落地（T-B61 迁移前）"
elif [ "$nb" != 1 ] || [ "$nr" != 1 ]; then
  echo "FAIL 4.6.5A 第 9 条需要后端确认表的位置（master_vendor_batches=$nb 张, master_vendor_list_rows=$nr 张）"
  fail=1
else
  batches="$(vendor_rel master_vendor_batches)"
  rows="$(vendor_rel master_vendor_list_rows)"
  missing="$(own -c "SELECT coalesce(string_agg(x, ',' ORDER BY x), '') FROM unnest(ARRAY['status','fetched_at','datasets','error_code']) x WHERE NOT EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = '$batches'::regclass AND a.attname = x AND a.attnum > 0 AND NOT a.attisdropped)")"
  if [ -n "$missing" ]; then
    echo "FAIL $batches 缺少 4.6.5A 第 9 条点名的列：$missing"
    fail=1
  else
    expect_ok     aia_ingest "SELECT * FROM $batches LIMIT 0"
    expect_ok     aia_ingest "UPDATE $batches SET status = status, fetched_at = fetched_at, datasets = datasets, error_code = error_code WHERE false"
    expect_denied aia_ingest "INSERT INTO $batches (status) SELECT NULL WHERE false"
    expect_denied aia_ingest "DELETE FROM $batches WHERE false"
    expect_denied aia_ingest "TRUNCATE $batches"
    while IFS= read -r stmt; do
      [ -n "$stmt" ] || continue
      expect_denied aia_ingest "$stmt"
    done < <(own -c "SELECT format('UPDATE %s SET %I = %I WHERE false', '$batches'::regclass, a.attname, a.attname) FROM pg_attribute a WHERE a.attrelid = '$batches'::regclass AND a.attnum > 0 AND NOT a.attisdropped AND a.attname NOT IN ('status','fetched_at','datasets','error_code') ORDER BY a.attnum")
    expect_denied aia_ingest "SELECT * FROM $rows LIMIT 0"
    expect_denied aia_ingest "DELETE FROM $rows WHERE false"
    expect_denied aia_ingest "TRUNCATE $rows"
    while IFS= read -r stmt; do
      [ -n "$stmt" ] || continue
      expect_denied aia_ingest "$stmt"
    done < <(own -c "SELECT format('UPDATE %s SET %I = %I WHERE false', '$rows'::regclass, a.attname, a.attname) FROM pg_attribute a WHERE a.attrelid = '$rows'::regclass AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum")
    ins="$(own -c "SELECT format('INSERT INTO %s (%I) SELECT NULL WHERE false', '$rows'::regclass, a.attname) FROM pg_attribute a WHERE a.attrelid = '$rows'::regclass AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum LIMIT 1")"
    expect_ok aia_ingest "$ins"
    expect_ok aia_api "SELECT * FROM $batches LIMIT 0"
    expect_ok aia_api "UPDATE $batches SET status = status WHERE false"
    expect_ok aia_api "DELETE FROM $batches WHERE false"
    expect_ok aia_api "SELECT * FROM $rows LIMIT 0"
    expect_ok aia_api "DELETE FROM $rows WHERE false"
    expect_ok aia_api "$ins"
    api_upd="$(own -c "SELECT format('UPDATE %s SET %I = %I WHERE false', '$batches'::regclass, a.attname, a.attname) FROM pg_attribute a WHERE a.attrelid = '$batches'::regclass AND a.attnum > 0 AND NOT a.attisdropped AND a.attname NOT IN ('status','fetched_at','datasets','error_code') ORDER BY a.attnum LIMIT 1")"
    [ -z "$api_upd" ] || expect_ok aia_api "$api_upd"
    expect_attr "aia_ingest 对批次表无表级 INSERT/UPDATE/DELETE，对行表无 SELECT/UPDATE/DELETE" \
      "SELECT NOT has_table_privilege('aia_ingest', '$batches'::regclass, 'INSERT') AND NOT has_table_privilege('aia_ingest', '$batches'::regclass, 'UPDATE') AND NOT has_table_privilege('aia_ingest', '$batches'::regclass, 'DELETE') AND NOT has_table_privilege('aia_ingest', '$rows'::regclass, 'SELECT') AND NOT has_table_privilege('aia_ingest', '$rows'::regclass, 'UPDATE') AND NOT has_table_privilege('aia_ingest', '$rows'::regclass, 'DELETE') AND NOT has_any_column_privilege('aia_ingest', '$rows'::regclass, 'SELECT')"
    expect_attr "aia_api 对两张对账表有 SELECT/INSERT/UPDATE/DELETE" \
      "SELECT has_table_privilege('aia_api', '$batches'::regclass, 'SELECT') AND has_table_privilege('aia_api', '$batches'::regclass, 'INSERT') AND has_table_privilege('aia_api', '$batches'::regclass, 'UPDATE') AND has_table_privilege('aia_api', '$batches'::regclass, 'DELETE') AND has_table_privilege('aia_api', '$rows'::regclass, 'SELECT') AND has_table_privilege('aia_api', '$rows'::regclass, 'INSERT') AND has_table_privilege('aia_api', '$rows'::regclass, 'UPDATE') AND has_table_privilege('aia_api', '$rows'::regclass, 'DELETE')"
    expect_attr "aia_maint 对两张对账表无表级 DML、也无列级 SELECT" \
      "SELECT NOT has_table_privilege('aia_maint', '$batches'::regclass, 'DELETE') AND NOT has_table_privilege('aia_maint', '$rows'::regclass, 'DELETE') AND NOT has_any_column_privilege('aia_maint', '$batches'::regclass, 'SELECT') AND NOT has_any_column_privilege('aia_maint', '$rows'::regclass, 'SELECT') AND NOT has_table_privilege('aia_maint', '$batches'::regclass, 'INSERT') AND NOT has_table_privilege('aia_maint', '$rows'::regclass, 'INSERT')"
    expect_denied aia_api "SELECT ciphertext FROM app.user_data_licences WHERE false"
  fi
fi


# T-O27：启动版本检查。api/worker 用 aia_api，ingest 用 aia_ingest。只读；写和 DDL 必须拒绝。
# 破坏性语句放在事务里，即使授权错误也会 ROLLBACK，不改版本行。
if [ "$(own -c "SELECT to_regclass('public.alembic_version') IS NOT NULL")" != t ]; then
  echo "FAIL 库里没有 public.alembic_version，T-O27 无法验收"; fail=1
else
  for r in aia_api aia_ingest; do
    expect_ok "$r" "SELECT to_regclass('public.alembic_version')"
    expect_ok "$r" "SELECT version_num FROM public.alembic_version"
    expect_denied "$r" "BEGIN; INSERT INTO public.alembic_version (version_num) VALUES ('t_o27'); ROLLBACK"
    expect_denied "$r" "UPDATE public.alembic_version SET version_num = version_num WHERE false"
    expect_denied "$r" "DELETE FROM public.alembic_version WHERE false"
    expect_denied "$r" "BEGIN; TRUNCATE public.alembic_version; ROLLBACK"
    expect_ddl_denied "$r" "BEGIN; ALTER TABLE public.alembic_version ADD COLUMN t_o27_probe int; ROLLBACK"
    expect_ddl_denied "$r" "BEGIN; DROP TABLE public.alembic_version; ROLLBACK"
    expect_ddl_denied "$r" "BEGIN; CREATE INDEX t_o27_probe ON public.alembic_version (version_num); ROLLBACK"
  done
  expect_denied aia_api "SELECT ciphertext FROM app.user_data_licences WHERE false"
fi


# T-O29：P2N-07 / T-B90 最小依赖。表未落地则跳过；点名列缺失则失败，不把缺列当成表级 UPDATE 通过。
if [ "$(own -c "SELECT to_regclass('app.action_plans') IS NOT NULL")" != t ]; then
  echo "SKIP T-O29：app.action_plans 未落地"
else
  miss="$(own -c "SELECT string_agg(c, ',' ORDER BY c) FROM unnest(ARRAY['status','triggered_at','updated_at']) c WHERE NOT EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = 'app.action_plans'::regclass AND a.attname = c AND a.attnum > 0 AND NOT a.attisdropped)")"
  if [ -n "$miss" ]; then
    echo "FAIL T-O29：app.action_plans 缺少点名列（$miss），不得退成表级 UPDATE"; fail=1
  else
    expect_ok aia_api "SELECT status, triggered_at, updated_at FROM app.action_plans WHERE false"
    expect_ok aia_api "UPDATE app.action_plans SET status = status, triggered_at = triggered_at, updated_at = updated_at WHERE false"
    expect_ok aia_api "SELECT id, status FROM app.users WHERE false"
    expect_ok aia_api "SELECT date, is_open FROM market.trading_calendar WHERE false"
    expect_ok aia_api "SELECT id, user_id, dedup_key FROM app.alerts WHERE false"
    expect_ok aia_api "INSERT INTO app.alerts SELECT * FROM app.alerts WHERE false"
    expect_ok aia_api "INSERT INTO app.audit_logs SELECT * FROM app.audit_logs WHERE false"
    expect_ddl_denied aia_api "BEGIN; ALTER TABLE app.action_plans ADD COLUMN t_o29_probe int; ROLLBACK"
    expect_ddl_denied aia_api "BEGIN; DROP TABLE app.action_plans; ROLLBACK"
    expect_denied aia_api "SELECT ciphertext FROM app.user_data_licences WHERE false"
    expect_attr "aia_maint 仍不能读证书密文" \
      "SELECT NOT has_column_privilege('aia_maint', 'app.user_data_licences', 'ciphertext', 'SELECT')"
  fi
fi
if [ "$(own -c "SELECT to_regclass('market.master_runs') IS NOT NULL AND to_regclass('market.master_vendor_batches') IS NOT NULL")" = t ]; then
  expect_ok aia_api "UPDATE market.master_runs SET status = status, finished_at = finished_at, stats = stats, snapshot_ids = snapshot_ids WHERE false"
  expect_ok aia_ingest "UPDATE market.master_runs SET stats = stats WHERE false"
  expect_denied aia_ingest "UPDATE market.master_vendor_batches SET reconciled_at = reconciled_at WHERE false"
  expect_denied aia_ingest "SELECT security_code FROM market.master_vendor_list_rows WHERE false"
  expect_ok aia_ingest "SELECT id, user_id, ciphertext, seal_key_version FROM app.user_data_licences WHERE false"
fi


# T-O30 / T-A30：aia_ingest 收窄后的正反例。aia_maint 原有 id/user_id SELECT 与 DELETE 仍允许。
if [ "$(own -c "SELECT to_regclass('market.master_runs') IS NOT NULL")" = t ]; then
  expect_ok aia_ingest "SELECT id, stats FROM market.master_runs WHERE false"
  expect_ok aia_ingest "SELECT id FROM market.master_runs WHERE false FOR UPDATE"
  expect_ok aia_ingest "UPDATE market.master_runs SET stats = stats WHERE false"
  expect_denied aia_ingest "BEGIN; INSERT INTO market.master_runs (stats) VALUES ('{}'); ROLLBACK"
  expect_denied aia_ingest "DELETE FROM market.master_runs WHERE false"
  expect_denied aia_ingest "BEGIN; TRUNCATE market.master_runs; ROLLBACK"
  expect_denied aia_ingest "UPDATE market.master_runs SET status = status WHERE false"
  expect_ok aia_api "BEGIN; INSERT INTO market.master_runs (stats) SELECT '{}'::jsonb WHERE false; ROLLBACK"
  expect_attr "aia_ingest 对 master_runs 无表级 INSERT/UPDATE/DELETE/TRUNCATE，且不能改 stats 以外的列" \
    "SELECT has_table_privilege('aia_ingest','market.master_runs','SELECT') AND has_column_privilege('aia_ingest','market.master_runs','stats','UPDATE') AND NOT has_table_privilege('aia_ingest','market.master_runs','INSERT') AND NOT has_table_privilege('aia_ingest','market.master_runs','UPDATE') AND NOT has_table_privilege('aia_ingest','market.master_runs','DELETE') AND NOT has_table_privilege('aia_ingest','market.master_runs','TRUNCATE') AND NOT has_column_privilege('aia_ingest','market.master_runs','status','UPDATE')"
else
  echo "SKIP T-O30：market.master_runs 未落地"
fi
for rel in app.action_plans app.alert_rules app.alerts; do
  if [ "$(own -c "SELECT to_regclass('$rel') IS NOT NULL")" != t ]; then
    echo "SKIP T-O30：$rel 未落地"
    continue
  fi
  expect_denied aia_ingest "SELECT * FROM $rel WHERE false"
  expect_denied aia_ingest "DELETE FROM $rel WHERE false"
  expect_ok aia_maint "SELECT id, user_id FROM $rel WHERE false"
  expect_ok aia_maint "DELETE FROM $rel WHERE false"
  expect_attr "aia_ingest 对 $rel 无表级和列级权限" \
    "SELECT NOT has_table_privilege('aia_ingest','$rel','SELECT') AND NOT has_table_privilege('aia_ingest','$rel','INSERT') AND NOT has_table_privilege('aia_ingest','$rel','UPDATE') AND NOT has_table_privilege('aia_ingest','$rel','DELETE') AND NOT has_any_column_privilege('aia_ingest','$rel','SELECT') AND NOT has_any_column_privilege('aia_ingest','$rel','UPDATE')"
done
expect_ddl_denied aia_ingest "BEGIN; CREATE TABLE market.t_o30_probe (x int); ROLLBACK"
expect_denied aia_api "SELECT ciphertext FROM app.user_data_licences WHERE false"

# P2N-06：表未落地则跳过。不把缺表当成失败（旧库）；表在则最小读写必须成立。
if [ "$(own -c "SELECT to_regclass('app.notification_refs') IS NOT NULL")" = t ]; then
  expect_ok aia_api "SELECT notification_id, ref_type, ref_id, at FROM app.notification_refs WHERE false"
  expect_ok aia_api "INSERT INTO app.notification_refs SELECT * FROM app.notification_refs WHERE false"
  expect_ok aia_maint "DELETE FROM app.notification_refs WHERE false"
else
  echo "SKIP P2N-06：app.notification_refs 未落地"
fi
if [ "$(own -c "SELECT to_regclass('app.intraday_candidate_refs') IS NOT NULL")" = t ]; then
  expect_ok aia_api "SELECT instance_id, event_id FROM app.intraday_candidate_refs WHERE false"
  expect_ok aia_api "INSERT INTO app.intraday_candidate_refs SELECT * FROM app.intraday_candidate_refs WHERE false"
  expect_ok aia_maint "DELETE FROM app.intraday_candidate_refs WHERE false"
else
  echo "SKIP P2N-06：app.intraday_candidate_refs 未落地"
fi
if [ "$(own -c "SELECT to_regclass('app.user_realtime_prefs') IS NOT NULL")" = t ]; then
  expect_ok aia_api "UPDATE app.user_realtime_prefs SET notify_cadence = notify_cadence, updated_at = updated_at WHERE false"
fi
if [ "$(own -c "SELECT to_regclass('app.signal_events') IS NOT NULL")" = t ]; then
  expect_ok aia_api "SELECT id FROM app.signal_events WHERE false"
  expect_ok aia_maint "DELETE FROM app.signal_events WHERE false"
fi
if [ "$(own -c "SELECT to_regclass('app.signal_states') IS NOT NULL")" = t ]; then
  expect_ok aia_maint "DELETE FROM app.signal_states WHERE false"
fi
if [ "$(own -c "SELECT to_regclass('app.intraday_universe') IS NOT NULL")" = t ]; then
  expect_ok aia_maint "DELETE FROM app.intraday_universe WHERE false"
fi
expect_denied aia_api "SELECT ciphertext FROM app.user_data_licences WHERE false"

[ "$(own -c "SELECT count(*) FROM app.users WHERE username LIKE 't\_o11\_%'")" = 0 ] \
  || { echo "FAIL 仍有 t_o11_ 探针用户残留"; fail=1; }
exit "$fail"
