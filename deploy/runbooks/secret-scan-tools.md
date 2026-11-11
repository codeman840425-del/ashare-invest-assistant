# 推送前双扫与 gitleaks 固定工具（O-04）

适用：本机 Windows/WSL 开发与获准任务分支推送。2026-11-11 北京时间。本文固定安装与使用口径，不修改 CI/扫描器/规则，不授权推送 main、部署或放宽扫描。

## 1. 固定版本、来源与仓库外路径

固定 **gitleaks 8.30.1**，与 `.github/workflows/secret-scan.yml` 的版本和 Linux x64 摘要一致。不使用 latest、镜像站重打包或未校验的旧副本。

官方发布页：<https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1>。下列 SHA256 对应**压缩包**，不是解压后的可执行文件；Windows/Linux 资产不能互换摘要。

| 平台 | 官方资产名 | 固定 SHA256 |
|---|---|---|
| Windows x64 | gitleaks_8.30.1_windows_x64.zip | `d29144deff3a68aa93ced33dddf84b7fdc26070add4aa0f4513094c8332afc4e` |
| Linux x64 | gitleaks_8.30.1_linux_x64.tar.gz | `551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb` |

官方固定下载 URL：

- <https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_windows_x64.zip>
- <https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz>

全队复用路径（不写入 PATH，不入 git）：

- Windows：`F:\workspace\team\tools\gitleaks\8.30.1\windows-x64\gitleaks.exe`。
- WSL 原生 Linux：`/mnt/f/workspace/team/tools/gitleaks/8.30.1/linux-x64/gitleaks`，**须按下文另行安装对应 Linux 包**，不能把 Windows exe 改名为 Linux 程序。
- `F:\workspace\team` 与交接中 `/workspace/team` 是逻辑等位；本机 WSL 对应物理路径为 `/mnt/f/workspace/team`，不能据逻辑别名猜测一个不存在的目录。

O-04 已把现有已核验 Windows ZIP 解出到上述固定 Windows 路径，版本及与 O-03 二进制一致性已复核；本单未安装 Linux 包。旧临时 `gitleaks-8.30.1-O03` 路径不再作为调用约定，但本单不擅自删除其他会话可能引用的文件。

仅运维维护工具目录；各角色复用现有二进制，不并发覆盖安装。存在目录先核版本/来源，不使用 `Expand-Archive -Force` 或直接覆盖使用中的工具；需要更换版本另开目录并重新审核版本与摘要。

## 2. Windows 首次安装（已有固定工具无需重复下载）

在仓库外执行；`curl.exe` 明确调用本机 curl，避免旧 PowerShell 的 curl 别名。以下只安装工具，不执行仓库或公网业务调用。

```powershell
$toolDir = 'F:\workspace\team\tools\gitleaks\8.30.1\windows-x64'
$zipPath = 'F:\workspace\team\tools\gitleaks\8.30.1\gitleaks_8.30.1_windows_x64.zip'
$expected = 'd29144deff3a68aa93ced33dddf84b7fdc26070add4aa0f4513094c8332afc4e'
if (Test-Path -LiteralPath $toolDir) { throw '目录已存在：先核验并复用，不覆盖' }
New-Item -ItemType Directory -Path (Split-Path $zipPath) -Force | Out-Null
curl.exe --location --fail --silent --show-error --max-time 900 --continue-at - --output $zipPath 'https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_windows_x64.zip'
if ($LASTEXITCODE -ne 0) { throw '下载未完成；不解压、不执行' }
$actual = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $expected) { throw '官方资产摘要不符；停止，不执行' }
New-Item -ItemType Directory -Path $toolDir | Out-Null
Expand-Archive -LiteralPath $zipPath -DestinationPath $toolDir
$gitleaks = Join-Path $toolDir 'gitleaks.exe'
$version = & $gitleaks version
if ($LASTEXITCODE -ne 0 -or $version.Trim() -ne '8.30.1') { throw '工具版本不符' }
```

