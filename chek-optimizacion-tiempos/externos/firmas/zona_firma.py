import cv2
import numpy as np
from PIL import Image

AREA_MIN = 0.00015
ANCHO_MIN = 0.025
ALTO_TRAZO = 0.025
HUECO_FIRMAS = 0.05
ANCHO_FIRMA = 0.08
AREA_FIRMA = 0.0015

def linea_firma(gris: np.ndarray):
    H, W = gris.shape
    oscuro = (gris < np.median(gris) - 50).astype(np.uint8)
    oscuro = cv2.dilate(oscuro, np.ones((3, 1), np.uint8))
    horizontal = cv2.morphologyEx(oscuro, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(15, W // 12), 1)))
    n, _, st, _ = cv2.connectedComponentsWithStats(horizontal)
    candidatas = [tuple(int(v) for v in st[i][:4]) for i in range(1, n)
                  if 0.25 * W <= st[i][2] <= 0.55 * W and st[i][0] + st[i][2] / 2 > 0.5 * W and 0.55 * H <= st[i][1] <= 0.95 * H]
    return max(candidatas, key=lambda l: l[2]) if candidatas else None

def zona(img: Image.Image, linea):
    x, y, w, _ = linea
    return (max(0, x - int(0.08 * img.width)), max(0, y - int(0.35 * img.height)),
            min(img.width, x + w + int(0.08 * img.width)), min(img.height, y + int(0.12 * img.height)))

def en_zona(caja, z):
    cx, cy = (caja[0] + caja[2]) / 2, (caja[1] + caja[3]) / 2
    return z[0] <= cx <= z[2] and z[1] <= cy <= z[3]

def _trazos(gris: np.ndarray, linea, xa, xb, quitar_verticales=False):
    H, W = gris.shape
    x, y, w, _ = linea
    y0 = max(0, y - int(0.3 * H))
    if y - 3 <= y0 or xb <= xa:
        return []
    tinta = (gris[y0:y - 3, xa:xb] < min(150, int(np.median(gris)) - 70)).astype(np.uint8)
    tinta &= 1 - cv2.morphologyEx(tinta, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(15, w // 4), 1)))
    if quitar_verticales:
        tinta &= 1 - cv2.morphologyEx(tinta, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(15, int(0.25 * H)))))
    _, _, st, _ = cv2.connectedComponentsWithStats(tinta, connectivity=8)
    return [(int(xa + s[0]), int(y0 + s[1]), int(xa + s[0] + s[2]), int(y0 + s[1] + s[3]), int(s[4]))
            for s in st[1:] if s[4] >= 0.00002 * H * W and s[3] >= ALTO_TRAZO * H]

def tinta_sobre_linea(img: Image.Image, gris: np.ndarray, linea):
    H, W = gris.shape
    x, _, w, _ = linea
    trazos = _trazos(gris, linea, x, x + w)
    if not trazos:
        return None
    x1, y1 = min(t[0] for t in trazos), min(t[1] for t in trazos)
    x2, y2 = max(t[2] for t in trazos), max(t[3] for t in trazos)
    if sum(t[4] for t in trazos) < AREA_MIN * H * W or x2 - x1 < ANCHO_MIN * W:
        return None
    return x1, y1, x2, y2

def firmas_separadas(img: Image.Image, gris: np.ndarray, linea):
    H, W = gris.shape
    x, _, w, _ = linea
    trazos = sorted(_trazos(gris, linea, max(0, x - int(0.08 * W)), min(W, x + w + int(0.08 * W)), True))
    bloques = []
    for t in trazos:
        if bloques and t[0] - bloques[-1][2] <= HUECO_FIRMAS * W:
            b = bloques[-1]
            bloques[-1] = [min(b[0], t[0]), min(b[1], t[1]), max(b[2], t[2]), max(b[3], t[3]), b[4] + t[4]]
        else:
            bloques.append(list(t))
    return [tuple(b[:4]) for b in bloques if b[2] - b[0] >= ANCHO_FIRMA * W and b[4] >= AREA_FIRMA * H * W]

def _cruza(a, b):
    return min(a[2], b[2]) > max(a[0], b[0])

def revisar(img: Image.Image, detecciones):
    gris = np.asarray(img.convert("L"))
    linea = linea_firma(gris)
    if linea is None:
        return [(*d, "modelo") for d in detecciones]
    z = zona(img, linea)
    dentro = [d for d in detecciones if en_zona(d, z)]
    if not dentro:
        caja = tinta_sobre_linea(img, gris, linea)
        return [(*caja, None, "tinta")] if caja else []
    bloques = firmas_separadas(img, gris, linea)
    firmas = []
    for d in dentro:
        partes = [b for b in bloques if d[0] <= (b[0] + b[2]) / 2 <= d[2]]
        if len(partes) >= 2:
            firmas += [(b[0], d[1], b[2], d[3], d[4], "modelo") for b in partes]
        else:
            firmas.append((*d, "modelo"))
    firmas += [(*b, None, "tinta") for b in bloques if not any(_cruza(b, f) for f in firmas)]
    return firmas
