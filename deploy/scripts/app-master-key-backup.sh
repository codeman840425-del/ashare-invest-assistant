#!/usr/bin/env bash
# APP_MASTER_KEY 离线备份 / 核对 / 恢复（T-O12；评审 bbf58a0 m8 的运维部分，方案见 deploy/runbooks/database.md §4）。
# V1 不轮换主密钥（T-O11 裁定 ⑤）：这里只保证“同一把钥匙能被可靠地备份、识别和放回原位”。
#   app-master-key-backup.sh fingerprint [--src FILE]          # 打印主密钥 sha256（64 位十六进制，与 runbook 口径一致）
#   app-master-key-backup.sh backup --dest DIR [--src FILE]    # 拷成 DIR/app_master_key-<UTC>.key（600）+ 同名 .sha256
#   app-master-key-backup.sh verify BACKUP [--src FILE]        # 备份与当前主密钥是否同一把（同 0 / 不同 1）
#   app-master-key-backup.sh restore BACKUP --dir DIR          # 放回 DIR/app_master_key（目标已存在则拒绝，从不覆盖）
#   app-master-key-backup.sh drill                             # 用假密钥在临时目录走一遍 备份→丢失→恢复→核对，结束即删
# --src 缺省为 compose.sh 解析出的 $AIA_SECRETS_DIR/app_master_key；读不了时用 sudo -n 读（文件属主是容器用户）。
# 规则：密钥从不打印、不经命令行参数或环境变量传递、不进日志；只输出路径和 sha256。
#       备份目录必须是仓库外的绝对路径，不能是密钥目录本身；目录里有 *.dump 时拒绝（主密钥不能和库备份放在一起）。
{ set +x; } 2>/dev/null
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SELF="$ROOT/deploy/scripts/app-master-key-backup.sh"
app_uid="${AIA_APP_UID:-10001}"
die() { echo "$1" >&2; exit "${2:-2}"; }
[[ "$app_uid" =~ ^[0-9]+$ ]] || die "AIA_APP_UID 必须是数字"

