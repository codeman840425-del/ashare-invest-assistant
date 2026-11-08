"""麦蕊（Mairui）API 探测公共模块：单长连接会话、串行调用、脱敏、计时、熔断、结果落盘。

安全规则：
- 证书只从环境变量 MAIRUI_LICENCE 读取，绝不打印/写入文件；dry-run 模式使用假证书，真实证书不会被读取发送。
- 所有对外输出（控制台、日志、样例、结果）中的 URL 与响应文本都会把证书替换为 ***；写盘前断言不含证书。
- 一个进程只建一个 requests.Session，连接池每个主机最多 1 条连接（pool_maxsize=1, pool_block=True），
  严格串行（in-flight 计数断言），调用间隔与冷却全部用 time.sleep 实现。
- 遇到 HTTP 429、非数据类 503、响应体/错误码 101/103 立即写 STOP 并抛 LimitHit；STOP 存在时拒绝任何调用。
- 每次运行写入 results/run-<时间戳>/ 与 samples/run-<时间戳>/（dry-run 在 results/dryrun/ 下），文件以独占方式创建，绝不覆盖旧结果。
跨平台：只用标准库 + requests；路径全部基于本文件所在目录（pathlib）；文件读写显式 utf-8；不使用 fork/signal/POSIX 专有模块。
"""
from __future__ import annotations

import json
import os
import re
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlencode, urlsplit

import requests
from requests.adapters import HTTPAdapter

# Direct `python run_all.py` also imports the same packaged standard-library gate.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.ingest.shared_gate import SharedGate, limit_code

REAL_BASE = "https://api.mairuiapi.com"
REAL_PRO_BASE = "https://pro.mairuiapi.com"
HERE = Path(__file__).resolve().parent
RESULTS_ROOT = HERE / "results"
SAMPLES_ROOT = HERE / "samples"
STOP_FILE = RESULTS_ROOT / "STOP"          # 真实运行的全局熔断文件（跨运行保留，需人工删除）
LEGACY_CALL_LOG = RESULTS_ROOT / "calls.jsonl"
DRYRUN_ROOT = RESULTS_ROOT / "dryrun"
COOLDOWN_SECONDS = 60                       # 麦蕊：同一证书 60 秒内最多 2 个 IP
TIMEOUT = 20
# dry-run 专用的虚构证书（不是真实值）。分段拼接，避免误中 gitleaks S1-mairui-licence-assign；
# CI 用 --ignore-gitleaks-allow，行内 allow 不生效，而允许清单在 probes/ 之外。值不变。
DRY_RUN_LICENCE = "-".join(("DRYRUN", "FAKE", "LICENCE", "0000", "000000000000"))


class LimitHit(RuntimeError):
    """触发限流/IP 超限/配额超限，必须停止。"""


def setup_console() -> None:
    """Windows GBK 控制台下输出中文/特殊字符不崩溃。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # Python 3.7+
        except (AttributeError, ValueError):
            pass


def now_iso() -> str:
    # 不用 time.strftime('%z')：Windows 上可能输出本地化的时区名称（GBK 乱码）
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_new(path: Path, text: str) -> Path:
    """以独占方式创建文件（mode='x'）；同名已存在时自动加序号，绝不覆盖。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    stem, suffix, i = path.stem, path.suffix, 1
    while True:
        try:
            with path.open("x", encoding="utf-8", newline="\n") as f:
                f.write(text)
            return path
        except FileExistsError:
            i += 1
            path = path.with_name(f"{stem}.{i}{suffix}")


# --------------------------------------------------------------------------- 运行上下文
@dataclass
class RunCtx:
    dry_run: bool
    base: str
    pro_base: str
    run_id: str
    run_dir: Path
    samples_dir: Path
    stop_file: Path
    call_log: Path
    min_interval: float
    skip_pro_host: bool = False
    no_env_proxy: bool = True
    proxy_mode: str = ""
    egress_url: str = ""
    egress: Optional[dict] = None
    session: Optional[requests.Session] = None
    shared_gate: Any = None
    last_call: float = 0.0
    inflight: int = 0
    n_calls: int = 0
    max_conn_per_host: dict = field(default_factory=dict)
    kept: dict = field(default_factory=dict)      # 本次运行内保留的完整响应（供后续探针复用，避免重复调用）


