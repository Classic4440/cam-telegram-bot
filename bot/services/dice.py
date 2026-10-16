"""Dice-notation roller: ``2d6+3``, ``d20``, ``4d6kh3``, ``1d20+1d4-2``, ``3d8kl1``."""
from __future__ import annotations

import random
import re
from dataclasses import dataclass

MAX_DICE = 100
MAX_SIDES = 1000
MAX_TERMS = 10

_TERM = re.compile(r"([+-]?)\s*(?:(\d*)d(\d+)(?:(kh|kl)(\d+))?|(\d+))", re.I)


class DiceError(ValueError):
    pass


@dataclass(slots=True)
class DiceResult:
    expression: str
    total: int
    detail: str
    min_possible: int
    max_possible: int


def roll(expression: str, rng: random.Random | None = None) -> DiceResult:
    rng = rng or random.SystemRandom()
    text = expression.strip().lower().replace(" ", "")
    if not text or len(text) > 60:
        raise DiceError("Use dice notation like 2d6+3, d20 or 4d6kh3")

    pos, total, low, high = 0, 0, 0, 0
    parts: list[str] = []
    terms = 0
    while pos < len(text):
        match = _TERM.match(text, pos)
        if not match or match.end() == pos:
            raise DiceError("Use dice notation like 2d6+3, d20 or 4d6kh3")
        pos = match.end()
        terms += 1
        if terms > MAX_TERMS:
            raise DiceError(f"At most {MAX_TERMS} terms")
        sign = -1 if match.group(1) == "-" else 1
        if match.group(3):  # dice term
            count = int(match.group(2) or 1)
            sides = int(match.group(3))
            if not 1 <= count <= MAX_DICE or not 2 <= sides <= MAX_SIDES:
                raise DiceError(f"Use 1-{MAX_DICE} dice with 2-{MAX_SIDES} sides")
            rolls = [rng.randint(1, sides) for _ in range(count)]
            kept = rolls
            label = f"{count}d{sides}"
            if match.group(4):
                keep = int(match.group(5))
                if not 1 <= keep <= count:
                    raise DiceError("Keep count must be between 1 and the number of dice")
                ordered = sorted(rolls, reverse=match.group(4) == "kh")
                kept = ordered[:keep]
                label += f"{match.group(4)}{keep}"
            subtotal = sum(kept)
            total += sign * subtotal
            low += sign * (len(kept) if sign > 0 else sides * len(kept))
            high += sign * (sides * len(kept) if sign > 0 else len(kept))
            shown = ", ".join(str(r) for r in rolls) if len(rolls) <= 20 else f"{len(rolls)} dice"
            marker = " → kept " + ", ".join(map(str, kept)) if match.group(4) else ""
            parts.append(f"{'-' if sign < 0 else ('+' if parts else '')}{label}[{shown}{marker}]")
        else:
            value = int(match.group(6))
            total += sign * value
            low += sign * value
            high += sign * value
            parts.append(f"{'-' if sign < 0 else ('+' if parts else '')}{value}")
    return DiceResult(expression.strip(), total, "".join(parts), min(low, high), max(low, high))
