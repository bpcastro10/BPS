# Documentación técnica – Análisis de Cheques

Esta guía explica **qué hace cada archivo**, **dónde están los modelos de IA**, **cómo funciona cada parte importante** y **cómo ejecutar la aplicación manualmente, paso a paso**.

---

## 1. Visión general

La aplicación tiene dos partes:

| Parte | Tecnología | Función |
|---|---|---|
| **Backend** | Python 3.11 + FastAPI | Vigila una carpeta, analiza cada cheque nuevo, guarda los resultados y expone una API REST. |
| **Frontend** | HTML + CSS + JavaScript (sin frameworks) | Muestra el reporte, permite revisar y corregir cheques y descargar el Excel. |

Todo se ejecuta **en su computadora**. No se envía ninguna imagen a internet. Solo la primera vez se descargan los modelos de OCR, y después funcionan sin conexión.

### Flujo completo de un cheque

```
 Archivo nuevo en cheques_entrada/
        │
        ▼
 [processing_service]  detecta el archivo, espera a que termine de copiarse,
        │              calcula su huella (SHA-256) y lo ignora si ya existe en la BD
        ▼
 [image_loader]        abre la imagen o el PDF, recorta el cheque, corrige la orientación y el tamaño
        ▼
 [ocr_engine]          lee todo el texto con sus posiciones (RapidOCR PP-OCRv5 latino)
        │              y, si el cheque está inclinado, lo endereza y vuelve a leer
        ▼
 [field_extractor]     ubica cada dato usando las etiquetas impresas y la posición
        ▼
 [micr_reader]         lee la banda inferior de números magnéticos (MICR)
 [signature_detector]  detecta si hay firma
 [writing_classifier]  decide si cada dato está escrito a mano o impreso
        ▼
 [handwriting_recognizer] (opcional) relee con TrOCR los manuscritos de baja confianza
        ▼
 [check_analyzer]      valida el monto en letras contra el número, calcula la confianza
        │              y define el estado: COMPLETO / REVISAR / ERROR
        ▼
 [vlm_refiner]         (opcional) si el cheque quedó en REVISAR, consulta un modelo de visión local (Ollama)
        ▼
 [check_repository]    guarda el resultado en SQLite y una vista previa JPG
        ▼
 Frontend              consulta /v1/summary cada 2.5 s; si hay cambios, recarga la tabla
```

---

## 2. Estructura de carpetas

```
j/
├── iniciar.bat                  Arranque rápido con doble clic
├── README.md                    Resumen corto
├── DOCUMENTACION.md             Este documento
├── cheques_entrada/             CARPETA VIGILADA: aquí se copian los cheques
├── muestras/                    Cheques de ejemplo para pruebas
├── frontend/
│   ├── index.html
│   ├── css/styles.css
│   └── js/api.js, js/app.js
└── backend/
    ├── run.py                   Punto de entrada del servidor
    ├── requirements.txt         Dependencias obligatorias
    ├── requirements-manuscritos.txt  Dependencias opcionales (TrOCR)
    ├── .env.example             Plantilla de configuración
    ├── data/                    (se crea solo) base de datos y vistas previas
    │   ├── cheques.db
    │   └── previews/*.jpg
    ├── tools/                   Utilidades de consola
    └── app/
        ├── main.py
        ├── config/              Configuración, CORS, logs
        ├── controller/          Endpoints REST + dto/ + mapper/
        ├── enums/               Estados, tipos de campo, orígenes
        ├── exception/           Excepciones personalizadas y su manejador
        ├── model/               Modelo de datos del cheque
        ├── repository/          Acceso a SQLite
        └── service/             Lógica de negocio
            └── analysis/        Motor de análisis de cheques
```

---

## 3. Qué hace cada archivo

### 3.1 Raíz

| Archivo | Descripción |
|---|---|
| `iniciar.bat` | Instala las dependencias, abre el navegador en `http://127.0.0.1:8000` y arranca el servidor. |
| `README.md` | Resumen rápido de uso. |

### 3.2 `backend/`

| Archivo | Descripción |
|---|---|
| `run.py` | Lee la configuración y arranca Uvicorn (el servidor web) con la app `app.main:app`. |
| `requirements.txt` | Librerías necesarias: FastAPI, Uvicorn, RapidOCR, ONNX Runtime, OpenCV, NumPy, Pillow, openpyxl y PyMuPDF. |
| `requirements-manuscritos.txt` | `torch` y `transformers`, solo si se quiere usar TrOCR. |
| `.env.example` | Variables configurables. Se copia como `.env` para modificarlas. |

