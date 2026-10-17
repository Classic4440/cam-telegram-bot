from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", Path(__file__).resolve().parents[1]))
GEN_PATH = Path(os.environ.get("GENERATE_CONTENT_PATH", PROJECT_ROOT / "scripts" / "generate_content.py"))

if not GEN_PATH.exists():
    pytest.skip(f"generator not found at {GEN_PATH}", allow_module_level=True)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, GEN_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gc = _load("generate_content_data_under_test")
BY_ISO = {c.iso2: c for c in gc.COUNTRIES}
MEMBERS = [c for c in gc.COUNTRIES if c.status == gc.STATUS_UN_MEMBER]

EXPECTED_UNSAFE = {"BI", "BJ", "BO", "CI", "GQ", "ID", "IL", "KI", "LK", "NR", "PS", "SZ", "TW", "XK", "YE", "ZA"}


# =========================================================================== countries: completeness
def test_internal_consistency_check_reports_no_problems():
    assert gc.validate_reference_data() == []


def test_193_un_members_plus_two_observers_and_two_limited_recognition():
    counts = {}
    for c in gc.COUNTRIES:
        counts[c.status] = counts.get(c.status, 0) + 1
    assert counts == {gc.STATUS_UN_MEMBER: 193, gc.STATUS_UN_OBSERVER: 2, gc.STATUS_LIMITED: 2}
    assert len(gc.COUNTRIES) == 197


def test_un_members_per_region_follow_un_m49():
    by_region = {r: len(v) for r, v in gc.countries_by_region(members_only=True).items()}
    assert by_region == {"africa": 54, "americas": 35, "asia": 47, "europe": 43, "oceania": 14}


def test_regions_constant_matches_data():
    assert gc.REGIONS == ("africa", "americas", "asia", "europe", "oceania")
    assert {c.region for c in gc.COUNTRIES} == set(gc.REGIONS)


@pytest.mark.parametrize("iso2,region", [
    ("TR", "asia"), ("CY", "asia"), ("GE", "asia"), ("AM", "asia"), ("AZ", "asia"), ("KZ", "asia"),
    ("RU", "europe"), ("IS", "europe"), ("EG", "africa"), ("MX", "americas"), ("HT", "americas"),
    ("AU", "oceania"), ("PG", "oceania"), ("VA", "europe"), ("PS", "asia"), ("TW", "asia"), ("XK", "europe"),
])
def test_region_assignments_for_edge_cases(iso2, region):
    assert BY_ISO[iso2].region == region


def test_each_region_is_alphabetical_by_name_for_members():
    for region, rows in gc.countries_by_region(members_only=True).items():
        names = [gc.fold(c.name).lower() for c in rows]
        assert names == sorted(names), region


# =========================================================================== countries: uniqueness and fields
def test_names_iso_codes_and_capitals_are_unique():
    for attr in ("name", "iso2", "capital"):
        values = [gc.fold(getattr(c, attr)).lower() for c in gc.COUNTRIES]
        assert len(values) == len(set(values)), f"duplicate {attr}"


def test_required_fields_have_correct_types_and_are_non_blank():
    for c in gc.COUNTRIES:
        assert isinstance(c.name, str) and c.name == c.name.strip() and c.name
        assert isinstance(c.capital, str) and c.capital == c.capital.strip() and c.capital
        assert re.fullmatch(r"[A-Z]{2}", c.iso2), c
        assert c.region in gc.REGIONS
        assert c.status in {gc.STATUS_UN_MEMBER, gc.STATUS_UN_OBSERVER, gc.STATUS_LIMITED}
        assert isinstance(c.quiz_safe, bool)
        assert isinstance(c.note, str)


def test_names_and_capitals_contain_no_control_characters_or_html():
    for c in gc.COUNTRIES:
        for text in (c.name, c.capital, c.note):
            assert not re.search(r"[\x00-\x1f\x7f<>]", text), (c.iso2, text)


