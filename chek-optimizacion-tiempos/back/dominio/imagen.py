import cv2

ANCHO_TRABAJO = 592

def preparar_imagen(gris):
    h = round(gris.shape[0] * ANCHO_TRABAJO / gris.shape[1])
    interp = cv2.INTER_AREA if gris.shape[1] > ANCHO_TRABAJO else cv2.INTER_CUBIC
    return cv2.resize(gris, (ANCHO_TRABAJO, h), interpolation=interp)
