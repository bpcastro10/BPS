# Analizador de Cheques

Aplicación local para leer cheques (impresos y manuscritos) con OCR puro, sin servicios ni modelos externos. Extrae banco, número, cuenta, fecha, beneficiario, montos, concepto y línea MICR, muestra el resultado en una tabla y permite bajarlo a Excel.

Todo corre en el PC: los modelos ONNX vienen dentro del paquete `rapidocr_onnxruntime`.

## Requisitos

- Windows 10/11 (también funciona en Linux/macOS con los mismos comandos de Python)
- Python 3.11 o superior
- No hace falta Tesseract ni conexión a internet después de instalar las librerías

## Arranque rápido (Windows)

1. Coloque las imágenes o PDF de los cheques en la carpeta `cheques/`.
2. Doble clic en `iniciar.bat`.
3. La primera vez crea `.venv` e instala lo de `requirements.txt` (tarda unos minutos).
4. Se abre el navegador en [http://127.0.0.1:5000](http://127.0.0.1:5000).

Si el puerto 5000 está ocupado, cierre la consola anterior o cambie `PUERTO` en `backend/config.py`.

## Arranque manual

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python backend\app.py
```

En Linux o macOS:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python backend/app.py
```

## Uso

- **Carpeta vigilada:** lo que copie a `cheques/` se analiza solo si es un archivo nuevo (se identifica por el contenido, no por el nombre).
- **Subir desde la web:** botón “Subir cheques”.
- **Revisión:** si la foto está borrosa, oscura o la letra a mano no cuadra, el cheque queda marcado para revisar.
- **Excel:** botón “Descargar Excel”. Incluye campos, validación de montos y avisos de calidad.
- **Reanalizar todo:** borra resultados y vuelve a leer toda la carpeta.

Formatos: `.jpg`, `.jpeg`, `.png`, `.bmp`, `.tif`, `.tiff`, `.webp`, `.pdf` (primera página).

## Qué extrae

Banco, número de cheque, cuenta, ciudad, fecha, beneficiario, monto en números, monto en letras, coincidencia entre ambos montos, concepto y línea MICR.

## Documentación extra

La explicación archivo por archivo, puntos críticos y las variantes de ejecución están en [docs/GUIA_TECNICA.md](docs/GUIA_TECNICA.md).