def test_kosovo_is_the_only_code_outside_iso_3166_1():
    # ISO 3166-1 alpha-2 uses AA..ZZ; XK is the widely used user-assigned code for Kosovo.
    assert [c.iso2 for c in gc.COUNTRIES if c.iso2.startswith("X")] == ["XK"]


# =========================================================================== countries: disputed and special cases
def test_unsafe_set_is_exactly_the_explicit_list():
    assert {c.iso2 for c in gc.COUNTRIES if not c.quiz_safe} == EXPECTED_UNSAFE


def test_every_unsafe_entry_has_a_note():
    for c in gc.COUNTRIES:
        if not c.quiz_safe:
            assert len(c.note) > 20, c.iso2


def test_limited_recognition_entities_are_never_quiz_safe_and_not_quiz_countries():
    for c in gc.COUNTRIES:
        if c.status == gc.STATUS_LIMITED:
            assert not c.quiz_safe
    assert not {"TW", "XK", "PS", "VA"} & {c.iso2 for c in gc.quiz_countries()}


def test_quiz_countries_are_un_members_with_safe_flag_only():
    quiz = gc.quiz_countries()
    assert all(c.status == gc.STATUS_UN_MEMBER and c.quiz_safe for c in quiz)
    assert len(quiz) == 193 - len(EXPECTED_UNSAFE & {c.iso2 for c in MEMBERS})
    assert len(quiz) == 180


@pytest.mark.parametrize("iso2,fragment", [
    ("ZA", "Cape Town"), ("BO", "La Paz"), ("IL", "disputed"), ("CI", "Abidjan"), ("BJ", "Cotonou"),
    ("LK", "Colombo"), ("YE", "Aden"), ("NR", "no official capital"), ("ID", "Nusantara"), ("GQ", "Malabo"),
    ("SZ", "Lobamba"), ("BI", "Bujumbura"), ("PS", "Ramallah"), ("NL", "The Hague"), ("CH", "no de jure capital"),
    ("TZ", "Dar es Salaam"), ("MY", "Putrajaya"), ("CL", "Valparaíso"), ("CY", "divided"),
])
def test_special_case_notes_name_the_competing_city(iso2, fragment):
    assert fragment in BY_ISO[iso2].note


def test_time_sensitive_entries_say_how_they_were_checked():
    assert "2026" in BY_ISO["GQ"].note and "Verify" in BY_ISO["GQ"].note
    assert "2026" in BY_ISO["ID"].note


def test_every_special_case_code_exists_in_the_dataset():
    assert set(gc._SPECIAL_CASES) <= set(BY_ISO)


def test_notes_only_exist_for_special_cases():
    assert {c.iso2 for c in gc.COUNTRIES if c.note} == set(gc._SPECIAL_CASES)


# =========================================================================== countries: representative pairs
REPRESENTATIVE = {
    "GB": "London", "FR": "Paris", "DE": "Berlin", "ES": "Madrid", "PT": "Lisbon", "IT": "Rome", "GR": "Athens",
    "PL": "Warsaw", "UA": "Kyiv", "RU": "Moscow", "IS": "Reykjavík", "MD": "Chișinău", "NL": "Amsterdam",
    "CH": "Bern", "UG": "Kampala", "KE": "Nairobi", "TZ": "Dodoma", "NG": "Abuja", "EG": "Cairo",
    "ET": "Addis Ababa", "GH": "Accra", "MA": "Rabat", "ZW": "Harare", "RW": "Kigali", "CM": "Yaoundé",
    "CD": "Kinshasa", "CG": "Brazzaville", "ST": "São Tomé", "BR": "Brasília", "AR": "Buenos Aires",
    "CA": "Ottawa", "MX": "Mexico City", "US": "Washington, D.C.", "CO": "Bogotá", "PY": "Asunción",
    "JP": "Tokyo", "CN": "Beijing", "IN": "New Delhi", "KR": "Seoul", "KP": "Pyongyang", "TH": "Bangkok",
    "VN": "Hanoi", "KZ": "Astana", "TR": "Ankara", "SA": "Riyadh", "AE": "Abu Dhabi", "IR": "Tehran",
    "MM": "Naypyidaw", "MV": "Malé", "AU": "Canberra", "NZ": "Wellington", "FJ": "Suva", "PW": "Ngerulmud",
    "TO": "Nukuʻalofa", "VA": "Vatican City", "TW": "Taipei", "XK": "Pristina", "PS": "East Jerusalem",
}


