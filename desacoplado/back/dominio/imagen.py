"""Imagen de trabajo del cheque. No depende de ningún OCR ni de ningún modelo."""

import cv2

ANCHO_TRABAJO = 592     # ancho al que se lleva todo cheque (igual que el escaneo de 100 dpi)


def preparar_imagen(gris):
    """Cheque llevado a ANCHO_TRABAJO de ancho. No necesita modelos."""
    h = round(gris.shape[0] * ANCHO_TRABAJO / gris.shape[1])
    interp = cv2.INTER_AREA if gris.shape[1] > ANCHO_TRABAJO else cv2.INTER_CUBIC
    return cv2.resize(gris, (ANCHO_TRABAJO, h), interpolation=interp)
