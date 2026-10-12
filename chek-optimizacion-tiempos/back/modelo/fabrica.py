import importlib

MODELOS = {"glm-ocr": "back.modelo.glm_ocr:crear"}

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
        raise ValueError(f"Modelo '{nombre}' no está registrado. Disponibles: {', '.join(sorted(MODELOS))}") from None
    return _cargar(spec)(config, raiz, dispositivo, precision)

def preparar_descarga(config, raiz):
    nombre = config.get("modelo_profundo", "glm-ocr")
    modulo = importlib.import_module(MODELOS[nombre].split(":")[0])
    if hasattr(modulo, "descargar"):
        modulo.descargar(config, raiz)
    else:
        print(f"El modelo '{nombre}' no define descargar(); no hay pesos que bajar.")
