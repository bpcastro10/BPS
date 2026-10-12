"""Plantilla del formato de cheque: imagen de referencia, zonas de cada campo y alineación.

Las zonas están en fracciones (x0, y0, x1, y1) del cheque de referencia. Cada escaneo se
alinea primero con la referencia, así las zonas caen en el mismo lugar aunque el cheque venga
corrido, inclinado o con otra resolución.
"""

import cv2
import numpy as np

# Formato Banco Pichincha (versión 1), medido sobre plantillas/pichincha_v1_referencia.tif (592x296, 100 dpi)
PICHINCHA_V1 = {
    "nombre": "Banco Pichincha v1",
    "banco": "Banco Pichincha",
    "referencia": "plantillas/pichincha_v1_referencia.tif",
    # Código de banco al inicio de la ruta en la MICR (10-129 135 -> 10129135)
    "codigo_banco_micr": "10",
    # Contenido de la MICR de la referencia (S = ⑈, T = ⑆), para crear las plantillas E-13B
    "micr_referencia": "S009835T10129135T3354618304S056460S",
    "zonas": {
        "cuenta_impresa": (0.71, 0.06, 0.92, 0.135),
        "cheque_impreso": (0.71, 0.135, 0.87, 0.21),
        "beneficiario": (0.08, 0.24, 0.74, 0.34),
        "monto_numeros": (0.785, 0.20, 0.98, 0.34),
        "monto_letras": (0.08, 0.34, 1.00, 0.445),
        "monto_letras_2": (0.03, 0.42, 0.90, 0.48),
        "ciudad_fecha": (0.10, 0.48, 0.50, 0.58),
        "micr": (0.00, 0.84, 1.00, 0.95),
    },
}

ANCHO_TRABAJO = 592   # todas las imágenes se llevan al tamaño de la referencia
MIN_COINCIDENCIAS = 25


def leer_gris(ruta):
    """Lee una imagen (TIF, PNG, JPG; ruta con tildes o espacios, o bytes) en escala de grises."""
    datos = np.frombuffer(ruta, np.uint8) if isinstance(ruta, (bytes, bytearray)) else np.fromfile(str(ruta), np.uint8)
    img = cv2.imdecode(datos, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError("No se pudo leer la imagen" + ("" if isinstance(ruta, (bytes, bytearray)) else f": {ruta}"))
    return img


class Plantilla:
    def __init__(self, definicion, raiz="."):
        self.d = definicion
        ref = leer_gris(f"{raiz}/{definicion['referencia']}")
        self.ref = cv2.resize(ref, (ANCHO_TRABAJO, round(ref.shape[0] * ANCHO_TRABAJO / ref.shape[1])))
        self.orb = cv2.ORB_create(1500)
        self.kp_ref, self.des_ref = self.orb.detectAndCompute(self.ref, None)
        self.matcher = cv2.BFMatcher(cv2.NORM_HAMMING)

    def alinear(self, gris):
        """Lleva el escaneo al marco de la referencia. Devuelve (imagen alineada, info)."""
        h, w = self.ref.shape
        base = cv2.resize(gris, (w, round(gris.shape[0] * w / gris.shape[1])), interpolation=cv2.INTER_AREA
                          if gris.shape[1] > w else cv2.INTER_CUBIC)
        kp, des = self.orb.detectAndCompute(base, None)
        if des is not None and len(kp) >= MIN_COINCIDENCIAS:
            pares = self.matcher.knnMatch(des, self.des_ref, k=2)
            buenos = [m for m, n in (p for p in pares if len(p) == 2) if m.distance < 0.75 * n.distance]
            if len(buenos) >= MIN_COINCIDENCIAS:
                src = np.float32([kp[m.queryIdx].pt for m in buenos])
                dst = np.float32([self.kp_ref[m.trainIdx].pt for m in buenos])
                M, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=4)
                if M is not None and int(inl.sum()) >= MIN_COINCIDENCIAS:
                    escala = float(np.hypot(M[0, 0], M[1, 0]))
                    if 0.8 < escala < 1.25:
                        alineada = cv2.warpAffine(base, M, (w, h), flags=cv2.INTER_CUBIC,
                                                  borderMode=cv2.BORDER_REPLICATE)
                        return alineada, {"metodo": "orb", "coincidencias": int(inl.sum()),
                                          "rotacion_grados": round(float(np.degrees(np.arctan2(M[1, 0], M[0, 0]))), 2)}
        # Sin suficientes puntos: se asume que el cheque viene completo y derecho
        return cv2.resize(gris, (w, h), interpolation=cv2.INTER_CUBIC), {"metodo": "escala", "coincidencias": 0}

    def recortar(self, img, zona):
        x0, y0, x1, y1 = self.d["zonas"][zona]
        h, w = img.shape[:2]
        return img[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
