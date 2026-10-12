import threading
from collections import deque

from back.dominio.plantilla import leer_gris

TOPE_BYTES = 2 * 1024 ** 3
TOPE_IMAGENES = 32
RESERVA_GB = 2.0
RAM_TRABAJO_POR_HILO_GB = 0.8

def presupuesto_ram(paralelos):
    from back.motor.hardware import _ram_gb
    _, libre_gb = _ram_gb()
    resto = libre_gb - RESERVA_GB - RAM_TRABAJO_POR_HILO_GB * max(1, paralelos)
    usar_gb = min(TOPE_BYTES / 1024 ** 3, max(0.25, resto * 0.5))
    return int(usar_gb * 1024 ** 3), min(TOPE_IMAGENES, max(paralelos, 4))

class Prefetch:
    def __init__(self, rutas, max_bytes, max_imagenes):
        self._rutas = list(rutas)
        self._max_bytes = max(1, int(max_bytes))
        self._max_imagenes = max(1, int(max_imagenes))
        self._cola = deque()
        self._bytes = 0
        self._fin = False
        self._parar = False
        self._cond = threading.Condition()
        self._hilo = threading.Thread(target=self._producir, name="ram-prefetch", daemon=True)
        self._hilo.start()

    def _cabe(self, nbytes):
        if not self._cola:
            return True
        return len(self._cola) < self._max_imagenes and self._bytes + nbytes <= self._max_bytes

    def _producir(self):
        for ruta in self._rutas:
            if self._parar:
                break
            try:
                imagen = leer_gris(ruta)
                nbytes = int(imagen.nbytes)
            except Exception as e:
                imagen, nbytes = e, 0
            with self._cond:
                while not self._parar and not self._cabe(nbytes):
                    self._cond.wait(timeout=0.2)
                if self._parar:
                    break
                self._cola.append((ruta, imagen, nbytes))
                self._bytes += nbytes
                self._cond.notify_all()
        with self._cond:
            self._fin = True
            self._cond.notify_all()

    def siguiente(self):
        with self._cond:
            while not self._cola and not self._fin and not self._parar:
                self._cond.wait(timeout=0.2)
            if not self._cola:
                return None
            ruta, imagen, nbytes = self._cola.popleft()
            self._bytes -= nbytes
            self._cond.notify_all()
            return ruta, imagen

    def cerrar(self):
        with self._cond:
            self._parar = True
            self._cond.notify_all()
        self._hilo.join(timeout=5)
