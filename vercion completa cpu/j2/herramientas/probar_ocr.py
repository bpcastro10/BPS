"""
Prueba rápida por consola: analiza un archivo y muestra los campos extraídos.

Uso:  .venv\\Scripts\\python herramientas\\probar_ocr.py cheques\\mi_cheque.jpg
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from extractor import extraer_campos  # noqa: E402
from ocr_motor import cargar_imagen, leer_cheque  # noqa: E402

for ruta in sys.argv[1:]:
    inicio = time.perf_counter()
    cajas, _, calidad = leer_cheque(cargar_imagen(Path(ruta)))
    resultado = extraer_campos(cajas)
    print(f"\n===== {ruta} ({(time.perf_counter() - inicio) * 1000:.0f} ms) =====")
    print("calidad:", json.dumps(calidad, ensure_ascii=False))
    print(json.dumps(resultado["campos"], ensure_ascii=False, indent=2))
    print("avisos:", resultado.get("avisos"))
    print("--- Texto OCR ---")
    print(resultado["texto_completo"])
