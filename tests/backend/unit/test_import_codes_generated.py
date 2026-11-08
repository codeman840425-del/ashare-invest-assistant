"""expected.json `generated_cases` 的运行时用例占位（T-T01a）。

这些提示码需要运行时构造输入（超大文件、含 NUL、随机字节、未来日期、非交易日……），不落盘为夹具。
每条用例在解析器落地前 skip；落地后改为：按 `input` 构造 → 调 `app.importing.registry` 预览 → 断言 `expect`。
构造时只用虚构值（股东代码按 ^A0{8}[0-9]$ 现场生成），不写入仓库。
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.import_case]

TESTS_DIR = Path(__file__).resolve().parents[2]
EXP = json.loads((TESTS_DIR / "fixtures/broker_statements/fmt_a/expected.json").read_text(encoding="utf-8"))
BACKEND_DIR = Path(os.environ.get("AIA_BACKEND_DIR", TESTS_DIR.parent / "src" / "backend"))


def _importing_available() -> bool:
    if not (BACKEND_DIR / "app").is_dir():
        return False
    sys.path.insert(0, str(BACKEND_DIR))
    try:
        return importlib.util.find_spec("app.importing.registry") is not None
    except (ModuleNotFoundError, ImportError):
        return False
    finally:
        sys.path.remove(str(BACKEND_DIR))


HAS_IMPORTING = _importing_available()


@pytest.mark.parametrize("gid", sorted(EXP["generated_cases"]))
def test_generated_case(gid: str) -> None:
    case = EXP["generated_cases"][gid]
    assert case["input"] and case["expect"]["codes_include"]
    if not HAS_IMPORTING:
        pytest.skip(f"{gid}（{case['code']}）：等待 app.importing.registry 落地（T-B 系列）；期望已就绪")
    pytest.xfail(f"{gid}：app.importing.registry 已存在，但运行时构造器尚未编写（T-T 后续）")
