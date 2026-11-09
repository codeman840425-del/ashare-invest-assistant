#!/usr/bin/env bash
# T-O40 compose.sh 运行环境守卫定点自检（纯合成环境：不连真实 docker/栈，不写仓库）。
# 用法：bash deploy/scripts/compose-guard-selftest.sh
# 覆盖三种调用方式：
#   1) 模拟 Windows Git Bash（uname=MINGW…）→ 守卫报错退出，且不写任何文件；
#   2) 模拟 WSL/Linux（uname=Linux）→ --resolve 正常通过，且不写文件；
#   3) 模拟密钥目录与运行栈来源不一致（假 docker 返回别的 app_master_key 来源）
#      → 守卫报错退出，且不生成任何分角色口令文件。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$HERE/compose.sh"
[ -f "$SRC" ] || { echo "找不到 compose.sh：$SRC" >&2; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

ROOT="$TMP/repo"
mkdir -p "$ROOT/deploy/scripts" "$ROOT/deploy/env" "$ROOT/deploy/compose"
cp "$SRC" "$ROOT/deploy/scripts/compose.sh"
: > "$ROOT/deploy/env/.env"

fail() { echo "FAIL: $*" >&2; exit 1; }
ok() { echo "ok - $*"; }

# 假 uname / docker 注入到 PATH 最前面，模拟不同运行环境。
mkdir -p "$TMP/bin-win" "$TMP/bin-linux" "$TMP/bin-dockermock"
printf '#!/bin/sh\necho "MINGW64_NT-10.0-19045"\n' > "$TMP/bin-win/uname"
printf '#!/bin/sh\necho "Linux"\n' > "$TMP/bin-linux/uname"
printf '#!/bin/sh\ncase "$1" in info) exit 0 ;; inspect) echo "${FAKE_KEY_SOURCE:-/nonexistent/app_master_key}" ;; *) exit 0 ;; esac\n' > "$TMP/bin-dockermock/docker"
chmod +x "$TMP/bin-win/uname" "$TMP/bin-linux/uname" "$TMP/bin-dockermock/docker"

# 用例1：Windows Git Bash 调用 → 拒绝且不写文件
H="$TMP/home-win"; mkdir -p "$H"
if HOME="$H" PATH="$TMP/bin-win:$PATH" bash "$ROOT/deploy/scripts/compose.sh" --resolve >/dev/null 2>&1; then
  fail "用例1：Windows 侧调用应被拒绝"
fi
[ ! -e "$H/.config/aia" ] || fail "用例1：Windows 侧调用写了文件"
ok "用例1 Windows 侧调用被拒绝且未写文件"

# 用例2：WSL/Linux 调用 --resolve → 通过且不写文件
H="$TMP/home-linux"; mkdir -p "$H"
HOME="$H" PATH="$TMP/bin-linux:$PATH" bash "$ROOT/deploy/scripts/compose.sh" --resolve >/dev/null 2>&1 \
  || fail "用例2：Linux 侧 --resolve 应通过"
[ ! -e "$H/.config/aia" ] || fail "用例2：--resolve 不应写文件"
ok "用例2 Linux 侧 --resolve 通过且未写文件"

# 用例3：Linux 侧但密钥目录与运行栈来源不一致 → 拒绝且不生成口令
H="$TMP/home-mismatch"; mkdir -p "$H"
if HOME="$H" PATH="$TMP/bin-linux:$TMP/bin-dockermock:$PATH" FAKE_KEY_SOURCE="/somewhere/else/app_master_key" \
     bash "$ROOT/deploy/scripts/compose.sh" ps >/dev/null 2>&1; then
  fail "用例3：密钥目录不一致应被拒绝"
fi
[ ! -e "$H/.config/aia" ] || fail "用例3：不一致时写了文件"
ok "用例3 密钥目录不一致被拒绝且未写文件"

echo "compose guard selftest: 3 passed"
