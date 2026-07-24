"""Secure computation and expression evaluation.

Replaces the unsafe eval() in calculate tool with safe alternatives.
"""

from __future__ import annotations

import ast
import math
import operator

SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

SAFE_FUNCTIONS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "len": len,
    "int": int,
    "float": float,
    "str": str,
    "bool": bool,
    "sqrt": math.sqrt,
    "ceil": math.ceil,
    "floor": math.floor,
    "log": math.log,
    "log10": math.log10,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "pi": math.pi,
    "e": math.e,
}


class ExpressionVisitor(ast.NodeVisitor):
    """Validate that an AST only contains safe operations."""

    def __init__(self):
        self.valid = True

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id in SAFE_FUNCTIONS:
            self.generic_visit(node)
        else:
            self.valid = False

    def visit_Attribute(self, node):
        self.valid = False

    def visit_Subscript(self, node):
        self.valid = False

    def visit_Lambda(self, node):
        self.valid = False

    def visit_ListComp(self, node):
        self.valid = False

    def visit_DictComp(self, node):
        self.valid = False

    def visit_SetComp(self, node):
        self.valid = False

    def visit_GeneratorExp(self, node):
        self.valid = False

    def visit_Import(self, node):
        self.valid = False

    def visit_ImportFrom(self, node):
        self.valid = False


class ExpressionEvaluator(ast.NodeVisitor):
    """Safely evaluate an AST expression."""

    def __init__(self):
        self._stack = []

    def push(self, value):
        self._stack.append(value)

    def pop(self):
        return self._stack.pop()

    def result(self):
        return self._stack[-1] if self._stack else None

    def visit_Constant(self, node):
        self.push(node.value)

    def visit_Name(self, node):
        if node.id in SAFE_FUNCTIONS:
            self.push(SAFE_FUNCTIONS[node.id])
        else:
            raise ValueError(f"Unknown name: {node.id}")

    def visit_BinOp(self, node):
        self.visit(node.left)
        self.visit(node.right)
        op_type = type(node.op)
        if op_type not in SAFE_OPERATORS:
            raise ValueError(f"Unsafe operator: {op_type.__name__}")
        right = self.pop()
        left = self.pop()
        self.push(SAFE_OPERATORS[op_type](left, right))

    def visit_UnaryOp(self, node):
        self.visit(node.operand)
        op_type = type(node.op)
        if op_type not in SAFE_OPERATORS:
            raise ValueError(f"Unsafe operator: {op_type.__name__}")
        operand = self.pop()
        self.push(SAFE_OPERATORS[op_type](operand))

    def visit_Call(self, node):
        if not isinstance(node.func, ast.Name) or node.func.id not in SAFE_FUNCTIONS:
            raise ValueError(
                f"Unsafe function call: {node.func.id if isinstance(node.func, ast.Name) else 'unknown'}"
            )
        args = []
        for arg in node.args:
            self.visit(arg)
            args.append(self.pop())
        func = SAFE_FUNCTIONS[node.func.id]
        self.push(func(*args))

    def visit_Expr(self, node):
        self.visit(node.value)

    def visit_BoolOp(self, node):
        values = []
        for v in node.values:
            self.visit(v)
            values.append(self.pop())
        if isinstance(node.op, ast.And):
            result = all(values)
        elif isinstance(node.op, ast.Or):
            result = any(values)
        else:
            raise ValueError("Unknown bool op")
        self.push(result)

    def visit_Compare(self, node):
        self.visit(node.left)
        for comparator in node.comparators:
            self.visit(comparator)
        right = self.pop()
        left = self.pop()
        for op in node.ops:
            if isinstance(op, ast.Eq):
                result = left == right
            elif isinstance(op, ast.NotEq):
                result = left != right
            elif isinstance(op, ast.Lt):
                result = left < right
            elif isinstance(op, ast.LtE):
                result = left <= right
            elif isinstance(op, ast.Gt):
                result = left > right
            elif isinstance(op, ast.GtE):
                result = left >= right
            else:
                raise ValueError(f"Unknown comparison: {type(op).__name__}")
            left = result
        self.push(left)


def is_safe_expression(expression: str) -> bool:
    """Check if an expression uses only safe operations."""
    try:
        tree = ast.parse(expression.strip(), mode="eval")
        visitor = ExpressionVisitor()
        visitor.visit(tree)
        return visitor.valid
    except SyntaxError:
        return False


def safe_calculate(expression: str) -> float | int | str:
    """Safely evaluate a mathematical expression.

    Only allows basic arithmetic, math functions, and constants.
    No attribute access, imports, lambdas, comprehensions, or assignments.
    """
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as e:
        return f"Syntax error: {e}"

    visitor = ExpressionVisitor()
    visitor.visit(tree)
    if not visitor.valid:
        return "Error: Expression contains unsafe operations"

    try:
        evaluator = ExpressionEvaluator()
        evaluator.visit(tree)
        result = evaluator.result()
        if result is None:
            return "Error: Empty expression"
        return result
    except (ValueError, ZeroDivisionError, OverflowError) as e:
        return f"Error: {e}"
