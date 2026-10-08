# Guía técnica del analizador de cheques

Este archivo explica **qué hace cada pieza del proyecto**, **dónde están los puntos críticos** y **cómo correrlo según el caso**.

---

## 1. Cómo está organizado

```
j2/
├── iniciar.bat                 Arranque en un clic (Windows)
├── requirements.txt            Librerías Python
├── README.md                   Uso general
├── docs/GUIA_TECNICA.md        Este archivo
├── cheques/                    Entrada: ponga aquí las imágenes/PDF
├── datos/                      Salida: resultados.json y vistas previas
├── frontend/                   HTML, CSS y JS (sin frameworks)
├── backend/                    Servidor y OCR
└── herramientas/               Scripts de prueba
```

No hay base de datos. Los resultados viven en `datos/resultados.json`.

---

## 2. Cada archivo y sus puntos críticos

### `iniciar.bat`

Crea el entorno virtual si no existe, instala dependencias y lanza `backend/app.py`.

- **Crítico:** usa `python` del PATH. Si hay varias versiones, deje 3.11+ como la que responde a `python --version`.
- **Crítico:** abre el navegador al instante; el servidor tarda unos segundos en cargar el modelo OCR. Si la página dice “sin conexión”, recargue.

### `requirements.txt`

Lista mínima: Flask, RapidOCR (ONNX), OpenCV, NumPy, openpyxl, pypdfium2.

- **Crítico:** RapidOCR baja los `.onnx` **dentro del pip**. No se llama a internet en tiempo de ejecución.
- **Crítico:** no mezclar `opencv-python` y `opencv-python-headless` a mano; el pip ya resuelve las dos.

### `backend/config.py`

Rutas, puerto, intervalo de vigilancia y umbrales de OCR.

| Variable | Para qué | Si la toca |
|---|---|---|
| `CARPETA_CHEQUES` | De dónde se leen archivos | Cambie si quiere otra carpeta de entrada |
| `INTERVALO_REVISION_SEG` | Cada cuánto se mira la carpeta | Baje a 2 si espera lotes muy seguidos |
| `ANCHO_OCR` | Ancho de trabajo (velocidad) | 1200 más rápido / menos preciso |
| `ANCHO_OCR_DIFICIL` | Ancho cuando la foto es mala | 2000 más preciso / más lento |
| `CONFIANZA_MINIMA` | Descarta texto dudoso | Baje si pierde letra a mano |
| `CONFIANZA_MINIMA_DIFICIL` | Igual, en fotos malas | Muy bajo = más ruido |
| `HOST` / `PUERTO` | Dirección del servidor | `0.0.0.0` si otro PC de la red debe entrar |

### `backend/ocr_motor.py` — el corazón del OCR

Carga imagen/PDF, mide calidad, endereza, refuerza si hace falta y llama a RapidOCR.

Puntos críticos:

1. **Calidad de imagen.** Mide nitidez (Laplaciano), brillo y contraste. Marca: borrosa, oscura, sobreexpuesta, bajo contraste, resolución baja.
2. **Refuerzo solo cuando hace falta.** Imagen nítida = un paso (contraste CLAHE) para ir rápido. Imagen mala o lectura pobre = nitidez, denoising, umbral adaptativo, trazo más grueso, gamma.
3. **Giros.** Si el alto es mayor que el ancho, prueba 90° a ambos lados y se queda con el mejor puntaje.
4. **Inclinación.** Endereza hasta ~12°. No toca giros fuertes (eso lo cubre el punto 3).
5. **Candado (`_candado`).** El motor ONNX no es seguro entre hilos. No quite el lock.
6. **`use_cls=False`.** El clasificador de orientación duplica el tiempo. Los cheques se orientan por geometría, no por ese clasificador.
7. **PDF.** Solo la primera página, a 300 dpi.

### `backend/numeros_letras.py`

Pasa “MIL QUINIENTOS VEINTE CON 50/100” a `1520.50`. Corrige palabras pegadas y errores típicos de OCR manuscrito.

Puntos críticos:

1. El vocabulario es **español de montos**. Si el cheque usa otra moneda en letras, agregue la palabra a `IGNORADAS`.
2. `corregir_palabra` usa programación dinámica: parte “quinientosveinte” y corrige “treycientos”. Si baja demasiado el `cutoff` de `difflib`, puede inventar números.
3. La fracción `xx/100` acepta `5o/1oo`. Si el OCR pone otra basura, amplíe `RE_FRACCION`.
4. Sustituciones `rn→m`, `+→t` ayudan a letra a mano, pero no se deben aplicar a nombres propios (solo se usan en el monto en letras).

