"""Tests for safe expression evaluation."""

import pytest

from hermes_mobile.tools.security import safe_calculate


class TestSafeCalculate:
    def test_basic_arithmetic(self):
        assert safe_calculate("2 + 3") == 5
        assert safe_calculate("10 - 4") == 6
        assert safe_calculate("3 * 7") == 21
        assert safe_calculate("15 / 3") == 5.0

    def test_floor_division(self):
        assert safe_calculate("17 // 5") == 3

    def test_modulo(self):
        assert safe_calculate("17 % 5") == 2

    def test_power(self):
        assert safe_calculate("2 ** 10") == 1024

    def test_unary_operators(self):
        assert safe_calculate("-5") == -5
        assert safe_calculate("+3") == 3

    def test_parentheses(self):
        assert safe_calculate("(2 + 3) * 4") == 20

    def test_math_functions(self):
        assert safe_calculate("abs(-10)") == 10
        assert safe_calculate("round(3.7)") == 4
        assert safe_calculate("min(5, 2, 8)") == 2
        assert safe_calculate("max(5, 2, 8)") == 8
        assert safe_calculate("int(3.14)") == 3
        assert safe_calculate("float(3)") == 3.0
        assert safe_calculate("str(42)") == "42"
        assert safe_calculate("bool(1)") is True
        import math

        assert safe_calculate("sqrt(9)") == 3.0
        assert safe_calculate("ceil(3.2)") == 4
        assert safe_calculate("floor(3.9)") == 3

    def test_comparisons(self):
        assert safe_calculate("3 < 5") is True
        assert safe_calculate("3 > 5") is False
        assert safe_calculate("3 <= 3") is True
        assert safe_calculate("5 >= 3") is True
        assert safe_calculate("3 == 3") is True
        assert safe_calculate("3 != 4") is True

    def test_boolean_operations(self):
        assert safe_calculate("True and False") is False
        assert safe_calculate("True or False") is True

    def test_constants(self):
        import math

        assert abs(safe_calculate("pi") - math.pi) < 1e-10
        assert abs(safe_calculate("e") - math.e) < 1e-10

    def test_complex_expressions(self):
        assert safe_calculate("2 + 3 * 4") == 14
        assert safe_calculate("(2 + 3) * 4") == 20
        assert safe_calculate("2 ** 3 + 1") == 9

    def test_unsafe_attribute_access_returns_error(self):
        result = safe_calculate("__import__('os')")
        assert isinstance(result, str)
        assert "unsafe" in result.lower()

    def test_unsafe_import_returns_error(self):
        # import statements can't be parsed by eval mode, so this returns a syntax error
        result = safe_calculate("import os")
        assert isinstance(result, str)
        assert "error" in result.lower() or "unsafe" in result.lower()

    def test_unsafe_subscript_returns_error(self):
        result = safe_calculate("[1, 2, 3][0]")
        assert isinstance(result, str)
        assert "unsafe" in result.lower()

    def test_unsafe_lambda_returns_error(self):
        result = safe_calculate("lambda x: x + 1")
        assert isinstance(result, str)
        assert "unsafe" in result.lower() or "error" in result.lower()

    def test_unsafe_comprehension_returns_error(self):
        result = safe_calculate("[x for x in [1, 2, 3]]")
        assert isinstance(result, str)
        assert "unsafe" in result.lower() or "error" in result.lower()

    def test_empty_expression_returns_error(self):
        result = safe_calculate("")
        assert isinstance(result, str)
        assert "error" in result.lower() or "empty" in result.lower()

    def test_nonexistent_function_returns_error(self):
        result = safe_calculate("nonexistent()")
        assert isinstance(result, str)

    def test_operator_precedence(self):
        assert safe_calculate("2 + 3 * 4 ** 2") == 2 + 3 * 16

    def test_float_division(self):
        result = safe_calculate("10 / 4")
        assert isinstance(result, float)
        assert result == 2.5
