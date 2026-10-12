import cv2
import numpy as np

from back.dominio.imagen import ANCHO_TRABAJO

PICHINCHA_V1 = {
    "nombre": "Banco Pichincha v1",
    "banco": "Banco Pichincha",
    "referencia": "plantillas/pichincha_v1_referencia.tif",
    "codigo_banco_micr": "10",
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

def leer_gris(ruta):
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

    def recortar(self, img, zona):
        x0, y0, x1, y1 = self.d["zonas"][zona]
        h, w = img.shape[:2]
        return img[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
