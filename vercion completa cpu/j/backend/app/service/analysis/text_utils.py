"""Utilidades de texto: normalización, búsqueda tolerante de palabras clave y parseo de montos/fechas."""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from typing import Optional

_ACCENT_CLASS = {
    "a": "[aáàäâã@]",
    "e": "[eéèëê]",
    "i": "[iíìïî1l!|]",
    "o": "[oóòöô0]",
    "u": "[uúùüûv]",
    "n": "[nñ]",
    "s": "[s5$]",
}


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", strip_accents(text or "").lower()).strip()


@lru_cache(maxsize=512)
def anchor_pattern(anchor: str) -> re.Pattern:
    """Patrón tolerante a tildes, espacios perdidos y confusiones típicas de OCR (o/0, i/1...)."""
    parts = []
    for ch in anchor.lower():
        if ch == " ":
            parts.append(r"\s*")
        elif ch == ".":
            parts.append(r"\.?")
        else:
            parts.append(_ACCENT_CLASS.get(ch, re.escape(ch)))
    short = len(anchor) <= 5
    prefix = r"(?<![a-záéíóúñ])" if short else ""
    suffix = r"(?![a-záéíóúñ])" if short else ""
    return re.compile(prefix + "".join(parts) + suffix + r"[\s:.\-_=*]*", re.IGNORECASE)


def find_anchor(text: str, anchors: list[str]) -> Optional[re.Match]:
    for anchor in anchors:
        match = anchor_pattern(anchor).search(text or "")
        if match:
            return match
    return None


_FILLER_RE = re.compile(r"^[\s\-_=*~.:,;#xX]{0,}|[\s\-_=*~.:,;#]+$")
_FILLER_RUNS = re.compile(r"(?:[-_=*~]{2,}|(?<![a-z])x{3,}(?![a-z]))", re.IGNORECASE)


def clean_value(text: str) -> str:
    text = _FILLER_RUNS.sub(" ", text or "")
    text = re.sub(r"^[\s\-_=*~.:,;#]+|[\s\-_=*~.:,;#]+$", "", text)
    return re.sub(r"\s{2,}", " ", text).strip()


_AMOUNT_TOKEN_RE = re.compile(
    r"(?<![\d/])(\d{1,3}(?:[.,' ]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)(?![\d/])"
)


def find_amount(text: str) -> Optional[tuple[str, Decimal]]:
    """Devuelve (texto_encontrado, valor) del monto numérico más plausible dentro del texto."""
    if not text:
        return None
    cleaned = re.sub(r"(?i)us\s*\$|usd|\$|s/\.?|€|\*|#", " ", text)
    cleaned = re.sub(r"(\d)\s*[-=]\s*(?=\d{2}\b)", r"\1.", cleaned)
    cleaned = re.sub(r"(\d)\s*[-=/]+\s*$", r"\1", cleaned.strip())
    whole_with_cents = re.fullmatch(r"\s*(\d{1,3}(?:[.,]\d{3})*|\d+)\s+(\d{2})\s*", cleaned)
    if whole_with_cents:
        cleaned = f"{whole_with_cents.group(1)}.{whole_with_cents.group(2)}"
    best = None
    for match in _AMOUNT_TOKEN_RE.finditer(cleaned):
        value = parse_amount(match.group(1))
        if value is None:
            continue
        if best is None or len(match.group(1)) > len(best[0]):
            best = (match.group(1), value)
    return best


def parse_amount(raw: str) -> Optional[Decimal]:
    s = re.sub(r"[^\d.,' ]", "", raw or "").strip().replace("'", ",")
    s = s.replace(" ", ",") if re.fullmatch(r"\d{1,3}( \d{3})+([.,]\d{1,2})?", s) else s.replace(" ", "")
    if not s or not any(c.isdigit() for c in s):
        return None
    if "," in s and "." in s:
        decimal_sep = "," if s.rfind(",") > s.rfind(".") else "."
        thousands_sep = "." if decimal_sep == "," else ","
        s = s.replace(thousands_sep, "").replace(decimal_sep, ".")
    elif "," in s or "." in s:
        sep = "," if "," in s else "."
        parts = s.split(sep)
        if len(parts[-1]) in (1, 2) and len(parts) >= 2:
            s = "".join(parts[:-1]) + "." + parts[-1]
        else:
            s = "".join(parts)
    try:
        return Decimal(s).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def format_amount(value: Optional[Decimal]) -> str:
    return f"{value:,.2f}" if value is not None else ""


