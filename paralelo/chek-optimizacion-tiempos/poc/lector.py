"""Lector rápido de líneas de texto: PaddleOCR (PP-OCR) en ONNX vía RapidOCR, solo reconocimiento.

No usa el detector de texto: la plantilla ya dice dónde está cada campo, así cada zona se lee
en ~0,1-0,2 s en CPU. Cada zona se lee en varias versiones (limpia, en gris, a otra escala)
para que las reglas elijan la lectura más coherente.
"""

import logging

import cv2
import numpy as np
from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR
from rapidocr.ch_ppocr_rec.typings import TextRecInput

# Modelos de reconocimiento que se pueden comparar en la evaluación
MODELOS = {
    "v6_small": {"Rec.ocr_version": OCRVersion.PPOCRV6, "Rec.model_type": ModelType.SMALL},
    "v6_medium": {"Rec.ocr_version": OCRVersion.PPOCRV6, "Rec.model_type": ModelType.MEDIUM},
    "v5_latin": {"Rec.ocr_version": OCRVersion.PPOCRV5, "Rec.lang_type": LangRec.LATIN,
                 "Rec.model_type": ModelType.MOBILE},
    "v5_server": {"Rec.ocr_version": OCRVersion.PPOCRV5, "Rec.lang_type": LangRec.CH,
                  "Rec.model_type": ModelType.SERVER},
}


def params_onnx(hilos=None, gpu=None):
    """Parámetros extra de RapidOCR/ONNX. Sin argumentos no cambia nada (modo original).

    hilos: núcleos para este proceso (cuando hay varios procesos en paralelo).
    gpu: índice de GPU CUDA (solo si onnxruntime-gpu está instalado).
    """
    p = {}
    if hilos:
        p["EngineConfig.onnxruntime.intra_op_num_threads"] = int(hilos)
        p["EngineConfig.onnxruntime.inter_op_num_threads"] = 1
    if gpu is not None:
        p["EngineConfig.onnxruntime.use_cuda"] = True
        p["EngineConfig.onnxruntime.cuda_ep_cfg.device_id"] = int(gpu)
        # Las zonas tienen anchos distintos: la búsqueda EXHAUSTIVE se repetiría con cada forma nueva
        p["EngineConfig.onnxruntime.cuda_ep_cfg.cudnn_conv_algo_search"] = "DEFAULT"
    return p


def limpiar(gris, escala=3, binarizar=True):
    """Amplía la zona, quita el fondo de seguridad y, si binariza, las líneas impresas."""
    c = cv2.resize(gris, None, fx=escala, fy=escala, interpolation=cv2.INTER_CUBIC)
    k = (10 * escala + 1) | 1
    norm = cv2.divide(c, cv2.medianBlur(c, min(k, 255)), scale=255)
    if not binarizar:
        return norm
    _, bw = cv2.threshold(norm, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    tinta = 255 - bw
    lineas = cv2.morphologyEx(tinta, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (30 * escala, 1)))
    return cv2.medianBlur(255 - cv2.subtract(tinta, lineas), 3)


def proporcion_tinta(gris):
    """Fracción de píxeles con tinta en la zona (para saber si un renglón está vacío)."""
    limpio = limpiar(gris, escala=1)
    return float((limpio < 128).mean())


VARIANTES = {
    "limpio_x3": lambda g: limpiar(g, 3, True),
    "gris_x3": lambda g: limpiar(g, 3, False),
    "limpio_x2": lambda g: limpiar(g, 2, True),
}


