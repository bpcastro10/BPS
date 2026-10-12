"""Descarga (una sola vez, con internet) los modelos que no vienen en el repositorio.

Qué se baja lo deciden las fábricas del OCR y del modelo activos en config.json
(back/ocr/fabrica.py y back/modelo/fabrica.py). El detector de firmas ya viene en modelos/.
"""

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).parent


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    config = json.loads((RAIZ / "config.json").read_text(encoding="utf-8"))
    from back.modelo.fabrica import preparar_descarga as descargar_modelo
    from back.ocr.fabrica import preparar_descarga as descargar_ocr
    descargar_modelo(config, RAIZ)
    descargar_ocr(config)


if __name__ == "__main__":
    main()
