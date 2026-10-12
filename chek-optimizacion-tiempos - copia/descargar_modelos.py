"""Descarga (una sola vez, con internet) los modelos que no vienen en el repositorio.

- GLM-OCR (2,5 GB) -> modelos/GLM-OCR            (lectura profunda de letra manuscrita)
- PaddleOCR / RapidOCR (detector y lectores ONNX) -> se bajan solos al crearlos por primera vez
- El detector de firmas (YOLOS-tiny, 25 MB) ya viene en modelos/
"""

import sys
from pathlib import Path

RAIZ = Path(__file__).parent


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    glm = RAIZ / "modelos" / "GLM-OCR"
    if (glm / "model.safetensors").exists():
        print("GLM-OCR ya está descargado.")
    else:
        print("Descargando GLM-OCR (2,5 GB, puede tardar varios minutos)...", flush=True)
        from huggingface_hub import snapshot_download
        snapshot_download("zai-org/GLM-OCR", local_dir=str(glm))
        print("GLM-OCR listo.")

    print("Preparando modelos de PaddleOCR (RapidOCR)...", flush=True)
    sys.path.insert(0, str(RAIZ))
    from poc.lector import Lector
    from poc.localizador import Localizador
    Localizador("v6_small", "small")
    Lector("v6_small")
    Lector("v5_latin")
    print("Modelos de PaddleOCR listos.")


if __name__ == "__main__":
    main()
