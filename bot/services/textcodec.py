"""Text transforms and classic ciphers (all pure functions)."""
from __future__ import annotations

import base64
import binascii
import re
import string
import unicodedata

MAX_TEXT = 3000

_MORSE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.", "G": "--.", "H": "....",
    "I": "..", "J": ".---", "K": "-.-", "L": ".-..", "M": "--", "N": "-.", "O": "---", "P": ".--.",
    "Q": "--.-", "R": ".-.", "S": "...", "T": "-", "U": "..-", "V": "...-", "W": ".--", "X": "-..-",
    "Y": "-.--", "Z": "--..", "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-",
    "5": ".....", "6": "-....", "7": "--...", "8": "---..", "9": "----.", ".": ".-.-.-", ",": "--..--",
    "?": "..--..", "'": ".----.", "!": "-.-.--", "/": "-..-.", "(": "-.--.", ")": "-.--.-", "&": ".-...",
    ":": "---...", ";": "-.-.-.", "=": "-...-", "+": ".-.-.", "-": "-....-", "_": "..--.-", '"': ".-..-.",
    "$": "...-..-", "@": ".--.-.",
}
_MORSE_REV = {v: k for k, v in _MORSE.items()}


class CodecError(ValueError):
    pass


def _limit(text: str) -> str:
    if len(text) > MAX_TEXT:
        raise CodecError(f"Please keep text under {MAX_TEXT} characters")
    return text


def morse_encode(text: str) -> str:
    words = []
    for word in _limit(text).upper().split():
        words.append(" ".join(_MORSE[c] for c in word if c in _MORSE))
    out = " / ".join(w for w in words if w)
    if not out:
        raise CodecError("Nothing to encode (letters, digits and basic punctuation only)")
    return out


def morse_decode(code: str) -> str:
    words = re.split(r"\s*(?:/|\|)\s*|\s{3,}", _limit(code).strip())
    decoded = []
    for word in words:
        letters = []
        for symbol in word.split():
            symbol = symbol.replace("−", "-").replace("·", ".").replace("_", "-")
            if symbol not in _MORSE_REV:
                raise CodecError(f"Unknown morse symbol {symbol[:10]!r}")
            letters.append(_MORSE_REV[symbol])
        decoded.append("".join(letters))
    return " ".join(decoded)


def caesar(text: str, shift: int, decode: bool = False) -> str:
    shift = (-shift if decode else shift) % 26
    out = []
    for ch in _limit(text):
        if "a" <= ch <= "z":
            out.append(chr((ord(ch) - 97 + shift) % 26 + 97))
        elif "A" <= ch <= "Z":
            out.append(chr((ord(ch) - 65 + shift) % 26 + 65))
        else:
            out.append(ch)
    return "".join(out)


def rot13(text: str) -> str:
    return caesar(text, 13)


def atbash(text: str) -> str:
    out = []
    for ch in _limit(text):
        if "a" <= ch <= "z":
            out.append(chr(122 - (ord(ch) - 97)))
        elif "A" <= ch <= "Z":
            out.append(chr(90 - (ord(ch) - 65)))
        else:
            out.append(ch)
    return "".join(out)


def vigenere(text: str, key: str, decode: bool = False) -> str:
    key_letters = [ord(c) - 97 for c in key.lower() if "a" <= c <= "z"]
    if not key_letters:
        raise CodecError("The key must contain at least one letter")
    out, i = [], 0
    for ch in _limit(text):
        if ch.isascii() and ch.isalpha():
            base = 97 if ch.islower() else 65
            shift = key_letters[i % len(key_letters)] * (-1 if decode else 1)
            out.append(chr((ord(ch) - base + shift) % 26 + base))
            i += 1
        else:
            out.append(ch)
    return "".join(out)


def b64_encode(text: str) -> str:
    return base64.b64encode(_limit(text).encode("utf-8")).decode("ascii")


def b64_decode(text: str) -> str:
    try:
        raw = base64.b64decode(_limit(text).strip() + "=" * (-len(text.strip()) % 4), validate=True)
        return raw.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise CodecError("That isn't valid base64 text") from None


def to_binary(text: str) -> str:
    return " ".join(f"{b:08b}" for b in _limit(text).encode("utf-8"))


