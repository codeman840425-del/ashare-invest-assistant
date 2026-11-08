"""golden 逐字段比较工具（T-T01）。

`diff_fields(expected, actual)` 返回不一致字段的路径列表（如 `expected.reasons[1].code`），
空列表表示完全一致。规则：
- dict：键集合必须相同（多键、少键都算差异）；
- list：长度与顺序都必须一致（理由/反证顺序属于输出的一部分）；
- 标量：严格相等；十进制一律用字符串表示（与 api-contract §1 一致），不做浮点容差。
"""

from __future__ import annotations

from typing import Any


def diff_fields(expected: Any, actual: Any, path: str = "$") -> list[str]:
    if isinstance(expected, dict) and isinstance(actual, dict):
        out: list[str] = []
        for key in sorted(set(expected) | set(actual)):
            sub = f"{path}.{key}"
            if key not in actual:
                out.append(f"{sub}（缺失）")
            elif key not in expected:
                out.append(f"{sub}（多出）")
            else:
                out.extend(diff_fields(expected[key], actual[key], sub))
        return out
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return [f"{path}（长度 {len(expected)} ≠ {len(actual)}）"]
        out = []
        for i, (e, a) in enumerate(zip(expected, actual)):
            out.extend(diff_fields(e, a, f"{path}[{i}]"))
        return out
    if type(expected) is not type(actual) or expected != actual:
        return [path]
    return []