@pytest.mark.parametrize("iso2,capital", sorted(REPRESENTATIVE.items()))
def test_representative_country_capital_pairs(iso2, capital):
    assert BY_ISO[iso2].capital == capital


def test_historical_names_are_not_used():
    names = {c.name for c in gc.COUNTRIES} | {c.capital for c in gc.COUNTRIES}
    assert not names & {"Nur-Sultan", "Burma", "Swaziland", "Czech Republic", "Macedonia", "Ivory Coast", "Kiev", "Peking"}


def test_fold_removes_diacritics_and_normalizes_apostrophes():
    assert gc.fold("Bogotá") == "Bogota"
    assert gc.fold("São Tomé") == "Sao Tome"
    assert gc.fold("Chișinău") == "Chisinau"
    assert gc.fold("Reykjavík") == "Reykjavik"
    assert gc.fold("Nukuʻalofa") == "Nuku'alofa"
    assert gc.fold("N'Djamena") == "N'Djamena"
    assert gc.fold("Plain ASCII") == "Plain ASCII"


# =========================================================================== elements
BY_NUMBER = {e.number: e for e in gc.ELEMENTS}
BY_SYMBOL = {e.symbol: e for e in gc.ELEMENTS}


def test_exactly_118_elements_numbered_1_to_118_in_order():
    assert len(gc.ELEMENTS) == 118
    assert [e.number for e in gc.ELEMENTS] == list(range(1, 119))


def test_symbols_and_names_are_unique():
    assert len({e.symbol for e in gc.ELEMENTS}) == 118
    assert len({e.name for e in gc.ELEMENTS}) == 118
    assert len({e.name.lower() for e in gc.ELEMENTS}) == 118


def test_symbol_and_name_formats():
    for e in gc.ELEMENTS:
        assert re.fullmatch(r"[A-Z][a-z]?", e.symbol), e
        assert re.fullmatch(r"[A-Z][a-z]+", e.name), e
        assert isinstance(e.number, int)


def test_every_symbol_letter_is_in_the_name_in_order():
    # Every symbol is built from letters of the English name, except these Latin/German-derived ones.
    latin = {"Na", "K", "Fe", "Cu", "Ag", "Sn", "Sb", "W", "Au", "Hg", "Pb"}
    for e in gc.ELEMENTS:
        if e.symbol in latin:
            continue
        letters = iter(e.name.lower())
        assert all(ch in letters for ch in e.symbol.lower()), e


def test_latin_or_german_derived_symbols_are_correct():
    assert {s: BY_SYMBOL[s].name for s in ("Na", "K", "Fe", "Cu", "Ag", "Sn", "Sb", "W", "Au", "Hg", "Pb")} == {
        "Na": "Sodium", "K": "Potassium", "Fe": "Iron", "Cu": "Copper", "Ag": "Silver", "Sn": "Tin",
        "Sb": "Antimony", "W": "Tungsten", "Au": "Gold", "Hg": "Mercury", "Pb": "Lead",
    }


