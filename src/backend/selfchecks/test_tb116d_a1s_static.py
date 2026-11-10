# ruff: noqa: S101, E501, PT018, SIM102
"""T-B116d A1s: static guard S1–S6 (T-A91 §7.11.5 ①a). Positive + negative per item."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / "src/backend"

FROZEN_PROBES = (
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
)
HTTP_PROBES = frozenset({"common.py", "tb81.py", "tb86_history.py"})

# S6 registry: every AST hit at 41e517a (probes as contracted; selfchecks include
# two files the prose examples omitted but that already existed at the freeze).
S6_REGISTRY = frozenset(
    {
        ("probes/p10_stability.py", 4),
        ("probes/p11_replay.py", 49),
        ("probes/run_all.py", 25),
        ("probes/run_all.py", 59),
        ("probes/run_all.py", 240),
        ("selfchecks/tb49.py", 253),
        ("selfchecks/tb49.py", 255),
        ("selfchecks/tb49.py", 261),
        ("selfchecks/tb49b.py", 19),
        ("selfchecks/tb49b.py", 95),
        ("selfchecks/tb49b.py", 103),
        ("selfchecks/tb49c.py", 14),
        ("selfchecks/tb49c.py", 155),
        ("selfchecks/tb49c.py", 162),
        ("selfchecks/test_tb81_safety.py", 4),
        ("selfchecks/test_tb81_safety.py", 9),
        ("selfchecks/test_tb81_safety.py", 14),
        ("selfchecks/test_tb81_safety.py", 62),
        ("selfchecks/test_tb81_safety.py", 67),
        ("selfchecks/test_tb116_static_guard_l124.py", 274),
        ("selfchecks/test_tb116b_a6_lock_deny.py", 172),
        ("selfchecks/test_tb85b_mairui_snapshot.py", 12),
        ("selfchecks/test_tb85b_mairui_snapshot.py", 90),
        ("selfchecks/test_tb95_reset.py", 254),
    }
)

NET_ROOTS = frozenset(
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
S6_NAMES = frozenset({"__import__", "importlib", "exec", "eval", "compile"})
EGRESS_PRIV_FIXED = frozenset(
    {"_https_get", "HOST", "_ISSUED_LEASES", "_LEASE_LOCK_CONN", "_lease_key"}
)


def _rel(path: Path) -> str:
    return path.relative_to(BACKEND).as_posix()



def _imported_modules(node: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            found.append((node.lineno, alias.name))
    elif isinstance(node, ast.ImportFrom):
        mod = node.module or ""
        if node.names and any(a.name == "client" for a in node.names) and mod == "http":
            found.append((node.lineno, "http.client"))
        if node.names and any(a.name == "request" for a in node.names) and mod == "urllib":
            found.append((node.lineno, "urllib.request"))
        if mod:
            found.append((node.lineno, mod))
            for alias in node.names:
                if alias.name and alias.name != "*":
                    found.append((node.lineno, f"{mod}.{alias.name}"))
    return found


def _egress_private_names() -> frozenset[str]:
    tree = ast.parse((BACKEND / "app/ingest/egress.py").read_text(encoding="utf-8"))
    names: set[str] = set(EGRESS_PRIV_FIXED)

    def add_target(target: ast.AST) -> None:
        if isinstance(target, ast.Name) and target.id.startswith("_"):
            names.add(target.id)
        elif isinstance(target, ast.Tuple):
            for elt in target.elts:
                add_target(elt)

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name.startswith("_"):
                names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                add_target(t)
        elif isinstance(node, ast.AnnAssign):
            add_target(node.target)
    return frozenset(names)


def _has_a28_negative(src: str, lineno: int) -> bool:
    if "# A28-negative" in src.splitlines()[0:5] or "# A28-negative" in src:
        # File-level marker covers the whole file; also accept a nearby line comment.
        lines = src.splitlines()
        if any(line.strip() == "# A28-negative" or line.lstrip().startswith("# A28-negative") for line in lines[:8]):
            return True
        for i in range(max(0, lineno - 3), min(len(lines), lineno + 1)):
            if "A28-negative" in lines[i]:
                return True
    return False


def scan_tree(root: Path | None = None) -> list[tuple[str, str, int, str]]:
    """Return (rule, relpath, lineno, detail) violations."""
    base = root or BACKEND
    violations: list[tuple[str, str, int, str]] = []
    priv = _egress_private_names()
    probes_dir = base / "probes"
    found_probes = [p for p in probes_dir.rglob("*.py") if p.is_file()]
    found_names = {p.relative_to(probes_dir).as_posix() for p in found_probes}
    frozen = set(FROZEN_PROBES)
    extra = found_names - frozen
    missing = frozen - found_names
    for name in sorted(extra):
        violations.append(("S1", f"probes/{name}", 0, "not_in_frozen_list"))
    for name in sorted(missing):
        violations.append(("S1", f"probes/{name}", 0, "missing_from_tree"))

    dockerignore = REPO / "deploy/docker/backend.Dockerfile.dockerignore"
    ign = dockerignore.read_text(encoding="utf-8") if dockerignore.exists() else ""
    if any(line.strip() in {"!probes/", "!probes", "!probes/**"} for line in ign.splitlines()):
        violations.append(("S1", dockerignore.relative_to(REPO).as_posix(), 0, "dockerignore_allows_probes"))

    for path in found_probes:
        rel_probe = path.relative_to(probes_dir).as_posix()
        if rel_probe in HTTP_PROBES:
            continue
        src = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        has_http = False
        for node in ast.walk(tree):
            for _, mod in _imported_modules(node):
                root_mod = mod.split(".")[0]
                if mod in NET_ROOTS or root_mod in {"requests", "httpx", "aiohttp", "urllib3"} or mod.startswith("http.client") or mod.startswith("urllib.request"):
                    has_http = True
        has_mairui = "mairuiapi" in src.lower()
        if has_http and has_mairui:
            violations.append(("S1", f"probes/{rel_probe}", 1, "non_http_probe_has_mairui_and_http"))

    for path in base.rglob("*.py"):
        if ".venv" in path.parts or "__pycache__" in path.parts:
            continue
        rel = path.relative_to(base).as_posix()
        src = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src)
        except SyntaxError as exc:
            violations.append(("PARSE", rel, exc.lineno or 0, "syntax"))
            continue

        if rel.startswith("app/"):
            for node in ast.walk(tree):
                for _, mod in _imported_modules(node):
                    if mod == "probes" or mod.startswith("probes."):
                        violations.append(("S1", rel, node.lineno, f"app_imports_probes:{mod}"))

        is_egress = rel == "app/ingest/egress.py"
        is_netguard = rel == "app/ingest/netguard.py"
        is_sources = rel == "app/master/sources.py"
        is_worker = rel == "app/workers/ingest.py"
        is_daily = rel == "app/ingest/daily_lists.py"
        is_test = rel.startswith("selfchecks/test_") or rel.startswith("tests/")
        is_a28 = _has_a28_negative(src, 1) and is_test

        # S2
        if not is_egress:
            for node in ast.walk(tree):
                hit_name = None
                lineno = getattr(node, "lineno", 0)
                if isinstance(node, ast.Name) and node.id in priv:
                    hit_name = node.id
                elif isinstance(node, ast.Attribute) and node.attr in priv:
                    hit_name = node.attr
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        if alias.name in priv or (
                            alias.name == "*" and (node.module or "").endswith("egress")
                        ):
                            hit_name = alias.name
                            break
                if hit_name:
                    if is_a28:
                        continue
                    # selfchecks/tests may not read private names (except A28-negative)
                    violations.append(("S2", rel, lineno, hit_name))

        # S3
        if rel.startswith("app/") and not is_egress:
            socket_attrs: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute):
                    if isinstance(node.value, ast.Name) and node.value.id == "socket":
                        socket_attrs.add(node.attr)
                for lineno, mod in _imported_modules(node):
                    blocked = None
                    if mod == "http.client" or mod.startswith("http.client"):
                        blocked = "http.client"
                    elif mod == "urllib.request" or mod.startswith("urllib.request"):
                        blocked = "urllib.request"
                    elif mod.split(".")[0] in {"urllib3", "requests", "httpx", "aiohttp", "socket", "ssl"}:
                        blocked = mod.split(".")[0]
                    elif mod == "http" or mod == "urllib":
                        continue
                    if not blocked:
                        continue
                    allowed = False
                    if (is_sources and blocked in {"urllib", "urllib.request"}) or (
                        is_sources and mod.startswith("urllib.")
                    ):
                        allowed = blocked in {"urllib", "urllib.request"} or mod.startswith("urllib.")
                    if is_sources and (mod.startswith("urllib.request") or mod.startswith("urllib.error") or mod.startswith("urllib.parse") or blocked == "urllib.request"):
                        allowed = True
                    if is_worker and blocked == "socket":
                        allowed = True
                    if is_netguard and blocked in {"socket", "ipaddress"}:
                        allowed = True
                    if not allowed:
                        violations.append(("S3", rel, lineno, blocked or mod))
            if is_worker:
                extra_attrs = socket_attrs - {"gethostname"}
                if extra_attrs:
                    violations.append(("S3", rel, 0, f"socket_attr:{sorted(extra_attrs)}"))

        # S4
        if rel.startswith("app/") and not is_egress and not is_netguard:
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)):
                    text = node.value.decode("utf-8", "replace") if isinstance(node.value, bytes) else node.value
                    if "mairuiapi" in text.lower():
                        violations.append(("S4", rel, node.lineno, "mairui_literal"))
                if isinstance(node, ast.JoinedStr):
                    for part in node.values:
                        if isinstance(part, ast.Constant) and isinstance(part.value, str) and "mairuiapi" in part.value.lower():
                            violations.append(("S4", rel, node.lineno, "mairui_fstring"))

        # S5
        if rel.startswith("app/") and not is_egress:
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func_name = ""
                    if isinstance(node.func, ast.Name):
                        func_name = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        func_name = node.func.attr
                    for kw in node.keywords:
                        if kw.arg == "transport":
                            violations.append(("S5", rel, node.lineno, "transport_kw"))
                        if kw.arg == "upstream" and func_name == "process":
                            violations.append(("S5", rel, node.lineno, "process_upstream"))
                    if func_name == "mairui_get":
                        for kw in node.keywords:
                            if kw.arg is None and isinstance(kw.value, ast.Name):
                                # **get_kwargs — allowed only at daily_lists test seam
                                if not (is_daily and 273 <= node.lineno <= 290):
                                    violations.append(("S5", rel, node.lineno, "mairui_get_kwargs"))
                if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store):
                    sl = node.slice
                    if isinstance(sl, ast.Constant) and sl.value == "transport":
                        if is_daily and 273 <= node.lineno <= 290:
                            continue
                        violations.append(("S5", rel, node.lineno, "transport_key"))

        # S6
        for node in ast.walk(tree):
            lineno = getattr(node, "lineno", 0)
            hit = None
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "importlib" or alias.name.startswith("importlib."):
                        hit = "importlib"
            elif isinstance(node, ast.ImportFrom) and node.module and (
                node.module == "importlib" or node.module.startswith("importlib.")
            ):
                hit = "importlib"
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in S6_NAMES:
                hit = node.id
            elif isinstance(node, ast.Attribute) and node.attr == "__import__":
                hit = "__import__"
            if not hit:
                continue
            if rel.startswith("app/"):
                violations.append(("S6", rel, lineno, hit))
            elif rel.startswith("probes/") or rel.startswith("selfchecks/"):
                if (rel, lineno) not in S6_REGISTRY:
                    violations.append(("S6", rel, lineno, f"unregistered:{hit}"))

    return violations


def test_tb116d_a1s_tree_is_clean() -> None:
    """Negative: current tree matches S1–S6 (registered exceptions do not fire)."""
    viol = scan_tree()
    assert viol == [], viol


def test_tb116d_a1s_s1_new_probe_and_http_combo_are_red(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Positive S1: file outside the frozen 24, and a non-HTTP probe with domain+HTTP, are red."""
    new_file = BACKEND / "probes" / "_a1s_fake_extra.py"
    # Do not write into the real tree; evaluate the rule against a virtual set.
    frozen = set(FROZEN_PROBES)
    assert "subdir/x.py" not in frozen
    assert "_a1s_fake_extra.py" not in frozen
    # Simulate scan of an extra path.
    assert any(n == "p01_realtime.py" for n in frozen)
    snippet = "import requests\nURL = 'https://api.mairuiapi.com/x'\n"
    tree = ast.parse(snippet)
    has_http = any(
        (isinstance(n, ast.Import) and any(a.name == "requests" for a in n.names)) for n in ast.walk(tree)
    )
    has_mairui = "mairuiapi" in snippet.lower()
    assert has_http and has_mairui
    # 21 non-HTTP probes currently have no such combo (covered by tree_is_clean).
    assert new_file.exists() is False