class Lector:
    def __init__(self, modelo="v6_small", onnx=None):
        params = {"Global.log_level": "error", "Global.use_det": False, "Global.use_cls": False}
        params.update(MODELOS[modelo])
        params.update(onnx or {})
        self.modelo = modelo
        self.motor = RapidOCR(params=params)
        logging.getLogger("RapidOCR").setLevel(logging.ERROR)
        self.motor(np.full((48, 320, 3), 255, np.uint8), use_det=False, use_cls=False)   # calentamiento

    def leer(self, imagenes):
        """Lee una lista de imágenes en gris (una línea cada una). Devuelve [(texto, confianza)]."""
        bgr = [cv2.cvtColor(i, cv2.COLOR_GRAY2BGR) for i in imagenes]
        r = self.motor.text_rec(TextRecInput(img=bgr))
        return list(zip(r.txts, r.scores))

    def leer_zona(self, gris, variantes=("limpio_x3", "gris_x3", "limpio_x2")):
        """Lee una zona en varias versiones. Devuelve [{variante, texto, confianza}]."""
        imgs = [VARIANTES[v](gris) for v in variantes]
        return [{"variante": v, "texto": t, "confianza": round(float(s), 3)}
                for v, (t, s) in zip(variantes, self.leer(imgs))]

    def leer_con_probabilidades(self, imagenes, variantes, con_matriz=()):
        """Lee versiones ya preparadas de una zona ({variante: imagen}) en UNA pasada del modelo.

        Devuelve ([{variante, texto, confianza}], {variante: matriz T x C}) para las de `con_matriz`.
        Las versiones de una zona tienen la misma proporción, así que el lote no agrega relleno y
        las matrices son las mismas que daría probabilidades() leyendo cada una aparte.
        """
        rec = self.motor.text_rec
        _, alto, ancho = rec.rec_image_shape[:3]
        proporciones = [imagenes[v].shape[1] / imagenes[v].shape[0] for v in variantes]
        ratio = max([ancho / alto] + proporciones)
        lote = np.stack([rec.resize_norm_img(cv2.cvtColor(imagenes[v], cv2.COLOR_GRAY2BGR), ratio)
                         for v in variantes]).astype(np.float32)
        P = rec.session(lote)
        lineas, _ = rec.postprocess_op(P, False, wh_ratio_list=proporciones, max_wh_ratio=ratio)
        lecturas = [{"variante": v, "texto": t, "confianza": round(float(s), 3)} for v, (t, s) in zip(variantes, lineas)]
        return lecturas, {v: P[i] for i, v in enumerate(variantes) if v in con_matriz}

    def probabilidades(self, gris):
        """Matriz de probabilidades por cuadro (T x C) del reconocedor, para puntuar candidatos."""
        rec = self.motor.text_rec
        bgr = cv2.cvtColor(gris, cv2.COLOR_GRAY2BGR)
        _, alto, ancho = rec.rec_image_shape[:3]
        ratio = max(ancho / alto, bgr.shape[1] / bgr.shape[0])
        entrada = rec.resize_norm_img(bgr, ratio)[np.newaxis].astype(np.float32)
        return rec.session(entrada)[0]

    @property
    def caracteres(self):
        return self.motor.text_rec.postprocess_op.character


    def inicio_digitos(self, gris, variantes=("limpio_x3", "gris_x3")):
        """Fracción del ancho donde empiezan los dígitos si antes hay letras impresas ('US$ 475.60').

        Usa el camino más probable del reconocedor: cada cuadro corresponde a una franja de la imagen.
        Devuelve 0 si la lectura ya empieza con dígitos o no hay prefijo claro de letras.
        """
        caracteres = self.caracteres
        cortes = []
        for v in variantes:
            P = self.probabilidades(VARIANTES[v](gris))
            camino = P.argmax(1)
            leidos = [(t, caracteres[i]) for t, i in enumerate(camino) if i != 0 and (t == 0 or camino[t - 1] != i)]
            letras = 0
            for k, (t, ch) in enumerate(leidos):
                siguientes = "".join(c for _, c in leidos[k:k + 3])
                if ch.isdigit() and sum(c.isdigit() for c in siguientes) >= 2:
                    if letras >= 2:
                        # el modelo trabaja sobre la imagen escalada a su alto con relleno: T cuadros = ancho útil
                        _, alto, _ = self.motor.text_rec.rec_image_shape[:3]
                        ancho_util = VARIANTES[v](gris).shape[1] * alto / VARIANTES[v](gris).shape[0]
                        cortes.append(max(0.0, (t - 1) * len(P) / len(P) * 8 / ancho_util))
                    break
                if ch.isalpha() or ch in "$":
                    letras += 1
        return min(cortes) if cortes else 0.0


def quitar_impreso_a_la_izquierda(gris):
    """Recorta lo impreso pequeño ('US$') que queda a la izquierda del primer trazo manuscrito alto.

    Los dígitos escritos a mano son bastante más altos que las letras impresas de la etiqueta.
    Devuelve (recorte, x_corte); x_corte = 0 si no hay nada que quitar.
    """
    limpio = limpiar(gris, escala=2)
    tinta = (limpio < 128).astype(np.uint8)
    n, _, st, _ = cv2.connectedComponentsWithStats(tinta)
    comps = [s for s in st[1:] if s[4] >= 6]
    if len(comps) < 2:
        return gris, 0
    alto_max = max(s[3] for s in comps)
    altos = [s for s in comps if s[3] >= 0.55 * alto_max]
    x_alto = min(s[0] for s in altos)
    chicos = [s for s in comps if s[0] + s[2] <= x_alto and s[3] < 0.55 * alto_max]
    if len(chicos) < 2:   # al menos dos letras impresas antes ('U', 'S'): si no, no se toca
        return gris, 0
    x = max(0, x_alto // 2 - 2)
    return gris[:, x:], x
