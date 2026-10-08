"""Detector de firmas: modelo YOLOS + verificación de tinta en la línea de firma.

No sabe nada de HTTP: el servicio REST (servicio/) lo usa, y se puede importar desde cualquier script.
"""
import io
import os
from dataclasses import asdict, dataclass

# El modelo se carga solo desde disco: nunca se consulta Hugging Face al arrancar.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

import torch
from PIL import Image
from transformers import AutoImageProcessor, AutoModelForObjectDetection

from . import cajas, zona_firma

MODELO_DEFAULT = "mdefrance/yolos-tiny-signature-detection"
# ServicioFirmas/modelos (este archivo está en ServicioFirmas/src/firmas/)
CARPETA_MODELOS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "modelos")
CONF_TINTA = 0.5  # confianza que se informa para una firma hallada por tinta (el modelo no la vio)


class ModeloNoEncontrado(RuntimeError):
    pass


@dataclass
class Firma:
    x1: int
    y1: int
    x2: int
    y2: int
    confianza: float
    origen: str  # "modelo" (la vio YOLOS) o "tinta" (trazos sobre la línea de firma que YOLOS no vio)

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

    def recorte_png(self, img: Image.Image, margen: int = 0) -> bytes:
        caja = (max(0, self.x1 - margen), max(0, self.y1 - margen),
                min(img.width, self.x2 + margen), min(img.height, self.y2 + margen))
        buf = io.BytesIO()
        img.crop(caja).save(buf, format="PNG")
        return buf.getvalue()


class DetectorFirmas:
    def __init__(self, repo: str = MODELO_DEFAULT, carpeta_modelos: str | None = None, verificar_tinta: bool = True,
                 dispositivo: str = "cpu"):
        self.repo = repo
        self.dispositivo = dispositivo  # "cpu" (original) o "cuda:N"
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
        """Firmas de la imagen (RGB), de mayor a menor confianza."""
        with torch.no_grad():
            entrada = self.processor(images=img, return_tensors="pt")
            if self.dispositivo != "cpu":
                entrada = entrada.to(self.dispositivo)
            out = self.model(**entrada)
            if self.dispositivo != "cpu":   # el posproceso arma sus tensores en CPU
                out.logits, out.pred_boxes = out.logits.cpu(), out.pred_boxes.cpu()
        r = self.processor.post_process_object_detection(out, threshold=conf, target_sizes=[(img.height, img.width)])[0]
        # YOLOS suele dar varias cajas superpuestas por la misma firma: se unen y luego se ajustan a la tinta.
        detecciones = cajas.unir_superpuestas([(*box, score) for box, score in zip(r["boxes"].tolist(), r["scores"].tolist())])
        if self.verificar_tinta:
            # Se descartan las detecciones fuera de la línea de firma (fecha, beneficiario), se separan las dos firmas
            # que el modelo junta en una caja y, si no queda ninguna, se mira si hay trazos sobre la línea: así
            # cuentan las firmas sencillas que son solo el nombre.
            detecciones = zona_firma.revisar(img, detecciones)
        else:
            detecciones = [(*d, "modelo") for d in detecciones]
        firmas = []
        for bx1, by1, bx2, by2, score, origen in detecciones:
            if origen == "modelo":
                x1, y1, x2, y2 = cajas.ajustar_a_tinta(img, round(bx1), round(by1), round(bx2), round(by2))
            else:  # la caja por tinta ya está ajustada a los trazos
                x1, y1, x2, y2, score = bx1, by1, bx2, by2, CONF_TINTA
            firmas.append(Firma(int(x1), int(y1), int(x2), int(y2), round(float(score), 4), origen))
        firmas.sort(key=lambda f: f.confianza, reverse=True)
        return firmas
