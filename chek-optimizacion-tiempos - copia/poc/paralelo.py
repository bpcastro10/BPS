"""Cómo se ejecutan los análisis: UN solo juego de modelos cargado, compartido por N análisis simultáneos.

Los modelos se cargan una sola vez (un Analizador). Con `paralelos` = N, hasta N cheques se analizan a la
vez en hilos distintos del mismo proceso, usando esos mismos modelos:
- ONNX Runtime (PaddleOCR) y torch (GLM-OCR, YOLOS) en modo inferencia admiten llamadas simultáneas sobre
  el mismo modelo y sueltan el GIL mientras calculan, así que los hilos avanzan de verdad en paralelo.
- Lo propio de cada cheque (la imagen de trabajo) es por hilo; nada se mezcla entre cheques.
- No se duplica la RAM ni la VRAM de los modelos: cada análisis extra solo suma su memoria de trabajo.

Con N = 1 es exactamente el modo original: un cheque a la vez.

Interfaz: analizar(ruta_o_bytes, seleccion) -> (resultado, imagen_trabajo, espera_s).
"""

import threading
import time


def config_de_ejecucion(config, dispositivo="cpu", hilos_torch=None, precision_gpu="float32", onnx_gpu=False):
    """Copia de config con la sección `ejecucion` que lee el Analizador."""
    c = dict(config)
    c["ejecucion"] = {**config.get("ejecucion", {}), "dispositivo_proceso": dispositivo, "hilos_torch": hilos_torch,
                      "precision_gpu": precision_gpu, "onnx_gpu": bool(onnx_gpu and dispositivo.startswith("cuda"))}
    return c


class Motor:
    def __init__(self, config, raiz, paralelos=1, descripcion=""):
        from poc.analizador import Analizador
        self.analizador = Analizador(config, raiz)   # los modelos se cargan UNA vez
        self.paralelos = max(1, int(paralelos))
        # Cupo de análisis simultáneos sobre los mismos modelos (con 1 es el candado de siempre)
        self._cupo = threading.BoundedSemaphore(self.paralelos)
        self._en_curso = 0
        self._contador = threading.Lock()
        self.descripcion = descripcion
        self.segundos_carga = self.analizador.segundos_carga
        self.modelo = self.analizador.lector.modelo

    @property
    def en_curso(self):
        return self._en_curso

    def analizar(self, ruta, seleccion=None):
        t = time.perf_counter()
        with self._cupo:
            espera = time.perf_counter() - t
            with self._contador:
                self._en_curso += 1
            try:
                r = self.analizador.analizar(ruta, seleccion)
                # ultima_imagen es por hilo: es la de ESTE cheque aunque haya otros en curso
                return r, self.analizador.ultima_imagen, espera
            finally:
                with self._contador:
                    self._en_curso -= 1

    def cerrar(self):
        pass
