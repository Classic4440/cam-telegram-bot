from __future__ import annotations

import importlib.util
import json
import os
import random
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", Path(__file__).resolve().parents[1]))
GEN_PATH = Path(os.environ.get("GENERATE_CONTENT_PATH", PROJECT_ROOT / "scripts" / "generate_content.py"))

if not GEN_PATH.exists():
    pytest.skip(f"generator not found at {GEN_PATH}", allow_module_level=True)

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_spec = importlib.util.spec_from_file_location("generate_content_under_test", GEN_PATH)
gc = importlib.util.module_from_spec(_spec)
sys.modules["generate_content_under_test"] = gc
_spec.loader.exec_module(gc)


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch):
    """Every test starts with an empty builder registry so real builders never leak in."""
    monkeypatch.setattr(gc, "BUILDERS", [])


def register(name, stem, payload_fn):
    gc.builder(name)(lambda rng: {stem: payload_fn(rng)})


# --------------------------------------------------------------------------- fingerprints
SAMPLES = [
    "Hello, World!", "  spaced   out  ", "Why did the chicken cross the road?", "Ünïcode çafé ☕",
    "", "!!!", {"q": "What is 2+2?", "a": "4"}, {"question": "Q?"}, {"text": "T"}, {"other": "x"},
]


@pytest.mark.parametrize("entry", SAMPLES)
def test_fingerprint_matches_runtime_loader(entry):
    from bot.content import _fingerprint

    assert gc.fingerprint(entry) == _fingerprint(entry)


def test_unique_keeps_first_and_drops_blank_and_duplicates():
    seen: set[str] = set()
    out = gc.unique(["A joke!", "a  joke", " ", "", "Another", "ANOTHER?"], seen)
    assert out == ["A joke!", "Another"]
    assert "a joke" in seen and "another" in seen


def test_unique_strips_surrounding_whitespace():
    assert gc.unique(["  padded  "]) == ["padded"]


def test_dedupe_against_removes_reserved_and_internal_duplicates_and_empty_categories():
    payload = {"b": ["Keep me", "keep ME!"], "a": ["Reserved one"], "c": ["only dup"]}
    out = gc.dedupe_against(payload, {"reserved one", "only dup"})
    assert out == {"b": ["Keep me"]}


# --------------------------------------------------------------------------- atomic write
def test_atomic_write_creates_file_with_utf8_and_trailing_newline(tmp_path):
    target = tmp_path / "sub" / "pack.json"
    gc.atomic_write_json(target, {"b": ["é☕"], "a": ["x"]})
    raw = target.read_text(encoding="utf-8")
    assert raw.endswith("\n")
    assert "é☕" in raw  # ensure_ascii=False
    assert json.loads(raw) == {"a": ["x"], "b": ["é☕"]}
    assert list(json.loads(raw)) == ["a", "b"]  # sorted keys -> stable diffs


def test_atomic_write_leaves_no_temp_files(tmp_path):
    gc.atomic_write_json(tmp_path / "p.json", {"a": ["x"]})
    assert sorted(p.name for p in tmp_path.iterdir()) == ["p.json"]


def test_failed_write_keeps_old_file_and_cleans_up(tmp_path):
    target = tmp_path / "p.json"
    gc.atomic_write_json(target, {"a": ["old"]})
    with pytest.raises(TypeError):
        gc.atomic_write_json(target, {"a": [object()]})
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": ["old"]}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["p.json"]


def test_failure_during_replace_removes_temp_file(tmp_path, monkeypatch):
    target = tmp_path / "p.json"

    def boom(src, dst):
        raise OSError("disk on fire")

    monkeypatch.setattr(gc.os, "replace", boom)
    with pytest.raises(OSError):
        gc.atomic_write_json(target, {"a": ["x"]})
    assert list(tmp_path.iterdir()) == []


def test_temp_file_name_never_matches_loader_glob(tmp_path, monkeypatch):
    seen_names = []
    real_replace = os.replace

    def spy(src, dst):
        seen_names.append(Path(src).name)
        real_replace(src, dst)

    monkeypatch.setattr(gc.os, "replace", spy)
    gc.atomic_write_json(tmp_path / "jokes.json", {"a": ["x"]})
    assert seen_names and not any(Path(n).match("*.json") for n in seen_names)


# --------------------------------------------------------------------------- validation
def test_valid_payload_has_no_errors():
    assert gc.validate_payload("jokes.generated", {"dad": ["One", "Two"], "riddle_x": [{"q": "Q?", "a": "A"}]}) == []


@pytest.mark.parametrize(
    "stem,payload,needle",
    [
        ("Bad-Stem", {"a": ["x"]}, "file stem"),
        ("jokes.gen.extra", {"a": ["x"]}, "file stem"),
        ("jokes", {}, "non-empty object"),
        ("jokes", [], "non-empty object"),
        ("jokes", {"Dad": ["x"]}, "category must match"),
        ("jokes", {"dad joke": ["x"]}, "category must match"),
        ("jokes", {"dad": []}, "non-empty list"),
        ("jokes", {"dad": "not a list"}, "non-empty list"),
        ("jokes", {"dad": ["   "]}, "blank entry"),
        ("jokes", {"dad": [" padded"]}, "whitespace"),
        ("jokes", {"dad": ["x" * 1001]}, "longer than"),
        ("jokes", {"dad": ["bad\x00char"]}, "control characters"),
        ("jokes", {"dad": [42]}, "strings or objects"),
        ("jokes", {"dad": [{"nothing": ""}]}, "q/question/text"),
        ("jokes", {"dad": ["Same!", "same"]}, "duplicate"),
        ("jokes", {"a": ["Same"], "b": ["same."]}, "duplicate"),
    ],
)
def test_validation_catches_problem(stem, payload, needle):
    errors = gc.validate_payload(stem, payload)
    assert any(needle in e for e in errors), errors


