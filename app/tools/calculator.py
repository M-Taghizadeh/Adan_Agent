"""Safe calculator tool for arithmetic used by agents."""

from __future__ import annotations

import ast
import json
import math
import operator
from typing import Any

from langchain_core.tools import tool

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_ALLOWED_FUNCS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sqrt": math.sqrt,
    "pct": lambda part, whole: (part / whole) * 100 if whole else 0.0,
    "pct_change": lambda new, old: ((new - old) / old) * 100 if old else 0.0,
    "avg": lambda *xs: sum(xs) / len(xs),
}


class CalculatorError(ValueError):
    pass


def _eval_node(node: ast.AST) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _BIN_OPS:
            raise CalculatorError(f"Unsupported operator: {op_type.__name__}")
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if op_type in (ast.Div, ast.FloorDiv, ast.Mod) and right == 0:
            raise CalculatorError("Division by zero")
        if op_type is ast.Pow and (abs(left) > 1e6 or abs(right) > 10):
            raise CalculatorError("Exponentiation too large")
        return _BIN_OPS[op_type](left, right)
    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _UNARY_OPS:
            raise CalculatorError(f"Unsupported unary operator: {op_type.__name__}")
        return _UNARY_OPS[op_type](_eval_node(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        name = node.func.id
        if name not in _ALLOWED_FUNCS:
            raise CalculatorError(f"Function not allowed: {name}")
        args = [_eval_node(a) for a in node.args]
        return _ALLOWED_FUNCS[name](*args)
    raise CalculatorError("Only numeric expressions are allowed")


def safe_calculate(expression: str) -> dict[str, Any]:
    """Evaluate a restricted arithmetic expression safely."""
    expr = (expression or "").strip()
    if not expr:
        raise CalculatorError("Empty expression")
    if len(expr) > 200:
        raise CalculatorError("Expression too long")

    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise CalculatorError(f"Invalid expression: {exc.msg}") from exc

    try:
        result = _eval_node(tree)
    except CalculatorError:
        raise
    except (TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
        # e.g. wrong argument count: pct(1) or avg()
        raise CalculatorError(f"Could not evaluate expression: {exc}") from exc
    if isinstance(result, float):
        result = round(result, 6)
    return {"expression": expr, "result": result}


@tool("calculator")
def calculator_tool(expression: str) -> str:
    """Evaluate a math expression and return JSON {"ok", "expression", "result"}.

    Supports + - * / // % **, abs, round, min, max, sqrt, avg(a, b, ...),
    pct(part, whole) -> part as a percent of whole,
    pct_change(new, old) -> percent change from old to new.
    Use this for ALL arithmetic on numbers retrieved from the database.
    """
    try:
        out = safe_calculate(expression)
        return json.dumps({"ok": True, **out})
    except CalculatorError as exc:
        return json.dumps({"ok": False, "expression": expression, "error": str(exc)})
