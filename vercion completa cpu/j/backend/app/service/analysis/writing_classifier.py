"""Estimación programática de si un campo fue escrito a mano o impreso (computadora/máquina)."""
from __future__ import annotations

from typing import Optional

import cv2
import numpy as np

from app.enums import WritingType
from app.service.analysis.image_loader import crop_norm


def classify_writing(image: np.ndarray, bbox: Optional[list[float]], ocr_conf: float) -> Optional[str]:
    if not bbox:
        return None
    crop = crop_norm(image, bbox, pad=0.0)
    if crop.size == 0 or crop.shape[0] < 8 or crop.shape[1] < 8:
        return None

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    ink_px = ink > 0
    if ink_px.sum() < 20:
        return None

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hue, sat = hsv[..., 0][ink_px], hsv[..., 1][ink_px]
    pen_ratio = float(((sat > 70) & (hue >= 95) & (hue <= 135)).mean())

    n, _, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    heights = np.array([s[cv2.CC_STAT_HEIGHT] for s in stats[1:] if s[cv2.CC_STAT_AREA] > 6], dtype=float)
    height_cv = float(heights.std() / heights.mean()) if len(heights) >= 3 else 0.0

    dist = cv2.distanceTransform(ink, cv2.DIST_L2, 3)[ink_px]
    stroke_cv = float(dist.std() / dist.mean()) if dist.mean() > 0 else 0.0

    if pen_ratio > 0.30:
        return WritingType.MANUSCRITO.value
    score = 0.0
    score += 0.25 if height_cv > 0.45 else 0.0
    score += 0.15 if stroke_cv > 0.75 else 0.0
    score += 0.25 if ocr_conf < 0.85 else (-0.25 if ocr_conf > 0.97 else 0.0)
    return WritingType.MANUSCRITO.value if score >= 0.4 else WritingType.IMPRESO.value
