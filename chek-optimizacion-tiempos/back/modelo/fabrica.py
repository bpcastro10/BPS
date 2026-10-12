"""Elige el modelo de letra manuscrita según config.json → "modelo_profundo".

Hoy el único modelo es "glm-ocr". Si "lectura_profunda" es false, no se carga nada.
"""

import importlib
from pathlib import Path

# clave de config -> "modulo:funcion"   crear(config, raiz, dispositivo, precision)
MODELOS = {
    "glm-ocr": "back.modelo.glm_ocr:crear",
}


def _cargar(spec):
    modulo, nombre = spec.split(":")
    return getattr(importlib.import_module(modulo), nombre)


def crear_modelo_profundo(config, raiz, dispositivo, precision):
    if not config.get("lectura_profunda"):
        return None
    nombre = config.get("modelo_profundo", "glm-ocr")
    try:
        spec = MODELOS[nombre]
    except KeyError:
        disponibles = ", ".join(sorted(MODELOS))
        raise ValueError(
            f"Modelo '{nombre}' no está registrado. Disponibles: {disponibles}. "
            "Agrégalo en back/modelo/fabrica.py (ver back/modelo/contrato.py)."
        ) from None
    return _cargar(spec)(config, raiz, dispositivo, precision)


def preparar_descarga(config, raiz):
    """Descarga los pesos del modelo activo. Lo usa descargar_modelos.py."""
    nombre = config.get("modelo_profundo", "glm-ocr")
    modulo = importlib.import_module(MODELOS[nombre].split(":")[0])
    if not hasattr(modulo, "descargar"):
        print(f"El modelo '{nombre}' no define descargar(); no hay pesos que bajar.")
        return
    modulo.descargar(config, raiz)


def carpeta_de_config(config, raiz, clave="carpeta_modelo_profundo", por_omision="modelos/GLM-OCR"):
    carpeta = Path(config.get(clave, por_omision))
    if not carpeta.is_absolute():
        carpeta = Path(raiz) / carpeta
    return carpeta
