#!/usr/bin/env bash
# docker compose 包装：固定项目名、env 文件与叠加层。其余参数原样传给 docker compose。
#   deploy/scripts/compose.sh ps
#   deploy/scripts/compose.sh logs -f ingest
#   deploy/scripts/compose.sh down -v
# AIA_PROFILE=dev（默认，叠加 docker-compose.dev.yml = 麦蕊回放模式）| live（只用基础文件；生产/live 要求 SESSION_COOKIE_SECURE=true）
#   deploy/scripts/compose.sh --resolve   # 只打印解析出的 项目名 / 卷前缀 / 后端镜像 / 密钥目录 及来源，不调用 docker
#   deploy/scripts/compose.sh --get NAME  # 只输出一个解析结果（COMPOSE_PROJECT_NAME|AIA_VOLUME_PREFIX|AIA_BACKEND_IMAGE|AIA_SECRETS_DIR）
#
# 项目名与卷名的优先级（T-O03；多个工作树共用一个 compose 项目“aia”就是因为 shell 里导出的
# COMPOSE_PROJECT_NAME 盖过了 .env）：
#   COMPOSE_PROJECT_NAME：deploy/env/.env 的值 > 由工作树目录名派生的 aia-<目录名>；
#                         shell 里导出的 COMPOSE_PROJECT_NAME 一律不用（不一致时告警），并以 -p 显式传给 compose。
#   AIA_VOLUME_PREFIX   ：deploy/env/.env 的值 > 项目名；同样不认 shell。数据卷显式命名为 <前缀>_pgdata/_redisdata/_imports，
#                         改项目名时把前缀设成旧项目名即可沿用原有数据卷（不删卷、不迁数据）。
#   AIA_BACKEND_IMAGE   ：shell > .env > aia-backend:<项目名>（每个项目各自的镜像 tag，构建不会互相覆盖）。
#   AIA_SECRETS_DIR     ：deploy/env/.env 的值 > ${XDG_CONFIG_HOME:-~/.config}/aia/secrets/<卷前缀>（T-O09）；不认 shell。
#                         证书封装密钥（seal-keygen.sh 生成）放在仓库外，按数据卷前缀区分：密钥跟着它加密的数据走，
#                         同一份数据卷换项目名/工作树仍用同一把密钥。
#   其余变量按 docker compose 默认：shell 导出 > .env > compose 文件里的默认值。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="$ROOT/deploy/env/.env"
ENV_EXAMPLE="$ROOT/deploy/env/.env.example"
PROFILE="${AIA_PROFILE:-dev}"

if [ ! -f "$ENV_FILE" ]; then
  echo "未找到 deploy/env/.env，从 .env.example 生成（仅占位值，请按需修改）。" >&2
  cp "$ENV_EXAMPLE" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
fi

