import logging

import cv2
import numpy as np
from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

MODELOS = {
    "v6_small": {"Rec.ocr_version": OCRVersion.PPOCRV6, "Rec.model_type": ModelType.SMALL},
    "v6_medium": {"Rec.ocr_version": OCRVersion.PPOCRV6, "Rec.model_type": ModelType.MEDIUM},
    "v5_latin": {"Rec.ocr_version": OCRVersion.PPOCRV5, "Rec.lang_type": LangRec.LATIN,
                 "Rec.model_type": ModelType.MOBILE},
    "v5_server": {"Rec.ocr_version": OCRVersion.PPOCRV5, "Rec.lang_type": LangRec.CH,
                  "Rec.model_type": ModelType.SERVER},
}

def params_onnx(hilos=None, gpu=None):
    p = {}
    if hilos:
        p["EngineConfig.onnxruntime.intra_op_num_threads"] = int(hilos)
        p["EngineConfig.onnxruntime.inter_op_num_threads"] = 1
    if gpu is not None:
        p["EngineConfig.onnxruntime.use_cuda"] = True
        p["EngineConfig.onnxruntime.cuda_ep_cfg.device_id"] = int(gpu)
        p["EngineConfig.onnxruntime.cuda_ep_cfg.cudnn_conv_algo_search"] = "DEFAULT"
    return p

class Lector:
    def __init__(self, modelo="v6_small", onnx=None):
        params = {"Global.log_level": "error", "Global.use_det": False, "Global.use_cls": False}
        params.update(MODELOS[modelo])
        params.update(onnx or {})
        self.modelo = modelo
        self.motor = RapidOCR(params=params)
        logging.getLogger("RapidOCR").setLevel(logging.ERROR)
        self.motor(np.full((48, 320, 3), 255, np.uint8), use_det=False, use_cls=False)

    def leer_con_probabilidades(self, imagenes, variantes, con_matriz=()):
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

    @property
    def caracteres(self):
        return self.motor.text_rec.postprocess_op.character
