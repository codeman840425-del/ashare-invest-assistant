"""Small partition, report-validation and JUnit merge regressions."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

import check_shard_union  # scripts/ci 由 conftest 加入 sys.path（与其他自测一致）
import merge_junit
import pytest_shard


def test_plan_deterministic_union_overhead_and_unknown_files():
    config = {"shards": 3, "shard_overhead_seconds": {"1": 3},
              "weights": {"a.py": 4, "b.py": 3, "c.py": 7, "d.py": 2}}
    files = ["a.py", "b.py", "c.py", "d.py", "unknown.py"]
    plan = pytest_shard.plan(files, config)
    assert plan == pytest_shard.plan(reversed(files), config)
    assert plan == [(["b.py", "unknown.py"], 7), (["c.py"], 7), (["a.py", "d.py"], 6)]
    assigned = [path for members, _ in plan for path in members]
    assert sorted(assigned) == sorted(files)
    assert len(assigned) == len(set(assigned))
    config["colocate"] = [["a.py", "d.py"]]
    plan = pytest_shard.plan(files, config)
    assert any({"a.py", "d.py"} <= set(members) for members, _ in plan)


def test_plugin_reports_full_collection_and_deselects(tmp_path, monkeypatch):
    settings = tmp_path / "config.json"
    settings.write_text(json.dumps({"shards": 2, "weights": {}}))
    monkeypatch.setattr(pytest_shard, "CONFIG", settings)
    monkeypatch.setattr(pytest_shard, "ROOT", tmp_path)
    report = tmp_path / "report.json"
    monkeypatch.setenv("AIA_SHARD_INDEX", "1")
    monkeypatch.setenv("AIA_SHARD_TOTAL", "2")
    monkeypatch.setenv("AIA_SHARD_REPORT", str(report))
    items = [Mock(path=tmp_path / name, nodeid=f"{name}::test_ok") for name in ("a.py", "b.py")]
    original = items[:]
    config = SimpleNamespace(hook=SimpleNamespace(pytest_deselected=Mock()))
    pytest_shard.pytest_collection_modifyitems(config, items)
    assert items == original[:1]
    config.hook.pytest_deselected.assert_called_once_with(items=original[1:])
    assert json.loads(report.read_text()) == {
        "shard": 1, "total": 2, "collected": [i.nodeid for i in original],
        "selected": [original[0].nodeid], "files": ["a.py"], "workers": 1,
    }
    monkeypatch.setenv("AIA_SHARD_TOTAL", "3")
    with pytest.raises(pytest.UsageError):
        pytest_shard.pytest_collection_modifyitems(config, original)
    monkeypatch.delenv("AIA_SHARD_INDEX")
    pytest_shard.pytest_collection_modifyitems(config, original)
    assert len(original) == 2


def union_inputs(tmp_path):
    baseline = tmp_path / "baseline.txt"
    nodes = ["backend/a.py::test_a", "backend/b.py::test_b", "backend/c.py::test_c"]
    baseline.write_text("\n".join(nodes) + "\n\n3 tests collected in 0.1s\n")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"shards": 2, "weights": {}}))
    groups = tmp_path / "ci-groups.yaml"
    groups.write_text("version: 1\ntests:\n" + "".join(
        f'  - {{"file": "tests/backend/{n}.py", "group": "serial_pg"}}\n' for n in "abc"))
    reports = [
        {"shard": 1, "total": 2, "collected": nodes, "selected": nodes[:2],
         "files": ["tests/backend/a.py", "tests/backend/b.py"], "workers": 1},
        {"shard": 2, "total": 2, "collected": nodes, "selected": nodes[2:],
         "files": ["tests/backend/c.py"], "workers": 1},
    ]
    return ["--baseline", str(baseline), "--config", str(config), "--groups", str(groups)], reports


def write_reports(tmp_path, reports):
    paths = []
    for i, report in enumerate(reports):
        path = tmp_path / f"report-{i}.json"
        path.write_text(json.dumps(report))
        paths.append(str(path))
    return paths


@pytest.mark.parametrize("invalid", ["empty", "missing", "duplicate", "omission", "file-twice", "overlap",
                                     "collection", "unlisted", "multi-worker", "colocate-split"])
def test_union_rejects_invalid_reports(tmp_path, capsys, invalid):
    args, reports = union_inputs(tmp_path)
    if invalid == "empty":
        reports.clear()
    elif invalid == "missing":
        reports.pop()
    elif invalid == "duplicate":
        reports[1]["shard"] = 1
    elif invalid == "omission":
        reports[1]["selected"] = []
    elif invalid == "file-twice":
        reports[1]["files"].append(reports[0]["files"][0])
    elif invalid == "overlap":
        reports[1]["selected"].append(reports[0]["selected"][0])
    elif invalid == "collection":
        reports[1]["collected"] = []
    elif invalid == "unlisted":
        reports[1]["files"] = ["tests/backend/z.py"]
    elif invalid == "multi-worker":
        reports[0]["workers"] = 4
    elif invalid == "colocate-split":
        config = tmp_path / "config.json"
        config.write_text(json.dumps({"shards": 2, "weights": {},
                                      "colocate": [["tests/backend/a.py", "tests/backend/c.py"]]}))
    assert check_shard_union.main(args + write_reports(tmp_path, reports)) == 1
    assert "::error" in capsys.readouterr().out


def test_union_tolerates_random_param_ids_but_not_count_change(tmp_path):
    args, reports = union_inputs(tmp_path)
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(baseline.read_text().replace("test_c", "test_c[550e8400-e29b-41d4-a716-446655440000]"))
    reports[0]["collected"] = reports[1]["collected"] = [
        n.replace("test_c", "test_c[32f78a26-1111-4444-8888-123456789abc]") for n in reports[0]["collected"]]
    reports[1]["selected"] = ["backend/c.py::test_c[32f78a26111144448888123456789abd]"]
    assert check_shard_union.main(args + write_reports(tmp_path, reports)) == 0
    reports[1]["selected"].append("backend/c.py::test_c[32f78a26-1111-4444-8888-123456789abe]")
    assert check_shard_union.main(args + write_reports(tmp_path, reports)) == 1


def test_union_summary_with_junit(tmp_path, monkeypatch, capsys):
    args, reports = union_inputs(tmp_path)
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    for i, report in enumerate(reports, 1):
        (tmp_path / f"backend-pytest-shard-{i}.xml").write_text(
            '<testsuites><testsuite>' + ''.join(
                f'<testcase classname="{node.split("::")[0][:-3].replace("/", ".")}" '
                f'name="{node.split("::")[1]}" time="{time}"/>'
                for node, time in zip(report["selected"], (1.2, 2.3))) + '</testsuite></testsuites>')
    assert check_shard_union.main(args + ["--junit", str(tmp_path)] + write_reports(tmp_path, reports)) == 0
    output = capsys.readouterr().out
    assert "| 1 | 2 | 3.5 |" in output
    assert "| 2 | 1 | 1.2 |" in output
    assert summary.read_text() == output


@pytest.mark.parametrize("nodeid,expected", [
    ("backend/a.py::test_a", ("backend.a", "test_a")),
    ("backend/a.py::Class::test_a[x::y[z]]", ("backend.a.Class", "test_a[x::y[z]]")),
    ("backend/a.py::Outer::Inner::test_a[x.py]", ("backend.a.Outer.Inner", "test_a[x.py]")),
    ("backend/a.py", ("", "backend.a")),
    ("backend/a[1].py", ("", "backend.a[1]")),
    ("backend/a[1].py::test_a[x]", ("backend.a[1]", "test_a[x]")),
])
def test_junit_node_mapping(nodeid, expected):
    assert check_shard_union.junit_node(nodeid) == expected


@pytest.fixture
def runtime_union_inputs(tmp_path):
    args, reports = union_inputs(tmp_path)
    contract = "backend/contract/test_contract_stub.py"
    reports[0]["selected"] = [f"{contract}::{name}" for name in (
        "test_stub_conforms_to_contract", "test_contract_checker_catches_violation",
        "test_stub_paths_exist_in_api_contract_doc")]
    reports[0]["files"] = [f"tests/{contract}"]
    nodes = reports[0]["selected"] + reports[1]["selected"]
    (tmp_path / "baseline.txt").write_text("\n".join(nodes))
    for report in reports:
        report["collected"] = nodes
    with (tmp_path / "ci-groups.yaml").open("a") as groups:
        groups.write(f"  - {{file: tests/{contract}, group: parallel}}\n")
    # Five cases extracted from run 43802901765, shard 4; no full artifact needed.
    root = ET.parse(Path(__file__).parent / "fixtures/contract-runtime-junit.xml").getroot()
    (tmp_path / "backend-pytest-shard-2.xml").write_text(
        '<testsuite><testcase classname="backend.c" name="test_c"/></testsuite>')
    return args + ["--junit", str(tmp_path)] + write_reports(tmp_path, reports), root


@pytest.mark.parametrize("keep_parent", [True, False])
def test_union_accepts_real_runtime_expansion(tmp_path, runtime_union_inputs, keep_parent, capsys):
    args, root = runtime_union_inputs
    if not keep_parent:
        root.remove(root[0])
    ET.ElementTree(root).write(tmp_path / "backend-pytest-shard-1.xml")
    assert check_shard_union.main(args) == 0
    output = capsys.readouterr().out
    assert "Shard union: OK" in output
    assert "| 1 | 3 | 1.1 |" in output if keep_parent else "| 1 | 3 | 0.2 |" in output


@pytest.mark.parametrize("invalid", ["missing", "extra", "foreign-class", "wrong-name", "failure", "error",
                                     "already-parametrized", "unterminated-child"])
def test_union_rejects_runtime_mismatch(tmp_path, runtime_union_inputs, invalid, capsys):
    args, root = runtime_union_inputs
    if invalid == "missing":
        root.remove(root[3])
    elif invalid == "extra":
        ET.SubElement(root, "testcase", classname=root[0].get("classname"), name="test_other[x]")
    elif invalid == "foreign-class":
        root[1].set("classname", "backend.other")
    elif invalid == "wrong-name":
        root[3].set("name", "test_other")
    elif invalid in {"failure", "error"}:
        ET.SubElement(root[1], invalid)
        # Keep the passing parent and make the raw count equal selected (three).
        root.remove(root[4])
        root.remove(root[2])
    elif invalid == "already-parametrized":
        for path in [tmp_path / "baseline.txt", *tmp_path.glob("report-*.json")]:
            path.write_text(path.read_text().replace(
                "::test_stub_conforms_to_contract", "::test_stub_conforms_to_contract[GET /health]"))
        root[0].set("name", "test_stub_conforms_to_contract[GET /health]")
        root[1].set("name", "test_stub_conforms_to_contract[GET /health][extra]")
    else:
        root[1].set("name", "test_stub_conforms_to_contract[unfinished")
    ET.ElementTree(root).write(tmp_path / "backend-pytest-shard-1.xml")
    assert check_shard_union.main(args) == 1
    output = capsys.readouterr().out
    assert f"selected=3 junit={len(root)}" in output
    if invalid in {"missing", "wrong-name"}:
        assert "missing selected nodes=[('backend.contract.test_contract_stub', 'test_contract_checker_catches_violation')]" in output
    if invalid == "extra":
        assert "unaccounted JUnit nodes=[('backend.contract.test_contract_stub', 'test_other[x]')]" in output


def test_merge_junit_preserves_suites_and_case_details(tmp_path):
    documents = [
        '<testsuite name="one" tests="1"><testcase name="a" time="1"><system-err>log</system-err></testcase></testsuite>',
        '<testsuites><testsuite name="two"><properties><property name="x" value="y"/></properties>'
        '<testcase name="b"><skipped/></testcase></testsuite><testsuite name="three">'
        '<testcase name="c"><system-out>log</system-out></testcase></testsuite></testsuites>',
    ]
    paths = []
    for i, document in enumerate(documents):
        path = tmp_path / f"{i}.xml"
        path.write_text(document)
        paths.append(str(path))
    output = tmp_path / "merged.xml"
    assert merge_junit.main(["--output", str(output), *paths]) == 0
    root = ET.parse(output).getroot()
    assert root.tag == "testsuites"
    expected = [ET.fromstring(documents[0]), *ET.fromstring(documents[1])]
    assert [ET.tostring(s) for s in root] == [ET.tostring(s) for s in expected]


def test_serial_skips_guard(tmp_path, capsys):
    import check_serial_skips

    groups = tmp_path / "g.yaml"
    groups.write_text('version: 1\ntests:\n  - {"file": "tests/backend/api_app/test_pg.py", "group": "serial_pg"}\n'
                      '  - {"file": "tests/backend/unit/test_x.py", "group": "parallel"}\n')
    config = tmp_path / "c.json"
    config.write_text(json.dumps({"max_skipped": {"serial_pg": 1}, "min_passed": {"serial_pg": 1}}))

    def run(cases):
        junit = tmp_path / "j.xml"
        junit.write_text("<testsuites><testsuite>" + "".join(cases) + "</testsuite></testsuites>")
        return check_serial_skips.main([str(junit), "--groups", str(groups), "--config", str(config)])

    ok = '<testcase classname="backend.api_app.test_pg.TestA" name="a"/>'
    skip = '<testcase classname="backend.api_app.test_pg" name="s"><skipped message="no pg"/></testcase>'
    other = '<testcase classname="backend.unit.test_x" name="x"><skipped/></testcase>'
    assert run([ok, skip, other]) == 0
    assert run([ok, skip, skip]) == 1
    assert run([skip]) == 1
    assert "::error" in capsys.readouterr().out


def test_serial_skips_guard_counts_src_backend_tests(tmp_path, capsys):
    import check_serial_skips

    groups = tmp_path / "g.yaml"
    groups.write_text('version: 1\ntests:\n'
                      '  - {"file": "tests/backend/api_app/test_pg.py", "group": "serial_pg"}\n'
                      '  - {"file": "src/backend/tests/test_real_pg.py", "group": "serial_pg"}\n')
    config = tmp_path / "c.json"
    config.write_text(json.dumps({"max_skipped": {"serial_pg": 1}, "min_passed": {"serial_pg": 2}}))
    junit = tmp_path / "j.xml"
    junit.write_text('<testsuites><testsuite>'
                     '<testcase classname="backend.api_app.test_pg" name="a"/>'
                     '<testcase file="src/backend/tests/test_real_pg.py" name="b"/>'
                     '<testcase file="src/backend/tests/test_real_pg.py" name="s1"><skipped/></testcase>'
                     '<testcase classname="src.backend.tests.test_real_pg" name="s2"><skipped/></testcase>'
                     '<testcase classname="test_real_pg" name="s3"><skipped/></testcase>'
                     '</testsuite></testsuites>')
    args = [str(junit), "--groups", str(groups), "--config", str(config)]

    assert check_serial_skips.main(args) == 1
    assert "passed=2 skipped=3" in capsys.readouterr().out
    config.write_text(json.dumps({"max_skipped": {"serial_pg": 3}, "min_passed": {"serial_pg": 2}}))
    assert check_serial_skips.main(args) == 0


def test_serial_skips_guard_counts_module_skip(tmp_path, capsys):
    import check_serial_skips

    groups = tmp_path / "g.yaml"
    groups.write_text('version: 1\ntests:\n'
                      '  - {"file": "tests/backend/api_app/test_pg.py", "group": "serial_pg"}\n'
                      '  - {"file": "tests/backend/api_app/test_other_pg.py", "group": "serial_pg"}\n')
    config = tmp_path / "c.json"
    config.write_text(json.dumps({"max_skipped": {"serial_pg": 1}, "min_passed": {"serial_pg": 3}}))
    junit = tmp_path / "j.xml"
    junit.write_text('<testsuites><testsuite>'
                     '<testcase classname="" name="backend.api_app.test_pg">'
                     '<skipped message="collection skipped"/></testcase>'
                     '<testcase classname="backend.api_app.test_other_pg" name="a"/>'
                     '<testcase classname="backend.api_app.test_other_pg" name="b"/>'
                     '</testsuite></testsuites>')

    assert check_serial_skips.main([str(junit), "--groups", str(groups), "--config", str(config)]) == 1
    output = capsys.readouterr().out
    assert "passed=2 skipped=1" in output
    assert "min_passed=3" in output
    assert "::error" in output


@pytest.mark.parametrize("passed,min_passed,expected", [(1, 2, 1), (2, 2, 0), (0, 0, 1)])
def test_serial_skips_guard_min_passed(tmp_path, capsys, passed, min_passed, expected):
    import check_serial_skips

    groups = tmp_path / "g.yaml"
    groups.write_text('version: 1\ntests:\n'
                      '  - {"file": "tests/backend/api_app/test_pg.py", "group": "serial_pg"}\n')
    config = tmp_path / "c.json"
    config.write_text(json.dumps({"max_skipped": {"serial_pg": 1}, "min_passed": {"serial_pg": min_passed}}))
    junit = tmp_path / "j.xml"
    junit.write_text('<testsuites><testsuite>' + ''.join(
        f'<testcase classname="backend.api_app.test_pg" name="test_{i}"/>' for i in range(passed)) +
        '<testcase classname="backend.api_app.test_pg" name="s"><skipped/></testcase>'
        '</testsuite></testsuites>')

    assert check_serial_skips.main([str(junit), "--groups", str(groups), "--config", str(config)]) == expected
    output = capsys.readouterr().out
    assert f"passed={passed} skipped=1" in output
    assert f"min_passed={min_passed}" in output
    assert ("::error" in output) == bool(expected)


def test_union_rejects_duplicate_non_uuid_params(tmp_path):
    args, reports = union_inputs(tmp_path)
    nodes = ["backend/c.py::test_x[a]", "backend/c.py::test_x[b]"]
    baseline = tmp_path / "baseline.txt"
    baseline.write_text("\n".join(reports[0]["collected"][:2] + nodes))
    for report in reports:
        report["collected"] = reports[0]["selected"] + nodes
    reports[1]["selected"] = nodes
    assert check_shard_union.main(args + write_reports(tmp_path, reports)) == 0
    reports[1]["selected"] = [nodes[0], nodes[0]]
    assert check_shard_union.main(args + write_reports(tmp_path, reports)) == 1


@pytest.mark.parametrize("params", [("a", "b"), ("uuid-1", "uuid-2"),
                                    ("550e8400-e29b-41d4-a716-446655440000-a",
                                     "32f78a26-1111-4444-8888-123456789abc-b")])
def test_stable_id_preserves_non_uuid_parameters(params):
    assert check_shard_union.stable_id(f"a.py::test_x[{params[0]}]") != check_shard_union.stable_id(
        f"a.py::test_x[{params[1]}]")


@pytest.mark.parametrize("invalid", ["failure", "error", "zero", "duplicate-file", "duplicate-node",
                                     "duplicate-across-inputs", "zero-input-among-valid"])
def test_merge_rejects_bad_junit(tmp_path, invalid):
    root = ET.fromstring('<testsuite><testcase classname="backend.a" name="test_a"/></testsuite>')
    if invalid in {"failure", "error"}:
        ET.SubElement(root[0], invalid, message="bad result")
    elif invalid == "zero":
        root.clear()
    elif invalid == "duplicate-node":
        ET.SubElement(root, "testcase", classname="backend.a", name="test_a")
    path = tmp_path / "one.xml"
    ET.ElementTree(root).write(path)
    inputs = [str(path)]
    if invalid == "duplicate-file":
        inputs.append(str(path))
    elif invalid in {"duplicate-across-inputs", "zero-input-among-valid"}:
        second = tmp_path / "two.xml"
        second.write_text(ET.tostring(root, encoding="unicode") if invalid == "duplicate-across-inputs"
                          else '<testsuite/>')
        inputs.append(str(second))
    output = tmp_path / "merged.xml"
    assert merge_junit.main(["--output", str(output), *inputs]) == 1
    merged = ET.parse(output).getroot()
    if invalid in {"failure", "error"}:
        assert merged.find(f".//testcase/{invalid}").get("message") == "bad result"


@pytest.mark.parametrize("invalid", ["failure", "error", "zero", "too-few", "too-many",
                                     "duplicate-node", "duplicate-across-shards"])
def test_union_rejects_bad_junit(tmp_path, invalid):
    args, reports = union_inputs(tmp_path)
    roots = []
    for report in reports:
        root = ET.Element("testsuite")
        for node in report["selected"]:
            path, name = node.split("::")
            ET.SubElement(root, "testcase", classname=path[:-3].replace("/", "."), name=name, time="1.2")
        roots.append(root)
    if invalid in {"failure", "error"}:
        ET.SubElement(roots[1][0], invalid)
    elif invalid == "zero":
        roots[1].clear()
    elif invalid == "too-few":
        roots[0].remove(roots[0][1])
    elif invalid == "too-many":
        ET.SubElement(roots[1], "testcase", classname="backend", name="extra")
    elif invalid == "duplicate-node":
        roots[0][1].set("name", roots[0][0].get("name"))
        roots[0][1].set("classname", roots[0][0].get("classname"))
    else:
        roots[1][0].set("name", roots[0][0].get("name"))
        roots[1][0].set("classname", roots[0][0].get("classname"))
    for i, root in enumerate(roots, 1):
        ET.ElementTree(root).write(tmp_path / f"backend-pytest-shard-{i}.xml")
    assert check_shard_union.main(args + ["--junit", str(tmp_path)] + write_reports(tmp_path, reports)) == 1


@pytest.mark.parametrize("invalid", ["failure", "error", "duplicate", "zero", "foreign-failure", "foreign-error"])
def test_serial_rejects_bad_junit_at_minimum(tmp_path, invalid, capsys):
    import check_serial_skips

    groups = tmp_path / "groups.yaml"
    groups.write_text('tests:\n  - {file: tests/backend/test_pg.py, group: serial_pg}\n')
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"min_passed": {"serial_pg": 1190}, "max_skipped": {"serial_pg": 0}}))
    root = ET.Element("testsuite")
    for i in range(1190):
        ET.SubElement(root, "testcase", classname="backend.test_pg", name=f"test_{i}")
    if invalid == "zero":
        root.clear()
    else:
        case = ET.SubElement(root, "testcase", classname="backend.test_pg", name="bad")
        if invalid == "duplicate":
            case.set("name", "test_0")
        else:
            if invalid.startswith("foreign-"):
                case.set("classname", "backend.test_other")
            ET.SubElement(case, invalid.removeprefix("foreign-"))
    junit = tmp_path / "junit.xml"
    ET.ElementTree(root).write(junit)
    assert check_serial_skips.main([str(junit), "--groups", str(groups), "--config", str(config)]) == 1
    output = capsys.readouterr().out
    if invalid in {"failure", "error"}:
        assert "passed=1190 skipped=0 failed=1" in output


@pytest.mark.parametrize("invalid", ["ordinary-extra-child", "ordinary-child-replaces-parent"])
def test_union_rejects_ordinary_expansion(tmp_path, invalid, capsys):
    args, reports = union_inputs(tmp_path)
    for index, report in enumerate(reports, 1):
        root = ET.Element("testsuite")
        for node in report["selected"]:
            classname, name = check_shard_union.junit_node(node)
            ET.SubElement(root, "testcase", classname=classname, name=name)
        if index == 2:
            if invalid == "ordinary-child-replaces-parent":
                root.remove(root[0])
            ET.SubElement(root, "testcase", classname="backend.c", name="test_c[unexpected]")
        ET.ElementTree(root).write(tmp_path / f"backend-pytest-shard-{index}.xml")
    assert check_shard_union.main(args + ["--junit", str(tmp_path)] + write_reports(tmp_path, reports)) == 1
    output = capsys.readouterr().out
    assert "unaccounted JUnit nodes=[('backend.c', 'test_c[unexpected]')]" in output
    if invalid == "ordinary-child-replaces-parent":
        assert "missing selected nodes=[('backend.c', 'test_c')]" in output


@pytest.mark.parametrize("invalid", ["missing-runtime-child", "all-runtime-children-missing",
                                     "extra-runtime-child", "same-count-wrong-child"])
def test_union_rejects_incomplete_runtime_set(tmp_path, runtime_union_inputs, invalid, capsys):
    args, root = runtime_union_inputs
    if invalid in {"missing-runtime-child", "all-runtime-children-missing"}:
        root.remove(root[2])
        if invalid == "all-runtime-children-missing":
            root.remove(root[1])
    elif invalid == "extra-runtime-child":
        ET.SubElement(root, "testcase", classname=root[0].get("classname"),
                      name="test_stub_conforms_to_contract[GET /unexpected]")
    else:
        root[2].set("name", "test_stub_conforms_to_contract[GET /unexpected]")
    ET.ElementTree(root).write(tmp_path / "backend-pytest-shard-1.xml")
    assert check_shard_union.main(args) == 1
    output = capsys.readouterr().out
    if invalid != "extra-runtime-child":
        assert "test_stub_conforms_to_contract[GET /me]" in output
    if invalid in {"extra-runtime-child", "same-count-wrong-child"}:
        assert "unaccounted JUnit nodes=[('backend.contract.test_contract_stub', 'test_stub_conforms_to_contract[GET /unexpected]')]" in output


def test_runtime_allowlist_matches_schema_and_pytest_evidence():
    from conftest import REPO

    schema = json.loads((REPO / "tests/backend/contract/openapi_v1_stub.json").read_text())
    parent = ("backend.contract.test_contract_stub", "test_stub_conforms_to_contract")
    methods = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
    children = {(parent[0], f"{parent[1]}[{method.upper()} {path}]")
                for path, item in schema["paths"].items() for method in item if method in methods}
    assert check_shard_union.RUNTIME_CHILDREN == {parent: children}
    root = ET.parse(Path(__file__).parent / "fixtures/contract-runtime-junit.xml").getroot()
    recorded = {(c.get("classname"), c.get("name")) for c in root}
    assert recorded == children | {parent, (parent[0], "test_contract_checker_catches_violation"),
                                  (parent[0], "test_stub_paths_exist_in_api_contract_doc")}


def junit_entry(entry, tmp_path, root):
    """Use the same document through all four executable validation paths."""
    import check_serial_skips
    from junit_validation import validate_junit

    args, reports = union_inputs(tmp_path)
    path = tmp_path / "backend-pytest-shard-2.xml"
    ET.ElementTree(root).write(path)
    if entry == "shared-validator":
        try:
            validate_junit(ET.parse(path).getroot())
        except ValueError:
            return 1
        return 0
    if entry == "merge":
        return merge_junit.main(["--output", str(tmp_path / "merged.xml"), str(path)])
    if entry == "serial":
        config = tmp_path / "serial.json"
        config.write_text(json.dumps({"min_passed": {"serial_pg": 1}, "max_skipped": {"serial_pg": 1}}))
        return check_serial_skips.main([str(path), "--groups", str(tmp_path / "ci-groups.yaml"),
                                       "--config", str(config)])
    (tmp_path / "backend-pytest-shard-1.xml").write_text(
        '<testsuite><testcase classname="backend.a" name="test_a"/>'
        '<testcase classname="backend.b" name="test_b"/></testsuite>')
    return check_shard_union.main(args + ["--junit", str(tmp_path)] + write_reports(tmp_path, reports))


@pytest.mark.parametrize("entry", ["union", "merge", "serial", "shared-validator"])
@pytest.mark.parametrize("invalid", ["count-mismatch", "tests", "failures", "errors", "skipped", "disabled",
                                     "negative", "non-integer", "nested-outer", "nested-inner"])
def test_junit_rejects_declared_count_mismatch(tmp_path, entry, invalid):
    root = ET.fromstring('<testsuite tests="1" failures="0" errors="0" skipped="0" disabled="0">'
                         '<testcase classname="backend.c" name="test_c"/></testsuite>')
    if invalid == "count-mismatch":
        # T-G15 exact declarations: a passing detail, tests=999 and failures=1.
        root.set("tests", "999")
        root.set("failures", "1")
    elif invalid in {"tests", "failures", "errors", "skipped", "disabled"}:
        root.set(invalid, "2" if invalid == "tests" else "1")
    elif invalid in {"negative", "non-integer"}:
        root.set("tests", "-1" if invalid == "negative" else "1.0")
    else:
        outer = ET.Element("testsuites", tests="1", failures="0", errors="0", skipped="0")
        outer.append(root)
        (outer if invalid == "nested-outer" else root).set("tests", "2")
        root = outer
    assert junit_entry(entry, tmp_path, root) == 1


@pytest.mark.parametrize("entry", ["union", "merge", "serial", "shared-validator"])
def test_junit_accepts_consistent_nested_counts(tmp_path, entry):
    root = ET.fromstring('<testsuites tests="1" failures="0" errors="0" skipped="0">'
                         '<testsuite tests="1" failures="0" errors="0" skipped="0">'
                         '<testsuite tests="1"><testcase classname="backend.c" name="test_c"/>'
                         '</testsuite></testsuite></testsuites>')
    assert junit_entry(entry, tmp_path, root) == 0


def test_junit_nested_skips_count_details_once():
    from junit_validation import validate_junit

    root = ET.fromstring('<testsuites tests="3" skipped="1" failures="0" errors="0">'
                         '<testsuite tests="2" skipped="1"><testcase name="a"/>'
                         '<testsuite tests="1" skipped="1"><testcase name="b"><skipped/>'
                         '</testcase></testsuite></testsuite>'
                         '<testsuite tests="1" skipped="0"><testcase name="c"/></testsuite></testsuites>')
    assert [case.get("name") for case in validate_junit(root)] == ["a", "b", "c"]
    root.set("skipped", "0")
    with pytest.raises(ValueError, match="skipped=.*differs from details=1"):
        validate_junit(root)
