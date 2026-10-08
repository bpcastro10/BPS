"""Motor OCR local (RapidOCR / PP-OCR sobre ONNX Runtime) y utilidades de disposición espacial."""
from __future__ import annotations

import logging
import math
import threading
from dataclasses import dataclass
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class OcrToken:
    """Texto detectado con su caja en coordenadas normalizadas (0..1) respecto a la imagen."""

    text: str
    confidence: float
    x0: float
    y0: float
    x1: float
    y1: float
    angle: float = 0.0
    idx: int = -1

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def h(self) -> float:
        return self.y1 - self.y0

    @property
    def w(self) -> float:
        return self.x1 - self.x0

    @property
    def bbox(self) -> list[float]:
        return [round(self.x0, 4), round(self.y0, 4), round(self.x1, 4), round(self.y1, 4)]


class OcrEngine:
    """Envuelve RapidOCR. Usa PP-OCRv5 con reconocedor latino (tildes, ñ) y, si no existe, la API 1.x."""

    def __init__(self):
        self._engine = None
        self._api = None
        self._lock = threading.Lock()

    def warmup(self) -> None:
        self._ensure_loaded()

    def _ensure_loaded(self) -> None:
        if self._engine is not None:
            return
        with self._lock:
            if self._engine is not None:
                return
            logging.getLogger("RapidOCR").setLevel(logging.WARNING)
            try:
                from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

                self._engine = RapidOCR(params={
                    "Det.ocr_version": OCRVersion.PPOCRV5, "Det.model_type": ModelType.MOBILE,
                    "Rec.ocr_version": OCRVersion.PPOCRV5, "Rec.model_type": ModelType.MOBILE,
                    "Rec.lang_type": LangRec.LATIN, "Global.log_level": "warning", "Global.text_score": 0.3,
                })
                self._api = "v3"
            except ImportError:
                from rapidocr_onnxruntime import RapidOCR

                self._engine, self._api = RapidOCR(), "v1"
            logging.getLogger("RapidOCR").setLevel(logging.WARNING)
            log.info("Motor OCR cargado (RapidOCR %s)", "PP-OCRv5 latino" if self._api == "v3" else "1.x")

    def read(self, image: np.ndarray) -> list[OcrToken]:
        self._ensure_loaded()
        h, w = image.shape[:2]
        raw = self._run(image)
        tokens = []
        for box, text, score in raw:
            text = (text or "").strip()
            if not text:
                continue
            pts = np.asarray(box, dtype=np.float32).reshape(-1, 2)
            (tlx, tly), (trx, try_) = pts[0], pts[1]
            angle = math.degrees(math.atan2(try_ - tly, trx - tlx)) if trx != tlx else 0.0
            tokens.append(
                OcrToken(
                    text=text,
                    confidence=float(score),
                    x0=float(pts[:, 0].min()) / w,
                    y0=float(pts[:, 1].min()) / h,
                    x1=float(pts[:, 0].max()) / w,
                    y1=float(pts[:, 1].max()) / h,
                    angle=angle,
                )
            )
        tokens.sort(key=lambda t: (round(t.cy, 2), t.x0))
        for i, t in enumerate(tokens):
            t.idx = i
        return tokens

    def _run(self, image: np.ndarray) -> list:
        if self._api == "v1":
            result, _ = self._engine(image)
            return result or []
        out = self._engine(image)
        if out is None or out.txts is None:
            return []
        return list(zip(out.boxes, out.txts, out.scores))


def estimate_skew(tokens: list[OcrToken]) -> float:
    angles = [t.angle for t in tokens if t.w > 0.08 and abs(t.angle) < 15]
    return float(np.median(angles)) if len(angles) >= 3 else 0.0


class Layout:
    """Consultas espaciales sobre los tokens OCR (misma fila, debajo, regiones)."""

    def __init__(self, tokens: list[OcrToken]):
        self.tokens = tokens
        self.rows = self._group_rows(tokens)

    @staticmethod
    def _group_rows(tokens: list[OcrToken]) -> list[list[OcrToken]]:
        rows: list[list[OcrToken]] = []
        for tok in sorted(tokens, key=lambda t: t.cy):
            for row in rows:
                ref_y0 = min(t.y0 for t in row)
                ref_y1 = max(t.y1 for t in row)
                overlap = min(ref_y1, tok.y1) - max(ref_y0, tok.y0)
                if overlap > 0.5 * min(tok.h, ref_y1 - ref_y0):
                    row.append(tok)
                    break
            else:
                rows.append([tok])
        for row in rows:
            row.sort(key=lambda t: t.x0)
        rows.sort(key=lambda r: min(t.cy for t in r))
        return rows

    def same_row_right(self, anchor: OcrToken, max_dx: float = 1.0) -> list[OcrToken]:
        tol = max(anchor.h, 0.02) * 0.9
        result = [
            t for t in self.tokens
            if t.idx != anchor.idx and t.x0 >= anchor.x1 - 0.01 and t.x0 - anchor.x1 <= max_dx and abs(t.cy - anchor.cy) <= tol
        ]
        return sorted(result, key=lambda t: t.x0)

    def below(self, anchor: OcrToken, max_dy_factor: float = 2.8) -> list[OcrToken]:
        limit = anchor.y1 + max(anchor.h, 0.025) * max_dy_factor
        cands = [t for t in self.tokens if t.cy > anchor.y1 and t.y0 < limit and t.x1 > anchor.x0 - 0.02]
        if not cands:
            return []
        first_y = min(t.cy for t in cands)
        row = [t for t in cands if abs(t.cy - first_y) < max(anchor.h, 0.02) * 0.8]
        return sorted(row, key=lambda t: t.x0)

    def in_region(self, x0: float, y0: float, x1: float, y1: float) -> list[OcrToken]:
        return [t for t in self.tokens if x0 <= t.cx <= x1 and y0 <= t.cy <= y1]

    def full_text(self) -> str:
        return "\n".join("  ".join(t.text for t in row) for row in self.rows)


def union_bbox(tokens: list[OcrToken]) -> Optional[list[float]]:
    if not tokens:
        return None
    return [
        round(min(t.x0 for t in tokens), 4),
        round(min(t.y0 for t in tokens), 4),
        round(max(t.x1 for t in tokens), 4),
        round(max(t.y1 for t in tokens), 4),
    ]


def mean_conf(tokens: list[OcrToken]) -> float:
    if not tokens:
        return 0.0
    weights = [max(len(t.text), 1) for t in tokens]
    return float(sum(t.confidence * w for t, w in zip(tokens, weights)) / sum(weights))
