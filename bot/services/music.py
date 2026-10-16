"""Music-theory and studio helpers: scales, chords, keys, transposition, tempo maths, note frequencies."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLAT = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
_NOTE_INDEX = {**{n: i for i, n in enumerate(SHARP)}, **{n: i for i, n in enumerate(FLAT)}}
_NOTE_INDEX.update({"E#": 5, "B#": 0, "Cb": 11, "Fb": 4})
_FLAT_KEYS = {"F", "Bb", "Eb", "Ab", "Db", "Gb", "Cb"}

SCALES: dict[str, list[int]] = {
    "major": [0, 2, 4, 5, 7, 9, 11],
    "minor": [0, 2, 3, 5, 7, 8, 10],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "phrygian": [0, 1, 3, 5, 7, 8, 10],
    "lydian": [0, 2, 4, 6, 7, 9, 11],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
    "locrian": [0, 1, 3, 5, 6, 8, 10],
    "harmonic_minor": [0, 2, 3, 5, 7, 8, 11],
    "melodic_minor": [0, 2, 3, 5, 7, 9, 11],
    "pentatonic_major": [0, 2, 4, 7, 9],
    "pentatonic_minor": [0, 3, 5, 7, 10],
    "blues": [0, 3, 5, 6, 7, 10],
    "whole_tone": [0, 2, 4, 6, 8, 10],
    "chromatic": list(range(12)),
}
_SCALE_ALIASES = {
    "maj": "major", "ionian": "major", "min": "minor", "aeolian": "minor", "natural_minor": "minor",
    "harmonic": "harmonic_minor", "melodic": "melodic_minor", "minor_pentatonic": "pentatonic_minor",
    "major_pentatonic": "pentatonic_major", "pentatonic": "pentatonic_minor",
}

CHORDS: dict[str, list[int]] = {
    "": [0, 4, 7], "m": [0, 3, 7], "dim": [0, 3, 6], "aug": [0, 4, 8],
    "sus2": [0, 2, 7], "sus4": [0, 5, 7], "5": [0, 7],
    "6": [0, 4, 7, 9], "m6": [0, 3, 7, 9],
    "7": [0, 4, 7, 10], "maj7": [0, 4, 7, 11], "m7": [0, 3, 7, 10], "dim7": [0, 3, 6, 9],
    "m7b5": [0, 3, 6, 10], "mmaj7": [0, 3, 7, 11], "7sus4": [0, 5, 7, 10],
    "add9": [0, 4, 7, 14], "madd9": [0, 3, 7, 14],
    "9": [0, 4, 7, 10, 14], "maj9": [0, 4, 7, 11, 14], "m9": [0, 3, 7, 10, 14],
    "11": [0, 4, 7, 10, 14, 17], "13": [0, 4, 7, 10, 14, 21],
}
_QUALITY_ALIASES = {
    "maj": "", "M": "", "min": "m", "-": "m", "°": "dim", "+": "aug", "M7": "maj7", "Δ": "maj7", "Δ7": "maj7",
    "min7": "m7", "-7": "m7", "ø": "m7b5", "ø7": "m7b5", "dom7": "7", "min9": "m9", "min6": "m6",
}

_DIATONIC = {
    "major": [("I", ""), ("ii", "m"), ("iii", "m"), ("IV", ""), ("V", ""), ("vi", "m"), ("vii°", "dim")],
    "minor": [("i", "m"), ("ii°", "dim"), ("III", ""), ("iv", "m"), ("v", "m"), ("VI", ""), ("VII", "")],
}

NOTE_VALUES = [
    ("1/1 (whole)", 4.0), ("1/2", 2.0), ("1/4 (quarter)", 1.0), ("1/8", 0.5), ("1/16", 0.25), ("1/32", 0.125),
]


class MusicError(ValueError):
    pass


def parse_note(token: str) -> int:
    token = token.strip()
    token = token[:1].upper() + token[1:].replace("♯", "#").replace("♭", "b")
    if token not in _NOTE_INDEX:
        raise MusicError(f"'{token[:6]}' isn't a note. Use C, C#, Db, F#, Bb ...")
    return _NOTE_INDEX[token]


def spell(index: int, use_flats: bool) -> str:
    return (FLAT if use_flats else SHARP)[index % 12]


def prefer_flats(root: str, minor: bool = False) -> bool:
    if "b" in root[1:]:
        return True
    if minor:
        # the relative major decides the spelling (D minor -> F major -> flats)
        return "#" not in root and FLAT[(parse_note(root) + 3) % 12] in _FLAT_KEYS
    return root in _FLAT_KEYS


def resolve_scale(name: str) -> str:
    key = name.lower().replace(" ", "_").replace("-", "_")
    key = _SCALE_ALIASES.get(key, key)
    if key not in SCALES:
        raise MusicError("Scales: " + ", ".join(SCALES))
    return key


_LETTERS = "CDEFGAB"
_NATURAL = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def _spell_by_letter(root: str, step: int, degree: int) -> str:
    """Spell scale degree ``degree`` (0-based) using consecutive letter names (F# major has E#, not F)."""
    letter = _LETTERS[(_LETTERS.index(root[0]) + degree) % 7]
    pitch_class = (parse_note(root) + step) % 12
    diff = (pitch_class - _NATURAL[letter] + 6) % 12 - 6
    return letter + ("#" * diff if diff > 0 else "b" * -diff)


def scale_notes(root: str, scale: str = "major") -> list[str]:
    scale = resolve_scale(scale)
    root = root[:1].upper() + root[1:].replace("♯", "#").replace("♭", "b")
    start = parse_note(root)
    steps = SCALES[scale]
    if len(steps) == 7:  # heptatonic scales use proper letter spelling
        return [_spell_by_letter(root, step, degree) for degree, step in enumerate(steps)]
    flats = prefer_flats(root, minor=scale in {"minor", "pentatonic_minor", "blues"})
    return [spell(start + step, flats) for step in steps]


@dataclass(slots=True)
class Chord:
    root: str
    quality: str
    notes: list[str]

    @property
    def name(self) -> str:
        return f"{self.root}{self.quality}"


_CHORD_RE = re.compile(r"^([A-Ga-g][#b♯♭]?)(.*)$")


def parse_chord(token: str) -> Chord:
    match = _CHORD_RE.match(token.strip())
    if not match:
        raise MusicError(f"Couldn't read chord '{token[:10]}'")
    root_raw, quality = match.group(1), match.group(2)
    root_raw = root_raw[:1].upper() + root_raw[1:].replace("♯", "#").replace("♭", "b")
    quality = _QUALITY_ALIASES.get(quality, quality)
    if quality not in CHORDS:
        raise MusicError(f"Unknown chord quality '{quality}'. Try: " + ", ".join(q or "maj" for q in CHORDS))
    start = parse_note(root_raw)
    flats = prefer_flats(root_raw, minor=quality.startswith("m") and not quality.startswith("maj"))
    notes = []
    for step in CHORDS[quality]:
        notes.append(spell(start + step, flats))
    # de-duplicate while preserving order (e.g. add9 spelled above the octave)
    seen, ordered = set(), []
    for n in notes:
        if n not in seen:
            seen.add(n)
            ordered.append(n)
    return Chord(root_raw, quality, ordered)


def diatonic_chords(root: str, mode: str = "major") -> list[tuple[str, str]]:
    mode = resolve_scale(mode)
    if mode not in _DIATONIC:
        raise MusicError("Diatonic chords are available for major and minor")
    notes = scale_notes(root, mode)
    return [(numeral, f"{note}{quality}") for (numeral, quality), note in zip(_DIATONIC[mode], notes)]


def relative_key(root: str, mode: str = "major") -> tuple[str, str]:
    mode = resolve_scale(mode)
    idx = parse_note(root)
    if mode == "major":
        return spell(idx + 9, prefer_flats(root)), "minor"
    if mode == "minor":
        return spell(idx + 3, prefer_flats(root, minor=True)), "major"
    raise MusicError("Relative keys are defined for major and minor")


def transpose_chords(tokens: list[str], semitones: int) -> list[str]:
    out = []
    for token in tokens:
        chord = parse_chord(token)
        flats = semitones < 0 or "b" in chord.root
        slash = ""
        if "/" in token:
            _, bass = token.split("/", 1)
            slash = "/" + spell(parse_note(bass) + semitones, flats)
        out.append(spell(parse_note(chord.root) + semitones, flats) + chord.quality + slash)
    return out


def note_frequency(token: str) -> dict[str, float | str | int]:
    """``A4`` -> 440 Hz, MIDI 69 (equal temperament, A4 = 440)."""
    match = re.fullmatch(r"([A-Ga-g][#b♯♭]?)(-?\d)", token.strip())
    if not match:
        raise MusicError("Use a note with octave, like A4, C#3 or Bb2")
    pitch = parse_note(match.group(1))
    octave = int(match.group(2))
    midi = 12 * (octave + 1) + pitch
    if not 0 <= midi <= 127:
        raise MusicError("That note is outside the MIDI range (C-1 to G9)")
    return {
        "note": f"{spell(pitch, 'b' in match.group(1))}{octave}",
        "midi": midi,
        "hz": round(440.0 * 2 ** ((midi - 69) / 12), 3),
    }


def tempo_table(bpm: float) -> list[tuple[str, float, float, float]]:
    """(label, straight_ms, dotted_ms, triplet_ms) for delay/LFO sync."""
    if not 20 <= bpm <= 400:
        raise MusicError("BPM must be between 20 and 400")
    beat_ms = 60000.0 / bpm
    return [(label, beat_ms * beats, beat_ms * beats * 1.5, beat_ms * beats * 2 / 3) for label, beats in NOTE_VALUES]


def bar_seconds(bpm: float, beats_per_bar: int = 4) -> float:
    return 60.0 / bpm * beats_per_bar


def bpm_from_taps(intervals_ms: list[float]) -> float:
    if not intervals_ms:
        raise MusicError("Need at least one interval")
    return 60000.0 / (sum(intervals_ms) / len(intervals_ms))


def semitone_ratio(cents: float) -> float:
    return 2 ** (cents / 1200)


def hz_to_nearest_note(hz: float) -> str:
    if hz <= 0:
        raise MusicError("Frequency must be positive")
    midi = round(69 + 12 * math.log2(hz / 440.0))
    cents = round(1200 * math.log2(hz / (440.0 * 2 ** ((midi - 69) / 12))))
    return f"{SHARP[midi % 12]}{midi // 12 - 1} ({cents:+d} cents)"
