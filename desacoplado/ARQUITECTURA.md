# Arquitectura de la PoC de lectura de cheques

Resumen de qué se usa y cómo interactúan las piezas al analizar el anverso de un cheque.
Todo corre en **un solo proceso local**, en CPU o en GPU NVIDIA con la misma instalación: no usa nube ni servicios externos.

## Estructura

El proceso sigue siendo uno solo, en este equipo. El código queda partido para que el OCR,
el modelo de letra y el Excel se puedan cambiar sin reescribir el análisis.

```
front/static/index.html     página (la sirve la API; no hay un segundo servidor)
back/api/                   FastAPI: subir un cheque, lotes, devolver el Excel
back/motor/                 orquesta un cheque o una carpeta (no sabe qué OCR ni qué modelo)
back/dominio/               reglas, MICR, CTC, comparación con verdad.csv
back/ocr/                   contrato + fábrica; hoy el motor es rapidocr/ (PP-OCR)
back/ocr/preproceso.py      versiones de cada zona (limpia, gris, escala); vale para cualquier OCR
back/modelo/                contrato + fábrica; hoy el modelo es glm_ocr.py
back/informe/excel.py       los dos Excel (lote y evaluación)
externos/firmas/            detector de firmas, igual que antes
modelos/  plantillas/       pesos y la referencia MICR (no se movieron)
```

`servidor.py`, `analizar.py`, `evaluar.py` y `descargar_modelos.py` siguen en la raíz:
son los mismos comandos de siempre y delegan en `back/`.

## Cambiar el OCR o el modelo

El analizador no importa RapidOCR ni GLM. Pide las piezas a una fábrica.

**Otro OCR ya registrado:** en `config.json` cambia `"motor_ocr"`.
**Otro modelo ya registrado:** cambia `"modelo_profundo"`. `"lectura_profunda": false` lo apaga.
**Un OCR nuevo:** implementa `back/ocr/contrato.py`, agrega una línea en `MOTORES`
de `back/ocr/fabrica.py` y pon esa clave en `"motor_ocr"`.
**Un modelo nuevo:** implementa `back/modelo/contrato.py` (`estimar_segundos` y `leer`),
agrega una línea en `MODELOS` de `back/modelo/fabrica.py` y pon esa clave en `"modelo_profundo"`.

Las reglas siguen leyendo la variante `"glm-ocr"`: es el nombre estable del resultado,
no el nombre del modelo. Un modelo nuevo no tiene que tocar `back/dominio/`.
El Excel no sabe de imágenes: si cambia el informe, el cambio queda en `back/informe/excel.py`.

## Qué se usa

| Pieza | Tecnología | Para qué | Tiempo aprox.* |
|---|---|---|---|
| Interfaz | `front/static/index.html` | Subir un cheque o una carpeta, ver resultados, Excel | — |
| API | FastAPI (`back/api/servidor.py`, arranque `servidor.py`) | Misma API local en el puerto 8300 | — |
| Orquestador | `back/motor/analizador.py` | Ejecuta los pasos, controla el presupuesto de tiempo, arma el JSON | — |
| Localizador de campos | **PP-OCRv6** vía `back/ocr/rapidocr/` | Encuentra cajas, etiquetas y la zona de cada campo | ~4,5–9 s |
| Clasificador por contenido | `back/dominio/clasificador.py` | Reubica campos según lo que dicen | <0,1 s |
| Detector de firmas | **YOLOS-tiny** — `externos/firmas/` | Borra la firma de los recortes; si tapa 2+ campos, marca ilegible | ~1,5 s |
| Lectura profunda | **GLM-OCR** vía `back/modelo/glm_ocr.py` | Lee la letra manuscrita. `"dudosos"` solo revisa lo que el camino rápido dejó pendiente | ~35 s |
| Lector rápido | **PP-OCRv6 small** — `back/ocr/rapidocr/lector.py` | Tres versiones de cada zona y la matriz de probabilidades | ~0,5 s por zona |
| Lector secundario | **PP-OCRv5 latin** | Otra opinión en zonas manuscritas | ~0,2 s por zona |
| Lector MICR | `back/dominio/micr.py` | Banda MICR carácter por carácter | milisegundos |
| Verificador CTC | `back/dominio/ctc.py` | Puntúa cada candidato contra la imagen | ~1 s en total |
| Reglas por campo | `back/dominio/` (`campos`, `parsers`, `reglas`, `nombres`) | Candidatos, cruce cifras/letras, fechas, ciudades, nombres | <0,5 s |
| Lotes y Excel | `back/motor/lotes.py` + `back/informe/excel.py` | Carpeta en segundo plano, acierto vs `verdad.csv`, Excel en `resultados/` | — |

\* Medido el 2026-10-08 con `muestras/pichincha_0001.tif` en una PC de 3 núcleos. Total: ~50 s por cheque. Sin GLM: ~10 s.

**Idea central:** ningún OCR se acepta "porque sí".
1. GLM, PP-OCR y el segundo lector solo **proponen** candidatos.
2. El verificador CTC mide qué tan bien encaja cada candidato con los trazos.
3. Las reglas cruzan fuentes: cifras con letras, MICR con lo impreso.
4. Un campo solo sale automático si gana con margen. Si no, queda en `revisar`.

