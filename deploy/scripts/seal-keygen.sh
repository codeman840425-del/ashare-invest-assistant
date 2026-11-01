#!/usr/bin/env bash
# 生成用户数据证书的封装密钥对（T-O09；plan §2.1B、T-A07 §2）：HPKE Base 模式，DHKEM(X25519, HKDF-SHA256)。
#   deploy/scripts/seal-keygen.sh [--version N] [--dir DIR]   # 缺省 N=1；DIR 缺省为 compose.sh 解析出的 AIA_SECRETS_DIR
# 结果放在 compose.sh 解析出的 AIA_SECRETS_DIR（默认 ~/.config/aia/secrets/<数据卷前缀>，在仓库外，权限 700）：
#   data_licence_seal_private_keys  私钥，权限 600，属主改成容器用户（AIA_APP_UID，默认 10001）；只以 docker secret 挂给 ingest
#   data_licence_seal_public_keys   公钥，权限 644；以 docker secret 挂给 api 和 ingest（公钥不是秘密，但它和本机部署绑定，不入库）
#   data_licence_seal_keys.meta.json  版本号、生成时间、公钥 sha256 指纹（不含密钥）
# 文件格式（后端在 T-B04a/T-B45 按此加载，pydantic-settings secrets_dir=/run/secrets，字段名即文件名）：
#   单行 JSON 对象 {"<key_version>": "<base64 DER>"}；私钥为 PKCS#8 DER，公钥为 SubjectPublicKeyInfo DER。
#   当前版本由环境变量 DATA_LICENCE_SEAL_KEY_VERSION 指定（api、ingest）。
# 规则：两个文件任一已存在就不覆盖、直接退出（退出码 0，并说明）；密钥从不打印、不经命令行参数、不进日志。
# 备份：私钥丢失 = 已加密的证书全部无法解密。私钥要单独备份，不能和数据库备份放在一起（见 deploy/runbooks/data-licence-seal-keys.md）。
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
version=1
dir=""
while [ $# -gt 0 ]; do
  case "$1" in
    --version) version="${2:?--version 需要参数}"; shift 2 ;;
    --dir) dir="${2:?--dir 需要参数}"; shift 2 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done
[[ "$version" =~ ^[1-9][0-9]{0,5}$ ]] || { echo "--version 必须是正整数" >&2; exit 2; }

[ -n "$dir" ] || dir="$("$HERE/compose.sh" --get AIA_SECRETS_DIR)"
case "$dir" in /*) ;; *) echo "--dir 必须是绝对路径" >&2; exit 2 ;; esac
app_uid="${AIA_APP_UID:-10001}"
priv="$dir/data_licence_seal_private_keys"
pub="$dir/data_licence_seal_public_keys"
meta="$dir/data_licence_seal_keys.meta.json"

if [ -e "$priv" ] || [ -e "$pub" ]; then
  echo "已有封装密钥文件（$dir），不覆盖。轮换请按 deploy/runbooks/data-licence-seal-keys.md 操作。"
  exit 0
fi
command -v openssl >/dev/null || { echo "需要 openssl" >&2; exit 1; }

umask 077
mkdir -p "$dir"
chmod 700 "$dir"
tmp="$(mktemp -d "$dir/.keygen.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT

openssl genpkey -algorithm X25519 -outform DER -out "$tmp/sk.der" 2>/dev/null
openssl pkey -inform DER -in "$tmp/sk.der" -pubout -outform DER -out "$tmp/pk.der" 2>/dev/null
# 自检：X25519 的 PKCS#8 / SPKI DER 长度固定为 48 / 44 字节
[ "$(stat -c %s "$tmp/sk.der")" = 48 ] && [ "$(stat -c %s "$tmp/pk.der")" = 44 ] \
  || { echo "生成的密钥长度异常，已放弃" >&2; exit 1; }
{ printf '{"%s": "' "$version"; base64 -w0 "$tmp/sk.der"; printf '"}\n'; } > "$tmp/priv"
{ printf '{"%s": "' "$version"; base64 -w0 "$tmp/pk.der"; printf '"}\n'; } > "$tmp/pub"
fp="$(sha256sum "$tmp/pk.der" | cut -c1-16)"
printf '{"algorithm": "HPKE Base DHKEM(X25519,HKDF-SHA256)+HKDF-SHA256+AES-256-GCM", "current_version": %s, "created_at": "%s", "public_key_sha256_16": {"%s": "%s"}}\n' \
  "$version" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$version" "$fp" > "$tmp/meta"
rm -f "$tmp/sk.der" "$tmp/pk.der"
chmod 600 "$tmp/priv"; chmod 644 "$tmp/pub" "$tmp/meta"

# 不覆盖：ln 在目标已存在时失败（原子）
ln "$tmp/priv" "$priv" || { echo "私钥文件已被并发创建，未覆盖" >&2; exit 1; }
ln "$tmp/pub" "$pub"
ln "$tmp/meta" "$meta" 2>/dev/null || true

# 容器以 uid $app_uid 运行，docker compose 的 file secret 是只读绑定挂载、不支持改属主（非 swarm），
# 所以把私钥属主改成容器用户（仍是 600，宿主机上只有 root 和该 uid 能读）。
if [ "$(id -u)" = 0 ]; then chown "$app_uid:$app_uid" "$priv"
elif sudo -n true 2>/dev/null; then sudo -n chown "$app_uid:$app_uid" "$priv"
else echo "警告：无法把私钥属主改成 $app_uid（无 sudo），ingest 读不到它；请让管理员执行 chown $app_uid:$app_uid $priv" >&2
fi
echo "已生成封装密钥 v$version：$dir（私钥 600 属主 $app_uid，公钥 sha256 前 16 位 $fp）。"
echo "提醒：立即把私钥单独备份到与数据库备份不同的位置；私钥丢失后已加密的证书无法解密。"
