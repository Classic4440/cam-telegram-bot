"""Unit conversion with a table-driven design: add a unit by adding one row."""
from __future__ import annotations

import re
from dataclasses import dataclass

# category -> {canonical: (factor_to_base, [aliases])}
_TABLE: dict[str, dict[str, tuple[float, list[str]]]] = {
    "length": {  # base: metre
        "mm": (0.001, ["millimeter", "millimeters", "millimetre", "millimetres"]),
        "cm": (0.01, ["centimeter", "centimeters", "centimetre", "centimetres"]),
        "m": (1.0, ["meter", "meters", "metre", "metres"]),
        "km": (1000.0, ["kilometer", "kilometers", "kilometre", "kilometres", "kms"]),
        "in": (0.0254, ["inch", "inches", '"']),
        "ft": (0.3048, ["foot", "feet", "'"]),
        "yd": (0.9144, ["yard", "yards"]),
        "mi": (1609.344, ["mile", "miles"]),
        "nmi": (1852.0, ["nauticalmile", "nauticalmiles"]),
    },
    "mass": {  # base: kilogram
        "mg": (1e-6, ["milligram", "milligrams"]),
        "g": (0.001, ["gram", "grams"]),
        "kg": (1.0, ["kilogram", "kilograms", "kilo", "kilos", "kgs"]),
        "t": (1000.0, ["tonne", "tonnes", "metricton"]),
        "oz": (0.028349523125, ["ounce", "ounces"]),
        "lb": (0.45359237, ["lbs", "pound", "pounds"]),
        "st": (6.35029318, ["stone", "stones"]),
    },
    "volume": {  # base: litre
        "ml": (0.001, ["milliliter", "milliliters", "millilitre", "millilitres"]),
        "l": (1.0, ["liter", "liters", "litre", "litres"]),
        "m3": (1000.0, ["cubicmeter", "cubicmeters"]),
        "tsp": (0.00492892159375, ["teaspoon", "teaspoons"]),
        "tbsp": (0.01478676478125, ["tablespoon", "tablespoons"]),
        "floz": (0.0295735295625, ["fluidounce", "fluidounces"]),
        "cup": (0.2365882365, ["cups"]),
        "pt": (0.473176473, ["pint", "pints"]),
        "qt": (0.946352946, ["quart", "quarts"]),
        "gal": (3.785411784, ["gallon", "gallons"]),
    },
    "time": {  # base: second
        "ms": (0.001, ["millisecond", "milliseconds"]),
        "s": (1.0, ["sec", "secs", "second", "seconds"]),
        "min": (60.0, ["mins", "minute", "minutes"]),
        "h": (3600.0, ["hr", "hrs", "hour", "hours"]),
        "d": (86400.0, ["day", "days"]),
        "wk": (604800.0, ["week", "weeks"]),
        "yr": (31557600.0, ["year", "years", "y"]),
    },
    "speed": {  # base: m/s
        "m/s": (1.0, ["mps"]),
        "km/h": (1 / 3.6, ["kmh", "kph", "kmph"]),
        "mph": (0.44704, ["mi/h"]),
        "kn": (1852 / 3600, ["knot", "knots", "kt"]),
        "ft/s": (0.3048, ["fps"]),
    },
    "area": {  # base: m²
        "mm2": (1e-6, []),
        "cm2": (1e-4, []),
        "m2": (1.0, ["sqm"]),
        "km2": (1e6, ["sqkm"]),
        "ha": (10000.0, ["hectare", "hectares"]),
        "acre": (4046.8564224, ["acres"]),
        "ft2": (0.09290304, ["sqft"]),
        "in2": (0.00064516, ["sqin"]),
        "mi2": (2589988.110336, ["sqmi"]),
    },
    "energy": {  # base: joule
        "j": (1.0, ["joule", "joules"]),
        "kj": (1000.0, ["kilojoule", "kilojoules"]),
        "cal": (4.184, ["calorie", "calories"]),
        "kcal": (4184.0, ["kilocalorie", "kilocalories", "food calorie"]),
        "wh": (3600.0, ["watthour", "watthours"]),
        "kwh": (3.6e6, ["kilowatthour", "kilowatthours"]),
    },
    "pressure": {  # base: pascal
        "pa": (1.0, ["pascal", "pascals"]),
        "kpa": (1000.0, ["kilopascal", "kilopascals"]),
        "bar": (1e5, ["bars"]),
        "psi": (6894.757293168, []),
        "atm": (101325.0, ["atmosphere", "atmospheres"]),
    },
    "angle": {  # base: radian
        "rad": (1.0, ["radian", "radians"]),
        "deg": (0.017453292519943295, ["degree", "degrees", "°"]),
        "grad": (0.015707963267948967, ["gradian", "gradians"]),
    },
}

