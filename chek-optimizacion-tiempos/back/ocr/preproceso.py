import cv2
import numpy as np

def limpiar(gris, escala=3, binarizar=True):
    c = cv2.resize(gris, None, fx=escala, fy=escala, interpolation=cv2.INTER_CUBIC)
    k = (10 * escala + 1) | 1
    norm = cv2.divide(c, cv2.medianBlur(c, min(k, 255)), scale=255)
    if not binarizar:
        return norm
    _, bw = cv2.threshold(norm, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    tinta = 255 - bw
    lineas = cv2.morphologyEx(tinta, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (30 * escala, 1)))
    return cv2.medianBlur(255 - cv2.subtract(tinta, lineas), 3)

def proporcion_tinta(gris):
    limpio = limpiar(gris, escala=1)
    return float((limpio < 128).mean())

VARIANTES = {
    "limpio_x3": lambda g: limpiar(g, 3, True),
    "gris_x3": lambda g: limpiar(g, 3, False),
    "limpio_x2": lambda g: limpiar(g, 2, True),
}

def quitar_impreso_a_la_izquierda(gris):
    limpio = limpiar(gris, escala=2)
    tinta = (limpio < 128).astype(np.uint8)
    n, _, st, _ = cv2.connectedComponentsWithStats(tinta)
    comps = [s for s in st[1:] if s[4] >= 6]
    if len(comps) < 2:
        return gris, 0
    alto_max = max(s[3] for s in comps)
    altos = [s for s in comps if s[3] >= 0.55 * alto_max]
    x_alto = min(s[0] for s in altos)
    chicos = [s for s in comps if s[0] + s[2] <= x_alto and s[3] < 0.55 * alto_max]
    if len(chicos) < 2:
        return gris, 0
    x = max(0, x_alto // 2 - 2)
    return gris[:, x:], x
