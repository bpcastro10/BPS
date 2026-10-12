"""Crea variaciones de un escaneo real (corrido, inclinado, ruido, desenfoque, contraste, JPEG)
para medir la estabilidad mientras no haya más cheques reales. Copia las respuestas correctas.

Uso: .venv\\Scripts\\python generar_variaciones.py muestras\\pichincha_0001.tif muestras_variaciones
"""

import csv
import sys
from pathlib import Path

import cv2
import numpy as np

from poc.plantilla import leer_gris


def mover(g, dx, dy, grados, escala=1.0):
    h, w = g.shape
    M = cv2.getRotationMatrix2D((w / 2, h / 2), grados, escala)
    M[:, 2] += (dx, dy)
    return cv2.warpAffine(g, M, (w, h), borderMode=cv2.BORDER_CONSTANT, borderValue=235)


def jpeg(g, calidad):
    return cv2.imdecode(cv2.imencode(".jpg", g, [cv2.IMWRITE_JPEG_QUALITY, calidad])[1], cv2.IMREAD_GRAYSCALE)


VARIACIONES = {
    "corrido": lambda g: mover(g, 9, -6, 0),
    "inclinado_1grado": lambda g: mover(g, 0, 0, 1.0),
    "inclinado_menos2": lambda g: mover(g, 4, 3, -2.0),
    "escala_110": lambda g: cv2.resize(g, None, fx=1.1, fy=1.1, interpolation=cv2.INTER_CUBIC),
    "ruido": lambda g: np.clip(g + np.random.default_rng(1).normal(0, 12, g.shape), 0, 255).astype(np.uint8),
    "desenfoque": lambda g: cv2.GaussianBlur(g, (3, 3), 0.9),
    "contraste_bajo": lambda g: (g * 0.55 + 100).astype(np.uint8),
    "jpeg_q30": lambda g: jpeg(g, 30),
    "oscuro": lambda g: np.clip(g.astype(int) - 45, 0, 255).astype(np.uint8),
    "todo_junto": lambda g: jpeg(cv2.GaussianBlur(mover(g, 6, 4, -1.2), (3, 3), 0.7), 45),
}


def main():
    origen, destino = Path(sys.argv[1]), Path(sys.argv[2])
    destino.mkdir(parents=True, exist_ok=True)
    g = leer_gris(origen)
    verdad = {r["archivo"]: r for r in csv.DictReader(open(origen.parent / "verdad.csv", encoding="utf-8"))}
    fila = verdad[origen.name]
    filas = []
    for nombre, fn in VARIACIONES.items():
        archivo = f"{origen.stem}_{nombre}.png"
        cv2.imencode(".png", fn(g))[1].tofile(str(destino / archivo))
        filas.append({**fila, "archivo": archivo, "notas": f"variación: {nombre}"})
    with open(destino / "verdad.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(fila))
        w.writeheader()
        w.writerows(filas)
    print(f"{len(filas)} variaciones en {destino}")


if __name__ == "__main__":
    main()
