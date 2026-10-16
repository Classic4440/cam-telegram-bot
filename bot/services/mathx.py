"""Safe math evaluator (no ``eval``) with functions, constants, variables and an equation solver.

Threat model: the expression is attacker-controlled text.  We therefore
* parse to an AST and interpret only a whitelist of node types,
* bound expression length, node count and result magnitude (no ``9**9**9`` memory/CPU bombs),
* reject complex results, booleans, attribute access, comprehensions, lambdas and names that are not
  whitelisted constants/functions/explicit variables.
"""
from __future__ import annotations

import ast
import math
import operator
import re
from collections.abc import Callable, Mapping

MAX_EXPR_LEN = 200
MAX_NODES = 150
MAX_BITS = 1000  # ints are capped near 1e301
MAX_FLOAT = 1e300


class CalcError(ValueError):
    """Raised for any invalid or unsafe expression; the message is safe to show to users."""


Number = int | float


def _check(value: Number) -> Number:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CalcError("Only real numbers are supported")
    if isinstance(value, int):
        if value.bit_length() > MAX_BITS:
            raise CalcError("The result is too large")
        return value
    if not math.isfinite(value) or abs(value) > MAX_FLOAT:
        raise CalcError("The result is too large or undefined")
    return value


def _pow(a: Number, b: Number) -> Number:
    if a == 0 and b < 0:
        raise CalcError("Division by zero")
    if a not in (0, 1, -1) and b != 0:
        if abs(b) * math.log10(abs(a)) > 300:
            raise CalcError("The result is too large")
    if a < 0 and not float(b).is_integer():
        raise CalcError("That would give a complex number (unsupported)")
    return operator.pow(a, b)


def _mul(a: Number, b: Number) -> Number:
    if isinstance(a, int) and isinstance(b, int) and a.bit_length() + b.bit_length() > MAX_BITS + 8:
        raise CalcError("The result is too large")
    return a * b


def _div(a: Number, b: Number) -> Number:
    if b == 0:
        raise CalcError("Division by zero")
    return a / b


def _floordiv(a: Number, b: Number) -> Number:
    if b == 0:
        raise CalcError("Division by zero")
    return a // b


def _mod(a: Number, b: Number) -> Number:
    if b == 0:
        raise CalcError("Division by zero")
    return a % b


_BINOPS: dict[type, Callable[[Number, Number], Number]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: _mul,
    ast.Div: _div,
    ast.FloorDiv: _floordiv,
    ast.Mod: _mod,
    ast.Pow: _pow,
}


def _need_int(x: Number, name: str) -> int:
    if isinstance(x, float):
        if not x.is_integer():
            raise CalcError(f"{name} needs whole numbers")
        return int(x)
    return x


def _factorial(n: Number) -> int:
    n = _need_int(n, "factorial")
    if not 0 <= n <= 160:
        raise CalcError("factorial supports 0..160")
    return math.factorial(n)


def _comb(n: Number, k: Number) -> int:
    n, k = _need_int(n, "comb"), _need_int(k, "comb")
    if n < 0 or k < 0 or n > 2000:
        raise CalcError("comb supports 0 <= n <= 2000")
    return math.comb(n, k)


def _perm(n: Number, k: Number) -> int:
    n, k = _need_int(n, "perm"), _need_int(k, "perm")
    if n < 0 or k < 0 or n > 300:
        raise CalcError("perm supports 0 <= n <= 300")
    return math.perm(n, k)


def _log(x: Number, base: Number | None = None) -> float:
    if x <= 0 or (base is not None and (base <= 0 or base == 1)):
        raise CalcError("log is only defined for positive numbers (and a base other than 1)")
    return math.log(x) if base is None else math.log(x, base)


def _sqrt(x: Number) -> float:
    if x < 0:
        raise CalcError("sqrt of a negative number is not real")
    return math.sqrt(x)


def _cbrt(x: Number) -> float:
    return math.copysign(abs(x) ** (1 / 3), x)


def _round(x: Number, digits: Number = 0) -> Number:
    return round(x, _need_int(digits, "round"))


def _domain(fn: Callable[..., float]) -> Callable[..., float]:
    def inner(*args: Number) -> float:
        try:
            return fn(*args)
        except (ValueError, OverflowError) as exc:
            raise CalcError(f"Math domain error: {exc}") from None

    return inner


FUNCTIONS: dict[str, tuple[Callable[..., Number], int, int]] = {
    # name: (callable, min_args, max_args)
    "sqrt": (_sqrt, 1, 1),
    "cbrt": (_cbrt, 1, 1),
    "sin": (_domain(math.sin), 1, 1),
    "cos": (_domain(math.cos), 1, 1),
    "tan": (_domain(math.tan), 1, 1),
    "asin": (_domain(math.asin), 1, 1),
    "acos": (_domain(math.acos), 1, 1),
    "atan": (_domain(math.atan), 1, 1),
    "atan2": (_domain(math.atan2), 2, 2),
    "sinh": (_domain(math.sinh), 1, 1),
    "cosh": (_domain(math.cosh), 1, 1),
    "tanh": (_domain(math.tanh), 1, 1),
    "log": (_log, 1, 2),
    "ln": (_log, 1, 1),
    "log2": (lambda x: _log(x, 2), 1, 1),
    "log10": (lambda x: _log(x, 10), 1, 1),
    "exp": (_domain(math.exp), 1, 1),
    "abs": (abs, 1, 1),
    "round": (_round, 1, 2),
    "floor": (lambda x: math.floor(x), 1, 1),
    "ceil": (lambda x: math.ceil(x), 1, 1),
    "trunc": (lambda x: math.trunc(x), 1, 1),
    "sign": (lambda x: (x > 0) - (x < 0), 1, 1),
    "fact": (_factorial, 1, 1),
    "factorial": (_factorial, 1, 1),
    "gcd": (lambda a, b: math.gcd(_need_int(a, "gcd"), _need_int(b, "gcd")), 2, 2),
    "lcm": (lambda a, b: math.lcm(_need_int(a, "lcm"), _need_int(b, "lcm")), 2, 2),
    "comb": (_comb, 2, 2),
    "perm": (_perm, 2, 2),
    "min": (min, 1, 6),
    "max": (max, 1, 6),
    "hypot": (_domain(math.hypot), 2, 2),
    "deg": (_domain(math.degrees), 1, 1),
    "rad": (_domain(math.radians), 1, 1),
}