_ctx: Optional[RunCtx] = None


PROXY_ENV_NAMES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


def make_session(no_env_proxy: bool = True) -> requests.Session:
    """no_env_proxy=True（默认）：trust_env=False 且 proxies 显式为空 → 不读 HTTP(S)_PROXY/ALL_PROXY（含小写）、
    不读 Windows 注册表系统代理、不读 .netrc、不读 REQUESTS_CA_BUNDLE/CURL_CA_BUNDLE（改用 certifi 自带 CA）。"""
    s = requests.Session()
    if no_env_proxy:
        s.trust_env = False
        s.proxies.clear()
    else:
        s.trust_env = True
    s.headers["User-Agent"] = "ashare-invest-assistant-probe/0.2"
    s.headers["Connection"] = "keep-alive"
    # 每个主机最多 1 条连接；pool_connections=2 以同时容纳 api 与 pro 两个主机，避免池被逐出导致重连
    # pool_connections=3：api、pro、IP 回显三个主机各一个池
    adapter = HTTPAdapter(pool_connections=3, pool_maxsize=1, pool_block=True, max_retries=0)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


def _new_run_dir(root: Path, tag: str) -> tuple:
    base_id = "run-" + datetime.now().strftime("%Y%m%d-%H%M%S") + (f"-{tag}" if tag else "")
    run_id, i = base_id, 1
    while True:
        d = root / run_id
        try:
            d.mkdir(parents=True, exist_ok=False)
            return run_id, d
        except FileExistsError:
            i += 1
            run_id = f"{base_id}-{i}"


def init_run(*, dry_run: bool = False, base: str | None = None, pro_base: str | None = None,
             min_interval: float | None = None, skip_pro_host: bool = False, tag: str = "",
             no_env_proxy: bool = True, egress_url: str | None = None) -> RunCtx:
    global _ctx
    if not dry_run and not os.environ.get("MAIRUI_LICENCE"):
        raise SystemExit("MAIRUI_LICENCE 未设置（只允许通过环境变量提供证书）")
    # dry-run 输出隔离在 results/dryrun/ 下，不触碰真实 STOP，也不计入冷却判断
    run_id, run_dir = _new_run_dir(DRYRUN_ROOT if dry_run else RESULTS_ROOT, tag or ("dryrun" if dry_run else ""))
    if min_interval is None:
        min_interval = float(os.environ.get("PROBE_MIN_INTERVAL", "0.25"))
    _ctx = RunCtx(
        dry_run=dry_run,
        base=(base or REAL_BASE).rstrip("/"),
        pro_base=(pro_base or REAL_PRO_BASE).rstrip("/"),
        run_id=run_id, run_dir=run_dir,
        samples_dir=(run_dir / "samples") if dry_run else (SAMPLES_ROOT / run_id),
        stop_file=(run_dir / "STOP") if dry_run else STOP_FILE,
        call_log=run_dir / "calls.jsonl",
        min_interval=min_interval, skip_pro_host=skip_pro_host,
        no_env_proxy=no_env_proxy,
        proxy_mode=proxy_mode_desc(no_env_proxy),
        egress_url=egress_url or EGRESS_URL,
        session=make_session(no_env_proxy=no_env_proxy),
    )
    if not dry_run:
        _ctx.shared_gate = SharedGate.from_environment(None, "probe_tb05")
        if STOP_FILE.exists():
            _ctx.shared_gate.stop.touch(exist_ok=True)
        _ctx.shared_gate.acquire()
        _ctx.stop_file = _ctx.shared_gate.stop
    print(f"代理模式：{_ctx.proxy_mode}")
    if dry_run:
        for b in (_ctx.base, _ctx.pro_base):
            if urlsplit(b).hostname not in ("127.0.0.1", "localhost", "::1"):
                raise SystemExit("dry-run 只允许本机回环地址")
    return _ctx


