# ruff: noqa: S101
"""T-T55 / T-A91 A1s：静态层只守 api-contract §7.11.5①a 的 S1–S6 有限清单。

正例=应报红的写法（合成样本或基线现状）；负例=登记例外不报红。
不得再为清单外动态写法堆叠静态反例（那些归 A1r）。
只用 AST；不发网络；env 无证书依赖。
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "src/backend/app"
PROBES = ROOT / "src/backend/probes"
SELFCHECKS = ROOT / "src/backend/selfchecks"
DOCKERIGNORE = ROOT / "deploy/docker/backend.Dockerfile.dockerignore"

# 41e517a 冻结的 24 个 probes/*.py（含子路径相对 probes/）
PROBES_FROZEN = frozenset(
    {
        "_helpers.py",
        "common.py",
        "dryrun_mock.py",
        "p01_realtime.py",
        "p02_kline.py",
        "p03_moneyflow.py",
        "p04_lhb_pool_auction.py",
        "p05_fundamental.py",
        "p06_factors.py",
        "p07_sector_index.py",
        "p08_news.py",
        "p09_ratelimit.py",
        "p10_stability.py",
        "p11_gaps.py",
        "p11_replay.py",
        "p12_code_lists.py",
        "p13_analyze.py",
        "p13_fin_pit.py",
        "run_all.py",
        "scan_licence.py",
        "tb81.py",
        "tb81_evidence.py",
        "tb86_history.py",
        "tb86_offline.py",
    }
)
PROBES_HTTP_MAIRUI_ALLOW = frozenset({"common.py", "tb81.py", "tb86_history.py"})

S3_FORBIDDEN = frozenset(
    {
        "http.client",
        "urllib.request",
        "urllib3",
        "requests",
        "httpx",
        "aiohttp",
        "socket",
        "ssl",
    }
)
S3_SOURCES_URLLIB = frozenset({"urllib.request", "urllib.error", "urllib.parse"})
S6_REGISTERED = frozenset(
    {
        "probes/p10_stability.py:4",
        "probes/p11_replay.py:49",
        "probes/run_all.py:25",
        "probes/run_all.py:59",
        "probes/run_all.py:240",
        "selfchecks/tb49.py",
        "selfchecks/tb49b.py",
        "selfchecks/tb49c.py",
        "selfchecks/test_tb81_safety.py",
        "selfchecks/test_tb71_cards_skeleton.py",
        "selfchecks/test_tb71_formal.py",
        "selfchecks/test_tb72_features.py",
        "selfchecks/test_tb116_static_guard_l124.py",
        "selfchecks/test_tb116b_a6_lock_deny.py",
        # 41e517a 已存在、plan 列举未穷尽的 selfchecks 动态导入（登记以免误伤既有测试代码）
        "selfchecks/test_tb85b_mairui_snapshot.py",
        "selfchecks/test_tb95_reset.py",
    }
)

HTTP_TOKENS = (
    "http.client",
    "HTTPSConnection",
    "urllib.request",
    "import requests",
    "import httpx",
    "urllib3",
    "aiohttp",
)


def _parse(path: Path) -> ast.AST | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeError):
        return None


def _import_modules(tree: ast.AST) -> list[tuple[str, int, str]]:
    """Return (imported_module, lineno, kind) for Import / ImportFrom."""
    out: list[tuple[str, int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append((alias.name, node.lineno, "import"))
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.append((node.module, node.lineno, "from"))
            if node.module == "http" and any(a.name == "client" for a in node.names):
                out.append(("http.client", node.lineno, "from"))
            if node.module == "urllib" and any(a.name == "request" for a in node.names):
                out.append(("urllib.request", node.lineno, "from"))
    return out


def _egress_private_names() -> set[str]:
    path = APP / "ingest/egress.py"
    if not path.is_file():
        return {
            "_https_get",
            "HOST",
            "_ISSUED_LEASES",
            "_LEASE_LOCK_CONN",
            "_lease_key",
            "_lease_is_valid",
        }
    tree = _parse(path)
    names = {"HOST", "_ISSUED_LEASES", "_LEASE_LOCK_CONN", "_lease_key"}
    if tree is None:
        return names
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name.startswith("_") and not (
                node.name.startswith("__") and node.name.endswith("__")
            ):
                names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.startswith("_") and not (
                    t.id.startswith("__") and t.id.endswith("__")
                ):
                    names.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id.startswith("_") and not (
                node.target.id.startswith("__") and node.target.id.endswith("__")
            ):
                names.add(node.target.id)
    names.discard("_STRICT_STATUSES")  # not a secret hook; still underscore — keep, actually contract says any
    names.add("_STRICT_STATUSES")
    return names


def _s2_hits(path: Path, tree: ast.AST, priv: set[str]) -> list[str]:
    rel = str(path)
    hits: list[str] = []
    text = path.read_text(encoding="utf-8")
    # A28 反例夹具豁免（整文件须含标记）
    if "# A28-negative" in text:
        return []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and "egress" in node.module:
            for alias in node.names:
                if alias.name == "*" or alias.name in priv or alias.name == "HOST":
                    hits.append(f"{rel}:{node.lineno}: from {node.module} import {alias.name}")
        if isinstance(node, ast.Attribute) and (
            node.attr in priv or node.attr == "HOST"
        ):
            hits.append(f"{rel}:{node.lineno}: .{node.attr}")
        if isinstance(node, ast.Name) and node.id in priv:
            # only if imported; Name _https_get after import
            if node.id.startswith("_") or node.id == "HOST":
                hits.append(f"{rel}:{getattr(node, 'lineno', 0)}: name {node.id}")
    return hits


def _s3_imported(mod: str, imported: set[str]) -> bool:
    if mod in imported:
        return True
    # import http.client listed as http.client; import http does not count unless client
    return False


def _has_mairui_literal(tree: ast.AST) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)):
            val = node.value.decode("utf-8", "ignore") if isinstance(node.value, bytes) else node.value
            if "mairuiapi" in val.lower():
                lines.append(getattr(node, "lineno", 0))
        if isinstance(node, ast.JoinedStr):
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    if "mairuiapi" in part.value.lower():
                        lines.append(getattr(node, "lineno", 0))
    return lines


def _s6_hits(path: Path, tree: ast.AST) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif node.module:
                mods = [node.module]
            for m in mods:
                if m == "importlib" or m.startswith("importlib."):
                    hits.append((node.lineno, f"import {m}"))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in {"__import__", "exec", "eval", "compile"}:
                hits.append((node.lineno, node.func.id))
    return hits


def _socket_attrs(tree: ast.AST) -> set[str]:
    attrs: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            # socket.X
            if isinstance(node.value, ast.Name) and node.value.id == "socket":
                attrs.add(node.attr)
    return attrs


# ---------------------------------------------------------------------------
# S1
# ---------------------------------------------------------------------------


def test_a1s_s1_tree_frozen_list_and_http_allow() -> None:
    """负例：41e517a 冻结 24 文件存在且仅 3 个允许域名+HTTP；app 不导入 probes；dockerignore 不含 probes 白名单。"""
    present = {str(p.relative_to(PROBES)) for p in PROBES.rglob("*.py") if p.is_file()}
    extra = present - PROBES_FROZEN
    missing = PROBES_FROZEN - present
    offenders: list[str] = []
    if extra:
        offenders.append(f"S1 extra probes: {sorted(extra)}")
    if missing:
        offenders.append(f"S1 missing frozen probes: {sorted(missing)}")
    for path in sorted(PROBES.rglob("*.py")):
        rel = path.name  # allow list is by basename per plan「3 个文件」
        src = path.read_text(encoding="utf-8")
        has_http = any(tok in src for tok in HTTP_TOKENS)
        has_mai = "mairuiapi" in src.lower()
        if has_http and has_mai and rel not in PROBES_HTTP_MAIRUI_ALLOW:
            offenders.append(f"S1 non-allow probe has mairui+HTTP: {path.relative_to(PROBES)}")
    # app/ must not import probes
    for path in APP.rglob("*.py"):
        tree = _parse(path)
        if tree is None:
            continue
        for mod, lineno, _k in _import_modules(tree):
            if mod == "probes" or mod.startswith("probes."):
                offenders.append(f"S1 app imports probes: {path.relative_to(APP)}:{lineno}")
    if DOCKERIGNORE.is_file():
        for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith("!") and "probes" in s:
                offenders.append(f"S1 dockerignore whitelist probes: {s}")
    assert not offenders, "A1s S1 tree:\n" + "\n".join(offenders)


def test_a1s_s1_positive_new_file_and_combo_flagged(tmp_path: Path) -> None:
    """正例：冻结清单外新增 .py（子目录、仅 import probes.common）即红；非白名单同时含域名+HTTP 即红。"""
    shadow = tmp_path / "probes"
    shadow.mkdir()
    # frozen placeholders
    for name in PROBES_FROZEN:
        dest = shadow / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("# frozen stub\n", encoding="utf-8")
    extra = shadow / "nested" / "only_common.py"
    extra.parent.mkdir(parents=True, exist_ok=True)
    extra.write_text("from probes.common import x\n", encoding="utf-8")
    present = {str(p.relative_to(shadow)) for p in shadow.rglob("*.py")}
    assert present - PROBES_FROZEN, "positive fixture must introduce an extra file"
    # combo on a 21-file
    dirty = shadow / "p01_realtime.py"
    dirty.write_text("import http.client\nHOST = 'api.mairuiapi.com'\n", encoding="utf-8")
    offenders: list[str] = []
    extra_files = present - PROBES_FROZEN
    if extra_files:
        offenders.append(f"extra={sorted(extra_files)}")
    src = dirty.read_text(encoding="utf-8")
    if any(t in src for t in HTTP_TOKENS) and "mairuiapi" in src.lower():
        if dirty.name not in PROBES_HTTP_MAIRUI_ALLOW:
            offenders.append("combo")
    # negative: allow file with both is OK
    ok = shadow / "common.py"
    ok.write_text("import http.client\nX='mairuiapi.com'\n", encoding="utf-8")
    src_ok = ok.read_text(encoding="utf-8")
    allow_off = any(t in src_ok for t in HTTP_TOKENS) and "mairuiapi" in src_ok.lower()
    assert allow_off  # would be http+domain
    # but allow list permits it — not added to offenders
    assert "extra=" in offenders[0] and "combo" in offenders


# ---------------------------------------------------------------------------
# S2
# ---------------------------------------------------------------------------


def test_a1s_s2_tree_app_has_no_private_refs() -> None:
    """负例：app/（除 egress）不得静态引用 egress 私有名。"""
    priv = _egress_private_names()
    offenders: list[str] = []
    for path in APP.rglob("*.py"):
        rel = str(path.relative_to(APP))
        if rel in {"ingest/egress.py"}:
            continue
        tree = _parse(path)
        if tree is None:
            continue
        # netguard may mention HOST/domain constants — still no egress private attrs required
        offenders.extend(_s2_hits(path, tree, priv))
    # filter Name HOST which is too generic in app
    offenders = [o for o in offenders if ": name HOST" not in o]
    assert not offenders, "A1s S2 tree:\n" + "\n".join(offenders)


def test_a1s_s2_positive_forms_flagged() -> None:
    """正例：绝对/相对/别名/import */.attr 引用 _https_get、HOST、_ISSUED_LEASES、_LEASE_LOCK_CONN 即红。"""
    priv = _egress_private_names() | {
        "_https_get",
        "HOST",
        "_ISSUED_LEASES",
        "_LEASE_LOCK_CONN",
    }
    samples = {
        "abs.py": "from app.ingest.egress import _https_get\n",
        "rel.py": "from .egress import HOST\n",
        "alias.py": "import app.ingest.egress as E\nX = E._ISSUED_LEASES\n",
        "star.py": "from app.ingest.egress import *\n",
        "attr.py": "import app.ingest.egress as e\nprint(e._LEASE_LOCK_CONN)\n",
    }
    for name, src in samples.items():
        tree = ast.parse(src)
        hits = []
        t = ast.parse(src)
        for node in ast.walk(t):
            if isinstance(node, ast.ImportFrom) and node.module and "egress" in node.module:
                for alias in node.names:
                    if alias.name == "*" or alias.name in priv:
                        hits.append(alias.name)
            if isinstance(node, ast.Attribute) and node.attr in priv:
                hits.append(node.attr)
        assert hits, f"S2 positive {name} should be flagged, src={src!r}"




# ---------------------------------------------------------------------------
# S2b netguard 窗口 API（T-A92）
# ---------------------------------------------------------------------------

S2B_WINDOW_NAMES = frozenset(
    {
        "egress_window",
        "_egress_window",
        "register_resolved_ip",
    }
)


def _netguard_private_names() -> set[str]:
    names = set(S2B_WINDOW_NAMES)
    path = APP / "ingest/netguard.py"
    if not path.is_file():
        return names
    tree = _parse(path)
    if tree is None:
        return names
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name.startswith("_") and not (
                node.name.startswith("__") and node.name.endswith("__")
            ):
                names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.startswith("_") and not (
                    t.id.startswith("__") and t.id.endswith("__")
                ):
                    names.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id.startswith("_") and not (
                node.target.id.startswith("__") and node.target.id.endswith("__")
            ):
                names.add(node.target.id)
    return names


def _s2b_hits(path: Path, tree: ast.AST, priv: set[str]) -> list[str]:
    rel = str(path.relative_to(APP))
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and "netguard" in node.module:
            for alias in node.names:
                if alias.name == "*" or alias.name in priv or alias.name in S2B_WINDOW_NAMES:
                    hits.append(f"{rel}:{node.lineno}: from {node.module} import {alias.name}")
        if isinstance(node, ast.Attribute) and (
            node.attr in priv or node.attr in S2B_WINDOW_NAMES
        ):
            # only count when the value chain mentions netguard, or attr is a window name
            hits.append(f"{rel}:{node.lineno}: .{node.attr}")
        if isinstance(node, ast.Name) and node.id in priv:
            hits.append(f"{rel}:{getattr(node, 'lineno', 0)}: name {node.id}")
    return hits


def _netguard_aliases(tree: ast.AST) -> set[str]:
    aliases: set[str] = {"netguard"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if "netguard" in str(node.module):
                for alias in node.names:
                    aliases.add(alias.asname or alias.name)
            for alias in node.names:
                if alias.name == "netguard" or "netguard" in (alias.asname or ""):
                    aliases.add(alias.asname or alias.name)
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "netguard" in alias.name:
                    aliases.add(alias.asname or alias.name.split(".")[-1])
        if isinstance(node, ast.Assign):
            if isinstance(node.value, ast.Name) and "netguard" in node.value.id.lower():
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        aliases.add(t.id)
    return aliases


def _attr_root_name(node: ast.AST) -> str | None:
    cur = node
    while isinstance(cur, ast.Attribute):
        cur = cur.value
    if isinstance(cur, ast.Name):
        return cur.id
    return None


def test_a1s_s2b_tree_allowed_refs() -> None:
    """负例：workers/ingest 只许 install；egress 只许窗口 API 与 EgressBlocked；其它 app 引用即红。"""
    priv = _netguard_private_names() | set(S2B_WINDOW_NAMES)
    ingest_allow = {"install"}
    egress_allow = set(S2B_WINDOW_NAMES) | {"EgressBlocked", "install"}
    offenders: list[str] = []
    for path in APP.rglob("*.py"):
        rel = str(path.relative_to(APP))
        tree = _parse(path)
        if tree is None:
            continue
        aliases = _netguard_aliases(tree)
        hits = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                mentions = "netguard" in str(node.module)
                imported_ng = any(a.name == "netguard" for a in node.names)
                if mentions or imported_ng:
                    for alias in node.names:
                        name = alias.name
                        if rel == "workers/ingest.py":
                            # 只许 import 模块后用 install，不得直接 from netguard import 窗口 API
                            if mentions and name not in ingest_allow and name != "netguard":
                                hits.append(f"import {name}")
                            if name == "*":
                                hits.append("import *")
                        elif rel == "ingest/egress.py":
                            if mentions and name not in egress_allow and name != "netguard":
                                hits.append(f"import {name}")
                            if name == "*":
                                hits.append("import *")
                        else:
                            hits.append(f"import {name}")
            if isinstance(node, ast.Attribute):
                root = _attr_root_name(node.value) if not isinstance(node.value, ast.Name) else node.value.id
                if root is None or (root not in aliases and "netguard" not in root.lower()):
                    continue
                if rel == "workers/ingest.py" and node.attr in ingest_allow:
                    continue
                if rel == "ingest/egress.py" and node.attr in egress_allow:
                    continue
                if node.attr in priv or node.attr in S2B_WINDOW_NAMES or node.attr == "install":
                    hits.append(f".{node.attr}")
        if hits:
            offenders.append(f"{rel}: {hits}")
    assert not offenders, "A1s S2b tree:\n" + "\n".join(offenders)


def test_a1s_s2b_positive_forms_flagged() -> None:
    """正例：egress 外以任何静态形式引用 egress_window / _egress_window / register_resolved_ip / netguard 下划线名即红。"""
    priv = _netguard_private_names() | set(S2B_WINDOW_NAMES)
    samples = {
        "abs_win": "from app.ingest.netguard import egress_window\n",
        "abs_priv": "from app.ingest.netguard import _egress_window\n",
        "reg": "from app.ingest.netguard import register_resolved_ip\n",
        "attr": "import app.ingest.netguard as ng\nng.egress_window(lease)\n",
        "star": "from app.ingest.netguard import *\n",
    }
    for name, src in samples.items():
        tree = ast.parse(src)
        hits: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and "netguard" in node.module:
                for alias in node.names:
                    if alias.name == "*" or alias.name in priv or alias.name in S2B_WINDOW_NAMES:
                        hits.append(alias.name)
            if isinstance(node, ast.Attribute) and (
                node.attr in priv or node.attr in S2B_WINDOW_NAMES
            ):
                hits.append(node.attr)
        assert hits, f"S2b positive {name} should be flagged, src={src!r}"

# ---------------------------------------------------------------------------
# S3
# ---------------------------------------------------------------------------


def test_a1s_s3_tree_and_registered_exceptions() -> None:
    """负例：sources 的 urllib、workers/ingest 的 socket.gethostname、netguard 的 socket 不红。"""
    offenders: list[str] = []
    for path in APP.rglob("*.py"):
        rel = str(path.relative_to(APP))
        tree = _parse(path)
        if tree is None:
            continue
        imported = {m for m, _l, _k in _import_modules(tree)}
        # expand prefixes
        hit = []
        for mod in S3_FORBIDDEN:
            if mod in imported:
                hit.append(mod)
        if not hit:
            continue
        if rel == "ingest/egress.py":
            continue
        if rel == "master/sources.py":
            unexpected = [m for m in hit if m not in S3_SOURCES_URLLIB and m != "urllib.error" and not m.startswith("urllib.")]
            # sources may import urllib.request / error / parse only
            bad = [m for m in hit if m not in {"urllib.request", "urllib.error", "urllib.parse", "urllib"}]
            # urllib alone is ok if only submods; import urllib.request listed as urllib.request
            bad = [m for m in hit if m in S3_FORBIDDEN and m not in {"urllib.request"}]
            # urllib.error/parse not in S3_FORBIDDEN
            bad = [m for m in hit if m in {"http.client", "urllib3", "requests", "httpx", "aiohttp", "socket", "ssl"}]
            if bad:
                offenders.append(f"sources unexpected {bad}")
            continue
        if rel == "workers/ingest.py":
            if any(m in hit for m in S3_FORBIDDEN if m != "socket"):
                offenders.append(f"workers/ingest unexpected {hit}")
            else:
                attrs = _socket_attrs(tree)
                if attrs - {"gethostname"}:
                    offenders.append(f"workers/ingest socket attrs {attrs - {'gethostname'}}")
            continue
        if rel == "ingest/netguard.py":
            bad = [m for m in hit if m not in {"socket", "ssl"} and m != "ipaddress"]
            # only socket (and ipaddress not in forbidden)
            bad = [m for m in hit if m not in {"socket"}]
            if bad:
                offenders.append(f"netguard unexpected {bad}")
            continue
        offenders.append(f"{rel}: {hit}")
    assert not offenders, "A1s S3 tree:\n" + "\n".join(offenders)


def test_a1s_s3_positive_forbidden_imports_flagged() -> None:
    """正例：egress 外 http.client / from http import client / urllib.request / urllib3 / requests / httpx / aiohttp / socket / ssl 即红。"""
    snippets = [
        "import http.client",
        "from http import client",
        "import urllib.request",
        "from urllib import request",
        "import urllib3",
        "import requests",
        "import httpx",
        "import aiohttp",
        "import socket",
        "import ssl",
    ]
    for src in snippets:
        tree = ast.parse(src)
        imported = {m for m, _l, _k in _import_modules(tree)}
        hit = any(m in imported for m in S3_FORBIDDEN)
        assert hit, f"S3 should flag {src!r}, imported={imported}"


# ---------------------------------------------------------------------------
# S4
# ---------------------------------------------------------------------------


def test_a1s_s4_tree_mairui_literal_only_egress_or_netguard() -> None:
    """负例：app/ 内除 egress（及 netguard 域名常量）外无 mairuiapi 字面量；sources 同样不得出现。"""
    offenders: list[str] = []
    for path in APP.rglob("*.py"):
        rel = str(path.relative_to(APP))
        if rel in {"ingest/egress.py", "ingest/netguard.py"}:
            continue
        tree = _parse(path)
        if tree is None:
            continue
        lines = _has_mairui_literal(tree)
        if lines:
            offenders.append(f"{rel}:{lines}")
    assert not offenders, "A1s S4 tree:\n" + "\n".join(offenders)


def test_a1s_s4_positive_literal_flagged() -> None:
    """正例：字符串常量/f-string 片段/bytes 含 mairuiapi 即红。"""
    samples = [
        "X = 'api.MAIRUIapi.com'\n",
        "X = f'api.mairuiapi.'\n",
        "X = b'mairuiapi'\n",
    ]
    for src in samples:
        lines = _has_mairui_literal(ast.parse(src))
        assert lines, f"S4 should flag {src!r}"


# ---------------------------------------------------------------------------
# S5
# ---------------------------------------------------------------------------


def _dict_has_transport_key(node: ast.AST) -> bool:
    if isinstance(node, ast.Dict):
        for k in node.keys:
            if isinstance(k, ast.Constant) and k.value == "transport":
                return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "dict":
        for kw in node.keywords:
            if kw.arg == "transport":
                return True
    return False


def _s5_starstar_names(tree: ast.AST) -> set[str]:
    """Names bound to a dict literal/dict() that contains a \"transport\" key."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _dict_has_transport_key(node.value):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
            and _dict_has_transport_key(node.value)
        ):
            names.add(node.target.id)
    return names


