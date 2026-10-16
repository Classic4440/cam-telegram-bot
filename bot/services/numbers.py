"""Number theory and statistics helpers."""
from __future__ import annotations

import math
import random
import statistics
from collections import Counter

MAX_PRIME_INPUT = 10**18
_SMALL_PRIMES = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)


class NumberError(ValueError):
    pass


def is_prime(n: int) -> bool:
    """Deterministic Miller-Rabin, exact for n < 3.3e24 (so exact for everything we accept)."""
    if n < 2:
        return False
    for p in _SMALL_PRIMES:
        if n % p == 0:
            return n == p
    d, s = n - 1, 0
    while d % 2 == 0:
        d //= 2
        s += 1
    for a in _SMALL_PRIMES:
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(s - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def next_prime(n: int) -> int:
    candidate = max(2, n + 1)
    while not is_prime(candidate):
        candidate += 1
    return candidate


def _pollard_rho(n: int, rng: random.Random) -> int:
    if n % 2 == 0:
        return 2
    while True:
        c = rng.randrange(1, n)
        x = y = rng.randrange(0, n)
        d = 1
        while d == 1:
            x = (x * x + c) % n
            y = (y * y + c) % n
            y = (y * y + c) % n
            d = math.gcd(abs(x - y), n)
        if d != n:
            return d


def factorize(n: int) -> dict[int, int]:
    """Prime factorisation as ``{prime: exponent}`` (n up to 1e18)."""
    if n < 2:
        raise NumberError("Give an integer >= 2")
    if n > MAX_PRIME_INPUT:
        raise NumberError("Numbers up to 10^18 are supported")
    factors: Counter[int] = Counter()
    rng = random.Random(n)  # deterministic per input

    for p in _SMALL_PRIMES + (41, 43, 47, 53, 59, 61, 67, 71, 73, 79, 83, 89, 97):
        while n % p == 0:
            factors[p] += 1
            n //= p

    def split(m: int) -> None:
        if m == 1:
            return
        if is_prime(m):
            factors[m] += 1
            return
        root = math.isqrt(m)
        if root * root == m:
            split(root)
            split(root)
            return
        d = _pollard_rho(m, rng)
        split(d)
        split(m // d)

    split(n)
    return dict(sorted(factors.items()))


def format_factors(factors: dict[int, int]) -> str:
    return " × ".join(str(p) if e == 1 else f"{p}^{e}" for p, e in factors.items())


def divisors(n: int) -> list[int]:
    if n < 1 or n > 10**12:
        raise NumberError("Give an integer between 1 and 10^12")
    small, large = [], []
    for i in range(1, math.isqrt(n) + 1):
        if n % i == 0:
            small.append(i)
            if i != n // i:
                large.append(n // i)
    return small + large[::-1]


def fibonacci(n: int) -> int:
    """Fast doubling; ``n`` is limited by the caller (the result grows ~0.209 digits per step)."""
    if n < 0:
        raise NumberError("n must be >= 0")

    def fd(k: int) -> tuple[int, int]:
        if k == 0:
            return 0, 1
        a, b = fd(k >> 1)
        c = a * (2 * b - a)
        d = a * a + b * b
        return (d, c + d) if k & 1 else (c, d)

    return fd(n)[0]


def collatz_steps(n: int, cap: int = 100_000) -> tuple[int, int]:
    """Return (steps to reach 1, peak value)."""
    if n < 1:
        raise NumberError("n must be >= 1")
    steps, peak = 0, n
    while n != 1:
        n = n // 2 if n % 2 == 0 else 3 * n + 1
        peak = max(peak, n)
        steps += 1
        if steps > cap:
            raise NumberError("That sequence is too long")
    return steps, peak


# ------------------------------------------------------------------------------ roman numerals
_ROMAN = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
          (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]


def to_roman(n: int) -> str:
    if not 1 <= n <= 3999:
        raise NumberError("Roman numerals support 1-3999")
    out = []
    for value, symbol in _ROMAN:
        count, n = divmod(n, value)
        out.append(symbol * count)
    return "".join(out)


def from_roman(text: str) -> int:
    text = text.strip().upper()
    if not text or any(c not in "IVXLCDM" for c in text):
        raise NumberError("Not a roman numeral")
    total, i = 0, 0
    for value, symbol in _ROMAN:
        while text.startswith(symbol, i):
            total += value
            i += len(symbol)
    if i != len(text) or to_roman(total) != text:
        raise NumberError("Not a valid roman numeral")
    return total


# ------------------------------------------------------------------------------ bases and words
_DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"


def convert_base(value: str, from_base: int, to_base: int) -> str:
    if not (2 <= from_base <= 36 and 2 <= to_base <= 36):
        raise NumberError("Bases must be between 2 and 36")
    value = value.strip().lower().replace("_", "")
    negative = value.startswith("-")
    value = value.lstrip("+-")
    for prefix in ("0x", "0b", "0o"):
        if value.startswith(prefix):
            value = value[2:]
    if not value or len(value) > 200:
        raise NumberError("Give a value up to 200 digits")
    try:
        number = int(value, from_base)
    except ValueError:
        raise NumberError(f"'{value[:20]}' is not a valid base-{from_base} number") from None
    if number == 0:
        return "0"
    digits = []
    n = number
    while n:
        n, rem = divmod(n, to_base)
        digits.append(_DIGITS[rem])
    return ("-" if negative else "") + "".join(reversed(digits))


_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
         "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_SCALES = ["", "thousand", "million", "billion", "trillion", "quadrillion"]


def number_to_words(n: int) -> str:
    if abs(n) >= 10**18:
        raise NumberError("Numbers below 10^18 are supported")
    if n < 0:
        return "minus " + number_to_words(-n)
    if n < 20:
        return _ONES[n]

    def below_thousand(x: int) -> str:
        parts = []
        if x >= 100:
            parts.append(f"{_ONES[x // 100]} hundred")
            x %= 100
        if x >= 20:
            tens, ones = divmod(x, 10)
            parts.append(_TENS[tens] + (f"-{_ONES[ones]}" if ones else ""))
        elif x > 0:
            parts.append(_ONES[x])
        return " ".join(parts)

    groups, scale = [], 0
    while n:
        n, chunk = divmod(n, 1000)
        if chunk:
            groups.append((below_thousand(chunk) + (" " + _SCALES[scale] if scale else "")).strip())
        scale += 1
    return " ".join(reversed(groups))


# ------------------------------------------------------------------------------ statistics
def describe(values: list[float]) -> dict[str, float | list[float]]:
    if not values:
        raise NumberError("Give at least one number")
    if len(values) > 5000:
        raise NumberError("At most 5000 numbers")
    ordered = sorted(values)
    result: dict[str, float | list[float]] = {
        "count": len(values),
        "sum": math.fsum(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "min": ordered[0],
        "max": ordered[-1],
        "range": ordered[-1] - ordered[0],
    }
    modes = statistics.multimode(values)
    result["mode"] = modes if len(modes) < len(set(values)) or len(values) == 1 else []
    if len(values) >= 2:
        result["stdev"] = statistics.stdev(values)
        result["variance"] = statistics.variance(values)
        q = statistics.quantiles(values, n=4, method="inclusive")
        result["quartiles"] = q
    return result


def compound_interest(principal: float, annual_rate_pct: float, years: float, per_year: int = 12) -> dict[str, float]:
    if principal < 0 or years < 0 or years > 200 or not 1 <= per_year <= 365 or abs(annual_rate_pct) > 1000:
        raise NumberError("Check the inputs: years <= 200, compounds/year 1-365, rate within ±1000%")
    rate = annual_rate_pct / 100
    final = principal * (1 + rate / per_year) ** (per_year * years)
    return {"final": final, "interest": final - principal}