def ctx() -> RunCtx:
    if _ctx is None:
        raise RuntimeError("请先调用 common.init_run()（推荐通过 run_all.py 运行）")
    return _ctx


def close_run() -> dict:
    c = ctx()
    summary = {"run_id": c.run_id, "dry_run": c.dry_run, "proxy_mode": c.proxy_mode, "egress_check": c.egress,
               "calls": c.n_calls,
               "connections_per_host": connection_stats(), "max_connections_seen": c.max_conn_per_host,
               "stop_file_exists": c.stop_file.exists(), "finished_at": now_iso()}
    if c.session is not None:
        c.session.close()
    if c.shared_gate is not None:
        c.shared_gate.release()
    write_new(c.run_dir / "summary.json", _safe_json(summary))
    return summary


# --------------------------------------------------------------------------- 证书与脱敏
def _licence() -> str:
    c = ctx()
    if c.dry_run:
        return DRY_RUN_LICENCE
    lic = os.environ.get("MAIRUI_LICENCE", "")
    if not lic:
        raise SystemExit("MAIRUI_LICENCE 未设置")
    return lic


def redact(text: Any) -> Any:
    if not isinstance(text, str):
        return text
    for lic in (os.environ.get("MAIRUI_LICENCE", ""), DRY_RUN_LICENCE):
        if lic:
            text = text.replace(lic, "***")
    return text


def _safe_json(obj: Any) -> str:
    out = json.dumps(obj, ensure_ascii=False, indent=1, default=str)
    lic = os.environ.get("MAIRUI_LICENCE", "")
    if (lic and lic in out) or DRY_RUN_LICENCE in out:
        raise AssertionError("输出含证书，拒绝写入")
    return out


# --------------------------------------------------------------------------- 连接统计
def connection_stats() -> dict:
    """读取 urllib3 连接池计数：每个主机累计新建的 TCP 连接数与请求数。"""
    out = {}
    s = ctx().session
    if s is None:
        return out
    seen = set()
    for adapter in s.adapters.values():
        if id(adapter) in seen:
            continue
        seen.add(id(adapter))
        pm = adapter.poolmanager
        for key in list(pm.pools.keys()):
            pool = pm.pools.get(key)
            if pool is None:
                continue
            out[f"{pool.scheme}://{pool.host}:{pool.port}"] = {
                "num_connections": getattr(pool, "num_connections", None),
                "num_requests": getattr(pool, "num_requests", None)}
    return out


# --------------------------------------------------------------------------- 响应
@dataclass
class Resp:
    name: str
    url_redacted: str
    status: Optional[int]
    ms: float
    nbytes: int
    data: Any = None
    text: str = ""
    error: Optional[str] = None
    headers: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == 200 and self.error is None and self.data is not None and not is_error_payload(self.data)


def is_error_payload(data: Any) -> bool:
    if isinstance(data, dict):
        keys = {str(k).lower() for k in data}
        if ("code" in keys and ("msg" in keys or "message" in keys or "detail" in keys)) or "error" in keys:
            code = data.get("code", data.get("Code"))
            if code in (None, 0, 200, "0", "200") and "error" not in keys:
                return False
            return True
        if "detail" in keys and len(keys) <= 2:
            return True
    return False


def build_url(path_tpl: str, pro: bool = False, **params) -> str:
    """path_tpl 中用 {licence} 占位，例如 '/hsstock/real/time/000001/{licence}'。"""
    c = ctx()
    url = (c.pro_base if pro else c.base) + path_tpl.replace("{licence}", _licence())
    if params:
        url += ("&" if "?" in url else "?") + urlencode(params)
    return url


def is_limit_response(status: Optional[int], text: str, data: Any) -> bool:
    """429 / 非数据类 503 / 响应体或 code 为 101、103 → 限流或配额/IP 超限。"""
    data_err_503 = status == 503 and any(k in text for k in ("redis history", "history miss", "cold fallback"))
    body = text.strip()
    code_hit = isinstance(data, dict) and str(data.get("code", "")) in ("101", "103")
    return (limit_code(status, data) is not None or limit_code(status, text) is not None
            or status == 429 or (status == 503 and not data_err_503) or code_hit
            or body.startswith("103") or body.startswith("101") or "最多允许2个不同IP" in body)


