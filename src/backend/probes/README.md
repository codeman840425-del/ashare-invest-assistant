# 麦蕊（Mairui）A 股数据 API 能力验证探针（T003）

一次性前置验证脚本，不是正式实现。结论报告：`team/reports/T003-mairui-capability.md`。
本目录可以整体拷到另一台机器（Windows / Linux / macOS，Python 3.9+）上运行，**只依赖标准库 + requests**。

> 为什么要换机器：麦蕊规定**同一证书 60 秒内最多 2 个不同公网 IP**，超限返回 HTTP 429 `103:同一Licence证书在60秒内最多允许2个不同IP访问`。
> 开发 box 的出口经透明代理，**每条新 TCP 连接的公网出口 IP 都可能不同**（实测连续 6 次 6 个 IP），上次因此触发 103。
> 因此本脚本改为：单进程、单 `requests.Session`、每个主机只保持 1 条长连接、严格串行，并要求在**出口 IP 固定**的机器上运行。

---

## 1. 运行前提（全部满足再跑）

1. **出口公网 IP 固定**：不要开会轮换出口的代理/VPN/机场/“智能分流”；公司网络如有多出口负载均衡，请换家庭宽带或固定 IP 的服务器。
   不确定时可加 `--check-egress`（见第 6 节），它用与麦蕊调用同一个 Session 访问国内 IP 回显 `myip.ipip.net`（不访问麦蕊），出口不唯一就拒绝运行。
   **代理说明：脚本默认（`--no-env-proxy`）忽略 `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY`（含小写）环境变量和 Windows 系统代理（注册表），从本机直连。**
   因此即使本机设置了 `HTTP(S)_PROXY=http://127.0.0.1:10808` 这类分流代理，脚本也不会经过它，走的是本机直连出口（如电信固定 IP）。
   但**运行前必须确认代理软件没有开启 TUN / 全局模式 / 虚拟网卡接管**：那会在系统网络层接管流量，`trust_env=False` 管不到，出口可能变成海外或轮换 IP。
2. **交易日运行**：最好在交易日盘中（北京时间 9:30–11:30、13:00–15:00）或收盘后当天，实时类接口才有当日数据。
3. **证书没有在别处同时使用**：确认其他机器、同事、开发 box 上的程序都没有在用这张证书（否则多个 IP 叠加会触发 103）。
4. **距离上一次任何地方用该证书调用 ≥60 秒**（建议 ≥5 分钟）。脚本会读取 `results/` 下已有的调用日志，不足 60 秒时自动 `time.sleep` 等待，
   但它看不到别的机器上的调用，需要人工确认。

## 2. 需要拷贝的文件

把整个 `src/backend/probes/` 目录拷过去即可（`__pycache__/` 和 `results/dryrun/` 可以不拷）：

| 文件 | 作用 |
|---|---|
| `run_all.py` | **唯一入口**：同一进程内顺序跑全部探针；`--dry-run` 离线自检；`--check-egress` 出口自检 |
| `common.py` | 单会话长连接、串行间隔、证书脱敏、调用日志、429/103 熔断（STOP 文件）、冷却、按运行时间戳落盘（不覆盖） |
| `_helpers.py` | `probe()`：调用 + 摘要（行数/字段/时间范围/首末行）+ 可选样例 |
| `dryrun_mock.py` | dry-run 用的本地 `http.server` 伪造服务端 + 出网拦截 |
| `scan_licence.py` | 发送结果前的证书泄漏扫描（只输出命中/未命中） |
| `p01_realtime.py` … `p10_stability.py` | 10 项探针（p09 限流温和实测放在最后跑） |
| `results/` | 历史结果（含 `STOP` 熔断文件，见第 5 节）；新结果写入 `results/run-<时间戳>/` |
| `samples/` | 历史脱敏样例；新样例写入 `samples/run-<时间戳>/` |

> `results/STOP` 是故意保留的“保险栓”：拷过去后它会阻止真实调用，直到你按第 5 节确认前提并手动删除。

## 3. 安装 Python 与 requests

**Windows**
1. 从 <https://www.python.org/downloads/windows/> 安装 Python 3.9+（勾选 “Add python.exe to PATH”），或 `winget install Python.Python.3.12`。
2. PowerShell 中：
   ```powershell
   cd <拷贝后的 probes 目录>
   py -3 --version
   py -3 -m pip install --user requests
   ```
**Linux / macOS**
```bash
cd <拷贝后的 probes 目录>
python3 --version                    # 需 3.9+
python3 -m pip install --user requests   # 或使用 venv：python3 -m venv .venv && . .venv/bin/activate && pip install requests
```
（下文 Windows 命令用 `py -3`，Linux/macOS 用 `python3`。）

## 4. 设置证书环境变量（只对当前会话生效）

