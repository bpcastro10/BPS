"""
Procesa la carpeta de cheques de forma incremental.

- Cada archivo se identifica por su huella SHA-1: si ya fue analizado no se vuelve a leer
  (aunque se renombre). Solo los archivos NUEVOS pasan por el OCR.
- Los resultados se guardan en datos/resultados.json para conservarlos entre reinicios.
- Un hilo en segundo plano revisa la carpeta cada INTERVALO_REVISION_SEG segundos.
"""
import hashlib
import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2

from config import (ARCHIVO_RESULTADOS, CARPETA_CHEQUES, CARPETA_VISTAS,
                    EXTENSIONES_VALIDAS, INTERVALO_REVISION_SEG)
from extractor import extraer_campos
from ocr_motor import cargar_imagen, leer_cheque

log = logging.getLogger(__name__)

_candado = threading.Lock()
_estado = {"procesando": None, "pendientes": 0, "ultima_revision": None}


# --------------------------------------------------------------------------- #
# Persistencia
# --------------------------------------------------------------------------- #
def cargar_resultados() -> list[dict]:
    if ARCHIVO_RESULTADOS.exists():
        return json.loads(ARCHIVO_RESULTADOS.read_text(encoding="utf-8"))
    return []


def guardar_resultados(resultados: list[dict]) -> None:
    temporal = ARCHIVO_RESULTADOS.with_suffix(".tmp")
    temporal.write_text(json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8")
    temporal.replace(ARCHIVO_RESULTADOS)


def huella(ruta: Path) -> str:
    return hashlib.sha1(ruta.read_bytes()).hexdigest()


# --------------------------------------------------------------------------- #
# Análisis de un cheque
# --------------------------------------------------------------------------- #
def analizar_archivo(ruta: Path, id_resultado: int, sha1: str) -> dict:
    inicio = time.perf_counter()
    registro = {
        "id": id_resultado,
        "archivo": ruta.name,
        "sha1": sha1,
        "fecha_proceso": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        imagen = cargar_imagen(ruta)
        cajas, imagen_usada, calidad = leer_cheque(imagen)
        extraido = extraer_campos(cajas)
        if calidad.get("problemas"):
            extraido.setdefault("avisos", [])
            extraido["avisos"].append(
                "Imagen poco clara: " + ", ".join(calidad["problemas"]))
            extraido["requiere_revision"] = True
        registro.update(extraido)
        registro["calidad"] = calidad
        registro["estado"] = "OK" if cajas else "SIN TEXTO"

        vista = CARPETA_VISTAS / f"{id_resultado}.jpg"
        cv2.imencode(".jpg", imagen_usada, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tofile(str(vista))
        registro["vista"] = vista.name
    except Exception as error:  # un archivo dañado no debe detener el lote
        log.exception("Error procesando %s", ruta.name)
        registro.update({
            "estado": "ERROR", "error": str(error), "campos": {}, "confianzas": {},
            "avisos": [str(error)], "requiere_revision": True, "calidad": {},
        })

    registro["tiempo_ms"] = int((time.perf_counter() - inicio) * 1000)
    log.info("Procesado %s en %d ms (%s)", ruta.name, registro["tiempo_ms"], registro["estado"])
    return registro


def archivos_en_carpeta() -> list[Path]:
    return sorted(
        (p for p in CARPETA_CHEQUES.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONES_VALIDAS),
        key=lambda p: p.stat().st_mtime,
    )


def procesar_nuevos() -> int:
    """Analiza solo los archivos que aún no están en resultados.json. Devuelve cuántos procesó."""
    with _candado:
        resultados = cargar_resultados()
        conocidos = {r["sha1"] for r in resultados}

        nuevos = []
        for ruta in archivos_en_carpeta():
            try:
                if time.time() - ruta.stat().st_mtime < 2:
                    continue  # el archivo aún se está copiando; se toma en la próxima revisión
                sha1 = huella(ruta)
            except OSError:
                continue
            if sha1 not in conocidos:
                nuevos.append((ruta, sha1))
                conocidos.add(sha1)

        _estado["pendientes"] = len(nuevos)
        siguiente_id = max((r["id"] for r in resultados), default=0) + 1
        for ruta, sha1 in nuevos:
            _estado["procesando"] = ruta.name
            resultados.append(analizar_archivo(ruta, siguiente_id, sha1))
            siguiente_id += 1
            _estado["pendientes"] -= 1
            guardar_resultados(resultados)  # se guarda tras cada cheque para verlo al instante

        _estado["procesando"] = None
        _estado["ultima_revision"] = datetime.now().strftime("%H:%M:%S")
        return len(nuevos)


def reiniciar() -> None:
    """Borra los resultados para volver a analizar toda la carpeta."""
    with _candado:
        guardar_resultados([])
        for vista in CARPETA_VISTAS.glob("*.jpg"):
            vista.unlink(missing_ok=True)


def estado() -> dict:
    return dict(_estado)


# --------------------------------------------------------------------------- #
# Vigilancia de la carpeta
# --------------------------------------------------------------------------- #
def _vigilar() -> None:
    while True:
        try:
            procesar_nuevos()
        except Exception:
            log.exception("Error revisando la carpeta")
        time.sleep(INTERVALO_REVISION_SEG)


def iniciar_vigilancia() -> None:
    threading.Thread(target=_vigilar, daemon=True, name="vigilante-cheques").start()
    log.info("Vigilando la carpeta %s cada %ss", CARPETA_CHEQUES, INTERVALO_REVISION_SEG)
