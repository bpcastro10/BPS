# PoC lectura de cheques (local, sin servicios en la nube)

## Instalar y levantar en otra PC (un solo paso)

1. Clonar: `git clone https://github.com/DarioRodriguez47/chek.git` (o descargar el ZIP).
2. Doble clic en **`instalar_y_levantar.bat`**. La primera vez:
   - instala Python 3.11 con winget si falta;
   - crea `.venv` e instala las librerías (`requirements.txt`: torch con CUDA, que también corre en CPU, y `onnxruntime-gpu`);
   - descarga GLM-OCR (2,5 GB) en `modelos/GLM-OCR` y los modelos de PaddleOCR (usa internet);
   - levanta la interfaz en http://127.0.0.1:8300 y abre el navegador.
3. Las siguientes veces el mismo `.bat` solo levanta (o `iniciar.bat`).

Requisitos: Windows 10/11, Python 3.11+, ~16 GB de RAM (el proceso usa ~5 GB), ~10 GB de disco (la rueda CUDA de torch es grande). Más núcleos de CPU =
más rápido (GLM-OCR es el 80 % del tiempo). La misma instalación corre en CPU y, si hay GPU NVIDIA, en CUDA.

## CPU / GPU y análisis en paralelo (al levantar)

Al iniciar (`iniciar.bat` o `instalar_y_levantar.bat`) la consola muestra el equipo detectado y pregunta:

1. **CPU o GPU** (solo si hay una GPU NVIDIA utilizable). GLM-OCR y el detector de firmas
   van a la GPU; PaddleOCR también si `onnxruntime-gpu` ve CUDA (si no, sigue en CPU). Sin GPU, todo queda en CPU.
2. **Qué GPU** (solo si hay más de una; por omisión la de más memoria libre).
3. **Cuántos procesos a la vez**, un número **entre el mínimo y el máximo** que aguanta el equipo
   (el máximo es el menor entre RAM libre, núcleos y VRAM). Si no se escribe nada, queda el **recomendado**.

**Los modelos se cargan UNA sola vez.** Los análisis simultáneos son hilos del mismo proceso que usan esos
mismos modelos (ONNX y torch admiten llamadas a la vez y sueltan el GIL al calcular). No se duplica RAM
ni VRAM: cada análisis extra solo suma su memoria de trabajo (~0,8 GB RAM / ~0,6 GB VRAM).
En CPU, varios a la vez no aceleran UN cheque (reparten los núcleos): sirven para **lotes**.
En GPU, uno solo ya baja mucho el tiempo; con varios, mientras uno usa la GPU los otros hacen la parte de CPU.
El límite de tiempo por cheque se mantiene: si por la carga un paso no alcanza, ese campo queda en "revisar".

Sin preguntas: `servidor.py --dispositivo gpu --paralelos 3 [--gpu 0]`, o `--sin-preguntar` para usar
`config.json` → `ejecucion` (`dispositivo`, `paralelos`, `gpu`, `precision_gpu`: `float32` por omisión,
`float16` usa la mitad de VRAM pero puede cambiar algo la lectura). Diagnóstico solo:
`.venv\Scripts\python -m back.motor.hardware`. `analizar.py` y `evaluar.py` aceptan `--dispositivo cuda:0`.

CPU y GPU NVIDIA usan los mismos paquetes (`torch` CUDA 12.6 y `onnxruntime-gpu` en `requirements.txt`).
Esa rueda usa la GPU si el driver admite CUDA 12.6 o superior (también un driver 13).
Si no hay GPU, esa rueda de torch corre en CPU. No instales además el paquete `onnxruntime` (solo CPU): sustituye al de GPU.

Todo corre en UN proceso: detector de firmas (código y modelo copiados de PR1/ServicioFirmas en
`externos/` y `modelos/`), búsqueda de campos, PaddleOCR, GLM-OCR y la interfaz.

## Estado al 2026-10-07

- Campos buscados por CONTENIDO (no por posición): sirve para cualquier diseño de cheque.
- Beneficiario y ciudad: texto de GLM-OCR tal cual. Fecha: de GLM, confirmada con el lector rápido.
- Monto: cruce cifras/letras; nunca automático si faltan centavos o no hay cruce.
- Detector de firmas: tapa la firma en los recortes y marca "letra ilegible" (se salta GLM: ~8 s).
- Tiempo en la VM de 3 núcleos: 25–35 s por cheque (8 s si es ilegible). `config.json` -> límite 60 s.
- Pendiente: medir acierto con cheques reales y verdad.csv; plantilla MICR del dígito 7; detector de
  campos entrenado (mismo YOLOS del servicio de firmas) para bajar la búsqueda de ~3 s a ~0,7 s.

