"""Extracción programática de campos usando etiquetas impresas del cheque + posición espacial + validaciones."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, Optional

from app.enums import FieldKey, FieldSource
from app.model import ExtractedField
from app.service.analysis.amount_words import (
    WordsAmount,
    canonical_amount_words,
    number_word_score,
    parse_amount_words,
)
from app.service.analysis.micr_reader import BAND_TOP
from app.service.analysis.ocr_engine import Layout, OcrToken, mean_conf, union_bbox
from app.service.analysis.text_utils import clean_value, find_amount, find_anchor, find_date, normalize

PAYEE_ANCHORS = [
    "paguese a la orden de", "pagase a la orden de", "paguese a la orden", "paguese por este cheque a",
    "pay to the order of", "a la orden de", "paguese a", "pay to the", "pay to", "orden de", "paguese",
    "beneficiario",
]
AMOUNT_WORDS_ANCHORS = ["la cantidad de", "la suma de", "the sum of", "cantidad de", "suma de", "son:"]
CHECK_NO_ANCHORS = ["cheque no", "cheque nro", "cheque n°", "cheque nº", "cheque #", "check no", "check #",
                    "cheque", "nro.", "no.", "n°", "nº", "serie", "#"]
ACCOUNT_ANCHORS = ["cuenta corriente no", "cuenta corriente", "cta. cte. no", "cta. cte.", "cta cte", "cuenta no",
                   "cuenta", "cta.", "account no", "account", "acct"]
CONCEPT_ANCHORS = ["por concepto de", "concepto", "memo", "referencia", "detalle"]
DATE_ANCHORS = ["lugar y fecha", "fecha", "date"]
BANK_KEYWORDS = ["banco", "bank", "cooperativa", "caja ", "mutualista", "financiera", "credit union", "pichincha",
                 "produbanco", "pacifico", "bolivariano", "bancolombia", "davivienda", "bbva", "santander",
                 "citibank", "scotiabank", "banorte", "banamex", "itau", "chase", "wells fargo", "procredit"]
CURRENCY_WORDS = ["dolares", "dollars", "pesos", "soles", "euros", "bolivares", "quetzales", "colones"]
_CURRENCY_SYMBOL = re.compile(r"(?i)^\s*(us\s*\$|usd|\$|s/\.?|€|mx\$|col\$)\s*$")
_ALL_LABELS = PAYEE_ANCHORS + AMOUNT_WORDS_ANCHORS + CONCEPT_ANCHORS + ["firma", "autorizada"]


@dataclass
class Hit:
    text: str
    tokens: list[OcrToken]
    anchor: Optional[OcrToken] = None

    @property
    def confidence(self) -> float:
        return mean_conf(self.tokens)

    @property
    def bbox(self) -> Optional[list[float]]:
        return union_bbox(self.tokens)


@dataclass
class ExtractionResult:
    fields: dict[str, ExtractedField] = field(default_factory=dict)
    words_amount: Optional[WordsAmount] = None
    amount_candidates: list[tuple[float, OcrToken, Decimal]] = field(default_factory=list)


def _field(hit: Optional[Hit], value: Optional[str] = None, source: FieldSource = FieldSource.OCR) -> ExtractedField:
    if hit is None:
        return ExtractedField()
    return ExtractedField(value=value if value is not None else hit.text, confidence=round(hit.confidence, 3),
                          bbox=hit.bbox, source=source.value)


def _starts_with_label(token: OcrToken) -> bool:
    m = find_anchor(token.text, _ALL_LABELS)
    return bool(m and m.start() <= 2)


def _is_currency_or_amount(token: OcrToken) -> bool:
    if _CURRENCY_SYMBOL.match(token.text):
        return True
    compact = re.sub(r"\s", "", token.text)
    digits = sum(c.isdigit() for c in compact)
    return digits >= 1 and digits / max(len(compact), 1) > 0.6


def value_after_anchor(layout: Layout, anchors: list[str], stop: Callable[[OcrToken], bool] = lambda t: False,
                       allow_below: bool = True, max_dx: float = 0.75,
                       skip: Callable[[OcrToken], bool] = lambda t: False,
                       accept: Callable[[str], bool] = lambda text: True) -> Optional[Hit]:
    for tok in layout.tokens:
        if tok.cy > BAND_TOP or skip(tok):
            continue
        match = find_anchor(tok.text, anchors)
        if not match:
            continue
        parts: list[OcrToken] = []
        rest = tok.text[match.end():]
        if clean_value(rest):
            frac = match.end() / max(len(tok.text), 1)
            parts.append(OcrToken(rest.strip(), tok.confidence, tok.x0 + frac * tok.w, tok.y0, tok.x1, tok.y1, idx=tok.idx))
        prev_x1 = parts[-1].x1 if parts else tok.x1
        for t in layout.same_row_right(tok, max_dx):
            if stop(t) or _starts_with_label(t) or t.x0 - prev_x1 > 0.18:
                break
            parts.append(t)
            prev_x1 = t.x1
        if not any(clean_value(p.text) for p in parts) and allow_below:
            parts = []
            for t in layout.below(tok):
                if stop(t) or _starts_with_label(t):
                    break
                parts.append(t)
        text = clean_value(" ".join(p.text for p in parts))
        if text and accept(text):
            return Hit(text=text, tokens=parts, anchor=tok)
    return None


def _row_text(row: list[OcrToken]) -> tuple[str, list[tuple[int, int, OcrToken]]]:
    pieces, spans, pos = [], [], 0
    for t in row:
        txt = unicodedata.normalize("NFC", t.text)
        spans.append((pos, pos + len(txt), t))
        pieces.append(txt)
        pos += len(txt) + 2
    return "  ".join(pieces), spans


class FieldExtractor:
    def extract(self, layout: Layout) -> ExtractionResult:
        result = ExtractionResult()
        f = result.fields
        f[FieldKey.BENEFICIARIO.value] = self._payee(layout)
        words_field, result.words_amount = self._amount_words(layout)
        f[FieldKey.MONTO_LETRAS.value] = words_field
        words_value = result.words_amount.value if result.words_amount else None
        f[FieldKey.MONTO.value], result.amount_candidates = self._amount(layout, words_value)
        date_field, city_field = self._date_and_city(layout)
        f[FieldKey.FECHA.value] = date_field
        f[FieldKey.CIUDAD.value] = city_field
        f[FieldKey.NUMERO_CHEQUE.value] = self._check_number(layout)
        f[FieldKey.CUENTA.value] = self._account(layout)
        f[FieldKey.BANCO.value] = self._bank(layout)
        f[FieldKey.CONCEPTO.value] = _field(value_after_anchor(layout, CONCEPT_ANCHORS, allow_below=False))
        f[FieldKey.MONEDA.value] = self._currency(layout, result.words_amount)
        return result

    # ---------------- Beneficiario ----------------
    def _payee(self, layout: Layout) -> ExtractedField:
        hit = value_after_anchor(layout, PAYEE_ANCHORS, stop=_is_currency_or_amount)
        if hit is None:
            return ExtractedField()
        text = re.sub(r"(?i)\s*(us\s*\$|usd|\$)\s*[\d.,*\s]*$", "", hit.text)
        text = clean_value(re.sub(r"\s*[\d.,]{4,}\s*$", "", text))
        return _field(hit, value=text or None)

    # ---------------- Monto en letras ----------------
    def _amount_words(self, layout: Layout) -> tuple[ExtractedField, Optional[WordsAmount]]:
        hit = value_after_anchor(layout, AMOUNT_WORDS_ANCHORS, stop=lambda t: _CURRENCY_SYMBOL.match(t.text) is not None)
        if hit is not None and not any(c in normalize(hit.text) for c in CURRENCY_WORDS):
            last = max(hit.tokens, key=lambda t: t.cy)
            continuation = [t for t in layout.below(last, 2.0) if t.cy < BAND_TOP]
            cont_text = " ".join(t.text for t in continuation)
            if continuation and number_word_score(cont_text) >= 0.4:
                hit = Hit(text=f"{hit.text} {clean_value(cont_text)}", tokens=hit.tokens + continuation, anchor=hit.anchor)
        if hit is None or parse_amount_words(hit.text) is None:
            best_row, best_score = None, 0.0
            for row in layout.rows:
                if min(t.cy for t in row) > BAND_TOP:
                    continue
                text = " ".join(t.text for t in row)
                score = number_word_score(text)
                if score > best_score and len(text.split()) >= 2:
                    best_row, best_score = row, score
            if best_row and best_score >= 0.5:
                hit = Hit(text=clean_value(" ".join(t.text for t in best_row)), tokens=best_row)
        if hit is None:
            return ExtractedField(), None
        text = clean_value(re.sub(r"(?i)^\s*(la\s*suma\s*de|la\s*cantidad\s*de|the\s*sum\s*of)\s*", "", hit.text))
        return _field(hit, value=canonical_amount_words(text)), parse_amount_words(text)

    # ---------------- Monto numérico ----------------
    def _amount(self, layout: Layout, words_value: Optional[Decimal]):
        symbols = [t for t in layout.tokens if _CURRENCY_SYMBOL.match(t.text)]
        candidates: list[tuple[float, OcrToken, Decimal]] = []
        for t in layout.tokens:
            if t.cy > BAND_TOP or find_date(t.text):
                continue
            found = find_amount(t.text)
            if not found:
                continue
            raw, value = found
            digits = re.sub(r"\D", "", raw)
            if value <= 0 or len(digits) > 11:
                continue
            has_symbol = bool(re.search(r"(?i)us\s*\$|\$|usd|€", t.text))
            letters = sum(c.isalpha() for c in re.sub(r"(?i)us|usd", "", t.text))
            if letters > 2 and not has_symbol:
                continue
            near_symbol = any(abs(s.cy - t.cy) < max(s.h, t.h) and -0.01 <= t.x0 - s.x1 < 0.15 for s in symbols)
            has_decimals = bool(re.search(r"[.,]\d{2}$", raw))
            score = 0.3
            score += 0.35 if (has_symbol or near_symbol) else 0.0
            score += 0.15 if (has_decimals or "*" in t.text) else 0.0
            score += 0.15 if t.cx > 0.55 else 0.0
            score += 0.05 if t.cy < 0.6 else 0.0
            score -= 0.45 if (len(digits) >= 7 and not has_decimals and not has_symbol) else 0.0
            score += 0.5 if (words_value is not None and value == words_value) else 0.0
            candidates.append((score, t, value))
        candidates.sort(key=lambda c: c[0], reverse=True)
        if not candidates or candidates[0][0] < 0.45:
            return ExtractedField(), candidates
        _, tok, value = candidates[0]
        return ExtractedField(value=str(value), confidence=round(tok.confidence, 3), bbox=tok.bbox,
                              source=FieldSource.OCR.value), candidates

    # ---------------- Fecha y ciudad ----------------
    def _date_and_city(self, layout: Layout) -> tuple[ExtractedField, ExtractedField]:
        best = None
        for row in layout.rows:
            if min(t.cy for t in row) > BAND_TOP - 0.02:
                continue
            text, spans = _row_text(row)
            found = find_date(text)
            if not found:
                continue
            match, value, kind = found
            score = 1.0 + (0.4 if kind.endswith("text") else 0.0) + (0.3 if find_anchor(text, DATE_ANCHORS) else 0.0)
            score += 0.2 if min(t.cy for t in row) < 0.45 else 0.0
            if best is None or score > best[0]:
                best = (score, match, value, spans)
        if best is None:
            return ExtractedField(), ExtractedField()

        _, match, value, spans = best
        tokens = [t for s, e, t in spans if s < match.end() and e > match.start()]
        date_field = ExtractedField(value=value.isoformat(), confidence=round(mean_conf(tokens), 3),
                                    bbox=union_bbox(tokens), source=FieldSource.OCR.value)

        city_field = ExtractedField()
        first_start, _, first_tok = next((s, e, t) for s, e, t in spans if e > match.start())
        prefix = first_tok.text[: max(match.start() - first_start, 0)]
        city_tok = first_tok
        if not re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{3,}", prefix):
            left = [t for s, e, t in spans if e <= match.start() and first_tok.x0 - t.x1 < 0.06]
            city_tok = left[-1] if left else None
            prefix = city_tok.text if city_tok else ""
        prefix = re.sub(r"(?i)lugar\s*y\s*fecha|fecha|date|:", " ", prefix)
        city = clean_value(prefix.split(",")[0])
        city = re.sub(r"(?<=[A-Za-záéíóúñ])0|0(?=[a-záéíóúñ])", "o", city)
        city = re.sub(r"(?<=[A-Za-záéíóúñ])1|1(?=[a-záéíóúñ])", "l", city)
        if city_tok and 3 <= len(city) <= 30 and re.fullmatch(r"[A-Za-zÁÉÍÓÚÑáéíóúñ .\-]+", city):
            city_field = ExtractedField(value=city.title(), confidence=round(city_tok.confidence, 3),
                                        bbox=city_tok.bbox, source=FieldSource.OCR.value)
        return date_field, city_field

    # ---------------- Número de cheque ----------------
    def _check_number(self, layout: Layout) -> ExtractedField:
        def skip(tok: OcrToken) -> bool:
            return bool(re.search(r"cuenta|cta|account|acct|ruc|telf|tel\.", normalize(tok.text)))

        def is_number(text: str) -> bool:
            return bool(re.match(r"\s*\d[\d\s\-]{2,14}\d", text)) and not re.search(r"[.,]\d{2}\b", text)

        hit = value_after_anchor(layout, CHECK_NO_ANCHORS, allow_below=False, max_dx=0.25, skip=skip, accept=is_number)
        if hit:
            m = re.search(r"\d[\d\s\-]{2,14}\d", hit.text)
            return _field(hit, value=re.sub(r"[\s\-]", "", m.group()))
        top_right = [t for t in layout.in_region(0.55, 0.0, 1.0, 0.32) if re.fullmatch(r"(?i)(n[o°º]\.?|#)?\s*\d{3,10}", t.text.strip())]
        if top_right:
            tok = min(top_right, key=lambda t: t.cy)
            return ExtractedField(value=re.sub(r"\D", "", tok.text), confidence=round(tok.confidence * 0.9, 3),
                                  bbox=tok.bbox, source=FieldSource.OCR.value)
        return ExtractedField()

    # ---------------- Cuenta ----------------
    def _account(self, layout: Layout) -> ExtractedField:
        hit = value_after_anchor(layout, ACCOUNT_ANCHORS, allow_below=False, max_dx=0.3,
                                 accept=lambda text: re.search(r"\d[\d\- ]{4,20}\d", text) is not None)
        if hit:
            m = re.search(r"\d[\d\- ]{4,20}\d", hit.text)
            return _field(hit, value=m.group().replace(" ", ""))
        return ExtractedField()

    # ---------------- Banco ----------------
    def _bank(self, layout: Layout) -> ExtractedField:
        cands = [t for t in layout.tokens if t.cy < 0.45 and any(k in f" {normalize(t.text)} " for k in BANK_KEYWORDS)]
        if cands:
            tok = max(cands, key=lambda t: (t.h, -t.cy))
            neighbors = [t for t in layout.same_row_right(tok, 0.03) if not _is_currency_or_amount(t)][:2]
            tokens = [tok] + neighbors
            name = clean_value(" ".join(t.text for t in tokens))
            return ExtractedField(value=name, confidence=round(mean_conf(tokens), 3), bbox=union_bbox(tokens),
                                  source=FieldSource.OCR.value)
        top = [t for t in layout.in_region(0.0, 0.0, 0.6, 0.3)
               if sum(c.isalpha() for c in t.text) >= 4 and not find_anchor(t.text, _ALL_LABELS + DATE_ANCHORS)
               and not find_date(t.text)]
        if top:
            tok = max(top, key=lambda t: t.h)
            return ExtractedField(value=clean_value(tok.text), confidence=round(tok.confidence * 0.7, 3),
                                  bbox=tok.bbox, source=FieldSource.OCR.value)
        return ExtractedField()

    # ---------------- Moneda ----------------
    @staticmethod
    def _currency(layout: Layout, words: Optional[WordsAmount]) -> ExtractedField:
        text = normalize(layout.full_text())
        if (words and words.currency_word in ("dolares", "dolar", "dollars", "dollar", "usd")) or re.search(r"us\s*\$|usd|dolar|dollar", text):
            value = "USD"
        elif "€" in text or "euro" in text:
            value = "EUR"
        elif "pesos" in text:
            value = "PESOS"
        elif "soles" in text or "s/." in text:
            value = "PEN"
        elif "$" in text:
            value = "USD"
        else:
            return ExtractedField()
        return ExtractedField(value=value, confidence=0.9, source=FieldSource.CALCULADO.value)
