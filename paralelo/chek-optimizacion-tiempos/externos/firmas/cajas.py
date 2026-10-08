"""Ajuste de cajas a la tinta: recorta una caja holgada al rectángulo que realmente contiene trazos.

Se usa para las firmas (YOLOS devuelve varias cajas superpuestas por firma) y para las zonas de
campos (rectángulos fijos que abarcan más que el texto).
"""
import numpy as np
from PIL import Image


def _umbral_otsu(gris):
    hist = np.bincount(gris.ravel(), minlength=256).astype(np.float64)
    total = hist.sum()
    w0 = np.cumsum(hist)
    m0 = np.cumsum(hist * np.arange(256))
    w1 = total - w0
    with np.errstate(divide="ignore", invalid="ignore"):
        var = (m0[-1] * w0 / total - m0) ** 2 / (w0 * w1 / total)
    return int(np.nanargmax(var[:-1]))


def _quitar_trazos_largos(tinta, largo, hueco=4):
    """Apaga los tramos horizontales de al menos `largo` píxeles (líneas impresas, bordes).

    Tolera cortes de hasta `hueco` píxeles para que también se quiten los renglones punteados o gastados.
    """
    h, w = tinta.shape
    # En fotos los renglones salen algo inclinados: se engrosa 1 px en vertical para que sigan siendo continuos.
    gruesa = tinta.copy()
    gruesa[1:] |= tinta[:-1]
    gruesa[:-1] |= tinta[1:]
    # Cierre horizontal: un píxel cuenta como línea si hay tinta a menos de `hueco` px a su izquierda y a su derecha.
    izq, der = gruesa.copy(), gruesa.copy()
    for k in range(1, hueco + 1):
        izq[:, k:] |= gruesa[:, :-k]
        der[:, :-k] |= gruesa[:, k:]
    unida = izq & der
    p = np.zeros((h, w + 2), bool)
    p[:, 1:-1] = unida
    d = np.diff(p.astype(np.int8), axis=1)
    for f, ini in zip(*np.nonzero(d == 1)):
        fin = ini + np.argmax(d[f, ini:] == -1)
        if fin - ini >= largo:
            # Se apagan también las filas vecinas para no dejar el borde antialiasado de la línea.
            tinta[max(0, f - 3):f + 4, max(0, ini - 2):fin + 2] = False
    return tinta


def _renglon_manuscrito(perfil, separacion):
    """Índices [ini, fin] del renglón más alto (la letra manuscrita es más grande que la impresa),
    uniendo los vecinos separados por menos de `separacion`."""
    idx = np.flatnonzero(perfil)
    cortes = np.flatnonzero(np.diff(idx) > separacion)
    grupos = np.split(idx, cortes + 1)
    mejor = max(grupos, key=lambda g: (g[-1] - g[0], perfil[g].sum()))
    return mejor[0], mejor[-1]


def _grupo_valor(perfil, separacion):
    """Columnas del valor escrito: el bloque con más tinta, extendido hacia la derecha (el valor sigue)
    y casi nada hacia la izquierda (ahí suele estar la etiqueta impresa, p. ej. "Páguese a la orden de:")."""
    idx = np.flatnonzero(perfil)
    cortes = np.flatnonzero(np.diff(idx) > separacion)
    grupos = np.split(idx, cortes + 1)
    i = j = max(range(len(grupos)), key=lambda k: perfil[grupos[k]].sum())
    while j + 1 < len(grupos) and grupos[j + 1][0] - grupos[j][-1] <= 2 * separacion:
        j += 1
    while i > 0 and grupos[i][0] - grupos[i - 1][-1] <= separacion // 2:
        i -= 1
    return grupos[i][0], grupos[j][-1]


def _recortar_extremos(perfil, ini, fin, fraccion):
    """Quita de cada extremo los bordes que juntos tienen menos de `fraccion` de la tinta (puntos sueltos, colas finas)."""
    tramo = perfil[ini:fin + 1].astype(np.float64)
    acum = np.cumsum(tramo) / tramo.sum()
    return ini + int(np.searchsorted(acum, fraccion)), ini + int(np.searchsorted(acum, 1 - fraccion))


