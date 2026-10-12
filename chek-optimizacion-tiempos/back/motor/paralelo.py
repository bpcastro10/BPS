import threading
import time

def config_de_ejecucion(config, dispositivo="cpu", hilos_torch=None, precision_gpu="float32", onnx_gpu=False):
    c = dict(config)
    c["ejecucion"] = {**config.get("ejecucion", {}), "dispositivo_proceso": dispositivo, "hilos_torch": hilos_torch,
                      "precision_gpu": precision_gpu, "onnx_gpu": bool(onnx_gpu and dispositivo.startswith("cuda"))}
    return c

class Motor:
    def __init__(self, config, raiz, paralelos=1, descripcion=""):
        from back.motor.analizador import Analizador
        self.analizador = Analizador(config, raiz)
        self.paralelos = max(1, int(paralelos))
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
                return r, self.analizador.ultima_imagen, espera
            finally:
                with self._contador:
                    self._en_curso -= 1

    def cerrar(self):
        pass