def call(name: str, path_tpl: str, *, pro: bool = False, method: str = "GET", json_body: Any = None,
         **params) -> Resp:
    c = ctx()
    if not c.dry_run:
        if c.shared_gate is None:
            raise LimitHit("shared gate required before live request")
        if STOP_FILE.exists():
            c.shared_gate.stop.touch(exist_ok=True)
    if c.stop_file.exists():
        raise LimitHit("STOP present; request refused")
    if c.inflight != 0:
        raise RuntimeError("检测到并发调用，探针必须串行")
    if pro and c.skip_pro_host:
        red = redact(build_url(path_tpl, pro=True, **params))
        print(f"[skip] {name} {red}（--skip-pro-host）")
        return Resp(name, red, None, 0.0, 0, None, "", "skipped: --skip-pro-host")
    url = build_url(path_tpl, pro=pro, **params)
    red = redact(url)
    wait = c.min_interval - (time.monotonic() - c.last_call)
    if wait > 0:
        time.sleep(wait)
    if c.stop_file.exists():
        raise LimitHit("STOP present before request")
    if c.shared_gate is not None:
        c.shared_gate.check()
        c.shared_gate.reserve()
    c.inflight += 1
    t0 = time.monotonic()
    status, text, err, hdr, redirected = None, "", None, {}, False
    try:
        r = c.session.request(method, url, json=json_body, timeout=TIMEOUT, allow_redirects=False)
        status, text, redirected = r.status_code, r.text, bool(r.history)
        hdr = {k: v for k, v in r.headers.items() if k.lower() in (
            "content-type", "x-ratelimit-limit", "x-ratelimit-remaining", "retry-after", "date", "last-modified",
            "x-cache", "server", "age", "connection", "keep-alive")}
    except requests.RequestException as e:  # 网络错误
        err = redact(f"{type(e).__name__}: {e}")
    finally:
        c.inflight -= 1
    ms = (time.monotonic() - t0) * 1000
    c.last_call = time.monotonic()
    c.n_calls += 1
    text = redact(text)
    data = None
    if text:
        try:
            data = json.loads(text)
        except ValueError:
            data = None
    shared_code = limit_code(status, data) or limit_code(status, text)
    if c.shared_gate is not None:
        if shared_code:
            c.shared_gate.trip(shared_code)
        if status is not None:
            c.shared_gate.complete()
    resp = Resp(name, red, status, round(ms, 1), len(text.encode("utf-8")), data, text, err, hdr)
    conns = connection_stats()
    for host, v in conns.items():
        n = v.get("num_connections") or 0
        c.max_conn_per_host[host] = max(c.max_conn_per_host.get(host, 0), n)
    entry = {"ts": now_iso(), "epoch": round(time.time(), 3), "name": name, "url": red, "method": method,
             "status": status, "ms": resp.ms, "bytes": resp.nbytes, "ok": resp.ok, "redirected": redirected,
             "conn": {h: v.get("num_connections") for h, v in conns.items()},
             "err_snippet": None if resp.ok else (text[:300] or err)}
    line = json.dumps(entry, ensure_ascii=False)
    lic = os.environ.get("MAIRUI_LICENCE", "")
    if (lic and lic in line) or DRY_RUN_LICENCE in line:  # 显式检查：python -O 下也生效（S101）
        raise AssertionError("调用日志含证书，拒绝写盘")
    c.call_log.parent.mkdir(parents=True, exist_ok=True)
    with c.call_log.open("a", encoding="utf-8", newline="\n") as f:  # 追加，不覆盖
        f.write(line + "\n")
    print(f"[{status}] {ms:7.1f}ms {resp.nbytes:>9}B {name} {red}"
          + ("" if resp.ok else f"  !! {(text[:160] or err)!r}"))
    if redirected:
        print("   注意：发生重定向，可能新建了到另一主机的连接")
    if is_limit_response(status, text, data):
        if shared_code and c.shared_gate is not None:
            raise LimitHit("shared licence limit latch set")
        msg = f"{now_iso()} source=probe_tb05 status={status} STOP"
        if not c.stop_file.exists():
            c.stop_file.parent.mkdir(parents=True, exist_ok=True)
            c.stop_file.write_text(msg + "\n", encoding="utf-8")
        raise LimitHit(f"触发限流/超限：status={status} body={text[:200]}")
    return resp