def ajustar_a_tinta(img: Image.Image, x1, y1, x2, y2, margen=2, solo_bloque_principal=False, recorte=0.01):
    """Devuelve (x1, y1, x2, y2) ajustada a la tinta dentro de la caja, o la caja original si no hay tinta clara.

    solo_bloque_principal: encuadra solo el valor escrito, sin la etiqueta impresa ni trazos aislados (zonas de campos).
    recorte: fracción de tinta que se ignora en cada borde para que la caja quede justa.
    """
    x1, y1 = max(0, int(x1)), max(0, int(y1))
    x2, y2 = min(img.width, int(x2)), min(img.height, int(y2))
    if x2 - x1 < 8 or y2 - y1 < 8:
        return x1, y1, x2, y2
    gris = np.asarray(img.crop((x1, y1, x2, y2)).convert("L"), dtype=np.uint8)
    if gris.std() < 12:  # zona casi uniforme: no hay trazo distinguible
        return x1, y1, x2, y2
    # Tinta = más oscuro que el umbral de Otsu y claramente más oscuro que el fondo (evita tramas de seguridad).
    tinta = gris < min(_umbral_otsu(gris), int(np.median(gris)) - 40)
    h, w = tinta.shape
    tinta = _quitar_trazos_largos(tinta, max(40, int(0.3 * w)))
    tinta = _quitar_trazos_largos(tinta.T, max(30, int(0.45 * h))).T
    if tinta.sum() < 0.002 * h * w:
        return x1, y1, x2, y2
    cols = tinta.sum(0) * (tinta.sum(0) >= 2)
    if not cols.any():
        return x1, y1, x2, y2
    if solo_bloque_principal:
        c0, c1 = _grupo_valor(cols, max(25, int(0.035 * w)))
    else:
        c = np.flatnonzero(cols)
        c0, c1 = c[0], c[-1]
    c0, c1 = _recortar_extremos(cols, c0, c1, recorte)
    sub = tinta[:, c0:c1 + 1]
    filas = sub.sum(1) * (sub.sum(1) >= 2)
    if not filas.any():
        return x1, y1, x2, y2
    if solo_bloque_principal:
        f0, f1 = _renglon_manuscrito(filas, max(8, int(0.15 * h)))
    else:
        f = np.flatnonzero(filas)
        f0, f1 = f[0], f[-1]
    f0, f1 = _recortar_extremos(filas, f0, f1, recorte)
    return (int(max(0, x1 + c0 - margen)), int(max(0, y1 + f0 - margen)),
            int(min(img.width, x1 + c1 + 1 + margen)), int(min(img.height, y1 + f1 + 1 + margen)))


def _deben_unirse(a, b, holgura):
    """Misma firma si se solapan bastante, o si una está justo encima de la otra (firma partida en dos)."""
    ix = min(a[2], b[2]) - max(a[0], b[0])
    iy = min(a[3], b[3]) - max(a[1], b[1])
    area_min = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])) or 1
    if ix > 0 and iy > 0 and ix * iy / area_min >= 0.5:
        return True
    ancho_min = min(a[2] - a[0], b[2] - b[0]) or 1
    return ix / ancho_min >= 0.6 and iy > -holgura


def unir_superpuestas(cajas, holgura=12):
    """Une cajas de la misma firma (YOLOS suele dar varias superpuestas o partidas).

    cajas: lista de (x1, y1, x2, y2, confianza). Devuelve la misma forma, con la confianza máxima del grupo.
    """
    cajas = [list(c) for c in cajas]
    cambio = True
    while cambio:
        cambio = False
        for i in range(len(cajas)):
            for j in range(i + 1, len(cajas)):
                a, b = cajas[i], cajas[j]
                if _deben_unirse(a, b, holgura):
                    cajas[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]), max(a[4], b[4])]
                    del cajas[j]
                    cambio = True
                    break
            if cambio:
                break
    return [tuple(c) for c in cajas]
