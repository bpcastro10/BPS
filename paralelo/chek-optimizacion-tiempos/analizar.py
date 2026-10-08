"""Analiza uno o varios cheques y muestra el JSON.

Uso:
    .venv\\Scripts\\python analizar.py muestras\\pichincha_0001.tif
    .venv\\Scripts\\python analizar.py muestras\\pichincha_0001.tif --beneficiario --modelo v5_latin
"""

import argparse
import json
import sys
from pathlib import Path

from poc.analizador import Analizador

RAIZ = Path(__file__).parent


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("imagenes", nargs="+")
    p.add_argument("--dispositivo", default="cpu", help="cpu (por omisión) o cuda:0, cuda:1...")
    p.add_argument("--modelo", help="v6_small, v6_medium, v5_latin, v5_server")
    p.add_argument("--beneficiario", action="store_true", help="incluir beneficiario (pendiente)")
    a = p.parse_args()
    config = json.loads((RAIZ / "config.json").read_text(encoding="utf-8"))
    if a.modelo:
        config["modelo_lectura"] = a.modelo
    if a.dispositivo != "cpu":
        from poc.hardware import detectar
        from poc.paralelo import config_del_proceso
        config = config_del_proceso(config, a.dispositivo, None, config.get("ejecucion", {}).get("precision_gpu", "float32"),
                                    detectar().onnx_cuda)
    analizador = Analizador(config, RAIZ)
    print(f"# modelos cargados en {analizador.segundos_carga} s (una sola vez)")
    for img in a.imagenes:
        r = analizador.analizar(img, {"beneficiario": True} if a.beneficiario else None)
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
