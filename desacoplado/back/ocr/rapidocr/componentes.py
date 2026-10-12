"""Arma el lector, el localizador y el segundo lector de RapidOCR.

Los nombres de modelo ("v6_small", "v5_latin", ...) y "detector" son de este motor.
Otro OCR puede leer otras claves de config.json.
"""

from back.ocr.contrato import ComponentesOcr
from back.ocr.rapidocr.lector import Lector, params_onnx
from back.ocr.rapidocr.localizador import Localizador


def crear_rapidocr(config, gpu_onnx):
    onnx = params_onnx(None, gpu_onnx)
    modelo = config.get("modelo_lectura", "v6_small")
    secundario = config.get("lector_secundario")
    return ComponentesOcr(
        localizador=Localizador(modelo, config.get("detector", "tiny"), onnx),
        lector=Lector(modelo, onnx),
        lector_secundario=Lector(secundario, onnx) if secundario else None,
    )


def preparar_descarga(config=None):
    """Primera carga: RapidOCR baja los ONNX que todavía no están en disco.

    Se piden los mismos tres que siempre (detector small + v6_small + v5 latin),
    aunque config use otro tamaño: así la instalación queda como hasta ahora.
    """
    print("Preparando modelos de PaddleOCR (RapidOCR)...", flush=True)
    Localizador("v6_small", "small")
    Lector("v6_small")
    Lector("v5_latin")
    print("Modelos de PaddleOCR listos.")
