import importlib

from back.ocr.contrato import ComponentesOcr

MOTORES = {"rapidocr": "back.ocr.rapidocr.componentes:crear_rapidocr"}

def _cargar(spec):
    modulo, nombre = spec.split(":")
    return getattr(importlib.import_module(modulo), nombre)

def crear_ocr(config, gpu_onnx=None) -> ComponentesOcr:
    nombre = config.get("motor_ocr", "rapidocr")
    try:
        spec = MOTORES[nombre]
    except KeyError:
        raise ValueError(f"Motor OCR '{nombre}' no está registrado. Disponibles: {', '.join(sorted(MOTORES))}") from None
    return _cargar(spec)(config, gpu_onnx)

def preparar_descarga(config):
    nombre = config.get("motor_ocr", "rapidocr")
    modulo = importlib.import_module(MOTORES[nombre].split(":")[0])
    if hasattr(modulo, "preparar_descarga"):
        modulo.preparar_descarga(config)
    else:
        print(f"El OCR '{nombre}' no define preparar_descarga(); no hay pesos que bajar.")
