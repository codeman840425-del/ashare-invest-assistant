#!/usr/bin/env bash
# 一键启动：deploy/scripts/up.sh
# - 没有 deploy/env/.env 时自动从 .env.example 生成
# - 非 systemd 主机上 Docker daemon 未运行时，自动调用 start-dockerd.sh
# - 默认叠加 docker-compose.dev.yml（麦蕊回放模式），等待全部服务 healthy 后返回
# - 默认带 --build：后端镜像与前端网关镜像都重建（有缓存时很快），避免 live 模式跑旧镜像；
#   AIA_UP_BUILD=0 可跳过构建
# - 启动顺序：postgres/redis → migrate（alembic upgrade head）→ timescale-apply（策略）→ 应用服务 → nginx；
#   一次性服务失败时 --wait 返回非 0，用 `compose.sh logs migrate timescale-apply` 看原因
# - 项目名/卷名优先级见 compose.sh 头部注释：只认 deploy/env/.env（缺省按工作树目录名派生），
#   shell 里导出的 COMPOSE_PROJECT_NAME 不生效（T-O03）；启动前先打印解析结果
# - 带 0017 迁移且 postgres 已运行时，先跑 db-precheck-0017.sh；有违规行就停止（review-6670b10）
# - 证书封装密钥缺失时：全新部署自动生成（seal-keygen.sh，不覆盖已有文件）；已有数据卷则停止并提示从备份恢复（T-O09）
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! docker info >/dev/null 2>&1 && ! sudo -n docker info >/dev/null 2>&1; then
  if command -v dockerd >/dev/null 2>&1 && [ "$(cat /proc/1/comm 2>/dev/null)" != "systemd" ]; then
    "$HERE/start-dockerd.sh"
  fi
fi

"$HERE/compose.sh" --resolve

# 证书封装密钥（T-O09）：compose 的 secret 文件必须存在。
# - 全新部署（本卷前缀的 pgdata 卷还不存在）：自动调用 seal-keygen.sh 生成（已有文件绝不覆盖）。
# - 已有数据卷但缺私钥：停止。库里可能已有用旧私钥加密的证书，换新密钥会让它们永远解不开；
#   先从私钥备份恢复（deploy/runbooks/data-licence-seal-keys.md），确认库里没有证书时才手动运行 seal-keygen.sh。
secrets_dir="$("$HERE/compose.sh" --get AIA_SECRETS_DIR)"
volume_prefix="$("$HERE/compose.sh" --get AIA_VOLUME_PREFIX)"
if [ ! -e "$secrets_dir/data_licence_seal_private_keys" ] || [ ! -e "$secrets_dir/data_licence_seal_public_keys" ]; then
  if docker volume inspect "${volume_prefix}_pgdata" >/dev/null 2>&1 \
     || sudo -n docker volume inspect "${volume_prefix}_pgdata" >/dev/null 2>&1; then
    echo "缺少证书封装密钥（$secrets_dir），但数据卷 ${volume_prefix}_pgdata 已存在：不自动生成新密钥。" >&2
    echo "请先从私钥备份恢复；确认库里没有已加密的证书后，才可手动运行 deploy/scripts/seal-keygen.sh。" >&2
    exit 1
  fi
  "$HERE/seal-keygen.sh"
fi

# 迁移 0017 预检查（review-6670b10）：postgres 已在运行且仓库带 0017 迁移时，升级前先只读查违规行；查到就停，不启动 migrate。
# postgres 没在运行（首次部署或已停机）时，由 0017 迁移自身的预检查兜底（同一条 SQL，报错退出、不改数据）。
if compgen -G "$HERE/../../src/backend/migrations/versions/0017_*.py" >/dev/null \
   && [ -n "$("$HERE/compose.sh" ps -q postgres 2>/dev/null || true)" ]; then
  "$HERE/db-precheck-0017.sh" || { echo "0017 预检查未通过：不执行 up（不会跑迁移）。见 deploy/runbooks/database.md §7。" >&2; exit 1; }
fi

build_flag=()
[ "${AIA_UP_BUILD:-1}" = "1" ] && build_flag=(--build)

"$HERE/compose.sh" up -d "${build_flag[@]}" --wait --wait-timeout "${UP_WAIT_TIMEOUT:-300}" "$@"
"$HERE/compose.sh" ps -a