### 3.3 `backend/app/config/`

| Archivo | Descripción |
|---|---|
| `settings.py` | Configuración central. Lee `backend/.env` y las variables de entorno, define rutas (carpeta de entrada, BD, vistas previas, frontend), el intervalo de vigilancia, los umbrales de confianza y las opciones de TrOCR y Ollama. También contiene `SUPPORTED_EXTENSIONS`, la lista de formatos aceptados. |
| `cors_config.py` | Configura CORS, para que el frontend pueda llamar a la API aunque se abra desde otro origen. |
| `logging_config.py` | Formato de los logs (`hora \| nivel \| módulo \| mensaje`) y silencia librerías ruidosas. |

### 3.4 `backend/app/controller/`

| Archivo | Descripción |
|---|---|
| `check_controller.py` | Define todos los endpoints `/v1/...`: listar (con paginación, filtros y orden), detalle, imagen, PATCH (corrección), DELETE (borrado lógico), reanálisis, escaneo, resumen y exportación a Excel. No contiene lógica de negocio: delega en los servicios. |
| `dto/check_dto.py` | DTOs (Pydantic) de entrada y salida, con validaciones (`max_length`, `pattern`, etc.) que aparecen documentadas en `/docs`. |
| `mapper/check_mapper.py` | Convierte el modelo `CheckRecord` en DTO de forma automática, porque los atributos tienen el mismo nombre, y agrega la URL de la imagen. |

### 3.5 `backend/app/enums/`

| Archivo | Descripción |
|---|---|
| `check_enums.py` | `CheckStatus` (COMPLETO, REVISAR, ERROR), `FieldKey` (claves de los campos: banco, fecha, monto…), `FieldSource` (origen de cada dato: ocr, micr, trocr, vlm, imagen, calculado, manual), `WritingType` (impreso o manuscrito) y las etiquetas que se muestran al usuario. |

### 3.6 `backend/app/exception/`

| Archivo | Descripción |
|---|---|
| `check_exceptions.py` | Excepciones personalizadas (todas heredan de `RuntimeError`): `CheckNotFoundException` (404), `ImageReadException` (422), `UnsupportedFileException` (415), `InvalidFieldException` (400) y `ExportException` (500). |
| `handlers.py` | Manejador global: convierte cualquiera de esas excepciones en una respuesta JSON uniforme `{status, error, message}`. Así los controladores no necesitan `try/except`. |

### 3.7 `backend/app/model/`

| Archivo | Descripción |
|---|---|
| `check.py` | `ExtractedField` guarda un dato extraído: valor, confianza, caja de ubicación `bbox`, origen y tipo de escritura. `CheckRecord` guarda el cheque completo: archivo, hash, estado, campos, observaciones, texto OCR, etc. La igualdad y el hash usan solo el `id`. |

### 3.8 `backend/app/repository/`

| Archivo | Descripción |
|---|---|
| `check_repository.py` | Persistencia en SQLite (`backend/data/cheques.db`). Crea la tabla, guarda y actualiza, busca por id o por hash, lista con filtros (estado, texto, rango de fechas, eliminados) y orden, y calcula los totales del resumen. Los campos detallados se guardan como JSON y los usados para filtrar u ordenar, en columnas propias. |

### 3.9 `backend/app/service/`

| Archivo | Descripción |
|---|---|
| `processing_service.py` | **Vigilancia de la carpeta y cola de trabajo.** Un hilo revisa `cheques_entrada/` cada `POLL_SECONDS`. Un archivo solo se encola cuando su tamaño no cambia entre dos revisiones (ya terminó de copiarse) y su SHA-256 no existe en la BD. Otro hilo procesa la cola de uno en uno. También lleva el contador `version` que usa el frontend para saber si hay cambios. |
| `check_service.py` | Casos de uso: consultar, corregir campos (valida montos y fechas), borrado lógico y reanálisis. |
| `excel_exporter.py` | Genera el `.xlsx` con tres hojas: **Cheques** (con formato de moneda, fecha y colores por estado), **Resumen** y **Texto OCR**. |
| `idempotency_store.py` | Guarda en memoria, durante 10 minutos, las claves `Idempotency-Key` y `requestId`, para que un mismo POST repetido no se ejecute dos veces. |

