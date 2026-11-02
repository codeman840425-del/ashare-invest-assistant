"""T-B48：用已有运行目录里的 p11 结果离线重放第 6/7 项（因子空值、时点性、因子数量），不发任何请求。

为什么能重放：p11_gaps.json 里保存了每次调用的摘要——factor/all 与 factor/batch 是 dict 响应，
摘要里有完整 ``sample``；factor/list 的 85 个 id 在 GAP7 evidence 里；factor/history 只存了首末行，
但 GAP6 evidence 里有全部跳变点（每类 ≤8 条，计数与明细条数一致时才算完整），据此重建一条
“首值 + 各跳变点”的序列，跳变日期与前后值与原序列完全相同（只是点数少，``points`` 用原摘要的行数）。
利润表只需 jzrq/plrq，取自 GAP6 evidence 的 reports_used。

网络护栏：重放期间 socket.connect / create_connection / getaddrinfo、requests 的 Session.request
以及 common.call 一律抛 NetworkBlocked；任何一处被触发，重放失败（退出码 2）。
本脚本不读取证书环境变量；环境里有证书变量时直接拒绝运行。

用法（目录 src/backend/probes）::

    env -u MAIRUI_LICENCE python3 p11_replay.py results/run-20261101-190106

输出写到 ``<运行目录>/p11_gaps.replay-T-B48.json``（不覆盖原 p11_gaps.json），并在终端打印 GAP6/GAP7 摘要。
"""
from __future__ import annotations

import contextlib
import json
import os
import socket
import sys
from pathlib import Path

ENV_NAME = "MAIRUI_" + "LICENCE"


class NetworkBlocked(RuntimeError):
    pass


@contextlib.contextmanager
def no_network():
    """把所有出网入口换成抛异常的桩；退出时恢复。记录被拦截的次数。"""
    hits: list = []

    def _block(*a, **k):
        hits.append(repr(a[:2])[:120])
        raise NetworkBlocked("p11_replay 禁止网络调用")

    saved = [(socket.socket, "connect", socket.socket.connect),
             (socket.socket, "connect_ex", socket.socket.connect_ex),
             (socket, "create_connection", socket.create_connection),
             (socket, "getaddrinfo", socket.getaddrinfo)]
    try:
        import requests
        saved.append((requests.Session, "request", requests.Session.request))
    except ImportError:
        pass
    try:
        import common
        saved.append((common, "call", common.call))
    except ImportError:
        pass
    for obj, attr, _ in saved:
        setattr(obj, attr, _block)
    try:
        yield hits
    finally:
        for obj, attr, orig in saved:
            setattr(obj, attr, orig)


class FakeResp:
    def __init__(self, data, status=200):
        self.data, self.status, self.ok = data, status, status == 200
        self.text, self.error, self.headers, self.ms = "", None, {}, 0.0


def _by_name(results: list) -> dict:
    return {e["name"]: e for e in results if isinstance(e, dict) and "name" in e}


def _rebuild_history(summary: dict, pit: dict, extra: dict | None = None) -> list:
    """首值 + 跳变点 → [{"trade_date","value"}]（降序，与接口一致）。明细不完整时抛错。
    extra={YYYY-MM-DD: 值}：原运行中已知的某日值（GAP6 的 history_vs_batch_same_day），插入序列；
    插入前核对它等于该日按跳变点推出的值，不等就抛错。"""
    counts, det = pit["counts"], pit["details"]
    chs = [c for k in det for c in det[k]]
    if sum(counts.values()) != len(chs):
        raise ValueError(f"跳变点明细不完整（计数 {counts}，明细 {len(chs)} 条），无法重建")
    chs.sort(key=lambda c: c["date"])
    first_day = pit["first"]
    rows = [{"trade_date": first_day.replace("-", ""), "value": chs[0]["from"] if chs else None}]
    for c in chs:
        rows.append({"trade_date": c["date"].replace("-", ""), "value": c["to"]})
    for day, val in (extra or {}).items():
        key = day.replace("-", "")
        prev = [r for r in rows if r["trade_date"] <= key]
        if not prev or prev[-1]["value"] != val:
            raise ValueError(f"{day} 的已知值 {val} 与跳变点推出的值不符")
        if prev[-1]["trade_date"] != key:
            rows.append({"trade_date": key, "value": val})
    rows.sort(key=lambda r: r["trade_date"])
    if summary.get("last_row", {}).get("trade_date") not in (None, rows[0]["trade_date"]):
        raise ValueError("首行日期与摘要不符")
    return list(reversed(rows))


