"""Análisis de todas las imágenes de una carpeta, en segundo plano, con avance consultable.

Los lotes se procesan de a uno y comparten el motor con el análisis individual (back/motor/paralelo.py).
Con paralelos = 1 se analiza un cheque a la vez (como siempre); con N, N cheques del lote a la vez
sobre los mismos modelos ya cargados.
Los resultados quedan en memoria mientras el servidor esté encendido. Al terminar se guarda un Excel
en resultados/ (en el orden de la carpeta).
"""

import csv
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from back.dominio.comparar import CAMPOS, clasificar
from back.informe.excel import guardar_excel_lote

EXTENSIONES = {".tif", ".tiff", ".png", ".jpg", ".jpeg"}


def listar_imagenes(carpeta, subcarpetas):
    patron = carpeta.rglob("*") if subcarpetas else carpeta.glob("*")
    return sorted(p for p in patron if p.is_file() and p.suffix.lower() in EXTENSIONES)


def _leer_verdad(carpeta):
    """Respuestas correctas si la carpeta trae verdad.csv (clave: nombre del archivo)."""
    ruta = carpeta / "verdad.csv"
    if not ruta.exists():
        return {}
    with open(ruta, encoding="utf-8-sig") as f:
        return {r["archivo"]: r for r in csv.DictReader(f)}


class Lote:
    def __init__(self, carpeta, imagenes, seleccion, verdad):
        self.id = uuid.uuid4().hex[:10]
        self.carpeta = carpeta
        self.imagenes = imagenes
        self.seleccion = seleccion
        self.verdad = verdad
        self.resultados = []        # resumen por imagen (sin la imagen)
        self.estado = "en_cola"     # en_cola, procesando, terminado, cancelado
        self.cancelar = False
        self.inicio = None
        self.fin = None
        self.excel = None

    def resumen(self, desde=0):
        hechos = len(self.resultados)
        tiempos = [r["tiempo_s"] for r in self.resultados if r.get("tiempo_s") is not None]
        transcurrido = (self.fin or time.time()) - self.inicio if self.inicio else 0
        restante = (transcurrido / hechos) * (len(self.imagenes) - hechos) if hechos and self.estado == "procesando" else 0
        conteo = {"OK": 0, "REVISAR": 0, "ERROR": 0}
        for r in self.resultados:
            conteo[r["estado"]] += 1
        acierto = {}
        if self.verdad:
            for c in CAMPOS:
                k = {"ok_auto": 0, "ok_revisar": 0, "error_revisar": 0, "error_auto": 0}
                for r in self.resultados:
                    t = (r.get("comparacion") or {}).get(c)
                    if t:
                        k[t] += 1
                if sum(k.values()):
                    acierto[c] = k
        return {
            "id": self.id, "carpeta": str(self.carpeta), "estado": self.estado, "total": len(self.imagenes),
            "hechos": hechos, "conteo": conteo, "con_verdad": bool(self.verdad), "acierto": acierto,
            "tiempo_promedio_s": round(sum(tiempos) / len(tiempos), 2) if tiempos else None,
            "tiempo_maximo_s": round(max(tiempos), 2) if tiempos else None,
            "segundos_transcurridos": round(transcurrido, 1), "segundos_restantes": round(restante),
            "excel": bool(self.excel),
            "resultados": self.resultados[desde:], "desde": desde,
        }


class GestorLotes:
    def __init__(self, motor, carpeta_resultados):
        self.motor = motor          # back.motor.paralelo.Motor (modelos cargados una vez)
        self.salida = Path(carpeta_resultados)
        self.lotes = {}
        self._cola = []
        self._hay_trabajo = threading.Event()
        threading.Thread(target=self._trabajar, daemon=True).start()

    def crear(self, ruta, subcarpetas, seleccion):
        carpeta = Path(ruta.strip().strip('"'))
        if not carpeta.is_dir():
            raise ValueError(f"No existe la carpeta o no es una carpeta: {carpeta}")
        imagenes = listar_imagenes(carpeta, subcarpetas)
        if not imagenes:
            raise ValueError("La carpeta no tiene imágenes (.tif, .tiff, .png, .jpg, .jpeg)")
        lote = Lote(carpeta, imagenes, seleccion, _leer_verdad(carpeta))
        self.lotes[lote.id] = lote
        self._cola.append(lote)
        self._hay_trabajo.set()
        return lote

    def _trabajar(self):
        while True:
            self._hay_trabajo.wait()
            while self._cola:
                self._procesar(self._cola.pop(0))
            self._hay_trabajo.clear()

    def _procesar(self, lote):
        lote.estado, lote.inicio = "procesando", time.time()
        n = max(1, getattr(self.motor, "paralelos", 1))
        cancelado = False
        if n == 1:   # modo original: de a un cheque, en orden
            for img in lote.imagenes:
                if lote.cancelar:
                    cancelado = True
                    break
                self._uno(lote, img)
        else:        # N análisis a la vez con los mismos modelos (los resultados llegan según terminan)
            with ThreadPoolExecutor(max_workers=n, thread_name_prefix="lote") as ex:
                pendientes = set()
                for img in lote.imagenes:
                    if lote.cancelar:
                        cancelado = True
                        break
                    if len(pendientes) >= n:
                        _, pendientes = wait(pendientes, return_when=FIRST_COMPLETED)
                    pendientes.add(ex.submit(self._uno, lote, img))
                wait(pendientes)
        lote.estado = "cancelado" if cancelado else "terminado"
        lote.fin = time.time()
        try:
            lote.excel = self._excel(lote)
        except Exception:   # noqa: BLE001 - el lote vale aunque falle el Excel
            lote.excel = None

    def _uno(self, lote, img):
        relativo = str(img.relative_to(lote.carpeta))
        fila = {"archivo": relativo}
        try:
            r, _, _ = self.motor.analizar(img, lote.seleccion)
            fila.update(estado=r["estado"], tiempo_s=r["tiempos_s"]["total"], tiempos_s=r["tiempos_s"], campos=r["campos"],
                        detalle=r["detalle"], campos_a_revisar=r["campos_a_revisar"],
                        dentro_de_presupuesto=r["dentro_de_presupuesto"],
                        validaciones=r["validaciones"], lecturas_crudas=r["lecturas_crudas"],
                        zonas=r["localizacion"]["zonas"], localizacion_notas=r["localizacion"]["notas"])
            esperado = lote.verdad.get(img.name) or lote.verdad.get(relativo)
            if esperado:
                fila["comparacion"] = {c: t for c in CAMPOS if c in r["detalle"]
                                       if (t := clasificar(c, r["detalle"][c], esperado.get(c)))}
                fila["esperado"] = {c: esperado.get(c) for c in fila["comparacion"]}
        except Exception as e:   # una imagen mala no detiene el lote
            fila.update(estado="ERROR", tiempo_s=None, error=str(e))
        lote.resultados.append(fila)

    def _excel(self, lote):
        return guardar_excel_lote(lote, self.salida)
