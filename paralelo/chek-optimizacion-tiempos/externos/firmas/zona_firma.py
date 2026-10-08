"""Verificación de tinta en la zona de firma del cheque.

El detector YOLOS reconoce bien las firmas con rasgos (garabatos, rúbricas), pero no las firmas sencillas
que son solo el nombre escrito: para el modelo eso es texto manuscrito, no firma. Y al revés, a veces marca
como firma la fecha o el beneficiario.

Aquí se busca la línea impresa de la firma (horizontal, en la mitad derecha de la parte inferior) y se mira:
  - qué detecciones de YOLOS caen sobre esa línea (las demás son otro texto manuscrito), y
  - si YOLOS no encontró nada ahí, si hay trazos manuscritos encima de la línea (firma sencilla).
Si no se encuentra la línea (foto muy rotada o borrosa) se deja el resultado de YOLOS tal cual.
"""
import cv2
import numpy as np
from PIL import Image

# Mínimos para dar por firmada la zona por tinta (calibrados con cheques Venus y sintéticos con/sin firma).
AREA_MIN = 0.00015   # fracción de la imagen cubierta por trazos (las firmas medidas dan 0.00018 o más; sin firma, 0)
ANCHO_MIN = 0.025    # ancho del conjunto de trazos, en fracción del ancho del cheque
ALTO_TRAZO = 0.025   # alto mínimo de cada trazo (descarta puntos, polvo y ruido de la foto)
# Dos firmas una al lado de la otra: bloques separados por más de HUECO_FIRMAS del ancho, cada uno de al menos
# ANCHO_FIRMA del ancho y AREA_FIRMA de tinta (en los cheques con dos firmas el bloque más chico dio 0.0019;
# los restos sueltos junto a una firma, como mucho 0.0013).
HUECO_FIRMAS = 0.05
ANCHO_FIRMA = 0.08
AREA_FIRMA = 0.0015


def linea_firma(gris: np.ndarray):
    """(x, y, ancho, alto) de la línea de firma, o None si no se encuentra una clara."""
    H, W = gris.shape
    oscuro = (gris < np.median(gris) - 50).astype(np.uint8)
    # En fotos la línea sale algo inclinada o cortada: se engrosa en vertical antes de buscar tramos largos.
    oscuro = cv2.dilate(oscuro, np.ones((3, 1), np.uint8))
    horizontal = cv2.morphologyEx(oscuro, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(15, W // 12), 1)))
    n, _, st, _ = cv2.connectedComponentsWithStats(horizontal)
    # La línea de firma ocupa entre un cuarto y la mitad del ancho y está abajo a la derecha (en los cheques
    # probados, entre el 62% y el 81% del alto); los renglones de "La suma de" o "No invadir esta zona" son
    # más largos o están más arriba y quedan fuera.
    candidatas = [tuple(int(v) for v in st[i][:4]) for i in range(1, n)
                  if 0.25 * W <= st[i][2] <= 0.55 * W and st[i][0] + st[i][2] / 2 > 0.5 * W and 0.55 * H <= st[i][1] <= 0.95 * H]
    return max(candidatas, key=lambda l: l[2]) if candidatas else None


def zona(img: Image.Image, linea):
    """Rectángulo (x1, y1, x2, y2) donde puede estar la firma: sobre la línea, con holgura a los lados y abajo
    (las firmas suelen pasarse de la línea)."""
    x, y, w, _ = linea
    return (max(0, x - int(0.08 * img.width)), max(0, y - int(0.35 * img.height)),
            min(img.width, x + w + int(0.08 * img.width)), min(img.height, y + int(0.12 * img.height)))


def en_zona(caja, z):
    cx, cy = (caja[0] + caja[2]) / 2, (caja[1] + caja[3]) / 2
    return z[0] <= cx <= z[2] and z[1] <= cy <= z[3]


def _trazos(gris: np.ndarray, linea, xa, xb, quitar_verticales=False):
    """Trazos manuscritos encima de la línea de firma, entre las columnas xa y xb.

    Devuelve [(x1, y1, x2, y2, área)] en coordenadas de la imagen (sin puntos sueltos ni ruido)."""
    H, W = gris.shape
    x, y, w, _ = linea
    y0 = max(0, y - int(0.3 * H))
    if y - 3 <= y0 or xb <= xa:
        return []
    # Tinta = claramente más oscura que el papel; la trama de seguridad del fondo es más clara y no entra.
    tinta = (gris[y0:y - 3, xa:xb] < min(150, int(np.median(gris)) - 70)).astype(np.uint8)
    tinta &= 1 - cv2.morphologyEx(tinta, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(15, w // 4), 1)))
    if quitar_verticales:  # borde del cheque u otras líneas impresas verticales
        tinta &= 1 - cv2.morphologyEx(tinta, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(15, int(0.25 * H)))))
    _, _, st, _ = cv2.connectedComponentsWithStats(tinta, connectivity=8)
    return [(int(xa + s[0]), int(y0 + s[1]), int(xa + s[0] + s[2]), int(y0 + s[1] + s[3]), int(s[4]))
            for s in st[1:] if s[4] >= 0.00002 * H * W and s[3] >= ALTO_TRAZO * H]


def tinta_sobre_linea(img: Image.Image, gris: np.ndarray, linea):
    """Caja (x1, y1, x2, y2) de los trazos manuscritos encima de la línea de firma, o None si está en blanco."""
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
    """Bloques de tinta sobre la línea separados por un espacio en blanco, que por tamaño pueden ser una firma
    entera (para cheques con dos firmas una al lado de la otra). Devuelve [(x1, y1, x2, y2)] de izquierda a derecha."""
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
    """Las cajas se superponen en horizontal."""
    return min(a[2], b[2]) > max(a[0], b[0])


def revisar(img: Image.Image, detecciones):
    """Combina las detecciones de YOLOS [(x1, y1, x2, y2, confianza)] con la línea de firma.

    Devuelve [(x1, y1, x2, y2, confianza, origen)], con origen "modelo" o "tinta" (confianza None):
      - se descartan las detecciones fuera de la línea de firma;
      - si una detección abarca dos firmas separadas, se parte en dos; si hay una firma que el modelo
        no marcó junto a las que sí, se agrega por tinta;
      - si el modelo no dejó nada en la línea, se busca tinta (una sola firma: las de nombre y apellido
        tienen espacios entre palabras y no se deben partir).
    Sin línea de firma clara, devuelve las detecciones tal cual.
    """
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