def keep(key: str, resp: "Resp") -> None:
    """把完整响应留在本次运行的内存里（只在当前进程、当前 RunCtx 内有效），供后续探针复用。"""
    ctx().kept[key] = (resp, datetime.now(timezone.utc).isoformat(timespec="seconds"))


def reuse(key: str) -> Optional[tuple]:
    """返回 (Resp, 取得时刻 UTC ISO) 或 None。"""
    return ctx().kept.get(key)


def assert_no_licence(text: str) -> None:
    lic = os.environ.get("MAIRUI_LICENCE", "")
    if (lic and lic in text) or DRY_RUN_LICENCE in text:
        raise AssertionError("输出含证书，拒绝写入")


def write_raw(rel: str, text: str) -> Path:
    """原样保存（已脱敏的）响应文本到当次运行目录；写盘前断言不含证书；独占创建、不覆盖。"""
    assert_no_licence(text)
    return write_new(ctx().run_dir / rel, text)


# --------------------------------------------------------------------------- 冷却与出口自检
def last_real_call_epoch() -> Optional[float]:
    """扫描历史 calls.jsonl（排除 dry-run 目录），返回最后一次真实调用的 epoch 秒。"""
    latest = None
    logs = [LEGACY_CALL_LOG] + list(RESULTS_ROOT.glob("run-*/calls.jsonl"))
    for p in logs:
        if not p.exists():
            continue
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                ep = d.get("epoch")
                if ep is None and d.get("ts"):
                    try:
                        ts = d["ts"]
                        ep = (datetime.fromisoformat(ts) if "T" in ts
                              else datetime.strptime(ts, "%Y-%m-%d %H:%M:%S%z")).timestamp()
                    except ValueError:
                        ep = None
                if ep and (latest is None or ep > latest):
                    latest = ep
    return latest


def cooldown_if_needed(seconds: int = COOLDOWN_SECONDS) -> float:
    last = last_real_call_epoch()
    if last is None:
        return 0.0
    remain = seconds + 1 - (time.time() - last)
    if remain > 0:
        print(f"距上次真实调用不足 {seconds} 秒，串行等待 {remain:.0f} 秒 ...")
        time.sleep(remain)
        return remain
    return 0.0


EGRESS_URL = "https://myip.ipip.net"   # 国内 IP 回显，返回如“当前 IP：1.2.3.4  来自于：中国 … 电信”
_IP_RE = re.compile(r"[0-9A-Fa-f:.]{7,45}")


def proxy_mode_desc(no_env_proxy: bool) -> str:
    if no_env_proxy:
        return "direct：忽略环境变量与系统代理（trust_env=False, proxies={}），从本机直连"
    present = [n for n in PROXY_ENV_NAMES if os.environ.get(n)]
    return "env：使用环境变量/系统代理（trust_env=True）" + (f"，检测到 {present}" if present else "，未检测到代理环境变量")


def parse_ip(text: str) -> Optional[str]:
    import ipaddress
    for cand in _IP_RE.findall(text or ""):
        try:
            return str(ipaddress.ip_address(cand.strip(".:")))
        except ValueError:
            continue
    return None


