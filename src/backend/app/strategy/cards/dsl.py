# ruff: noqa: ANN401
"""Bounded, non-executing AST interpreter for imported-card fixture validation.

No eval/exec, Python attribute lookup, IO, or fixture expectation is available here.
Series inputs must already be valid, as-of-adjusted bars; production features are T-B72.
"""

from __future__ import annotations

import ast
import operator
import re
from decimal import Decimal, InvalidOperation
from typing import Any

FUNCTIONS = frozenset(
    [
        "ma",
        "ema",
        "atr",
        "highest",
        "lowest",
        "ref",
        "cross_up",
        "cross_down",
        "between",
        "rank_pct",
        "pct_change",
        "max2",
        "min2",
        "greatest",
        "least",
        "std",
        "ts_pct_rank",
        "rank_pct_in",
        "min",
        "max",
    ]
)
CONTEXT = frozenset(
    [
        "ctx.last_price",
        "ctx.cost_price",
        "ctx.cost_price_qfq",
        "ctx.position_weight",
        "ctx.sector_weight",
        "ctx.highest_close_since_entry",
        "ctx.highest_close_since_entry_qfq",
        "ctx.now_hhmm",
        "ctx.holding_days",
        "ctx.sellable_qty",
        "ctx.max_r_reached",
        "plan.stop_loss",
        "plan.take_profit",
        "plan.entry_price",
        "plan.entry_price_qfq",
    ]
)
_TEMPORAL = re.compile(r"^(.*?)\s+(for|within)\s+(\d+|p\.[a-z][a-z0-9_]*)\s+(days|bars)$")
_BIN = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_CMP = {
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
}


def symbol(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return node.value.id + "." + node.attr
    return None


def parse(
    expr: str, features: set[str], params: set[str], role: str, eval_time: str
) -> tuple[ast.expr, str | None, str | None]:
    if not isinstance(expr, str) or len(expr) > 300:
        raise ValueError("dsl_length")
    temporal = _TEMPORAL.fullmatch(expr)
    text, mode, count = (temporal[1], temporal[2], temporal[3]) if temporal else (expr, None, None)
    try:
        tree = ast.parse(text, mode="eval").body
    except (SyntaxError, RecursionError):
        raise ValueError("invalid_dsl") from None
    allowed = features | {"p." + key for key in params} | CONTEXT

    def check(node: ast.AST, depth: int) -> None:
        if depth > 6:
            raise ValueError("dsl_depth")
        name = symbol(node)
        if name is not None:
            if name not in allowed:
                raise ValueError("dsl_unknown_symbol")
            if name.startswith(("ctx.", "plan.")):
                if name == "ctx.now_hhmm":
                    if eval_time == "daily_close":
                        raise ValueError("intraday_ctx_in_daily_rule")
                elif role not in {"hold", "weakening", "exit"}:
                    raise ValueError("dsl_context_role")
            return
        if isinstance(node, ast.Constant) and type(node.value) in {int, float, str, bool}:
            if (
                isinstance(node.value, int | float)
                and not isinstance(node.value, bool)
                and abs(node.value) > 1e15
            ):
                raise ValueError("dsl_literal_bound")
            return
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in FUNCTIONS
            and not node.keywords
        ):
            expected = (
                1 if node.func.id in {"atr", "rank_pct"} else 3 if node.func.id == "between" else 2
            )
            if len(node.args) != expected:
                raise ValueError("dsl_function_arity")
            for arg in node.args:
                check(arg, depth + 1)
            return
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
            check(node.left, depth + 1)
            check(node.right, depth + 1)
            return
        if isinstance(node, ast.Compare) and all(type(op) in _CMP for op in node.ops):
            check(node.left, depth + 1)
            for child in node.comparators:
                check(child, depth + 1)
            return
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And | ast.Or):
            for child in node.values:
                check(child, depth + 1)
            return
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not | ast.UAdd | ast.USub):
            check(node.operand, depth + 1)
            return
        raise ValueError("unsafe_dsl_node")

    check(tree, 1)
    if count is not None and count.startswith("p.") and count[2:] not in params:
        raise ValueError("dsl_unknown_parameter")
    return tree, mode, count


def decimal(value: Any) -> Any:
    if type(value) in {int, float}:
        return Decimal(str(value))
    return value


class Interpreter:
    def __init__(
        self,
        features: dict[str, Any],
        series: dict[str, Any],
        context: dict[str, Any],
        params: dict[str, Any],
    ) -> None:
        self.features, self.series, self.context, self.params = features, series, context, params
        self.columns: dict[str, Any] = {}
        self.materialize = True
        self.inputs: dict[str, Any] = {}
        self.computed: dict[str, Any] = {}

    def window(self, node: ast.expr, count: int, offset: int) -> list[Any] | None:
        if count < 1 or count > 250:
            return None
        values = [self.value(node, offset + index) for index in range(count - 1, -1, -1)]
        return None if any(value is None for value in values) else values

    def value(self, node: ast.expr, offset: int = 0) -> Any:
        name = symbol(node)
        if name is not None:
            if name.startswith("p."):
                value = self.params.get(name[2:])
            elif name in self.series:
                values = self.series[name]
                value = values[-1 - offset] if offset < len(values) else None
            elif name.startswith("f."):
                value = self.features.get(name) if offset == 0 else None
            else:
                value = self.context.get(name)
            self.inputs[name + (f"@-{offset}" if offset else "")] = value
            return decimal(value)
        if isinstance(node, ast.Constant):
            return decimal(node.value)
        if isinstance(node, ast.Call):
            try:
                result = self.call(node, offset)
            except (ArithmeticError, InvalidOperation, TypeError, ValueError):
                result = None
            self.computed[ast.unparse(node) + (f"@-{offset}" if offset else "")] = result
            return result
        if isinstance(node, ast.BoolOp):
            values = [self.value(child, offset) for child in node.values]
            if isinstance(node.op, ast.And):
                return False if False in values else None if None in values else True
            return True if True in values else None if None in values else False
        if isinstance(node, ast.UnaryOp):
            value = self.value(node.operand, offset)
            if value is None:
                return None
            if isinstance(node.op, ast.Not):
                return not value
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp):
            left, right = self.value(node.left, offset), self.value(node.right, offset)
            if left is None or right is None:
                return None
            try:
                result = _BIN[type(node.op)](left, right)
                self.computed[ast.unparse(node)] = result
                return result
            except (ArithmeticError, TypeError):
                return None
        if isinstance(node, ast.Compare):
            values = [self.value(child, offset) for child in [node.left, *node.comparators]]
            if any(value is None for value in values):
                return None
            return all(
                _CMP[type(op)](values[index], values[index + 1])
                for index, op in enumerate(node.ops)
            )
        raise ValueError("unsupported_ast")

    def call(self, node: ast.Call, offset: int) -> Any:
        from app.features.pipeline import indicator

        return indicator(self, node, offset)

    def evaluate(self, parsed: tuple[ast.expr, str | None, str | None]) -> bool | None:
        node, mode, count = parsed
        if mode is None:
            value = self.value(node)
            return None if value is None else bool(value)
        n = self.params.get(count[2:]) if count and count.startswith("p.") else int(count or 0)
        if type(n) is not int or not 1 <= n <= 250:
            return None
        values = [self.value(node, offset) for offset in range(n)]
        if mode == "for":
            return False if False in values else None if None in values else True
        return True if True in values else None if None in values else False