### 3.10 `backend/app/service/analysis/` (el motor)

| Archivo | Descripción |
|---|---|
| `check_analyzer.py` | **Orquestador.** Ejecuta todo el flujo de la sección 1, combina los resultados, hace la validación cruzada y define el estado y las observaciones. |
| `image_loader.py` | Abre imágenes (también con rutas que tienen tildes) y PDF página por página. `crop_check` detecta el rectángulo del cheque en fotos y corrige la perspectiva. `normalize_size` gira a horizontal y escala el ancho entre 1400 y 2000 px. También incluye `rotate` y `crop_norm`. |
| `ocr_engine.py` | `OcrEngine` carga RapidOCR una sola vez y devuelve `OcrToken` (texto, confianza y caja normalizada de 0 a 1). `estimate_skew` mide la inclinación. `Layout` permite consultas espaciales: tokens en la misma fila a la derecha, la fila de abajo o los de una región. |
| `field_extractor.py` | **Reglas para ubicar cada campo** (ver sección 5). |
| `text_utils.py` | Normalización (quitar tildes y pasar a minúsculas), búsqueda tolerante de etiquetas, interpretación de montos (`1.250,50` o `1,250.50`), fechas en muchos formatos y verificación del código de ruta ABA. |
| `amount_words.py` | Convierte montos escritos en letras a número, en español e inglés ("Mil doscientos cincuenta con 50/100" → 1250.50). Corrige errores de OCR con coincidencia aproximada y separa palabras pegadas ("milquinientos"). |
| `micr_reader.py` | Lee la banda MICR (el 22 % inferior del cheque). Si el OCR general ya la leyó bien, la reutiliza; si no, relee solo la banda con contraste mejorado. Separa los grupos de dígitos en código de ruta, cuenta y número de serie. |
| `signature_detector.py` | En la zona de la firma (abajo a la derecha), quita el texto impreso y las líneas horizontales y mide la cantidad y extensión de los trazos. Con eso decide si hay firma. |
| `writing_classifier.py` | Decide si un dato es manuscrito o impreso: tinta azul de bolígrafo, variación de la altura de las letras, variación del grosor del trazo y confianza del OCR. |
| `handwriting_recognizer.py` | TrOCR (opcional). Se carga en segundo plano al iniciar y nunca bloquea el análisis. Solo se usa en campos manuscritos con confianza menor a `LOW_CONFIDENCE`. |
| `vlm_refiner.py` | Modelo de visión vía Ollama (opcional). Envía la imagen a `http://localhost:11434` y pide un JSON con los campos. Solo reemplaza datos ausentes o con baja confianza. |

### 3.11 `backend/tools/`

| Archivo | Descripción |
|---|---|
| `generar_cheques_ejemplo.py` | Crea cheques de prueba con texto impreso y con fuentes que imitan la escritura a mano en tinta azul. |
| `probar_cheque.py` | Analiza uno o varios archivos desde la consola y muestra cada campo con su confianza, origen y tipo de escritura. Sirve para ajustar reglas sin abrir la web. |

### 3.12 `frontend/`

| Archivo | Descripción |
|---|---|
| `index.html` | Estructura de la página: barra superior con el estado del motor, carpeta vigilada, indicadores (total, completos, por revisar, con error), filtros, tabla del reporte y ventana de detalle. |
| `css/styles.css` | Estilos: colores por estado, barras de confianza, cajas de colores sobre la imagen y diseño adaptable. |
| `js/api.js` | Cliente de la API: una función por endpoint. Si la página se abre como archivo suelto, apunta a `http://127.0.0.1:8000`. |
| `js/app.js` | Lógica de la interfaz. `poll()` consulta el resumen cada 2.5 s y recarga la tabla si cambió `version`. `renderTable` dibuja las filas y resalta las nuevas. `openDetail` muestra la imagen con las zonas detectadas y el formulario de corrección. `saveCorrections` envía solo los campos modificados por PATCH. |

---

## 4. Modelos de IA: cuáles son y dónde se guardan

