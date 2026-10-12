import os
from dataclasses import asdict, dataclass

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

import torch
from PIL import Image
from transformers import AutoImageProcessor, AutoModelForObjectDetection

from . import cajas, zona_firma

MODELO_DEFAULT = "mdefrance/yolos-tiny-signature-detection"
CARPETA_MODELOS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "modelos")
CONF_TINTA = 0.5

class ModeloNoEncontrado(RuntimeError):
    pass

@dataclass
class Firma:
    x1: int
    y1: int
    x2: int
    y2: int
    confianza: float
    origen: str

    @property
    def ancho(self):
        return self.x2 - self.x1

    @property
    def alto(self):
        return self.y2 - self.y1

    def a_dict(self):
        d = asdict(self)
        d.update(ancho=self.ancho, alto=self.alto)
        return d

class DetectorFirmas:
    def __init__(self, repo: str = MODELO_DEFAULT, carpeta_modelos: str | None = None, verificar_tinta: bool = True,
                 dispositivo: str = "cpu"):
        self.repo = repo
        self.dispositivo = dispositivo
        self.verificar_tinta = verificar_tinta
        carpeta_modelos = carpeta_modelos or CARPETA_MODELOS
        try:
            self.processor = AutoImageProcessor.from_pretrained(repo, cache_dir=carpeta_modelos, local_files_only=True)
            self.model = AutoModelForObjectDetection.from_pretrained(
                repo, cache_dir=carpeta_modelos, local_files_only=True).eval()
        except OSError as e:
            raise ModeloNoEncontrado(f"No se encontró el modelo {repo} en {carpeta_modelos}. "
                                     "Ejecuta scripts\\instalar.bat una vez (es el único paso que usa internet).") from e
        if self.dispositivo != "cpu":
            self.model = self.model.to(self.dispositivo)

    def detectar(self, img: Image.Image, conf: float = 0.5) -> list[Firma]:
        with torch.no_grad():
            entrada = self.processor(images=img, return_tensors="pt")
            if self.dispositivo != "cpu":
                entrada = entrada.to(self.dispositivo)
            out = self.model(**entrada)
            if self.dispositivo != "cpu":
                out.logits, out.pred_boxes = out.logits.cpu(), out.pred_boxes.cpu()
        r = self.processor.post_process_object_detection(out, threshold=conf, target_sizes=[(img.height, img.width)])[0]
        detecciones = cajas.unir_superpuestas([(*box, score) for box, score in zip(r["boxes"].tolist(), r["scores"].tolist())])
        if self.verificar_tinta:
            detecciones = zona_firma.revisar(img, detecciones)
        else:
            detecciones = [(*d, "modelo") for d in detecciones]
        firmas = []
        for bx1, by1, bx2, by2, score, origen in detecciones:
            if origen == "modelo":
                x1, y1, x2, y2 = cajas.ajustar_a_tinta(img, round(bx1), round(by1), round(bx2), round(by2))
            else:
                x1, y1, x2, y2, score = bx1, by1, bx2, by2, CONF_TINTA
            firmas.append(Firma(int(x1), int(y1), int(x2), int(y2), round(float(score), 4), origen))
        firmas.sort(key=lambda f: f.confianza, reverse=True)
        return firmas
