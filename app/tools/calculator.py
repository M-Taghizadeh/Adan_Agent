"""Safe calculator tool for arithmetic used by agents."""

from __future__ import annotations

import ast
import json
import math
import operator
from typing import Any

from langchain_core.tools import tool

# فقط اینها مجاز هستند: عملگرهای دو طرفه + عملگرهای یک طرفه + توابع مجاز
# عملگرهای دو طرفه
_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

# عملگرهای یک طرفه
_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

# توبع مجاز
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
    # اگر گره، پوشش بیرونی عبارت است، محتوای داخلش (body) را حساب کن
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)

    # اگر گره یک عدد (صحیح یا اعشاری) است، همان را برگردان (پایان بازگشت)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value

    # اگر گره یک عملیات دوطرفه است (مثل a + b)
    if isinstance(node, ast.BinOp):
        # نوع عملگر را بگیر (مثلاً ast.Add)
        op_type = type(node.op)
        # اگر عملگر در لیست مجاز نیست، خطا بده
        if op_type not in _BIN_OPS:
            raise CalculatorError(f"Unsupported operator: {op_type.__name__}")
        # سمت چپ و راست را با بازگشت حساب کن
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        # جلوگیری از تقسیم بر صفر در / و // و %
        if op_type in (ast.Div, ast.FloorDiv, ast.Mod) and right == 0:
            raise CalculatorError("Division by zero")
        # جلوگیری از توان‌های خیلی بزرگ (که سیستم را قفل می‌کنند)
        if op_type is ast.Pow and (abs(left) > 1e6 or abs(right) > 10):
            raise CalculatorError("Exponentiation too large")
        # عملگر را روی دو طرف اجرا کن و نتیجه را برگردان
        return _BIN_OPS[op_type](left, right)

    # اگر گره یک عملیات تک‌طرفه است (مثل -5)
    if isinstance(node, ast.UnaryOp):
        # نوع علامت را بگیر
        op_type = type(node.op)
        # اگر علامت مجاز نیست (فقط + و - مجازند)، خطا بده
        if op_type not in _UNARY_OPS:
            raise CalculatorError(f"Unsupported unary operator: {op_type.__name__}")
        # مقدار عدد را حساب کن و علامت را رویش اعمال کن
        return _UNARY_OPS[op_type](_eval_node(node.operand))

    # اگر گره فراخوانی تابع است و اسم تابع ساده است (مثل sqrt(...)، نه os.system(...))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        # اسم تابع را بگیر
        name = node.func.id
        # اگر تابع در لیست مجاز نیست، خطا بده
        if name not in _ALLOWED_FUNCS:
            raise CalculatorError(f"Function not allowed: {name}")
        # هر آرگومان را هم با همین تابع (بازگشتی) حساب کن
        args = [_eval_node(a) for a in node.args]
        # تابع را با آرگومان‌ها اجرا کن و نتیجه را برگردان
        return _ALLOWED_FUNCS[name](*args)

    # هر چیز دیگر (متغیر، متن، لیست، lambda و...) ممنوع است
    raise CalculatorError("Only numeric expressions are allowed")


# نگهبان ورودی = عبارت خالی نباشد و طولش بیشتر از 200 کاراکتر نباشد و از ظر دستوری درست باشد
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


# متن داک استرینگ به مدل زبانی توضیح میدهد این ابزار چکار میکند
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