| Modelo | Uso | ¿Obligatorio? | Ubicación en disco |
|---|---|---|---|
| `ch_PP-OCRv5_det_mobile.onnx` (~5 MB) | **Detecta** dónde hay texto | Sí | `C:\Users\Usuario\AppData\Local\Programs\Python\Python311\Lib\site-packages\rapidocr\models\` |
| `ch_ppocr_mobile_v2.0_cls_mobile.onnx` (~0.6 MB) | Detecta líneas de texto invertidas | Sí | misma carpeta |
| `latin_PP-OCRv5_rec_mobile.onnx` (~8 MB) | **Reconoce** el texto (alfabeto latino: tildes, ñ) | Sí | misma carpeta |
| `microsoft/trocr-base-handwritten` (~1.3 GB) | Relee texto manuscrito difícil | No | `C:\Users\Usuario\.cache\huggingface\hub\` |
| Modelo de Ollama, ej. `qwen2.5vl:7b` (~6 GB) | Lectura con modelo de visión, como último recurso | No | `C:\Users\Usuario\.ollama\models\` |

Notas:

- Los modelos de RapidOCR **se descargan solos la primera vez** que arranca el motor y después funcionan sin internet. En otra PC sin internet, copie esos tres archivos `.onnx` a la misma ruta, dentro de la carpeta `site-packages\rapidocr\models\` de su Python.
- Los modelos se configuran en `backend/app/service/analysis/ocr_engine.py`, método `_ensure_loaded`. Ahí se elige la versión (`PPOCRV5`), el tamaño (`MOBILE`) y el idioma (`LangRec.LATIN`).
- El modelo TrOCR se cambia con `HANDWRITING_MODEL` en `.env`. El de Ollama, con `OLLAMA_MODEL`.

---

## 5. Cómo funciona cada punto fundamental

### 5.1 Detectar solo archivos nuevos (`processing_service.py`)
1. Cada 2 s se recorre `cheques_entrada/`, incluidas las subcarpetas.
2. Para cada archivo con extensión válida se compara su (tamaño, fecha de modificación) con la última vez que se vio. Si no cambió, se salta.
3. Si es nuevo, se espera una vuelta más para confirmar que el tamaño no cambia, es decir, que terminó de copiarse.
4. Se calcula su **SHA-256**. Si ese hash ya está en la BD, se ignora. Por eso un cheque repetido con otro nombre no se procesa dos veces.
5. Si no está, se encola y el hilo de trabajo lo analiza.

### 5.2 Preparar la imagen (`image_loader.py`, `check_analyzer._prepare`)
1. PDF: cada página se convierte en imagen a 250 dpi.
2. Fotos: se busca un rectángulo con proporción de cheque (entre 1.6 y 3.4) y se corrige la perspectiva.
3. Si la imagen está vertical, se gira a horizontal y se escala.
4. Se ejecuta el OCR. Si la inclinación media del texto supera 0.8°, se endereza y se vuelve a leer.
5. Si los números MICR aparecen arriba, el cheque está invertido: se gira 180°.

### 5.3 Leer el texto (`ocr_engine.py`)
RapidOCR devuelve cada bloque de texto con su caja. Las coordenadas se normalizan de 0 a 1, para que las reglas funcionen con cualquier resolución. `Layout` agrupa los bloques en filas según su solapamiento vertical.

### 5.4 Ubicar cada campo (`field_extractor.py`)
La idea central es la función `value_after_anchor`: busca una **etiqueta impresa** y toma el texto que está **a su derecha** en la misma fila, o en la fila siguiente si a la derecha no hay nada. La búsqueda tolera tildes, espacios perdidos y confusiones típicas del OCR (o/0, i/1).

| Campo | Cómo se encuentra |
|---|---|
| Beneficiario | Etiquetas "Páguese a la orden de", "Pay to the order of"… Se detiene al llegar a `$` o a un número. |
| Monto en letras | "La suma de", "La cantidad de"… Si la línea continúa abajo, la une. Si no hay etiqueta, elige la fila con más palabras numéricas. |
| Monto numérico | Puntúa cada número del cheque: +0.35 si tiene `$` cerca, +0.15 si tiene decimales o asteriscos, +0.15 si está a la derecha, −0.45 si parece un número de cuenta y **+0.5 si coincide con el monto en letras**. Gana el de mayor puntaje. |
| Fecha y ciudad | Busca fechas en cada fila (`8 de octubre de 2026`, `15/09/2026`, `2026-09-15`, casillas `DD MM AAAA`). La ciudad es el texto antes de la coma ("Quito, …"). |
| N° de cheque | "Cheque No.", "Nº", "Serie"… Si no aparece, toma el número de la esquina superior derecha; si tampoco, el de la banda MICR. |
| Cuenta | "Cta. Cte.", "Cuenta", "Account"… Si no aparece, la toma de la banda MICR. |
| Banco | Texto con "Banco", "Bank", "Cooperativa" o nombres conocidos en la parte superior. Si no hay, el texto más grande arriba a la izquierda. |
| Concepto | "Por concepto de", "Memo", "Referencia". |
| Moneda | US$, USD, dólares, pesos, €… |

Para agregar una etiqueta nueva, edite las listas al inicio de `field_extractor.py` (`PAYEE_ANCHORS`, `AMOUNT_WORDS_ANCHORS`, etc.).

### 5.5 Banda MICR (`micr_reader.py`)
- Extrae los grupos de 3 o más dígitos.
- Un grupo de 9 dígitos que pasa el dígito verificador ABA se toma como **código de ruta**.
- El grupo más largo se toma como **cuenta**.
- Los demás son candidatos a **número de cheque**.
- Si el número de cheque o la cuenta leídos arriba coinciden con la banda, su confianza sube al 98 %.

### 5.6 Firma (`signature_detector.py`)
1. Toma la zona entre el 50 % y el 98 % del ancho y entre el 55 % y el 86 % del alto.
2. Binariza la imagen y borra el texto impreso, como "Firma autorizada".
3. Elimina las líneas horizontales largas (la línea de la firma).
4. Hay firma si los trazos ocupan más del 0.6 % del área y abarcan más del 12 % del ancho.

### 5.7 Manuscrito o impreso (`writing_classifier.py`)
- Si más del 30 % de la tinta es azul de bolígrafo, el dato es **manuscrito**.
- Si no, suma puntos por variación de altura de letras (> 0.45), variación del grosor del trazo (> 0.75) y confianza baja del OCR. Si el puntaje es 0.4 o más, es manuscrito.

### 5.8 Validación y estado (`check_analyzer._finalize`)
1. **Montos:**
   - Si no hay monto numérico pero sí en letras, se usa el de letras.
   - Si los dos coinciden, la confianza sube a 97 %.
   - Si no coinciden, se busca otro número del cheque que sí coincida. Si no aparece ninguno, se agrega una observación.
2. Se revisan los campos obligatorios (monto, beneficiario y fecha) y su confianza, que debe ser de al menos 60 %.
3. Se verifica que haya firma.
4. **COMPLETO** si no hay ninguna observación; **REVISAR** si hay al menos una; **ERROR** si el archivo no se pudo procesar.
5. La confianza general es el promedio de banco, N° de cheque, fecha, beneficiario, monto y monto en letras. Los obligatorios que falten cuentan como 0.

### 5.9 Refinamiento opcional
- **TrOCR:** solo para beneficiario, montos, fecha y concepto **manuscritos** con confianza menor a `LOW_CONFIDENCE` (0.80). Reemplaza el valor solo si el resultado nuevo tiene más confianza y es válido (por ejemplo, que el monto se pueda interpretar).
- **Ollama:** solo si el cheque quedó en REVISAR (con `VLM_MODE=fallback`). Si su valor coincide con el del OCR, sube la confianza; si el dato faltaba o era dudoso, lo reemplaza.

### 5.10 Excel (`excel_exporter.py`)
Exporta los mismos registros que se ven con el filtro actual. La fecha se guarda como fecha real y el monto como número con formato `#,##0.00`, así se puede sumar y filtrar en Excel. El estado lleva color, la primera fila queda fija y la tabla tiene filtros automáticos.