## Detalle técnico (versión inicial)

Lee el anverso de un cheque Banco Pichincha escaneado (TIF gris, 100 dpi) y valida cada campo
cruzando fuentes. Todo corre en la CPU local; no se usa internet ni ningún LLM.

## Interfaz de prueba

Doble clic en `iniciar.bat` → http://127.0.0.1:8300 (solo este equipo).

- **Un cheque:** arrastrar la imagen, elegir qué analizar y ver campos, tiempos y zonas.
- **Carpeta:** pegar la ruta de una carpeta (opcional: subcarpetas). Avance en vivo, filtros, detalle
  por cheque y Excel al terminar (también queda en `resultados/lote_*.xlsx`). Si la carpeta trae
  `verdad.csv`, muestra el acierto por campo y los errores aceptados automáticamente.

## Uso por línea de comandos

```bat
.venv\Scripts\python analizar.py muestras\pichincha_0001.tif            :: JSON de un cheque
.venv\Scripts\python analizar.py muestras\pichincha_0001.tif --beneficiario
.venv\Scripts\python evaluar.py                                          :: acierto vs muestras\verdad.csv + Excel en resultados\
.venv\Scripts\python evaluar.py muestras_variaciones
.venv\Scripts\python generar_variaciones.py muestras\pichincha_0001.tif muestras_variaciones
```

Para medir con cheques nuevos: copiarlos a una carpeta con un `verdad.csv` (mismas columnas que
`muestras\verdad.csv`) y ejecutar `evaluar.py <carpeta>`.

## Lista de selección (`config.json`)

```json
"anverso": {"micr_cheque_cuenta_banco": true, "montos": true, "ciudad_fecha": true, "beneficiario": false}
```

`presupuesto_segundos_por_lado` (8) es un límite duro: si un paso no alcanza, sus campos quedan
"revisar (sin tiempo)" en lugar de pasarse. La firma no se analiza (servicio aparte).

## Cómo decide cada campo

| Campo | Fuente principal | Validación cruzada |
|---|---|---|
| N.º cheque, cuenta, MICR | Lector E-13B por plantillas (`back/dominio/micr.py`) | Cuenta y n.º impresos arriba. Si el lector duda, OCR general y siempre "revisar" |
| Banco | Plantilla | Código `10` al inicio de la ruta MICR |
| Monto | Candidatos puntuados sobre la imagen (`back/dominio/ctc.py`) | Debe encajar en la zona de cifras y en la de letras. Si ninguna zona lo leyó sola, nunca es automático |
| Fecha | Lecturas + variantes de 1 dígito verificadas en la imagen | Fecha válida, plausible, aviso de posdatado |
| Ciudad | Lista de ciudades de Ecuador | Verificada en la imagen |
| Beneficiario | Lectura directa (pendiente) | — |

Regla general: un campo solo es automático si la verificación tiene ventaja clara sobre la segunda
opción; si no, `revisar: true`. Imágenes con menos resolución que la referencia → todo "revisar".

## Archivos

```
front/static/index.html          página de prueba
back/api/servidor.py             API local
back/motor/                      análisis de un cheque y de una carpeta
back/dominio/                    reglas, MICR, CTC, fechas y nombres
back/ocr/                        contrato del OCR; el motor actual está en rapidocr/
back/modelo/glm_ocr.py           modelo de letra manuscrita (GLM-OCR)
back/informe/excel.py            Excel de lote y de evaluación
config.json                      motor_ocr, modelo_profundo y el resto de la selección
```

Para cambiar el OCR o el modelo sin reescribir el análisis, ver `ARQUITECTURA.md`
(secciones «Estructura» y «Cambiar el OCR o el modelo»).

## Limitaciones conocidas (al 2026-10-07)

- Una sola muestra real del escáner: las plantillas MICR salen de ese mismo cheque y las
  variaciones derivan de él → los números son optimistas. Falta la plantilla del dígito **7**.
- Umbrales (`MARGEN_*`, `PENALIZACION`) calibrados con muy pocos casos.
- Beneficiario sin validar.
