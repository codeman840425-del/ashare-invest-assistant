#!/usr/bin/env bash
# APP_MASTER_KEY 密钥文件的启动前检查（T-O11 评审 M1/M2，严格按 docs/plan.md e56462c“升级约束”①–⑤）：
# compose.sh 每次调用 docker compose 之前都执行（文件已存在时也要做 ④ 的一致性比对）。
# 主密钥只有一份 secret 文件 app_master_key，只挂给 api / worker（plan“按服务分配”表；其余服务不挂、不要求）。
# 换主密钥会让邀请码 HMAC、证书去重 HMAC、冷却指纹、登录 IP HMAC、分页游标、导入文件派生密钥全部失效，所以：
#   旧来源 = 调用方环境变量 APP_MASTER_KEY，或 .env 里最后一个 APP_MASTER_KEY 赋值（只做文本解析，不 source；
#            按 compose 的 .env 规则处理行尾注释与引号，做不到一致的写法拒绝，见下方解析段）；
#            占位值（空、含 < 或 >、changeme/example 开头，与 check_real_secrets.sh 一致）视为没有；
#            环境变量与 .env 两处都有且不一致 → 拒绝（由人决定用哪把）。
#   ④ 密钥文件已存在、旧来源也有且与文件不一致 → 拒绝启动，等人工确认（读不到文件无法比对时同样拒绝）；
#     一致 → 用文件，并提示从 .env 删除该行；文件存在但为空 → 拒绝，不覆盖。
#     旧来源没有 → 直接用文件。
#   ② 文件不存在、旧来源有非占位值 → 迁移进密钥文件（umask 077、600、属主 AIA_APP_UID 默认 10001；不打印值、
#     值不进命令行参数），提示从 .env 删除该行（脚本不自动删）；不生成新值。值短于 32 个字符（后端会拒绝）→ 拒绝。
#   ③ 两者都没有、但数据库已有数据（app.users、app.invite_codes、app.user_data_licences 任一非空）→ 拒绝启动，
#     提示从备份恢复主密钥；连不上数据库（docker 不可用、数据卷在但没有运行中的 postgres、查询失败）同样拒绝。
#     另外两项保守检查（plan 未列，只会多拒绝、不会多生成）：app.import_files 有行、导入卷里有文件 → 拒绝。
#   ① 只有全新部署（文件不存在、旧来源没有、数据库为空——数据卷不存在，或上述表都不存在/都为空）才生成。
#   ⑤ 主密钥轮换不在 V1 范围：本脚本从不替换已有文件。
# 排错时不要用 bash -x（脚本开头会强制 set +x；值也绝不会出现在普通输出里）。
# AIA_KEYCHECK_ONLY=1：检查模式（compose.sh 对 down/ps/logs 等不启动容器的子命令使用），只判定、不迁移不生成。
# ③ 的查库会话强制只读；“有数据”还包括 app.llm_providers 里的 api_key_ciphertext（评审 75c233b n1/n2）。
# 退出码：0 可以继续（已有 / 已迁移 / 已生成）；2 配置错误；3 拒绝启动。
# 用法：app-master-key-ensure.sh <密钥目录> <env 文件> <卷前缀>
#   AIA_DOCKER   docker 命令（默认 docker；compose.sh 传 "sudo -n docker" 等）
#   AIA_KEYCHECK_IMAGE  检查导入卷用的镜像（默认取基础 compose 里 postgres 的镜像，部署机上一定有）
# 评审 8cf9771 m3：继承来的 xtrace（bash -x 排错、SHELLOPTS=xtrace 导出）会把 raw / file_val 等值打到 stderr，先关掉。
{ set +x; } 2>/dev/null
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

