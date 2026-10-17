#!/usr/bin/env python3
"""Content pack generator for cam-telegram-bot.

Writes JSON packs into ``bot/data`` in the shape ``bot/content.py`` expects::

    {"category": ["entry", ...]}            # text kinds
    {"category": [{"q": "...", ...}, ...]}  # structured kinds (riddles, trivia)

For each kind it writes ``<kind>.json`` (curated, passed through unchanged) and
``<kind>.generated.json`` (new, seeded and reproducible).

Design rules
* Deterministic: every builder gets its own ``random.Random`` derived from ``seed`` and the builder
  name, so adding a builder never changes another builder's output.
* Atomic: files are written to a temp file in the same directory, fsynced, then ``os.replace``d, so a
  crash can never leave a half-written pack (and the temp name never matches the loader's ``*.json``).
* Strict: output is validated before anything is written; any error aborts with a non-zero exit code.
* Curated wins: generated entries that duplicate curated ones are removed before writing.
"""
from __future__ import annotations

import argparse
import contextlib
import itertools
import json
import os
import random
import re
import sys
import tempfile
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE.parent / "bot" / "data"
DEFAULT_SEED = 20261015

Payload = dict[str, list[Any]]
Builder = Callable[[random.Random], dict[str, Payload]]

MAX_ENTRY_CHARS = 1000
_STEM_RE = re.compile(r"^[a-z0-9_]+(?:\.[a-z0-9_]+)?$")  # must match bot/content.py's _PACK_NAME
_CATEGORY_RE = re.compile(r"^[a-z0-9_]+$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


# ======================================================================================
# fingerprints and de-duplication (mirrors bot/content.py::_fingerprint exactly)
# ======================================================================================
def fingerprint(entry: Any) -> str:
    if isinstance(entry, str):
        return re.sub(r"\W+", " ", entry.lower()).strip()
    if isinstance(entry, dict):
        text = entry.get("q") or entry.get("question") or entry.get("text") or entry
        return re.sub(r"\W+", " ", str(text).lower()).strip()
    return str(entry)


def unique(entries: list[Any], seen: set[str] | None = None) -> list[Any]:
    """Keep first occurrences, drop blanks and duplicates (by fingerprint); updates ``seen`` in place."""
    seen = set() if seen is None else seen
    out: list[Any] = []
    for entry in entries:
        if isinstance(entry, str):
            entry = entry.strip()
        key = fingerprint(entry)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(entry)
    return out


def payload_fingerprints(payload: Payload) -> set[str]:
    return {fingerprint(e) for entries in payload.values() for e in entries}


def dedupe_against(payload: Payload, reserved: set[str]) -> Payload:
    """Return ``payload`` without entries whose fingerprint is in ``reserved`` (or repeated inside it)."""
    seen = set(reserved)
    result: Payload = {}
    for category in sorted(payload):
        kept = unique(list(payload[category]), seen)
        if kept:
            result[category] = kept
    return result


# ======================================================================================
# atomic JSON writing
# ======================================================================================
def atomic_write_json(path: Path, payload: Any) -> None:
    """Serialize first (so a bad payload fails before touching disk), then replace atomically."""
    text = json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise


# ======================================================================================
# validation (generic shape rules; per-kind rules are added in stage 6)
# ======================================================================================
def validate_payload(stem: str, payload: Any) -> list[str]:
    errors: list[str] = []
    if not _STEM_RE.match(stem):
        errors.append(f"{stem}: file stem must match [a-z0-9_]+(.[a-z0-9_]+)? so the loader accepts it")
    if not isinstance(payload, dict) or not payload:
        return errors + [f"{stem}: payload must be a non-empty object of category -> list"]

    seen: set[str] = set()
    for category, entries in payload.items():
        where = f"{stem}[{category}]"
        if not isinstance(category, str) or not _CATEGORY_RE.match(category):
            errors.append(f"{where}: category must match [a-z0-9_]+")
        if not isinstance(entries, list) or not entries:
            errors.append(f"{where}: must be a non-empty list")
            continue
        for index, entry in enumerate(entries):
            label = f"{where}#{index}"
            if isinstance(entry, str):
                if not entry.strip():
                    errors.append(f"{label}: blank entry")
                elif entry != entry.strip():
                    errors.append(f"{label}: leading/trailing whitespace")
                elif len(entry) > MAX_ENTRY_CHARS:
                    errors.append(f"{label}: longer than {MAX_ENTRY_CHARS} characters")
                elif _CONTROL_RE.search(entry):
                    errors.append(f"{label}: contains control characters")
            elif isinstance(entry, dict):
                # fingerprint() falls back to str(entry), so it can't detect a missing text field
                text = entry.get("q") or entry.get("question") or entry.get("text")
                if not isinstance(text, str) or not text.strip():
                    errors.append(f"{label}: structured entry needs a non-empty q/question/text string")
            else:
                errors.append(f"{label}: entries must be strings or objects, got {type(entry).__name__}")
                continue
            key = fingerprint(entry)
            if key in seen:
                errors.append(f"{label}: duplicate of an earlier entry in the same file")
            seen.add(key)
    return errors


# ======================================================================================
# builder registry
# ======================================================================================
BUILDERS: list[tuple[str, Builder]] = []


def builder(name: str) -> Callable[[Builder], Builder]:
    """Register ``fn(rng) -> {file_stem: payload}``.  Order of registration is order of execution."""

    def decorator(fn: Builder) -> Builder:
        if any(existing == name for existing, _ in BUILDERS):
            raise ValueError(f"duplicate builder name {name!r}")
        BUILDERS.append((name, fn))
        return fn

    return decorator


def rng_for(seed: int, name: str) -> random.Random:
    """Independent, reproducible stream per builder (string seeds are hashed deterministically)."""
    return random.Random(f"{seed}:{name}")


def build_all(seed: int = DEFAULT_SEED) -> dict[str, Payload]:
    packs: dict[str, Payload] = {}
    for name, fn in BUILDERS:
        produced = fn(rng_for(seed, name))
        for stem, payload in produced.items():
            if stem in packs:
                raise ValueError(f"builder {name!r} produced {stem!r}, which another builder already produced")
            packs[stem] = payload
    return finalize(packs)


def finalize(packs: dict[str, Payload]) -> dict[str, Payload]:
    """Make curated entries authoritative: drop generated duplicates of ``<kind>`` from ``<kind>.generated``."""
    result = dict(packs)
    for stem in list(result):
        if stem.endswith(".generated"):
            base = stem[: -len(".generated")]
            if base in result:
                result[stem] = dedupe_against(result[stem], payload_fingerprints(result[base]))
    return {stem: payload for stem, payload in result.items() if payload}


def validate_all(packs: dict[str, Payload]) -> list[str]:
    errors: list[str] = []
    for stem in sorted(packs):
        errors.extend(validate_payload(stem, packs[stem]))
    return errors


def summarize(packs: dict[str, Payload]) -> str:
    if not packs:
        return "No packs were produced (no builders registered)."
    width = max(len(stem) for stem in packs)
    lines = []
    total = 0
    for stem in sorted(packs):
        count = sum(len(v) for v in packs[stem].values())
        total += count
        lines.append(f"  {stem:<{width}}  {count:>6} entries  {len(packs[stem]):>3} categories")
    lines.append(f"  {'TOTAL':<{width}}  {total:>6} entries")
    return "\n".join(lines)


# ======================================================================================
# STAGE 2: REFERENCE DATA TABLES (countries/capitals and chemical elements)
#
# Pure, immutable data: importing this module registers no builders and writes nothing.
#
# Country scope
#   * 193 UN member states, 2 UN non-member observer states (Holy See, Palestine) and 2 entities
#     with limited recognition (Taiwan, Kosovo), kept for completeness but excluded from quizzes.
#   * `region` follows the UN M49 geoscheme (so Turkey, Cyprus, Georgia, Armenia and Azerbaijan are
#     "asia", Russia is "europe"), not cultural or political groupings.
#   * `iso2` is ISO 3166-1 alpha-2, except Kosovo's "XK", a widely used user-assigned code.
#   * Where "the capital" is not a single uncontested fact, the entry carries a `note` and
#     `quiz_safe=False`.  Generators must only use `quiz_countries()` for factual claims.
#   * Time-sensitive entries (Indonesia, Equatorial Guinea) were checked against news reports in
#     Oct 2026; re-check them before relying on them.
# ======================================================================================
REGIONS = ("africa", "americas", "asia", "europe", "oceania")
STATUS_UN_MEMBER = "un_member"
STATUS_UN_OBSERVER = "un_observer"
STATUS_LIMITED = "limited_recognition"


class Country(NamedTuple):
    name: str
    iso2: str
    capital: str
    region: str
    status: str
    quiz_safe: bool
    note: str


# (name, iso2, capital) per region.  Ordered alphabetically by name within each region.
_AFRICA = (
    ("Algeria", "DZ", "Algiers"), ("Angola", "AO", "Luanda"), ("Benin", "BJ", "Porto-Novo"),
    ("Botswana", "BW", "Gaborone"), ("Burkina Faso", "BF", "Ouagadougou"), ("Burundi", "BI", "Gitega"),
    ("Cabo Verde", "CV", "Praia"), ("Cameroon", "CM", "Yaoundé"), ("Central African Republic", "CF", "Bangui"),
    ("Chad", "TD", "N'Djamena"), ("Comoros", "KM", "Moroni"), ("Côte d'Ivoire", "CI", "Yamoussoukro"),
    ("Democratic Republic of the Congo", "CD", "Kinshasa"), ("Djibouti", "DJ", "Djibouti"),
    ("Egypt", "EG", "Cairo"), ("Equatorial Guinea", "GQ", "Ciudad de la Paz"), ("Eritrea", "ER", "Asmara"),
    ("Eswatini", "SZ", "Mbabane"), ("Ethiopia", "ET", "Addis Ababa"), ("Gabon", "GA", "Libreville"),
    ("Gambia", "GM", "Banjul"), ("Ghana", "GH", "Accra"), ("Guinea", "GN", "Conakry"),
    ("Guinea-Bissau", "GW", "Bissau"), ("Kenya", "KE", "Nairobi"), ("Lesotho", "LS", "Maseru"),
    ("Liberia", "LR", "Monrovia"), ("Libya", "LY", "Tripoli"), ("Madagascar", "MG", "Antananarivo"),
    ("Malawi", "MW", "Lilongwe"), ("Mali", "ML", "Bamako"), ("Mauritania", "MR", "Nouakchott"),
    ("Mauritius", "MU", "Port Louis"), ("Morocco", "MA", "Rabat"), ("Mozambique", "MZ", "Maputo"),
    ("Namibia", "NA", "Windhoek"), ("Niger", "NE", "Niamey"), ("Nigeria", "NG", "Abuja"),
    ("Republic of the Congo", "CG", "Brazzaville"), ("Rwanda", "RW", "Kigali"),
    ("São Tomé and Príncipe", "ST", "São Tomé"), ("Senegal", "SN", "Dakar"), ("Seychelles", "SC", "Victoria"),
    ("Sierra Leone", "SL", "Freetown"), ("Somalia", "SO", "Mogadishu"), ("South Africa", "ZA", "Pretoria"),
    ("South Sudan", "SS", "Juba"), ("Sudan", "SD", "Khartoum"), ("Tanzania", "TZ", "Dodoma"),
    ("Togo", "TG", "Lomé"), ("Tunisia", "TN", "Tunis"), ("Uganda", "UG", "Kampala"),
    ("Zambia", "ZM", "Lusaka"), ("Zimbabwe", "ZW", "Harare"),
)
_AMERICAS = (
    ("Antigua and Barbuda", "AG", "Saint John's"), ("Argentina", "AR", "Buenos Aires"),
    ("Bahamas", "BS", "Nassau"), ("Barbados", "BB", "Bridgetown"), ("Belize", "BZ", "Belmopan"),
    ("Bolivia", "BO", "Sucre"), ("Brazil", "BR", "Brasília"), ("Canada", "CA", "Ottawa"),
    ("Chile", "CL", "Santiago"), ("Colombia", "CO", "Bogotá"), ("Costa Rica", "CR", "San José"),
    ("Cuba", "CU", "Havana"), ("Dominica", "DM", "Roseau"), ("Dominican Republic", "DO", "Santo Domingo"),
    ("Ecuador", "EC", "Quito"), ("El Salvador", "SV", "San Salvador"), ("Grenada", "GD", "Saint George's"),
    ("Guatemala", "GT", "Guatemala City"), ("Guyana", "GY", "Georgetown"), ("Haiti", "HT", "Port-au-Prince"),
    ("Honduras", "HN", "Tegucigalpa"), ("Jamaica", "JM", "Kingston"), ("Mexico", "MX", "Mexico City"),
    ("Nicaragua", "NI", "Managua"), ("Panama", "PA", "Panama City"), ("Paraguay", "PY", "Asunción"),
    ("Peru", "PE", "Lima"), ("Saint Kitts and Nevis", "KN", "Basseterre"), ("Saint Lucia", "LC", "Castries"),
    ("Saint Vincent and the Grenadines", "VC", "Kingstown"), ("Suriname", "SR", "Paramaribo"),
    ("Trinidad and Tobago", "TT", "Port of Spain"), ("United States", "US", "Washington, D.C."),
    ("Uruguay", "UY", "Montevideo"), ("Venezuela", "VE", "Caracas"),
)
_ASIA = (
    ("Afghanistan", "AF", "Kabul"), ("Armenia", "AM", "Yerevan"), ("Azerbaijan", "AZ", "Baku"),
    ("Bahrain", "BH", "Manama"), ("Bangladesh", "BD", "Dhaka"), ("Bhutan", "BT", "Thimphu"),
    ("Brunei", "BN", "Bandar Seri Begawan"), ("Cambodia", "KH", "Phnom Penh"), ("China", "CN", "Beijing"),
    ("Cyprus", "CY", "Nicosia"), ("Georgia", "GE", "Tbilisi"), ("India", "IN", "New Delhi"),
    ("Indonesia", "ID", "Jakarta"), ("Iran", "IR", "Tehran"), ("Iraq", "IQ", "Baghdad"),
    ("Israel", "IL", "Jerusalem"), ("Japan", "JP", "Tokyo"), ("Jordan", "JO", "Amman"),
    ("Kazakhstan", "KZ", "Astana"), ("Kuwait", "KW", "Kuwait City"), ("Kyrgyzstan", "KG", "Bishkek"),
    ("Laos", "LA", "Vientiane"), ("Lebanon", "LB", "Beirut"), ("Malaysia", "MY", "Kuala Lumpur"),
    ("Maldives", "MV", "Malé"), ("Mongolia", "MN", "Ulaanbaatar"), ("Myanmar", "MM", "Naypyidaw"),
    ("Nepal", "NP", "Kathmandu"), ("North Korea", "KP", "Pyongyang"), ("Oman", "OM", "Muscat"),
    ("Pakistan", "PK", "Islamabad"), ("Philippines", "PH", "Manila"), ("Qatar", "QA", "Doha"),
    ("Saudi Arabia", "SA", "Riyadh"), ("Singapore", "SG", "Singapore"), ("South Korea", "KR", "Seoul"),
    ("Sri Lanka", "LK", "Sri Jayawardenepura Kotte"), ("Syria", "SY", "Damascus"),
    ("Tajikistan", "TJ", "Dushanbe"), ("Thailand", "TH", "Bangkok"), ("Timor-Leste", "TL", "Dili"),
    ("Turkey", "TR", "Ankara"), ("Turkmenistan", "TM", "Ashgabat"), ("United Arab Emirates", "AE", "Abu Dhabi"),
    ("Uzbekistan", "UZ", "Tashkent"), ("Vietnam", "VN", "Hanoi"), ("Yemen", "YE", "Sana'a"),
)
_EUROPE = (
    ("Albania", "AL", "Tirana"), ("Andorra", "AD", "Andorra la Vella"), ("Austria", "AT", "Vienna"),
    ("Belarus", "BY", "Minsk"), ("Belgium", "BE", "Brussels"), ("Bosnia and Herzegovina", "BA", "Sarajevo"),
    ("Bulgaria", "BG", "Sofia"), ("Croatia", "HR", "Zagreb"), ("Czechia", "CZ", "Prague"),
    ("Denmark", "DK", "Copenhagen"), ("Estonia", "EE", "Tallinn"), ("Finland", "FI", "Helsinki"),
    ("France", "FR", "Paris"), ("Germany", "DE", "Berlin"), ("Greece", "GR", "Athens"),
    ("Hungary", "HU", "Budapest"), ("Iceland", "IS", "Reykjavík"), ("Ireland", "IE", "Dublin"),
    ("Italy", "IT", "Rome"), ("Latvia", "LV", "Riga"), ("Liechtenstein", "LI", "Vaduz"),
    ("Lithuania", "LT", "Vilnius"), ("Luxembourg", "LU", "Luxembourg City"), ("Malta", "MT", "Valletta"),
    ("Moldova", "MD", "Chișinău"), ("Monaco", "MC", "Monaco"), ("Montenegro", "ME", "Podgorica"),
    ("Netherlands", "NL", "Amsterdam"), ("North Macedonia", "MK", "Skopje"), ("Norway", "NO", "Oslo"),
    ("Poland", "PL", "Warsaw"), ("Portugal", "PT", "Lisbon"), ("Romania", "RO", "Bucharest"),
    ("Russia", "RU", "Moscow"), ("San Marino", "SM", "San Marino"), ("Serbia", "RS", "Belgrade"),
    ("Slovakia", "SK", "Bratislava"), ("Slovenia", "SI", "Ljubljana"), ("Spain", "ES", "Madrid"),
    ("Sweden", "SE", "Stockholm"), ("Switzerland", "CH", "Bern"), ("Ukraine", "UA", "Kyiv"),
    ("United Kingdom", "GB", "London"),
)
_OCEANIA = (
    ("Australia", "AU", "Canberra"), ("Fiji", "FJ", "Suva"), ("Kiribati", "KI", "South Tarawa"),
    ("Marshall Islands", "MH", "Majuro"), ("Micronesia", "FM", "Palikir"), ("Nauru", "NR", "Yaren"),
    ("New Zealand", "NZ", "Wellington"), ("Palau", "PW", "Ngerulmud"), ("Papua New Guinea", "PG", "Port Moresby"),
    ("Samoa", "WS", "Apia"), ("Solomon Islands", "SB", "Honiara"), ("Tonga", "TO", "Nukuʻalofa"),
    ("Tuvalu", "TV", "Funafuti"), ("Vanuatu", "VU", "Port Vila"),
)
# Non-members, stated explicitly: (name, iso2, capital, region, status)
_NON_MEMBERS = (
    ("Vatican City", "VA", "Vatican City", "europe", STATUS_UN_OBSERVER),
    ("Palestine", "PS", "East Jerusalem", "asia", STATUS_UN_OBSERVER),
    ("Taiwan", "TW", "Taipei", "asia", STATUS_LIMITED),
    ("Kosovo", "XK", "Pristina", "europe", STATUS_LIMITED),
)

# iso2 -> (note, quiz_safe).  Every entry whose capital is contested, split, changing or ambiguous
# must be listed here; `validate_reference_data()` enforces that unsafe entries carry a note.
_SPECIAL_CASES: dict[str, tuple[str, bool]] = {
    "BJ": ("Porto-Novo is the official capital; the government sits in Cotonou.", False),
    "BI": ("Gitega is the political capital (moved from Bujumbura in 2019); Bujumbura remains the economic capital.", False),
    "CI": ("Yamoussoukro is the official capital; Abidjan is the economic centre and de facto seat of government.", False),
    "GQ": ("A decree of 2 Jan 2026 reportedly transferred the capital from Malabo (capital since 1968) to Ciudad de la Paz; "
           "institutions were given about a year to relocate, and many references still list Malabo. Verify before use.", False),
    "SZ": ("Mbabane is the administrative capital; Lobamba is the legislative and royal capital.", False),
    "ZA": ("Three capitals: Pretoria (executive), Cape Town (legislative), Bloemfontein (judicial).", False),
    "TZ": ("Dodoma is the official capital; Dar es Salaam is the largest city and former capital.", True),
    "BO": ("Sucre is the constitutional capital; La Paz is the seat of government.", False),
    "CL": ("Santiago is the capital; the National Congress sits in Valparaíso.", True),
    "ID": ("Jakarta remains the capital until a presidential decree transfers the status to Nusantara "
           "(Constitutional Court, May 2026); no such decree had been reported.", False),
    "IL": ("Israel designates Jerusalem as its capital; Jerusalem's status is disputed internationally and "
           "countries differ on where they place embassies.", False),
    "MY": ("Kuala Lumpur is the national capital; the federal administration is based in Putrajaya.", True),
    "LK": ("Sri Jayawardenepura Kotte is the legislative/official capital; Colombo is the commercial capital "
           "and hosts much of the government.", False),
    "YE": ("Sana'a is the constitutional capital but has been under Houthi control since 2014; Aden serves as "
           "the internationally recognized government's temporary seat.", False),
    "CH": ("Switzerland has no de jure capital; Bern is the 'federal city' and seat of government.", True),
    "NL": ("Amsterdam is the constitutional capital; the government and parliament sit in The Hague.", True),
    "CY": ("Nicosia is divided; the north is administered by the self-declared Turkish Republic of Northern "
           "Cyprus, recognized only by Turkey.", True),
    "KI": ("Government offices are on South Tarawa (Tarawa atoll); sources list either 'Tarawa' or 'South Tarawa'.", False),
    "NR": ("Nauru has no official capital; Yaren is the de facto seat of government.", False),
    "VA": ("The Holy See is a UN non-member observer state; Vatican City is a city-state.", True),
    "PS": ("Palestine declares East Jerusalem its capital; the administrative centre is Ramallah.", False),
    "TW": ("Taiwan's political status is disputed; included for completeness and excluded from quizzes.", False),
    "XK": ("Kosovo declared independence in 2008; it is recognized by many but not all states and is not a UN member.", False),
}


def _build_countries() -> tuple[Country, ...]:
    rows: list[Country] = []
    for region, table in (
        ("africa", _AFRICA), ("americas", _AMERICAS), ("asia", _ASIA), ("europe", _EUROPE), ("oceania", _OCEANIA),
    ):
        for name, iso2, capital in table:
            note, safe = _SPECIAL_CASES.get(iso2, ("", True))
            rows.append(Country(name, iso2, capital, region, STATUS_UN_MEMBER, safe, note))
    for name, iso2, capital, region, status in _NON_MEMBERS:
        note, safe = _SPECIAL_CASES.get(iso2, ("", True))
        rows.append(Country(name, iso2, capital, region, status, safe, note))
    return tuple(rows)


COUNTRIES: tuple[Country, ...] = _build_countries()


def countries_by_region(members_only: bool = False) -> dict[str, list[Country]]:
    result: dict[str, list[Country]] = {region: [] for region in REGIONS}
    for country in COUNTRIES:
        if members_only and country.status != STATUS_UN_MEMBER:
            continue
        result[country.region].append(country)
    return result


def quiz_countries() -> list[Country]:
    """UN members whose capital is an uncontested single answer; the only safe source for factual claims."""
    return [c for c in COUNTRIES if c.status == STATUS_UN_MEMBER and c.quiz_safe]


def fold(text: str) -> str:
    """ASCII-fold for answer matching: 'Bogotá' -> 'Bogota', 'Nukuʻalofa' -> "Nuku'alofa"."""
    text = text.replace("ʻ", "'").replace("’", "'")
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


class Element(NamedTuple):
    number: int
    symbol: str
    name: str


# IUPAC English spellings, in atomic-number order (the position in the string IS the atomic number).
_ELEMENT_SPEC = """
H:Hydrogen He:Helium Li:Lithium Be:Beryllium B:Boron C:Carbon N:Nitrogen O:Oxygen F:Fluorine Ne:Neon
Na:Sodium Mg:Magnesium Al:Aluminium Si:Silicon P:Phosphorus S:Sulfur Cl:Chlorine Ar:Argon
K:Potassium Ca:Calcium Sc:Scandium Ti:Titanium V:Vanadium Cr:Chromium Mn:Manganese Fe:Iron Co:Cobalt
Ni:Nickel Cu:Copper Zn:Zinc Ga:Gallium Ge:Germanium As:Arsenic Se:Selenium Br:Bromine Kr:Krypton
Rb:Rubidium Sr:Strontium Y:Yttrium Zr:Zirconium Nb:Niobium Mo:Molybdenum Tc:Technetium Ru:Ruthenium
Rh:Rhodium Pd:Palladium Ag:Silver Cd:Cadmium In:Indium Sn:Tin Sb:Antimony Te:Tellurium I:Iodine Xe:Xenon
Cs:Caesium Ba:Barium La:Lanthanum Ce:Cerium Pr:Praseodymium Nd:Neodymium Pm:Promethium Sm:Samarium
Eu:Europium Gd:Gadolinium Tb:Terbium Dy:Dysprosium Ho:Holmium Er:Erbium Tm:Thulium Yb:Ytterbium
Lu:Lutetium Hf:Hafnium Ta:Tantalum W:Tungsten Re:Rhenium Os:Osmium Ir:Iridium Pt:Platinum Au:Gold
Hg:Mercury Tl:Thallium Pb:Lead Bi:Bismuth Po:Polonium At:Astatine Rn:Radon
Fr:Francium Ra:Radium Ac:Actinium Th:Thorium Pa:Protactinium U:Uranium Np:Neptunium Pu:Plutonium
Am:Americium Cm:Curium Bk:Berkelium Cf:Californium Es:Einsteinium Fm:Fermium Md:Mendelevium
No:Nobelium Lr:Lawrencium Rf:Rutherfordium Db:Dubnium Sg:Seaborgium Bh:Bohrium Hs:Hassium
Mt:Meitnerium Ds:Darmstadtium Rg:Roentgenium Cn:Copernicium Nh:Nihonium Fl:Flerovium Mc:Moscovium
Lv:Livermorium Ts:Tennessine Og:Oganesson
"""

ELEMENTS: tuple[Element, ...] = tuple(
    Element(number, *token.split(":"))
    for number, token in enumerate(_ELEMENT_SPEC.split(), start=1)
)

# Accepted alternative English spellings (IUPAC name -> common regional variant).
ELEMENT_ALT_NAMES: dict[str, str] = {
    "Aluminium": "Aluminum",
    "Caesium": "Cesium",
    "Sulfur": "Sulphur",
}


def validate_reference_data() -> list[str]:
    """Internal-consistency checks for the Stage 2 tables; returns a list of problems (empty = OK)."""
    problems: list[str] = []
    for label, values in (
        ("country name", [fold(c.name).lower() for c in COUNTRIES]),
        ("country iso2", [c.iso2 for c in COUNTRIES]),
        ("capital", [fold(c.capital).lower() for c in COUNTRIES]),
        ("element symbol", [e.symbol for e in ELEMENTS]),
        ("element name", [e.name for e in ELEMENTS]),
    ):
        duplicates = sorted({v for v in values if values.count(v) > 1})
        if duplicates:
            problems.append(f"duplicate {label}: {duplicates}")
    for country in COUNTRIES:
        if country.region not in REGIONS:
            problems.append(f"{country.name}: unknown region {country.region!r}")
        if not (country.name.strip() and country.capital.strip()):
            problems.append(f"{country.iso2}: blank name or capital")
        if not country.quiz_safe and not country.note:
            problems.append(f"{country.name}: quiz_safe=False requires an explanatory note")
        if country.status == STATUS_LIMITED and country.quiz_safe:
            problems.append(f"{country.name}: limited-recognition entities must not be quiz_safe")
    unknown = sorted(set(_SPECIAL_CASES) - {c.iso2 for c in COUNTRIES})
    if unknown:
        problems.append(f"special-case iso2 codes not in the dataset: {unknown}")
    if [e.number for e in ELEMENTS] != list(range(1, 119)):
        problems.append("elements must be numbered 1..118 without gaps")
    return problems


# ======================================================================================
# STAGE 3: template-based text generators
#
# Each ``generate_*(rng, cap)`` takes a seeded ``random.Random`` and a cap on the TOTAL number of entries,
# and returns ``{category: [entries]}`` (only non-empty categories; ``{}`` when ``cap == 0``).
# They are plain functions and are deliberately NOT registered with ``@builder`` yet: wiring happens in
# stage 5, so running the CLI still writes nothing.
#
# Design rules
# * Deterministic and cross-version stable: selection uses ``rng.getrandbits`` keys, never ``rng.sample`` or
#   ``rng.shuffle`` (whose algorithms may change between Python versions), and never touches global state.
# * Every candidate is linted (grammar-level checks) before selection; a bad template raises instead of
#   silently shipping a broken sentence.
# * Case-insensitive de-duplication across ALL categories of one generator (same fingerprint as the loader).
# * Caps are exact: ``len(all entries) == min(cap, unique capacity)``, shared fairly between categories.
# * Labeling: quotes are original, unattributed text (categories are prefixed ``original_``); fortunes
#   carry a playful "just for fun" label and hedged wording, and are never presented as real predictions.
# ======================================================================================
DEFAULT_CAPS: dict[str, int] = {
    "jokes": 1500,
    "quotes": 2000,
    "compliments": 200,
    "fortunes": 600,
    "would_you_rather": 900,
}

_AN_EXCEPT_A = frozenset({"one", "once", "unicorn", "university", "user", "useful", "uniform", "unit", "united", "european", "uk"})
_A_EXCEPT_AN = frozenset({"hour", "honest", "heir", "honor", "honour"})
_ARTICLE_RE = re.compile(r"\b(a|an)\s+([A-Za-z][A-Za-z'-]*)", re.IGNORECASE)
_REPEAT_RE = re.compile(r"\b(\w+)\s+\1\b", re.IGNORECASE)
_END_RE = re.compile(r"[.?!][\"']?$")


# --------------------------------------------------------------------------- helpers
def check_cap(cap: Any) -> int:
    """Validate a cap: a real int (not bool) >= 0."""
    if isinstance(cap, bool) or not isinstance(cap, int):
        raise TypeError(f"cap must be an int, got {type(cap).__name__}")
    if cap < 0:
        raise ValueError(f"cap must be >= 0, got {cap}")
    return cap


def check_rng(rng: Any) -> random.Random:
    if not isinstance(rng, random.Random):
        raise TypeError(f"rng must be a random.Random instance, got {type(rng).__name__}")
    return rng


def cap_first(text: str) -> str:
    return text[:1].upper() + text[1:]


def stable_pick(rng: random.Random, items: Sequence[Any], n: int) -> list[Any]:
    """Pick ``n`` distinct items in a seeded order using only ``getrandbits`` (stable across Python versions)."""
    check_rng(rng)
    items = list(items)
    if n <= 0 or not items:
        return []
    keyed = sorted((rng.getrandbits(64), index) for index in range(len(items)))
    return [items[index] for _, index in keyed[:n]]


def allocate(cap: int, sizes: Mapping[str, int], rng: random.Random) -> dict[str, int]:
    """Split ``cap`` across families fairly (water-filling).

    Small families are taken whole; the rest share what is left evenly; when fewer slots remain than families,
    the seeded ``rng`` decides which families get the extra one.  ``sum(result) == min(cap, sum(sizes))`` and
    ``result[name] <= sizes[name]`` always hold.
    """
    check_cap(cap)
    check_rng(rng)
    if any(size < 0 for size in sizes.values()):
        raise ValueError("family sizes must be >= 0")
    alloc = {name: 0 for name in sizes}
    active = sorted(name for name, size in sizes.items() if size > 0)
    remaining = min(cap, sum(sizes[name] for name in active))
    while remaining > 0 and active:
        share, extra = divmod(remaining, len(active))
        if share == 0:
            order = sorted(active, key=lambda name: (rng.getrandbits(64), name))
            for name in order[:extra]:
                alloc[name] += 1
            return alloc
        full = [name for name in active if sizes[name] - alloc[name] <= share]
        if full:
            for name in full:
                remaining -= sizes[name] - alloc[name]
                alloc[name] = sizes[name]
            active = [name for name in active if name not in full]
        else:
            for name in active:
                alloc[name] += share
            remaining -= share * len(active)
    return alloc


def lint_text(text: str) -> list[str]:
    """Grammar-level checks for one generated entry; returns a list of problems (empty means clean)."""
    problems: list[str] = []
    if not isinstance(text, str) or not text:
        return ["empty or non-string entry"]
    if "{" in text or "}" in text:
        problems.append("unresolved template braces")
    if text != text.strip():
        problems.append("leading/trailing whitespace")
    if "  " in text:
        problems.append("double space")
    if len(text) > MAX_ENTRY_CHARS:
        problems.append("too long")
    if not (text[:1].isupper() or text[:1].isdigit()):
        problems.append("must start with a capital letter or digit")
    if not _END_RE.search(text):
        problems.append("must end with . ? or !")
    if _REPEAT_RE.search(text):
        problems.append("repeated word")
    for match in _ARTICLE_RE.finditer(text):
        word = re.split(r"[-']", match.group(2).lower())[0] or match.group(2).lower()  # "one-time" -> "one"
        wants_an = word[0] in "aeiou"
        if word in _AN_EXCEPT_A:
            wants_an = False
        elif word in _A_EXCEPT_AN:
            wants_an = True
        if (match.group(1).lower() == "an") != wants_an:
            problems.append(f"a/an disagreement before {word!r}")
    return problems


def assemble(rng: random.Random, cap: int, families: Mapping[str, Sequence[str]]) -> dict[str, list[str]]:
    """Lint, de-duplicate (across all families, case-insensitively), allocate the cap, pick, and return."""
    check_rng(rng)
    check_cap(cap)
    if cap == 0:
        return {}
    seen: set[str] = set()
    pools: dict[str, list[str]] = {}
    for name in sorted(families):
        for text in families[name]:
            problems = lint_text(text)
            if problems:
                raise ValueError(f"template bug in {name!r}: {text!r}: {'; '.join(problems)}")
        pools[name] = unique(list(families[name]), seen)
    quotas = allocate(cap, {name: len(pool) for name, pool in pools.items()}, rng)
    out: dict[str, list[str]] = {}
    for name in sorted(pools):
        picked = stable_pick(rng, pools[name], quotas[name])
        if picked:
            out[name] = picked
    return out


# --------------------------------------------------------------------------- jokes
JOKE_AUTHORITIES = (
    "my doctor", "my barber", "my accountant", "my grandmother", "my dentist", "my neighbor",
    "the bartender", "the librarian", "my personal trainer", "my mechanic", "a very confident stranger",
    "the barista", "my cat", "my dog", "my houseplant", "my reflection", "a passing pigeon", "my rubber duck",
    "the GPS", "the office printer", "my smart speaker", "my teacher", "the wise old tortoise",
    "a fortune cookie", "my alarm clock", "the tour guide", "my landlord", "my hairdresser",
    "a talking parrot", "the lifeguard",
)
JOKE_PROBLEMS = (
    "my procrastination", "my sleep schedule", "my overflowing inbox", "my Wi-Fi", "my motivation",
    "my budget", "my tangled headphones", "my never-ending to-do list", "my cooking", "my garden",
    "my morning routine", "my terrible sense of direction", "my sourdough starter", "my phone storage",
)
JOKE_ANSWERS = (
    "Have you tried turning it off and on again.", "That sounds like a Monday problem.",
    "Honestly, I would sleep on it.", "Bold of you to assume there is a plan.",
    "Everything is a learning experience, including this.", "Let me get back to you next year.",
    "I charge extra for obvious questions.", "Have you considered doing it tomorrow.",
    "That is above my pay grade.", "I would add more coffee.", "Technically, that is a feature.",
    "Panic quietly and carry on.", "It worked on my machine.", "Write it down and ignore it.",
)
JOKE_ADVICE_TEMPLATES = (
    'I asked {authority} what to do about {problem}, and the answer was, "{answer}"',
    'For help with {problem}, I consulted {authority}. The entire reply was, "{answer}"',
)
JOKE_THEMES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "sleep": (
        ("I'm tired", "I love my bed", "mornings and I are not friends", "I could use a nap",
         "I stay up too late", "I need more sleep"),
        ("my pillow knows my name", "my alarm clock has stopped making eye contact",
         "the snooze button needs a vacation", "my blanket has applied for a promotion",
         "my mattress asks how my day went", "my dreams are mostly reruns"),
    ),
    "messy_digital_life": (
        ("my code is messy", "my desktop is cluttered", "I have too many browser tabs open",
         "my project folders are chaos", "my file names need work", "I never close anything"),
        ("the comments are mostly apologies", "my browser is holding a support group for the tabs",
         "even the bugs have started filing tickets", "my commit messages read like cries for help",
         "my desktop has its own weather system", "my search history needs a table of contents"),
    ),
    "food_lover": (
        ("I love snacks", "I take dessert seriously", "I'm always hungry", "I think about lunch at breakfast",
         "I'm a big fan of bread", "I'm a coffee person"),
        ("my fridge light is my favorite spotlight", "the bakery knows my order by heart",
         "my snack drawer has a snack drawer", "I have a loyalty card for three different bakeries",
         "my lunch plans begin at breakfast", "the delivery driver sends me holiday cards"),
    ),
    "frugal": (
        ("I love a bargain", "I'm careful with money", "I hate paying full price", "I always check the receipt",
         "I compare prices obsessively", "I save every coupon"),
        ("the sale sign and I have an understanding", "I own a coupon folder with its own filing system",
         "my wallet has not seen daylight in years", "the cashier knows me by my coupons",
         "I have haggled with a vending machine", "my receipts have their own filing cabinet"),
    ),
    "lazy": (
        ("I'm not very athletic", "I avoid exercise", "I prefer sitting", "I'm allergic to jogging",
         "I love my couch", "I'm saving my energy"),
        ("my fitness tracker sends me sympathy cards", "the couch has a permanent dent shaped like me",
         "my sneakers still have the price tag on", "I count carrying the groceries as cardio",
         "the stairs and I are strangers", "my gym membership is a very expensive reminder"),
    ),
    "forgetful": (
        ("I'm a bit forgetful", "my memory is not great", "I lose things often", "I forget names",
         "I walk into rooms and forget why", "I misplace my keys"),
        ("my keys have their own witness protection program", "I have searched for my glasses while wearing them",
         "my to-do list has a to-do list", "I have met my neighbors four separate times",
         "my sticky notes have sticky notes", "I rely on my calendar to remember my calendar"),
    ),
}
JOKE_BAR_CHARACTERS = (
    "A skeleton", "A ghost", "A robot", "A penguin", "A dragon", "A very polite octopus", "A pirate",
    "A wizard", "A time traveler", "An astronaut", "A tired programmer", "A giraffe", "A snowman",
    "A vampire", "A mummy", "A cowboy", "A clown", "An alien", "A goldfish", "A knight in shining armor",
    "A lost tourist", "A talking horse", "A sleepy bear", "A chicken", "A scarecrow", "A caveman",
    "A detective", "A ninja", "A scientist",
)
JOKE_BAR_ORDERS = (
    "I'll have whatever is on tap.", "One drink, please, and make it a double.",
    "Could I get a glass of water with extra ice?", "I'll have the special.",
    "Something tall, cold and slightly dramatic, please.", "I would like a quiet corner table.",
    "Surprise me.", "I'll have what the last customer had.", "Make mine a mocktail.",
    "One round for the whole room, please.", "I'll have a lemonade and a good story.",
    "Just a small snack and a big chair, please.",
)
JOKE_BAR_REPLIES = (
    "Coming right up.", "That is the strangest order I have heard today.", "Sure, but you are paying in advance.",
    "We were just about to close.", "Take a seat and I will see what I can do.", "Sorry, we only serve regulars.",
    "You are the third one tonight.", "Funny, you do not look like a regular.", "No problem, but the music stays on.",
    "I will need to check with the manager.", "Right away, and the first one is on the house.",
    "Pull up a stool, friend.",
)