### 5.11 Actualización automática del frontend (`app.js`)
Cada 2.5 s se llama a `GET /v1/summary`. Si cambió el número `version` (porque entró un cheque o hubo una corrección), se recarga la tabla. Las filas nuevas se resaltan y aparece un aviso.

---

## 6. API REST

Documentación interactiva: **http://127.0.0.1:8000/docs**

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/v1/checks` | Lista. Parámetros: `page`, `pageSize`, `status`, `search`, `dateFrom`, `dateTo`, `includeDeleted`, `sortBy` (processedAt, amount, date, payee, bank, checkNumber, status, confidence, fileName), `order` (asc/desc). |
| GET | `/v1/checks/{id}` | Detalle con texto OCR. |
| GET | `/v1/checks/{id}/image` | Imagen procesada. |
| PATCH | `/v1/checks/{id}` | Corrige los campos enviados. Ejemplo: `{"beneficiario": "Juan Pérez", "monto": "1250.50"}`. |
| DELETE | `/v1/checks/{id}` | Borrado lógico (sigue visible con `includeDeleted=true`). |
| POST | `/v1/checks/{id}/reprocessings` | Reanaliza el archivo original. Header opcional `Idempotency-Key`. |
| POST | `/v1/scans` | Busca archivos nuevos ahora. Body `{"request_id": "..."}`. |
| GET | `/v1/summary` | Totales y estado del motor. |
| GET | `/v1/exports/excel` | Descarga el Excel (acepta los mismos filtros que la lista). |

---

## 7. Ejecución manual paso a paso

### Paso 1: Verificar Python
Abra **PowerShell** y ejecute:
```powershell
python --version
```
Debe mostrar **Python 3.10 o superior** (este equipo tiene 3.11.0). Si no lo reconoce, instale Python desde https://www.python.org y marque **"Add Python to PATH"**.

### Paso 2: Ir a la carpeta del backend
```powershell
cd C:\Users\Usuario\Desktop\j\backend
```

### Paso 3 (recomendado): Crear un entorno virtual
Así las librerías del proyecto no se mezclan con las de otros proyectos:
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```
Si PowerShell bloquea el script, ejecute una vez:
```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```
Cuando el entorno está activo, la línea de comandos empieza con `(.venv)`.

