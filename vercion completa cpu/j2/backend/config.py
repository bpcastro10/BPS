"""Configuración central de la aplicación."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Carpeta donde se colocan los cheques a analizar (imágenes o PDF)
CARPETA_CHEQUES = BASE_DIR / "cheques"

# Carpeta donde se guardan los resultados y las vistas previas
CARPETA_DATOS = BASE_DIR / "datos"
ARCHIVO_RESULTADOS = CARPETA_DATOS / "resultados.json"
CARPETA_VISTAS = CARPETA_DATOS / "vistas"

CARPETA_FRONTEND = BASE_DIR / "frontend"

EXTENSIONES_VALIDAS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp", ".pdf"}

# Cada cuántos segundos se revisa la carpeta en busca de archivos nuevos
INTERVALO_REVISION_SEG = 5

# Ancho (px) al que se normalizan las imágenes antes del OCR.
# Más grande = más preciso pero más lento.
ANCHO_OCR = 1400
# Fotos borrosas o de baja resolución se suben más para recuperar trazo.
ANCHO_OCR_DIFICIL = 1800

# Confianza mínima (0-1) para aceptar un texto reconocido.
# Se deja baja para no perder texto manuscrito.
CONFIANZA_MINIMA = 0.28
# En imágenes difíciles se aceptan lecturas más dudosas y luego se cruzan campos.
CONFIANZA_MINIMA_DIFICIL = 0.18

HOST = "127.0.0.1"
PUERTO = 5000

for carpeta in (CARPETA_CHEQUES, CARPETA_DATOS, CARPETA_VISTAS):
    carpeta.mkdir(parents=True, exist_ok=True)