# 读 .env 里某个键的最后一个赋值（不 source，不展开；去掉首尾空白和成对引号）
env_get() {
  local v
  v="$(sed -n "s/^[[:space:]]*$1[[:space:]]*=//p" "$ENV_FILE" | tail -n 1)"
  v="${v#"${v%%[![:space:]]*}"}"; v="${v%"${v##*[![:space:]]}"}"
  case "$v" in \"*\") v="${v:1:${#v}-2}" ;; \'*\') v="${v:1:${#v}-2}" ;; esac
  printf '%s' "$v"
}
valid_name() { [[ "$1" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; }

shell_project="${COMPOSE_PROJECT_NAME-}"
shell_prefix="${AIA_VOLUME_PREFIX-}"
project="$(env_get COMPOSE_PROJECT_NAME)"; project_src="deploy/env/.env"
if [ -z "$project" ]; then
  base="$(basename "$ROOT" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9_-' '-')"
  project="aia-${base%-}"; project_src="工作树目录名派生"
fi
valid_name "$project" || { echo "COMPOSE_PROJECT_NAME=$project 不合法（只能小写字母/数字/-/_，字母或数字开头）" >&2; exit 2; }
prefix="$(env_get AIA_VOLUME_PREFIX)"; prefix_src="deploy/env/.env"
[ -n "$prefix" ] || { prefix="$project"; prefix_src="= 项目名"; }
valid_name "$prefix" || { echo "AIA_VOLUME_PREFIX=$prefix 不合法" >&2; exit 2; }
if [ -n "$shell_project" ] && [ "$shell_project" != "$project" ]; then
  echo "警告：忽略 shell 中导出的 COMPOSE_PROJECT_NAME=$shell_project，使用 $project（$project_src）。" >&2
fi
if [ -n "$shell_prefix" ] && [ "$shell_prefix" != "$prefix" ]; then
  echo "警告：忽略 shell 中导出的 AIA_VOLUME_PREFIX=$shell_prefix，使用 $prefix（$prefix_src）。" >&2
fi
export COMPOSE_PROJECT_NAME="$project" AIA_VOLUME_PREFIX="$prefix"
shell_secrets="${AIA_SECRETS_DIR-}"
secrets_dir="$(env_get AIA_SECRETS_DIR)"; secrets_src="deploy/env/.env"
if [ -z "$secrets_dir" ]; then
  secrets_dir="${XDG_CONFIG_HOME:-$HOME/.config}/aia/secrets/$prefix"; secrets_src="按卷前缀派生"
fi
case "$secrets_dir" in /*) ;; *) echo "AIA_SECRETS_DIR=$secrets_dir 必须是绝对路径" >&2; exit 2 ;; esac
case "$secrets_dir/" in "$ROOT"/*) echo "AIA_SECRETS_DIR 不能在仓库里（$secrets_dir）" >&2; exit 2 ;; esac
if [ -n "$shell_secrets" ] && [ "$shell_secrets" != "$secrets_dir" ]; then
  echo "警告：忽略 shell 中导出的 AIA_SECRETS_DIR=$shell_secrets，使用 $secrets_dir（$secrets_src）。" >&2
fi
export AIA_SECRETS_DIR="$secrets_dir"
image_src="shell"
if [ -z "${AIA_BACKEND_IMAGE-}" ]; then
  if [ -n "$(env_get AIA_BACKEND_IMAGE)" ]; then image_src="deploy/env/.env"; AIA_BACKEND_IMAGE="$(env_get AIA_BACKEND_IMAGE)"
  else image_src="项目名派生"; AIA_BACKEND_IMAGE="aia-backend:$project"; fi
  export AIA_BACKEND_IMAGE
fi

if [ "${1-}" = "--resolve" ]; then
  echo "compose 项目：$project（$project_src）；数据卷前缀：$prefix（$prefix_src）；后端镜像：$AIA_BACKEND_IMAGE（$image_src）；密钥目录：$secrets_dir（$secrets_src）；profile：$PROFILE"
  exit 0
fi
if [ "${1-}" = "--get" ]; then
  case "${2-}" in
    COMPOSE_PROJECT_NAME|AIA_VOLUME_PREFIX|AIA_BACKEND_IMAGE|AIA_SECRETS_DIR) printf '%s\n' "${!2}" ;;
    *) echo "--get 只支持 COMPOSE_PROJECT_NAME|AIA_VOLUME_PREFIX|AIA_BACKEND_IMAGE|AIA_SECRETS_DIR" >&2; exit 2 ;;
  esac
  exit 0
fi

# daemon 没起来（机器重启后）或 docker.sock ACL 丢失（dockerd 被别处重启）时，自动修复一次（T-O08）。
if ! docker info >/dev/null 2>&1 && [ "$(cat /proc/1/comm 2>/dev/null)" != "systemd" ] \
   && command -v dockerd >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
  "$ROOT/deploy/scripts/start-dockerd.sh" >&2 || true
fi

if docker info >/dev/null 2>&1; then
  DOCKER=(docker)
elif sudo -n docker info >/dev/null 2>&1; then
  DOCKER=(sudo -n docker)
else
  echo "无法访问 Docker daemon：请先运行 deploy/scripts/start-dockerd.sh，或把当前用户加入 docker 组。" >&2
  exit 1
fi

FILES=(-f "$ROOT/deploy/compose/docker-compose.yml")
case "$PROFILE" in
  dev)  FILES+=(-f "$ROOT/deploy/compose/docker-compose.dev.yml") ;;
  live) ;;
  *) echo "未知 AIA_PROFILE=$PROFILE（可选 dev|live）" >&2; exit 2 ;;
esac

exec "${DOCKER[@]}" compose -p "$project" --project-directory "$ROOT/deploy/compose" --env-file "$ENV_FILE" "${FILES[@]}" "$@"
