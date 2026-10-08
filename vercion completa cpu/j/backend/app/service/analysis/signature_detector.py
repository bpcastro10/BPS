"""Detección programática de presencia de firma (densidad de trazos en la zona de firma)."""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from app.enums import WritingType
from app.service.analysis.ocr_engine import OcrToken
from app.service.analysis.text_utils import normalize
from app.service.analysis.writing_classifier import classify_writing

REGION = (0.50, 0.55, 0.98, 0.86)
_PRINTED_HINTS = ("firma", "autorizad", "signature", "authorized", "gerente", "representante")


@dataclass
class SignatureResult:
    present: bool
    confidence: float
    bbox: list[float]


def detect_signature(image: np.ndarray, tokens: list[OcrToken]) -> SignatureResult:
    h, w = image.shape[:2]
    rx0, ry0, rx1, ry1 = REGION
    xa, ya, xb, yb = int(rx0 * w), int(ry0 * h), int(rx1 * w), int(ry1 * h)
    gray = cv2.cvtColor(image[ya:yb, xa:xb], cv2.COLOR_BGR2GRAY)
    ink = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 15)

    for t in tokens:
        if not (t.cx > rx0 and ry0 < t.cy < ry1):
            continue
        printed = any(hint in normalize(t.text) for hint in _PRINTED_HINTS) or (
            t.confidence >= 0.9 and classify_writing(image, t.bbox, t.confidence) == WritingType.IMPRESO.value)
        if printed:
            x0, y0 = int((t.x0 - rx0) * w) - 3, int((t.y0 - ry0) * h) - 3
            x1, y1 = int((t.x1 - rx0) * w) + 3, int((t.y1 - ry0) * h) + 3
            ink[max(y0, 0):max(y1, 0), max(x0, 0):max(x1, 0)] = 0

    line_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(ink.shape[1] // 6, 15), 1))
    lines = cv2.morphologyEx(ink, cv2.MORPH_OPEN, line_kernel)
    strokes = cv2.morphologyEx(cv2.subtract(ink, lines), cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))

    n, _, stats, _ = cv2.connectedComponentsWithStats(strokes, connectivity=8)
    min_area = max(int(strokes.size * 0.00008), 12)
    components = [s for s in stats[1:] if s[cv2.CC_STAT_AREA] >= min_area]
    ink_ratio = sum(int(s[cv2.CC_STAT_AREA]) for s in components) / max(strokes.size, 1)
    span = 0.0
    if components:
        xs = [s[cv2.CC_STAT_LEFT] for s in components] + [s[cv2.CC_STAT_LEFT] + s[cv2.CC_STAT_WIDTH] for s in components]
        span = (max(xs) - min(xs)) / strokes.shape[1]

    present = ink_ratio > 0.006 and span > 0.12
    confidence = min(1.0, 0.5 + ink_ratio * 25) if present else min(1.0, 0.6 + (0.006 - min(ink_ratio, 0.006)) * 60)
    return SignatureResult(present=present, confidence=round(confidence, 3), bbox=[rx0, ry0, rx1, ry1])
