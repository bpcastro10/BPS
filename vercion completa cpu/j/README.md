# Análisis de Cheques (100% local)

Lee cheques (JPG, PNG, TIFF, BMP, WEBP, PDF) desde una carpeta, extrae los datos impresos y manuscritos y los muestra en un reporte web descargable en Excel.

## Cómo usar

1. Doble clic en `iniciar.bat` (o `cd backend && pip install -r requirements.txt && python run.py`).
2. Se abre http://127.0.0.1:8000
3. Copie cheques en la carpeta `cheques_entrada/`. Solo los archivos **nuevos** se analizan y se agregan al reporte (los duplicados se detectan por contenido, aunque cambien de nombre).
4. Clic en una fila para ver el cheque con las zonas detectadas, corregir datos o reanalizar.
5. **Descargar Excel** exporta lo que se ve con el filtro actual (hojas: Cheques, Resumen, Texto OCR).

Para probar: `python backend/tools/generar_cheques_ejemplo.py` genera cheques de ejemplo en `cheques_entrada/`.

## Qué extrae

Banco, N° de cheque, ciudad, fecha, beneficiario, monto, monto en letras, moneda, cuenta, código de ruta, línea MICR, concepto y presencia de firma. Para cada campo indica la confianza, el origen y si está escrito a mano o impreso.

## Cómo funciona (de lo programático a lo local con IA)

| Paso | Técnica |
|---|---|
| Recorte, enderezado, orientación | OpenCV (programático) |
| Lectura de texto | RapidOCR PP-OCRv5 latino, ONNX en CPU (~1.5 s por cheque) |
| Ubicación de campos | Etiquetas impresas ("Páguese a la orden de", "La suma de"…) + posición |
| Validación del monto | El monto en letras se convierte a número y se compara con el numérico |
| N° de cheque / cuenta | Se confirman con la banda MICR; el código de ruta ABA se valida con su dígito verificador |
| Firma y tipo de escritura | Densidad de trazos y color de tinta (programático) |
| Manuscritos difíciles (opcional) | TrOCR local, solo para campos manuscritos con baja confianza |
| Último recurso (opcional) | Modelo de visión local con Ollama, solo si el cheque queda "REVISAR" |

Estados: **COMPLETO** (monto, beneficiario y fecha encontrados, montos coinciden y hay firma), **REVISAR** (ver observaciones), **ERROR**.

## Opcionales (copie `backend/.env.example` como `backend/.env`)

- **TrOCR**: requiere `pip install -r backend/requirements-manuscritos.txt`. En Windows, `torch` necesita el *Microsoft Visual C++ Redistributable*. Se descarga una sola vez (~1.3 GB) en segundo plano.
- **Ollama**: instale Ollama, ejecute `ollama pull qwen2.5vl:7b` y ponga `OLLAMA_MODEL=qwen2.5vl:7b`.

## API (documentación interactiva en http://127.0.0.1:8000/docs)

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/v1/checks?page=&pageSize=&status=&search=&dateFrom=&dateTo=&sortBy=&order=&includeDeleted=` | Listado paginado, filtrado y ordenado |
| GET | `/v1/checks/{id}` | Detalle |
| GET | `/v1/checks/{id}/image` | Imagen procesada |
| PATCH | `/v1/checks/{id}` | Corrección manual de campos |
| DELETE | `/v1/checks/{id}` | Borrado lógico |
| POST | `/v1/checks/{id}/reprocessings` | Reanalizar (header `Idempotency-Key`) |
| POST | `/v1/scans` | Escanear la carpeta ahora (`requestId` / `Idempotency-Key`) |
| GET | `/v1/summary` | Totales y estado del procesamiento |
| GET | `/v1/exports/excel` | Descarga Excel (mismos filtros que el listado) |

## Estructura

```
backend/app/
  config/        configuración, CORS, logs
  controller/    endpoints + dto/ + mapper/
  enums/  exception/  model/  repository/ (SQLite)
  service/       procesamiento de carpeta, Excel, casos de uso
  service/analysis/  OCR, extracción de campos, MICR, firma, manuscritos
frontend/        index.html, css/, js/
cheques_entrada/ carpeta vigilada
```