下载超时留下的部分 ZIP 可按同一 URL 续传；只有完整包退出 0 且固定摘要匹配后才解压。摘要错配不继续、不自动接受新摘要，报编排者核来源；不要把新下载的 checksums 文件与二进制同时被替换时的「自洽」当成固定摘要验证。

若需复核已有 exe：先对存档 ZIP 比对上表固定摘要，再解到新的仓库外核验目录，比较两份 exe 的 `Get-FileHash`。`version` 只核版本号，不独立证明来源。不要输出 Docker 认证配置、实际环境变量全集或任何证书来诊断安装失败。

## 3. WSL 原生安装（可选，单独校验 Linux 资产）

```bash
set -euo pipefail
base=/mnt/f/workspace/team/tools/gitleaks/8.30.1
tool_dir="$base/linux-x64"
archive="$base/gitleaks_8.30.1_linux_x64.tar.gz"
[ ! -e "$tool_dir" ] || { echo '已有目录，先核验并复用，不覆盖' >&2; exit 1; }
mkdir -p "$base"
curl -fLsS --max-time 900 -C - -o "$archive" 'https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz'
printf '%s  %s\n' '551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb' "$archive" | sha256sum -c -
mkdir "$tool_dir"
tar -xzf "$archive" -C "$tool_dir" gitleaks
chmod u+x "$tool_dir/gitleaks"
[ "$("$tool_dir/gitleaks" version)" = '8.30.1' ]
```

Linux 版本依赖本机可执行挂载与 Git；若该挂载禁止执行，停止并报编排者另定仓库外原生路径，不改挂载权限、不改用 Windows exe 混跑。无需 sudo、服务注册或 Docker socket。

## 4. 提交前：只扫本单文件和本人暂存内容

在**自己的 worktree 根**运行，先确认分支/索引归属。以下文件列表替换成本次真实路径，不扫他人 WIP，不擅自 stash 或重新暂存其他人的文件。

```powershell
$gitleaks = 'F:\workspace\team\tools\gitleaks\8.30.1\windows-x64\gitleaks.exe'
git branch --show-current
if ($LASTEXITCODE -ne 0) { throw '无法确认分支' }
# 先用 files 模式扫描本单已改文件（此行的占位符必须替换）。
uv run --no-project --with pyyaml==6.0.3 python scripts/ci/secret_scan.py files '<changed-file-1>' '<changed-file-2>'
if ($LASTEXITCODE -ne 0) { throw 'secret_scan 未通过' }
git diff --check
if ($LASTEXITCODE -ne 0) { throw 'diff 检查失败' }
# 仅按本单 pathspec 暂存后，人工核对下面的名单。
git diff --cached --name-only
& $gitleaks protect --staged --redact=100 --no-banner --config .gitleaks.toml --ignore-gitleaks-allow
if ($LASTEXITCODE -ne 0) { throw 'gitleaks staged 未通过' }
git diff --cached --check
if ($LASTEXITCODE -ne 0) { throw '暂存 diff 检查失败' }
```

提交时只 pathspec 提交本人文件；暂存区含他人内容时，不把整个 index 当本单合格证据。先分清归属，可用本单独立 worktree，不能通过清理他人索引来获得「干净」。

## 5. 推送前：冻结完整提交范围并双扫

- 首推新任务分支：以当次批准的 main 基线 SHA 到候选 HEAD 为范围；后续追加推送：至少覆盖本次远端旧头到候选 HEAD。若有分支合并/依赖，范围必须覆盖实际将推出的全部提交。
- 使用已核实存在的完整 SHA；`fetch` 后再冻结。没有 fetch/无法证明远端状态就如实标未核实，不猜测基线。只看最终 diff、只跑 files/staged 不足以检出「先提交密钥、后删除」的中间历史。
- 不以仅提示报告生成成功的 `--exit-code 0` 判通过；下列 Windows 命令使用 gitleaks 默认阻断退出码。

