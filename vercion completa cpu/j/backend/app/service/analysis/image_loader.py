"""Carga de archivos (imágenes y PDF) y preprocesamiento geométrico del cheque."""
from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from app.config.settings import SUPPORTED_EXTENSIONS
from app.exception import ImageReadException, UnsupportedFileException

log = logging.getLogger(__name__)


def load_pages(path: Path) -> list[np.ndarray]:
    """Devuelve cada página/imagen del archivo en formato BGR."""
    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileException(path.name)
    if ext == ".pdf":
        return _load_pdf(path)
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None
    if image is None:
        image = _load_with_pillow(path)
    if image is None:
        raise ImageReadException(path.name, "archivo dañado o vacío")
    return [image]


def _load_pdf(path: Path) -> list[np.ndarray]:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise ImageReadException(path.name, "instale PyMuPDF para leer PDF") from exc
    pages = []
    with fitz.open(str(path)) as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=250)
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            code = cv2.COLOR_RGBA2BGR if pix.n == 4 else cv2.COLOR_RGB2BGR
            pages.append(cv2.cvtColor(arr, code) if pix.n > 1 else cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR))
    if not pages:
        raise ImageReadException(path.name, "PDF sin páginas")
    return pages


def _load_with_pillow(path: Path):
    try:
        from PIL import Image

        with Image.open(path) as img:
            return cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)
    except Exception:
        return None


def crop_check(image: np.ndarray) -> np.ndarray:
    """En fotos con fondo, detecta el rectángulo del cheque y corrige la perspectiva."""
    h, w = image.shape[:2]
    scale = 800 / max(h, w)
    small = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    edges = cv2.dilate(cv2.Canny(gray, 40, 120), np.ones((3, 3), np.uint8), iterations=2)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    area_total = small.shape[0] * small.shape[1]
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
        area = cv2.contourArea(contour)
        if area < 0.25 * area_total or area > 0.97 * area_total:
            continue
        approx = cv2.approxPolyDP(contour, 0.02 * cv2.arcLength(contour, True), True)
        if len(approx) != 4:
            continue
        pts = _order_points(approx.reshape(4, 2).astype(np.float32) / scale)
        width = int(max(np.linalg.norm(pts[0] - pts[1]), np.linalg.norm(pts[3] - pts[2])))
        height = int(max(np.linalg.norm(pts[0] - pts[3]), np.linalg.norm(pts[1] - pts[2])))
        if height == 0 or not (1.6 <= width / height <= 3.4):
            continue
        dst = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=np.float32)
        log.debug("Cheque recortado por perspectiva (%dx%d)", width, height)
        return cv2.warpPerspective(image, cv2.getPerspectiveTransform(pts, dst), (width, height))
    return image


def _order_points(pts: np.ndarray) -> np.ndarray:
    s, d = pts.sum(axis=1), np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], dtype=np.float32)


def normalize_size(image: np.ndarray, min_width: int, max_width: int) -> np.ndarray:
    h, w = image.shape[:2]
    if h > w * 1.15:
        image = cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
        h, w = image.shape[:2]
    if w > max_width:
        f = max_width / w
        return cv2.resize(image, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    if w < min_width:
        f = min_width / w
        return cv2.resize(image, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    return image


def rotate(image: np.ndarray, angle_deg: float) -> np.ndarray:
    h, w = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle_deg, 1.0)
    return cv2.warpAffine(image, matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def crop_norm(image: np.ndarray, bbox: list[float], pad: float = 0.004) -> np.ndarray:
    h, w = image.shape[:2]
    x0, y0, x1, y1 = bbox
    xa, ya = max(int((x0 - pad) * w), 0), max(int((y0 - pad * 2) * h), 0)
    xb, yb = min(int((x1 + pad) * w), w), min(int((y1 + pad * 2) * h), h)
    return image[ya:yb, xa:xb]
