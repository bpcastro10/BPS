"""Cómo se ejecutan los análisis: 1 proceso (el modo de siempre) o varios procesos en paralelo.

- MotorLocal: un solo Analizador en este proceso y un candado (un cheque a la vez). Es exactamente el
  comportamiento original; con dispositivo GPU los modelos torch (GLM-OCR, YOLOS) van a la GPU.
- PoolProcesos: N procesos, cada uno con SU Analizador (los modelos no se comparten entre procesos).
  Cada pedido va al primer proceso libre; con N procesos se analizan N cheques a la vez.

Los dos tienen la misma interfaz: analizar(ruta_o_bytes, seleccion) -> (resultado, imagen_trabajo, espera_s).
"""

import os
import queue
import sys
import threading
import time
import traceback


def config_del_proceso(config, dispositivo, hilos=None, precision_gpu="float32", onnx_gpu=False):
    """Copia de config con la sección `ejecucion` que lee el Analizador de un proceso."""
    c = dict(config)
    c["ejecucion"] = {**config.get("ejecucion", {}), "dispositivo_proceso": dispositivo, "hilos": hilos,
                      "precision_gpu": precision_gpu, "onnx_gpu": bool(onnx_gpu and dispositivo.startswith("cuda"))}
    return c


class MotorLocal:
    """Un proceso, un cheque a la vez (modo original)."""

    def __init__(self, config, raiz, descripcion):
        from poc.analizador import Analizador
        self.analizador = Analizador(config, raiz)
        self.candado = threading.Lock()
        self.procesos = 1
        self.descripcion = descripcion
        self.segundos_carga = self.analizador.segundos_carga
        self.modelo = self.analizador.lector.modelo

    def analizar(self, ruta, seleccion=None):
        t = time.perf_counter()
        with self.candado:
            espera = time.perf_counter() - t
            r = self.analizador.analizar(ruta, seleccion)
            return r, self.analizador.ultima_imagen, espera

    def cerrar(self):
        pass


# ---------------------------------------------------------------- varios procesos
def _trabajador(config, raiz, conn, indice):
    """Cuerpo de cada proceso: carga los modelos una vez y atiende pedidos hasta que se cierra."""
    hilos = (config.get("ejecucion") or {}).get("hilos")
    if hilos:   # antes de cargar torch/ONNX: que cada proceso use solo sus núcleos
        for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
            os.environ[var] = str(hilos)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:   # noqa: BLE001
        pass
    if str(raiz) not in sys.path:
        sys.path.insert(0, str(raiz))
    try:
        from poc.analizador import Analizador
        an = Analizador(config, raiz)
        conn.send(("listo", an.segundos_carga, an.lector.modelo))
    except BaseException:   # noqa: BLE001 - se informa al proceso principal
        conn.send(("fallo", traceback.format_exc()))
        return
    while True:
        try:
            pedido = conn.recv()
        except (EOFError, OSError):
            break
        if pedido is None:
            break
        ruta, seleccion = pedido
        try:
            r = an.analizar(ruta, seleccion)
            conn.send(("ok", r, an.ultima_imagen))
        except Exception as e:   # noqa: BLE001 - un cheque malo no tumba el proceso
            conn.send(("error", type(e).__name__, str(e)))


class _Proceso:
    def __init__(self, indice, dispositivo, hilos, proceso, conn):
        self.indice, self.dispositivo, self.hilos = indice, dispositivo, hilos
        self.proceso, self.conn = proceso, conn
        self.vivo = False
        self.segundos_carga = None


class PoolProcesos:
    def __init__(self, config, raiz, dispositivos, hilos, precision_gpu="float32", onnx_gpu=False,
                 simultaneos=None, descripcion=""):
        """dispositivos: uno por proceso ("cpu", "cuda:0", "cuda:1"...). simultaneos: cuántos cargan a la vez
        (cargar GLM pide mucha RAM por un momento; de a pocos no se agota)."""
        import multiprocessing as mp
        ctx = mp.get_context("spawn")   # igual en Windows y Linux; torch/CUDA no se lleva bien con fork
        t = time.perf_counter()
        self.descripcion = descripcion
        self.modelo = None
        self._libres = queue.Queue()
        self.todos = []
        simultaneos = max(1, simultaneos or len(dispositivos))
        for inicio in range(0, len(dispositivos), simultaneos):
            tanda = []
            for i in range(inicio, min(len(dispositivos), inicio + simultaneos)):
                cfg = config_del_proceso(config, dispositivos[i], hilos, precision_gpu, onnx_gpu)
                padre, hijo = ctx.Pipe()
                p = ctx.Process(target=_trabajador, args=(cfg, str(raiz), hijo, i), daemon=True,
                                name=f"analizador-{i}")
                p.start()
                hijo.close()
                w = _Proceso(i, dispositivos[i], hilos, p, padre)
                self.todos.append(w)
                tanda.append(w)
                print(f"  proceso {i + 1}/{len(dispositivos)} ({dispositivos[i]}"
                      f"{f', {hilos} hilos' if hilos else ''}): cargando modelos...", flush=True)
            for w in tanda:
                try:
                    msg = w.conn.recv()
                except (EOFError, OSError):
                    msg = ("fallo", "el proceso terminó sin avisar (¿falta de memoria?)")
                if msg[0] == "listo":
                    w.vivo, w.segundos_carga, self.modelo = True, msg[1], msg[2]
                    self._libres.put(w)
                    print(f"  proceso {w.indice + 1} listo en {msg[1]} s", flush=True)
                else:
                    print(f"  [AVISO] el proceso {w.indice + 1} no pudo cargar:\n{msg[1]}", flush=True)
                    w.proceso.join(timeout=5)
        self.procesos = sum(w.vivo for w in self.todos)
        if not self.procesos:
            raise RuntimeError("Ningún proceso de análisis pudo cargar los modelos (ver mensajes de arriba)")
        if self.procesos < len(dispositivos):
            print(f"  [AVISO] quedaron {self.procesos} de {len(dispositivos)} procesos", flush=True)
            self.descripcion += f" (activos {self.procesos})"
        self.segundos_carga = round(time.perf_counter() - t, 2)

    def analizar(self, ruta, seleccion=None):
        t = time.perf_counter()
        while True:
            if not any(w.vivo for w in self.todos):
                raise RuntimeError("No quedan procesos de análisis activos: reinicia el servidor")
            try:
                w = self._libres.get(timeout=2)
            except queue.Empty:
                continue
            if w.vivo:
                break
        espera = time.perf_counter() - t
        try:
            w.conn.send((ruta, seleccion))
            msg = w.conn.recv()
        except (EOFError, OSError, BrokenPipeError):
            w.vivo = False   # no vuelve a la cola
            self.procesos = sum(x.vivo for x in self.todos)
            raise RuntimeError(f"El proceso de análisis {w.indice + 1} se cerró (¿falta de memoria?)")
        self._libres.put(w)
        if msg[0] == "ok":
            return msg[1], msg[2], espera
        if msg[1] == "ValueError":
            raise ValueError(msg[2])
        raise RuntimeError(f"{msg[1]}: {msg[2]}")

    def cerrar(self):
        for w in self.todos:
            try:
                w.conn.send(None)
            except Exception:   # noqa: BLE001
                pass
        for w in self.todos:
            w.proceso.join(timeout=3)
            if w.proceso.is_alive():
                w.proceso.terminate()
