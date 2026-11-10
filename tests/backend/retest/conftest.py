# T-T82 接线：tests/backend/retest 用例直接 import 被测模块 retest.t_r58.splice（离线科学命名空间，
# 位于 src/backend/retest/，不属生产 app 包）。importlib 收集模式下把 src/backend 挂到 sys.path，
# 与 selfchecks（PYTHONPATH）同一解析来源；不改动任何业务文件。
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[3] / "src" / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))
