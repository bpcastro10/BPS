"""Refinamiento opcional con un modelo de visión local servido por Ollama (p.ej. qwen2.5vl, llama3.2-vision)."""
from __future__ import annotations

import base64
import json
import logging
import urllib.request
from typing import Optional

import cv2
import numpy as np

log = logging.getLogger(__name__)

_PROMPT = (
    "Eres un experto en lectura de cheques bancarios. Lee el cheque de la imagen y devuelve SOLO un JSON con "
    "estas claves: banco, numero_cheque, ciudad, fecha (formato YYYY-MM-DD), beneficiario, monto (número con "
    "punto decimal, sin símbolos), monto_letras, cuenta, concepto. Transcribe exactamente lo escrito (a mano o "
    "impreso). Usa null si un dato no existe."
)
VLM_KEYS = ("banco", "numero_cheque", "ciudad", "fecha", "beneficiario", "monto", "monto_letras", "cuenta", "concepto")


class VlmRefiner:
    def __init__(self, base_url: str, model: str, mode: str):
        self._url = base_url.rstrip("/") + "/api/generate"
        self._model = model
        self._mode = mode

    @property
    def enabled(self) -> bool:
        return bool(self._model) and self._mode != "off"

    def should_run(self, needs_review: bool) -> bool:
        return self.enabled and (self._mode == "always" or needs_review)

    def extract(self, image: np.ndarray) -> Optional[dict]:
        ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            return None
        payload = {
            "model": self._model,
            "prompt": _PROMPT,
            "images": [base64.b64encode(buf.tobytes()).decode()],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
        }
        request = urllib.request.Request(self._url, data=json.dumps(payload).encode(),
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                body = json.loads(response.read().decode())
            data = json.loads(body.get("response", "{}"))
            return {k: (str(data[k]).strip() if data.get(k) not in (None, "", "null") else None) for k in VLM_KEYS}
        except Exception as exc:
            log.warning("No se pudo usar el modelo de visión local (%s): %s", self._model, exc)
            return None
