"""
Motor OCR 100 % local.

Usa RapidOCR (modelos PaddleOCR en formato ONNX que vienen DENTRO del paquete pip),
por lo que no se descarga ni se consume ningún servicio externo.

Flujo:
    archivo -> cargar imagen -> orientar -> evaluar calidad -> reforzar si hace falta
            -> OCR -> lista de "cajas" de texto con posición y confianza

Si la foto está borrosa, oscura o la letra a mano sale muy fragmentada, se aplican
variantes extra de preprocesado (nitidez, umbral, trazo más grueso) y se queda
la lectura con mejor puntaje. En imágenes nítidas solo se usa un paso, para no
perder velocidad.
"""
import logging
import threading
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from rapidocr_onnxruntime import RapidOCR

from config import ANCHO_OCR, ANCHO_OCR_DIFICIL, CONFIANZA_MINIMA, CONFIANZA_MINIMA_DIFICIL
from numeros_letras import contar_palabras_numericas, letras_a_numero

log = logging.getLogger(__name__)

_motor = RapidOCR()
_candado = threading.Lock()  # el motor ONNX se usa desde un solo hilo a la vez

# Umbrales para decidir si la imagen es difícil (foto de celular, escaneo sucio, etc.)
# El fondo del cheque es blanco: un brillo alto NO significa sobreexposición.
UMBRAL_NITIDEZ = 80.0
UMBRAL_CONTRASTE = 24.0
UMBRAL_OSCURA = 70.0
UMBRAL_QUEMADA = 248.0
CAJAS_MINIMAS = 6


@dataclass
class Caja:
    """Un fragmento de texto detectado. Coordenadas relativas (0 a 1) a la imagen."""
    texto: str
    confianza: float
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def alto(self) -> float:
        return self.y1 - self.y0


# --------------------------------------------------------------------------- #
# Carga de archivos
# --------------------------------------------------------------------------- #
def cargar_imagen(ruta: Path) -> np.ndarray:
    """Devuelve la imagen en BGR. Soporta imágenes comunes y la 1ra página de un PDF."""
    if ruta.suffix.lower() == ".pdf":
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(ruta))
        pagina = pdf[0].render(scale=300 / 72).to_pil().convert("RGB")
        pdf.close()
        return cv2.cvtColor(np.array(pagina), cv2.COLOR_RGB2BGR)

    # np.fromfile + imdecode permite rutas con tildes/espacios en Windows
    datos = np.fromfile(str(ruta), dtype=np.uint8)
    imagen = cv2.imdecode(datos, cv2.IMREAD_COLOR)
    if imagen is None:
        raise ValueError(f"No se pudo leer la imagen: {ruta.name}")
    return imagen


# --------------------------------------------------------------------------- #
# Calidad de la imagen
# --------------------------------------------------------------------------- #
def evaluar_calidad(imagen: np.ndarray) -> dict:
    """Mide nitidez, brillo y contraste para saber si hay que reforzar el preprocesado."""
    gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)
    nitidez = float(cv2.Laplacian(gris, cv2.CV_64F).var())
    brillo = float(gris.mean())
    contraste = float(gris.std())
    alto, ancho = gris.shape
    problemas = []
    if nitidez < UMBRAL_NITIDEZ:
        problemas.append("borrosa")
    if contraste < UMBRAL_CONTRASTE:
        problemas.append("bajo contraste")
    if brillo < UMBRAL_OSCURA:
        problemas.append("oscura")
    elif brillo > UMBRAL_QUEMADA and contraste < UMBRAL_CONTRASTE:
        problemas.append("sobreexpuesta")
    if min(alto, ancho) < 500:
        problemas.append("resolución baja")
    return {
        "nitidez": round(nitidez, 1),
        "brillo": round(brillo, 1),
        "contraste": round(contraste, 1),
        "ancho": int(ancho),
        "alto": int(alto),
        "problemas": problemas,
        "dificil": bool(problemas),
    }


# --------------------------------------------------------------------------- #
# Preprocesamiento
# --------------------------------------------------------------------------- #
def normalizar_tamano(imagen: np.ndarray, ancho_objetivo: int) -> np.ndarray:
    alto, ancho = imagen.shape[:2]
    if ancho <= 0:
        return imagen
    escala = ancho_objetivo / ancho
    interpolacion = cv2.INTER_CUBIC if escala > 1 else cv2.INTER_AREA
    return cv2.resize(imagen, None, fx=escala, fy=escala, interpolation=interpolacion)


def corregir_inclinacion(imagen: np.ndarray) -> np.ndarray:
    """Endereza un escaneo torcido unos pocos grados. Si no detecta borde claro, no toca nada."""
    gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)
    bordes = cv2.Canny(gris, 50, 150)
    coords = np.column_stack(np.where(bordes > 0))
    if len(coords) < 400:
        return imagen
    angulo = cv2.minAreaRect(coords)[-1]
    if angulo < -45:
        angulo = 90 + angulo
    if abs(angulo) < 0.6 or abs(angulo) > 12:
        return imagen
    alto, ancho = imagen.shape[:2]
    matriz = cv2.getRotationMatrix2D((ancho / 2, alto / 2), angulo, 1.0)
    return cv2.warpAffine(imagen, matriz, (ancho, alto), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_REPLICATE)