# 旧来源：调用方环境变量 / .env（只做 KEY=VALUE 文本解析，不 source）
is_real() {  # 非占位值
  case "$1" in ''|*'<'*|*'>'*|changeme*|example*) return 1 ;; esac
  return 0
}
env_val=""; file_val=""
if [ -n "${APP_MASTER_KEY+x}" ]; then env_val="$APP_MASTER_KEY"; fi
envfile_refuse() {  # 不打印值，只说原因
  unset file_val env_val raw rest q tail_
  echo "拒绝启动（$tag）：${env_file} 里 APP_MASTER_KEY 的写法$1，无法保证与 docker compose 读到的值一致；" >&2
  echo "  请人工核对后改成不加引号的纯值（或单引号包住、不含 \\ 和空白），或直接把原值写入 $f（600，属主 ${AIA_APP_UID:-10001}）后重试。" >&2
  exit 3
}
if [ -f "$env_file" ]; then
  # 按 docker compose（compose-go）.env 规则解析（评审 75c233b B1；规则用 docker compose v5.6.1 实测对照，见测试 test_env_parse_matches_compose）：
  #   同名多行取最后一行；KEY=VAL / KEY = VAL / export KEY=VAL；值去首尾空白；
  #   未加引号：只有“空格 + #”起是行尾注释（# 前没有空格、或前面是制表符时都算值的一部分；
  #   KEY=  # 注释 这种“等号后只有注释”的写法，compose 读到的值是“# 注释”本身，按含空白拒绝）；
  #   引号值：取到配对的引号为止，引号后的“# 注释”和空白忽略。
  # 做不到逐字一致的写法一律拒绝（宁可停下来让人确认，也不悄悄迁移错值）：KEY: VAL 写法、含 $（插值）、
  # 引号值含 \（转义）、引号不配对或跨行、引号后还有非注释内容、最终值里有空白或控制字符。
  # 占位判断在解析之后（评审 8cf9771 m1）：对解析出的值做 is_real，行尾注释里的 < > 不再让真实值被当成占位；
  # 解析不了（会拒绝）的写法，先看原文第一个词像不像占位值（如 KEY=<请填写 32 位>），像就视为没有，否则拒绝。
  if grep -Eq '^[[:space:]]*(export[[:space:]]+)?APP_MASTER_KEY[[:space:]]*:' "$env_file"; then
    envfile_refuse "是 KEY: VALUE 形式"
  fi
  raw="$(sed -n 's/^[[:space:]]*\(export[[:space:]]\{1,\}\)\{0,1\}APP_MASTER_KEY[[:space:]]*=//p' "$env_file" | tail -n 1)"
  raw="${raw%$'\r'}"
  raw="${raw#"${raw%%[![:space:]]*}"}"
  raw="${raw%"${raw##*[![:space:]]}"}"
  bad=""
  q="${raw:0:1}"
  if [ "$q" = '"' ] || [ "$q" = "'" ]; then
    rest="${raw:1}"
    case "$rest" in
      *"$q"*)
        file_val="${rest%%"$q"*}"
        tail_="${rest#*"$q"}"
        tail_="${tail_#"${tail_%%[![:space:]]*}"}"
        case "$file_val" in *\\*) bad="在引号里含反斜杠（compose 会按转义处理）" ;; esac
        case "$tail_" in ''|'#'*) ;; *) bad="${bad:-在引号后还有非注释内容}" ;; esac
        if [ "$q" = '"' ]; then case "$file_val" in *'$'*) bad="${bad:-在双引号里含 \$（compose 会插值）}" ;; esac; fi
        ;;
      *) bad="引号不配对（或跨行）"; file_val="$rest" ;;
    esac
  else
    file_val="$raw"
    case "$file_val" in *' #'*) file_val="${file_val%%' #'*}" ;; esac
    file_val="${file_val%"${file_val##*[![:space:]]}"}"
    case "$file_val" in *'$'*) bad="含 \$（compose 会插值）" ;; esac
  fi
  if [ -z "$bad" ] && [[ "$file_val" =~ [[:space:][:cntrl:]] ]]; then bad="解析出的值里有空白或控制字符"; fi
  if [ -n "$bad" ]; then
    # 解析失败：只有原文第一个词（到第一个空白为止，注释不算；引号不配对时已去掉开头引号）是占位值时才视为没有
    cand="${file_val%%[[:space:]]*}"
    if is_real "$cand"; then unset cand; envfile_refuse "$bad"; fi
    file_val=""
  fi
  unset raw rest q tail_ cand bad
fi
is_real "$env_val" || env_val=""
is_real "$file_val" || file_val=""
if [ -n "$env_val" ] && [ -n "$file_val" ] && [ "$env_val" != "$file_val" ]; then
  echo "拒绝启动（$tag）：环境变量 APP_MASTER_KEY 与 ${env_file} 里的值不一致，无法判断哪把是线上在用的；请人工确认后写入 $f。" >&2
  exit 3
fi
legacy="${env_val:-$file_val}"
src="${env_val:+环境变量 APP_MASTER_KEY}"; src="${src:-$env_file}"

