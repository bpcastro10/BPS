"""Lector de cheques: backend Flask.

Recibe una imagen, la lee con el modelo GLM-OCR afinado y devuelve los datos
extraídos junto con el porcentaje de confianza de cada uno.

Uso:
    python app.py
    y abre http://127.0.0.1:5000
"""

import os
import sys
import tempfile
import threading
import time
import traceback
import webbrowser
from pathlib import Path

def _check_dependencies():
    """Avisa con el comando exacto si falta alguna librería (evita errores crípticos)."""
    import importlib.util

    required = {
        "torch": "torch",
        "torchvision": "torchvision",
        "PIL": "pillow",
        "flask": "flask",
        "accelerate": "accelerate",
        "transformers": "transformers",
        "openpyxl": "openpyxl",
    }
    missing = [pip for mod, pip in required.items() if importlib.util.find_spec(mod) is None]
    if missing:
        sys.exit(
            "\nFaltan estas librerias: " + ", ".join(missing) + "\n"
            "Instalalas con este comando (usa el mismo Python que esta ejecutando esto):\n\n"
            f'  "{sys.executable}" -m pip install ' + " ".join(missing) + "\n"
        )


_check_dependencies()

import torch
from flask import Flask, jsonify, request, send_file, send_from_directory
from PIL import Image, ImageOps, UnidentifiedImageError
from transformers import AutoModelForImageTextToText, AutoProcessor

from confidence import build_token_groups, compute_confidence, parse_json
from informe import escribir_informe
from validacion import cargar_reglas, evaluar_cheque, fila_no_leida, valores_fila

# Soporte opcional para fotos HEIC/HEIF (iPhone): pip install pillow-heif
try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:
    pass

# --------------------------------------------------------------------------
# Configuración (todo se puede cambiar con variables de entorno)
# --------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
MODEL_PATH = Path(os.environ.get("MODEL_PATH", BASE_DIR / "glm_ocr_merged"))
# Debe ser el mismo texto con el que se entrenó el modelo.
PROMPT = os.environ.get(
    "OCR_PROMPT", "Extrae los datos del cheque y detecta la firma en formato JSON"
)
MAX_NEW_TOKENS = int(os.environ.get("MAX_NEW_TOKENS", "1024"))
MAX_SIDE = int(os.environ.get("MAX_SIDE", "2400"))  # lado mayor máximo, en píxeles
MAX_UPLOAD_MB = 25
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "5000"))
ENTRADA_DIR = Path(os.environ.get("ENTRADA_DIR", BASE_DIR / "entrada"))
INFORMES_DIR = Path(os.environ.get("INFORMES_DIR", BASE_DIR / "informes"))
REGLAS_PATH = Path(os.environ.get("REGLAS_PATH", BASE_DIR / "reglas.json"))
EXTENSIONES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif", ".heic", ".heif"}

ENTRADA_DIR.mkdir(exist_ok=True)
INFORMES_DIR.mkdir(exist_ok=True)

app = Flask(__name__, static_folder=str(BASE_DIR / "static"), static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

processor = None
tokenizer = None
model = None
stop_ids = set()
generation_lock = threading.Lock()  # una lectura a la vez (la GPU es una sola)
_job_lock = threading.Lock()
_job = {
    "estado": "inactivo",
    "total": 0,
    "hechos": 0,
    "actual": "",
    "error": None,
    "resultado": None,
}


def load_model():
    global processor, tokenizer, model, stop_ids

    if not (MODEL_PATH / "config.json").exists():
        sys.exit(
            f"No encuentro el modelo en: {MODEL_PATH}\n"
            "Pon la carpeta 'glm_ocr_merged' junto a app.py o define MODEL_PATH."
        )

    print(f"Cargando el modelo desde {MODEL_PATH} ...")
    processor = AutoProcessor.from_pretrained(str(MODEL_PATH), trust_remote_code=True)
    tokenizer = getattr(processor, "tokenizer", processor)
    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    model = AutoModelForImageTextToText.from_pretrained(
        str(MODEL_PATH), dtype=dtype, device_map="auto", trust_remote_code=True
    )
    model.eval()

    eos = model.generation_config.eos_token_id
    stop_ids = set(eos if isinstance(eos, (list, tuple)) else [eos])
    if model.generation_config.pad_token_id is not None:
        stop_ids.add(model.generation_config.pad_token_id)
    stop_ids.discard(None)
    print(f"Modelo listo en: {model.device}")


# --------------------------------------------------------------------------
# Inferencia
# --------------------------------------------------------------------------
@torch.inference_mode()
def read_image(image_path: str):
    """Ejecuta el modelo y devuelve (texto, ids generados, logprob de cada token)."""
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "path": image_path},
                {"type": "text", "text": PROMPT},
            ],
        }
    ]
    inputs = processor.apply_chat_template(
        messages,
        add_generation_prompt=True,
        tokenize=True,
        return_dict=True,
        return_tensors="pt",
    ).to(model.device)
    inputs.pop("token_type_ids", None)

    out = model.generate(
        **inputs,
        max_new_tokens=MAX_NEW_TOKENS,
        do_sample=False,
        output_scores=True,
        return_dict_in_generate=True,
    )

    prompt_len = inputs["input_ids"].shape[1]
    ids = out.sequences[0][prompt_len:].tolist()
    steps = min(len(ids), len(out.scores))
    ids = ids[:steps]

    # Probabilidad (en log) que el modelo dio a cada token que eligió.
    logprobs = []
    for step in range(steps):
        log_probs = torch.log_softmax(out.scores[step][0].float(), dim=-1)
        logprobs.append(log_probs[ids[step]].item())

    # Quitar los tokens de fin de texto del final.
    while ids and ids[-1] in stop_ids:
        ids.pop()
        logprobs.pop()

    def decode(token_ids):
        return tokenizer.decode(
            token_ids, skip_special_tokens=True, clean_up_tokenization_spaces=False
        )

    groups, text = build_token_groups(ids, logprobs, decode)
    overall, per_field = compute_confidence(text, groups, logprobs)
    return text.strip(), len(ids), overall, per_field


