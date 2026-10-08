"""Reconocimiento local de texto manuscrito con TrOCR (Hugging Face transformers + torch)."""
from __future__ import annotations

import logging
import threading
from typing import Optional

import cv2
import numpy as np

log = logging.getLogger(__name__)


class HandwritingRecognizer:
    def __init__(self, model_name: str, enabled: bool = True):
        self._model_name = model_name
        self._enabled = enabled
        self._model = None
        self._processor = None
        self._torch = None
        self._failed = False
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        """Solo True cuando el modelo ya está en memoria: nunca bloquea el análisis esperando la descarga."""
        return self._enabled and self._model is not None

    @property
    def enabled(self) -> bool:
        return self._enabled and not self._failed

    def preload_async(self) -> None:
        if self._enabled:
            threading.Thread(target=self._ensure_loaded, name="trocr-loader", daemon=True).start()

    def _ensure_loaded(self) -> bool:
        if self._model is not None:
            return True
        with self._lock:
            if self._model is not None:
                return True
            if self._failed:
                return False
            try:
                import torch
                from transformers import TrOCRProcessor, VisionEncoderDecoderModel

                log.info("Cargando modelo de manuscritos %s (solo la primera vez descarga ~1.3 GB)...", self._model_name)
                self._processor = TrOCRProcessor.from_pretrained(self._model_name)
                model = VisionEncoderDecoderModel.from_pretrained(self._model_name)
                device = "cuda" if torch.cuda.is_available() else "cpu"
                self._model = model.to(device).eval()
                self._torch = torch
                torch.set_num_threads(max(torch.get_num_threads(), 4))
                log.info("Modelo de manuscritos listo en %s", device)
                return True
            except Exception as exc:
                self._failed = True
                log.warning("Reconocimiento de manuscritos desactivado: %s", exc)
                return False

    def recognize(self, crop_bgr: np.ndarray) -> Optional[tuple[str, float]]:
        if crop_bgr is None or crop_bgr.size == 0 or not self.available:
            return None
        from PIL import Image

        rgb = Image.fromarray(cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB))
        torch = self._torch
        with torch.inference_mode():
            pixel_values = self._processor(images=rgb, return_tensors="pt").pixel_values.to(self._model.device)
            out = self._model.generate(pixel_values, max_new_tokens=48, num_beams=1,
                                       output_scores=True, return_dict_in_generate=True)
            scores = self._model.compute_transition_scores(out.sequences, out.scores, normalize_logits=True)
            confidence = float(torch.exp(scores[0]).mean()) if scores.numel() else 0.0
        text = self._processor.batch_decode(out.sequences, skip_special_tokens=True)[0].strip()
        return (text, confidence) if text else None
