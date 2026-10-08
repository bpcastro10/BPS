"""Convierte montos escritos en letras (español / inglés) a número, tolerando errores de OCR."""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from app.service.analysis.text_utils import normalize

_UNITS = {
    "cero": 0, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
    "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14,
    "quince": 15, "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20,
    "veintiun": 21, "veintiuno": 21, "veintiuna": 21, "veintidos": 22, "veintitres": 23, "veinticuatro": 24,
    "veinticinco": 25, "veintiseis": 26, "veintisiete": 27, "veintiocho": 28, "veintinueve": 29,
    "treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "setenta": 70, "ochenta": 80, "noventa": 90,
    "cien": 100, "ciento": 100, "doscientos": 200, "doscientas": 200, "trescientos": 300, "trescientas": 300,
    "cuatrocientos": 400, "cuatrocientas": 400, "quinientos": 500, "quinientas": 500, "seiscientos": 600,
    "seiscientas": 600, "setecientos": 700, "setecientas": 700, "ochocientos": 800, "ochocientas": 800,
    "novecientos": 900, "novecientas": 900,
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_MULTIPLIERS = {"mil": 1_000, "thousand": 1_000, "millon": 1_000_000, "millones": 1_000_000, "million": 1_000_000}
_HUNDRED = {"hundred"}
_CONNECTORS = {"y", "and", "de", "del", "la", "suma", "cantidad", "the", "sum", "of", "only", "solo", "son"}
_CURRENCY = {"dolares", "dolar", "dollars", "dollar", "pesos", "peso", "soles", "euros", "usd", "us", "bolivares",
             "quetzales", "colones", "lempiras", "cordobas", "guaranies", "reales"}
_CENTS_WORDS = {"centavos", "centavo", "cents", "cent", "ctvs", "ctv", "cvs"}
_CENT_SEPARATORS = {"con", "and", "with"}

_FRACTION_RE = re.compile(r"(?<![a-z])([0-9o]{1,2})\s*/\s*[1l][0o]{2}", re.IGNORECASE)

_VOCAB = list(_UNITS) + list(_MULTIPLIERS) + list(_HUNDRED) + list(_CENTS_WORDS) + list(_CURRENCY) + ["con"]


@dataclass
class WordsAmount:
    value: Decimal
    recognized_ratio: float
    currency_word: Optional[str]


def _fix_word(word: str) -> Optional[str]:
    if word in _UNITS or word in _MULTIPLIERS or word in _HUNDRED or word in _CENTS_WORDS or word in _CURRENCY:
        return word
    if word in _CONNECTORS or word in _CENT_SEPARATORS:
        return word
    if len(word) < 3:
        return None
    match = difflib.get_close_matches(word, _VOCAB, n=1, cutoff=0.78)
    return match[0] if match else None


def _split_glued(word: str) -> list[str]:
    """Separa palabras pegadas por el OCR, p.ej. 'milquinientos' -> ['mil', 'quinientos']."""
    if word in _UNITS or word in _MULTIPLIERS or len(word) < 6:
        return [word]
    candidates = sorted(set(_UNITS) | set(_MULTIPLIERS) | {"y", "con"}, key=len, reverse=True)
    result, rest = [], word
    while rest:
        for cand in candidates:
            if rest.startswith(cand) and (len(cand) > 1 or cand in ("y",)):
                result.append(cand)
                rest = rest[len(cand):]
                break
        else:
            return [word]
    return result


def _words_to_int(words: list[str]) -> Optional[int]:
    total, current, seen = 0, 0, False
    for w in words:
        if w in _UNITS:
            current += _UNITS[w]
            seen = True
        elif w in _HUNDRED:
            current = max(current, 1) * 100
            seen = True
        elif w in ("mil", "thousand"):
            total += max(current, 1) * 1_000
            current = 0
            seen = True
        elif w in ("millon", "millones", "million"):
            total = (total + max(current, 1)) * 1_000_000
            current = 0
            seen = True
    return total + current if seen else None


def parse_amount_words(text: str) -> Optional[WordsAmount]:
    if not text:
        return None
    norm = normalize(text)
    cents = None
    frac = _FRACTION_RE.search(norm)
    if frac:
        cents = int(frac.group(1).replace("o", "0"))
        norm = norm[: frac.start()] + " " + norm[frac.end():]
    norm = re.sub(r"[^a-z\s]", " ", norm)

    raw_words = [w for w in norm.split() if w]
    words: list[str] = []
    recognized = 0
    for raw in raw_words:
        for piece in _split_glued(raw):
            fixed = _fix_word(piece)
            if fixed:
                words.append(fixed)
                recognized += 1
    if not words:
        return None

    currency = next((w for w in words if w in _CURRENCY), None)
    integer_words, cents_words = words, []
    has_cents_word = any(w in _CENTS_WORDS for w in words)
    if cents is None and has_cents_word:
        for idx, w in enumerate(words):
            if w in _CENT_SEPARATORS or w in _CURRENCY:
                tail = words[idx + 1:]
                if any(t in _UNITS for t in tail):
                    integer_words, cents_words = words[:idx], tail
                    break
    integer = _words_to_int([w for w in integer_words if w not in _CENTS_WORDS])
    if integer is None:
        return None
    if cents is None and cents_words:
        cents = _words_to_int(cents_words) or 0
    cents = cents if cents is not None and cents < 100 else 0
    value = (Decimal(integer) + Decimal(cents) / Decimal(100)).quantize(Decimal("0.01"))
    ratio = recognized / max(len(raw_words), 1)
    return WordsAmount(value=value, recognized_ratio=min(ratio, 1.0), currency_word=currency)


_CANONICAL = {"dieciseis": "dieciséis", "veintidos": "veintidós", "veintitres": "veintitrés",
              "veintiseis": "veintiséis", "millon": "millón", "dolares": "dólares", "dolar": "dólar"}


def canonical_amount_words(text: str) -> str:
    """Corrige la ortografía de las palabras numéricas leídas por OCR (p.ej. 'Míl cíncuenta' -> 'Mil cincuenta')."""
    def fix(match: re.Match) -> str:
        word = match.group(0)
        norm = normalize(word)
        if norm not in _UNITS and norm not in _MULTIPLIERS and norm not in _CANONICAL:
            return word
        fixed = _CANONICAL.get(norm, norm)
        if word.isupper():
            return fixed.upper()
        return fixed.capitalize() if word[0].isupper() else fixed

    text = _FRACTION_RE.sub(lambda m: m.group(1).replace("o", "0").replace("O", "0") + "/100", text or "")
    return re.sub(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", fix, text)


def number_word_score(text: str) -> float:
    """Proporción de palabras de la línea que son palabras numéricas (para localizar el monto en letras)."""
    words = [w for w in re.sub(r"[^a-z\s]", " ", normalize(text)).split() if len(w) > 1]
    if not words:
        return 0.0
    hits = sum(1 for w in words if (_fix_word(w) or "") in _UNITS or (_fix_word(w) or "") in _MULTIPLIERS)
    return hits / len(words)