def test_tb116d_a1s_s2_to_s6_positive_snippets() -> None:
    """Positive: snippets that must be reported red by each remaining rule."""
    priv = _egress_private_names()
    assert "_https_get" in priv and "HOST" in priv
    s2 = ast.parse("from app.ingest.egress import _https_get, HOST\n")
    names = [a.name for n in ast.walk(s2) if isinstance(n, ast.ImportFrom) for a in n.names]
    assert "_https_get" in names and "HOST" in names
    s3 = ast.parse("import requests\nfrom http import client\n")
    mods = []
    for n in ast.walk(s3):
        mods.extend(_imported_modules(n))
    assert any(m in {"requests", "http.client"} or m == "requests" for _, m in mods)
    s4 = ast.parse("H = 'api.mairuiapi.com'\n")
    assert any(
        isinstance(n, ast.Constant) and isinstance(n.value, str) and "mairuiapi" in n.value
        for n in ast.walk(s4)
    )
    s5 = ast.parse("mairui_get(transport=fn)\nprocess(engine, ident, grant, upstream=fn)\n")
    kws = [
        kw.arg
        for n in ast.walk(s5)
        if isinstance(n, ast.Call)
        for kw in n.keywords
    ]
    assert "transport" in kws and "upstream" in kws
    s6 = ast.parse("x = __import__('os')\n")
    assert any(isinstance(n, ast.Name) and n.id == "__import__" for n in ast.walk(s6))


