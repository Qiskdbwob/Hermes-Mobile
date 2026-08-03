"""Tests for safe expression evaluation."""

import ast

import pytest

from hermes_mobile.tools.security import (
    ExpressionEvaluator,
    ExpressionVisitor,
    is_safe_expression,
    safe_calculate,
)


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


class TestExpressionVisitor:
    def test_valid_expression(self):
        visitor = ExpressionVisitor()
        tree = ast.parse("2 + 3", mode="eval")
        visitor.visit(tree)
        assert visitor.valid is True

    def test_invalid_name(self):
        visitor = ExpressionVisitor()
        tree = ast.parse("foo", mode="eval")
        visitor.visit(tree)
        # Bare Name is not caught by ExpressionVisitor (no visit_Name)
        assert visitor.valid is True

    def test_invalid_attribute(self):
        visitor = ExpressionVisitor()
        tree = ast.parse("foo.bar", mode="eval")
        visitor.visit(tree)
        assert visitor.valid is False

    def test_invalid_lambda(self):
        visitor = ExpressionVisitor()
        tree = ast.parse("lambda x: x", mode="eval")
        visitor.visit(tree)
        assert visitor.valid is False

    def test_invalid_listcomp(self):
        visitor = ExpressionVisitor()
        tree = ast.parse("[x for x in [1]]", mode="eval")
        visitor.visit(tree)
        assert visitor.valid is False

    def test_invalid_dictcomp(self):
        visitor = ExpressionVisitor()
        tree = ast.parse("{k: v for k, v in []}", mode="eval")
        visitor.visit(tree)
        assert visitor.valid is False

    def test_invalid_setcomp(self):
        visitor = ExpressionVisitor()
        tree = ast.Expression(
            body=ast.SetComp(
                generators=[
                    ast.comprehension(
                        target=ast.Name(id="x"),
                        iter=ast.List(elts=[ast.Constant(value=1)], ctx=ast.Load()),
                        ifs=[],
                        is_async=0,
                    )
                ],
                elt=ast.Name(id="x"),
            )
        )
        visitor.visit(tree)
        assert visitor.valid is False

    def test_invalid_generator_exp(self):
        visitor = ExpressionVisitor()
        tree = ast.Expression(
            body=ast.GeneratorExp(
                generators=[
                    ast.comprehension(
                        target=ast.Name(id="x"),
                        iter=ast.List(elts=[ast.Constant(value=1)], ctx=ast.Load()),
                        ifs=[],
                        is_async=0,
                    )
                ],
                elt=ast.Name(id="x"),
            )
        )
        visitor.visit(tree)
        assert visitor.valid is False


class TestExpressionEvaluator:
    def test_unknown_name_raises(self):
        evaluator = ExpressionEvaluator()
        tree = ast.parse("nonexistent_variable", mode="eval")
        with pytest.raises(ValueError, match="Unknown name"):
            evaluator.visit(tree)

    def test_unsafe_operator_raises(self):
        evaluator = ExpressionEvaluator()
        # ~ is bitwise invert, not in SAFE_OPERATORS
        tree = ast.parse("~1", mode="eval")
        with pytest.raises(ValueError, match="Unsafe operator"):
            evaluator.visit(tree)

    def test_unsafe_function_raises(self):
        evaluator = ExpressionEvaluator()
        tree = ast.parse("unsafe_func(42)", mode="eval")
        with pytest.raises(ValueError, match="Unsafe function"):
            evaluator.visit(tree)

    def test_empty_stack_returns_none(self):
        evaluator = ExpressionEvaluator()
        assert evaluator.result() is None


class TestIsSafeExpression:
    def test_safe_arithmetic(self):
        assert is_safe_expression("2 + 3") is True

    def test_unsafe_attribute(self):
        assert is_safe_expression("os.system") is False

    def test_unsafe_subscript(self):
        assert is_safe_expression("[1][0]") is False

    def test_unsafe_lambda(self):
        assert is_safe_expression("lambda x: x") is False

    def test_invalid_syntax(self):
        assert is_safe_expression("2 +") is False

    def test_import_unsafe(self):
        visitor = ExpressionVisitor()
        visitor.visit(ast.Import(names=[ast.alias(name="os")]))
        assert visitor.valid is False

    def test_import_from_unsafe(self):
        visitor = ExpressionVisitor()
        visitor.visit(ast.ImportFrom(module="os", names=[ast.alias(name="system")], level=0))
        assert visitor.valid is False


class TestSafeCalculateEdgeCases:
    def test_unknown_bare_name(self):
        result = safe_calculate("some_undefined_var")
        assert isinstance(result, str)
        assert "error" in result.lower()

    def test_bitwise_not(self):
        result = safe_calculate("~1")
        assert isinstance(result, str)
        assert "unsafe" in result.lower()

    def test_expression_statement(self):
        # Test that an expression that produces no result returns an error
        result = safe_calculate("     ")
        assert isinstance(result, str)

    def test_whitespace_expression(self):
        result = safe_calculate("  42  ")
        assert result == 42

    def test_unsafe_binary_operator(self):
        result = safe_calculate("1 << 2")
        assert isinstance(result, str)

    def test_expr_node_evaluator(self):
        evaluator = ExpressionEvaluator()
        module = ast.parse("42", mode="exec")
        evaluator.visit(module.body[0])
        assert evaluator.result() == 42

    def test_unknown_bool_op(self):
        evaluator = ExpressionEvaluator()
        tree = ast.Expression(body=ast.BoolOp(op=ast.Or(), values=[ast.Constant(value=True)]))
        evaluator.visit(tree)
        assert evaluator.result() is True

    def test_unsafe_comparison_is(self):
        result = safe_calculate("1 is 1")
        assert isinstance(result, str)

    def test_empty_result_after_eval(self):
        evaluator = ExpressionEvaluator()
        tree = ast.parse("42", mode="eval")
        evaluator.visit(tree)
        evaluator._stack.clear()
        assert evaluator.result() is None

    def test_none_constant_is_empty(self):
        result = safe_calculate("None")
        assert isinstance(result, str)
        assert "empty" in result.lower() or "error" in result.lower()

    def test_unknown_bool_op_ast(self):
        node = ast.BoolOp(
            op=ast.Or(),
            values=[ast.Constant(value=True), ast.Constant(value=False)],
        )
        evaluator = ExpressionEvaluator()
        evaluator.visit(node)
        assert evaluator.result() is True

    def test_unknown_bool_op_raises(self):
        class CustomBoolOp(ast.boolop):
            pass

        node = ast.BoolOp(
            op=CustomBoolOp(),
            values=[ast.Constant(value=True), ast.Constant(value=False)],
        )
        evaluator = ExpressionEvaluator()
        with pytest.raises(ValueError, match="Unknown bool op"):
            evaluator.visit(node)