### Paso 4: Instalar las dependencias
```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Paso 5 (opcional): Configurar
```powershell
copy .env.example .env
notepad .env
```
Cambie lo que necesite, por ejemplo `CHEQUES_INPUT_DIR` para vigilar otra carpeta o `APP_PORT` para usar otro puerto. Si no crea el `.env`, se usan los valores por defecto.

### Paso 6: Arrancar el servidor
```powershell
python run.py
```
Debe ver algo como:
```
INFO | app.service.processing_service | Vigilando la carpeta: C:\Users\Usuario\Desktop\j\cheques_entrada
INFO | app.main | Aplicación lista en http://127.0.0.1:8000
INFO | app.service.analysis.ocr_engine | Motor OCR cargado (RapidOCR PP-OCRv5 latino)
```
La **primera vez** descarga los modelos de OCR (unos 15 MB) y necesita internet. **No cierre esta ventana**: el servidor funciona mientras esté abierta.

### Paso 7: Abrir la aplicación
En el navegador, entre a **http://127.0.0.1:8000**

### Paso 8: Analizar cheques
1. Copie imágenes o PDF de cheques en `C:\Users\Usuario\Desktop\j\cheques_entrada\`.
2. En unos segundos aparecen en la tabla. En la consola se ve una línea como `Cheque analizado: archivo.jpg -> COMPLETO (99% conf, 2100 ms)`.
3. Para probar sin cheques reales, en otra ventana de PowerShell:
   ```powershell
   cd C:\Users\Usuario\Desktop\j\backend
   python tools\generar_cheques_ejemplo.py
   ```

### Paso 9: Revisar y corregir
- Haga clic en una fila para ver la imagen con las zonas detectadas y la confianza de cada campo.
- Corrija lo necesario y pulse **Guardar correcciones**. El cheque pasa a COMPLETO y el campo queda marcado como "Manual".
- **Reanalizar** vuelve a procesar el archivo original. **Eliminar** lo quita del reporte, pero no borra el archivo.

### Paso 10: Descargar el Excel
Aplique los filtros que quiera (estado, búsqueda, orden) y pulse **Descargar Excel**.

### Paso 11: Detener
En la ventana del servidor presione **Ctrl + C**.

### Probar un cheque desde la consola (sin la web)
```powershell
cd C:\Users\Usuario\Desktop\j\backend
python tools\probar_cheque.py ..\cheques_entrada\cheque_impreso_5569.jpg
```

### Empezar de cero
Detenga el servidor y borre la carpeta `backend\data\`. Al arrancar de nuevo, se vuelven a analizar todos los archivos de `cheques_entrada\`.

---

## 8. Activar los modelos opcionales

### TrOCR (manuscritos)
```powershell
pip install -r requirements-manuscritos.txt
```
En Windows, `torch` necesita el **Microsoft Visual C++ Redistributable (x64)**: https://aka.ms/vs/17/release/vc_redist.x64.exe

En este equipo hoy falta, por eso TrOCR aparece desactivado (`Error loading fbgemm.dll`). Después de instalarlo, reinicie el servidor. El modelo (~1.3 GB) se descarga en segundo plano y la barra superior mostrará "IA manuscritos".

### Ollama (modelo de visión)
1. Instale Ollama desde https://ollama.com
2. Descargue un modelo de visión:
   ```powershell
   ollama pull qwen2.5vl:7b
   ```
3. En `backend\.env`, ponga `OLLAMA_MODEL=qwen2.5vl:7b` y `VLM_MODE=fallback`.
4. Reinicie el servidor.

---

## 9. Configuración (`backend/.env`)

| Variable | Por defecto | Descripción |
|---|---|---|
| `CHEQUES_INPUT_DIR` | `../cheques_entrada` | Carpeta vigilada. |
| `APP_HOST` / `APP_PORT` | `127.0.0.1` / `8000` | Dirección del servidor. |
| `POLL_SECONDS` | `2` | Cada cuántos segundos se revisa la carpeta. |
| `MAX_IMAGE_WIDTH` / `MIN_IMAGE_WIDTH` | `2000` / `1400` | Rango de ancho al que se escala la imagen. Más ancho es más preciso pero más lento. |
| `LOW_CONFIDENCE` | `0.80` | Por debajo de este valor se intenta refinar un campo. |
| `HANDWRITING_ENABLED` / `HANDWRITING_MODEL` | `true` / `microsoft/trocr-base-handwritten` | TrOCR. |
| `OLLAMA_URL` / `OLLAMA_MODEL` / `VLM_MODE` | `http://localhost:11434` / vacío / `fallback` | Modelo de visión (`fallback`, `always` u `off`). |
| `CORS_ORIGINS` | `*` | Orígenes permitidos para el frontend. |