```powershell
# 在本人 worktree 根；把占位基线替换为本次冻结的完整 SHA。
$base = '<approved-full-base-sha>'
$head = git rev-parse HEAD
if ($LASTEXITCODE -ne 0) { throw 'HEAD 无效' }
git cat-file -e "$base^{commit}"
if ($LASTEXITCODE -ne 0) { throw '基线不存在' }
$range = "$base..$head"
$gitleaks = 'F:\workspace\team\tools\gitleaks\8.30.1\windows-x64\gitleaks.exe'
uv run --no-project --with pyyaml==6.0.3 python scripts/ci/secret_scan.py range $range
if ($LASTEXITCODE -ne 0) { throw 'secret_scan range 未通过' }
# 与既有 range wrapper 相同，仅排除前端 dist 构建产物，不缩小源码扫描范围。
$logOpts = "$range -- . :(exclude,glob)src/frontend/**/dist/**"
& $gitleaks git . --redact=100 --no-banner --config .gitleaks.toml --ignore-gitleaks-allow "--log-opts=$logOpts"
if ($LASTEXITCODE -ne 0) { throw 'gitleaks range 未通过' }
if ((git rev-parse HEAD) -ne $head) { throw 'HEAD 已变化，重新冻结并双扫' }
# 两扫均通过且任务明确授权后，才按批准目标推送；本手册不自动推 main。
```

输出验收：secret_scan **0 阻断/0 告警**、gitleaks **0 命中**，且两者真实退出码均 0。secret_scan 告警即使退出 0，也应先核清并按裁定处理，不能只检查 `$LASTEXITCODE` 就宣称全零。网络问题、缺工具、解析失败、未知历史命中均不是通过；停止推送并向编排者报告，不改规则、缩范围或临时豁免。

若发生新的提交、合并或内容改动，旧扫描证据不能覆盖新候选，需重新冻结。历史误报只认 `.gitleaksignore` 中已裁定的精确指纹；不改写已共享历史、不强推、不自行扩大白名单。扫描通过也不替代当次推送授权或独立复核前置。

## 6. WSL/CI wrapper：报告检查器不可省

既有 `scripts/ci/gitleaks_run.sh` 固定 `--exit-code 0`，作用是生成 JSON；必须紧接 `gitleaks_report.py` 并检查其退出码，和 secret_scan 共同阻断。

```bash
set -euo pipefail
export GITLEAKS_BIN=/mnt/f/workspace/team/tools/gitleaks/8.30.1/linux-x64/gitleaks
# BASE/HEAD_SHA 必须已设置为当次核实的完整提交 SHA。
: "${BASE:?设置获准基线 SHA}" "${HEAD_SHA:?设置候选 SHA}"
range="$BASE..$HEAD_SHA"
# 受控本机临时报告；不入库、不上传，不写进可被清理的 worktree。
umask 077
report=$(mktemp /tmp/aia-gitleaks-report.XXXXXX.json)
trap 'rm -f -- "$report"' EXIT
bash scripts/ci/gitleaks_run.sh range "$range" "$report"
uv run --no-project --with pyyaml==6.0.3 python scripts/ci/gitleaks_report.py "$report"
uv run --no-project --with pyyaml==6.0.3 python scripts/ci/secret_scan.py range "$range"
```

wrapper 的原始 JSON 可能含匹配内容，只能放受控临时位置；不得 cat、提交、作为 artifact 上传或贴进群。共享报告仅记规则、路径、行号、数量与脱敏结论，不能复制真实值。命中或执行失败时 `set -euo pipefail` 会停止；不要 `|| true`、只看最后一条命令、吞 stderr 或用 `--exit-code 0` 直接放行。

history（`--all`）只在明确的全历史/收口检查范围下执行，仍需报告检查器；不在普通单据中擅自跑全库历史或覆盖率。CI 已有同版固定与双扫流程，本单只同步本机文档，不修改工作流。