# ④ / 已有密钥文件
if [ -e "$f" ] || [ -L "$f" ]; then
  [ -s "$f" ] || { echo "$f 存在但为空：拒绝启动，也不覆盖（请人工处理）" >&2; exit 3; }
  [ -n "$legacy" ] || exit 0
  if [ -r "$f" ]; then cur="$(tr -d '\r\n' < "$f")"
  else cur="$(sudo -n cat "$f" 2>/dev/null | tr -d '\r\n')" || cur=""
  fi
  if [ -z "$cur" ]; then
    unset legacy env_val file_val
    echo "拒绝启动（$tag）：$src 里有 APP_MASTER_KEY，但读不到 $f 无法比对两者是否一致（plan 升级约束④）；请人工确认。" >&2
    exit 3
  fi
  if [ "$cur" != "$legacy" ]; then
    unset cur legacy env_val file_val
    {
      echo "拒绝启动（$tag）：$f 与 $src 里的 APP_MASTER_KEY 不一致（plan 升级约束④），无法判断哪把是线上在用的。"
      echo "  请人工确认：保留文件 → 从 $src 删除 APP_MASTER_KEY；改用旧值 → 先备份再替换文件（见 deploy/runbooks/database.md）。"
    } >&2
    exit 3
  fi
  unset cur legacy env_val file_val
  echo "$tag：$f 与 $src 里的值一致，使用密钥文件；请从 $src 删除 APP_MASTER_KEY 行（compose 已不再读它，脚本不自动删除）。" >&2
  exit 0
fi
# 检查模式（评审 75c233b m2）：compose.sh 对不启动容器的子命令（down/ps/logs/stop…）传 AIA_KEYCHECK_ONLY=1：
# 上面的拒绝照常判定（由 compose.sh 降为告警），但不迁移、不生成，也不为 ③ 起容器查库——这些只在 up/run/create/start/restart 时做。
if [ "${AIA_KEYCHECK_ONLY:-0}" = 1 ]; then
  unset legacy env_val file_val
  echo "$tag：$f 不存在（检查模式，不迁移、不生成；下次 up/run/create/start/restart 时按升级约束②/③/①处理）。" >&2
  exit 0
fi
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
  [ "$src" = "$env_file" ] && echo "  请确认迁移无误后从 ${env_file} 删除 APP_MASTER_KEY 行（compose 已不再读它；脚本不自动删除）。" >&2
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
  # 判定“库里有数据”（评审 75c233b n1/n2）：4 张表的行数 + app.llm_providers 里非空的 api_key_ciphertext（系统级密文，
  # users 为空时也可能存在）。表或列不存在算 0。会话强制只读：PGOPTIONS default_transaction_read_only=on，
  # 外加显式 BEGIN READ ONLY（两道都在，任一生效都写不进去）。表名写死，没有注入面。
  cnt() {  # $1 表，$2 条件（可空），$3 条件依赖的列（可空）
    local guard="to_regclass('$1') IS NULL" where=""
    if [ -n "$3" ]; then
      guard="$guard OR NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='${1%%.*}' AND table_name='${1#*.}' AND column_name='$3')"
    fi
    [ -n "$2" ] && where=" WHERE $2"
    printf "%s" " || '|' || CASE WHEN $guard THEN 0 ELSE (xpath('/row/c/text()', query_to_xml('SELECT count(*) AS c FROM $1$where', false, true, '')))[1]::text::bigint END"
  }
  sql="SELECT 0$(cnt app.users '' '')$(cnt app.invite_codes '' '')$(cnt app.user_data_licences '' '')$(cnt app.import_files '' '')$(cnt app.llm_providers 'api_key_ciphertext IS NOT NULL' api_key_ciphertext)"
  out="$(printf 'BEGIN READ ONLY;\n%s;\nCOMMIT;\n' "$sql" | "${DOCKER[@]}" exec -i -e PGOPTIONS='-c default_transaction_read_only=on' "$cid" sh -c \
        'psql -X -q -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' 2>/dev/null)" \
    || refuse "查询 $pg 所在的库失败，无法确认是空库"
  IFS='|' read -r _zero users invites licences files llmkeys <<< "$out"
  for v in "$users" "$invites" "$licences" "$files" "$llmkeys"; do
    [[ "$v" =~ ^[0-9]+$ ]] || refuse "查询 $pg 所在的库返回了无法解析的结果，无法确认是空库"
  done
  if [ "$users" != 0 ] || [ "$invites" != 0 ] || [ "$licences" != 0 ] || [ "$files" != 0 ] || [ "$llmkeys" != 0 ]; then
    refuse "库里已有数据（app.users=$users，app.invite_codes=$invites，app.user_data_licences=$licences，app.import_files=$files，app.llm_providers 密文=$llmkeys）；请从备份恢复主密钥"
  fi
fi
echo "$tag：全新部署（数据卷 $pg 不存在，或 app.users / invite_codes / user_data_licences / import_files / llm_providers 密文都为空或不存在；导入卷为空），生成新主密钥。" >&2
exec "$ROOT/deploy/scripts/app-master-keygen.sh" "$dir"