CONSTANTS: dict[str, float] = {
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
    "phi": (1 + math.sqrt(5)) / 2,
}

_SUBSTITUTIONS = (("×", "*"), ("÷", "/"), ("−", "-"), ("–", "-"), ("^", "**"), ("√", "sqrt"), ("π", "pi"))
_PERCENT_OF = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*of\s*(\d+(?:\.\d+)?|\()", re.I)
_IMPLICIT_NUM_NAME = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(?![eE][+-]?\d)([A-Za-z_(])")
_IMPLICIT_PAREN = re.compile(r"\)\s*(?=[\w(])")


def normalize(expression: str) -> str:
    """Turn "friendly" input into something ``ast`` can parse (``2x``, ``20% of 50``, ``3(4+1)``, ``^``)."""
    expr = expression.strip()
    for old, new in _SUBSTITUTIONS:
        expr = expr.replace(old, new)
    expr = _PERCENT_OF.sub(lambda m: f"({m.group(1)}/100)*{m.group(2)}", expr)
    expr = _IMPLICIT_NUM_NAME.sub(r"\1*\2", expr)
    expr = _IMPLICIT_PAREN.sub(")*", expr)
    return expr


def evaluate(expression: str, variables: Mapping[str, Number] | None = None) -> Number:
    """Evaluate ``expression``; raises ``CalcError`` on anything invalid or unsafe."""
    if len(expression) > MAX_EXPR_LEN:
        raise CalcError(f"Please keep expressions under {MAX_EXPR_LEN} characters")
    expr = normalize(expression)
    if not expr:
        raise CalcError("Empty expression")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        raise CalcError("I couldn't parse that expression") from None
    if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
        raise CalcError("Expression is too complex")
    scope = {**CONSTANTS, **(variables or {})}
    return _eval(tree.body, scope)


def _eval(node: ast.AST, scope: Mapping[str, Number]) -> Number:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise CalcError("Only numbers are allowed")
        return _check(node.value)
    if isinstance(node, ast.Name):
        if node.id in scope:
            return scope[node.id]
        raise CalcError(f"Unknown name '{node.id}'")
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval(node.operand, scope)
        return _check(value if isinstance(node.op, ast.UAdd) else -value)
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        left = _eval(node.left, scope)
        right = _eval(node.right, scope)
        try:
            return _check(_BINOPS[type(node.op)](left, right))
        except OverflowError:
            raise CalcError("The result is too large") from None
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
        spec = FUNCTIONS.get(node.func.id)
        if spec is None:
            raise CalcError(f"Unknown function '{node.func.id}'")
        func, lo, hi = spec
        if not lo <= len(node.args) <= hi:
            raise CalcError(f"{node.func.id}() takes {lo}" + (f"-{hi}" if hi != lo else "") + " argument(s)")
        args = [_eval(arg, scope) for arg in node.args]
        try:
            return _check(func(*args))
        except OverflowError:
            raise CalcError("The result is too large") from None
        except (ValueError, TypeError) as exc:
            if isinstance(exc, CalcError):
                raise
            raise CalcError("Invalid argument") from None
    raise CalcError("Only basic arithmetic and the listed functions are supported")


# --------------------------------------------------------------------------------------
# equation solving (linear and quadratic in one variable, by sampling the polynomial)
# --------------------------------------------------------------------------------------
def solve(equation: str, var: str = "x") -> list[float] | str:
    """Solve ``lhs = rhs`` for a polynomial of degree <= 2 in ``var``.

    Returns the list of real roots, or ``"all"`` (identity) / ``"none"`` (contradiction).
    """
    if equation.count("=") != 1:
        raise CalcError("Write an equation with exactly one '=' sign, e.g. 2x + 3 = 11")
    lhs, rhs = (side.strip() for side in equation.split("="))
    if not lhs or not rhs:
        raise CalcError("Both sides of the equation need a value")

    def f(x: float) -> float:
        return float(evaluate(lhs, {var: x}) - evaluate(rhs, {var: x}))

    f0, f1, fm1, f2, fm2 = f(0), f(1), f(-1), f(2), f(-2)
    c = f0
    a = (f1 + fm1) / 2 - c
    b = (f1 - fm1) / 2
    # verify it really is a degree<=2 polynomial (rejects cubic, sin(x), 1/x, ...)
    scale = max(1.0, abs(f0), abs(f1), abs(f2), abs(fm1), abs(fm2))
    tol = 1e-9 * scale
    if abs(a * 4 + b * 2 + c - f2) > tol or abs(a * 4 - b * 2 + c - fm2) > tol:
        raise CalcError("I can only solve linear and quadratic equations (like 2x+3=11 or x^2-5x+6=0)")
    if abs(a) < tol:
        if abs(b) < tol:
            return "all" if abs(c) < tol else "none"
        return [-c / b]
    disc = b * b - 4 * a * c
    if disc < -tol:
        return []
    if abs(disc) <= tol:
        return [-b / (2 * a)]
    root = math.sqrt(disc)
    return sorted([(-b - root) / (2 * a), (-b + root) / (2 * a)])