def generate_jokes(rng: random.Random, cap: int = DEFAULT_CAPS["jokes"]) -> dict[str, list[str]]:
    """Three template families: ``advice``, ``not_saying``, ``bar_walk_in`` (original, unattributed)."""
    check_rng(rng)
    check_cap(cap)
    if cap == 0:
        return {}
    advice = [
        template.format(authority=authority, problem=problem, answer=answer)
        for template in JOKE_ADVICE_TEMPLATES
        for authority in JOKE_AUTHORITIES
        for problem in JOKE_PROBLEMS
        for answer in JOKE_ANSWERS
    ]
    not_saying = [
        f"I'm not saying {premise}, but {consequence}."
        for theme in sorted(JOKE_THEMES)
        for premise in JOKE_THEMES[theme][0]
        for consequence in JOKE_THEMES[theme][1]
    ]
    bar = [
        f'{character} walks into a bar and says, "{order}" The bartender says, "{reply}"'
        for character in JOKE_BAR_CHARACTERS
        for order in JOKE_BAR_ORDERS
        for reply in JOKE_BAR_REPLIES
    ]
    return assemble(rng, cap, {"advice": advice, "not_saying": not_saying, "bar_walk_in": bar})


# --------------------------------------------------------------------------- quotes
# Original, unattributed aphorisms.  Category names carry an ``original_`` prefix so nothing can be mistaken
# for a quotation by a real person.
QUOTE_REFRAME_THEMES: dict[str, tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = {
    "effort": (
        ("Progress", "Improvement", "Mastery", "Consistency", "Growth"),
        ("a straight line", "a race", "a single leap", "a matter of luck", "something that happens overnight",
         "a performance for others"),
        ("a habit repeated on ordinary days", "many small steps taken on purpose", "a pile of unglamorous days",
         "a quiet decision made again and again", "patience paid in installments", "the result of showing up"),
    ),
    "courage": (
        ("Courage", "Bravery", "Confidence", "Resilience", "Boldness"),
        ("the absence of fear", "a loud performance", "a gift only a few people receive", "the absence of doubt",
         "something you wait to feel", "a trait you either have or lack"),
        ("taking the next step while afraid", "acting even when your hands shake",
         "a decision made in spite of doubt", "a skill that grows with use",
         "showing up before you feel ready", "a small yes in a loud room"),
    ),
    "care": (
        ("Kindness", "Generosity", "Compassion", "Respect", "Friendship"),
        ("a grand gesture", "a weakness", "a favor you owe", "something reserved for special days",
         "a transaction", "a debt to repay"),
        ("attention given freely", "a small act repeated daily", "listening without waiting to reply",
         "making room for someone else", "a habit of noticing others", "warmth that costs very little"),
    ),
    "rest": (
        ("Rest", "Sleep", "Stillness", "Balance", "Recovery"),
        ("laziness", "a reward for finishing", "wasted time", "a luxury", "giving up", "a break from real effort"),
        ("part of the work", "how strength is rebuilt", "a pause that makes the next step possible",
         "fuel for tomorrow", "the quiet half of every good effort", "a skill worth practicing"),
    ),
    "curiosity": (
        ("Curiosity", "Learning", "Wisdom", "Creativity", "Imagination"),
        ("knowing all the answers", "a talent you are born with", "something that only happens in school",
         "a spare-time hobby", "a finish line", "a luxury for later"),
        ("the courage to ask again", "a habit of asking better questions", "practice that never quite ends",
         "a door you keep opening", "the joy of not knowing yet", "attention turned into something new"),
    ),
}
QUOTE_START_CONDITIONS = (
    "perfect conditions", "the right mood", "a better moment", "someone's permission", "all the answers",
    "a guarantee", "more time", "a clearer sign", "the fear to fade", "everything to line up",
)
QUOTE_START_ACTIONS = (
    "begin with what you have", "take one small step", "write the first line", "make the first call",
    "start badly and improve", "give it ten honest minutes", "open the file", "put on your shoes",
    "clear one small corner", "say the first sentence",
)
QUOTE_START_RESULTS = (
    "momentum", "clarity", "confidence", "a plan", "progress", "courage", "energy", "direction", "rhythm",
    "the next step",
)
QUOTE_DEPOSIT_THINGS = (
    "page you read today", "small step you take today", "kind word you offer today", "honest hour you work today",
    "scale you practice today", "note you play today", "line you write today", "question you ask today",
    "apology you offer today", "walk you take today", "meal you cook today", "call you return today",
    "habit you keep today", "boundary you set today", "minute you spend listening today",
)
QUOTE_DEPOSIT_GIFTS = ("a deposit in", "a gift to", "an investment in", "a vote for", "a seed for", "a step toward")
QUOTE_DEPOSIT_FUTURES = (
    "your future self", "the person you are becoming", "tomorrow's confidence", "your long-term goals",
    "the habits that last", "a calmer year ahead",
)
QUOTE_REWARD_NOUNS = (
    "Patience", "Effort", "Honesty", "Curiosity", "Consistency", "Kindness", "Humility", "Courage",
)
QUOTE_REWARD_PAIRS = (
    ("keep showing up", "only show up when it is easy"),
    ("ask good questions", "pretend to know everything"),
    ("listen first", "wait for their turn to talk"),
    ("finish what they start", "chase every new idea"),
    ("practice quietly", "only perform"),
    ("admit mistakes", "hide them"),
    ("stay with the work", "look for shortcuts"),
    ("plan the next step", "hope the path appears"),
)


def generate_quotes(rng: random.Random, cap: int = DEFAULT_CAPS["quotes"]) -> dict[str, list[str]]:
    """Four aphorism families, all original and unattributed: ``original_reframe``, ``original_start_now``,
    ``original_daily_deposit`` and ``original_rewards``."""
    check_rng(rng)
    check_cap(cap)
    if cap == 0:
        return {}
    reframe = [
        f"{virtue} is not {misconception}; it is {truth}."
        for theme in sorted(QUOTE_REFRAME_THEMES)
        for virtue in QUOTE_REFRAME_THEMES[theme][0]
        for misconception in QUOTE_REFRAME_THEMES[theme][1]
        for truth in QUOTE_REFRAME_THEMES[theme][2]
    ]
    start_now = [
        f"Do not wait for {condition}; {action}, and {result} will follow."
        for condition in QUOTE_START_CONDITIONS
        for action in QUOTE_START_ACTIONS
        for result in QUOTE_START_RESULTS
    ]
    deposit = [
        f"Every {thing} is {gift} {future}."
        for thing in QUOTE_DEPOSIT_THINGS
        for gift in QUOTE_DEPOSIT_GIFTS
        for future in QUOTE_DEPOSIT_FUTURES
    ]
    rewards = [
        f"{noun} rewards those who {behavior}, not those who {anti}."
        for noun in QUOTE_REWARD_NOUNS
        for behavior, anti in QUOTE_REWARD_PAIRS
    ]
    return assemble(rng, cap, {
        "original_reframe": reframe,
        "original_start_now": start_now,
        "original_daily_deposit": deposit,
        "original_rewards": rewards,
    })


# --------------------------------------------------------------------------- compliments
COMPLIMENT_TRAITS = (
    "kindness", "sense of humor", "creativity", "patience", "curiosity", "determination", "generosity",
    "honesty", "enthusiasm", "imagination",
)
COMPLIMENT_SIMILES = (
    ("bright", "a lighthouse at midnight"), ("warm", "fresh bread on a cold morning"),
    ("steady", "a mountain in the rain"), ("sharp", "a freshly sharpened pencil"),
    ("refreshing", "a cold glass of water on a hot day"), ("reliable", "the sunrise"),
    ("rare", "a quiet moment in a busy city"), ("comforting", "a favorite blanket"),
    ("clear", "a mountain lake"), ("bold", "a splash of bright paint"), ("gentle", "a summer breeze"),
    ("sparkling", "a clear night sky"),
)
COMPLIMENT_HARD_THINGS = (
    "hard problems", "early mornings", "busy days", "tricky decisions", "long projects", "complicated ideas",
)
COMPLIMENT_LOOKS = ("easy", "effortless", "graceful", "simple", "natural")
COMPLIMENT_QUALITIES = (
    "Kindness", "Curiosity", "Generosity", "Honesty", "Patience", "Creativity", "Enthusiasm",
)
COMPLIMENT_EFFECTS = (
    "the people around you feel at ease", "teams enjoy working with you", "rooms feel warmer when you arrive",
    "problems feel smaller around you", "good ideas find a home near you", "people trust you with their stories",
    "ordinary days feel brighter", "everyone leaves a little happier",
)


def generate_compliments(rng: random.Random, cap: int = DEFAULT_CAPS["compliments"]) -> dict[str, list[str]]:
    """Three families: ``as_as``, ``you_make`` and ``like_yours``."""
    check_rng(rng)
    check_cap(cap)
    if cap == 0:
        return {}
    as_as = [
        f"Your {trait} is as {adjective} as {metaphor}."
        for trait in COMPLIMENT_TRAITS
        for adjective, metaphor in COMPLIMENT_SIMILES
    ]
    you_make = [
        f"You make {hard} look {look}."
        for hard in COMPLIMENT_HARD_THINGS
        for look in COMPLIMENT_LOOKS
    ]
    like_yours = [
        f"{quality} like yours is why {effect}."
        for quality in COMPLIMENT_QUALITIES
        for effect in COMPLIMENT_EFFECTS
    ]
    return assemble(rng, cap, {"as_as": as_as, "you_make": you_make, "like_yours": like_yours})


# --------------------------------------------------------------------------- fortunes
# Entertainment only.  Every entry starts with a playful label, forecasts are hedged ("might", "may",
# "could"; never "will") and nothing touches health, money or other real-world decisions.
FORTUNE_FORECAST_LABELS = (
    "Just for fun:", "Cookie forecast (entertainment only):", "Unscientific forecast:",
    "Strictly for entertainment:",
)
FORTUNE_LUCKY_LABELS = ("Fortune-cookie style:", "Lucky-biscuit wisdom:", "Just for fun:")
FORTUNE_LABELS = tuple(dict.fromkeys(FORTUNE_FORECAST_LABELS + FORTUNE_LUCKY_LABELS))
FORTUNE_TIMEFRAMES = (
    "This week", "Sometime soon", "Later today", "Over the next few days", "Before the month ends",
    "On a quiet afternoon",
)
FORTUNE_EVENTS = (
    "find a forgotten snack in an old coat pocket", "hear a song you love at exactly the right moment",
    "receive a message from someone you have not heard from in a while", "discover a shortcut you never noticed",
    "find the perfect parking spot", "win an argument with a stubborn jar lid",
    "meet someone who laughs at your jokes", "spot a rainbow on the way home", "learn a useful little fact",
    "taste something delicious for the first time",
)
FORTUNE_TWISTS = (
    "it could brighten the whole afternoon", "someone nearby might smile about it too",
    "you may want to tell a friend about it", "it could become a favorite story",
    "the day may feel a little lighter afterward", "you may feel strangely pleased with yourself",
)
FORTUNE_ADVICE = (
    "Be kind to the next person you meet", "Take the scenic route today",
    "Say thank you to someone who does not expect it", "Try one new thing before the weekend ends",
    "Call an old friend", "Tidy one small corner and enjoy the view", "Share a snack with a friend",
    "Learn one new word today", "Smile at a stranger", "Write down one thing that went well",
    "Listen to a song you have not heard in years", "Plant something, even if it is a small seed",
)
FORTUNE_LUCKY_DRAWS = 25


def _lucky_numbers(rng: random.Random) -> str:
    """Three distinct numbers in 1..60, ascending.  ``getrandbits(32) % 60`` has a negligible bias (< 1e-8)."""
    numbers: list[int] = []
    while len(numbers) < 3:
        value = 1 + rng.getrandbits(32) % 60
        if value not in numbers:
            numbers.append(value)
    return ", ".join(str(n) for n in sorted(numbers))


def generate_fortunes(rng: random.Random, cap: int = DEFAULT_CAPS["fortunes"]) -> dict[str, list[str]]:
    """Two families: ``just_for_fun_forecast`` and ``just_for_fun_lucky``.  Entertainment only."""
    check_rng(rng)
    check_cap(cap)
    if cap == 0:
        return {}
    forecast = [
        f"{label} {timeframe}, you might {event}, and {twist}."
        for label in FORTUNE_FORECAST_LABELS
        for timeframe in FORTUNE_TIMEFRAMES
        for event in FORTUNE_EVENTS
        for twist in FORTUNE_TWISTS
    ]
    lucky = [
        f"{label} {advice}. Lucky numbers: {_lucky_numbers(rng)}."
        for advice in FORTUNE_ADVICE
        for label in FORTUNE_LUCKY_LABELS
        for _ in range(FORTUNE_LUCKY_DRAWS)
    ]
    return assemble(rng, cap, {"just_for_fun_forecast": forecast, "just_for_fun_lucky": lucky})


# --------------------------------------------------------------------------- would you rather
WYR_POWERS = (
    "be able to fly", "be able to turn invisible", "read minds", "teleport anywhere", "talk to animals",
    "stop time", "never need sleep", "speak every language", "breathe underwater", "have super strength",
    "control the weather", "run at the speed of sound", "shrink to the size of an ant",
    "grow as tall as a building", "see ten seconds into the future", "rewind time by one minute",
    "have a photographic memory", "become any animal", "walk through walls",
    "summon any food you can imagine", "play any instrument perfectly", "know the answer to any question",
    "speak to plants", "never get lost", "make anyone laugh", "have a personal robot assistant",
    "have a pet dragon", "glow in the dark",
)
WYR_LIFESTYLE = (
    "live in a treehouse", "live on a boat", "live in a lighthouse", "work from a beach every day",
    "have breakfast for every meal", "give up music for a year", "travel the world for a year",
    "learn a new language every year", "have a secret library", "own a bakery", "cook every meal at home",
    "eat dessert first every day", "take a nap every afternoon", "visit the moon once",
    "have a tiny house in the mountains", "live in a big city", "live in a quiet village",
    "wake up at sunrise every day", "stay up late every night", "always be ten minutes early",
    "always be ten minutes late", "have a garden full of flowers", "have a garden full of vegetables",
    "spend a year without internet", "take a long train trip across a continent",
    "have dinner with your favorite fictional character", "go camping every weekend", "have a rooftop terrace",
)


def generate_would_you_rather(rng: random.Random, cap: int = DEFAULT_CAPS["would_you_rather"]) -> dict[str, list[str]]:
    """Three families: ``powers`` and ``lifestyle`` (pairs within a group) and ``mixed`` (one of each).

    The order inside every pair is decided by a seeded coin flip, so the same option is not always first.
    """
    check_rng(rng)
    check_cap(cap)
    if cap == 0:
        return {}

    def question(first: str, second: str) -> str:
        if rng.getrandbits(1):
            first, second = second, first
        return f"Would you rather {first} or {second}?"

    powers = [question(a, b) for a, b in itertools.combinations(WYR_POWERS, 2)]
    lifestyle = [question(a, b) for a, b in itertools.combinations(WYR_LIFESTYLE, 2)]
    mixed = [question(a, b) for a, b in itertools.product(WYR_POWERS, WYR_LIFESTYLE)]
    return assemble(rng, cap, {"powers": powers, "lifestyle": lifestyle, "mixed": mixed})


TEXT_GENERATORS: dict[str, Callable[[random.Random, int], dict[str, list[str]]]] = {
    "jokes": generate_jokes,
    "quotes": generate_quotes,
    "compliments": generate_compliments,
    "fortunes": generate_fortunes,
    "would_you_rather": generate_would_you_rather,
}


# ======================================================================================
# STAGES 4-6: computed content, curated pass-through, validation, and output.
# ======================================================================================

PIPELINE_CAPS = {
    "jokes": 94,
    "quotes": 7,
    "compliments": 5,
    "fortunes": 4,
    "would_you_rather": 10,
}

_MATH_FACTS = (
    "Pi is irrational.",
    "The square root of two is irrational.",
    "The Fibonacci sequence appears in many natural patterns.",
    "Prime numbers are used in modern cryptography.",
    "The real numbers are uncountably infinite.",
)


def _computed_trivia(rng: random.Random) -> Payload:
    geography = [
        {"q": f"What is the capital of {country.name}?", "a": country.capital}
        for country in stable_pick(rng, quiz_countries(), 10)
    ]
    chemistry = [
        {"q": f"What is the chemical symbol for {element.name}?", "a": element.symbol}
        for element in stable_pick(rng, ELEMENTS, 10)
    ]
    math = [
        {"q": question, "a": answer}
        for question, answer in (
            ("Is pi rational or irrational?", "Pi is irrational."),
            ("Is the square root of two rational or irrational?", "The square root of two is irrational."),
            ("What is the Fibonacci sequence known for?", "It appears in many natural patterns."),
            ("What is one use of prime numbers?", "They are used in modern cryptography."),
            ("How large is the set of real numbers?", "It is uncountably infinite."),
        )
    ]
    return {"geography": geography, "chemistry": chemistry, "math": math}


def _computed_facts(rng: random.Random) -> Payload:
    country_facts = [
        f"{country.capital} is the capital of {country.name}."
        for country in stable_pick(rng, quiz_countries(), 8)
    ]
    element_facts = [
        f"{element.name} ({element.symbol}) is element {element.number} on the periodic table."
        for element in stable_pick(rng, ELEMENTS, 8)
    ]
    return {"general": country_facts + element_facts + list(_MATH_FACTS)}


_COMMON_FIVE_LETTER_WORDS = (
    "about", "above", "after", "again", "apple", "beach", "brain", "brave", "bread", "chair",
    "cloud", "dance", "dream", "earth", "faith", "field", "flame", "focus", "fruit", "grace",
    "green", "happy", "heart", "house", "light", "magic", "music", "ocean", "peace", "plant",
    "power", "quiet", "river", "smile", "sound", "space", "speed", "sport", "stone", "story",
    "sweet", "table", "think", "tiger", "today", "train", "trust", "water", "world", "write",
)


def _computed_words(rng: random.Random) -> Payload:
    candidates = set(_COMMON_FIVE_LETTER_WORDS)
    for text in (
        *(country.name for country in COUNTRIES),
        *(country.capital for country in COUNTRIES),
        *(element.name for element in ELEMENTS),
    ):
        normalized = fold(text).lower()
        for index in range(len(normalized) - 4):
            word = normalized[index : index + 5]
            if word.isalpha():
                candidates.add(word)
    words = stable_pick(rng, sorted(candidates), 151)
    if len(words) < 151:
        raise ValueError(f"five-letter word pool only has {len(words)} entries; 151 are required")
    return {"five_letter": words}


def _curated_packs(data_dir: Path) -> dict[str, Payload]:
    """Load existing curated packs without including prior generated output."""
    curated: dict[str, Payload] = {}
    for path in sorted(data_dir.glob("*.json")):
        if path.name.endswith(".generated.json"):
            continue
        stem = path.name[:-5]
        if not _STEM_RE.fullmatch(stem):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not read curated content pack {path}: {exc}") from exc
        if isinstance(payload, list):
            payload = {"general": payload}
        errors = validate_payload(stem, payload)
        if errors:
            raise ValueError(f"Invalid curated content pack {path}: {'; '.join(errors[:5])}")
        curated[stem] = payload
    return curated


def register_content_pipeline(data_dir: Path = DEFAULT_OUT) -> None:
    """Register the built-in Stage 3-6 builders for the CLI's ``--all`` option."""
    registered = {name for name, _ in BUILDERS}
    names = {f"text:{kind}" for kind in TEXT_GENERATORS} | {
        "computed:trivia", "computed:facts", "computed:words", "curated:packs",
    }
    if names <= registered:
        return
    if names & registered:
        raise ValueError("the built-in content pipeline is only partially registered")

    for kind, generator in TEXT_GENERATORS.items():
        def build_text(rng: random.Random, kind=kind, generator=generator) -> dict[str, Payload]:
            return {f"{kind}.generated": generator(rng, PIPELINE_CAPS[kind])}

        builder(f"text:{kind}")(build_text)

    @builder("computed:trivia")
    def build_trivia(rng: random.Random) -> dict[str, Payload]:
        return {"trivia.generated": _computed_trivia(rng)}

    @builder("computed:facts")
    def build_facts(rng: random.Random) -> dict[str, Payload]:
        return {"facts.generated": _computed_facts(rng)}

    @builder("computed:words")
    def build_words(rng: random.Random) -> dict[str, Payload]:
        return {"words.generated": _computed_words(rng)}

    @builder("curated:packs")
    def build_curated(_rng: random.Random) -> dict[str, Payload]:
        return _curated_packs(data_dir)


# ======================================================================================
# CLI
# ======================================================================================
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate bot content packs.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output directory (default: bot/data)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="random seed (default: %(default)s)")
    parser.add_argument("--dry-run", action="store_true", help="build and validate, but write nothing")
    parser.add_argument("--all", action="store_true", help="run the built-in Stages 3-6 content pipeline")
    args = parser.parse_args(argv)

    if args.all:
        try:
            register_content_pipeline(args.out)
        except ValueError as exc:
            print(f"Content pipeline setup failed: {exc}", file=sys.stderr)
            return 1
    try:
        packs = build_all(args.seed)
    except (OSError, ValueError) as exc:
        print(f"Content generation failed: {exc}", file=sys.stderr)
        return 1
    errors = validate_all(packs)
    print(summarize(packs))
    if errors:
        print(f"\n{len(errors)} validation error(s); nothing was written:", file=sys.stderr)
        for message in errors[:50]:
            print(f"  - {message}", file=sys.stderr)
        if len(errors) > 50:
            print(f"  ... and {len(errors) - 50} more", file=sys.stderr)
        return 1
    if args.dry_run:
        print("\nDry run: validation passed, nothing written.")
        return 0

    for stem in sorted(packs):
        if args.all and not stem.endswith(".generated"):
            continue
        atomic_write_json(args.out / f"{stem}.json", packs[stem])
    print(f"\nWrote {len(packs)} file(s) to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