secrets_dir() { "$ROOT/deploy/scripts/compose.sh" --get AIA_SECRETS_DIR; }
default_src() { echo "$(secrets_dir)/app_master_key"; }
abs_outside_repo() {  # $1 路径 $2 用途
  case "$1" in /*) ;; *) die "$2 必须是绝对路径：$1" ;; esac
  case "$1/" in "$ROOT"/*) die "$2 不能在仓库里：$1" ;; esac
}
read_key() {  # 把文件内容写到 stdout（只用于管道/重定向，从不到终端）
  if [ -r "$1" ]; then cat -- "$1"; elif sudo -n true 2>/dev/null; then sudo -n cat -- "$1"; else die "读不了 $1（需要 sudo -n）" 3; fi
}
key_exists() { [ -e "$1" ] || sudo -n test -e "$1" 2>/dev/null; }
sha_of() { read_key "$1" | sha256sum | cut -d' ' -f1; }
check_len() {  # 后端要求至少 32 个字符；空文件/截断文件不能当备份
  local n; n="$(read_key "$1" | wc -c)"; [ "$n" -ge 32 ] || die "$1 不像主密钥（${n} 字节 < 32）" 3
}

cmd="${1:-}"; [ $# -gt 0 ] && shift
src=""; dest=""; dir=""; backup=""
while [ $# -gt 0 ]; do
  case "$1" in
    --src) src="${2:?--src 需要参数}"; shift 2 ;;
    --dest) dest="${2:?--dest 需要参数}"; shift 2 ;;
    --dir) dir="${2:?--dir 需要参数}"; shift 2 ;;
    -*) die "未知参数：$1" ;;
    *) [ -z "$backup" ] || die "多余参数：$1"; backup="$1"; shift ;;
  esac
done

case "$cmd" in
fingerprint)
  [ -n "$src" ] || src="$(default_src)"
  key_exists "$src" || die "不存在：$src" 3
  sha_of "$src" ;;
backup)
  [ -n "$dest" ] || die "backup 需要 --dest DIR"
  [ -n "$src" ] || src="$(default_src)"
  abs_outside_repo "$dest" "--dest"
  key_exists "$src" || die "不存在：$src" 3
  sdir="$(cd "$(dirname "$src")" 2>/dev/null && pwd -P || dirname "$src")"
  mkdir -p "$dest"; ddir="$(cd "$dest" && pwd -P)"
  [ "$ddir" != "$sdir" ] || die "--dest 不能是密钥所在目录（$dest）"
  if compgen -G "$ddir/*.dump" >/dev/null; then die "--dest 里有数据库备份（*.dump），主密钥必须和 dump 分开存放：$dest"; fi
  check_len "$src"
  want="$(sha_of "$src")"
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"; out="$ddir/app_master_key-$stamp.key"
  [ ! -e "$out" ] && [ ! -e "$out.sha256" ] || die "已存在，不覆盖：$out" 3
  umask 077
  tmp="$(mktemp "$ddir/.app_master_key.XXXXXX")"; trap 'rm -f "$tmp"' EXIT
  read_key "$src" > "$tmp"; chmod 600 "$tmp"
  [ "$(sha256sum "$tmp" | cut -d' ' -f1)" = "$want" ] || die "拷贝后摘要不一致，已放弃" 4
  ln "$tmp" "$out" 2>/dev/null || die "已存在，不覆盖：$out" 3   # ln 不会覆盖已有文件
  rm -f "$tmp"; trap - EXIT
  printf '%s  %s\n' "$want" "$(basename "$out")" > "$out.sha256"; chmod 600 "$out.sha256"
  echo "已备份：$out（600）sha256=$want"
  echo "提醒：把它挪到离线介质 / 密码管理器，与数据库 dump、导入卷备份分开存放。" ;;
verify)
  [ -n "$backup" ] || die "verify 需要 BACKUP 路径"
  [ -n "$src" ] || src="$(default_src)"
  key_exists "$backup" || die "不存在：$backup" 3
  key_exists "$src" || die "不存在：$src" 3
  b="$(sha_of "$backup")"; c="$(sha_of "$src")"
  if [ -e "$backup.sha256" ] && [ "$(cut -d' ' -f1 "$backup.sha256")" != "$b" ]; then die "备份文件与它的 .sha256 不符（备份已损坏）" 4; fi
  if [ "$b" = "$c" ]; then echo "一致：备份与 $src 是同一把（sha256=$c）"; else echo "不一致：备份 sha256=$b，当前 sha256=$c"; exit 1; fi ;;
restore)
  [ -n "$backup" ] || die "restore 需要 BACKUP 路径"
  [ -n "$dir" ] || dir="$(secrets_dir)"
  abs_outside_repo "$dir" "--dir"
  key_exists "$backup" || die "不存在：$backup" 3
  f="$dir/app_master_key"
  if key_exists "$f"; then die "已存在，不覆盖：$f（主密钥只能人工决定替换；先用 verify 核对是不是同一把）" 3; fi
  check_len "$backup"
  b="$(sha_of "$backup")"
  if [ -e "$backup.sha256" ]; then [ "$(cut -d' ' -f1 "$backup.sha256")" = "$b" ] || die "备份文件与它的 .sha256 不符（备份已损坏），不恢复" 4
  else echo "警告：没有 $backup.sha256，无法核对完整性；请对照备份台账里的 sha256" >&2; fi
  umask 077; mkdir -p "$dir"
  tmp="$(mktemp "$dir/.app_master_key.XXXXXX")"; trap '[ -e "$tmp" ] && { rm -f "$tmp" 2>/dev/null || sudo -n rm -f "$tmp"; }' EXIT
  read_key "$backup" > "$tmp"; chmod 600 "$tmp"
  [ "$(sha256sum "$tmp" | cut -d' ' -f1)" = "$b" ] || die "拷贝后摘要不一致，已放弃" 4
  if [ "$(stat -c %u "$tmp")" != "$app_uid" ]; then
    if [ "$(id -u)" = 0 ]; then chown "$app_uid:$app_uid" "$tmp"
    elif sudo -n true 2>/dev/null; then sudo -n chown "$app_uid:$app_uid" "$tmp"
    else echo "警告：无法把属主改成 $app_uid（无 sudo），api/worker 读不到它" >&2; fi
  fi
  if [ -e "$tmp" ]; then mv -n "$tmp" "$f"; else sudo -n mv -n "$tmp" "$f"; fi
  key_exists "$tmp" && die "目标在恢复过程中出现了，未覆盖：$f" 3
  trap - EXIT
  echo "已恢复：$f（600，属主 $app_uid）sha256=$b"
  echo "下一步：按 deploy/runbooks/database.md §4 先恢复库、再恢复导入卷，然后才 up（带 --scale ingest=0）。" ;;
drill)
  w="$(mktemp -d)"; trap 'rm -rf "$w"' EXIT
  s="$w/secrets"; o="$w/offline"; mkdir -p "$s" "$o"; chmod 700 "$s"
  export AIA_APP_UID="$(id -u)"
  "$ROOT/deploy/scripts/app-master-keygen.sh" "$s" >/dev/null
  fp="$("$SELF" fingerprint --src "$s/app_master_key")"; echo "1 生成假密钥 sha256=${fp:0:16}…"
  "$SELF" backup --dest "$o" --src "$s/app_master_key" >/dev/null; bk="$(ls "$o"/app_master_key-*.key)"
  [ "$(stat -c %a "$bk")" = 600 ] || die "drill：备份权限不是 600" 5; echo "2 备份 → $(basename "$bk")（600）"
  "$SELF" verify "$bk" --src "$s/app_master_key" >/dev/null || die "drill：备份核对失败" 5; echo "3 核对一致"
  if "$SELF" restore "$bk" --dir "$s" >/dev/null 2>&1; then die "drill：目标存在时 restore 居然成功了" 5; fi; echo "4 目标存在时拒绝恢复（不覆盖）"
  if "$SELF" backup --dest "$s" --src "$s/app_master_key" >/dev/null 2>&1; then die "drill：备份到密钥目录居然成功了" 5; fi
  : > "$w/fake.dump"; if "$SELF" backup --dest "$w" --src "$s/app_master_key" >/dev/null 2>&1; then die "drill：和 dump 放一起居然成功了" 5; fi
  echo "5 拒绝备份到密钥目录 / 有 dump 的目录"
  rm -f "$s/app_master_key"; echo "6 模拟丢失主密钥"
  "$SELF" restore "$bk" --dir "$s" >/dev/null
  [ "$("$SELF" fingerprint --src "$s/app_master_key")" = "$fp" ] && [ "$(stat -c %a "$s/app_master_key")" = 600 ] || die "drill：恢复后摘要/权限不对" 5
  echo "7 从备份恢复，sha256 与原来一致，600"
  od -An -tx1 -N32 /dev/urandom | tr -d ' \n' > "$w/other"
  if "$SELF" verify "$bk" --src "$w/other" >/dev/null; then die "drill：不同的钥匙居然核对一致" 5; fi; echo "8 换一把钥匙核对 → 不一致（能识别错钥匙）"
  printf x >> "$bk"; if "$SELF" restore "$bk" --dir "$w/new" >/dev/null 2>&1; then die "drill：损坏的备份居然恢复了" 5; fi; echo "9 备份被改动 → 拒绝恢复"
  echo "drill：全部通过（临时目录已删除）" ;;
*) sed -n '2,11p' "$SELF" | sed 's/^# \{0,1\}//'; [ -z "$cmd" ] && exit 2 || die "未知子命令：$cmd" ;;
esac
