"""Contrato del OCR. El análisis de un cheque solo usa esto.

Para enchufar otro OCR (sin tocar el motor, las reglas ni el Excel):

1. Crea un módulo con una función
       crear(config, gpu_onnx) -> ComponentesOcr
   - lector y lector_secundario implementan LectorOcr.
   - localizador implementa LocalizadorOcr.
   - preparar() debe usar back.dominio.imagen.preparar_imagen, porque la interfaz
     dibuja las zonas sobre esa misma imagen.
   - leer_con_probabilidades devuelve matrices T x C (numpy) alineadas con
     `caracteres` (el índice 0 es el blanco del CTC). Las reglas puntúan candidatos
     contra esas matrices.
2. Agrega UNA línea en MOTORES de back/ocr/fabrica.py.
3. En config.json pon "motor_ocr" con esa clave.

Con eso el cheque se lee igual: las reglas siguen decidiendo OK o revisar.
"""

from dataclasses import dataclass
from typing import Protocol


class LectorOcr(Protocol):
    """Reconocimiento de una línea ya recortada."""

    modelo: str

    @property
    def caracteres(self):
        """Alfabeto del reconocedor, en el mismo orden que las columnas de la matriz."""

    def leer_con_probabilidades(self, imagenes, variantes, con_matriz=()):
        """imagenes: {variante: imagen gris ya preparada}.

        Devuelve (lecturas, matrices).
        lecturas: [{variante, texto, confianza}, ...] en el orden de `variantes`.
        matrices: {variante: ndarray T x C} solo para las variantes de `con_matriz`.
        """


class LocalizadorOcr(Protocol):
    """Encuentra las zonas del cheque sobre la imagen de trabajo."""

    def preparar(self, gris):
        """Devuelve la imagen de trabajo (ancho ANCHO_TRABAJO)."""

    def localizar(self, imagen):
        """Devuelve (zonas, cajas, info).

        zonas: nombre -> (x0, y0, x1, y1) en píxeles de `imagen`.
        info incluye banco_impreso, notas, impresos y el resto que ya arma el localizador actual.
        """


@dataclass
class ComponentesOcr:
    """Piezas que el analizador pide al motor OCR. El segundo lector puede no existir."""

    lector: LectorOcr
    localizador: LocalizadorOcr
    lector_secundario: LectorOcr | None = None