### `backend/extractor.py`

Convierte las cajas del OCR en campos del cheque **con reglas**, no con otro modelo.

Puntos críticos:

1. Las **etiquetas impresas** (`PÁGUESE A LA ORDEN DE`, `LA SUMA DE`) pueden salir pegadas (`PAGUESEALAORDENDE`). Los regex ya contemplan huecos y esa forma compacta.
2. El **monto en números** se busca a la derecha y se compara con el de letras. Si coinciden → `COINCIDE`. Esa es la validación más fiable.
3. **Fecha:** corrige letras leídas como dígitos (`28/0a/2026` → `28/09/2026`).
4. **Banco y ciudad:** listas fijas. Agregue sucursales locales en `BANCOS_CONOCIDOS` y `CIUDADES`.
5. **Beneficiario:** es el campo más frágil con letra ilegible. No hay diccionario de nombres; se muestra lo leído y se marca revisión si la confianza es baja.
6. `requiere_revision` se enciende si faltan campos clave, los montos no cuadran, la confianza es baja o la imagen salió mala.

### `backend/procesador.py`

Vigila `cheques/`, procesa solo archivos nuevos y guarda JSON.

Puntos críticos:

1. La identidad del archivo es el **SHA-1 del contenido**. Renombrar no relanza el OCR. Editar el archivo sí.
2. Espera 2 segundos tras la última modificación para no leer un archivo a medio copiar.
3. Guarda el JSON **después de cada cheque**, así la web se actualiza en el lote.
4. `reiniciar()` borra JSON y vistas, no borra los originales de `cheques/`.
5. Un archivo dañado no detiene el lote: queda en estado `ERROR`.

### `backend/exportar_excel.py`

Arma el `.xlsx` en memoria (no deja basura en disco). Hoja “Cheques” + hoja “Texto OCR”.

- **Crítico:** el monto va como número (no texto) para poder sumar en Excel.
- Incluye columnas de revisión, avisos y calidad de imagen.

### `backend/app.py`

Flask: sirve el front y la API `/api/v1/...`.

| Método | Ruta | Qué hace |
|---|---|---|
| GET | `/` | Interfaz |
| GET | `/api/v1/cheques` | Resultados + estado |
| GET | `/api/v1/cheques/excel` | Descarga Excel |
| POST | `/api/v1/cheques/archivos` | Sube archivos a `cheques/` |
| POST | `/api/v1/procesamientos` | Revisa la carpeta ya |
| DELETE | `/api/v1/cheques` | Borra resultados y reanaliza |
| GET | `/api/v1/vistas/<archivo>` | Miniatura del cheque |

- **Crítico:** `threaded=True` y el OCR con candado. No lance dos procesos Flask sobre la misma carpeta `datos/`.
- **Crítico:** `debug=False` a propósito: el reloader duplicaría el hilo vigilante.

### `frontend/index.html` / `styles.css` / `app.js`

Página única. El JS consulta la API cada 3 segundos y pinta filas nuevas.

Puntos críticos:

1. No hay login. Está pensado para uso local.
2. El filtro es en el navegador (no recarga el servidor).
3. “Requieren revisión” cuenta cheques con avisos o error. Ya no se muestra un monto total agregado (no aporta y mezcla cheques distintos).
4. Si cambia un endpoint, actualice `API` en `app.js`.

### `herramientas/generar_cheques_prueba.py`

Dibuja cheques de ejemplo (Arial + fuente manuscrita de Windows). Sirve para probar el flujo sin escaneos reales.

- **Crítico:** necesita `C:\Windows\Fonts\Inkfree.ttf` o `segoesc.ttf`. Si no están, usa la fuente por defecto y el OCR de “mano” será peor.

### `herramientas/probar_ocr.py`

Prueba un archivo por consola, sin levantar Flask. Ideal para ajustar umbrales.

### `cheques/` y `datos/`

- `cheques/`: **solo entrada**. No se modifica.
- `datos/resultados.json`: estado persistente. Bórrelo (o use “Reanalizar todo”) si cambió el código de extracción y quiere volver a leer los mismos archivos.
- `datos/vistas/`: JPEG de lo que realmente se mandó al OCR (ya orientado y recortado de tamaño).

---

## 3. Cómo correr el proyecto, paso a paso

### Caso A — Primera vez en esta PC (Windows)

