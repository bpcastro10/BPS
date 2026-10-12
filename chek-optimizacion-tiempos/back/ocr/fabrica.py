"""Elige el OCR según config.json → "motor_ocr".

Hoy el único motor es "rapidocr". Para usar otro:

1. Implementa el contrato de back/ocr/contrato.py.
2. Agrega una línea en MOTORES (módulo:función).
3. Cambia "motor_ocr" en config.json.

No hace falta tocar el analizador, las reglas ni el Excel.
"""

import importlib

from back.ocr.contrato import ComponentesOcr

# clave de config -> "modulo:funcion"   crear(config, gpu_onnx) -> ComponentesOcr
MOTORES = {
    "rapidocr": "back.ocr.rapidocr.componentes:crear_rapidocr",
}


def _cargar(spec):
    modulo, nombre = spec.split(":")
    return getattr(importlib.import_module(modulo), nombre)


def crear_ocr(config, gpu_onnx=None) -> ComponentesOcr:
    nombre = config.get("motor_ocr", "rapidocr")
    try:
        spec = MOTORES[nombre]
    except KeyError:
        disponibles = ", ".join(sorted(MOTORES))
        raise ValueError(
            f"Motor OCR '{nombre}' no está registrado. Disponibles: {disponibles}. "
            "Agrégalo en back/ocr/fabrica.py (ver back/ocr/contrato.py)."
        ) from None
    return _cargar(spec)(config, gpu_onnx)


def preparar_descarga(config):
    """Descarga los pesos del OCR activo. Lo usa descargar_modelos.py."""
    nombre = config.get("motor_ocr", "rapidocr")
    modulo = importlib.import_module(MOTORES[nombre].split(":")[0])
    if not hasattr(modulo, "preparar_descarga"):
        print(f"El OCR '{nombre}' no define preparar_descarga(); no hay pesos que bajar.")
        return
    modulo.preparar_descarga(config)