def _ajustar_gamma(imagen: np.ndarray, gamma: float) -> np.ndarray:
    tabla = np.array([(i / 255.0) ** (1.0 / gamma) * 255 for i in range(256)]).astype("uint8")
    return cv2.LUT(imagen, tabla)


def mejorar_contraste(imagen: np.ndarray, clip: float = 2.0) -> np.ndarray:
    """CLAHE sobre la luminancia: resalta tinta (sobre todo bolígrafo) sin destruir el fondo."""
    lab = cv2.cvtColor(imagen, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l = cv2.createCLAHE(clipLimit=clip, tileGridSize=(8, 8)).apply(l)
    return cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)


def nitidez_extra(imagen: np.ndarray) -> np.ndarray:
    """Máscara de enfoque: recupera bordes en fotos movidas o escaneos suaves."""
    desenfoque = cv2.GaussianBlur(imagen, (0, 0), 1.4)
    return cv2.addWeighted(imagen, 1.7, desenfoque, -0.7, 0)


def quitar_ruido(imagen: np.ndarray) -> np.ndarray:
    return cv2.fastNlMeansDenoisingColored(imagen, None, 7, 7, 7, 21)


def trazo_mas_grueso(imagen: np.ndarray) -> np.ndarray:
    """Engrosa la tinta fina manuscrita para que el detector no la pierda."""
    gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    tinta = cv2.morphologyEx(255 - gris, cv2.MORPH_CLOSE, kernel, iterations=1)
    return cv2.cvtColor(255 - tinta, cv2.COLOR_GRAY2BGR)


def binarizar_adaptativa(imagen: np.ndarray) -> np.ndarray:
    """Fondo blanco y tinta negra. Sirve en cheques descoloridos o con fondo sucio."""
    gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)
    gris = cv2.bilateralFilter(gris, 7, 50, 50)
    binaria = cv2.adaptiveThreshold(
        gris, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 12)
    return cv2.cvtColor(binaria, cv2.COLOR_GRAY2BGR)


def variantes_preproceso(imagen: np.ndarray, calidad: dict) -> list[tuple[str, np.ndarray]]:
    """
    Lista de (nombre, imagen) a probar. La primera siempre es la rápida.
    Las extras solo se usan si la imagen es difícil o si el primer OCR sale pobre.
    """
    base = mejorar_contraste(imagen)
    variantes = [("contraste", base)]
    if not calidad["dificil"]:
        return variantes

    if "oscura" in calidad["problemas"]:
        variantes.append(("gamma_oscura", mejorar_contraste(_ajustar_gamma(imagen, 1.6), clip=3.0)))
    if "sobreexpuesta" in calidad["problemas"]:
        variantes.append(("gamma_clara", mejorar_contraste(_ajustar_gamma(imagen, 0.7), clip=2.5)))
    if "borrosa" in calidad["problemas"] or "resolución baja" in calidad["problemas"]:
        variantes.append(("nitidez", nitidez_extra(base)))
        variantes.append(("ruido_nitidez", nitidez_extra(quitar_ruido(imagen))))
    if "bajo contraste" in calidad["problemas"] or "oscura" in calidad["problemas"]:
        variantes.append(("binaria", binarizar_adaptativa(imagen)))
        variantes.append(("contraste_fuerte", mejorar_contraste(imagen, clip=4.0)))
    variantes.append(("trazo", trazo_mas_grueso(base)))
    return variantes


# --------------------------------------------------------------------------- #
# OCR
# --------------------------------------------------------------------------- #
def _ejecutar_ocr(imagen: np.ndarray, confianza_minima: float) -> list[Caja]:
    alto, ancho = imagen.shape[:2]
    with _candado:
        # El clasificador de orientación duplica el tiempo y los cheques ya llegan horizontales
        resultado, _ = _motor(imagen, use_cls=False)

    cajas = []
    for puntos, texto, confianza in resultado or []:
        confianza = float(confianza)
        texto = str(texto).strip()
        if not texto or confianza < confianza_minima:
            continue
        xs = [p[0] for p in puntos]
        ys = [p[1] for p in puntos]
        cajas.append(Caja(
            texto=texto,
            confianza=confianza,
            x0=min(xs) / ancho, y0=min(ys) / alto,
            x1=max(xs) / ancho, y1=max(ys) / alto,
        ))
    return cajas


def _puntaje(cajas: list[Caja]) -> float:
    """Suma de confianza ponderada por longitud: sirve para comparar dos lecturas."""
    return sum(c.confianza * len(c.texto) for c in cajas)