def normalizar_imagen(image: Image.Image) -> Image.Image:
    """Deja la imagen en RGB y de un tamaño razonable para el modelo."""
    image.load()  # primer fotograma si es GIF/TIFF animado
    image = ImageOps.exif_transpose(image)

    if image.mode in ("RGBA", "LA", "P"):
        image = image.convert("RGBA")
        fondo = Image.new("RGB", image.size, "white")
        fondo.paste(image, mask=image.getchannel("A"))
        image = fondo
    else:
        image = image.convert("RGB")

    largo = max(image.size)
    if largo > MAX_SIDE:
        escala = MAX_SIDE / largo
        image = image.resize(
            (round(image.width * escala), round(image.height * escala)),
            Image.Resampling.LANCZOS,
        )
    return image


def prepare_image(file_storage) -> Image.Image:
    """Abre la imagen subida desde el navegador."""
    return normalizar_imagen(Image.open(file_storage.stream))


def abrir_imagen(ruta: Path) -> Image.Image:
    """Abre una imagen de la carpeta de entrada."""
    with Image.open(ruta) as imagen:
        return normalizar_imagen(imagen)


def listar_imagenes(carpeta: Path) -> list[Path]:
    if not carpeta.is_dir():
        return []
    return sorted(
        (ruta for ruta in carpeta.iterdir() if ruta.is_file() and ruta.suffix.lower() in EXTENSIONES),
        key=lambda ruta: ruta.name.lower(),
    )


def leer_cheque(ruta: Path) -> dict:
    """Lee una imagen con el modelo y devuelve el JSON extraído."""
    if model is None:
        raise RuntimeError("El modelo todavía no está cargado.")

    imagen = abrir_imagen(ruta)
    with tempfile.TemporaryDirectory() as tmp:
        destino = Path(tmp) / "entrada.png"
        imagen.save(destino)
        with generation_lock:
            texto, _tokens, _global, _campos = read_image(str(destino))

    datos = parse_json(texto)
    if isinstance(datos, list) and len(datos) == 1 and isinstance(datos[0], dict):
        datos = datos[0]
    return datos if isinstance(datos, dict) else {}


def _actualizar_job(**cambios):
    with _job_lock:
        _job.update(cambios)


def _copiar_job():
    with _job_lock:
        return dict(_job)


def _procesar_carpeta():
    try:
        archivos = listar_imagenes(ENTRADA_DIR)
        if not archivos:
            _actualizar_job(
                estado="error",
                error="No hay imágenes en la carpeta entrada. Copia ahí los cheques y vuelve a intentar.",
                actual="",
            )
            return

        reglas = cargar_reglas(REGLAS_PATH)
        _actualizar_job(estado="procesando", total=len(archivos), hechos=0, actual="", error=None, resultado=None)
        filas = []
        no_leidos = 0

        for indice, ruta in enumerate(archivos, start=1):
            _actualizar_job(hechos=indice - 1, actual=ruta.name)
            print(f"Leyendo {indice}/{len(archivos)}: {ruta.name}")
            try:
                datos = leer_cheque(ruta)
                fila = evaluar_cheque(ruta.name, datos, reglas)
            except torch.cuda.OutOfMemoryError:
                torch.cuda.empty_cache()
                no_leidos += 1
                print(f"Sin memoria al leer {ruta.name}")
                fila = fila_no_leida(ruta.name)
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                no_leidos += 1
                print(f"No se pudo leer {ruta.name}: {exc}")
                fila = fila_no_leida(ruta.name)
            if fila["incluir"]:
                filas.append(fila)

        destino = escribir_informe(filas, INFORMES_DIR)
        _actualizar_job(
            estado="listo",
            hechos=len(archivos),
            actual="",
            resultado={
                "leidos": len(archivos) - no_leidos,
                "no_leidos": no_leidos,
                "con_observaciones": len(filas),
                "sin_observaciones": len(archivos) - len(filas),
                "archivo": destino.name,
                "descarga": f"/api/informes/{destino.name}",
                "filas": [valores_fila(fila) for fila in filas],
            },
        )
        print(f"Informe generado: {destino}")
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        _actualizar_job(estado="error", error=str(exc), actual="")


