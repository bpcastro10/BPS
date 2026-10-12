"""Lector dedicado de la línea MICR (fuente E-13B) por comparación con plantillas.

La E-13B es una fuente fija diseñada para lectura automática: cada carácter se recorta y se
compara con plantillas sacadas de escaneos reales cuyo MICR se conoce. Es más fiable que un OCR
general (que confunde 8/3/9 en esta fuente) y tarda milisegundos.

Clases: dígitos '0'-'9', 'S' (símbolo ⑈ on-us), 'T' (símbolo ⑆ tránsito).
Un carácter que no se parece lo suficiente a ninguna plantilla queda como '?' (nunca se adivina).
"""

import cv2
import numpy as np

TAM = (20, 28)            # ancho, alto normalizado de cada carácter
ESCALA = 4
SIMILITUD_MINIMA = 0.55   # por debajo: carácter desconocido
MARGEN_MINIMO = 0.06      # diferencia mínima entre la mejor clase y la segunda


def _binarizar(zona):
    z = cv2.resize(zona, None, fx=ESCALA, fy=ESCALA, interpolation=cv2.INTER_CUBIC)
    n = cv2.divide(z, cv2.medianBlur(z, 61), scale=255)
    _, bw = cv2.threshold(n, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return cv2.morphologyEx(bw, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))


def segmentar(zona):
    """Cajas (x, y, w, h) de cada carácter, de izquierda a derecha, sobre la zona ampliada."""
    bw = _binarizar(zona)
    _, _, st, _ = cv2.connectedComponentsWithStats(bw)
    cajas = sorted([list(s[:4]) for s in st[1:] if s[4] > 40], key=lambda c: c[0])
    unidas = []
    for x, y, w, h in cajas:   # partes de un mismo carácter se solapan en x (símbolos ⑆ ⑈)
        if unidas and x < unidas[-1][0] + unidas[-1][2] - 2:
            X, Y, W, H = unidas[-1]
            x2, y2 = max(X + W, x + w), max(Y + H, y + h)
            X, Y = min(X, x), min(Y, y)
            unidas[-1] = [X, Y, x2 - X, y2 - Y]
        else:
            unidas.append([x, y, w, h])
    if not unidas:
        return bw, []
    alto = np.median([c[3] for c in unidas])
    return bw, [c for c in unidas if c[3] >= 0.6 * alto]


def _normalizar(bw, caja):
    x, y, w, h = caja
    g = bw[y:y + h, x:x + w].astype(np.float32) / 255
    return cv2.resize(g, TAM, interpolation=cv2.INTER_AREA)


class LectorMICR:
    def __init__(self):
        self.plantillas = []   # [(clase, imagen normalizada)]

    def agregar(self, zona, etiquetas):
        """Agrega plantillas desde una zona MICR cuyo contenido se conoce (ej. 'S009835T1012...').

        Devuelve False si la cantidad de caracteres segmentados no coincide (no se agrega nada).
        """
        bw, cajas = segmentar(zona)
        if len(cajas) != len(etiquetas):
            return False
        self.plantillas += [(e, _normalizar(bw, c)) for e, c in zip(etiquetas, cajas)]
        return True

    @property
    def clases(self):
        return sorted({c for c, _ in self.plantillas})

    def _clasificar(self, g):
        pad = cv2.copyMakeBorder(g, 2, 2, 2, 2, cv2.BORDER_CONSTANT, value=0)
        mejor = {}
        for clase, t in self.plantillas:
            s = float(cv2.matchTemplate(pad, t, cv2.TM_CCOEFF_NORMED).max())
            if s > mejor.get(clase, -1):
                mejor[clase] = s
        orden = sorted(mejor.items(), key=lambda kv: kv[1], reverse=True)
        (c1, s1), s2 = orden[0], (orden[1][1] if len(orden) > 1 else 0)
        if s1 < SIMILITUD_MINIMA or s1 - s2 < MARGEN_MINIMO:
            return "?", s1, s1 - s2
        return c1, s1, s1 - s2

    def leer(self, zona):
        """Devuelve {'texto': 'S009835T...', 'caracteres': [(clase, similitud, margen)]}."""
        bw, cajas = segmentar(zona)
        chars = []
        ancho = np.median([c[2] for c in cajas]) if cajas else 0
        for i, c in enumerate(cajas):
            # Un hueco grande entre caracteres separa grupos aunque no haya símbolo (ej. '05   6460')
            if i and c[0] - (cajas[i - 1][0] + cajas[i - 1][2]) > 1.2 * ancho:
                chars.append((" ", 1.0, 1.0))
            chars.append(self._clasificar(_normalizar(bw, c)))
        return {"texto": "".join(c for c, _, _ in chars), "caracteres": chars}


def grupos(lectura):
    """Separa la lectura en grupos de dígitos (los símbolos S/T son separadores).

    Devuelve [(digitos, confiable)] donde confiable = ningún carácter dudoso en el grupo.
    """
    out, actual, dudoso = [], "", False
    for c, _, _ in lectura["caracteres"] + [("S", 1, 1)]:
        if c in "ST ":
            if actual:
                out.append((actual, not dudoso))
            actual, dudoso = "", False
        else:
            actual += c
            dudoso |= c == "?"
    return out