KNOWN = {
    1: ("H", "Hydrogen"), 2: ("He", "Helium"), 6: ("C", "Carbon"), 7: ("N", "Nitrogen"), 8: ("O", "Oxygen"),
    11: ("Na", "Sodium"), 13: ("Al", "Aluminium"), 14: ("Si", "Silicon"), 16: ("S", "Sulfur"), 19: ("K", "Potassium"),
    26: ("Fe", "Iron"), 29: ("Cu", "Copper"), 47: ("Ag", "Silver"), 50: ("Sn", "Tin"), 55: ("Cs", "Caesium"),
    74: ("W", "Tungsten"), 79: ("Au", "Gold"), 80: ("Hg", "Mercury"), 82: ("Pb", "Lead"), 92: ("U", "Uranium"),
    94: ("Pu", "Plutonium"), 99: ("Es", "Einsteinium"), 100: ("Fm", "Fermium"), 101: ("Md", "Mendelevium"),
    102: ("No", "Nobelium"), 109: ("Mt", "Meitnerium"), 112: ("Cn", "Copernicium"), 113: ("Nh", "Nihonium"),
    114: ("Fl", "Flerovium"), 115: ("Mc", "Moscovium"), 116: ("Lv", "Livermorium"), 117: ("Ts", "Tennessine"),
    118: ("Og", "Oganesson"),
}


@pytest.mark.parametrize("number,expected", sorted(KNOWN.items()))
def test_known_elements(number, expected):
    e = BY_NUMBER[number]
    assert (e.symbol, e.name) == expected


# SHA-256 of "number:symbol:name" lines (joined by newlines) for all 118 elements.  The table was
# cross-checked against the `periodictable` package (0 mismatches, only the Aluminium/Caesium spelling variants).
# If you deliberately change an element (for example a new IUPAC name), recompute this value.
ELEMENTS_SHA256 = "5219fdeaa34949ae9c5bcdab25f810b8eb87bf5f8a16ae48a0a75b61be4eea06"


def test_full_element_table_matches_the_verified_pin():
    canonical = "\n".join(f"{e.number}:{e.symbol}:{e.name}" for e in gc.ELEMENTS)
    assert hashlib.sha256(canonical.encode("utf-8")).hexdigest() == ELEMENTS_SHA256


def test_single_letter_symbols_are_exactly_the_fourteen_official_ones():
    assert {e.symbol for e in gc.ELEMENTS if len(e.symbol) == 1} == set("HBCNOFPSKVYIWU")


def test_group_structure_sanity():
    noble = [BY_NUMBER[n].symbol for n in (2, 10, 18, 36, 54, 86, 118)]
    assert noble == ["He", "Ne", "Ar", "Kr", "Xe", "Rn", "Og"]
    halogens = [BY_NUMBER[n].symbol for n in (9, 17, 35, 53, 85, 117)]
    assert halogens == ["F", "Cl", "Br", "I", "At", "Ts"]
    alkali = [BY_NUMBER[n].symbol for n in (3, 11, 19, 37, 55, 87)]
    assert alkali == ["Li", "Na", "K", "Rb", "Cs", "Fr"]
    lanthanides = [BY_NUMBER[n].symbol for n in range(57, 72)]
    assert lanthanides == ["La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu"]
    actinides = [BY_NUMBER[n].symbol for n in range(89, 104)]
    assert actinides == ["Ac", "Th", "Pa", "U", "Np", "Pu", "Am", "Cm", "Bk", "Cf", "Es", "Fm", "Md", "No", "Lr"]


def test_names_use_iupac_spellings_with_documented_alternatives():
    assert BY_NUMBER[13].name == "Aluminium" and gc.ELEMENT_ALT_NAMES["Aluminium"] == "Aluminum"
    assert BY_NUMBER[55].name == "Caesium" and gc.ELEMENT_ALT_NAMES["Caesium"] == "Cesium"
    assert BY_NUMBER[16].name == "Sulfur" and gc.ELEMENT_ALT_NAMES["Sulfur"] == "Sulphur"
    names = {e.name for e in gc.ELEMENTS}
    for iupac, alt in gc.ELEMENT_ALT_NAMES.items():
        assert iupac in names and alt not in names and iupac != alt