**规则：证书只放在当前终端会话的环境变量 `MAIRUI_LICENCE` 里。**
不要写进任何脚本、`.env`、`.bashrc`/`.zshrc`/PowerShell profile、系统/用户环境变量，也不要直接把证书敲在命令行里（会进命令历史）。
下面的写法都是“隐藏输入 → 只存在于当前窗口”，关闭窗口即失效。

**Windows PowerShell（推荐）**
```powershell
$sec = Read-Host "MAIRUI_LICENCE" -AsSecureString
$env:MAIRUI_LICENCE = [System.Net.NetworkCredential]::new('', $sec).Password
Remove-Variable sec
```
- `Read-Host -AsSecureString` 输入不回显，输入内容不会进 PSReadLine 历史（历史只记录上面这几行命令本身）。
- **不要**写成 `$env:MAIRUI_LICENCE = "真实证书"`：这一整行会被 PSReadLine 记进
  `%APPDATA%\Microsoft\Windows\PowerShell\PSReadLine\ConsoleHost_history.txt`。如果已经这样做过，请编辑该文件删掉那一行。
- **不要**用 `[Environment]::SetEnvironmentVariable(..., 'User'/'Machine')` 或 `setx`，那会永久写入注册表。
- `$env:` 赋值只影响当前 PowerShell 进程及其子进程，新开窗口需要重新输入。
- 用完清除：`Remove-Item Env:MAIRUI_LICENCE`

**Windows cmd**
```bat
set /p MAIRUI_LICENCE=请输入证书: 
```
- `set /p` 的输入会**明文回显在屏幕上**（不会进 doskey 命令历史），注意屏幕共享/录屏；能用 PowerShell 就用 PowerShell。
- **不要**用 `set MAIRUI_LICENCE=真实证书`（会进命令历史）或 `setx`（永久写入）。
- 用完清除：`set MAIRUI_LICENCE=`

**Linux / macOS（bash / zsh）**
```bash
read -rs MAIRUI_LICENCE && export MAIRUI_LICENCE   # 输入不回显，回车结束
```
- **不要** `export MAIRUI_LICENCE=真实证书`（会进 `~/.bash_history` / `~/.zsh_history`），也不要 `MAIRUI_LICENCE=xxx python3 run_all.py`。
- 不要 `set -x`、`env`、`printenv` 把它打出来。
- 用完清除：`unset MAIRUI_LICENCE`

## 5. 先 dry-run，再删 STOP

**第一步：离线自检（不会访问麦蕊，不使用真实证书，不出网，不碰 `results/STOP`）**
```powershell
py -3 run_all.py --dry-run          # Linux/macOS: python3 run_all.py --dry-run
```
它会在本机 `127.0.0.1` 启动两个伪造服务端（模拟 api / pro 两个主机），用假证书把全部探针跑一遍，然后逐项检查：
每个主机只建立 1 条 TCP 连接、服务端同时处理中的请求峰值 = 1（串行）、客户端调用数 = 服务端请求数、
输出文件与控制台不含证书、遇到 429/103 立即熔断且熔断后不再发任何请求、同名结果不覆盖、每次运行独立目录、
无任何非回环网络访问（DNS 解析和 connect 都被拦截记录）、真实 `results/STOP` 未被改动；
另外模拟 `myip.ipip.net`（IP 一致放行、不一致拒绝），并把假的 `HTTP(S)_PROXY`/`ALL_PROXY` 指向本地记录端口，
确认默认模式下代理端口收到 0 个请求、`--use-env-proxy` 时请求改走代理。
最后应看到 **“全部通过”**，退出码 0。dry-run 输出在 `results/dryrun/run-*-dryrun*/`（可删除，不需要回传）。
（Windows 防火墙一般不会对只绑定 127.0.0.1 的程序弹窗；如弹窗，选择“取消/不允许”也不影响本地自检。）

**第二步：确认第 1 节前提全部满足后，手动删除 STOP**
```powershell
Remove-Item results\STOP            # cmd: del results\STOP     Linux/macOS: rm results/STOP
```

## 6. 真实运行

```powershell
py -3 run_all.py                    # Linux/macOS: python3 run_all.py
```
可选参数：
- `--check-egress`（默认关闭）：用与麦蕊调用**同一个 Session、同一代理设置**访问 `https://myip.ipip.net` 共 3 次（`--egress-rounds` 可调），
  每次带 `Connection: close` 强制新连接以暴露“按连接换出口”的情况；从返回文本中提取 IP，任一失败或不一致就拒绝运行（退出码 3）。
  它会额外占用一个主机连接（myip.ipip.net），不计入麦蕊的单连接统计。若 https 不通可用 `--egress-url http://myip.ipip.net`。
