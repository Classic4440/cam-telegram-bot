"""Propositional logic: parser, truth tables, tautology/contradiction/equivalence checks.

Hand-written recursive-descent parser (no ``eval``).  Precedence, high to low:
``not``  >  ``and``/``nand``  >  ``xor``  >  ``or``/``nor``  >  ``->`` (right assoc)  >  ``<->``
Accepted spellings: and & && ∧ | or || ∨ | not ! ~ ¬ | xor ^ ⊕ | -> => → implies | <-> <=> ↔ iff
"""
from __future__ import annotations

import itertools
import re
from dataclasses import dataclass

MAX_VARS = 6
MAX_LEN = 160

_TOKEN = re.compile(
    r"\s*(?:(?P<op><->|<=>|->|=>|&&|\|\||[&|!~^()∧∨¬⊕→↔])|(?P<word>[A-Za-z_][A-Za-z_0-9]*)|(?P<num>[01]))"
)
_WORD_OPS = {
    "and": "and", "or": "or", "not": "not", "xor": "xor", "nand": "nand", "nor": "nor", "xnor": "iff",
    "implies": "imp", "iff": "iff", "true": "true", "false": "false",
}
_SYMBOL_OPS = {
    "&": "and", "&&": "and", "∧": "and", "|": "or", "||": "or", "∨": "or", "!": "not", "~": "not", "¬": "not",
    "^": "xor", "⊕": "xor", "->": "imp", "=>": "imp", "→": "imp", "<->": "iff", "<=>": "iff", "↔": "iff",
    "(": "(", ")": ")",
}


class LogicError(ValueError):
    pass


Node = tuple  # ("var", name) | ("const", bool) | ("not", n) | (op, l, r)


def _tokenize(text: str) -> list[tuple[str, str]]:
    if len(text) > MAX_LEN:
        raise LogicError(f"Please keep expressions under {MAX_LEN} characters")
    tokens: list[tuple[str, str]] = []
    pos = 0
    text = text.strip()
    while pos < len(text):
        match = _TOKEN.match(text, pos)
        if not match or match.end() == pos:
            raise LogicError(f"Unexpected character {text[pos:pos + 1]!r}")
        pos = match.end()
        if match.group("op"):
            tokens.append((_SYMBOL_OPS[match.group("op")], match.group("op")))
        elif match.group("word"):
            word = match.group("word")
            lower = word.lower()
            if lower in _WORD_OPS:
                kind = _WORD_OPS[lower]
                tokens.append((kind, word) if kind not in {"true", "false"} else (kind, word))
            else:
                tokens.append(("var", word))
        else:
            tokens.append(("true" if match.group("num") == "1" else "false", match.group("num")))
        while pos < len(text) and text[pos].isspace():
            pos += 1
    if not tokens:
        raise LogicError("Empty expression")
    return tokens


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]) -> None:
        self.tokens = tokens
        self.i = 0

    def peek(self) -> str | None:
        return self.tokens[self.i][0] if self.i < len(self.tokens) else None

    def take(self) -> tuple[str, str]:
        token = self.tokens[self.i]
        self.i += 1
        return token

    def parse(self) -> Node:
        node = self.iff()
        if self.i != len(self.tokens):
            raise LogicError(f"Unexpected {self.tokens[self.i][1]!r}")
        return node

    def iff(self) -> Node:
        left = self.imp()
        while self.peek() == "iff":
            self.take()
            left = ("iff", left, self.imp())
        return left

    def imp(self) -> Node:
        left = self.or_()
        if self.peek() == "imp":
            self.take()
            return ("imp", left, self.imp())  # right associative
        return left

    def or_(self) -> Node:
        left = self.xor()
        while self.peek() in {"or", "nor"}:
            op = self.take()[0]
            left = (op, left, self.xor())
        return left

    def xor(self) -> Node:
        left = self.and_()
        while self.peek() == "xor":
            self.take()
            left = ("xor", left, self.and_())
        return left

    def and_(self) -> Node:
        left = self.not_()
        while self.peek() in {"and", "nand"}:
            op = self.take()[0]
            left = (op, left, self.not_())
        return left

    def not_(self) -> Node:
        if self.peek() == "not":
            self.take()
            return ("not", self.not_())
        return self.atom()

    def atom(self) -> Node:
        kind = self.peek()
        if kind is None:
            raise LogicError("Expression ended unexpectedly")
        if kind == "(":
            self.take()
            node = self.iff()
            if self.peek() != ")":
                raise LogicError("Missing closing parenthesis")
            self.take()
            return node
        if kind == "var":
            return ("var", self.take()[1])
        if kind in {"true", "false"}:
            self.take()
            return ("const", kind == "true")
        raise LogicError(f"Unexpected {self.tokens[self.i][1]!r}")


def parse(text: str) -> Node:
    return _Parser(_tokenize(text)).parse()


def variables(node: Node) -> list[str]:
    seen: list[str] = []

    def walk(n: Node) -> None:
        if n[0] == "var":
            if n[1] not in seen:
                seen.append(n[1])
        elif n[0] == "const":
            return
        else:
            for child in n[1:]:
                walk(child)

    walk(node)
    return sorted(seen)


def evaluate(node: Node, env: dict[str, bool]) -> bool:
    kind = node[0]
    if kind == "var":
        return env[node[1]]
    if kind == "const":
        return node[1]
    if kind == "not":
        return not evaluate(node[1], env)
    a, b = evaluate(node[1], env), evaluate(node[2], env)
    return {
        "and": a and b,
        "or": a or b,
        "xor": a != b,
        "nand": not (a and b),
        "nor": not (a or b),
        "imp": (not a) or b,
        "iff": a == b,
    }[kind]


@dataclass(slots=True)
class TruthTable:
    names: list[str]
    rows: list[tuple[tuple[bool, ...], bool]]

    @property
    def classification(self) -> str:
        results = {r for _, r in self.rows}
        if results == {True}:
            return "tautology"
        if results == {False}:
            return "contradiction"
        return "contingent"

    @property
    def true_count(self) -> int:
        return sum(1 for _, r in self.rows if r)


def truth_table(text: str, max_vars: int = MAX_VARS) -> TruthTable:
    node = parse(text)
    names = variables(node)
    if len(names) > max_vars:
        raise LogicError(f"At most {max_vars} variables are supported")
    rows = []
    for values in itertools.product((True, False), repeat=len(names)):
        rows.append((values, evaluate(node, dict(zip(names, values)))))
    return TruthTable(names, rows)


def equivalent(a: str, b: str) -> bool:
    na, nb = parse(a), parse(b)
    names = sorted(set(variables(na)) | set(variables(nb)))
    if len(names) > MAX_VARS:
        raise LogicError(f"At most {MAX_VARS} variables are supported")
    return all(
        evaluate(na, dict(zip(names, v))) == evaluate(nb, dict(zip(names, v)))
        for v in itertools.product((True, False), repeat=len(names))
    )


def render(table: TruthTable, result_label: str = "out") -> str:
    """Monospace table suitable for a <pre> block."""
    names = table.names or ["·"]
    header = " ".join(f"{n:^3}" for n in names) + " | " + result_label
    rule = "-" * len(header)
    lines = [header, rule]
    for values, result in table.rows:
        cells = values if table.names else ()
        left = " ".join(f"{'T' if v else 'F':^3}" for v in cells) if cells else f"{'':^3}"
        lines.append(f"{left} | {'T' if result else 'F'}")
    return "\n".join(lines)
