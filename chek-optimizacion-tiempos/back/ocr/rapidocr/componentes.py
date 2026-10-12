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
    print("Preparando modelos de PaddleOCR (RapidOCR)...", flush=True)
    Localizador("v6_small", "small")
    Lector("v6_small")
    Lector("v5_latin")
    print("Modelos de PaddleOCR listos.")
