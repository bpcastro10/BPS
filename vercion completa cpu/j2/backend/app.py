"""
Servidor web (Flask) del Analizador de Cheques.

Endpoints:
    GET    /                         -> interfaz web (frontend)
    GET    /api/v1/cheques           -> resultados + estado del procesamiento
    GET    /api/v1/cheques/excel     -> descarga del Excel con todos los cheques
    POST   /api/v1/cheques/archivos  -> sube archivos a la carpeta de cheques
    POST   /api/v1/procesamientos    -> fuerza una revisión inmediata de la carpeta
    DELETE /api/v1/cheques           -> borra resultados para reanalizar todo
    GET    /api/v1/vistas/<archivo>  -> imagen del cheque analizado
"""
import logging
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory
from werkzeug.utils import secure_filename

from config import (CARPETA_CHEQUES, CARPETA_FRONTEND, CARPETA_VISTAS,
                    EXTENSIONES_VALIDAS, HOST, PUERTO)
import procesador
from exportar_excel import generar_excel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

app = Flask(__name__, static_folder=str(CARPETA_FRONTEND), static_url_path="")


@app.get("/")
def inicio():
    return send_from_directory(CARPETA_FRONTEND, "index.html")


@app.get("/api/v1/cheques")
def listar_cheques():
    resultados = procesador.cargar_resultados()
    return jsonify({
        "estado": procesador.estado(),
        "carpeta": str(CARPETA_CHEQUES),
        "total": len(resultados),
        "resultados": resultados,
    })


@app.get("/api/v1/cheques/excel")
def descargar_excel():
    archivo = generar_excel(procesador.cargar_resultados())
    nombre = f"analisis_cheques_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
    return send_file(archivo, as_attachment=True, download_name=nombre,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.post("/api/v1/cheques/archivos")
def subir_archivos():
    guardados = []
    for archivo in request.files.getlist("archivos"):
        nombre = secure_filename(archivo.filename or "")
        if nombre and Path(nombre).suffix.lower() in EXTENSIONES_VALIDAS:
            archivo.save(CARPETA_CHEQUES / nombre)
            guardados.append(nombre)
    threading.Thread(target=procesador.procesar_nuevos, daemon=True).start()
    return jsonify({"guardados": guardados}), 201


@app.post("/api/v1/procesamientos")
def procesar_ahora():
    threading.Thread(target=procesador.procesar_nuevos, daemon=True).start()
    return jsonify({"mensaje": "Revisión de carpeta iniciada"}), 202


@app.delete("/api/v1/cheques")
def reiniciar():
    procesador.reiniciar()
    threading.Thread(target=procesador.procesar_nuevos, daemon=True).start()
    return jsonify({"mensaje": "Resultados borrados; se reanalizará la carpeta"})


@app.get("/api/v1/vistas/<path:nombre>")
def ver_imagen(nombre):
    return send_from_directory(CARPETA_VISTAS, nombre)


if __name__ == "__main__":
    procesador.iniciar_vigilancia()
    log.info("Abra http://%s:%s en el navegador", HOST, PUERTO)
    app.run(host=HOST, port=PUERTO, debug=False, threaded=True)
