#!/usr/bin/env bash
# APP_MASTER_KEY 密钥文件的启动前检查（T-O11 评审 M1）：compose.sh 每次调用 docker compose 之前执行。
# 已有部署升级时绝不悄悄生成新主密钥（换主密钥会让邀请码 HMAC、证书去重 HMAC、冷却指纹、登录 IP HMAC、
# 分页游标、导入文件与 raw_line 的派生密钥全部失效）。按顺序判定：
#   1. <密钥目录>/app_master_key 已存在 → 直接用（为空则拒绝，不覆盖）；
#   2. 不存在，但旧来源里有非占位值的 APP_MASTER_KEY（调用方环境变量，或 .env 的最后一个赋值）→ 迁移进密钥文件
#      （umask 077、600、属主 AIA_APP_UID 默认 10001；不打印值、值不进命令行参数）；只提示“已迁移”，
#      不改 .env（是否删除 .env 里那一行由人决定）。环境变量与 .env 两处值不一致 → 拒绝（由人决定用哪把）。
#      值短于 32 个字符（后端会拒绝）→ 拒绝，不迁移。
#   3. 两边都没有：只有“全新空库”才调用 app-master-keygen.sh 生成新密钥。下列任一条成立都视为“已有数据”，拒绝（退出 3）：
#      - 导入卷 <卷前缀>_imports 存在且里面有文件（加密的原始交割单）；
#      - 数据卷 <卷前缀>_pgdata 存在，且库已初始化：有任何非系统、非扩展自带的表（含 public.alembic_version），
#        或 app.users / app.invite_codes / app.user_data_licences / app.import_files 有行；
#      - 数据卷存在但没有运行中的 postgres 挂着它、或查询失败 → 无法确认是空库，按“有数据”拒绝（fail-closed）；
#      - 访问不了 docker → 无法确认，拒绝。
#      数据卷不存在（首次部署）或库里一张业务表都没有 → 生成。
# 占位值（与 check_real_secrets.sh 一致）：空、含 < 或 >、changeme/example 开头 → 视为没有。
# 退出码：0 可以继续（已有 / 已迁移 / 已生成）；2 配置错误；3 拒绝启动（有数据但没有主密钥，或两处旧值冲突）。
# 用法：app-master-key-ensure.sh <密钥目录> <env 文件> <卷前缀>
#   AIA_DOCKER   docker 命令（默认 docker；compose.sh 传 "sudo -n docker" 等）
#   AIA_KEYCHECK_IMAGE  检查导入卷用的镜像（默认取基础 compose 里 postgres 的镜像，部署机上一定有）
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
[ $# -eq 3 ] || { echo "用法：$0 <密钥目录> <env 文件> <卷前缀>" >&2; exit 2; }
dir="$1"; env_file="$2"; prefix="$3"
case "$dir" in /*) ;; *) echo "密钥目录必须是绝对路径：$dir" >&2; exit 2 ;; esac
read -r -a DOCKER <<< "${AIA_DOCKER:-docker}"
f="$dir/app_master_key"
tag="app_master_key"

refuse() {
  {
    echo "拒绝启动（$tag）：$f 不存在，环境变量和 ${env_file} 里也没有可用的 APP_MASTER_KEY，"
    echo "  但$1。"
    echo "  自动生成新主密钥会让既有邀请码 / 证书 HMAC、登录 IP HMAC、分页游标和加密的导入文件全部失效。"
    echo "  处理：找回原主密钥写入 $f（600，属主 ${AIA_APP_UID:-10001}）后重试，见 deploy/runbooks/database.md“APP_MASTER_KEY 迁移”；"
    echo "  确认放弃旧数据时，才由人工运行 deploy/scripts/app-master-keygen.sh $dir。"
  } >&2
  exit 3
}

# 1. 已有密钥文件
if [ -e "$f" ] || [ -L "$f" ]; then
  [ -s "$f" ] || { echo "$f 存在但为空：拒绝启动，也不覆盖（请人工处理）" >&2; exit 3; }
  exit 0
fi

# 2. 旧来源：调用方环境变量 / .env（只做 KEY=VALUE 文本解析，不 source）
is_real() {  # 非占位值
  case "$1" in ''|*'<'*|*'>'*|changeme*|example*) return 1 ;; esac
  return 0
}
env_val=""; file_val=""
if [ -n "${APP_MASTER_KEY+x}" ]; then env_val="$APP_MASTER_KEY"; fi
if [ -f "$env_file" ]; then
  file_val="$(sed -n 's/^[[:space:]]*\(export[[:space:]]\{1,\}\)\{0,1\}APP_MASTER_KEY[[:space:]]*=//p' "$env_file" | tail -n 1)"
  file_val="${file_val%$'\r'}"
  file_val="${file_val#"${file_val%%[![:space:]]*}"}"; file_val="${file_val%"${file_val##*[![:space:]]}"}"
  case "$file_val" in \"*\") file_val="${file_val:1:${#file_val}-2}" ;; \'*\') file_val="${file_val:1:${#file_val}-2}" ;; esac
fi
is_real "$env_val" || env_val=""
is_real "$file_val" || file_val=""
if [ -n "$env_val" ] && [ -n "$file_val" ] && [ "$env_val" != "$file_val" ]; then
  echo "拒绝启动（$tag）：环境变量 APP_MASTER_KEY 与 ${env_file} 里的值不一致，无法判断哪把是线上在用的；请人工确认后写入 $f。" >&2
  exit 3
fi
legacy="${env_val:-$file_val}"
src="${env_val:+环境变量 APP_MASTER_KEY}"; src="${src:-$env_file}"
if [ -n "$legacy" ]; then
  if [ "${#legacy}" -lt 32 ]; then
    echo "拒绝启动（$tag）：$src 里的 APP_MASTER_KEY 短于 32 个字符（后端会拒绝），不迁移；请人工处理。" >&2
    exit 3
  fi
  app_uid="${AIA_APP_UID:-10001}"
  case "$app_uid" in ''|*[!0-9]*) echo "AIA_APP_UID 必须是数字：$app_uid" >&2; exit 2 ;; esac
  case "$dir/" in "$ROOT"/*) echo "密钥目录不能在仓库里（$dir）" >&2; exit 2 ;; esac
  umask 077
  mkdir -p "$dir"
  tmp="$(mktemp "$dir/.app_master_key.migrate.XXXXXX")"
  trap '[ -e "$tmp" ] && { rm -f "$tmp" 2>/dev/null || sudo -n rm -f "$tmp"; }' EXIT
  printf '%s' "$legacy" > "$tmp"   # printf 是内建命令，值不出现在进程参数里
  unset legacy env_val file_val
  chmod 600 "$tmp"
  if [ "$(stat -c %u "$tmp")" != "$app_uid" ]; then
    if [ "$(id -u)" = 0 ]; then chown "$app_uid:$app_uid" "$tmp"
    elif sudo -n true 2>/dev/null; then sudo -n chown "$app_uid:$app_uid" "$tmp"
    else echo "警告：无法把属主改成 $app_uid（无 sudo），api/worker 读不到它；请让管理员执行 chown $app_uid:$app_uid $f" >&2
    fi
  fi
  mv -n "$tmp" "$f"
  [ -e "$tmp" ] && { echo "$f 已被并发创建，未覆盖" >&2; exit 3; }
  echo "已从 $src 迁移 APP_MASTER_KEY 到 $f（600，属主 $(stat -c %u "$f")）。" >&2
  [ "$src" = "$env_file" ] && echo "  ${env_file} 里的 APP_MASTER_KEY 行未删除（compose 已不再读它）；确认迁移无误后由人决定是否删除。" >&2
  exit 0
fi

# 3. 两边都没有：只有全新空库才生成
"${DOCKER[@]}" info >/dev/null 2>&1 || refuse "访问不了 docker，无法确认数据卷 ${prefix}_pgdata / ${prefix}_imports 是否为空"
vol_exists() { "${DOCKER[@]}" volume inspect "$1" >/dev/null 2>&1; }
img="${AIA_KEYCHECK_IMAGE:-$(sed -n 's/^ *image: *\(timescale\/[^ ]*\).*/\1/p' "$ROOT/deploy/compose/docker-compose.yml" | head -1)}"
imp="${prefix}_imports"; pg="${prefix}_pgdata"
if vol_exists "$imp"; then
  n="$("${DOCKER[@]}" run --rm --network none --user 0 -v "$imp:/v:ro" --entrypoint sh "$img" \
        -c 'find /v -mindepth 1 -type f | wc -l' 2>/dev/null)" || refuse "无法检查导入卷 $imp（镜像 $img 不可用？）"
  n="$(printf '%s' "$n" | tr -dc 0-9)"
  [ "${n:-x}" = 0 ] || refuse "导入卷 $imp 里有 ${n:-?} 个文件（用主密钥派生密钥加密的原始交割单）"
fi
if vol_exists "$pg"; then
  cid="$("${DOCKER[@]}" ps -q --filter "volume=$pg" | head -n 1)"
  [ -n "$cid" ] || refuse "数据卷 $pg 已存在、但没有运行中的 postgres 挂着它，无法确认是空库（可先 docker start 原 postgres 容器——docker ps -a --filter volume=$pg——再重试）"
  sql="SELECT (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE c.relkind IN ('r','p') AND n.nspname NOT IN ('pg_catalog','information_schema')
       AND n.nspname NOT LIKE 'pg\\_%' AND n.nspname NOT LIKE '\\_timescaledb%' AND n.nspname NOT LIKE 'timescaledb%'
       AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype = 'e'))"
  for t in app.users app.invite_codes app.user_data_licences app.import_files; do
    sql="$sql || '|' || CASE WHEN to_regclass('$t') IS NULL THEN 0 ELSE
      (xpath('/row/c/text()', query_to_xml('SELECT count(*) AS c FROM $t', false, true, '')))[1]::text::bigint END"
  done
  out="$(printf '%s;\n' "$sql" | "${DOCKER[@]}" exec -i "$cid" sh -c \
        'psql -X -q -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' 2>/dev/null)" \
    || refuse "查询 $pg 所在的库失败，无法确认是空库"
  IFS='|' read -r tables users invites licences files <<< "$out"
  [[ "$tables" =~ ^[0-9]+$ ]] || refuse "查询 $pg 所在的库返回了无法解析的结果，无法确认是空库"
  if [ "$tables" != 0 ]; then
    refuse "库已初始化（$tables 张业务表；app.users=$users，app.invite_codes=$invites，app.user_data_licences=$licences，app.import_files=$files）"
  fi
fi
echo "$tag：全新空库（数据卷 $pg 不存在或没有业务表，导入卷为空），生成新主密钥。" >&2
exec "$ROOT/deploy/scripts/app-master-keygen.sh" "$dir"