MONTHS = {
    "enero": 1, "ene": 1, "january": 1, "jan": 1,
    "febrero": 2, "feb": 2, "february": 2,
    "marzo": 3, "mar": 3, "march": 3,
    "abril": 4, "abr": 4, "april": 4, "apr": 4,
    "mayo": 5, "may": 5,
    "junio": 6, "jun": 6, "june": 6,
    "julio": 7, "jul": 7, "july": 7,
    "agosto": 8, "ago": 8, "august": 8, "aug": 8,
    "septiembre": 9, "setiembre": 9, "sep": 9, "sept": 9, "set": 9, "september": 9,
    "octubre": 10, "oct": 10, "october": 10,
    "noviembre": 11, "nov": 11, "november": 11,
    "diciembre": 12, "dic": 12, "december": 12, "dec": 12,
}
_MONTH_ALT = "|".join(sorted(MONTHS, key=len, reverse=True))

DATE_PATTERNS = [
    ("dmy_text", re.compile(rf"(\d{{1,2}})\s*(?:de\s*)?({_MONTH_ALT})[a-z]*\.?\s*(?:de(?:l)?\s*)?,?\s*(\d{{4}}|\d{{2}})\b", re.I)),
    ("mdy_text", re.compile(rf"\b({_MONTH_ALT})[a-z]*\.?\s*(\d{{1,2}})\s*,?\s*(\d{{4}})\b", re.I)),
    ("ymd", re.compile(r"\b(\d{4})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{1,2})\b")),
    ("dmy", re.compile(r"\b(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{4}|\d{2})\b")),
    ("boxes", re.compile(r"\b(\d{2})\s+(\d{2})\s+(\d{4})\b")),
    ("compact", re.compile(r"\b(\d{2})(\d{2})(20\d{2})\b")),
]


def _year(value: str) -> int:
    year = int(value)
    return 2000 + year if year < 100 else year


def _month(word: str) -> Optional[int]:
    word = normalize(word)
    for name in sorted(MONTHS, key=len, reverse=True):
        if word.startswith(name):
            return MONTHS[name]
    return None


def find_date(text: str) -> Optional[tuple[re.Match, date, str]]:
    """Busca una fecha válida. Devuelve (match, fecha, tipo_de_patrón)."""
    norm = strip_accents(text or "")
    for kind, pattern in DATE_PATTERNS:
        for match in pattern.finditer(norm):
            try:
                if kind == "dmy_text":
                    d, m, y = int(match.group(1)), _month(match.group(2)), _year(match.group(3))
                elif kind == "mdy_text":
                    m, d, y = _month(match.group(1)), int(match.group(2)), _year(match.group(3))
                elif kind == "ymd":
                    y, m, d = int(match.group(1)), int(match.group(2)), int(match.group(3))
                else:
                    d, m, y = int(match.group(1)), int(match.group(2)), _year(match.group(3))
                    if m > 12 >= d:
                        d, m = m, d
                if m is None or not (1990 <= y <= 2100):
                    continue
                return match, date(y, m, d), kind
            except ValueError:
                continue
    return None


def aba_checksum_ok(digits: str) -> bool:
    if not re.fullmatch(r"\d{9}", digits or ""):
        return False
    d = [int(c) for c in digits]
    return (3 * (d[0] + d[3] + d[6]) + 7 * (d[1] + d[4] + d[7]) + (d[2] + d[5] + d[8])) % 10 == 0