---

## 10. Configuración probada (la que funcionó correctamente)

Esta es la configuración exacta con la que se hizo la prueba del 08/10/2026. Si algo deja de funcionar, vuelva a esta configuración.

### 10.1 Resultado de la prueba

| Archivo | Estado | Monto | Monto en letras | Tiempo |
|---|---|---|---|---|
| cheque_impreso_5569.jpg | COMPLETO | 47.20 | Cuarenta y siete con 20/100 | 2.1 s |
| cheque_impreso_6193.jpg | COMPLETO | 325.00 | Trescientos veinticinco con 00/100 | 2.6 s |
| cheque_manuscrito_7573.jpg | COMPLETO | 8,940.75 | Ocho mil novecientos cuarenta con 75/100 | 2.2 s |
| cheque_manuscrito_8577.jpg | COMPLETO | 1,250.50 | Mil doscientos cincuenta con 50/100 | 2.2 s |
| sin_firma.jpg | REVISAR (correcto: no tiene firma) | 325.00 | Trescientos veinticinco con 00/100 | 2.2 s |

También se comprobó que:
- al copiar archivos nuevos, solo se procesaron esos;
- un cheque repetido con otro nombre se ignoró;
- el Excel salió con 3 hojas;
- funcionaron el PATCH, el borrado lógico, los filtros, la búsqueda y los errores 404 y 400.

### 10.2 Entorno

| Elemento | Valor |
|---|---|
| Sistema operativo | Windows 11 (NT 10.0.26200) |
| Python | 3.11.0 (instalación global, sin entorno virtual) |
| Procesador | Solo CPU (sin GPU) |
| Internet | Solo la primera vez, para descargar los modelos de OCR |

### 10.3 Versiones de librerías

Guardadas en `backend/requirements-probado.txt`:

| Librería | Versión |
|---|---|
| fastapi | 0.115.6 |
| starlette | 0.41.3 |
| uvicorn | 0.32.1 |
| pydantic | 2.10.3 |
| email-validator | 2.3.0 |
| rapidocr | 3.9.2 |
| onnxruntime | 1.18.1 |
| opencv-python | 4.8.1.78 |
| numpy | 1.26.4 |
| Pillow | 10.4.0 |
| openpyxl | 3.1.2 |
| PyMuPDF | 1.28.2 |

### 10.4 Modelos de OCR

