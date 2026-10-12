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