def build_fixtures(results: list) -> tuple:
    """返回 (probe 名 → FakeResp, shared)。只覆盖 item67_factors 用到的调用。"""
    by = _by_name(results)
    g6, g7 = by["GAP6_factor_nulls_pit"], by["GAP7_factor_count"]
    fx = {"factor_list": FakeResp({"code": 200, "data": [{"factor_id": f} for f in g7["evidence"]["factor_list_ids"]]})}
    for name, e in by.items():
        if name.startswith("factor_all_") or name == "pit_batch_hist_date":
            if not isinstance(e.get("sample"), dict):
                raise ValueError(f"{name} 没有完整 sample，无法重放")
            fx[name] = FakeResp(e["sample"], e.get("status") or 200)
    for fid, pit in g6["evidence"]["pit"].items():
        name = f"pit_history_{fid}_600519"
        known = g6["conclusion"].get("history_vs_batch_same_day", {}).get(fid) or {}
        extra = {known["date"]: known["history"]} if known.get("date") and known.get("history") is not None else None
        fx[name] = FakeResp({"code": 200, "data": _rebuild_history(by[name], pit, extra)})
    inc = [{"jzrq": r["jzrq"], "plrq": r["plrq"]} for r in g6["evidence"]["reports_used"]]
    return fx, {"income_600519": inc}, {n: by[n].get("rows") for n in fx if n.startswith("pit_history_")}


def replay(run_dir: Path) -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import p11_gaps as g
    results = json.loads((run_dir / "p11_gaps.json").read_text(encoding="utf-8"))
    fx, shared, orig_points = build_fixtures(results)
    used: list = []

    def fake_probe(res, name, path_tpl, *a, **k):
        if name not in fx:
            raise KeyError(f"重放缺少 {name} 的数据")
        used.append(name)
        return fx[name]

    out: list = []
    with no_network() as hits:
        saved_probe, g.probe = g.probe, fake_probe
        try:
            g.item67_factors(out, shared)
        finally:
            g.probe = saved_probe
    if hits:
        raise NetworkBlocked(f"重放期间有 {len(hits)} 次网络调用被拦截：{hits[:3]}")
    gaps = {e["name"]: e for e in out if e["name"].startswith("GAP")}
    for fid, n in orig_points.items():          # 点数恢复为原摘要行数（重建序列只含跳变点）
        key = fid.replace("pit_history_", "").replace("_600519", "")
        gaps["GAP6_factor_nulls_pit"]["evidence"]["pit"][key]["points_replayed"] = \
            gaps["GAP6_factor_nulls_pit"]["evidence"]["pit"][key]["points"]
        gaps["GAP6_factor_nulls_pit"]["evidence"]["pit"][key]["points"] = n
    return {"source_run": run_dir.name, "replayed_calls": used, "network_calls_blocked": len(hits),
            "items": list(gaps.values())}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if os.environ.get(ENV_NAME):
        print("拒绝运行：环境里有证书变量（请 env -u 该变量）")
        return 3
    run_dir = Path(argv[0] if argv else "results/run-20261101-190106")
    try:
        rep = replay(run_dir)
    except NetworkBlocked as e:
        print(f"FAIL 网络护栏触发：{e}")
        return 2
    dst = run_dir / "p11_gaps.replay-T-B48.json"
    dst.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    for e in rep["items"]:
        print(f"{e['name']} [{e['status']}] {e['conclusion']['summary']}")
    print(f"网络调用被拦截 {rep['network_calls_blocked']} 次；写入 {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