def percent(value):
    return None if value is None else round(value * 100, 1)


# --------------------------------------------------------------------------
# Rutas
# --------------------------------------------------------------------------
@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "device": str(model.device) if model else None})


@app.post("/api/extract")
def extract():
    upload = request.files.get("image")
    if upload is None or upload.filename == "":
        return jsonify({"error": "No llegó ninguna imagen. Elige un archivo e inténtalo de nuevo."}), 400

    try:
        image = prepare_image(upload)
    except (UnidentifiedImageError, OSError):
        return jsonify({"error": "El archivo no es una imagen válida. Prueba con PNG, JPG, WEBP, BMP, TIFF o GIF."}), 400

    started = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "entrada.png"
            image.save(path)
            with generation_lock:
                text, token_count, overall, per_field = read_image(str(path))
    except torch.cuda.OutOfMemoryError:
        torch.cuda.empty_cache()
        return jsonify({"error": "La GPU se quedó sin memoria. Usa una imagen más pequeña o baja MAX_SIDE."}), 507
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return jsonify({"error": f"El modelo falló al leer la imagen: {exc}"}), 500

    data = parse_json(text)
    fields = []
    if isinstance(data, dict):
        for key, value in data.items():
            fields.append(
                {"key": key, "value": value, "confidence": percent(per_field.get(key))}
            )

    return jsonify(
        {
            "text": text,
            "data": data,
            "fields": fields,
            "confidence": {"overall": percent(overall), "tokens": token_count},
            "seconds": round(time.perf_counter() - started, 1),
        }
    )


@app.get("/api/entrada")
def entrada():
    archivos = listar_imagenes(ENTRADA_DIR)
    return jsonify(
        {
            "carpeta": str(ENTRADA_DIR),
            "cantidad": len(archivos),
            "archivos": [ruta.name for ruta in archivos],
        }
    )


@app.get("/api/reglas")
def reglas():
    try:
        cargadas = cargar_reglas(REGLAS_PATH)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify(
        {
            "archivo": str(REGLAS_PATH),
            "meses_maximos": cargadas["meses_maximos"],
            "regla_fecha": cargadas["regla_fecha"],
            "formatos": cargadas["formatos"],
            "validaciones": cargadas["validaciones"],
        }
    )


@app.post("/api/procesar")
def procesar():
    with _job_lock:
        if _job["estado"] == "procesando":
            return jsonify({"error": "Ya hay una lectura de la carpeta en curso."}), 409
        _job.update(estado="procesando", total=0, hechos=0, actual="", error=None, resultado=None)
    threading.Thread(target=_procesar_carpeta, daemon=True).start()
    return jsonify({"estado": "procesando"})


@app.get("/api/procesar")
def estado_procesar():
    return jsonify(_copiar_job())


@app.get("/api/informes/<path:nombre>")
def descargar_informe(nombre):
    archivo = (INFORMES_DIR / Path(nombre).name).resolve()
    carpeta = INFORMES_DIR.resolve()
    if archivo.parent != carpeta or archivo.suffix.lower() != ".xlsx" or not archivo.is_file():
        return jsonify({"error": "No encuentro ese informe."}), 404
    return send_file(archivo, as_attachment=True, download_name=archivo.name)


@app.errorhandler(413)
def too_large(_error):
    return jsonify({"error": f"La imagen supera los {MAX_UPLOAD_MB} MB. Reduce su tamaño e inténtalo de nuevo."}), 413


if __name__ == "__main__":
    load_model()
    url = f"http://{HOST}:{PORT}"
    print(f"Listo. Abre {url} en tu navegador (Ctrl+C para cerrar)")
    if os.environ.get("OPEN_BROWSER", "1") == "1":
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host=HOST, port=PORT, threaded=True, debug=False)
