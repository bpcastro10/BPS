"""Lectura de la banda MICR (E-13B / CMC-7) ubicada en la parte inferior del cheque."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

from app.service.analysis.ocr_engine import OcrEngine, OcrToken, mean_conf
from app.service.analysis.text_utils import aba_checksum_ok

BAND_TOP = 0.78


@dataclass
class MicrResult:
    raw: str = ""
    groups: list[str] = field(default_factory=list)
    confidence: float = 0.0
    bbox: Optional[list[float]] = None
    routing: Optional[str] = None
    account: Optional[str] = None
    serial_candidates: list[str] = field(default_factory=list)


def _digit_ratio(text: str) -> float:
    compact = text.replace(" ", "")
    return sum(c.isdigit() for c in compact) / max(len(compact), 1)


def read_micr(image: np.ndarray, ocr: OcrEngine, full_tokens: list[OcrToken]) -> MicrResult:
    fallback = [t for t in full_tokens if t.cy > BAND_TOP and _digit_ratio(t.text) >= 0.6]
    digits_found = sum(c.isdigit() for t in fallback for c in t.text)
    if fallback and digits_found >= 12 and mean_conf(fallback) >= 0.9:
        tokens = fallback
    else:
        tokens = _read_band(image, ocr)
        if sum(len(t.text) for t in tokens) < sum(len(t.text) for t in fallback):
            tokens = fallback
    if not tokens:
        return MicrResult()

    lowest = max(t.cy for t in tokens)
    tokens = sorted([t for t in tokens if abs(t.cy - lowest) < 0.06], key=lambda t: t.x0)
    raw = " ".join(t.text for t in tokens)
    groups = re.findall(r"\d{3,}", raw)
    result = MicrResult(
        raw=re.sub(r"\s{2,}", " ", raw).strip(),
        groups=groups,
        confidence=mean_conf(tokens),
        bbox=[min(t.x0 for t in tokens), min(t.y0 for t in tokens), max(t.x1 for t in tokens), max(t.y1 for t in tokens)],
    )
    _assign_groups(result)
    return result


def _read_band(image: np.ndarray, ocr: OcrEngine) -> list[OcrToken]:
    """Relee solo la banda inferior con contraste mejorado (más preciso para la tipografía magnética)."""
    h = image.shape[0]
    band = image[int(h * BAND_TOP):, :]
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(cv2.cvtColor(band, cv2.COLOR_BGR2GRAY))
    tokens = [t for t in ocr.read(cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)) if _digit_ratio(t.text) >= 0.55]
    band_h = 1 - BAND_TOP
    for t in tokens:
        t.y0, t.y1 = BAND_TOP + t.y0 * band_h, BAND_TOP + t.y1 * band_h
    return tokens


def _assign_groups(result: MicrResult) -> None:
    remaining = list(result.groups)
    for g in remaining:
        if aba_checksum_ok(g):
            result.routing = g
            remaining.remove(g)
            break
    if remaining:
        longest = max(remaining, key=len)
        if len(longest) >= 6:
            result.account = longest
            remaining.remove(longest)
    result.serial_candidates = [g for g in remaining if 3 <= len(g) <= 10]