- `--no-env-proxy`（**默认开启**）/ `--use-env-proxy`：默认 `trust_env=False` 且 `proxies` 显式为空，不读环境变量代理和系统代理；
  `--use-env-proxy` 则恢复 requests 默认行为（读环境变量；Windows 上未设环境变量时会读注册表系统代理）。启动时会打印一行“代理模式”，并写入 `summary.json`。
  注意：`trust_env=False` 同时会让 requests **不读 `~/.netrc`/`_netrc`**（本脚本不需要）和 **不读 `REQUESTS_CA_BUNDLE`/`CURL_CA_BUNDLE`**，
  改用 certifi 自带 CA。若公司网络做了 HTTPS 解密、必须用自定义 CA，会出现 `SSLError`；此时请换不解密 HTTPS 的网络，而不是关闭证书校验。
- `--skip-pro-host`：跳过 p02 中 2 次 `pro.mairuiapi.com` 调用，全程只连 `api.mairuiapi.com` 一个主机。
- `p01 p02 ...`：只跑指定前缀的探针。`--min-interval 0.5`：加大串行间隔（默认 0.25 秒）。
- 环境变量 `PROBE_STABILITY_N`：p10 每个接口重复次数（默认 12）。

**预期调用量与时长**：全部探针约 **222 次**（`api.mairuiapi.com` 220 次 + `pro.mairuiapi.com` 2 次；
其中 p10 稳定性 60 次、p09 限流实测 31 次），单次 0.25–1.3 秒（全市场接口约 1.9 MB），加上 0.25 秒间隔，**约 3–6 分钟**。
连接：每个主机 1 条长连接（共 1–2 条，`--skip-pro-host` 时 1 条），全部串行，无并发、无子进程。

**输出位置**（每次运行新建目录，永不覆盖旧结果）：
- `results/run-<YYYYmmdd-HHMMSS>/calls.jsonl`：每次调用的脱敏 URL（证书为 `***`）、状态、耗时、字节、当前连接数、错误摘要
- `results/run-<…>/p01_realtime.json` … `p09_ratelimit.json`：各探针结果；`summary.json`：调用总数、各主机累计 TCP 连接数
- `samples/run-<…>/`：脱敏、截断后的接口样例
- 如果 `summary.json` 或控制台提示某主机连接数 > 1（服务端关闭了空闲连接后重连），出口 IP 固定时不影响，但请在回传时说明。

## 7. 遇到 103（或 429 / 101）怎么办

脚本检测到 HTTP 429、非“数据缺失”类 503、或响应为 101/103 时会：立即停止、写入 `results/STOP`（内容为脱敏后的原始报错）、后续所有调用直接拒绝。此时：
1. **不要重试，不要删除 STOP，不要换机器马上再跑。**
2. 至少等待 60 秒（建议 10 分钟以上）再做任何调用；排查是否有其他机器/同事在用证书、出口 IP 是否在变（代理/VPN/多出口）。
3. 把当前 `results/` 和 `samples/` 按第 8 节原样回传，并附上控制台最后几十行（已脱敏）。是否再跑由协调人决定。

## 8. 回传结果

1. **先做证书扫描**（证书仍在当前会话环境变量中时）：
   ```powershell
   py -3 scan_licence.py               # Linux/macOS: python3 scan_licence.py
   ```
   只输出“未命中”或命中的文件路径，不会打印证书。**必须是“未命中”才能发送**；命中则删除/修复对应文件后重扫。
2. 打包 `results/`（可去掉 `results/dryrun/`）和 `samples/`，例如：
   - PowerShell：`Compress-Archive -Path results, samples -DestinationPath T003-results.zip`
   - Linux/macOS：`zip -r T003-results.zip results samples -x 'results/dryrun/*'`
3. 发送前再对压缩包扫一次：`py -3 scan_licence.py T003-results.zip`（zip 有压缩，此项仅作补充，以第 1 步为准）。
4. 清除证书：PowerShell `Remove-Item Env:MAIRUI_LICENCE` / cmd `set MAIRUI_LICENCE=` / bash `unset MAIRUI_LICENCE`。

## 安全与限流约束（脚本内已强制）
- 证书只从 `os.environ["MAIRUI_LICENCE"]` 读取；控制台、日志、样例、结果中的 URL 一律替换成 `***`，写盘前断言不含证书。dry-run 用假证书。
- 严格串行（in-flight 计数断言 + 连接池 `pool_maxsize=1, pool_block=True`），调用间隔与冷却都用 `time.sleep`；不做压测，总量约 222 次。
- 不使用 subprocess / fork / signal；路径全部基于脚本所在目录（pathlib）；文件读写显式 UTF-8；控制台输出 `reconfigure(encoding='utf-8', errors='replace')`，GBK 终端不会因中文崩溃（个别字符可能显示为乱码/问号，不影响结果文件）。
- 结果文件以独占方式创建（同名自动加 `.2`、`.3` 后缀），每次运行独立目录，绝不覆盖旧结果。