def from_binary(bits: str) -> str:
    compact = re.sub(r"[^01]", "", _limit(bits))
    if not compact or len(compact) % 8:
        raise CodecError("Give binary in groups of 8 bits (e.g. 01001000 01101001)")
    try:
        return bytes(int(compact[i:i + 8], 2) for i in range(0, len(compact), 8)).decode("utf-8")
    except UnicodeDecodeError:
        raise CodecError("Those bits aren't valid UTF-8 text") from None


def to_hex(text: str) -> str:
    return _limit(text).encode("utf-8").hex(" ")


def from_hex(text: str) -> str:
    try:
        return bytes.fromhex(_limit(text)).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        raise CodecError("That isn't valid hex text") from None


# ----------------------------------------------------------------------------- fun transforms
def mock(text: str) -> str:
    out, upper = [], False
    for ch in _limit(text):
        if ch.isalpha():
            out.append(ch.upper() if upper else ch.lower())
            upper = not upper
        else:
            out.append(ch)
    return "".join(out)


def clap(text: str) -> str:
    words = _limit(text).split()
    return " 👏 ".join(words) + " 👏" if words else ""


def spongecase_title(text: str) -> str:
    return string.capwords(_limit(text))


_LEET = str.maketrans({"a": "4", "e": "3", "i": "1", "o": "0", "s": "5", "t": "7", "A": "4", "E": "3", "I": "1", "O": "0", "S": "5", "T": "7"})


def leet(text: str) -> str:
    return _limit(text).translate(_LEET)


_FLIP_SRC = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ?!.,'()[]{}<>_&"
_FLIP_DST = "ɐqɔpǝɟƃɥᴉɾʞlɯuodbɹsʇnʌʍxʎz∀ᗺƆᗡƎℲ⅁HIſʞ⅂WNOԀQᴚS⊥∩ΛMX⅄Z¿¡˙'،)(][}{><‾⅋"
_FLIP = dict(zip(map(ord, _FLIP_SRC), _FLIP_DST))  # zip() tolerates a length mismatch, maketrans would not


def flip_text(text: str) -> str:
    return _limit(text).translate(_FLIP)[::-1]


def reverse(text: str) -> str:
    return _limit(text)[::-1]


def case_convert(text: str, style: str) -> str:
    text = _limit(text)
    words = re.findall(r"[A-Za-z0-9]+", unicodedata.normalize("NFKD", text))
    if style == "upper":
        return text.upper()
    if style == "lower":
        return text.lower()
    if style == "title":
        return string.capwords(text)
    if style == "sentence":
        return text[:1].upper() + text[1:].lower()
    if style == "snake":
        return "_".join(w.lower() for w in words)
    if style == "kebab":
        return "-".join(w.lower() for w in words)
    if style == "camel":
        return "".join(w.lower() if i == 0 else w.capitalize() for i, w in enumerate(words))
    if style == "pascal":
        return "".join(w.capitalize() for w in words)
    if style == "constant":
        return "_".join(w.upper() for w in words)
    raise CodecError("Styles: upper, lower, title, sentence, snake, kebab, camel, pascal, constant")


def slugify(text: str) -> str:
    folded = unicodedata.normalize("NFKD", _limit(text)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")


def is_palindrome(text: str) -> bool:
    cleaned = [c.lower() for c in text if c.isalnum()]
    return bool(cleaned) and cleaned == cleaned[::-1]


def text_stats(text: str) -> dict[str, float | int]:
    text = _limit(text) if len(text) <= 100_000 else text[:100_000]
    words = re.findall(r"\b[\w'’-]+\b", text)
    sentences = [s for s in re.split(r"[.!?]+\s|[.!?]+$", text.strip()) if s.strip()]
    return {
        "characters": len(text),
        "characters_no_spaces": len(re.sub(r"\s", "", text)),
        "words": len(words),
        "sentences": len(sentences),
        "paragraphs": len([p for p in re.split(r"\n\s*\n", text) if p.strip()]),
        "unique_words": len({w.lower() for w in words}),
        "reading_minutes": round(len(words) / 220, 1),
        "speaking_minutes": round(len(words) / 150, 1),
    }
