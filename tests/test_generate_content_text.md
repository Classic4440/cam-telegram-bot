# Tests for the Stage 3 text generators in `scripts/generate_content.py`

Save the code block below as `tests/test_generate_content_text.py`. It loads the generator from
`scripts/generate_content.py` (or from `GENERATE_CONTENT_PATH`) and skips itself if neither exists.
Run with `pytest tests/test_generate_content_text.py`.

**Stage 3 tests:** shape and Stage 1 validation, determinism (in-process, across processes with different
`PYTHONHASHSEED`, independent of global `random`), caps (zero, tiny, exact, huge, invalid), capacity equals the
pool products, case-insensitive de-duplication, fair allocation across families, exact template membership
(every entry is rebuilt independently from the pool constants), pool coverage, labeling rules (quotes are
unattributed, fortunes are labeled and hedged), unit tests for the helpers, and Stage 1/2 integration.

```python
from __future__ import annotations

import hashlib
import importlib.util
import itertools
import json
import os
import random
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", Path(__file__).resolve().parents[1]))
GEN_PATH = Path(os.environ.get("GENERATE_CONTENT_PATH", PROJECT_ROOT / "scripts" / "generate_content.py"))

if not GEN_PATH.exists():
    pytest.skip(f"generator not found at {GEN_PATH}", allow_module_level=True)

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_spec = importlib.util.spec_from_file_location("generate_content_text_under_test", GEN_PATH)
gc = importlib.util.module_from_spec(_spec)
sys.modules["generate_content_text_under_test"] = gc
_spec.loader.exec_module(gc)

KINDS = ["jokes", "quotes", "compliments", "fortunes", "would_you_rather"]
HUGE = 10**6
# Determinism pins.  If you intentionally edit a pool or template, update PINNED_DIGEST (the stable_pick pin
# only changes if the selection algorithm changes).
PINNED_PICK = [7, 5, 4, 0, 1]
PINNED_DIGEST = "5d232beddd4ea6995fdd25f6a8c1fdf2fbafb28e67c068b8c135a22c23598216"
EXPECTED_CATEGORIES = {
    "jokes": {"advice", "not_saying", "bar_walk_in"},
    "quotes": {"original_reframe", "original_start_now", "original_daily_deposit", "original_rewards"},
    "compliments": {"as_as", "you_make", "like_yours"},
    "fortunes": {"just_for_fun_forecast", "just_for_fun_lucky"},
    "would_you_rather": {"powers", "lifestyle", "mixed"},
}


def run(kind, seed=1, cap=None):
    rng = random.Random(seed)
    fn = gc.TEXT_GENERATORS[kind]
    return fn(rng, gc.DEFAULT_CAPS[kind] if cap is None else cap)


def flat(payload):
    return [entry for category in sorted(payload) for entry in payload[category]]


@pytest.fixture(scope="module")
def full():
    """Every generator at a cap far above capacity, i.e. the complete unique pool."""
    return {kind: run(kind, seed=1, cap=HUGE) for kind in KINDS}


# --------------------------------------------------------------------------- registry and shape
def test_text_generators_registry_matches_default_caps_and_kinds():
    assert sorted(gc.TEXT_GENERATORS) == sorted(KINDS) == sorted(gc.DEFAULT_CAPS)
    assert all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in gc.DEFAULT_CAPS.values())


@pytest.mark.parametrize("kind", KINDS)
def test_shape_is_category_to_nonempty_list_of_strings(kind):
    out = run(kind)
    assert isinstance(out, dict) and out
    assert set(out) == EXPECTED_CATEGORIES[kind]
    for category, entries in out.items():
        assert isinstance(entries, list) and entries
        assert all(isinstance(e, str) and e for e in entries)


@pytest.mark.parametrize("kind", KINDS)
def test_output_passes_stage1_validation(kind):
    assert gc.validate_payload(f"{kind}.generated", run(kind)) == []
    assert gc.validate_payload(f"{kind}.generated", run(kind, cap=HUGE)) == []


@pytest.mark.parametrize("kind", KINDS)
def test_every_entry_is_lint_clean(kind, full):
    bad = [(e, gc.lint_text(e)) for e in flat(full[kind]) if gc.lint_text(e)]
    assert bad == []


@pytest.mark.parametrize("kind", KINDS)
def test_defaults_apply_when_cap_is_omitted(kind):
    capacity = sum(len(v) for v in run(kind, cap=HUGE).values())
    out = gc.TEXT_GENERATORS[kind](random.Random(1))
    assert sum(len(v) for v in out.values()) == min(gc.DEFAULT_CAPS[kind], capacity)


@pytest.mark.parametrize("kind", KINDS)
def test_default_caps_are_reachable(kind):
    capacity = sum(len(v) for v in run(kind, cap=HUGE).values())
    assert capacity >= gc.DEFAULT_CAPS[kind]


# --------------------------------------------------------------------------- determinism
@pytest.mark.parametrize("kind", KINDS)
def test_same_seed_same_output(kind):
    assert run(kind, seed=5) == run(kind, seed=5)
    assert run(kind, seed=5, cap=37) == run(kind, seed=5, cap=37)


@pytest.mark.parametrize("kind", ["jokes", "quotes", "fortunes", "would_you_rather"])
def test_different_seed_changes_selection_when_capped(kind):
    assert run(kind, seed=1, cap=60) != run(kind, seed=2, cap=60)


@pytest.mark.parametrize("kind", KINDS)
def test_output_is_independent_of_global_random_state(kind):
    random.seed(111)
    a = run(kind, seed=9, cap=80)
    random.seed(222)
    random.random()
    b = run(kind, seed=9, cap=80)
    assert a == b


@pytest.mark.parametrize("kind", KINDS)
def test_generators_do_not_consume_global_random(kind):
    random.seed(4242)
    expected = random.random()
    random.seed(4242)
    run(kind, seed=3, cap=50)
    assert random.random() == expected


def _digest_all():
    blob = json.dumps({k: run(k, seed=123, cap=50) for k in KINDS}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def test_output_is_identical_across_processes_with_different_hash_seeds():
    code = (
        "import importlib.util, json, hashlib, random, sys\n"
        f"spec = importlib.util.spec_from_file_location('g', {str(GEN_PATH)!r})\n"
        "g = importlib.util.module_from_spec(spec); sys.modules['g'] = g; spec.loader.exec_module(g)\n"
        "kinds = ['jokes','quotes','compliments','fortunes','would_you_rather']\n"
        "out = {k: g.TEXT_GENERATORS[k](random.Random(123), 50) for k in kinds}\n"
        "print(hashlib.sha256(json.dumps(out, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest())\n"
    )
    digests = set()
    for hash_seed in ("0", "1", "987654"):
        env = dict(os.environ, PYTHONHASHSEED=hash_seed)
        result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True)
        digests.add(result.stdout.strip())
    assert digests == {_digest_all()}


def test_rng_for_streams_give_independent_generator_output():
    a = gc.generate_jokes(gc.rng_for(7, "jokes"), 40)
    b = gc.generate_jokes(gc.rng_for(7, "jokes"), 40)
    c = gc.generate_jokes(gc.rng_for(7, "other"), 40)
    assert a == b and a != c


# --------------------------------------------------------------------------- caps
@pytest.mark.parametrize("kind", KINDS)
def test_cap_zero_returns_empty_dict(kind):
    assert run(kind, cap=0) == {}


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("cap", [1, 2, 3, 4, 5, 7, 10, 50, 100])
def test_tiny_and_small_caps_are_exact(kind, cap):
    out = run(kind, cap=cap)
    capacity = sum(len(v) for v in run(kind, cap=HUGE).values())
    assert sum(len(v) for v in out.values()) == min(cap, capacity)
    assert all(out[c] for c in out)  # no empty categories are ever returned


@pytest.mark.parametrize("kind", KINDS)
def test_cap_one_returns_exactly_one_entry_in_one_category(kind):
    out = run(kind, cap=1)
    assert len(out) == 1 and len(flat(out)) == 1


@pytest.mark.parametrize("kind", KINDS)
def test_cap_above_capacity_returns_everything_unique(kind, full):
    total = sum(len(v) for v in full[kind].values())
    assert run(kind, cap=total + 500) == run(kind, cap=total + 1)
    assert sum(len(v) for v in run(kind, cap=total).values()) == total
    assert sum(len(v) for v in run(kind, cap=total - 1).values()) == total - 1


@pytest.mark.parametrize("kind", KINDS)
def test_capped_output_is_a_subset_of_the_full_pool(kind, full):
    # Lucky numbers are drawn from the seeded rng, so that one category's pool legitimately depends on the seed
    # (its structure is checked separately); every other category has a seed-independent pool.
    seed_dependent = {"just_for_fun_lucky"}

    def norm(entry):  # would-you-rather option order is a seeded coin flip, so compare the unordered pair
        match = re.fullmatch(r"Would you rather (.+) or (.+)\?", entry)
        return frozenset(match.groups()) if (kind == "would_you_rather" and match) else entry

    for cap in (1, 9, 77):
        out = run(kind, seed=4, cap=cap)
        for category, entries in out.items():
            if category not in seed_dependent:
                assert {norm(e) for e in entries} <= {norm(e) for e in full[kind][category]}


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("bad", [-1, -100])
def test_negative_cap_raises_value_error(kind, bad):
    with pytest.raises(ValueError):
        run(kind, cap=bad)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("bad", [True, False, 1.0, 2.5, "10", None, [5]])
def test_non_int_cap_raises_type_error(kind, bad):
    with pytest.raises(TypeError):
        gc.TEXT_GENERATORS[kind](random.Random(1), bad)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("bad", [None, 5, "seed", random])
def test_non_random_rng_raises_type_error(kind, bad):
    with pytest.raises(TypeError):
        gc.TEXT_GENERATORS[kind](bad, 10)


@pytest.mark.parametrize("kind", KINDS)
def test_false_is_not_accepted_as_a_zero_cap(kind):
    with pytest.raises(TypeError):
        gc.TEXT_GENERATORS[kind](random.Random(1), False)  # False == 0 but is not an int cap


def test_cap_is_shared_fairly_between_categories():
    out = run("jokes", cap=300)
    assert sorted(len(v) for v in out.values()) == [100, 100, 100]
    out = run("jokes", cap=1500)  # not_saying (216) is taken whole; the other two share the rest evenly
    assert {c: len(v) for c, v in out.items()} == {"advice": 642, "bar_walk_in": 642, "not_saying": 216}
    out = run("would_you_rather", cap=300)
    assert sorted(len(v) for v in out.values()) == [100, 100, 100]
    out = run("quotes", cap=40)
    assert sorted(len(v) for v in out.values()) == [10, 10, 10, 10]


# --------------------------------------------------------------------------- capacity equals pool products
def _theme_product(themes):
    return sum(len(t[0]) * len(t[1]) * len(t[2]) for t in themes.values())


def test_joke_capacity_equals_pool_products(full):
    counts = {c: len(v) for c, v in full["jokes"].items()}
    assert counts == {
        "advice": len(gc.JOKE_ADVICE_TEMPLATES) * len(gc.JOKE_AUTHORITIES) * len(gc.JOKE_PROBLEMS) * len(gc.JOKE_ANSWERS),
        "not_saying": sum(len(p) * len(c) for p, c in gc.JOKE_THEMES.values()),
        "bar_walk_in": len(gc.JOKE_BAR_CHARACTERS) * len(gc.JOKE_BAR_ORDERS) * len(gc.JOKE_BAR_REPLIES),
    }


def test_quote_capacity_equals_pool_products(full):
    counts = {c: len(v) for c, v in full["quotes"].items()}
    assert counts == {
        "original_reframe": _theme_product(gc.QUOTE_REFRAME_THEMES),
        "original_start_now": len(gc.QUOTE_START_CONDITIONS) * len(gc.QUOTE_START_ACTIONS) * len(gc.QUOTE_START_RESULTS),
        "original_daily_deposit": len(gc.QUOTE_DEPOSIT_THINGS) * len(gc.QUOTE_DEPOSIT_GIFTS) * len(gc.QUOTE_DEPOSIT_FUTURES),
        "original_rewards": len(gc.QUOTE_REWARD_NOUNS) * len(gc.QUOTE_REWARD_PAIRS),
    }


def test_compliment_capacity_equals_pool_products(full):
    counts = {c: len(v) for c, v in full["compliments"].items()}
    assert counts == {
        "as_as": len(gc.COMPLIMENT_TRAITS) * len(gc.COMPLIMENT_SIMILES),
        "you_make": len(gc.COMPLIMENT_HARD_THINGS) * len(gc.COMPLIMENT_LOOKS),
        "like_yours": len(gc.COMPLIMENT_QUALITIES) * len(gc.COMPLIMENT_EFFECTS),
    }


def test_fortune_capacity(full):
    counts = {c: len(v) for c, v in full["fortunes"].items()}
    forecast = (
        len(gc.FORTUNE_FORECAST_LABELS) * len(gc.FORTUNE_TIMEFRAMES) * len(gc.FORTUNE_EVENTS) * len(gc.FORTUNE_TWISTS)
    )
    assert counts["just_for_fun_forecast"] == forecast
    draws = len(gc.FORTUNE_ADVICE) * len(gc.FORTUNE_LUCKY_LABELS) * gc.FORTUNE_LUCKY_DRAWS
    assert 0.95 * draws <= counts["just_for_fun_lucky"] <= draws  # rare number collisions are de-duplicated


def test_would_you_rather_capacity_equals_pair_counts(full):
    p, l = len(gc.WYR_POWERS), len(gc.WYR_LIFESTYLE)
    counts = {c: len(v) for c, v in full["would_you_rather"].items()}
    assert counts == {"powers": p * (p - 1) // 2, "lifestyle": l * (l - 1) // 2, "mixed": p * l}


# --------------------------------------------------------------------------- de-duplication
@pytest.mark.parametrize("kind", KINDS)
def test_no_case_insensitive_duplicates_within_or_across_categories(kind, full):
    fingerprints = [gc.fingerprint(e) for e in flat(full[kind])]
    assert len(fingerprints) == len(set(fingerprints))
    assert len({e.lower() for e in flat(full[kind])}) == len(flat(full[kind]))


def test_pool_constants_have_no_internal_duplicates():
    pools = [
        gc.JOKE_AUTHORITIES, gc.JOKE_PROBLEMS, gc.JOKE_ANSWERS, gc.JOKE_BAR_CHARACTERS, gc.JOKE_BAR_ORDERS,
        gc.JOKE_BAR_REPLIES, gc.QUOTE_START_CONDITIONS, gc.QUOTE_START_ACTIONS, gc.QUOTE_START_RESULTS,
        gc.QUOTE_DEPOSIT_THINGS, gc.QUOTE_DEPOSIT_GIFTS, gc.QUOTE_DEPOSIT_FUTURES, gc.QUOTE_REWARD_NOUNS,
        gc.COMPLIMENT_TRAITS, gc.COMPLIMENT_HARD_THINGS, gc.COMPLIMENT_LOOKS, gc.COMPLIMENT_QUALITIES,
        gc.COMPLIMENT_EFFECTS, gc.FORTUNE_TIMEFRAMES, gc.FORTUNE_EVENTS, gc.FORTUNE_TWISTS, gc.FORTUNE_ADVICE,
        gc.WYR_POWERS, gc.WYR_LIFESTYLE, gc.QUOTE_REWARD_PAIRS, gc.COMPLIMENT_SIMILES,
    ]
    for pool in pools:
        keys = [gc.fingerprint(x if isinstance(x, str) else " ".join(x)) for x in pool]
        assert len(keys) == len(set(keys)), pool
    assert not set(gc.WYR_POWERS) & set(gc.WYR_LIFESTYLE)


def test_assemble_dedupes_case_insensitively_across_families():
    out = gc.assemble(random.Random(1), 100, {
        "a": ["Hello there.", "Hello THERE!", "Another one."],
        "b": ["Hello there?", "Unique to b."],
    })
    assert len(flat(out)) == 3
    texts = [gc.fingerprint(e) for e in flat(out)]
    assert len(set(texts)) == 3
    assert "Hello there." in out["a"]  # the first family (sorted) keeps the first copy
    assert "b" in out and out["b"] == ["Unique to b."]


def test_assemble_drops_a_family_that_dedupes_to_nothing():
    out = gc.assemble(random.Random(1), 10, {"a": ["Same text."], "b": ["SAME text!"]})
    assert out == {"a": ["Same text."]}


def test_assemble_cap_applies_after_dedupe():
    out = gc.assemble(random.Random(1), 3, {"a": ["One.", "ONE.", "Two.", "TWO."], "b": ["Three.", "THREE!"]})
    assert len(flat(out)) == 3 and sorted(gc.fingerprint(e) for e in flat(out)) == ["one", "three", "two"]


def test_assemble_raises_on_template_bug():
    with pytest.raises(ValueError, match="template bug"):
        gc.assemble(random.Random(1), 5, {"a": ["Fine.", "this is {broken}."]})
    with pytest.raises(ValueError, match="template bug"):
        gc.assemble(random.Random(1), 5, {"a": ["I bought a apple."]})


def test_assemble_zero_cap_and_empty_families():
    assert gc.assemble(random.Random(1), 0, {"a": ["Fine."]}) == {}
    assert gc.assemble(random.Random(1), 5, {}) == {}
    assert gc.assemble(random.Random(1), 5, {"a": []}) == {}


def test_assemble_respects_allocate_quotas():
    families = {"big": [f"Big entry number {chr(97 + i)}{chr(97 + j)}." for i in range(10) for j in range(10)],
                "small": ["Small one.", "Small two."]}
    out = gc.assemble(random.Random(3), 10, families)
    assert len(out["small"]) == 2 and len(out["big"]) == 8


# --------------------------------------------------------------------------- exact template membership
def _expected_jokes():
    advice = {
        t.format(authority=a, problem=p, answer=n)
        for t in gc.JOKE_ADVICE_TEMPLATES for a in gc.JOKE_AUTHORITIES for p in gc.JOKE_PROBLEMS for n in gc.JOKE_ANSWERS
    }
    saying = set()
    for premises, consequences in gc.JOKE_THEMES.values():
        for p, c in itertools.product(premises, consequences):
            saying.add("I'm not saying " + p + ", but " + c + ".")
    bar = {
        c + ' walks into a bar and says, "' + o + '" The bartender says, "' + r + '"'
        for c, o, r in itertools.product(gc.JOKE_BAR_CHARACTERS, gc.JOKE_BAR_ORDERS, gc.JOKE_BAR_REPLIES)
    }
    return {"advice": advice, "not_saying": saying, "bar_walk_in": bar}


def test_joke_entries_match_their_templates_exactly(full):
    expected = _expected_jokes()
    assert {c: set(v) for c, v in full["jokes"].items()} == expected


def test_joke_families_have_the_expected_shapes(full):
    for e in full["jokes"]["advice"]:
        assert re.fullmatch(r'(I asked .+ what to do about .+, and the answer was, ".+\."|For help with .+, I consulted .+\. The entire reply was, ".+\.")', e)
    for e in full["jokes"]["not_saying"]:
        assert re.fullmatch(r"I'm not saying .+, but .+\.", e)
    for e in full["jokes"]["bar_walk_in"]:
        assert re.fullmatch(r'An? .+ walks into a bar and says, ".+[.!?]" The bartender says, ".+[.!?]"', e)


def test_joke_themes_are_consistent_shapes():
    assert len(gc.JOKE_THEMES) >= 6
    for name, (premises, consequences) in gc.JOKE_THEMES.items():
        assert re.fullmatch(r"[a-z_]+", name)
        assert len(premises) >= 5 and len(consequences) >= 5
        assert all(not p.endswith((".", "!", "?")) for p in premises)
        assert all(not c.endswith((".", "!", "?")) for c in consequences)


def _expected_quotes():
    reframe = {
        f"{v} is not {m}; it is {t}."
        for virtues, misc, truths in gc.QUOTE_REFRAME_THEMES.values()
        for v, m, t in itertools.product(virtues, misc, truths)
    }
    start = {
        "Do not wait for " + c + "; " + a + ", and " + r + " will follow."
        for c, a, r in itertools.product(gc.QUOTE_START_CONDITIONS, gc.QUOTE_START_ACTIONS, gc.QUOTE_START_RESULTS)
    }
    deposit = {
        "Every " + t + " is " + g + " " + f + "."
        for t, g, f in itertools.product(gc.QUOTE_DEPOSIT_THINGS, gc.QUOTE_DEPOSIT_GIFTS, gc.QUOTE_DEPOSIT_FUTURES)
    }
    rewards = {
        n + " rewards those who " + b + ", not those who " + a + "."
        for n in gc.QUOTE_REWARD_NOUNS for b, a in gc.QUOTE_REWARD_PAIRS
    }
    return {"original_reframe": reframe, "original_start_now": start, "original_daily_deposit": deposit,
            "original_rewards": rewards}


def test_quote_entries_match_their_templates_exactly(full):
    assert {c: set(v) for c, v in full["quotes"].items()} == _expected_quotes()


def test_compliment_entries_match_their_templates_exactly(full):
    expected = {
        "as_as": {f"Your {t} is as {a} as {m}." for t in gc.COMPLIMENT_TRAITS for a, m in gc.COMPLIMENT_SIMILES},
        "you_make": {f"You make {h} look {l}." for h in gc.COMPLIMENT_HARD_THINGS for l in gc.COMPLIMENT_LOOKS},
        "like_yours": {f"{q} like yours is why {e}." for q in gc.COMPLIMENT_QUALITIES for e in gc.COMPLIMENT_EFFECTS},
    }
    assert {c: set(v) for c, v in full["compliments"].items()} == expected


def test_fortune_forecast_entries_match_their_template_exactly(full):
    expected = {
        f"{lab} {tf}, you might {ev}, and {tw}."
        for lab, tf, ev, tw in itertools.product(
            gc.FORTUNE_FORECAST_LABELS, gc.FORTUNE_TIMEFRAMES, gc.FORTUNE_EVENTS, gc.FORTUNE_TWISTS)
    }
    assert set(full["fortunes"]["just_for_fun_forecast"]) == expected


def test_fortune_lucky_entries_have_valid_distinct_ascending_numbers(full):
    advice_by_text = {f"{lab} {adv}.": None for lab in gc.FORTUNE_LUCKY_LABELS for adv in gc.FORTUNE_ADVICE}
    for entry in full["fortunes"]["just_for_fun_lucky"]:
        match = re.fullmatch(r"(.+\.) Lucky numbers: (\d{1,2}), (\d{1,2}), (\d{1,2})\.", entry)
        assert match, entry
        assert match.group(1) in advice_by_text
        a, b, c = (int(match.group(i)) for i in (2, 3, 4))
        assert 1 <= a < b < c <= 60


def test_lucky_numbers_helper_is_deterministic_and_in_range():
    seen = set()
    for seed in range(200):
        text = gc._lucky_numbers(random.Random(seed))
        assert text == gc._lucky_numbers(random.Random(seed))
        nums = [int(x) for x in text.split(", ")]
        assert len(nums) == 3 and nums == sorted(set(nums)) and all(1 <= n <= 60 for n in nums)
        seen.update(nums)
    assert len(seen) > 40


def test_would_you_rather_entries_are_valid_unordered_pairs(full):
    powers, life = set(gc.WYR_POWERS), set(gc.WYR_LIFESTYLE)
    groups = {"powers": (powers, powers), "lifestyle": (life, life), "mixed": (powers, life)}
    for category, entries in full["would_you_rather"].items():
        left_pool, right_pool = groups[category]
        pairs = set()
        for entry in entries:
            match = re.fullmatch(r"Would you rather (.+) or (.+)\?", entry)
            assert match, entry
            a, b = match.groups()
            assert a != b
            assert (a in left_pool and b in right_pool) or (b in left_pool and a in right_pool), entry
            key = frozenset((a, b))
            assert key not in pairs  # each unordered pair appears once
            pairs.add(key)
    expected_mixed = {frozenset(p) for p in itertools.product(gc.WYR_POWERS, gc.WYR_LIFESTYLE)}
    got_mixed = {frozenset(re.fullmatch(r"Would you rather (.+) or (.+)\?", e).groups())
                 for e in full["would_you_rather"]["mixed"]}
    assert got_mixed == expected_mixed


def test_would_you_rather_order_is_mixed_not_always_the_same():
    firsts = [re.fullmatch(r"Would you rather (.+) or (.+)\?", e).group(1) for e in run("would_you_rather", cap=HUGE)["mixed"]]
    from_powers = sum(1 for f in firsts if f in set(gc.WYR_POWERS))
    assert 0.3 * len(firsts) < from_powers < 0.7 * len(firsts)


# --------------------------------------------------------------------------- pool coverage
def _covered(entries, pool):
    blob = "\n".join(entries)
    return [item for item in pool if item not in blob]


def test_every_pool_item_is_used(full):
    j, q, c, f, w = (full[k] for k in KINDS)
    assert _covered(j["advice"], gc.JOKE_AUTHORITIES + gc.JOKE_PROBLEMS + gc.JOKE_ANSWERS) == []
    assert _covered(j["bar_walk_in"], gc.JOKE_BAR_CHARACTERS + gc.JOKE_BAR_ORDERS + gc.JOKE_BAR_REPLIES) == []
    for premises, consequences in gc.JOKE_THEMES.values():
        assert _covered(j["not_saying"], premises + consequences) == []
    for virtues, misc, truths in gc.QUOTE_REFRAME_THEMES.values():
        assert _covered(q["original_reframe"], virtues + misc + truths) == []
    assert _covered(q["original_start_now"], gc.QUOTE_START_CONDITIONS + gc.QUOTE_START_ACTIONS + gc.QUOTE_START_RESULTS) == []
    assert _covered(q["original_daily_deposit"], gc.QUOTE_DEPOSIT_THINGS + gc.QUOTE_DEPOSIT_GIFTS + gc.QUOTE_DEPOSIT_FUTURES) == []
    assert _covered(q["original_rewards"], gc.QUOTE_REWARD_NOUNS) == []
    assert _covered(c["as_as"], gc.COMPLIMENT_TRAITS + tuple(x for pair in gc.COMPLIMENT_SIMILES for x in pair)) == []
    assert _covered(c["you_make"], gc.COMPLIMENT_HARD_THINGS + gc.COMPLIMENT_LOOKS) == []
    assert _covered(c["like_yours"], gc.COMPLIMENT_QUALITIES + gc.COMPLIMENT_EFFECTS) == []
    assert _covered(f["just_for_fun_forecast"], gc.FORTUNE_FORECAST_LABELS + gc.FORTUNE_TIMEFRAMES + gc.FORTUNE_EVENTS + gc.FORTUNE_TWISTS) == []
    assert _covered(f["just_for_fun_lucky"], gc.FORTUNE_LUCKY_LABELS + gc.FORTUNE_ADVICE) == []
    assert _covered(flat(w), gc.WYR_POWERS + gc.WYR_LIFESTYLE) == []


# --------------------------------------------------------------------------- labeling and safety
FAMOUS_NAMES = ["einstein", "twain", "gandhi", "churchill", "confucius", "aristotle", "shakespeare", "lincoln",
                "socrates", "plato", "franklin", "mandela", "jobs", "buddha", "lao tzu", "nietzsche", "wilde",
                "king jr", "roosevelt", "edison"]


def test_quotes_are_unattributed_and_prefixed_original(full):
    quotes = full["quotes"]
    assert all(category.startswith("original_") for category in quotes)
    for entry in flat(quotes):
        assert not re.search(r"[—–]|(^|\s)-{1,2}\s", entry), entry  # no dash attributions
        assert '"' not in entry and "“" not in entry and "”" not in entry  # no quotation marks
        low = entry.lower()
        for word in ("proverb", "ancient", "once said", "according to", "said by", "famous"):
            assert word not in low, entry
        for name in FAMOUS_NAMES:
            assert name not in low, (name, entry)


@pytest.mark.parametrize("kind", ["jokes", "compliments", "fortunes", "would_you_rather"])
def test_no_attribution_or_famous_names_in_other_kinds(kind, full):
    for entry in flat(full[kind]):
        low = entry.lower()
        assert not re.search(r"[—–]", entry)
        assert "proverb" not in low and "according to" not in low
        for name in FAMOUS_NAMES:
            assert name not in low, (name, entry)


def test_every_fortune_is_labeled_and_label_set_is_consistent(full):
    assert set(gc.FORTUNE_LABELS) >= set(gc.FORTUNE_FORECAST_LABELS) | set(gc.FORTUNE_LUCKY_LABELS)
    assert len(gc.FORTUNE_LABELS) == len(set(gc.FORTUNE_LABELS))
    for entry in flat(full["fortunes"]):
        assert any(entry.startswith(label + " ") for label in gc.FORTUNE_LABELS), entry
        assert re.match(r"(Just for fun|Fortune-cookie style|Cookie forecast \(entertainment only\)|"
                        r"Lucky-biscuit wisdom|Unscientific forecast|Strictly for entertainment):", entry)


def test_forecast_fortunes_are_hedged_and_never_certain(full):
    for entry in full["fortunes"]["just_for_fun_forecast"]:
        assert re.search(r"\bmight\b", entry)
        body = entry.split(":", 1)[1]
        assert re.search(r"\b(might|may|could)\b", body)
        assert not re.search(r"\b(will|shall|guarantee[sd]?|certain|certainly|definitely|destined)\b", body.lower()), entry


def test_no_fortune_contains_will_or_real_world_advice(full):
    banned = re.compile(
        r"\b(will|won't|health|healthy|medic\w*|doctor|disease|sick|illness|cure[sd]?|diet|weight|pregnan\w*|"
        r"money|cash|invest\w*|stocks?|crypto\w*|loans?|debts?|lottery|jackpot|salary|savings|gambl\w*|bet)\b",
        re.IGNORECASE)
    for entry in flat(full["fortunes"]):
        assert not banned.search(entry), entry


def test_fortune_entries_state_that_numbers_are_for_fun_only(full):
    for entry in full["fortunes"]["just_for_fun_lucky"]:
        assert "Lucky numbers:" in entry
        assert not re.search(r"\b(win|winning|jackpot|lottery|draw)\b", entry.lower())


def test_content_is_family_friendly(full):
    banned = re.compile(r"\b(damn|hell|crap|sex\w*|kill\w*|dead|die[sd]?|death|drunk|drug\w*|gun|weapon)\b", re.IGNORECASE)
    for kind in KINDS:
        for entry in flat(full[kind]):
            assert not banned.search(entry), entry


# --------------------------------------------------------------------------- helper unit tests: lint
@pytest.mark.parametrize("text", [
    "A ghost walks in.", "An alien waves.", "I bought an apple.", "That took an hour.", "It was a unicorn.",
    "A useful tip.", "An honest answer.", "A one-time offer.", "Why?", "Stop!", 'He said, "Go."', "7 is lucky.",
    "She is a university student.", "Would you rather fly or swim?",
])
def test_lint_accepts_clean_text(text):
    assert gc.lint_text(text) == []


@pytest.mark.parametrize("text,needle", [
    ("", "empty"),
    ("this is lowercase.", "capital"),
    ("No terminal punctuation", "must end"),
    ("Trailing space. ", "whitespace"),
    (" Leading space.", "whitespace"),
    ("Double  space.", "double space"),
    ("Unresolved {thing} here.", "braces"),
    ("Stray } brace.", "braces"),
    ("This is is repeated.", "repeated"),
    ("The the cat.", "repeated"),
    ("I bought a apple.", "a/an"),
    ("It was an dog.", "a/an"),
    ("It was a hour.", "a/an"),
    ("It was an unicorn.", "a/an"),
    ("It was an useful tip.", "a/an"),
    ("It was a honest answer.", "a/an"),
    ("It was a investment.", "a/an"),
    ("x" * 1001 + ".", "too long"),
])
def test_lint_catches_problem(text, needle):
    problems = gc.lint_text(text)
    assert any(needle in p for p in problems), problems


def test_lint_rejects_non_strings():
    assert gc.lint_text(None) and gc.lint_text(42)


# --------------------------------------------------------------------------- helper unit tests: check_cap / check_rng / cap_first
def test_check_cap_accepts_ints_only():
    assert gc.check_cap(0) == 0 and gc.check_cap(7) == 7
    for bad in (True, False, 1.0, "1", None):
        with pytest.raises(TypeError):
            gc.check_cap(bad)
    with pytest.raises(ValueError):
        gc.check_cap(-1)


def test_check_rng_accepts_random_and_subclasses_only():
    r = random.Random(1)
    assert gc.check_rng(r) is r
    assert gc.check_rng(random.SystemRandom()) is not None
    for bad in (None, 1, random, "x"):
        with pytest.raises(TypeError):
            gc.check_rng(bad)


def test_cap_first():
    assert gc.cap_first("hello") == "Hello" and gc.cap_first("") == "" and gc.cap_first("Éa") == "Éa"
    assert gc.cap_first("élan") == "Élan"


# --------------------------------------------------------------------------- helper unit tests: stable_pick
def test_stable_pick_basics():
    items = list(range(20))
    picked = gc.stable_pick(random.Random(1), items, 7)
    assert len(picked) == 7 and len(set(picked)) == 7 and set(picked) <= set(items)
    assert picked == gc.stable_pick(random.Random(1), items, 7)
    assert picked != gc.stable_pick(random.Random(2), items, 7)
    assert gc.stable_pick(random.Random(1), items, 0) == []
    assert gc.stable_pick(random.Random(1), items, -3) == []
    assert gc.stable_pick(random.Random(1), [], 5) == []
    assert sorted(gc.stable_pick(random.Random(1), items, 500)) == items
    assert items == list(range(20))  # input untouched


def test_stable_pick_accepts_any_sequence_and_does_not_mutate():
    assert len(gc.stable_pick(random.Random(3), tuple("abcdef"), 3)) == 3
    assert len(gc.stable_pick(random.Random(3), "abcdef", 3)) == 3


def test_stable_pick_is_pinned_across_python_versions():
    # Mersenne Twister getrandbits is stable across CPython versions; this pins the selection algorithm.
    assert gc.stable_pick(random.Random("pin"), list(range(10)), 5) == PINNED_PICK


def test_stable_pick_is_roughly_uniform():
    counts = [0] * 10
    for seed in range(2000):
        for item in gc.stable_pick(random.Random(seed), list(range(10)), 3):
            counts[item] += 1
    assert all(500 < c < 700 for c in counts), counts  # expected 600 each


# --------------------------------------------------------------------------- helper unit tests: allocate
def test_allocate_even_split_and_remainder():
    a = gc.allocate(7, {"a": 10, "b": 10, "c": 10}, random.Random(1))
    assert sum(a.values()) == 7 and sorted(a.values()) == [2, 2, 3]
    assert gc.allocate(7, {"a": 10, "b": 10, "c": 10}, random.Random(1)) == a


def test_allocate_small_family_taken_whole_rest_shared():
    assert gc.allocate(10, {"a": 1, "b": 100}, random.Random(1)) == {"a": 1, "b": 9}
    assert sorted(gc.allocate(100, {"a": 5, "b": 100, "c": 100}, random.Random(1)).values()) == [5, 47, 48]
    assert gc.allocate(100, {"a": 5, "b": 100, "c": 100}, random.Random(1))["a"] == 5


def test_allocate_edges():
    assert gc.allocate(0, {"a": 3, "b": 3}, random.Random(1)) == {"a": 0, "b": 0}
    assert gc.allocate(99, {"a": 3, "b": 4}, random.Random(1)) == {"a": 3, "b": 4}
    assert gc.allocate(5, {}, random.Random(1)) == {}
    assert gc.allocate(5, {"a": 0, "b": 0}, random.Random(1)) == {"a": 0, "b": 0}
    assert gc.allocate(2, {"a": 0, "b": 5}, random.Random(1)) == {"a": 0, "b": 2}
    one = gc.allocate(1, {"a": 5, "b": 5, "c": 5}, random.Random(1))
    assert set(one) == {"a", "b", "c"} and sum(one.values()) == 1


def test_allocate_rejects_bad_input():
    with pytest.raises(ValueError):
        gc.allocate(1, {"a": -1}, random.Random(1))
    with pytest.raises(ValueError):
        gc.allocate(-1, {"a": 1}, random.Random(1))
    with pytest.raises(TypeError):
        gc.allocate(1.5, {"a": 1}, random.Random(1))
    with pytest.raises(TypeError):
        gc.allocate(1, {"a": 1}, None)


def test_allocate_extra_slot_goes_to_different_families_for_different_seeds():
    winners = set()
    for seed in range(60):
        alloc = gc.allocate(1, {"a": 5, "b": 5, "c": 5}, random.Random(seed))
        winners.update(name for name, v in alloc.items() if v)
    assert winners == {"a", "b", "c"}


def test_allocate_invariants_over_random_inputs():
    meta = random.Random(2024)
    for _ in range(600):
        n = meta.randint(1, 6)
        sizes = {f"f{i}": meta.choice([0, 1, 2, 3, 5, 10, 50, 400]) for i in range(n)}
        cap = meta.choice([0, 1, 2, 3, 5, 8, 13, 50, 200, 1000])
        alloc = gc.allocate(cap, sizes, random.Random(meta.getrandbits(32)))
        assert set(alloc) == set(sizes)
        assert sum(alloc.values()) == min(cap, sum(sizes.values()))
        assert all(0 <= alloc[k] <= sizes[k] for k in sizes)
        for i in sizes:  # fairness: a family that is not full is never more than 1 below any other
            if alloc[i] < sizes[i]:
                assert all(alloc[j] <= alloc[i] + 1 for j in sizes), (sizes, cap, alloc)


# --------------------------------------------------------------------------- pinned digest (determinism contract)
def test_full_output_digest_is_pinned_for_default_seed():
    blob = json.dumps({k: run(k, seed=gc.DEFAULT_SEED, cap=60) for k in KINDS}, sort_keys=True, ensure_ascii=False)
    assert hashlib.sha256(blob.encode("utf-8")).hexdigest() == PINNED_DIGEST


# --------------------------------------------------------------------------- Stage 1 / Stage 2 integration
def test_stage1_and_stage2_api_is_still_present():
    for name in ("fingerprint", "unique", "payload_fingerprints", "dedupe_against", "atomic_write_json",
                 "validate_payload", "builder", "rng_for", "build_all", "finalize", "validate_all", "summarize",
                 "main", "DEFAULT_SEED", "MAX_ENTRY_CHARS", "BUILDERS", "COUNTRIES", "ELEMENTS", "Country",
                 "Element", "quiz_countries", "countries_by_region", "fold", "validate_reference_data"):
        assert hasattr(gc, name), name
    assert gc.validate_reference_data() == []


def test_stage3_does_not_register_builders_or_write_files(tmp_path, capsys):
    assert gc.BUILDERS == []
    assert gc.build_all(1) == {}
    assert gc.main(["--out", str(tmp_path)]) == 0
    assert list(tmp_path.iterdir()) == []
    assert "no builders" in capsys.readouterr().out.lower()


def test_generators_do_not_write_anything(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for kind in KINDS:
        run(kind, cap=25)
    assert list(tmp_path.iterdir()) == []


def test_generators_do_not_mutate_the_pool_constants():
    before = repr((gc.JOKE_THEMES, gc.QUOTE_REFRAME_THEMES, gc.WYR_POWERS, gc.FORTUNE_ADVICE, gc.JOKE_ANSWERS))
    for kind in KINDS:
        run(kind, cap=HUGE)
    assert before == repr((gc.JOKE_THEMES, gc.QUOTE_REFRAME_THEMES, gc.WYR_POWERS, gc.FORTUNE_ADVICE, gc.JOKE_ANSWERS))


@pytest.mark.parametrize("kind", KINDS)
def test_generated_packs_atomically_write_and_round_trip_through_the_runtime_loader(kind, tmp_path):
    from bot.content import ContentLibrary

    payload = run(kind, seed=3, cap=120)
    gc.atomic_write_json(tmp_path / f"{kind}.generated.json", payload)
    assert json.loads((tmp_path / f"{kind}.generated.json").read_text(encoding="utf-8")) == payload
    lib = ContentLibrary(tmp_path, seed=1)
    assert lib.category_counts(kind) == {c: len(v) for c, v in payload.items()}
    for category, entries in payload.items():
        assert sorted(lib.pool(kind, category)) == sorted(entries)


def test_curated_entries_still_win_over_generated_duplicates():
    generated = run("jokes", seed=1, cap=HUGE)
    victim = generated["not_saying"][0]
    packs = {"jokes": {"general": [victim.upper()]}, "jokes.generated": generated}
    out = gc.finalize(packs)
    assert victim not in out["jokes.generated"].get("not_saying", [])
    assert out["jokes"] == packs["jokes"]
```