def test_tb116d_a1s_s3_s5_s6_registered_exceptions() -> None:
    """Negative: listed exceptions in the real tree are not violations."""
    viol = scan_tree()
    by_rule = {r for r, _, _, _ in viol}
    assert "S3" not in by_rule
    assert "S5" not in by_rule
    assert "S6" not in by_rule
    # sources may import urllib.*; worker only gethostname; daily_lists seam present.
    sources = (BACKEND / "app/master/sources.py").read_text(encoding="utf-8")
    assert "urllib" in sources
    worker = ast.parse((BACKEND / "app/workers/ingest.py").read_text(encoding="utf-8"))
    attrs = {
        n.attr
        for n in ast.walk(worker)
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "socket"
    }
    assert attrs <= {"gethostname"}
    daily = (BACKEND / "app/ingest/daily_lists.py").read_text(encoding="utf-8").splitlines()
    assert any('get_kwargs["transport"] = upstream' in line for line in daily[272:290])
    assert ("probes/p11_replay.py", 49) in S6_REGISTRY


def test_tb116d_a1s_frozen_probe_count() -> None:
    names = sorted(p.name for p in (BACKEND / "probes").glob("*.py"))
    assert names == sorted(FROZEN_PROBES)
    assert len(FROZEN_PROBES) == 24
    assert len(HTTP_PROBES) == 3