1. Instale Python 3.11+ y marque “Add python.exe to PATH”.
2. Abra una consola en la carpeta `j2`.
3. Ejecute `iniciar.bat` (o los comandos del README).
4. Espere a ver en consola: `Abra http://127.0.0.1:5000`.
5. Copie un cheque a `cheques/` o use “Subir cheques”.
6. En 5 segundos o menos debe aparecer la fila. Clic en la fila para ver detalle y avisos.

### Caso B — Ya está instalado, solo quiere usarlo

Doble clic en `iniciar.bat`. No vuelve a instalar librerías si `.venv` existe.

### Caso C — El entorno está roto o cambió `requirements.txt`

```bat
rmdir /s /q .venv
iniciar.bat
```

O a mano:

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python backend\app.py
```

### Caso D — Linux / macOS

```bash
cd "ruta/al/j2"
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python backend/app.py
```

Luego abra `http://127.0.0.1:5000`.

### Caso E — Probar un solo archivo sin abrir el navegador

```bat
.venv\Scripts\python herramientas\probar_ocr.py cheques\mi_cheque.jpg
```

Sirve para ver texto OCR crudo, calidad de imagen y avisos.

### Caso F — Generar cheques de prueba

```bat
.venv\Scripts\python herramientas\generar_cheques_prueba.py
```

Crea `cheques/cheque_prueba_1.jpg` … `_3.jpg`. Si el servidor está arriba, los toma solo si no los había leído antes.

### Caso G — Cambió el código de extracción y quiere rehacer todo

En la web: **Reanalizar todo**.  
O borre `datos/resultados.json` y `datos/vistas/` y reinicie el servidor.

Los originales en `cheques/` no se tocan.

### Caso H — Fotos de celular borrosas o letra casi ilegible

No hay que cambiar de motor. El OCR ya entra en modo difícil si detecta borrosidad, poca luz o poco contraste.

Si aún pierde campos:

1. Suba `ANCHO_OCR_DIFICIL` a `2000` en `config.py`.
2. Baje `CONFIANZA_MINIMA_DIFICIL` a `0.12`.
3. Reinicie el servidor y pulse **Reanalizar todo**.
4. Revise en el detalle la lista de avisos: ahí dice si el problema fue la imagen o el cruce de montos.

La letra a mano de **nombres** nunca va a ser perfecta con OCR puro. El monto sí se puede cruzar (números vs letras); si no coinciden, el cheque queda en “Revisar”.

### Caso I — El puerto 5000 está ocupado

Cierre la consola del servidor anterior, o en `config.py`:

```python
PUERTO = 5001
```

y abra `http://127.0.0.1:5001`. En `iniciar.bat` el `start http://...` sigue apuntando a 5000: cámbielo también si usa otro puerto.

### Caso J — Quieren acceder desde otra máquina de la red local

En `config.py`:

```python
HOST = "0.0.0.0"
```

Reinicie. En el otro PC abra `http://IP-DE-ESTE-EQUIPO:5000`. Sigue siendo un uso interno, sin autenticación.

### Caso K — Lote grande (cientos de cheques)

1. Copie todos a `cheques/` **antes** de arrancar, o deje el servidor corriendo y copie por tandas.
2. No abra dos instancias de `app.py` sobre la misma carpeta.
3. Cada cheque nítido tarda ~2–4 s; uno borroso puede ir a 6–10 s porque prueba más variantes.
4. El Excel se puede bajar en cualquier momento; incluye lo ya procesado.

### Caso L — Un PDF de varias páginas

Hoy solo se lee la **primera página**. Si cada cheque es una página, exporte el PDF a imágenes (una por página) y póngalas en `cheques/`.

---

## 4. Flujo interno (resumen)

```
archivo en cheques/
    → huella SHA-1 (¿ya visto? si sí, se ignora)
    → cargar imagen / 1ª página PDF
    → evaluar nitidez, brillo, contraste
    → orientar y enderezar
    → OCR (contraste; si falla, variantes de refuerzo)
    → reglas de extractor.py
    → cruzar monto números vs letras
    → guardar JSON + miniatura
    → el front lo pinta en la tabla
```

---

## 5. Límites reales del OCR puro

- Firmas no se validan.
- Nombres manuscritos ilegibles no se “adivinan”.
- Tildes y ñ suelen salir mal con el modelo incluido.
- Cheques muy recortados, con flash, o de 200 px de ancho van a pedir revisión.
- No hay llamada a GPT ni a APIs de visión: si el trazo no se lee, el sistema marca aviso en lugar de inventar.