def _puntaje_util(cajas: list[Caja]) -> float:
    """
    Prefiere la variante que mejor conserva montos en letras, no solo la que más texto imprime.
    Una binarización agresiva a veces 'gana' en confianza y pierde el 'mil' manuscrito.
    """
    texto = " ".join(c.texto for c in cajas)
    puntos = _puntaje(cajas)
    puntos += 12 * contar_palabras_numericas(texto)
    if letras_a_numero(texto) is not None:
        puntos += 40
    if any(c for c in cajas if "/" in c.texto and any(ch.isdigit() for ch in c.texto)):
        puntos += 8
    return puntos


def _lectura_pobre(cajas: list[Caja]) -> bool:
    if len(cajas) < CAJAS_MINIMAS:
        return True
    if _puntaje(cajas) < 18:
        return True
    # Muchas cajas cortas = letra a mano partida letra por letra
    cortas = sum(1 for c in cajas if len(c.texto) <= 2)
    return cortas >= max(4, len(cajas) * 0.45)


def _probar_variantes(imagen: np.ndarray, calidad: dict, confianza_minima: float
                      ) -> tuple[list[Caja], np.ndarray, str]:
    mejor_cajas, mejor_imagen, mejor_nombre = [], imagen, "contraste"
    for nombre, variante in variantes_preproceso(imagen, calidad):
        cajas = _ejecutar_ocr(variante, confianza_minima)
        if not mejor_cajas or _puntaje_util(cajas) > _puntaje_util(mejor_cajas) + 12:
            mejor_cajas, mejor_imagen, mejor_nombre = cajas, variante, nombre
        # En imagen nítida, si el primer paso ya lee bien no se prueban extras.
        # En imagen difícil sí se siguen probando (la letra a mano puede “leerse” mal con buen puntaje).
        if nombre == "contraste" and not calidad["dificil"] and not _lectura_pobre(cajas):
            break
    return mejor_cajas, mejor_imagen, mejor_nombre


def leer_cheque(imagen: np.ndarray) -> tuple[list[Caja], np.ndarray, dict]:
    """
    Ejecuta el OCR sobre el cheque y devuelve (cajas, imagen_usada, calidad).

    - Si la imagen está en vertical se prueban los dos giros de 90° y se queda el mejor.
    - Si está borrosa, oscura o la primera lectura es pobre, se prueban más variantes.
    """
    calidad = evaluar_calidad(imagen)
    alto, ancho = imagen.shape[:2]
    candidatas = [imagen]
    if alto > ancho * 1.2:
        candidatas = [
            cv2.rotate(imagen, cv2.ROTATE_90_CLOCKWISE),
            cv2.rotate(imagen, cv2.ROTATE_90_COUNTERCLOCKWISE),
        ]

    ancho_objetivo = ANCHO_OCR_DIFICIL if calidad["dificil"] else ANCHO_OCR
    confianza_minima = CONFIANZA_MINIMA_DIFICIL if calidad["dificil"] else CONFIANZA_MINIMA

    mejor_cajas, mejor_imagen, mejor_nombre = [], candidatas[0], "contraste"
    for candidata in candidatas:
        candidata = normalizar_tamano(corregir_inclinacion(candidata), ancho_objetivo)
        # Primera pasada siempre con contraste. Si sale pobre, se marcan extras.
        calidad_paso = dict(calidad)
        cajas, usada, nombre = _probar_variantes(candidata, calidad_paso, confianza_minima)
        if _lectura_pobre(cajas) and not calidad_paso["dificil"]:
            calidad_paso["dificil"] = True
            cajas, usada, nombre = _probar_variantes(
                candidata, calidad_paso, CONFIANZA_MINIMA_DIFICIL)
        if _puntaje_util(cajas) > _puntaje_util(mejor_cajas):
            mejor_cajas, mejor_imagen, mejor_nombre = cajas, usada, nombre

    calidad["variante_usada"] = mejor_nombre
    calidad["refuerzo"] = mejor_nombre != "contraste" or calidad["dificil"]
    log.debug("OCR: %d cajas, variante=%s, problemas=%s",
              len(mejor_cajas), mejor_nombre, calidad["problemas"])
    return mejor_cajas, mejor_imagen, calidad


def agrupar_en_renglones(cajas: list[Caja]) -> list[list[Caja]]:
    """Agrupa las cajas que están a la misma altura en renglones (ordenados de arriba a abajo)."""
    renglones: list[list[Caja]] = []
    for caja in sorted(cajas, key=lambda c: c.cy):
        if renglones:
            ultimo = renglones[-1]
            referencia = sum(c.cy for c in ultimo) / len(ultimo)
            alto_medio = sum(c.alto for c in ultimo) / len(ultimo)
            if abs(caja.cy - referencia) < max(alto_medio, caja.alto) * 0.6:
                ultimo.append(caja)
                continue
        renglones.append([caja])
    return [sorted(r, key=lambda c: c.x0) for r in renglones]
