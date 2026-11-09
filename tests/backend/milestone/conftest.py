# T-T35：milestone 目录专属插件（T-T21 家族）。importlib 模式下同名裸模块不可直接导入，
# 先把本目录挂到 sys.path，再以插件模块名加载（与旧行为 `-p tt21_plugin` 等价，但无需手工传参）。
# 注意：pytest_plugins 只允许在顶层 conftest 定义（rootdir 级），子目录会报 non-top-level 错误；
# 这里改为显式 import 模块本体——模块内的 fixture/hookimpl 会正常注册。
import sys
from pathlib import Path

_DIR = Path(__file__).resolve().parent
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))

import tt21_plugin  # noqa: F401,E402
