import argparse
import atexit
import base64
import json
import sys
import time
from pathlib import Path

import cv2
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel

from back.dominio.imagen import preparar_imagen
from back.dominio.plantilla import leer_gris
from back.motor.lotes import GestorLotes

RAIZ = Path(__file__).resolve().parents[2]
PAGINA = RAIZ / "front" / "static" / "index.html"
PUERTO = 8300

ZONA_DEL_CAMPO = {"micr": "micr", "numero_cheque": "cheque_impreso", "cuenta": "cuenta_impresa",
                  "monto_numeros": "monto_numeros", "monto_letras": "monto_letras",
                  "ciudad": "ciudad_fecha", "fecha": "ciudad_fecha", "beneficiario": "beneficiario"}

config = json.loads((RAIZ / "config.json").read_text(encoding="utf-8"))
motor = None
lotes = None
plan = {}
app = FastAPI(title="PoC cheques Pichincha")

def iniciar(args=None):
    global motor, lotes, plan
    from back.motor.arranque import crear_motor, elegir_plan
    equipo, plan = elegir_plan(config, args)
    print("Cargando modelos...", flush=True)
    motor = crear_motor(config, RAIZ, equipo, plan)
    atexit.register(motor.cerrar)
    print(f"Listo en {motor.segundos_carga} s ({motor.descripcion})", flush=True)
    lotes = GestorLotes(motor, RAIZ / "resultados")

def _imagen_con_zonas(img, detalle, zonas):
    vis = cv2.cvtColor(cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC), cv2.COLOR_GRAY2BGR)
    h, w = vis.shape[:2]
    for z, (x0, y0, x1, y1) in zonas.items():
        campos_zona = [c for c, zz in ZONA_DEL_CAMPO.items() if zz == z and c in detalle]
        if z == "monto_letras_2":
            campos_zona = ["monto_letras"] if "monto_letras" in detalle else []
        if not campos_zona:
            continue
        revisar = any(detalle[c]["revisar"] for c in campos_zona)
        color = (0, 140, 255) if revisar else (60, 170, 60)
        cv2.rectangle(vis, (int(x0 * w), int(y0 * h)), (int(x1 * w) - 1, int(y1 * h) - 1), color, 2)
    return base64.b64encode(cv2.imencode(".png", vis)[1]).decode()

@app.get("/")
def inicio():
    return FileResponse(PAGINA)

@app.get("/api/config")
def ver_config():
    return {"seleccion": config["anverso"], "presupuesto": config["presupuesto_segundos_por_lado"],
            "modelo": motor.modelo, "segundos_carga": motor.segundos_carga,
            "ejecucion": {**plan, "descripcion": motor.descripcion, "en_curso": motor.en_curso}}

@app.post("/api/analizar")
async def analizar(imagen: UploadFile = File(...), seleccion: str = Form("{}")):
    t0 = time.perf_counter()
    datos = await imagen.read()
    servidor = {"leer_subida": time.perf_counter() - t0}
    try:
        sel = json.loads(seleccion)
    except json.JSONDecodeError:
        raise HTTPException(400, "Selección inválida")
    try:
        r, img, servidor["espera_cola"] = await run_in_threadpool(motor.analizar, datos, sel)
    except ValueError as e:
        raise HTTPException(400, str(e))
    t = time.perf_counter()
    r["imagen_zonas"] = _imagen_con_zonas(img, r["detalle"], r["localizacion"]["zonas"])
    servidor["dibujar_zonas"] = time.perf_counter() - t
    servidor["total"] = time.perf_counter() - t0
    r["tiempos_servidor_s"] = {k: round(v, 3) for k, v in servidor.items()}
    r["tamano_bytes"] = len(datos)
    r["archivo"] = imagen.filename
    return r

class PedidoLote(BaseModel):
    ruta: str
    subcarpetas: bool = False
    seleccion: dict = {}

def _lote(id_lote):
    lote = lotes.lotes.get(id_lote)
    if not lote:
        raise HTTPException(404, "Lote no encontrado (¿se reinició el servidor?)")
    return lote

@app.post("/api/lotes")
def crear_lote(p: PedidoLote):
    try:
        lote = lotes.crear(p.ruta, p.subcarpetas, {**config["anverso"], **p.seleccion})
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"id": lote.id, "total": len(lote.imagenes), "con_verdad": bool(lote.verdad)}

@app.get("/api/lotes/{id_lote}")
def ver_lote(id_lote: str, desde: int = 0):
    return _lote(id_lote).resumen(desde)

@app.post("/api/lotes/{id_lote}/cancelar")
def cancelar_lote(id_lote: str):
    _lote(id_lote).cancelar = True
    return {"ok": True}

@app.get("/api/lotes/{id_lote}/excel")
def excel_lote(id_lote: str):
    lote = _lote(id_lote)
    if not lote.excel:
        raise HTTPException(409, "El Excel estará listo cuando termine el lote")
    return FileResponse(lote.excel, filename=lote.excel.name)

@app.get("/api/lotes/{id_lote}/imagen/{indice}")
def imagen_lote(id_lote: str, indice: int):
    lote = _lote(id_lote)
    if not 0 <= indice < len(lote.resultados):
        raise HTTPException(404, "Imagen fuera de rango")
    fila = lote.resultados[indice]
    img = preparar_imagen(leer_gris(lote.carpeta / fila["archivo"]))
    return {"imagen_zonas": _imagen_con_zonas(img, fila.get("detalle", {}), fila.get("zonas", {}))}

def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="PoC cheques: interfaz web local")
    ap.add_argument("--dispositivo", choices=["cpu", "gpu"], help="sin preguntar: dónde ejecutar los modelos")
    ap.add_argument("--paralelos", "--procesos", type=int, dest="paralelos",
                    help="sin preguntar: cheques a la vez sobre los mismos modelos (1 = modo actual)")
    ap.add_argument("--gpu", type=int, help="índice de la GPU a usar (por omisión la de más memoria libre)")
    ap.add_argument("--sin-preguntar", action="store_true", help='usar la sección "ejecucion" de config.json')
    ap.add_argument("--abrir-navegador", action="store_true", help="abrir el navegador cuando los modelos estén listos")
    a = ap.parse_args(argv)
    iniciar({"dispositivo": a.dispositivo, "paralelos": a.paralelos, "gpu": a.gpu, "sin_preguntar": a.sin_preguntar})
    print(f"Abrir http://127.0.0.1:{PUERTO}", flush=True)
    if a.abrir_navegador:
        import threading
        import webbrowser
        threading.Timer(1.5, webbrowser.open, args=(f"http://127.0.0.1:{PUERTO}",)).start()
    uvicorn.run(app, host="127.0.0.1", port=PUERTO, log_level="warning")

if __name__ == "__main__":
    main()