def _s5_transport_inject(tree: ast.AST) -> list[str]:
    hits: list[str] = []
    star_names = _s5_starstar_names(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # mairui_get(..., transport=...) / **{"transport": ...} / **var
            for kw in node.keywords:
                if kw.arg == "transport":
                    hits.append(f"kw:transport:{node.lineno}")
                if kw.arg is None:
                    if _dict_has_transport_key(kw.value):
                        hits.append(f"kw-star-dict:transport:{node.lineno}")
                    elif isinstance(kw.value, ast.Name) and kw.value.id in star_names:
                        hits.append(f"kw-star-name:transport:{node.lineno}")
            # process(..., upstream=...)
            func = node.func
            name = ""
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name == "process":
                for kw in node.keywords:
                    if kw.arg == "upstream":
                        hits.append(f"process.upstream:{node.lineno}")
        if isinstance(node, ast.Subscript):
            sl = node.slice
            if isinstance(sl, ast.Constant) and sl.value == "transport":
                hits.append(f"dict-key:transport:{node.lineno}")
    return hits


def test_a1s_s5_tree_daily_lists_seam_only() -> None:
    """负例：daily_lists process 测试缝 transport 键不红；app 内不得调用 process(upstream=)。"""
    offenders: list[str] = []
    for path in APP.rglob("*.py"):
        rel = str(path.relative_to(APP))
        tree = _parse(path)
        if tree is None:
            continue
        hits = _s5_transport_inject(tree)
        if rel == "ingest/daily_lists.py":
            # seam at get_kwargs["transport"] = upstream is registered; process(upstream=) inside def is the signature, not a call from app production
            # filter dict-key transport (allowed seam) and skip function *definition* defaults
            # calls to process with upstream in this file?
            bad = [h for h in hits if h.startswith("process.upstream:")]
            # defining process(upstream=None) is a FunctionDef, not a Call
            if bad:
                offenders.append(f"{rel}: {bad}")
            continue
        if rel == "ingest/egress.py":
            # mairui_get may have transport= param in signature; calls inside?
            continue
        if hits:
            offenders.append(f"{rel}: {hits}")
    assert not offenders, "A1s S5 tree:\n" + "\n".join(offenders)


def test_a1s_s5_positive_inject_and_process_upstream_flagged() -> None:
    """正例：app 内 transport= / 字典键 transport / process(upstream=) / **{\"transport\":…} / **变量 即红。"""
    samples = {
        "kw": "mairui_get(path, transport=fn)\n",
        "dict": 'get_kwargs["transport"] = fn\n',
        "proc": "process(engine, bid, grant, upstream=fn)\n",
        # T-A92 / T-T56：两种 ** 写法（T-T55 均漏报）
        "star_dict": 'mairui_get(**{"transport": fn})\n',
        "star_var": 'params = {"transport": fn}\nmairui_get(path, **params)\n',
    }
    for name, src in samples.items():
        hits = _s5_transport_inject(ast.parse(src))
        assert hits, f"S5 should flag {name}: {src!r}"
    # negative seam shape is the same dict key — registered only in daily_lists; scanner flags raw, tree test exempts that file


# ---------------------------------------------------------------------------
# S6
# ---------------------------------------------------------------------------


def test_a1s_s6_tree_app_clean_registered_probes_selfchecks() -> None:
    """负例：登记项（含 p11_replay.py:49）不红。app/ 若出现 __import__/importlib/exec/eval/compile 即红。"""
    offenders: list[str] = []
    for path in APP.rglob("*.py"):
        tree = _parse(path)
        if tree is None:
            continue
        hits = _s6_hits(path, tree)
        if hits:
            offenders.append(f"app/{path.relative_to(APP)}: {hits}")
    # probes + selfchecks: unregistered hits are red
    for root, prefix in ((PROBES, "probes"), (SELFCHECKS, "selfchecks")):
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            tree = _parse(path)
            if tree is None:
                continue
            rel = f"{prefix}/{path.relative_to(root)}"
            for lineno, kind in _s6_hits(path, tree):
                keys = {rel, f"{rel}:{lineno}"}
                if keys & S6_REGISTERED or rel in S6_REGISTERED:
                    continue
                # also allow registered file:line only
                offenders.append(f"unregistered S6 {rel}:{lineno} {kind}")
    assert not offenders, "A1s S6 tree:\n" + "\n".join(offenders)


def test_a1s_s6_positive_dynamic_constructs_flagged() -> None:
    """正例：app 内 __import__/importlib/exec/eval/compile（Name 调用）即红；登记外新增即红。"""
    samples = [
        "__import__('requests')\n",
        "import importlib\n",
        "import importlib.util\n",
        "exec('x')\n",
        "eval('x')\n",
        "compile('x', 'n', 'eval')\n",
    ]
    for src in samples:
        hits = _s6_hits(Path("app/x.py"), ast.parse(src))
        assert hits, f"S6 should flag {src!r}"
    # re.compile 属性调用不算
    hits = _s6_hits(Path("app/x.py"), ast.parse("import re\nre.compile('a')\n"))
    assert not any(k == "compile" for _l, k in hits), "re.compile must not be flagged"


def test_a1s_no_dynamic_bypass_stack_in_this_module() -> None:
    """A1s 不得再为清单外动态写法加静态反例（importlib/getattr/拆串域名等归 A1r）。"""
    names = [fn for fn in globals() if fn.startswith("test_") and "stack" not in fn]
    assert not any("bypass" in n for n in names)
    assert "test_a1_static_guard" not in names