def check_egress_stable(rounds: int = 3) -> tuple:
    """用与麦蕊调用相同的 Session（代理设置一致）访问 IP 回显服务 rounds 次。
    每次带 Connection: close 强制新建 TCP 连接，以暴露“按连接轮换出口”的情况；不访问麦蕊。
    返回 (是否唯一且全部成功, 观测到的 IP 列表)。"""
    c = ctx()
    ips = []
    for i in range(rounds):
        ip = None
        try:
            r = c.session.get(c.egress_url, timeout=TIMEOUT, headers={"Connection": "close"})
            ip = parse_ip(r.text) if r.status_code == 200 else None
            print(f"出口自检 {i + 1}/{rounds}：status={r.status_code} ip={ip}")
        except requests.RequestException as e:
            print(f"出口自检 {i + 1}/{rounds}：失败 {type(e).__name__}")
        ips.append(ip)
        if i + 1 < rounds:
            time.sleep(1.0)
    stable = all(ips) and len(set(ips)) == 1
    c.egress = {"url": c.egress_url, "rounds": rounds, "ips": ips, "stable": bool(stable)}
    if stable and c.shared_gate is not None:
        c.shared_gate.confirm_egress(ips[0])
    return bool(stable), ips


# --------------------------------------------------------------------------- 样例、摘要、结果
def save_sample(name: str, resp: Resp, max_rows: int = 5) -> None:
    """保存脱敏、截断后的样例到 samples/<run_id>/（不覆盖）。"""
    data = resp.data
    if isinstance(data, list):
        payload = {"_total_rows": len(data), "_rows_saved": min(len(data), max_rows), "rows": data[:max_rows]}
    elif isinstance(data, dict):
        payload = {k: (v[:max_rows] if isinstance(v, list) else v) for k, v in data.items()}
    else:
        payload = {"_raw_text": resp.text[:2000]}
    out = _safe_json({"url": resp.url_redacted, "status": resp.status, "ms": resp.ms, "data": payload})
    write_new(ctx().samples_dir / f"{name}.json", out)


def rows(data: Any) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("data", "rows", "items", "list", "result"):
            v = data.get(k)
            if isinstance(v, list):
                return v
            if isinstance(v, dict) and isinstance(v.get("list"), list):
                return v["list"]
    return []


def fields_of(data: Any) -> list:
    r = rows(data)
    if r and isinstance(r[0], dict):
        return list(r[0].keys())
    if isinstance(data, dict):
        return list(data.keys())
    return []


def summarize(resp: Resp, time_keys=("t", "d", "date", "trade_date", "jzrq", "rq", "sj", "ts", "time")) -> dict:
    r = rows(resp.data)
    tvals = []
    for row in r:
        if isinstance(row, dict):
            for k in time_keys:
                if k in row and row[k] not in (None, ""):
                    tvals.append(str(row[k]))
                    break
    return {
        "name": resp.name, "url": resp.url_redacted, "status": resp.status, "ok": resp.ok, "ms": resp.ms,
        "bytes": resp.nbytes, "rows": len(r) if r else (1 if isinstance(resp.data, dict) and resp.ok else 0),
        "fields": fields_of(resp.data), "time_min": min(tvals) if tvals else None,
        "time_max": max(tvals) if tvals else None,
        "error": None if resp.ok else (resp.text[:300] or resp.error),
    }


def write_results(probe: str, results: list) -> Path:
    return write_new(ctx().run_dir / f"{probe}.json", _safe_json(results))


def pct(values: list, p: float) -> Optional[float]:
    if not values:
        return None
    v = sorted(values)
    k = (len(v) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return round(v[lo] + (v[hi] - v[lo]) * (k - lo), 1)


def latency_stats(ms: list) -> dict:
    return {"n": len(ms), "p50": pct(ms, 0.5), "p95": pct(ms, 0.95), "min": min(ms) if ms else None,
            "max": max(ms) if ms else None, "mean": round(statistics.mean(ms), 1) if ms else None}


def run_probe(probe: str, fn: Callable[[list], None]) -> bool:
    """在当前进程内运行一个探针；返回 False 表示触发熔断（调用方应停止后续探针）。"""
    results: list = []
    ok = True
    try:
        fn(results)
    except LimitHit as e:
        results.append({"name": "ABORT", "error": str(e)})
        print("!!! 触发限流/熔断，已停止：", e)
        ok = False
    finally:
        write_results(probe, results)
    return ok