# --------------------------------------------------------------------------- builders
def test_build_all_is_deterministic():
    register("jokes", "jokes.generated", lambda rng: {"dad": [str(rng.random()) for _ in range(5)]})
    assert gc.build_all(7) == gc.build_all(7)
    assert gc.build_all(7) != gc.build_all(8)


def test_adding_a_builder_does_not_change_existing_output():
    register("a", "alpha.generated", lambda rng: {"x": [str(rng.random()) for _ in range(5)]})
    before = gc.build_all(3)["alpha.generated"]
    register("b", "beta.generated", lambda rng: {"x": [str(rng.random()) for _ in range(5)]})
    assert gc.build_all(3)["alpha.generated"] == before


def test_rng_streams_differ_per_builder_name():
    assert gc.rng_for(1, "a").random() != gc.rng_for(1, "b").random()
    assert gc.rng_for(1, "a").random() == gc.rng_for(1, "a").random()


def test_duplicate_builder_name_rejected():
    register("same", "one", lambda rng: {"x": ["1"]})
    with pytest.raises(ValueError):
        gc.builder("same")(lambda rng: {})


def test_two_builders_producing_same_stem_is_an_error():
    register("a", "same", lambda rng: {"x": ["1"]})
    register("b", "same", lambda rng: {"x": ["2"]})
    with pytest.raises(ValueError, match="already produced"):
        gc.build_all(1)


def test_finalize_makes_curated_authoritative():
    packs = {
        "jokes": {"dad": ["Shared joke!", "Curated only"]},
        "jokes.generated": {"dad": ["shared  joke", "Generated only"], "gone": ["SHARED JOKE"]},
    }
    out = gc.finalize(packs)
    assert out["jokes"] == packs["jokes"]
    assert out["jokes.generated"] == {"dad": ["Generated only"]}


def test_finalize_drops_packs_that_become_empty_and_leaves_unpaired_generated_alone():
    packs = {"a": {"x": ["One"]}, "a.generated": {"x": ["one"]}, "b.generated": {"x": ["Solo"]}}
    out = gc.finalize(packs)
    assert "a.generated" not in out
    assert out["b.generated"] == {"x": ["Solo"]}


def test_validate_all_collects_errors_across_files():
    errors = gc.validate_all({"ok": {"a": ["fine"]}, "bad": {"a": [" "]}})
    assert len(errors) == 1 and errors[0].startswith("bad[")


# --------------------------------------------------------------------------- CLI
def test_cli_dry_run_writes_nothing(tmp_path, capsys):
    register("jokes", "jokes.generated", lambda rng: {"dad": ["One", "Two"]})
    assert gc.main(["--out", str(tmp_path), "--dry-run"]) == 0
    assert list(tmp_path.iterdir()) == []
    assert "Dry run" in capsys.readouterr().out


def test_cli_writes_files_and_is_reproducible(tmp_path):
    register("jokes", "jokes.generated", lambda rng: {"dad": [f"joke {rng.randint(0, 10**9)}" for _ in range(20)]})
    out1, out2 = tmp_path / "one", tmp_path / "two"
    assert gc.main(["--out", str(out1), "--seed", "5"]) == 0
    assert gc.main(["--out", str(out2), "--seed", "5"]) == 0
    assert (out1 / "jokes.generated.json").read_bytes() == (out2 / "jokes.generated.json").read_bytes()


def test_cli_returns_1_and_writes_nothing_on_validation_error(tmp_path, capsys):
    register("jokes", "jokes.generated", lambda rng: {"dad": ["ok", "OK"]})
    assert gc.main(["--out", str(tmp_path)]) == 1
    assert list(tmp_path.iterdir()) == []
    assert "duplicate" in capsys.readouterr().err


def test_cli_with_no_builders_is_a_clean_noop(tmp_path, capsys):
    assert gc.main(["--out", str(tmp_path)]) == 0
    assert "no builders" in capsys.readouterr().out.lower()
    assert list(tmp_path.iterdir()) == []


def test_cli_does_not_touch_unrelated_files(tmp_path):
    keep = tmp_path / "notes.txt"
    keep.write_text("mine", encoding="utf-8")
    register("jokes", "jokes.generated", lambda rng: {"dad": ["One"]})
    assert gc.main(["--out", str(tmp_path)]) == 0
    assert keep.read_text(encoding="utf-8") == "mine"


# --------------------------------------------------------------------------- loader round-trip
def test_generated_files_merge_with_curated_exactly_as_assumed(tmp_path):
    from bot.content import ContentLibrary

    register("jokes", "jokes", lambda rng: {"dad": ["Shared joke!", "Curated only"]})
    register("jokes_gen", "jokes.generated", lambda rng: {"dad": ["shared joke", "Generated only"], "newcat": ["N"]})
    assert gc.main(["--out", str(tmp_path)]) == 0

    lib = ContentLibrary(tmp_path, seed=1)
    pool = lib.pool("jokes", "dad")
    assert "Shared joke!" in pool and "shared joke" not in pool  # curated copy survived
    assert sorted(pool) == ["Curated only", "Generated only", "Shared joke!"]
    assert lib.category_counts("jokes") == {"dad": 3, "newcat": 1}
    assert list(tmp_path.glob(".*")) == []  # no temp files left behind
