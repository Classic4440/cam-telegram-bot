"""Content library: loads JSON packs, serves without immediate repeats. [155 lines]

Pack format (one file per kind; ``<kind>.json`` and/or ``<kind>.generated.json``)::

    {"category": ["entry", "entry", ...], "another": [...]}

or, for structured kinds (trivia, riddles), ``{"category": [{...}, ...]}``.

* Curated and generated packs for the same kind are merged and de-duplicated (case/space-insensitive).
* ``pick`` walks a shuffled "deck" per (chat, kind, category) so the same entry never repeats until the
  whole deck has been used.
* ``reload`` re-reads disk, so new packs go live without a restart (admin ``/reload``).
"""
from __future__ import annotations

import json
import logging
import random
import re
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent / "data"
_PACK_NAME = re.compile(r"^(?P<kind>[a-z0-9_]+)(?:\.[a-z0-9_]+)?\.json$")


def _fingerprint(entry: Any) -> str:
    """Case-insensitive, whitespace-normalized fingerprint for de-duping."""
    if isinstance(entry, str):
        return re.sub(r"\W+", " ", entry.lower()).strip()
    if isinstance(entry, dict):
        return re.sub(r"\W+", " ", str(entry.get("q") or entry.get("question") or entry.get("text") or entry).lower()).strip()
    return str(entry)


class ContentLibrary:
    def __init__(self, data_dir: Path = DATA_DIR, seed: int | None = None) -> None:
        self.data_dir = data_dir
        self._rng = random.Random(seed)
        self._lock = threading.RLock()
        self._packs: dict[str, dict[str, list[Any]]] = {}
        self._decks: OrderedDict[tuple, list[int]] = OrderedDict()
        self.load()

    # ---------------------------------------------------------------- loading
    def load(self) -> dict[str, int]:
        """Load all *.json packs from data_dir, merge, de-dup, and return counts."""
        packs: dict[str, dict[str, list[Any]]] = {}
        seen: dict[str, set[str]] = {}
        files = sorted(self.data_dir.glob("*.json"))
        for path in files:
            match = _PACK_NAME.match(path.name)
            if not match:
                continue
            kind = match.group("kind")
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                logger.exception("Skipping unreadable content pack %s", path.name)
                continue
            if isinstance(payload, list):
                payload = {"general": payload}
            if not isinstance(payload, dict):
                logger.warning("Content pack %s has unsupported shape", path.name)
                continue
            bucket = packs.setdefault(kind, {})
            dedupe = seen.setdefault(kind, set())
            for category, entries in payload.items():
                if not isinstance(entries, list):
                    continue
                target = bucket.setdefault(str(category).lower(), [])
                for entry in entries:
                    key = _fingerprint(entry)
                    if key and key not in dedupe:
                        dedupe.add(key)
                        target.append(entry)
        with self._lock:
            self._packs = packs
            self._decks.clear()
        counts = self.counts()
        logger.info("Loaded content: %s", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
        return counts

    reload = load

    # ---------------------------------------------------------------- queries
    def kinds(self) -> list[str]:
        """Sorted list of all content kinds (jokes, quotes, etc.)."""
        return sorted(self._packs)

    def categories(self, kind: str) -> list[str]:
        """Sorted categories within a kind."""
        return sorted(self._packs.get(kind, {}))

    def counts(self) -> dict[str, int]:
        """Total entry count per kind."""
        return {kind: sum(len(v) for v in cats.values()) for kind, cats in self._packs.items()}

    def total(self) -> int:
        """Total entries across all kinds."""
        return sum(self.counts().values())

    def category_counts(self, kind: str) -> dict[str, int]:
        """Entry count per category within a kind."""
        return {cat: len(items) for cat, items in self._packs.get(kind, {}).items()}

    def resolve_category(self, kind: str, wanted: str | None) -> str | None:
        """Map user input to a category: exact → prefix → substring."""
        if not wanted:
            return None
        wanted = wanted.lower().strip()
        cats = self.categories(kind)
        if wanted in cats:
            return wanted
        for test in (lambda c: c.startswith(wanted), lambda c: wanted in c):
            hits = [c for c in cats if test(c)]
            if len(hits) == 1:
                return hits[0]
        return None

    def pool(self, kind: str, category: str | None = None) -> list[Any]:
        """All entries for a kind (all categories if category=None)."""
        cats = self._packs.get(kind, {})
        if category:
            return cats.get(category, [])
        merged: list[Any] = []
        for items in cats.values():
            merged.extend(items)
        return merged

    def pick(self, kind: str, category: str | None = None, scope: Any = None) -> Any | None:
        """Random entry without repeating per scope until deck exhausted. LRU deck per (scope, kind, category)."""
        pool = self.pool(kind, category)
        if not pool:
            return None
        key = (scope, kind, category)
        with self._lock:
            deck = self._decks.get(key)
            if not deck:
                deck = list(range(len(pool)))
                self._rng.shuffle(deck)
            index = deck.pop()
            self._decks[key] = deck
            self._decks.move_to_end(key)
            while len(self._decks) > 2000:
                self._decks.popitem(last=False)
        return pool[index % len(pool)]

    def sample(self, kind: str, n: int, category: str | None = None) -> list[Any]:
        """Random sample of n entries without replacement."""
        pool = self.pool(kind, category)
        return self._rng.sample(pool, min(n, len(pool)))

    def search(self, kind: str, term: str, limit: int = 5) -> list[Any]:
        """Full-text search across a kind, return shuffled top-N."""
        term = term.lower().strip()
        if not term:
            return []
        hits = [item for item in self.pool(kind) if term in _fingerprint(item)]
        self._rng.shuffle(hits)
        return hits[:limit]