## Diagrama de secuencia (un cheque)

```mermaid
sequenceDiagram
    autonumber
    actor U as Usuario
    participant S as servidor.py (FastAPI)
    participant A as Analizador
    participant L as Localizador<br/>(PP-OCRv6 det+rec)
    participant F as Detector firmas<br/>(YOLOS)
    participant G as GLM-OCR<br/>(VLM)
    participant R as Lector rápido<br/>(PP-OCRv6 + v5 latin)
    participant M as Lector MICR<br/>(plantillas E-13B)
    participant C as Reglas + CTC<br/>(campos.py / ctc.py)

    U->>S: POST /api/analizar (imagen + selección)
    S->>A: analizar(imagen)
    A->>A: leer gris y llevar a 592 px de ancho

    A->>L: localizar(imagen)
    L->>L: detectar cajas de texto + leerlas
    L->>L: etiquetas impresas y clasificación por contenido
    L-->>A: zonas de cada campo + cajas impresas
    A->>A: copia "manuscrito" (borra texto impreso)

    A->>F: detectar(imagen)
    F-->>A: cajas de firma
    A->>A: borra firmas de los recortes / marca ilegibles

    opt micr_cheque_cuenta_banco
        A->>R: leer cheque_impreso y cuenta_impresa (1 pasada: texto + matriz)
        A->>M: leer(zona MICR)
        M-->>A: caracteres E-13B (o "?" si duda)
        A->>C: datos_impresos(MICR, impresos, matrices)
        alt MICR con caracteres dudosos
            A->>R: leer MICR con OCR general
            C-->>A: campos marcados "revisar"
        end
        C-->>A: n.º cheque, cuenta, banco
    end

    opt montos
        A->>R: leer monto_letras (+ 2.º renglón) y monto_numeros
        R-->>A: lecturas (3 versiones + v5 latin) + matrices
        A->>C: montos(lecturas + texto GLM)
        C->>C: candidatos (cifras, letras, variantes de 1 dígito)
        C->>C: puntaje CTC de cada candidato en AMBAS zonas
        C-->>A: monto + "revisar" si no hay cruce claro
    end

    opt ciudad_fecha
        A->>R: leer ciudad_fecha
        A->>C: ciudad_fecha(lecturas + GLM)
        C-->>A: ciudad (lista Ecuador) + fecha verificada
    end

    opt beneficiario
        A->>R: leer beneficiario
        A->>C: beneficiario(GLM como base + lecturas)
        C-->>A: nombre (diccionario de nombres/apellidos + CTC)
    end

    opt lectura_profunda (modo "dudosos"), alcanza el tiempo y letra legible
        A->>A: ¿qué campos quedaron en "revisar"?
        A->>G: leer solo esas zonas (beneficiario / monto_letras / ciudad_fecha) apiladas
        G-->>A: un renglón de texto por zona
        A->>C: volver a decidir esos campos con GLM + lecturas ya hechas (sin releer)
        C-->>A: campos actualizados
    end

    A->>A: control de presupuesto, ilegibles, resolución
    A-->>S: JSON (campos, detalle, revisar, tiempos)
    S-->>U: resultado + imagen con zonas
```

## Notas

- **Arranque:** al levantar se cargan todos los modelos y se analiza el cheque de referencia
  (`plantillas/`) como calentamiento. Por eso tarda 1,5–3,5 min.
- **Presupuesto de tiempo:** `config.json` → `presupuesto_segundos_por_lado`. Si un paso no
  alcanza, sus campos quedan "omitido / revisar" en lugar de pasarse del límite.
- **Selección:** `config.json` → `anverso` activa o desactiva cada grupo de campos.
  `lectura_profunda` activa GLM.
- **Lotes:** `POST /api/lotes` procesa una carpeta con el mismo motor que el análisis individual y genera
  el Excel (en el orden de la carpeta). Con 1, de a un cheque (candado); con N, N a la vez sobre los mismos modelos.
- **Ejecución** (`back/motor/hardware.py`, `arranque.py`, `paralelo.py`): al levantar se detecta CPU, RAM y
  GPU, se pregunta CPU/GPU y cuántos cheques a la vez. Se crea UN `Analizador` (modelos cargados una vez) y
  `Motor` deja que hasta N hilos lo usen al mismo tiempo (semáforo; con N = 1 es el candado de siempre).
  Todo lo de cada cheque es local a la llamada y `ultima_imagen` es por hilo. Con N > 1, torch reparte los
  núcleos (`set_num_threads(núcleos / N)`); ONNX y OpenCV comparten su grupo de hilos como siempre.

## Pendientes de optimización

- **GLM en segundo plano** (devolver primero el resultado rápido). Hecho: GLM solo para campos dudosos (`lectura_profunda_modo`).
- **GLM en int8** (`quantize_dynamic` u OpenVINO): las capas lineales son ~60 % de su tiempo.
- **Calentamiento corto al arrancar:** una imagen chica para GLM en lugar del análisis completo.
- **Descartados:**
  - Detector "tiny" o entrada más chica en el localizador: mueve las zonas.
  - Tiras de GLM de alto 40 o 32, o relleno ajustado al ancho: empeora la lectura manuscrita.
