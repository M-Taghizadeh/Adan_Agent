import pytest

from app.tools.calculator import CalculatorError, safe_calculate


def test_basic_arithmetic():
    assert safe_calculate("2 + 3 * 4")["result"] == 14


def test_pct_helper():
    out = safe_calculate("pct(250, 1000)")
    assert out["result"] == 25.0


def test_pct_change():
    out = safe_calculate("pct_change(120, 100)")
    assert out["result"] == 20.0


def test_rejects_names():
    with pytest.raises(CalculatorError):
        safe_calculate("__import__('os').system('echo hi')")


def test_division_by_zero():
    with pytest.raises(CalculatorError):
        safe_calculate("1 / 0")


def test_avg_helper():
    assert safe_calculate("avg(10, 20, 30)")["result"] == 20.0


def test_wrong_argument_count_is_a_calculator_error():
    with pytest.raises(CalculatorError):
        safe_calculate("pct(1)")
    with pytest.raises(CalculatorError):
        safe_calculate("avg()")