Configurados en `backend/app/service/analysis/ocr_engine.py`, método `_ensure_loaded`:

| Parámetro | Valor | Significado |
|---|---|---|
| `Det.ocr_version` | `PP-OCRv5` | Versión del detector de texto |
| `Det.model_type` | `MOBILE` | Modelo liviano (rápido en CPU) |
| `Rec.ocr_version` | `PP-OCRv5` | Versión del reconocedor |
| `Rec.model_type` | `MOBILE` | Modelo liviano |
| `Rec.lang_type` | `LATIN` | Alfabeto latino: conserva tildes, ñ y espacios |
| `Global.text_score` | `0.3` | Confianza mínima para conservar un texto (no descarta manuscritos tenues) |
| `Global.log_level` | `warning` | Menos mensajes en la consola |

Archivos de modelo usados (en `...\Python311\Lib\site-packages\rapidocr\models\`):
- `ch_PP-OCRv5_det_mobile.onnx`
- `ch_ppocr_mobile_v2.0_cls_mobile.onnx`
- `latin_PP-OCRv5_rec_mobile.onnx`

> Se comparó con el modelo chino por defecto. Ese modelo perdía espacios y tildes ("BANCOBOLIVARIANO", "Gomez", "0o/100"), mientras que el latino los leyó bien con confianza de 0.97 a 1.00. Por eso se eligió el latino.

### 10.5 Variables de configuración

Guardadas en `backend/.env.probado`:

```
CHEQUES_INPUT_DIR=../cheques_entrada
APP_HOST=127.0.0.1
APP_PORT=8000
POLL_SECONDS=2
MAX_IMAGE_WIDTH=2000
MIN_IMAGE_WIDTH=1400
LOW_CONFIDENCE=0.80
HANDWRITING_ENABLED=false
OLLAMA_MODEL=
VLM_MODE=fallback
CORS_ORIGINS=*
```

TrOCR y Ollama estaban **desactivados**. Todo el resultado se obtuvo solo con el OCR más las reglas programáticas.

### 10.6 Cómo colocar esta configuración, paso a paso

1. Abra PowerShell en la carpeta del backend:
   ```powershell
   cd C:\Users\Usuario\Desktop\j\backend
   ```
2. (Opcional, recomendado en otra PC) Cree y active un entorno virtual:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```
3. Instale **exactamente** las versiones probadas:
   ```powershell
   pip install -r requirements-probado.txt
   ```
4. Copie la configuración probada como `.env`:
   ```powershell
   copy .env.probado .env
   ```
5. Verifique que `ocr_engine.py` tenga los parámetros de la sección 10.4. Ya vienen así en el proyecto; solo revíselo si lo modificó.
6. (Opcional) Si quiere repetir la prueba desde cero, borre los resultados anteriores:
   ```powershell
   Remove-Item -Recurse -Force data
   ```
7. Arranque el servidor:
   ```powershell
   python run.py
   ```
   La primera vez descarga los 3 modelos de OCR (unos 14 MB). En la consola debe aparecer:
   `Motor OCR cargado (RapidOCR PP-OCRv5 latino)`
8. Abra **http://127.0.0.1:8000**. Los cheques que estén en `cheques_entrada\` se analizarán en unos 2 s cada uno.
9. Para generar los mismos tipos de cheques de prueba:
   ```powershell
   python tools\generar_cheques_ejemplo.py
   ```

> **Importante:** si tiene instalado `opencv-python-headless` junto con `opencv-python` y aparecen errores de OpenCV, deje solo uno:
> `pip uninstall -y opencv-python-headless`

---

## 11. Problemas frecuentes

| Síntoma | Solución |
|---|---|
| `email-validator version >= 2.0 required` | `pip install -U "email-validator>=2.0"` |
| `Error loading fbgemm.dll` | Instale el Visual C++ Redistributable (solo afecta a TrOCR, que es opcional). |
| La web dice "Sin conexión con el backend" | El servidor no está corriendo: ejecute `python run.py`. |
| `address already in use` | El puerto 8000 está ocupado: cambie `APP_PORT` en `.env`. |
| Un cheque no aparece | Revise que la extensión sea válida y que no sea un duplicado. Pulse **Escanear carpeta** y mire la consola. |
| Muchos cheques en REVISAR | Abra el detalle y lea las observaciones. Si sus cheques usan otras etiquetas, agréguelas en `field_extractor.py`. |