def test_element_namedtuple_is_immutable_and_hashable():
    e = gc.ELEMENTS[0]
    with pytest.raises(AttributeError):
        e.symbol = "X"
    assert hash(e) == hash(gc.Element(1, "H", "Hydrogen"))


# =========================================================================== integration with Stage 1
STAGE1_NAMES = [
    "fingerprint", "unique", "payload_fingerprints", "dedupe_against", "atomic_write_json", "validate_payload",
    "builder", "rng_for", "build_all", "finalize", "validate_all", "summarize", "main",
    "BUILDERS", "Payload", "Builder", "DEFAULT_OUT", "DEFAULT_SEED", "MAX_ENTRY_CHARS",
]


def test_stage1_interfaces_are_preserved():
    for name in STAGE1_NAMES:
        assert hasattr(gc, name), name


def test_stage2_registers_no_builders_and_produces_no_packs():
    fresh = _load("generate_content_fresh_registry")
    assert fresh.BUILDERS == []
    assert fresh.build_all(1) == {}


def test_cli_writes_nothing_with_stage2_only(tmp_path, capsys):
    fresh = _load("generate_content_fresh_cli")
    assert fresh.main(["--out", str(tmp_path)]) == 0
    assert list(tmp_path.iterdir()) == []
    assert "no builders" in capsys.readouterr().out.lower()


def test_importing_the_module_has_no_side_effects(tmp_path):
    code = (
        "import importlib.util, sys;"
        f"s=importlib.util.spec_from_file_location('g', r'{GEN_PATH}');"
        "m=importlib.util.module_from_spec(s); sys.modules['g']=m; s.loader.exec_module(m);"
        "print(len(m.BUILDERS))"
    )
    result = subprocess.run([sys.executable, "-I", "-c", code], cwd=tmp_path, capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "0" and result.stderr == ""
    assert list(tmp_path.iterdir()) == []


def test_reference_data_is_deterministic_across_processes():
    code = (
        "import importlib.util, sys, hashlib;"
        f"s=importlib.util.spec_from_file_location('g', r'{GEN_PATH}');"
        "m=importlib.util.module_from_spec(s); sys.modules['g']=m; s.loader.exec_module(m);"
        "print(hashlib.sha256(repr((m.COUNTRIES, m.ELEMENTS, sorted(m._SPECIAL_CASES.items()))).encode()).hexdigest())"
    )
    digests = set()
    for seed in ("0", "1", "random"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True, env=env)
        digests.add(out.stdout.strip())
    assert len(digests) == 1
    local = hashlib.sha256(repr((gc.COUNTRIES, gc.ELEMENTS, sorted(gc._SPECIAL_CASES.items()))).encode()).hexdigest()
    assert digests == {local}


def test_reference_tables_are_immutable_tuples():
    assert isinstance(gc.COUNTRIES, tuple) and isinstance(gc.ELEMENTS, tuple) and isinstance(gc.REGIONS, tuple)
    with pytest.raises(AttributeError):
        gc.COUNTRIES[0].capital = "Nowhere"


def test_stage2_data_flows_through_stage1_unique_and_validation():
    facts = [f"The capital of {c.name} is {c.capital}." for c in gc.quiz_countries()]
    facts += [f"{e.name} has the chemical symbol {e.symbol}." for e in gc.ELEMENTS]
    payload = {"capitals": facts[:180], "elements": facts[180:]}
    assert gc.validate_payload("facts.generated", payload) == []
    assert len(gc.unique(facts)) == len(facts) == 180 + 118


def test_curated_files_are_untouched_by_loading_the_module():
    scripts = GEN_PATH.parent
    curated = sorted(scripts.glob("curated_*.py"))
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in curated}
    _load("generate_content_hash_check")
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in curated}
    assert before == after