# bytes are case sensitive (b = bit, B = byte); keys are matched exactly
_DATA: dict[str, float] = {
    "b": 0.125, "B": 1.0, "KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12, "PB": 1e15,
    "KiB": 1024.0, "MiB": 1024.0**2, "GiB": 1024.0**3, "TiB": 1024.0**4,
}
_DATA_ALIASES = {
    "bit": "b", "bits": "b", "byte": "B", "bytes": "B", "kilobyte": "KB", "kilobytes": "KB", "kb": "KB",
    "megabyte": "MB", "megabytes": "MB", "mb": "MB", "gigabyte": "GB", "gigabytes": "GB", "gb": "GB",
    "terabyte": "TB", "terabytes": "TB", "tb": "TB", "kib": "KiB", "mib": "MiB", "gib": "GiB", "tib": "TiB",
}
_TEMP = {
    "c": "c", "celsius": "c", "°c": "c", "centigrade": "c",
    "f": "f", "fahrenheit": "f", "°f": "f",
    "k": "k", "kelvin": "k",
}

_LOOKUP: dict[str, tuple[str, str]] = {}  # alias -> (category, canonical)
for _cat, _units in _TABLE.items():
    for _name, (_factor, _aliases) in _units.items():
        for _alias in [_name, *_aliases]:
            _LOOKUP.setdefault(_alias.lower().replace(" ", ""), (_cat, _name))

_PARSE = re.compile(
    r"^\s*(?P<value>[-+]?\d+(?:[.,]\d+)?(?:e[-+]?\d+)?)\s*(?P<src>[^\s\d][^\n]*?)\s+(?:to|in|into|as|->|=)\s+(?P<dst>\S[^\n]*?)\s*$",
    re.I,
)


class UnitError(ValueError):
    pass


@dataclass(slots=True)
class Conversion:
    value: float
    src: str
    dst: str
    result: float
    category: str


def _resolve(raw: str) -> tuple[str, str]:
    key = raw.strip()
    if key in _DATA:
        return "data", key
    low = key.lower().replace(" ", "")
    if low in _DATA_ALIASES:
        return "data", _DATA_ALIASES[low]
    if low in _TEMP:
        return "temperature", _TEMP[low]
    if low in _LOOKUP:
        return _LOOKUP[low]
    raise UnitError(f"I don't know the unit '{raw.strip()[:20]}'. Try /units to see supported units.")


def _to_kelvin(value: float, unit: str) -> float:
    return {"c": value + 273.15, "f": (value - 32) * 5 / 9 + 273.15, "k": value}[unit]


def _from_kelvin(value: float, unit: str) -> float:
    return {"c": value - 273.15, "f": (value - 273.15) * 9 / 5 + 32, "k": value}[unit]


def convert(value: float, src: str, dst: str) -> Conversion:
    cat_a, unit_a = _resolve(src)
    cat_b, unit_b = _resolve(dst)
    if cat_a != cat_b:
        raise UnitError(f"Can't convert {cat_a} to {cat_b}.")
    if cat_a == "temperature":
        kelvin = _to_kelvin(value, unit_a)
        if kelvin < 0:
            raise UnitError("That is below absolute zero.")
        result = _from_kelvin(kelvin, unit_b)
    elif cat_a == "data":
        result = value * _DATA[unit_a] / _DATA[unit_b]
    else:
        table = _TABLE[cat_a]
        result = value * table[unit_a][0] / table[unit_b][0]
    return Conversion(value, unit_a, unit_b, result, cat_a)


def parse_and_convert(text: str) -> Conversion:
    match = _PARSE.match(text)
    if not match:
        raise UnitError("Format: /convert 10 km to mi   (also: 72 f to c, 5 GB to MB)")
    value = float(match.group("value").replace(",", "."))
    return convert(value, match.group("src"), match.group("dst"))


def supported_units() -> dict[str, list[str]]:
    out = {cat: list(units) for cat, units in _TABLE.items()}
    out["temperature"] = ["c", "f", "k"]
    out["data"] = list(_DATA)
    return out
